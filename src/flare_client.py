"""
FlareKeeper — Flare network client (stdlib JSON-RPC, EVM compatible).

Flare is an EVM-compatible L1 focused on data protocols and *Confidential
Compute* (TEE-secured off-chain execution that attests results on-chain).
This client reads on-chain USDC balances so the agent can monitor its
treasury and decide rebalances — the same zero-dependency (urllib-only)
philosophy as the rest of RebalanceKeeper.

Verified network parameters (Flare docs / chainlist):
  - Coston2 (Flare testnet, recommended for hackathon):
        RPC      https://coston2-api.flare.network/ext/bc/C/rpc
        Chain ID 114
        Explorer https://coston2-explorer.flare.network
  - Flare mainnet:
        RPC      https://flare-api.flare.network/ext/bc/C/rpc
        Chain ID 14
        Explorer https://flare-explorer.flare.network
  - Songbird (canary):
        RPC      https://songbird-api.flare.network/ext/bc/C/rpc
        Chain ID 19

NOTE: the canonical USDC address on Flare must be verified against the
Flare token registry before mainnet use. For Coston2 testnet, use the
test-USDC faucet. Set FLARE_USDC_ERC20 in .env.
"""

import json
import re
import urllib.request
import urllib.error
from typing import Dict, Optional

from eth_utils import to_checksum_address


# A valid EVM address: 0x + 40 hex chars.
_ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")


class FlareError(Exception):
    """Raised when a Flare RPC call fails."""


def validate_address(address: str) -> str:
    """Return the EIP-55 checksum address if valid, else raise FlareError.

    Called before any signing so a malformed / truncated address can never
    end up in a real transaction. A checksum address (mixed-case) is required
    because eth_account.sign_transaction() validates that `from` matches the
    key's checksum address — a plain lower-cased `from` would be rejected.
    """
    if not isinstance(address, str) or not _ADDRESS_RE.match(address):
        raise FlareError(f"Invalid Flare address: {address!r}")
    return to_checksum_address(address)


class FlareClient:
    """Minimal EVM JSON-RPC client for Flare (Coston2 default)."""

    def __init__(
        self,
        rpc_url: str = None,
        chain_id: int = None,
        usdc_address: str = None,
    ):
        from src import config

        self.rpc_url = rpc_url or config.FLARE_RPC_URL
        self.chain_id = chain_id or config.FLARE_CHAIN_ID
        self.usdc_address = (usdc_address or config.FLARE_USDC_ERC20).lower()

    # ── safety: refuse to operate on a swapped / wrong RPC ─────
    def verify_chain(self) -> int:
        """Assert the RPC actually serves the chain we configured.

        A swapped/MITM RPC could lie about balances to trick the agent into
        rebalancing. We refuse to sign if eth_chainId != configured chainId.
        """
        rpc_id = int(self._rpc("eth_chainId", []), 16)
        if rpc_id != self.chain_id:
            raise FlareError(
                f"RPC chainId {rpc_id} != configured FLARE_CHAIN_ID "
                f"{self.chain_id}. Refusing to sign — possible RPC swap / "
                "wrong network."
            )
        return rpc_id

    # ── low-level RPC ──────────────────────────────────────────
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
            raise FlareError(f"HTTP {e.code}: {e.reason}")
        except urllib.error.URLError as e:
            raise FlareError(f"Network error: {e.reason}")
        if "error" in data:
            raise FlareError(str(data["error"]))
        return data.get("result")

    # ── chain / block queries ──────────────────────────────────
    def get_chain_id(self) -> int:
        return int(self._rpc("eth_chainId", []), 16)

    def get_block_number(self) -> int:
        return int(self._rpc("eth_blockNumber", []), 16)

    def get_native_balance(self, address: str) -> float:
        """Native FLR (18 decimals) gas balance."""
        raw = int(self._rpc("eth_getBalance", [address, "latest"]), 16)
        return raw / 1e18

    # ── ERC-20 USDC ────────────────────────────────────────────
    def _erc20_call(self, address: str, selector: str, args_hex: str = "") -> str:
        data = selector + args_hex
        return self._rpc(
            "eth_call",
            [{"to": self.usdc_address, "data": data}, "latest"],
        )

    @staticmethod
    def _enc_address(address: str) -> str:
        return address[2:].lower().rjust(64, "0")

    def get_usdc_balance(self, address: str) -> float:
        """USDC balance via ERC-20 balanceOf (6 decimals by default)."""
        from src import config

        res = self._erc20_call(address, "0x70a08231", self._enc_address(address))
        raw = int(res, 16)
        return raw / (10 ** config.FLARE_USDC_DECIMALS)

    # ── treasury asset (native C2FLR or ERC-20 stable) ─────────
    def get_treasury_balance(self, address: str) -> float:
        """Balance of the *treasury asset* for the configured mode.

        Coston2 has no canonical USDC, so the default treasury asset is native
        C2FLR (read via eth_getBalance). Set FLARE_ASSET_MODE=erc20 to track a
        stablecoin (USDT0/USDC) via balanceOf instead.
        """
        from src import config

        if config.FLARE_ASSET_MODE == "erc20":
            return self.get_usdc_balance(address)
        return self.get_native_balance(address)

    # ── position snapshot ──────────────────────────────────────
    def get_position(self, address: str, floor_usdc: float = 50.0) -> Dict:
        """Read a treasury position: real on-chain balance + health metric.

        `usdc_balance` holds the treasury-asset balance (native C2FLR by
        default, or the ERC-20 stable if FLARE_ASSET_MODE=erc20). The field
        name is kept for cross-chain compatibility with the Arc evaluator.
        """
        from src import config

        treasury = self.get_treasury_balance(address)
        native = self.get_native_balance(address)
        health = (treasury / floor_usdc) if floor_usdc > 0 else float("inf")
        return {
            "address": address,
            "usdc_balance": treasury,      # treasury asset (native or ERC-20)
            "native_flr_balance": native,  # gas side (always native C2FLR)
            "asset_mode": config.FLARE_ASSET_MODE,
            "asset_symbol": config.flare_treasury_symbol(),
            "floor_usdc": floor_usdc,
            "treasury_health": health,
            "block_number": self.get_block_number(),
            "chain_id": self.chain_id,
        }

    def explorer_tx(self, tx_hash: str) -> str:
        from src import config

        return f"{config.FLARE_EXPLORER}/tx/{tx_hash}"

    def explorer_address(self, address: str) -> str:
        from src import config

        return f"{config.FLARE_EXPLORER}/address/{address}"
