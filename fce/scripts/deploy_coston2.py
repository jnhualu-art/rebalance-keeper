#!/usr/bin/env python3
"""
Deploy FlareKeeperVerifier to Flare Coston2 and exercise on-chain verification.

The Verifier is a STANDALONE contract (no dependency on Flare's system
TeeExtensionRegistry/TeeMachineRegistry), so it deploys cleanly on Coston2
today. FlareKeeperInstructionSender is deployed as part of FCC extension
registration via the official scaffold tooling (which supplies the system
contract addresses).

Requires (in .env or environment):
  FLARE_PRIVATE_KEY  a funded Coston2 account (faucet: https://faucet.flare.network/coston2)
  FLARE_RPC_URL      defaults to https://coston2-api.flare.network/ext/C/rpc

The script uses py-solc-x to compile (auto-installs solc 0.8.27 on first run).
"""

from __future__ import annotations

import os
import sys

from web3 import Web3
from eth_account import Account

RPC_URL = os.getenv("FLARE_RPC_URL", "https://coston2-api.flare.network/ext/C/rpc")
PRIVATE_KEY = os.getenv("FLARE_PRIVATE_KEY", "")
CHAIN_ID = 114  # Coston2

_CONTRACT_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "contracts", "FlareKeeperVerifier.sol"
)


def _compile_verifier():
    try:
        import solcx
    except ImportError:
        print("py-solc-x not installed. Run: pip install py-solc-x")
        raise
    solcx.install_solc("0.8.27")
    compiled = solcx.compile_files(
        [os.path.abspath(_CONTRACT_PATH)], solc_version="0.8.27",
        output_values=["abi", "bin"],
    )
    key = [k for k in compiled if k.endswith("FlareKeeperVerifier.sol:FlareKeeperVerifier")][0]
    return compiled[key]["abi"], compiled[key]["bin"]


def _w3():
    w3 = Web3(Web3.HTTPProvider(RPC_URL))
    if not w3.is_connected():
        raise RuntimeError(f"cannot connect to {RPC_URL}")
    return w3


def deploy_verifier(tee_private_key: str) -> str:
    """Deploy FlareKeeperVerifier; set its teeAddress to the (demo) TEE key.

    Returns the deployed contract address.
    """
    if not PRIVATE_KEY:
        raise RuntimeError("FLARE_PRIVATE_KEY not set — cannot deploy on-chain.")
    w3 = _w3()
    abi, bin_ = _compile_verifier()
    acct = Account.from_key(PRIVATE_KEY)
    tee_address = Account.from_key(tee_private_key).address

    contract = w3.eth.contract(abi=abi, bytecode=bin_)
    tx = contract.constructor().build_transaction({
        "from": acct.address,
        "nonce": w3.eth.get_transaction_count(acct.address),
        "gas": 2_000_000,
        "gasPrice": w3.eth.gas_price,
        "chainId": CHAIN_ID,
    })
    signed = acct.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    rcpt = w3.eth.wait_for_transaction_receipt(tx_hash)
    addr = rcpt.contractAddress

    # set teeAddress so the verifier accepts the TEE signature
    vcontract = w3.eth.contract(address=addr, abi=abi)
    tx2 = vcontract.functions.setTeeAddress(tee_address).build_transaction({
        "from": acct.address,
        "nonce": w3.eth.get_transaction_count(acct.address),
        "gas": 100_000,
        "gasPrice": w3.eth.gas_price,
        "chainId": CHAIN_ID,
    })
    signed2 = acct.sign_transaction(tx2)
    w3.eth.send_raw_transaction(signed2.raw_transaction)
    w3.eth.wait_for_transaction_receipt(signed2.hash)
    return addr


def verify_on_chain(verifier_addr: str, action_id: bytes, submission_tag: bytes,
                    result_data: bytes, status: int, signature: bytes,
                    tee_private_key: str) -> bool:
    """Call verifyDecision() on-chain and return whether it was accepted."""
    w3 = _w3()
    abi, _ = _compile_verifier()
    vcontract = w3.eth.contract(address=Web3.to_checksum_address(verifier_addr), abi=abi)

    r = signature[0:32]
    s = signature[32:64]
    v = signature[64]
    acct = Account.from_key(PRIVATE_KEY)
    tx = vcontract.functions.verifyDecision(
        action_id, submission_tag, result_data, status, v, r, s
    ).build_transaction({
        "from": acct.address,
        "nonce": w3.eth.get_transaction_count(acct.address),
        "gas": 200_000,
        "gasPrice": w3.eth.gas_price,
        "chainId": CHAIN_ID,
    })
    signed = acct.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    rcpt = w3.eth.wait_for_transaction_receipt(tx_hash)
    if rcpt.status != 1:
        return False
    decision_hash = vcontract.functions.computeDecisionHash(
        action_id, submission_tag, result_data, status
    ).call()
    return vcontract.functions.isDecisionVerified(decision_hash).call()


if __name__ == "__main__":
    tee_key = "0x" + "11" * 32
    addr = deploy_verifier(tee_key)
    print(f"FlareKeeperVerifier deployed at {addr}")
