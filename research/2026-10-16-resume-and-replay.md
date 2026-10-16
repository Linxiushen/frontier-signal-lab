# 原会话恢复与代理轨迹回放：两项新合并信号

本轮材料增强了 H2 的“恢复时重新取得权限并保留历史效果边界”，以及 H4 的“固定代理版本后核对轨迹、分支和 token 归属”。它们支持我们下一步的公开工程预测，不能证明任何研究者或机构的私人计划。本报告只记录来源阅读；本来源工作者新增本地实验为 **0**，H2/H4 的完整代理框架验证仍未完成。

## 时间、身份和覆盖

基线是本仓库 `4413132e716fbaa3fd694798a1fff68c19cc9067`，前次成功覆盖截止为 `2026-10-16T00:39:41.605720+00:00`。本来源工作者独立查询 `00:39:41Z–02:39:10Z`，下界重叠 0.605720 秒；实际 31 次 GET 发生于 `02:39:44.576180Z–02:49:22.392294Z`。读取时间不替代事件时间，也不推进主扫描器覆盖。

| 新材料 | 事件时间（UTC） | 作者与合并者 | 固定版本 |
| --- | --- | --- | --- |
| [OpenClaw #173579](https://github.com/openclaw/openclaw/pull/173579) | 创建 10-16 00:10:21；合并 02:22:06 | `steipete`，GitHub association 为 CONTRIBUTOR；同人合并 | squash `bfbfae742a5187ff2255f0f367c80d685a7fd24b`；真实父提交 `660ebad698f58803f3a6b37f881817c838fbdd5c` |
| [verifiers #2864](https://github.com/PrimeIntellect-ai/verifiers/pull/2864) | 创建 10-15 15:42:17；合并 10-16 01:40:59 | `mikasenghaas`，MEMBER；`xeophon` 合并 | squash `0976c3073f903d3449163d473e31c7e278b4a042`；真实父提交 `d8d4dce78962f37a523acbb2c120a07046e06f84` |

两仓和 `earendil-works/pi` 均在本轮重新确认为 public、MIT。association 是 GitHub 字段，不等同于雇佣关系；#2864 也不是 Will Brown 的个人贡献证据。旧陈广宇帖子和雇主判断没有在本来源任务中重新核验。

独立窗口内 OpenClaw 默认分支提交两页共 68 项，verifiers 2 项，pi 0 项；最后页均无 next 链接。#173454、verifiers #2866/#2857、pi #11000 的状态、head、正文及评论计数与前次相同；#173454 整体 issue 4 条/inline 2 条数组相同，#2857 增量评论为 0。这里没有覆盖全部分支、作者动态、X、网站或 GitHub Discussions。

## H2：原会话恢复需要权限、存储与效果共同成立

`openclaw-in-place-resume`：#173579 把 WebChat Resume 接到原会话。合并差异中的 [恢复服务](https://github.com/openclaw/openclaw/blob/bfbfae742a5187ff2255f0f367c80d685a7fd24b/src/gateway/session-recovery-service.ts) 校验 session ID、生命周期 revision、恢复 cycle/revision、归档/运行/placement 状态，并拒绝未交付的 final reply 或缺失 transcript。它使用当前点击者的授权，沿普通 chat admission 启动 continuation。

[pending-input store](https://github.com/openclaw/openclaw/blob/bfbfae742a5187ff2255f0f367c80d685a7fd24b/src/config/sessions/session-pending-input-store.ts) 将 lifecycle settlement 传给现有 input actor 的 `acceptInput`，避免先清 tombstone、后接受输入的间隙；本轮阅读了调用差异，没有重新审计整个未变更 actor 事务实现。内存会话或不存在当前 input actor 时拒绝这种 resume。限制通过 dispatch、queue 和权限 overlay 传播，不能执行 restart-safe 工具的 CLI 会返回显式 new-session 入口。旧 mode 省略时仍走 replacement API。

70 个变更文件的 patch 全部保留并校验哈希；其中 18 个关键 patch 完整重读，其余只做选择性阅读，不能称为全 70 文件审计。两个主要测试文件的范围如下：

| 证据 | 源码中实际检查的范围 | 本轮验证边界 |
| --- | --- | --- |
| [434 行 Gateway owner 测试](https://github.com/openclaw/openclaw/blob/bfbfae742a5187ff2255f0f367c80d685a7fd24b/src/gateway/server.sessions.recover-in-place.test.ts) | 生产 RPC、授权、recovery/input storage；原身份、重复请求、CLI 保留限制、过期 in-place ID、只读来访者、admission 等待期间撤权 | 下游推理被 mock；不是完整工具运行 |
| [668 行进程测试](https://github.com/openclaw/openclaw/blob/bfbfae742a5187ff2255f0f367c80d685a7fd24b/test/gateway-session-resume-restart.e2e.test.ts) | 独立真实 Gateway 进程、脚本 Responses provider、真实文件效果；普通权限控制、managed/SIGTERM/SIGKILL 重启；取消、受限、恢复分支 | 所有用例明确 skip Windows；“revoked”用例改变 session permissionMode 为 read-only，并非真实 device/role 撤销。第二次 SIGKILL 只发生在 continue 分支 |

作者报告进程测试 4/4、owner 测试 10/10，以及其他测试数。这些是公开陈述；本轮没有执行测试，也未审计该活动的原始日志。进程测试中受控 provider 与真实宿主效果是有价值的工程证据，不能直接推广到真实模型行为、设备撤权后再次重启或一般可靠性。

`openclaw-in-place-checkpoint-review`：最新公开 [P1 评论 r4290098935](https://github.com/openclaw/openclaw/pull/173579#discussion_r4290098935) 创建于 `01:55:37Z`，由 `chatgpt-codex-connector[bot]` 发布。它指出早期 Code Mode replay-safe checkpoint 可能被最近 20 条消息的尾部窗口挤出。合并 patch 确实只读取 recent 20/max 256 KiB，未见 `readMainSessionRecoveryCheckpoint` 调用；这是具体待验证窗口，**不是我们复现出的故障**。评论摘要报告 prepared head 有 unresolved findings，但未查询权威 GraphQL review-thread resolution 状态。

`openclaw-in-place-head-ci`：[CI 38837406620](https://github.com/openclaw/openclaw/actions/runs/38837406620) 的 API 元数据为 completed/**failure**，绑定 prepared head `c25ebe8a0b86270bf0b8e9a6482d7a51056176ea`，更新于 `02:11:05Z`。作者在 [02:20:16 评论](https://github.com/openclaw/openclaw/pull/173579#issuecomment-6206582978) 中把失败归于 inherited compiler-inventory assertion 和下游 aggregate gate，并描述授权 landing exception。本轮没有独立审计 job 日志、clean-main 复现或所有 attribution 输入；因此不能称为 CI 通过，也不能把作者的归因当成我们的证明。

旧 `openclaw-background-exec-kill-settlement-review` 的 [P2](https://github.com/openclaw/openclaw/pull/173454#discussion_r4288588952) 创建于 10-15 `21:44:03Z`，仍是旧事件。本轮默认分支固定到 `eee5170d25ca` 读取的 process 文件仍在请求取消后、supervisor settlement 前清除 exit notification；评论数组未变。它保留为未复现的 crash 窗口，不能当作本轮新故障。

## H4：把表面回放差异与真实训练分叉分开

`verifiers-harness-replay-views`：#2864 的 31 个变更 patch 全部阅读，另获取固定 squash 的完整文件，检查 graph matching/token 段、依赖、Pi harness、integration grid、相关 fixtures 和 resume-tool 测试。

[Harness.replay_view](https://github.com/PrimeIntellect-ai/verifiers/blob/0976c3073f903d3449163d473e31c7e278b4a042/verifiers/v1/harness.py) 默认返回原消息；rollout 把 override 放在 trace 的私有、非序列化字段。[graph](https://github.com/PrimeIntellect-ai/verifiers/blob/0976c3073f903d3449163d473e31c7e278b4a042/verifiers/v1/graph.py) 在存储侧与入站侧都通过 view 建 matching key，保留原始 sampled message。`drop_blank_text` 只把 assistant 的空白字符串 content 转为 None；`strip_text` 处理 assistant 字符串 content 和 reasoning 的首尾/空白，保留其他字段。Pi、Prime Agent、Claude Code 使用前者，Hermes 使用后者。

这不是所有差异都可以忽略的许可。完整 graph 仍检查实际 token 与 renderer token 前缀，bridged 情况不匹配会报错，其他不匹配形成物理分支。源码存在这些保护不等于训练 token/mask 归属已被我们运行验证。Bash 的另一项修复只在 replay transcript 已包含相同 harness system prompt、且 task 无自带 prompt 时避免再次追加。

版本约束是关键：Pi `0.86.1`、Prime Agent `0.9.5`、Hermes `2026.9.14` 的规则附上游源码链接；Claude Code `2.1.278` 规则明确标为 observed，因为其源码未公开。不能把该规则当作可跨版本不变的事实。

单位测试增加 4 个参数组合，比较有/无 view 及 tool call 保留；多项 integration 测试新增 `num_branches == 1`，包括两段交互与 MCP 的 [test_resume_tool](https://github.com/PrimeIntellect-ai/verifiers/blob/0976c3073f903d3449163d473e31c7e278b4a042/tests/integration/test_resume_tool.py)。mini-swe-agent 的两个对话场景有明确设计性例外；没有 model turn 的测试也不适用该断言。作者报告四种 harness 在 Prime sandbox 的 12 个 single/multiturn/tool cells 从 4 过/8 失败变成 12 过；本轮没有运行或独立审计这组结果。#2866 的关闭/评分生命周期问题仍作为独立 gate 保留，#2857 仍 open。

## 下一步只选一个完整框架 gate

候选是固定父/合并 verifiers 与 Pi `0.86.1`、pi-acp `0.0.33`、pi-mcp `2.34.0`，通过真实 Pi/ACP 运行两段 MCP resume。记录 task/model/runtime/config、wire requests、原始 message 不变性、分支和 token/mask 归属；空白 cosmetic replay 是正例，改变 tool call/result/content 或 token prefix 是负例，必须形成分支或拒绝。保留原始 episode、退出/清理效果与成本，不用抽取 helper 的玩具测试替代完整链路。

当前 Windows 完整框架运行条件仍未满足：[Pi harness](https://github.com/PrimeIntellect-ai/verifiers/blob/0976c3073f903d3449163d473e31c7e278b4a042/verifiers/v1/harnesses/pi/harness.py) 使用 `/var/tmp`、POSIX shell、`chmod` 和运行时 Node/npm 安装；需要已有可用的受支持 Linux/container runtime、依赖和模型端点。[上游 live fixture](https://github.com/PrimeIntellect-ai/verifiers/blob/0976c3073f903d3449163d473e31c7e278b4a042/tests/integration/conftest.py) 在缺少 `PRIME_API_KEY` 时跳过模型驱动测试。本来源任务未读取凭据值、安装依赖、购买算力或启动外部工作。

通过这个 gate 只能增加回放忠实度的证据。要证明 RL 奖励、训练质量、设备内存或整个 OpenClaw 的可靠性，还需要各自实验；本轮未把这些结论写成既成结果。

本轮独立审计文件是 ignored 的 `reports/runs/20261016T023826Z/frontier-checks.json`，SHA256 `312535e6efa74a5fccf96b49f4bcebe12fe7ca9fe439e5d55aac5a4a4485a2c9`；包含 31 次请求时间、原始 CLI HTTP/body 哈希、分页、比较结果和明确的阅读范围。原始字节是 `gh api --include` 输出，不是网络抓包。公开 ledger 的四个新 source ID 与 H2/H4 对应，历史来源的事件时间不改写为本轮读取时间。
