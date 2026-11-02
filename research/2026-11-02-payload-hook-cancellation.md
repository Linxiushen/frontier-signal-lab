# OpenClaw Chat Completions payload-hook 取消边界：仅源码与测试设计

2026-11-02 本轮发现并复核 OpenClaw PR #191090，作者和合并者均为 vincentkoc，12:48:28Z 合并。精确 parent 为 43bb559f841430368a4ae2bc1a213fc285d29ccc，landed 为 775dbe6eebe70ca93db665c8431e7eac09124ae7。这是本轮新落地信号，不归因为 Peter Steinberger 的个人研究发布。相关 #191024 仅是原 PR 引用，未另作第二项源码深读。

事实：旧 Chat Completions 请求在进入 HTTP create 之前直接 await onPayload；挂起的 hook 会令调用方 abort 无法结束这个等待。新调用把同一 hook 交给既有 awaitProviderLifecycleCallback，并传入调用方 signal。payload 替换仍只在返回值非 undefined 时发生。direct 和 managed Chat 路径共享这个请求函数；managed 内另有转 Responses 的路由，本次结论不覆盖那条分支。

既有 helper 在回调前检查 abort，用 Promise.resolve().then 调用 callback，把尚未完成的 promise 交给 optional observePendingProviderWork，然后以 signal race，返回后再次检查 abort。其 retry 依赖 racePromiseWithAbortSignal 是同一版本的原有实现：运行中 promise 与 abort promise 都进入 Promise.race，finally 移除注册的 abort listener；这保留 late rejection 的观察路径，但不终止 callback。host.ts 的 retention 是可选端口，默认 inert host 未安装它。因此调用方已收到 aborted 不能代表 hook 或 host 后台工作已经 drain，也没有任何持久化保管承诺。

测试设计：新增参数化两例是 direct+late resolve 和 managed+late reject，不是四种笛卡尔积组合。使用实际 adapter，但 buildModelFetch 注入 vi.fn 返回 synthetic Response，没有真实 HTTP server。hook entered 后，abort 带 CALLER_ABORTED；先要求 stream.result 返回 aborted/code，同时 observed promise 尚未 drain、fetch 零调用；再释放或拒绝 hook，要求保留同一个 terminal result 且 fetch 仍未调用。finally 释放 hook 并 allSettled。邻近 response-hook 用例已读。作者称指定两例在 base 的 2 秒 deadline 失败、head 通过，整套 8/8、93 邻近、14 prefix、类型和格式检查通过。这些是作者报告，非本项目执行或独立 CI 核验；2 秒也不是本项目 SLO。原评论明确缺少 shipped entry-point cancellation trace。

H2 工程推断：下一项既定 native ToolTask + 免费本地 HTTP 集成应把 caller cancellation terminal、未完回调/HTTP drain 和独立持久化 effect 分开记录与预算。对 late success/error 要检查不再 dispatch、不覆写既有 terminal，且在 current authority、幂等 key 和两次进程重启下查证 effect DB。这个信号直接帮助原集成的取消验收，不构成扩展孤立 observer 工具的理由。源码/作者 synthetic HTTP 证据不能升级成本项目真实 HTTP、durable effect、重启、exactly-once 或生产证据。

审阅范围：四条 changed path 的精确 diff 全读；17 个成功 immutable source versions 捕获，14 full-text read、3 scoped-only（旧 production 的完整 diff，host 两版的接口/默认/配置）。依赖 helper 两版字节一致已核验；不声称完整 dependency closure。first capture 的错误 helper 路径导致 assert exit1，原请求状态/时间未保留，成功压缩字节保留后恢复；manifest 如实记录，不补造。源码审阅阶段没有执行 upstream 测试、native/model/scientific suite，也未修改共享账本或 tracked 文件；之后本次选编新增本报告、不可变源码包和审阅清单，并将 research/sources.json 从215条增为216条，215个旧对象逐条保持不变。假设、共享账本与科学状态未改。

一手证据：[PR #191090](https://github.com/openclaw/openclaw/pull/191090)、[精确落地 commit](https://github.com/openclaw/openclaw/commit/775dbe6eebe70ca93db665c8431e7eac09124ae7)、[审阅清单](receipts/20261102T125850Z-openclaw-payload-cancellation-review.json)、[不可变源码包及 MIT 许可](receipts/20261102T125850Z-openclaw-payload-cancellation-source/manifest.json)。
