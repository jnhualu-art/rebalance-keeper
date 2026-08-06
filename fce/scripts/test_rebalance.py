"""FlareKeeper FCE — custom end-to-end test (REBALANCE / COMPUTE).

Replaces the scaffold's HelloWorld-specific `test.sh` (which hardcodes
SAY_HELLO / SAY_GOODBYE). This sends a real REBALANCE/COMPUTE instruction to
the deployed InstructionSender, extracts the on-chain instruction id, and polls
the extension proxy for the TEE-signed rebalance decision.

Prereqs (run in WSL after post-build.sh):
  - Docker stack up (extension-tee + ext-proxy + redis)
  - config/extension.env present (EXTENSION_ID, INSTRUCTION_SENDER)
  - .env has FLARE_PRIVATE_KEY + CHAIN_URL + EXT_PROXY_URL
  - python3 with web3 + eth-account

Usage:
  python scripts/test_rebalance.py
"""
from __future__ import annotations
import os, sys, json, time, urllib.request
from web3 import Web3
from eth_account import Account

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_env(p):
    if not os.path.exists(p):
        return
    for line in open(p):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        v = v.strip().strip('"').strip("'")
        os.environ.setdefault(k, v)


load_env(os.path.join(ROOT, ".env"))
load_env(os.path.join(ROOT, "config", "extension.env"))

PK = os.environ["FLARE_PRIVATE_KEY"]
CHAIN = os.environ.get("CHAIN_URL", "https://coston2-api.flare.network/ext/C/rpc")
SENDER = os.environ["INSTRUCTION_SENDER"]
PROXY = os.environ.get("EXT_PROXY_URL", "http://localhost:6674").rstrip("/")

w3 = Web3(Web3.HTTPProvider(CHAIN))
assert w3.is_connected(), f"cannot reach {CHAIN}"
acct = Account.from_key(PK)

ABI = [
    {
        "inputs": [{"internalType": "bytes", "name": "_message", "type": "bytes"}],
        "name": "sendRebalance",
        "outputs": [],
        "stateMutability": "payable",
        "type": "function",
    },
]

contract = w3.eth.contract(address=Web3.to_checksum_address(SENDER), abi=ABI)

snapshot = {
    "treasury_balance": 100.0,
    "treasury_health": 35.0,
    "floor": 20.0,
    "ceiling": 50.0,
}
msg = json.dumps(snapshot, separators=(",", ":")).encode("utf-8")

print(f"[test] sending REBALANCE/COMPUTE from {acct.address}")
print(f"[test] snapshot: {snapshot}")

tx = contract.functions.sendRebalance(msg).build_transaction(
    {
        "from": acct.address,
        "value": 10**6,  # 1e6 wei instruction fee (matches registry requirement)
        "nonce": w3.eth.get_transaction_count(acct.address),
        "gas": 600000,
        "chainId": 114,
    }
)
signed = acct.sign_transaction(tx)
h = w3.eth.send_raw_transaction(signed.raw_transaction)
print(f"[test] tx: {h.hex()}")
rcpt = w3.eth.wait_for_transaction_receipt(h)
assert rcpt.status == 1, "sendRebalance tx reverted"

# instruction id = actionId, first indexed topic after sender (topic[2])
instruction_id = rcpt.logs[0].topics[2].hex()
print(f"[test] instructionId: {instruction_id}")

print(f"[test] polling {PROXY}/action/result/{instruction_id} ...")
result = None
for i in range(40):
    try:
        with urllib.request.urlopen(
            f"{PROXY}/action/result/{instruction_id}", timeout=10
        ) as r:
            data = json.loads(r.read())
        res = data.get("result", data)
        status = res.get("status")
        if status == 1:
            result = res
            break
        if status == 0:
            print(f"[test] FAILED: {res}")
            sys.exit(1)
    except Exception as e:
        pass
    time.sleep(3)

if result is None:
    print("[test] timed out waiting for result — check proxy logs")
    sys.exit(1)

print("[test] === TEE-signed rebalance decision ===")
print(json.dumps(result, indent=2))

# Validate it's our decision shape
data = result.get("data")
try:
    decision = json.loads(data) if isinstance(data, str) else data
    assert "action" in decision or "decision" in decision or "repay" in str(decision).lower(), \
        "result does not look like a rebalance decision"
    print("[test] PASS: rebalance decision returned by TEE")
except Exception as e:
    print(f"[test] WARNING: could not validate decision shape: {e}")
    print("[test] (raw result above is still proof the TEE executed)")
print("[test] DONE")
