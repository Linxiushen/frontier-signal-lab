# 六个提供方 payload hook 调用点接入取消边界（源码记录）

OpenClaw [#191261](https://github.com/openclaw/openclaw/pull/191261) 于2026-11-02 18:33:25Z合并，原作者SunnyShu0925，合并者obviyus。实际审查边界为父提交 `f9478d593c96c955db06923f4aa6367fb2825b61` →落地 `1c03d49956edc1f6f1b62726023bbc70e7bed355`；候选head为 `f205f1782ab4d18c1a739d02326f3f306ff5fafb`。公开仓库、非fork及当前MIT许可已用后台API/不可变原文核验。MIT全文随证据保存。

已有#191090只把Chat Completions的payload等待接入取消感知helper；这次新增Google Interactions、shared Google Generate Content、Mistral、Codex Responses请求owner、shared OpenAI Responses lifecycle与managed Responses client六个调用点。它们在继续构造/发送请求前改用既有 `awaitProviderLifecycleCallback`。Codex重构仍保持hook前捕获用户内容、hook后恢复用户内容与compaction检查的顺序。Anthropic来自更早#191024，这次保留在矩阵内，不计入新增六点。

helper先检查AbortSignal，将callback排入Promise并交给可选 `observePendingProviderWork`，随后竞争取消并在成功后重检。调用者可以先收到终态，callback仍继续运行；默认library host没有该可选观察端口。取消响应、后台work drain和已提交外部效应因此仍是不同端点。这里没有强停任意host代码、pending work总量上限、持久化托管或关闭耗时保证。

新的完整测试文件列出十个入口：Anthropic SDK/fetch、Completions direct/managed、Google Interactions/Generate Content、Mistral、Responses direct/managed、Codex Responses。每入口分别让hook晚resolve/reject，共20个矩阵cell；Codex明确选SSE。断言取消终态先于hook结束及drain、晚结果不替换终态、mock fetch无晚派发。这是十个具名入口的设计覆盖；我们没有穷举全部provider/plugin/custom adapter、WebSocket、retry/replay或compaction分支，不能把标题“every adapter”当成全路径实测结论。

[维护者obviyus的公开报告](https://github.com/openclaw/openclaw/pull/191261#issuecomment-6584785004)另述Node24.22.1无凭据Docker中source-built Gateway、正常provider-plugin慢hook、本地Responses SSE及真实chat.send/chat.abort：baseline两次4926/5105ms，候选18/7ms；每个build两次未取消control完成一次HTTP请求与预期history回复，并报告26/26focused tests。我们完整读了该报告，未独立执行、未核验其原始运行日志或精确head CI；这些数字属于作者报告，既非本项目测量，也非真实模型或生产收益。

证据保留全部12路径的父/落地差异和22个完整版本字节。6个变更版本全文阅读，16个仅变更hunk/调用上下文阅读；额外6个完整版本中3个全文、3个限定范围。全部12路径的实际新增/删除行多重集合与PR patch匹配，11个存在的落地blob均匹配落地commit API。assertion-safety baseline的完整落地blob与PR-head file blob不同，但实际父/落地16→15的allowance差异一致；不推断whole-blob差异原因。首次误查不存在的provider-work-lifecycle.ts得到404并保留，实际owner已在transport-stream-shared.ts定位。这不是完整依赖或全路径审计。

这只新增源码/测试设计证据。没有本地上游测试、native运行、模型加载或科学实验，不采用新runtime，不扩展observer前置项。H1负结果/invalid RSS/原5GiB门槛、H2并发冻结审计失败与事后观察的区分、现有next gate及H3/H4全部保持。
