# 下一站黑客松机会（2026-07-20 核实）

## ⚠️ 重要更正
- **Unite DeFi（1inch x ETHGlobal）是 2025/7/25–8/8 已结束活动**，获奖公告已出（403 提交），2026 无法再投。此前分析的「2026 / 7/25–8/6 / 截止8/3 / $525k」年份有误。
- 2026 真实 ETHGlobal 线上继任者是 **ETHOnline 2026（9/4–16，async）**，1inch 为常驻赞助商。

## 🔥 首选近窗目标：KeeperHub - Agents Onchain Hackathon
- 平台：DoraHacks｜线上｜提交 **2026/07/27 开 → 截止 2026/08/13**
- 奖池：**$5,000**（1st $2,000 / 2nd $1,200 / 3rd $800）+ $1,000 bounties
- 核心要求：agent **必须经 KeeperHub 作链上执行层真实执行交易**（MCP server / x402 / MPP，结算在链上）
- 评判重点：**真实链上执行权重极高**——"a working transaction that executes through KeeperHub beats a polished demo that never touches a chain"
- 适配度：⭐⭐⭐⭐⭐
  - 你已是 KeeperHub 生态（BUIDL #47135 RebalanceKeeper，MCP endpoint `https://app.keeperhub.com/mcp` 已用）
  - ArcKeeper 的「自主检测+决策+执行」正是它要的；Arc 真实 USDC 转账证据（tx `0xe24a56a2` / `0xeae89dc2` / `0x22b1dfa9`）可直接复用为「执行 proof」
- 动作：拉 `keeperhub-hackathon` 分支，把 ArcKeeper 执行层从 raw RPC 改接 KeeperHub MCP，做「自主资金库 Agent 经 KeeperHub 真实再平衡」参赛

## 次级目标：ETHOnline 2026（更大奖池）
- 平台：ETHGlobal｜线上 async｜**2026/09/04–16**
- 1inch 常驻赞助商；RebalanceKeeper → 1inch API 应用 / Fusion+ 跨链 / 限价单协议「换壳」
- 时间衔接 Encode 终稿（8/9）之后

## 其他扫描（2026-07-20 状态）
| 活动 | 窗口 | 奖池 | 状态 / 适配 |
|------|------|------|------------|
| **KeeperHub Agents Onchain** | 7/27–8/13 | $5,000 | ✅ **主目标**，完美契合 |
| WTF!! hackathon summer (iExec Nox) | 截止 8/1 | $1,500 | DeFi+TEE 隐私，适配一般 |
| HashKey Chain Horizon · Japan | 截止 7/11/12 | $12k USDT | ❌ 已过 |
| CROO Agent Hackathon | 截止 7/12 | $10.2k | ❌ 已过 |
| OKX.AI Genesis (ASP) | 剩 ~2 天 | $100k | ❌ 太晚 |
| Injective Global Cup | 剩 ~3 天 | $1k | ❌ 太晚 |
| Flare Summer Signal | 至 8/14 | — | Flare 生态，可选 |
| Agent Builders Cup (Botcamp) | 8/1–31 | 交易 agent | 交易竞赛，可选 |
| ETHGlobal Lisbon 2026 | 7/24–26 | $125k | ❌ 线下 + 申请已过 |

## 关键日期
- **7/26**：Encode Checkpoint 2 提交（草稿已备 `docs/ENCODE_ARC_CHECKPOINT2.md`）
- **7/27**：KeeperHub 开赛 → 启动构建（主目标）
- **8/9**：Encode 终稿（checkpoint3）
- **8/13**：KeeperHub 截止
- **9/4–16**：ETHOnline 2026（次级目标）

## 建议策略
1. 7/26 提交 Encode Checkpoint 2（不暴露阈值驱动已完成）。
2. 7/27 起用 ~2.5 周做 KeeperHub：复用 ArcKeeper 自主执行能力，改接 KeeperHub MCP 执行层，主打「agent 真实链上执行」。
3. 8/9 交 Encode 终稿；8/13 交 KeeperHub。
4. 9 月用 ETHOnline 做大奖池冲刺（1inch 换壳）。
