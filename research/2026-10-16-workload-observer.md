# Torch 工作负载与原生子进程观察器：六例工程验收

固定六例单次真实验收全部通过，耗时27.545秒。四个工作负载实例各完成一次CPU Torch前向、反向和SGD更新；五个握手后的解释器及其五个原生`cmd.exe`子进程得到身份核验。另一个握手前退出控制明确不提供实际解释器身份。原始回执、预声明协议、冻结实现与离线审计均公开；没有重试、调阈值、预训练模型运行或历史科学实验重跑。

| 固定情形 | 实际结果 |
| --- | --- |
| 32 MiB健康分配 | 正常退出；resident增加32 MiB，private增加约32.06 MiB |
| 64 MiB健康对照，无阈值终止 | 正常退出；resident增加约64.004 MiB，private增加约64.125 MiB |
| 计算中的1.5秒超时 | 实际忙态区间1.515秒；73个样本、原生进程CPU增量3.000秒；采样最大间隙22.29毫秒 |
| 导入后private基线加48 MiB阈值，触碰64 MiB | 在一次忙态矩阵乘后请求整job终止；从allocated self-before到终止返回147.743毫秒 |
| 握手前退出37 | 精确退出码37、无握手、job为空；不以launcher冒充实际解释器 |
| 注入缺失模块／退出38 | 已认证的工作进程发生指定`ModuleNotFoundError`，未导入Torch／更新优化器，launcher和解释器均退出38，清理完成 |

协议先于实现冻结，冻结先于真实执行。新增代码复用[既有冻结观察器](2026-10-16-process-observer.md)，没有修改其源码、测试、协议或旧结果。先以suspended launcher分配非breakaway、kill-on-close的Windows Job，再resume；握手使用nonce、保留句柄、PID／创建时间、Toolhelp父链和实时job membership。五个握手实例的launcher与实际解释器PID全部不同。

解释器通过认证后才允许创建原生子进程并开启site／Torch导入。原生子进程以固定argv直接启动`cmd.exe`，使用匿名stdin pipe、DEVNULL输出、`shell=False`、`close_fds=True`与隐藏窗口标志。父进程核对它的PID／创建时间、真实image路径与冻结文件hash、直接父进程和job归属。它没有自带nonce回执，证据来自已认证工作进程的启动记录与父进程OS核验。健康路径写入非空一行后正常关闭；整job终止时pipe EOF也可能参与子进程退出，因此不声称每个子进程的唯一死亡原因。

握手中的`runtime_executable`文件hash来自工作进程的`sys.executable`路径，本次仍指向venv launcher；它不是实际工作进程的OS image查询。实际worker的PID／创建时间／句柄与内存读取已按合同核验，但base interpreter文件hash只作为安装元数据保存，没有成为另一道预冻结image门槛。原生`cmd.exe`另有OS image查询和冻结hash核验，两个范围不能混同。

Torch固定为2.9.1+cpu，CPU float32、1024方阵、常量输入和参数，不使用RNG或预训练数据。单次SGD为lr0.001、momentum0；损失／梯度／更新后参数有限且参数发生变化。之后的忙态仅在`no_grad`内复用输出buffer做矩阵乘，不追加backward或optimizer step。Torch实际设置为intra/inter各2；四例的OS原生线程计数均为导入前4、操作前后10。这些计数不是“恰好两个OS线程”的证据，也没有测量父采样器开销。

八组导入与更新后的持有状态以self-before／parent／self-after同步比对resident与private，最大绝对差4096字节。手动触碰payload最多64 MiB，Torch／runtime内存另外存在；阈值按导入和一次更新后的基线计算。64 MiB健康对照防止“全部杀掉”也通过验收。忙态采样最大间隙均低于预声明0.5秒，终止前再次核对解释器与原生子进程仍活着、仍属于job；六例的全部保留句柄退出且job active count为0。

27项生产者纯mock测试及15项独立合成／篡改审计器测试通过。冻结前的另一位本地代理发现整体平移cleanup时钟仍可通过的漏洞，修复后补了事件跨度与case wall的一致性检查，并保留发现与复核记录。这些本地代理审查不是第三方或另一台机器复现。真实回执离线检查9,316项通过，包含本机launcher／cmd文件重哈希；无这两个Windows文件的可移植CI审计会明确省略两项，即9,314项，不执行Torch或子进程。

通过范围限于这台Windows主机上的受控合作进程。采样阈值允许越界，不能当作硬上限、任意后代内存cap、连续峰值或生产隔离证明；有限采样也不能恢复[旧训练研究](2026-10-16-training-cost-and-final-evaluation.md)的无效parent RSS。既有六组成本／终评联合筛查失败、全部12个终评NLL回退、CPU INT8较慢的结论均不改变。SaveScope v0.1 API仍限fresh-state审计。

下一道门槛是在新版本实际预训练加载／训练harness内固定工作进程与线程、native／provider后代，加入真实导入失败、健康对照、活性和清理，并分别测量训练阶段内存与观察器开销。当前单步常量Torch接入不等于该门槛已通过，也不足以触发同设置seed／lr补救扫描或宣称压缩收益。

[完整结果与hash](../results/workload-observer/report.md) · [原始回执](../results/workload-observer/report.json) · [派生摘要](../results/workload-observer/summary.json) · [协议与复现命令](../fixtures/workload-observer/README.md) · [冻结实现](../fixtures/workload-observer/implementation.json) · [离线审计](../results/workload-observer/independent-audit.json) · [生产者独立审查](../results/workload-observer/code-review.json) · [审计器独立审查](../results/workload-observer/auditor-review.json)
