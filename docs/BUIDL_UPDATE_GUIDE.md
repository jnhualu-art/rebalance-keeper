# RebalanceKeeper — YouTube 上传 + BUIDL 更新指南

> 你的 YouTube 视频链接：`https://youtu.be/UuerezHxdl4`

---

## 一、YouTube Studio 填写（按截图里的字段）

### 标题（把默认的 `2026 07 19 15 25 26` 换成）
```
RebalanceKeeper Demo — Autonomous Aave V3 Rebalancing via KeeperHub (BUIDL #47135)
```

### 说明 / 描述
```
RebalanceKeeper is an autonomous DeFi agent that monitors Aave V3 Health Factors and automatically rebalances positions via the KeeperHub MCP execution layer.

In this demo, we run a real position on Ethereum Sepolia:
1. Wrap 0.05 ETH to WETH and supply it as collateral.
2. Borrow 100 USDC — Health Factor drops to 1.65 (WARNING).
3. Borrow another 30 USDC to simulate price stress — HF falls to 1.2692 (DANGER, below the 1.5 threshold).
4. RebalanceKeeper detects the DANGER zone and auto-repays 32.5 USDC.
5. Health Factor recovers to 1.6923 (WARNING / safe zone).

All transactions are real and verifiable on Sepolia Etherscan:
• Supply WETH:        0x807937e3b31f1cf05507d9a01a37ccb06d94054588376efefff8a662c0fbb28c
• SetCollateral:      0xb58a1fa4e2f89e259c139c676383e54beb75f5785a2ec7b4ec7422f40d17c7f0
• Borrow 100 USDC:   0x012e58fe1840a92b0d9325d9f78b573f0062960bb1ab50bd9a3ac12075b9860d
• Borrow 30 USDC:    0xd9b5b3571a3e92c7f2fe8d2130857ccab2bc59affa7c1c014801e0d70b2416e2
• Repay 32.5 USDC:   0x22aec5f3856dc29579069fcf4b3f7cf89a379d0c9676ee3976f7bfab16c6c857

Project links:
GitHub:      https://github.com/jnhualu-art/rebalance-keeper
DoraHacks:   https://dorahacks.io/buidl/47135

Built for the KeeperHub Agents Onchain Hackathon.
```

### 标签 / Tags（YouTube 允许的写法，用逗号或换行）
```
Aave V3, KeeperHub, DeFi, Autonomous Agent, RebalanceKeeper, Blockchain, Web3, Sepolia, Crypto AI, DeFAI, Ethereum, Onchain Agent
```

### 缩略图（Thumbnail）
- 先用「自动生成」也可以。
- 建议：打开 `docs/demo_walkthrough.html` 第一页，截图标题卡片 `RebalanceKeeper / BUIDL #47135`，做成 1280×720 缩略图，更专业。

### 播放列表
- 可选：新建/加入一个「Hackathon Demos」或「Web3 Projects」播放列表。

### 公开范围（Visibility）
- **必须选「公开」**（Public），否则评委打不开。

---

## 二、DoraHacks BUIDL 页面修改

### 1. 打开编辑页（⚠️ Edit 不在公开页！）
DoraHacks 公开页对所有访客只读，**Edit 入口在你的账户中心（Profile）**：
1. 点头像（右上角）→ 点 **Profile** 进入账户中心
2. 在 Profile 页里找到 RebalanceKeeper 这个 BUIDL 卡片
3. 点卡片**右上角的「Edit」按钮**进入编辑表单
（直接访问 `dorahacks.io/buidl/47135/edit` 会返 403，必须从左上角头像→Profile 的卡片进入）

### 2. 填 Demo Video 字段
找到 **Demo Video** / **视频链接** / **Project Demo** 字段，粘贴：
```
https://youtu.be/UuerezHxdl4
```

### 3. 更新 BUIDL 描述（建议加一段「Live Demo」）
在描述最前面或最后面加一段（中英文皆可，建议都加）：

#### 中文
```
【真实链上演示】
我们在 Ethereum Sepolia 上完成了完整再平衡生命周期：
- 0.05 WETH 作为抵押，借出 130 USDC（含压力测试）
- Health Factor 跌至 1.2692（DANGER）
- Keeper 自动偿还 32.5 USDC
- Health Factor 回升至 1.6923（WARNING / 安全区）
全部 5 笔交易均为真实 Sepolia 交易，可在 Etherscan 验证。
Demo 视频：https://youtu.be/UuerezHxdl4
```

#### English
```
[Live On-Chain Demo — Real Transactions on Ethereum Sepolia]
RebalanceKeeper ran a full autonomous rebalance lifecycle on Sepolia:
- Supplied 0.05 WETH as collateral, borrowed 130 USDC (incl. a stress test)
- Health Factor dropped to 1.2692 (DANGER, below the 1.5 threshold)
- Agent detected the breach and auto-repaid 32.5 USDC via KeeperHub MCP
- Health Factor recovered to 1.6923 (WARNING / safe zone)

All 5 transactions are REAL and verifiable on Sepolia Etherscan:
• Supply WETH:     https://sepolia.etherscan.io/tx/0x807937e3b31f1cf05507d9a01a37ccb06d94054588376efefff8a662c0fbb28c
• SetCollateral:   https://sepolia.etherscan.io/tx/0xb58a1fa4e2f89e259c139c676383e54beb75f5785a2ec7b4ec7422f40d17c7f0
• Borrow 100 USDC: https://sepolia.etherscan.io/tx/0x012e58fe1840a92b0d9325d9f78b573f0062960bb1ab50bd9a3ac12075b9860d
• Borrow 30 USDC:  https://sepolia.etherscan.io/tx/0xd9b5b3571a3e92c7f2fe8d2130857ccab2bc59affa7c1c014801e0d70b2416e2
• Repay 32.5 USDC: https://sepolia.etherscan.io/tx/0x22aec5f3856dc29579069fcf4b3f7cf89a379d0c9676ee3976f7bfab16c6c857

Demo video: https://youtu.be/UuerezHxdl4
```

### 4. 检查/更新项目链接
确保以下链接已填：
- GitHub: `https://github.com/jnhualu-art/rebalance-keeper`
- Demo video: `https://youtu.be/UuerezHxdl4`

### 5. 报名到本次比赛（Submit to Hackathon）— 编辑页保存 ≠ 已报名
报名入口在 **hackathon 详情页**，不在 BUIDL 编辑页：
1. 进入 **KeeperHub Agents Onchain Hackathon** 详情页
2. 点 **Submit BUIDL**（若已报名会显示 **Manage Submission**）
3. 选 **Apply with Existing BUIDL** → 选 RebalanceKeeper → 选 Track → Submit for review
4. 提交后状态变 **In review**；能在 hackathon 的 BUIDLs 列表里搜到 RebalanceKeeper = 报名成功
- **判断是否已报名**：详情页按钮是「Submit BUIDL」(未报名) 还是「Manage Submission」(已报名)

⚠️ **时间线提醒（重要）**：本 hackathon **2026-07-27 12:00 (UTC+2) 才开放提交**。在此之前 hackathon 详情页**不会出现 Submit BUIDL 按钮**，属正常现象，不是你操作问题——等 7/27 开放当天再去提交即可。
- 官方提交硬性要求（hackathon 页「How to submit」写明）：① GitHub 源码链接 ② 一段 demo 视频（展示 agent 经 KeeperHub 在链上执行）③ 一笔 agent 经 KeeperHub 执行的交易链接。
- **这三样我们都已具备**：GitHub 已 push（`jnhualu-art/rebalance-keeper`）；YouTube demo `https://youtu.be/UuerezHxdl4`；5 笔真实 tx 中 **repay `0x22aec...`** 最能体现「agent 决策 → KeeperHub 执行」。开放当天直接填即可。

---

## 三、改完后的快速检查清单

- [ ] YouTube 标题、描述、标签已改，视频设为「公开」
- [ ] BUIDL #47135 的 Demo Video 字段已贴 `https://youtu.be/UuerezHxdl4`
- [ ] BUIDL 描述里加了真实 tx / demo 视频段
- [ ] BUIDL 已 Submit / 报名到本次比赛
- [ ] 用无痕浏览器打开 BUIDL 页面，确认视频能正常播放
