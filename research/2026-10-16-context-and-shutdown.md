# 上下文转换实测与停机恢复证据

本轮选择的研究方向是：把上下文身份、未完成工作的持久归属和恢复后的进度放进可执行契约。依据是公开代码与测试；这不是对研究者私下计划的断言。新增实验仅一项：执行 pi 修复前后两个完整、未修改的上下文转换模块。

## pi：用真实旧版本作对照

固定 [9113094](https://github.com/earendil-works/pi/commit/911309429175254550837167baee245d5f9dbcb6) 与其真实 parent [5ab7fe7](https://github.com/earendil-works/pi/commit/5ab7fe74c400097b386662205cd93900695b8a71)，以 Node 原生 TypeScript 执行完整 `transform-messages.ts`。该模块仅有被擦除的类型导入，没有运行时依赖替身、提取函数或模型调用。上游作者是 davidbrai；17:38:33 UTC 的合并已在上一轮记录，本轮新增的是本地执行证据。

输入为确定性消息 fixture，8条轨迹共执行模块16次。真实旧版本在模型、provider、API 切换及模型交替的4条轨迹中，把其他模型的可读 thinking 转为可见 text；修复版在这4条中均丢弃它。普通文本、完整工具调用/结果、同身份的签名及脱敏空 thinking 块均符合预先写定的输出；error/aborted turn 被移除，所有输入和模型对象保持不变。旧版本未满足目标边界的结果作为负对照保留。

签名与脱敏字段使用合成标记；保留标记不证明签名有效或 provider 接受请求。[实验报告](../results/pi-context-transform/report.md)及[完整输入输出与 hash](../results/pi-context-transform/probe.json)可独立重跑。执行范围是消息转换模块；可选 ID normalizer、缺失工具结果的补造、图像分支、provider 序列化/请求、完整 pi harness 和持久化恢复尚未执行。

本地一键复现通过83项测试及六个实验，其中本轮新增实验只计这一项。源码篡改会被hash检查拒绝；在隔离副本中把 merged 换成真实 parent 后，实验进程按预期返回失败。其余五项为回归重跑；CPU 内存/时间观测随环境变化，数值稳定载荷与前次一致。

## OpenClaw：跨进程恢复已有上游实现与执行证据

Peter / steipete 于 **2026-10-15 20:35:52 UTC** 合并 [PR173342](https://github.com/openclaw/openclaw/pull/173342)，squash commit 为 [7ee9c27](https://github.com/openclaw/openclaw/commit/7ee9c27cd427b455ae39e3a81644bb406b7a0755)。普通进程停止现在等待恢复归属标记，再使用有类型的中断；显式 Stop 保持终止，reset 撤销旧生命周期。若标记失败，代码仍会报警并继续关闭，不能理解为存储故障下无条件持久化。已读全部14个改动文件。

新增进程测试启动真实 `dist/index.js` Gateway，使用本地脚本化模型端点、真实 exec/HTTP 效果与 SQLite 状态。一个组合测试跨4次进程生命周期，覆盖 SIGTERM、managed restart、SIGKILL、恢复中再次停止、显式 Stop 与 reset；检查会话连续性、接受的效果为1、reset 禁止的效果为0。它完成了这些受控任务，不能推出所有停止/恢复/权限/存储组合都有进度，或任意外部副作用都恰好执行一次。

本轮实际下载并核对 [CI run38795468794](https://github.com/openclaw/openclaw/actions/runs/38795468794) 的日志：[changed-7 job](https://github.com/openclaw/openclaw/actions/runs/38795468794/job/116631453199) 报告该测试通过，test 为80.476秒、文件总 duration 为120.26秒、分片 exit0。workflow 关联 head `647d29fe`，**实际 checkout 是临时 PR merge `8ad31f93`**（该 head 合入 base `2f228582`），不是后来的 squash commit。另核对的5份实现/测试 blob 与 squash 一致；这不是整个最终 tree 的 CI，也没有本地执行。

整体 CI 结论仍是 **failure**：43 success、25 skipped、2 failure。实际日志显示 `apple-build-cache.test.ts:232` 的 TS2345；[scheduled main run38794323475](https://github.com/openclaw/openclaw/actions/runs/38794323475) 的配置、退出码与完整诊断也相同，支持该失败已在 main 出现。CI gate 同时注明 selected scope 未作比较，不能据此宣称所有差异均无回归。原样 Gateway 测试依赖 POSIX shell/signal 和完整构建；本轮 Windows 未执行它。

因此 H2 的下一门槛进一步收紧：复用已经存在的上游恢复测试，将其状态查询、生命周期撤销等断言扩展到真实 provider、效果回执与持久化故障组合。真实发布旧态的 Doctor 锁、备份、精确行校验、重开和任务进度仍是独立门槛。不能再把“停机后恢复”本身当成尚无人实现的空白。

## 其他信号与可证伪判断

verifiers [e3c2863 / PR2869](https://github.com/PrimeIntellect-ai/verifiers/commit/e3c28634ce1f6243ac4b9758dce2c715b1861bed) 是 xeophon 的已合并修复：isolated verifier 从原始 agent runtime policy 解析，避免沿用 solver 已解析的配置。已读源码，未执行；它不代表未合并的 PR2866 服务生命周期提案已经落地。

H1 的真实 activation、等 token/时间训练与 GPU 成本门槛仍未完成。FLA1415 的新内容是相同 head 上追加作者验证主张，包含 empty-packed 变慢；1402 的新 commit 是非连续输入归一化边界修复。两者都未合并，相关性能表不是本项目实测，也不归因 Nathan。保留原始区别，未将其作为 AttnRes 训练进展。

本项目的两周工作预测是：公开 agent 工程将继续增加以恢复进度、生命周期撤销和外部效果为断言的回归测试。复查日期 **2026-10-30**；若后续有界样本没有独立支持，降低该预测的证据强度，并继续保留未知覆盖。这个预测用于安排我们的验证工作，不推断个人或机构的未公开路线。

## 本轮覆盖

扫描实际 **20:35:42.986938–20:40:25.630719 UTC**，事件截止 **20:35:42.982941 UTC**。93个顶层事件首次采到或更新时间变化；没有新增七人原创个人仓库或 profile 变化。该停机恢复 PR 的合并发生在扫描截止之后，由单独定向读取核验，未推进扫描截止时间。

| 窗口 | commits | issues | PR | discussions |
| --- | ---: | ---: | ---: | ---: |
| 24h | 64 | 24 | 85 | 1 |
| 72h | 91 | 24 | 99 | 5 |
| 7d | 117 | 24 | 99 | 5 |

扫描请求无失败；首页/评论采样有截断，定向 OpenClaw commits50条也有下一页。七个主页、Nathan 博客和三个 RSS 的11份响应与前轮摘要一致；已知离职帖预览未变。支持浏览器读取当前 X 时间线失败，未读新帖仍未知，Nathan 新去向继续记为未核验。定向读取的失败、解析重试、原始 hash 和独立观察区间见[证据快照](../reports/2026-10-16-context-and-shutdown/evidence.json)。
