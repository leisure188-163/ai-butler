# specs · 设计规格入口

> 命名规范见 [`../conventions/规范索引.md`](../conventions/规范索引.md) 与 skill 标准：
> `A{层级}-{NN}{分册字母}-{主题}.md`，**层级字母在 NN 前**。

## 推荐阅读顺序（按架构与设计先后）

1. **架构（architecture/）**：A1-01 产品定位 → A1-02 一核多端 → A1-03 命名与语言
   → A1-04 网页会话通道 → A1-05 按业务域重写总设计（总纲，最后读）
2. **领域（domain/）**：A2-01 领域总纲 → A2-02 Connector 规范 → A2-03 网页捕获通道
   → A2-04..A2-09 六业务域（accounts / platforms / execution / usage / health / scheduling）
3. **横切（cross-cutting/）**：A4-01 L0 底座设计
4. **应用（application/）**：A3-01 信息架构与核心页面
5. **旧系统（legacy/）**：A0-01 仅参照，非移植

> 业务域分册按域图顺序编号：A2-04 accounts / A2-05 execution / A2-06 usage /
> A2-07 health / A2-08 scheduling；通用领域文档（A2-01 总纲 / A2-02 Connector /
> A2-03 网页捕获）排在业务域分册之前。

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
| [A1-01](architecture/A1-01-产品定位与能力全景.md) | 产品定位 / 命名与词表 / L0~L7 能力 / 活动时间表 / 里程碑 / 合规边界 |
| [A1-02](architecture/A1-02-一核多端落地.md) | 分层与依赖方向 / 领域模型概览（多账号）/ Connector 机制 / 门禁 |
| [A1-03](architecture/A1-03-命名与语言标准.md) | 命名与语言标准：定位 / 四铁律 + 两层词汇 / 词表 v2 / IA / 主题 / 命名当前值 / 数据自动迁移 / 路线图 |
| [A1-04](architecture/A1-04-网页会话通道与跨平台矩阵.md) | 网页会话通道（browser_cookie + 声明式探针）/ 跨平台矩阵 / ChatGPT·Claude 连接器 |
| [A1-05](architecture/A1-05-按业务域重写总设计.md) | **按业务域重写总设计**：域图 / 包结构与依赖恒等式 / 多账号 / 数据迁移收口 / 阶段计划 / 验收 |
| [A2-01](domain/A2-01-领域模型与动作模型.md) | 领域总纲：业务域地图 / 账户与多账号 / 结果词汇单源 / Action-Run / Trigger / Event / 端口总则 |
| [A2-02](domain/A2-02-Connector-规范.md) | manifest / 三级扩展 / 声明式 schema / 沙箱 / PROTOCOL.md 模板 |
| [A2-03](domain/A2-03-网页捕获通道与健康探针.md) | 网页捕获通道（Chrome cookie 直读 + DPAPI/GCM）/ 声明式健康探针通道 |
| [A2-04](domain/A2-04-accounts域.md) | 账户域：Provider / Account 集合 / 凭据权益会话 / vault 端口 / 注册与导入 |
| [A2-05](domain/A2-05-execution域.md) | 执行域：Action / Run / 幂等键 / 时间预算 / execute_action |
| [A2-06](domain/A2-06-usage域.md) | 用量域：UsageSample / 额度三型语义谓词 / 耗尽预测 / collect_usage |
| [A2-07](domain/A2-07-health域.md) | 健康域：健康分级 / 风险规则 / 到期扫描 / health_scan |
| [A2-08](domain/A2-08-scheduling域.md) | 调度域：Trigger 三型 / 窗口 / 待办队列 / list_pending |
| [A3-01](application/A3-01-信息架构与核心页面.md) | **v2 六页 IA**（仪表盘/应用/账户/流量/日志/设置）/ 页面规格 / 组件结构 / 重定向表 v2 / 渲染纪律 |
| [A4-01](cross-cutting/A4-01-L0-底座设计.md) | 凭据保险库 / 健康中心 / 事件总线与通知 / 审计 |
| [A0-01](legacy/A0-01-旧系统知识资产.md) | auto-signin-kit = 协议字典 + 行为验收基准（**非移植**） |
