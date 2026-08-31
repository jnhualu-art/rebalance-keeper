"""
ArcKeeper — Arc Testnet client (stdlib JSON-RPC, EVM compatible).

Arc is Circle's stablecoin-native L1. USDC is the native gas token.
This client talks to the public Arc Testnet RPC using only the Python
standard library (urllib), matching the zero-dependency philosophy of the
rest of RebalanceKeeper. It reads on-chain USDC balances so the agent can
monitor its treasury and decide rebalances.

Key facts (verified against https://docs.arc.io):
  - RPC:      https://rpc.testnet.arc.network
  - Chain ID: 5042002
  - Explorer: https://testnet.arcscan.app
  - USDC ERC-20 interface: 0x3600000000000000000000000000000000000000 (6 decimals)
  - Native USDC gas uses 18 decimals; we standardise on the 6-decimal ERC-20 view.
"""

from typing import Dict, Optional

from src.arc_rpc import ArcRPC, ArcRPCError


class ArcError(Exception):
    """Raised when an Arc RPC call fails."""


class ArcClient:
    """Minimal EVM JSON-RPC client for Arc Testnet."""

    def __init__(
        self,
        rpc_url: str = None,
        chain_id: int = None,
        usdc_address: str = None,
    ):
        from src import config

        self._rpc_client = ArcRPC(rpc_url)
        self.chain_id = chain_id or config.ARC_CHAIN_ID
        self.usdc_address = (usdc_address or config.ARC_USDC_ERC20).lower()

    @property
    def rpc_url(self) -> str:
        """Currently active RPC endpoint (read-only)."""
        return self._rpc_client.rpc_url

    # ── low-level RPC ──────────────────────────────────────────
    def _rpc(self, method: str, params: list) -> str:
        """Delegate to the shared transport, preserving the ArcError contract."""
        try:
            return self._rpc_client.call(method, params)
        except ArcRPCError as exc:
            raise ArcError(str(exc)) from exc

    # ── chain / block queries ──────────────────────────────────
    def get_chain_id(self) -> int:
        return int(self._rpc("eth_chainId", []), 16)

    def get_block_number(self) -> int:
        return int(self._rpc("eth_blockNumber", []), 16)

    def get_native_balance(self, address: str) -> float:
        """Native USDC gas balance (18 decimals)."""
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
        """USDC balance via ERC-20 balanceOf (6 decimals)."""
        from src import config

        res = self._erc20_call(address, "0x70a08231", self._enc_address(address))
        raw = int(res, 16)
        return raw / (10 ** config.ARC_USDC_DECIMALS)

    # ── position snapshot ──────────────────────────────────────
    def get_position(self, address: str, floor_usdc: float = 50.0) -> Dict:
        """Read a treasury position: real on-chain USDC + health metric."""
        usdc = self.get_usdc_balance(address)
        native = self.get_native_balance(address)
        health = (usdc / floor_usdc) if floor_usdc > 0 else float("inf")
        return {
            "address": address,
            "usdc_balance": usdc,
            "native_usdc_balance": native,  # gas side
            "floor_usdc": floor_usdc,
            "treasury_health": health,
            "block_number": self.get_block_number(),
            "chain_id": self.chain_id,
        }

    def explorer_tx(self, tx_hash: str) -> str:
        from src import config

        return f"{config.ARC_EXPLORER}/tx/{tx_hash}"

    def explorer_address(self, address: str) -> str:
        from src import config

        return f"{config.ARC_EXPLORER}/address/{address}"
