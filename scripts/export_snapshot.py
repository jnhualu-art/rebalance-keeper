#!/usr/bin/env python3
"""
export_snapshot.py — publish the live Arc treasury position for the x402 gateway.

Thin CLI wrapper around src.snapshot_publisher, which holds the implementation.
Kept as a script so the documented one-liner stays short:

    python scripts/export_snapshot.py                 # publish once
    python scripts/export_snapshot.py --watch         # keep it fresh
    python scripts/export_snapshot.py --print         # also echo the JSON

The gateway refuses to sell a snapshot older than SNAPSHOT_TTL_SECONDS (300s by
default), so for anything longer than a quick demo run use --watch, or run the
rebalancer's own watch loop, which publishes every cycle.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.snapshot_publisher import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
