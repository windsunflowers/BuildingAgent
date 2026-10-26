# 本地 RDFLib 原样与等价执行计划的边界

用户要求严格保留作者本地 RDFLib，不接入 GraphDB。本轮全部探测只用 RDFLib 7.6.0、本地 bldg11.ttl（62578 三元组）、原 gold_execution_sparql，不调用模型。

- 原执行器单独运行，在180秒预算下超时（约180.86秒）。证据 mortar009_rdflib_serial180_20261026.json。
- 标准查询初始类型候选为394个VAV绑定、512个温度测点绑定、394个HVAC_Zone绑定；默认初始BGP排序优先多个未相互绑定的类型条件，理论候选组合为79480832，然后才约束feeds+/hasPoint。
- 独立候选连接器仅在同一BGP每次绑定后重新选择未绑定节点最少的三元组，单个三元组仍交给RDFLib原evalBGP执行；通过RDFLib CUSTOM_EVALS 官方扩展点运行，不改SPARQL文本、不改图、不加LIMIT、不改模型提示或评分。该测试约1.015秒返回470行，完整多重集与独立本地三元组遍历一致。证据 mortar009_connected_bgp_probe_20261026.json。

重要边界：这一候选是本地RDFLib执行器补丁，作者原源码没有注册该扩展，因此不能称为执行器完全原样。只证明本查询多重集一致，不能据此宣称所有SPARQL或模型轨迹完全一致。未指定ORDER BY的返回行序可能变化，并影响模型工具反馈的前几行；复杂LIMIT/聚合场景还需单独守卫及差分测试。

候选仅存在 output/validation/probe_mortar009_connected_bgp_20261026.py，未接入生产 sparql_worker.py。正式代码未改变引擎或180秒预算，正在等待用户选择是否接受这一执行器工程适配。
