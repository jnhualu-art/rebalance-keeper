#!/usr/bin/env python3
"""
RebalanceKeeper — DeFi position rebalancing agent.

Monitors an Aave V3 position's health factor and automatically triggers
repay / supply actions via KeeperHub MCP when it drops below a threshold.

Usage:
  python -m src.main --once         # Single check
  python -m src.main --monitor      # Continuous monitoring (default)
  python -m src.main --status       # Show current position status
  python -m src.main --setup        # Set up a test position (supply + borrow)
  python -m src.main --audit        # Show audit log summary
  python -m src.main --supply 0.01  # Manual supply
  python -m src.main --borrow 10    # Manual borrow
  python -m src.main --repay 5      # Manual repay
"""

import argparse
import json
import sys
import os

# Ensure .env is loaded if python-dotenv is available
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Ensure project root is on path when run as script
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import config
from src.audit import AuditLogger
from src.keeperhub_client import KeeperHubClient, MCPError
from src.monitor import Monitor
from src.rebalancer import Rebalancer


def get_client() -> KeeperHubClient:
    """Create a KeeperHub client from environment config."""
    api_key = os.getenv("KEEPERHUB_API_KEY", "")
    if not api_key:
        print("ERROR: Set KEEPERHUB_API_KEY in .env or environment.")
        sys.exit(1)
    return KeeperHubClient(api_key=api_key)


def cmd_once(args):
    """Run a single health check."""
    client = get_client()
    audit = AuditLogger(config.REBALANCE_CONFIG.audit_log_path)
    rebalancer = Rebalancer(client, audit=audit)
    monitor = Monitor(client, audit=audit)
    monitor.on_unsafe(rebalancer.handle_unsafe)
    monitor.check_once()


def cmd_monitor(args):
    """Run continuous monitoring loop."""
    client = get_client()
    audit = AuditLogger(config.REBALANCE_CONFIG.audit_log_path)
    rebalancer = Rebalancer(client, audit=audit)
    monitor = Monitor(client, audit=audit)
    monitor.on_unsafe(rebalancer.handle_unsafe)
    monitor.run()


def cmd_status(args):
    """Show current Aave V3 position status."""
    client = get_client()
    data = client.get_user_account_data(config.WALLET_ADDRESS)

    hf_raw = float(data.get("healthFactor", "0"))
    hf = hf_raw if hf_raw < 1e30 else float("inf")

    print(f"\n{'='*60}")
    print(f"  RebalanceKeeper — Position Status")
    print(f"{'='*60}")
    print(f"  Wallet:    {config.WALLET_ADDRESS}")
    print(f"  Chain:     {config.CHAIN_NAME} (id={config.CHAIN_ID})")
    print(f"  Pool:      {config.AAVE_POOL}")
    print(f"{'─'*60}")
    print(f"  Health Factor:        {hf:.4f}" if hf != float("inf") else "  Health Factor:        ∞ (no debt)")
    print(f"  Total Collateral:     {data.get('totalCollateralBase', '0')} (base units)")
    print(f"  Total Debt:           {data.get('totalDebtBase', '0')} (base units)")
    print(f"  Available Borrows:    {data.get('availableBorrowsBase', '0')} (base units)")
    print(f"  LTV:                  {data.get('ltv', '0')}")
    print(f"  Liquidation Threshold:{data.get('currentLiquidationThreshold', '0')}")
    print(f"{'─'*60}")

    if hf != float("inf"):
        threshold = config.REBALANCE_CONFIG.health_factor_threshold
        status = "✓ SAFE" if hf >= threshold else "⚠ UNSAFE — rebalance needed!"
        print(f"  Status: {status} (threshold: {threshold})")
    else:
        print(f"  Status: ✓ No debt position")
    print()


def cmd_setup(args):
    """Set up a test Aave V3 position: supply collateral + borrow."""
    client = get_client()
    wallet = config.WALLET_ADDRESS

    print(f"\nSetting up test position for {wallet}")
    print(f"  Chain: {config.CHAIN_NAME}")
    print(f"  Supply: {args.supply_amount} {config.COLLATERAL_TOKEN} as collateral")
    print(f"  Borrow: {args.borrow_amount} {config.DEBT_TOKEN} against collateral")
    print()

    # Step 1: Supply collateral
    print("Step 1: Supplying collateral...")
    try:
        result = client.supply(
            asset=config.token_addr(config.COLLATERAL_TOKEN),
            amount=args.supply_amount,
        )
        tx = result.get("transactionHash", "N/A")
        print(f"  ✓ Supply TX: {tx}")
        if result.get("transactionLink"):
            print(f"  ✓ Explorer: {result['transactionLink']}")
    except MCPError as e:
        print(f"  ✗ Supply failed: {e}")
        return

    # Step 2: Borrow debt token
    print("\nStep 2: Borrowing...")
    try:
        result = client.borrow(
            asset=config.token_addr(config.DEBT_TOKEN),
            amount=args.borrow_amount,
            interest_rate_mode=config.REBALANCE_CONFIG.interest_rate_mode,
        )
        tx = result.get("transactionHash", "N/A")
        print(f"  ✓ Borrow TX: {tx}")
        if result.get("transactionLink"):
            print(f"  ✓ Explorer: {result['transactionLink']}")
    except MCPError as e:
        print(f"  ✗ Borrow failed: {e}")
        return

    print("\n✓ Test position created! Run --status to verify.")


def cmd_audit(args):
    """Show audit log summary."""
    audit = AuditLogger(config.REBALANCE_CONFIG.audit_log_path)
    print(audit.summary())


def cmd_supply(args):
    """Manual supply."""
    client = get_client()
    print(f"Supplying {args.amount} {config.COLLATERAL_TOKEN}...")
    result = client.supply(
        asset=config.token_addr(config.COLLATERAL_TOKEN),
        amount=args.amount,
    )
    print(f"  TX: {result.get('transactionHash', 'N/A')}")


def cmd_borrow(args):
    """Manual borrow."""
    client = get_client()
    print(f"Borrowing {args.amount} {config.DEBT_TOKEN}...")
    result = client.borrow(
        asset=config.token_addr(config.DEBT_TOKEN),
        amount=args.amount,
        interest_rate_mode=config.REBALANCE_CONFIG.interest_rate_mode,
    )
    print(f"  TX: {result.get('transactionHash', 'N/A')}")


def cmd_repay(args):
    """Manual repay."""
    client = get_client()
    print(f"Repaying {args.amount} {config.DEBT_TOKEN}...")
    result = client.repay(
        asset=config.token_addr(config.DEBT_TOKEN),
        amount=args.amount,
        interest_rate_mode=config.REBALANCE_CONFIG.interest_rate_mode,
    )
    print(f"  TX: {result.get('transactionHash', 'N/A')}")


def main():
    parser = argparse.ArgumentParser(
        description="RebalanceKeeper — Aave V3 auto-rebalancing agent via KeeperHub",
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("once", help="Run a single health check")
    sub.add_parser("monitor", help="Run continuous monitoring (default)")
    sub.add_parser("status", help="Show current Aave V3 position")
    sub.add_parser("audit", help="Show audit log summary")

    setup_p = sub.add_parser("setup", help="Set up a test position")
    setup_p.add_argument("--supply-amount", default="0.01", help="Amount of WETH to supply")
    setup_p.add_argument("--borrow-amount", default="10", help="Amount of USDC to borrow")

    supply_p = sub.add_parser("supply", help="Manual supply")
    supply_p.add_argument("amount", help="Amount to supply")

    borrow_p = sub.add_parser("borrow", help="Manual borrow")
    borrow_p.add_argument("amount", help="Amount to borrow")

    repay_p = sub.add_parser("repay", help="Manual repay")
    repay_p.add_argument("amount", help="Amount to repay")

    args = parser.parse_args()

    if args.command is None:
        # Default: monitor
        args.command = "monitor"

    commands = {
        "once": cmd_once,
        "monitor": cmd_monitor,
        "status": cmd_status,
        "setup": cmd_setup,
        "audit": cmd_audit,
        "supply": cmd_supply,
        "borrow": cmd_borrow,
        "repay": cmd_repay,
    }

    if args.command in commands:
        commands[args.command](args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
