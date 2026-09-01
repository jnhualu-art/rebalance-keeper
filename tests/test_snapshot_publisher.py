"""
Unit tests for the snapshot publisher — the seam between the Python agent and
the x402 gateway.

These cover the parts that decide what a paying consumer receives: how an
evaluation is shaped into a document, how an action result is summarised
without depending on any particular wallet backend, and the guard that stops a
misconfigured wallet from being published as a false emergency.
"""

import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import snapshot_publisher
from src.arc_position import ArcRebalanceDecision


def make_position(**overrides):
    position = {
        "address": "0x57047A430c4cfe335674e6bAD81b4D5F68ff505c",
        "usdc_balance": 74.998958,
        "native_usdc_balance": 1.5,
        "floor_usdc": 50.0,
        "treasury_health": 1.499979,
        "block_number": 59887793,
        "chain_id": 5042002,
    }
    position.update(overrides)
    return position


def make_decision(**overrides):
    decision = ArcRebalanceDecision(
        action="none", zone="WARNING", amount_usdc=0.0, reason="Treasury healthy"
    )
    for key, value in overrides.items():
        setattr(decision, key, value)
    return decision


class TestBuildSnapshot(unittest.TestCase):
    def test_shapes_one_evaluation_into_the_published_document(self):
        snapshot = snapshot_publisher.build_snapshot(make_position(), make_decision())

        self.assertEqual(snapshot["schema"], "arckeeper-treasury-snapshot/2")
        self.assertEqual(snapshot["wallet"], "0x57047A430c4cfe335674e6bAD81b4D5F68ff505c")
        self.assertEqual(snapshot["block_number"], 59887793)
        self.assertEqual(snapshot["chain"]["id"], 5042002)
        self.assertEqual(snapshot["treasury"]["usdc_balance"], 74.998958)
        self.assertEqual(snapshot["decision"]["zone"], "WARNING")
        self.assertIsNone(snapshot["last_action"])
        self.assertTrue(snapshot["generated_at"].endswith("Z"))

    def test_band_comes_from_config_not_from_the_position(self):
        # floor_usdc is passed into get_position, so trusting the position's
        # copy would mean trusting whatever the caller happened to ask for.
        snapshot = snapshot_publisher.build_snapshot(
            make_position(floor_usdc=999.0), make_decision()
        )
        self.assertEqual(snapshot["treasury"]["floor_usdc"], 50.0)

    def test_infinite_health_becomes_null_so_it_survives_json(self):
        # A zero floor means "no floor configured", which is not an emergency.
        snapshot = snapshot_publisher.build_snapshot(
            make_position(treasury_health=float("inf")), make_decision()
        )
        self.assertIsNone(snapshot["treasury"]["health"])
        json.dumps(snapshot)  # must not raise

    def test_missing_optional_fields_do_not_crash_the_build(self):
        position = {"address": "0xabc", "usdc_balance": 1.0, "treasury_health": 1.0}
        snapshot = snapshot_publisher.build_snapshot(position, make_decision())
        self.assertIsNone(snapshot["block_number"])
        self.assertEqual(snapshot["treasury"]["native_usdc_balance"], 0.0)


class TestExtractLastAction(unittest.TestCase):
    def test_no_action_means_no_summary(self):
        self.assertIsNone(snapshot_publisher.extract_last_action(None, make_decision()))
        self.assertIsNone(snapshot_publisher.extract_last_action({}, make_decision()))

    def test_a_successful_transfer_keeps_its_transaction_hash(self):
        action = snapshot_publisher.extract_last_action(
            {"tx_hash": "0xdeadbeef"}, make_decision(action="sweep", amount_usdc=2.5)
        )
        self.assertEqual(action["type"], "sweep")
        self.assertEqual(action["tx_hash"], "0xdeadbeef")
        self.assertEqual(action["status"], "success")
        self.assertFalse(action["dry_run"])

    def test_backend_shape_changes_do_not_break_the_publisher(self):
        # Backends disagree on the key; losing the hash is fine, crashing is not.
        for key in ("txHash", "transaction_hash", "hash"):
            action = snapshot_publisher.extract_last_action(
                {key: "0xfeed"}, make_decision(action="topup")
            )
            self.assertEqual(action["tx_hash"], "0xfeed")

    def test_an_action_with_no_hash_is_unknown_not_success(self):
        action = snapshot_publisher.extract_last_action(
            {"something": "else"}, make_decision(action="topup")
        )
        self.assertEqual(action["status"], "unknown")
        self.assertIsNone(action["tx_hash"])

    def test_a_dry_run_is_labelled_as_one(self):
        action = snapshot_publisher.extract_last_action(
            {"tx_hash": "0x1", "dry_run": True}, make_decision(action="sweep")
        )
        self.assertEqual(action["status"], "dry_run")
        self.assertTrue(action["dry_run"])

    def test_a_failed_action_is_reported_not_swallowed(self):
        action = snapshot_publisher.extract_last_action(
            {"error": "reserve wallet not set"}, make_decision(action="topup")
        )
        self.assertEqual(action["status"], "error")
        self.assertIn("reserve wallet not set", action["error"])


class TestSnapshotFromResult(unittest.TestCase):
    def test_reuses_the_cycle_the_agent_already_ran(self):
        result = {
            "position": make_position(),
            "decision": make_decision(action="sweep", amount_usdc=2.5, zone="OVER"),
            "action": {"tx_hash": "0xabc", "status": "success"},
        }
        snapshot = snapshot_publisher.snapshot_from_result(result)

        self.assertEqual(snapshot["decision"]["action"], "sweep")
        self.assertEqual(snapshot["last_action"]["tx_hash"], "0xabc")
        self.assertEqual(snapshot["treasury"]["usdc_balance"], 74.998958)

    def test_a_result_whose_action_failed_still_publishes_a_valid_reading(self):
        # The transfer failed, but the position is still real and still sellable.
        result = {
            "position": make_position(),
            "decision": make_decision(action="topup", amount_usdc=10.0, zone="CRITICAL"),
            "error": "ARC_RESERVE_ADDRESS not set",
        }
        snapshot = snapshot_publisher.snapshot_from_result(result)
        self.assertEqual(snapshot["decision"]["zone"], "CRITICAL")
        self.assertIsNone(snapshot["last_action"])


class TestResolveWallet(unittest.TestCase):
    def test_an_explicit_wallet_wins(self):
        with patch.dict(os.environ, {"ARC_WALLET_ADDRESS": ""}, clear=False):
            self.assertEqual(snapshot_publisher.resolve_wallet("0xgiven"), "0xgiven")

    def test_an_unset_arc_wallet_is_an_error_not_a_fallback(self):
        # Falling back to the Sepolia WALLET_ADDRESS would read as an empty
        # treasury on Arc and be sold as a false CRITICAL.
        with patch.dict(os.environ, {"ARC_WALLET_ADDRESS": ""}, clear=False):
            with self.assertRaises(ValueError) as ctx:
                snapshot_publisher.resolve_wallet()
        self.assertIn("ARC_WALLET_ADDRESS", str(ctx.exception))

    def test_a_configured_wallet_is_returned(self):
        with patch.dict(os.environ, {"ARC_WALLET_ADDRESS": "0xarc"}, clear=False):
            self.assertEqual(snapshot_publisher.resolve_wallet(), "0xarc")


class TestPublish(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.path = os.path.join(self.tmpdir, "treasury-snapshot.json")

    def test_writes_valid_utf8_json_that_reads_back_identically(self):
        snapshot = snapshot_publisher.build_snapshot(
            make_position(),
            make_decision(reason="Treasury healthy — dépassement du plafond"),
        )
        snapshot_publisher.publish(self.path, snapshot)

        with open(self.path, encoding="utf-8") as handle:
            loaded = json.load(handle)
        self.assertEqual(loaded, snapshot)
        self.assertEqual(loaded["decision"]["reason"], snapshot["decision"]["reason"])

    def test_leaves_no_temporary_file_behind(self):
        snapshot_publisher.publish(self.path, snapshot_publisher.build_snapshot(
            make_position(), make_decision()
        ))
        leftovers = [n for n in os.listdir(self.tmpdir) if n.startswith(".snapshot-")]
        self.assertEqual(leftovers, [])

    def test_overwrites_a_previous_snapshot_cleanly(self):
        snapshot_publisher.publish(self.path, snapshot_publisher.build_snapshot(
            make_position(usdc_balance=10.0), make_decision()
        ))
        snapshot_publisher.publish(self.path, snapshot_publisher.build_snapshot(
            make_position(usdc_balance=20.0), make_decision()
        ))

        with open(self.path, encoding="utf-8") as handle:
            loaded = json.load(handle)
        self.assertEqual(loaded["treasury"]["usdc_balance"], 20.0)

    def test_creates_the_directory_when_it_is_missing(self):
        nested = os.path.join(self.tmpdir, "a", "b", "snapshot.json")
        snapshot_publisher.publish(nested, snapshot_publisher.build_snapshot(
            make_position(), make_decision()
        ))
        self.assertTrue(os.path.exists(nested))


if __name__ == "__main__":
    unittest.main()
