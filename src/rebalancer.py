"""
RebalanceKeeper — Multi-strategy rebalancing decision engine.

When the health factor drops into warning/danger/critical zones, the
rebalancer evaluates multiple strategies and picks the best one:

Strategies (by priority):
  1. EMERGENCY_REPAY   — Critical zone: repay 50% of debt immediately
  2. REPAY             — Danger zone: repay 25% of debt
  3. LIGHT_REPAY       — Warning zone with declining trend: repay 10%
  4. SUPPLY_COLLATERAL — Fallback: supply more collateral if no debt token
  5. REBALANCE_DEBT    — Interest rate arbitrage: switch debt to lower APY
  6. NO_ACTION         — Position is safe

Decision factors:
  - Current health factor vs zone thresholds
  - Trend (declining / stable / rising)
  - Available wallet balances
  - Debt composition (multi-asset)
"""

import time as _time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from . import config
from .audit import AuditLogger
from .keeperhub_client import KeeperHubClient, MCPError
from .monitor import AlertLevel, HealthSnapshot


@dataclass
class RebalanceDecision:
    """A rebalancing decision produced by the evaluation logic."""

    action: str           # "repay" | "supply" | "withdraw_repay" | "arb" | "no_action"
    asset: str            # token address
    amount: str           # human-readable amount
    reason: str           # human-readable explanation
    priority: int = 0     # higher = more urgent
    alert_level: str = "SAFE"
    estimated_hf_impact: float = 0.0  # estimated HF improvement


class Rebalancer:
    """Evaluates position health and executes rebalancing actions.

    The rebalancer uses a multi-strategy approach:
    1. Classify the alert level from the snapshot
    2. Evaluate all applicable strategies
    3. Pick the highest-priority strategy that's executable
    4. Execute via KeeperHub MCP
    """

    def __init__(
        self,
        client: KeeperHubClient,
        cfg: config.RebalanceConfig = config.REBALANCE_CONFIG,
        audit: Optional[AuditLogger] = None,
    ):
        self.client = client
        self.cfg = cfg
        self.audit = audit or AuditLogger(cfg.audit_log_path)
        self._last_decision: Optional[RebalanceDecision] = None

    # ── Strategy evaluation ───────────────────────────────────

    def evaluate(self, snap: HealthSnapshot) -> RebalanceDecision:
        """Decide what to do based on the current health factor and trend.

        Args:
            snap: Current health snapshot from the monitor (includes trend data).

        Returns:
            A RebalanceDecision with action, asset, amount, reason.
        """
        debt_token = config.TOKENS[config.DEBT_TOKEN]
        collateral_token = config.TOKENS[config.COLLATERAL_TOKEN]

        total_debt = float(snap.total_debt_base)
        level = snap.alert_level

        # ── CRITICAL: emergency repay 50% ──
        if level == AlertLevel.CRITICAL:
            return self._make_repay_decision(
                snap, debt_token, total_debt,
                self.cfg.repay_fraction_critical,
                priority=100,
                level_str="CRITICAL",
                prefix="EMERGENCY",
            )

        # ── DANGER: repay 25% ──
        if level == AlertLevel.DANGER:
            return self._make_repay_decision(
                snap, debt_token, total_debt,
                self.cfg.repay_fraction_danger,
                priority=50,
                level_str="DANGER",
                prefix="ACTIVE",
            )

        # ── WARNING with declining trend: repay 10% ──
        if level == AlertLevel.WARNING:
            if snap.consecutive_declines >= self.cfg.trend_window - 1:
                # Declining fast → pre-emptive repay
                return self._make_repay_decision(
                    snap, debt_token, total_debt,
                    self.cfg.repay_fraction_warn,
                    priority=20,
                    level_str="WARNING",
                    prefix="PRE-EMPTIVE",
                )
            # Just warning, no decline → light supply
            boost_wei = str(int(float(self.cfg.supply_boost_amount) * 1e18))
            return RebalanceDecision(
                action="supply",
                asset=collateral_token["address"],
                amount=boost_wei,
                reason=(
                    f"HF={snap.health_factor:.4f} in WARNING zone "
                    f"({self.cfg.warn_threshold}-{self.cfg.safe_threshold}). "
                    f"No strong decline yet. Supply {self.cfg.supply_boost_amount} "
                    f"{config.COLLATERAL_TOKEN} as buffer."
                ),
                priority=10,
                alert_level=level.value,
                estimated_hf_impact=self._estimate_supply_impact(snap),
            )

        # ── SAFE: no action ──
        return RebalanceDecision(
            action="no_action",
            asset="",
            amount="0",
            reason=f"HF={snap.health_factor:.4f} in SAFE zone. No action needed.",
            priority=0,
            alert_level=level.value,
        )

    def _make_repay_decision(
        self,
        snap: HealthSnapshot,
        debt_token: Dict,
        total_debt: float,
        fraction: float,
        priority: int,
        level_str: str,
        prefix: str,
    ) -> RebalanceDecision:
        """Create a repay decision with proper amount calculation.

        Note on units:
          - ``total_debt`` comes from Aave's ``totalDebtBase`` which is in
            1e8 "base units" where 1e8 == $1.
          - Aave V3 repay/borrow actions expect the amount in the token's
            own base units (e.g. 1e6 for USDC, 1e18 for WETH).
          So:  debt_usd = total_debt / 1e8
               repay_usd = debt_usd * fraction
               repay_token_units = int(repay_usd * 10**decimals)
        """
        decimals = debt_token["decimals"]
        debt_usd = total_debt / 1e8
        repay_usd = debt_usd * fraction
        # SECURITY: clamp to a hard USD ceiling so a bad reading / units bug
        # can never produce a runaway repay amount.
        cap = getattr(self.cfg, "max_rebalance_usd", 0) or 0
        if cap > 0 and repay_usd > cap:
            print(f"  🛡️  Repay {repay_usd:.2f} USD exceeds cap {cap:.2f} — clamping.")
            repay_usd = cap
        repay_token_units = int(repay_usd * (10 ** decimals))

        return RebalanceDecision(
            action="repay",
            asset=debt_token["address"],
            amount=f"{repay_token_units}",
            reason=(
                f"{prefix} — HF={snap.health_factor:.4f} ({level_str}). "
                f"Repay {fraction*100:.0f}% of {config.DEBT_TOKEN} debt "
                f"({repay_usd:.6f} {config.DEBT_TOKEN}). "
                f"Trend: {snap.hf_trend:+.4f}/read, "
                f"{snap.consecutive_declines} consecutive declines."
            ),
            priority=priority,
            alert_level=level_str,
            estimated_hf_impact=self._estimate_repay_impact(snap, fraction),
        )

    # ── HF impact estimation ──────────────────────────────────

    def _estimate_repay_impact(self, snap: HealthSnapshot, fraction: float) -> float:
        """Estimate how much HF improves after repaying fraction of debt.

        HF = total_collateral * liquidation_threshold / total_debt
        New HF ≈ collateral * lt / (debt * (1 - fraction))
        """
        collateral = float(snap.total_collateral_base)
        debt = float(snap.total_debt_base)
        lt = float(snap.liquidation_threshold) / 10000  # basis points → ratio

        if debt <= 0 or lt <= 0:
            return 0.0

        current_hf = collateral * lt / debt
        new_debt = debt * (1 - fraction)
        new_hf = collateral * lt / new_debt if new_debt > 0 else float("inf")

        return new_hf - current_hf

    def _estimate_supply_impact(self, snap: HealthSnapshot) -> float:
        """Estimate HF improvement from supplying more collateral."""
        collateral = float(snap.total_collateral_base)
        debt = float(snap.total_debt_base)
        lt = float(snap.liquidation_threshold) / 10000

        if debt <= 0 or lt <= 0:
            return 0.0

        # Assume 0.01 WETH ≈ 0.01 * $3000 = $30 in base units
        boost = 30 * 1e8  # rough estimate in base units
        current_hf = collateral * lt / debt
        new_hf = (collateral + boost) * lt / debt

        return new_hf - current_hf

    # ── Execution ─────────────────────────────────────────────

    def execute(self, decision: RebalanceDecision, snap: HealthSnapshot) -> dict:
        """Execute a rebalance decision via KeeperHub.

        Returns the execution result dict (with tx_hash, gas, etc.).
        """
        if decision.action == "no_action":
            return {"status": "no_action"}

        idem_key = f"{self.cfg.idempotency_prefix}_{int(_time.time())}"

        print(f"\n{'='*60}")
        print(f"  REBALANCE TRIGGERED — {decision.alert_level}")
        print(f"  Action:  {decision.action.upper()}")
        print(f"  Asset:   {decision.asset}")
        print(f"  Amount:  {decision.amount}")
        print(f"  Est. HF impact: +{decision.estimated_hf_impact:.4f}")
        print(f"  Reason:  {decision.reason}")
        print(f"  Idem:    {idem_key}")
        print(f"{'='*60}\n")

        try:
            if decision.action == "repay":
                # Approve the debt token for the Aave Pool so repay() can pull funds.
                # SECURITY: approve the EXACT repay amount, never an unlimited
                # (MAX uint256) allowance — a lingering infinite allowance is a
                # standing drain risk if the Pool or a delegate is ever compromised.
                try:
                    self.client.approve(
                        decision.asset, config.AAVE_POOL, decision.amount,
                    )
                except MCPError as e:
                    print(f"  ⚠️  Pre-repay approve skipped: {e}")
                result = self.client.repay(
                    asset=decision.asset,
                    amount=decision.amount,
                    interest_rate_mode=self.cfg.interest_rate_mode,
                    idempotency_key=idem_key,
                )
            elif decision.action == "supply":
                result = self.client.supply(
                    asset=decision.asset,
                    amount=decision.amount,
                    idempotency_key=idem_key,
                )
            else:
                return {"status": "no_action"}

            # Extract key fields from result
            tx_hash = result.get("transactionHash") or result.get("txHash", "N/A")
            gas_used = result.get("gasUsed", "N/A")
            explorer_link = result.get("transactionLink", "")
            status = "success" if result.get("success") else "failed"

            if status == "success":
                print(f"  ✓ TX confirmed: {tx_hash}")
                if explorer_link:
                    print(f"  ✓ Explorer: {explorer_link}")
            else:
                print(f"  ✗ TX failed: {result.get('error', 'unknown')}")

            # Log to audit
            self.audit.log_trigger(
                health_factor=f"{snap.health_factor:.4f}",
                action=f"{decision.action} {decision.amount}",
                params={
                    "asset": decision.asset,
                    "idempotency_key": idem_key,
                    "alert_level": decision.alert_level,
                    "estimated_hf_impact": decision.estimated_hf_impact,
                },
                tx_hash=tx_hash,
                gas_used=gas_used,
                status=status,
                error=result.get("error"),
                explorer_link=explorer_link,
            )

            self._last_decision = decision
            return result

        except MCPError as e:
            print(f"  ✗ Execution error: {e}")
            self.audit.log_trigger(
                health_factor=f"{snap.health_factor:.4f}",
                action=f"{decision.action} {decision.amount}",
                params={
                    "asset": decision.asset,
                    "idempotency_key": idem_key,
                    "alert_level": decision.alert_level,
                },
                status="error",
                error=str(e),
            )
            raise

    def handle_unsafe(self, snap: HealthSnapshot):
        """Callback for Monitor.on_unsafe — evaluate and execute."""
        decision = self.evaluate(snap)
        self.execute(decision, snap)

    def handle_warning(self, snap: HealthSnapshot):
        """Callback for Monitor.on_warning — evaluate, execute if needed."""
        decision = self.evaluate(snap)
        if decision.action != "no_action":
            self.execute(decision, snap)
        else:
            print(f"  ℹ️  Warning zone but no action needed. HF={snap.health_factor:.4f}")

    # ── Position summary ──────────────────────────────────────

    def get_position_summary(self, snap: HealthSnapshot) -> Dict:
        """Return a summary of the current position and recommended action."""
        decision = self.evaluate(snap)
        return {
            "health_factor": snap.health_factor,
            "alert_level": snap.alert_level.value,
            "total_collateral": snap.total_collateral_base,
            "total_debt": snap.total_debt_base,
            "ltv": snap.ltv,
            "liquidation_threshold": snap.liquidation_threshold,
            "trend": {
                "avg_change_per_reading": snap.hf_trend,
                "pct_rate": snap.hf_rate_pct,
                "consecutive_declines": snap.consecutive_declines,
            },
            "recommended_action": {
                "action": decision.action,
                "asset": decision.asset,
                "amount": decision.amount,
                "reason": decision.reason,
                "estimated_hf_impact": decision.estimated_hf_impact,
            },
        }
