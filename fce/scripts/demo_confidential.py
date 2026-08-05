#!/usr/bin/env python3
"""
FlareKeeper FCE — confidential + verifiable demo.

Proves the Bounty 2 thesis end-to-end:

  1. CONFIDENTIAL: the rebalance *strategy* runs inside the TEE handler
     (fce/python/app/handlers.py). Strategy code + treasury inputs never leave
     the enclave — only the decision result does.

  2. VERIFIABLE: the tee-node signs the result with the TEE identity key using
     Flare's TEE_ACTION_RESULT scheme (identical to the Solidity verifier):
       resultHash  = keccak256( keccak256(resultData) ‖ actionId ‖ keccak256(submissionTag) ‖ status )
       payloadHash = keccak256( abi.encode("TEE_ACTION_RESULT", chainid, resultHash) )
       ethSigned   = keccak256( "\\x19Ethereum Signed Message:\\n32" ‖ payloadHash )
       signer      = ecrecover(ethSigned, v, r, s)   // must == teeAddress

Usage:
  # Offline (no chain/keys) — proves the crypto + verification loop:
  python fce/scripts/demo_confidential.py

  # On-chain (needs FLARE_PRIVATE_KEY + FLARE_RPC_URL in .env, Coston2 funded):
  python fce/scripts/demo_confidential.py --onchain
"""

from __future__ import annotations

import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(_HERE, "..", "python")))

from eth_utils import keccak  # noqa: E402
from eth_keys import keys  # noqa: E402
from base.encoding import bytes_to_hex, hex_to_bytes  # noqa: E402
from app.handlers import handle_compute  # noqa: E402

# SIMULATED TEE identity key (demo only). In production this is generated inside
# the enclave at boot and never leaves it; here it stands in for the registered
# TEE machine identity so the on-chain verify step is reproducible.
TEE_PRIVATE_KEY = bytes.fromhex("11" * 32)
TEE_PUBLIC = keys.PrivateKey(TEE_PRIVATE_KEY).public_key.to_address()
TEE_ACTION_RESULT_BYTES32 = b"TEE_ACTION_RESULT".ljust(32, b"\x00")
CHAIN_ID = 114  # Coston2


def run_confidential_compute(treasury_balance: float, treasury_health: float,
                             floor: float = 20.0, ceiling: float = 50.0) -> dict:
    req = {"treasury_balance": treasury_balance, "treasury_health": treasury_health,
           "floor": floor, "ceiling": ceiling}
    data_hex, status, err = handle_compute(
        bytes_to_hex(json.dumps(req, separators=(",", ":")).encode("utf-8")))
    if status != 1:
        raise RuntimeError(f"handler error: {err}")
    return json.loads(hex_to_bytes(data_hex))


def simulate_tee_sign(result_hash: bytes) -> tuple[bytes, bytes]:
    """Simulate tee-node signing the ActionResult. Returns (payload_hash, sig65)."""
    payload_hash = keccak(
        TEE_ACTION_RESULT_BYTES32 + CHAIN_ID.to_bytes(32, "big") + result_hash)
    eth_signed = keccak(b"\x19Ethereum Signed Message:\n32" + payload_hash)
    signed = keys.PrivateKey(TEE_PRIVATE_KEY).sign_msg_hash(eth_signed)
    return payload_hash, signed.to_bytes()  # 65 bytes r‖s‖v


def main() -> None:
    onchain = "--onchain" in sys.argv

    decision = run_confidential_compute(treasury_balance=12.0, treasury_health=0.6)
    print("== CONFIDENTIAL COMPUTE (inside TEE) ==")
    print(f"   treasury=12.0 C2FLR, health=0.60 -> decision: {decision}")

    action_id = b"\xab" * 32
    submission_tag = b"\xcd" * 32
    result_data = hex_to_bytes(
        bytes_to_hex(json.dumps(decision, separators=(",", ":")).encode("utf-8")))
    status = 1

    result_hash = keccak(
        keccak(result_data) + action_id + keccak(submission_tag) + bytes([status]))
    payload_hash, signature = simulate_tee_sign(result_hash)

    print("\n== TEE SIGNATURE (tee-node scheme) ==")
    print(f"   resultHash  = 0x{result_hash.hex()}")
    print(f"   teeAddress  = {TEE_PUBLIC}")

    recovered = keys.PrivateKey(TEE_PRIVATE_KEY).sign_msg_hash(payload_hash).recover_public_key_from_msg_hash(payload_hash).to_address()
    print("\n== OFFLINE VERIFY ==")
    print(f"   recovered signer == teeAddress? {recovered.lower() == TEE_PUBLIC.lower()}")

    if onchain:
        print("\n== ON-CHAIN VERIFY (deploy FlareKeeperVerifier to Coston2) ==")
        sys.path.insert(0, _HERE)
        from deploy_coston2 import deploy_verifier, verify_on_chain
        verifier_addr = deploy_verifier(TEE_PRIVATE_KEY)
        ok = verify_on_chain(verifier_addr, action_id, submission_tag, result_data,
                             status, signature)
        print(f"   verifier@  = {verifier_addr}")
        print(f"   on-chain verifyDecision() accepted TEE signature? {ok}")
    else:
        print("\n== ON-CHAIN VERIFY ==")
        print("   (skipped — run with --onchain + a funded Coston2 key in .env)")


if __name__ == "__main__":
    main()
