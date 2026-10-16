# Loss 保存边界未解释主要梯度误差

本轮完成一个预声明的固定参数诊断：保留 cross-entropy（CE）的精确保存值，确实恢复了 logits 层解析梯度；但三个批次的完整模型梯度误差都没有减半。**“loss 路径保存值是主要解释”的操作性判据未通过。** 没有据结果调整配置或重跑挑选。

同时，新合并的恢复权限、取消和单调时钟测试把 H2 验收条件写得更具体，仍是源码证据。研究方向由公开技术贡献决定，不能将仓库贡献者的工作归给知名作者的私人计划。

## 实验：同一参数点，改变 CE 保存边界

此前 [实际训练](2026-10-16-training-and-replay-boundaries.md) 中，int8 保存库存下降但耗时/进程峰值上升，两组最终合成保留集 NLL 都退化。本轮不训练：固定公开 Pythia-14m revision `cf967c0a9a04383db6f7b1108d86b2962634b4ac`，三个新进程各选一个已有训练批次，在同一权重下依次运行 dense、model+CE 全范围 int8、仅 model 范围 int8。每个方法 128 个目标 token，三个批次有重叠，不能当独立统计样本。

协议固定于 UTC `04:43:13.189651`，SHA-256 `133ac86c71ef28870f7380bae55812f30a007165ae8bd2590c3485d90e432744`；实际比较发生于 `04:47:09.666978–04:47:41.553813`。没有 optimizer、参数更新、holdout 前向、超参/检查点选择。既有 loader 仅验证 train/holdout 数据结构和 hash。

预声明判据为：仅压缩 model 后，完整参数梯度相对 dense 的 L2 误差至多为全范围压缩的一半，且 cosine 不降低，要求三个批次全部成立。

| Seed | 全范围 int8 相对 L2 | 仅 model int8 相对 L2 | 后者/前者 | Cosine：全范围 → 仅 model | 判据 |
| --- | ---: | ---: | ---: | ---: | --- |
| 11 | 7.549238 | 7.602382 | 1.007040 | 0.160379 → 0.159897 | 失败 |
| 29 | 7.648300 | 7.687965 | 1.005186 | 0.156610 → 0.156118 | 失败 |
| 47 | 4.093265 | 4.038288 | 0.986569 | 0.249704 → 0.254370 | 失败 |

这是完整梯度向量误差，不是 loss 百分比。全部 76 个参数张量、14,067,712 个元素都有有限梯度；有限不等于准确。各方法 logits hash 与 forward loss 完全一致，每次 backward 前后参数 hash 不变。

CE 局部控制有效：全范围 int8 的 logits 梯度相对解析 `(softmax−onehot)/128` 误差约 2.39–2.83%；dense 与仅 model 两组约 `2.14e-8–2.46e-8`。这支持“移出 hook 确实保留精确 CE 保存值”，却不支持它消除主要完整参数误差。normalization 及其他 model 保存值在两种 int8 方法中仍受压缩；本轮不能判定其中哪个是原因。

完整逐参数指标、三份原始 worker、hash 和命令见 [实验报告](../results/activation-gradient/report.md) / [JSON](../results/activation-gradient/report.json)。稳定结果 hash 为 `9d6437eb6fce77f19422733803abd077cf5bb04b8b0188ba74b5900067946606`。独立审查通过 9,538 项记录/hash/聚合算术核查，没有重新生成梯度数组。初次完整测试有一个 float32 零行和容差失败；实际模型运行前仅将测试容差修为 float32 epsilon/2，正式 `1e-5` 解析控制及协议未变，随后 6 项专项、101 项完整测试通过。失败日志指纹保留在证据中。

这次不比较实用内存收益：dense 梯度引用和 logits 梯度仍驻留；仅 model 的 hook 库存也不包括 hook 外 CE 的精确保存值。没有新的训练/更新质量、GPU 或 AttnRes 结论。下一步先预声明模型保存操作数的隔离，包括 normalization 敏感性，再做同梯度下真实 optimizer update 对照；两项本轮均未执行。既有训练负结果保持原样。

## 上游 H1：适配进展与验证缺口

[FLA #1462](https://github.com/fla-org/flash-linear-attention/pull/1462) 当前 head 为 `6f15159f91df5af45863f70ca2ae2580d79000dd`。四个 patch 完整读取：FlashKDA training backend 适配新的 `BaseBackend/register` 与 norm import，并拒绝 `use_graph=True`。作者 [明确表示未重跑 CUDA](https://github.com/fla-org/flash-linear-attention/pull/1462#issuecomment-6207726104)。这是 `xy200303` 的历史贡献在当前接口上的移植：commit authored_at 为 8 月 8 日、committed_at 为本轮 03:45:30；旧 benchmark 不成为新验证。

[FLA #1452](https://github.com/fla-org/flash-linear-attention/pull/1452) 当前 `42722baf32705276dd4e02f097eef21ffd229780` 恢复历史 GDN-2 causal anchor 修复。四个 patch 包括 forward/backward lower-bound 传递；现有新增测试只有两个 dense forward prefix 情形。[当前 review](https://github.com/fla-org/flash-linear-attention/pull/1452#discussion_r4290912041) 指出 Ascend 签名缺少 `lower_bound` 导致 fallback，另要求直接 backward 和 varlen 回归。没有执行上游 GPU 代码或核验历史 A100 运行。这两项不能记为 Nathan 新成果。

## H2 与本轮覆盖

OpenClaw 三项新 merge：[#170336](https://github.com/openclaw/openclaw/pull/170336) 只有 test/support 变化，增加设备/角色撤权与真实 disabled Cron job 持久化 owner 的源码断言；[#173580](https://github.com/openclaw/openclaw/pull/173580) 区分写入前取消和写入后/超时清理；[#173241](https://github.com/openclaw/openclaw/pull/173241) 用单调时钟控制 poll 相对期限。mock turn/provider、冷态重建、合成 transport 与仅取得 CI 元数据的边界都保留。旧 checkpoint-tail 与 kill-settlement 问题没有因此自动解决。详见 [独立来源报告](2026-10-16-recovery-authority.md)。H3/H4 仍未执行。

主扫描 UTC `04:35:20.753205–04:40:08.149219`，基于真实前次 snapshot，七日重叠采样，无请求失败；57 个新增/变化顶层事件，无新个人原创仓库/profile 变化。

| 窗口 | Commits | Issues | PRs | Discussions |
| --- | ---: | ---: | ---: | ---: |
| 24h | 62 | 28 | 79 | 0 |
| 72h | 93 | 28 | 90 | 5 |
| 7d | 113 | 28 | 90 | 5 |

14 个端点截断标记保留，不宣称覆盖完整 GitHub。另有 H1 的 32 次成功 GET、H2/H4 的 54 次成功 GET 加 2 次已纠正的 issue-as-pull 404。网站/RSS 与已知 X 原帖 syndication 共 12 次 HTTP 读取成功，11 份非 X 原始响应与前次相同，已知离职帖预览未变。当前 X timeline 浏览器设置因 `unsupported Codex auth method: apikey` 失败，页面读取为 0，覆盖保持未知。Nathan 新雇主仍未核验；离开 Kimi 不等于宣布加入 Anthropic。

扫描、来源审查与实验各用自己的实际时间/边界。[选定证据清单](evidence/2026-10-16-gradient-and-authority.json) 保存请求/原始文件 hash、预登记、失败记录指纹和独立结果审查；滚动原始响应不提交。主扫描成功截止仅推进到 `04:35:20.748207+00:00`，稍后的定向读取不替代它。
