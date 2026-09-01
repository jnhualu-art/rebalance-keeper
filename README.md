# ArcKeeper

> An autonomous agent that manages a USDC treasury on Arc (Circle's stablecoin-native L1) — and sells what it knows through an x402 paywall, so the machine that watches the money also earns it.

[![Hackathon](https://img.shields.io/badge/Encode%20Club-Arc%20Programmable%20Money-blue)](https://www.encode.club/)
[![Network](https://img.shields.io/badge/Treasury-Arc%20Testnet-orange)](https://testnet.arcscan.app)
[![Paywall](https://img.shields.io/badge/x402-USDC%20via%20EIP--3009-1f6feb)](https://x402.org)
[![Tests](https://img.shields.io/badge/tests-148%20passing-3fb950)](#testing)

ArcKeeper is RebalanceKeeper re-architected for the Agentic Economy. The original
agent watched an Aave position; this one owns a USDC treasury, rebalances it
on-chain with signed transactions and no human in the loop, and monetizes its
own risk signal with per-request micropayments.

## How it works

```
 Arc Testnet (chainId 5042002)              x402 gateway (Node)          Base Sepolia
 ┌─────────────────────────────┐           ┌──────────────────────┐    ┌──────────────────┐
 │  Treasury agent (Python)    │ snapshot  │  GET /signal  $0.001 │    │                  │
 │  read → decide → act        ├──────────▶│  GET /treasury $0.005│    │  USDC            │
 │  signed ERC-20 sweeps/topups│  atomic   │  402 → EIP-3009 sign │───▶│  settlement      │
 │  floor 50 / ceiling 75      │  write    │  facilitator settles │    │  (facilitator    │
 │  SAFE/WARNING/DANGER/CRIT   │           │  payer pays no gas   │    │   pays the gas)  │
 └─────────────────────────────┘           └──────────────────────┘    └──────────────────┘
        autonomous rebalancing               sells the decision          programmable money
```

One evaluation, one truth: the watch loop publishes the snapshot from the same
`run_once()` that acts, so the decision sold through `/signal` is *literally
the decision the agent acted on* — not a second, independent reading.

## What is actually on chain

| Proof | Network | Tx |
|---|---|---|
| Agent sweeps 5 USDC operational → reserve | Arc | `0xe24a56a208913fee980d339029b733309c0ddcd86de3ce4be3aae486a4b8664` |
| Agent tops up 5 USDC reserve → operational | Arc | `0xeae89dc2c4fd37ce4c1b812776755d3f8d48d7d89abdd523d935d888b75740b3` |
| `/signal` purchase settled ($0.001 → revenue wallet) | Base Sepolia | `0x5bd2da0ca3aa9e7e5443250766d42227777721f5d3059ab3a48bc1b774a49bcc` |
| `/treasury` purchase settled ($0.005 → revenue wallet) | Base Sepolia | `0x7a6c7512f6763ae57977ec5c0647fcd6091a01943c1ce9d2c78493085fd93068` |

The agent's treasury lives on Arc; the x402 paywall settles on Base Sepolia
through the reference facilitator (`x402.org/facilitator`), which is where the
ecosystem's facilitators are today. Arc-native settlement is the obvious next
step the moment an Arc facilitator exists — the gateway only needs a URL.

## Quick start

```bash
git clone git@github.com:jnhualu-art/rebalance-keeper.git
cd rebalance-keeper
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt  # python-dotenv only

# Terminal 1 — keep the goods on the shelf (publishes every 10s)
.venv/Scripts/python.exe scripts/export_snapshot.py --watch --interval 10

# Terminal 2 — the paywall + operator console
cd x402 && cp .env.example .env && node src/server.js
#   console:  http://localhost:3402/dashboard

# Terminal 3 — be a customer
node src/client.js /signal     # 402 → sign → settle → data, $0.001
node src/client.js /treasury   # full position, $0.005
```

## Running on Hedera (x402 via Blocky402)

The same gateway serves the **Hedera Agentic Payments** track by switching the
settlement rail. Set `CHAIN=hedera` and the 402 quote is emitted for
`hedera:testnet` with the USDC HTS token `0.0.429274`; the facilitator is forced
to Blocky402's testnet endpoint (`api.testnet.blocky402.com`) — no other
facilitator can settle Hedera payments.

```bash
# Seller (Terminal 2 above, Hedera rail)
CHAIN=hedera node src/server.js

# Buyer — for a real cross-account payment, use a dedicated buyer account:
node setup_hedera_buyer.mjs            # creates + associates a buyer account
# fund it with test USDC at https://faucet.circle.com (Hedera Testnet), then:
HEDERA_BUYER_ACCOUNT_ID=0.0.NEW  HEDERA_BUYER_PRIVATE_KEY=0x...  CHAIN=hedera \
  node src/client.js /signal
```

Requirements for a live paid call on Hedera: the **buyer** account must hold its
ECDSA private key, be associated with USDC `0.0.429274`, and carry a test-USDC
balance. The seller (`HEDERA_ACCOUNT_ID`) only receives — it does **not** sign,
so its private key is not needed for settlement; Blocky402 co-signs as fee payer,
so the buyer needs no HBAR either.

The agent itself:

```bash
python -m src.main arc-status                        # live treasury report
python -m src.main arc-rebalance --watch             # autonomous loop; each cycle
                                                     # also publishes the snapshot
python -m src.main arc-rebalance --sweep 5           # signed manual sweep
python -m src.main arc-rebalance --topup 5           # signed manual top-up
```

## The paywall's audit properties

- **Refuse before quoting.** The snapshot is loaded and freshness-checked
  *before* the payment path. Stale or missing goods → 503, no 402, nothing to
  refund. Verified by backdating the snapshot: balance unchanged across the
  refusal.
- **The price is the server's word.** Declared in the 402; no part of the
  request can move it. A tier's price and its payload builder live in one
  object, so a tier cannot charge one price and serve another's data.
- **A failing handler never charges.** Settlement runs only after the handler
  produced a successful body.
- **The payer needs USDC, not gas.** EIP-3009 `transferWithAuthorization`,
  settled by the facilitator relayer.
- **Every settlement attempt is booked.** Success or failure, with the tx hash
  and error reason, appended to `state/settlements.json`. An audit trail that
  only records wins is marketing, not accounting.

## Testing

148 tests: 111 Python (decision model, publisher contract, wallet backends,
client) and 37 Node (snapshot schema/TTL/clock-skew, settlement ledger,
config validation). `node --test` in `x402/`, `pytest` at the root.

## Repository map

| Path | What it is |
|---|---|
| `src/` | The Python agent: Arc client (stdlib-only JSON-RPC), decision model, signed execution, snapshot publisher |
| `scripts/export_snapshot.py` | Standalone snapshot refresher (`--watch`) |
| `x402/src/` | The gateway: config, snapshot validation, tier catalogue, settlement ledger |
| `x402/src/server.js` / `client.js` | Seller and buyer sides of the x402 paywall |
| `dashboard/index.html` | Operator console served by the gateway itself |
| `docs/`, `CHECKPOINT2_SUBMISSION_READY.md` | Hackathon checkpoint history |

## Links

- **GitHub**: https://github.com/jnhualu-art/rebalance-keeper/tree/arc-migration
- **Arc explorer**: https://testnet.arcscan.app/address/0x57047A430c4cfe335674e6bAD81b4D5F68ff505c
- **x402 protocol**: https://x402.org

## Author

**华Dee (Lu Junhua)** — Web3 / smart-contract engineer.
Maple Finance syrup.fi lending protocol (ERC-4626, upgradeable proxies),
Craze Labs craze.fun EIP-712 relayer (2M gasless transactions).
Encode Club Arc Programmable Money Hackathon — August 2026.
