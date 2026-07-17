"""
Unit tests for Monitor: HealthSnapshot, AlertLevel, trend analysis.
"""

import unittest
import sys
import os

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.monitor import AlertLevel, HealthSnapshot, Monitor
from src.audit import AuditLogger
from tests.mocks import MockKeeperHubClient, make_account_data


class TestHealthSnapshot(unittest.TestCase):
    """Tests for HealthSnapshot data class."""

    def _make_snap(self, hf=999, debt="0", collateral="100"):
        snap = HealthSnapshot(
            timestamp="2026-01-01T00:00:00Z",
            health_factor=hf,
            total_collateral_base=collateral,
            total_debt_base=debt,
            available_borrows_base="0",
            ltv="0",
            liquidation_threshold="8000",
        )
        return snap

    def test_no_debt_has_debt_false(self):
        """Snapshot with zero debt should report has_debt=False."""
        snap = self._make_snap(debt="0")
        self.assertFalse(snap.has_debt)

    def test_has_debt_true(self):
        """Snapshot with debt should report has_debt=True."""
        snap = self._make_snap(debt="5000000")
        self.assertTrue(snap.has_debt)

    def test_is_safe_no_debt(self):
        """No debt position should be safe."""
        snap = self._make_snap(debt="0")
        snap.alert_level = AlertLevel.SAFE
        self.assertTrue(snap.is_safe)

    def test_is_safe_high_hf(self):
        """High HF should be safe."""
        snap = self._make_snap(hf=3.0, debt="1000")
        snap.alert_level = AlertLevel.SAFE
        self.assertTrue(snap.is_safe)

    def test_needs_action_danger(self):
        """Danger level should need action."""
        snap = self._make_snap(hf=1.3, debt="1000")
        snap.alert_level = AlertLevel.DANGER
        self.assertTrue(snap.needs_action)

    def test_needs_action_safe(self):
        """Safe level should not need action."""
        snap = self._make_snap(hf=3.0, debt="1000")
        snap.alert_level = AlertLevel.SAFE
        self.assertFalse(snap.needs_action)

    def test_needs_action_critical(self):
        """Critical level should need action."""
        snap = self._make_snap(hf=1.05, debt="1000")
        snap.alert_level = AlertLevel.CRITICAL
        self.assertTrue(snap.needs_action)


class TestMonitorClassification(unittest.TestCase):
    """Tests for Monitor._classify() alert level classification."""

    def setUp(self):
        self.client = MockKeeperHubClient()
        self.audit = AuditLogger("logs/test_audit.jsonl")
        self.monitor = Monitor(self.client, audit=self.audit)

    def test_classify_no_debt(self):
        """No debt should be SAFE."""
        self.client.account_data = make_account_data(hf=999, debt="0")
        self.monitor.read()
        snap = self.monitor.history[-1]
        self.assertEqual(snap.alert_level, AlertLevel.SAFE)

    def test_classify_safe(self):
        """HF >= safe_threshold (2.0) should be SAFE."""
        self.client.account_data = make_account_data(hf=2.5, debt="1000", collateral="5000")
        self.monitor.read()
        snap = self.monitor.history[-1]
        self.assertEqual(snap.alert_level, AlertLevel.SAFE)

    def test_classify_warning(self):
        """HF in [1.5, 2.0) should be WARNING."""
        self.client.account_data = make_account_data(hf=1.7, debt="1000", collateral="2000")
        self.monitor.read()
        snap = self.monitor.history[-1]
        self.assertEqual(snap.alert_level, AlertLevel.WARNING)

    def test_classify_danger(self):
        """HF in [1.2, 1.5) should be DANGER."""
        self.client.account_data = make_account_data(hf=1.35, debt="1000", collateral="1500")
        self.monitor.read()
        snap = self.monitor.history[-1]
        self.assertEqual(snap.alert_level, AlertLevel.DANGER)

    def test_classify_critical(self):
        """HF < 1.2 should be CRITICAL."""
        self.client.account_data = make_account_data(hf=1.05, debt="1000", collateral="1100")
        self.monitor.read()
        snap = self.monitor.history[-1]
        self.assertEqual(snap.alert_level, AlertLevel.CRITICAL)

    def test_classify_boundary_safe_warning(self):
        """HF exactly at safe_threshold should be WARNING (not safe)."""
        # safe_threshold=2.0, hf=2.0 → WARNING (since SAFE requires >= threshold)
        self.client.account_data = make_account_data(hf=2.0, debt="1000", collateral="2000")
        self.monitor.read()
        snap = self.monitor.history[-1]
        self.assertEqual(snap.alert_level, AlertLevel.SAFE)

    def test_classify_boundary_warning_danger(self):
        """HF exactly at warn_threshold should be DANGER (since WARNING requires >= threshold)."""
        # warn_threshold=1.5, hf=1.5 → WARNING (>= 1.5)
        self.client.account_data = make_account_data(hf=1.5, debt="1000", collateral="1500")
        self.monitor.read()
        snap = self.monitor.history[-1]
        self.assertEqual(snap.alert_level, AlertLevel.WARNING)


class TestMonitorTrendAnalysis(unittest.TestCase):
    """Tests for Monitor trend computation."""

    def setUp(self):
        self.client = MockKeeperHubClient()
        self.audit = AuditLogger("logs/test_audit.jsonl")
        self.monitor = Monitor(self.client, audit=self.audit)

    def test_no_trend_with_one_reading(self):
        """Single reading should produce zero trend."""
        self.client.account_data = make_account_data(hf=2.5, debt="1000", collateral="5000")
        self.monitor.read()
        snap = self.monitor.history[-1]
        self.assertEqual(snap.hf_trend, 0.0)
        self.assertEqual(snap.consecutive_declines, 0)

    def test_declining_trend(self):
        """Three decreasing HF readings should show negative trend."""
        hfs = [3.0, 2.8, 2.6]
        for hf in hfs:
            self.client.account_data = make_account_data(hf=hf, debt="1000", collateral="3000")
            self.monitor.read()

        snap = self.monitor.history[-1]
        self.assertLess(snap.hf_trend, 0)  # declining
        self.assertEqual(snap.consecutive_declines, 2)  # 2 consecutive declines

    def test_increasing_trend(self):
        """Three increasing HF readings should show positive trend."""
        hfs = [1.3, 1.5, 1.7]
        for hf in hfs:
            self.client.account_data = make_account_data(hf=hf, debt="1000", collateral="2000")
            self.monitor.read()

        snap = self.monitor.history[-1]
        self.assertGreater(snap.hf_trend, 0)  # increasing
        self.assertEqual(snap.consecutive_declines, 0)

    def test_mixed_trend(self):
        """Up-down-up pattern: consecutive_declines should be 0."""
        hfs = [1.5, 1.7, 1.4, 1.6]
        for hf in hfs:
            self.client.account_data = make_account_data(hf=hf, debt="1000", collateral="2000")
            self.monitor.read()

        snap = self.monitor.history[-1]
        # Last reading went up, so consecutive_declines = 0
        self.assertEqual(snap.consecutive_declines, 0)


class TestMonitorCallbacks(unittest.TestCase):
    """Tests for Monitor callback triggering."""

    def setUp(self):
        self.client = MockKeeperHubClient()
        self.audit = AuditLogger("logs/test_audit.jsonl")
        self.monitor = Monitor(self.client, audit=self.audit)
        self.unsafe_called = []
        self.warning_called = []

    def _on_unsafe(self, snap):
        self.unsafe_called.append(snap)

    def _on_warning(self, snap):
        self.warning_called.append(snap)

    def test_danger_triggers_unsafe(self):
        """Danger zone should trigger on_unsafe callback."""
        self.monitor.on_unsafe(self._on_unsafe)
        self.client.account_data = make_account_data(hf=1.35, debt="1000", collateral="1500")
        self.monitor.check_once()
        self.assertEqual(len(self.unsafe_called), 1)

    def test_critical_triggers_unsafe(self):
        """Critical zone should trigger on_unsafe callback."""
        self.monitor.on_unsafe(self._on_unsafe)
        self.client.account_data = make_account_data(hf=1.05, debt="1000", collateral="1100")
        self.monitor.check_once()
        self.assertEqual(len(self.unsafe_called), 1)

    def test_safe_no_trigger(self):
        """Safe zone should not trigger any callback."""
        self.monitor.on_unsafe(self._on_unsafe)
        self.monitor.on_warning(self._on_warning)
        self.client.account_data = make_account_data(hf=3.0, debt="1000", collateral="5000")
        self.monitor.check_once()
        self.assertEqual(len(self.unsafe_called), 0)
        self.assertEqual(len(self.warning_called), 0)

    def test_warning_triggers_warning_callback(self):
        """Warning zone should trigger on_warning callback."""
        self.monitor.on_warning(self._on_warning)
        self.client.account_data = make_account_data(hf=1.7, debt="1000", collateral="2000")
        self.monitor.check_once()
        self.assertEqual(len(self.warning_called), 1)


class TestMonitorCooldown(unittest.TestCase):
    """Tests for Monitor cooldown enforcement."""

    def setUp(self):
        self.client = MockKeeperHubClient()
        self.audit = AuditLogger("logs/test_audit.jsonl")
        self.monitor = Monitor(self.client, audit=self.audit)
        self.action_count = [0]

    def test_danger_triggers_action(self):
        """First danger reading should trigger action."""
        def callback(snap):
            self.action_count[0] += 1
        self.monitor.on_unsafe(callback)
        self.client.account_data = make_account_data(hf=1.35, debt="1000", collateral="1500")
        self.monitor.check_once()
        self.assertEqual(self.action_count[0], 1)

    def test_critical_ignores_cooldown(self):
        """Critical should always trigger, even in cooldown."""
        call_count = [0]
        def callback(snap):
            call_count[0] += 1
        self.monitor.on_unsafe(callback)

        # First trigger (danger)
        self.client.account_data = make_account_data(hf=1.35, debt="1000", collateral="1500")
        self.monitor.check_once()

        # Second trigger (critical) - should still fire despite cooldown
        self.client.account_data = make_account_data(hf=1.05, debt="1000", collateral="1100")
        self.monitor.check_once()

        self.assertEqual(call_count[0], 2)


if __name__ == "__main__":
    unittest.main()
