"""
ArcKeeper — treasury health evaluation & rebalance decision (Arc-native).

On Arc there is no Aave-style lending pool, so ArcKeeper manages a USDC
*treasury*: it watches its operating USDC balance and, when it dips below a
floor, rebalances by pulling USDC back from a reserve wallet — and when it
runs above a ceiling, it sweeps the excess back to reserve. This is the
Agentic Economy pattern — an agent that manages treasury and rebalances
funds using USDC without a human in the loop.
"""

from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from src import config


@dataclass
class ArcRebalanceDecision:
    action: str            # "none" | "topup" | "sweep"
    zone: str              # SAFE | WARNING | DANGER | CRITICAL | OVER
    amount_usdc: float     # how much to move (0 if none)
    reason: str


def evaluate(position: Dict, cfg: Optional[config.ArcRebalanceConfig] = None) -> Tuple[str, ArcRebalanceDecision]:
    """Evaluate a treasury position and decide whether/how to rebalance.

    The agent keeps the operating wallet inside the band [floor, ceiling]:
      - current > ceiling  → sweep the excess to reserve  (action="sweep")
      - floor <= current   → healthy, no action
      - current < floor    → pull USDC back from reserve   (action="topup"),
                             severity (WARNING/DANGER/CRITICAL) by how far below
    """
    cfg = cfg or config.ARC_REBALANCE_CONFIG
    # Cross-chain compatible: Flare uses treasury_balance/floor/ceiling,
    # Arc keeps usdc_balance/floor_usdc/ceiling_usdc.
    current = position.get("treasury_balance", position.get("usdc_balance"))
    floor = position.get("floor", position.get("floor_usdc"))
    ceiling = getattr(cfg, "ceiling", None) or getattr(cfg, "ceiling_usdc")
    health = position["treasury_health"]  # = current / floor

    # 1) Over-funded: keep only `ceiling` in the operating wallet, sweep the rest.
    if current > ceiling:
        excess = current - ceiling
        amount = round(excess * cfg.sweep_fraction, 6)
        if amount >= 1e-6:
            return "OVER", ArcRebalanceDecision(
                "sweep", "OVER", amount,
                f"Operating {current:.2f} > ceiling {ceiling:.2f}; "
                f"sweep {amount:.2f} to reserve",
            )

    # 2) Healthy band [floor, ceiling]: no action, just report.
    if current >= floor:
        zone = "SAFE" if health >= cfg.safe_threshold else "WARNING"
        return zone, ArcRebalanceDecision("none", zone, 0.0, "Treasury healthy")

    # 3) Below floor: pull USDC back from reserve (severity by deficit).
    deficit = floor - current
    if health >= cfg.warn_threshold:
        zone, amount = "WARNING", deficit * cfg.topup_fraction_warn
    elif health >= cfg.danger_threshold:
        zone, amount = "DANGER", deficit * cfg.topup_fraction_danger
    else:
        zone, amount = "CRITICAL", deficit * cfg.topup_fraction_critical
    amount = round(amount, 6)
    if amount >= 1e-6:
        return zone, ArcRebalanceDecision(
            "topup", zone, amount,
            f"Below floor; pull {amount:.2f} from reserve to restore",
        )
    return "CRITICAL", ArcRebalanceDecision("none", "CRITICAL", 0.0, "Deficit negligible")


def zone_icon(zone: str) -> str:
    return {
        "SAFE": "✓",
        "WARNING": "⚠",
        "DANGER": "⚡",
        "CRITICAL": "🚨",
        "OVER": "🔼",
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
    print(f"  Ceiling:             {cfg.ceiling_usdc:.2f} USDC")
    print(f"  Treasury Health:     {health:.4f}" if health != float('inf') else "  Treasury Health: ∞")
    print(f"{'─'*60}")
    icon = zone_icon(decision.zone)
    print(f"  Status: {icon} {decision.zone}")
    print(f"  Band:   [floor {cfg.floor_usdc:.0f} .. ceiling {cfg.ceiling_usdc:.0f}] USDC")
    if decision.action in ("topup", "sweep"):
        print(f"  ➜ Rebalance: {decision.reason}")
    print()
