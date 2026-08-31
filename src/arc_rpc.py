"""
ArcKeeper — shared JSON-RPC transport for Arc.

This module is the single place that owns HTTP headers, endpoint fallback,
timeouts and error normalisation. Both the read path (ArcClient) and the
write path (ArcExecutor) go through here, so transport behaviour is
identical and auditable in exactly one file.

Why endpoint fallback exists:
    Arc publishes `rpc.testnet.arc.io`, but some networks and some Python
    IPv6 stacks resolve/route one domain and not the other. A single hard
    failure should never take the agent down, so we rotate across known
    public endpoints before giving up.
"""

import json
import urllib.error
import urllib.request
from typing import Any, List, Optional

# Public Arc Testnet endpoints, most preferred first.
DEFAULT_ARC_ENDPOINTS = (
    "https://rpc.testnet.arc.io",
    "https://rpc.testnet.arc.network",
)

USER_AGENT = "ArcKeeper/1.0 (rebalance-keeper)"
DEFAULT_TIMEOUT = 20


class ArcRPCError(Exception):
    """Raised when an Arc RPC call fails at every configured endpoint."""


def normalise_endpoints(primary: Optional[str]) -> List[str]:
    """Build an ordered, de-duplicated endpoint list with `primary` first.

    An empty or missing primary simply yields the defaults; we never return
    an empty list, because callers rely on at least one usable endpoint.
    """
    endpoints: List[str] = []
    for url in (primary, *DEFAULT_ARC_ENDPOINTS):
        if not url:
            continue
        cleaned = str(url).strip().rstrip("/")
        if cleaned and cleaned not in endpoints:
            endpoints.append(cleaned)
    return endpoints or list(DEFAULT_ARC_ENDPOINTS)


class ArcRPC:
    """Minimal EVM JSON-RPC transport with automatic endpoint failover."""

    def __init__(self, rpc_url: str = None, timeout: int = DEFAULT_TIMEOUT):
        self.endpoints = normalise_endpoints(rpc_url)
        self.timeout = timeout
        self._cursor = 0

    @property
    def rpc_url(self) -> str:
        """Currently active endpoint. Read-only view for callers/logging."""
        return self.endpoints[self._cursor]

    def call(self, method: str, params: list) -> Any:
        """Call a JSON-RPC method, rotating endpoints on failure.

        Raises ArcRPCError only after every endpoint has been tried, so a
        single-endpoint hiccup never surfaces to the caller.
        """
        errors: List[str] = []
        for _ in range(len(self.endpoints)):
            url = self.endpoints[self._cursor]
            try:
                return self._call_once(url, method, params)
            except ArcRPCError as exc:
                errors.append(f"{url}: {exc}")
                self._cursor = (self._cursor + 1) % len(self.endpoints)
        raise ArcRPCError("All Arc RPC endpoints failed -> " + " | ".join(errors))

    def _call_once(self, url: str, method: str, params: list) -> Any:
        body = json.dumps(
            {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        ).encode("utf-8")

        req = urllib.request.Request(
            url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                # The gateway rejects the default `Python-urllib/x.y` UA with
                # HTTP 403, so an explicit UA is required, not cosmetic.
                "User-Agent": USER_AGENT,
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.load(resp)
        except urllib.error.HTTPError as exc:
            raise ArcRPCError(f"HTTP {exc.code}")
        except urllib.error.URLError as exc:
            raise ArcRPCError(f"Network error: {exc.reason}")
        except (json.JSONDecodeError, ValueError):
            raise ArcRPCError("Malformed JSON response")
        except OSError as exc:
            raise ArcRPCError(f"Connection error: {exc}")

        if not isinstance(data, dict):
            raise ArcRPCError("Malformed response envelope")
        if data.get("error"):
            raise ArcRPCError(str(data["error"]))
        if "result" not in data:
            raise ArcRPCError("Response missing 'result'")
        return data["result"]
