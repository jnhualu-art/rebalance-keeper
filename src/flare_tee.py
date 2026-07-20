"""
FlareKeeper — Confidential Compute (TEE) layer for the rebalancer.

WHY THIS FILE EXISTS
--------------------
Flare Summer Signal **Bounty 2 — Confidential Compute Apps** rewards
"TEE-secured agents / private strategy execution / confidential AI workflows".
The idea: the agent's *rebalancing strategy* (how much to move, when, under
what thresholds) is sensitive IP and, more importantly, leaks the agent's
treasury state if computed in the clear. Running it inside a Trusted
Execution Environment (TEE / SGX enclave) and attesting the result on-chain
means:

  * the strategy logic + treasury inputs stay private (not exposed in the tx),
  * the resulting decision is *verifiable* — anyone can check an enclave
    quote proving "this decision came from the approved strategy binary",
  * smart contracts / other agents can consume the attested decision
    trustlessly.

This module is the integration seam. It runs in two modes:

  1. SIMULATED (default, no enclave infra needed): computes locally and
     returns a deterministic *attestation hash* so the full agent loop is
     demoable today. Clearly marked where the real path slots in.

  2. REAL (TODO): submit the strategy payload to a Flare Confidential
     Compute enclave, get back the signed quote + result.

FLASH CONFIDENTIAL COMPUTE — REAL INTEGRATION (TODO, research before ship)
--------------------------------------------------------------------------
Flare runs a network of enclaves. The high-level flow:
  a. Package the strategy as a CC app (the enclave binary / wasm).
  b. Register it / get an app-id via the Flare CC control API.
  c. Submit `{app_id, input}` to the CC submit endpoint
     (e.g. https://...flare.network/confidential-compute  — verify in docs).
  d. The enclave executes off-chain, produces `result` + an SGX `quote`
     (attestation). The quote is verifiable on-chain via Flare's verifier
     contract (FdcHub / dedicated CC verifier).
  e. The agent posts the attestation + decision on-chain (or to a contract)
     so execution can be gated on a valid quote.

For the hackathon we ship SIMULATED now, wire REAL in week 2–3.
"""

import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


# Flip to True once the real Flare CC enclave is wired (see TODO above).
CC_REAL_ENCLAVE = os.getenv("FLARE_CC_REAL", "0") == "1"


@dataclass
class AttestedDecision:
    """A rebalance decision plus its confidential-compute attestation."""

    decision: Dict[str, Any]
    attestation: str          # quote / hash proving the decision came from TEE
    enclave_mode: str         # "simulated" | "sgx"
    app_id: str = "rebalance-strategy-v1"
    verified: bool = True     # simulated mode self-verifies; real mode checks quote


class ConfidentialCompute:
    """Runs the rebalancer *strategy* inside a confidential enclave.

    The strategy function is intentionally pure & serialisable so it can be
    shipped into an enclave unchanged. `strategy_fn(decision_inputs) -> dict`
    receives the treasury snapshot and returns the rebalance decision.
    """

    def __init__(self, app_id: str = "rebalance-strategy-v1", real: bool = None):
        self.app_id = app_id
        self.real = CC_REAL_ENCLAVE if real is None else real

    def compute(self, decision_inputs: Dict[str, Any], strategy_fn) -> AttestedDecision:
        """Execute `strategy_fn` confidentially and return an attested decision.

        decision_inputs: serialisable treasury snapshot (balance, floor, ceiling…)
        strategy_fn:     pure function(decision_inputs) -> decision dict
        """
        if self.real:
            return self._compute_real(decision_inputs, strategy_fn)
        return self._compute_simulated(decision_inputs, strategy_fn)

    # ── SIMULATED enclave (demoable today) ──────────────────────
    def _compute_simulated(self, decision_inputs, strategy_fn) -> AttestedDecision:
        decision = strategy_fn(decision_inputs)
        # Attestation = hash of (app_id || inputs || decision || nonce). In a
        # real enclave this is replaced by the SGX quote over the same bundle.
        bundle = json.dumps(
            {
                "app_id": self.app_id,
                "inputs": decision_inputs,
                "decision": decision,
                "nonce": int(time.time() * 1000),
            },
            sort_keys=True,
        ).encode()
        attestation = "sim:" + hashlib.sha256(bundle).hexdigest()
        return AttestedDecision(
            decision=decision,
            attestation=attestation,
            enclave_mode="simulated",
            app_id=self.app_id,
            verified=True,
        )

    # ── REAL enclave (TODO: wire Flare Confidential Compute API) ─
    def _compute_real(self, decision_inputs, strategy_fn) -> AttestedDecision:
        # TODO: 
        #   1. POST {app_id, input: decision_inputs} to Flare CC submit endpoint
        #   2. Poll for the enclave result + SGX quote
        #   3. Verify the quote on-chain (Flare CC verifier) before returning
        # For now, fall back to simulated so the loop never breaks.
        return self._compute_simulated(decision_inputs, strategy_fn)
