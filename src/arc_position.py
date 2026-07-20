"""
ArcKeeper — treasury health evaluation & rebalance decision (Arc-native).

On Arc there is no Aave-style lending pool, so ArcKeeper manages a USDC
*treasury*: it watches its operating USDC balance and, when it dips below a
floor, rebalances by pulling USDC back from a reserve wallet. This is the
Agentic Economy pattern — an agent that manages treasury and rebalances
funds using USDC without a human in the loop.
"""

from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from src import config


@dataclass
class ArcRebalanceDecision:
    action: str            # "none" | "topup"
    zone: str              # SAFE | WARNING | DANGER | CRITICAL
    amount_usdc: float     # how much to pull from reserve (0 if none)
    reason: str


def evaluate(position: Dict, cfg: Optional[config.ArcRebalanceConfig] = None) -> Tuple[str, ArcRebalanceDecision]:
    """Evaluate a treasury position and decide whether to rebalance."""
    cfg = cfg or config.ARC_REBALANCE_CONFIG
    health = position["treasury_health"]
    current = position["usdc_balance"]
    floor = position["floor_usdc"]
    deficit = max(0.0, floor - current)

    if health >= cfg.safe_threshold:
        zone = "SAFE"
        return zone, ArcRebalanceDecision("none", zone, 0.0, "Treasury healthy")
    if health >= cfg.warn_threshold:
        zone = "WARNING"
        # Watch only — no action yet
        return zone, ArcRebalanceDecision("none", zone, 0.0, "Treasury thinning; monitor")
    if health >= cfg.danger_threshold:
        zone = "DANGER"
        amount = deficit * cfg.topup_fraction_danger
        return zone, ArcRebalanceDecision(
            "topup", zone, amount,
            f"Below floor; pull {amount:.2f} USDC from reserve to restore",
        )
    zone = "CRITICAL"
    amount = deficit * cfg.topup_fraction_critical
    return zone, ArcRebalanceDecision(
        "topup", zone, amount,
        f"Critical; emergency pull {amount:.2f} USDC from reserve",
    )


def zone_icon(zone: str) -> str:
    return {
        "SAFE": "✓",
        "WARNING": "⚠",
        "DANGER": "⚡",
        "CRITICAL": "🚨",
    }.get(zone, "?")


def print_status(position: Dict, decision: ArcRebalanceDecision, cfg: config.ArcRebalanceConfig):
    """Pretty-print an Arc treasury status block (used by CLI)."""
    from src import config as C

    health = position["treasury_health"]
    print(f"\n{'='*60}")
    print(f"  ArcKeeper — Arc Testnet Treasury Status")
    print(f"{'='*60}")
    print(f"  Wallet:    {position['address']}")
    print(f"  Chain:     {C.ARC_CHAIN_NAME} (id={position['chain_id']})")
    print(f"  Explorer:  {C.ARC_EXPLORER}")
    print(f"  Block:     {position['block_number']}")
    print(f"{'─'*60}")
    print(f"  USDC (ERC-20, 6dp): {position['usdc_balance']:.6f}")
    print(f"  USDC (native gas):   {position['native_usdc_balance']:.6f}")
    print(f"  Floor:               {position['floor_usdc']:.2f} USDC")
    print(f"  Treasury Health:     {health:.4f}" if health != float('inf') else "  Treasury Health: ∞")
    print(f"{'─'*60}")
    icon = zone_icon(decision.zone)
    print(f"  Status: {icon} {decision.zone}")
    print(f"  Zones:  SAFE≥{cfg.safe_threshold} | WARN≥{cfg.warn_threshold} | "
          f"DANGER≥{cfg.danger_threshold} | CRITICAL<{cfg.danger_threshold}")
    if decision.action == "topup":
        print(f"  ➜ Rebalance: {decision.reason}")
    print()
