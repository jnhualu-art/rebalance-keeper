"""★ MAIN CUSTOMIZATION POINT: FlareKeeper's rebalance handler.

Mirrors the scaffold's app/handlers.py. Each handler follows the 4-step
pattern: decode, validate, execute, respond.

  (original_message_hex) -> (data_hex_or_None, status, error_or_None)
  status 0 = error, 1 = success. See docs/extension-contract.md §4.6.

This handler runs INSIDE the TEE. The tee-node signs the ActionResult with the
TEE identity key, so the returned decision is attestable on-chain. The strategy
logic itself never leaves the enclave — only the decision result does.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from base.encoding import bytes_to_hex, hex_to_bytes
from base.types import Framework

from .config import (
    OP_COMMAND_COMPUTE,
    OP_TYPE_REBALANCE,
    VERSION,
)
from .strategy import evaluate

logger = logging.getLogger(__name__)

# --- Extension state ---------------------------------------------------------
# Serialized by the framework; no locking needed here.
_last_request: dict = {}
_last_decision: dict = {}


def reset_state() -> None:
    """Reset all state. Used by tests; not part of the wire contract."""
    global _last_request, _last_decision
    _last_request = {}
    _last_decision = {}


def register(framework: Framework) -> None:
    """Wire handlers to (opType, opCommand) pairs."""
    framework.handle(OP_TYPE_REBALANCE, OP_COMMAND_COMPUTE, handle_compute)


def report_state() -> Any:
    """Snapshot returned by GET /state."""
    return {
        "version": VERSION,
        "lastRequest": _last_request,
        "lastDecision": _last_decision,
    }


def handle_compute(msg: str) -> tuple[Optional[str], int, Optional[str]]:
    """REBALANCE/COMPUTE — treasury snapshot in, attested decision out.

    Request  (hex JSON): {"treasury_balance": float, "treasury_health": float,
                          "floor": float?, "ceiling": float?}
    Response (hex JSON): {"zone": str, "action": str, "amount": float,
                          "reason": str}
    """
    global _last_request, _last_decision

    # 1. Decode
    try:
        raw = hex_to_bytes(msg)
    except ValueError as e:
        return None, 0, f"decoding request: invalid hex: {e}"

    try:
        req = json.loads(raw)
    except (json.JSONDecodeError, ValueError) as e:
        return None, 0, f"decoding request: {e}"

    if not isinstance(req, dict):
        return None, 0, "decoding request: expected a JSON object"

    # 2. Validate
    try:
        treasury_balance = float(req["treasury_balance"])
        treasury_health = float(req["treasury_health"])
    except (KeyError, TypeError, ValueError):
        return None, 0, "treasury_balance and treasury_health are required numbers"

    floor = float(req.get("floor", 20.0))
    ceiling = float(req.get("ceiling", 50.0))
    if floor <= 0 or ceiling <= floor:
        return None, 0, "floor must be > 0 and ceiling must be > floor"

    # 3. Execute (the confidential brain)
    zone, dec = evaluate(treasury_balance, treasury_health, floor, ceiling)

    _last_request = {
        "treasury_balance": treasury_balance,
        "treasury_health": treasury_health,
        "floor": floor,
        "ceiling": ceiling,
    }
    _last_decision = {
        "zone": dec.zone,
        "action": dec.action,
        "amount": dec.amount,
        "reason": dec.reason,
    }

    # 4. Respond
    resp = {
        "zone": dec.zone,
        "action": dec.action,
        "amount": dec.amount,
        "reason": dec.reason,
    }
    return bytes_to_hex(json.dumps(resp, separators=(",", ":")).encode("utf-8")), 1, None
