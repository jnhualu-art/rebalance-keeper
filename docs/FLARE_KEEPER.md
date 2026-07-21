# FlareKeeper — TEE-secured Autonomous Treasury Rebalancer

**Flare Summer Signal · Bounty 2 — Confidential Compute Apps**

FlareKeeper is an autonomous on-chain agent that keeps a treasury's operating
balance inside a safe `[floor, ceiling]` band — **without exposing its strategy
or signing keys**. Every rebalance decision is computed inside a Trusted
Execution Environment (TEE / Confidential Compute), the resulting attestation
is **anchored on-chain** so anyone can verify the move came from the approved
strategy, and only then is the transfer executed.

## Why this fits Confidential Compute

- **Private strategy & inputs.** The rebalancing logic (thresholds, fractions)
  and the live treasury state are sensitive — computing them in the clear leaks
  the agent's position. Running the decision in a TEE keeps both private.
- **Verifiable decisions.** The enclave produces an attestation over
  `(app_id, inputs, decision, nonce)`. FlareKeeper writes that attestation into
  the calldata of a 0-value on-chain tx, so any observer or contract can confirm
  the rebalance originated from the attested strategy binary — not a spoof.
- **Autonomous execution.** The agent signs and broadcasts the transfer itself
  (EIP-1559), closing the loop with no human in it.

## The loop

```
read on-chain treasury
   → decide the rebalance INSIDE a TEE (Confidential Compute)
   → ANCHOR the attestation on-chain (verifiable provenance)
   → EXECUTE the attested decision (native C2FLR or ERC-20 transfer)
```

## Architecture

| Module | Role |
|---|---|
| `src/flare_client.py` | Zero-dependency (urllib) Coston2 JSON-RPC reader: native C2FLR + ERC-20 balances, treasury snapshot. |
| `src/flare_tee.py` | Confidential Compute seam. `simulated` mode (demoable today) produces a deterministic attestation; `real` mode (TODO) submits to a Flare CC enclave for an SGX quote. |
| `src/flare_executor.py` | Signs + broadcasts transfers (native or ERC-20, EIP-1559) and **anchors the attestation** on-chain via a 0-value memo tx. |
| `src/flare_rebalancer.py` | Orchestrates read → decide (TEE) → anchor → execute. |
| `src/arc_position.py` | Chain-agnostic band evaluator (`[floor, ceiling]`), reused as the confidential strategy function. |

## Network (Coston2 testnet)

| Field | Value |
|---|---|
| RPC | `https://coston2-api.flare.network/ext/C/rpc` |
| Chain ID | `114` |
| Native gas | `C2FLR` (18 decimals) |
| Explorer | `https://coston2-explorer.flare.network` |
| Faucet | `https://faucet.flare.network/coston2` (dispenses C2FLR, FXRP, USDT0) |

**Treasury asset.** Coston2 has no canonical USDC, so FlareKeeper defaults to a
**native C2FLR treasury** (`FLARE_ASSET_MODE=native`) — it runs on Coston2 today
with only a faucet claim, no token contract to hunt. To track a stablecoin
(USDT0/USDC), set `FLARE_ASSET_MODE=erc20` + `FLARE_USDC_ERC20`.

## Setup

1. Create two Coston2 wallets (operational + reserve). Any EVM keypair works.
2. Fund both from the [Coston2 faucet](https://faucet.flare.network/coston2).
3. Fill `.env`:

```dotenv
FLARE_WALLET_ADDRESS=0x...            # operational
FLARE_RESERVE_ADDRESS=0x...           # reserve
FLARE_PRIVATE_KEY=0x...               # operational key (signs sweep + anchor)
FLARE_RESERVE_PRIVATE_KEY=0x...       # reserve key (signs topup)
# optional: FLARE_ASSET_MODE=erc20 + FLARE_USDC_ERC20=0x...
```

## Run

```bash
# DEFAULT is dry-run: build + attest + plan, broadcast NOTHING (no keys/gas
# needed). Safe to run anywhere.
python -m src.main flare-rebalance

# explicitly show it's a dry run
python -m src.main flare-rebalance --dry-run

# LIVE: actually broadcast the anchor + transfer on Coston2. Requires the
# operator to opt in. Alternatively set FLARE_ALLOW_LIVE=1 in .env.
python -m src.main flare-rebalance --execute

# live, but skip on-chain attestation anchoring
python -m src.main flare-rebalance --execute --no-anchor
```

## Security guardrails

FlareKeeper is built so a bug or a tampered config can **never** move more
than intended, nor send funds to an unexpected address:

- **No custom contract.** The agent only calls native transfers / ERC-20
  `transfer`, so there is no Solidity surface to audit.
- **Private keys never leave the machine.** Loaded from `.env` (gitignored),
  held only in memory, used by `eth_account` for local signing.
- **Anti-drain cap.** A single transfer is refused if it exceeds
  `FLARE_MAX_TRANSFER` (default 1000 treasury units).
- **Recipient allowlist.** Funds may only ever move between the operational and
  reserve wallets; any other recipient is rejected before signing.
- **Chain pinning.** The RPC must report `FLARE_CHAIN_ID` (114 = Coston2);
  a swapped / MITM node that lied about the chain is refused (stops fake
  balances tricking the agent into rebalancing).
- **Address validation.** Every `from`/`to` is validated before signing — no
  malformed addresses in transactions.
- **Pre-broadcast simulation.** Every tx is run through `eth_call` first; if it
  would revert, it is never signed or broadcast.
- **Safe-by-default broadcast.** `flare-rebalance` only broadcasts when given
  `--execute` (or `FLARE_ALLOW_LIVE=1`) — default is dry-run.
- **Honest TEE disclosure.** In `simulated` mode a clear runtime warning states
  the attestation is **not** enclave-backed; real confidential compute needs
  `FLARE_CC_REAL=1` + the Flare CC enclave.

> ⚠️ The "Confidential Compute" story is currently a **simulated attestation**
> (a `sha256` anyone can recompute), not a real SGX quote. It demonstrates the
> architecture honestly; wiring the real Flare CC enclave is on the roadmap.

## Status & roadmap

- [x] Coston2 JSON-RPC client (native + ERC-20 reads)
- [x] Confidential Compute seam with simulated attestation
- [x] EIP-1559 executor: native + ERC-20 transfers
- [x] On-chain attestation anchoring (verifiable provenance)
- [x] Full read → decide → anchor → execute loop + tests
- [ ] Real Flare Confidential Compute enclave (SGX quote) — swap `flare_tee._compute_real`
- [ ] On-chain quote verification (Flare CC verifier contract)
- [ ] FTSO price feeds for collateral-aware health; FDC for cross-chain reserve custody
- [ ] Demo video
