# 实际训练成本与恢复轨迹的边界

本轮完成一个配对训练实验：**反向保存张量的 int8 存储减少约 54%，但 CPU 训练更慢、实测进程峰值更高；两组保留集损失都比训练前差。** 这清除了“是否真正更新模型参数”的空白，尚不支持提高此压缩实现的研究优先级。代码、完整逐步轨迹与负结果公开，见[实验报告](../results/activation-training/report.md)和[原始结果](../results/activation-training/report.json)。

实际开始 2026-10-16 **02:38:26 UTC / 北京时间 10:38:26**。扫描执行 02:38:46–02:43:21 UTC，事件截止 `02:38:46.921970 UTC`。独立来源阅读时间和覆盖缺口见[证据快照](evidence/2026-10-16-training-and-replay-boundaries.json)；定向查询的较晚 cutoff 不推进主扫描覆盖。

## H1：全参数小模型训练已执行，压缩收益未成立

固定历史公开 [Pythia-14m](https://huggingface.co/EleutherAI/pythia-14m/tree/cf967c0a9a04383db6f7b1108d86b2962634b4ac) revision 和七项资产大小/SHA256，Apache-2.0 权重留在本地、不提交。使用本项目原创、模型生成的两份合成故事，分离 train/holdout，各取八段独立 65-token block，每段 64 个预测目标。输入、分词结果、配置和准备脚本哈希在训练前固定；保留集仅在初始和最终各评分一次，没有中途选择 checkpoint 或调参。[预声明协议](../fixtures/activation-training/protocol.md) / [数据与配置清单](../fixtures/activation-training/manifest.json)。

三个 seed 控制批次顺序，两个方法各用独立新进程顺序执行。每个 worker 更新全部 **14,067,712** 个可训练参数，AdamW 24 步、batch=2、sequence=64，即 **3,072 个训练目标位置**，重复访问 512 个唯一位置六轮。配对方法的初始权重、批次、token 预算和初始保留集评分相同；所有 144 步的 76 个参数张量均有有限梯度，最终整体参数哈希改变。此检查不证明每个参数都有非零更新，也不证明梯度准确。

两组前向都为 float32/eager；int8 仅替换 autograd 为反向保留的合格 CPU float32 张量，按最后一维对称量化，保存 codes/scales，反向时重建操作数。排除参数及转置 alias。它包含 attention、MLP 和 loss 保存张量，**不是残差 bank 专用方案**；没有 identity STE、量化前向、学习深度 query 或 AttnRes 架构。

| 指标 | dense | int8 保存张量 |
| --- | ---: | ---: |
| 初始保留集 NLL，512 目标位置 | 4.73105 | 4.73105 |
| 最终保留集 NLL，三个 seed 范围 | 6.06307–6.10029 | 5.47478–5.66683 |
| 反向保留的非参数 backing storage inventory | 32,590,852 bytes | 14,989,316 bytes |
| 同 token 训练循环耗时 | 7.84–8.00 s | 11.78–12.00 s |
| OS 进程生命周期峰值 | 579.95–580.82 MiB | 604.04–604.91 MiB |

int8 的最终 NLL 低于 dense，但**两者都退化于共同初始模型**，不能称为模型质量改善。压缩组的梯度范数差异明显；没有逐步同参数点的完整梯度方向/更新误差对照，不能断言退化原因。tiny synthetic holdout 不代表一般语言建模能力。

storage inventory 是实际保存对象的去重记账，不是 OS 峰值或显存。生命周期峰值包含导入、模型、梯度、AdamW、评估、哈希和有限性/范数检查；回调计时与分配器也会影响观测。每方法/seed 一个进程，缺少独立进程重复，不作性能显著性或跨机器外推。仍观察到配对循环耗时为 dense 的 **1.47–1.52 倍（增加约 47–52%）**，峰值增加 **23.22–24.86 MiB**；不能把 inventory 下降写成真实内存收益。

激活压缩训练已有 [ActNN（2021）](https://arxiv.org/abs/2104.14129) 等先行工作。本轮核验其官方摘要；该工作使用随机量化与混合精度，并报告视觉模型结果。我们的确定性 int8 hook 是独立成本诊断，不是 ActNN 复现或新提出的研究方向。

**本项目推断与下一门槛：**先检查保存 loss/归一化张量时的梯度偏差，在固定输入与参数点上比较梯度方向和更新误差，再考虑更窄的压缩范围。学习路由、等 wall-clock 训练、真实自然语言终评、GPU 峰值/吞吐以及忠实 AttnRes 验证均未完成。本轮只执行以上一个新实验，没有改动旧实验结果。稳定结果 SHA256：`3b23184bec741fa44ac03ed884b9948f005f667074a966fe548ed9cf2713f1c1`。

## 上游 H1：恢复历史贡献不等于新发布算法

36 次有界 GitHub API 读取确认 AttnRes/default FLA 窗口内无 commit，旧五个跟踪 PR 的 head/body/state 未变；Nathan 的 62 个仓库、23 个原创仓库元数据无技术增量，author 搜索结果为零。这不是全部分支、私有工作或完整个人时间线的覆盖。

FLA 出现大量恢复 PR。抽查六项并保留原作者、旧提交时间、状态和 patch 指纹：

| 新 PR | 原有工作与当前边界 |
| --- | --- |
| [#1422](https://github.com/fla-org/flash-linear-attention/pull/1422) | 恢复 #1331 的统一 residual interface，10 月 6/8 日旧提交；历史 Standard 内存声明不能归为 AttnRes 收益 |
| [#1425](https://github.com/fla-org/flash-linear-attention/pull/1425) | 恢复 #1390；10 月 16 日 01:49 的新分支 merge 只整合当前 main，四文件增量；不是 PR 已合并，也没有新 GPU 验证 |
| [#1461](https://github.com/fla-org/flash-linear-attention/pull/1461) | 恢复 lbx154 8 月贡献：精确 residual 数 specialization、保存 RMS reciprocal、长 N 四路 FP32 atomic reduction；旧 B200 声明未重跑 |
| [#1458](https://github.com/fla-org/flash-linear-attention/pull/1458)、[#1462](https://github.com/fla-org/flash-linear-attention/pull/1462) | 分别恢复 TileLang / CUDA KDA 训练后端；严格形状/精度限制、外部依赖和当前集成验证缺口仍在 |
| [#1484](https://github.com/fla-org/flash-linear-attention/pull/1484) | 恢复 0z5a 的真实输入 benchmark profiles；不是新算子或实测加速 |

这些材料提示继续看训练保存空间、形状特化与完整 autograd 集成，但不能归为 Nathan 今天的新原创贡献。只阅读选定 patch，未执行上游 GPU 代码，也未核验作者原始 benchmark 日志。

## H2/H4：新增合并使恢复权限和重放归属更具体

Peter 的 [OpenClaw #173579](https://github.com/openclaw/openclaw/pull/173579) 于 02:22:06 UTC 合并，原会话 Resume 经过普通 chat admission 和当前操作者权限。真实进程测试源码使用脚本 provider 与文件副作用，全部跳过 Windows；只读 session 测试不等于设备/角色撤权。公开 P1 指出 recent-20-message 窗口可能丢失更早 replay-safe checkpoint；合并 patch 保留该窗口。这是具体待复现问题，不是本项目已证实的故障。prepared head CI 为 **failure**，作者的 inherited-failure 归因未独立核验。

[verifiers #2864](https://github.com/PrimeIntellect-ai/verifiers/pull/2864) 于 01:40:59 UTC 合并，按 harness 归一化表面 replay 差异，保留实际采样消息和 token/renderer 分支核对。它由 `mikasenghaas` 贡献，不归为 Will Brown 的个人工作。H4 因此增加固定 harness 版本、回放视图与训练 token 归属一致性的验证门槛。

完整来源、固定 squash/parent、patch 覆盖、测试替身和 CI 边界见[恢复与回放报告](2026-10-16-resume-and-replay.md)。两项上游变更均未本地执行；H2 完整 harness 的 liveness/真实撤权/第二次重启与 H4 奖励一致性仍未清除。预测只是公开工程方向，复核日仍为 2026-10-30。

## 扫描覆盖与核验

| 有界窗口 | commits | issues | PR | discussions |
| --- | ---: | ---: | ---: | ---: |
| 24h | 63 | 25 | 87 | 0 |
| 72h | 93 | 25 | 100 | 5 |
| 7d | 114 | 25 | 100 | 5 |

扫描校验通过，失败 0，96 个新增/变化顶层记录；14 个端点截断标记保留未知。首次错误的占位目录扫描已中止，不推进覆盖；正确独立目录的完整扫描用于本表。新增个人仓库和 profile 变化为零，旧仓库 updated_at、star 和恢复 PR 编号不当研究进度。

X/博客另做 12 次公开 HTTP 读取，11 个非 X 原始响应与前轮相同；已知离开 Kimi 的帖子预览不变。支持的浏览器认证设置失败，实际 X timeline 读取为 0，不推进覆盖。Nathan 新雇主仍未核验；用户给的帖子只宣布离开 Kimi，发布时间为 10 月 15 日 00:04:05 UTC。

本地 **95 项测试全部通过、无跳过**，新增六项覆盖数据完整性、量化回调、参数 alias、正确 next-token shift 和实际 AdamW 更新。另有独立源码审查及 1,555 项原始结果核验。CI 新作业在固定提交数据上下载 hash 固定的公开资产并重跑六组训练；它不重新准备 tokenizer 数据。每个 CI 环境的成本和浮点数值需单独解释，不能预称与本地相同。
