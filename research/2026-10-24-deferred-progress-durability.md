# Pi 流式进度：内存可见、存储提交与恢复边界

2026-10-24 UTC 源码核验。Pi 的 [6c2fd73b](https://github.com/earendil-works/pi/commit/6c2fd73b0c545a4034672cb60e34d53e035dd751) 由 `badlogic` 提交于 17:49:30Z，位于本轮上次雷达截止时间之后。相邻 parent 为 `d0aa218cb16c333c008f6aa3dcd670ac8b68383c`。这项变更使 H2 需要明确区分**进度被观察到**与**进度已进入存储事务**；本项目没有执行 Pi、上游测试、模型或恢复实验，H2 科学状态不升级。

核验材料为 GitHub 精确 commit 的完整 blob、提交 patch 与新增测试代码；根 LICENSE 为 MIT，版权 Mario Zechner。完整文件 hash 和实际阅读范围见[来源回执](receipts/20261024T182345Z-pi-deferred-progress.json)。保存了十个相邻已有文件对、两个新增测试和三个 landed 调用方／测试支持文件；阅读集中在下面列出的路径，没有完成全部三十个改动文件或后端／调度依赖闭包审查。

## 已核对的源码语义

默认提交仍先存储后返回。调用方可以指定 `persistence.kind = "deferred"`；只有所有写入均修改**已存在、conversation scope、history latest、fork initial、定义版本已存储**的文档时，事务才允许暂存。创建、迁移、退休、条目、任务状态等写入使事务回到立即存储路径。该条件来自 [Transaction.holdable](https://github.com/earendil-works/pi/blob/6c2fd73b0c545a4034672cb60e34d53e035dd751/packages/durable/src/session/transaction.ts#L752)，不是调用方单凭标记即可放宽的保证。

符合条件的更改立即被内存 tracker 采用，并进入 watch／内部 observer；其操作按文档 incarnation 折叠，tracker 被 pin。`subscribeCommits()` 此时没有发布，稍后才收到实际存储的 seq 和操作。下一次正常事务若取得该文档并且本身有写入，会把暂存操作放在自身操作之前，在同一存储批次提交；内部 observer 则只接收该次新增的操作，避免再次采用之前的内存进度。见 [Session 提交分支](https://github.com/earendil-works/pi/blob/6c2fd73b0c545a4034672cb60e34d53e035dd751/packages/durable/src/session/session.ts#L760)、[takeHeld](https://github.com/earendil-works/pi/blob/6c2fd73b0c545a4034672cb60e34d53e035dd751/packages/durable/src/session/transaction.ts#L804) 和 [publish](https://github.com/earendil-works/pi/blob/6c2fd73b0c545a4034672cb60e34d53e035dd751/packages/durable/src/session/session.ts#L957)。

**纯读事务不会触发落盘。** `#runCommit` 在 `writes.length === 0` 时提前返回，尚未进入 `takeHeld`。读取该文档并追加派生条目是触发条件；只读取、或只写不相关条目都不是。新增 session 测试分别写明并断言这三个控制，见[第296行起](https://github.com/earendil-works/pi/blob/6c2fd73b0c545a4034672cb60e34d53e035dd751/packages/durable/test/session-deferred-commits.test.ts#L296)。因此，不能把“执行过一次 read transaction”当作外部效应的持久化屏障，也不能从 watch／snapshot 取得的值直接产生持久化派生结果而省略事务内依赖读取。

其他存储触发包括 deadline、正常 close、卸载 tracker 与另一版本 token 引发重载。deadline 取各文档暂存提交的最早值；定时任务进入同一 mutation line 后，会批量存储全部 held 文档。默认窗口为 1000ms，`Infinity` 不设置定时器，等待其他触发。callback／settlement／checkpoint 在 Storage 前失败会保留 held 操作；Storage 失败则使 Session 失败，失败的 Session 不再 flush。见 [hold／store／timer](https://github.com/earendil-works/pi/blob/6c2fd73b0c545a4034672cb60e34d53e035dd751/packages/durable/src/session/session.ts#L845) 与 [spec §4.1](https://github.com/earendil-works/pi/blob/6c2fd73b0c545a4034672cb60e34d53e035dd751/packages/durable/docs/spec.md#L1776)。这不是硬性一秒丢失上限：spec 明确还存在 mutation line 与 I/O 延迟；进程被杀与正常 close 也不同。

实际原生接入点已经存在：[LiveDoc](https://github.com/earendil-works/pi/blob/6c2fd73b0c545a4034672cb60e34d53e035dd751/packages/durable/src/harness/live.ts#L120) 满足 latest／initial 条件，`PROGRESS_COMMIT` 为 deferred；[generation partial throttle](https://github.com/earendil-works/pi/blob/6c2fd73b0c545a4034672cb60e34d53e035dd751/packages/durable/src/harness/generation.ts#L465) 与 [tool progress](https://github.com/earendil-works/pi/blob/6c2fd73b0c545a4034672cb60e34d53e035dd751/packages/durable/src/harness/tool.ts#L506) 将其传入 runtime.commit。Harness 将 `settings.progress.persistWithinMs` 接到 Session 配置。因此这是实际流式输出路径的改变，本文没有把 API 提案当作运行结果。

## 测试代码与作者声明的范围

新增测试覆盖内存／存储发布差异、依赖读取、失败、deadline／Infinity、close、overflow／base 和 reopen；harness 测试包含首次落盘前丢失、存储 partial 转 aborted entry、重复模拟崩溃、safe／unsafe 工具恢复及派生审计条目。本文阅读了相关断言，**没有执行这些测试或验证其全套通过**。

这些测试中的 `ControlledStorage` [继承 MemoryStorage](https://github.com/earendil-works/pi/blob/6c2fd73b0c545a4034672cb60e34d53e035dd751/packages/durable/test/session-support.ts#L38)，`reopen()` 重置同一对象的 closed 标志；[crash helper](https://github.com/earendil-works/pi/blob/6c2fd73b0c545a4034672cb60e34d53e035dd751/packages/durable/test/harness-deferred-progress.test.ts#L57) 调用内部 fail 并等待 closed。多次这种 reopen 不等于两次 OS 进程重启、真实 SQLite crash consistency 或外部效应幂等。

提交说明报告 32 路 SQLite stream 下存储事务 562→99/s、磁盘 14.3→4.9MB/s、单核 CPU 29%→22%。这些仅是**作者报告**，本文未独立核验配置、完整成本、尾延迟、峰值资源或质量／恢复成功率，不能据此外推生产容量。README/spec 还明确说明：首次存储前崩溃可能没有 aborted entry，该次 usage 没有记录。它不代表提供方没有消耗资源。

## 回到 H2 实际调用链的下一项验收

实际调用方是多会话 Pi Durable 的 generation/tool progress，放大瓶颈是每次 partial 存储的事务／磁盘成本，以及可见进度与落盘的时间差。复用原生 `PROGRESS_COMMIT`、commit dependency 与 `subscribeCommits()`，回退点是显式 immediate；本文不另造持久化层，也没有开始实验。

下一次可运行切片须**另行预注册**精确包版本、真实持久化后端、多会话固定负载、并发／队列／时间／内存上限和接受阈值。至少包括：

- 对照 immediate 与 deferred；把 watch 可见、存储事务确认和外部效应确认分别记账。纯读与无关写入必须保留为不强制 flush 的控制，依赖读取加派生写入必须与所依赖值同批落盘。
- 在首次存储前、held 后、Storage admission／settlement、派生条目提交前后注入有界故障，跨两次**真实进程重启**独立核对数据库、条目和幂等效应。恢复后按当前权限重新授权，单测的模拟 fail 不代替这些控制。
- 测试有限窗口与 Infinity／堵塞 mutation line／存储失败。取消前写入、已准入写入、过载拒绝、释放槽位后的继续推进分别验收；deadline 不作为提供方操作已消失或系统已静默的证据。
- 同时报告成功／失败／未落盘／未记录 usage 的分母、有效任务吞吐、端到端和 p95/p99 延迟、持久化延迟、CPU／内存／存储流量及观测开销。丢失进度或 usage 的请求仍计入 attempted 成本；未取得提供方计费回执时保留未知。

退出条件是这个原生切片通过预定控制或保留具体失败，并返回同一集成问题；不扩展为独立诊断项目。H1 已关闭的实际 caller ledger／导入观察、六项联合失败及暂不支持的20秒启动不受本次源码信号改变。H3/H4 也没有新的执行证据。
