# 适合你的高性价比黑客松（检索于 2026-07-19）

> 筛选标准：Web3/DeFi/onchain agent 方向、**线上**、能复用 RebalanceKeeper 这个已成型 BUIDL、
> 奖金真实、来钱相对快。今天是 2026-07-19。

## 一句话策略
**RebalanceKeeper 是一个可复用的核心资产**：Aave V3 链上自动再平衡 agent（已跑通真实 Sepolia 交易）。
用它打底，只需按各赛要求换执行层/加一层特性，就能多线投稿。优先打这三个：
**KeeperHub（已备好，7/27 提交）→ Encode Arc（agentic economy，8/9）→ Flare（TEE 隐私 agent，8/15）**。

---

## 排名表（按性价比 + 适配度）

| 优先级 | 平台 / 赛事 | 奖金 | 截止 | 与你的适配 | 复用 RebalanceKeeper? | 工作量 | 结论 |
|--------|------------|------|------|-----------|----------------------|--------|------|
| ⭐⭐⭐ | **DoraHacks / KeeperHub Agents Onchain** | $5,000 (稳定币) | 8/13（7/27 开放） | **完美**：强制要求用 KeeperHub，项目本来就是 | ✅ 直接用 | 已做完，7/27 点一次 Submit | **必投，等开放** |
| ⭐⭐⭐ | **Encode Club / Programmable Money (Arc·Circle)** | 8 周加速器名额 + Circle 生态 | 8/9–8/10（注册 8/8 截） | **极佳**：Agentic Economy 赛道 = "agent 管理钱包、跨链再平衡" 就是 RebalanceKeeper 概念 | ✅ 移植概念到 Arc/USDC/Agent Stack | 中：换执行层 | **高价值，现在加入**（checkpoint1=今天） |
| ⭐⭐ | **DoraHacks / Flare Summer Signal** | $12,000（两个 $6K bounty） | 8/15（44 天） | 好：Confidential Compute / TEE-secured agents 赛道 = 给 agent 加隐私执行层 | ✅ 加 TEE 隐私层 | 中高：需 Flare 集成 | **次选目标** |
| ⭐⭐ | **HackQuest / OKX.AI Genesis Hackathon** | **100,000 USDT** | ~2 天（注册将截） | 高：你**已参加过**；"在 OKX.AI 上发 Agentic Service Provider" = onchain agent | 视是否有 OKX agent | 2 天内极紧 | **能 2 天出货就冲，否则等下届** |
| ⭐ | **HackQuest / Injective Global Cup** | 1,000 USDT | ~3 天 | 高：Injective 是你背景生态 | 需 Injective agent | 紧+池小 | **ROI 低，除非现成 Injective agent** |
| ⭐ | **HackQuest / Arbitrum Open House Dubai (Online)** | 30,000 USDT | 107 天（未开启） | 好：Arbitrum DeFi 线上 | 可复用概念 | 低紧急 | **放雷达，暂不急** |
| — | DoraHacks / WTF!! summer | $1,500 | 8/1 | 一般：DeFi/TEE | 部分 | 池小 | 低优先 |
| — | Devpost (各 AI 赛) | 大但偏纯 AI | — | 低：Gemini XPRIZE $2M 等是纯 AI，非 Web3 | 不搭 | — | **Web3 开发者不优先** |

---

## 详细要点

### 1. KeeperHub Agents Onchain（DoraHacks）— 已备好
- 强制要求：项目必须用电 KeeperHub 作为链上执行层（RebalanceKeeper 正是）。
- 提交三件套：GitHub 链接 + demo 视频（YouTube 已传）+ 一笔 KeeperHub 执行的 tx。
- 我们已齐：GitHub ✅、视频 `https://youtu.be/UuerezHxdl4` ✅、repay tx `0x22aec...` ✅。
- **行动：7/27 开放当天去 hackathon 页 Submit BUIDL → Apply with Existing BUIDL → 选 RebalanceKeeper。**

### 2. Programmable Money Hackathon（Encode Club · Arc/Circle）— 高价值
- 赛道 Agentic Economy：「autonomous agents that hold wallets, make payments, manage risk, settle in USDC」。
- RebalanceKeeper 的"监测 HF → 自动 repay"概念几乎原样可搬，执行层换成 Circle Agent Stack + USDC。
- 奖励不是现金而是 **8 周加速器名额**（对想做 founder 的你价值 > 现金）+ Circle 生态资源。
- 时间线：启动 7/13，checkpoint1=**今天 7/19**，注册 8/8 截，最终提交 8/9–8/10。
- **行动：现在去 encodeclub.com 注册、建项目页、交 checkpoint1（idea 即可）。**

### 3. Flare Summer Signal（DoraHacks）— 次选
- Bounty 2 Confidential Compute Apps（$6K）：用 Flare TEE 做隐私 agent，正好给 RebalanceKeeper 加"策略隐私"包装。
- 44 天充裕，可作为 KeeperHub 之后的第二战场。

### 4. OKX.AI Genesis（HackQuest）— 赌一把
- $100K USDT 最大池，你已有参赛经验；但**注册约 2 天内截止**。
- 若你手上有能跑在 OKX.AI 的 agent（哪怕是 RebalanceKeeper 改个壳），2 天冲一波；否则放弃等下届。

### 5. Injective Global Cup（HackQuest）— 低 ROI
- 你背景有 Injective，但仅 $1K、3 天截止，性价比低。除非已有 Injective agent。

---

## 推荐执行排期
- **今天（7/19）**：Encode Arc 注册 + 交 checkpoint1（idea 占位）。
- **7/27**：KeeperHub 开放 → 提交 RebalanceKeeper。
- **8/9**：Encode Arc 最终提交（移植版 RebalanceKeeper on Arc）。
- **8/15**：Flare 最终提交（RebalanceKeeper + TEE 隐私层，可选）。
- **随时**：若 OKX.AI 还能赶（2 天内），冲一把 $100K。

## 备注（不在你清单里但值得关注）
- **ETHGlobal**：Web3 圈最大黑客松系列，奖池常 $50K–$100K+，纯线上多场。你清单没列，但 ROI 最高，建议补关注 `ethglobal.com`。
- 真实链上交易是这些赛的共同硬要求——你已有 5 笔可验证 Sepolia tx，是核心优势。
