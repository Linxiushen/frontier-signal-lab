# 动态长度编译成本与恢复资源的释放边界

本轮公开源码信号支持两项后续研究：把动态长度的首次编译／调参停顿从稳定内核时间中单独测量；让代理任务的容量释放跟随其持有工作的实际收尾，并分别定义归档、身份替换和流内错误的可见结果。这是我们从公开变更提出的可证伪假设。没有运行上游实现、复现其性能数字或据此推断任何人的保密路线；H1成本／终评、H2完整Gateway harness和H3/H4执行状态均不升级。

本页时间均为2026-10-16 UTC，历史日期另标。H1目标区间为`(16:42:16.494056,18:45:43.102653]`；H2/H3/H4为`(16:41:07.222262,18:45:43.102653]`。主扫描cutoff另为18:46:52.231226；随后读取到的运行状态是观察上下文，不等于发生在目标窗口内的新事件。

| 公开对象与实际作者 | 本窗口新增事件 | 日期／状态边界 |
|---|---|---|
| FLA [1494](https://github.com/fla-org/flash-linear-attention/pull/1494)、[1495](https://github.com/fla-org/flash-linear-attention/pull/1495)，Windyskr | 17:39:33／17:39:36新建PR，减少动态长度专用化／调参重复 | 均open、非draft、未合并；1494代码07:01作者日期／17:35提交日期，1495提交07:19，后者新增的是提案公开事件 |
| FLA [1470维护者评论](https://github.com/fla-org/flash-linear-attention/pull/1470#issuecomment-6221639232)，yzhangcs | 18:02关闭未合并的历史修复 | 正文称原作者TimDarcet；保留head是7月9日zhiyuan1i的合并，不能把merge作者当原修复作者 |
| FLA [1493](https://github.com/fla-org/flash-linear-attention/pull/1493)，yzhangcs | 16:51:20提案、18:22:26合并共享modeling／checkpoint helpers | Git作者／提交日期18:22:25；65文件已列清单，只深读5个核心patch |
| OpenClaw [174442](https://github.com/openclaw/openclaw/pull/174442)，steipete／Peter Steinberger | 16:45:24提案、16:59:50合并归档恢复静默取消 | exact prepared-head CI成功；未读取jobs／logs，未执行上游测试 |
| OpenClaw [174262](https://github.com/openclaw/openclaw/pull/174262)、[174295](https://github.com/openclaw/openclaw/pull/174295)，vincentkoc／Vincent Koc | 17:12:49／16:56:09合并容量保留至scope收尾 | 提案13:41:21／14:14:19均早于窗口下界；不是Peter的新提案 |
| verifiers [2881](https://github.com/PrimeIntellect-ai/verifiers/pull/2881)，hallerite／Konstantin Dunas | 17:03:43提案、17:42:07合并SSE错误身份保留 | 不是Will Brown贡献；exact-head Tests失败，原因未核实 |
| OpenClaw [174480](https://github.com/openclaw/openclaw/pull/174480)，steipete | 17:23:40提案、17:39:49合并运行文件打包补齐 | 打包修正，未证明新生命周期行为；exact-head CI失败 |

这些FLA变更均不是Nathan Chen的新贡献。作者字段、提案时间、提交时间和合并时间分开保存；仓库属于某位关注者，不意味着其中每项改动由其完成。

1494从长序列token_shift的autotune键、签名和launch中移除未用的`NB`；读取的完整[固定head源文件](https://github.com/fla-org/flash-linear-attention/blob/2261092e7a2b45a7d3c54a6cd05887811b435444/fla/modules/token_shift.py)已无`NB`，但host驱动的`BT`仍为constexpr。1495把PaTH backward helpers的`T`／`NUM_BLOCKS`改为runtime参数并排除专用化。两个head的真实相邻parent均为`4b5b38a982ec98061b4a394e733f054d7b4cbbae`；1495 head为`eb034f39ee643ec54b0df5380a3d506353ca2c55`。共读7个patch，不能据此声称所有长度编译都消失。

作者报告在A800、fresh process／empty cache交替运行时，后续新packed bucket的token_shift调用从2.45–5.18秒变为0.8–1.3毫秒；重复配置的稳定内核代价为0–7.5%，某些整数整除条件仍会编译。PaTH后续新长度从0.69–3.17秒变为20–45毫秒，首次编译仍约26秒，warm差异0–0.5%，baseline自身spread最高0.6%。这些数字、正确性／梯度／CP断言来自PR正文；未下载benchmark gist、未独立执行。1495明确未覆盖FlashAttention依赖的forward、Hopper-only和4GPU分支。观察时H100测试skipped、smoke queued，1494 NPU运行中、1495 NPU skipped；没有新增成功数值验证。

因此下一项可证伪实验应在同设备固定parent／head，交替使用独立空cache进程，同时保留首个输入、每个新长度／bucket、编译与autotune次数、选中配置的warm代价和完整梯度。若差异只来自缓存状态、配置重用变慢或遗漏的dense／packed／CP分支，假设就应收缩。当前CPU工程工作不具备执行这些GPU对照的条件。

1470提供另一类反例：维护者接受原始varlen `B>1` dweight问题存在，但拒绝补丁。在读取的[历史head内核](https://github.com/fla-org/flash-linear-attention/blob/a3a65f5036bdd5ebee5ae455509e613424340c1e/fla/modules/conv/triton/kernels.py)中，dense `bos=i_b*T`与新输出地址`i_b*stride_y_n+bos*D`叠加；当连续布局`stride_y_n=T*D`时，batch偏移被计算两次，`B=2`第二个batch的起点已到输出末端。对应backward activation读取也有相似变化。[参考parent](https://github.com/fla-org/flash-linear-attention/blob/7dd7cf5ed265e35f124940107ebc03173ce2bb2a/fla/modules/conv/triton/kernels.py)只使用`bos*D`。这是源码算式核对；维护者所述CPU Triton interpreter／guard-region／poisoned-dweight结果未独立运行，也不是GPU验证。这里只审3个PR patch和2个完整固定文件；历史merge的100文件页面仍有未取下一页，未声称全量审计。

后续独立实现应分别验证输入契约和地址不变量：明确拒绝非法`B>1` varlen，同时保留正常dense多batch、合法packed／B1、非均匀上游梯度和输出guard对照。修复一个拒绝条件不能替代普通路径的forward／backward正确性。

1493合并为[33af5256e9fa3d2776ee25e90cfd8f131b6dc378](https://github.com/fla-org/flash-linear-attention/commit/33af5256e9fa3d2776ee25e90cfd8f131b6dc378)，真实唯一相邻parent为`c12db31575ad9e5d80214bfe3938671321e60c47`。核心patch引入共享attention配置解析／构造，直接使用上游`GradientCheckpointingLayer`，移除本地fallback，把Transformers最低版本4.45.0提高到4.52.4；HGRN lower-bound表达式内联没有算法／性能结论。作者报告216 GPU hybrid测试、212 CPU通过／4 GPU跳过、5000配置差分，以及39个依赖文件398通过／62跳过／12失败，并把失败归因于baseline。该归因没有独立复现；早期72项before／after来自旧revision，也不能当最新head证明。

最新PR head `1411a90b3095d13c26613e218af7de487794ef78`的[H100 job](https://github.com/fla-org/flash-linear-attention/actions/runs/38940895252/job/117107996806)于17:35:53开始、18:22:29取消，`steps=[]`，公开日志返回404 `BlobNotFound`，取消原因未知。PR／merge NPU仍queued／running，部分启动时间晚于本页目标上界。未来模型／观察器接入应固定Transformers与checkpoint路线并比较等价配置／梯度；本次refactor不能转写为训练质量或kernel速度收益。

延续观察中，FLA [1490](https://github.com/fla-org/flash-linear-attention/pull/1490)新增17:53:28 stacked merge `8a02c1e9e9460792d504178138c58da8fe3150ae`，真实parents为旧测试`39fd6d9005aee849132cd01f30de3276f36de5dd`与1487修复`039a3d0134b39a4a3147578205acbd32d780981a`，当前diff为76行测试。正文明确新stacked head没有重跑加速器验证，旧84通过不可重复记作新结果。1487只补依赖顺序；1452 draft→ready无新代码／数值完成。此前A2所选1617项加graph15项通过也继续去重，保留[既有运行边界](2026-10-16-a2-runtime-boundaries.md)。

OpenClaw174442的[落地提交](https://github.com/openclaw/openclaw/commit/0f6f06339f28164aceece0651c837a0f0fd7d6c0)真实parent为`47edda1e4d2294826fff66c0a3d41defff768354`。源码先核对保存的source／target精确身份和destination input ownership。仅归档的endpoint使用当前authority撤回pending input，保留cancelled receipt，记录debug `endpoint-archived`后返回，不写blocked notice／transcript或warning。reset／replacement继续先持久化notice再撤回，原因`endpoint-replaced`；permission／storage路径没有改变。此前归档也需可见notice的源码观察因此被本次变更取代，旧记录仍是当时的历史事实。

变更中的real-SQLite测试覆盖归档source／target与replacement、第二次恢复、cancelled／displayfalse input、无归档dispatch／notice；Gateway subprocess测试使用mock provider。这些源码测试未由我们执行。作者报告27项本地focused通过，并说明未本地跑cold-process。prepared head `070f755f9b45c007c4d1a6c0725f93ffb8f5f724`的[CI38934459057](https://github.com/openclaw/openclaw/actions/runs/38934459057)成功，16:57:21更新；只核对run元数据，未读jobs／logs或证明真实squash与相邻parent已被执行。我们下一道门槛应分别重启这些身份／归档控制，要求取消receipt持久、归档无重放与notice、replacement恰有持久解释，并加入暂时storage／permission失败的健康恢复对照。

Vincent Koc的174262／174295把容量从逻辑状态中分离。Observer digest的独立running reservation在eviction、unsubscribe、replacement、abort或状态删除后仍保留，等待该digest的`AsyncWorkScope` drain后才释放并调度pending。Recap用每次recap自己的scope，在slot释放前drain，同时通过外层`trackAsyncWork`保留connection shutdown custody；不能drain共享父scope而等待自身。落地提交／实际parent分别为[9c5f4589e098875d2d2f9b8bd4f2294aba8f8958](https://github.com/openclaw/openclaw/commit/9c5f4589e098875d2d2f9b8bd4f2294aba8f8958)／`d095f1043e9a1779b2c3c41de318f082110b2b39`和[7e8deb02b6b8934123346937e845e7a31fa54b29](https://github.com/openclaw/openclaw/commit/7e8deb02b6b8934123346937e845e7a31fa54b29)／`9d1d2edbe9c52f856e0924be7d6eed156e0241fb`。正文中的synthetic prepared-merge不能替代这些真实parents。

测试源码使用真实async-work resource／scope owner，配controlled callback、deferred promise和fake timer：observer持有6个reservation而后续等待，recap持有2个而第3个等待，并检查late-output抑制、最终释放、dispose／shutdown等待。它们证明的目标是进程内被追踪工作的收尾合同，尚无live provider cancellation或OS进程灭失证据。observer6、recap2、shared-background2、recovery4属于不同owner，不能相加或当同一个预算。Observer head `3cf474d3d12faf0fa0bf2076180ce55893d9f071`的[CI38933061503](https://github.com/openclaw/openclaw/actions/runs/38933061503)成功并于16:48:03更新；recap head `a6fcb5ac246bea4baa6f5eb802fc858ad8729bc5`的[CI38914177307](https://github.com/openclaw/openclaw/actions/runs/38914177307)14:28:51已成功，早于窗口。新合并不制造新验证运行。

可独立复现的下一步是让任务逻辑完成／abort后仍占住owned cleanup，确认第7个observer／第3个recap不提前启动、cleanup settle后pending恢复、继承shutdown等待不会死锁，dispose后没有迟到输出。更强的远端provider／OS生命周期断言需要额外门槛。此前[恢复与launcher合同](2026-10-16-recovery-lifetime-contracts.md)的checkpoint-tail、requested-kill settlement和第二次restart仍未通过真实完整harness验证。

verifiers2881的[落地提交](https://github.com/PrimeIntellect-ai/verifiers/commit/a0441a9faa2a7227bc3db4ea2947a27e4561c7cf)parent为`a4035acbf51a7a89d663f60d53f190e476708d59`。Anthropic dialect识别HTTP200后的SSE `type:error`，保留serialized provider details并抛`ProviderError`；invalid_request／auth／permission／not_found／too_large／rate_limit／api_error／overloaded映射400／401／403／404／413／429／502／529，未知为502。`stream_error`接收eventual status，keepalive已提交200后仍把之后的status传入，Anthropic未知5xx使用`api_error`。这使client能解释错误，代码映射本身不代表已经执行retry，更不证明task／token／reward正确。

该4文件patch未新增测试。作者报告165单元测试及临时HTTP回归，测试没有独立执行，临时脚本未读取。head `055cec9e1987bf6d3ed7b5d8dc19fb7a768d5bfb`的[Tests38938234723](https://github.com/PrimeIntellect-ai/verifiers/actions/runs/38938234723)失败，17:20:38更新；Style与PR workflow成功不能消除它，jobs／logs未取，失败原因未知。下一道门槛应在keepalive前后重放正常流与各类error，核对eventual identity／status、仅对合格错误有限重试，确认无重复effect／token／reward，并解决失败CI。H3/H4仍为planned_not_executed。

174480在11个文件以+12／-0把`cli-parent-lifetime.mjs`补入依赖`node-runtime-recovery.mjs`的精简／复制runtime closure，是此前174268的packaging修正。落地[7c112970cd9ed304acdc2654a53756d806e5e3cd](https://github.com/openclaw/openclaw/commit/7c112970cd9ed304acdc2654a53756d806e5e3cd)实际parent为`75a6e08f156c8e58ea37a86c771fc2f44e7d248e`；head `888e17e41aefad466195f8b9bfbadfadf55722f6`的[CI38939386670](https://github.com/openclaw/openclaw/actions/runs/38939386670)失败，17:43:11更新。正文称incomplete mock Responses stream，但未取得匹配main job作比较，不能把失败标为继承／修复；另有Doctor fixture失败待解。作者本地reproduction／smoke／build与bot无发现均不是我们的运行证明。

在18:44:54的cutoff tip `0e16643538c1e41ec0d22990738749d2413055c5`，recovery-service blob未变；bash-process blob变更只在读取的两个固定快照之间表现为引入共享`failText`、删除本地helper，共享helper语义未审。完整最终kill分支仍相同：请求cancel、立即清exit notification、可隐藏record并返回completed／“termination requested”。这不构成物理终止证明，也未在没有对应patch时归因于仅见标题的174495。VF2872的Compose命名service策略仍是VM-wide egress，未建立per-service隔离；pi11036作者仍为davidbrai，其未变head／body不是新的badlogic贡献。

H1与固定非X身份核验共90次GET，89成功，1为上述取消H100日志404；离线收据检查517项加身份93项通过。H2/H3/H4使用50次成功GET，筛109条default-main提交标题，OpenClaw108条含完整第2页，verifiers1条，pi／AI-Scientist-v3为0；5个选中落地commit、真实相邻parents、5个PR正文、3个comment thread及31个patch均已读，收据408项检查通过。这里的计数只审数据与来源一致性，不验证上游运行。仓库元数据为public；FLA／OpenClaw／pi／verifiers标MIT、AI-Scientist-v3标Apache-2.0，未做逐文件license审计，也未复制上游实现。

查询按committer时间筛选，并非覆盖所有分支、proposal、review、discussion或release；空comment feed不证明没有inline review。H1的历史大commit分页、索引延迟／alias、未关联邮箱和private branch仍未知。11个固定非X身份／博客原始响应与前次一致；Nathan62个public owned／23个nonfork仓库名单未变，3项有界索引查询与3个命名仓库实际author-date窗口未见新贡献。旧Kimi profile不建立现任身份；这些固定来源未验证新雇主，X原帖由主任务另行记录。没有联系研究者、创建上游issue／PR、购买算力或发布社交信息。

本页来源摘要与不可变commit／patch、时间和覆盖限制见[公开研究收据](receipts/20261016T184605Z-reviewed-sources.json)；原始响应、读取记录、缺页与失败保留在本地run。独立[Windows observer工程结果](2026-10-16-process-observer.md)及其新workload接入另行记录；既有自然文本六组联合成本／终评失败、无效旧parent RSS及未建立的历史实际worker cap继续保留，不能由本页源码信号修复。
