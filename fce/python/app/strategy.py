"""FlareKeeper rebalance *strategy* — the sensitive IP that runs inside the TEE.

This is the confidential brain of FlareKeeper. It is intentionally PURE and
self-contained (no network, no chain reads) so it can be shipped into a Flare
Confidential Compute enclave *unchanged* and reproduce bit-for-bit. It mirrors
src/arc_position.evaluate() from the parent repo so behaviour is identical.

The agent's treasury is kept inside a [floor, ceiling] band:
  - current > ceiling  -> sweep the excess to the reserve wallet (action="sweep")
  - floor <= current   -> healthy, no action
  - current < floor    -> pull funds back from reserve   (action="topup"),
                          severity WARNING/DANGER/CRITICAL by how far below
"""

from dataclasses import dataclass
from typing import Tuple


@dataclass
class RebalanceDecision:
    action: str            # "none" | "topup" | "sweep"
    zone: str             # SAFE | WARNING | DANGER | CRITICAL | OVER
    amount: float         # how much to move (0 if none)
    reason: str


# Thresholds. Kept here (not imported from the repo) so the enclave image is
# small and reproducible. These mirror FlareRebalanceConfig defaults.
FLOOR = 20.0
CEILING = 50.0
SAFE_THRESHOLD = 2.0
WARN_THRESHOLD = 1.5
DANGER_THRESHOLD = 1.2
SWEEP_FRACTION = 1.0
TOPUP_FRACTION_WARN = 0.5
TOPUP_FRACTION_DANGER = 1.0
TOPUP_FRACTION_CRITICAL = 1.0


def evaluate(
    treasury_balance: float,
    treasury_health: float,
    floor: float = FLOOR,
    ceiling: float = CEILING,
) -> Tuple[str, RebalanceDecision]:
    """Decide how (and whether) to rebalance, given a treasury snapshot.

    Mirrors src/arc_position.evaluate(): current=t安全员reasury_balance,
    floor=floor, ceiling=cfg.ceiling, health=treasury_health.
    """
    current = treasury_balance
    health = treasury_health

    # 1) Over-funded: keep only `ceiling` in the operating wallet, sweep the rest.
    if current > ceiling:
        excess = current - ceiling
        amount = round(excess * SWEEP_FRACTION, 6)
        if amount >= 1e-6:
            return "OVER", RebalanceDecision(
                "sweep", "OVER", amount,
                f"Operating {current:.2f} > ceiling {ceiling:.2f}; "
                f"sweep {amount:.2f} to reserve",
            )

    # 2) Healthy band [floor, ceiling]: no action, just report.
    if current >= floor:
        zone = "SAFE" if health >= SAFE_THRESHOLD else "WARNING"
        return zone, RebalanceDecision("none", zone, 0.0, "Treasury healthy")

    # 3) Below floor: pull funds back from reserve (severity by deficit).
    deficit = floor - current
    if health >= WARN_THRESHOLD:
        zone, amount = "WARNING", deficit * TOPUP_FRACTION_WARN
    elif health >= DANGER_THRESHOLD:
        zone, amount = "DANGER", deficit * TOPUP_FRACTION_DANGER
    else:
        zone, amount = "CRITICAL", deficit * TOPUP_FRACTION_CRITICAL
    amount = round(amount, 6)
    if amount >= 1e-6:
        return zone, RebalanceDecision(
            "topup", zone, amount,
            f"Below floor; pull {amount:.2f} from reserve to restore",
        )
    return "CRITICAL", RebalanceDecision("none", "CRITICAL", 0.0, "Deficit negligible")
