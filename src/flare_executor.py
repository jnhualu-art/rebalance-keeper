"""
FlareKeeper — Flare (Coston2) transaction executor.

Signs and broadcasts the rebalance the TEE decided, and — the novel part for
the Confidential Compute bounty — *anchors the attestation on-chain* so the
decision is publicly verifiable ("this move came from the attested strategy").

Two transfer modes (see config.FLARE_ASSET_MODE):
  - native  : move native C2FLR via the tx `value` field (runs today with a
              faucet claim, no token contract needed).
  - erc20   : move an ERC-20 stable (USDT0/USDC) via transfer(address,uint256).

Signing uses `eth_account`; keys come from .env (FLARE_PRIVATE_KEY for the
operational wallet, FLARE_RESERVE_PRIVATE_KEY for the reserve) and are NEVER
committed. Flare is EVM-compatible (chainId 114) with EIP-1559 support, so this
mirrors src/arc_executor.py's type-2 fee handling.
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


class FlareExecutorError(Exception):
    """Raised when a Flare transaction fails to build or broadcast."""


class FlareExecutor:
    """Signs and sends value transfers (native or ERC-20) on Flare/Coston2."""

    def __init__(
        self,
        rpc_url: str = None,
        chain_id: int = None,
        usdc_address: str = None,
    ):
        self.rpc_url = rpc_url or config.FLARE_RPC_URL
        self.chain_id = chain_id or config.FLARE_CHAIN_ID
        self.usdc_address = (usdc_address or config.FLARE_USDC_ERC20 or "").lower()
        self._account_cache = {}

    # ── account handling ────────────────────────────────────────
    def _load_account(self, private_key: str) -> LocalAccount:
        if private_key in self._account_cache:
            return self._account_cache[private_key]
        if not private_key:
            raise FlareExecutorError(
                "Private key is empty. Set FLARE_PRIVATE_KEY "
                "(or FLARE_RESERVE_PRIVATE_KEY) in .env."
            )
        if not private_key.startswith("0x"):
            private_key = "0x" + private_key
        try:
            acct = Account.from_key(private_key)
        except Exception as e:
            raise FlareExecutorError(f"Invalid private key: {e}")
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
            raise FlareExecutorError(f"HTTP {e.code}: {e.reason}")
        except urllib.error.URLError as e:
            raise FlareExecutorError(f"Network error: {e.reason}")
        if "error" in data:
            raise FlareExecutorError(str(data["error"]))
        return data.get("result")

    # ── EIP-1559 fee discovery (mirrors ArcExecutor) ────────────
    def _get_fee_params(self) -> tuple:
        """Return (max_fee_per_gas, max_priority_fee_per_gas) as ints (wei)."""
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
            try:
                gp = int(self._rpc("eth_gasPrice", []), 16)
            except Exception:
                gp = 10 ** 10  # 10 gwei
            max_fee = 2 * gp + priority
        max_fee = max(max_fee, priority)
        return max_fee, priority

    def _nonce(self, address: str) -> int:
        return int(self._rpc("eth_getTransactionCount", [address, "pending"]), 16)

    # ── transaction building ────────────────────────────────────
    def build_transfer(self, from_address: str, to_address: str, amount: float) -> dict:
        """Build (unsigned) a treasury transfer tx in the configured asset mode.

        native mode : send `amount` C2FLR via the `value` field.
        erc20 mode  : send `amount` tokens via transfer(address,uint256).
        """
        max_fee, priority = self._get_fee_params()
        base = {
            "from": from_address,
            "chainId": self.chain_id,
            "nonce": self._nonce(from_address),
            "maxFeePerGas": "0x" + hex(max_fee)[2:],
            "maxPriorityFeePerGas": "0x" + hex(priority)[2:],
            "type": "0x2",
        }

        if config.FLARE_ASSET_MODE == "erc20":
            if not self.usdc_address:
                raise FlareExecutorError(
                    "FLARE_ASSET_MODE=erc20 but FLARE_USDC_ERC20 is unset."
                )
            value = int(round(amount * (10 ** config.FLARE_USDC_DECIMALS)))
            if value <= 0:
                raise FlareExecutorError(f"Amount too small: {amount}")
            data = (
                TRANSFER_SELECTOR
                + to_address[2:].lower().rjust(64, "0")
                + hex(value)[2:].rjust(64, "0")
            )
            base.update({
                "to": self.usdc_address,
                "value": "0x0",
                "data": data,
                "gas": "0x" + hex(100_000)[2:],   # ERC-20 transfer
            })
        else:
            value = int(round(amount * (10 ** config.FLARE_NATIVE_DECIMALS)))
            if value <= 0:
                raise FlareExecutorError(f"Amount too small: {amount}")
            base.update({
                "to": to_address,
                "value": "0x" + hex(value)[2:],
                "data": "0x",
                "gas": "0x" + hex(21_000)[2:],     # plain native transfer
            })
        return base

    def build_anchor(self, from_address: str, memo_hex: str, to_address: str = None) -> dict:
        """Build (unsigned) a 0-value tx carrying `memo_hex` (the attestation).

        Defaults to a self-transfer (from == to) so it's free of side effects
        beyond publishing the attestation in calldata for anyone to verify.
        """
        to = (to_address or config.FLARE_ANCHOR_ADDRESS or from_address)
        if not memo_hex.startswith("0x"):
            memo_hex = "0x" + memo_hex
        max_fee, priority = self._get_fee_params()
        # 21000 base + 16 gas/non-zero byte; pad generously for the memo.
        gas = 21_000 + 16 * ((len(memo_hex) - 2) // 2) + 5_000
        return {
            "from": from_address,
            "to": to,
            "value": "0x0",
            "data": memo_hex,
            "chainId": self.chain_id,
            "nonce": self._nonce(from_address),
            "gas": "0x" + hex(gas)[2:],
            "maxFeePerGas": "0x" + hex(max_fee)[2:],
            "maxPriorityFeePerGas": "0x" + hex(priority)[2:],
            "type": "0x2",
        }

    # ── signing / broadcast ─────────────────────────────────────
    def sign_and_send(self, tx: dict, private_key: str) -> str:
        acct = self._load_account(private_key)
        signed = acct.sign_transaction(tx)
        raw = signed.raw_transaction.hex()
        if not raw.startswith("0x"):
            raw = "0x" + raw
        return self._rpc("eth_sendRawTransaction", [raw])

    # ── high-level helpers ──────────────────────────────────────
    def transfer(
        self,
        from_address: str,
        to_address: str,
        amount: float,
        private_key: str,
        dry_run: bool = False,
    ) -> dict:
        """Move `amount` of the treasury asset from → to."""
        tx = self.build_transfer(from_address, to_address, amount)
        if dry_run:
            return {"dry_run": True, "from": from_address, "to": to_address,
                    "amount": amount, "asset": config.flare_treasury_symbol(), "tx": tx}
        tx_hash = self.sign_and_send(tx, private_key)
        return {
            "tx_hash": tx_hash,
            "from": from_address,
            "to": to_address,
            "amount": amount,
            "asset": config.flare_treasury_symbol(),
            "explorer": self.explorer_tx(tx_hash),
        }

    def anchor_attestation(
        self,
        from_address: str,
        attestation: str,
        private_key: str,
        dry_run: bool = False,
    ) -> dict:
        """Publish the TEE `attestation` string on-chain (calldata of a 0-value tx).

        This is the verifiable half of the Confidential Compute story: the
        enclave-produced attestation is anchored on Flare so any observer /
        contract can confirm the rebalance came from the approved strategy.
        """
        memo_hex = "0x" + attestation.encode("utf-8").hex()
        tx = self.build_anchor(from_address, memo_hex)
        if dry_run:
            return {"dry_run": True, "anchor_from": from_address,
                    "attestation": attestation, "memo_hex": memo_hex, "tx": tx}
        tx_hash = self.sign_and_send(tx, private_key)
        return {
            "tx_hash": tx_hash,
            "anchor_from": from_address,
            "attestation": attestation,
            "explorer": self.explorer_tx(tx_hash),
        }

    def explorer_tx(self, tx_hash: str) -> str:
        return f"{config.FLARE_EXPLORER}/tx/{tx_hash}"
