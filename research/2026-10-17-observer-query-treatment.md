# 把内存查询与全局快照的成本分开

本轮交付可复现的 M/T/T/M 处理实验、冻结协议、独立收据审计器及原始结果。
四个全新 Pythia-14m 进程各做 16 次相同的稠密 AdamW 更新，共 4 次加载、64 次更新。
固定 seed 503、CPU float32、单线程；四组初始参数、数据顺序、完整 loss 轨迹与
最终参数哈希完全一致。本轮只执行这一套实际实验，没有调 seed、学习率或阈值重试。

M 和 T 都通过保留的实际 worker handle 查询当前内存和 native CPU；T 额外取得
全局 Toolhelp 进程快照。两组保持相同 20 ms 目标轮询、边界身份/角色检查、
provider 策略、确认屏障、存活检查、deadline 和清理要求。M 未执行的快照字段为
null，而非伪造为零成本。Toolhelp 全局数量不是活跃角色准入，也不证明连续隔离。

## 实际结果

| 顺序 | 训练循环 wall 秒 | 所选查询数 | 实现频率 Hz | 含边界最大间隔 ms | 更宽窗口父进程 CPU 秒 |
| --- | ---: | ---: | ---: | ---: | ---: |
| M1 | 3.080093 | 154 | 49.9985 | 20.520 | 0.000000 |
| T1 | 3.293826 | 134 | 40.6822 | 45.958 | 2.343750 |
| T2 | 3.199178 | 139 | 43.4487 | 47.768 | 2.328125 |
| M2 | 3.147344 | 157 | 49.8833 | 22.290 | 0.000000 |

两对 T/M 耗时比为 1.0693918121、1.0164691880，带符号差分别为
正 0.213733200、正 0.051834200 秒，几何均值 1.0425947568。
仅两对短运行，描述本次固定干预，不推断总体固定开销。此处没有 OFF 组，不能
估计全部观察成本。M 父进程 CPU 的零读数是 native 计时分辨率内的观察，不是零真实成本。

所选内存/CPU 查询累计 wall time 为 M1 0.0088484、T1 0.0066241、
T2 0.0070708、M2 0.0096377 秒；T 的额外快照累计为 2.230975/2.255356 秒。
所选合计查询 wall time 占循环约 0.2873%/67.9331%/70.7190%/0.3062%。
这些区间排除跨边界查询、共同轮询和控制工作，不等于 CPU 或全部观察成本。

四组 resident 采样最大值分别为 584409088/584388608/584081408/584531968 字节，
private 为 692174848/692142080/691970048/692056064 字节。
它们是整进程当前内存采样的下界，含模型、梯度、优化器及分配历史；
不代表独立 backward 峰值、完整峰值、硬上限、压缩节省或显存。

冻结前 37 个 producer mock 与 36 个 auditor synthetic/mutation 测试通过；
没有额外模型运行。实际收据 portable 8894/8894、本地文件检查 8898/8898 项通过，
独立复算另通过 97 项检查。176 份 worker 原始 JSON、20 个保留身份正常退出、
四个 Job 清空。四组都满足精确 worker 确认、父进程等待完成、两个存活检查、
finish 的时序。全部材料见[结果与收据](../results/observer-query-treatment/report.md)
及[冻结协议、执行与离线复核命令](../fixtures/observer-query-treatment/README.md)。

## 下一道研究门槛

本次支持将较轻的 retained-handle 查询作为下一次测量设计的候选。
下一项须单独预声明训练/forward/backward 阶段、基线分配及采样窗口、漏峰和
查询成本控制，再检验实际训练解释器的阶段内存。不能用这次整进程读数代替该实验。
此前六项科学成本/终评失败、无效历史 RSS、duty v1 四项拒绝和已通过的 v2 收据
均保留原样；H1 科学状态及 H3/H4 未执行状态不变。

## 本轮覆盖

实际开始 2026-10-17 14:56:21 UTC（北京时间 22:56:21）。七日扫描使用真实旧
snapshot；cutoff 14:57:05 UTC，请求至 15:01:32 UTC。7 人、10 仓库，无 scanner
错误，15 个端点可能截断。24h/72h/7d 当前主事件数 161/237/252；current-only
均 51、changed-shared 均 17、prior-only 49/55/55。窗口重叠不能相加；current-only
可能来自重采样，prior-only 不是删除，PR/issue updated 时间不是首次发布时间。
保留样本未发现新原创仓库；成功覆盖已核验后推进一次。

浏览器另读 Nathan 顶部可见 timeline 与 10 月 15 日离开 Kimi 的完整英文原帖。
原帖是旧消息，只宣布离开，未宣布下一雇主；Palo Alto/SF 位置也不是雇主证据。
顶部 timeline 非穷尽查询，另六人的个人 X/博客本轮未读，scanner 不覆盖整个 X。
没有研究者联系、社交发布或上游变更。

## 两项新合并的技术证据

FLA [1502](https://github.com/fla-org/flash-linear-attention/pull/1502) 于
14:24:49 UTC 合并为 44464f64，作者 yzhangcs，实际 parent 为此前 1506 的
68a2bdf。新模块分别承接 cache/generation，旧 utils 保留公共符号导出。
核验完整 104 路径元数据和 9 个核心完整源码对；其余 95 个文件未独立重建。
generation 输入准备方法与不支持 cache 的 class AST 保持一致；整个 generation
class 另改文档并移除单纯转发构造器，不能称整个 class 无变。
仅三条选定消费者路径做了去 imports AST 核对，“80 个消费者均无变化”仍是作者断言。
旧 module pickle、alias 及状态继续更新、五类状态 transfer 和空状态在源码测试中
有覆盖，但本轮未执行。作者微基准在更早 7db053ec 上报告 transfer
14.949→15.116 微秒、约慢 1.1%，没有端到端提速结论；CPU/GB200 测试也是作者自报。
当前 PR-head 的 H100/A2 workflow 虽成功，实际硬件测试被跳过；不能升级硬件资格。
这次合并是已见提案的新落地，不是 Nathan 的贡献或新算法发布。

Peter 的 OpenClaw
[175498](https://github.com/openclaw/openclaw/pull/175498) 在 14:49:48 UTC
合并为 271f240e（commit committer 时间为 14:49:47，分开记录）。
核心变化把 PostgreSQL 的缓存失效绑定到实际 mutation、当前 writer 的 pending
receipt 和实际事务状态；只读 handle 不能结算共享 anchor 上另一 writer 的写入。
多 statement 的尾部 SELECT 不能遮蔽前面的写入，空 commit 不发布修订；未知结果、
schema/raw 写入仍保守失效。31 路径元数据核验、10 个核心源码对精确重建，其余
21 个未重建。lexer、锁、rollback、只读误分类和复用测试是源码证据，未本地执行。

作者性能数据属于更早 02db95bb，不是最终 035edd37 或 landing 的实测。
traced 请求减少同时 full-window 请求/SQL 增加，两窗口重叠不可相加；作者的
4 倍 throughput 对照还有共享 host load 差异，不能归因于代码。精确 head CI
39038871417 的 attempt 1 为 57 成功/2 失败/24 跳过，attempt 2 为
59 成功/24 跳过，两者都保留。超时/继承失败的归因尚未读日志独立核验。
landed primary CI 的 1 成功/41 跳过也不代表重做了全部测试。
H2 下一门槛仍是实际持久效果、当前版本/归属、rollback/未知结果、锁及跨两次重启的
活性验证；本轮来源核验不构成这些执行结果。

本轮 57 份选定 GET 收据中 55 成功，2 份 OpenClaw archive 在收窄范围后主动取消，
部分内容未解析、未计入覆盖。FLA 两份完整 archive 仅检视选定路径。
来源代理 595 项、root 独立 869 项检查通过；完整元数据不等于所有文件完整内容或
所有历史 CI。来源事实、作者自报、CI 元数据、本项目推断和本地实测分别记录于
[来源证据](receipts/20261017T145621Z-reviewed-sources.json)、
[独立来源核验](receipts/20261017T145621Z-root-source-review.json)及
[扫描和浏览器覆盖](receipts/20261017T145621Z-coverage.json)。未执行上游代码或嵌入脚本，
未读取数值 artifact、job logs 或 legacy combined status contexts。
