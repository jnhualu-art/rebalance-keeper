"""Unit tests for the FlareKeeper FCE rebalance handler."""

import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from base.encoding import bytes_to_hex, hex_to_bytes  # noqa: E402
from app.handlers import handle_compute, reset_state  # noqa: E402


def _run(tb: float, health: float, floor=20.0, ceiling=50.0) -> dict:
    req = {"treasury_balance": tb, "treasury_health": health, "floor": floor, "ceiling": ceiling}
    data_hex, status, err = handle_compute(
        bytes_to_hex(json.dumps(req, separators=(",", ":")).encode("utf-8")))
    assert status == 1, f"handler returned error: {err}"
    return json.loads(hex_to_bytes(data_hex))


def test_healthy_no_action():
    dec = _run(40.0, 2.0)
    assert dec["action"] == "none"
    assert dec["zone"] in ("SAFE", "WARNING")


def test_below_floor_topup():
    dec = _run(12.0, 0.6)
    assert dec["action"] == "topup"
    assert dec["zone"] in ("WARNING", "DANGER", "CRITICAL")
    assert dec["amount"] > 0


def test_over_ceiling_sweep():
    dec = _run(80.0, 4.0, floor=20.0, ceiling=50.0)
    assert dec["action"] == "sweep"
    assert dec["zone"] == "OVER"
    assert dec["amount"] == 30.0


def test_critical_full_restore():
    dec = _run(5.0, 0.25)
    assert dec["action"] == "topup"
    assert dec["zone"] == "CRITICAL"
    assert dec["amount"] == 15.0  # full deficit restored


def test_invalid_request():
    data_hex, status, err = handle_compute(bytes_to_hex(b'{"foo":1}'))
    assert status == 0
    assert err


def test_decode_error():
    data_hex, status, err = handle_compute("0xzzzz")
    assert status == 0


if __name__ == "__main__":
    for name in [v for v in dir() if v.startswith("test_")]:
        globals()[name]()
        print(f"PASS {name}")
    print("ALL TESTS PASSED")
