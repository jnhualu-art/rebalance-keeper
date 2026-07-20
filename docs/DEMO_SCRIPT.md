# RebalanceKeeper — Demo 视频脚本（3–5 分钟）

> 用途：AgenTank / KeeperHub 黑客松 BUIDL #47135 演示视频
> 节奏：共 6 个分镜，约 4 分钟。旁白为中文（可直接录制），英文要点见文末给国际评委。
> 真实链上数据（Sepolia）：钱包 `0x1573C3d151200922375bC48012BB1f232B2cF531`，Pool `0x6Ae43d3271ff6888e7Fc43Fd7321a503ff738951`
> 生命周期：HF 2.0 → 1.65 (WARNING) → 1.2692 (DANGER) → repay 32.5 USDC → 1.6923 (WARNING)

---

## 录制准备（开录前）

- 工具：OBS / 系统录屏，分辨率 1920×1080
- 预先打开 4 个窗口（用分屏或快速切换）：
  1. 终端：在 `rebalance-keeper/` 目录，`python -m src.main status` 已跑通
  2. VS Code：打开仓库，展示 `src/` 目录与架构
  3. 浏览器：Dashboard `http://127.0.0.1:8080/dashboard/index.html`（已起本地服务）
  4. 浏览器标签页：Sepolia Etherscan（repay tx `0x22aec5f3856dc29579069fcf4b3f7cf89a379d0c9676ee3976f7bfab16c6c857`）
- 角标常驻：屏幕右下角贴 "54 unit tests passing · BUIDL #47135"

---

## 分镜表

### 分镜 1 — 开场 & 痛点（0:00–0:35）

**画面**：黑底白字标题
```
RebalanceKeeper
你的 Aave V3 自动再平衡 Keeper
AgenTank / KeeperHub Hackathon · BUIDL #47135
```

**旁白**：
> 在 DeFi 里，借贷头寸最大的风险就是清算。当抵押品价格下跌，Health Factor 跌破清算线，你的资产会被瞬间清算、损失惨重。
> RebalanceKeeper 是一个运行在 KeeperHub 上的自动化 Keeper——它 7×24 监控你的 Aave V3 头寸，一旦 Health Factor 逼近危险区，就自动偿还债务、把抵押率拉回安全线。
> 今天我用真实 Sepolia 测试网，完整演示一次自动再平衡。

---

### 分镜 2 — 架构 & 代码仓库（0:35–1:20）

**画面**：GitHub 仓库 `github.com/jnhualu-art/rebalance-keeper`，滚动展示 `src/` 目录（monitor.py / rebalancer.py / keeperhub_client.py / audit.py）与 README 架构图。

**旁白**：
> 项目完全开源。核心是一个事件驱动的「监控—决策—执行」管道：
> monitor 模块定时读取 Aave V3 账户数据；rebalancer 根据 Health Factor 阈值决定动作——supply、repay 或 borrow；所有链上操作都通过 KeeperHub 的 MCP 协议完成，不需要自己跑节点，也不需要托管私钥。
> 一共 6 个模块，54 个单元测试全部通过。

**标注**：屏幕角落常驻 "54 unit tests passing"

---

### 分镜 3 — 真实链上建仓（1:20–2:00）

**画面**：终端展示 `python -m src.main status` 输出（钱包地址 + Pool），再展示 `setup_test_position.py` 执行日志。

**旁白**：
> 先在我们绑定好的钱包上建一个真实头寸：把 0.05 ETH 包装成 WETH 作为抵押，借出 100 USDC。此时 Health Factor 1.65，进入 WARNING 区。
> 为了演示价格压力，我再借 30 USDC，把 HF 压到 1.2692——已经跌破 1.5 的安全阈值，进入 DANGER。
> 注意，这全是真实的 Sepolia 交易，不是模拟。

**标注**：列出 supply tx `0x8079…`、borrow tx `0x012e…` / `0xd9b5…`（前 6 位）

---

### 分镜 4 — Dashboard 实时自动再平衡（2:00–2:50）

**画面**：浏览器打开 Dashboard，展示 HF 曲线 `2.0 → 1.65 → 1.2692`（红色段）→ `1.6923`（回升）；右侧审计表出现 repay 行。

**旁白**：
> 现在打开监控 Dashboard。看这条曲线——当 HF 跌破 1.5，系统立刻触发 DANGER 规则，自动发起一笔 32.5 USDC 的偿还，不需要任何人工干预。
> 偿还后 HF 回到 1.6923，重新进入 WARNING 安全区。整个过程在几秒内自动完成。

---

### 分镜 5 — 链上验证（2:50–3:40）

**画面**：点击审计表里 repay 那行的 tx 链接 → 跳转到 Sepolia Etherscan，展示 tx 状态 `success`、from 钱包地址、金额 32.5 USDC。

**旁白**：
> 关键是我们不靠嘴说。审计表里每一行都挂着真实的交易哈希。
> 点开这笔 repay 交易——Sepolia Etherscan 上显示它确实是 success，金额 32.5 USDC，从我刚才的钱包发出。同样，supply、两次 borrow 也都能在链上查到。这就是「可验证的自动化」。

**真实 tx 清单（可字幕展示）**：
| 动作 | Tx Hash |
|------|---------|
| Supply WETH | `0x807937e3b31f1cf05507d9a01a37ccb06d94054588376efefff8a662c0fbb28c` |
| SetCollateral | `0xb58a1fa4e2f89e259c139c676383e54beb75f5785a2ec7b4ec7422f40d17c7f0` |
| Borrow 100 USDC | `0x012e58fe1840a92b0d9325d9f78b573f0062960bb1ab50bd9a3ac12075b9860d` |
| Borrow 30 USDC | `0xd9b5b3571a3e92c7f2fe8d2130857ccab2bc59affa7c1c014801e0d70b2416e2` |
| Repay 32.5 USDC | `0x22aec5f3856dc29579069fcf4b3f7cf89a379d0c9676ee3976f7bfab16c6c857` |

---

### 分镜 6 — 结尾（3:40–4:20）

**画面**：回到 GitHub 仓库 + DoraHacks BUIDL 页面（BUIDL #47135）。

**旁白**：
> RebalanceKeeper 已经跑通完整的真实链上生命周期——代码开源、测试完备、每一步都可链上验证。
> 欢迎在 DoraHacks 上查看 BUIDL #47135，或在 GitHub 上 clone 试跑。我是陆俊华，谢谢观看。

**标注**：`github.com/jnhualu-art/rebalance-keeper` · `BUIDL #47135`

---

## 英文要点（给国际评委，可做成英文字幕或口播）

- **Problem**: DeFi borrowers get liquidated when Health Factor drops below the liquidation threshold.
- **Solution**: RebalanceKeeper — an autonomous Keeper on KeeperHub that monitors Aave V3 positions 24/7 and auto-repays debt when HF enters the DANGER zone.
- **Architecture**: `monitor → rebalancer → KeeperHub MCP → Aave V3 (Sepolia)`. No self-hosted node, no custodial keys.
- **Live proof**: Real Sepolia lifecycle — HF 2.0 → 1.65 (WARNING) → 1.2692 (DANGER) → auto-repay 32.5 USDC → 1.6923 (WARNING). Every step verified on Etherscan.
- **Links**: GitHub `github.com/jnhualu-art/rebalance-keeper` · DoraHacks BUIDL #47135

---

## 录制 Tips

- 语速中等，每分镜之间留 1–2 秒空场，方便后期剪辑。
- 分镜 2/3 可以加速播放（1.5×）终端输出，避免等待。
- Etherscan 页面提前加载好，分镜 5 直接切过去，不要现场等加载。
- 结尾把 GitHub 和 BUIDL 链接做成可点击卡片，方便评委跳转。
