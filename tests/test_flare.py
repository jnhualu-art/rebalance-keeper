"""
Unit tests for the FlareKeeper (Flare Summer Signal Bounty 2) modules:
  - flare_tee        : Confidential Compute (simulated attestation)
  - flare_executor   : native + ERC-20 tx building, attestation anchoring
  - flare_rebalancer : read → decide (TEE) → anchor → execute loop

All tests are network-free: the executor's RPC-dependent helpers are stubbed
and the rebalancer is driven by a fake client + fake executor.
"""

import json

import pytest

from src import config
from src.flare_tee import ConfidentialCompute, AttestedDecision
from src.flare_executor import FlareExecutor, FlareExecutorError
from src.flare_rebalancer import FlareRebalancer


# ── flare_tee ────────────────────────────────────────────────
def test_tee_simulated_attestation():
    cc = ConfidentialCompute(real=False)

    def strat(inp):
        return {"action": "sweep", "amount_usdc": 5.0, "zone": "OVER", "reason": "x"}

    att = cc.compute({"usdc_balance": 55.0, "floor_usdc": 20.0}, strat)
    assert isinstance(att, AttestedDecision)
    assert att.enclave_mode == "simulated"
    assert att.verified is True
    assert att.attestation.startswith("sim:")
    assert att.decision["action"] == "sweep"


def test_tee_real_falls_back_to_simulated():
    # Real enclave not wired yet → must not break the loop.
    cc = ConfidentialCompute(real=True)
    att = cc.compute({"usdc_balance": 10.0, "floor_usdc": 20.0},
                     lambda i: {"action": "topup", "amount_usdc": 10.0,
                                "zone": "CRITICAL", "reason": "y"})
    assert att.decision["action"] == "topup"
    assert att.attestation.startswith("sim:")


# ── flare_executor: tx building (stubbed RPC) ────────────────
def _stub_executor(monkeypatch):
    ex = FlareExecutor()
    monkeypatch.setattr(ex, "_get_fee_params", lambda: (2_000_000_000, 1_000_000_000))
    monkeypatch.setattr(ex, "_nonce", lambda addr: 7)
    return ex


A = "0x57047A430c4cfe335674e6bAD81b4D5F68ff505c"
B = "0xeC3cD471c204c27493D9b5c5230479dEB421DD43"


def test_build_native_transfer(monkeypatch):
    monkeypatch.setattr(config, "FLARE_ASSET_MODE", "native")
    ex = _stub_executor(monkeypatch)
    tx = ex.build_transfer(A, B, 20.0)
    assert tx["to"].lower() == B.lower()          # native → recipient is the peer
    assert tx["data"] == "0x"
    assert tx["type"] == "0x2"
    assert tx["nonce"] == 7
    # 20 C2FLR at 18 decimals
    assert int(tx["value"], 16) == 20 * 10 ** 18
    assert tx["gas"] == "0x" + hex(21_000)[2:]


def test_build_erc20_transfer(monkeypatch):
    monkeypatch.setattr(config, "FLARE_ASSET_MODE", "erc20")
    monkeypatch.setattr(config, "FLARE_USDC_ERC20", "0x000000000000000000000000000000000000dEaD")
    monkeypatch.setattr(config, "FLARE_USDC_DECIMALS", 6)
    ex = _stub_executor(monkeypatch)
    ex.usdc_address = config.FLARE_USDC_ERC20.lower()
    tx = ex.build_transfer(A, B, 5.0)
    assert tx["to"] == config.FLARE_USDC_ERC20.lower()   # ERC-20 → token contract
    assert tx["value"] == "0x0"
    assert tx["data"].startswith("0xa9059cbb")           # transfer(address,uint256)
    # recipient encoded in calldata; amount = 5 * 1e6
    assert B[2:].lower() in tx["data"].lower()
    assert int(tx["data"][-64:], 16) == 5 * 10 ** 6


def test_build_erc20_requires_address(monkeypatch):
    monkeypatch.setattr(config, "FLARE_ASSET_MODE", "erc20")
    ex = _stub_executor(monkeypatch)
    ex.usdc_address = ""
    with pytest.raises(FlareExecutorError):
        ex.build_transfer(A, B, 5.0)


def test_build_anchor_carries_attestation(monkeypatch):
    ex = _stub_executor(monkeypatch)
    att = "sim:deadbeef"
    tx = ex.build_anchor(A, "0x" + att.encode().hex())
    assert tx["value"] == "0x0"
    assert tx["to"] == A                                  # self-transfer by default
    # calldata decodes back to the attestation string
    assert bytes.fromhex(tx["data"][2:]).decode() == att


def test_amount_too_small_rejected(monkeypatch):
    monkeypatch.setattr(config, "FLARE_ASSET_MODE", "native")
    ex = _stub_executor(monkeypatch)
    with pytest.raises(FlareExecutorError):
        ex.build_transfer(A, B, 0.0)


# ── flare_rebalancer: full loop with fakes ───────────────────
class FakeClient:
    def __init__(self, balance):
        self.balance = balance

    def get_position(self, address, floor_usdc=50.0):
        return {
            "address": address,
            "usdc_balance": self.balance,
            "native_flr_balance": self.balance,
            "asset_mode": "native",
            "asset_symbol": "C2FLR",
            "floor_usdc": floor_usdc,
            "treasury_health": (self.balance / floor_usdc) if floor_usdc else float("inf"),
            "block_number": 123,
            "chain_id": 114,
        }


class FakeExecutor:
    def __init__(self):
        self.transfers = []
        self.anchors = []

    def anchor_attestation(self, frm, attestation, pk, dry_run=False):
        self.anchors.append((frm, attestation, dry_run))
        return {"dry_run": dry_run, "anchor_from": frm, "attestation": attestation}

    def transfer(self, frm, to, amount, pk, dry_run=False):
        self.transfers.append((frm, to, amount, dry_run))
        return {"dry_run": dry_run, "from": frm, "to": to, "amount": amount, "asset": "C2FLR"}


def _rebalancer(monkeypatch, balance):
    monkeypatch.setattr(config, "FLARE_WALLET_ADDRESS", A)
    monkeypatch.setattr(config, "FLARE_RESERVE_ADDRESS", B)
    monkeypatch.setattr(config, "FLARE_PRIVATE_KEY", "0x" + "11" * 32)
    monkeypatch.setattr(config, "FLARE_RESERVE_PRIVATE_KEY", "0x" + "22" * 32)
    fake_ex = FakeExecutor()
    r = FlareRebalancer(client=FakeClient(balance), executor=fake_ex)
    return r, fake_ex


def test_loop_sweep_when_over_ceiling(monkeypatch):
    # balance 80 > ceiling 50 → sweep excess (30) operating → reserve
    r, ex = _rebalancer(monkeypatch, balance=80.0)
    res = r.run_once(dry_run=True)
    d = res["attested_decision"].decision
    assert d["action"] == "sweep"
    assert ex.transfers and ex.transfers[0][0] == A and ex.transfers[0][1] == B
    assert ex.anchors  # attestation was anchored


def test_loop_topup_when_below_floor(monkeypatch):
    # balance 5 < floor 20 → topup reserve → operating
    r, ex = _rebalancer(monkeypatch, balance=5.0)
    res = r.run_once(dry_run=True)
    d = res["attested_decision"].decision
    assert d["action"] == "topup"
    assert ex.transfers and ex.transfers[0][0] == B and ex.transfers[0][1] == A


def test_loop_none_when_healthy(monkeypatch):
    # balance 30 within [20, 50] → no action
    r, ex = _rebalancer(monkeypatch, balance=30.0)
    res = r.run_once(dry_run=True)
    d = res["attested_decision"].decision
    assert d["action"] == "none"
    assert res["execution"]["action"] == "none"
    assert not ex.transfers            # nothing moved
    assert ex.anchors                  # but attestation still anchored


def test_loop_errors_without_wallet(monkeypatch):
    monkeypatch.setattr(config, "FLARE_WALLET_ADDRESS", "")
    r = FlareRebalancer(client=FakeClient(30.0), executor=FakeExecutor())
    res = r.run_once(dry_run=True)
    assert "error" in res
