"""
ArcKeeper — autonomous rebalance executor (Arc-native treasury).

Turns an ArcRebalanceDecision into a real on-chain USDC transfer:
  - topup:  pull USDC from the RESERVE wallet into the OPERATIONAL wallet
            (when the treasury dips below its floor)
  - sweep:  push excess USDC from OPERATIONAL back to RESERVE
            (when the treasury is far above its floor)

This is the "agent acts on its own" half of the Agentic Economy track.
Signing/broadcast happens through a pluggable `WalletBackend` (local key by
default, Circle Agent Stack custody when ARC_WALLET_BACKEND=circle), so the
custody model is swappable without touching this logic.
"""

from typing import Dict, Optional

from src import config
from src.arc_client import ArcClient, ArcError
from src.arc_position import evaluate, ArcRebalanceDecision
from src.arc_wallet_backends import get_backend, WalletBackend, WalletBackendError


class ArcRebalancer:
    def __init__(self, backend: WalletBackend = None, client: ArcClient = None):
        self.backend = backend or get_backend()
        self.client = client or ArcClient()

    # ── read → decide → act ────────────────────────────────────
    def run_once(self, dry_run: bool = False) -> Dict:
        """Read the treasury, decide, and (if needed) execute a rebalance."""
        operational = config.ARC_WALLET_ADDRESS
        reserve = config.ARC_RESERVE_ADDRESS
        pos = self.client.get_position(operational, floor_usdc=config.ARC_REBALANCE_CONFIG.floor_usdc)
        _, decision = evaluate(pos, config.ARC_REBALANCE_CONFIG)

        result = {"position": pos, "decision": decision, "action": None}

        if decision.action == "none":
            return result

        if decision.action == "topup":
            if not reserve:
                result["error"] = "ARC_RESERVE_ADDRESS not set — cannot top up."
                return result
            result["action"] = self._topup(decision, operational, reserve, dry_run)
        elif decision.action == "sweep":
            if not reserve:
                result["error"] = "ARC_RESERVE_ADDRESS not set — cannot sweep."
                return result
            result["action"] = self.sweep(decision.amount_usdc, dry_run=dry_run)

        return result

    def _topup(
        self,
        decision: ArcRebalanceDecision,
        operational: str,
        reserve: str,
        dry_run: bool,
    ) -> Dict:
        """Pull `decision.amount_usdc` from reserve → operational."""
        return self.backend.transfer_usdc(
            from_address=reserve,
            to_address=operational,
            amount_usdc=decision.amount_usdc,
            private_key=config.ARC_RESERVE_PRIVATE_KEY,
            dry_run=dry_run,
        )

    # ── explicit demo actions ──────────────────────────────────
    def sweep(self, amount_usdc: float, dry_run: bool = False) -> Dict:
        """Push `amount_usdc` from operational → reserve (proves autonomous action)."""
        operational = config.ARC_WALLET_ADDRESS
        reserve = config.ARC_RESERVE_ADDRESS
        if not reserve:
            raise WalletBackendError("ARC_RESERVE_ADDRESS not set — cannot sweep.")
        return self.backend.transfer_usdc(
            from_address=operational,
            to_address=reserve,
            amount_usdc=amount_usdc,
            private_key=config.ARC_PRIVATE_KEY,
            dry_run=dry_run,
        )

    def topup(self, amount_usdc: float, dry_run: bool = False) -> Dict:
        """Pull `amount_usdc` from reserve → operational (explicit top-up)."""
        operational = config.ARC_WALLET_ADDRESS
        reserve = config.ARC_RESERVE_ADDRESS
        if not reserve:
            raise WalletBackendError("ARC_RESERVE_ADDRESS not set — cannot top up.")
        return self.backend.transfer_usdc(
            from_address=reserve,
            to_address=operational,
            amount_usdc=amount_usdc,
            private_key=config.ARC_RESERVE_PRIVATE_KEY,
            dry_run=dry_run,
        )
