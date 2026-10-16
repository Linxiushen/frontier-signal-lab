# 恢复容量、数据库归属与工具服务边界

公开源码支持三个下一步实验：恢复任务与正常请求同时运行时的容量约束、写锁内确认数据库归属、实时和重放工具消息的一致性。verifiers 的新合并则提供具名服务放置入口。它们也可能属于常规集成修复，不能据此断言个人或机构的私人路线。本轮没有执行上游测试、Gateway、provider 或云端环境；H2 运行状态不升级，H3/H4 仍未执行。

专项事件窗口为 `(2026-10-16T12:42:56.583839Z, 2026-10-16T14:43:29.3684848Z]`，实际读取为 14:45:35.030720Z–14:48:42.231906Z。45 次只读 GET 中 44 次 HTTP200，另一次是核对作者所列测试路径的预期 HTTP404；无分页 Link。OpenClaw/pi/verifiers/AI-Scientist-v3 默认分支前 100 项分别返回 98/0/1/0 条 commit，99 条 committer 时间均通过严格窗口检查。选中 5 项变更的 32 个 changed patches 全读，共 57,242 字节；并非全仓库代码审计。四仓库为 public，前三项为 MIT，AI-Scientist-v3 为 Apache-2.0，均仅仓库元数据，未逐文件审核或复制实现。

| PR | 提案创建 → 合并（UTC） | PR 作者 | 精确 merge |
| --- | --- | --- | --- |
| [OpenClaw #174248](https://github.com/openclaw/openclaw/pull/174248) | 13:22:40 → 13:49:26 | steipete | `0e6818f076d304fe363dad62a1a070f084dffb49` |
| [OpenClaw #174251](https://github.com/openclaw/openclaw/pull/174251) | 13:26:44 → 13:51:11 | steipete | `2ce7c9253b8c51e8d0feef8ab6be72aab7b47078` |
| [OpenClaw #174293](https://github.com/openclaw/openclaw/pull/174293) | 14:11:44 → 14:30:46 | steipete | `750d231b0b06eb3814d9118ee342f65dada288ff` |
| [OpenClaw #174282](https://github.com/openclaw/openclaw/pull/174282) | 14:03:45 → 14:25:31 | roboclaw-bot，正文致谢 @vincentkoc | `39be602a8c9b11bac9174fc5433d1331fc8b95b8` |
| [verifiers #2872](https://github.com/PrimeIntellect-ai/verifiers/pull/2872) | 10 月 15 日 20:56:52 → 10 月 16 日 12:46:17 | hallerite，非 willccbb | `a4035acbf51a7a89d663f60d53f190e476708d59` |

**H2：恢复也需要资源预算和当前归属。** #174248 把原有 restored-requester 的 per-Gateway `pLimit(2)` 扩展为共享后台生命周期预算：cleanup、cleanup tail、过期 delivery finalization、orphan resume read、restored wake 共用 **2 个后台槽位**，live requester 继续走原有旁路。这与前轮独立 recovery gate 的 **4 个恢复槽位**是不同机制。排队前保留 task root，退休 owner 保留自己的 limiter，dispatch 仍检查 source/row/authority。新测试源码用被挂起的 mock announcement 排队 130 行，断言只启动 2 行、保留 130 个 root，释放后按 FIFO 顺序启动／出队，最终全部完成并归零；它是进程内模拟，不能证明真实 OS 重启。见不可变[生命周期源码](https://github.com/openclaw/openclaw/blob/0e6818f076d304fe363dad62a1a070f084dffb49/src/agents/subagents/registry/subagent-registry-lifecycle-context.ts)与[测试](https://github.com/openclaw/openclaw/blob/0e6818f076d304fe363dad62a1a070f084dffb49/src/agents/subagents/registry/subagent-registry-lifecycle.test.ts)。

#174251 将 schema owner/version/migration 决策移入既有写事务，在取得 writer lock 后仅失效 schema facts 并重读 owner。新测试使用两条真实 native SQLite connection，在待执行 `BEGIN IMMEDIATE` 前由 spy 让赢家 agent-b 提交归属，再要求 agent-a 拒绝并保留 b 的 owner/registry。它并非同时运行的双进程实验，未改动的跨进程测试也未在本轮执行或通读。见[写事务源码](https://github.com/openclaw/openclaw/blob/2ce7c9253b8c51e8d0feef8ab6be72aab7b47078/src/state/openclaw-agent-db-schema.ts)与[测试](https://github.com/openclaw/openclaw/blob/2ce7c9253b8c51e8d0feef8ab6be72aab7b47078/src/state/openclaw-agent-db.test.ts)。真实相邻 parent 是 #174248 的 merge，不能用 PR 的 base metadata 替代。

#174293 把 worker 的 routing/source resolver 移至已有 candidates 模块，resolver 函数体未因搬迁改变，新增 import 回边约束；这是模块边界变化。作者报告少 20 个本地模块、两个小样本中位数下降，但三次样本区间重叠，完整 boot 仅 1 次 candidate 对 3 次 noisy baseline，不能推生产性能百分比。见[worker](https://github.com/openclaw/openclaw/blob/750d231b0b06eb3814d9118ee342f65dada288ff/src/gateway/session-history-worker-reader.ts)与[import 测试](https://github.com/openclaw/openclaw/blob/750d231b0b06eb3814d9118ee342f65dada288ff/src/config/sessions/session-history-read.imports.test.ts)。#174248 的作者合成 rig 报告 0/50 → 50/50 reconnect，涉及 13,000 sessions/6,000 runs；测量树与真实相邻 parent/head 不同，candidate 延迟仍为秒级且有争用。它是未经本轮复现的可用性报告，不能描述为延迟提速；clean-close 后仍有 abort warning，也不能升级成优雅退出验收。

下一 H2 验收固定真实相邻 packaged trees，同时施加后台 catch-up 和健康客户端读取，核对 2 槽位、root、旧 owner limiter、当前权限和最终 drain；再用两个独立进程的 writer-lock barrier、SQLite reopen 与 registry receipt 核对归属竞态。实际两次 OS 重启、checkpoint tail 和 kill 请求后尚未 settlement 的窗口继续保留。任何正常读取饥饿、提前释放 root、陈旧 owner 写入、重复或越权效果均失败。

**H2/H4：工具消息的 live/replay 身份。** #174282 在 hook/storage clone 前，把 transcript run ID 发布到新鲜可变的 assistant **或** toolResult；冻结 replay 不变。同步/异步 append 测试区分原 live 内容与仅 transcript 生效的 hook，随后通过实际 Responses serializer 比较合成 live/replay JSON 与 observer prefix。源码断言内部 run metadata 不进入 provider tool output；它不证明 provider cache hit、数据库持久化或 reward 相等。PR 是 roboclaw-bot，不能归为 steipete 的个人贡献；正文致谢也不等于个人实现身份。见[guard](https://github.com/openclaw/openclaw/blob/39be602a8c9b11bac9174fc5433d1331fc8b95b8/src/agents/session-tool-result-guard.ts)与[测试](https://github.com/openclaw/openclaw/blob/39be602a8c9b11bac9174fc5433d1331fc8b95b8/src/agents/session-tool-result-guard.test.ts)。下一门槛是 shipped tool turn、不可变 transcript/reopen receipt、真实 wire bytes 与一次性合法 effect；cache/reward 分别测量。

**H4：工具放置与网络策略分别验收。** verifiers #2872 是旧提案的新合并，增加 `ToolsetConfig.service`，把 task MCP server 放进具名 Compose service，构造 `http://service:port/mcp`；与 colocated、URL、非 Subprocess 配置互斥，并拒绝 missing service/local runtime。测试 grid 的 service 轴仅在 Prime/Modal ComposeVM 执行，其余跳过。内部 Compose hostname 不加入 policy URL 列表，但当前策略仍是 **VM 级**；旧 egressproxy/composed 方案已移除，独立 VM LAN 被作者列为未来 PR，不能声称已有每服务 egress 隔离。见[配置与拒绝路径](https://github.com/PrimeIntellect-ai/verifiers/blob/a4035acbf51a7a89d663f60d53f190e476708d59/verifiers/v1/mcp/toolset.py)、[rollout 放置](https://github.com/PrimeIntellect-ai/verifiers/blob/a4035acbf51a7a89d663f60d53f190e476708d59/verifiers/v1/rollout.py)与[集成测试](https://github.com/PrimeIntellect-ai/verifiers/blob/a4035acbf51a7a89d663f60d53f190e476708d59/tests/integration/test_multi_turn_tool.py)。

作者所述 2,716 rollouts 属早期 revision，最终版本 smoke 仍列未来；正文声称的 `tests/unit/test_toolset_placement.py` 在精确 merge 路径返回 HTTP404，不能把该旧单测陈述转移为最终版本证明。下一验收需真实 Prime/Modal 当前环境版本、MCP stamped output/reward、VM 级策略、state channel 与 teardown 收据，并保留 missing/local/conflict 拒绝和合法服务对照。

5 项 prepared-head CI 均有 success 元数据；#174282/#174293 另保留较早同 head 的 skipped CI。verifiers Tests/Style 完成于本轮下界之前，并非本轮新 CI 事件。未检查 jobs/logs 或作者 rig 产物；bot review 亦非独立运行证明。12 项旧 issue-comment followup 为空，未全面覆盖 head/body 更新、其他分支、inline reviews、X 或一般公开讨论。

截止 tip `33f497e178d7acf5a48c940f00b18096de279672` 的 recovery/process blob 仍分别为 `9bd72cfe036715d1ecef6323ba9eda945828e365`、`4aac65c346765fb5463cc2736725b2782aba6465`，与上轮相同。没有新增真实重启、provider 或效果证据。[结构化来源、不可变文件与 CI 收据](evidence/2026-10-16-recovery-capacity-and-service-boundaries.json)保留完整 SHA、相邻 parent、作者与限制。
