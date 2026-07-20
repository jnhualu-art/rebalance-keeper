#!/usr/bin/env python3
"""
arc_status.py — Standalone Arc Testnet treasury reader for ArcKeeper.

Reads the REAL on-chain USDC balance of an Arc wallet via the public Arc
Testnet RPC (stdlib only, no web3 dependency) and prints a treasury-health
report. This is the Checkpoint 2 progress proof for the Encode Club
"Programmable Money Hackathon" (Agentic Economy track).

Usage:
  python scripts/arc_status.py [WALLET_ADDRESS]

If no address is given, it uses ARC_WALLET_ADDRESS from .env, then falls
back to the Sepolia WALLET_ADDRESS.

Step 1 (one-time): create an Arc wallet and fund it with testnet USDC
from the Circle Faucet: https://faucet.circle.com  (select Arc Testnet)
Then set ARC_WALLET_ADDRESS in .env.
"""

import os
import sys

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import config
from src.arc_client import ArcClient, ArcError
from src import arc_position


def main():
    wallet = sys.argv[1] if len(sys.argv) > 1 else config.ARC_WALLET_ADDRESS
    print(f"ArcKeeper — reading treasury from Arc Testnet ({config.ARC_RPC_URL})")
    print(f"Wallet: {wallet}")

    try:
        client = ArcClient()
        # Sanity: confirm we're on the right chain
        cid = client.get_chain_id()
        if cid != config.ARC_CHAIN_ID:
            print(f"WARNING: RPC returned chainId {cid}, expected {config.ARC_CHAIN_ID}")
        pos = client.get_position(wallet, floor_usdc=config.ARC_REBALANCE_CONFIG.floor_usdc)
    except ArcError as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    _, decision = arc_position.evaluate(pos, config.ARC_REBALANCE_CONFIG)
    arc_position.print_status(pos, decision, config.ARC_REBALANCE_CONFIG)

    print(f"Explorer: {client.explorer_address(wallet)}")
    if pos["usdc_balance"] == 0:
        print("\n(USDC balance is 0 — fund this wallet via the Circle Faucet:")
        print(" https://faucet.circle.com  → select Arc Testnet, paste the address)")


if __name__ == "__main__":
    main()
