"""
FlareKeeper — TEE-secured autonomous rebalancer (Flare Summer Signal Bounty 2).

Pipeline:  read on-chain treasury  →  compute rebalance decision INSIDE a
TEE (Confidential Compute)  →  return an *attested* decision that can be
verified on-chain / consumed by a contract.

This is the "agent acts on its own, but its brain is confidential" half of
the Confidential Compute Apps bounty. The actual on-chain *execution* of the
decision (a USDC transfer on Flare) is a thin TODO — the rebalancer already
proves the novel part: a private, attestable strategy.

All signing/execution wiring mirrors src/arc_executor.py; swap the USDC
contract + chain config and it reuses the same EIP-1559 transfer path.
"""

from typing import Dict, Optional

from src import config
from src.flare_client import FlareClient, FlareError
from src.flare_tee import ConfidentialCompute, AttestedDecision
from src.arc_position import evaluate, ArcRebalanceDecision


class FlareRebalancer:
    def __init__(self, client: FlareClient = None, tee: ConfidentialCompute = None):
        self.client = client or FlareClient()
        self.tee = tee or ConfidentialCompute()

    # ── read → decide (in TEE) → (execute TODO) ─────────────────
    def run_once(self, dry_run: bool = False) -> Dict:
        """Read the treasury, decide the rebalance INSIDE a TEE, attest it."""
        operational = config.FLARE_WALLET_ADDRESS
        pos = self.client.get_position(
            operational, floor_usdc=config.FLARE_REBALANCE_CONFIG.floor_usdc
        )

        # The strategy runs confidentially. `evaluate` is pure & serialisable.
        decision_inputs = {
            "usdc_balance": pos["usdc_balance"],
            "floor_usdc": config.FLARE_REBALANCE_CONFIG.floor_usdc,
            "ceiling_usdc": config.FLARE_REBALANCE_CONFIG.ceiling_usdc,
            "sweep_fraction": config.FLARE_REBALANCE_CONFIG.sweep_fraction,
            "topup_fraction_danger": config.FLARE_REBALANCE_CONFIG.topup_fraction_danger,
        }

        def strategy_fn(inp: Dict) -> Dict:
            # Reuse the chain-agnostic evaluator; map its output to a dict so
            # it serialises cleanly into / out of the enclave.
            snapshot = {
                "address": operational,
                "usdc_balance": inp["usdc_balance"],
                "floor_usdc": inp["floor_usdc"],
            }
            zone, dec = evaluate(snapshot, config.FLARE_REBALANCE_CONFIG)
            return {
                "zone": zone,
                "action": dec.action,
                "amount_usdc": dec.amount_usdc,
                "reason": dec.reason,
            }

        attested: AttestedDecision = self.tee.compute(decision_inputs, strategy_fn)

        result = {
            "position": pos,
            "attested_decision": attested,
        }

        # ── Execution (TODO) ─────────────────────────────────────
        # Once FLARE_USDC_ERC20 + keys are set, mirror arc_executor.transfer_usdc
        # to broadcast the attested decision on Flare. Kept out of the skeleton
        # so the confidential-compute story is the demonstrable core.
        if attested.decision["action"] != "none":
            result["execution"] = (
                "TODO: broadcast attested decision on Flare (wire FLARE_USDC_ERC20 "
                "+ FLARE_PRIVATE_KEY, reuse EIP-1559 transfer path)"
            )
        else:
            result["execution"] = "none — treasury healthy, no on-chain action"

        return result

    # ── explicit demo actions (optional, for manual proofs) ──────
    def status(self) -> Dict:
        """Read-only treasury report (no TEE needed)."""
        return self.client.get_position(
            config.FLARE_WALLET_ADDRESS,
            floor_usdc=config.FLARE_REBALANCE_CONFIG.floor_usdc,
        )
