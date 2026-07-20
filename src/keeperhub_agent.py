"""
KeeperHubAgent — RebalanceKeeper entry point for the KeeperHub Agents Onchain hackathon.

This module exposes the "read → decide → execute" loop that proves an AI agent
can autonomously protect a DeFi position via the KeeperHub MCP execution layer.

It is intentionally thin: the heavy lifting (KeeperHubClient, Rebalancer,
Monitor, Audit) already lives in the main project. This file wraps them into a
single, demo-friendly API that is easy to run from the CLI and easy to showcase
in a DoraHacks BUIDL submission.
"""

import time
import sys
from typing import Optional

from src import config
from src.audit import AuditLogger
from src.keeperhub_client import KeeperHubClient, MCPError
from src.monitor import Monitor, AlertLevel
from src.rebalancer import Rebalancer, RebalanceDecision


class KeeperHubAgent:
    """Autonomous agent that monitors an Aave V3 position and rebalances through KeeperHub."""

    def __init__(self, client: KeeperHubClient = None, cfg: config.RebalanceConfig = None):
        self.client = client or KeeperHubClient(
            url=config.KEEPERHUB_MCP_URL,
            api_key=config.KEEPERHUB_API_KEY,
        )
        self.cfg = cfg or config.REBALANCE_CONFIG
        self.audit = AuditLogger(self.cfg.audit_log_path)
        self.rebalancer = Rebalancer(self.client, cfg=self.cfg, audit=self.audit)
        self.monitor = Monitor(self.client, audit=self.audit)
        self.monitor.on_unsafe(self.rebalancer.handle_unsafe)
        self.monitor.on_warning(self.rebalancer.handle_warning)

    def run_once(self, dry_run: bool = False) -> dict:
        """Read position once, decide, and (unless dry_run) execute via KeeperHub."""
        snap = self.monitor.read()
        decision = self.rebalancer.evaluate(snap)

        print(f"\n{'='*60}")
        print(f"  KeeperHub Agent — One Shot")
        print(f"{'='*60}")
        print(f"  HF:       {snap.health_factor:.4f}")
        print(f"  Zone:     {snap.alert_level.value}")
        print(f"  Decision: {decision.action}")
        print(f"  Reason:   {decision.reason}")
        print(f"{'='*60}")

        if dry_run or decision.action == "no_action":
            return {
                "status": "dry_run" if dry_run else "no_action",
                "health_factor": snap.health_factor,
                "decision": decision,
            }

        return self.rebalancer.execute(decision, snap)

    def watch(self, interval: int = None, dry_run: bool = False):
        """Continuous monitoring loop. Ctrl-C to stop."""
        interval = interval or self.cfg.monitor_interval
        print(f"\n⮕ KeeperHub Agent watching every {interval}s (Ctrl-C to stop) ...")
        try:
            while True:
                self.run_once(dry_run=dry_run)
                time.sleep(interval)
        except KeyboardInterrupt:
            print("\n⏹ Agent stopped.")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="KeeperHub Agents Onchain — autonomous rebalancer")
    parser.add_argument("--once", action="store_true", help="Run one evaluation")
    parser.add_argument("--watch", action="store_true", help="Run continuous monitoring")
    parser.add_argument("--dry-run", action="store_true", help="Read+decide but do NOT execute")
    parser.add_argument("--interval", type=int, default=None, help="Poll interval in seconds")
    args = parser.parse_args()

    if not args.once and not args.watch:
        args.once = True

    agent = KeeperHubAgent()
    if args.watch:
        agent.watch(interval=args.interval, dry_run=args.dry_run)
    else:
        agent.run_once(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
