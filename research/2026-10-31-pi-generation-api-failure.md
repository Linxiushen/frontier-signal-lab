# 实际 GenerationTask / tool 调用链：冻结验收失败

2026-10-31 20:18Z，单次H2原生套件把同一Pi/Chord1.4.0 runtime接到实际Conversation.submit→GenerationTask→Models→官方Faux provider→ToolTask→ToolExecutionApi.commit→终态回收。两个独立SQLite Session、每个两个conversation、容量各2，20项有界到达，三进程／两次强杀重开。预注册完整验收失败：本项目检查器误把动态`faux:<epoch>:<suffix>`标识写成固定`faux`。冻结源码、全部50份raw（1,630,434字节）保持，无重试／模型加载，不将错误归于上游。

独立副本数据库／轨迹事后观察到14准入／6过载、14generation和14tool终态（20completed／8aborted）、14fixture提供方调用、10项本地效应各count1和4次同tool-ID恢复。仅为诊断在内存适配一个断言后的回放不追认冻结通过。有限5.25秒套件的效应／吞吐／延迟和采样资源为描述性观察，非收益、模型质量或生产容量证据；完整指标和原始失败见[报告](../results/pi-generation/report.md)。

调用方的具体阻塞是提供方API身份契约；下一轮须在同一完整调用链另版预注册默认动态与显式固定API控制，再冻结完整负载／当前权限／取消／两次重启，不扩展孤立observer。host预留、native提交与host-ID持久化三次独立提交之间的crash gap暂不支持；只在持久化tool意图／效应之后注入崩溃。可信host权限、本地同库效应和显式reap界限仍适用，不证明tenant认证或外部exactly-once。旧失败与已接受自定义任务切片保留；H1原5GiB门槛未满足，H1/H3/H4无变化。
