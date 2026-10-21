# 2026-10-21：实际训练调用方失败与未评分回放语义

实际训练调用方接入ledger的一次冻结尝试在导入完成回执前超时。零模型加载、零更新；预注册的第二故障用例未运行。本轮消耗一个科学/模型执行尝试名额，不重试。五个保留进程退出、Job清空与两条776字节记录得到独立保存字节核验，但冻结验收仍失败。[完整原始记录](../results/training-ledger/report.md)区分源码接线、已执行preimport边界与未执行训练。下一步继续该调用方内的有界导入证据，不能以不断扩展孤立诊断替代实际集成，也不能把超时归因于冻结前已记录的Python文件变化。

另核验PrimeIntellect Verifiers的新合并[PR2935](https://github.com/PrimeIntellect-ai/verifiers/pull/2935)和[PR2936](https://github.com/PrimeIntellect-ai/verifiers/pull/2936)：前者在16:03:23Z合并，rubric支持显式分数映射，零权重项不参与加权；有权重的NaN会留下未评分结果，rollout完成评分后把相应reward置为None并以UnscoredError失败。后者在16:55:53Z合并，对Task.rescore加入对应的NaN拒绝。两者均晚于上一轮扫描cutoff；这与PR的最初创建时间不同。

上述事实来自精确落地版本的完整源码与Git blob/内容hash核验，[回执](receipts/20261021T174423Z-verifiers-unscored.json)记录具体版本。没有在本地运行Verifiers、复现其测试或验证下游训练行为。我们的工程推断是：H4真实runner必须把rubric/评分代码版本、未评分与零分的区别、attempted/scored/failed分母及重试/恢复绑定一起；weighted-NaN和zero-weight-NaN应是不同控制。源码合并不证明完整client→wire→score路径或恢复一致性。H1六项失败、历史parent RSS无效及H2–H4未满足门槛保持不变。
