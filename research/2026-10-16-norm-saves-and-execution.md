# LayerNorm 保存值隔离仍未解释主要梯度误差

本轮完成一个预声明实验：三个固定参数批次中，保留实际 `torch.nn.LayerNorm.forward` 内全部保存值，没有让完整参数梯度误差减半，cosine 也略降。**三个预声明判据全部失败。** 这缩小了本实现下一步的排查范围，没有定位剩余原因。

## 实测：精确 CE 与精确 LayerNorm 保存值

复用固定 Pythia-14m revision `cf967c0a9a04383db6f7b1108d86b2962634b4ac`、既有合成训练 token 与前三个 seed 的首批次 `[3,1] / [5,3] / [7,0]`。三个全新进程依次比较 dense、仅 model int8、仅 model int8 但保留 LayerNorm。每个方法 128 个目标位置，批次重叠，总共 320 个独有目标位置；不能当独立统计重复。

设计登记于 UTC `06:38:53.153007`，最终协议冻结于 `06:44:27.234292`，均早于测试与实际比较；协议 SHA-256 `048f232f2d5367bbe548ccc334c81903db14d3d950bfb4ca1ec8a4703d8e9869`。实际比较 `06:46:11.433138–06:46:42.822666`。没有 optimizer、参数更新、holdout 前向或调参；共享 loader 只验证两份数据结构/hash。

预声明门槛：保留 norm 后完整参数梯度相对 dense 的 L2 误差 ≤ 原 model-int8 的一半，且 cosine 不降，三个批次全部成立。

| Seed | Model int8 相对 L2 | 保留 norm 相对 L2 | 后者/前者 | Cosine：原 → 保留 norm | 判据 |
| --- | ---: | ---: | ---: | ---: | --- |
| 11 | 7.602382 | 7.613840 | 1.001507 | 0.159897 → 0.159637 | 失败 |
| 29 | 7.687965 | 7.699570 | 1.001510 | 0.156118 → 0.155752 | 失败 |
| 47 | 4.038288 | 4.053040 | 1.003653 | 0.254370 → 0.253355 | 失败 |

全部 76 个参数张量、14,067,712 个元素都有有限梯度，各方法 logits hash/loss 相同，每次 backward 前后参数 hash 不变。13 个实际 LayerNorm 均调用一次并记录保存/取回；仅 treatment 的 norm 库存保留精确值。独立审查还逐参数确认本次 dense/model-only 梯度 hash 与前次相同，支持“额外作用域仪表没有改变 baseline”。CE 三种方法都在全部 hook 外，解析梯度相对误差约 `2.14e-8–2.46e-8`。

这只否定当前命名模块保存范围的“误差减半”判据，不证明 normalization 普遍不敏感，也不识别单一 operand。norm 和外层库存分开统计，未包含精确 CE 的保存值；不能当总 backward 内存或峰值显存。先前训练的时间/进程峰值增加和两份 holdout 退化继续保留。下一门槛是预声明隔离其他 model 保存范围及独立 backward 参考，之后验证 optimizer 更新保真度；本轮不加跑第二实验。

6 项新增测试和全部 107 项测试通过；独立原始记录审查通过 10,900 项检查，没有重新生成梯度数组。审查脚本初次把同形状的受保护参数别名误当 CE 激活，产生9项假失败；只修正审查范围并保留初次记录指纹，实验源码、协议和结果均未修改或重跑。命令、逐参数指标与三份 worker 见 [实验报告](../results/activation-norm-gradient/report.md) / [JSON](../results/activation-norm-gradient/report.json)。稳定结果 hash `5bfdec9147453be22eb53d6e967d243d3beba7bea1334c598a287eccfc9461b0`。

## 新公开贡献如何改变验证要求

[FLA #1398](https://github.com/fla-org/flash-linear-attention/pull/1398)，作者 `2313247981`、由 `zhiyuan1i` 合并于 `05:40:23Z`：Ascend/HCCL 的 KDA 上下文并行调整 UB tile、V/K 布局与 partial-tail masks，并修正参考实现重复 gating。作者报告 Ascend 910B3/CANN9.2.0-beta.2 上 17 passed / 1 reference OOM；CP8 失败发生在参考端、未进入 CP kernel。三份不可变 merge patch 已读，未执行 NPU 或审查运行日志。

[FLA #1399](https://github.com/fla-org/flash-linear-attention/pull/1399)，作者 `arcusbuilds`、合并于 `05:34:53Z`：仅 Blackwell/Triton<3.8 排除 dv_local 的 8-warp 配置，新版本恢复 forward 候选；测试每个配置用相同输入重复20次。作者 Ada 152 passed / 30 skipped，Blackwell 专项未跑，版本切点和性能没有独立验证。三份 patch 已读。

[FLA #1400](https://github.com/fla-org/flash-linear-attention/pull/1400)，作者 `Windyskr`、合并于 `05:44:06Z`：恢复 opt-in inference CP 后端在 `chunk_offsets=None` 时的实际分派，拒绝 graph offsets，并加 autospec 分派断言。两份 patch 已读。作者 A800 报告57 targeted passed及224 passed / 1 gradient failure / 30 skipped；“继承失败”的归因未核验，bench 随形状有升有降。它是既有贡献的新 merge，不能写成新算法或普遍提速。另一个 #1423 merge 只读取消息，尚未深审。

三项仓库公开、许可 MIT、作者和 merge SHA 均核验；均非 Nathan 新贡献。它们支持我们的推断：硬件、编译器版本、实际 dispatch 和完整 backward 必须进入低内存方案验收。该推断不是上游作者对下一步私有计划的公告。

H2 新 merge 则具体化保存输入的 JSON 稳定身份、不可续租的暂停排空期限，以及保留 producer 权限上限的有界重新准入。详见 [恢复来源审查](2026-10-16-receipt-drain-readmission.md)。这些仍属源码与 CI 元数据；checkpoint-tail、kill-settlement、二次重启和真实持久副作用门槛继续保留。H3/H4 本轮未执行。

## 覆盖和盲区

主扫描 UTC `06:37:11.163630–06:41:39.987349`，真实旧 snapshot 加7日重叠；66个新增/变化顶层事件均晚于前次截止，未发现新个人原创仓库/profile 变化。

| 窗口 | Commits | Issues | PRs | Discussions |
| --- | ---: | ---: | ---: | ---: |
| 24h | 65 | 30 | 80 | 0 |
| 72h | 97 | 30 | 91 | 5 |
| 7d | 117 | 30 | 91 | 5 |

主扫描请求无失败，14个分页截断保留；不代表完整 GitHub。另有 H1 34次、H2/H4 54次成功定向 GET。网站/RSS及已知离职帖预览12次 HTTP 成功，11份非X原始响应与前次相同，已知离职帖预览未变。本轮支持浏览器会话命名报 `unsupported Codex auth method: apikey`，发生在绑定 tab 之前；当前 X 页面读取0、timeline覆盖未知。Nathan 新雇主仍未核验；离开 Kimi 不等于加入 Anthropic。

来源和实验保留各自实际时间及限制。[选定证据](evidence/2026-10-16-norm-saves-and-execution.json) 包含请求/原始文件指纹、预登记、独立审查与结果 hash；滚动原始响应不提交。成功扫描截止仅推进到 `06:37:11.159628+00:00`，定向审查不替代它。
