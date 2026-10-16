# 同一梯度策略，优化器状态会改变更新保真度

本轮完成一个预登记实验：Pythia-14m 先做四步真实稠密 AdamW 更新，再固定权重和优化器状态。保留实际注意力 forward 保存值的策略，在匹配四步状态的下一步更新中通过三个种子的全部门槛；相同暖启动权重、相同梯度、零状态的对照仍全部失败。此前预训练权重上的首步失败和训练成本/保留集负结果继续成立。

| Seed | 匹配状态：norm-only 误差 | 匹配状态：保留 attention 误差 | 匹配状态：cosine | 零状态：保留 attention 误差 |
| --- | --- | --- | --- | --- |
| 11 | 0.215667124 | 0.008563226 | 0.999963338 | 0.109041819 |
| 29 | 0.239227788 | 0.007663672 | 0.999970635 | 0.105082811 |
| 47 | 0.248779972 | 0.007763336 | 0.999969868 | 0.109491334 |

误差为所有参数实际 float32 更新向量相对各自 context 稠密更新的 relative L2。匹配状态下，treatment/baseline 误差比为0.039706、0.032035、0.031206。主门槛没有变化：误差≤0.10、cosine≥0.99，并且误差不超过 norm-only 一半、cosine 不差于它，每个种子都要满足。主结果全部通过；次要零状态组仅绝对误差条件失败，未用于挽救主结果。

## 固定了什么

[协议](../fixtures/activation-state-update/protocol.json)记录于 **2026-10-16T10:46:17.734195Z**，早于新实现、测试和模型运行；[实现清单](../fixtures/activation-state-update/implementation.json)在工程测试、独立代码复核后于 **10:54:34.827352Z** 冻结。科学运行从10:54:36.438477Z至11:01:47.596323Z，只有这一次本地声明运行，没有改门槛或重选种子。时间戳是本地记录，不是外部注册证明。

使用相同的不可变 Pythia-14m、CPU float32、eager attention、单线程确定性执行和公开固定合成 token 数据。每个种子的第1–4批生成真实非零 m/v/step4，第5批在固定暖启动参数点执行 dense、norm-only int8、norm+attention-preserved int8 三次 backward。每个梯度分别进入独立的匹配状态 step4→5 和零状态 step0→1 原生 AdamW 克隆。不是使用 NumPy 预测值替代实际 optimizer.step。

学习率1e-4、betas(0.9,0.999)、eps1e-8、weight decay0.01，全部76参数共用一个组；无裁剪或调度器。精确 CE 在 hooks 外，13个实际 LayerNorm 和6个实际 GPTNeoXAttention forward 保存范围均检查。三个策略的 forward logits/loss 相同，探测期间原始暖启动权重、原生优化器状态及冻结快照均未改变。每个克隆的 theta/gradient/m/v/step 初始化均相同且存储隔离，包含每个原生 scalar step tensor。

总计12次 warmup backward、9次 probe backward、12次 warmup 原生更新、18次克隆原生更新。每次更新对全部76参数的 theta/m/v/t 检查独立 float64 NumPy 方程：动量使用更新前各项绝对值之和的舍入界，参数使用 m/v 四角传播区间。数值校验与科学门槛分开；它们全部通过。三个 worker 分别约144.846、142.284、141.698秒，均在360秒上限内；包括启动的父进程各次均低于420秒。这些时长包含诊断开销，不是效率对比。

新增17个工程测试，全仓165个本地测试通过。同一工作区的独立审查脚本重新检查55,416项 hash/收据链、统计量、配置、时间顺序和门槛；没有重新运行模型，也不是外部独立复现。CI 配置增加相同冻结协议的异环境重放，执行状态以真实 CI 记录为准。

## 能推断到哪一步

在这三个短稠密历史点，优化器的 m/v/step context 对实际更新误差有实质影响。两个 context 同时改变动量与 bias-correction 步数，不能把差别归因到某一个动量、某一坐标或某一保存算子。新的零状态组使用暖启动后的权重，也不是此前预训练权重首步结果的重复。

四步稠密 warmup 不是压缩训练轨迹。三个固定合成批次及其历史有重叠，不是独立统计重复，也不是封闭终评。宽 attention 保存范围包含投影、RoPE、attention 和输出投影，没有单算子因果归因。保留的 hash/充分统计不能让读者离线重算未发布的原始权重、梯度、动量数组。

下一门槛须另行预登记：在新、固定且未用于选择的批次与多个审计点上匹配真实 dense/compressed 训练历史，分别检查状态漂移和实际更新，再考虑密封质量与匹配时间成本。此前训练更慢、进程峰值更高、两组合成保留集回归的结果不能由本次通过推翻。GPU峰值、硬件吞吐、AttnRes/学习深度路由和一般收敛性仍未验证。

SaveScope v0.1 的公共 API 仍是 fresh-state CPU float32 first-step；本实验的状态克隆辅助模块是独立研究代码，不是扩大 API 兼容性承诺。

## 本轮公开技术信号

[FLA #1490](https://github.com/fla-org/flash-linear-attention/pull/1490)是 Aphelios183 的新公开测试草稿，依赖尚未合并的#1487：7函数×4 singleton-stride 布局×3 dtype，检查输出及全部输入梯度。08:30:12Z的 commit 早于上次截止，08:56:17Z 的 PR 创建是新事件。作者自报 L40 7fail/1pass、组合84pass；没有独立日志/组合树/设备验证。NaN padding 和 empty_like 包装是诊断夹具，不是原分配内存安全证明。#1487 仅变为 ready，当前硬件任务排队、旧任务取消，不升级执行。见[证据](evidence/2026-10-16-singleton-stride-regression.json)。这些是布局/反向验收线索，不直接支持本次 AdamW 结果或 Nathan 的贡献。

H2 的恢复当前权限与并发4、H4 的 harness `.git` 干扰，来自旧提案的新合并，仍为源码与作者自报层面的证据。实际作者、源码阅读范围、红色 CI 与未执行门槛见[另一份记录](2026-10-16-recovery-concurrency-and-harness-root.md)。

本轮另用支持的浏览器读到 Nathan 主页4条可见原帖时间及已知离职帖完整原文；它仍只确认离开 Kimi。其他六人的固定公开网页/Feed共11个非X响应与前次字节相同。这个有界观察不能证明没有未显示的新消息，也不能核实新的雇主；没有社交发布、联系研究者或上游 issue/PR。

## 复现与 hash

[运行说明](../fixtures/activation-state-update/README.md) · [结果表](../results/activation-state-update/report.md) · [原始报告](../results/activation-state-update/report.json) · [数值控制](../experiments/adamw_state_reference.py)

| 项目 | SHA256 |
| --- | --- |
| 协议文件 | `9b3a45c205defd8d1211c3f2ad2c60a447e057438a219e4f38e2cc1371706cca` |
| 实现清单文件 | `cb89d0c1cbb0151e48d6fd6ca5e7859e848c08d14b1ad01a268d1551eec32a08` |
| stable result | `27f898785bb8e0c5f7460dc9670e95a03aa73cb06fcc47a39656c6bf13f337bc` |
| observation | `11a8e19cc6cff92ef2dbeec3ed9dc3dd90790ca7200ae63d4f9e34b931e2288b` |
| 报告文件 | `0cc65219b0a6beea5f68b3ce8b0001f72f93fc3dee92855ae4b0c727a9b0c61d` |
