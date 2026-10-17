# 两步训练：逻辑状态不等于进程内存

本轮原创实验把训练过程分为八个操作区间，并在九个边界记录参数、梯度、AdamW 状态的逻辑库存和进程当前内存。**清除 56,270,848 字节逻辑梯度后，进程 private bytes 反增 147,456 字节，resident 只减 630,784 字节。** 因而不能把梯度引用减少当作同等的操作系统内存释放。

本轮实际开始于 2026-10-17 16:54:58 UTC（北京时间 10 月 18 日 00:54:58）；独立目录为 `reports/runs/20261017T165458Z`，滚动原件与本地状态不提交。协议在 17:10:36 UTC 预声明，17:15:31 冻结，17:15:45—17:16:00 仅执行一次，没有重试。固定 Pythia-14m revision、seed503、CPU float32/eager、线程1/1；一次加载、两个稠密 AdamW 更新，初始状态为空，不跑压缩、保留集或 checkpoint。

| 边界 | 梯度逻辑字节 | 两组 moment 逻辑字节 | step 字节 | parent 当前 private bytes |
| --- | ---: | ---: | ---: | ---: |
| B0 加载后 | 0 | 0 | 0 | 380121088 |
| B3 第一次 backward 后 | 56270848 | 0 | 0 | 511438848 |
| B4 第一次 step 及 housekeeping 后 | 56270848 | 112541696 | 304 | 688640000 |
| B5 第二次清梯度后 | 0 | 112541696 | 304 | 688787456 |
| B8 第二次 step 及 housekeeping 后 | 56270848 | 112541696 | 304 | 692207616 |

九次库存只保存 primitive metadata；storage 在每个快照内去重，不发布原始指针，也不跨时间合并。它不包括保存的激活、输入、Python/native arena 和分配器空闲容量。首次 step 创建76组状态，两个 moment 总计112,541,696逻辑字节，76个计数器占304字节；第二次计数为2。两步是有顺序的同一轨迹，不能当作独立复本推断“首步额外成本”。

父进程以20ms目标查询已认证的实际解释器handle。37份原始查询中只有22份完整落在操作区间，15份交叉区间记录全部保留。两次约0.30ms的zero_grad均无内部样本，最大值、采样率和查询占比为null，覆盖状态为unobserved。其余六个阶段也只有有限采样下界；时间间隔不能给出漏掉峰值的字节上界。12个held self/parent/self完整查询区间均通过原4MiB容差；阶段signed delta仍是整个进程的观测，不是隔离的backward/激活峰值。

八个操作墙钟合计0.428679秒，而首操作开始至进入B8的带观察跨度为1.987344秒；整个suite为15.589065秒。跨度包括中途等待、控制、文件及独立housekeeping，不能直接相减称总观察成本或无仪表吞吐。B4/B8位于单独计时的loss标量读取/删除之后；hold延长loss/graph寿命，库存和分配器历史也会影响后续读数。

62项执行前guarded mock/合成测试通过，实际执行不与这些测试混算。13次角色普查、26组控制/真实worker确认、最后确认→两次live检查→finish、原始非续期deadline，以及5个保留身份exit0/Job归零全部成立。公开110份worker原始JSON；冻结便携审计23,382项、可选本地文件审计23,386项、独立结果重算6,943项通过，彼此存在重叠，均不是模型质量测试数。1,240个历史实验文件逐字节保留。

[完整结果、八阶段表与hash](../results/training-phase-memory/report.md) · [无Torch收据复核命令](../fixtures/training-phase-memory/README.md) · [独立重算](../results/training-phase-memory/independent-outcome-summary.json)。当前工程一致性通过，全部阶段覆盖没有通过；不声称峰值捕获、压缩收益、GPU性能或生产证明。旧六项成本/终评失败、旧无效parent RSS和observer-duty v1时序拒绝不被修复或覆盖。

本轮扫描于 2026-10-17 16:56—17:00 UTC 实际执行，覆盖 7 人、10 仓库。24/72/168 小时窗口分别保留 166/240/253 条主记录；相对旧快照各有 57 条首次出现、10 条同事件变更。窗口重叠，不可相加；首次出现也可能来自重采样，旧记录消失不代表删除。15 个仓库端点存在截断，评论和讨论仅有限抽样，本轮未发现新增原创仓库。[覆盖收据](receipts/20261017T165458Z-coverage.json)记录这些边界。X 另由支持浏览器查看 Nathan 主页顶部和本人网站；可见最新原帖仍是 10 月 15 日离开 Kimi，未核验新雇主。网站无日期旧简介不能覆盖离职公告，其他六人的 X/博客本轮未读。

两条新证据都是既有提案的新合入，仓库公开且固定版本许可为 MIT。[FLA1505](https://github.com/fla-org/flash-linear-attention/pull/1505)由 **yzhangcs** 创作、合入，并非 Nathan；提案创建于 10 月 17 日 10:35，15:27:46 UTC 合入 `329b5342`，实际单亲为 `9a86daa2`。43 路径元数据完整，逐字节重建仅 **6/43**。共享 logits/shifted-label loss 接收 `num_items_in_batch`，以求和后除指定分母；自定义 criterion 复制后改 reduction。标签存在时投影全序列，MoM 保留旧参数别名和辅助损失。

作者测试和基准针对较早 `a6bdd67d`，全 40 调用点审计及其与最终 head 等价仍是自报。零 decoder 的三条 head 路径均变慢：unfused **+3.9%**、fused CE **+3.2%**、fused linear+CE **+5.8%**；广矩阵保留 4/5 个失败，packed-label 边界另属 1454。最终 head H100 的“成功”实际为 2 个检测成功、4 个 GPU/基准跳过；另一 run 取消，landing smoke/Ascend 仍待执行。CPU API 成功不能替代加速器数值与端到端训练验收。

[Verifiers2880](https://github.com/PrimeIntellect-ai/verifiers/pull/2880)作者、合入者是 **mikasenghaas**，并非 Will Brown；10 月 16 日提案于 17 日 14:57:42 UTC 合入 `6fa0c0a7`，实际单亲 `17e66c08`。完整 20 路径元数据中仅 **10/20** 重建。请求的 dialect 由 `PendingTurn` 持有至 commit，各 dialect 使用独立索引；新增节点同步已有索引，避免并发请求借用错误重放规则。pi/OpenCode/Kimi 的空白文本规则不同，`replay_view` 新参数也要求自定义 hook 迁移。head/landing Tests 各 21 个 job 成功，但 Kimi 的 `CI_MODEL_GAPS`、e2b/modal 缺密钥或 SDK 后的 deselect 均保留；未独立执行客户端或核验真实 wire。机器人摘要不算独立人工验证。

[来源收据](receipts/20261017T165458Z-reviewed-sources.json)通过 405 项证据检查，[独立审查](receipts/20261017T165458Z-root-source-review.json)通过 468 项，[CI 绑定](receipts/20261017T165458Z-selected-ci-binding.json)以 451 项检查将 7 个 run、59 个 job 逐项绑定保存的 HTTP。这些是来源核验数，不是模型测试数；剩余 47 个文件内容未重建，未下载 archive、导入或运行上游代码。

68 次来源 GET 中 67 次成功，另一次是新增 FLA 测试在父版本不存在的预期 404；错误 JSON 没有当作源码，重建使用空的缺失父文件。逐份保留请求时间、原始响应和内容 hash；不同 CI 查询属于分开的可变时间区间，并非原子快照，也未覆盖全部历史或旧式 status。语法解析和补丁一致只说明所读文本关系成立，不能证明梯度正确、故障因果、服务恢复或生产活性。作者所称既有 LAPACK/基线失败原因，以及相同树、实机分支数等归因，均没有升级为本项目实测。

来源只补充 H1/H2/H4 的可证伪门槛：训练需固定有效 token 分母、梯度与真实内存成本；重放需固定客户端/协议/评分版本，覆盖并发 prepare、逆序 commit、token/mask/reward 和恢复后分支身份。实际客户端、跳过矩阵和既有未满足门槛仍须验证。H4 保持 `planned_not_executed`、`experiment=null`，H3 不变；不据入职、声望或 CI 绿标推断私人研究计划或质量提升。

下一次只选择一个另行预声明的实验。在声称残差bank收益前，固定数据、有效token分母、observer成本和allocation-lifetime对照，测实际packing/retrieval与端到端成本，并封闭终评；如果终点是allocator/full peak，先明确适合该终点的观测方法。当前读数不能代替这些门槛，不作同seed/lr/阈值救援。
