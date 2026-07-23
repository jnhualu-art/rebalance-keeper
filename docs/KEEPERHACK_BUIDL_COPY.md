# KeeperHub · Agents Onchain — BUIDL Submission Copy

> **Project:** RebalanceKeeper — autonomous DeFi position rebalancing agent via KeeperHub MCP
> **Track:** Agents Onchain (DoraHacks)
> **BUIDL URL:** https://dorahacks.io/buidl/47135
> **GitHub branch:** https://github.com/jnhualu-art/rebalance-keeper/tree/keeperhub-hackathon
> **Demo video:** https://youtu.be/UuerezHxdl4

---

## 1. Pitch (30 words)

RebalanceKeeper is an AI agent that monitors your Aave V3 position and automatically repays or supplies collateral when your health factor drops — all executions go through KeeperHub MCP, on-chain and auditable.

## 2. Problem

DeFi borrowers face liquidation when collateral prices fall. Manual monitoring is stressful and slow; bots require private keys, gas management, and MEV protection. Users need an agent that executes reliably without surrendering custody.

## 3. Solution

- **Agent monitors** health factor via KeeperHub MCP `execute_protocol_action` (`aave-v3/get-user-account-data`).
- **Agent decides** whether to repay, supply, or do nothing based on threshold zones (SAFE / WARNING / DANGER / CRITICAL).
- **Agent executes** via KeeperHub MCP `execute_protocol_action` (`aave-v3/repay`, `aave-v3/supply`) and `execute_check_and_execute`.
- **Agent proves** every action with a real on-chain transaction hash and an audit trail (`logs/audit.jsonl`).

## 4. Why KeeperHub

KeeperHub is the on-chain execution layer: the agent does not hold a local private key for the core execution. Instead, it calls KeeperHub tools that sign, broadcast, and protect the transaction (MEV-aware, retry, gas estimation). This makes the agent both **autonomous** and **secure**.

## 5. How to Run

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Configure .env (KEEPERHUB_API_KEY, WALLET_ADDRESS, WALLET_INTEGRATION_ID)
# 3. Run a single autonomous evaluation
python -m src.keeperhub_agent --once

# 4. Or run continuous monitoring
python -m src.keeperhub_agent --watch
```

## 6. Real On-Chain Evidence (Sepolia)

| Action | TX Hash |
|---|---|
| supply WETH | `0x8079...bb28c` |
| setCollateral | `0xb58a...c7f0` |
| borrow 100 USDC | `0x012e...860d` |
| borrow 30 USDC | `0xd9b5...16e2` |
| repay 32.5 USDC | `0x22ae...c857` |

Full details and explorer links are in `README.md` and `docs/ARC_MIGRATION.md`.

## 7. Repo Structure

- `src/keeperhub_agent.py` — hackathon entry point (read → decide → execute)
- `src/keeperhub_client.py` — KeeperHub MCP HTTP client
- `src/rebalancer.py` — decision engine
- `src/monitor.py` — position polling
- `src/audit.py` — immutable audit log
- `docs/ENCODE_ARC_CHECKPOINT1.md` / `docs/ENCODE_ARC_CHECKPOINT2.md` — Arc extension docs

## 8. Future Work (post-hackathon)

- **Workflow**: encode the strategy as a KeeperHub `create_workflow` so users can call it via `call_workflow` / x402.
- **Multi-protocol**: extend to Morpho and Compound.
- **Mainnet**: migrate from Sepolia test position to mainnet with KeeperHub gas sponsorship.

---

**Submission checklist:**
- [ ] GitHub repo link (branch `keeperhub-hackathon`)
- [ ] Demo video
- [ ] Real on-chain transaction links
- [ ] BUIDL description pasted above
- [ ] Track: Agents Onchain
