# BUIDL Submission — RebalanceKeeper

## 🏆 Project Name

**RebalanceKeeper** — Autonomous DeFi Position Rebalancing Agent

## 📝 One-Line Description

An on-chain agent that monitors Aave V3 health factor in real-time and automatically executes repay/supply actions via KeeperHub MCP to prevent liquidation — no manual intervention required.

## 🎯 Problem Statement

In DeFi lending protocols like Aave V3, borrowers must maintain their health factor (HF) above 1.0 to avoid liquidation. When market conditions cause collateral values to drop, positions can become undercollateralized within minutes — but most users:

- **Can't monitor 24/7** — they sleep, work, or simply forget
- **React too slowly** — by the time they see the alert, gas prices have spiked and the position is already being liquidated
- **Lack sophisticated strategies** — they don't know the optimal amount to repay vs. supply, or when to switch debt to lower-APY assets

The result: **$100M+ in avoidable liquidations** across DeFi every month.

## 💡 Solution

RebalanceKeeper is an always-on agent that:

1. **Monitors** the Aave V3 health factor every 30 seconds via KeeperHub MCP
2. **Analyzes trends** — not just current HF, but rate of decline and consecutive drops
3. **Classifies risk** into 4 zones: SAFE → WARNING → DANGER → CRITICAL
4. **Executes autonomously** using tiered strategies:
   - **WARNING + declining**: Pre-emptive repay 10% of debt
   - **DANGER**: Active repay 25% of debt  
   - **CRITICAL**: Emergency repay 50% of debt (bypasses cooldown)
   - **Fallback**: Supply more collateral if no debt token available
5. **Logs everything** to a tamper-evident JSONL audit trail

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    RebalanceKeeper Agent                  │
│                                                          │
│  ┌──────────┐   ┌──────────────┐   ┌──────────────┐    │
│  │ Monitor  │──▶│  Rebalancer  │──▶│  Executor    │    │
│  │          │   │              │   │              │    │
│  │ • Read   │   │ • Classify   │   │ • repay()    │    │
│  │   HF     │   │   alert level│   │ • supply()   │    │
│  │ • Trend  │   │ • Pick       │   │ • withdraw() │    │
│  │   analysis│   │   strategy   │   │ • borrow()   │    │
│  │ • Rate   │   │ • Estimate   │   │              │    │
│  │   of Δ   │   │   HF impact  │   │ Retry +      │    │
│  │ • Cooldown│   │              │   │ backoff     │    │
│  └────┬─────┘   └──────┬───────┘   └──────┬───────┘    │
│       │                │                   │            │
│       ▼                ▼                   ▼            │
│  ┌─────────────────────────────────────────────────┐   │
│  │              AuditLogger (JSONL)                 │   │
│  │  monitor → trigger → execution → tx → gas → result│  │
│  └─────────────────────────────────────────────────┘   │
│                          │                               │
└──────────────────────────┼───────────────────────────────┘
                           │
                    ┌──────▼──────┐
                    │  KeeperHub  │
                    │     MCP     │
                    │             │
                    │ • Aave V3   │
                    │   actions   │
                    │ • Turnkey   │
                    │   wallet    │
                    │ • On-chain  │
                    │   signing   │
                    └─────────────┘
```

## 🔧 Tech Stack

| Component | Technology |
|-----------|-----------|
| Agent language | Python 3.13 (zero external deps, stdlib only) |
| MCP transport | Streamable HTTP (JSON-RPC 2.0) |
| DeFi protocol | Aave V3 (Sepolia testnet → Mainnet ready) |
| Wallet | Turnkey non-custodial (via KeeperHub) |
| Audit log | JSONL (append-only, tamper-evident) |
| Dashboard | HTML + Chart.js (static, no backend) |

## 🚀 Quick Start

```bash
# 1. Clone
git clone https://github.com/jnhualu-art/rebalance-keeper.git
cd rebalance-keeper

# 2. Configure
cp .env.example .env
# Edit .env: add your KeeperHub API key

# 3. Check position status
python -m src.main status

# 4. Set up a test position (needs Sepolia ETH)
python -m src.main setup

# 5. Start monitoring (runs forever)
python -m src.main monitor
```

## 📋 Commands

| Command | Description |
|---------|-------------|
| `status` | Show current Aave V3 position with multi-level zones |
| `summary` | Full position summary with rebalancer recommendation (JSON) |
| `once` | Single health check (triggers rebalance if needed) |
| `monitor` | Continuous monitoring loop (default) |
| `setup` | Create test position (supply WETH + borrow USDC) |
| `supply <amt>` | Manual supply |
| `borrow <amt>` | Manual borrow |
| `repay <amt>` | Manual repay |
| `audit` | Show audit log summary |

## 🧠 Strategy Engine

### Alert Zones

```
HF ≥ 2.0     → SAFE      (no action, log only)
HF 1.5–2.0   → WARNING   (watch + pre-emptive if declining)
HF 1.2–1.5   → DANGER    (active rebalance: repay 25%)
HF < 1.2     → CRITICAL  (emergency: repay 50%, ignore cooldown)
```

### Trend-Aware Pre-emption

Instead of waiting for HF to cross a threshold, the agent tracks:
- **Average change per reading** over a 5-reading window
- **Consecutive decline count** — if HF dropped 4 times in a row, trigger early
- **Percentage rate of change** — detect accelerating decline

This means the agent can act **before** the danger zone if the trend is bad enough.

### Cooldown System

- After any rebalance action, a 120-second cooldown prevents over-rebalancing
- **CRITICAL zone bypasses cooldown** — emergency always fires
- DANGER respects cooldown to avoid rapid-fire transactions

## 🔐 Security Features

- **Non-custodial wallet** — Turnkey signs transactions, private keys never exposed
- **Idempotency keys** — every transaction has a unique key to prevent duplicates
- **Audit trail** — every monitor check and rebalance action logged to JSONL
- **Exponential backoff** — failed transactions retry with 1s/2s/4s delays
- **Session management** — MCP session IDs cached for 23 hours, auto-renewed

## 🎮 Demo Scenario

1. **Setup**: Supply 0.01 WETH as collateral, borrow 10 USDC
   - Initial HF ≈ 2.5 (SAFE)
2. **Simulate danger**: Manually withdraw some collateral
   - HF drops to ~1.3 (DANGER)
   - Agent automatically repays 25% of USDC debt
   - HF recovers to ~1.7
3. **Simulate critical**: Market crash simulation
   - HF drops below 1.2 (CRITICAL)
   - Agent emergency-repays 50% of debt, bypassing cooldown
   - HF recovers above 1.5
4. **View audit**: `python -m src.main audit` shows full action history

## 🌟 Innovation Highlights

1. **Trend-aware pre-emption** — Most keepers react to thresholds; we react to *trends*. If HF is declining for 4+ consecutive readings, we act before the threshold is breached.

2. **Tiered strategy engine** — Not just "repay everything." We calibrate response intensity to severity: 10% at warning, 25% at danger, 50% at critical. This minimizes unnecessary transactions and gas costs.

3. **Zero-dependency Python** — The entire agent runs on Python stdlib. No web3.py, no ethers.js, no heavy frameworks. Easier to audit, deploy, and trust.

4. **KeeperHub-native** — Built specifically for the KeeperHub MCP ecosystem. Uses `execute_protocol_action` for Aave V3 interactions and is ready for `execute_check_and_execute` for conditional on-chain automation.

5. **Production-ready audit trail** — Every decision is logged with full context: trigger → decision → execution → tx hash → gas → result. Not just for debugging — for regulatory compliance.

## 🔮 Roadmap

- [ ] **Multi-protocol support** — Extend beyond Aave V3 to Compound V3, Spark
- [ ] **Interest rate arbitrage** — Auto-switch debt to lower-APY assets
- [ ] **Gas optimization** — Batch transactions, use flash loans for rebalancing
- [ ] **Dashboard WebSocket** — Real-time HF streaming to browser
- [ ] **Mobile alerts** — Telegram/Discord notifications for critical events
- [ ] **Mainnet deployment** — Move from Sepolia to Ethereum mainnet

## 🔗 Links

- **GitHub**: https://github.com/jnhualu-art/rebalance-keeper
- **KeeperHub**: https://app.keeperhub.com
- **Aave V3 Sepolia**: https://sepolia.etherscan.io/address/0x6Ae43d3271ff6888e7Fc43Fd7321a503ff738951

## 👤 Author

**华Dee (Lu Junhua)**  
Web3 / Blockchain Engineer  
Aave V3 + KeeperHub MCP Hackathon — July 2026
