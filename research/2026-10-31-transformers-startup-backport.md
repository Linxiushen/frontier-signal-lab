# 将启动阻塞收敛到一个具体初始化改动

H1 的实际调用方仍是 `native_training_cost.py` 的完整 dense/INT8 训练套件。
原 20 秒 postimport 失败及 15 秒单次栈观察全部保留；栈位置不能证明根因。
本次没有重复观察、延长期限或启动模型。

静态检查发现，固定的 Transformers 4.57.3 在构建全模型导入结构时使用
`listdir` 和重复的 `isdir`。本地模型目录含 1,957 个 Python 文件、
45,057,855 字节及 409 个非缓存目录，没有发现链接或 reparse 条目。
这说明初始化会遍历较大的依赖目录，**不说明这些文件导致了原来的超时**。

上游 [PR #44253](https://github.com/huggingface/transformers/pull/44253)
已在 2026-03-10 合并为 `652f2f7a50096f1fc65356b4e7bb1b50fe1888fc`，
将这段目录枚举改用 `scandir`。这是本次首次发现的历史修复，不是新发布。
本项目仅回移枚举部分，保留 4.57.3 的 modular/conversion 过滤；
没有升级整个 Transformers 或更改训练参数。

另一个刚合并的 [PR #50047](https://github.com/huggingface/transformers/pull/50047)
延迟构建 package distribution mapping，但该 eager mapping 在固定的
4.57.3 源码中不存在。它不能直接解释或修复本项目保存的失败，未将其套入本地依赖。
作者的网络文件系统/NVMe 计时没有本地重跑。

新增的 `prepare_transformers_scandir_runtime.py` 只接受精确的原源码 SHA256，
先清点后复制到新 runtime，再核对完整原/新文件清单。它拒绝链接、超限清单和已有目标，
只修改一个源码文件，保留其余字节和时间戳以及已有 bytecode，避免额外引入整包重编译处理。
原环境、旧冻结源码、模型、seed、数据、质量阈值和期限不变。
生成的完整依赖副本属于 ignored local-state；仅显式使用其 Python launcher，
不依赖复制后的 pip 等 console script。上游归属和 Apache-2.0 许可见
`third_party/transformers-scandir/`。

已验证三项 stdlib 回归：未审源码拒绝、目标/容量边界，以及含两个后端、嵌套目录、
modular/conversion 文件、缓存目录的导出结构兼容性。
另外仅执行三个 AST 选定的原/新 scanner 定义，遍历真实已安装模型树，
两份完整导入结构相等，规范化结构 SHA256 为
`257f579368c56c5388aaa71dbc82927ac4f076ab0a4c15989cb69fb3a9366ba0`。
该结构对照没有执行 Transformers/Torch 模块、模型加载或计时比较。
这只接受该普通目录树上的 scanner 语义，不接受启动修复或训练收益。

隔离副本共 26,720 文件、757,706,940 字节，完整清点确认只有 scanner 源码不同；
准备程序重新核对原目录未变。独立审查核对清单路径、差异和总量，并重新读取 scanner、
Python launcher 与 pyvenv.cfg；没有将这次抽查称为独立重哈希整个依赖树。
基础环境完整测试为 1,008 项，927 通过、81 跳过。
此前使用 `-S` 隐藏 NumPy 的 11 个导入错误，以及装有 Torch 的环境先运行其他测试后
污染三个 stdlib-import 断言的失败，都保留在原始回执；该错误环境确实导入了 Torch 并运行
普通工具单测，不属于原生 pretrained 套件。没有修改这些历史测试来获得通过。

实际集成点是新副本的 `transformers/utils/import_utils.py`，其补丁 SHA256 为
`a2334855248d272d4dd60df846d2ba8bc9643c1744f3a8ac63cc6a056a63bff8`。
下一项直接返回同一个完整训练入口：在完整副本清单与身份/provider/依赖 hash 核验后，
另行冻结同样 12 用例、20 秒导入期限、原资源和质量阈值，再执行一次。
本轮发现磁盘可用空间低于原定 5 GiB 的运行前门槛，因而未启动该科学套件；
不能通过放宽资源阈值绕过。旧 venv 只做了只读清理候选清点，没有删除。
已关闭的 ledger/native observer 和单栈观察前置项不重开。
依赖准备的退出条件现已完成，不再继续扩展准备器或孤立诊断。

原始来源、目录清单、结构相等回执、测试和独立审查保存在
`reports/runs/20261031T080306Z/h1-static/`。H1 的六项历史联合失败、
历史 parent RSS 无效与 H2–H4 的未满足门槛全部保留。
