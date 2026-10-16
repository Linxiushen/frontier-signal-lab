# 先确认测到了真正的训练进程

SaveScope 新增一个独立、纯标准库的 Windows 进程观察器及可复现验收。**五个固定场景全部通过；五次启动的 venv launcher 都不是实际解释器。**本轮实际验收只有一次，耗时5.819657秒，没有模型训练或科学重试。

父进程先以 suspended 创建启动器，放入不可 breakaway 的 JobObject 后再 resume。真实解释器和后代分别发出256-bit nonce、PID、父PID、创建FILETIME；父进程保留原生句柄，并按 OS 祖先链和 live job membership 核验。每个分配屏障执行 self-before→parent→self-after，对 resident 与 private 读数比较；10个屏障中最大差异8192字节，低于预声明4MiB。分配最大64MiB，均真实触碰页面。

| 场景 | 实际结果 |
|---|---|
| healthy32 | resident/private增加33,562,624／33,619,968字节，正常完成 |
| healthy64 | resident/private增加67,117,056／67,239,936字节，未误杀 |
| private_cap64 | actual-interpreter private基线+48MiB阈值被跨过，分配就绪到整Job终止调用返回0.051469秒 |
| timeout_descendant | 等待1.511455秒后整Job终止，全部保留进程对象退出 |
| job_close_descendant | 只关闭唯一Job句柄触发KILL_ON_JOB_CLOSE，全部保留进程对象退出；关闭后active count不可查询 |

四个可查询场景最终job active count均0；两组健康对照四个exit code均0。三个终止控制在行动前重新核验实际解释器与后代仍是live member，避免把早已自然退出算作终止成功。所有cleanup在0.020770–0.042034秒内完成，低于4秒上限。job-close控制中OS返回exit code0不代表正常执行完毕，应结合终止路径、行动前活性与退出句柄解释。

预声明16:43:12Z，实现冻结16:58:04.591760Z，实际运行16:58:13.646781Z–16:58:19.466673Z。另一个本地代理的源码审查抓出了并修复了close失败丢句柄、异常清理遗漏和终止前后代活性检查；这不是外部同行复现。38项模拟测试、265项当时全套测试通过；随后8项新收据核验测试独立通过，不能宣称执行过273项全套。离线审计完成1170项一致性核验，不调用Windows或模型。配置、全部PID/FILETIME/nonce、内存屏障、采样序列、退出码、时间和hash均在[公开结果](../results/process-observer/report.md)；[Windows复现与跨平台核验命令](../fixtures/process-observer/README.md)。

这通过的是**单机、受控、合作进程的独立工程门槛**。20ms轮询跨过private阈值后再终止，64MiB分配可先超出48MiB增量，不是kernel硬上限、连续private峰值、所有后代内存总量限制或生产隔离证明。没有把观察器接入训练harness，也没覆盖模型导入、多线程、真实provider/GPU、握手前崩溃或恶意逃逸。下一次成本研究之前，先在新版本工作负载中验证该接入及异常阳性／阴性控制，再单独冻结独立数据、训练与终评协议。

旧[自然文本训练实验](2026-10-16-training-cost-and-final-evaluation.md)原报告和无效RSS说明原样保留：六组联合门槛仍失败，旧parent RSS仍无效，旧真实worker cap仍未获验证。不能用这次工程通过修复历史或宣称CPU/GPU收益；SaveScopev0.1API仍是fresh-state审计。

本轮另核验了[A2所选数值执行日志](2026-10-16-a2-runtime-boundaries.md)，并把[恢复通知、停止顺序与launcher生命周期](2026-10-16-recovery-lifetime-contracts.md)细化为待执行的H2合同；H2完整harness和H3/H4运行状态不升级。主扫描7人10仓库，24/72/168小时保留167/221/239条有界主记录，各窗口43个current-only身份均在前次cutoff之后；分页/详情时差仍有盲区，不能当全量趋势。Nathan已知原帖仍只证实离开Kimi，没有新雇主公告。未发送研究者消息、评论、issue、PR或社交贴文。

| 固定项 | SHA256 |
|---|---|
| 协议 | `e4b77a96ab8aa1a2857b3156f485226791c877b923f847798eaad97e1f4b58a0` |
| 实现冻结 | `535c3e78a9abf53fd89452876796c1df8c39a5a8d2b21963f173f148fc03e954` |
| 原始验收报告 | `303da062f1f0a5eaf4560dc2e5c259ce24462e48af22fbb9dafc83635faf9f85` |
