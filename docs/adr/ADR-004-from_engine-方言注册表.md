---
name: butler-adr-004
description: 连接器方言以数据在 core 注册，from_engine(text, dialect) 是唯一运行时翻译入口，未知码显式报错。TRIGGER when 实现 Connector/翻译业务码/对验收 oracle 时
version: "1.0.0"
level: must
---

# ADR-004 · from_engine 方言注册表：core 单源翻译，未知码显式报错

- **状态**：Accepted
- **日期**：2026-11-10
- **决策者**：hiclaw520 + AI
- **关联**：A2-01 §2/§6、A2-02 §4/§6、ADR-001、02-开发红线 §1.2/§1.5

## 背景

两份规格对"业务码 → Status"的翻译各说了一半：

- A2-01 §2：`from_engine(text)` 是**唯一**翻译入口（core 单源）；
  A2-01 §6：适配器**不做语义决策、不维护结果映射表**。
- A2-02 §4：每个 Connector 的 PROTOCOL.md 记"业务码字典：码 → 语义 → core 结果词汇映射"。

未定义的是管道：连接器各自的码表**怎么进入** core 的翻译入口而不违反上述任一条。

## 决策

**方言注册表（data-driven）**，落在 `core/domain/results.py`：

1. `register_dialect(name, mapping: dict[str, Status])`——连接器以**数据**
   （manifest/declarative YAML 片段或连接器包内的常量字典）申报自己的业务码映射，
   **加载期**注册一次；同名重复注册显式报错（加载逻辑 bug 不许静默覆盖）。
2. `from_engine(text, *, dialect="legacy")` 是**唯一运行时翻译入口**（A2-01 §2）。
   适配器只负责把原始码原样带回来，自己不翻译。
3. 内置 `legacy` 方言 = Status 字面量自映射（旧系统说的就是这七个词，
   行为对照 oracle 零损耗，A0-01 §2.2）。
4. **未知码 → `UnknownEngineCode` 显式异常**（红线 5：显式报错不静默兜底）；
   用例层捕获后记 `FAILED` + evidence 保留原始码 + 产 `PROTOCOL_CHANGED` 事件
   （= A2-01 §5 的"上游协议变化自动探测"落地路径）。
5. **严格字面匹配**：不做 trim / 大小写归一——宽松匹配会掩盖协议变更，
   与 oracle"同输入同结果"冲突。
6. **PROTOCOL.md 的角色不变**（A2-02 §6）：文档侧唯一事实来源，先改文档再改代码；
   注册表是它的运行时投影，两者不一致 = review 打回。

明确排除项：端上（web/cli/desktop）不得 import 注册表或自行维护任何映射表
（红线 2：端零映射）；engine 适配器同样禁止携带映射表（A2-01 §6）。

## 后果

**正面**：

- 翻译语义 core 单源，可被门禁与评审机器定位（grep 注册点即全部映射）
- 新 Connector 接入 = 交一份数据字典，不写分支
- 未知码成为协议变更探测器（PROTOCOL_CHANGED）的数据来源

**负面/约束**：

- 连接器加载期多一步注册；重复注册会炸，需要加载器保证只注册一次
- 全局注册表要求测试用方言名互不冲突（用唯一名 + 不提供删除接口）
- 未知码以异常上抛——用例层必须接住，否则 Run 会以异常终态而非 FAILED 落账
  （用例层测试兜底，见入口任务 2）
