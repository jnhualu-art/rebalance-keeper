# ArcKeeper — ETHGlobal ETHOnline 2026 提交状态

> 正确的提交目标是 **ETHGlobal ETHOnline 2026**，不是 Encode Club（那场 8/9–8/10 已结束，是干扰项）。
> 源头：`docs/HACKATHON_OPPORTUNITIES.md`（2026-07-19 多线投稿清单，备注第 64 行「ETHGlobal：建议补关注」）。

## 赛事信息
- 平台：https://ethglobal.com/events/ethonline2026 （登录后进项目页 Submit Project，9/4 开放）
- 时间：**2026-09-04 – 2026-09-16**（现 9/1，Pre-Event 阶段）
- 总奖池：$100K
- 2026 新规：允许带已有 repo（existing_code welcomed）→ ArcKeeper 符合「Extend / Ship a Feature」

## Bounty 映射
| Bounty | 金额 | ArcKeeper 契合度 | 状态 |
|---|---|---|---|
| **Arc** | $10K | 项目本体就在 Arc Testnet（chain 5042002），自治再平衡 + 卖决策 | ✅ 代码在 Arc，最稳 |
| **Hedera — Agentic Payments** | $15K | x402 模块命中「live x402 服务 + 至少 1 笔真实付费」 | ⚠️ 代码就绪，真实付款被凭证卡住（见下） |
| 总池（评审奖） | 部分 | 完整 story：agent 自己养自己 | ✅ |

## x402 双链支持（已完成）
- 安装 `@x402/hedera@2.24.0`（与现有 `@x402/*` 同版本）
- `config.js`：`CHAIN=evm|hedera` 切换；Hedera 用 USDC HTS `0.0.429274`、Blocky402 testnet facilitator（**强制，忽略 .env 覆盖**）
- `server.js`：按 chain 注册 scheme（`registerExactEvmScheme` / `resourceServer.register('hedera:testnet', new ExactHederaScheme())`），402 报价正确（已验证 hedera:testnet + asset 0.0.429274 + payTo + feePayer 自动带入）
- `client.js`：Hedera 用 `createClientHederaSigner` + `ExactHederaScheme`，支持独立买家账户（env `HEDERA_BUYER_*`）

## 已验证（EVM / Base Sepolia 路径，真实链上）
- `/signal` 成交 $0.001：https://sepolia.basescan.org/tx/0x5bd2da0ca3aa9e7e5443250766d42227777721f5d3059ab3a48bc1b774a49bcc
- `/treasury` 成交 $0.005：https://sepolia.basescan.org/tx/0x7a6c7512f6763ae57977ec5c0647fcd6091a01943c1ce9d2c78493085fd93068
- demo 视频：https://youtu.be/8dwgH1LVzjU

## ⚠️ Hedera 真实付款的前置条件（已厘清，比最初判断更松）
- 现象：`node setup_hedera_buyer.mjs` 以 `HEDERA_ACCOUNT_ID=0.0.7326075` 为 operator 创建买家账户报 `INVALID_SIGNATURE`
- 根因：`.env` 的 `HEDERA_PRIVATE_KEY=0x2b52…` 不控制 `0.0.7326075`（派生公钥 `036a6fe6…` ≠ 账户真实公钥 `0281b6ff…`），该私钥在 testnet 不控制任何账户 → 用它当 operator 签名会失败
- **关键澄清：真实付款本身不需要卖家私钥**。x402 Hedera 付款 = 买家签名一笔 USDC 转账给 `payTo`（卖家），Blocky402 当 feePayer 付 HBAR；卖家只是收款方，**不签名**。所以只要有一个**我掌握其私钥、且持有 USDC 的买家账户**，就能付给 `0.0.7326075`（它已存在、`max_automatic_token_associations=-1` 收 USDC 自动关联，无需卖家私钥）
- 因此真正缺的不是卖家私钥，而是：**一个你知道 ECDSA 私钥的买家 Hedera testnet 账户**（新建最简单）

### 解法：给我一个"你知道私钥的买家账户"
1. **新建买家账户（推荐，~2 分钟）**：登录 https://portal.hedera.com → Testnet → 新建账户 → 复制它的 **account id** + **ECDSA private key** 贴给我
2. **复用已有账户**：若你手上有别的 Hedera testnet 账户且知道其 ECDSA 私钥，直接把 id+key 贴给我

### 我拿到买家 id+key 后的执行顺序
1. 用买家 key 通过 SDK 把 USDC `0.0.429274` 关联到买家账户（买家账户在 Portal 建时已带 HBAR 付关联费）
2. 你在 https://faucet.circle.com 选 **Hedera Testnet**、填买家账户 id，领 20 USDC
3. `HEDERA_BUYER_ACCOUNT_ID=<买家> HEDERA_BUYER_PRIVATE_KEY=<key> CHAIN=hedera node src/client.js /signal` → 真实跨账户付款
4. 验证买家 USDC 减少、卖家 `0.0.7326075` USDC 增加（Hashscan）、settlements 台账落账
5. 链接补进提交稿 + 更新 demo 视频/README

## 提交字段（直接照抄，完整文案见对话）
- Project name: `ArcKeeper`
- Tagline: 见 BUIDL_SUBMISSION 的 ONE-LINE DESCRIPTION
- Demo video: `https://youtu.be/8dwgH1LVzjU`
- GitHub: `https://github.com/jnhualu-art/rebalance-keeper`（branch `arc-migration`）
- Track 勾选：`Agent` / `x402` / `Arc` / `USDC`（按平台备选项）
- Team: 陆俊华 / GitHub `jnhualu-art` / X `@Jhhu73965779`
