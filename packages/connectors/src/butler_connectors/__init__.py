"""Butler 连接器家族（A2-02）。

一 AI 产品 = 一个子包：``<id>/manifest.yaml`` 声明能力矩阵，PROTOCOL.md
是协议字典（逆向结论的归宿，A0-01 §2.1）。本包内含共享运行时：

- ``manifest``：manifest/declarative 的 schema（extra=forbid，配置事故显式爆）
- ``transport``：可注入 HTTP 出站通道（默认 httpx；测试换假通道）
- ``decl``：三级扩展第一级——声明式 provision 引擎（A2-02 §4 五段式）
- ``storage``：本机凭据存储发现（平台宏路径解析，接入扫描用）
- ``ssaes``：Trae CN SS_AES 信封解锁（协议事实归 PROTOCOL.md，代码全新写）
- ``registry``：装载 manifest → 组建 ProvisionPort / 停靠调度条目 / dispose 分发

依赖方向：本包只准依赖 core（端口与领域模型），依赖注入由端（server/cli）
的组装层完成——engine 不 import 本包（ADR-003）。
"""
