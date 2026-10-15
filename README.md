# Frontier Signal Lab

**追踪公开研究信号，把“他们可能往哪里走”变成我们可以证伪的小实验。**

Public evidence → falsifiable hypotheses → reproducible experiments.

追踪前沿实验室研究者与开源作者的个人公告、原创仓库、实际贡献、issue/PR/discussion。每个判断附原始链接、观察时间、替代解释和下一次检查条件。入职消息用于发现人物；研究优先级由技术证据决定。

## 第一轮：2026-10-15

- **陈广宇 / Nathan Chen** 的[原帖](https://x.com/nathancgy4/status/2110522061953327565)发布于北京时间 **08:04:05**，宣布离开 Kimi；该帖没有宣布加入 Anthropic。新去向暂记 **未核验**。
- 他明确回顾 **KDA kernels、Attention Residuals、optimizers**。第一条研究假设：深度信息路由的下一步机会，在精度、优化动态与硬件预算的共同约束中。
- 首个可运行实验：**AttnRes budget probe**。在合成残差 bank 上比较压缩与选择策略，测数值损失、逻辑存储和打分开销。
- 第二个可运行实验：**Recovery contract probe**。用明确的事件轨迹注入崩溃、重复回执和上下文压缩并发，比较三种恢复协议。
- 其他优先切口：自动研究的封闭终评、RL 环境的可验证奖励。详见[研究判断与证伪条件](research/2026-10-15-frontier.md)。

本日跟进：Peter 的 OpenClaw 未合并 PR 新增异常 binding 诊断与保留测试；本项目据此完成独立的真实 SQLite 迁移/崩溃恢复实验。静默跳过与报警两组都保留原记录，但“诊断干净”与“工作完成”不能等同。时间线、来源变化及边界见 [H2 跟进](research/2026-10-15-h2-sqlite.md)。

## 快速运行

需要 Python 3.11+；在线雷达另需 [GitHub CLI](https://cli.github.com/) 已登录（或 CI 中的 `GH_TOKEN`）。实验离线运行，不调用模型 API。

```bash
python -m pip install -r requirements.txt
python experiments/attnres_budget_probe.py --output results/attnres-budget
python experiments/recovery_contract_probe.py --output results/recovery-contract
python experiments/sqlite_migration_probe.py --output results/sqlite-migration
python -m unittest discover -s tests -v

# 明确最近 7 天的有界采样；失败和截断会记录在报告中
python -m frontier_radar scan --config watchlist.json --output-dir reports/live --since-hours 168
```

雷达生成 `snapshot.json`、`report.md` 和校验文件。它只读取公开 GitHub 数据。X 原帖、个人站、论文由研究者人工核验后进入[证据账本](research/sources.json)；扫描器不会声称已经自动覆盖整个 X。

首轮在线扫描于北京时间 **18:24–18:29** 完成：7 人、10 个仓库，采样到 117 条 commits、36 条 issues、98 条 PR 和 5 条 discussions；请求无失败。活跃仓库有分页截断，报告明确标注，因此这些数字不能当成最近七天的全部活动。[扫描报告](reports/2026-10-15-initial/report.md) / [快照与校验](reports/2026-10-15-initial/snapshot.json)。

## 实验能回答什么

给定残差向量与 pseudo-query，压缩或丢弃历史层信息会怎样改变 attention-over-depth 的输出？相同预算下，平均误差与长尾误差是否一致？先计算全部 logits 再 top-k 的方法，需要保留多少原始信息？

实验报告中的 bank bytes 是按数组形状计算的**逻辑持久存储**。它不等于 GPU 峰值显存；还需计入重建临时空间、activation、反向图、kernel 和模型其他参数。离线 block-sum 代理也不是完整 Block AttnRes 网络。

当前没有训练语言模型，没有测困惑度或 GPU 吞吐，没有证明一种新架构优于现有方法。下一个门槛是小模型等 token / 等 wall-clock 训练，以及多 seed 和梯度/路由指标。

## 首轮结果与跟踪对象

初始跟踪 **7 人 / 10 个仓库**：Nathan Chen、Guangxuan Xiao、Will Brown、Robert Tjarko Lange、Peter Steinberger、Mario Zechner、Nicholas Carlini。覆盖 Anthropic、OpenAI、Thinking Machines Lab、SakanaAI、Prime Intellect 的公开从业者与独立开源作者；每个人的角色证据和日期状态见 [watchlist.json](watchlist.json)，不统一贴“新入职”或“天才”标签。

| 实验 | 已运行的范围 | 可复查结果 |
| --- | --- | --- |
| AttnRes budget | 2 深度 × 3 分布 × 2 query × 3 seeds × 7 策略，252 条测量 | [完整表格](results/attnres-budget.md) / [原始 JSON](results/attnres-budget.json) |
| Recovery contract | 3 协议 × 11 事件场景，33 条可回放轨迹 | [结果](results/recovery-contract/report.md) / [轨迹和假设](results/recovery-contract/probe.json) |
| SQLite migration | 2 诊断策略 × 5 故障配置，10 条真实数据库轨迹 | [结果](results/sqlite-migration/report.md) / [快照与 hash](results/sqlite-migration/probe.json) |

一键重跑测试、三个实验并记录本地环境与文件指纹：`python scripts/reproduce.py`。[本轮运行清单](results/reproduction.json)记录了 Python、NumPy、SQLite、配置和 SHA256。

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
- 不自动给研究者发消息、发 issue 或 PR。仅此仓库的新代码使用 MIT；外部材料的权利归原作者。

欢迎提交能复现的负结果、反例、真实显存/吞吐数据，以及新的一手来源。
