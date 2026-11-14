---
name: butler-adr-002
description: core 按业务域分包——butler_core 内部为 shared + accounts/execution/usage/health/scheduling 五业务域，每域固定 domain.py+ports.py+usecases/ 三件套，依赖恒等式「域→shared」入门禁机检。TRIGGER when 讨论 core/engine 目录结构、业务域边界、新增业务域时
version: "1.0.0"
level: must
---

# ADR-002 · core 按业务域分包（五域 + shared 内核）

- **状态**：Accepted
- **日期**：2026-11-14
- **决策者**：hiclaw520 + AI（六问逐项裁决）
- **关联**：[ADR-001](ADR-001-出站适配器独立成包-packages-engine.md)（出站适配器独立成包）、
  [ADR-003](ADR-003-一人多账号领域模型.md)（多账号并入领域模型）；
  实施细则见 [A1-05](../specs/architecture/A1-05-按业务域重写总设计.md)；
  五域分册 A2-04..A2-08；[conventions/01](../conventions/01-开发红线.md)
  第 8 条红线（裁决必须回收 spec）

## 背景

core 是全库唯一业务规则出处，其内部分包方式决定业务边界是否可见。
若按技术概念横切（实体集中一个目录、端口集中一个文件），业务边界只剩
口口相传：改一个业务的对外面要动全库公共端口文件，跨域耦合无从拦截。
分包单位必须与业务单位一致——**目录即业务地图**。

## 决策

1. **目录即业务**：`butler_core` 内按业务域分包——`shared / accounts / execution /
   usage / health / scheduling`，每域固定三件套 `domain.py + ports.py + usecases/`；
   端口随域走，不设全库单一 ports.py。`butler_engine` 对齐同一域图。
2. **依赖恒等式**：域间依赖只允许 `域 → shared`，禁止域互依；跨域编排由用例组合
   完成（用例可以跨域读，域的 domain.py 不得 import 其他域）。依赖方向入门禁机检。
3. **多账号并入领域模型**（[ADR-003](ADR-003-一人多账号领域模型.md) 全部五点）：
   Account 是应用下集合，身份 = `(provider, account_key)`（`account_key` 缺省
   `"main"`）；target 编址 = 应用 + 账号；幂等键 = `(kind, account_id, 窗口)`；
   凭据/权益/会话/用量全部按账号隔离；契约字段 `account_key` / `account_ids`。
4. **命名统一 butler**：包名 / CLI / env / db / 存储键按
   [A1-03 §6](../specs/architecture/A1-03-命名与语言标准.md) 映射总表。
5. **历史兼容收口在装配期**：旧数据源迁移集中 `butler_engine/db/migrate.py`
   一次性完成（幂等、旧文件保留不删、写审计，机制见 A1-03 §7），运行时零 legacy 分支。
6. **裁决回收是红线**（conventions/01 第 8 条）：任何 ADR 合入时必须同步回收受影响
   spec，文档漂移在 review / 门禁层拦截。

## 后果

**正面**：

- 目录即业务地图：新人/AI 进场看目录就知道业务边界
- 端口随域走：改动一个域的对外面只触碰该域的 ports.py
- 依赖恒等式机检后，跨域耦合无法静默滋生
- spec 与代码漂移有制度性拦截

**负面/约束**：

- 域间禁止互依 → 跨域功能必须经用例组合，禁止在 domain.py 互 import
- shared 只放真正跨域的原语；拿不准的先放域内，出现第二处使用再上收
