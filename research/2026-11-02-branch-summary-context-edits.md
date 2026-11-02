# Pi 分支摘要补齐 context_edit 投影边界：源码审查

2026-11-02 09:55:30Z 合入的 [Pi PR #11680](https://github.com/earendil-works/pi/pull/11680) 修复了一个实际摘要调用链中的上下文不一致：自动重试已经从实时模型上下文隐藏的失败回复，仍可能进入 `/tree` 离开分支时的摘要输入；内容替换也被忽略。原报告 [#11602](https://github.com/earendil-works/pi/issues/11602) 创建于10月30日，本轮核验的是新合入实现，不将旧报告叫作新发布。PR作者是 robopipi[bot]，合入者是 davidbrai；不因仓库关联而将实现归给 Mario Zechner。

核验版本是父提交 `6ab6c1e0e431a55ddfdd804f35c16073b1031e56` 与落地提交 `d0fe213089aef0599aa9c90bf910c8b562e0dcf8`。三个改动路径的精确差异均已读取；完整读取了分支摘要实现和对应测试的父/落地四个文件版本。另四个 session-manager/AgentSession 版本完整保存，但只读取指定函数和调用范围，不声称完整依赖审计。

实际调用方是 `AgentSession.navigateTree(..., {summarize:true})`：收集旧叶到公共祖先之外的时间顺序条目，经过可接管或取消的扩展钩子，默认调用 `generateBranchSummary`。后者先执行 `prepareBranchEntries`，再转换并序列化消息，沿原会话 streamFunction、认证、取消 signal 和重试设置调用摘要。两版 AgentSession 字节完全相同。

父版直接把 `message` 条目的原始内容加入摘要。落地版先遍历被收集的条目，按 targetId 保留最后一个 context_edit，然后对 message/custom_message 使用已有的 `projectContextEntry`：null 省略该条目，其它替换只改变投影内容。此后才提取当前消息中的文件操作和估算 token。因此隐藏或替换后的内容决定本次摘要消息与其预算计算。toolResult 仍先跳过，已有 compaction/branch_summary 转换和累计文件摘要详情路径保留；不能把此修复泛化为所有历史、扩展生成摘要或既有摘要详情的清除机制。

共享投影函数本体没有变化，session-manager 仅新增导出与说明。其既有 `appendContextEdit` 检查目标存在且在当前分支、可编辑类型为 user/assistant/toolResult 或 custom_message，再追加编辑条目；恢复方法 `_omitRecoveryAttempt` 对失败消息及相关 toolResult 追加省略并刷新上下文。自动重试调用在等待可取消退避之前执行该方法。默认分支摘要由此使用与实时投影相同的内容规则，而非改写原始历史。

新提交测试是直接调用 `prepareBranchEntries` 的固定条目测试：同一数组中一个失败 assistant 被 null 省略、另一个 assistant 被替换，断言用户内容与替换内容存在、失败和原文不出现。现有四个测试也使用模拟 streamFn，检查 thinking 设置、tool choice、工具调用和截断错误。PR作者另报告四组测试、faux provider/AgentSession 端到端前后复现及未修改 main 也出现的六个类型错误；这些是作者陈述。本项目未执行这些测试、真实 Provider、模型、Pi 原生会话或进程重启，也未核验该PR全部托管CI。

工程含义是为同一版本化原始条目建立统一投影后再进行摘要和预算，避免失败重试内容跨摘要边界再次进入模型上下文。长会话的瓶颈仍包括原始历史增长、分支扫描、摘要 token 和重试成本；新 Map 随编辑目标数增长，不是有界内存或吞吐实测。后续如单独采纳，应固定一个真实 AgentSession 分支工作负载，比较实时投影、序列化摘要请求与两次重启后的消息/预算一致性，覆盖同目标多次编辑、null/替换、工具配对、扩展接管、取消及失败重试，并报告成功率、有效吞吐、尾延迟与峰值资源。验收应要求已隐藏的失败文本零次泄漏、最终替换一致、分支身份和当前权限不变；性能指标需实测，不能由源码推断。

本记录只提供源码与测试设计证据。当前本项目 H2 仍优先同一个已固定可选原生服务的 busy/submit-error/request-ID-content-collision gate；不更改 H1 既有负结果或 H2–H4 状态，不触发额外科学实验。
