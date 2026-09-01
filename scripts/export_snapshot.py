#!/usr/bin/env python3
"""
export_snapshot.py — publish the live Arc treasury position for the x402 gateway.

This is the bridge between the Python agent (which owns the on-chain reads and
the rebalance policy) and the Node x402 server (which owns the paywall).

Why a file instead of a direct call:
  - The rebalance policy lives in src/arc_position.py and is unit-tested there.
    Re-implementing it in JavaScript would create two sources of truth that
    drift apart silently.
  - The Node service keeps zero chain dependencies. It can boot, be tested and
    be restarted without a working Arc RPC.
  - The snapshot is a durable artefact: it can be archived, diffed and replayed
    during a demo without touching mainnet-ish state.

The write is atomic (temp file + os.replace) so the Node side can never observe
a half-written JSON document.

Usage:
  python scripts/export_snapshot.py                # write to the default path
  python scripts/export_snapshot.py --out FILE     # explicit destination
  python scripts/export_snapshot.py --print        # also echo to stdout
"""

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timezone

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import arc_position, config
from src.arc_client import ArcClient, ArcError

SCHEMA = "arckeeper-treasury-snapshot/1"

DEFAULT_OUT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "x402",
    "state",
    "treasury-snapshot.json",
)


def build_snapshot(wallet: str) -> dict:
    """Read the real on-chain position and run the rebalance policy over it."""
    client = ArcClient()

    chain_id = client.get_chain_id()
    if chain_id != config.ARC_CHAIN_ID:
        # Not fatal, but a snapshot tagged with the wrong chain would silently
        # mislead every paying consumer, so make it loud.
        print(
            f"WARNING: RPC returned chainId {chain_id}, expected {config.ARC_CHAIN_ID}",
            file=sys.stderr,
        )

    cfg = config.ARC_REBALANCE_CONFIG
    position = client.get_position(wallet, floor_usdc=cfg.floor_usdc)
    zone, decision = arc_position.evaluate(position, cfg)

    health = position["treasury_health"]
    return {
        "schema": SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "chain": {
            "id": chain_id,
            "name": config.ARC_CHAIN_NAME,
            "explorer": config.ARC_EXPLORER,
        },
        "block_number": position["block_number"],
        "wallet": position["address"],
        "explorer": client.explorer_address(wallet),
        "treasury": {
            "usdc_balance": round(position["usdc_balance"], 6),
            "native_usdc_balance": round(position["native_usdc_balance"], 6),
            "floor_usdc": cfg.floor_usdc,
            "ceiling_usdc": cfg.ceiling_usdc,
            # Infinity is not representable in JSON; the consumer treats null
            # as "no floor configured", which is the same meaning.
            "health": None if health == float("inf") else round(health, 6),
        },
        "decision": {
            "action": decision.action,
            "zone": decision.zone,
            "amount_usdc": decision.amount_usdc,
            "reason": decision.reason,
        },
    }


def write_atomic(path: str, payload: dict) -> None:
    """Write JSON via a temp file in the same directory, then rename.

    os.replace is atomic on both POSIX and Windows, and keeping the temp file
    in the target directory guarantees the rename stays on one filesystem.
    """
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".snapshot-", suffix=".tmp")
    try:
        # Encoding is pinned: Windows defaults to GBK here and any non-ASCII
        # character in a reason string would crash the export.
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=DEFAULT_OUT, help="destination JSON path")
    parser.add_argument("--wallet", default=None, help="override ARC_WALLET_ADDRESS")
    parser.add_argument("--print", dest="do_print", action="store_true")
    args = parser.parse_args()

    wallet = args.wallet or config.ARC_WALLET_ADDRESS
    if not wallet:
        print("ERROR: no wallet. Set ARC_WALLET_ADDRESS in .env or pass --wallet.", file=sys.stderr)
        return 1

    try:
        snapshot = build_snapshot(wallet)
    except ArcError as exc:
        # Deliberately no fallback write: a stale-but-valid-looking snapshot is
        # worse than no snapshot, because the gateway would happily sell it.
        print(f"ERROR: could not read Arc position: {exc}", file=sys.stderr)
        return 1

    try:
        write_atomic(args.out, snapshot)
    except OSError as exc:
        print(f"ERROR: could not write snapshot: {exc}", file=sys.stderr)
        return 1

    if args.do_print:
        print(json.dumps(snapshot, indent=2, ensure_ascii=False))

    print(
        f"snapshot written: {args.out}\n"
        f"  wallet  {snapshot['wallet']}\n"
        f"  balance {snapshot['treasury']['usdc_balance']} USDC  "
        f"(floor {snapshot['treasury']['floor_usdc']}, "
        f"ceiling {snapshot['treasury']['ceiling_usdc']})\n"
        f"  zone    {snapshot['decision']['zone']}  "
        f"action={snapshot['decision']['action']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
