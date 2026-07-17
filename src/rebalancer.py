"""
RebalanceKeeper — Rebalancing decision engine.

When the health factor drops below the threshold, the rebalancer decides
whether to:
  1. Repay a portion of the debt (reduces debt → raises HF), or
  2. Supply more collateral (increases collateral → raises HF)

Decision logic:
  - If the wallet holds enough debt token → repay (cheaper, direct)
  - If not → supply more collateral (fallback)
"""

from dataclasses import dataclass
from typing import Optional

from . import config
from .audit import AuditLogger
from .keeperhub_client import KeeperHubClient, MCPError
from .monitor import HealthSnapshot


@dataclass
class RebalanceDecision:
    """A rebalancing decision produced by the evaluation logic."""

    action: str           # "repay" | "supply" | "no_action"
    asset: str            # token address
    amount: str           # human-readable amount
    reason: str           # human-readable explanation


class Rebalancer:
    """Evaluates position health and executes rebalancing actions."""

    def __init__(
        self,
        client: KeeperHubClient,
        cfg: config.RebalanceConfig = config.REBALANCE_CONFIG,
        audit: Optional[AuditLogger] = None,
    ):
        self.client = client
        self.cfg = cfg
        self.audit = audit or AuditLogger(cfg.audit_log_path)

    def evaluate(self, snap: HealthSnapshot) -> RebalanceDecision:
        """Decide what to do based on the current health factor.

        Args:
            snap: Current health snapshot from the monitor.

        Returns:
            A RebalanceDecision with action, asset, amount, reason.
        """
        debt_token = config.TOKENS[config.DEBT_TOKEN]
        collateral_token = config.TOKENS[config.COLLATERAL_TOKEN]

        # Calculate repay amount: fraction of total debt
        total_debt = float(snap.total_debt_base)
        repay_amount = total_debt * self.cfg.repay_fraction

        if repay_amount > 0:
            # Convert to human-readable based on token decimals
            # Aave returns values in base units (wei), so divide by 10^decimals
            decimals = debt_token["decimals"]
            human_amount = repay_amount / (10 ** decimals)

            return RebalanceDecision(
                action="repay",
                asset=debt_token["address"],
                amount=f"{human_amount:.6f}",
                reason=(
                    f"HF={snap.health_factor:.4f} < {self.cfg.health_factor_threshold}. "
                    f"Repay {self.cfg.repay_fraction*100:.0f}% of {config.DEBT_TOKEN} debt "
                    f"({human_amount:.6f} {config.DEBT_TOKEN})."
                ),
            )

        # Fallback: supply more collateral
        return RebalanceDecision(
            action="supply",
            asset=collateral_token["address"],
            amount=self.cfg.supply_boost_amount,
            reason=(
                f"HF={snap.health_factor:.4f} < {self.cfg.health_factor_threshold}. "
                f"No debt to repay. Supply {self.cfg.supply_boost_amount} "
                f"{config.COLLATERAL_TOKEN} as extra collateral."
            ),
        )

    def execute(self, decision: RebalanceDecision, snap: HealthSnapshot) -> dict:
        """Execute a rebalance decision via KeeperHub.

        Returns the execution result dict (with tx_hash, gas, etc.).
        """
        import time as _time

        idem_key = f"{self.cfg.idempotency_prefix}_{int(_time.time())}"

        print(f"\n{'='*60}")
        print(f"  REBALANCE TRIGGERED")
        print(f"  Action: {decision.action.upper()}")
        print(f"  Asset:  {decision.asset}")
        print(f"  Amount: {decision.amount}")
        print(f"  Reason: {decision.reason}")
        print(f"  Idempotency key: {idem_key}")
        print(f"{'='*60}\n")

        try:
            if decision.action == "repay":
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
                params={"asset": decision.asset, "idempotency_key": idem_key},
                tx_hash=tx_hash,
                gas_used=gas_used,
                status=status,
                error=result.get("error"),
                explorer_link=explorer_link,
            )

            return result

        except MCPError as e:
            print(f"  ✗ Execution error: {e}")
            self.audit.log_trigger(
                health_factor=f"{snap.health_factor:.4f}",
                action=f"{decision.action} {decision.amount}",
                params={"asset": decision.asset, "idempotency_key": idem_key},
                status="error",
                error=str(e),
            )
            raise

    def handle_unsafe(self, snap: HealthSnapshot):
        """Callback for Monitor.on_unsafe — evaluate and execute."""
        decision = self.evaluate(snap)
        self.execute(decision, snap)
