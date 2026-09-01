# BUIDL Submission — ArcKeeper

## 🏆 Project Name

**ArcKeeper** — an autonomous USDC treasury that earns by selling what it knows

## 📝 One-Line Description

An on-chain agent that manages a USDC treasury on Arc with zero human intervention — and monetizes its own risk signal through an x402 paywall, so the machine that watches the money also earns it.

## 🎬 Demo Video

https://youtu.be/8dwgH1LVzJU

## 🎯 Problem Statement

Treasury management is a 24/7 job with no 24/7 staff:

- **Balances drift.** An operational wallet that pays out all day silently drains toward zero; a reserve wallet accrues dust nobody deploys. Someone notices when something breaks.
- **Alerts are not actions.** Monitoring dashboards email a human, who opens a wallet, who moves funds — hours later, if at all.
- **Agent intelligence has no business model.** Every team rebuilding risk monitoring redoes the same work for free, because there was no standard way to charge $0.001 for an API call — until x402.

The missing piece in the agentic economy is not smarter agents. It is agents that **own money, move money, and charge money** — natively.

## 💡 Solution

ArcKeeper is one agent doing all three, on Arc (Circle's stablecoin-native L1):

1. **Owns money** — a real USDC treasury on Arc Testnet (operational + reserve wallets) with an explicit policy: floor 50, ceiling 75 USDC, four risk zones (SAFE / WARNING / DANGER / CRITICAL).
2. **Moves money** — reads its on-chain balance via stdlib-only JSON-RPC, decides deterministically, and *signs and broadcasts real ERC-20 transfers* (EIP-1559 via `eth_account`). Sweeps and top-ups between its own wallets are verified on chain, no human in the loop.
3. **Charges money** — the agent's decision is a product. An x402 gateway sells it: `GET /signal` for $0.001 (zone + recommended action), `GET /treasury` for $0.005 (full position + decision). Customers pay in USDC via EIP-3009; the facilitator settles on chain and pays the gas, so a payer needs USDC but no ETH.

The bridge is a snapshot file, not a function call: the agent's watch loop publishes what it just decided to `state/treasury-snapshot.json`, and the gateway sells that. **The decision a customer buys is literally the decision the agent acted on** — one `run_once()`, zero extra RPC, no drift between what is sold and what is done.

## 🏗️ Architecture

```
 Arc Testnet (chainId 5042002)              x402 gateway (Node)          Base Sepolia
 ┌─────────────────────────────┐           ┌──────────────────────┐    ┌──────────────────┐
 │  Treasury agent (Python)    │ snapshot  │  GET /signal  $0.001 │    │                  │
 │  read → decide → act        ├──────────▶│  GET /treasury $0.005│    │  USDC            │
 │  signed ERC-20 sweeps/topups│  atomic   │  402 → EIP-3009 sign │───▶│  settlement      │
 │  floor 50 / ceiling 75      │  write    │  facilitator settles │    │  (facilitator    │
 │  SAFE/WARNING/DANGER/CRIT   │           │  payer pays no gas   │    │   pays the gas)  │
 └─────────────────────────────┘           └──────────────────────┘    └──────────────────┘
```

Plus an **operator console** (`/dashboard`, served by the gateway itself): treasury band with the live balance marked against floor/ceiling, current zone, last executed action with explorer link, per-tier sales and revenue, and the settlement ledger — every attempt, pass or fail, booked to `state/settlements.json`.

## 🔗 What is actually on chain

| Proof | Network | Tx |
|---|---|---|
| Agent sweeps 5 USDC operational → reserve (signed, autonomous) | Arc | [`0xe24a56a2…b8664`](https://testnet.arcscan.app/tx/0xe24a56a208913fee980d339029b733309c0ddcd86de3ce4be3aae486a4b8664) |
| Agent tops up 5 USDC reserve → operational (signed, autonomous) | Arc | [`0xeae89dc2…740b3`](https://testnet.arcscan.app/tx/0xeae89dc2c4fd37ce4c1b812776755d3f8d48d7d89abdd523d935d888b75740b3) |
| `/signal` purchase settled — exactly $0.001 USDC to the agent's revenue wallet | Base Sepolia | [`0x5bd2da0c…9bcc`](https://sepolia.basescan.org/tx/0x5bd2da0ca3aa9e7e5443250766d42227777721f5d3059ab3a48bc1b774a49bcc) |
| `/treasury` purchase settled — exactly $0.005 USDC to the agent's revenue wallet | Base Sepolia | [`0x7a6c7512…3068`](https://sepolia.basescan.org/tx/0x7a6c7512f6763ae57977ec5c0647fcd6091a01943c1ce9d2c78493085fd93068) |

The treasury lives on Arc; the paywall settles on Base Sepolia through the x402 reference facilitator, which is where the ecosystem's facilitators run today. Arc-native settlement is a one-line change (a facilitator URL) the moment one exists.

## 🔐 Why the paywall can be trusted

- **Refuse before quoting.** The snapshot is freshness-checked *before* the payment path. Stale goods → 503, no 402, nothing to refund. Verified by backdating the snapshot: the payer's balance did not move.
- **The price is the server's word.** Declared in the 402; no part of the request can move it. Each tier's price and payload builder live in one object, so a tier cannot charge one price and serve another's data.
- **A failing handler never charges.** Settlement runs only after a successful body exists.
- **Failures are booked, not erased.** Failed settlements keep their ledger row with the error reason — an audit trail that only records wins is marketing, not accounting.

## 🔧 Tech Stack

- **Agent**: Python 3, stdlib-only Arc client (raw EVM JSON-RPC, no web3.py), `eth_account` for EIP-1559 signing
- **Gateway**: Node 22, `@x402/core` + `@x402/evm`, viem; no framework, no database
- **Payment**: x402 v2, exact scheme, EIP-3009 `transferWithAuthorization`, USDC, facilitator-settled (payer pays zero gas)
- **Console**: single-file vanilla JS, zero build step

## 🚀 Quick Start

```bash
git clone https://github.com/jnhualu-art/rebalance-keeper.git
cd rebalance-keeper

# Agent + snapshot publisher
python -m src.main arc-status
python scripts/export_snapshot.py --watch --interval 10

# Gateway + operator console
cd x402 && cp .env.example .env && node src/server.js
#   → http://localhost:3402/dashboard

# Be a customer
node src/client.js /signal      # 402 → sign → settle → data, $0.001
node src/client.js /treasury    # full position, $0.005
```

## 🧪 Testing

**148 tests, all passing**: 111 Python (decision model, snapshot publisher contract, wallet backends, client) and 37 Node (snapshot schema, TTL boundary, clock skew, settlement ledger incl. corrupt-file resilience, config validation).

## 🌟 Innovation Highlights

1. **Sell the decision, not a copy of it.** The snapshot is published from the same evaluation the agent acts on — the product and the behavior cannot drift.
2. **Refuse-before-quote.** Most paywalls charge first and argue later. ArcKeeper checks it has goods *before* inviting a payment, making refunds structurally impossible rather than merely rare.
3. **The agent is its own first customer.** The same USDC rails that rebalance the treasury (EIP-3009-style value transfer, signed by a machine) are the rails that monetize it.
4. **Zero-dependency agent.** The Arc client is raw stdlib JSON-RPC — a few hundred lines a human can actually audit, which matters when it holds signing keys.

## 🔮 Roadmap

- [ ] Arc-native x402 settlement (awaiting an Arc facilitator — gateway change is one URL)
- [ ] Second buyer persona: the agent *spends* x402 to buy oracle prices before rebalancing (machine-to-machine economy)
- [ ] Policy upgrade: APY-aware floor (hold less when reserve yield > operational need)
- [ ] Multi-treasury: one gateway, N agents, per-agent pricing

## 🔗 Links

- **GitHub**: https://github.com/jnhualu-art/rebalance-keeper/tree/arc-migration
- **Agent wallet on Arc**: https://testnet.arcscan.app/address/0x57047A430c4cfe335674e6bAD81b4D5F68ff505c
- **x402 protocol**: https://x402.org

## 👤 Author

**华Dee (Lu Junhua)**
Web3 / smart-contract engineer — Maple Finance syrup.fi lending protocol (ERC-4626, upgradeable proxies, Sigma Prime-audited), Craze Labs craze.fun EIP-712 relayer (2M gasless transactions, 8000+ QPS).
Encode Club Arc Programmable Money Hackathon — August 2026.
