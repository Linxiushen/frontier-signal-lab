# H2：从独立模型推进到实际 pi 适配器原语

本轮 GitHub 扫描于 **2026-10-15 14:31:09–14:35:42 UTC** 完成，事件截止 **14:31:09 UTC**，请求无失败；分页与评论采样盲区保留。对上轮实际快照及本地已见事件去重后，有 102 个首次采到或更新时间变化的顶层事件。许多是旧 PR 关单，不等于新代码或新研究发布。

| 累计窗口 | commits | issues | PR | discussions |
| --- | ---: | ---: | ---: | ---: |
| 24 小时 | 55 | 32 | 74 | 2 |
| 72 小时 | 85 | 32 | 93 | 5 |
| 7 天 | 118 | 32 | 93 | 5 |

## 事实、提案与研究判断

**已合并事实。** pi [PR #10937](https://github.com/earendil-works/pi/pull/10937) 在 **13:02:28 UTC** 合并，对应 [f7e3cb5](https://github.com/earendil-works/pi/commit/f7e3cb5433ba9500d4381d201e628bb5301c9924)，提交时间 **13:02:27 UTC**。作者及合并者为 `christianklotz`，不归为 Mario 本人的新提交。上轮已看到的 namespace/queue 方案和相关测试早于本轮；本轮新事实是它进入主分支，不是今天首次提出这些机制。

**发生变化的提案。** verifiers [PR #2857](https://github.com/PrimeIntellect-ai/verifiers/pull/2857) 仍未合并，新 head `565b63377d8810caa690f42db290772582cecaf9` 改为用统一的 `trace.errors` 与 `Error.details` 记录评分失败，并在外层去重。不能继续把旧提案中的 `scoring_attempts/ScoringAttempt` 当作当前设计。该评分路径有多层运行时依赖，本轮只读代码，未运行评分或声明已复现超时语义问题。

**仍待验证。** OpenClaw [PR #173018](https://github.com/openclaw/openclaw/pull/173018) 在本轮定向读取时仍未合并。Peter 在 **13:36:49 UTC** 提交的 [105f2db](https://github.com/openclaw/openclaw/commit/105f2db64eaf9119eac00ee739b1f54154ec16e4) 处理不确定的 assignment retirement：在通过 owner 检查后，重复处理已不存在的 undelivered assignment 可以返回成功。对应测试代码已读，未执行；旧库升级、前台收据和恢复后工作进度仍需实际证据。上轮已经核验的 malformed-binding warning 不重复算新成果。

**本项目判断。** H2 可以从独立状态模型推进到一个实际适配器的队列和事务边界：失败的事务之后，已排队的独立写入是否真正完成；绕过 owner queue 的直接写入是否随事务回滚。上游已有相关测试，本项目做独立复核与边界记录，不宣称首创。

**下一方向推断。** 两个 agent 项目都在细化持久化与操作归属边界，因此本项目优先验证恢复后的持久任务进度、并发 owner 与上下文版本的共同契约。替代解释是这些改动只是在修复局部接口问题，并不指向更大的系统设计；若完整 harness 已覆盖这些场景且无进度损失，当前优先级应下调。这是本项目的实验选择，不代表作者的未公开计划。

H1 本轮未建立新的原作者 KDA/AttnRes 技术信号，真实 activation 与训练门槛仍未通过。七人个人站点、可读博客/RSS及已知 X 公告的补查未见明确新去向公告；本轮浏览器访问 X 失败，只读到已知帖的官方 syndication，不能判断 X 是否另有新帖。Nathan 新雇主继续记未核验。

## 唯一新增实验的范围

[pi adapter queue probe](../experiments/pi_adapter_queue_probe.mjs) 执行已合并 commit 的真实 `DurableObjectSqliteDatabase` 原语。上游 [cloudflare.ts](../third_party/pi/cloudflare.ts) 保留原始字节、MIT 许可、来源和 hash；Node 模块 hook 将未使用的上层 `SqliteStorage` 工厂依赖替换为一旦调用就抛错的 sentinel。

因此执行范围是**实际适配器代码 + 本地 node:sqlite stand-in**。没有执行完整 Pico storage、namespace migration、pi harness 或 Cloudflare 服务；也没有把内存队列变成持久队列。这种隔离及 sentinel 调用检查已写入结果。

结果与轨迹见 [report.md](../results/pi-adapter-queue/report.md) / [probe.json](../results/pi-adapter-queue/probe.json)，第三方代码的完整来源见 [provenance.json](../third_party/pi/provenance.json)。

## 实测结果

本地完整复现实际运行于 **14:42:44–14:42:59 UTC**：**61 项测试通过**，四个实验均完成，其中只有本次适配器实验是本轮新增。使用 Node **v24.19.0**、内存 SQLite；不使用随机数，无 seed。每条轨迹期限 2 秒，整体期限 20 秒，测试子进程外层期限 25 秒。

| 轨迹 | 实际 SQL 结果与进度 |
| --- | --- |
| 事务提交 + 第二适配器排队写入 | 释放前只有事务内行；提交后两行均保留，排队 Promise 完成 |
| 事务回滚 + 第二适配器排队写入 | 事务内行回滚；排队写入随后完成且保留 |
| 绕过队列的直接写入，随后回滚 | 直接写入已返回且可读；事务回滚后两行都消失，保留为负对照 |
| 回滚后再开事务 | 后一事务完成并保留自己的行，队列没有停住 |
| 提交后使用保留的 transaction handle | 实际拒绝晚写入，只保留已提交行 |
| 回滚后使用保留的 transaction handle | 实际拒绝晚写入，最终无行 |

6 条轨迹的行结果均与独立期望一致，正常运行 factory sentinel 调用数 **0**。额外自检实际调用工厂时被拒绝；真实永不完成的 Promise 也会触发 deadline。结果包含完整操作顺序、Promise 状态及 SQL 行，不把布尔安全指标代作任务进度。

结果 canonical SHA256：`7b5df023acea9c596764f779776a411c5382f8300a3071a36d6f2df675fd9d7d`。源码与许可指纹、命令和本地环境见[运行清单](../results/reproduction.json)。只执行队列/事务原语，不执行 namespace、旧库迁移或真实进程恢复；已有上游相关测试也已列入[本轮证据](../reports/2026-10-15-pi-adapter-followup/evidence.json)。

## 下一次门槛

通过有限、无进程崩溃的队列场景，只能支持这些具体操作在释放事务后能继续完成。下一步仍需真实旧数据库、维护锁与并发 owner、进程重启后的持久工作账本，以及修复后到业务结果的有限调度检查。直接底层写入回滚是所测边界的负结果，不能直接称为 Cloudflare 生产缺陷。

H3/H4 继续保持未执行状态。H4 的下一验证应区分可重试失败与最终失败的统一错误历史，检查超时标记、最终 `ok` 与失败事件序列能否一致；本轮不再另开评分实验。
