"""FlareKeeper FCE SDK — run the confidential rebalance handler + TEE signing.

This module is the shared seam between the enclave (where handle_compute runs
for real) and the agent loop (flare_tee.py). When run *outside* the enclave it
acts as a faithful local stand-in: it executes the exact same handler code the
enclave would, then signs the result with the TEE_ACTION_RESULT scheme so the
decision is verifiable by FlareKeeperVerifier — exactly as the tee-node would.

The signing key is the SIMULATED TEE key. In production the tee-node holds the
real enclave-generated key and signs inside the TEE; only the signature leaves.
"""

from __future__ import annotations

import json
import os
import sys

# Make `from base.../app...` resolvable whether imported from fce/python or elsewhere.
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from eth_utils import keccak  # noqa: E402
from eth_keys import keys  # noqa: E402
from eth_account import Account  # noqa: E402
from eth_account.messages import encode_defunct  # noqa: E402
from base.encoding import bytes_to_hex, hex_to_bytes  # noqa: E402
from app.handlers import handle_compute  # noqa: E402

# SIMULATED TEE identity key (demo). Replaced by the enclave's real key in prod.
TEE_PRIVATE_KEY = bytes.fromhex(os.getenv("FLARE_TEE_PRIVATE_KEY", "11" * 32))
TEE_ACTION_RESULT_BYTES32 = b"TEE_ACTION_RESULT".ljust(32, b"\x00")
CHAIN_ID = int(os.getenv("FLARE_CHAIN_ID", "114"))  # Coston2


def compute_decision(treasury_balance: float, treasury_health: float,
                     floor: float = 20.0, ceiling: float = 50.0) -> dict:
    """Run the confidential rebalance handler (the enclave code path)."""
    req = {
        "treasury_balance": treasury_balance,
        "treasury_health": treasury_health,
        "floor": floor,
        "ceiling": ceiling,
    }
    data_hex, status, err = handle_compute(
        bytes_to_hex(json.dumps(req, separators=(",", ":")).encode("utf-8")))
    if status != 1:
        raise RuntimeError(f"FCE handler error: {err}")
    return json.loads(hex_to_bytes(data_hex))


def sign_result(result_hash: bytes) -> bytes:
    """Sign a decision result the way the tee-node does (TEE_ACTION_RESULT).

    Uses the Ethereum personal_sign scheme (eth_account.sign_message), which is
    exactly what FlareKeeperVerifier's ecrecover expects: the message
    `payload_hash` is prefixed and hashed into `eth_signed`, and that is signed.
    """
    payload_hash = keccak(
        TEE_ACTION_RESULT_BYTES32 + CHAIN_ID.to_bytes(32, "big") + result_hash)
    acct = Account.from_key(TEE_PRIVATE_KEY)
    sm = acct.sign_message(encode_defunct(hexstr=payload_hash.hex()))
    return sm.signature  # 65 bytes r‖s‖v (v already 27/28)


def compute_and_sign(treasury_balance: float, treasury_health: float,
                    floor: float = 20.0, ceiling: float = 50.0):
    """Compute the decision AND produce a TEE-signed attestation.

    Returns (decision_dict, signature_hex, result_hash_hex).
    """
    decision = compute_decision(treasury_balance, treasury_health, floor, ceiling)
    result_data = hex_to_bytes(
        bytes_to_hex(json.dumps(decision, separators=(",", ":")).encode("utf-8")))
    # actionId/submissionTag are assigned by the instruction when relayed; we use
    # a deterministic placeholder so the attestation is reproducible locally.
    action_id = keccak(str(treasury_balance).encode() + b"|" + str(floor).encode())
    submission_tag = keccak(str(treasury_health).encode() + b"|" + str(ceiling).encode())
    status = 1
    result_hash = keccak(
        keccak(result_data) + action_id + keccak(submission_tag) + bytes([status]))
    signature = sign_result(result_hash)
    return decision, "0x" + signature.hex(), "0x" + result_hash.hex()
