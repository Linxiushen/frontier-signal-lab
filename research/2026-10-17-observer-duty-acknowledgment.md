# 先确认工作进程收到指令，再测观察器成本

本轮交付了新的观察器测量版本、冻结协议和一次真实训练的完整收据。
四个全新 Pythia-14m 工作进程按 OFF / ON / ON / OFF 顺序，各执行相同的
16 次稠密 AdamW 更新，共 4 次加载、64 次更新。固定 seed 503，四组的初始参数、
批次顺序、最终参数哈希与完整 loss 轨迹完全一致。

新版本完整通过冻结收据验收：portable 6185/6185 项，本地文件检查后为
6189/6189 项。这是有限运行的身份、指令、时间、采样和清理证据一致性验收，
不是模型质量、压缩收益或生产可靠性证明。

## 修复的是哪一个实际问题

上一版控制器发出最后一次 continue 后，没有等待 worker 的确认，就检查存活并
发出 finish。上一版的四项审计拒绝仍然保留。本轮单独冻结 v2，只增加确认屏障：
按原 nonce、实际 worker PID、完整指令内容与下一个指令序号接受确认，使用
原 case/suite deadline 和最长五秒的一次性等待，再检查两个保留进程的存活并
发出 finish。确认可以在父进程开始等待前到达，但不能早于指令，也不能晚于
等待完成。超时、错配或未来时间确认均禁止存活检查和 finish，并进入清理。

冻结前 33 个 producer mock 测试与 28 个独立审计 mutation 测试通过；这些不含
额外模型运行。17 个旧 producer 函数及 20 个旧 auditor 函数/类的 AST 保持一致，
训练内容、采样处理、阈值及角色/provider 策略均未调整。四组实际确认等待约
21.6–22.1 ms，均满足确认、等待完成、存活检查、finish 的先后顺序。
20 个保留身份正常退出，四个 Job 清空。

## 实际成本与解释范围

| 顺序 | 稠密训练循环耗时（秒） | 更宽观察窗口内父进程 CPU（秒） | 循环内完整查询数 |
| --- | ---: | ---: | ---: |
| OFF 1 | 3.053044 | 0.015625 | 未观测 |
| ON 1 | 3.175089 | 2.328125 | 147 |
| ON 2 | 3.202095 | 2.343750 | 142 |
| OFF 2 | 3.015668 | 0.000000 | 未观测 |

两对 ON/OFF wall time 比为 1.039975、1.061819，几何均值 1.050840。
只有两对短运行，不能将这个约 5.1% 的描述值推广为固定开销。ON 除了相同的
完成轮询，还查询实际训练解释器当前内存/native CPU，并取得全局 Toolhelp
进程快照。完整快照累计约 2.323/2.261 秒，内存/CPU 查询仅约
0.00685/0.00686 秒。所选查询 wall time 占训练循环 wall time 的
73.39%/70.82%，这是查询区间占比，不是 CPU 占比或总观察成本。
父进程 CPU 使用另一个更宽的 release-to-completion 窗口。

目标间隔 20 ms，实际所选频率为 46.30/44.35 Hz，包含边界的最大间隔为
47.25/44.31 ms。ON 采样的 resident 最大值为 584208384/584470528 字节，
private 最大值为 691773440/692207616 字节。它们是整个进程当前内存的采样
下界，含模型、优化器、梯度和分配历史；OFF 为 null，表示未知。
不把这些读数称为独立 backward 峰值、内存节省、硬上限或显存。

见[完整结果和原始收据](../results/observer-duty-v2/report.md)、
[冻结协议与复核命令](../fixtures/observer-duty-v2/README.md)。
下一项工程检验应在单独预注册中分离 retained-handle 内存查询与全局进程快照的
处理成本，同时保留原边界身份、liveness、deadline、清理和四组轨迹一致性要求。
未证明活跃期间全局 count 是角色准入；不能以删掉快照为由声称连续子进程隔离。
本轮不再运行新的处理组，也不调整 seed、学习率或失败阈值。

此前六组科学成本/终评失败、无效历史 RSS、上一版四项时序拒绝和 H3/H4 未执行
状态均保持不变。新运行不修复旧收据，也未测试压缩训练、GPU 或模型质量。

## 覆盖与时间

本轮实际开始于 2026-10-17 12:49:22 UTC。GitHub cutoff 为 12:50:01 UTC，
请求持续至 12:54:21 UTC；7 人、10 仓库，无 scanner 错误，15 个端点可能截断。
24h/72h/7d 当前主事件数为 163/243/257，current-only 均为 48，
changed-shared 均为 15，prior-only 均为 54。窗口重叠不可相加；PR/issue 的
updated 时间只代表活动，current-only 可能来自重采样，prior-only 不代表删除。
保留样本未发现新原创仓库。

浏览器另读了 Nathan 10 月 15 日离开 Kimi 的英文原帖，未宣布新雇主；原帖是
旧消息，不是本轮新发布。可见作者回复的自动翻译提到湾区，没有雇主名称。
本轮未重读个人 timeline，另外六人的个人 X/博客未读；scanner 不覆盖整个 X。
本轮没有发送研究者消息、评论、issue、PR 或社交帖子。

## 两项新合并的技术证据

FLA [1506](https://github.com/fla-org/flash-linear-attention/pull/1506) 于
11:27:40 UTC 合并。原始贡献来自 aniruddhaadak80，保留在 eeb043cd；
yzhangcs 的第二个对齐 commit 为 68a2bdf，并非 Nathan 的贡献。
共享生成 mixin 区分 sequence-length 与旧 cache-position 协议，避免把已切片
prompt 再缩成一个 token 或在 decode 重用旧 embedding。六个最终文件、两个
原始贡献文件及完整两 commit 聚合补丁都精确重建。源码事实不能代替实际
生成/梯度验证；作者报告的多版本 CPU、GB200 及微秒计时尚未复现。
作者披露显式完整 suffix 路径 2.460→13.378 微秒的成本增加：旧路径忽略了参数，
所以不能把语义不同的两条路径当等价性能对照。H100 workflow 的运行测试跳过，
A2 尚未完成；历史 checklist/title 失败也保留。下一验证需固定版本、实际 token、
cache 长度、首轮/解码、IDs/embeddings 和新旧协议，再比较完整生成成本。

Peter 的 OpenClaw
[175496](https://github.com/openclaw/openclaw/pull/175496) 于 12:30:06 UTC
合并为 12048edd（commit 时间为 12:30:05 UTC，分别记录）。广播发现从强引用
pool 集合改成 WeakRef，显式关闭仍先 join/finish 再注销；测试 generation 退休
同时处理 publication bus 和 observation cache，以免重装订阅时保留旧监听或
让当前缓存失去更新。七个完整文件的相邻 parent 补丁精确重建。
作者组合改动的 retained-heap 降幅未复现，单项 ablation 也不能支持相同收益。
未使用 pool 可回收不证明活跃原生进程/provider 已退出。当前 PR-head CI 与
正文引用的过时 head 分开；landed primary CI 仅 1 成功/41 跳过，不能当作全部
运行检查重做。后续需把 retained heap、GC 成本、活跃 worker 存活、失败 drain
的 custody、当前订阅缓存更新及跨重启持久效果一起检验。

本轮 66 次选定公开 GET 均成功；来源代理 278 项、root 独立 262 项离线检查通过。
[来源证据](receipts/20261017T124922Z-reviewed-sources.json)、
[独立来源核验](receipts/20261017T124922Z-root-source-review.json)和
[扫描/浏览器覆盖](receipts/20261017T124922Z-coverage.json)保留来源事实、作者自报、
CI 元数据、本项目推断与实际实验的区别。未执行上述上游代码或数值日志验证。
