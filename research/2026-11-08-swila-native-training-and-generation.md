# SwiLA 草稿：训练目标与生成缓存的原生接入边界

记录时间：2026-11-08 UTC。验证层级：固定提交的源码与作者测试设计审查；本项目未运行上游测试、模型、GPU 或科学实验。

[FLA PR #1702](https://github.com/fla-org/flash-linear-attention/pull/1702) 由 `jhdlee` 于 2026-11-08 08:17:20 UTC 创建，捕获时仍为 open draft，未合并。审查 head 为 `251366e93a0a7732ca5c8706f8a1aa718fdad7da`，base 为 `98193113ecb7835143252a786e06933e371b67cc`。这是既有 [SwiLA 论文](https://arxiv.org/abs/2609.39034) 的 FLA 集成提案，不能称为今天新发表的方法或已发布功能，也没有依据将作者归为 Nathan Chen。

SwiLA 把 token 路由至固定数量的线性循环记忆专家。草稿同时提供 plain、gated、temporal、temporal-gated 四种变体，以及 Triton 算子、独立层、Transformers 模型和 FLA Cache 接口。固定模型维度下，循环推理状态不随序列长度增长；这不等于完整训练的峰值内存有同样保证。本次保存了完整 76 文件变更清单、PR 正文及七份固定 head 的完整文件，核对 Contents 字节、Git blob 与变更清单；未闭合全部 76 文件、依赖或内核调用链。

## 已核对的实际调用链

[模型实现](https://github.com/fla-org/flash-linear-attention/blob/251366e93a0a7732ca5c8706f8a1aa718fdad7da/fla/models/swila/modeling_swila.py) 中，block 接收层的四项返回，模型累加各层辅助目标，CausalLM 用 `CE + (aux - aux.detach())` 构造 loss。因此数值报告仍是 CE，梯度包含 CE 与加权 MI。只看训练日志不能确认 MI 是否接入或是否被重复加入。MI 默认权重为零，需要训练模式与正权重；默认 tensor-only 独立层返回也不会把 MI 自动附到外部任务目标，调用方须取四项返回并只加一次已加权辅助项。

`accepts_loss_kwargs=False` 把默认 Trainer 的梯度累积语义固定为完整单次 CE+MI 目标的微批均值。等序列数、等有效标签数的微批可与对应整批目标对齐；不等微批保留 mean-of-microbatch-means，并非按全部有效 token 加权的整批等价。显式 `num_items_in_batch` 仅归一化 CE；自定义 loss、label smoothing 和外部循环必须另定 MI 的缩放。[原生 Trainer 测试](https://github.com/fla-org/flash-linear-attention/blob/251366e93a0a7732ca5c8706f8a1aa718fdad7da/tests/models/test_swila_trainer.py) 调用 `Trainer.training_step`，比较参数梯度，涵盖不等微批、余批、checkpoint 重算，并用改变接受 loss kwargs 的开关制造 MI 倍增对照。这是有针对性的测试设计证据，本项目没有执行，也不把单次梯度比较当成完整优化器训练。

[原生层](https://github.com/fla-org/flash-linear-attention/blob/251366e93a0a7732ca5c8706f8a1aa718fdad7da/fla/layers/swila.py) 的缓存所有权同样影响服务行为：独立层需要显式 FLA Cache 与非负 layer index；传入 cache 后即使 `use_cache=False` 也会推进它，该开关本身不会为独立层创建缓存。packed 边界隔离循环状态，但普通标签位移不会自动屏蔽跨序列目标，后续序列起点标签仍须设为 `-100` 或构造正确 `shift_labels`。packed MI 先在每条序列内平均 token，再等权平均序列，和 CE 的 token 分母不同。packed forward/cache 也不代表 `.generate()` 能把它们当独立请求解码。

[集成 README](https://github.com/fla-org/flash-linear-attention/blob/251366e93a0a7732ca5c8706f8a1aa718fdad7da/fla/models/swila/README.md) 明确原生层/模型仅支持 `fused_recurrent`、1–8 experts，没有 CPU recurrence fallback；单独的可微 PyTorch reference 不能替代原生 CUDA 路径验证。需要循环状态回退的生成模式尚不支持。checkpoint 中已存储的 FP32 `A_log`/`dt_bias` 可保持精度，但无法恢复保存前已被舍入的值。

## 作者报告与性能证据范围

作者正文报告最近一次 217 项通过（166 CPU、51 H100）和一项仅 Blackwell 的跳过；此前多批数字有重叠，不能相加。作者另保留 wheel-discovery harness 失败，并报告独立 CPU continuation 完成当时待运行的五个 wheel workers、48 次精确 checkpoint round trips；这不是完整上游套件重跑，公开 selector wrapper 也仅做过语法/清单检查，没有另行 GPU 执行。本项目没有复现这些数字。

正文另列的八例 H100 算子比较来自较早 `lint_usage_v1` / `fbe2c383`，公共参考为 `lindermanlab/switching-linear-attention@4b43bb5c9d3e76659e5f07740c15b046cddb581b`，并非当前 head 的现有 FLA SwiLA 基线。八例峰值 allocation 相等，temporal-gated dense combined 报告快 3.17%，temporal packed 慢 2.30%；原因未定。算子计时排除编译，不能推广为当前提交的完整训练成本、质量、端到端吞吐、多卡或生产收益；H100 也没有执行 Blackwell 专用回归。

## 对后续工程实验的具体约束

实际调用方是原生 `SwiLAForCausalLM → SwiLABlock → SwitchingLinearAttention` 的训练，以及使用 FLA Cache 的生成服务。放大负载时应分开处理专家状态/临时张量成本、MI/CE 分母、checkpoint 重算、packed 标签边界，以及并发请求的缓存身份与回退能力。可回退接口应保留已验证的原模型/attention backend；尚不支持的回退式生成不能默默启用。

若以后进入原生研究，必须先另行预注册固定版本、tokenizer/数据/seed、模型与专家维度、序列/微批形状、有效标签与序列计数、优化器/累积/checkpoint、缓存策略、设备与时长/内存/通信上限。正确性验收须分别覆盖 CE 和 MI 梯度、等/不等微批、余批、packed/padded 标签、重算以及缓存推进/隔离；比较质量与成本时须固定 matched dense/bank 完整训练预算和封闭终评，报告成功率/质量、有效吞吐、端到端与尾延迟、峰值资源/通信及观测成本。此处只是未来准入要求，没有冻结新协议或启动实验。

SwiLA 的序列循环记忆与本项目 H1 的残差/保存激活 bank 对应不同对象。这条源码信号提供具体集成接口，不证明 H1 的质量或成本收益；已有负结果、无效 RSS 端点、H2 已关闭的有限切片以及 H3/H4 未满足门槛全部保留。本轮不新增孤立 observer 工具，也不改变现行工程路线。

可审查的内容哈希与证据范围见 [来源收据](receipts/20261108T093339Z-swila-native-integration.json)。
