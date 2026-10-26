# 最新 ReAct NoKG 全零诊断

报告：e33b3c92de0fc4c949b796cef540c79c6，已完成 30 题。实际配置 ReAct、GraphDB TUC_building_test、qwen-plus-2025-12-01、NoKG、8 并发；不是 5000T，也不是 BrickQA 搜索 Agent。29 题最终 empty_result，1 题 other_error；全部 gold 成功，每题 18 行。不能把执行错误的那题算作合法空结果。

只读查询原配置仓库确认：Min_Air_Temperature_Setpoint 23 个实例；Air_Temperature_Setpoint_Sensor 与 Minimum_Air_Temperature_Setpoint_Sensor 均为 0；brick:hasTimeseries、brick:uuid、brick:hasTag tag:Minimum 均无匹配三元组。ref:hasTimeseriesId 有 2244 个匹配、ref:ifcName 有 104 个匹配。Zone hasPart space / space hasPoint point 路径为 0；经 space isLocationOf / hasPoint 路径为 179。三项独立必要条件已经使截图生成查询无解，并非执行器丢失了已有结果。

NoKG 不向 Writer 注入 TTL；ReAct 无 BrickQA 搜索/定位工具，Critic 只得到查询执行摘要，空结果没有真实行可供纠正。模型轨迹存在将原猜测改成其他未出现在图中的类型和外部引用关系的情况。不能通过改写 gold、给 Critic 测试答案、按 gold 挑历史最佳查询来提高复现分数。

如需验证有初始图谱上下文的条件，应显式选择已有 TUC_building_sample_5000.ttl 并作为新 5000T 条件运行；保留本次 NoKG 报告。若与论文定量比较，还须单独使用论文的 Gemini 2.5 Flash 条件，不能把当前固定 Qwen 的表现称为论文同模型复现。以上只说明条件及已证实的错误原因，未测量更改模型或上下文后的新准确率。

本次只读诊断、未调用模型、未改原报告/查询/评分/方法。机器可读计数与原报告哈希见 react_nokg_empty_diagnosis_20261024.json。
