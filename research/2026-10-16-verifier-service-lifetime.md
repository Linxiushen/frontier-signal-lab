# 服务生命周期已合并：下一门槛是评分与失败分支

verifiers 的 [PR2866](https://github.com/PrimeIntellect-ai/verifiers/pull/2866) 于 **2026-10-15 21:17:48 UTC** 合并为 [2a3ddf7](https://github.com/PrimeIntellect-ai/verifiers/commit/2a3ddf7725f655cb7ea14fc9f10195221fa3ed1a)。上一轮仍是未合并提案；现在它已是上游接受的实现。作者 hallerite、审批和合并者 xeophon 是这项贡献的实际参与者；不能把仓库内其他作者的工作归给跟踪名单中的 Will Brown。

## 已核验事实与尚未执行的部分

已读合并提交全部三个改动文件：`rollout.py` 和两份文档，没有新增测试文件。正常完成及交换分段间隙先执行 finalize/采集；同环境评分在关闭 session 前，isolated 评分则在采集、关闭及环境停止后进行。超时或中途停止先尝试关闭 session，failed rollout 不评分。关闭异常会记录后继续，因此关闭调用本身不证明进程已静止或写入权限已撤销。

PR head 仍是 `f1444853`，但合并版完整 `rollout.py` 与它不同：还包含此前 PR2869 从原始 agent runtime policy 解析隔离配置的改动。四个生命周期方法与 head 一致，两份文档 blob 一致；不能把 head 上的 CI 当成最终合并 tree 的执行证明。本轮没有下载验证相关 CI 执行日志。

作者原有“150 个曾全部失败的任务、每任务两次 rollout”主张没有新增可审计的任务清单、精确模型/harness/baseline 或逐次结果。已观察到的 CI artifact 列表也不等同于这些原始实验数据。**合并改变实现状态，作者汇总效果仍待独立验证。** 本轮新增本地实验为 0；当前运行环境缺少完整 verifiers/ACP 依赖与已核验服务运行环境，没有用替身回调冒充实际服务生命周期。

## 可证伪的下一实验

H4 继续检验“评分是否依赖环境版本和生命周期”。先固定完整合并版本、任务、harness、seed 和 verifier，使用真实由 session 管理的本地服务；按同一输入比较[真实 parent e71c69c](https://github.com/PrimeIntellect-ai/verifiers/commit/e71c69c811327b29e1becd1651cda223d4742ebd)与合并版本，并保留所有失败。实验需记录服务 PID/请求、采集内容 hash、评分、时间轨迹及异常。

| 分支 | 需要观察的可执行断言 |
| --- | --- |
| 正常完成 / 分段间隙，同环境评分 | finalize、collect、score、on_score 看到预期服务；关闭后进程状态明确，重复 close 不重复副作用 |
| 超时 / 主动停止 | 先关闭再取证评分；另注入 close 异常，实测仍存活进程和评分期写入，不将尝试关闭当作静止证明 |
| isolated 评分 | collect 时服务可访问；关闭、metrics、停止 workspace、sidecar 取证与隔离评分顺序有实际轨迹，评分配置身份可追溯 |
| finalize / collect 失败 | 分别注入超时与普通异常，检查失败记录、metrics 是否执行、证据是否丢失，以及清理能否完成 |
| 评分预算 | 测量零、有限、无上限配置的真实耗时；同环境 score/on_score 后另分配 metrics 预算；隔离评分分支中，metrics 从评分预算扣除，关闭与 metrics 会延长 finalize deadline |

源码静态阅读显示：普通 finalize/collect 异常可以跳到外层失败处理；它与超时路径的 metrics 行为不同。该项是优先验证条件，尚未本地复现。若固定版本后各分支评分一致且故障证据和进度均满足约定，应降低 H4 中“仍有实质不一致”的判断；替代解释是普通兼容性修复已经解决主要偏差。

## H2：新合并证据把版本与活性边界具体化

- obviyus 的 [PR173459 / 330c27e](https://github.com/openclaw/openclaw/commit/330c27ed6342b371c18839d895d12adb83780192)，22:05:11 UTC 合并：abort 或新用户轮次取消旧建议审查，重复 steering 结果不再进入 fallback。
- 同作者的 [PR173489 / 4d13205](https://github.com/openclaw/openclaw/commit/4d1320586e4574b0d207031531d7cb791b9fb9e0)，22:04:49 UTC 合并：同 run/transport 的已提交快照保留至原子替换；新 run/transport 仍撤销旧快照，reset 后未完成的准备不能将它复活。
- Peter / steipete 的 [PR173213 / 5a56a45](https://github.com/openclaw/openclaw/commit/5a56a45999dff95591b5ada6e87ecebfff17b558)，22:18:06 UTC 合并：lease 释放在既有两秒重试预算内接受有类型的 maintenance contention；只重试释放，不重放业务 callback。混合/不符合条件的错误仍拒绝重试。

本轮已读这些合并补丁及测试断言，未执行 OpenClaw，也未独立验证 PR 正文中的集成 campaign、性能或测试通过主张。它们支持 H2 的工程方向判断：版本替换要兼顾可用性和撤销，恢复进度要区分清理重试与业务重放。这可能是已知集成问题的持续修复；并不证明新的个人研究计划。

下一门槛保留真实发布旧态 Doctor 升级、持久化故障和外部效果回执，并加入维护在重试预算内/外结束、混合错误拒绝、callback 只执行一次的真实状态测试。既有 H2 工作预测仍于 **2026-10-30** 复查；这批同项目修复不作为独立研究复现或生产可靠性证明。

## 覆盖与执行状态

GitHub 扫描实际 **22:32:57.586731–22:37:41.037612 UTC**，事件截止 **22:32:57.581731 UTC**，七天重叠。73 个顶层事件首次采到或更新时间变化；新发现不等于新发布。七人没有采到新建原创仓库或 profile 变化。

| 窗口 | commits | issues | PR | discussions |
| --- | ---: | ---: | ---: | ---: |
| 24h | 61 | 29 | 82 | 1 |
| 72h | 91 | 29 | 98 | 5 |
| 7d | 117 | 29 | 98 | 5 |

扫描请求无失败，首页/评论仍有截断；定向 OpenClaw commits 只读首 50 条，有下一页。H1 定向读取未发现新的训练、activation 或性能验证，既有真实训练门槛不变。11 份一手主页/博客/RSS 原始响应与前轮逐字节一致。已知 Nathan 离职帖预览内容未变，一次连接失败后重试成功；当前 X 时间线仍因支持浏览器认证错误未读，未推进时间线覆盖，新去向仍未核验。

本轮只更新证据和实验门槛，既有六项实验结果保持原样。各独立观察区间、分页和 hash 见[证据快照](../reports/2026-10-16-verifier-service-lifetime/evidence.json)。
