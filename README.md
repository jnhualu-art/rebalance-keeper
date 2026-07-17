# RebalanceKeeper

> Autonomous DeFi agent that monitors your Aave V3 position and auto-rebalances when the health factor drops — executed entirely through KeeperHub MCP.

[![Hackathon](https://img.shields.io/badge/KeeperHub-Agents%20Onchain-blue)](https://dorahacks.io/hackathon/agents-onchain/detail)
[![Network](https://img.shields.io/badge/Network-Ethereum%20Sepolia-orange)](https://sepolia.etherscan.io)
[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)

## How It Works

```
  ┌──────────────────────────────────────────┐
  │            Agent (Python)                │
  │                                          │
  │  Monitor ──→ Evaluate ──→ Decide        │
  │                  │                      │
  │           HF < threshold?               │
  │           ├─ YES → repay or supply      │
  │           └─ NO  → keep monitoring      │
  └──────────────┬───────────────────────────┘
                 │
                 ▼
  ┌──────────────────────────────────────────┐
  │         KeeperHub MCP Server            │
  │                                          │
  │  execute_protocol_action                 │
  │  ├─ aave-v3/repay   ← reduce debt       │
  │  ├─ aave-v3/supply  ← add collateral    │
  │  └─ aave-v3/get-user-account-data       │
  │                                          │
  │  execute_check_and_execute (conditional) │
  │  + retry · gas estimation · MEV protect │
  └──────────────┬───────────────────────────┘
                 │
                 ▼
  ┌──────────────────────────────────────────┐
  │     Ethereum (Sepolia / Mainnet)        │
  │     Aave V3 Pool — real transactions     │
  └──────────────────────────────────────────┘
```

## Features

- **Zero-dependency** — Pure Python stdlib, no web3/ethers.js bloat
- **MCP-native** — Talks directly to KeeperHub MCP over Streamable HTTP
- **Conditional execution** — Uses `execute_check_and_execute` for atomic check-then-act
- **Full audit trail** — Every monitor check and trigger logged as JSONL with tx hashes
- **Idempotent** — Retries with idempotency keys, no duplicate transactions
- **Configurable** — Threshold, repay fraction, interval all adjustable

## Quick Start

### 1. Clone & configure

```bash
git clone git@github.com:jnhualu-art/rebalance-keeper.git
cd rebalance-keeper
cp .env.example .env
# Edit .env — add your KeeperHub API key (kh_ prefix)
```

### 2. Install

```bash
pip install -r requirements.txt  # Only python-dotenv needed
```

### 3. Check your position

```bash
python -m src.main status
```

Output:
```
============================================================
  RebalanceKeeper — Position Status
============================================================
  Wallet:    0x1573C3d151200922375bC48012BB1f232B2cF531
  Chain:     Ethereum Sepolia (id=11155111)
  Pool:      0x6Ae43d3271ff6888e7Fc43Fd7321a503ff738951
────────────────────────────────────────────────────────────
  Health Factor:        1.8234
  Total Collateral:     320000000000 (base units)
  Total Debt:           120000000 (base units)
  Status: ✓ SAFE (threshold: 1.5)
```

### 4. Set up a test position (Sepolia)

```bash
# Supply 0.01 WETH as collateral, borrow 10 USDC
python -m src.main setup --supply-amount 0.01 --borrow-amount 10
```

### 5. Run the monitor

```bash
python -m src.main monitor
```

```
Monitor started. Wallet: 0x1573...C531
  Chain: Ethereum Sepolia (id=11155111)
  Threshold: HF < 1.5
  Interval: 30s
────────────────────────────────────────────────────────
[2026-07-17T09:30:00Z] HF=1.8234 Collateral=320000000000 Debt=120000000 → SAFE
[2026-07-17T09:30:30Z] HF=1.7512 Collateral=320000000000 Debt=120000000 → SAFE
[2026-07-17T09:31:00Z] HF=1.4201 Collateral=320000000000 Debt=120000000 → UNSAFE

============================================================
  REBALANCE TRIGGERED
  Action: REPAY
  Asset:  0x94a9D9AC8a22534E3FaCa9F4e7F2E2cf85d5E4C8 (USDC)
  Amount: 1.800000
  Reason: HF=1.4201 < 1.50. Repay 15% of USDC debt.
============================================================

  ✓ TX confirmed: 0xabc123...
  ✓ Explorer: https://sepolia.etherscan.io/tx/0xabc123...
```

## Commands

| Command | Description |
|---------|-------------|
| `python -m src.main status` | Show current Aave V3 position |
| `python -m src.main once` | Run a single health check |
| `python -m src.main monitor` | Continuous monitoring (default) |
| `python -m src.main setup` | Create a test position (supply + borrow) |
| `python -m src.main supply 0.01` | Manual supply |
| `python -m src.main borrow 10` | Manual borrow |
| `python -m src.main repay 5` | Manual repay |
| `python -m src.main audit` | Show audit log summary |

## Configuration

All config in `.env` or environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `KEEPERHUB_API_KEY` | — | API key from app.keeperhub.com (required) |
| `WALLET_ADDRESS` | — | Your KeeperHub Turnkey wallet address |
| `CHAIN_ID` | `11155111` | Sepolia testnet. Use `1` for mainnet |
| `HEALTH_FACTOR_THRESHOLD` | `1.5` | Trigger rebalance below this |
| `REPAY_FRACTION` | `0.15` | Fraction of debt to repay per trigger |
| `MONITOR_INTERVAL` | `30` | Seconds between checks |

## Audit Trail

Every action is logged to `logs/audit.jsonl`:

```json
{
  "timestamp": "2026-07-17T09:31:00Z",
  "event_type": "trigger",
  "trigger": "health_factor=1.4201",
  "decision": "repay 1.800000",
  "execution": {
    "tx_hash": "0xabc123...",
    "gas_used": "142000",
    "status": "success",
    "explorer_link": "https://sepolia.etherscan.io/tx/0xabc123..."
  }
}
```

View with: `python -m src.main audit`

## Architecture

| Layer | Technology |
|-------|-----------|
| Agent | Pure Python (stdlib only) |
| MCP Client | Streamable HTTP transport (urllib) |
| Execution | KeeperHub MCP — `execute_protocol_action`, `execute_check_and_execute` |
| Protocol | Aave V3 (supply, borrow, repay, withdraw) |
| Chain | Ethereum Sepolia (testnet) / Mainnet |
| Wallet | Turnkey non-custodial (via KeeperHub) |

## Supported Aave V3 Actions

| Action | Type | Description |
|--------|------|-------------|
| `aave-v3/get-user-account-data` | Read | Health factor, collateral, debt |
| `aave-v3/get-user-reserve-data` | Read | Per-asset position |
| `aave-v3/supply` | Write | Supply collateral |
| `aave-v3/borrow` | Write | Borrow against collateral |
| `aave-v3/repay` | Write | Repay debt |
| `aave-v3/withdraw` | Write | Withdraw collateral |
| `aave-v3/set-collateral` | Write | Toggle collateral flag |

## Hackathon

- **Event**: [KeeperHub Agents Onchain Hackathon](https://dorahacks.io/hackathon/agents-onchain/detail)
- **BUIDL**: [#47135](https://dorahacks.io/buidl/47135)
- **Category**: DeFi / AI Agents
- **Dates**: July 27 — August 13, 2026

## License

MIT
