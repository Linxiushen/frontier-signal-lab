# 训练集成在导入前失败：先核对完整进程树

本轮产出了一份冻结的真实训练集成代码和一次可审查的失败实验。它原计划在固定离线 Pythia-14m 上执行三次加载、共六步 dense AdamW 更新；实际四个已认证场景全部在 preimport 阶段发现两个未识别后代，按预声明规则终止。只有握手前准确 exit37 的对照通过。**实际模型加载0次、优化器更新0次**，不能说训练集成已经验证。

实际运行发生在2026-10-16 21:03:56–21:03:59Z，总耗时3.225秒。协议在20:51:52Z登记，代码、历史依赖、launcher、实际base Python和cmd哈希于21:03:39Z冻结。只运行一次，没有修改阈值、放行未知进程或重试。24项producer模拟测试、14项auditor合成测试和25项独立篡改检查先前通过，仍未预见这次实际环境的进程组成。

四份preimport快照均包含预期的launcher、实际解释器、cmd，以及一个launcher的额外子进程和一个cmd的额外子进程。快照保存PID、创建时间、父PID、Job归属和存活状态，但未保存这八个未知进程的OS image。不能把它们认定为conhost、Python辅助进程或provider，也不能从这个失败推出模型加载本身有问题。此时训练导入许可尚未发送，精确缺包exit38的注入也没有执行。

通过的局部证据是：四个实际解释器的OS image均经保留handle核对为冻结base Python，和venv launcher为不同PID；四个cmd另行核对；四组preimport内存前后夹测最大差4096字节。失败清理保留并等待未知进程在内的全部handle退出；五个场景合计21个handle，Job active均为0，最长清理0.021023秒。这些局部结果不验证训练内存、完整进程生命周期或生产隔离。

冻结成功auditor继续返回失败：本地451/465项、portable447/461项通过，两种模式均有14个失败检查。未执行的postimport/load/update/overhead/busy/cap门槛仍是未知。后来新增的失败收据审计仅固定和校验这个负结果，保留`experiment_acceptance_passed=false`；它不是事前成功判据，也不会把失败变成成功。

下一实验必须另行登记：先对每个观察到的后代记录OS image/hash、PID创建关系和Job归属，再决定可审查的窄身份规则，同时保留真正未知子进程的拒绝对照、健康退出和全部handle清理。不能直接按数量增加白名单。后续还需原定实际loader、线程、两步训练、阶段内存、忙循环期限、采样阈值和观察开销。H1的六组自然文本成本/终评联合失败、历史无效parent RSS、fresh-state AdamW误差和SaveScope v0.1边界均不变；H2/H3/H4执行状态也不升级。

[完整结果与原始轨迹](../results/training-observer/report.md) ·
[冻结配置与运行命令](../fixtures/training-observer/README.md) ·
[本轮公开源证据](2026-10-16-causal-prefix-and-worker-custody.md)
