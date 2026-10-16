# 因果前缀、实时配置与工作进程的退出责任

本轮公开证据强化了两个可检验问题：注意力算子的前缀输出和梯度是否受未来输入影响，以及长期运行的agent能否在配置变化、重放和退出期间保持准确的权限与资源责任。这是对公开项目工作的研究判断，不代表任何研究者或机构的未公开计划。

本轮扫描覆盖七人、十仓库，截止2026-10-16 20:45:53Z，实际读取20:45:53–20:50:18Z。24h／72h／7d分别保留166／233／250条主事件；三个重叠窗口均有54个相对上轮新出现的身份，全部晚于旧截止，另有16个同身份变化。窗口不能相加，旧样本缺席也不是删除。14个端点可能截断，六人的原创仓库发现列表截断；没有完整覆盖的“零新增”结论。快照canonical hash、文件hash和报告重新生成均通过。

## H1：因果性与相邻测试的证据边界

[FLA1496](https://github.com/fla-org/flash-linear-attention/pull/1496)由yzhangcs整合xy200303旧1452贡献，于20:41:03Z合并为`e4adbb8f8f2124df611f31101d41a1c98ba648fa`，实际相邻父版本为`33af5256e9fa3d2776ee25e90cfd8f131b6dc378`。不是Nathan的新贡献；其18:46:39Z提案已进入上轮主扫描，本轮新增的是合并和详细核验。

GPU Triton safe_gate把依赖未来行／序列长度的anchor改为首个累计gate加固定shift，forward和backward使用相同默认强度2。新回归只改变未来gate，要求前缀输出及前缀损失下支持的全部梯度严格相等；它明确跳过CPU／NPU。四个完整patch和两个固定源码文件支持这个源代码结论。作者GB200报告128pass／4skip来自中断后续跑，strict60pass仍是作者声明；CP8fail／1skip的“与基线相同”归因未独立复现，阈值未放宽。两次取消的NPU测试日志没有GDN2节点结论；通用container失败不能证明取消原因。一个NPU benchmark有七种形状的时间，却没有同设置候选／基线对比，也不验证GPU前缀因果性。

[1490](https://github.com/fla-org/flash-linear-attention/pull/1490)的新A2实日志在20:33:34Z完成，stacked head对应synthetic checkout中有84个独立singleton-stride通过；选定模块总计1703pass／409skip，另有graph15pass／16skip。[1494](https://github.com/fla-org/flash-linear-attention/pull/1494)的新A2任务在19:40:09Z完成，选定模块1617pass／409skip和graph15pass／16skip，但未选择`test_cache.py`。两者包含CPU inverse fallback与Gluon导入跳过；不能变成全路径NPU、H100数值覆盖或A800冷编译加速证明。

[1404](https://github.com/fla-org/flash-linear-attention/pull/1404)的Alfred Wong新相邻commit`888c2da6e8acbbff8829e201053c98f39d12b1eb`只修改两份测试：BF16形状扩展，以及graph replay中切换mild／−200／−1e8／mild gate和初始状态，比较输出、状态、梯度并防止输入状态被改写。不是新kernel或新性能结果；B300运行数字仍是作者声明。

下一问题应分别检验未来输入不变性、recurrent-reference误差、graph动态状态和具体硬件成本，不能用其中一项代替其他项。现有H1六组成本／终评联合失败、无效历史parent RSS、CPU INT8较慢及SaveScope fresh-state API边界均保留。

## H2／H4：退出、重放和实时配置

Peter Steinberger的新[174633](https://github.com/openclaw/openclaw/pull/174633)把preparation client纳入明确的退出责任：close拒绝新准备工作、等待已接纳工作、关闭资源和pool后才释放root／capture；失败保留责任。另一个[174558](https://github.com/openclaw/openclaw/pull/174558)将durable intake与数据库准备分开，仍共享输入预算与物理owner检查；跨pump32个active start和另行32个released deferral不是同一额度。后者prepared-head CI失败，作者“继承失败”的归因没有日志核验，不能写成已验证。

Vincent Koc的[174540](https://github.com/openclaw/openclaw/pull/174540)只把准确的`thread/closed`当作卸载完成，并允许准确的`thread/resume`、−32600 closing拒绝在原两秒期限内重放一次，每次重查authority／abort；不延长期限，也不把模糊错误当未接纳。其[160765](https://github.com/openclaw/openclaw/pull/160765)将保护性压力循环与可关闭诊断分开；注入计数／假时钟测试不证明真实OOM、内存收益或采样成本。

RomneyDa的[174571](https://github.com/openclaw/openclaw/pull/174571)把Windows pipe完成条件改为`write`接纳，保留擦除／销毁。字节被接纳、被子进程消费、采用指定认证身份是三个独立门槛；CI绿色也不能替代被跳过的Windows lane或未执行的认证测试。

Mario Zechner的[pi7ec1](https://github.com/earendil-works/pi/commit/7ec1f648e9b21391ab2a886d3ef8325945660d6d)在使用时解析model／settings getter；四个MemoryStorage／假provider测试没有证明跨多次await的决策来自同一版本。可证伪问题是：解析、排队、tool读取到实际effect之间修改配置，是否出现权限／模型版本混用。需要持久化重启和真实effect回执，逐次新鲜不能自动保证整体一致。

Konstantin Dunas的新合并[VF2860](https://github.com/PrimeIntellect-ai/verifiers/pull/2860)增加固定版本DeepSeek minimal native ACP、per-trace状态和可选外部批准；不是Will Brown的新代码。旧prepared-head成功发生在本轮窗口前，七个patch没有新assertion测试文件，作者Docker／MCP／Prime运行数字未独立核验。H4仍需真实wire、stored message、token／mask／reward与teardown的固定版本配对实验。

这些是源代码与有界CI元数据。九个已知PR／CI、两个recovery／bash residual blob未变化；checkpoint-tail、实际kill完成、二次重启和完整harness门槛仍未执行。H2状态不变，H3／H4仍为planned。

固定的11个本人网站／feed响应与上轮一致。单独支持浏览器读取Nathan主页的四篇可见原帖和已知离职帖英文全文，仍只确认离开Kimi；没有下一雇主公告。其余六个X时间线、完整搜索和全部回复未覆盖。旧帖首次读到不作为新发布。

[本轮可审查证据、commit、相邻父版本、CI与hash](receipts/20261016T204339Z-reviewed-sources.json)保留54次GitHub H1读取、72次H2／H4读取与11次固定网站读取，全部HTTP200；375／605／97项离线检查是回执一致性检查，不是独立运行上游。原始rolling抓取保留在忽略目录，没有发送消息、评论、issue、PR或社交帖子。
