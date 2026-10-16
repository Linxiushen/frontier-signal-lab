# A2 的真实数值日志，能证明哪些范围

FLA 在不可变 merge `c12db31575ad9e5d80214bfe3938671321e60c47` 上的 [A2 测试作业](https://github.com/fla-org/flash-linear-attention/actions/runs/38911468095/job/117008149029) 于 **2026-10-16 16:13:07Z** 完成。完整日志记录所选并行测试 **1,617 passed / 409 skipped**；另行串行执行的 `tests/ops/test_kda_graph.py` 为 **15 passed / 16 skipped**。这是一条本轮新增的公开执行证据，区别于只读源码或绿色状态摘要；本项目没有在本地执行上游 NPU 测试。

环境自报 Ascend910B3、NPU available=True、Torch2.9.0+cpu、torch_npu2.9.0.post6、Triton3.2.0。日志显示 triton_ascend 的 KDA forward/backward 路由及所选数值对照。完整命令与定位行号见[公开收据](receipts/20261016T164107Z-reviewed-sources.json)。计数仅适用于列出的测试集合，不能外推成所有算子、布局或反向路径都已覆盖。

图测试中，通过的是 callable graph 数值／拒绝分支；普通 CUDA replay、varlen、partial-token 和 CP 场景跳过16项。日志同时保留 `_assert_async.msg`、`linalg_inv_ex.inverse` 的 CPU fallback，以及 Gluon `constexpr_type` 导入失败导致的跳过。整个所选测试日志没有 HGRN 记录，因此它不能直接验收 PR1435 的 expanded lower-bound／checkpoint migration；也不能消除此前 PR1426 H100 dispatch fallback 测试失败或解释 PR1492 缺失的失败日志。

[A2 benchmark](https://github.com/fla-org/flash-linear-attention/actions/runs/38911468441/job/117008130766) 14:50:14Z 完成的元数据在前轮已经观察到，本轮新读的是运行日志，不能再称新完成。日志中 KDA B1/T8192/H96/D128 的绝对时延为 forward30.753ms、forward+backward91.452ms。没有匹配的旧版本基线，不能推出跨版本加速、训练成本或模型质量收益。同一 head 的 eager/graph smoke 也不能替代这种比较。benchmark artifact 未下载。

| 原始公开日志 | 字节数 | SHA256 |
|---|---:|---|
| Selected A2 tests | 665459 | `bb7c8917fe989083c3a3344403bde7a538a1b1dc4eb97077934e35331e2a36af` |
| A2 benchmark | 112728 | `d7e284b2224b3e0df1edd01085924054edc655f6223f0963401a3de7aa8ba966` |

本轮 H1/身份核查共84个公开 GET，均HTTP200；有界 API／索引／作者别名仍有盲区。Nathan 的自有仓库名字未变，三个固定作者提交窗口与三个索引搜索未发现新结果。旧 TileLang draft1465 的新回复只是请求验证建议，原八个提交仍来自7–8月；没有把它算作新研究。固定11个非X主页／feed内容未变，X只另行核查5个可见原创、已知离职原帖全文及有限旧回复，仍没有新雇主公告。

本项目的 H1 推断：硬件与分派的验证范围正在变得更明确，但这与残差保存压缩的训练收益是两条证据链。既有六组完整成本／终评失败继续保留。本轮只进行独立的 Windows 进程观察器工程验收；不重跑模型、不从上游设备 CI 推导压缩质量或速度。
