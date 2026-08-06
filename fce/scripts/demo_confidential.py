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
from eth_account import Account  # noqa: E402
from eth_account.messages import encode_defunct  # noqa: E402
from base.encoding import bytes_to_hex, hex_to_bytes  # noqa: E402
from app.handlers import handle_compute  # noqa: E402

# SIMULATED TEE identity key (demo only). In production this is generated inside
# the enclave at boot and never leaves it; here it stands in for the registered
# TEE machine identity so the on-chain verify step is reproducible.
TEE_PRIVATE_KEY = bytes.fromhex("11" * 32)
TEE_PUBLIC = keys.PrivateKey(TEE_PRIVATE_KEY).public_key.to_address()
TEE_ACTION_RESULT_BYTES32 = b"TEE_ACTION_RESULT".ljust(32, b"\x00")
CHAIN_ID = 114  # Coston2


def _load_dotenv(path=None):
    """Minimal CR-safe .env loader (no external deps). Sets only unset vars.

    Lets `python demo_confidential.py --onchain` pick up FLARE_PRIVATE_KEY and
    FLARE_RPC_URL from the repo-root .env without printing secrets.
    """
    if path is None:
        # repo root .env (rebalance-keeper/.env)
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".env")
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if k and k not in os.environ:
                os.environ[k] = v


_load_dotenv()


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
    """Simulate tee-node signing the ActionResult. Returns (payload_hash, sig65).

    Uses the Ethereum personal_sign scheme (eth_account.sign_message), which is
    exactly what the Solidity verifier's ecrecover expects: the message
    `payload_hash` is prefixed and hashed into `eth_signed`, and that is what
    gets signed. This matches the real Flare tee-node TEE_ACTION_RESULT signing.
    """
    payload_hash = keccak(
        TEE_ACTION_RESULT_BYTES32 + CHAIN_ID.to_bytes(32, "big") + result_hash)
    acct = Account.from_key(TEE_PRIVATE_KEY)
    sm = acct.sign_message(encode_defunct(hexstr=payload_hash.hex()))
    return payload_hash, sm.signature  # 65 bytes r‖s‖v (v already 27/28)


def _write_proof(verifier_addr, ok, action_id, submission_tag, result_hash, signature):
    """Persist the on-chain proof to JSON so the deployed address survives even
    if a later step crashes (buffered stdout would otherwise be lost)."""
    proof = {
        "network": "coston2",
        "chain_id": CHAIN_ID,
        "verifier_address": verifier_addr,
        "tee_address": TEE_PUBLIC,
        "action_id": "0x" + action_id.hex(),
        "submission_tag": "0x" + submission_tag.hex(),
        "result_hash": "0x" + result_hash.hex(),
        "signature": "0x" + signature.hex(),
        "verify_decision_accepted": bool(ok),
    }
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "coston2_proof.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(proof, f, indent=2)
    print(f"   proof written -> {out}")


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

    # Real offline check: recover the signer from the actual signature using the
    # same personal_sign scheme (recover_message pairs with sign_message).
    recovered = Account.recover_message(
        encode_defunct(hexstr=payload_hash.hex()),
        vrs=(signature[64], signature[0:32], signature[32:64]))
    print("\n== OFFLINE VERIFY ==")
    print(f"   recovered signer == teeAddress? {recovered.lower() == TEE_PUBLIC.lower()}")

    if onchain:
        print("\n== ON-CHAIN VERIFY (deploy FlareKeeperVerifier to Coston2) ==")
        sys.path.insert(0, _HERE)
        from deploy_coston2 import deploy_verifier, verify_on_chain
        try:
            verifier_addr = deploy_verifier(TEE_PRIVATE_KEY)
            print(f"   verifier@  = {verifier_addr}")
            ok = verify_on_chain(verifier_addr, action_id, submission_tag, result_data,
                                 status, signature)
            print(f"   on-chain verifyDecision() accepted TEE signature? {ok}")
            _write_proof(verifier_addr, ok, action_id, submission_tag, result_hash, signature)
        except Exception as e:
            # deploy_verifier already prints [deploy] tx; re-raise after flush
            print(f"   [ERROR] {e}")
            raise
    else:
        print("\n== ON-CHAIN VERIFY ==")
        print("   (skipped — run with --onchain + a funded Coston2 key in .env)")


if __name__ == "__main__":
    main()
