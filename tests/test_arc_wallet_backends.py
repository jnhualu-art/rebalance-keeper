"""
Unit tests for ArcKeeper wallet backends (local + Circle Agent Stack).

Verifies the custody-abstraction layer without touching real chains:
  - LocalKeyBackend  (default, eth_account)
  - CircleWalletBackend (Circle Agent Stack dev-controlled wallet)
  - get_backend factory
"""

import unittest
from unittest import mock
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.arc_wallet_backends import (
    WalletBackendError,
    LocalKeyBackend,
    CircleWalletBackend,
    get_backend,
)


OP = "0x57047A430c4cfe335674e6bAD81b4D5F68ff505c"
RES = "0xeC3cD471c204c27493D9b5c5230479dEB421DD43"


class TestCircleBackend(unittest.TestCase):
    def _backend(self, **kw):
        return CircleWalletBackend(
            api_key=kw.get("api_key", "PREFIX:ID:SECRET"),
            entity_secret=kw.get("entity_secret", "entity-secret"),
            wallet_address=kw.get("wallet_address", OP),
            reserve_address=kw.get("reserve_address", RES),
        )

    def test_missing_creds_raises(self):
        with self.assertRaises(WalletBackendError):
            CircleWalletBackend(api_key="", entity_secret="", wallet_address="")

    def test_dry_run_does_not_call_api(self):
        b = self._backend()
        res = b.transfer_usdc(OP, RES, 5.0, dry_run=True)
        self.assertTrue(res["dry_run"])
        self.assertEqual(res["backend"], "circle")
        self.assertEqual(res["from"], OP)
        self.assertEqual(res["to"], RES)

    def test_unknown_source_wallet_rejected(self):
        b = self._backend()
        with self.assertRaises(WalletBackendError):
            b.transfer_usdc("0x1111111111111111111111111111111111111111", RES, 5.0)

    def test_real_transfer_polls_to_complete(self):
        b = self._backend()
        responses = [
            {"data": {"id": "tx_1"}},                       # create
            {"data": {"transaction": {"state": "PENDING"}}},  # poll 1
            {"data": {"transaction": {"state": "COMPLETE", "txHash": "0xabc"}}},  # poll 2
        ]
        with mock.patch.object(b, "_request", side_effect=responses):
            with mock.patch("time.sleep"):  # speed up the loop
                res = b.transfer_usdc(OP, RES, 5.0)
        self.assertEqual(res["tx_hash"], "0xabc")
        self.assertEqual(res["backend"], "circle")
        self.assertEqual(res["explorer"], "https://testnet.arcscan.app/tx/0xabc")

    def test_real_transfer_failed_state_raises(self):
        b = self._backend()
        responses = [
            {"data": {"id": "tx_2"}},
            {"data": {"transaction": {"state": "FAILED"}}},
        ]
        with mock.patch.object(b, "_request", side_effect=responses):
            with mock.patch("time.sleep"):
                with self.assertRaises(WalletBackendError):
                    b.transfer_usdc(OP, RES, 5.0)


class TestLocalBackend(unittest.TestCase):
    def test_dry_run(self):
        with mock.patch("src.arc_executor.ArcExecutor") as MockExec:
            inst = MockExec.return_value
            inst.transfer_usdc.return_value = {
                "dry_run": True, "from": OP, "to": RES, "amount_usdc": 5.0,
            }
            b = LocalKeyBackend()
            res = b.transfer_usdc(OP, RES, 5.0, private_key="0x" + "11" * 32)
        self.assertTrue(res["dry_run"])
        inst.transfer_usdc.assert_called_once()

    def test_missing_private_key_raises(self):
        with mock.patch("src.arc_executor.ArcExecutor") as MockExec:
            inst = MockExec.return_value
            inst.transfer_usdc.side_effect = WalletBackendError("no key")
            b = LocalKeyBackend()
            with self.assertRaises(WalletBackendError):
                b.transfer_usdc(OP, RES, 5.0, private_key=None)


class TestFactory(unittest.TestCase):
    def test_local_default(self):
        self.assertIsInstance(get_backend("local"), LocalKeyBackend)

    def test_circle_without_creds_raises(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            # ensure no Circle creds leak from the env
            os.environ.pop("CIRCLE_API_KEY", None)
            os.environ.pop("CIRCLE_ENTITY_SECRET", None)
            os.environ.pop("CIRCLE_WALLET_ADDRESS", None)
            with self.assertRaises(WalletBackendError):
                get_backend("circle")

    def test_unknown_backend_raises(self):
        with self.assertRaises(WalletBackendError):
            get_backend("bogus")


if __name__ == "__main__":
    unittest.main()
