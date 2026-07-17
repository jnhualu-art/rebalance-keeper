"""
Unit tests for AuditLogger: JSONL format, read, summary.
"""

import json
import os
import tempfile
import unittest
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.audit import AuditLogger


class TestAuditLoggerWrite(unittest.TestCase):
    """Tests for AuditLogger write operations."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmpdir, "test_audit.jsonl")
        self.audit = AuditLogger(self.log_path)

    def tearDown(self):
        if os.path.exists(self.log_path):
            os.remove(self.log_path)
        os.rmdir(self.tmpdir)

    def test_log_creates_file(self):
        """log() should create the log file."""
        self.audit.log("test", "trigger", "decision")
        self.assertTrue(os.path.exists(self.log_path))

    def test_log_returns_entry(self):
        """log() should return the entry dict."""
        entry = self.audit.log("test", "trigger", "decision")
        self.assertEqual(entry["event_type"], "test")
        self.assertEqual(entry["trigger"], "trigger")
        self.assertEqual(entry["decision"], "decision")
        self.assertIn("timestamp", entry)

    def test_log_appends(self):
        """Multiple log() calls should append to the file."""
        self.audit.log("monitor", "hf=1.5", "no_action")
        self.audit.log("trigger", "hf=1.2", "repay 5")
        entries = self.audit.read_all()
        self.assertEqual(len(entries), 2)

    def test_log_monitor_format(self):
        """log_monitor() should create proper monitor entry."""
        self.audit.log_monitor("1.5000", "1000", "500")
        entries = self.audit.read_all()
        self.assertEqual(len(entries), 1)
        entry = entries[0]
        self.assertEqual(entry["event_type"], "monitor")
        self.assertEqual(entry["trigger"], "health_factor=1.5000")
        self.assertEqual(entry["decision"], "no_action")
        self.assertEqual(entry["extra"]["total_collateral_base"], "1000")
        self.assertEqual(entry["extra"]["total_debt_base"], "500")

    def test_log_trigger_format(self):
        """log_trigger() should create proper trigger entry."""
        self.audit.log_trigger(
            health_factor="1.0500",
            action="repay 5.0",
            params={"asset": "0xabc", "idempotency_key": "rbk_123"},
            tx_hash="0xdef456",
            gas_used="120000",
            status="success",
            explorer_link="https://sepolia.etherscan.io/tx/0xdef456",
        )
        entries = self.audit.read_all()
        self.assertEqual(len(entries), 1)
        entry = entries[0]
        self.assertEqual(entry["event_type"], "trigger")
        self.assertEqual(entry["decision"], "repay 5.0")
        self.assertEqual(entry["execution"]["tx_hash"], "0xdef456")
        self.assertEqual(entry["execution"]["gas_used"], "120000")
        self.assertEqual(entry["execution"]["status"], "success")
        self.assertEqual(entry["execution"]["params"]["asset"], "0xabc")

    def test_jsonl_format(self):
        """Each line should be valid JSON."""
        self.audit.log_monitor("1.5", "100", "50")
        self.audit.log_trigger("1.2", "repay", {}, tx_hash="0x123")
        with open(self.log_path, "r") as f:
            for line in f:
                line = line.strip()
                if line:
                    entry = json.loads(line)  # should not raise
                    self.assertIn("timestamp", entry)
                    self.assertIn("event_type", entry)


class TestAuditLoggerRead(unittest.TestCase):
    """Tests for AuditLogger read operations."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmpdir, "test_audit.jsonl")
        self.audit = AuditLogger(self.log_path)

    def tearDown(self):
        if os.path.exists(self.log_path):
            os.remove(self.log_path)
        os.rmdir(self.tmpdir)

    def test_read_empty(self):
        """read_all() on non-existent file should return empty list."""
        audit = AuditLogger(os.path.join(self.tmpdir, "nonexistent.jsonl"))
        self.assertEqual(audit.read_all(), [])

    def test_read_all(self):
        """read_all() should return all entries."""
        for i in range(5):
            self.audit.log_monitor(f"1.{i}00", "100", "50")
        entries = self.audit.read_all()
        self.assertEqual(len(entries), 5)

    def test_read_skips_invalid_json(self):
        """read_all() should skip invalid JSON lines."""
        # Write valid entry
        self.audit.log_monitor("1.5", "100", "50")
        # Write invalid JSON
        with open(self.log_path, "a") as f:
            f.write("{invalid json}\n")
        # Write another valid entry
        self.audit.log_monitor("1.4", "100", "50")

        entries = self.audit.read_all()
        self.assertEqual(len(entries), 2)  # only valid entries


class TestAuditLoggerSummary(unittest.TestCase):
    """Tests for AuditLogger.summary()."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmpdir, "test_audit.jsonl")
        self.audit = AuditLogger(self.log_path)

    def tearDown(self):
        if os.path.exists(self.log_path):
            os.remove(self.log_path)
        os.rmdir(self.tmpdir)

    def test_empty_summary(self):
        """summary() on empty log should return 'No audit entries yet.'"""
        audit = AuditLogger(os.path.join(self.tmpdir, "empty.jsonl"))
        self.assertEqual(audit.summary(), "No audit entries yet.")

    def test_summary_counts(self):
        """summary() should correctly count monitors, triggers, errors."""
        self.audit.log_monitor("1.5", "100", "50")  # monitor
        self.audit.log_monitor("1.4", "100", "50")  # monitor
        self.audit.log_trigger("1.2", "repay 5", {}, tx_hash="0x123", status="success")  # trigger
        self.audit.log_trigger("1.1", "repay 10", {}, status="error", error="timeout")  # trigger + error

        summary = self.audit.summary()
        self.assertIn("Monitor checks: 2", summary)
        self.assertIn("Rebalance triggers: 2", summary)
        self.assertIn("Errors: 1", summary)

    def test_summary_shows_recent_triggers(self):
        """summary() should show recent trigger details."""
        self.audit.log_trigger(
            "1.05", "repay 5.0", {},
            tx_hash="0xabc123",
            status="success",
        )
        summary = self.audit.summary()
        self.assertIn("0xabc123", summary)
        self.assertIn("repay 5.0", summary)


if __name__ == "__main__":
    unittest.main()
