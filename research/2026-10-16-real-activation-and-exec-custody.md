# 真实残差压缩成本与后台通知归属

本轮完成一个原创实验：在固定预训练模型的真实残差上，测量逐步 int8 打包、前向和反向。**这版实现没有减少反向保存的存储，观测 CPU 耗时和进程峰值更高。** 完整数值、配置和哈希见[实验报告](../results/real-activation/report.md)与[JSON](../results/real-activation/report.json)。

实际开始：2026-10-16 00:39:06 UTC（北京时间 08:39:06）。扫描执行：00:39:41–00:45:07 UTC，事件截止 00:39:41.605720 UTC。独立定向查询的时间、来源与局限见[证据快照](evidence/2026-10-16-real-activation-and-exec-custody.json)，不替代扫描覆盖。

## H1：真实激活与算子反向已有测量，训练仍待验证

固定历史公开模型 [EleutherAI/pythia-14m](https://huggingface.co/EleutherAI/pythia-14m/tree/cf967c0a9a04383db6f7b1108d86b2962634b4ac) 的 revision 与七项资产的大小/SHA256。权重使用 Apache-2.0，未提交权重；输入为本仓库原创文本。离线 CPU float32/eager/eval/no_grad 前向，在六个 GPT-NeoX block 入口采集 `[6,512,128]` bank。512 tokens 是四段独立的 128-token 上下文。复采的 bank、NPZ、token 和配置哈希一致；独立复核还确认第一层输入精确等于固定权重的 token embedding。[来源与许可](../fixtures/real-activation/README.md)。

这些是传统残差网络的累计 block 输入，不是 AttnRes 分支输出。在脱离模型计算图的 bank 上，三个固定随机共享 pseudoquery 比较 dense 与每一步重新量化/解码的 int8。损失 `mean(output**2)` 只对 bank/query 叶子副本反向，无学习 query、优化器或模型反向。int8 的 identity STE 是代理梯度，codes/scales 不求导。

| 指标 | 本次结果 |
| --- | --- |
| dense 对独立 float64 NumPy 前向 | 三个 seed 全部通过既定容差 |
| int8 输出相对 L2 差异 | 0.8659%–0.9030% |
| bank / query 算子梯度相对 L2 差异 | 1.0587%–1.4719% / 0.4416%–0.6152% |
| 反向保存的唯一 backing storage | 两方法均 3,432,960 bytes，无减少 |
| dense / int8 前向加反向中位耗时 | 2.62–3.13 ms / 3.96–7.99 ms |
| dense / int8 OS 生命周期峰值 | 207.88–208.68 MiB / 210.49–210.86 MiB |

六个新进程，每方法/seed 一个；每进程一次 warmup、三次相同输入计时，不是三次独立进程重复。峰值包含 Torch、输入、warmup、额外 saved-tensor 采样与输出持久化；不是隔离算子峰值或 GPU 显存。耗时为各 worker 中位数范围，不做性能显著性推断。初次预跑与复采进程重叠，其成本排除；随后在采集/测试进程退出后独立执行的六 worker 测量用于报告，数值稳定哈希与预跑相同。

storage inventory 是张量记账，不是 RAM 测量。当前 STE 保留 float32 叶子并物化 float32 解码 bank，没有训练期压缩保留机制。输出/梯度误差不是模型质量。稳定结果 SHA256：`a61b7dabb97e9e38f3016e628d9de4129d9d2919741b1ca8fe4f40373f2b07c5`。

**判断改变：**真实激活与算子 backward 的空白已补一部分；朴素解码 STE 未获存储收益。下一步应在学习 query、优化器与真实 backbone 保留成本下，做等 token / 等 wall-clock 小模型训练及封闭 loss 评估，再决定压缩优先级。无 GPU、困惑度、训练质量或架构优势结论。

## H2：通知义务已合并，kill settlement 仍需实验

Peter / `steipete` 的 [OpenClaw PR173454](https://github.com/openclaw/openclaw/pull/173454)于 2026-10-15 **23:19:53 UTC** 合并为 [`dbc41ff76ba1d835ab36261c48c5ecea87deff4c`](https://github.com/openclaw/openclaw/commit/dbc41ff76ba1d835ab36261c48c5ecea87deff4c)。源码把后台 exec 的通知义务保存在私有 session row，持久化后返回 background handle；恢复时重查 session、逻辑 agent 和工具权限，以 process-instance/source-turn 交给既有事件 owner。它通知结果未知，不重放命令或维持物理进程存活。

已读全部 22 个文件 patch，包括 owner 测试与真实 Gateway 进程 E2E 源码。E2E 使用本地脚本化 SSE provider，覆盖 managed/SIGTERM/SIGKILL、文件效果与通知/权限断言，明确跳过 Windows。本轮未执行上游测试；新读成功 CI 只核验 metadata/head，未读 jobs/logs，不能证明具体测试或 squash tree 执行。

保留[公开 P2 关切](https://github.com/openclaw/openclaw/pull/173454#discussion_r4288588952)：通知义务应在 kill settlement 后清除。当前源码在请求终止后、确认完成前清除持久事实。评论原发 21:44，早于前轮截止；这是本轮关联到最终源码的旧关切，尚未本地复现。早期 shared-store/logical-agent P1 已有修复，不能据此称所有发现均已解决。

下一门槛：固定真实 parent `824e909530916673681c05f1dfef9ba3721fd071` 与合并版本的进程 fixture，在 kill 已请求但未确认时崩溃，记录 PID、SQLite 义务、notice、请求与副作用，加入 cleanup uncertain、reset/revocation 和写入失败。已有“取消完成后再重启”测试不能清除这个窗口。H2 预测仍是公开工程继续加强版本、持久归属与活性边界，复核日 2026-10-30；不推断个人私有计划。

## 覆盖与未变化项

| 有界窗口 | commits | issues | PR | discussions |
| --- | ---: | ---: | ---: | ---: |
| 24h | 61 | 31 | 85 | 1 |
| 72h | 91 | 31 | 100 | 5 |
| 7d | 117 | 31 | 100 | 5 |

扫描校验通过，请求失败 0，52 个新增/变化顶层记录。活跃仓库首页和评论截断保留未知，数字不是全量活动。H1 另做 20 次定向读取，未发现改变现有 AttnRes/FLA 判断的技术增量。verifiers2866/2857 与 pi11000 状态/head/body 未变，H3/H4 不新增实测。

X/博客单独核验：12 次公开 HTTP 读取成功，11 个非 X 响应与前轮原始内容一致；已知 Nathan 离开 Kimi 的帖子预览未变。支持的浏览器在认证设置阶段失败，实际 timeline 读取 0，未推进覆盖。该帖发布于 2026-10-15 00:04:05 UTC，仍不能证明加入 Anthropic；新雇主未核验。职位、声望与旧 fork 不作为方向证据。

本轮本地 89 项测试通过，包含新增 6 项 Torch 梯度/存储/完整性检查。CI 增设 CPU Torch 作业离线重放 fixture，跨平台数值使用容差对照。此前六实验的已发布结果不改写；新报告自身记录代码、输入、配置、轨迹和结果哈希。
