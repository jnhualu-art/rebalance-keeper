"""
Safety tests for ArcExecutor calldata construction.

These guard the invariants that actually matter once a transaction is
broadcast: a malformed address or an out-of-range amount must be rejected
locally, never encoded into calldata that is syntactically valid but
semantically wrong. On-chain, that class of bug is unrecoverable.
"""

import pytest

from src.arc_executor import TRANSFER_SELECTOR, ArcExecutor, ArcExecutorError

USDC = "0x3600000000000000000000000000000000000000"
ALICE = "0x" + "11" * 20
BOB = "0x" + "22" * 20


@pytest.fixture(scope="module")
def ex():
    return ArcExecutor()


def test_build_transfer_encodes_calldata_correctly(ex):
    """selector + 32-byte address word + 32-byte amount word."""
    tx = ex.build_transfer(ALICE, BOB, 1.5)

    assert tx["to"].lower() == USDC
    data = tx["data"]
    assert data.startswith(TRANSFER_SELECTOR)
    assert len(data) == 2 + 8 + 64 + 64

    address_word = data[10:74]
    amount_word = data[74:138]
    assert address_word == BOB[2:].lower().rjust(64, "0")
    assert int(amount_word, 16) == 1_500_000  # 1.5 USDC at 6 decimals


def test_from_address_is_normalised(ex):
    """A checksummed `from` address must survive normalisation."""
    tx = ex.build_transfer(ALICE.upper().replace("0X", "0x"), BOB, 1.0)
    assert tx["from"].lower() == ALICE.lower()


@pytest.mark.parametrize(
    "bad_address",
    [
        "",
        "0x1234",
        "0x" + "11" * 19,          # one byte short
        "0x" + "11" * 21,          # one byte long
        "zz" * 20,                 # non-hex
        "0x" + "gg" * 20,
        None,
        12345,                     # wrong type
    ],
)
def test_rejects_malformed_recipient(ex, bad_address):
    with pytest.raises(ArcExecutorError):
        ex.build_transfer(ALICE, bad_address, 1.0)


@pytest.mark.parametrize(
    "bad_address",
    ["", "0x1234", "zz" * 20, None, 12345],
)
def test_rejects_malformed_sender(ex, bad_address):
    with pytest.raises(ArcExecutorError):
        ex.build_transfer(bad_address, BOB, 1.0)


@pytest.mark.parametrize(
    "bad_amount",
    [
        0,
        -1,
        -0.0001,
        "abc",
        None,
        float("nan"),
        float("inf"),
        float("-inf"),
        2 ** 300,                  # beyond uint256
    ],
)
def test_rejects_bad_amount(ex, bad_amount):
    with pytest.raises(ArcExecutorError):
        ex.build_transfer(ALICE, BOB, bad_amount)


def test_rejects_sub_base_unit_precision(ex):
    """0.0000001 USDC is below 6-decimal resolution and must not truncate to 0."""
    with pytest.raises(ArcExecutorError):
        ex.build_transfer(ALICE, BOB, 0.0000001)

    with pytest.raises(ArcExecutorError):
        ex.build_transfer(ALICE, BOB, 1.0000001)


def test_float_rounding_does_not_shift_amount(ex):
    """0.1 is not representable in binary float; decimal math must still land exact."""
    tx = ex.build_transfer(ALICE, BOB, 0.1)
    assert int(tx["data"][74:138], 16) == 100_000


def test_private_key_errors_never_leak_material(ex):
    """Error text must not echo the key back into logs or traces."""
    secret = "0x" + "ab" * 32
    with pytest.raises(ArcExecutorError) as excinfo:
        ex._load_account("not-a-valid-key")
    message = str(excinfo.value)
    assert secret not in message
    assert "not-a-valid-key" not in message

    with pytest.raises(ArcExecutorError) as excinfo:
        ex._load_account("")
    assert "empty" in str(excinfo.value).lower()


def test_endpoint_list_is_deduplicated_and_never_empty():
    from src.arc_rpc import DEFAULT_ARC_ENDPOINTS, normalise_endpoints

    result = normalise_endpoints("https://rpc.testnet.arc.io")
    assert result[0] == "https://rpc.testnet.arc.io"
    assert len(result) == len(set(result))

    # A junk primary must still fall back to usable defaults.
    fallback = normalise_endpoints("   ")
    assert fallback == list(DEFAULT_ARC_ENDPOINTS)
    assert normalise_endpoints(None) == list(DEFAULT_ARC_ENDPOINTS)
