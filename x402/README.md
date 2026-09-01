# ArcKeeper x402 — agentic payments layer

Part of the **ArcKeeper** entry for **ETHOnline 2026**, targeting the
Hedera *AI & Agentic Payments* track.

## What this is

An autonomous agent that holds a stablecoin treasury and pays for the
services it consumes, per call, with no human in the loop and no API keys
or subscriptions anywhere in the path.

The Python agent reads the real treasury on Arc Testnet, the Node service
sells that reading behind an x402 paywall, and a buyer agent pays per call.

```
   ┌─────────────────────────────┐
   │  ArcKeeper agent (Python)   │
   │  reads Arc Testnet treasury │
   └──────────────┬──────────────┘
                  │ scripts/export_snapshot.py  (atomic write)
                  ▼
        state/treasury-snapshot.json
                  │ read + freshness-checked on every request
                  ▼
   ┌─────────────────────────────┐
   │  x402-gated service (Node)  │
   │   GET /health    free       │
   │   GET /signal    $0.001     │  zone + recommended action
   │   GET /treasury  $0.005     │  full position + decision
   └──────────────┬──────────────┘
                  │ 402 → signed EIP-3009 authorization → settle
                  ▼
        Base Sepolia — the facilitator relays the transaction,
        so the payer signs but never pays gas
```

The two sides communicate through one file rather than a direct call, so
neither runtime depends on the other: the rebalance policy stays in Python
where it is tested, and the Node service keeps zero chain dependencies.

## Layout

| Path | Role |
|---|---|
| `src/config.js` | Environment loading, validation, integer amount math, log redaction |
| `src/server.js` | The x402-gated service (seller side) — two priced tiers |
| `src/client.js` | The paying agent (buyer side) |
| `src/snapshot.js` | Loads and validates the published position; builds each tier's payload |
| `src/balance.js` | Pre-flight check that the payer actually holds USDC |
| `../scripts/export_snapshot.py` | Reads the real Arc treasury and publishes the snapshot |
| `scripts/verify-settlement.mjs` | Proves a settlement tx landed, was relayed, and charged the right amount |

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
| Charging for data the seller does not have | The snapshot is loaded and freshness-checked *before* a price is quoted. A stale or missing snapshot returns 503 and never reaches the payment path, so there is nothing to refund |
| A tier's price drifting from the data it returns | Price and payload builder are declared together in `TIERS`; the route table is generated from it, so the two cannot disagree |
| Serving a paid route for free because of a config mismatch | Reaching `no-payment-required` on a priced route is treated as a server fault and fails closed |
| Selling a position that silently went stale | `SNAPSHOT_TTL_SECONDS` (default 300) makes the service refuse rather than serve old data |
| Chargebacks from a failed settlement | Settlement runs only after the body is produced; if the facilitator fails after that, the data is still served and the failure is logged |

## Setup

```bash
cp .env.example .env
# fill in HEDERA_ACCOUNT_ID and HEDERA_PRIVATE_KEY

# Publish the data the service sells. Without this the service returns 503.
cd .. && .venv/Scripts/python.exe scripts/export_snapshot.py
```

The snapshot expires after `SNAPSHOT_TTL_SECONDS` (300s by default). Re-run
the export to keep the service sellable — in a live deployment this is the
job of a timer, not of a human.

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

## Verified end to end

The full loop runs against the x402 reference facilitator on Base Sepolia:
service returns 402, client signs an EIP-3009 authorization, facilitator
settles on chain, client retries and receives the payload.

```bash
node src/server.js           # terminal 1
node src/client.js /signal   # terminal 2 — also try /treasury
```

Both tiers were bought and settled on chain. `scripts/verify-settlement.mjs`
reads the receipts back and confirms the amount charged matches the tier:

| Tier | Price | Settlement tx | Charged |
|---|---|---|---|
| `GET /signal` | $0.001 | `0x13ba2afb5114a5862b19781b4f05e74d4a28ee6d5ecdc33a783c6a584ea272fc` | 0.001 USDC |
| `GET /treasury` | $0.005 | `0xa29fa55676450e071d63495560b68002aacceaabb1201360f0da059702a19255` | 0.005 USDC |

```bash
node scripts/verify-settlement.mjs 0x13ba2afb... 0xa29fa556...
```

Each receipt shows `status: SUCCESS`, an `AuthorizationUsed` event, a
`Transfer` of exactly the tier price, and `tx.from` equal to the facilitator
relayer — confirming the payer paid the price and no gas.

**Refusal without charging was verified too.** Backdating the snapshot by an
hour makes the service return `503 {"error":"signal_stale"}` instead of a 402,
and the payer balance is unchanged across the attempt (19.993 USDC before and
after). A client that sees a 503 gets an explicit note that nothing was
settled, so a refused sale never looks like a lost payment.

Two things worth knowing before debugging a failed payment.

**The payer needs USDC but not ETH.** Under the exact scheme the payer signs an
authorization and the facilitator submits it, paying the gas. The settlement
above cost the payer 0.001 USDC and zero gas. `src/balance.js` reports this
correctly; do not top up gas to fix a payment failing for another reason.

**A bad payer address looks exactly like a signing bug.** A payer derived from
an obvious filler key such as `0xabab...` is a public address on a public
testnet and can be rejected at the token level, which surfaces only as
`invalid_exact_evm_signature`. Before suspecting the signing code, sign the
same authorization with a throwaway key: if the token then fails on balance
rather than signature, the original address is the problem. The controls live
in `scripts/diff-*.mjs`.

The facilitator's `invalidReason` distinguishes the two cases:
`invalid_exact_evm_signature` means the signature did not verify, while
`invalid_exact_evm_insufficient_balance` means it did and the payer is simply
short of funds.
