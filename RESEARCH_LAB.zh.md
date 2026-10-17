# Frontier Signal Lab

**追踪公开研究信号，把“他们可能往哪里走”变成我们可以证伪的小实验。**

Public evidence → falsifiable hypotheses → reproducible experiments.

追踪前沿实验室研究者与开源作者的个人公告、原创仓库、实际贡献、issue/PR/discussion。每个判断附原始链接、观察时间、替代解释和下一次检查条件。入职消息用于发现人物；研究优先级由技术证据决定。

本轮交付：[内存查询与全局快照对照](results/observer-query-treatment/report.md)完成 4 次加载、64 次更新，8894 项便携审计通过；两对 T/M 耗时比 1.069/1.016，轻量查询约 50 Hz，仅为两对短运行的描述值。保留六项科学负结果、无效历史 RSS 和旧时序拒绝。见[复核命令](fixtures/observer-query-treatment/README.md)与[研究判断](research/2026-10-17-observer-query-treatment.md)。

## 第一轮：2026-10-15

- **陈广宇 / Nathan Chen** 的[原帖](https://x.com/nathancgy4/status/2110522061953327565)发布于北京时间 **08:04:05**，宣布离开 Kimi；该帖没有宣布加入 Anthropic。新去向暂记 **未核验**。
- 他明确回顾 **KDA kernels、Attention Residuals、optimizers**。第一条研究假设：深度信息路由的下一步机会，在精度、优化动态与硬件预算的共同约束中。
- 首个可运行实验：**AttnRes budget probe**。在合成残差 bank 上比较压缩与选择策略，测数值损失、逻辑存储和打分开销。
- 第二个可运行实验：**Recovery contract probe**。用明确的事件轨迹注入崩溃、重复回执和上下文压缩并发，比较三种恢复协议。
- 其他优先切口：自动研究的封闭终评、RL 环境的可验证奖励。详见[研究判断与证伪条件](research/2026-10-15-frontier.md)。

10 月 15 日早期跟进：Peter 的 OpenClaw PR 当时未合并，新增异常 binding 诊断与保留测试；本项目据此完成独立的真实 SQLite 迁移/崩溃恢复实验。静默跳过与报警两组都保留原记录，但“诊断干净”与“工作完成”不能等同。时间线、来源变化及边界见 [H2 跟进](research/2026-10-15-h2-sqlite.md)。

此前适配器实验：pi 的事务队列 PR 已合并。本项目固定该 commit，执行未修改的数据库适配器代码，在本地 SQLite stand-in 上验证 6 条轨迹：排队写入能在前一事务回滚后完成，直接底层写入则随事务回滚。不是完整 harness 或 Cloudflare 生产验证；详见[适配器实验与新证据](research/2026-10-15-pi-adapter.md)。

北京时间 10 月 16 日跟进：OpenClaw 恢复 PR 已合并；FLA 的公开 commit 新增 CP 输出/梯度与布局对照；verifiers 新提案细化取证、评分与关闭 session 的顺序。本轮更新真实旧态升级和服务生命周期的验证门槛，新增实验为 0。见[研究判断与证据边界](research/2026-10-16-lifecycle-and-cp.md)。

随后完成 **AttnRes memory probe**：用独立进程实测 dense、完整 int8 反量化与分块 int8 的 CPU 内存峰值和耗时，并对照输出误差。测量包含解释器、输入和分配器；预先打包的合成 bank 不包含训练、反向或 GPU 成本。pi / OpenClaw 的新上下文修复与可复查边界见[内存实测与上下文跟进](research/2026-10-16-memory-and-context.md)。

上一轮跟进：执行 pi 修复前后两个完整、未修改的上下文转换模块，检查模型身份切换、thinking 和工具消息边界；无运行时依赖替身。Peter 新合并的停机恢复实现让 H2 进一步聚焦未完成任务的持久归属、停止/重置语义与跨进程进度。上游 CI 的失败和已核验测试日志单独记录，见[上下文实验与停机恢复证据](research/2026-10-16-context-and-shutdown.md)。

此前跟进：verifiers 的服务生命周期 PR2866 已合并，H4 从提案跟踪转入实际合并版本的评分/失败分支验证。OpenClaw 的旧建议撤销、同轮次快照替换和 lease 释放重试进一步细化 H2 的版本与活性边界；见[服务生命周期与下一实验门槛](research/2026-10-16-verifier-service-lifetime.md)。

此前实验：固定 Pythia-14m 的真实残差激活，执行逐步 int8 打包与 CPU 算子反向。输出差异约 0.9%，但这版 STE **没有减少反向保存的存储**，观测耗时/进程峰值更高；该实验未训练模型。OpenClaw 已合并后台进程丢失通知，kill 请求到终止确认的窗口仍待复现。见[真实激活实验与研究判断](research/2026-10-16-real-activation-and-exec-custody.md)。

此前实验：实际微调 Pythia-14m 全部 **1,406 万参数**，三个 seed、每组 3,072 个目标 token，对照 dense 与仅压缩反向保存张量的 int8。保存库存减少 **54%**，但 CPU 训练约慢 **50%**、进程峰值更高；两组最终保留集 NLL 均差于初始模型，未获质量收益。OpenClaw 原会话恢复和 verifiers 回放视图新增合并；来源、负结果与下一门槛见[训练成本与恢复边界](research/2026-10-16-training-and-replay-boundaries.md)。

此前实验：在相同预训练参数点比较三种反向保存策略。保留精确 loss 保存值恢复了局部解析梯度，但三个批次的完整模型梯度误差均未减半，预声明判据全部失败。见[梯度诊断与研究判断](research/2026-10-16-gradient-and-authority.md)。

此前实验：在精确 CE 下，进一步保留 13 个实际 LayerNorm 内的全部保存值；三个批次的完整梯度误差仍未减半，cosine 略降，对照梯度 hash 与前次完全相同。下一步预声明隔离其余保存范围，再验证实际更新保真度。FLA 硬件/版本/分派修复与 OpenClaw 收据身份、维护期限、策略重新准入的新证据见[本轮研究报告](research/2026-10-16-norm-saves-and-execution.md)。

此前实验：在精确 CE 与13个实际 LayerNorm 模块内保存值固定时，再保留6个实际注意力模块 forward 内的保存值，三个批次完整梯度相对误差从4.05–7.70降至0.034–0.041，cosine约0.999，全部预声明门槛通过。下一步验证实际优化器更新；训练质量与成本仍未获收益结论。公开草稿和会话延续新证据见[本轮报告](research/2026-10-16-attention-saves-and-continuation.md)。

此前实验：先保留了预训练权重上实际 AdamW 首步误差10.9%–11.9%的失败结果，并发布可安装的 [SaveScope](SAVESCOPE.md)。本轮另行预登记四步真实稠密暖启动：匹配 m/v/step4 的下一步更新误差0.77%–0.86%，三个主门槛均通过；同一暖启动权重上的零状态对照仍全部失败（10.51%–10.95%）。30次实际原生更新的数值/状态控制通过。它表明这组诊断对优化器状态敏感，不是压缩训练质量、成本或GPU收益。见[结果与复现](research/2026-10-16-accumulated-state-update.md)。恢复并发和评测工作区的公开源码信号见[独立证据记录](research/2026-10-16-recovery-concurrency-and-harness-root.md)。

此前实验：在新固定数据上分别执行8步dense/INT8历史，各在第4/8步以自己的完整theta/m/v/t审计实际更新，12个共同锚点全部通过（误差1.335%–1.564%）。但seed211第8步的跨历史m/v相对L2差异为0.861/1.955，局部通过不能推出轨迹接近或训练收益。84次原生更新的6384个参数步控制通过，公开无Torch收据核验器完成213926项检查。此前首步失败和训练成本/保留集负结果保留；见[完整结果、漂移与复现](research/2026-10-16-short-history-update.md)。恢复义务与摘要预算的[公开源码信号](research/2026-10-16-recovery-settlement-and-summary-budget.md)单列，H2/H4运行状态不升级。

此前工程产出：独立 Windows 真实解释器观察器的5个固定场景全部通过，包含32/64MiB健康对照、private阈值、超时和Job-close后代退出；1170项离线收据检查通过。旧成本研究六组负结果与无效parent RSS保留。见[工程结果与下一门槛](research/2026-10-16-process-observer.md)、[可复现代码与命令](fixtures/process-observer/README.md)。

此前工程产出：真实预训练加载/训练集成代码已冻结并执行一次，**在模型导入前失败**。四个已认证场景各发现两个未知后代而停止，只有exit37对照通过；实际模型加载和训练更新均为0。21个保留handle全部退出、五个Job归零；未知进程缺少image证据，下一版本须先查明完整进程身份。原始失败与14项成功审计拒绝结果完整公开，没有放宽规则重试。见[结果和下一门槛](research/2026-10-16-pretrained-training-observer.md)、[代码和复现命令](fixtures/training-observer/README.md)。本轮另有[因果前缀、配置版本和退出责任的公开证据](research/2026-10-16-causal-prefix-and-worker-custody.md)，不代表任何人的私下研究计划。

此前工程产出：带时间戳控制链的预训练集成 v2 冻结后执行一次，三组完成 Torch/Transformers 导入，随后因 Python 守卫拒绝 `socket.bind` 而失败；实际身份和 7 个线程通过对应检查，不能把通用报错当身份漂移。**模型加载和更新均为 0**，健康完成、忙循环、内存阈值与开销门槛尚未执行。两项精确失败对照通过，21 个保留身份退出、5 个 Job 为空。冻结成功审计保留 10 项拒绝；后验 800 项检查仅证明负记录未被改写。静态源码中的 IPv6 探测只是候选原因，缺少运行时地址和调用栈。下一步单独冻结有来源诊断和明确本地探测策略的真实训练集成。见[失败结果](results/training-observer-v2/report.md)、[复核命令](fixtures/training-observer-v2/README.md)及[上游编译/退出边界](research/2026-10-17-pretrained-observer-and-teardown-bounds.md)。

最新工程产出：单独冻结的真实预训练集成 v3 一次执行，**5/5 场景通过，3 次模型加载、6 次稠密更新**。16 组内存对照、22 次角色普查、37 对时间戳控制和全部21个保留进程退出通过；原始收据与无模型审计器已公开。每个模型导入的精确 urllib3 IPv6 bind 尝试有来源记录，但不证明 OS bind 成功，也不追认 v2 原因。观察器 held 窗口的父进程 CPU 成本0.140625秒与内存阈值越界量保留；不能当压缩提速、显存节省或质量收益。旧科学负结果和无效 RSS 不变。见[完整结果](results/training-observer-v3/report.md)、[复核命令](fixtures/training-observer-v3/README.md)及[新合并源码与下一门槛](research/2026-10-17-training-integration-and-replacement-failure.md)。

本轮实际测量：4 次固定模型加载、64 次稠密更新的 observer duty 研究完成一次，但冻结审计拒绝全部四组结束屏障顺序。5524/5528 项通过不等于验收通过；耗时比仅保留描述值，20 个保留进程正常退出、4 个 Job 归零。见[失败结果](results/observer-duty/report.md)与[来源及下一门槛](research/2026-10-17-observer-duty-and-validation-lifetime.md)。

## 快速运行

需要 Python 3.11+；pi 适配器实验、完整测试和一键复现另需 Node.js 24.19+。在线雷达另需 [GitHub CLI](https://cli.github.com/) 已登录（或 CI 中的 `GH_TOKEN`）。实验离线运行，不调用模型 API。

```bash
python -m pip install -r requirements.txt
python experiments/attnres_budget_probe.py --output results/attnres-budget
python experiments/attnres_memory_probe.py --output results/attnres-memory
python experiments/recovery_contract_probe.py --output results/recovery-contract
python experiments/sqlite_migration_probe.py --output results/sqlite-migration
node experiments/pi_adapter_queue_probe.mjs --output results/pi-adapter-queue
node experiments/pi_context_transform_probe.mjs --output results/pi-context-transform
python -m unittest discover -s tests -v

# 明确最近 7 天的有界采样；失败和截断会记录在报告中
python -m frontier_radar scan --config watchlist.json --output-dir reports/live --since-hours 168
```

可选的真实激活反向实验需要独立安装 CPU Torch，使用已提交 fixture 离线重放，无需下载模型：

```bash
python -m pip install --index-url https://download.pytorch.org/whl/cpu torch==2.9.1+cpu
python -m pip install numpy==2.3.5
python experiments/real_activation_autograd_probe.py --trace fixtures/real-activation/bank.npz --manifest fixtures/real-activation/manifest.json --output reports/runs/my-activation-replay --seeds 11 29 47 --warmup 1 --repeats 3
```

输出目录须全新。重新采集需要另装 Transformers/safetensors，并取得固定模型资产，见[采集说明](fixtures/real-activation/README.md)。

实际小模型训练使用另一份预声明数据。安装上述 CPU Torch 后，下载七项不可变、hash 固定的公开资产并离线训练；不调用付费 API：

```bash
python -m pip install -r requirements-real-activation.txt
python scripts/download_pythia.py --output local-state/models/pythia-14m-cf967c0 --record reports/my-training-assets.json
python experiments/activation_training_probe.py --model-dir local-state/models/pythia-14m-cf967c0 --data fixtures/activation-training/data.json --manifest fixtures/activation-training/manifest.json --output reports/runs/my-training --seeds 11 29 47 --steps 24 --batch-size 2 --lr 0.0001 --max-seconds 180
```

训练使用已提交 token 数据；重新分词准备的独立步骤见[训练 fixture](fixtures/activation-training/README.md)。每个 worker 有 180 秒训练循环上限，未完成的运行不能当成完整对照。

固定参数的梯度诊断复用上述模型与训练数据，额外读取预声明协议：

```bash
python experiments/activation_gradient_probe.py --model-dir local-state/models/pythia-14m-cf967c0 --data fixtures/activation-training/data.json --manifest fixtures/activation-training/manifest.json --protocol fixtures/activation-gradient/protocol.json --output reports/runs/my-activation-gradient
```

此命令不更新权重，不执行 holdout 前向；详见[协议](fixtures/activation-gradient/README.md)。

进一步隔离实际 LayerNorm 保存范围，同样复用本地模型和数据：

```bash
python experiments/activation_norm_gradient_probe.py --model-dir local-state/models/pythia-14m-cf967c0 --data fixtures/activation-training/data.json --manifest fixtures/activation-training/manifest.json --protocol fixtures/activation-norm-gradient/protocol.json --output reports/runs/my-activation-norm-gradient
```

该命令的三种方法都保留精确 CE，逐模块记录保存/取回；见[隔离协议](fixtures/activation-norm-gradient/README.md)。

进一步隔离6个实际注意力模块保存范围，三种方法均保留精确 CE 与 LayerNorm：

```bash
python experiments/activation_attention_gradient_probe.py --model-dir local-state/models/pythia-14m-cf967c0 --data fixtures/activation-training/data.json --manifest fixtures/activation-training/manifest.json --protocol fixtures/activation-attention-gradient/protocol.json --output reports/runs/my-activation-attention-gradient
```

完整作用域、独立 VJP 与判据见[attention 协议](fixtures/activation-attention-gradient/README.md)。

雷达生成 `snapshot.json`、`report.md` 和校验文件。它只读取公开 GitHub 数据。X 原帖、个人站、论文由研究者人工核验后进入[证据账本](research/sources.json)；扫描器不会声称已经自动覆盖整个 X。

首轮在线扫描于北京时间 **18:24–18:29** 完成：7 人、10 个仓库，采样到 117 条 commits、36 条 issues、98 条 PR 和 5 条 discussions；请求无失败。活跃仓库有分页截断，报告明确标注，因此这些数字不能当成最近七天的全部活动。[扫描报告](reports/2026-10-15-initial/report.md) / [快照与校验](reports/2026-10-15-initial/snapshot.json)。

## 实验能回答什么

给定残差向量与 pseudo-query，压缩或丢弃历史层信息会怎样改变 attention-over-depth 的输出？相同预算下，平均误差与长尾误差是否一致？先计算全部 logits 再 top-k 的方法，需要保留多少原始信息？

实验报告中的 bank bytes 是按数组形状计算的**逻辑持久存储**。它不等于 GPU 峰值显存；还需计入重建临时空间、activation、反向图、kernel 和模型其他参数。离线 block-sum 代理也不是完整 Block AttnRes 网络。

当前已做传统小型语言模型的等 token 全参数训练，数据仅为原创合成故事；未验证一般语言模型质量、学习深度路由或 GPU 吞吐。两组保留集 NLL 均退化，没有新架构优势结论。同参数点诊断中，仅保留精确 loss 或进一步保留实际 LayerNorm 保存值，都未使完整梯度误差减半；再保留实际注意力 forward 内保存值后，三个批次门槛通过；这只定位到广泛执行范围，不能归因单个 operand。下一门槛是实际优化器更新保真度，之后才是等 wall-clock 训练和独立终评。

## 首轮结果与跟踪对象

初始跟踪 **7 人 / 10 个仓库**：Nathan Chen、Guangxuan Xiao、Will Brown、Robert Tjarko Lange、Peter Steinberger、Mario Zechner、Nicholas Carlini。覆盖 Anthropic、OpenAI、Thinking Machines Lab、SakanaAI、Prime Intellect 的公开从业者与独立开源作者；每个人的角色证据和日期状态见 [watchlist.json](watchlist.json)，不统一贴“新入职”或“天才”标签。

| 实验 | 已运行的范围 | 可复查结果 |
| --- | --- | --- |
| AttnRes budget | 2 深度 × 3 分布 × 2 query × 3 seeds × 7 策略，252 条测量 | [完整表格](results/attnres-budget.md) / [原始 JSON](results/attnres-budget.json) |
| AttnRes memory | 预打包合成 bank；每个方法/形状/seed 在独立进程中测 CPU 内存与耗时 | [实测报告](results/attnres-memory/report.md) / [轨迹与 hash](results/attnres-memory/probe.json) |
| Real activation autograd | 固定 Pythia 的六层累计残差；3 pseudoquery seeds，逐步 int8 打包与 identity STE 算子反向，无模型训练 | [实测报告](results/real-activation/report.md) / [轨迹与 hash](results/real-activation/report.json) |
| Activation training | Pythia-14m 全参数 AdamW，3 seeds × 2 方法 × 24 步，固定合成 train/holdout；dense 前向与近似 backward | [负结果与复现](results/activation-training/report.md) / [完整逐步轨迹与 hash](results/activation-training/report.json) |
| Activation gradient | 相同 Pythia-14m 参数，3 批次 × 3 backward 策略；全参数误差与 CE 解析控制，无参数更新 | [失败判据与复现](results/activation-gradient/report.md) / [逐参数指标与 hash](results/activation-gradient/report.json) |
| Activation norm gradient | 相同参数与精确 CE，3 批次 × 3 策略；隔离 13 个实际 LayerNorm 保存范围，无参数更新 | [失败判据与复现](results/activation-norm-gradient/report.md) / [逐参数与逐模块记录](results/activation-norm-gradient/report.json) |
| Activation attention gradient | 相同参数与精确 CE/norm，3批次×3策略；隔离6个实际注意力 forward 保存范围，无参数更新 | [通过判据与复现](results/activation-attention-gradient/report.md) / [逐参数及逐模块记录](results/activation-attention-gradient/report.json) |
| Recovery contract | 3 协议 × 11 事件场景，33 条可回放轨迹 | [结果](results/recovery-contract/report.md) / [轨迹和假设](results/recovery-contract/probe.json) |
| SQLite migration | 2 诊断策略 × 5 故障配置，10 条真实数据库轨迹 | [结果](results/sqlite-migration/report.md) / [快照与 hash](results/sqlite-migration/probe.json) |
| pi adapter queue | 固定上游适配器 + Node SQLite stand-in，6 条确定性队列/事务轨迹 | [结果](results/pi-adapter-queue/report.md) / [实际 SQL 与事件](results/pi-adapter-queue/probe.json) |
| pi context transform | 修复前后完整模块；确定性消息、模型身份及工具调用边界，未发起 provider 请求 | [结果](results/pi-context-transform/report.md) / [输入输出与 hash](results/pi-context-transform/probe.json) |

一键重跑基础测试、此前六个实验并记录本地环境与文件指纹：`python scripts/reproduce.py`。[先前六实验运行清单](results/reproduction.json)记录了 Python、NumPy、SQLite、Node、配置和 SHA256；新增真实激活、训练、CE、LayerNorm 与 attention 梯度诊断使用上面的可选命令及各自报告清单。内存与耗时随运行环境变化，复现检查不要求这些数值逐字一致。

一个值得继续验证的观察：depth=128、64 tokens、dim=64、共享随机 query，在三种合成分布和三个 seed 上，int8 bank 的平均相对 L2 误差约 **0.00968**，逻辑 bank 从 **2 MiB 到 544 KiB**。但当前实现还生成 **2 MiB 的反量化临时数组**，所以这个结果不支持“实际峰值内存已降低”的结论。全量打分后的 oracle top-k 仍保留完整 bank；减少输出项并不自动减少存储。

恢复实验中，持久化先于 ACK / hook 消除了所枚举的已确认消息丢失，但单独这一步没有解决旧上下文、重复完成、终止重试复活和失败证据丢失。带版本、幂等回执与终止记录的协议通过本次有限场景；这不是生产可靠性证明。

该状态机也没有完整的已接受任务/完成结果账本，五项安全指标可能漏掉任务进度丢失。SQLite 实验另外报告未分类、阻塞与未完成工作；报警不会自动修复坏数据，runnable 也不是已完成。

## 证据规则

| 类型 | 可以支持 | 不能据此推断 |
| --- | --- | --- |
| 本人公告 / 官方论文 | 公开表达与已发布工作 | 私有计划、未宣布的新雇主 |
| 本人的合并 PR | 实际被接受的代码贡献 | 上游仓库全部工作都属于此人 |
| issue / discussion | 用户报告、问题、提案 | 官方认可、已复现、性能已证实 |
| fork / stars / profile | 发现线索、抓取时的自述 | 新原创成果、入职日期、研发进度 |
| 我们的实验 | 指定配置下可重复的结果 | 生产可用性、规模外推、领先承诺 |

`watchlist.json` 的机构字段均有来源和状态，首次观察不等于首次加入。profile 更新滞后时，以最新明确公告为准。仓库 `updated_at` 可由 star 等变化触发，不能用来认定新研究；扫描记录 commits / issues / comments 的实际时间。

## 更新与开源

- GitHub Actions 运行测试，并每 6 小时采样一次公开数据，保存为 workflow artifact；失败显示为失败，不补造覆盖。
- 人工/代理复核后更新研究判断和实验。任何预测都要写出后续观察条件与失效条件。
- 不自动给研究者发消息、发 issue 或 PR。本仓库原创代码使用 MIT；固定引用的 pi [适配器](third_party/pi/README.md)及[上下文模块](third_party/pi-context/README.md)保留上游 MIT 许可，真实激活 fixture 保留 [Pythia Apache-2.0 来源](fixtures/real-activation/README.md)，其他外部材料的权利归原作者。

欢迎提交能复现的负结果、反例、真实显存/吞吐数据，以及新的一手来源。

2026-10-17 跟进：完成[后代进程镜像普查与版本证据审查](research/2026-10-17-child-images-and-versioned-evidence.md)。新身份/清理工具保持额外进程未批准；没有模型加载、训练或科学结论升级，旧失败记录保留。

2026-10-17 新版本：独立声明的[双身份普查](results/dual-identity-census/report.md)分别校验自报路径和真实 OS 镜像，两个身份/清理控制及冻结审计通过。同镜像 helper 仍被拒绝，额外进程未获训练批准；旧拒绝、历史八个未知镜像和科学负结果保留。
