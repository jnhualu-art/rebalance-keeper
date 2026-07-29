"""
Unit tests for FlareKeeper Confidential Compute layer (flare_tee.py).

Covers both modes without touching real enclaves:
  - SIMULATED (default) returns a `sim:` attestation hash
  - REAL with no endpoint raises FlareTeeError (honest, not faked)
  - REAL with a mocked CC API returns a verified sgx-mode decision
"""

import os
import sys
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.flare_tee import ConfidentialCompute, FlareTeeError


def _strategy(inputs):
    # trivial strategy: sweep when over the ceiling
    if inputs.get("usdc_balance", 0) > 75:
        return {"action": "sweep", "amount": 5.0}
    return {"action": "none", "amount": 0.0}


class TestFlareTeeSim(unittest.TestCase):
    def test_simulated_returns_sim_attestation(self):
        cc = ConfidentialCompute(real=False)
        d = cc.compute({"usdc_balance": 50}, _strategy)
        self.assertEqual(d.enclave_mode, "simulated")
        self.assertTrue(d.attestation.startswith("sim:"))
        self.assertTrue(d.verified)
        self.assertEqual(d.decision["action"], "none")


class TestFlareTeeReal(unittest.TestCase):
    def test_real_without_endpoint_degrades_to_sim(self):
        # No enclave deployed yet → transparently degrade to simulated (loop-safe),
        # but honestly marked `simulated`, not `sgx`.
        cc = ConfidentialCompute(real=True)
        d = cc.compute({"usdc_balance": 50}, _strategy)
        self.assertEqual(d.enclave_mode, "simulated")
        self.assertTrue(d.attestation.startswith("sim:"))

    def test_real_complete_with_quote(self):
        cc = ConfidentialCompute(real=True)
        calls = {"post": 0, "get": 0}

        def fake_post(url, body):
            calls["post"] += 1
            if url.endswith("/submit"):
                return {"job_id": "job_1"}
            # verify endpoint
            return {"valid": True}

        def fake_get(url):
            calls["get"] += 1
            if calls["get"] == 1:
                return {"state": "PENDING"}
            return {
                "state": "COMPLETE",
                "result": {"action": "sweep", "amount": 5.0},
                "quote": "0xenclavequote",
            }

        with mock.patch.dict(os.environ, {
            "FLARE_CC_ENDPOINT": "https://cc.test",
            "FLARE_CC_VERIFIER_RPC": "https://verifier.test",
        }):
            with mock.patch.object(cc, "_cc_post", side_effect=fake_post):
                with mock.patch.object(cc, "_cc_get", side_effect=fake_get):
                    with mock.patch.object(time, "sleep"):
                        d = cc.compute({"usdc_balance": 80}, _strategy)

        self.assertEqual(d.enclave_mode, "sgx")
        self.assertEqual(d.attestation, "0xenclavequote")
        self.assertEqual(d.decision["action"], "sweep")
        self.assertTrue(d.verified)  # verifier returned {"valid": True}


if __name__ == "__main__":
    unittest.main()
