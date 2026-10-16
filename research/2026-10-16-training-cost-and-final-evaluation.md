# 局部更新通过之后，完整训练仍没有收益

SaveScope 新增了一次独立冻结的自然文本训练成本基准：三组固定顺序，分别比较相同训练量与相同时间预算下的 dense 和保留 norm/attention 保存值的 INT8 backward。**六组预声明联合门槛全部失败；相同训练量下压缩慢5.4%–12.2%，十二个最终端点的留出 NLL 都高于初始模型。**这是当前小模型和训练设置的负结果，不能归因成“压缩导致全部质量回归”，因为 dense 也回归。

本轮还有一个必须公开的测量缺陷：父进程采样值约3.7MB，与真实训练进程自读的约560–590MiB不符。**父采样不能作为训练 RSS，实际训练进程的父监控内存上限未获验证。**[测量有效性补充](../results/activation-cost/measurement-validity.json)与原样报告一同发布；598项收据一致性检查通过不代表测量有效或研究成功。

## 全部配对结果

初始模型在统一终评集上的 NLL 为 **4.457542557**，越低越好。以下每对数字依次为 dense / INT8。每个相同训练量端点执行64步、8,192个目标位置；峰值为截至训练循环结束的 worker **自身** Windows进程生命周期 resident 高水位，单位MiB，含导入、模型加载、准备与初始hash，不是训练独占峰值或GPU显存。

| Seed | 循环秒数 dense / INT8 | 自读生命周期峰值MiB | 最终NLL dense / INT8 | 联合门槛 |
| --- | --- | --- | --- | --- |
| 503 | 11.899079 / 13.355544 | 559.613281 / 559.773438 | 4.574105818 / 4.546694003 | failed |
| 701 | 12.083676 / 12.855667 | 560.027344 / 559.750000 | 4.602038879 / 4.600431066 | failed |
| 907 | 11.838140 / 12.477783 | 559.433594 / 559.433594 | 4.587996807 / 4.600448988 | failed |

压缩三组均更慢。生命周期峰值仅seed701较低约0.277MiB，seed503较高约0.160MiB，seed907相同；这些单次小差异不支持一般内存收益。两组压缩终评优于 dense，一组较差，不能仅保留好看的两组。所有端点均差于初始模型。

相同时间组完成原子更新直到60秒。六个端点均在预声明60–61秒内，未触及4,096步上限，不能描述为严格相同耗时。不同步数也意味着不同训练量。

| Seed | 完成步数 dense / INT8 | 循环秒数 dense / INT8 | 最终NLL dense / INT8 | 时间控制 / 联合门槛 |
| --- | --- | --- | --- | --- |
| 503 | 322 / 299 | 60.029880 / 60.116162 | 5.642478772 / 5.634735636 | valid / failed |
| 701 | 322 / 300 | 60.140776 / 60.166576 | 5.636638254 / 5.656550504 | valid / failed |
| 907 | 322 / 301 | 60.188726 / 60.153958 | 5.594762564 / 5.597567298 | valid / failed |

压缩完成299/300/301步，dense均322步；只有seed503压缩NLL较低，另外两组较高，且全部回归初始模型。更少步数、不同历史、过拟合或固定设置都可能解释结果，不能提出单一因果归因。三组是共享文本上的固定顺序情景，不是统计独立重复；门槛是严格方向性筛查，没有显著性、等价容差或一般实用收益结论。

## 保存成本与父进程采样缺陷

主计时循环使用原生dense（无saved hook）和既有压缩器，覆盖实际forward、精确CE、backward、AdamW、必要有限输入扫描、scope进入/退出及逐步scalar记录/检查；不在主回调里放诊断计数器、时钟或NumPy参考。完成时先获取本进程OS峰值，再做最终有限检查、hash、保存checkpoint或评分。

另六个新进程从初始权重各运行两步，只测仪表化回调。每步19个outer保存值被压缩，13个实际LayerNorm与6个实际attention forward保存范围保持精确。outer非参数backing union为3,605,504→911,872字节，排除了参数存储，但它仍不是所有保存值或实际OS峰值。压缩outer打包回调8.2163–8.3946ms，取回1.4392–1.6567ms；它们含计数/计时开销，只覆盖初始两步，不能当长程平均开销或从主耗时扣除。实际压缩有限值扫描的成本被保留。

父进程用 `Popen.pid` 采样，冻结报告未记录 interpreter PID/父子关系。一次独立、无模型的标准库工程复现使用同一venv启动路径和16MiB分配，确认Popen启动器PID与真正interpreter PID不同：启动器RSS3,731,456字节，interpreter自读及按其PID查询均42,467,328字节。这支持venv redirector解释；它不能认证原运行的历史进程图。原始[工程代码](../results/activation-cost/diagnostics/check-launcher-identity.py)及[收据](../results/activation-cost/diagnostics/launcher-identity-check.json)保留，没有替换任何科学结果。

因此报告中的 `parent_sampling` 生命周期和训练区间RSS、private值以及基于它们的实际worker内存限制都不能验收；原先“采样下界”的标签不足以修复被测对象错误。timeout杀进程树的覆盖也未建立。worker `GetCurrentProcess` 自读的OS生命周期高水位是另一条路径，保留为有明确范围的观察；不能由此补造连续private峰值。下一次成本实验之前先修实际PID握手、同步parent/self内存一致性及后代退出/上限对照。**本轮不修改冻结程序、不重跑模型、不挑选替代数值。**

## 协议、终评与复现

[协议](../fixtures/activation-cost/protocol.json)于14:53:36.469217Z预声明；225项全仓库测试通过，最终26项纯标准库审计测试另行通过（与全套有重叠，不能相加）。[实现](../fixtures/activation-cost/implementation.json)于15:10:29.593796Z冻结，执行收据15:10:37.230665Z开始；总墙钟668.518894秒。最后一段训练的循环后内存边界收据时间为15:20:02.010799Z；全部12端点checkpoint完成并经过六个独立profile后，才释放终评。终评实际15:21:11.063127Z–15:21:45.177650Z，初始模型一次、12端点各一次，每次64块／4,096目标位置，没有中途看分、筛选、调参或第二次科学执行。这些是本地时间与hash收据，不是外部预注册或不可篡改证明。

模型固定EleutherAI/pythia-14m revision `cf967c0a9a04383db6f7b1108d86b2962634b4ac`，每个worker检查全部7资产。Windows10/i7-10700，Python3.12.14、Torch2.9.1+cpu，float32/eager/单线程/确定性/eval dropout0但开启梯度。AdamW lr1e-4、betas(.9,.999)、eps1e-8、weight_decay.01、foreach/fused关闭，无调度或裁剪。2,250个主训练更新和12个profile更新完成，76参数原生计数与末态有限检查通过；不是独立NumPy单步数值控制。没有CPU独占、频率或背景负载保证。

训练为《Alice's Adventures in Wonderland》前128块，终评为《Through the Looking-Glass》前64块，块长65token，前64预测后64；保留Gutenberg完整来源文本及版权/许可包装，MIT仅适用于原创工具。两本同作者/系列、固定小前缀、未知预训练重叠，只做完整块去重，不能当干净未见基准或广泛模型质量结论。公开字节在本机可读，这是一条过程上的终评边界，不是秘密测试集。

[完整收据与表格](../results/activation-cost/report.md)保留所有seed、逐步loss、最终逐块NLL、时间控制、原始错误采样摘要与失败门槛；[纯标准库审计器](../scripts/audit_activation_cost.py)检查598项hash/时间/运算/覆盖一致性。另34项冻结复核与[316项原始收据交叉检查](../results/activation-cost/postrun-independent-review.json)通过；采样运算正确仍不能挽救被测进程错误。未发布checkpoint/模型权重或含本机绝对路径的release原文，不能由其hash离线认证未公开字节；离线收据检查也不重算模型损失、OS峰值或证明实际隔离。CI只重验本轮工程与公开收据，未重跑Windows成本实验。[下载、执行与离线核验命令](../fixtures/activation-cost/README.md)。

## 判断与下一门槛

前两轮局部AdamW锚点门槛通过，并没有在这次完整成本/终评诊断里变成CPU实用收益；停止把该保存策略作为已证实的CPU优化宣传，也不再用同设置的seed/lr扫参挽救失败。下一轮若继续成本工作，先通过真实interpreter测量与资源控制工程门槛，再另行预声明不同数据和训练验收；真实GPU、完整backward/dispatch、learned routing/AttnRes仍未验证。SaveScope v0.1公共API仍是fresh-state审计工具。本项目可交付价值是复现反例、显式作用域及可审计成本边界。

本轮另有[整体绿色却含dispatch失败](2026-10-16-dispatch-log-boundaries.md)与[恢复容量／服务边界](2026-10-16-recovery-capacity-and-service-boundaries.md)源码信号，均不升级H2/H4运行状态，H3仍未执行。Nathan已知帖仍只证实离开Kimi，新雇主未核验；有界X读取不代表全站覆盖。未对研究者发送消息、评论、issue、PR或社交贴文。

| 固定项 | SHA256 |
| --- | --- |
| 协议 | `8908ca5362a51a1b0e2a9d27657b0b8e64ac5632fc695b30407331be5c1c87ed` |
| 实现冻结 | `e28fe5df090bcc86dae9e0151e3765f130d40a28499df5b0714be32f4b826de5` |
| stable结果 | `2cb0e663ac2d28fbda9864752a641d27e12e16262ef97832627358e04f9c508c` |
| observation | `850dc87cb9f6aa2f4240dcc63bdeaacdbaa8d57e3cdb1b3ef8fda4c4f32dbd45` |
| 报告文件 | `abfee40bcfc79bd5a4c98aa708a0611621db5635aae9d9a07fc16f1438a981c9` |
