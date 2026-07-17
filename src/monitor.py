"""
RebalanceKeeper — Position monitor.

Polls Aave V3 account data on a fixed interval, records health-factor
history, and triggers the rebalancer when the health factor drops
below the configured threshold.
"""

import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Deque, Dict, Optional

from . import config
from .audit import AuditLogger
from .keeperhub_client import KeeperHubClient, MCPError


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

    @property
    def has_debt(self) -> bool:
        return float(self.total_debt_base) > 0

    @property
    def is_safe(self) -> bool:
        """True if health factor is above threshold (or no debt at all)."""
        if not self.has_debt:
            return True
        return self.health_factor >= config.REBALANCE_CONFIG.health_factor_threshold


class Monitor:
    """Monitors an Aave V3 position and triggers rebalancing when needed."""

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

    def on_unsafe(self, callback: Callable[[HealthSnapshot], None]):
        """Register a callback for when health factor drops below threshold."""
        self._on_unsafe = callback

    def read(self) -> HealthSnapshot:
        """Read the current position from Aave V3 via KeeperHub."""
        data = self.client.get_user_account_data(self.wallet)

        hf_raw = data.get("healthFactor", "0")
        # uint256 max (~1.15e77) means no debt → health factor is infinite
        hf = float(hf_raw) if float(hf_raw) < 1e30 else float("inf")

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
        return snap

    def check_once(self) -> HealthSnapshot:
        """Read once, log to audit, trigger callback if unsafe."""
        snap = self.read()

        if snap.has_debt:
            status = "SAFE" if snap.is_safe else "UNSAFE"
            print(
                f"[{snap.timestamp}] HF={snap.health_factor:.4f} "
                f"Collateral={snap.total_collateral_base} "
                f"Debt={snap.total_debt_base} "
                f"→ {status}"
            )
        else:
            print(f"[{snap.timestamp}] No debt position. HF=infinity")

        # Log to audit
        if snap.is_safe:
            self.audit.log_monitor(
                health_factor=f"{snap.health_factor:.4f}",
                collateral=snap.total_collateral_base,
                debt=snap.total_debt_base,
            )
        else:
            # Trigger rebalancer callback
            if self._on_unsafe:
                self._on_unsafe(snap)

        return snap

    def run(self, interval: int = None):
        """Run the monitoring loop forever (or until Ctrl+C)."""
        interval = interval or self.cfg.monitor_interval
        print(f"Monitor started. Wallet: {self.wallet}")
        print(f"  Chain: {config.CHAIN_NAME} (id={config.CHAIN_ID})")
        print(f"  Threshold: HF < {self.cfg.health_factor_threshold}")
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

    def get_history(self) -> list:
        """Return history as list of dicts (for dashboard)."""
        return [
            {
                "timestamp": s.timestamp,
                "health_factor": s.health_factor if s.health_factor != float("inf") else 999,
                "total_collateral_base": s.total_collateral_base,
                "total_debt_base": s.total_debt_base,
            }
            for s in self.history
        ]
