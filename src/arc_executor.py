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

from decimal import Decimal, InvalidOperation
from typing import Optional

from eth_account import Account
from eth_account.signers.local import LocalAccount

from src import config
from src.arc_rpc import ArcRPC, ArcRPCError


# ERC-20 function selectors
TRANSFER_SELECTOR = "0xa9059cbb"   # transfer(address,uint256)

# Largest value a 32-byte EVM word can hold. Guards calldata encoding.
MAX_UINT256 = (1 << 256) - 1

_HEX_DIGITS = frozenset("0123456789abcdefABCDEF")


def _validate_address(value: str, label: str) -> str:
    """Validate an EVM address and return it lower-cased, without the 0x.

    Downstream encoders assume exactly 20 bytes. A malformed address would
    otherwise be padded into syntactically valid but semantically wrong
    calldata, which is the kind of bug that only shows up on-chain.
    """
    if not isinstance(value, str):
        raise ArcExecutorError(f"{label} must be a hex string")
    addr = value.strip()
    if addr[:2] in ("0x", "0X"):
        addr = addr[2:]
    if len(addr) != 40 or any(c not in _HEX_DIGITS for c in addr):
        raise ArcExecutorError(f"{label} is not a valid 20-byte address")
    return addr.lower()


def _encode_word(hex_no_prefix: str, label: str) -> str:
    """Left-pad a hex string (no 0x) into a 32-byte word.

    Refuses values wider than 32 bytes instead of silently truncating.
    """
    if len(hex_no_prefix) > 64:
        raise ArcExecutorError(f"{label} exceeds 32 bytes and cannot be encoded")
    return hex_no_prefix.rjust(64, "0")


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
        self._rpc_client = ArcRPC(rpc_url)
        self.chain_id = chain_id or config.ARC_CHAIN_ID
        # Fail fast on a malformed token address, but keep the 0x-prefixed
        # form because tx["to"] is handed to the signer as-is.
        raw_usdc = (usdc_address or config.ARC_USDC_ERC20).lower()
        _validate_address(raw_usdc, "usdc_address")
        self.usdc_address = raw_usdc

    @property
    def rpc_url(self) -> str:
        """Currently active RPC endpoint (read-only)."""
        return self._rpc_client.rpc_url

    # ── account handling ────────────────────────────────────────
    @staticmethod
    def _load_account(private_key: str) -> LocalAccount:
        """Load a local account from a hex private key (0x-prefixed).

        Deliberately not cached. The previous implementation keyed an
        in-memory dict by the private key itself, which keeps key material
        reachable from a traceback, a debugger or an accidental repr.
        Deriving an account costs ~1ms and transfers are infrequent, so
        correctness beats that micro-optimisation here.
        """
        if not private_key:
            raise ArcExecutorError(
                "Private key is empty. Set ARC_PRIVATE_KEY (or ARC_RESERVE_PRIVATE_KEY) in .env."
            )
        key = private_key if private_key.startswith("0x") else "0x" + private_key
        try:
            return Account.from_key(key)
        except Exception as exc:
            # Never echo key material back in an error message.
            raise ArcExecutorError(f"Invalid private key ({type(exc).__name__})")

    # ── low-level RPC ───────────────────────────────────────────
    def _rpc(self, method: str, params: list) -> str:
        """Delegate to the shared transport, preserving ArcExecutorError."""
        try:
            return self._rpc_client.call(method, params)
        except ArcRPCError as exc:
            raise ArcExecutorError(str(exc)) from exc

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
    def _to_base_units(self, amount_usdc) -> int:
        """Convert a USDC amount into 6-decimal base units.

        Uses Decimal, not float: binary floats cannot represent values like
        0.1 exactly, so float rounding can silently shift a transfer by a
        base unit. Sub-unit precision is rejected rather than truncated.
        """
        try:
            amount = Decimal(str(amount_usdc))
        except (InvalidOperation, ValueError):
            raise ArcExecutorError("amount_usdc must be a number")
        if not amount.is_finite():
            raise ArcExecutorError("amount_usdc must be finite")
        if amount <= 0:
            raise ArcExecutorError(f"Amount must be positive, got {amount_usdc}")

        scaled = amount.scaleb(config.ARC_USDC_DECIMALS)
        units = int(scaled)
        if scaled != units:
            raise ArcExecutorError(
                f"Amount {amount_usdc} carries more precision than "
                f"{config.ARC_USDC_DECIMALS} decimals; refusing to truncate silently"
            )
        if units > MAX_UINT256:
            raise ArcExecutorError("Amount exceeds uint256 range")
        return units

    def build_transfer(self, from_address: str, to_address: str, amount_usdc: float) -> dict:
        """Build (but do not sign) an ERC-20 USDC transfer transaction dict."""
        to_hex = _validate_address(to_address, "to_address")
        from_hex = _validate_address(from_address, "from_address")
        value = self._to_base_units(amount_usdc)

        data = (
            TRANSFER_SELECTOR
            + _encode_word(to_hex, "to_address")
            + _encode_word(format(value, "x"), "amount")
        )
        max_fee, priority = self._get_fee_params()
        tx = {
            "from": "0x" + from_hex,
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
