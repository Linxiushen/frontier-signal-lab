# 保留注意力模块保存值通过梯度门槛，下一步验证实际更新

本轮一个预声明实验改变了 H1 的执行顺序：在精确 CE 与13个实际 LayerNorm 模块内保存值固定时，再保留6个实际注意力模块 forward 内的保存值，三个固定预训练批次的完整梯度误差均降至原来的约0.53%–0.85%，cosine 约0.999。**三个预声明“误差减半且 cosine 不降”判据全部通过。** 这是本实现广泛保存范围的敏感性证据，不能定位单一 operand 或推断训练收益。

## 实测与可证伪边界

| Seed | 仅保留 norm 相对 L2 | 再保留 attention 相对 L2 | 后者/前者 | Cosine：原 → 保留 attention | 判据 |
| --- | ---: | ---: | ---: | --- | --- |
| 11 | 7.613840 | 0.040762 | 0.005354 | 0.159637 → 0.999169 | 通过 |
| 29 | 7.699570 | 0.040662 | 0.005281 | 0.155752 → 0.999173 | 通过 |
| 47 | 4.053040 | 0.034482 | 0.008508 | 0.253355 → 0.999406 | 通过 |

复用 Pythia-14m revision`cf967c0a9a04383db6f7b1108d86b2962634b4ac`、原训练 token 和首批次[3,1]/[5,3]/[7,0]；三个新进程依次比较 dense、仅保留 norm 的 int8、同时保留 norm+attention 的 int8。每方法128目标位置，三批次合计320独有位置且有重叠，不能当独立统计重复。无 optimizer、参数更新、holdout 前向或调参。

设计登记`2026-10-16T08:41:03.534775+00:00`；最终源码/协议冻结`2026-10-16T08:45:40.125525+00:00`，早于测试与实际比较。协议 SHA256`46d29186eecdb17369004bac921cc65a8077086779dc0b79961b34f57e9096e3`。比较实际区间`2026-10-16T08:50:00.317167+00:00`–`2026-10-16T08:50:43.942540+00:00`。全部76参数张量、14,067,712元素梯度有限，参数 hash 不变，各方法 logits/loss 完全相同，解析 CE 控制通过。新增 wrapper 的 dense 与 norm-only 基线逐参数指标/hash 与前轮完全相同。

按实际`GPTNeoXAttention`类选6个模块，临时实例 wrapper 在`finally`恢复，三组使用相同仪表。作用域包含 QKV、RoPE、因果注意力和输出投影；不能把效果归给单个操作。独立 NumPy float64 forward/VJP 覆盖真实按 head 交错的 QKV 布局、输入、QKV/输出投影权重和 bias，但使用 identity RoPE，不是完整模型或一般 rotary backward 证明。13个 norm 和6个 attention 均调用一次，保存/取回非空；baseline attention 合资格保存值全部压缩，treatment 全部精确。

新增6项与全113项测试通过，无跳过；独立原始结果审查7613项通过，没有重新生成梯度。分开库存排除了精确 CE，不能当总 backward 内存或峰值显存。前两轮 CE/norm 门槛失败、此前训练耗时/进程峰值增加及两个 holdout 退化均保留。下一步先预声明并验证实际 AdamW 更新保真度，再决定是否训练；本轮不加跑第二实验。详见[实验记录](../results/activation-attention-gradient/report.md)/[逐参数与逐模块 JSON](../results/activation-attention-gradient/report.json)。稳定结果 SHA256`b5051eae772617e4fc30a18727936cb74fc30c3629c670f83526691edf033e66`。

## 公开技术信号与我们的推断

[FLA #1452](https://github.com/fla-org/flash-linear-attention/pull/1452)仍是恢复草稿；`yzhangcs`恢复、原贡献和当前更新来自`xy200303`。本轮新 head`df6759bd…`的两次提交为 Ascend verifier/implementation 补上`lower_bound`，并新增直接 backward 与 varlen prefix-causality 回归。贡献者解释 verifier 的 TypeError 曾被吞掉并静默回退 Triton；NPU 内核故意不用该参数。旧→新3个完整 patch 和两个新回复已读，未执行设备或审查 CI 日志。正文原 A100 数字是历史验证，没有本轮重跑；不能更新其时间或当成当前 NPU 证明。

新草稿[FLA #1487](https://github.com/fla-org/flash-linear-attention/pull/1487)，`zhiyuan1i`于06:57:43Z提出：size1维的非标准 stride 可能让`.contiguous()`不产生真正 dense 布局；fallback 改成显式 contiguous-format clone，保留可接受 view 的 zero-copy 路径。3个 patch 已读，作者只报告 host/lint/测试收集，accelerator 与 compute-sanitizer 未跑。

新草稿[FLA #1488](https://github.com/fla-org/flash-linear-attention/pull/1488)，同作者于06:57:49Z提出：尾块 level-scales 的前后向对角读取需同时满足行、列 token 边界，梯度 store 增加`i<L`；新增 T16 的输出与5项梯度对照。2个 patch 已读。host 地址枚举报告不等于 GPU/sanitizer 实测，小L varlen 仍待验收。1487/1488核验了 PR 作者和固定 head，没有另外读取 head commit 作者。

三项均公开 MIT、未合并、没有性能结论，均非 Nathan 新贡献。我们据此推断低内存实现的验收必须包含实际 dispatch、非标准布局、partial tails 与完整 backward；它们不直接支持本轮 attention 保存值判据，也不是任何人的私下研究公告。首次读取的 #1423 merge 早于前次截止，未记为新合并。

H2 的新证据把下一门槛具体化为持久限制/临时授权分离、失败读取到真实 transport 的阻断，以及模型级压缩策略在 threshold/overflow/summary 之间的一致快照。OpenClaw #173383 的成功 CI 仅为元数据，#173970 与 pi 当前主 CI 失败均保留；历史附件、合并和源码不能替代本轮运行。详见[来源与恢复门槛](2026-10-16-continuation-and-fail-closed.md)。H3/H4 本轮未执行，旧 checkpoint-tail、kill-settlement、admission-await 残余问题继续保留。

## 覆盖与盲区

主扫描`2026-10-16T08:35:32.734459Z`–`2026-10-16T08:40:08.760050Z`，使用真实旧 snapshot 与7日重叠；58个新增/变化顶层事件，未发现新个人原创仓库/profile 变化。

| 窗口 | Commits | Issues | PRs | Discussions |
| --- | ---: | ---: | ---: | ---: |
| 24h | 68 | 28 | 80 | 0 |
| 72h | 98 | 28 | 91 | 5 |
| 7d | 118 | 28 | 91 | 5 |

主扫描无失败，14处分页截断保留。另有 H1 42次、H2/H4 78次成功定向 GET，各有独立窗口/观察时间，均不能代表完整 GitHub。网站/RSS和已知离职帖预览12次 HTTP 成功，11个非X原始响应与前轮完全相同；已知预览无新去向。支持浏览器命名因`unsupported Codex auth method: apikey`失败，发生于 tab绑定前；当前 X 页面读取0，timeline未知。Nathan 新雇主仍未核验；离开 Kimi 不能改成加入 Anthropic。

[选定证据](evidence/2026-10-16-attention-saves-and-continuation.json)保留原始指纹、归属、协议、审查和结果 hash；滚动原始响应不提交。成功扫描截止仅推进到`2026-10-16T08:35:32.730428+00:00`。本轮变化提升的是本项目下一实验的针对性，不支持领先、首创、训练质量或现实成本优势。
