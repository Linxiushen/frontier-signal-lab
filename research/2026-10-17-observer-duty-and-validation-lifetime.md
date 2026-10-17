# 观察器开销：先保留失败的结束屏障

本轮产出是可运行代码、冻结协议、176 份原始收据，以及一次实际训练测量的审计失败。
**完整验收未通过**，不是研究质量或压缩收益的正结果。

四个全新 Pythia-14m 进程按 OFF / ON / ON / OFF 顺序，各用 seed 503 和相同
16 个批次进行稠密 AdamW 更新，共 4 次加载、64 次更新。初始/最终参数哈希
和完整 16 项 loss 轨迹一致，但控制器在收到 worker 的最后一次 continue 确认前，
就进行了存活检查并发出 finish。冻结审计四组均拒绝这一时序条件：5524/5528
通过，4 项拒绝；增加本地文件核验后为 5528/5532，仍是同四项拒绝。
20 个保留进程最终正常退出、4 个 Job 归零，也不能补足缺失的先后关系。

两对 ON/OFF 耗时比 1.059954 / 1.111302 仅保留为未验收研究的描述值。
全局 Toolhelp 查询占所选查询区间的主要耗时，值得后续单独设计减负对照；
这不等于已证明 8.5% 训练开销。ON 内存只是实际解释器当前读数的采样下界，
OFF 未采样；不推断反向峰值、显存节省或模型质量。

见[完整结果与原始数据](../results/observer-duty/report.md)、
[预注册和复核命令](../fixtures/observer-duty/README.md)。下一轮如继续，必须新冻结
“确认 continue 被消费 → 保留 handle 存活检查 → finish”的真实训练版本，
先用延迟确认 mock 检查禁止提前结束；本轮不修冻结代码、不重跑、不调阈值。
之前六组成本/终评失败、无效历史 RSS 和 H3/H4 未执行状态均保持。

## 两条新的公开合并证据

FLA [1419](https://github.com/fla-org/flash-linear-attention/pull/1419) 的作者是
adenzhou1350，合并者 yzhangcs，并非 Nathan Chen 的贡献。旧提案于本轮
10:20:46 UTC 合并为 c067059d：packed IPLR 最终状态按真实序列数 N 分配，
而不是展平后的 batch 数 B。两份完整 kernel AST 和旧测试 AST 不变，新加
10 个 packed 用例。24 个 GB200 测试通过属于作者报告；当前读取未审阅数值日志
或运行 GPU。PR-head 的标题检查失败、landed A2 取消和 benchmark 进行中均保留。
我们据此提出的检验条件是：状态基数、空序列、初态和梯度语义必须先一致，
才能解释所谓内存节省；不据此推断私人研究计划。

Peter 的 OpenClaw [175399](https://github.com/openclaw/openclaw/pull/175399)
于 10:05:51 UTC 合并：只共享重叠的、相同 prewarmed build 的待定完整性校验，
各调用者保留取消与成功记录，校验完成/retention/替换后不延续旧信任。源码加入
12 并发调用、一个取消、后续等长篡改和 retention 分隔对照。PR-head CI 为
49 成功/27 跳过，而 landed primary CI 只有 1 成功/41 跳过，不能视作等量复验。
下一可证伪问题是校验观察的有效期限、各调用者取消和持久 effect 的归属，
需真实 harness、篡改注入和两次重启；本轮没有执行这些上游代码。

41 次选定 GET 均成功，5 组补丁精确重建相邻 parent 到 landing 字节，
来源代理 256 项和 root 独立 153 项离线核验通过。
[来源快照](receipts/20261017T104831Z-reviewed-sources.json)与
[独立核验](receipts/20261017T104831Z-root-source-review.json)区分作者自报、源码事实、
CI 元数据、本项目推断和实际执行。

## 覆盖与时间

本轮实际开始 2026-10-17 10:48:31 UTC。GitHub cutoff 为 10:49:04 UTC，
请求持续至 10:53:32 UTC；7 人、10 仓库，没有错误，14 个端点有截断盲区。
24h/72h/7d 当前事件数为 178/252/263，current-only 为 69/68/68，
changed-shared 为 12/13/13，prior-only 为 41/48/48。窗口重叠不能相加，
mutable PR updated 时间改变样本归属；prior-only 不代表删除，也不是所有事件
都属于新技术提案。保留样本未发现新原创仓库。

浏览器另读 Nathan 公开原帖的完整英文原文，内容仍是 10 月 15 日离开 Kimi，
没有宣布新雇主；首次完整读到旧帖不是新发布。Guangxuan 主页为当前自述，
没有由此确认新技术发布或入职日期；另外五人的个人 X/博客本轮未读。
Scanner 不自动覆盖 X。见[覆盖记录](receipts/20261017T104831Z-coverage.json)。
本轮没有对外发消息、评论、issue、PR 或社交帖子。
