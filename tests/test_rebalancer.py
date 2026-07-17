"""
Unit tests for Rebalancer: decision engine, HF impact estimation.
"""

import unittest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.rebalancer import RebalanceDecision, Rebalancer
from src.monitor import AlertLevel, HealthSnapshot
from src.audit import AuditLogger
from src import config
from tests.mocks import MockKeeperHubClient, make_account_data


def make_snap(
    hf=999,
    debt="0",
    collateral="100",
    lt="8000",
    trend=0.0,
    declines=0,
    level=AlertLevel.SAFE,
):
    """Create a HealthSnapshot for testing."""
    return HealthSnapshot(
        timestamp="2026-01-01T00:00:00Z",
        health_factor=hf,
        total_collateral_base=collateral,
        total_debt_base=debt,
        available_borrows_base="0",
        ltv="0",
        liquidation_threshold=lt,
        hf_trend=trend,
        hf_rate_pct=0.0,
        consecutive_declines=declines,
        alert_level=level,
    )


class TestRebalancerSafe(unittest.TestCase):
    """Tests for SAFE zone — no action."""

    def setUp(self):
        self.client = MockKeeperHubClient()
        self.audit = AuditLogger("logs/test_audit.jsonl")
        self.rebalancer = Rebalancer(self.client, audit=self.audit)

    def test_safe_no_action(self):
        """SAFE zone should produce no_action decision."""
        snap = make_snap(hf=3.0, debt="1000", level=AlertLevel.SAFE)
        decision = self.rebalancer.evaluate(snap)
        self.assertEqual(decision.action, "no_action")
        self.assertEqual(decision.priority, 0)

    def test_no_debt_no_action(self):
        """No debt position should produce no_action."""
        snap = make_snap(hf=float("inf"), debt="0", level=AlertLevel.SAFE)
        decision = self.rebalancer.evaluate(snap)
        self.assertEqual(decision.action, "no_action")


class TestRebalancerCritical(unittest.TestCase):
    """Tests for CRITICAL zone — emergency repay 50%."""

    def setUp(self):
        self.client = MockKeeperHubClient()
        self.audit = AuditLogger("logs/test_audit.jsonl")
        self.rebalancer = Rebalancer(self.client, audit=self.audit)

    def test_critical_repay_50_percent(self):
        """CRITICAL zone should repay 50% of debt."""
        # debt = 10 USDC = 10 * 10^6 = 10000000 base units
        snap = make_snap(
            hf=1.05,
            debt="10000000",
            collateral="11000000",
            level=AlertLevel.CRITICAL,
        )
        decision = self.rebalancer.evaluate(snap)
        self.assertEqual(decision.action, "repay")
        self.assertEqual(decision.priority, 100)
        self.assertEqual(decision.alert_level, "CRITICAL")

        # 50% of 10 USDC = 5 USDC
        amount = float(decision.amount)
        self.assertAlmostEqual(amount, 5.0, places=4)

    def test_critical_executes_repay(self):
        """CRITICAL should execute repay via client."""
        snap = make_snap(
            hf=1.05,
            debt="10000000",
            collateral="11000000",
            level=AlertLevel.CRITICAL,
        )
        decision = self.rebalancer.evaluate(snap)
        result = self.rebalancer.execute(decision, snap)

        # Check client was called with repay
        repay_calls = [c for c in self.client.calls if c[0] == "repay"]
        self.assertEqual(len(repay_calls), 1)
        self.assertTrue(result.get("success"))


class TestRebalancerDanger(unittest.TestCase):
    """Tests for DANGER zone — repay 25%."""

    def setUp(self):
        self.client = MockKeeperHubClient()
        self.audit = AuditLogger("logs/test_audit.jsonl")
        self.rebalancer = Rebalancer(self.client, audit=self.audit)

    def test_danger_repay_25_percent(self):
        """DANGER zone should repay 25% of debt."""
        snap = make_snap(
            hf=1.35,
            debt="10000000",
            collateral="15000000",
            level=AlertLevel.DANGER,
        )
        decision = self.rebalancer.evaluate(snap)
        self.assertEqual(decision.action, "repay")
        self.assertEqual(decision.priority, 50)
        self.assertEqual(decision.alert_level, "DANGER")

        # 25% of 10 USDC = 2.5 USDC
        amount = float(decision.amount)
        self.assertAlmostEqual(amount, 2.5, places=4)


class TestRebalancerWarning(unittest.TestCase):
    """Tests for WARNING zone — light repay or supply."""

    def setUp(self):
        self.client = MockKeeperHubClient()
        self.audit = AuditLogger("logs/test_audit.jsonl")
        self.rebalancer = Rebalancer(self.client, audit=self.audit)

    def test_warning_with_decline_repay_10_percent(self):
        """WARNING with declining trend should repay 10%."""
        snap = make_snap(
            hf=1.7,
            debt="10000000",
            collateral="20000000",
            level=AlertLevel.WARNING,
            declines=4,  # trend_window=5, so 4 declines triggers pre-emptive
        )
        decision = self.rebalancer.evaluate(snap)
        self.assertEqual(decision.action, "repay")
        self.assertEqual(decision.priority, 20)

        # 10% of 10 USDC = 1 USDC
        amount = float(decision.amount)
        self.assertAlmostEqual(amount, 1.0, places=4)

    def test_warning_stable_supply_buffer(self):
        """WARNING without decline should supply collateral."""
        snap = make_snap(
            hf=1.7,
            debt="10000000",
            collateral="20000000",
            level=AlertLevel.WARNING,
            declines=0,
        )
        decision = self.rebalancer.evaluate(snap)
        self.assertEqual(decision.action, "supply")
        self.assertEqual(decision.priority, 10)
        self.assertEqual(decision.amount, config.REBALANCE_CONFIG.supply_boost_amount)


class TestHFImpactEstimation(unittest.TestCase):
    """Tests for HF impact estimation functions."""

    def setUp(self):
        self.client = MockKeeperHubClient()
        self.audit = AuditLogger("logs/test_audit.jsonl")
        self.rebalancer = Rebalancer(self.client, audit=self.audit)

    def test_repay_improves_hf(self):
        """Repaying debt should show positive HF impact."""
        snap = make_snap(
            hf=1.3,
            debt="10000000",
            collateral="15000000",
            lt="8000",  # 80%
            level=AlertLevel.DANGER,
        )
        impact = self.rebalancer._estimate_repay_impact(snap, 0.25)
        self.assertGreater(impact, 0)

    def test_repay_zero_debt_zero_impact(self):
        """Zero debt should show zero HF impact."""
        snap = make_snap(hf=999, debt="0", collateral="100", lt="8000")
        impact = self.rebalancer._estimate_repay_impact(snap, 0.25)
        self.assertEqual(impact, 0.0)

    def test_supply_improves_hf(self):
        """Supplying collateral should show positive HF impact."""
        snap = make_snap(
            hf=1.3,
            debt="10000000",
            collateral="15000000",
            lt="8000",
            level=AlertLevel.DANGER,
        )
        impact = self.rebalancer._estimate_supply_impact(snap)
        self.assertGreater(impact, 0)

    def test_larger_repay_bigger_impact(self):
        """Larger repay fraction should show bigger HF impact."""
        snap = make_snap(
            hf=1.3,
            debt="10000000",
            collateral="15000000",
            lt="8000",
            level=AlertLevel.DANGER,
        )
        impact_25 = self.rebalancer._estimate_repay_impact(snap, 0.25)
        impact_50 = self.rebalancer._estimate_repay_impact(snap, 0.50)
        self.assertGreater(impact_50, impact_25)


class TestRebalancerExecution(unittest.TestCase):
    """Tests for Rebalancer.execute() with mock client."""

    def setUp(self):
        self.client = MockKeeperHubClient()
        self.audit = AuditLogger("logs/test_audit.jsonl")
        self.rebalancer = Rebalancer(self.client, audit=self.audit)

    def test_execute_no_action_returns_status(self):
        """No-action decision should return {status: no_action}."""
        snap = make_snap(hf=3.0, debt="0", level=AlertLevel.SAFE)
        decision = RebalanceDecision(
            action="no_action", asset="", amount="0", reason="safe"
        )
        result = self.rebalancer.execute(decision, snap)
        self.assertEqual(result, {"status": "no_action"})

    def test_execute_repay_calls_client(self):
        """Repay decision should call client.repay."""
        snap = make_snap(hf=1.05, debt="10000000", level=AlertLevel.CRITICAL)
        decision = RebalanceDecision(
            action="repay",
            asset=config.TOKENS[config.DEBT_TOKEN]["address"],
            amount="5.0",
            reason="emergency",
            priority=100,
            alert_level="CRITICAL",
        )
        result = self.rebalancer.execute(decision, snap)
        self.assertTrue(result.get("success"))
        repay_calls = [c for c in self.client.calls if c[0] == "repay"]
        self.assertEqual(len(repay_calls), 1)

    def test_execute_supply_calls_client(self):
        """Supply decision should call client.supply."""
        snap = make_snap(hf=1.7, debt="10000000", level=AlertLevel.WARNING)
        decision = RebalanceDecision(
            action="supply",
            asset=config.TOKENS[config.COLLATERAL_TOKEN]["address"],
            amount="0.01",
            reason="buffer",
            priority=10,
        )
        result = self.rebalancer.execute(decision, snap)
        self.assertTrue(result.get("success"))
        supply_calls = [c for c in self.client.calls if c[0] == "supply"]
        self.assertEqual(len(supply_calls), 1)

    def test_execute_repay_error_logged(self):
        """Repay failure should be logged to audit."""
        self.client.raise_on_repay = True
        snap = make_snap(hf=1.05, debt="10000000", level=AlertLevel.CRITICAL)
        decision = RebalanceDecision(
            action="repay",
            asset=config.TOKENS[config.DEBT_TOKEN]["address"],
            amount="5.0",
            reason="emergency",
        )
        from src.keeperhub_client import MCPError
        with self.assertRaises(MCPError):
            self.rebalancer.execute(decision, snap)

        # Check audit log has error entry
        entries = self.audit.read_all()
        trigger_entries = [e for e in entries if e["event_type"] == "trigger"]
        self.assertTrue(any(e.get("error") for e in trigger_entries))


class TestPositionSummary(unittest.TestCase):
    """Tests for Rebalancer.get_position_summary()."""

    def setUp(self):
        self.client = MockKeeperHubClient()
        self.audit = AuditLogger("logs/test_audit.jsonl")
        self.rebalancer = Rebalancer(self.client, audit=self.audit)

    def test_summary_has_recommended_action(self):
        """Summary should include a recommended_action dict."""
        snap = make_snap(hf=3.0, debt="1000", level=AlertLevel.SAFE)
        summary = self.rebalancer.get_position_summary(snap)
        self.assertIn("recommended_action", summary)
        self.assertEqual(summary["recommended_action"]["action"], "no_action")

    def test_summary_has_trend(self):
        """Summary should include trend data."""
        snap = make_snap(hf=1.7, debt="1000", trend=-0.05, declines=3, level=AlertLevel.WARNING)
        summary = self.rebalancer.get_position_summary(snap)
        self.assertIn("trend", summary)
        self.assertEqual(summary["trend"]["consecutive_declines"], 3)

    def test_summary_alert_level(self):
        """Summary should include alert level."""
        snap = make_snap(hf=1.05, debt="1000", level=AlertLevel.CRITICAL)
        summary = self.rebalancer.get_position_summary(snap)
        self.assertEqual(summary["alert_level"], "CRITICAL")


if __name__ == "__main__":
    unittest.main()
