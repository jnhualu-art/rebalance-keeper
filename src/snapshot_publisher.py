"""
ArcKeeper — publish the live treasury position for the x402 gateway.

The Python agent owns the chain reads and the rebalance policy; the Node x402
service owns the paywall. This module is the seam between them: it turns one
evaluation of the treasury into the JSON document the service sells.

Two ways in, one implementation:

  * `snapshot_from_result()` — reuse a cycle the agent already ran. Costs no
    extra RPC calls, and the decision it publishes is the very decision the
    agent acted on. This is what the watch loop uses.
  * `refresh_from_chain()`  — read the chain independently. Used by the CLI
    when no rebalance loop is running.

The write is atomic (temp file + os.replace) so a consumer can never observe a
half-written document. A failed read never overwrites a good snapshot: absence
of data must be visible as staleness, not as corruption.

CLI:
  python -m src.snapshot_publisher                 # publish once
  python -m src.snapshot_publisher --watch         # keep it fresh
"""

import argparse
import json
import os
import sys
import tempfile
import time
from datetime import datetime, timezone

try:
    from dotenv import load_dotenv

    # Must run before `src.config` is imported: it reads os.environ at module
    # level. Without this, running the module directly (rather than through
    # main.py) silently sees no configuration at all.
    load_dotenv()
except ImportError:
    pass

from src import arc_position, config
from src.arc_client import ArcClient, ArcError

# Bumped from /1 when last_action was added. The consumer accepts both so an
# already-published /1 file does not turn into a 503.
SCHEMA = "arckeeper-treasury-snapshot/2"

DEFAULT_OUT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "x402",
    "state",
    "treasury-snapshot.json",
)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def resolve_wallet(explicit: str = None) -> str:
    """Resolve the Arc treasury wallet, refusing a silent fallback.

    `config.ARC_WALLET_ADDRESS` falls back to the Sepolia `WALLET_ADDRESS` when
    unset. Reading that address on Arc returns a zero balance, which would then
    be published - and sold to paying consumers - as a CRITICAL treasury that
    is simply the wrong wallet. An unset Arc wallet is an error, not a default.
    """
    if explicit:
        return explicit
    wallet = (os.getenv("ARC_WALLET_ADDRESS") or "").strip()
    if not wallet:
        raise ValueError(
            "ARC_WALLET_ADDRESS is not set. Refusing to fall back to the "
            "Sepolia WALLET_ADDRESS, which would read as an empty treasury on "
            "Arc and be published as a false CRITICAL."
        )
    return wallet


def build_snapshot(position: dict, decision, last_action: dict = None, cfg=None) -> dict:
    """Shape one evaluation into the published document.

    Pure: no I/O, no clock reads beyond `position`'s own data, so it can be
    asserted against directly in tests.
    """
    cfg = cfg or config.ARC_REBALANCE_CONFIG
    health = position.get("treasury_health")
    address = position.get("address")

    return {
        "schema": SCHEMA,
        "generated_at": utc_now_iso(),
        "chain": {
            "id": position.get("chain_id", config.ARC_CHAIN_ID),
            "name": config.ARC_CHAIN_NAME,
            "explorer": config.ARC_EXPLORER,
        },
        "block_number": position.get("block_number"),
        "wallet": address,
        "explorer": f"{config.ARC_EXPLORER}/address/{address}" if address else None,
        "treasury": {
            "usdc_balance": round(position["usdc_balance"], 6),
            "native_usdc_balance": round(position.get("native_usdc_balance", 0.0), 6),
            "floor_usdc": cfg.floor_usdc,
            "ceiling_usdc": cfg.ceiling_usdc,
            # Infinity is not representable in JSON; the consumer reads null as
            # "no floor configured", which carries the same meaning.
            "health": None if health == float("inf") else round(health, 6),
        },
        "decision": {
            "action": decision.action,
            "zone": decision.zone,
            "amount_usdc": decision.amount_usdc,
            "reason": decision.reason,
        },
        "last_action": last_action,
    }


def extract_last_action(action: dict, decision) -> dict:
    """Summarise what the agent just did, tolerating any backend's shape.

    Backends differ in what they return (local key vs Circle Agent Stack), and
    a shape change here must not take the publisher down. Anything unknown
    degrades to `status: unknown` rather than an exception.
    """
    if not action or not isinstance(action, dict):
        return None

    if action.get("error"):
        return {
            "type": decision.action,
            "status": "error",
            "error": str(action["error"])[:300],
        }

    tx_hash = None
    for key in ("tx_hash", "txHash", "hash", "transaction_hash", "transactionHash"):
        value = action.get(key)
        if isinstance(value, str) and value:
            tx_hash = value
            break

    if action.get("dry_run"):
        status = "dry_run"
    elif tx_hash:
        status = "success"
    else:
        status = "unknown"

    return {
        "type": decision.action,
        "amount_usdc": decision.amount_usdc,
        "tx_hash": tx_hash,
        "status": status,
        "dry_run": bool(action.get("dry_run")),
    }


def snapshot_from_result(result: dict, cfg=None) -> dict:
    """Publish from a cycle the agent already ran. No extra RPC calls.

    `result` is `ArcRebalancer.run_once()`'s return value. Reusing it matters:
    the decision sold to a paying consumer is then the same decision the agent
    acted on, rather than a second, independent reading taken moments later.
    """
    position = result["position"]
    decision = result["decision"]
    last_action = extract_last_action(result.get("action"), decision)
    return build_snapshot(position, decision, last_action=last_action, cfg=cfg)


def refresh_from_chain(path: str = DEFAULT_OUT, wallet: str = None, cfg=None) -> dict:
    """Read the chain, evaluate, publish. Used when no watch loop is running."""
    cfg = cfg or config.ARC_REBALANCE_CONFIG
    wallet = resolve_wallet(wallet)

    client = ArcClient()
    chain_id = client.get_chain_id()
    if chain_id != config.ARC_CHAIN_ID:
        # Not fatal, but a snapshot tagged with the wrong chain would mislead
        # every paying consumer, so make it loud.
        print(
            f"WARNING: RPC returned chainId {chain_id}, expected {config.ARC_CHAIN_ID}",
            file=sys.stderr,
        )

    position = client.get_position(wallet, floor_usdc=cfg.floor_usdc)
    _, decision = arc_position.evaluate(position, cfg)
    snapshot = build_snapshot(position, decision, cfg=cfg)
    publish(path, snapshot)
    return snapshot


def publish(path: str, snapshot: dict) -> None:
    """Write the snapshot atomically.

    The temp file lands in the destination directory so the rename never
    crosses a filesystem boundary.
    """
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".snapshot-", suffix=".tmp")
    try:
        # Encoding is pinned: Windows defaults to GBK here and any non-ASCII
        # character in a reason string would crash the export.
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(snapshot, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise


def _describe(snapshot: dict) -> str:
    t = snapshot["treasury"]
    d = snapshot["decision"]
    return (
        f"  wallet  {snapshot.get('wallet')}\n"
        f"  block   {snapshot.get('block_number')}\n"
        f"  balance {t['usdc_balance']} USDC  "
        f"(floor {t['floor_usdc']}, ceiling {t['ceiling_usdc']})\n"
        f"  zone    {d['zone']}  action={d['action']}"
    )


def run_watch(path: str, interval: int, wallet: str = None, max_errors: int = 5) -> int:
    """Keep the snapshot fresh on a timer.

    Publishing has to outrun the gateway's TTL or the service stops selling
    mid-demo. Errors back off and are counted; a transient RPC failure must not
    kill the loop, but a persistently broken one should stop rather than spin.
    """
    try:
        wallet = resolve_wallet(wallet)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"publishing snapshot every {interval}s -> {path} (Ctrl-C to stop)")
    errors = 0

    try:
        while True:
            try:
                snapshot = refresh_from_chain(path, wallet)
                errors = 0
                print(f"[{utc_now_iso()}] published")
                print(_describe(snapshot))
            except (ArcError, OSError, ValueError) as exc:
                errors += 1
                # Deliberately no fallback write: a stale snapshot must go
                # stale, so the gateway refuses to sell it.
                print(f"  ! publish failed ({errors}/{max_errors}): {exc}", file=sys.stderr)
                if errors >= max_errors:
                    print("  X too many consecutive failures - stopping.", file=sys.stderr)
                    return 1
            sleep_t = min(interval * (2 ** min(errors, 4)), 300)
            time.sleep(sleep_t)
    except KeyboardInterrupt:
        print("\nstopped.")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=DEFAULT_OUT)
    parser.add_argument("--wallet", default=None)
    parser.add_argument("--watch", action="store_true")
    parser.add_argument(
        "--interval",
        type=int,
        default=config.ARC_REBALANCE_CONFIG.monitor_interval,
        help="seconds between publishes in --watch mode",
    )
    parser.add_argument("--print", dest="do_print", action="store_true")
    args = parser.parse_args(argv)

    if args.watch:
        return run_watch(args.out, args.interval, args.wallet)

    try:
        snapshot = refresh_from_chain(args.out, args.wallet)
    except (ArcError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.do_print:
        print(json.dumps(snapshot, indent=2, ensure_ascii=False))
    print(f"snapshot written: {args.out}")
    print(_describe(snapshot))
    return 0


if __name__ == "__main__":
    sys.exit(main())
