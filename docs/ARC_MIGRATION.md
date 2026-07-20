# ArcKeeper — Arc (Programmable Money Hackathon) Migration

ArcKeeper is RebalanceKeeper re-architected for **Arc**, Circle's stablecoin-native L1,
for the Encode Club *Programmable Money Hackathon* — **Agentic Economy** track.

> Agentic Economy = "autonomous AI agents that hold wallets, manage treasury, settle
> jobs or rebalance funds using USDC." ArcKeeper is exactly that: an agent that monitors
> its own USDC treasury on Arc and autonomously rebalances it.

## Why Arc, and what's different from Aave V3

| | Aave V3 (Sepolia) | Arc (Testnet) |
|---|---|---|
| Type | Lending protocol on Ethereum L2/testnet | Standalone stablecoin-native L1 |
| Gas | ETH | **USDC (native)** |
| Position | Collateral + debt, health factor | **Treasury**: USDC balance vs floor |
| Rebalance | repay / supply via pool | pull USDC from reserve to restore floor |
| EVM? | yes | **yes** (standard JSON-RPC) |

Arc has **no Aave-style lending pool yet**, so ArcKeeper manages a *treasury* instead of a
borrow position. The agent watches its operating USDC balance; when it dips below a floor
(e.g. after autonomous payments / nanopayments), it rebalances by pulling USDC back from a
reserve wallet. This is the canonical Agentic Economy pattern and needs no human in the loop.

## Verified Arc Testnet parameters

| Param | Value |
|---|---|
| Chain ID | `5042002` |
| RPC | `https://rpc.testnet.arc.network` |
| Explorer | `https://testnet.arcscan.app` |
| USDC (ERC-20 interface) | `0x3600000000000000000000000000000000000000` (6 decimals) |
| Faucet | `https://faucet.circle.com` (select **Arc Testnet**) |

> ⚠️ **Sepolia testnet assets cannot be bridged to Arc.** You must request Arc Testnet USDC
> from the Circle Faucet. Arc's native gas token is USDC, so the faucet funds both gas and balance.

## Architecture (zero-dependency, stdlib only)

RebalanceKeeper deliberately avoids external dependencies. ArcKeeper reuses that design:

- `src/arc_client.py` — stdlib JSON-RPC client for Arc. Reads real on-chain USDC balances
  via `eth_call` (ERC-20 `balanceOf`) and `eth_getBalance`. Mirrors `keeperhub_client.py`.
- `src/arc_position.py` — treasury-health model + rebalance decision (SAFE/WARNING/DANGER/CRITICAL).
- `src/config.py` — `ARC_*` constants + `ArcRebalanceConfig` (floor, thresholds).
- `src/main.py` — new `arc-status` and `arc-rebalance` subcommands.
- `scripts/arc_status.py` — standalone reader (Checkpoint 2 proof).

### Autonomous execution layer (Checkpoint 3 core, already implemented)

- `src/arc_executor.py` — signs & broadcasts ERC-20 USDC transfers on Arc via `eth_account`
  (installed in the managed venv). Builds an EIP-1559 `transfer(address,uint256)` tx to
  `0x3600…0000`, signs locally, broadcasts with `eth_sendRawTransaction`.
- `src/arc_rebalancer.py` — turns a decision into a real on-chain action:
  - `topup`:   pull USDC from **reserve → operational** (when below floor)
  - `sweep`:   push excess USDC from **operational → reserve** (proof of autonomous action)
  - `run_once`: read → decide → act (fully autonomous loop body)

## Checkpoint plan

- **Checkpoint 1 (Jul 19)** ✅ Idea submitted: *ArcKeeper — Autonomous USDC Rebalancing Agent*.
- **Checkpoint 2 (Jul 26)** 🚧 *In progress* — this branch. Read a real Arc treasury position
  via `python -m src.main arc-status`. Execution layer (`arc_executor.py` + `arc_rebalancer.py`)
  already implemented and dry-run verified. Repo link + progress summary.
- **Checkpoint 3 (Aug 9)** — Functional MVP on Arc: live autonomous rebalance (signed USDC
  transfer), 3-min video, deck.
- **Demo Day (Aug 20)**.

## How to run (local)

```bash
# 1. Create TWO Arc wallets + fund both with testnet USDC from https://faucet.circle.com
# 2. Put addresses + keys in .env (keys are git-ignored, never committed):
#      ARC_WALLET_ADDRESS=0xYourOperationalWallet...
#      ARC_RESERVE_ADDRESS=0xYourReserveWallet...
#      ARC_PRIVATE_KEY=0xOperationalPrivateKey...
#      ARC_RESERVE_PRIVATE_KEY=0xReservePrivateKey...
# 3. Read the treasury:
python -m src.main arc-status
# 4. Dry-run a rebalance (builds tx, does NOT broadcast):
python -m src.main arc-rebalance --sweep 5 --dry-run
# 5. Live autonomous rebalance (signs + broadcasts a real USDC transfer):
python -m src.main arc-rebalance --sweep 5
#    or pull from reserve:  python -m src.main arc-rebalance --topup 5
#    or fully auto:         python -m src.main arc-rebalance
```

The reader talks to the **public** Arc Testnet RPC, so it works without any API key —
only a funded wallet is needed to see a non-zero balance. Execution requires a local
private key (from `.env`); signing is done locally and the raw tx is broadcast to Arc.
