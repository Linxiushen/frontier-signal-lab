# 整体绿色作业与内嵌 dispatch 失败

本轮 FLA 的实质新信号是验证边界，不能据此声称内核数值错误或性能收益。
事件窗口为 `(2026-10-16T12:42:56.583839Z, 14:43:29.3684848Z]`；
专项读取发生于 14:46:37–14:51:32 UTC。86 次公开 GET 和 505 项离线检查
保留于本地原始收据，所选事实见[结构化证据](evidence/2026-10-16-dispatch-log-boundaries.json)。
没有执行或复制上游实现，以下也不是 Nathan Chen 的新贡献。

- [#1426 的新 bot 报告](https://github.com/fla-org/flash-linear-attention/pull/1426#issuecomment-6217454712)
  发布于 14:16:36。精确 head 为 `39c5f90d0f857bc13343c75bf2428e34e81494bb`。
  [H100 ops 作业](https://github.com/fla-org/flash-linear-attention/actions/runs/38837144685/job/116768729804)
  整体标为 success，但完整 430,357 字节日志记录 dispatch coverage exit 1：
  dispatch 测试共 1 failed / 78 passed，失败用例为 `hardware_fallback`。Gluon capability 拒绝后走
  TileLang，`torch.empty` 收到测试使用的 `SimpleNamespace` 假设备，发生
  TypeError，尚未进入数值比较。bot 的“backend disagrees”概括不能代替
  这个实际错误。Models 作业当时仍 queued；draft 未合并。
- [#1435](https://github.com/fla-org/flash-linear-attention/pull/1435) 于
  13:54:11 合并为 `c12db31575ad9e5d80214bfe3938671321e60c47`。
  这是 taking-lying-flat 在 9 月 30 日写出的旧 HGRN lower-bound shape
  修复，由 yzhangcs 恢复、合并。正文中的历史检查和非默认 checkpoint
  迁移说明未在本轮复现；不能当成今天新完成的训练验证。
- 已存在的 #1492 在 12:43:40 出现一个新的
  [A2 benchmark failure](https://github.com/fla-org/flash-linear-attention/actions/runs/38890251848/job/116937764820)。
  精确 head 为 `1cee0e3c5b1075be3554a83b9583a6ea06d92a78`，job 无 steps，
  公开日志返回 HTTP404 BlobNotFound。原因未知；作者所说 unrelated failure
  是未经核验的归因。旧正文性能数字也没有升级为当前结果。

本项目下一验证必须检查实际 dispatch route、完整 backward 和非阻塞子测试
的退出码，同时保留正确设备、fallback、合法布局与尾块对照。整体作业绿色
不能覆盖内嵌失败，日志不可取也不能推断基础设施或数值原因。H1 的本地训练、
真实设备成本与质量门槛由独立实验决定；这些上游记录不清除任何门槛。
