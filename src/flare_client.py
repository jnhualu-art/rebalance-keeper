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
import urllib.request
import urllib.error
from typing import Dict, Optional


class FlareError(Exception):
    """Raised when a Flare RPC call fails."""


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

    # ── position snapshot ──────────────────────────────────────
    def get_position(self, address: str, floor_usdc: float = 50.0) -> Dict:
        """Read a treasury position: real on-chain USDC + health metric."""
        usdc = self.get_usdc_balance(address)
        native = self.get_native_balance(address)
        health = (usdc / floor_usdc) if floor_usdc > 0 else float("inf")
        return {
            "address": address,
            "usdc_balance": usdc,
            "native_flr_balance": native,  # gas side
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
