# 创建回执不能恢复旧权限：OpenClaw 的跨进程重放提案

2026-11-02，本轮读取 [OpenClaw PR #190862](https://github.com/openclaw/openclaw/pull/190862) 的不可变候选 `ad51a9143047d2ca47dd9b51a491f0befde1c7c6`。09:02 UTC 的公开 API 回执仍为 open、未合并；用于源码比较的共同祖先为 `4221b02f6e4a08ab0d73646f7e3eb4834f6c8914`。该提案创建于 04:19 UTC，已在此前 04:58 轮发现并保存元数据；本轮增加源码审查，不能称为 09:00 的新发布。公开作者账号为 `roboclaw-bot`，关联仓库进入 Peter Steinberger 的关注列表并不证明此改动由 Peter 创作。

实际调用方是 Gateway 的公开 `sessions.create`。原有进程内缓存随请求上下文或进程消失，重试可能再次分配会话、准备资源或派发初始轮次。候选新增 `idempotentDurableSessionCreate`：把 principal/device 命名空间与 idempotency key 生成操作摘要，对完整请求生成指纹，在调用原创建处理器前查询原生 history reader 中的创建回执。原调用方把 `creationOperation` 交给现有 lifecycle/native 与 worker replacement 路径；保存的 patch 显示原 replacement/reset writer 内加入回执提交。这里只审查有限路径，不宣称完整事务或迁移依赖闭包已验收。

新回执保存原 key、session ID、lifecycle revision、请求指纹以及原角色和 scopes。重放时，请求内容不同、角色改变或缺少原 scope 均拒绝；原条目丢失或 incarnation 改变也拒绝，包含 session ID 未变的 reset。保存的 scopes 只能增加限制。源码还在异步 sharing 授权之后、返回会话元数据之前重查当前 requester、sharing 与 lifecycle，并核对持有源仍匹配当前配置；进程内热缓存重放也接入此检查。回执有效不能恢复已撤销的权限。

重启重放返回 `creationReplayed: true`、`runStarted: false`，表示本次没有启动新轮次；该字段不重建原轮次是否已启动、完成或仍需恢复。保留期仍为原来的五分钟，incognito 不增加落盘回执。不能从有限保留的创建去重推导无限期去重、任意崩溃恢复或外部效应 exactly-once。

完整读取的新端到端测试使用确定性本地 Responses 端点：先等待首轮完成并断言 provider 调用数为 1，改名后让其他会话复用旧 label，再正常 stop/start Gateway、检查 PID 改变，重放后计数仍为 1，随后新轮次计数为 2，最后 reset 后拒绝旧回执。它在源码中设计的是首轮完成后的**一次有序重启**，没有证明在途请求强杀或两次强杀重开。另两个完整测试文件设计了 SQLite、条件启用 PostgreSQL 的 close/reopen 精确回执与竞争行回滚；处理器 patch 还加入授权返回后撤回 requester/membership 且不泄露元数据的断言。作者在正文报告进程、PostgreSQL 和迁移执行结果；本项目没有运行这些测试或独立复现作者结果。

本轮核对 67 路径清单，下载 27 份完整源码版本，实际完整阅读其中 12 路径的 17 份版本：5 个修改文件的前后配对、7 个新增文件；新增文件父版本的 7 个 404 与其 added 状态吻合。另 10 份版本仅保存，不计入完整阅读，其余关联文件只做有限 patch/context 阅读。没有本地原生调用、模型、云资源、数据库迁移、GPU 或性能实验。确切范围和字节 hash 见配套清单。

对本项目的启示是把操作内容指纹、回执身份、当前权限与工作完成状态分别验收。未来若接入这一实际调用方，应事前固定同 key 不同内容、删除/reset incarnation、响应前权限/取消变化、保留期与准入上限，以及提交和初始派发前后的两次强杀重启，分别记录有效工作和外部调用次数。本条只新增提案源码门槛；当前 H2 继续执行已有同服务的 native busy、submit error、request-ID 内容碰撞下一门槛，H2/H3/H4 的科学状态和既有对象保持不变。
