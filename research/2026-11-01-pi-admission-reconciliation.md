# 同一原生服务的准入协调

2026-11-01 00:18Z，H2另版冻结套件单次通过。服务以原始conversation/requestId及完整输入内容恢复host预留→原生提交→ID写回三个commit之间的状态，两个SQLite Session、三进程／两次强杀重开。26逻辑请求含20持久准入／6过载；20原生generation／tool／官方Faux调用，16本地效应各count1；8项恢复中2项首次创建原生提交，6项保留原生ID／工具ID，最终active0。保留当前权限、前后效应取消及原始动态／固定API精确绑定。六份副本数据库与完整保存字节独立核验通过。[完整结果](../results/pi-generation-admission/report.md)。

这是实际原生生命周期配合官方本地确定性fixture的有限工程证据，没有真实模型／HTTP、tenant认证、外部exactly-once、并发owner、生产或性能比较结论。host-only预留在重开后才首次生成，不能按到达阶段绑定API；该区别已预注册。before-reserve错误由调用方显式重试，不声称此前已有服务持久性。权限检查与提交仍为分开的commit，效应事务会重查权限；pending权限撤回／cancel标记后崩溃以及原生busy/提交错误/ID碰撞仍须同服务另行冻结验收，不能用纯分支测试升级。事后复核发现冻结auditor未拒绝效应日志taskId被替换、额外孤儿assistant两种内存突变；真实数据通过更严身份／数量检查。保留原冻结接受状态并增加单独事后补充，不追称预注册证据。原始失败与H1原5GiB、H3/H4保持。
