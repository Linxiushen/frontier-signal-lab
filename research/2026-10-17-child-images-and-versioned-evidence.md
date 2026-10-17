# 2026-10-17：进程身份与版本证据的边界

本轮完成了一个新工具实验：Windows 后代进程镜像普查，两个固定控制的 producer 运行标志均通过，但联合验收 **NOT ACCEPTED**：冻结审计器拒绝两个 self hash 检查。单次运行耗时 1.384134 秒，记录 5 份持有屏障的快照；两个用例共 12 个保留句柄身份均退出，最终 Job 计数为零。实际预训练模型加载与优化器更新均为 **0**。H1 的训练、质量、成本与历史无效 RSS 结论保持不变。

## 本项目实际执行

旧训练集成在 preimport 发现八个未记录镜像的额外进程后失败。旧 producer、协议、结果和失败审计全部保留。本轮使用独立声明的新 producer：先对 launcher、实际解释器及 native cmd 取 OS 镜像/文件 hash，再记录其他后代的 PID、creation、parent、Job/live、镜像 basename、文件 SHA256 和匿名路径摘要。

本轮额外镜像中包含 `conhost.exe, python.exe`；这些是本轮新观测，不能倒推旧八个进程的身份，也没有加入允许列表。第二个用例专门注入相同 base-Python 镜像的辅助进程：虽然可识别，仍因不属于固定角色而被拒绝；全 Job 终止并核验清理。逐行证据见[结果](../results/child-image-census/report.md)、[原始回执](../results/child-image-census/report.json)与[复现协议](../fixtures/child-image-census/README.md)。

代码、测试、协议、依赖、执行文件与 portable auditor 均在单次实际 suite 前冻结；无预演、重跑或结果后改阈值。审查修复了关闭句柄晚返回仍误报通过的边界。portable auditor 为 422/424，两个 `base_worker_self_hash` 检查失败：Python 自报 `sys.executable` 的文件 hash 指向 venv launcher，而保留句柄查询的实际 OS 镜像 hash 对应 base interpreter。两类字段不能相等代用。冻结审计器、拒绝结果与 producer 均不修改，本轮不重跑；下一版本须独立声明双身份契约。后写的 pinned rejection checker 仅保留本次负结果，不能把联合验收改为通过。

下一门槛仍是单独声明的真实训练集成：先依据身份和行为论证窄允许策略，保留同镜像未知 helper 拒绝，再验证实际 loader、线程/native/provider 后代、两步训练、正常/失败/超时/阈值、采样开销与清理。当前工具没有 ML 放行路径；采样计数一致也不证明连续覆盖、已加载 DLL 完整性或生产可靠性。

## 公开证据与本项目推断

FLA 的 1490/1487 修订把 singleton stride 源码用例扩展到 168 个 eager/compile 单元，但新可见修订的代码提交时间早于上一 cutoff；首次看到不是刚发布。基线先在规范化断言失败，不能说 168 个内核运行全部失败。1487 的新 A2 日志只有两个该类 PowGLU 用例通过，不能升级 1490 的完整矩阵。1496 的落地提交和原提案 synthetic merge 各有成功日志，但 22 个因果性、36 个 lower-bound 和两个 shift 用例全部跳过。1404 的新提交只扩展 FP16/BF16 测试，当前 tip 无 checks；旧 Ascend 两个编译失败保留，作者另报的 FP16 状态梯度负结果尚无独立原始日志核验。这些贡献不能归为 Nathan 的新工作。

OpenClaw 的共享启动取消归属、清理完成后延迟重载、精确重连读取已合并，但源码断言和 prepared-head CI 不能代替落地运行。延迟重载还保留作者承认的异步交接旧配置 P2 问题；所链接 Package Acceptance 失败与候选选择未核验的限制都保留。新增调用方 deadline 包含 preparation（Vincent Koc），以及缺少原始授权来源的完成通知持久化不投递（Peter Steinberger），为 H2 提供具体的失败注入点；后者仍缺 shipped-Gateway 升级和两次重启证明。

verifiers 的默认 decision judge 改为 cloudflare/clef；后续评分比较必须显式固定裁判及配置。新 Rust Prime Agent 0.10.0/bootstrap 提案来自 xeophon，并非 Will Brown。它仍是 open proposal，审查提出共享 kernel 路径兼容缺口；Tests 当前 attempt 2 成功不能抹除未审 attempt 1/log 的盲区。这些不是奖励一致性或训练收益的实测。

本项目推断：值得投入的切口是“数值与优化器状态契约 × 实际资源边界”以及“带版本的权限、时限、持久效果和清理”。这仅指导我们的可证伪实验，不预测个人或机构的私有路线。H2 完整 harness 未验证；H3/H4 仍计划未执行。

## 时间与覆盖

本轮主 scanner cutoff 为 `2026-10-17T00:45:41.798305Z`，实际采样 `00:45:41.802305–00:50:02.436508Z`，7 人/10 仓库，请求错误零。24h/72h/7d 重叠窗口分别保留 168/230/245 条主记录；66 条 current-only 全在旧 cutoff 后，另有 19 条相同身份变化。14 个端点可能截断，七个仓库关闭 discussions，均不当全量覆盖。

前一未完成轮次仅做来源审读，没有主 scanner 或实验；此次复用时保留其原事件和较晚实际 HTTP 时间，再作独立增量补读。X 由支持的浏览器单独核验：主页可见四条最新原帖及完整英文离职公告，仍未确认新雇主。没有联系研究者、发 issue/PR、评论或发布社交内容。[公开证据回执](receipts/20261017T004420Z-reviewed-sources.json)记录作者、事件、版本、许可、CI、原始 hash 与盲区。
