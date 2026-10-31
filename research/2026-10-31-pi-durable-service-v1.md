# H2：真实 Pi durable 入口在工作负载前失败

2026-10-31 10:26Z 的唯一冻结尝试仅启动一个 Node 进程，1.547 秒后 exit 1。
我们的适配器从 Chord 根模块解构 `BACKGROUND_CONTEXT`，实际常量仅由
`@earendil-works/chord/context` 导出；因此正确参数顺序的 `Harness.open`
收到 undefined context，尚未创建 conversation/task。不是 Pi 上游缺陷。

实际调用方为可选 `openService` → 官方 `pi-durable@1.4.0` Harness/Session/
task scheduler/原生 SQLite。预固定的负载为一个 Session 中两个逻辑会话、
六个原生任务与十二次准入调用；两个 active 槽位，当前权限版本校验、同事务
本地效应与 checkpoint、取消释放和两次真正进程终止/恢复，均须由完整轨迹验收。
90 秒套件、每进程 25 秒、128 MiB JS heap、采样 private 1 GiB、输出 10 MiB
及零重试在运行前冻结。没有性能对比或模型质量主张。

本轮实际准入/效应/强杀/重启均为零，所有工作负载验收未执行。独立只读副本
核验数据库 integrity ok 且相关记录全为零；原始 SQLite/WAL/SHM 及冻结源码
hash 未改变。两项纯单测和静态 API 审查没有覆盖真实导出边界。证据层级仅为
原生入口失败及其留存，不升级 H2 科学状态，也不证明完整服务性质。

后续只修正这一集成的 context 解析，在新版本验证真实导出契约并另行冻结同一
完整负载；本轮不修后重跑，不扩展孤立 observer。适配器可完全不启用，现有
SaveScope API 与原运行环境独立。可信主机授权/取消不是多租户鉴权，效应仅限
同一 SQLite 事务；active 有界不代表历史库存有界，亦无外部 exactly-once 保证。

[冻结协议、原始结果与复核](../results/pi-durable-service-v1/report.md)。
H1 原 5 GiB 资源门槛和已关闭前置项保持，未加载模型或运行训练。
