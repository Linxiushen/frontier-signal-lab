# 插件后台通知：会话代次、当前权限与独立效应

OpenClaw PR #190893 于 2026-11-02 14:24:41Z 合并，作者及合并者均为 obviyus。精确 parent 为 9c2446678be4df226d9de4cb4e09edb1135997f7，landed 为 2163664150dffac1d4cfed646fb2d50973ad9e3d。该落地晚于上一轮 13:01 的扫描截止；05:42 的原提案不是本轮新发布，也不归因为 Peter Steinberger 的个人成果。

新增的 captureSessionGeneration / postSessionNotice 接到既有插件 registry 的 system 路由和 Workshop review 完成调用。捕获值包含 agentId、storePath、sessionKey、sessionId、lifecycleRevision。运行时 wrapper 仅转发公开字段，从宿主作用域取得 pluginId 和当前 owner 检查，插件参数不能自行提供这些权限。初始有序会话读取发现代次变化时返回 skipped；当前插件检查还被传入后续 channel handoff 与 transcript writer。这里核验的是调用与检查位置，未审计完整依赖闭包，不能据此声称覆盖所有并发竞态。

三个效应仍分开：可选 system event 在首次有效读取的同步消费阶段入队；durable channel send 随后执行；最后 append transcript-only notice。新的 notice marker 不直接成为后续模型历史，另一个可选 system event 才提供下一轮上下文。channel 已接受后再撤回插件，会拒绝 transcript 写入，但不能收回已经发送的消息；此前已入队的 event 也没有跨三个效应的事务回滚。重试测试证明的是其指定 channel/transcript 情形，未证明所有 event 重试恰好一次。

channel 队列新增的 completion 只保存 kind=plugin-notice 与 pluginId。恢复时查当前 active registry 中同 ID 的 loaded/enabled 实例，并把 live 检查接到异步准备之后的最终 adapter handoff / dispatch；撤回后拒绝继续发送。这没有固定原插件代码版本或 incarnation，同 ID 换版是否可重放仍需调用方明确约定。稳定 intent key 与完成回执支持指定重试，但回执保留上限为 24 小时、2,000 条，不能外推无限期 external exactly-once 或有界准入。

新增四个测试文件涵盖磁盘插件加载、fixture channel、transcript 失败后重试、同进程 registry 重建、恢复准备中撤回、旧版本 queue JSON，以及 Gateway/mock-provider 的 prompt-prefix 断言。名为 restart 的 helper 没有启动、强杀或重开 OS 进程；旧 JSON fixture 也不是安装并执行旧版本的降级测试。作者报告的 7 项 runtime e2e 和其他通过结果仅是作者报告，本项目没有运行 upstream 测试、核验其 CI 或进行 native/model 实验，更没有测量模型 cache 收益。

本项目推断：这提供了一个实际 runner 的可复用通知边界，下一项有充分理由的集成应分别固定会话代次、插件权限及版本替换语义，独立记录 event 入队、channel 接受、transcript 提交与过期回执；在 await 前后、transport 接受前后撤回，并完成两次真实进程重开，同时预注册准入、取消、成功率、有效吞吐、尾延迟、资源与观测成本。此次只补充源码证据，不新增 observer 前置工具，不重开已关闭的有限 H2 HTTP fixture；H1 负结果及原资源门槛、H3/H4 科学状态均未改变。本轮科学实验为零。

审阅范围为全部 19 条 changed-path diff；32 个完整 changed-path 版本已捕获，其中 20 个跨 13 路径全文读取、12 个跨 6 路径只读变更及相关上下文；另读两版 MIT LICENSE。六个新增文件的 parent 404 是预期缺失。19 个 landed Git blob 均核验；18 个与 PR head 整文件相同，types-core 的相邻 base 上下文不同，新增 patch 在行号归一后相同。11 条 PR 普通评论有界捕获，未声称覆盖全部 review threads；部分历史 bot 内容仅捕获。公开证据包保留精确源码、许可、时间、hash 和这些阅读边界，217 个既有 source 对象逐条不变。

一手证据：[PR #190893](https://github.com/openclaw/openclaw/pull/190893)、[精确落地 commit](https://github.com/openclaw/openclaw/commit/2163664150dffac1d4cfed646fb2d50973ad9e3d)、[审阅清单](receipts/20261102T150351Z-openclaw-session-notice-review.json)、[源码及 MIT 许可清单](receipts/20261102T150351Z-openclaw-session-notice-source/manifest.json)。
