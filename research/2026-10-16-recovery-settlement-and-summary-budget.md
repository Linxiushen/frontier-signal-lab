# 恢复义务与摘要预算：公开源码证据

这两组变化支持两个可反证的项目方向：恢复需区分“尚未准备好”和“已经无法合法继续”，摘要触发阈值则应与实际生成预算分别记录。它们也可能只是常规集成修复，不能推出个人或机构的私人研究路线。H2运行状态不升级；H3/H4仍未执行。

窗口为`2026-10-16T10:40:38.681788Z–12:42:46.677543Z`（下界排除）；33次只读GET全部成功，无分页Link。OpenClaw/pi/verifiers/AI-Scientist-v3默认分支分别返回88/3/0/0项，8项旧issue-comment查询为空；其他分支、inline reviews、X和一般公开讨论不在覆盖内。OpenClaw和pi为public/MIT仓库元数据，未逐文件审核许可证或复制实现。

| 源码 | 创建→合并（UTC） | 实际作者 | exact merge / prepared head |
| --- | --- | --- | --- |
| OpenClaw#174134 | 10:58:28→11:24:39 | steipete | `b4ce369de7e8d0047365e7410145321d654eaf51` / `a3e307f4101f355a7db11fb01b2267e71911f54e` |
| OpenClaw#174177 | 11:40:46→12:19:04 | steipete | `ce9d859d68abc213d9c82990ae4d75afc566a830` / `23f912d780e85e35ea44ac8f267bd881ceba07ef` |
| OpenClaw#174203 | 12:17:56→12:32:40 | steipete | `fa191c5ce97ff8e3ce1415d3f7dca1f84455c20d` / `5dd2b9e549284275b90051a843313ebc8af7f524` |
| pi#11036 | 11:08:27→11:53:17 | davidbrai，非badlogic | `6fcb48670fc0e6672a644f3b2691010321734426` / `baba5233a79a95f4611e65453777fd896ba0e788` |

四项提案和合并都在窗口内；37个不可变changed patches全读，范围为12+15+1+9。

**H2：先等待依赖，再决定恢复或结算。** #174134等子代理恢复“结束”后才启动主会话恢复；失败也释放等待，不代表恢复成功。worker只搬运实际有持久义务的行，保留已完成但尚有delivery/recovery义务的行。#174177把缺失/不匹配原权限与明确grant拒绝，和overload/政策尚不可用分开：前者结算精确旧cohort并写一次本地中断notice，后者保留重试；child结果和可重放的未确认reply保留。pending-final深相等检查防止并发新intent被旧notice覆盖。测试包含SQLite重载、模拟lifecycle轮换和mock runtime；不能当成独立OS重启证明。#174203随后在普通peer admission触碰receiver行前调用既有orphan reconciliation；这项仅改1个源文件，66/66、五次有序投递及第二次重启无重复均是作者对未改测试的报告。

四项prepared-head CI metadata为success，run依次为38891592916、38897024977、38899565434、38895892125。#174203同head另有较早skipped CI，不能合并为一个结果。未取jobs/logs；作者focused数量和历史timing不是本轮执行或补丁性能提升。

下一验收固定packaged Gateway和真实相邻parent，阻塞/失败registry startup，让saved peer replay先到；分别注入temporary policy/overload与永久失权，加取消/已消费/reset/revoked/合法对照和并发pending-final替换，再真实重启两次。独立PID、SQLite、receipt、lifecycle、现行device/role和provider/effect记录必须证明5条合法update有序且一次、永久notice一次、临时custody不丢。任何误结算临时失败、重复/越权效果或覆盖新intent都失败。

**H2/H4：摘要触发阈值与输出预算分开。** pi#11036移除0.8reserve/0.5reserve/4096的本地summary maxTokens；旧reserve参数保留但忽略。源码可证明“不再传固定cap”；provider怎样根据真实request/model/context定额只是作者与docs陈述，本轮没追provider实现或实际wire。旧cap断言被删除/改写，routing/thinking和split usage断言保留；无质量、recall、token/成本或真实provider实验。

下一门槛先固定parent/head/provider/model，核对manual/automatic/overflow/branch/split/routing/restart下实际wire与策略快照，将reserve trigger与reasoning/output/context上限独立变化，含zero/unknown cap及near-full input。overflow、静默截断、错误routing、重试/重启预算漂移都否定预期收益。H4原真实Pi/ACP/MCP replay及reward版本门槛继续保留。

旧checkpoint/kill源文件在截止tip`3bf1c1b3…`仍为blob`9bd72cfe…`/`4aac65c3…`，完全未变；长checkpoint-tail、kill请求到settlement前crash、精确receipt、第二次重启及真实效果门槛未清除。OC#130973为8月旧提案的新合并，仅正文triage，不作第三簇。本次来源审计未执行上游测试或模型。结构化证据保留完整SHA/parent、实际作者、请求hash与CI边界。


**H1 设备测试边界。** FLA [#1452](https://github.com/fla-org/flash-linear-attention/pull/1452) 和 [#1487](https://github.com/fla-org/flash-linear-attention/pull/1487) 的新 A2 test job 均在 Initialize containers 以 exit130、custom container failure、runner shutdown signal 结束；checkout、环境检查和全部 unit/graph tests 为 skipped。这是未执行数值测试的基础设施失败。相同 head 的 A2 benchmark job 元数据为 success，但未审日志/产物，不能推出速度或 activation correctness。H100 仍 queued；两 PR 源码 head 未变、未合并，非 Nathan 新贡献。见[精确 job/log 收据](evidence/2026-10-16-a2-ci-infrastructure.json)。

[源码及 CI 元数据收据](evidence/2026-10-16-recovery-settlement-and-summary-budget.json)。本轮独立 H1 history 实验的结果另列，不用于升级 H2/H4 的执行状态。
