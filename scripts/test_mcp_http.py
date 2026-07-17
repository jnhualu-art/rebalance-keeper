#!/usr/bin/env python3
"""
Test KeeperHub MCP over Streamable HTTP transport.

MCP protocol flow:
  1. initialize  → get session ID from response header
  2. notifications/initialized → tell server we're ready
  3. tools/call  → actual tool invocation
"""

import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))
except ImportError:
    pass

MCP_URL = "https://app.keeperhub.com/mcp"
API_KEY = os.getenv("KEEPERHUB_API_KEY", "")
WALLET = os.getenv("WALLET_ADDRESS", "0x1573C3d151200922375bC48012BB1f232B2cF531")

if not API_KEY:
    print("ERROR: Set KEEPERHUB_API_KEY in .env")
    sys.exit(1)

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


def send(method, params, msg_id=None, session_id=None, extra_headers=None):
    """Send one MCP JSON-RPC message. Returns (parsed_body, session_id_from_header)."""
    msg = {"jsonrpc": "2.0", "method": method, "params": params}
    if msg_id is not None:
        msg["id"] = msg_id

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {API_KEY}",
        "User-Agent": UA,
        "Accept": "application/json, text/event-stream",
    }
    if session_id:
        headers["Mcp-Session-Id"] = session_id
    if extra_headers:
        headers.update(extra_headers)

    data = json.dumps(msg).encode()
    req = urllib.request.Request(MCP_URL, data=data, headers=headers)

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode()
            sid = resp.headers.get("Mcp-Session-Id")
            parsed = json.loads(body) if body.strip() else {}
            return parsed, sid
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"  HTTP {e.code}: {body[:300]}")
        return None, None
    except Exception as e:
        print(f"  Error: {e}")
        return None, None


def main():
    # 1. Initialize
    print("=== Step 1: initialize ===")
    result, session_id = send(
        "initialize",
        {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "RebalanceKeeper", "version": "1.0.0"},
        },
        msg_id=0,
    )
    print(f"  Session ID: {session_id}")
    if result:
        print(f"  Server: {json.dumps(result.get('result', {}), indent=2)[:300]}")

    if not session_id:
        print("  ERROR: No session ID returned. Cannot continue.")
        return

    # 2. Send initialized notification (no id = notification)
    print("\n=== Step 2: notifications/initialized ===")
    send("notifications/initialized", {}, session_id=session_id)
    print("  Sent.")

    # 3. Call get-user-account-data
    print("\n=== Step 3: tools/call (get-user-account-data) ===")
    result, _ = send(
        "tools/call",
        {
            "name": "execute_protocol_action",
            "arguments": {
                "actionType": "aave-v3/get-user-account-data",
                "params": {"network": "11155111", "user": WALLET},
            },
        },
        msg_id=1,
        session_id=session_id,
    )
    if result:
        # MCP wraps tool results in content array
        print(f"  Raw: {json.dumps(result, indent=2)[:1500]}")
        # Try to extract text content
        content = result.get("result", {}).get("content", [])
        if content:
            for item in content:
                if item.get("type") == "text":
                    data = json.loads(item["text"])
                    print(f"\n  Parsed result:")
                    print(f"    healthFactor: {data.get('healthFactor')}")
                    print(f"    totalCollateralBase: {data.get('totalCollateralBase')}")
                    print(f"    totalDebtBase: {data.get('totalDebtBase')}")


if __name__ == "__main__":
    main()
