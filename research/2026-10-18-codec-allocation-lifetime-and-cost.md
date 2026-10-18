# INT8 节省的保存张量，需要把临时工作区与时间一起算

本轮完成一个独立冻结的八 case CPU 实验：固定 Pythia-14m、seed 503、同一自然文本 batch，每个 worker 一次加载、一次 exact-loss 前向和一次反向，优化器更新为零。八 case 均通过；冻结保存证据审计 739/739，独立复算 13,925/13,925，三项预声明的保存证据篡改均被拒绝。之前的 v1 preimport 失败保留原样。

在前向结束的选定注册存储子集中，dense 为 37,321,728 B，INT8 为 34,628,096 B，差 2,693,632 B。19 个 eligible source 合计 3,604,480 B，INT8 code/scale 为 910,848 B；反向还会创建合计 3,604,480 B 的 decoded backing。最大的单次 pack callback 临时 requested-live 小计为 524,800 B，不能用其累计分配量 1,575,089 B 代替峰值。详细生命周期及复算脚本见[完整结果](../results/codec-allocation-v2/report.md)。

两个 OFF 配对的 INT8/dense 算子时间比为 1.108977、1.076496，几何均值 1.092616。dense 与 INT8 的 ON/OFF 几何均值分别为 1.207221、1.204161。每格仅两次、固定顺序且 OFF 全在 ON 前；这是描述数据，不是因果观测开销估计或普遍速度结论。ON/OFF 同方法 loss 与梯度摘要一致，不能解释为 dense/INT8 梯度相同或模型质量通过。

这些是 PyTorch CPU allocator 请求字节和选定 StorageImpl 的强所有权生命周期。原生 allocation ID 缺失，按预声明的无歧义 pointer epochs 绑定；每条轨迹保留 78 个右删失分配。选定子集包含 exact/parameter backing，既不是纯 residual bank，也不是进程 RSS/private、OS 返还容量或 GPU 峰值。四条完整轨迹从模型准备前开始，累计请求量也不是训练峰值。

本轮实际套件只执行一次，无重试。48 项冻结前受保护测试通过；扩大可移植测试时，先遇到 -S 缺 NumPy 和临时测试 runner 的路径/可选依赖暴露错误，并发现旧冻结测试把计时器里的字符串 `443` 当成端口泄漏的假阳性。所有失败日志保留，未修改旧冻结测试。正确仅暴露 NumPy、隐藏 ML 库的 profile 最终运行 915 tests、67 skipped、零失败/错误；此测试不再执行模型。验证记录见[validation.json](../results/codec-allocation-v2/validation.json)。

H1 的历史六项自然文本联合成本/终评失败、旧 parent RSS 无效结论不变。下一项有价值的门槛仍是独立声明、固定数据与封闭终评的 matched dense/bank 训练成本实验，连同打包/取回成本和适合目标指标的实测内存与观测对照；本轮不能宣称训练收益。另对已知旧论文中评估协议漂移的[一手复核](2026-10-18-evaluator-protocol-drift.md)，仅补充 H3/H4 的 proposed gate，尚未执行。
