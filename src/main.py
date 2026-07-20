#!/usr/bin/env python3
"""
RebalanceKeeper — DeFi position rebalancing agent.

Monitors a position's health factor (Aave V3 on Sepolia) or treasury balance
(Arc Testnet) and automatically triggers rebalance actions when it drops
below a threshold.

Usage:
  python -m src.main --once         # Single Aave V3 check
  python -m src.main --monitor      # Continuous Aave V3 monitoring (default)
  python -m src.main --status       # Show current Aave V3 position status
  python -m src.main --setup        # Set up a test Aave V3 position
  python -m src.main --audit        # Show audit log summary
  python -m src.main --supply 0.01  # Manual Aave V3 supply
  python -m src.main --borrow 10    # Manual Aave V3 borrow
  python -m src.main --repay 5      # Manual Aave V3 repay
  python -m src.main arc-status     # Show Arc Testnet treasury status (real on-chain)
"""

import argparse
import json
import sys
import os
import time

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
from src.arc_client import ArcClient, ArcError
from src.arc_executor import ArcExecutor, ArcExecutorError
from src.arc_rebalancer import ArcRebalancer
from src import arc_position


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
    monitor.on_warning(rebalancer.handle_warning)
    monitor.check_once()


def cmd_monitor(args):
    """Run continuous monitoring loop."""
    client = get_client()
    audit = AuditLogger(config.REBALANCE_CONFIG.audit_log_path)
    rebalancer = Rebalancer(client, audit=audit)
    monitor = Monitor(client, audit=audit)
    monitor.on_unsafe(rebalancer.handle_unsafe)
    monitor.on_warning(rebalancer.handle_warning)
    monitor.run()


def cmd_status(args):
    """Show current Aave V3 position status."""
    client = get_client()
    cfg = config.REBALANCE_CONFIG
    data = client.get_user_account_data(config.WALLET_ADDRESS)

    hf_raw = float(data.get("healthFactor", "0"))
    hf = hf_raw / 1e18 if hf_raw < 1e30 else float("inf")

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
        # Multi-level zone display
        if hf >= cfg.safe_threshold:
            zone = "SAFE"
            icon = "✓"
        elif hf >= cfg.warn_threshold:
            zone = "WARNING"
            icon = "⚠"
        elif hf >= cfg.danger_threshold:
            zone = "DANGER"
            icon = "⚡"
        else:
            zone = "CRITICAL"
            icon = "🚨"
        print(f"  Status: {icon} {zone}")
        print(f"  Zones:  SAFE≥{cfg.safe_threshold} | "
              f"WARN≥{cfg.warn_threshold} | "
              f"DANGER≥{cfg.danger_threshold} | "
              f"CRITICAL<{cfg.danger_threshold}")
    else:
        print(f"  Status: ✓ No debt position")
    print()


def cmd_summary(args):
    """Show full position summary with rebalancer recommendation."""
    client = get_client()
    audit = AuditLogger(config.REBALANCE_CONFIG.audit_log_path)
    rebalancer = Rebalancer(client, audit=audit)
    monitor = Monitor(client, audit=audit)
    snap = monitor.read()

    summary = rebalancer.get_position_summary(snap)
    print(f"\n{'='*60}")
    print(f"  Position Summary & Recommendation")
    print(f"{'='*60}")
    print(json.dumps(summary, indent=2, default=str))
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


def cmd_arc_status(args):
    """Show current Arc Testnet treasury status (real on-chain USDC read)."""
    from src import config as C

    wallet = args.address or C.ARC_WALLET_ADDRESS
    try:
        client = ArcClient()
        pos = client.get_position(wallet, floor_usdc=C.ARC_REBALANCE_CONFIG.floor_usdc)
    except ArcError as e:
        print(f"ERROR: Could not reach Arc Testnet RPC: {e}")
        print("Check your network / ARC_RPC_URL. The public RPC is "
              "https://rpc.testnet.arc.network")
        return
    _, decision = arc_position.evaluate(pos, C.ARC_REBALANCE_CONFIG)
    arc_position.print_status(pos, decision, C.ARC_REBALANCE_CONFIG)


def cmd_arc_rebalance(args):
    """Autonomous rebalance on Arc Testnet: read → decide → act.

    Modes:
      arc-rebalance                   # threshold-driven auto: top up if below floor, sweep if above ceiling
      arc-rebalance --watch           # loop: monitor + autonomously rebalance every --interval seconds
      arc-rebalance --sweep 5         # demo: push 5 USDC operational → reserve
      arc-rebalance --topup 5         # demo: pull 5 USDC reserve → operational
      arc-rebalance --dry-run         # build tx, do not broadcast
    """
    from src import config as C

    rebalancer = ArcRebalancer()
    dry_run = args.dry_run

    try:
        if args.sweep is not None:
            print(f"\n⮕ Sweeping {args.sweep} USDC operational → reserve ...")
            res = rebalancer.sweep(args.sweep, dry_run=dry_run)
        elif args.topup is not None:
            print(f"\n⮕ Topping up {args.topup} USDC reserve → operational ...")
            res = rebalancer.topup(args.topup, dry_run=dry_run)
        elif args.watch:
            _run_watch(rebalancer, dry_run, args.interval)
            return
        else:
            print(f"\n⮕ Auto rebalance (read → decide → act) ...")
            res = rebalancer.run_once(dry_run=dry_run)
            if res.get("error"):
                print(f"  ✗ {res['error']}")
                return
            decision = res.get("decision")
            if decision and decision.action == "none":
                print(f"  ✓ Treasury healthy ({decision.zone}); no action needed.")
                return
            # run_once wraps the transfer result under "action"
            res = res.get("action") or {}
    except ArcExecutorError as e:
        print(f"  ✗ Rebalance failed: {e}")
        return

    _print_rebalance_result(res, dry_run)


def _run_watch(rebalancer, dry_run: bool, interval: int):
    """Loop: evaluate the treasury and autonomously rebalance every interval."""
    from src import config as C

    interval = interval or C.ARC_REBALANCE_CONFIG.monitor_interval
    print(f"\n⮕ Watching treasury every {interval}s (Ctrl-C to stop) ...")
    try:
        while True:
            res = rebalancer.run_once(dry_run=dry_run)
            if res.get("error"):
                print(f"  ✗ {res['error']}")
            else:
                decision = res.get("decision")
                if decision and decision.action == "none":
                    print(f"  ✓ {decision.zone}: {decision.reason}")
                else:
                    _print_rebalance_result(res.get("action") or {}, dry_run)
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\n⏹ Stopped watching.")


def _print_rebalance_result(res: dict, dry_run: bool):
    if dry_run:
        print(f"  [DRY-RUN] Would broadcast:")
        print(f"    from:   {res['from']}")
        print(f"    to:     {res['to']}")
        print(f"    amount: {res['amount_usdc']} USDC")
        print(f"    tx:     {json.dumps(res['tx'], indent=2)}")
        return
    print(f"  ✓ TX broadcast: {res.get('tx_hash')}")
    print(f"  ✓ Explorer: {res.get('explorer')}")
    print(f"    {res['from']} → {res['to']} : {res['amount_usdc']} USDC")


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
    sub.add_parser("summary", help="Show position summary with rebalancer recommendation")
    sub.add_parser("audit", help="Show audit log summary")

    arc_status_p = sub.add_parser(
        "arc-status", help="Show Arc Testnet treasury status (real on-chain USDC)"
    )
    arc_status_p.add_argument(
        "--address", default=None, help="Arc wallet address (default: ARC_WALLET_ADDRESS)"
    )

    arc_reb_p = sub.add_parser(
        "arc-rebalance", help="Autonomous rebalance on Arc (read → decide → act)"
    )
    arc_reb_p.add_argument(
        "--sweep", type=float, default=None,
        help="Demo: sweep N USDC from operational wallet to reserve wallet",
    )
    arc_reb_p.add_argument(
        "--topup", type=float, default=None,
        help="Demo: pull N USDC from reserve wallet into operational wallet",
    )
    arc_reb_p.add_argument(
        "--dry-run", action="store_true",
        help="Build the transaction but do NOT broadcast it",
    )
    arc_reb_p.add_argument(
        "--watch", action="store_true",
        help="Loop: monitor + autonomously rebalance every --interval seconds",
    )
    arc_reb_p.add_argument(
        "--interval", type=int, default=None,
        help="Watch-loop interval in seconds (default: config.monitor_interval)",
    )

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
        "summary": cmd_summary,
        "setup": cmd_setup,
        "audit": cmd_audit,
        "arc-status": cmd_arc_status,
        "arc-rebalance": cmd_arc_rebalance,
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
