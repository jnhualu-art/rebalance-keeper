"""
RebalanceKeeper — Configuration constants for Aave V3 on Sepolia testnet.

All on-chain addresses are from the official Aave address book
(https://github.com/aave/aave-address-book) for Sepolia testnet.
"""

import os
from dataclasses import dataclass, field
from typing import Dict


# ── KeeperHub MCP ──────────────────────────────────────────────
KEEPERHUB_MCP_URL = os.getenv("KEEPERHUB_MCP_URL", "https://app.keeperhub.com/mcp")
KEEPERHUB_API_KEY = os.getenv("KEEPERHUB_API_KEY", "")

# ── Wallet (Turnkey non-custodial, provisioned via KeeperHub) ──
WALLET_ADDRESS = os.getenv("WALLET_ADDRESS", "0x1573C3d151200922375bC48012BB1f232B2cF531")
WALLET_INTEGRATION_ID = os.getenv("WALLET_INTEGRATION_ID", "flx4bwzye6tb6re68wost")

# ── Chain ──────────────────────────────────────────────────────
# Sepolia testnet (chainId = 11155111).  Switch to "1" for mainnet.
CHAIN_ID = os.getenv("CHAIN_ID", "11155111")
CHAIN_NAME = "Ethereum Sepolia"

# ── Aave V3 Core Contracts (Sepolia) ──────────────────────────
AAVE_POOL = "0x6Ae43d3271ff6888e7Fc43Fd7321a503ff738951"
AAVE_POOL_ADDRESSES_PROVIDER = "0x012bAC54348C0E635dCAc9D5FB99f06F24136C9A"
AAVE_POOL_CONFIGURATOR = "0x7Ee60D184C24Ef7AfC1Ec7Be59A0f448A0abd138"
AAVE_ORACLE = "0x2da88497588bf89281816106C7259e31AF45a663"
AAVE_ACL_MANAGER = "0x7F2bE3b178deeFF716CD6Ff03Ef79A1dFf360ddD"
WETH_GATEWAY = "0x387d311e47e80b498169e6fb51d3193167d89F7D"

# ── Token Addresses (Sepolia) ─────────────────────────────────
# Collateral asset: WETH.  Debt asset: USDC.
TOKENS: Dict[str, Dict] = {
    "WETH": {
        "address": "0xC558DBdd856501FCd9aaF1E62eae57A9F0629a3c",
        "aToken": "0x5b071b590a59395fE4025A0Ccc1FcC931AAc1830",
        "decimals": 18,
        "role": "collateral",
    },
    "USDC": {
        "address": "0x94a9D9AC8a22534E3FaCa9F4e7F2E2cf85d5E4C8",
        "aToken": "0x16dA4541aD1807f4443d92D26044C1147406EB80",
        "decimals": 6,
        "role": "debt",
    },
    "DAI": {
        "address": "0xFF34B3d4Aee8ddCd6F9AFFFB6Fe49bD371b8a357",
        "aToken": "0x29598b72eb5CeBd806C5dCD549490FdA35B13cD8",
        "decimals": 18,
        "role": "debt",
    },
    "LINK": {
        "address": "0xf8Fb3713D459D7C1018BD0A49D19b4C44290EBE5",
        "aToken": "0x3FfAf50D4F4E96eB78f2407c090b72e86eCaed24",
        "decimals": 18,
        "role": "collateral",
    },
    "AAVE": {
        "address": "0x88541670E55cC00bEEFD87eB59EDd1b7C511AC9a",
        "aToken": "0x6b8558764d3b7572136F17174Cb9aB1DDc7E1259",
        "decimals": 18,
        "role": "collateral",
    },
    "WBTC": {
        "address": "0x29f2D40B0605204364af54EC677bD022dA425d03",
        "aToken": "0x1804Bf30507dc2EB3bDEbbbdd859991EAeF6EefF",
        "decimals": 8,
        "role": "collateral",
    },
    "USDT": {
        "address": "0xaA8E23Fb1079EA71e0a56F48a2aA51851D8433D0",
        "decimals": 6,
        "role": "debt",
    },
    "GHO": {
        "address": "0xc4bF5CbDaBE595361438F8c6a187bDc330539c60",
        "decimals": 18,
        "role": "debt",
    },
}

# Convenience accessors
COLLATERAL_TOKEN = "WETH"   # supply this as collateral
DEBT_TOKEN = "USDC"          # borrow this against collateral


def token_addr(symbol: str) -> str:
    return TOKENS[symbol]["address"]


def token_decimals(symbol: str) -> int:
    return TOKENS[symbol]["decimals"]


# ── Rebalancer Parameters ─────────────────────────────────────
@dataclass
class RebalanceConfig:
    """Thresholds and behaviour for the rebalance loop."""

    # Health factor below this → trigger rebalance (Aave liquidates at <1.0)
    health_factor_threshold: float = 1.5

    # How much of the debt to repay per trigger (fraction of total debt, 0–1)
    repay_fraction: float = 0.15

    # If repay is not possible (no debt token balance), supply extra collateral
    # instead.  Amount in base units of the collateral token.
    supply_boost_amount: str = "0.01"   # 0.01 WETH

    # Polling interval in seconds
    monitor_interval: int = 30

    # Max retries on a failed execution
    max_retries: int = 3

    # Idempotency key prefix (appended with timestamp)
    idempotency_prefix: str = "rbk"

    # Audit log file path
    audit_log_path: str = "logs/audit.jsonl"

    # Health-factor history for dashboard (in-memory ring buffer)
    history_size: int = 500

    # Interest rate mode for borrow/repay (2 = variable, 1 = stable)
    interest_rate_mode: str = "2"


# Default config instance
REBALANCE_CONFIG = RebalanceConfig()
