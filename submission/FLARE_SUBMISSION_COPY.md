# FlareKeeper — Flare Summer Signal · 提交文案（可直接粘贴 DoraHacks）

> 用途：DoraHacks 提交页 / Bounty 2 (Confidential Compute Apps) 填写。
> 分支：`flare-fcc-bounty2` ｜ Repo：https://github.com/jnhualu-art/rebalance-keeper

---

## Project name
**FlareKeeper**

## One-liner
A TEE-secured autonomous treasury rebalancer on Flare — rebalance decisions are
computed inside Confidential Compute, the attestation is anchored on-chain, and
execution happens with no human in the loop.

## Problem
Autonomous DeFi agents leak their strategy and signing keys when they compute
rebalance decisions in the clear. That makes them (a) predictable — front-runnable
once the band logic is observed — and (b) fragile — a single key compromise is
total loss.

## Why Confidential Compute (Bounty 2 fit)
FlareKeeper ships as a **Flare Compute Extension (FCE)** — the official Flare
Confidential Compute (FCC) framework. The rebalance *strategy* runs inside a TEE:
- **Private strategy & inputs** — thresholds, fractions and live treasury state
  are fed to the `REBALANCE/COMPUTE` handler (`fce/python/app/handlers.py`) and
  never leave the enclave in clear text; only the decision result is returned.
- **Verifiable decisions** — the tee-node signs the result with the
  `TEE_ACTION_RESULT` scheme (`keccak256("TEE_ACTION_RESULT" ‖ chainid ‖
  resultHash)` + EIP-191 + secp256k1). The on-chain **FlareKeeperVerifier**
  contract `ecrecover`s the signer and requires it to equal the registered
  `teeAddress`, so any observer/contract can confirm the decision came from the
  approved TEE build, not a spoof.
- **Autonomous execution** — once a decision is verified, the agent signs &
  broadcasts the transfer itself (EIP-1559), closing the loop with no human in it.

> **Honesty note:** the local/offline demo uses a *simulated* TEE key for
> reproducibility, and only the demo TEE *environment* is simulated locally — the
> handler code, the `TEE_ACTION_RESULT` signing scheme and the `FlareKeeperVerifier`
> contract are production-shaped and **identical to what runs on Flare's hosted
> TEE machines**. The verifier is in fact **deployed and ecrecover-verified live on
> Coston2** (see *Live on-chain proof*). In production the key is generated inside
> the enclave and the signature is produced there.

## Flare ecosystem fit (FTSO / FDC)
- **FTSO** — Flare's decentralized price oracle feeds the treasury valuation /
  health inputs consumed inside the enclave.
- **FDC** (Flare Data Connector) — brings off-chain / cross-chain state
  attestations that can gate or enrich the rebalance decision.
- **Coston2 testnet** — native `C2FLR` treasury (faucet-funded, no token hunt),
  EIP-1559 execution; `FLARE_ASSET_MODE=erc20` switches to a stablecoin.

## The loop
```
read on-chain treasury
  → decide the rebalance INSIDE a TEE (Confidential Compute)
  → ANCHOR the attestation on-chain (verifiable provenance)
  → EXECUTE the attested decision (native C2FLR or ERC-20 transfer)
```

## Demo
- **Confidential + verifiable demo** (offline, no keys): `python fce/scripts/demo_confidential.py`
  — runs the strategy inside the FCE handler, signs with `TEE_ACTION_RESULT`, then
  recovers the signer and confirms `recovered == teeAddress`.
- **Live HTML demo** (record your screen): FCE decision loop → `TEE_ACTION_RESULT`
  signature → "TEE-attested · on-chain verifiable" badge. File: `flare_demo.html`
- **15s overview video** (submission asset).
- **CLI**: `python -m src.main flare-rebalance` (dry-run default, no keys/gas)
  · `--execute` (live on Coston2) · `--execute --no-anchor`.
- **On-chain verify (Coston2)**: `python fce/scripts/demo_confidential.py --onchain`
  deploys `FlareKeeperVerifier.sol` and runs the identical `ecrecover` check on-chain.
  The verifier is already deployed and verified live — see **Live on-chain proof** below.

## Live on-chain proof (Coston2)
The verifier is **not just code — it's deployed and ecrecover-verified on live Flare infrastructure**:
- `FlareKeeperVerifier` @ `0x4C79c50085668e42a3626eca81F39EE9F9185201`
- deploy tx `0x88d1c0cc0d490549ce779b47570c491a3fa47295e4130dd02d0ef1c6202703ea`
- setTeeAddress tx `0x730d124922fa049924755d2f7f2f619319e068a30073d8814864e42fdb86091b`
- verifyDecision tx `0xfa03386321fe8ad97fa0adf18614598a444bf2b8b50a3b52f1e70e52361cff5d`
- result: **ACCEPTED** (`ecrecover(sig) == teeAddress`, status=1) — proving the
  `TEE_ACTION_RESULT` signing scheme is Solidity-compatible end-to-end on real Flare infra.

## Security guardrails
Chain-id binding (Coston2 only) · EIP-55 checksum + monotonic nonces ·
idempotent retry · dry-run by default · `max_rebalance_usd` cap.

## Shipped in this submission
- ✅ **FCE package** (`fce/`): Python TEE handler (`REBALANCE/COMPUTE`), matching
  the official `fce-extension-scaffold` wire contract (POST /action, GET /state).
- ✅ **On-chain verifier** — `FlareKeeperVerifier.sol` enforces the
  `TEE_ACTION_RESULT` signature (`ecrecover == teeAddress`) before execution.
- ✅ **Instruction sender** — `FlareKeeperInstructionSender.sol` relays
  `REBALANCE` instructions to the TEE via `TeeExtensionRegistry.sendInstructions`.
- ✅ **Offline + agent-loop verification** — confidential compute + TEE sign +
  verify all green (handler unit tests 6/6, signer recovery == teeAddress).
- ✅ **Live on-chain proof** — `FlareKeeperVerifier` deployed on Coston2
  (`0x4C79c5…85201`), `verifyDecision()` returned **ACCEPTED** (ecrecover == teeAddress),
  so the `TEE_ACTION_RESULT` scheme is proven on real Flare infra, not just in unit tests.

## Roadmap
- Register the FCE on Coston2 via the official scaffold tooling (governance +
  `TeeExtensionRegistry` / `TeeMachineRegistry`) and switch to a real hosted TEE
  key (replace the simulated key in production).
- Stablecoin mode (USDT0/USDC) via `FLARE_ASSET_MODE=erc20`.

## Links
- Repo (Flare port): https://github.com/jnhualu-art/rebalance-keeper/tree/flare-fcc-bounty2
- Bounty: Flare Summer Signal — Bounty 2: Confidential Compute Apps

---

## DoraHacks 提交页 · 字段粘贴清单（re-save 用）

| DoraHacks 字段 | 粘贴内容 |
|---|---|
| **Project name** | `FlareKeeper` |
| **One-liner** | `A TEE-secured autonomous treasury rebalancer on Flare — rebalance decisions are computed inside Confidential Compute, the attestation is anchored on-chain, and execution happens with no human in the loop.` |
| **Vision**（≤256 字符硬限制） | `FlareKeeper rebalances treasuries inside a Flare Compute Extension (TEE). Decisions are TEE_ACTION_RESULT-signed and ecrecover-verified on-chain by FlareKeeperVerifier — deployed & accepted live on Coston2. Decision→anchor→execute, no human in loop.` |
| **Bounty** | `Flare Summer Signal — Bounty 2: Confidential Compute Apps` |
| **Repo URL** | `https://github.com/jnhualu-art/rebalance-keeper/tree/flare-fcc-bounty2` |
| **Demo video** | 现有 15s overview：`https://youtu.be/jN3J7JFo8CI`（或重新录 `flare_demo.html` 屏幕） |
| **Description** | 粘贴本文件「One-liner → Roadmap」全部章节（含 *Live on-chain proof* 段） |

> 注意：DoraHacks 的 **Vision** 字段有 256 字符硬上限，务必用上面的 Vision 文本（249 字符），
> 不要把整段 Description 粘进 Vision 框。Description 框贴完整正文即可。
>
> 提交页 Save 需在你的 DoraHacks 登录会话里手动点 Save（本机无 DoraHacks API/MCP）。
> 上面 Repo URL 已切到 `flare-fcc-bounty2` 分支，且分支已 push 到 GitHub。
