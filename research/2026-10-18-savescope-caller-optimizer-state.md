# SaveScope 接入现有 AdamW 状态

本轮交付 SaveScope v0.2 的可复用功能：

```python
result = audit(model, lambda m: m(x), lambda y: loss_fn(y), optimizer=optimizer)
```

API 在 callback 前捕获现有优化器的 m/v/逐参数步数；dense、int8、
int8_keep_sensitive 各自从同一状态的独立克隆开始。调用者优化器不会被
step 或 load。缺失状态保留 lazy 初始化；本次没有梯度的参数不推进步数、
不衰减权重，也不改动已有动量。

支持范围是一个参数组、按对象身份精确覆盖所有可训练参数的原生 AdamW，
CPU float32，普通标量计数器。多组、特殊执行 flags、定制 step/hook、
无效数值以及状态与注册参数/buffer/已有梯度共享存储均在 forward 前拒绝。
callback 或并发操作修改优化器属于不支持的外部副作用：检测后拒绝，不代为恢复。

2026-10-18 11:34 UTC，预先冻结的 seed20261018 微型 CPU 案例只执行一次，
16 项控制通过。dense 与独立克隆原生 AdamW 的参数、更新、有效梯度哈希逐项一致；
fresh-reset 负控产生不同更新；未使用参数及异常路径符合约定。
43 项相关工具测试通过，零跳过；wheel 的隔离导入与离线回放通过。
首次单元测试中的 deepcopy-grad oracle 错误和首次审查中的 CRLF/LF 哈希
解释错误均保留并修正，冻结案例未重跑。完整配置、轨迹和哈希见
[结果](../results/savescope-optimizer-state/report.md)。

这是工程集成结果，不提高 H1 的科学置信度。此前六项成本与封闭终评失败、
无效的历史 parent RSS、真实成本和训练门槛仍保留。H2 的持久化/恢复与
实际 provider 效果、H3/H4 的执行门槛也没有改变。

本轮公开信号扫描未选出需要另起来源审查的新技术事件。GitHub 七日扫描仍有
15 个仓库端点及 6 个发现端点截断；7 个仓库讨论未启用。支持浏览器不可用，
另以公开 API 核验三个作者 RSS 与 Nathan 离职帖的有限摘录；主页仅取 HTML
源文本，不能称为浏览器核验或全 X 覆盖。Nathan 的新去向仍未知。
