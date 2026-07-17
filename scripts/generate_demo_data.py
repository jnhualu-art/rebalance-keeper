#!/usr/bin/env python3
"""
RebalanceKeeper — Demo data generator.

Generates realistic audit logs, monitoring session output, and dashboard
data that demonstrate the full rebalancing lifecycle without needing
real on-chain interaction.

Scenario:
  1. Position setup: supply 0.05 WETH, borrow 50 USDC → HF=2.40 (SAFE)
  2. Stable monitoring (5 readings, SAFE zone)
  3. ETH price drops → HF declines into WARNING zone
  4. Pre-emptive repay triggered (10% of debt)
  5. ETH continues dropping → HF enters DANGER zone
  6. Active repay triggered (25% of debt)
  7. HF recovers back to SAFE zone

Output files:
  - logs/audit.jsonl          — Full audit trail (JSONL)
  - logs/demo_session.txt     — Simulated console output
  - logs/demo_history.json    — HF history for dashboard
  - logs/demo_summary.json    — Final position summary
"""

import json
import os
import sys
from datetime import datetime, timezone, timedelta

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import config
from src.audit import AuditLogger
from src.monitor import AlertLevel, HealthSnapshot
from src.rebalancer import Rebalancer, RebalanceDecision
from tests.mocks import MockKeeperHubClient, make_account_data


# ── Scenario parameters ──────────────────────────────────────
WALLET = config.WALLET_ADDRESS
WETH_PRICE_INIT = 3200  # USD per WETH at start
COLLATERAL_WETH = 0.05  # 0.05 WETH supplied
BORROW_USDC = 50  # 50 USDC borrowed
LIQ_THRESHOLD = 8000  # 80% (basis points in Aave: 8000 = 80.00%)

# Base units: collateral in 8 decimals (WETH), debt in 6 decimals (USDC)
# Aave V3 uses "base" units where 1 unit = $0.01 (prices from oracle in 8 decimals)
# For simplicity, we use USD-denominated base units
COLLATERAL_BASE_INIT = int(COLLATERAL_WETH * WETH_PRICE_INIT * 1e2)  # $160 → 16000
DEBT_BASE = int(BORROW_USDC * 1e2)  # $50 → 5000


def calc_hf(collateral_base: int, debt_base: int, lt_bps: int = LIQ_THRESHOLD) -> float:
    """Calculate health factor from base units."""
    if debt_base <= 0:
        return float("inf")
    lt = lt_bps / 10000
    return (collateral_base * lt) / debt_base


def hf_to_raw(hf: float) -> str:
    """Convert ratio HF to Aave's 1e18 precision raw value."""
    if hf == float("inf"):
        return "115792089237316195423570985008687907853269984665640564039457584007913129639935"
    return str(int(hf * 1e18))


def make_snapshot(hf: float, collateral: int, debt: int, ts: datetime,
                  trend: float = 0.0, declines: int = 0) -> HealthSnapshot:
    """Create a HealthSnapshot for the given parameters."""
    level = AlertLevel.SAFE
    if hf != float("inf"):
        if hf >= config.REBALANCE_CONFIG.safe_threshold:
            level = AlertLevel.SAFE
        elif hf >= config.REBALANCE_CONFIG.warn_threshold:
            level = AlertLevel.WARNING
        elif hf >= config.REBALANCE_CONFIG.danger_threshold:
            level = AlertLevel.DANGER
        else:
            level = AlertLevel.CRITICAL

    return HealthSnapshot(
        timestamp=ts.isoformat(),
        health_factor=hf,
        total_collateral_base=str(collateral),
        total_debt_base=str(debt),
        available_borrows_base=str(int(collateral * 0.7 - debt)),
        ltv=str(int(debt / collateral * 10000)) if collateral > 0 else "0",
        liquidation_threshold=str(LIQ_THRESHOLD),
        hf_trend=trend,
        hf_rate_pct=(trend / max(hf, 0.01)) * 100,
        alert_level=level,
        consecutive_declines=declines,
    )


def generate_demo():
    """Generate all demo data files."""
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    logs_dir = os.path.join(project_root, "logs")
    os.makedirs(logs_dir, exist_ok=True)

    audit = AuditLogger(os.path.join(logs_dir, "audit.jsonl"))
    # Clear old log
    audit_path = os.path.join(logs_dir, "audit.jsonl")
    if os.path.exists(audit_path):
        os.remove(audit_path)

    console_lines = []
    history = []
    triggers = []
    start_time = datetime(2026, 7, 17, 9, 0, 0, tzinfo=timezone.utc)

    def log_console(line: str):
        console_lines.append(line)
        print(line)

    # ── Header ────────────────────────────────────────────────
    log_console("=" * 60)
    log_console("  RebalanceKeeper — Demo Monitoring Session")
    log_console("=" * 60)
    log_console(f"  Wallet:    {WALLET}")
    log_console(f"  Chain:     {config.CHAIN_NAME} (id={config.CHAIN_ID})")
    log_console(f"  Pool:      {config.AAVE_POOL}")
    log_console(f"  Collateral: {COLLATERAL_WETH} WETH (~${COLLATERAL_WETH * WETH_PRICE_INIT:.0f})")
    log_console(f"  Debt:      {BORROW_USDC} USDC")
    log_console(f"  Zones:     SAFE>=2.0 | WARN>=1.5 | DANGER>=1.2 | CRITICAL<1.2")
    log_console(f"  Interval:  30s")
    log_console("-" * 60)

    # ── Phase 1: Setup ───────────────────────────────────────
    log_console("\n[SETUP] Creating test position on Aave V3 Sepolia...")
    log_console(f"  Step 1: Supplying {COLLATERAL_WETH} WETH as collateral...")
    log_console(f"    TX: 0xa1b2c3d4e5f6789012345678901234567890abcdef1234567890abcdef1234")
    log_console(f"    Explorer: https://sepolia.etherscan.io/tx/0xa1b2c3d4...")
    log_console(f"  Step 2: Borrowing {BORROW_USDC} USDC against collateral...")
    log_console(f"    TX: 0xb2c3d4e5f6789012345678901234567890abcdef1234567890abcdef123456")
    log_console(f"    Explorer: https://sepolia.etherscan.io/tx/0xb2c3d4e5...")
    log_console(f"  Position created! Initial HF: {calc_hf(COLLATERAL_BASE_INIT, DEBT_BASE):.4f}")

    # Audit: setup events
    audit.log(
        event_type="trigger",
        trigger="position_setup",
        decision=f"supply {COLLATERAL_WETH} WETH + borrow {BORROW_USDC} USDC",
        execution={
            "tx_hash": "0xa1b2c3d4e5f6789012345678901234567890abcdef1234567890abcdef1234",
            "gas_used": "165000",
            "status": "success",
            "explorer_link": "https://sepolia.etherscan.io/tx/0xa1b2c3d4e5f6789012345678901234567890abcdef1234567890abcdef1234",
            "params": {"supply_amount": f"{COLLATERAL_WETH} WETH", "borrow_amount": f"{BORROW_USDC} USDC"},
        },
    )

    triggers.append({
        "timestamp": start_time.isoformat(),
        "trigger": "position_setup",
        "action": f"supply {COLLATERAL_WETH} WETH + borrow {BORROW_USDC} USDC",
        "txHash": "0xa1b2c3d4e5f6789012345678901234567890abcdef1234567890abcdef1234",
        "status": "success",
    })

    # ── Phase 2: Stable monitoring (SAFE zone, 5 readings) ──
    log_console("\n[MONITOR] Starting continuous monitoring...")
    log_console(f"  Monitor started. Wallet: {WALLET}")
    log_console(f"  Zones: SAFE>=2.0 | WARN>=1.5 | DANGER>=1.2 | CRITICAL<1.2")
    log_console(f"  Trend window: 5 readings")
    log_console(f"  Cooldown: 120s")
    log_console(f"  Interval: 30s")
    log_console("-" * 60)

    # ETH price stable around $3200, small fluctuations
    eth_prices = [3200, 3195, 3210, 3198, 3205]
    collateral_base = COLLATERAL_BASE_INIT
    debt_base = DEBT_BASE
    prev_hf = None

    for i, price in enumerate(eth_prices):
        ts = start_time + timedelta(minutes=i * 2)
        collateral_base = int(COLLATERAL_WETH * price * 1e2)
        hf = calc_hf(collateral_base, debt_base)
        trend = hf - prev_hf if prev_hf else 0.0
        declines = 1 if (prev_hf and hf < prev_hf) else 0

        snap = make_snapshot(hf, collateral_base, debt_base, ts, trend, declines)
        history.append({
            "timestamp": ts.isoformat(),
            "hf": round(hf, 4),
            "collateral": collateral_base,
            "debt": debt_base,
            "alert": snap.alert_level.value,
            "trend": round(trend, 4),
            "declines": declines,
        })

        log_console(
            f"[{ts.isoformat()}] HF={hf:.4f} "
            f"Collateral={collateral_base} Debt={debt_base} "
            f"| trend={trend:+.4f}/read ({trend/max(hf,0.01)*100:+.2f}%) "
            f"declines={declines} -> {snap.alert_level.value}"
        )
        audit.log_monitor(f"{hf:.4f}", str(collateral_base), str(debt_base))
        prev_hf = hf

    # ── Phase 3: ETH drops, HF declines into WARNING ─────────
    log_console("\n  --- ETH price declining, HF entering WARNING zone ---")

    # ETH drops from 3205 to ~1900 over 5 readings → HF drops from 2.56 to ~1.52
    eth_decline = [3100, 2900, 2700, 2500, 2300, 2100, 1900]
    for i, price in enumerate(eth_decline):
        ts = start_time + timedelta(minutes=(5 + i) * 2)
        collateral_base = int(COLLATERAL_WETH * price * 1e2)
        hf = calc_hf(collateral_base, debt_base)
        trend = hf - prev_hf
        declines = (i + 1) if hf < prev_hf else 0

        snap = make_snapshot(hf, collateral_base, debt_base, ts, trend, declines)
        history.append({
            "timestamp": ts.isoformat(),
            "hf": round(hf, 4),
            "collateral": collateral_base,
            "debt": debt_base,
            "alert": snap.alert_level.value,
            "trend": round(trend, 4),
            "declines": declines,
        })

        zone_icon = "⚠" if snap.alert_level == AlertLevel.WARNING else "✓"
        log_console(
            f"[{ts.isoformat()}] HF={hf:.4f} "
            f"Collateral={collateral_base} Debt={debt_base} "
            f"| trend={trend:+.4f}/read ({trend/max(hf,0.01)*100:+.2f}%) "
            f"declines={declines} -> {snap.alert_level.value}"
        )

        if snap.alert_level == AlertLevel.WARNING and declines >= 4:
            # Pre-emptive trigger
            repay_fraction = config.REBALANCE_CONFIG.repay_fraction_warn
            repay_amount_usdc = BORROW_USDC * repay_fraction
            repay_amount_base = int(repay_amount_usdc * 1e2)
            log_console(f"  WARNING - HF declining for {declines} readings. Pre-emptive rebalance.")
            log_console(f"  Decision: repay {repay_fraction*100:.0f}% of USDC debt ({repay_amount_usdc:.2f} USDC)")
            log_console(f"  Estimated HF impact: +{calc_hf(collateral_base, debt_base - repay_amount_base) - hf:.4f}")
            log_console(f"  TX: 0xc3d4e5f6789012345678901234567890abcdef1234567890abcdef12345678")
            log_console(f"  Explorer: https://sepolia.etherscan.io/tx/0xc3d4e5f6...")
            log_console(f"  TX confirmed: 0xc3d4e5f6789012345678901234567890abcdef1234567890abcdef12345678")
            log_console(f"  Gas used: 120000")

            audit.log_trigger(
                health_factor=f"{hf:.4f}",
                action=f"repay {repay_amount_usdc:.2f} USDC (10% of debt)",
                params={
                    "asset": config.token_addr("USDC"),
                    "idempotency_key": f"rbk_{int(ts.timestamp())}",
                    "alert_level": "WARNING",
                    "estimated_hf_impact": calc_hf(collateral_base, debt_base - repay_amount_base) - hf,
                },
                tx_hash="0xc3d4e5f6789012345678901234567890abcdef1234567890abcdef12345678",
                gas_used="120000",
                status="success",
                explorer_link="https://sepolia.etherscan.io/tx/0xc3d4e5f6789012345678901234567890abcdef1234567890abcdef12345678",
            )

            triggers.append({
                "timestamp": ts.isoformat(),
                "trigger": f"health_factor={hf:.4f} (WARNING, {declines} declines)",
                "action": f"repay {repay_amount_usdc:.2f} USDC (10%)",
                "txHash": "0xc3d4e5f6789012345678901234567890abcdef1234567890abcdef12345678",
                "status": "success",
            })

            # Update debt after repay
            debt_base -= repay_amount_base

        audit.log_monitor(f"{hf:.4f}", str(collateral_base), str(debt_base))
        prev_hf = hf

    # ── Phase 4: ETH continues dropping, DANGER zone ─────────
    log_console("\n  --- ETH price continues to drop, HF entering DANGER zone ---")

    # ETH drops further to ~1450 → HF drops to ~1.29 (DANGER)
    eth_danger = [1750, 1600, 1450]
    for i, price in enumerate(eth_danger):
        ts = start_time + timedelta(minutes=(10 + i) * 2)
        collateral_base = int(COLLATERAL_WETH * price * 1e2)
        hf = calc_hf(collateral_base, debt_base)
        trend = hf - prev_hf
        declines = (i + 1) if hf < prev_hf else 0

        snap = make_snapshot(hf, collateral_base, debt_base, ts, trend, declines)
        history.append({
            "timestamp": ts.isoformat(),
            "hf": round(hf, 4),
            "collateral": collateral_base,
            "debt": debt_base,
            "alert": snap.alert_level.value,
            "trend": round(trend, 4),
            "declines": declines,
        })

        log_console(
            f"[{ts.isoformat()}] HF={hf:.4f} "
            f"Collateral={collateral_base} Debt={debt_base} "
            f"| trend={trend:+.4f}/read ({trend/max(hf,0.01)*100:+.2f}%) "
            f"declines={declines} -> {snap.alert_level.value}"
        )

        if snap.alert_level == AlertLevel.DANGER:
            # Active rebalance
            repay_fraction = config.REBALANCE_CONFIG.repay_fraction_danger
            repay_amount_usdc = (debt_base / 1e2) * repay_fraction
            repay_amount_base = int(repay_amount_usdc * 1e2)
            new_hf = calc_hf(collateral_base, debt_base - repay_amount_base)
            log_console(f"  DANGER - HF below {config.REBALANCE_CONFIG.warn_threshold}. Rebalancing.")
            log_console(f"  Decision: repay {repay_fraction*100:.0f}% of USDC debt ({repay_amount_usdc:.2f} USDC)")
            log_console(f"  Estimated HF impact: +{new_hf - hf:.4f}")
            log_console(f"  TX: 0xd4e5f6789012345678901234567890abcdef1234567890abcdef12345678901")
            log_console(f"  Explorer: https://sepolia.etherscan.io/tx/0xd4e5f678...")
            log_console(f"  TX confirmed: 0xd4e5f6789012345678901234567890abcdef1234567890abcdef12345678901")
            log_console(f"  Gas used: 135000")

            audit.log_trigger(
                health_factor=f"{hf:.4f}",
                action=f"repay {repay_amount_usdc:.2f} USDC (25% of debt)",
                params={
                    "asset": config.token_addr("USDC"),
                    "idempotency_key": f"rbk_{int(ts.timestamp())}",
                    "alert_level": "DANGER",
                    "estimated_hf_impact": new_hf - hf,
                },
                tx_hash="0xd4e5f6789012345678901234567890abcdef1234567890abcdef12345678901",
                gas_used="135000",
                status="success",
                explorer_link="https://sepolia.etherscan.io/tx/0xd4e5f6789012345678901234567890abcdef1234567890abcdef12345678901",
            )

            triggers.append({
                "timestamp": ts.isoformat(),
                "trigger": f"health_factor={hf:.4f} (DANGER)",
                "action": f"repay {repay_amount_usdc:.2f} USDC (25%)",
                "txHash": "0xd4e5f6789012345678901234567890abcdef1234567890abcdef12345678901",
                "status": "success",
            })

            debt_base -= repay_amount_base

        audit.log_monitor(f"{hf:.4f}", str(collateral_base), str(debt_base))
        prev_hf = hf

    # ── Phase 5: Recovery (SAFE zone) ────────────────────────
    log_console("\n  --- HF recovering after repay, entering SAFE zone ---")

    # ETH recovers slightly, but debt is reduced so HF improves more
    eth_recovery = [1500, 1550, 1600, 1650, 1700]
    for i, price in enumerate(eth_recovery):
        ts = start_time + timedelta(minutes=(13 + i) * 2)
        collateral_base = int(COLLATERAL_WETH * price * 1e2)
        hf = calc_hf(collateral_base, debt_base)
        trend = hf - prev_hf
        declines = 0 if hf >= prev_hf else 1

        snap = make_snapshot(hf, collateral_base, debt_base, ts, trend, declines)
        history.append({
            "timestamp": ts.isoformat(),
            "hf": round(hf, 4),
            "collateral": collateral_base,
            "debt": debt_base,
            "alert": snap.alert_level.value,
            "trend": round(trend, 4),
            "declines": declines,
        })

        log_console(
            f"[{ts.isoformat()}] HF={hf:.4f} "
            f"Collateral={collateral_base} Debt={debt_base} "
            f"| trend={trend:+.4f}/read ({trend/max(hf,0.01)*100:+.2f}%) "
            f"declines={declines} -> {snap.alert_level.value}"
        )
        audit.log_monitor(f"{hf:.4f}", str(collateral_base), str(debt_base))
        prev_hf = hf

    # ── Summary ──────────────────────────────────────────────
    final_hf = calc_hf(collateral_base, debt_base)
    log_console("\n" + "=" * 60)
    log_console("  Session Summary")
    log_console("=" * 60)
    log_console(f"  Duration: 18 monitoring cycles (~36 min simulated)")
    log_console(f"  Total readings: {len(history)}")
    log_console(f"  Rebalance triggers: {len(triggers) - 1} (1 warning repay + 1 danger repay)")
    log_console(f"  Initial HF: {calc_hf(COLLATERAL_BASE_INIT, DEBT_BASE):.4f}")
    log_console(f"  Lowest HF:  {min(h['hf'] for h in history):.4f}")
    log_console(f"  Final HF:   {final_hf:.4f}")
    log_console(f"  Debt repaid: {DEBT_BASE - debt_base} base units (${(DEBT_BASE - debt_base)/1e2:.2f} USDC)")
    log_console(f"  All transactions: SUCCESS")
    log_console(f"  Audit log: logs/audit.jsonl ({len(audit.read_all())} entries)")
    log_console("=" * 60)

    # ── Write output files ───────────────────────────────────
    # Demo session console output
    session_path = os.path.join(logs_dir, "demo_session.txt")
    with open(session_path, "w", encoding="utf-8") as f:
        f.write("\n".join(console_lines))
    print(f"\n[OK] Written: {session_path}")

    # Demo history (for dashboard)
    history_path = os.path.join(logs_dir, "demo_history.json")
    demo_data = {
        "healthFactor": final_hf,
        "totalCollateralBase": str(collateral_base),
        "totalDebtBase": str(debt_base),
        "availableBorrowsBase": str(int(collateral_base * 0.7 - debt_base)),
        "ltv": str(int(debt_base / collateral_base * 10000)) if collateral_base > 0 else "0",
        "liquidationThreshold": str(LIQ_THRESHOLD),
        "history": [{"t": h["timestamp"][11:19], "hf": h["hf"]} for h in history],
        "triggers": triggers,
        "wallet": WALLET,
        "chain": config.CHAIN_NAME,
    }
    with open(history_path, "w", encoding="utf-8") as f:
        json.dump(demo_data, f, indent=2)
    print(f"[OK] Written: {history_path}")

    # Demo summary
    summary_path = os.path.join(logs_dir, "demo_summary.json")
    summary = {
        "session_date": start_time.isoformat(),
        "wallet": WALLET,
        "chain": config.CHAIN_NAME,
        "pool": config.AAVE_POOL,
        "initial_position": {
            "collateral_weth": COLLATERAL_WETH,
            "borrowed_usdc": BORROW_USDC,
            "health_factor": round(calc_hf(COLLATERAL_BASE_INIT, DEBT_BASE), 4),
        },
        "monitoring_cycles": len(history),
        "rebalance_actions": [
            {
                "timestamp": t["timestamp"],
                "trigger": t["trigger"],
                "action": t["action"],
                "tx_hash": t["txHash"],
                "status": t["status"],
                "explorer": f"https://sepolia.etherscan.io/tx/{t['txHash']}",
            }
            for t in triggers
        ],
        "final_position": {
            "health_factor": round(final_hf, 4),
            "collateral_base": collateral_base,
            "debt_base": debt_base,
            "debt_repaid_usdc": round((DEBT_BASE - debt_base) / 1e2, 2),
        },
        "lowest_hf": round(min(h["hf"] for h in history), 4),
        "all_txs_success": True,
    }
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    print(f"[OK] Written: {summary_path}")

    # Audit summary
    print(f"\n  {audit.summary()}")


if __name__ == "__main__":
    generate_demo()
