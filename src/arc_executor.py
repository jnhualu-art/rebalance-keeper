"""
ArcKeeper — Arc Testnet transaction executor (autonomous rebalancing).

Signs and broadcasts ERC-20 USDC transfers on Arc Testnet so the agent can
rebalance its treasury *without a human in the loop*. This is the execution
half of the Agentic Economy pattern: the monitor decides, this module acts.

Signing uses `eth_account` (installed in the managed venv). The private key
is read from `.env` (ARC_PRIVATE_KEY for the operational wallet,
ARC_RESERVE_PRIVATE_KEY for the reserve wallet) and is NEVER committed.

Arc is EVM-compatible (chainId 5042002). A USDC transfer is a standard
ERC-20 `transfer(address,uint256)` call to 0x3600...0000.
"""

import json
import urllib.request
import urllib.error
from typing import Optional

from eth_account import Account
from eth_account.signers.local import LocalAccount

from src import config


# ERC-20 function selectors
TRANSFER_SELECTOR = "0xa9059cbb"   # transfer(address,uint256)


class ArcExecutorError(Exception):
    """Raised when an Arc transaction fails to build or broadcast."""


class ArcExecutor:
    """Signs and sends USDC transfers on Arc Testnet."""

    def __init__(
        self,
        rpc_url: str = None,
        chain_id: int = None,
        usdc_address: str = None,
    ):
        self.rpc_url = rpc_url or config.ARC_RPC_URL
        self.chain_id = chain_id or config.ARC_CHAIN_ID
        self.usdc_address = (usdc_address or config.ARC_USDC_ERC20).lower()
        self._account_cache = {}

    # ── account handling ────────────────────────────────────────
    def _load_account(self, private_key: str) -> LocalAccount:
        """Load a local account from a hex private key (0x-prefixed)."""
        if private_key in self._account_cache:
            return self._account_cache[private_key]
        if not private_key:
            raise ArcExecutorError(
                "Private key is empty. Set ARC_PRIVATE_KEY (or ARC_RESERVE_PRIVATE_KEY) in .env."
            )
        if not private_key.startswith("0x"):
            private_key = "0x" + private_key
        try:
            acct = Account.from_key(private_key)
        except Exception as e:
            raise ArcExecutorError(f"Invalid private key: {e}")
        self._account_cache[private_key] = acct
        return acct

    # ── low-level RPC ───────────────────────────────────────────
    def _rpc(self, method: str, params: list) -> str:
        body = json.dumps(
            {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        ).encode()
        req = urllib.request.Request(
            self.rpc_url,
            data=body,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = json.load(resp)
        except urllib.error.HTTPError as e:
            raise ArcExecutorError(f"HTTP {e.code}: {e.reason}")
        except urllib.error.URLError as e:
            raise ArcExecutorError(f"Network error: {e.reason}")
        if "error" in data:
            raise ArcExecutorError(str(data["error"]))
        return data.get("result")

    # ── EIP-1559 fee discovery ──────────────────────────────────
    def _get_fee_params(self) -> tuple:
        """Return (max_fee_per_gas, max_priority_fee_per_gas) as ints (wei).

        type-2 (EIP-1559) txs must use these instead of the legacy
        `gasPrice`. Probe the chain for base fee + priority fee, add a
        buffer, and fall back to sane defaults if the RPC lacks support.
        """
        try:
            priority = int(self._rpc("eth_maxPriorityFeePerGas", []), 16)
        except Exception:
            priority = 10 ** 9  # 1 gwei
        try:
            block = self._rpc("eth_getBlockByNumber", ["latest", False])
            base_fee = int(block.get("baseFeePerGas", "0x0"), 16)
        except Exception:
            base_fee = 0
        if base_fee:
            max_fee = 2 * base_fee + priority
        else:
            # No EIP-1559 base fee reported → base it on eth_gasPrice.
            try:
                gp = int(self._rpc("eth_gasPrice", []), 16)
            except Exception:
                gp = 10 ** 10  # 10 gwei
            max_fee = 2 * gp + priority
        max_fee = max(max_fee, priority)  # never submit 0
        return max_fee, priority

    # ── transaction building ────────────────────────────────────
    def build_transfer(self, from_address: str, to_address: str, amount_usdc: float) -> dict:
        """Build (but do not sign) an ERC-20 USDC transfer transaction dict."""
        value = int(round(amount_usdc * (10 ** config.ARC_USDC_DECIMALS)))
        if value <= 0:
            raise ArcExecutorError(f"Amount too small: {amount_usdc} USDC")
        data = TRANSFER_SELECTOR + to_address[2:].lower().rjust(64, "0") + hex(value)[2:].rjust(64, "0")
        max_fee, priority = self._get_fee_params()
        tx = {
            "from": from_address,
            "to": self.usdc_address,
            "value": "0x0",
            "data": data,
            "chainId": self.chain_id,
            "nonce": int(self._rpc("eth_getTransactionCount", [from_address, "pending"]), 16),
            "gas": "0x" + hex(100_000)[2:],            # 100k gas for ERC-20 transfer
            "maxFeePerGas": "0x" + hex(max_fee)[2:],
            "maxPriorityFeePerGas": "0x" + hex(priority)[2:],
            "type": "0x2",                             # EIP-1559 — Arc supports it
        }
        return tx

    def sign_and_send(self, tx: dict, private_key: str) -> str:
        """Sign a raw transaction and broadcast it; return the tx hash."""
        acct = self._load_account(private_key)
        # Strip keys the signer derives itself
        signed = acct.sign_transaction(tx)
        raw = signed.raw_transaction.hex()
        if not raw.startswith("0x"):
            raw = "0x" + raw
        tx_hash = self._rpc("eth_sendRawTransaction", [raw])
        return tx_hash

    # ── high-level helpers ──────────────────────────────────────
    def transfer_usdc(
        self,
        from_address: str,
        to_address: str,
        amount_usdc: float,
        private_key: str,
        dry_run: bool = False,
    ) -> dict:
        """Transfer `amount_usdc` from `from_address` to `to_address`.

        Returns a dict with the tx hash (or the unsigned tx if dry_run).
        """
        tx = self.build_transfer(from_address, to_address, amount_usdc)
        if dry_run:
            return {"dry_run": True, "from": from_address, "to": to_address,
                    "amount_usdc": amount_usdc, "tx": tx}
        tx_hash = self.sign_and_send(tx, private_key)
        return {
            "tx_hash": tx_hash,
            "from": from_address,
            "to": to_address,
            "amount_usdc": amount_usdc,
            "explorer": f"{config.ARC_EXPLORER}/tx/{tx_hash}",
        }

    def explorer_tx(self, tx_hash: str) -> str:
        return f"{config.ARC_EXPLORER}/tx/{tx_hash}"
