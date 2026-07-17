# KeeperHub Agents Onchain Hackathon — RebalanceKeeper

Autonomous DeFi agent for Aave V3 health factor monitoring and rebalancing via KeeperHub MCP.

## Project Status

🚧 Work in progress for [KeeperHub Agents Onchain Hackathon](https://dorahacks.io/hackathon/agents-onchain/detail).

- BUIDL: https://dorahacks.io/buidl/47135
- Category: DeFi / AI Agents
- Network: Ethereum mainnet + Sepolia testnet

## What It Does

RebalanceKeeper monitors an Aave V3 lending position and automatically rebalances it when the health factor drops below a configurable threshold.

1. **Read**: Query Aave V3 user account data (health factor, collateral, debt, borrowing power).
2. **Decide**: Agent evaluates whether health factor is below threshold.
3. **Execute**: If conditions are met, KeeperHub executes a repay or supply transaction on-chain.

Every rebalancing action produces a real transaction hash — verifiable, auditable, and retryable through KeeperHub infrastructure.

## Tech Stack

- Aave V3
- KeeperHub MCP
- x402 / MPP (optional)
- Ethereum / Sepolia

## Getting Started

TBD

## License

MIT
