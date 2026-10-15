# 恢复、评分生命周期与 CP 数值对照

本轮观察于北京时间 **2026-10-16 00:28–00:33** 完成 GitHub 有界扫描，事件截止为 **2026-10-15 16:28:30 UTC**；对上一真实快照与已见事件去重后，105 个顶层事件首次采到或发生更新时间变化。没有发现七位跟踪对象的新原创个人仓库或 profile 字段变化；旧 issue/PR 的更新不当作新发布。

| 窗口 | commits | issues | PR | discussions |
| --- | ---: | ---: | ---: | ---: |
| 24h | 56 | 29 | 78 | 1 |
| 72h | 87 | 29 | 94 | 5 |
| 7d | 117 | 29 | 94 | 5 |

请求无失败，FLA、verifiers、OpenClaw、pi 的部分端点仍受首页及评论采样限制。定向源码读取另有自己的实际时间；个人站、RSS 与已知 X 帖另查，浏览器读取 X 时间线仍失败。已知离职帖重试成功，仍不包含 Nathan 加入 Anthropic 的公告；不能据此判断是否有未读新帖。

## H2：上游已合并，实现与兼容性证明分开

OpenClaw [PR #173018](https://github.com/openclaw/openclaw/pull/173018) 于 **16:09:21 UTC** 由 Peter / `steipete` 合并为 [275c611e](https://github.com/openclaw/openclaw/commit/275c611ead7a010e544ce5337e0588ec593e8087)。PR head 仍是上轮已读的 `db2ca7ef`，本轮新事实是进入主分支。不能把同一实现再算一次新研究，也不能把已存在的 retirement/repair 合同包装成上游缺失的设计。

独立核验的[上游 CI](https://github.com/openclaw/openclaw/actions/runs/38751786059) 对应该 PR head，42 个 job 成功、26 个跳过。作者的 213 项 native tests、14 个 Doctor cases 属于尚未核读日志的计数主张。CI 元数据、源码、作者主张与本项目实测保持分开。

固定 merge 的 repair 单测手建 version-1 binding，模拟 session store、current evidence 及 repair callback。生产 repair 需要锁定的 SQLite maintenance owner；注册为 `doctorOnly`、`after-session-repair`。这些单测不等于从真实旧 release 数据库执行升级，也不证明恢复后任务已完成。

因此 H2 继续验证**已接受实现的旧态兼容性与持久任务进度**。下一实验需由官方旧 release 生成 fixture，经真实 Doctor/维护 owner 执行、备份、compare-and-apply、关闭重开，再独立核对 assignment、receipt、结果与未完成工作。如果真实 harness 已覆盖且反例消失，应下调该切口的优先级。

## H1：新的维护者分支证据，尚无训练收益

FLA [PR #1390](https://github.com/fla-org/flash-linear-attention/pull/1390) 已关闭且未合并，API 记录的 PR head 仍是 `4056b9de`。其正文公开引用维护者 `yzhangcs` 的新 tip [7571b6f](https://github.com/fla-org/flash-linear-attention/commit/7571b6fcfd5bdf30fb012bc640d889e33e7e31b9)，提交时间为 **16:02:16 UTC**。对固定 hash 的 compare 确认窗口内四个真实新 commit，涉及 CP 输出/梯度对照 serial、按 state layout 处理 merge、small-state pipeline 与 GDP reference scaling。这不是 PR head 已推进或已合并的证据，也不是 Nathan 的贡献或新雇主证据。

这让 H1 的数值检查更具体：真实 activation/训练实验需同时对照 serial 与 CP 的输出、梯度、state layout 和缩放次数，避免把参考实现的缩放差异算成架构收益。它没有提供本项目的残差 bank 训练结果、GPU 峰值显存或吞吐。本轮没有执行这些 GPU kernel 或训练；H1 的真实 activation、等 token/等时间训练门槛仍未通过。

## H4：取证、评分与关闭服务的顺序

verifiers [PR #2866](https://github.com/PrimeIntellect-ai/verifiers/pull/2866) 是 `hallerite` 的新未合并提案。固定 head `f144485317dd96863ab096b8251b26482b55b346` 将正常 same-box 路径的 finalize、collect、score、`on_score` 放在关闭 harness session 之前；isolated 路径先 collect、再 close，随后做独立评分；timeout/stop 中断路径仍先关闭。该 head 三个改动文件是 rollout 与文档，未提交新增回归测试。本项目未执行其评分路径。

H4 的下一门槛新增**服务生命周期**：取证或评分所依赖的真实进程/HTTP 服务必须活到使用结束；被中止的 agent 同时不能继续改动被评分的 box。应在受支持的真实 harness 中分别验证正常完成、segment 间隙、中断、same-box 与 isolated 路径，独立记录清理时间和评分结果。若正确清理顺序对最终证据和 reward 没有影响，则该方向的收益有限。统一错误历史的旧 [PR #2857](https://github.com/PrimeIntellect-ai/verifiers/pull/2857) 仍未合并、head 未变，其 timeout 语义疑点继续保持未复现。

## 本轮执行边界

**新增实验为 0。** 本轮完成来源、实际改动和依赖边界检查；现有四个实验的结果未改写。另造 Doctor callback、状态机或评分替身会重复现有代理实验，不能补上真实旧态和服务生命周期门槛。本轮不把这些源码阅读记作实验完成，也不声称研究者的内部路线。

选定的原始事件、固定版本、CI 摘要、时间、许可和采样范围见[本轮证据](../reports/2026-10-16-lifecycle-and-cp/evidence.json)；历史实测见[适配器实验](2026-10-15-pi-adapter.md)。
