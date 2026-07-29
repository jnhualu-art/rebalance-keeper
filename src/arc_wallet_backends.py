"""
ArcKeeper — Wallet backend abstraction (Agentic Economy custody options).

Why this file exists
--------------------
Encode Checkpoint 3 asks for "integrate Circle Agent Stack wallet custody".
To do that cleanly we decouple *how the agent signs/broadcasts* from the
rebalance logic. The rebalancer now talks to a `WalletBackend` interface, and
we ship two implementations:

  1. LocalKeyBackend  — signs locally with eth_account (default, zero external
                        deps, the original behaviour).
  2. CircleWalletBackend — uses Circle Agent Stack developer-controlled wallets
                        on ARC-TESTNET. The agent's USDC lives in a Circle
                        custody wallet with programmable spending policies
                        instead of a raw .env private key.

Both expose the same `transfer_usdc(...)` method, so the rebalancer code is
identical regardless of which custody model is active. Switching is one
env var: `ARC_WALLET_BACKEND=circle`.

NOTE on Circle: the real integration needs a Circle sandbox/business account
(`CIRCLE_API_KEY`, `CIRCLE_ENTITY_SECRET`) and a pre-created ARC-TESTNET
developer wallet. This module talks to the documented Circle REST surface
(developer-controlled wallets) over stdlib urllib — no third-party SDK needed,
keeping the project's zero-dependency philosophy. Field names follow Circle's
developer docs; verify against the latest spec before production use.
"""

import json
import os
import time
import urllib.request
import urllib.error
from typing import Dict, Optional

from src import config


class WalletBackendError(Exception):
    """Raised when a wallet backend fails to build or broadcast a transfer."""


class WalletBackend:
    """Interface: move `amount_usdc` from `from_address` to `to_address`.

    Returns {"tx_hash": str, "explorer": str} on success, or
    {"dry_run": True, ...} when dry_run=True.
    """

    def transfer_usdc(
        self,
        from_address: str,
        to_address: str,
        amount_usdc: float,
        dry_run: bool = False,
    ) -> Dict:
        raise NotImplementedError


class LocalKeyBackend(WalletBackend):
    """Original behaviour: sign locally with eth_account, broadcast via Arc RPC."""

    def __init__(self, rpc_url: str = None, chain_id: int = None, usdc_address: str = None):
        # Imported lazily to avoid a hard dependency when only Circle is used.
        from src.arc_executor import ArcExecutor
        self._executor = ArcExecutor(
            rpc_url=rpc_url or config.ARC_RPC_URL,
            chain_id=chain_id or config.ARC_CHAIN_ID,
            usdc_address=usdc_address or config.ARC_USDC_ERC20,
        )

    def transfer_usdc(self, from_address, to_address, amount_usdc, dry_run=False,
                      private_key: str = None) -> Dict:
        if private_key is None:
            raise WalletBackendError("LocalKeyBackend requires a private_key.")
        return self._executor.transfer_usdc(
            from_address=from_address,
            to_address=to_address,
            amount_usdc=amount_usdc,
            private_key=private_key,
            dry_run=dry_run,
        )


class CircleWalletBackend(WalletBackend):
    """Circle Agent Stack developer-controlled wallet on ARC-TESTNET.

    The agent's USDC is held in a Circle custody wallet. Transfers are
    authorised through Circle's API, which enforces the wallet's spending
    policy (daily caps, allow/block lists) server-side — a stronger guarantee
    than a local key check.

    Required env:
      CIRCLE_API_KEY        (format PREFIX:ID:SECRET)
      CIRCLE_ENTITY_SECRET  (entity secret from Circle console)
      CIRCLE_WALLET_ADDRESS (the agent's Circle dev wallet address on ARC-TESTNET)

    Optional env:
      ARC_USDC_ERC20       (defaults to 0x3600...0000)
      CIRCLE_API_BASE      (defaults to https://api.circle.com/v1/w3s)
    """

    def __init__(
        self,
        api_key: str = None,
        entity_secret: str = None,
        wallet_address: str = None,
        reserve_address: str = None,
        token_address: str = None,
        api_base: str = None,
    ):
        self.api_key = api_key or os.getenv("CIRCLE_API_KEY", "")
        self.entity_secret = entity_secret or os.getenv("CIRCLE_ENTITY_SECRET", "")
        self.wallet_address = wallet_address or os.getenv("CIRCLE_WALLET_ADDRESS", "")
        self.reserve_address = reserve_address or os.getenv("CIRCLE_RESERVE_ADDRESS", "")
        self.token_address = token_address or config.ARC_USDC_ERC20
        self.api_base = (api_base or os.getenv("CIRCLE_API_BASE", "")).rstrip("/")
        if not self.api_base:
            self.api_base = "https://api.circle.com/v1/w3s"
        if not (self.api_key and self.entity_secret and self.wallet_address):
            raise WalletBackendError(
                "CircleWalletBackend requires CIRCLE_API_KEY, CIRCLE_ENTITY_SECRET, "
                "and CIRCLE_WALLET_ADDRESS (set them in .env)."
            )

    def _is_known_wallet(self, addr: str) -> bool:
        return addr.lower() in {
            w.lower() for w in (self.wallet_address, self.reserve_address) if w
        }

    # ── REST plumbing (stdlib only) ─────────────────────────────
    def _request(self, method: str, path: str, body: Optional[dict] = None) -> dict:
        url = f"{self.api_base}{path}"
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Authorization", f"Bearer {self.api_key}")
        req.add_header("X-Entity-Secret", self.entity_secret)
        req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")
            raise WalletBackendError(f"Circle API {e.code}: {detail}")
        except urllib.error.URLError as e:
            raise WalletBackendError(f"Circle network error: {e.reason}")

    # ── transfer ────────────────────────────────────────────────
    def transfer_usdc(self, from_address, to_address, amount_usdc, dry_run=False,
                      private_key: str = None) -> Dict:
        # The Circle wallet that signs is the `from_address`; it must be one of
        # the agent's authorised Circle wallets (operational or reserve).
        if not self._is_known_wallet(from_address):
            raise WalletBackendError(
                f"Circle wallet mismatch: {from_address} is not an authorised "
                f"Circle wallet (set CIRCLE_WALLET_ADDRESS / CIRCLE_RESERVE_ADDRESS)."
            )
        if dry_run:
            return {
                "dry_run": True,
                "backend": "circle",
                "from": from_address,
                "to": to_address,
                "amount_usdc": amount_usdc,
            }

        # 1) create the transfer transaction
        create = self._request(
            "POST", "/developer/transactions/transfer",
            {
                "walletAddress": from_address,
                "blockchain": "ARC-TESTNET",
                "destinationAddress": to_address,
                "tokenAddress": self.token_address,
                "amounts": [f"{amount_usdc:.6f}"],
                "feeLevel": "MEDIUM",
            },
        )
        tx_id = create.get("data", {}).get("id")
        if not tx_id:
            raise WalletBackendError(f"Circle did not return a transaction id: {create}")

        # 2) poll until terminal state
        terminal = {"COMPLETE", "FAILED", "CANCELLED", "DENIED"}
        state = "INITIATED"
        tx_hash = None
        for _ in range(40):  # ~2 min max
            poll = self._request("GET", f"/developer/transactions/{tx_id}")
            tx = poll.get("data", {}).get("transaction", {})
            state = tx.get("state", state)
            tx_hash = tx.get("txHash") or tx.get("tx_hash") or tx_hash
            if state in terminal:
                break
            time.sleep(3)

        if state != "COMPLETE":
            raise WalletBackendError(f"Circle transfer ended in state: {state}")

        return {
            "tx_hash": tx_hash,
            "from": self.wallet_address,
            "to": to_address,
            "amount_usdc": amount_usdc,
            "explorer": f"{config.ARC_EXPLORER}/tx/{tx_hash}" if tx_hash else "",
            "backend": "circle",
        }


def get_backend(name: str = None) -> WalletBackend:
    """Factory: resolve the active wallet backend from config / env.

    `name` overrides the `ARC_WALLET_BACKEND` env var (local | circle).
    """
    kind = (name or os.getenv("ARC_WALLET_BACKEND", "local")).lower()
    if kind == "circle":
        return CircleWalletBackend()
    if kind == "local":
        return LocalKeyBackend()
    raise WalletBackendError(f"Unknown wallet backend: {kind!r} (use 'local' or 'circle')")
