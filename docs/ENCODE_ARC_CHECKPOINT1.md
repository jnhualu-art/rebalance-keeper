# Encode Club — Programmable Money Hackathon (Arc / Circle)
## Checkpoint 1 提交文案（2026-07-20 截止）

> 直接复制下面各栏到 Encode Club 项目页对应字段。Checkpoint 1 允许占位/WIP，
> 重点是**选对赛道 + 说清创意**。全程英文（评委为 Circle / 欧洲团队）。

---

### ① Project Name（项目名）
```
ArcKeeper — Autonomous USDC Rebalancing Agent
```

### ② Track（赛道）— 下拉选择
```
Agentic Economy
```
（不要选 DeFi；Agentic Economy 才匹配"agent 管理钱包、自主再平衡/支付"）

### ③ One-line / Tagline（一句话）
```
An on-chain agent that watches your stablecoin position and rebalances it in USDC — autonomously, sub-second, with no volatile gas token.
```

### ④ Idea / Description（创意描述，长文）
```
Problem
DeFi positions go unhealthy when markets move and nobody acts in time. Most "agents" only decide — they never settle. When they do settle, volatile gas, failed transactions, and MEV eat the margin, so autonomous risk management is impractical on most chains.

What we're building — ArcKeeper
ArcKeeper is an autonomous agent that keeps a stablecoin position healthy without a human in the loop:
- Monitors risk signals (health factor, collateral ratio, FX exposure) on a schedule or trigger;
- Decides a rebalance action (supply / repay / move liquidity), expressed purely in USDC;
- Executes it on Arc with sub-second settlement and USDC-denominated gas — no volatile gas token, no guessing fees;
- Uses Circle's Agent Stack so the agent holds its own wallet and pays/settles autonomously.

Why Arc / USDC (maps directly to the track's judging criteria)
- Clear decision logic tied to real signals: a risk threshold triggers a deterministic action.
- Autonomous settlement in USDC: repayments and moves are USDC-denominated with deterministic, sub-cent fees and instant finality.
- Uses Circle Agent Stack + Nanopayments for micro-actions between services (e.g. paying an alert/oracle service in USDC nanopayments).
- Predictable fees make continuous monitoring affordable — the core requirement for any self-running agent.

Proof it works
We already shipped a working version of this exact agent on Ethereum Sepolia (Aave V3), with 5 real on-chain transactions verifying an autonomous rebalance: health factor dropped to 1.2692 (DANGER) → the agent auto-repaid → recovered to 1.6923 (safe). We are porting that proven logic onto Arc + USDC + Circle Agent Stack for this hackathon.

Repo: https://github.com/jnhualu-art/rebalance-keeper (Arc port in progress)

By final submission
A functional MVP on Arc: the agent holds a Circle wallet, monitors a USDC position, and autonomously rebalances via the Agent Stack, with a 3-minute demo video and a full audit trail of triggers, decisions, and settled transactions.
```

### ⑤ Team（团队）
```
[你的名字 / handle]  —  solo builder (可在此加队友)
```
（ solo 也行；若组队把队友 handle 加上）

### ⑥ Repository link（仓库，checkpoint1 可留空或填现有）
```
https://github.com/jnhualu-art/rebalance-keeper
```
（注明 Arc 移植进行中即可；checkpoint 2 / 最终再补 Arc 专属分支）

---

## 提交后下一步（时间线）
- **现在（7/20）**：粘贴上面内容 → 建项目页 → 选 Agentic Economy → Save。
- **7/26 checkpoint 2**：补 Arc 移植进度 + 仓库链接（我会帮你起 Arc 端口骨架）。
- **8/8 注册截止 / 8/9–8/10 最终提交**：Arc 上可跑的 MVP + 3 分钟视频 + deck。
- 入围前 8 名 → 8 周 Circle 加速器（价值 > 现金奖金）。

## 为什么这赛事性价比高
RebalanceKeeper 的核心（监测→决策→自动链上执行）几乎原样可搬，执行层换成
Arc/USDC/Agent Stack 即可。你已有 5 笔真实 tx 证明 agent 真能跑——这是评委最看重的
"execution, not mockup"。等于**用一份已验证的资产，换一个 Circle 加速器名额**。
