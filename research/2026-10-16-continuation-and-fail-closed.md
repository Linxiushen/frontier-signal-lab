# 会话延续、失败读取与模型级压缩：H2 的下一步验收

本轮三个公开变化支持把 H2 的研究进一步收窄为：权限的有效期必须与会话身份一起持久化；恢复读取失败不能伪装成空状态；上下文压缩需要记录实际使用的模型和策略版本。这是我们自己的可检验方向，也可能只是已知集成问题的常规修复，不能据此推断个人或机构的私人路线。

**本来源工作者执行上游测试、模型及完整代理框架实验均为 0。** H2 仍为 `independent_sqlite_adapter_and_context_primitives_executed_full_harness_unverified`；H4 仍为 `planned_not_executed`。以下断言来自所读源码，作者报告和 CI 元数据另行标注。

## 观察界限与归属

基线 `457dc7242cce005f678ed4f554f3dd46ab987c28`，前次成功扫描截止 `2026-10-16T06:37:11.159628+00:00`。独立提交窗口 `06:37:11Z–08:35:23Z`，下界重叠 0.159628 秒，上界是本轮开始整秒；主扫描截止由主扫描器管理。78 次 GET 均成功，实际观察区间 `08:36:42.612238Z–08:44:04.900193Z`。观察时间可以晚于提交窗口，不等于扩大事件覆盖。

OpenClaw / verifiers / pi 各返回 90 / 0 / 3 个提交，均只有一页且没有 next Link。三仓当轮均 public、MIT。只深入三个信号簇，完整阅读 31 + 7 + 17 = 55 个不可变文件 patch，没有审阅全部 90 个 OpenClaw 提交。X、个人网站和作者全部活动未被这项 GitHub 审阅覆盖。

| 来源 | 创建 → 合并或提交（UTC） | 贡献归属 | 不可变提交 / 真实父提交 |
| --- | --- | --- | --- |
| [OpenClaw #173383](https://github.com/openclaw/openclaw/pull/173383) | 10-15 18:21:55 → 10-16 08:07:39 | `YuriyPopovDev`，CONTRIBUTOR；`vincentkoc` 合并 | `50982158d0883504d381db0a930948c0214de86a` / `d5342a4275b64a93b6addf022ed3bca3357ae5b7` |
| [OpenClaw #173970](https://github.com/openclaw/openclaw/pull/173970) | 10-16 07:21:04 → 08:13:19 | `steipete` / Peter Steinberger，CONTRIBUTOR；同账号合并 | `fee013dd6a3dc0cbac29c2090e4dcd8b225e7c02` / `d5f9a1eafe973438bc9fbb06674224799932f93a` |
| [pi 模型级压缩](https://github.com/earendil-works/pi/commit/6085986e4b4a55a36a872df9e438e1a55ffcba35) | 10-16 08:19:56，随后两次提交至 08:20:58 | `badlogic` / Mario Zechner；需求来自 `finnvoor` #10942，类型问题来自 `jpenilla` #10858 | `6085986e… → c4cf7957… → 790271cd…`；首个真实父提交 `4954d760504c11df9b2cbdc040346107b6a8153d` |

上述账号、作者名和 association 是公开贡献信息，不是雇佣或年龄证据。#173383 正文还明确致谢 `mywondvision` 的 #156651 / `7e56f0b802b8fe9deb3d5ed95b469fb50aa69278` 基础贡献。

## #173383：会话权限的有效期进入持久化合同

31 文件改动（+1335/-102）将工具策略分为 conversation 与 turn 两种有效期。长期限制的原生线程保存创建配置指纹；兼容的 warm / cold 后续请求继续使用同一线程。单次 allowlist、sender 限制、临时授权和 additive plugin grant 采用隔离 owner，首次临时请求也不能建立永久会话绑定。无实际约束变化的 wildcard / scheduled 请求保持普通延续。

当受管理线程的创建策略变化，或旧绑定缺少指纹时，现有 ownership guard 决定能否创建 successor；启动失败保留原绑定，外部 owner 与活跃工作保护继续拒绝替换。context engine 在 assembly 后才发现需要 successor 时，投影已经准入的快照及附件，而不是再次 assembly 后使用后台新快照。configured-MCP predecessor 的清理仍位于替换提交之后。指纹是可选持久化字段，旧行仍可读取。

新增生命周期测试明确使用 synthetic native responses 和内存 binding store，覆盖 warm/cold、一次 legacy 转换、变更 deny、保护拒绝、启动失败、临时首轮/后续轮、incognito 与 additive grant。另有真实 SQLite close/reopen 验证旧行和指纹保存；file-backed session/context-engine 测试检查 epoch 迁移及已准备快照。它们没有构成真实 Gateway/OS 重启验收。

正文及历史评论提到旧 head `27e2843f…` 的隔离 Gateway / native Codex 0.160.1、12 turn / 24 request、6 次允许文件写入和 6 次拒绝、Alice–Bob–Alice、归档 stable-state 升级证明。这些是作者或 bot 的旧版本附件陈述；本轮没有下载附件或审计其原始轨迹，不能移植到最新 head。35/129/108 等局部数量存在重叠，不能相加。`vincentkoc` 于 06:59:07Z 明确接受 guarded successor 产品决策，随后 squash merge；这只能确立公开的维护者决策与合并事实。

**明确未解决 #148329：**权限、客户端相关的描述、schema 和工具目录成员仍可能改变 fingerprint。不能把保持会话 ID 当成工具目录稳定、记忆质量提升或 token / 延迟收益。

## #173970：读取失败必须到达拥有取消权的边界

七文件改动（+309/-46）修复三种“失败被当成可用状态”的兜底：synthetic auth delegation 遇到 `OAuthRefreshFailureError` / `SecretSurfaceUnavailableError` 重新抛出；历史 branch / context projection 失败显式返回 `{cancel:true}` 并保留原错误；`models.json` 的文件读取移出 JSON parse catch，读取 I/O 错误在规划/写入前传播。真正缺失或 malformed JSON 仍可按原合同重建。

压缩路径仅抛错可能被扩展 dispatch 捕获并继续默认压缩，因此这项修复需要到 registered callback 的取消出口。所读测试检查取消、原错误、没有 auth lookup / summarize；catalog 测试通过实际 private-file store 注入 `FsSafeError` / EIO，并检查真实原文件 bytes 完全保留。auth 测试只证明 resolver 拒绝，尚未证明生产 request transport 没有发出 I/O。

公开 review 仍要求 unavailable-owner 到最终 provider I/O 的阻断证据与健康 marker-only control、stable upgrade、catalog 的 base-fail/head-pass。它还提出 P3：取消消息应说明历史已保存及恢复动作；作者将其延期。本地 focused/type/lint 与新 catalog pre-fix baseline 未完成，不能记为通过，也不能当作新断言失败。合并没有补齐这些缺口。

## pi：模型策略必须在三个读取点对齐

`CompactionSettings.modelOverrides` 按精确 `provider/modelId` 匹配，每字段以 `??` 覆盖 `enabled`、`reserveTokens`、`keepRecentTokens`、`backgroundTokens`。generation threshold 使用当前解析模型；overflow recovery 使用该 request 的模型；compaction select 使用其选择的模型，确定 cut 与 summary `maxTokens`。三个 faux-provider 测试覆盖匹配/不匹配阈值、overflow enable 和 summary 范围/长度，未验证真实 provider 或重启后行为。

不能按标题认定引入位置。真实链为：

1. `6085986e4b4a55a36a872df9e438e1a55ffcba35`（08:19:56Z）标题是 terminate 类型修复，实际已经加入模型压缩实现和测试，共九文件 +132/-14。
2. `c4cf7957b4e6698a182925f4393240c1e3b23f41`（08:20:12Z）标题是模型压缩，实际只误删 terminate boolean/no-op 回归及 storage 错误文档，四文件 +2/-28。
3. `790271cd0218b27068211771704f9e2d42500e9a`（08:20:58Z）恢复这四文件 +28/-2。相对首个父提交的最终九个文件 blob SHA 与首个提交完全相同。

`terminate:false` 是类型对齐及已有 no-op 语义的回归，storage 变更只是明确 `StorageRequestError` 仅豁免 reads，不能称为新的 runtime 实现。`badlogic` 的关闭评论明确标记由 `/wr` AI 生成，并承认 commit collision / 误回退；提交差异是主要证据。

这给 H2 增加的可检验问题是：模型在请求准备、overflow classification、summary select、retry 和恢复之间变化时，每一步究竟使用哪个模型、策略和上下文快照。源码有三个读取点，不等于真实混合模型系统已经满足一致性。

## CI 与仍未关闭的旧问题

| 固定 head | 主 CI 元数据 | 限制 |
| --- | --- | --- |
| #173383 `9fbda548dcc9e3dbb77859eeca8ba4a8ef4102a3` | [38870439836](https://github.com/openclaw/openclaw/actions/runs/38870439836) completed/success，08:05:12Z 更新 | 只读 run metadata，没有 job logs / artifacts 或当前真实运行证明 |
| #173970 `14445749fa0221d3f4be3595d6c0ee873270cf37` | [38866728949](https://github.com/openclaw/openclaw/actions/runs/38866728949) completed/**failure**，07:33:28Z 更新 | 完整 69-job metadata 的 lint-core-2 与 aggregate 失败；作者归因为继承的 debug-overlay consistent-return 并作 admin merge，未独立审计 logs、因果或授权 |
| pi `790271cd0218b27068211771704f9e2d42500e9a` | [38873093464](https://github.com/earendil-works/pi/actions/runs/38873093464) completed/**failure**，08:23:31Z 更新 | 未审 job / logs / 失败原因；其他 label、Nix、catalog workflow 成功不能代替主 CI |

前轮八项 OpenClaw、verifiers #2864/#2866/#2857/#2875、pi #11000 与 #11012/#9602 metadata 保持不变。八项 OpenClaw 完整 issue/inline 数组、verifiers #2857/#2875 及 pi #11012/#9602 全数组与前轮相同。#2864/#2866 和 pi #11000 本轮完整数组虽已取得，前轮没有可逐数组比较的捕获，不据此宣称“所有讨论无变化”。H4 没有新材料支持改变。

窗口末端 OpenClaw `62240dbc4fa6dc86a126788b10b6378c4d3546c2` 的四个关键 blob 与前轮一致：恢复仍 recent 20 / 256 KiB 且缺少 checkpoint reader；kill 仍在取消请求后、supervisor settlement 前清 notification obligation；followup execution / session-event handoff 没有改变。因此 [checkpoint-tail](https://github.com/openclaw/openclaw/pull/173579#discussion_r4290098935)、[kill-settlement](https://github.com/openclaw/openclaw/pull/173454#discussion_r4288588952) 与 publication 落在 `admitUserTurn` awaits 内的 residual 仍保留。没有本地复现，也没有查询权威 review-thread resolved 状态；旧评论不算新事件。

H2 下一次完整框架验收在旧有设备/角色撤权、exact receipt identity、前后写取消、单调 deadline、不可续期维护 drain、原 producer ceiling、max2 重入耗尽和第二次重启条件之上，加入持久限制指纹/legacy successor/临时授权撤销、读取失败前 transport 阻断、历史与 catalog bytes 保留，以及跨阶段模型/压缩策略快照。先预声明对照和外部效果收据，再运行一个候选；本轮只修改验收，不提升运行状态。

公开请求指纹、全部真实父提交、作者、55 个 patch 哈希和 CI 界限见 [evidence](evidence/2026-10-16-continuation-and-fail-closed.json)。当前忽略目录 `reports/runs/20261016T083523Z/frontier-checks.json` SHA-256：`a788703a02d8509dfafa1ca264d5ab69737d2ffdf47f9e2684f465f617826c86`。raw 是 `gh api --include` stdout bytes，不是网络包抓取；上游代码仅存放于忽略目录审阅，没有复制进发布代码。
