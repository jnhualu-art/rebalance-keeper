"""
RebalanceKeeper — Setup a real Aave V3 test position on Sepolia.

Flow:
  1. Wrap native ETH  -> WETH  (WETH.deposit, payable)
  2. Approve WETH      -> Aave Pool
  3. Supply WETH       -> Aave V3 (collateral)
  4. Set WETH as collateral (useAsCollateral = true)
  5. Borrow USDC       -> against the WETH collateral
  6. Verify the resulting position (health factor)

Usage:
  python scripts/setup_test_position.py [WRAP_ETH] [BORROW_USDC]
  e.g. python scripts/setup_test_position.py 0.15 180
"""
import sys
import json
import time
import os

# Ensure project root is on sys.path so `from src...` works
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load .env (API key, wallet address, etc.)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from src.keeperhub_client import KeeperHubClient, MCPError
from src import config

MAX_UINT = "115792089237316195423570985008687907853269984665640564039457584007913129639935"

WRAP_ETH = sys.argv[1] if len(sys.argv) > 1 else "0.15"
BORROW_USDC = sys.argv[2] if len(sys.argv) > 2 else "180"

WETH = config.token_addr("WETH")
USDC = config.token_addr("USDC")
POOL = config.AAVE_POOL
USER = config.WALLET_ADDRESS

client = KeeperHubClient()


def step(label, fn):
    print(f"\n▶ {label} ...")
    try:
        res = fn()
        print(f"  ✓ done: {json.dumps(res, ensure_ascii=False)[:300]}")
        return res
    except MCPError as e:
        print(f"  ✗ ERROR: {e}")
        raise


def main():
    print(f"=== RebalanceKeeper: setup test position ===")
    print(f"Wallet : {USER}")
    print(f"Chain  : {config.CHAIN_NAME} ({config.CHAIN_ID})")
    print(f"Wrap   : {WRAP_ETH} ETH -> WETH")
    print(f"Borrow : {BORROW_USDC} USDC")
    print(f"WETH   : {WETH}")
    print(f"USDC   : {USDC}")
    print(f"Pool   : {POOL}")

    # 0) Check existing state (idempotent)
    existing = int(client.get_token_balance(WETH, USER) or "0")
    print(f"  Existing WETH balance = {existing / 1e18:.6f} WETH")

    acc0 = client.get_user_account_data(USER)
    collateral_base = int(acc0.get("totalCollateralBase", "0"))
    print(f"  Existing collateral (base) = {collateral_base} (~${collateral_base / 1e8:.2f})")

    already_supplied = collateral_base > 0

    if not already_supplied:
        # 1) Wrap ETH -> WETH (only if needed)
        target_weth_wei = int(float(WRAP_ETH) * 1e18)
        if existing >= target_weth_wei:
            print(f"  ✓ Already have enough WETH, skipping wrap")
            weth_bal = str(existing)
        else:
            to_wrap = (target_weth_wei - existing) / 1e18
            step(f"1/6 Wrap {to_wrap:.6f} ETH -> WETH", lambda: client.wrap_eth(
                f"{to_wrap:.6f}", idempotency_key="setup-wrap"
            ))
            time.sleep(3)
            weth_bal = step(f"2/6 Check WETH balance", lambda: client.get_token_balance(WETH, USER))
            print(f"  WETH balance = {weth_bal}")

        # 3) Approve WETH for Pool
        step(f"3/6 Approve WETH for Pool (max)", lambda: client.approve(
            WETH, POOL, MAX_UINT, idempotency_key="setup-approve"
        ))
        time.sleep(3)

        # 4) Supply WETH (full balance)
        step(f"4/6 Supply {weth_bal} WETH", lambda: client.supply(
            WETH, weth_bal, on_behalf_of=USER, idempotency_key="setup-supply"
        ))
        time.sleep(3)

        # 5) Set WETH as collateral
        step(f"5/6 Enable WETH as collateral", lambda: client.set_collateral(
            WETH, True, network=config.CHAIN_ID
        ))
        time.sleep(3)
    else:
        print(f"  ✓ Collateral already supplied, skipping wrap/approve/supply")

    # 6) Borrow USDC (USDC has 6 decimals)
    borrow_amt = str(int(float(BORROW_USDC) * 10 ** 6))
    step(f"6/6 Borrow {BORROW_USDC} USDC", lambda: client.borrow(
        USDC, borrow_amt, on_behalf_of=USER,
        interest_rate_mode=config.REBALANCE_CONFIG.interest_rate_mode,
        idempotency_key="setup-borrow"
    ))
    time.sleep(5)

    # Verify
    print("\n=== Position after setup ===")
    acc = client.get_user_account_data(USER)
    print(json.dumps(acc, indent=2))

    hf = acc.get("healthFactor", "0")
    try:
        hf_num = int(hf) / 1e18 if hf != "115792089237316195423570985008687907853269984665640564039457584007913129639935" else float("inf")
    except (ValueError, TypeError):
        hf_num = hf
    print(f"\nHealth Factor: {hf_num}")

    if acc.get("totalDebtBase", "0") != "0":
        print("✅ Position created successfully!")
    else:
        print("⚠️  Position may be incomplete — check the logs above.")


if __name__ == "__main__":
    main()
