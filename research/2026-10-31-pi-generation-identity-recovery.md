# 原生 GenerationTask / tool 身份与恢复切片

2026-10-31 22:13Z，另版冻结H2套件单次通过：同一Pi/Chord1.4.0实际Conversation.submit→GenerationTask→官方Faux→ToolTask→本地commit调用链，两个独立SQLite Session、容量各2。默认动态API按每个原始请求/阶段精确绑定，另一Session显式固定API；跨两次强杀重开保留14条assistant身份。14准入／6过载、14generation／14tool、10项本地效应各count1、4次同tool-ID恢复与权限／前后效应取消控制通过。独立六份副本数据库／全记录审计接受冻结断言；50份raw1,632,663字节完整保存，无重试或模型加载。

这是本机真实原生任务生命周期配合官方确定性fixture的工程证据。5.282秒套件、尾延迟、采样私有字节／OS工作集及观测成本仅为有限负载描述；含运行库认证的完整controller耗时另报。没有真实模型／HTTP、tenant认证、外部exactly-once、并发owner、GPU／多机或生产证明。[完整报告](../results/pi-generation-v2/report.md)。旧v1的固定API检查错误及其失败冻结不追认通过。

下一具体阻塞回到同服务的准入一致性：host预留、native提交、host-ID持久化是三个独立commit，当前崩溃只注入已持久化tool意图／效应之后。后续另版冻结须以稳定request identity、当前权限和原生恢复协调这些gap，在每个边界注入故障并保留两次重开、无孤儿／丢失／重复提交或效应、有界settlement与容量释放，不能扩展孤立observer。H1原5GiB门槛未满足；H1/H3/H4和全部历史失败保持。
