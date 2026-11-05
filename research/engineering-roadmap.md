# 面向规模化工程的研究路线

2026-10-21 用户方向更新：把研究尽可能贴合大规模工程实现。本文规定选题和后续交付，属于执行方向，**不是新实验结果或生产能力声明**。H1 的六个联合成本/终评失败、历史 parent RSS 无效，以及 H2–H4 尚未满足的门槛全部保留。

## 研究对象与交付

优化目标是：在明确质量、正确性、尾延迟与资源预算下，增加有效训练量或成功完成的任务量。每项工作先写清实际调用方、当前瓶颈、完整执行路径和可回退的集成点，再选择实验或修复。优先复用维护中的训练、推理、Agent 和评测框架；贡献位置可以是核心路径，也可以是影响该路径的 CPU 工具或 SDK。

| 假设 | 实际工程场景 | 下一项可交付实现 | 验收重点与当前边界 |
| --- | --- | --- | --- |
| H1：残差 bank / 激活压缩 | 真实训练循环中的显存压力与压缩开销；SaveScope 接入调用方已有 AdamW 状态 | 将已有 trace ledger 接入实际 native observer，统一线程事件与失败清理；随后在同一训练入口提供可开关的 dense/bank 对照 | 先验证调用/梯度/优化器状态语义和观测完整性，再预注册完整训练成本与封闭终评。现有单步诊断、CPU 字节差和局部计时不证明训练收益 |
| H2：版本化上下文与恢复 | 多会话、长时间运行的 Agent 服务，排队、取消、故障重启与持久化副作用 | 选定一个实际 runtime/适配器入口，串起请求身份、当前权限、持久化与恢复；验证跨进程两次重启 | 无越权、无重复已提交副作用、过载时有界拒绝/排队、释放槽位后继续推进。SQLite canary 和状态机测试尚未证明这些服务性质 |
| H3：封闭评估 | 可中断、可恢复的实验调度与候选选择 | 在实际 runner 中隔离 evaluator 和终评数据，保存预算、checkpoint 与版本；增加 evaluator 篡改拒绝控制 | 恢复不增加选择/终评次数；预算耗尽停止；评估代码或分母改变不能污染接受的分数。仍是未执行计划 |
| H4：评分一致性 | 异步/分布式 rollout、重试与恢复后的评分聚合 | 在真实 client→wire→消息/token/mask→score 路径绑定模型、tokenizer、环境、配置和请求版本 | 重排、重复回调、重试与并发 prepare/commit 后归属及分母一致；语义变化分叉或拒绝。实际 Pi/ACP/MCP 和服务静默门槛仍未满足 |

## 近期执行顺序

H2 按时间到达与双 Session（2026-10-31 18:13Z）单次冻结套件通过：同一适配器，每组两个独立原生 Harness/Session 和 SQLite、各两个 conversation；共六进程、四次强杀重开。36个负载请求在容量被控制任务占用时到达；直接拒绝组36次拒绝、0负载效应，重试组12次准入／24次背压、12项效应各count1、92次准入调用，pending最多4、实际最多7次尝试。两组各14项控制任务全部准入终态，权限拒绝／写前取消零效应，写后取消保留已提交效应；独立副本DB与轨迹／源码审计通过，53份原始文件1,277,022字节完整保留。队列单owner串行调用，重试开始年龄须小于200ms，不是异步完成期限；队列在崩溃前排空，历史仍增长。有限双Session自定义任务门槛关闭，下一步直接接同runtime实际GenerationTask／tool／provider边界，单独预注册完整负载、当前权限、取消与两次重启；无付费模型时可用本地提供方／传输fixture但明确其范围，不扩展observer前置项。一对固定顺序与不同接受集合不证明因果收益、通用容量、模型质量或生产性质；H1原5GiB、H3/H4及旧失败不变。[完整结果](../results/pi-durable-paced/report.md)。

H2有限突发负载（2026-10-31 16:11Z）一套4组冻结运行通过：复用原适配器，每组4个conversation/一个Session；12个进程、8次强杀重开。容量2每组准入6／拒绝6／完成4of10可提交目标，容量4准入12／拒绝0／完成10of10；均有1权限拒绝和1写前取消且无效应。同容量两种sink逻辑结果相同，报告成功分母、有效任务／完整arm时间、观测终态尾延迟、采样private／OS高水位及callback／flush成本。93原始文件1,156,630字节与独立副本DB审计保留；只是一次门控burst，不能声称通用性能、外部幂等或生产性质。固定burst门槛关闭，直接在同调用方预注册按时间到达、有界重试／背压、写前写后取消边界；独立Session及真正agent任务／提供方仍待接入，不增加observer前置项。旧结果和H1原5GiB门槛保持。[结果与完整边界](../results/pi-durable-load/report.md)。

H2 v3 固定原生切片（2026-10-31 14:04Z）另行冻结后一次通过：原v2适配器／worker，三个进程、两次强杀重启、六项终态任务，四项本地事务效应各count1，权限撤销／取消无效应，容量2且最终活动0。独立数据库副本和轨迹／源码审查通过；21份原始文件223,614字节保留。该自定义任务单机集成门槛关闭；下一步直接在同一原生适配器单独预注册有界到达负载和支持的效应／取消边界，并匹配成功率、有效吞吐、端到端／尾延迟、资源与观测成本，不扩展observer前置工具。当前只有可信host权限和本地SQLite事务，没有GenerationTask、真实提供方、独立租户、并发writer、外部exactly-once或生产验证；历史增长未有界。旧v1/v2失败和H1原5GiB门槛／既有负结果及H3/H4保留。[结果与支持边界](../results/pi-durable-service-v3/report.md)。

H2 原生切片 v2（2026-10-31 12:09Z）：另行冻结后实际完成三个进程、两次强杀和两次重新打开，冻结最终数据库验收因我们未按 Pi 原生 JSON 格式查询 document kind 而失败。事后副本见六终态任务、四项各 count1 的本地效应、十二次准入与最终 seq31 一致，仅保存观察，不能追认通过。v1/v2 源码与原始字节不变，零重试；单独 v3 完整控制器已修正查询并拒绝旧 freeze，六项原生 schema/旧冻结回归及保存副本端点核对通过，但没有新原生运行或验收。此准备项结束，后续轮次直接另行冻结同一 v2 producer/worker 与完整负载/资源门槛，不扩展孤立诊断。H2 完整服务性质及 H1 原5GiB门槛/关闭项/负结果保持。[原始失败与后续接口](../results/pi-durable-service-v2/report.md)。

H2 原生切片首次尝试（2026-10-31 10:26Z）：官方 Pi durable1.4.0 的可选适配器已固定两个 conversation/一个 Session、活动容量2、权限版本、事务内本地效应、取消及两次进程重启的完整负载。唯一冻结运行因我们从 Chord 根模块导入实际不存在的 context 常量而在 Harness.open 失败；1进程/0准入/0任务/0效应/0强杀/0重启，所有服务验收尚未执行，本轮不重试。原始数据库副本 integrity 与零记录核验仅保存失败，不能算恢复通过。下一版直接修正并验证 context 导出边界，再另行冻结同一完整负载，不扩展 observer；H2科学状态及H1原5GiB资源门槛/已关闭项保持。[失败与下一门槛](../results/pi-durable-service-v1/report.md)。

1. **先交付一个真实集成。** H1 最近的工程切口是已有 ledger→native observer 的调用桥接，沿用已经工作的实际进程入口。固定线程拓扑、事件身份/顺序、容量上限、错误传播和清理对照，检查接入前后行为与观测开销。ledger 的 flush 不等于 fsync，任意阻塞 sink 仍需明确支持边界。交付范围与退出条件在实现前冻结。
2. **让集成回答成本问题。** 在具备合适测量端点后，单独预注册 matched dense/bank 训练：相同模型/数据/初始优化器状态与质量目标，分别比较等 token 和等时间预算。计入 pack/retrieve、forward/backward、optimizer、数据读取、观测及可用时的通信成本；保留初次编译与稳定运行差异、所有失败和封闭终评。已有失败设置不做 seed/LR 救援。
3. **H2 聚焦一个可运行服务切片。** 冻结一个实际入口、持久化后端、效应边界和当前权限规则，先做单机多进程的取消、提交窗口故障、两次重启、容量耗尽与槽位释放。预写取消和已开始的写入/提供方操作分别验证，独立核对真实持久化效应与进程退出。外部模型服务不可用时明确标注本地提供方控制范围。
4. **H3/H4 跟随真实调用链。** 优先嵌入正在使用的 runner、rollout 或评分服务，把复现、预算、版本和恢复规则变成接口/回归控制；等核心链路稳定后再扩大验证范围。

下一轮先冻结并推进上述集成切口，普通准入上游修复继续推进。每轮至多一个 H1–H4 科学实验；实际模型训练仍受该限制。前置工具只在一个具体集成失败阻塞目标时单独立项，写明所解除的阻碍和结束条件。完成后返回原集成；连续受阻则缩小支持范围或记录阻塞，避免持续扩展独立测量工具。

最新集成边界（2026-10-21）：ledger→native v3 沿用未修改的 v2 producer/worker/admission/adapter/native/ledger，在运行前冻结修正后的审计 schema 和真实序列化/helper-console 回归夹具。四个真实 stdlib 用例与独立保存字节审计全部通过：32 次采样、38 条提交记录、十个保留进程退出、四个 Job 清空。**该前置项已关闭**，下一项直接回到 `experiments/training_observer_v3.py` 的 `sample` / `read_stage` / `run_case` 实际训练调用方，保持 launcher/native 身份区分、provider guard、确认屏障与清理。实际调用方冻结前不运行模型；不再另开 observer-only 前置工具。其后完整 dense/bank 训练成本、合适内存端点与封闭终评仍须单独预注册。V1/v2 冻结失败与全部科学负结果保留，本轮模型加载/更新与科学实验均为零。详见 [v3 集成证据与限制](../results/observed-job-v3/report.md)。

实际调用方最新尝试（2026-10-21 UTC／北京时间22日）：新增 `training_ledger_integration.py` 把 ledger 注入既有 pretrained caller 的 held/active native 查询路径，原 duty-v2 worker/provider/role/ack 保持不变。单次冻结尝试在等待 `postimport-ready.json` 的20秒期限停止，零模型加载/更新；仅完成实际解释器绑定、一次preimport采样与两次census。两条记录776字节、五个退出57347、Job清空；冻结验收仍拒绝，事后保存核验不算通过。下一步仍在该实际调用方内，另行预注册有界导入进度证据与原身份/provider/清理门槛，不盲目延长超时、不另开observer-only前置项。基础Python文件hash在冻结前变化且已重新固定，尚不能归因。详见[原始失败](../results/training-ledger/report.md)。H4同时把Verifiers新合并的weighted-NaN→unscored与replay拒绝纳入实际runner的版本/分母验收；只是源码证据，未本地运行。

实际调用方 v2（2026-10-21 22:05Z／北京时间22日）：同一pretrained调用链另行冻结七个有界导入标记，保持20秒导入/60秒用例期限和原provider/身份/确认/清理。两次CPU模型加载、16次dense更新完成；健康路径113次接受采样，故障路径2次提交采样后pretrain部分写入拒绝继续，合计118条66258字节与5字节不确定尾；十个退出、两个Job清空。**冻结审计仍拒绝**：旧完整raw清单未纳入新增七个进度文件。事后独立完整并集核验通过不能修复冻结验收；61个focused和983个full测试未覆盖该集成。下一步仍在同一调用方，另行冻结完整目录schema与缺失/未知文件控制；不扩展孤立observer、不增加超时、不重跑本版。V1旧超时原因未知，H1六项失败与成本/内存/封闭终评门槛不变。[完整证据](../results/training-ledger-v2/report.md)。

实际调用方 v3（2026-10-22 UTC／北京时间22日）：另行预冻结完整suite/case目录并集和真实v2完整目录回归，随后原v2 producer/worker不改动完成一次两用例CPU套件。冻结schema与1914条健康原payload检查通过；两次加载/16次dense更新，127次提交采样/130条73075字节，加故障5字节不确定尾；14个导入标记、十个退出、两个Job清空。部分写入在训练释放前拒绝后续查询。**ledger→实际训练调用方门槛关闭，不再扩展observer-only前置项。** 下一项直接在该实际调用方单独预注册matched dense/bank完整训练成本、合适native内存端点与封闭终评，保持既有负结果和不做seed/LR救援。993全套测试（912通过/81跳过）只验证本地/保存字节；本次单健康轨迹吞吐与采样max不证明质量、完整峰值或规模性能。V1超时原因未知、v2冻结失败原样保留。[v3完整证据](../results/training-ledger-v3/report.md)。

## 每项工程验证必须回答的问题

完整训练成本启动失败（2026-10-22 04:07Z／北京时间12:07）：已准备同一实际调用方的12个dense/INT8匹配训练用例、完整阶段/用例计时、checkpoint后置终评和实际解释器OS生命周期working-set峰值端点，但唯一冻结CLI调用在输出路径比较时抛出ValueError：本项目wrapper传相对路径，入口使用绝对ROOT。失败发生在创建输出目录、native Job、模型导入/加载之前；零训练用例、零更新、零终评，无成本/质量/内存结果，本轮不重跑。49个冻结源码与50个前版源码原样保留。新增独立入口对所有CLI路径resolve并要求新freeze固定其自身hash；真实parser加mocked runner回归只验证此边界，不算原生验收。**实际调用方ledger门槛继续关闭**；下一轮直接另行冻结修正入口和同一完整成本套件，不另开observer-only项目、不换seed/LR/阈值。终评仍复用既有公开LookingGlass数据，只提供流程封闭，不能称新泛化测试。[失败证据与支持边界](../results/native-training-cost/report.md)。

完整训练成本 v2（2026-10-22 06:02Z／北京时间14:02）：修正入口与真实parser→runner边界控制预先另行冻结；唯一套件通过路径检查并启动第一个dense seed503原生用例，但在原定20秒postimport期限停止。五个标记最后为Transformers-start，Torch-complete已保存；没有Transformers完成、子模块栈或worker异常回执，原因未知。零模型加载/更新/终评，另外11例未启动；五个退出57347、Job清空、两行776字节。180条保存核验不算冻结执行通过；9个focused／1002个full预冻结方法（81跳过）未验证导入能完成。**实际调用方ledger v3继续保持已接受／关闭**，完整成本仍受阻，不重复同一套件；若再推进，须先在同一调用方预注册一个有明确问题、资源上限和退出条件的有界导入失败观察／控制，完成后直接返回完整训练。不得盲目延时、另开observer-only项目或改seed/LR/阈值；旧负结果、生命周期working-set／采样private边界及复用公开终评数据限制保持。[失败证据](../results/native-training-cost-v2/report.md)。

同一调用方有界导入观察（2026-10-22 08:06Z／北京时间16:06）：一次15秒栈采集显示Transformers正在构建导入结构，随后仍触发原20秒期限。栈定位观察完成并关闭；没有模型加载/更新/终评，不再重复同一观察或扩展observer-only项目。具体源码仅在事后读盘固定hash，单栈不能证明根因或死锁。保持该本地20秒启动暂不支持，下一步须给出可验证的具体依赖/初始化修复或缩小支持范围，再直接返回完整训练预注册。51个本版源码与前版52/50个源码不变，186条保存核验、五个退出和空Job；旧失败与科学门槛保持。另已核验FLA1554两文件落地：八个safe-gate反向dot显式设置精度，提示大规模长上下文比较须绑定后端/版本/精度并检查gate参数梯度；这里只是源码证据，无本地GPU/数值/吞吐结论。[观察报告](../results/native-training-import-observation/report.md)与[一手源码核验](2026-10-22-import-boundary-and-safe-gate.md)。

具体初始化候选（2026-10-31）：历史 Transformers44253 的 scandir 枚举部分已回移到单独4.57.3副本，保留原过滤语义；三项stdlib回归及真实已安装模型树的完整导出结构相等检查通过。26,720文件副本仅一个源码不同，独立清单与关键字节审查通过；1008项基础测试927通过／81跳过，两次错误测试环境失败原样保留。**依赖准备结束，不再扩展前置工具。** 本轮可用磁盘低于原5GiB运行前门槛，完整训练未启动，启动修复尚未验收；满足原资源门槛后，直接另行冻结同一12用例与20秒导入期限，不重开已关闭观察或放宽阈值。[实现、来源与边界](2026-10-31-transformers-startup-backport.md)。

新增损失边界源码门槛（2026-10-22）：FLA1552落地四个scale/softcap之后的LSE尾部重掩码；仅load时mask可能被后续变换破坏。四份完整前后源码／AST和两项2x1025直接前向测试已核对，但没有本地加速器执行、完整loss/参数梯度或吞吐结论，测试也未强制每个后端分支。实际loss调用方须预固定非整齐词表／tile边界、后端版本和scale0／负scale／softcap，再验完整损失与input/weight/bias梯度后比较成本。本轮不重复启动或观察套件，科学实验为零；20秒本地启动仍不支持，既有失败与已关闭前置项保留。[源码核验与限制](2026-10-22-lse-tail-transform-order.md)。

在运行前确定下列内容；阈值来自调用方要求、基线与可用资源，不能在看到结果后调整。没有可信基线的指标先作为诊断，不能承诺收益。

| 项目 | 需要保存的内容 |
| --- | --- |
| 调用与负载 | 精确 base、入口/API、版本/许可、模型/数据修订、设备；实际 shape、长度分布、batch、并发、请求/任务分布，含长尾与过载样本 |
| 正确性与质量 | 独立参考或不变量、有效 token/任务分母、梯度/实际参数更新、封闭终评；区分数值误差与模型质量 |
| 完整成本 | 有效 tokens/s 或成功任务/s、端到端与排队耗时、p50/p95/p99 的样本量与估计方法、失败/重试率、观测成本；训练/推理采用适用指标，如 TTFT 和 token 间延迟 |
| 内存与扩展 | 区分逻辑库存、allocator allocated/reserved、进程 RSS/private 与实际设备峰值；记录采样空洞。适用时记录通信字节/时间、同步、负载不均与缓存生命周期 |
| 故障与恢复 | 超时、取消、部分写入、崩溃、重启、重复/乱序回调、陈旧权限、依赖不可用；有界队列、背压/拒绝、幂等效应和恢复用时 |
| 交付与运维 | 可复现配置/seed/轨迹/hash、安装与运行命令、结构化诊断、支持/不支持范围、开关/回退方式；错误不得静默改成成功 |

按可用资源预先冻结并发/长度/批量阶梯、总时间和内存上限，超过预算即停止并保留部分结果。吞吐必须同时报告质量或成功率、尾延迟和超时；失败或丢弃请求计入分母。容量结论只适用于实测负载与环境，费用外推需列明价格和利用率假设。

## 从本地结果走向规模验证

验证依次推进到：独立参考/回归 → 实际调用入口的单进程集成 → 单机多进程负载与故障 → 具备资源时的真实 GPU/多机路径 → 有明确环境授权后的受控服务验证。每个结果声明实际完成的层级、执行数量和未运行项；用 CPU 或 mock 能验证的正确性修复可以独立交付，GPU、分布式性能和生产结论需要对应环境的证据。

多机阶段重点检查 DDP/FSDP 或目标框架的分片/collective 语义、通信与计算重叠、rank 失败、checkpoint 一致性、异构版本及扩容后的背压。推理链路关注长上下文、KV/cache 生命周期、continuous batching 和取消后的资源释放；这些是按选定项目实际范围启用的验证项，尚无本项目实测。当前不购买 GPU/API，也不把扩大资源作为本轮完成条件。

## 上游贡献与进度判定

筛选时补充一句完整因果链：**哪个实际调用方 → 哪个规模放大的故障/成本 → 补丁改变什么 → 哪条实测可验证**。优先数值稳定性、变长/批处理、调度与背压、流式取消、缓存失效、恢复/幂等、评分/数据一致性及相应原生回归。具体准入、去重和发布仍按 [上游协议](../UPSTREAM_CONTRIBUTIONS.md)。

交付按已集成入口、独立复现、可维护组件、真实 PR 接受/反馈和可测运行结果记录。新闻、额外回执数量、孤立脚本或未验证分支不能代表规模化进展。研究来源和 H1–H4 的科学状态只随新证据改变。

新增实际runner评分策略门槛（2026-10-22）：Verifiers2949落地每轮token cap后拒绝下一模型调用，以及可选截断／超时跳过任务评分。空reward总和为0，必须通过scoring_skipped与正常0分、NaN→None失败区分；同一runner版本固定cap、resolved sampling和skip策略，保留attempted/scored/skipped/failed分母并验证shared/isolated、评分预算先耗尽及重试／恢复。十一份完整前后源码、patch与新增测试代码已读；未本地运行provider／wire／模型，不证明硬预算或吞吐收益，H4科学门槛不变。H1原20秒启动仍不支持，已关闭ledger／导入观察不重开。[源码依据与待验收路径](2026-10-22-rollout-cap-and-scoring-policy.md)。

版本边界补充（2026-10-22）：Verifiers2960引入独立于ok/errors的dropped，None省略reward但不自动drop，非有限reward值改为报错并删除UnscoredError；前述NaN约定仅属于旧固定版本。H4须接到实际训练准入，验证drop排除、shared回滚／isolated提交、rescore清除与两次恢复，记录attempted/scored/skipped/dropped/failed/admitted成员及交集，不能假定状态互斥或只看reward均值。十六份完整前后源码及四个新增单测函数已读；没有本地runner／trainer／模型验证，科学状态及H1关闭门槛不变。[源码与待验收调用链](2026-10-22-trace-drop-and-training-admission.md)。

新增H2持久化边界（2026-10-24）：Pi6c2fd73将原生generation／tool progress标为deferred，watch可先于Storage；subscribeCommits只发布实际存储操作。正常事务须读取held文档且有自身写入才触发依赖落盘，纯读／无关写入均不是屏障。默认1000ms还受mutation line与I/O延迟影响，Infinity无定时器；首次store前崩溃可能无aborted条目与usage记录。已读精确源码及相关测试断言，但其MemoryStorage fail／reopen不是两次OS重启。H2仍须在同一真实多会话runtime预注册当前权限、幂等效应、取消、准入背压和真实持久化重启，分别记账可见／存储／效应确认及丢失usage成本；未执行新实验，H1关闭项与既有失败保持。[源码与原生验收门槛](2026-10-24-deferred-progress-durability.md)。

H2实际GenerationTask/tool（2026-10-31 20:18Z）单次冻结验收失败：检查器误把官方动态Faux API身份固定为faux。实际三进程／两次重开与副本数据库观察单列，50份raw完整保留，无重试／模型加载，不追认通过。下一步直接同调用方另版固定提供方身份契约和完整负载／权限／取消／两次重启；host预留／native提交／host-ID持久化之间crash gap暂不支持。不扩展observer，不改变已接受自定义任务、旧失败、H1原5GiB及H3/H4。[完整失败与边界](../results/pi-generation/report.md)。

H2原生generation/tool v2（2026-10-31 22:13Z）另版冻结单次通过：两个SQLite Session、14generation／14tool、10本地效应各count1、两次重开与默认动态／显式固定API的原始请求身份精确绑定。此有限fixture原生生命周期门槛关闭；下一步直接同服务协调host预留／native提交／host-ID持久化三个commit gap，在每个边界故障注入并保持当前权限／取消／两次重启及有界settlement，无孤儿／丢失／重复提交或效应。当前只在持久化tool意图／效应后强杀，不证明任意崩溃／真实HTTP模型／tenant／外部exactly-once／生产。50份raw完整保留；旧v1失败及H1原5GiB、H3/H4不变。[完整结果](../results/pi-generation-v2/report.md)。

H2同服务准入协调（2026-11-01 00:18Z）一次另版冻结通过：两个SQLite Session、26请求／20持久准入／6过载，三个commit gap故障后两次进程重开协调8项预留，20generation／tool／Faux调用、16本地效应各count1、最终active0。六份副本完整记录独立核验；host-only请求在重开后首次生成，API按实际生成阶段精确绑定。只验证官方本地fixture原生生命周期；pending权限撤回／cancel标记崩溃、原生busy／提交错误／身份碰撞及并发owner、真实HTTP模型／外部效应仍未验收，下一步回同服务另行冻结，不扩展observer。旧失败与H1原5GiB、H3/H4保持。[完整报告](../results/pi-generation-admission/report.md)。

H2下一完整调用方（2026-11-01 02:02Z）已准备 pending 权限撤回与 durable cancel-mark-before-abort 的同服务两次重开负载；19 项 Python、7 项 Node／mock 方法与语法检查通过。18 请求／12 host 准入／8 native 输入／6 effect 是预注册目标，尚非结果；未建实施冻结，未执行 native 套件。初次可用451,641,344字节低于原1GiB门槛，保持原资源上限，满足后直接冻结／执行此调用方，不扩展观察器。[准备代码与边界](2026-11-01-pending-authority-cancellation.md)。

新源码边界：OpenClaw189106将不可变磁盘回执与当前claim／generation／权限分开，在cleanup之后以及accept／publication／release前重检；丢失／替换原资源须保留结果托管，不回退旧镜像。只核验落地的未启用前置实现和测试设计，未复现作者测试或真实磁盘恢复；后续外部效应接入须另验精确资源身份、取消／权限变化和恢复交接，不能从本地Faux或有效回执推导分布式权限／exactly-once。[源码与拟议验收](2026-11-01-repository-disk-authority.md)。

新增开放提案源码边界（2026-11-01 04:02Z）：Verifiers3037尝试接管仍存活的Prime VM／background job，而其在途模型请求强杀测试明确期待该轮上游调用两次。作者另列重放缓存过期分叉、不可接管的harness和无预算重启回退；VM／PID连续性不能证明外部调用恰好一次。后续真实外部runtime集成须分别计入当前权限／取消、资源托管与清理期限、重复调用及回退成本、恢复context与sampled／scored分母。这里只核验未合并源码／测试设计，不执行云资源，不改变H1–H4状态；当前先完成既有同服务pending权限／cancel-mark负载，原资源门槛保持。[源码与边界](2026-11-01-live-rollout-adoption.md)。

新增已落地源码边界（2026-11-01 06:07Z）：OpenClaw189263将显式当前磁盘快照接入已有capture／publication／Gateway materialization路径，推进189106的I/O实现缺口。回复丢失后的重试保留原始快照并补充不可变alias，Gateway绑定前检查源稳定性，部分暂存index或不可用history须拒绝导出。磁盘模式仍不可选；paused准备、最终durable Move／teardown、真实云端／模型／远端发布仍未验证。这里只核验13个完整版本及测试设计，不运行原生实验、不提升H2状态；当前先完成既有同服务pending权限／cancel-mark负载，原资源门槛保持，不增加observer前置工作。[源码与边界](2026-11-01-explicit-repository-disk-snapshots.md)。

新增已落地源码边界（2026-11-01 08:06Z）：OpenClaw189350把已绑定active disk的显式Gateway Move接入fresh capture、pending result、验证后的worktree／session绑定、原磁盘claim退休及原环境cleanup／reconcile调用链，推进此前final Move实现缺口。绑定前恢复重新捕获原盘，绑定后保留已绑定worktree并避免重新导入。磁盘模式仍不可选，paused准备仍开放。核验37路径清单中的15路径／29完整版本及1个新增文件父版本缺失；非完整依赖审计。作者测试的restart是同进程store／harness重建，provider删除／GitHub身份合成；未执行本地原生、测试、云端或模型。当前仍直接回到同服务pending权限／cancel-mark既有负载，原1GiB／5GiB门槛不变，不新增observer前置工作。[源码与限制](2026-11-01-repository-disk-gateway-custody.md)。

H2同服务pending权限／cancel-mark恢复（2026-11-02 03:03Z）一次另版冻结通过：两个SQLite Session、18请求／12准入／6过载；2项权限撤回与2项已取消host-only预留均未调用provider或创建native输入。8条真实Generation／Tool／官方本地Faux链、6本地效应各count1、12host与16native终态、三进程／两次强杀重开、最终active0。50原始文件1,496,032字节、六份隔离副本完整DB检查与独立源码／轨迹审查通过。该有限门槛关闭，下一步直接同调用方单独预注册真正native busy／submit错误／request-ID内容碰撞的身份、槽位处理、当前权限／取消及两次重开；不扩展observer。4.437s只含suite，外层依赖核验单调总时未保存，完整成本吞吐不可用；无对照性能、真实模型／HTTP／tenant／并发owner／外部exactly-once／生产结论。旧失败、H1原5GiB、H3/H4保持。[结果与边界](../results/pi-generation-cancellation/report.md)。


完整训练成本v3（2026-11-02 05:11Z）：满足原5GiB／8GiB门槛后，唯一冻结套件完成dense503的64次AdamW更新／8192targets；对应INT8加载后在train阶段解包失败，另外10例／全部终评未运行，无配对成本／质量结论、不重试。两例在原20秒内完成导入，但环境同时包括scandir副本与明确更新且认证的base Python，不能归因scandir。93文件58,889,795B完整保留，92metadata公开，checkpoint仅本地保留与公开hash；十退出／两Job清空。直接阻碍已定位到调用契约：producer返回13norm和6attention两个组，context要求扁平name/module对；原异常无栈，此解释属源码核验。另行命名v4仅展平并增加独立入口／真实context纯回归，12controls与1129项portable（1048通过／81跳过）通过，旧源码／冻结未改。准备退出条件已到；下一轮直接另行冻结同一12例，不再扩展observer／放宽超时／改seed或LR。旧科学失败、invalidRSS与H2–H4保持。[原始失败、成本边界及修复准备](../results/native-training-cost-scandir-v3/report.md)。


## 2026-11-02 matched native CPU training outcome

H1 native cost v4 (2026-11-02 09:16Z): one original12job suite completes12training loops/2130AdamWupdates/272640targets and12endpoint scores, but frozen acceptance FAILED on evaluator cleanup KeyError:censuses. Separate saved-data recomputation is negative0/6joint screens; all12NLLs above initial4.4575425573.671rawfiles759604672B unchanged,659metadata public,12checkpoints hash-only;62retained exits/13emptyJobs. Independent176checks verify saved negative outcome only. Separate v5exact2role cleanup fix passes pure differential/malformed/downstream controls, no freeze/native rerun. Do not rerun unchanged training solely for green software acceptance. Return to existing H2native busy/submit-error/content-collision gate; future H1needs scientific justification and separate protocol. Prior failures/invalidRSS/accepted ledger/H2-H4 preserved. CPU saved-activation INT8, reused public procedural evaluation; no learned-bank/GPU/production/causal benefit claim. See results/native-training-cost-scopes-v4/report.md.

Preserve this failed v4 freeze, all historical negative results and invalid parent RSS. All12training loops and endpoint scores exist, but original evaluator cleanup validation fails; supplemental saved-record comparisons are negative0/6 and every endpoint NLL exceeds initial. Do not repeat unchanged expensive H1 training solely to make software acceptance green. Separate v5 evaluator-role cleanup preparation is complete with pure differential/malformed controls; no new freeze or model execution. Return to the existing H2 same-runtime native busy/submit-error/request-ID-content-collision gate. A future H1 study needs separate scientific justification and preregistration of actual learned residual-bank architecture, matched complete training cost, appropriate retained-interpreter/GPU memory endpoints and closed evaluation; no seed/LR/threshold rescue or observer expansion. Actual-caller ledger v3 remains accepted/CLOSED. One-host CPU saved-activation INT8 and reused public procedural evaluation do not establish learned-bank quality, causal speed/observer-overhead, fresh generalization or GPU/distributed/production benefit.


H2 native busy/error/collision (2026-11-02 11:20Z): one separately frozen two-Session suite passes, 18arrivals/14host reservations/4overload,2nativebusy/2typeerrors/2changed-content IDreuses/4hostquarantines; 10Generation/Tool/official localFaux chains plus2writes,6local effects count1,14host/20native taskterminals, 3PIDs/2forcedkills/reopens and finalactive0. Host quarantine never adopts/automatically aborts foreign native work; fixture cleanup is conversation-wide after exact original identity checks. Suite5.000s, controller44.032s and completeCLI44.328s (including authentication) are separate observations. Finite gate CLOSED; next separately preregister independent durable effects/transport at this native tool boundary, current authority/cancel/idempotency and two reopens, no observer detour. Official deterministic localFaux/single trusted Windows owner; no real model/HTTP/tenant/concurrent-owner/externalexactlyonce/GPU/production or causal performance proof. Old H1negative/invalidRSS/5GiB and H3/H4 unchanged. [Result](../results/pi-generation-conflict/report.md).


H2 native scoped HTTP effect (2026-11-02 13:39Z): one separately frozen suite with two native Sessions passes. It records 16 arrivals, 12 host reservations, four overload refusals, 12 GenerationTask/ToolTask chains with official local Faux, eight separately persisted loopback HTTP effects (each count 1), 14 GETs and 14 POSTs. Six reservations recover; 12 host records and 24 native tasks reach terminal states, with final active count 0. Three native processes include two forced kills and reopens; three server processes include two graceful reopens. Lookup recovers committed receipts after cancellation. Native numeric IDs repeat across Sessions, so remote authority binds a stable service scope. While scheduling is paused, public task-abort calls mark the exact original pairs before conversation-wide abort can resume scheduling. The suite takes 7.172 s, the controller 35.828 s and the complete CLI 36.234 s; these are distinct scopes. All 95 raw files (2,072,017 bytes) and nine stopped SQL copies are retained. This finite gate is CLOSED. Next work must separately preregister current-authority/cancellation with concurrent callers in the same runtime, or integration into an actual runner. Evidence covers free loopback HTTP and deterministic Faux under one trusted owner. It does not establish real-model quality, tenant authentication, concurrent-owner correctness, general external exactly-once effects, GPU/production behavior or causal performance gains. H1 negative results, invalid RSS endpoint and original 5 GiB gate, and H3/H4 remain unchanged. OpenClaw #191090 is separate source/test-design evidence. [Result](../results/pi-generation-http/report.md).


H2 concurrent native HTTP admission (2026-11-02 17:21Z): one frozen suite completes three native processes, two forced kills/reopens and three loopback effect-server processes, but frozen acceptance FAILED with `KeyError('service')`. The auditor assumes a scope field on content-conflict records and reads it before filtering unrelated event types; initial pure tests and two static reviews missed both schema cases. All 95 raw files (2085625 bytes), failed frozen code and old serial accepted result remain unchanged. A separately named saved-only observer checks six three-caller rounds and28admission outcomes (12admit/6exactretry/6contentconflict/4overload),12Generation/Tool/Faux chains,eight independently persisted HTTP effects count1,14GET/14POST,six recovered reservations,12host/24native terminals and finalactive0. This is post-outcome observation, not acceptance. Suite7.172s/controller37.141s/fullCLI37.515s are separate costs. No real-model quality, multi-owner, arbitrary authority/cancel interleaving, tenant authentication, external exactly-once, GPU/production or causal performance claim. No retry or threshold change. Do not repeat this unchanged workload solely to green the auditor; next work needs a concrete actual-runner integration or independently justified authority/cancellation intervention with a separate protocol, retaining bounded admission and two native reopens. H1negative/invalidRSS/original5GiB and H3/H4 remain unchanged. [Failed result and separate saved observations](../results/pi-generation-concurrent-http/report.md).


H2 scoped-v2 native generation (2026-11-02 23:27Z): one separately frozen finite integration passes. Two native Sessions reuse keys with different payloads; scope binds the HTTP resource and durable identity. 18 arrivals yield 12 admissions / 6 overloads, 4 exact retries / 4 conflicts, 12 generation/tool pairs, 9 expected eligible effects (9/9 eligible; 9/12 admitted), 5 recoveries and 24 native terminal tasks across two forced native reopens; final active 0. Remote/host refusal and pre-cancel leave no effect; post-commit cancellation recovers the original receipt while remote permission remains false. All 94 raw files / 2,082,999 bytes and nine SQLite copies are retained. Suite 7.563 s / controller 38.625 s/complete CLI 39.062 s and 151/2434 ms terminal p50/p95 are descriptive scopes including fixed holds/restarts; sampled memory and HTTP body counts are qualified in the report. This finite gate is CLOSED. Next work requires a separately justified actual runner and concrete untested authority/cancellation/receipt boundary with preregistered admission/recovery limits; no observer detour or unchanged rerun. Official local Faux and one trusted owner establish no real-model, tenant, multi-owner, general exactly-once, GPU/production or causal performance claim. The prior concurrent freeze remains failed; H1/H3/H4 are unchanged. [Result and limits](../results/pi-scoped-generation/report.md).


- Native receipt recovery overlap (2026-11-03 03:36Z): one separately frozen actual public-reconcile suite passes,2Sessions/2concurrent recovery pairs,2forced native kills/reopens. Genuine late404/403 callbacks preserve6eligible count1receipts;8admissions/4overloads,2newnegative controls,16native terminal tasks/finalactive0. Independent stopped-SQL/raw review preserves167old sources/3782oldfixture-result files. Finite same-owner/localFaux/loopback gate CLOSED; no real-model, arbitrary-interleaving, multi-owner, GPU/production or performance conclusion. Old concurrent failure and H1/H3/H4 unchanged. [Result](../results/pi-receipt-recovery/report.md).


新增实际runner源码入口（2026-11-03）：Verifiers3047已落地`vf-run`，将typed config、有限taskset、实际`Env.run_slot`与episode落盘接到一个入口，现有integration fixture也采用它。active-attempt semaphore不限制全量预建Future、重试总预算或trace保留；取消等待与shielded append不是跨进程恢复或fsync保证。终端成功分母为episode，reward均值分母为全部trace，须另留scored/skipped/dropped/failed/admitted成员。紧随2610/3052已删除vf-eval/vf-replay CLI；短调用入口为vf-run，完整评测改指向prime-rl，Task.rescore仅保留库级文档指引，旧CLI依据保留为固定版本历史。未来H3/H4可据此提出实际调用方集成，但须先完整预注册固定任务/提供方、持久预算、版本、取消/恢复和资源边界；这里只核验源码/作者测试设计，零本地test/native/model/科学运行，不改变旧结果、H3/H4未满足门槛或重开H2。[完整源码依据与限制](2026-11-03-minimal-evaluation-runner.md)。


ReWY source review (2026-11-03): the new FLA RFC proposes a residual pullback for existing delta-rule backward, with a pinned public implementation and explicit original-backend rollback. Seven-to-three counts a local expanded WY graph; reported hardware gains are author measurements with separate low-level/operator/model and precision boundaries. Failed model trajectory diagnostics remain. This refines a possible cost mechanism, not residual-bank quality: no local code/model/scientific execution, no H1v4 rescue or H2-H4 gate change. [Review and proposed integration boundary](2026-11-03-residual-pullback-engineering-boundary.md).


Pi message threads source review (2026-11-03): newly landed11545 connects server-side continuation to the actual Anthropic transport and isolates cache-warming replays. Selected normalized prefix fingerprints, per-send retry/fallback and process-local cleanup require separate wire/store/score receipts. This supplies a concrete H4 caller; fake test design and source reading do not establish native/provider, restart, authority, reward or performance correctness. All scientific states and existing unmet gates remain unchanged. [Review and proposed integration boundary](2026-11-03-message-threads-and-evaluation-identity.md).

H3准备（2026-11-04）：已实现实际vf-run调用链的可选预算包装、评分版本检查、一次终评与两次重启控制器；7项stdlib回归通过。94包固定Linux环境及真实入口导入成功，仅关闭导入前置项。NullHarness真实脚本依赖缓存的Docker卷初始化在Python启动前因复制I/O错误退出125，之后daemon不可用且清理未核验。尚无freeze、原生episode/provider/score/model或科学实验；H3完整封闭评估/H4及H1/H2既有状态不变。下一步须先恢复资源/daemon健康，用显式volume-nocopy完成同一脚本lock，独立审查冻结后直接一次运行完整调用方，不扩展observer前置项。[实现与真实失败范围](2026-11-04-budgeted-native-evaluation-preparation.md)。


Pi MCP framing source review (2026-11-05): landed11791 from4November replaces repeated growing-prefix copy/scan with a fragment queue in actual StdioTransport/PipeTransport. Complete pinned source/test-design review only; author timings are unreplicated and cumulative copy is not peak memory. The pending-byte cap does not bound incoming/decoded/aggregate-reader allocations or supply backpressure, authority or recovery. No local tests/native/model/scientific work, new observer prerequisite or H1-H4 change; continue the same blocked actual evaluation runner when its existing resource gates are met. [Review and boundaries](2026-11-05-fragmented-mcp-framing.md).


H3 actual runner attempt (2026-11-05): one separately frozen native vf-run/NullHarness/EvalClient/Echo suite FAILED. Two entries yield one completed echoed score0; five HTTP arrivals include one accepted/four failed, and only one of two required forced kills occurs. Native SDK request retries expose our fixture's global-arrival identity defect; the initial504 cause remains unmeasured. No selection/final/second-reopen acceptance, no unchanged retry or rescue. All22raw files/69,737bytes retained; sampled memory is not peak, and failure-branch observer time/complete HTTP bodies are unavailable. Composite main94/script35 environment and all prior preparation failures remain explicit. Next intervention must correct reservation/content identity and native request/cold-start boundaries in this same caller before a separately frozen study. Full H3/H4 and H1/H2 historical gates remain unchanged. [Failed result and limits](../results/verifiers-budget-native-failed/report.md).


Native evaluation budget v2 (2026-11-05): one separately frozen suite passes its finite fixture gate in the actual runner. Three native episodes produced scores 0, 1 and 1 across two verified SIGKILL/reopen transitions. Four durable reservations end as two completed development entries, one burned allowance and one completed final entry. Immutable attempt/model/data binding replaces ordinal routing. Complete CLI time was 50.777 s; controller time was 48.850 s. The cgroup memory.peak endpoint was 501,383,168 bytes before teardown. No native HTTP failure or retry was injected; four fixture controls and seven ledger controls are separate evidence. Preserve the failed v1 freeze, its 22 raw files, earlier preparation failures and H1/H2 states. This finite gate is closed; full H3/H4 remain unmet. Evidence covers a local deterministic provider, with no real model, GPU, production, general exactly-once or performance-improvement claim. [Result and limits](../results/verifiers-budget-native-v2/report.md).
