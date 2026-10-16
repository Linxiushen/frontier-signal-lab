# 恢复并发与评测工作区：两个源码信号的下一步验收

本轮只选择两个信号簇：H2 的“当前权限下恢复、有限并发下前进”，以及 H4 的“评测环境包含安装产生的文件系统线索”。这是公开项目的实现方向与我们自己的可反证实验，不能据此推断个人或机构的私人路线。**本来源工作者没有执行上游代码、测试、模型或新框架实验；H2 不升级运行状态，H3/H4 仍未执行。**

提交窗口为 `(2026-10-16T08:35:32.730428Z, 10:39:54Z]`；观察发生在 `10:42:26.322483Z–10:45:42.679751Z`。30 次只读 GET 全部 HTTP200，无返回分页 Link。OpenClaw/pi/verifiers/AI-Scientist-v3 默认分支分别返回83/2/1/0项；这不覆盖其他分支、全部公开讨论或 CI 日志。主扫描器管理事件截止，观察时间不扩大提交窗口。OpenClaw 与 verifiers 当轮仓库元数据均为 public、MIT；没有逐文件许可证审计，也没有复制上游实现。

| 来源 | 创建 → 合并（UTC） | 实际贡献归属 | 不可变提交 / 真实父提交 |
| --- | --- | --- | --- |
| [OpenClaw #173873](https://github.com/openclaw/openclaw/pull/173873) | 10-16 06:00:14 → 08:43:16 | steipete / Peter Steinberger | `37d210e4aaf3811c27d5d7191027cf9f0da08425` / `ce35625937bcfe988d361dea1ca8c7678baaab05` |
| [OpenClaw #173924](https://github.com/openclaw/openclaw/pull/173924) | 10-16 06:42:09 → 09:00:05 | steipete / Peter Steinberger | `f7f3b9ca184c12c0b56c28f5cffbc789dc635b57` / `35b769240bb14a7f400292936fbaf1c3e32196ef` |
| [verifiers #2874](https://github.com/PrimeIntellect-ai/verifiers/pull/2874) | 10-15 23:38:39 → 10-16 09:19:36 | hallerite / Konstantin Dunas；不是 Will Brown 的贡献 | `a681caefb5228fa74c247890a5b9d3e02816559e` / `0976c3073f903d3449163d473e31c7e278b4a042` |

三项都是旧提案的新合并。#2874 早已记录过两次更新（10-15 23:39:03、10-16 07:32:55），本轮新增事实是合并及其不可变源码。

**H2 的源码变化。** #173873 为子代理保存有界、规范解码的恢复来源证据，绑定原请求者身份及准入范围。证据本身不授予执行权；恢复时检查当前 Gateway/owner、会话与 lifecycle，并重新验证现行政策和授权。缺失、撤销或格式错误不会退回 system；只有 overload 被标为可重试。所读状态迁移24→25是该合并的兼容性栅栏，不能说后来的 main 仍为25。完整读了14/63个 changed patches，没有读完全部生成代码与其他测试。

#173924 的16个 changed patches 全读。无人值守恢复进入专门的 RestartRecovery 队列，默认并发4；可见的按需恢复走 Main。启动候选按中断时间跨 store 排序；单候选准备失败保留未计费标记，健康候选继续。改动中的测试覆盖8会话/2store、后台被占用而 Main 可运行、容量失败后重试、重复中断；进程夹具扩为5个中断会话，持住4个响应，释放后第5个开始。夹具使用真实 Gateway 子进程加合成 loopback provider/自有工具进程，不能等同真实模型或外部投递结果。

CI 元数据确证：#173873 的 prepared head `88b29015…` 对应 run38872939453 **failure**；作者称失败继承而来，归因未审计。#173924 的 prepared head `ce148c0c…` 对应 run38870946535 **success**；75 jobs/71秒等仍是作者报告，未取日志或逐测试证明。元数据不等于本地验证或 exact merge 上的运行。

下一实验须固定真实 packaged Gateway/依赖及 authentic parent；8会话/2store持住4恢复、释放后第5个启动，并保留健康 Main 对照。跨 await 撤销设备/角色/临时授权，注入准备 overload，再做 SQLite reopen 与两次重启。独立记录 PID、会话/lifecycle/sourceRun、精确 receipt、provider transport 和允许/禁止的持久效果；越权、重复效果、丢未计费 claim、旧权限复用或并发超4即失败。全4槽持续被占用时不宣称具有无条件前进保证。

**旧门槛没有清除。** 截止 tip `ab1d3b9e…` 下 `session-recovery-service.ts`、`bash-tools.process.ts` 的 blob 分别仍为 `9bd72cfe…`、`4aac65c3…`，与上一轮完全相同。因此长 checkpoint-tail、kill 请求到实际 settlement 前崩溃、精确 receipt、第二次重启及真实效果门槛继续保留。

**H4 的源码变化。** #2874 只增加3行：在检出配置版本之后、editable installation 之前移除 harness checkout 的 `.git`，源码文件保留。作者报告智能体把 harness 的历史/作者当成任务项目历史；4个选择性 timeout rerun 从低覆盖变为完成，harness git使用33/2716→0/630。不同分母与选择性重跑不能建立总体提升或受控因果效果；此 patch 没有新增测试，行为数据未独立复核。

可反证的下一步是固定任务/模型/nano-rlm/部署/预算，预登记全部任务并随机配对保留/移除 harness `.git` 两臂；另加确实需要任务仓库历史的健康对照。删除元数据前先核验安装版本，并保存环境/文件 hash、工具轨迹、覆盖、timeout、token和reward版本。没有减少干扰、损害合法历史任务或 trace/reward 版本漂移都否定预期收益。它只增加 H4 的环境控制门槛，不能证明 H3 自适应偏差或训练 reward 一致性；原真实 Pi/ACP/MCP replay 门槛仍未满足。

[结构化证据与请求 hash](evidence/2026-10-16-recovery-concurrency-and-harness-root.json)保存真实作者、父提交、CI head、源码阅读范围、原始请求摘要及限制。原始响应仍在 ignored run 目录；hash 是本地观察见证，不是公开原始归档。除此之外不提升任何实验状态。
