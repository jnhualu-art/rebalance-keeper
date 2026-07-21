"""
FlareKeeper — TEE-secured autonomous rebalancer (Flare Summer Signal Bounty 2).

Pipeline:
  read on-chain treasury
    → compute the rebalance decision INSIDE a TEE (Confidential Compute)
    → ANCHOR the attestation on-chain (verifiable "this came from the strategy")
    → EXECUTE the attested decision (native C2FLR or ERC-20 transfer)

This is the full "agent acts on its own, but its brain is confidential AND its
decisions are verifiable" loop for the Confidential Compute Apps bounty.

Signing/execution reuse src/flare_executor.py (EIP-1559, mirrors arc_executor).
"""

from typing import Dict, Optional

from src import config
from src.flare_client import FlareClient, FlareError
from src.flare_tee import ConfidentialCompute, AttestedDecision
from src.flare_executor import FlareExecutor, FlareExecutorError
from src.arc_position import evaluate


class FlareRebalancer:
    def __init__(
        self,
        client: FlareClient = None,
        tee: ConfidentialCompute = None,
        executor: FlareExecutor = None,
    ):
        self.client = client or FlareClient()
        self.tee = tee or ConfidentialCompute()
        self.executor = executor or FlareExecutor()

    # ── read → decide (in TEE) → anchor → execute ───────────────
    def run_once(self, dry_run: bool = False, anchor: bool = True) -> Dict:
        """One autonomous cycle. `anchor` publishes the attestation on-chain.

        In dry_run mode nothing is broadcast — the built (unsigned) txs are
        returned so the whole loop is inspectable without keys / gas.
        """
        cfg = config.FLARE_REBALANCE_CONFIG
        operational = config.FLARE_WALLET_ADDRESS
        reserve = config.FLARE_RESERVE_ADDRESS
        if not operational:
            return {"error": "FLARE_WALLET_ADDRESS not set in .env"}

        # Safety: refuse to sign if the RPC is serving a different chain
        # (swapped / MITM node could fake balances to trigger bad rebalances).
        if hasattr(self.client, "verify_chain"):
            try:
                self.client.verify_chain()
            except FlareError as e:
                return {"error": f"Chain verification failed: {e}"}

        # Funds may only ever move between operational <-> reserve. This set is
        # passed to the executor as a recipient allowlist (defence-in-depth).
        allowed = {operational, reserve} if reserve else {operational}

        pos = self.client.get_position(operational, floor_usdc=cfg.floor_usdc)

        # ── strategy runs confidentially (pure + serialisable) ──
        decision_inputs = {
            "usdc_balance": pos["usdc_balance"],
            "treasury_health": pos["treasury_health"],
            "floor_usdc": cfg.floor_usdc,
            "ceiling_usdc": cfg.ceiling_usdc,
            "sweep_fraction": cfg.sweep_fraction,
            "topup_fraction_danger": cfg.topup_fraction_danger,
        }

        def strategy_fn(inp: Dict) -> Dict:
            snapshot = {
                "address": operational,
                "usdc_balance": inp["usdc_balance"],
                "floor_usdc": inp["floor_usdc"],
                "treasury_health": inp["treasury_health"],
            }
            zone, dec = evaluate(snapshot, cfg)
            return {
                "zone": zone,
                "action": dec.action,
                "amount_usdc": dec.amount_usdc,
                "reason": dec.reason,
            }

        attested: AttestedDecision = self.tee.compute(decision_inputs, strategy_fn)
        result = {"position": pos, "attested_decision": attested}

        # Honest disclosure: in simulated mode the attestation is NOT
        # enclave-backed. Surface it so operators never mistake the demo for
        # real confidential compute.
        if not self.tee.real:
            result["warning"] = (
                "TEE attestation is SIMULATED (sim:...) — NOT enclave-backed. "
                "Set FLARE_CC_REAL=1 and wire the Flare CC enclave for real "
                "confidential compute."
            )

        # ── anchor the attestation on-chain ─────────────────────
        if anchor:
            try:
                result["anchor"] = self.executor.anchor_attestation(
                    operational, attested.attestation,
                    config.FLARE_PRIVATE_KEY, dry_run=dry_run,
                )
            except FlareExecutorError as e:
                result["anchor"] = {"skipped": str(e)}

        # ── execute the attested decision ───────────────────────
        action = attested.decision["action"]
        amount = attested.decision.get("amount_usdc", 0.0)
        if action == "none" or amount <= 0:
            result["execution"] = {"action": "none", "reason": "treasury healthy"}
            return result

        try:
            if action == "sweep":
                # operating → reserve (signed by operational key)
                if not reserve:
                    raise FlareExecutorError("FLARE_RESERVE_ADDRESS not set")
                exec_res = self.executor.transfer(
                    operational, reserve, amount,
                    config.FLARE_PRIVATE_KEY, dry_run=dry_run,
                    allowed_recipients=allowed,
                )
            elif action == "topup":
                # reserve → operating (signed by reserve key)
                if not reserve:
                    raise FlareExecutorError("FLARE_RESERVE_ADDRESS not set")
                exec_res = self.executor.transfer(
                    reserve, operational, amount,
                    config.FLARE_RESERVE_PRIVATE_KEY, dry_run=dry_run,
                    allowed_recipients=allowed,
                )
            else:
                exec_res = {"action": action, "note": "unknown action"}
            exec_res["action"] = action
            result["execution"] = exec_res
        except FlareExecutorError as e:
            result["execution"] = {"action": action, "error": str(e)}

        return result

    # ── read-only status ────────────────────────────────────────
    def status(self) -> Dict:
        return self.client.get_position(
            config.FLARE_WALLET_ADDRESS,
            floor_usdc=config.FLARE_REBALANCE_CONFIG.floor_usdc,
        )
