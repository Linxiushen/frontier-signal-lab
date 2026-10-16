# 收据身份、维护期限与策略重入：H2 的三项新验收边界

三个新合并支持把 H2 的下一步研究收窄为：持久化前后保持已接收输入的身份；为维护暂停设定不可续期的期限；配置更新后重新准入后台完成通知，同时保留原生产者的权限上限。它们也可能只是已知可靠性问题的常规修复，不能据此推断个人或机构的私人路线。

**本来源工作者执行上游测试、模型和完整代理框架实验均为 0。** H2 运行状态保持 `independent_sqlite_adapter_and_context_primitives_executed_full_harness_unverified`，H4 保持 `planned_not_executed`。以下“测试”是所读源码中的断言；作者运行陈述和 CI 元数据分别标注。

## 窗口、作者与可复核性

基线 `8c777425a743879da8fe59288a18a89f76c22310`，前次成功截止 `2026-10-16T04:35:20.748207+00:00`。独立提交查询为 `04:35:20Z–06:36:24Z`，下界重叠 0.748207 秒，上界为本轮开始整秒；该来源任务不推进主扫描截止。54 次 GET 均成功，实际观察区间为 `06:37:40.618743Z–06:42:00.033088Z`。

窗口内 OpenClaw 返回 100 个提交，verifiers、pi 均为 0。OpenClaw 第一页 Link 同时标注 next=2、last=1；显式读取第二页为空，仅 first/prev、无 next，已保留异常。未将 100 个提交全部进行 patch 审计，只深入下面三项，保存并完整阅读不可变合并提交的全部 31 个文件 patch。

三仓当轮 metadata 均为 public、MIT。GitHub 作者、association 和合并者是贡献归属证据，不是雇佣证据。旧提议在本窗口合并，不等于算法或研究方向今天首次出现。

| 来源 | 创建 → 合并（UTC） | 实际作者 / 合并者 | 不可变合并提交 / 真实父提交 |
| --- | --- | --- | --- |
| [#173878](https://github.com/openclaw/openclaw/pull/173878) | 10-16 06:02:17 → 06:24:53 | `steipete`，CONTRIBUTOR / `steipete` | `ed3fcdbbbea61537c3383944a5f4b1e904aa362b` / `68f4a155f46be0894aeb6ee962011be19b37ffa4` |
| [#173788](https://github.com/openclaw/openclaw/pull/173788) | 10-16 04:15:10 → 04:57:22 | `steipete`，CONTRIBUTOR / `steipete` | `7042b9a4f572d92304c369f47cb30a55f5210e98` / `4dc7c469e677aa0f3c5f1e753a3041ac31cfa453` |
| [#169529](https://github.com/openclaw/openclaw/pull/169529) | 10-12 02:06:43 → 10-16 04:58:58 | `wangmiao0668000666`，CONTRIBUTOR / `RomneyDa` | `4217e957da91629c74db29b4a96d7692d10b3d55` / `f11e2139bb7a253dc598935371de273ad26052e4` |

## #173878：存储归一化不能改变收据身份

旧 peer delivery metadata 显式带有 `lifecycleRevision: undefined`。接收时的稳定哈希包含该属性，JSON 持久化会省略它，重放同一输入因而可能产生虚假冲突。

最终八文件改动（+176/-20）在 [producer](https://github.com/openclaw/openclaw/blob/ed3fcdbbbea61537c3383944a5f4b1e904aa362b/src/agents/tools/sessions-send-communication.ts) 省略未设置的两个 revision 属性；[replay owner](https://github.com/openclaw/openclaw/blob/ed3fcdbbbea61537c3383944a5f4b1e904aa362b/src/config/sessions/session-accessor.pending-input-request.ts) 只重建 source/target 这两个属性，并且仅在 **同一 run 的完整候选哈希等于原已接收哈希** 时采用。它没有放宽任意内容或身份的匹配。保留中的收据继续拥有原始 request hash，直到退休后才允许 transcript-backed 重建身份；已消费、取消等候选在解析旧 endpoint 前先被排除。

新增存储测试使用真实 pending-input/completion owner，轮换 lifecycle generation、关闭并重开 SQLite，覆盖 pending、interrupted、consumed、completed 四态；改变内容仍冲突，相同已完成输入返回已有结果，不能再启动 turn。通信及恢复测试另检查省略属性与旧候选跳过顺序。作者报告 95 项局部测试通过；本轮未执行，也没有完整 Gateway/OS 进程重启与再次崩溃的端到端证据。

这要求 H2 区分“序列化后内容相同”“原收据身份相同”“当前仍有通信权限”三个条件。未来完整实验应保留 changed-content、reset/replaced/archived/permission-denied 负对照，不能仅凭哈希修复宣称 exactly-once。

## #173788：暂停必须有一个期限所有者

[coordinator](https://github.com/openclaw/openclaw/blob/7042b9a4f572d92304c369f47cb30a55f5210e98/src/infra/gateway-suspend-coordinator.ts) 将 drain 改为准备开始后固定 45 秒：30 秒排空，15 秒交接或清理。重复 prepare、轮询和变为 ready 都不能续期；相对单调时钟和墙钟双重边界防止回拨延长预算。仅 refuse-only freeze/snapshot 保留两分钟可续期租约。

超期先恢复调度，再开放准入；不会取消已准入工作或丢弃受保护写入。已提交 shutdown 的归属仍由 host 持有，不能被租约超期重新打开。owner/request、lease、caller、reason、exit cause 被写入日志。[原生 CLI](https://github.com/openclaw/openclaw/blob/7042b9a4f572d92304c369f47cb30a55f5210e98/src/cli/update-cli/update-command-service-drain.ts) 的预算从首次取得租约起算，受剩余 expiry 减去 15 秒约束，拒绝已过期或被替换的租约。controller 去除续期，将 drain 上限设为 30 秒，瞬时 write custody 最多再等五秒，保留有界 status RPC 和准确租约清理。

18 个 patch（+413/-211）全部阅读，包括 dispatcher 的断线控制器/尝试续期后 45 秒重新开放 RPC、慢 status/prepare、替换/超期拒绝，以及协调器和虚拟时钟 controller 测试。controller 下第三方 skill 文本只作为证据阅读，未执行其中操作。没有实 Gateway suspension、真实 GNU timeout、stable-to-candidate update 或部署证据；合并 Gateway 也不代表安装了匹配 controller。

这支持把维护 liveness 作为 H2 研究合同的一部分：任务保留和用户恢复可用性需要同时验收。短期限是一个公开兼容性变更，不能仅测“任务没有丢”，还应测写入保护、控制器消失、交接承诺和恢复准入。

## #169529：重试必须携带原生产者的权限

接受但尚未启动的后台完成通知持有 enqueue 时策略。配置发布后旧策略检查拒绝它，原 settlement 又会消费 occurrence，造成完成通知丢失。

[session-event owner](https://github.com/openclaw/openclaw/blob/4217e957da91629c74db29b4a96d7692d10b3d55/src/auto-reply/reply/session-event-handoff.ts) 只让“因策略发布拒绝、尚未开始、尚未尝试发送、未 abort/abandon”的 occurrence 经当前策略重新 dispatch，最多两次。重入携带原 destination/store、tool ceiling、settings、delivery opt-out、生产者 `assertCurrent`、取消信号和 `onAdopted`；未首次接受时还携带 ingress authority。原收据 cancel/settled 追随 live attempt。

每次尝试使用不同 `MessageSid`，防止 inbound dedupe 把重入当成已消费重复；耗尽、撤权或同步拒绝都终止并记日志，不能退回不携带 producer contract 的 passive queue，供后续普通 turn 用自身权限执行。三行 [precheck](https://github.com/openclaw/openclaw/blob/4217e957da91629c74db29b4a96d7692d10b3d55/src/auto-reply/reply/followup-turn-execution.ts) 在 `recovery.admitUserTurn` 前拒绝过期策略，避免提前退休 durable exec source。

五个 patch（+454/-11）全部阅读。五场景测试使用真实 queue、dispatcher、durable source admission、managed write tool 和文件最终效果，模型推理仍是 synthetic：新策略 deny、原 producer ceiling、允许写入 control、producer 撤权和 publication storm。另一个真实 background child/exec-notify 测试检查完成内容与新策略，但明确 skip Windows。

**剩余窗口未关闭：**策略发布如果落在 `admitUserTurn` 自身 await 内，仍可能先把 durable source 标成 terminal，再拒绝执行，最后 failed 并记日志。当前正文明确将 source-retirement policy 留在范围外。正文的 packaged-Gateway 痕迹属于重构前版本；driver 未提交，也未在当前结构上复跑。最新公开 review 仍要求当前真实入口证明，随后发生的 merge 和 success CI 均不能替代它。

## CI、旧问题与下一步

| 固定 prepared head | 主 CI 元数据 | updated_at（UTC） | 限制 |
| --- | --- | --- | --- |
| #173878 `b2be282378c3a46597c6ed92b33f7fa559c31c89` | [38859007079](https://github.com/openclaw/openclaw/actions/runs/38859007079) completed/**failure** | 06:13:37 | 68 项 job metadata 中 prod-types、lint-core-2 及 aggregate 失败；作者归因为继承的 `LitContent` import 并声称获准例外，归因和授权未独立审计 |
| #173788 `09d1899acf8ad1176ee2521173754deed233e42f` | [38851464205](https://github.com/openclaw/openclaw/actions/runs/38851464205) completed/success | 04:55:46 | 未审 job logs/artifacts，没有 live update 证明 |
| #169529 `1d327ac2821e486307c0f9dbf765f602b894c584` | [38852541184](https://github.com/openclaw/openclaw/actions/runs/38852541184) completed/success | 04:57:06 | 未审 job logs；不消除上述 packaged-Gateway 与 admission-window 缺口 |

已跟踪的 OpenClaw #173579/#173454/#170336/#173580/#173241，以及 verifiers #2864/#2866/#2857/#2875、pi #11000 metadata 均未变。前五项 OpenClaw issue/inline、verifiers #2857 和 pi #11012/#9602 完整评论数组与前次一致。verifiers #2875 本轮取得完整 issue 0 / inline 0；旧提议不能满足 pinned Pi/ACP/MCP 两段回放，H4 不变。

窗口末端 ref `785f2467d88c18c57aac91fe387442ed583dd474` 的恢复服务、process 文件 blob 与前次完全一致：checkpoint reader 仍缺失，recent 20 / 256 KiB；kill 仍在取消请求后、supervisor settlement 前清除 notification obligation。[checkpoint-tail](https://github.com/openclaw/openclaw/pull/173579#discussion_r4290098935) 与 [kill-settlement](https://github.com/openclaw/openclaw/pull/173454#discussion_r4288588952) 继续是未复现源问题。未查询权威 review-thread resolved 状态，旧评论不是新事件。

H2 下一次完整框架实验需在已有真实入口、当前设备/角色权限、durable-effect receipts、写前/写后取消和单调等待验收之外，加入 JSON round-trip 收据身份、断线维护期限、当前策略加原 producer ceiling、允许写入 control、撤权/取消/耗尽后无 passive drain，以及 publication 落在 durable admission 内的独立对照。还必须保留旧 checkpoint-tail、kill-before-settlement、持久化失败、并发与第二次重启。Windows 完整框架前提仍未满足，本轮只收紧验收。

可公开的请求指纹、真实父提交、31 个 patch 哈希、完整观察界限见 [evidence](evidence/2026-10-16-receipt-drain-readmission.json)。忽略目录冻结审计 `reports/runs/20261016T063624Z/frontier-checks.json` SHA-256：`320a2bb4861df3ae360905f1085511e3b4ff787a36f52aeeaa41edc3854b08e4`。原始证据为 `gh api --include` stdout bytes，非网络包抓取；上游代码仅保存在忽略目录用于审阅，未复制进发布代码。
