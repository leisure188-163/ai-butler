# specs · 设计规格入口

> 命名规范见 [`../conventions/规范索引.md`](../conventions/规范索引.md) 与 skill 标准：
> `A{层级}-{NN}{分册字母}-{主题}.md`，**层级字母在 NN 前**。

## 层级字母 ↔ 子目录映射（本项目自定）

> **为什么用 `A` 而不是 keshumai 的 `L`**：本项目 `L0~L7` 已被产品能力分层占用
> （[A1-01](architecture/A1-01-产品定位与能力全景.md)），文档层级前缀必须换字母避免双义。

| 前缀 | 子目录 | 含义 | TOGAF 对应 |
|---|---|---|---|
| `A0` | `legacy/` | 旧系统参照资产（协议字典 + 验收基准，非移植） | — |
| `A1` | `architecture/` | 愿景与总体架构 | Architecture Vision |
| `A2` | `domain/` | 领域/业务架构 | Business Architecture |
| `A3` | `application/` | 应用架构（UI/信息架构） | Application Architecture |
| `A4` | `cross-cutting/` | 技术架构与横切 | Technology Architecture |

## 文档清单

| 文件 | 内容 |
|---|---|
| [A1-01](architecture/A1-01-产品定位与能力全景.md) | 产品定位 / 品牌与词表 / L0~L7 能力 / 活动时间表 / 里程碑 / 合规边界 |
| [A1-02](architecture/A1-02-一核多端落地.md) | 分层与依赖方向 / 领域模型概览 / Connector 机制 / 门禁 |
| [A1-03](architecture/A1-03-品牌与业务语言标准.md) | 品牌与业务语言标准：定位 / 四铁律 + 两层词汇 / 词表 v1 / 侧边栏 IA / 主题 / 命名当前值 / 数据自动迁移 / R1-R5 |
| [A2-01](domain/A2-01-领域模型与动作模型.md) | 聚合根 / 结果词汇单源 / Action-Run / Trigger / Event / 端口 |
| [A2-02](domain/A2-02-Connector-规范.md) | manifest / 三级扩展 / 声明式 schema / 沙箱 / PROTOCOL.md 模板 |
| [A3-01](application/A3-01-信息架构与核心页面.md) | 侧边栏 IA / 页面规格（落地态）/ 组件结构 / 渲染纪律 |
| [A4-01](cross-cutting/A4-01-L0-底座设计.md) | 凭据保险库 / 健康中心 / 事件总线与通知 / 审计 |
| [A0-01](legacy/A0-01-旧系统知识资产.md) | auto-signin-kit = 协议字典 + 行为验收基准（**非移植**） |
