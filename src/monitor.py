"""
RebalanceKeeper — Position monitor with trend analysis.

Polls Aave V3 account data on a fixed interval, records health-factor
history, and triggers the rebalancer when the health factor drops
below the configured threshold.

Enhanced features:
  - Multi-level alert zones (safe / warning / danger / critical)
  - Trend analysis: detect sustained HF decline and pre-empt
  - Rate-of-change tracking for predictive alerts
"""

import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Callable, Deque, Dict, List, Optional

from . import config
from .audit import AuditLogger
from .keeperhub_client import KeeperHubClient, MCPError


class AlertLevel(Enum):
    """Alert severity level for the current health factor."""
    SAFE = "SAFE"
    WARNING = "WARNING"
    DANGER = "DANGER"
    CRITICAL = "CRITICAL"


@dataclass
class HealthSnapshot:
    """A single point-in-time reading of the Aave position."""

    timestamp: str
    health_factor: float       # parsed to float (0 = no debt / infinity)
    total_collateral_base: str
    total_debt_base: str
    available_borrows_base: str
    ltv: str
    liquidation_threshold: str

    # Trend data (populated by Monitor)
    hf_trend: float = 0.0       # avg change per reading over trend_window
    hf_rate_pct: float = 0.0    # percentage change rate
    alert_level: AlertLevel = AlertLevel.SAFE
    consecutive_declines: int = 0  # how many readings in a row HF dropped

    @property
    def has_debt(self) -> bool:
        return float(self.total_debt_base) > 0

    @property
    def is_safe(self) -> bool:
        """True if health factor is in the safe zone (or no debt at all)."""
        if not self.has_debt:
            return True
        return self.alert_level == AlertLevel.SAFE

    @property
    def needs_action(self) -> bool:
        """True if the rebalancer should be triggered."""
        return self.alert_level in (AlertLevel.DANGER, AlertLevel.CRITICAL)


class Monitor:
    """Monitors an Aave V3 position and triggers rebalancing when needed.

    Features:
      - Multi-level alert zones with different response strategies
      - Trend analysis: if HF is declining steadily, trigger before threshold
      - Rate-of-change tracking for predictive alerts
      - Cooldown enforcement to prevent over-rebalancing
    """

    def __init__(
        self,
        client: KeeperHubClient,
        wallet: str = config.WALLET_ADDRESS,
        cfg: config.RebalanceConfig = config.REBALANCE_CONFIG,
        audit: Optional[AuditLogger] = None,
    ):
        self.client = client
        self.wallet = wallet
        self.cfg = cfg
        self.audit = audit or AuditLogger(cfg.audit_log_path)
        self.history: Deque[HealthSnapshot] = deque(maxlen=cfg.history_size)
        self._on_unsafe: Optional[Callable[[HealthSnapshot], None]] = None
        self._on_warning: Optional[Callable[[HealthSnapshot], None]] = None
        self._last_action_time: float = 0.0

    def on_unsafe(self, callback: Callable[[HealthSnapshot], None]):
        """Register a callback for when health factor drops to danger/critical."""
        self._on_unsafe = callback

    def on_warning(self, callback: Callable[[HealthSnapshot], None]):
        """Register a callback for when health factor enters warning zone."""
        self._on_warning = callback

    # ── Alert level classification ────────────────────────────

    def _classify(self, hf: float) -> AlertLevel:
        """Classify health factor into an alert level."""
        if hf == float("inf") or not self._has_debt_value():
            return AlertLevel.SAFE
        if hf >= self.cfg.safe_threshold:
            return AlertLevel.SAFE
        if hf >= self.cfg.warn_threshold:
            return AlertLevel.WARNING
        if hf >= self.cfg.danger_threshold:
            return AlertLevel.DANGER
        return AlertLevel.CRITICAL

    def _has_debt_value(self) -> bool:
        """Check if the latest snapshot has debt."""
        if not self.history:
            return False
        return float(self.history[-1].total_debt_base) > 0

    # ── Trend analysis ────────────────────────────────────────

    def _compute_trend(self) -> tuple:
        """Compute HF trend over the last N readings.

        Returns:
            (avg_change_per_reading, pct_rate, consecutive_declines)
        """
        window = list(self.history)[-self.cfg.trend_window:]
        if len(window) < 2:
            return (0.0, 0.0, 0)

        hfs = [s.health_factor for s in window if s.health_factor != float("inf")]
        if len(hfs) < 2:
            return (0.0, 0.0, 0)

        # Average change per reading
        diffs = [hfs[i] - hfs[i - 1] for i in range(1, len(hfs))]
        avg_change = sum(diffs) / len(diffs)

        # Percentage rate (relative to first reading in window)
        first = hfs[0] if hfs[0] != 0 else 1e-10
        pct_rate = (avg_change / abs(first)) * 100

        # Count consecutive declines
        declines = 0
        for d in reversed(diffs):
            if d < 0:
                declines += 1
            else:
                break

        return (avg_change, pct_rate, declines)

    # ── Cooldown ──────────────────────────────────────────────

    def _in_cooldown(self) -> bool:
        """Check if we're still in the cooldown period after last action."""
        if self._last_action_time == 0:
            return False
        elapsed = time.time() - self._last_action_time
        return elapsed < self.cfg.cooldown_seconds

    def _mark_action(self):
        """Record that an action was taken (resets cooldown)."""
        self._last_action_time = time.time()

    # ── Core read + check ─────────────────────────────────────

    def read(self) -> HealthSnapshot:
        """Read the current position from Aave V3 via KeeperHub."""
        data = self.client.get_user_account_data(self.wallet)

        hf_raw = data.get("healthFactor", "0")
        hf_val = float(hf_raw)
        # uint256 max (~1.15e77) means no debt → health factor is infinite
        if hf_val >= 1e30:
            hf = float("inf")
        else:
            # Aave V3 returns HF in 1e18 precision (like wei); convert to ratio
            hf = hf_val / 1e18

        snap = HealthSnapshot(
            timestamp=datetime.now(timezone.utc).isoformat(),
            health_factor=hf,
            total_collateral_base=data.get("totalCollateralBase", "0"),
            total_debt_base=data.get("totalDebtBase", "0"),
            available_borrows_base=data.get("availableBorrowsBase", "0"),
            ltv=data.get("ltv", "0"),
            liquidation_threshold=data.get("currentLiquidationThreshold", "0"),
        )
        self.history.append(snap)

        # Enrich with trend data
        avg_change, pct_rate, declines = self._compute_trend()
        snap.hf_trend = avg_change
        snap.hf_rate_pct = pct_rate
        snap.consecutive_declines = declines
        snap.alert_level = self._classify(hf)

        return snap

    def check_once(self) -> HealthSnapshot:
        """Read once, log to audit, trigger callbacks based on alert level."""
        snap = self.read()

        if snap.has_debt:
            trend_str = (
                f"trend={snap.hf_trend:+.4f}/read "
                f"({snap.hf_rate_pct:+.2f}%) "
                f"declines={snap.consecutive_declines}"
            )
            print(
                f"[{snap.timestamp}] HF={snap.health_factor:.4f} "
                f"Collateral={snap.total_collateral_base} "
                f"Debt={snap.total_debt_base} "
                f"| {trend_str} "
                f"→ {snap.alert_level.value}"
            )
        else:
            print(f"[{snap.timestamp}] No debt position. HF=infinity")
            snap.alert_level = AlertLevel.SAFE

        # Log to audit
        self.audit.log_monitor(
            health_factor=f"{snap.health_factor:.4f}",
            collateral=snap.total_collateral_base,
            debt=snap.total_debt_base,
        )

        # Trigger callbacks based on alert level
        if snap.alert_level == AlertLevel.CRITICAL:
            # Critical: always trigger, ignore cooldown
            print(f"  ⚠️  CRITICAL — HF below {self.cfg.danger_threshold}! Emergency rebalance.")
            if self._on_unsafe:
                self._on_unsafe(snap)
                self._mark_action()

        elif snap.alert_level == AlertLevel.DANGER:
            if not self._in_cooldown():
                print(f"  ⚡ DANGER — HF below {self.cfg.warn_threshold}. Rebalancing.")
                if self._on_unsafe:
                    self._on_unsafe(snap)
                    self._mark_action()
            else:
                remaining = int(self.cfg.cooldown_seconds - (time.time() - self._last_action_time))
                print(f"  ⏳ DANGER but in cooldown ({remaining}s remaining)")

        elif snap.alert_level == AlertLevel.WARNING:
            # Pre-emptive: if HF is declining fast, trigger early
            if snap.consecutive_declines >= self.cfg.trend_window - 1:
                print(f"  📉 WARNING — HF declining for {snap.consecutive_declines} readings. Pre-emptive rebalance.")
                if self._on_warning:
                    self._on_warning(snap)
                    self._mark_action()
            else:
                if self._on_warning:
                    self._on_warning(snap)  # soft warning, no cooldown

        return snap

    def run(self, interval: int = None):
        """Run the monitoring loop forever (or until Ctrl+C)."""
        interval = interval or self.cfg.monitor_interval
        print(f"Monitor started. Wallet: {self.wallet}")
        print(f"  Chain: {config.CHAIN_NAME} (id={config.CHAIN_ID})")
        print(f"  Zones: SAFE≥{self.cfg.safe_threshold} | "
              f"WARN≥{self.cfg.warn_threshold} | "
              f"DANGER≥{self.cfg.danger_threshold} | "
              f"CRITICAL<{self.cfg.danger_threshold}")
        print(f"  Trend window: {self.cfg.trend_window} readings")
        print(f"  Cooldown: {self.cfg.cooldown_seconds}s")
        print(f"  Interval: {interval}s")
        print(f"  Audit log: {self.cfg.audit_log_path}")
        print("-" * 60)

        while True:
            try:
                self.check_once()
            except MCPError as e:
                print(f"  [ERROR] {e}")
                self.audit.log(
                    event_type="error",
                    trigger="monitor_loop",
                    decision="error",
                    error=str(e),
                )
            except KeyboardInterrupt:
                print("\nMonitor stopped.")
                break
            time.sleep(interval)

    def get_history(self) -> List[Dict]:
        """Return history as list of dicts (for dashboard)."""
        return [
            {
                "timestamp": s.timestamp,
                "health_factor": s.health_factor if s.health_factor != float("inf") else 999,
                "total_collateral_base": s.total_collateral_base,
                "total_debt_base": s.total_debt_base,
                "alert_level": s.alert_level.value,
                "hf_trend": s.hf_trend,
                "consecutive_declines": s.consecutive_declines,
            }
            for s in self.history
        ]
