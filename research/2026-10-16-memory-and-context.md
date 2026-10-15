# 残差 bank 的真实 CPU 成本与上下文兼容性

本轮新增并执行 **1 项实验**：预打包合成 residual bank 的独立进程内存/耗时测量。研究重点进一步落到总计算成本、可验证状态与既有实现的兼容性；这只是本项目根据公开证据选择的方向，不是研究者未公开的计划。

## H1：完整反量化与分块计算的实测成本

配置为 depth128/256、256 tokens、dim256、seed7、共享随机 query、float32；每种方法每个形状启动3个新进程，共18次。两种形状的 dense bank 分别为32/64 MiB。int8 worker只加载packed/scales/query，生成与量化发生在父进程并单独计时。默认tile-depth16，分块算法两次扫描，重复计算RMSNorm/logits，并用float64累加。

| Depth | 方法 | 进程峰值中位数 MiB | operator中位数 ms |
| ---: | --- | ---: | ---: |
| 128 | dense_float32 | 97.08 | 38.74 |
| 128 | int8_full_dequantize | 105.01 | 64.27 |
| 128 | int8_tiled | 50.02 | 157.15 |
| 256 | dense_float32 | 161.30 | 76.10 |
| 256 | int8_full_dequantize | 177.44 | 128.11 |
| 256 | int8_tiled | 58.17 | 246.91 |

在最大形状，本次完整反量化峰值为177.44 MiB，dense为161.30 MiB；int8持久数据更小仍未带来更低进程峰值。分块峰值为58.17 MiB，耗时为dense的3.24倍。这是本配置下的成本取舍，保留了完整反量化未节省峰值及分块变慢的结果。

所有数值核验通过；tiled相对完整量化参考的最大relative L2为 **1.21e-07**，逐元素门槛rtol=1e-4、atol=1e-5。量化相对dense的误差另列在原始JSON。重复进程是成本测量重复，不是多个独立训练seed，也不是模型质量评测。

这些峰值由Windows GetProcessMemoryInfo读取，包含解释器、NumPy、输入、临时数组、分配器及输出落盘前的阶段。Linux使用当前exec的procfs VmHWM/VmRSS，避免继承的ru_maxrss历史峰值污染；fallback会明确标注。两个阶段high-water的差不等于operator独占峰值。耗时不含生成/量化/读盘/写盘，这些成本在[原始结果](../results/attnres-memory/probe.json)中分开记录。

代码、输出、配置、数值证据和可变观测均有hash；[完整报告](../results/attnres-memory/report.md)保留每个子进程的阶段内存、耗时及限制。下一门槛仍是真实activation、等token/等时间训练、每步打包/保留与反向成本、GPU实测；本实验不能外推为显存收益或新架构优势。

FLA [1414](https://github.com/fla-org/flash-linear-attention/pull/1414) / [1416](https://github.com/fla-org/flash-linear-attention/pull/1416) 是ZenAlexa恢复的旧未合并提案，分别承接1313/1301，新PR号不等于新算法。前者修复indexed state容量与写入边界，可能需要更多state容量；后者只移除dense输出的初始化写入，保留packed清零与caller buffer语义，不减少输出张量字节。作者H200测试与速度主张未在本地核验，也不归因Nathan。

## H2：验证已经合并的兼容性实现

pi [9113094](https://github.com/earendil-works/pi/commit/911309429175254550837167baee245d5f9dbcb6)于17:38:33 UTC合并，由davidbrai提交并合并。切换provider/API/model时丢弃其他模型thinking，保留普通文本及tool calls/results；同模型保留签名/脱敏块；已读回归测试覆盖模型交替与thinking保留/丢弃。OpenClaw [9fe4372](https://github.com/openclaw/openclaw/commit/9fe4372390be59f5d55c4e9e5c3701cf98661229)于18:25:09 UTC提交、18:25:10合并，作者/合并者RomneyDa：只对精确typed turn/start rejection（-32600与thread-not-found）恢复原有thread并重试一次，保持binding与权限边界；不确定传输错误等继续显式失败。两者仅核读源码/测试，没有在本地执行，也不因为属于关注仓库就归给Mario或Peter。

本项目据此收紧H2：检验模型身份、原thread、权限及不确定错误边界，同时独立统计持久化工作进度。真实旧态路径已有更具体方案：官方脚本由发布版Gateway写SQLite，模型后端可以是官方确定性WebSocket fixture；但原封不动seed硬限定core/codex **2026.9.4**。10.3需要明确适配，不能只改版本标签。本轮定位了真实Doctor维护锁、数据库lease、backup及exact-row写入路径，尚未安装或执行该升级流程。

## H4：作者E2E主张与可复核数据分开

verifiers [PR2866](https://github.com/PrimeIntellect-ai/verifiers/pull/2866) head仍为f144485，PR更新时间16:45:21 UTC。本轮首次观察到作者追加的150个此前全失败live-service任务、每任务2rollouts的汇总：88% rollout通过、147/150任务至少成功一次，以及176/190与15/31两个运行方式分组。选择条件、任务级成功与rollout级成功不能混用；分组对应关系也未完整给出。

已读正文、1条issue comment、3条reviews、4条inline comments（这些端点无下一页），以及同head的CI工件元数据。列出17个integration-results工件，固定workflow配置上传行为矩阵的pytest XML；未据此确认150任务E2E原始结果。未下载工件内容，也未找到公开逐任务清单、准确模型/harness SHA、seed、完整baseline与逐rollout轨迹。结论是这些已读来源尚不足以独立复核该汇总，不是断言其他地方不存在数据。Windows当前缺少完整依赖和可用Linux清理环境；本轮未执行评分harness或另造关闭回调替身。

## 覆盖与复现

GitHub有界扫描实际18:30:41–18:35:35 UTC（北京时间10月16日02:30–02:35），事件截止18:30:41.627749 UTC。对上一真实快照与已见键去重，75个顶层事件首次采到或更新时间变化；没有新增七人原创个人仓库或profile字段变化。

| 窗口 | commits | issues | PR | discussions |
| --- | ---: | ---: | ---: | ---: |
| 24h | 57 | 27 | 76 | 1 |
| 72h | 88 | 27 | 94 | 5 |
| 7d | 117 | 27 | 94 | 5 |

扫描请求无失败；活跃仓库首页/评论采样仍有截断，定向源码另记请求时段。11个官网/博客/RSS响应与上轮字节相同。已知X离职帖重试成功、内容未变，仍未宣布新雇主；支持浏览器读时间线失败，未读新帖仍未知。入职不是方向证据。

本地一键复现通过70项测试及五个实验；本轮新增实验只计CPU memory probe，其他四项是回归重跑。运行`python scripts/reproduce.py`，或只运行`python experiments/attnres_memory_probe.py --output results/attnres-memory`。时间/内存允许随系统变化，不设胜出阈值。选定来源、精确hash、请求范围和公开许可状态见[证据快照](../reports/2026-10-16-memory-and-context/evidence.json)。
