# OpenClaw 重启：终端回复持久化与取消等待的边界

本次是固定版本源码及测试设计审查，未运行 OpenClaw、模型、测试或科学实验。Peter Steinberger（GitHub `steipete`）的 [PR #195164](https://github.com/openclaw/openclaw/pull/195164) 于 2026-11-08 10:12:24 UTC 创建、11:13:56 UTC 合并。PR head 为 `a320c5f9420a340a0e783c1e178f68cf0afd0b2f`，PR base 为 `f89b123d7fee5b991b8efa511867fb45072d017f`；实际落地提交为 `9fb5cdc3039aa23bb4a8bba828ad0820d6bbab5e`，相邻父提交为 `dcdd5c6da6d7d4047946e3030f273aad31bbdc8b`，二者不可混称。

实际调用方是 Gateway 优雅重启中的 embedded `AgentSession`：流式 provider 收到取消后可能稍晚才发出携带部分回复的 terminal event；如果 transcript writer 先关闭，尾部内容会丢失。改动把 restart 专用的消费等待与 writer 关闭顺序接在一起。`streamWithIdleTimeout` 立即把取消传给 provider，但为迭代消费保留一次不可续期的 abort-settle grace，通常为 2 秒、快速测试为 250 毫秒。chunk 和 heartbeat 不能延长它；到期的 pending read 保留原取消原因。原生 producer 已在期限内完成时会清除计时器，排队的 terminal reply 可供延迟消费者读取。

`cleanupEmbeddedAttemptSessionPhase` 在 transcript `beginCleanup` 前，用已有 `waitForEmbeddedAbortSettle` 等待 prompt/abort settlement；资源 dispose 不再顺序追加第二次同类等待。已接受的写入仍须排空。源码仍把 raw provider `next()`/`return()` 放在 retained cleanup owner 下：逻辑消费能到期，不代表底层工作已经关闭。忽略取消和 iterator cleanup 的 provider 仍可能拖住整个 Gateway shutdown。因此不能从这个局部 grace 推出“所有 Gateway 均在两秒退出”或没有 SIGKILL 风险。PR 的 User Impact 段落存在更宽表述，本记录采用其明确 Scope limit 及源码的较窄边界；作者也明确原始九秒 stall 未复现。

本次保存完整 PR 正文、九个 PR-head 文件补丁、实际落地 commit，以及七份完整落地文件。三个生产 owner、改变的回归段和 fixture 验收段经过审查，未闭合所有依赖。六份落地 blob 与 PR-head 清单相同；`attempt-session-settle.test.ts` 落地 blob 为 `996423c3b60a40ce2f2ac3d5b82b681be55acbf1`，不同于 PR-head 的 `c36577a5873525d82da083995a447a959362e33d`。初始“全部相同”检查真实失败并保留，随后直接用 Contents 字节及 Git blob 认证落地版本，未把这个差异隐藏为全部成功。

测试定义覆盖一次及 16 个并发 cleanup 在同一个 250 毫秒窗口结束、迟到 chunk 不续期、及时完成但延迟读取的 terminal，以及真正的 AgentSession/SQLite terminal row。新 stream 测试还显式要求底层 work 在释放前保持 pending。它们是作者测试设计证据，本项目没有执行。作者报告 130 个 focused tests，其中 115 个来自最终 timer 实现、15 个未改变案例复用同版本结果；其 exact-head CI 链接未由本次 API 核验，不能记作本项目 CI 通过。

作者的五组交错合成比较报告 SIGTERM 到退出中位数从 1.487 秒升至 1.894 秒（+27.4%），主线程 CPU 从 579 升至 693 毫秒（+19.7%）；candidate 范围 1.364–2.004 秒，最差配对 wall +41.1%、CPU +21.1%。A/A wall spread 为 87 毫秒、配对中位增量为 399 毫秒。候选在退出前及恢复后保留 16/16 部分回复，而 baseline 丢失 16 个，因此两组正确性结果不同，不能称为等质量加速。作者另报告 18 个一次恢复输入、两个 interrupted tool receipt、四个 cron receipt、无存活 child，以及 18 份恢复前 transcript 是恢复后字节前缀。以上均为未复现的作者报告。

单独 allocation sampling 的 A/A 为 119,675,296 / 121,983,120 bytes；A/B 为 121,983,120 → 135,585,240 bytes（+11.15%）。这组采样 CPU 为 674.924 → 858.439 毫秒（+27.19%），wall 为 1.459 → 2.168 秒（+48.55%），不并入普通计时中位数。它只覆盖 Gateway 主线程/heap，排除 workers 和 tool children。负载为 16 个慢流、两个前台 tool child、四个 cron、四个 pending WebSocket RPC 和 fsync 压力；35.1 GiB 数据库主要是合成 padding，并非生产历史。正文把新比较称为 exact-parent，却没有给该组 baseline hash；不能将实际落地相邻父提交或另一个旧 gate 失败 parent `3a25991…` 自动代入。历史 1.388 → 1.742 秒属于先前 revision，不能当成当前结果。

这条来源与已收录的 Pi `c96e368` 远程 CANCEL/local settlement 不同：这里是实际多会话 runtime 的 restart-only native stream → terminal persistence → writer closure 边界。先前 OpenClaw preparation worker 和 payload cancellation 来源也未覆盖此行为。放大并发时，需要同时约束逻辑 admission、未关闭 provider、已接受写入及恢复 effect 身份，而非把局部消费超时当资源已释放。

未来若接入此真实调用链，须先单独冻结版本、会话/慢流/工具负载、资源上限与可回退接口，预注册当前权限、幂等效应、取消、两次真实重启、terminal-row/前缀/effect-count 验收，并同时记录成功率、有效吞吐、端到端/尾延迟、峰值资源/通信和观测成本。本轮只添加源码信号，没有冻结协议、执行或依赖升级；不重开已关闭有限 gate，不增加 observer 前置工具。H1 负结果及无效 RSS 端点、H2 早先 concurrent 冻结失败与后续有限通过、H3/H4 未满足条件均保持。
