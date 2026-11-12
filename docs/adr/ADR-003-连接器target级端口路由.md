---
name: kabao-adr-003
description: 连接器端口按 target 精确路由优先、kind 兜底，端组装层动态挂载。TRIGGER when 讨论连接器接入/端口路由时
version: "1.0.0"
level: must
---

# ADR-003 · 连接器 target 级端口路由（追溯补记）

- **状态**：Accepted（2026-11-11 实施，83784fe；2026-11-11 补记文档）
- **日期**：2026-11-11（裁决随 83784fe 实施）
- **决策者**：M1 首提交会话
- **关联**：ADR-001（engine 独立包）、ADR-002（from_engine 方言注册表）、A2-02 §3 三级扩展

## 背景

M0 用例层端口是单端口注入（`ExecuteAction(ports=...)`）；M1 起多连接器并存
（trae → qoder → doubao → workbuddy），用例按什么维度选端口？候选：
kind 全局映射（同 kind 连接器冲突）、target 精确映射（每连接器一个）、
连接器自带分发。

约束：engine 不 import 连接器包（依赖方向恒指 core）；连接器端口由端组装层
产出（注册表在 connectors 包，装配在 server/desktop 端）。

## 决策

**target 精确路由优先，kind 兜底**；端组装层经 `EngineKit.register_provision_ports()`
动态挂载，连接器注册表产出纯数据映射（dict），engine 不 import 连接器包。

1. 选择器形状：`select(action) -> ProvisionPort | None`——None = 未接入
   （UnsupportedAction，用例层显式拒绝）
2. `routing_ports(kind_ports, target_ports)`：`target_ports.get(action.target)
   or kind_ports.get(action.kind)`——连接器 id 是 Action 契约里的 target
3. kind 级端口留给跨连接器通用能力与测试注入
4. 重复挂载同名 target（不同实例）= 注册表装配 bug，显式拒绝（红线 5）

## 后果

**正面**：

- 多连接器并存零特殊分支；每连接器端口独立可换（M1 各家逐个接入）
- engine 与 connectors 解耦到数据面（依赖方向机检可查）

**负面/约束**：

- 端组装层（server/desktop）必须正确把注册表产出转交 bridge——装配错误只能
  在端侧测试暴露
