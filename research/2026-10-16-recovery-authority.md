# 恢复权限、取消与等待期限：收紧 H2 的验收条件

本轮三个新合并把 H2 的下一步工作收窄到具体边界：恢复后用当前设备/角色权限控制真实持久写入；区分写入前取消与写入后清理；用单调时钟衡量等待期限。它们是公开工程信号，也可能只是已知集成问题的常规修复。不能据此推断个人或机构的私人路线。

**本来源工作者执行的上游测试、模型或完整代理框架实验均为 0。** H2 的运行验证状态不变，H4 仍为 planned。本文中的“测试检查”指源码断言；CI success 只指取得的运行元数据。

## 事件与覆盖

基线 `cb09c5fb7bfd279e6b746392a74fccd81627ec76`；前次成功扫描截止 `2026-10-16T02:38:46.921970+00:00`。独立提交查询为 `02:38:46Z–04:35:11Z`，下界重叠 0.921970 秒，上界取本轮开始时间的整秒。本来源任务不推进主扫描器截止。56 次 GET 实际发生于 `04:38:06.775518Z–04:42:38.671126Z`：54 成功、2 次把 pi issue 当作 pull 读取的 404；错误响应已保留，随后用 issue 端点成功读取。

默认分支窗口内 OpenClaw 86 个提交，verifiers 0，pi 0；每仓一页、无 next 链接。没有审计所有 86 个 patch。保存 18 个 patch，其中三个 H2 候选的全部 13 个以及 verifiers 补充提议的 3 个完整阅读；另外 2 个 session-link patch 只保存、未纳入结论。未覆盖全部分支、作者动态、X、个人网站或 GitHub Discussions。

三仓当轮 metadata 均为 public、MIT。下面的 GitHub 作者/association 是贡献归属，不等同于雇佣关系；这三个改动都不能归给 Peter Steinberger 的个人研究计划。事件新鲜度按合并时间判断，不能把旧 proposal/CI 当作今天的新结果。

| 来源 | 创建 → 合并（UTC） | 实际作者 / 合并者 | 不可变合并提交 / 真实父提交 |
| --- | --- | --- | --- |
| [#170336](https://github.com/openclaw/openclaw/pull/170336) | 10-12 22:26:24 → 10-16 04:05:58 | `jjjhenriksen`，CONTRIBUTOR / `fuller-stack-dev` | `a6299915e2838fcb9081b72ce12c4c7b30a49319` / `7bf56c8aa5029a1bd2b2d5cba762ea7c2b70362b` |
| [#173580](https://github.com/openclaw/openclaw/pull/173580) | 10-16 00:13:15 → 02:59:11 | `LLagoon3`，CONTRIBUTOR / `RomneyDa` | `0169c8acfbff959e3009c2550e5a0ca2bd708371` / `c2d48f9f67488bd450a0e5f580955bf59e1063fd` |
| [#173241](https://github.com/openclaw/openclaw/pull/173241) | 10-15 15:37:50 → 10-16 04:25:20 | `wangmiao0668000666`，CONTRIBUTOR / `obviyus` | `8447f6a1ad25fcdc398c0e8e50299d6e33ea5602` / `1c93dbed0cce9698eedc32839793baa487481a82` |

## #170336：比只读会话控制更具体的撤权断言

`openclaw-native-recovery-authority-tests`：最终合并差异只有五个 test/support 文件，+496/-38，**没有新的 production 修复**。不能沿用旧评论对旧 head 的生产变更或 232 个用例的描述来解释最终差异。

新增 [native-restart-recovery 测试](https://github.com/openclaw/openclaw/blob/a6299915e2838fcb9081b72ce12c4c7b30a49319/src/gateway/server-instance-runtime.native-restart-recovery.test.ts) 保存源身份和 transcript，关闭旧 SQLite handles，轮换进程生命周期 generation，再用新 Gateway runtime/context 恢复。11 个场景包括 native 原输入/steering、Control UI、无主 delegated/cron 输入、agent/session key/incarnation/lifecycle 不匹配，以及 admission 后设备撤销和角色变更。

被允许的 continuation 进入现有 automation tool 和真实 Gateway/Cron 持久化 owner，写入一个 **disabled** job；被拒绝的场景检查 jobs 为空。身份不匹配还检查不启动 turn、保留原 source 与 aborted 状态。这里确实调用设备撤销/角色写入 owner，较先前 #173579 的 session permissionMode→read-only 对照更贴近所需权限边界。

但身份握手、设备材料和 provider 均为合成 fixture；turn service 与模型 preflight 被 mock。冷态重建发生在同一测试进程，没有 OS kill/restart、签名 native handshake、真实推理或外部自动化执行。disabled job 的落盘也不证明远端效果或 exactly-once。作者 11/11 及其他数量、mutation check 的运行陈述均未独立复跑或审计日志。

另两组 [工具准备测试](https://github.com/openclaw/openclaw/blob/a6299915e2838fcb9081b72ce12c4c7b30a49319/src/agents/embedded-agent-runner/run/attempt-tool-prepare.web-search.test.ts) 分开检查 built-in/catalog：阻塞 attribution baseline 后使 source 失效，断言参数准备与 execute 均不发生。built-in factory 是消费真实转发 callback 的 mock，不能称为实际工具执行。持久 dashboard metadata/inherited deny 则用来约束缺少搜索配置的 guidance。

## #173580：取消成功不等于可以清理所有共享资源

`openclaw-prewrite-handoff-cancellation`：完整六文件 patch 在 [startup](https://github.com/openclaw/openclaw/blob/0169c8acfbff959e3009c2550e5a0ca2bd708371/extensions/codex/src/app-server/attempt-startup.ts) 和 lifecycle owner 之间传递同步 `onPrewriteHandoffCancelled`。在等待旧 owner 的物理退出、当前 client 尚未写 thread state 时取消，保留健康 replacement；后继继续等 predecessor 真正退出才发 `thread/resume`。

这不是全面放松清理：timeout 仍退休 client；configured-MCP replacement 已经 `thread/start` 后，显式禁止把退出等待取消标成 pre-write。提交中的两个测试文件通过合成 client/transport、deferred lease 和请求顺序覆盖取消保活、超时退休、写后排除。

维护者在 [02:51:37 评论](https://github.com/openclaw/openclaw/pull/173580#issuecomment-6206946008) 提供 pinned Codex 0.161.0 实进程 before/after 片段：head 重用第二个 app-server，base 启动第三个；predecessor 退出序号 14 早于 resume 15。**这是公开的作者/维护者运行陈述，临时 native harness 未提交，本轮没有独立执行或核验原始 artifacts。** 03:58:21 的后续评论还承认完整 Docker lane 有一项据称可在 base 复现的失败，以及新 autoreview 因认证失败未产生报告；不能写成全部验证通过。

## #173241：liveness 的相对预算不能依赖墙钟

`openclaw-monotonic-process-poll`：两文件小改动将 [process poll](https://github.com/openclaw/openclaw/blob/8447f6a1ad25fcdc398c0e8e50299d6e33ea5602/src/agents/bash-tools.process.ts) 的 deadline、循环条件和 sleep 剩余量从 `Date.now()` 改为 `performance.now()`。新增单个 regression 用 fake Date/setTimeout 制造墙钟向前跳 60 秒，断言仍收到稍后输出；它不是实际 OS 时钟实验，也不覆盖所有退出/恢复状态。

作者正文报告 secretless Linux ARM64 Gateway、脚本 provider、真实 shell、libfaketime 的八个 turns，含向前/向后跳与不跳对照。还列出两个原有 Code Mode persistence 用例失败并归因于未修改 base。本轮只读 patch/正文/评论，未审计其原始执行日志。此修复支持把单调期限加入 H2 liveness 验收，但不修复下面的 kill-settlement 持久义务窗口。

## CI 元数据与仍存在的旧窗口

| 固定 prepared head | 主 CI 元数据 | updated_at（UTC） | 证明边界 |
| --- | --- | --- | --- |
| #170336 `61ffd2d6f0f68c72f8ada8ad5e7cc89ca7773cae` | [38847209993](https://github.com/openclaw/openclaw/actions/runs/38847209993) completed/success | 10-16 04:05:12 | 未审 job logs，不证明具体场景已独立执行 |
| #173580 `f5e9dc46d236cdb7f5f658fb0c113350cbb31adc` | [38828234904](https://github.com/openclaw/openclaw/actions/runs/38828234904) completed/success | 10-16 00:24:45 | CI 早于本轮截止；新事件是 merge |
| #173241 `845628b2d516580229e00aab4fef3a7e30bf1161` | [38849580849](https://github.com/openclaw/openclaw/actions/runs/38849580849) completed/success | 10-16 04:22:21 | 未把作者局部失败的归因提升为独立证明 |

固定窗口末端 ref `7a16e56789212f3d5985317f1e8d0205ab06d787` 的恢复服务 blob 仍为 `9bd72cfe036715d1ecef6323ba9eda945828e365`，与 #173579 squash 中该文件完全相同：recent 20 / 256 KiB，整个文件没有 `readMainSessionRecoveryCheckpoint`。当前 process 文件的 kill 路径仍在取消请求后立即 `clearExitNotification`，supervisor 尚负责 settlement。

因此 [checkpoint-tail P1](https://github.com/openclaw/openclaw/pull/173579#discussion_r4290098935) 与 [kill-settlement P2](https://github.com/openclaw/openclaw/pull/173454#discussion_r4288588952) 保留为未复现源问题。#173579/#173454 完整 issue/inline 数组与前次一致，没有新评论；未查询权威 review-thread resolved 状态。旧 #173579 failed CI 的历史判断也未被这些新 PR 的 success 元数据覆盖。

## 补充信号与下一步

[verifiers #2875](https://github.com/PrimeIntellect-ai/verifiers/pull/2875) 是 `Emilianopp`（association NONE）于 03:14:38 创建的 open 提议，head `04b05dae300fa0271bf40d44fc0d9e886e10f775`，父提交为 #2864 squash。三个 patch 完整读取：在 env-server 进程共享 HTTP pool，发 tool-less streamed completion，拒绝 MCP，没有 compaction。作者性能/mock-server测试陈述未经验证，integration cells 明确未本地运行。它不能替代固定 Pi/ACP/MCP 的真实两段回放、token/mask 和 teardown gate，H4 不改状态或优先级。

pi [#11012](https://github.com/earendil-works/pi/issues/11012) closed issue 新评论给出 fork-only 的 compaction preflight 修复及 144 项测试陈述；未验证其已进入上游。旧 [#9602](https://github.com/earendil-works/pi/issues/9602) 的新评论支持把预算检查与实际 thinking serialization 对齐，没有新的已验证结果。verifiers #2864/#2866、pi #11000 unchanged；#2857 仍 open、head 不变，仅 GitHub 计算的 prospective merge SHA 改变，不是源提交更新。

H2 下一次完整框架验收应结合这些更精确的上游 fixtures：真实入口与设备/角色撤权后，旧身份不能产生 durable effect；写前取消释放等待但不销毁健康共享 client，写后/timeout 保持保守清理；墙钟跳变不破坏相对期限。还必须保留旧 checkpoint-tail、kill-before-settlement crash、持久化失败、外部 effect receipt、再次重启和并发控制。当前 Windows 本地完整框架条件仍未满足；本轮仅修订来源与测试要求，未把要求写成实验完成。

选定来源、各 patch 哈希、CI 元数据与完整请求清单的指纹见 [evidence](evidence/2026-10-16-recovery-authority.json)。忽略目录中的冻结审计 `reports/runs/20261016T043511Z/frontier-checks.json` SHA-256 为 `51f438c65674a31c93f1954fae04dabbc07a1af9279614580a22fb50782db072`。原始证据是 `gh api --include` 的 stdout bytes，不是网络包抓取；上游代码只在忽略目录中用于审阅，没有复制到发布代码。
