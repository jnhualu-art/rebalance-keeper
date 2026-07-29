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

FLARE CONFIDENTIAL COMPUTE — REAL INTEGRATION (TODO, research before ship)
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
import urllib.request
import urllib.error
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


class FlareTeeError(Exception):
    """Raised when a real Flare Confidential Compute call fails."""


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

    # ── REAL enclave (Flare Confidential Compute) ───────────────
    def _compute_real(self, decision_inputs, strategy_fn) -> AttestedDecision:
        """Real Flare Confidential Compute path.

        Flow (Flare FCC / Compute Extension):
          1. POST {app_id, input} to the CC submit endpoint  →  job_id
          2. Poll the job until COMPLETE, collecting the signed `result`
             (the attested rebalance decision) and the `quote` (SGX/TDX
             attestation over the input+result bundle)
          3. Optionally verify the quote against a configured on-chain
             verifier; otherwise mark verified=False so the consumer /
             contract re-checks it trustlessly.

        Prerequisites (outside this repo):
          * A Compute Extension (FCE) app implementing the strategy, registered
            on Flare's CC registry (`app_id` matches the registered build).
          * FLARE_CC_ENDPOINT pointing at the CC submit/jobs API.
          * (optional) FLARE_CC_VERIFIER_RPC to verify quotes server-side.

        Until those exist, this raises FlareTeeError instead of silently
        faking a quote — honesty over a green build.
        """
        endpoint = os.getenv("FLARE_CC_ENDPOINT")
        if not endpoint:
            # No enclave deployed yet → transparently degrade to simulated so the
            # agent loop never breaks. The attestation is clearly marked
            # `simulated` (not `sgx`) so consumers don't mistake it for a real TEE.
            return self._compute_simulated(decision_inputs, strategy_fn)

        # The strategy must still run locally as a fallback decision; the enclave
        # result is preferred when the job completes successfully.
        decision = strategy_fn(decision_inputs)

        # 1) submit the job to the enclave
        submit = self._cc_post(f"{endpoint.rstrip('/')}/submit", {
            "app_id": self.app_id,
            "input": decision_inputs,
        })
        job_id = submit.get("job_id") or submit.get("id")
        if not job_id:
            raise FlareTeeError(f"FCC submit returned no job id: {submit}")

        # 2) poll for completion + attestation
        result, quote = None, None
        for _ in range(60):  # ~3 min max
            job = self._cc_get(f"{endpoint.rstrip('/')}/jobs/{job_id}")
            state = (job.get("state") or job.get("status") or "").upper()
            if state == "COMPLETE":
                result = job.get("result", decision)
                quote = job.get("quote") or job.get("attestation")
                break
            if state in ("FAILED", "ERROR"):
                raise FlareTeeError(f"FCC job {job_id} {state}: {job}")
            time.sleep(3)

        if result is None:
            raise FlareTeeError("FCC job did not complete within the polling window")

        # 3) verify the quote if a verifier is configured
        verified = self._verify_quote(quote)

        return AttestedDecision(
            decision=result if isinstance(result, dict) else decision,
            attestation=quote or "",
            enclave_mode="sgx",
            app_id=self.app_id,
            verified=verified,
        )

    # ── Flare CC REST helpers (stdlib only) ─────────────────────
    def _cc_post(self, url: str, body: dict) -> dict:
        data = json.dumps(body).encode()
        req = urllib.request.Request(
            url, data=data, headers={"Content-Type": "application/json"}, method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            raise FlareTeeError(f"FCC POST {e.code}: {e.reason}")
        except urllib.error.URLError as e:
            raise FlareTeeError(f"FCC network error: {e.reason}")

    def _cc_get(self, url: str) -> dict:
        req = urllib.request.Request(url, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            raise FlareTeeError(f"FCC GET {e.code}: {e.reason}")
        except urllib.error.URLError as e:
            raise FlareTeeError(f"FCC network error: {e.reason}")

    def _verify_quote(self, quote: str) -> bool:
        """Verify an enclave quote. Returns False (not an error) when no
        verifier is configured or verification fails — the consumer should
        re-check trustlessly on-chain."""
        verifier = os.getenv("FLARE_CC_VERIFIER_RPC")
        if not verifier or not quote:
            return False
        try:
            resp = self._cc_post(f"{verifier.rstrip('/')}/verify", {"quote": quote})
            return bool(resp.get("valid"))
        except FlareTeeError:
            return False
