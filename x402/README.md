# ArcKeeper x402 — agentic payments layer

Part of the **ArcKeeper** entry for **ETHOnline 2026**, targeting the
Hedera *AI & Agentic Payments* track.

## What this is

An autonomous agent that holds a stablecoin treasury and pays for the
services it consumes, per call, with no human in the loop and no API keys
or subscriptions anywhere in the path.

```
        ┌──────────────────────────┐
        │   ArcKeeper agent        │
        │   (Python, Arc treasury) │
        └────────────┬─────────────┘
                     │ needs a paid API call
                     ▼
        ┌──────────────────────────┐
        │  x402 client (Node)      │
        │  budget ceiling enforced │
        └────────────┬─────────────┘
                     │ 1. GET /signal
                     ▼
        ┌──────────────────────────┐
        │  x402-gated service      │
        │  402 + payment terms     │
        └────────────┬─────────────┘
                     │ 2. sign + pay via Blocky402
                     │ 3. retry with X-PAYMENT
                     ▼
              Hedera testnet
```

## Layout

| Path | Role |
|---|---|
| `src/config.js` | Environment loading, validation, integer amount math, log redaction |
| `src/server.js` | The x402-gated service (seller side) |
| `src/client.js` | The paying agent (buyer side) |

## Security design

These are the properties an audit of an *autonomous spender* should check,
and how each one is enforced:

| Risk | Control |
|---|---|
| Agent drains its own wallet on an overpriced or hostile service | Hard `MAX_PAYMENT_USDC` ceiling checked before signing; anything above it aborts |
| Malformed account id reaches the signing path | `shard.realm.num` format asserted at startup |
| Placeholder credentials accidentally used | `.env.example` placeholder key is explicitly rejected |
| Float rounding moves the amount | All amounts parsed to 6-decimal base units with `BigInt`; sub-unit precision rejected, never truncated |
| Private key leaks into logs or error text | `redact()` is the only projection allowed for logging; key errors never echo the key |
| Unbounded network wait | Every client request carries an explicit timeout |

## Setup

```bash
cp .env.example .env
# fill in HEDERA_ACCOUNT_ID and HEDERA_PRIVATE_KEY
```

## Known environment pitfalls

Three non-obvious traps were hit installing these dependencies on this
machine; recorded here so nobody re-derives them.

1. **A safe-delete shim intercepts npm's cache cleanup.** npm aborts with
   `[safe-delete] 操作失败 ... _cacache\tmp\...`. Work around it with an
   independent cache directory: `--cache <project>/.npm-cache`.
2. **npmmirror does not carry every Hedera dependency** (notably
   `@hiero-ledger/proto`). Install with
   `--registry=https://registry.npmjs.org` for this package tree.
3. **`@x402/hedera` pulls in a very large transitive tree** (Hedera SDK →
   React Native / Metro tooling). Resolution takes several minutes; use
   `--omit=optional` and run it in the background.
