# uscm-agent（中文说明）

**面向微服务 / 多模块业务系统的放置决策智能体**——通过治理"变更落在哪里"来
在持续迭代中把技术债务与复杂度维持在合理区间，因为结构性的债正是在放置中
复利累积的。

本仓库是 USCM-CC 变更成本统一货币模型（论文）的软件 artifact；代码与论文
构造的精确对应见 [THEORY.md](THEORY.md)（英文）。统计决策核心是确定性的、
可审计、可复现，通过 CLI（人类 / CI）与 MCP server（AI 编程智能体）双通道
暴露。

## 六句话理论

1. 功能（story）会被反复触及；若每次都落在同一模块，每次变更成本不变——
   这就是"放置正确"的操作性含义。
2. 功能落点散布到多个模块（"散落"）后，后续每次变更都要牵动多处——散落是
   持续计息的债务存量，不是静态坏味道。
3. 散落是一种**体制**，且**仅凭 git 历史即可预测**：
   `logit P(散落) = −1.01 + 0.93·log(nMR) − 0.01·KA − 0.61·GA`
   （nMR=功能上的合并数，KA/GA=作者数/作者集中度）。
4. 池化定律可**冷启动迁移**：出样本的 74 仓完整微服务系统上，冻结系数
   AUC 0.586 ≈ 本地重拟合 0.592（Java 业务仓 0.60–0.85；前端约 0.51，
   需本地重标定）。
5. 因此护栏第一天就能用先验系数上线，每月用本地遥测收紧——**两层标定**。
6. 历史回放（26 仓、1,125 功能、仅事前信息）：被报警功能最终重度散落比例
   0.81 vs 对照 0.43（**lift 1.88**）——决策效度首个正结果（相关性证据）。

## 决策规则

| 规则 | 决策 | 命令 |
|---|---|---|
| **R1′ 反散落护栏** | 为功能引入**新**放置单元、且其 P(散落) 越过系统基率 τ 的合并被拦下：要求放置理由或改放置 | `uscm check 仓 sha`（单合并，CI）· `uscm watch`（每日增量） |
| **R2′ 先收窄** | 越过 τ 的功能：按落点次数排序其既有单元——把变更留在里面，高风险期不扩大选项 | `uscm advise --story KEY` |
| **Φ 预算** | 功能落点数 Φ 越过其 nMR 分带的本地 P90 → 拆分/搬迁候选。Φ 无跨系统上界，预算是纯本地量 | `uscm advise` |
| **R3′ 局部异常** | 功能最近 ≥3 次变更规模持续高于其自身基线 → 供人工复核（统计告警，不是债的证明） | `uscm advise` |
| **评审分档 T0–T3** | 每个合并依同一组事前信号落一档评审决策：**T3** 先分解（越过规模门——本地 P90 只收紧、不放松配置上限；或带键合并一次把足迹扩张到 ≥3 单元）· **T2** 深评+放置讨论（R1′ FLAG 或前瞻 Φ 超预算，须附放置理由）· **T1** 标准评审（多单元同步与无键合并附逐单元评审焦点）· **T0** 机器+抽样（只管放置维度，不判正确性） | `uscm check`（review 块）· `uscm reviewstats` |
| **两层标定** | 每月本地重拟合、τ=本地体制基率、Φ 带更新，并跑三项自检（方向/份额漂移/报警精度） | `uscm calibrate` |

单合并裁决阶梯：`FLAG` / `PASS` / `OK`（跳过：无功能键 · 无源码落点 · 功能
首现）。所有评估**只用事前信息**——回放循环先裁决、后并入功能表。

## 快速开始（10 分钟，无需任何真实数据）

```bash
git clone <本仓库> && cd uscm-agent
python3 -m venv .venv && .venv/bin/pip install -e ".[test,mcp]"
bash demo/demo.sh
```

demo 生成确定性的合成微服务系统（8 仓、60 功能；散落按体制律本身种植），
然后跑完整闭环：init 回放 → calibrate（本地重拟合恢复种植方向
`log_nMR>0, GA<0`，CI 中有断言）→ advise 排行 → check 出 FLAG、评论文本与
评审档位（T0–T3）→ watch 增量 → report 月度报告。

## 用在真实系统上

```bash
mkdir ws && cd ws
cat > uscm.toml <<'EOF'
since = "2024-01-01"
repos = ["~/code/my-system/*"]     # 路径或通配，任意 git 仓组合

[[feature]]                        # 可选：你们的 story 编号方言
regex = "PROJ-(\\d+)"
tag   = "PROJ-{0}"
EOF
uscm init && uscm calibrate
```

手写 uscm.toml 之前，先对每个仓跑只读的**分支工作流预分析**——让配置来自
证据而非猜测：

```bash
uscm probe ~/code/my-repo          # 分支工作流、story 方言、单元风格
uscm probe ~/code/my-repo --toml   # 直接产 uscm.toml 脚手架
uscm probe ~/code/my-repo --json   # 机器可读，含 staging 的 graft 清单
```

`probe` 会给每个合并分类（落线 / 线间滚动 / 评审迭代 / 同步 / 特性内部），
发现落线集合（直连 vs release 列车流、快进合流时代），从源分支数字形状
提议 story 键正则，对 squash 型工作流（键覆盖率近零）与多线继承（逐线
worktree 必重复计数）给出告警，并预检单元风格退化（module 单元全是架构
层 → `pkg`；业务编码在类名前缀 → `camel`）。对二级流它会推荐 staging：
`--shared` 克隆、把列出的嵌套合并 `git replace --graft` 摘除、以
`mainline = false` 运行。

日常运营：`uscm watch [--fetch]`（巡检新合并）；CI 对每个 MR 跑
`uscm check 仓 sha --json` 解析 `verdict` 与 `review.tier`（FLAG/T2 要求
放置理由，T3 要求沿放置单元分解，评论文本可直接回贴）；每月
`uscm calibrate && uscm report`，随后 `uscm reviewstats` 看档位分布、T0
占比与 T2/T3 富集度；随时 `uscm advise --top 10` 看散落风险榜。

模块方案自动识别：Maven 多模块（multi）/ 单树 Java 包（single）/ Go-TS
目录前缀（flat2）/ 前端仓（front）。前端仓只有**不同页面**才算放置单元
（page→api→component 分层穿越是规范结构）；前端在池化先验下会告警要求
先本地重标定。

### MCP 接入（AI 编程智能体）

`pip install 'uscm-agent[mcp]'` 后，在任何 MCP 客户端注册：

```json
{"mcpServers": {"uscm": {"command": "uscm", "args": ["mcp"], "cwd": "/绝对路径/ws"}}}
```

工具：`uscm_status`、`uscm_calibration`、`uscm_check(repo, sha)`、
`uscm_advise(story?, top?)`。编程智能体在提 PR 前调 `uscm_check`，
在动手前调 `uscm_advise` 获知高风险功能应守在哪些既有单元内（R2′）。

## 证据与边界

| 结果 | 数值 |
|---|---|
| 池化体制律 | β(log nMR)=0.93±0.07，β(GA)=−0.61±0.16；n=3,010 功能 / 19 仓；CV AUC 0.623 |
| 池化冷迁移 | 留一仓 AUC 0.634 |
| 出样本系统 | 74 仓 / 2,882 功能：冻结系数 0.586 ≈ 本地重拟合 0.592 |
| R1′ 回放 | τ=0.38，10 个月 164 次报警；被报警功能重度散落 0.81 vs 0.43（lift 1.88）——相关性证据 |
| Φ 普适规模律 | 被否定（R² 中位 0.09）→ 改为本地分位数预算 |

**边界声明**：本模型只提供方向、排序、概率与预算告警；不提供绝对成本预测；
不提供功能级缺陷预测（三仪器零结果）；所有阈值需每月本地重标定；幅度不跨
系统外推，方向与排序可外推。

## 引用与许可

见 [CITATION.cff](CITATION.cff)（请同时引用 artifact 与论文）；MIT 许可。
