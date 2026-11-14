---
name: butler-adr-011
description: 产品二次更名 Butler（AI 智能助手管家）：全工程层换名 + 词表 v2 + 品类句退役。TRIGGER when 品牌与命名处置/数据迁移设计/文档措辞争议时
version: "1.0.0"
level: must
---

# ADR-011 · 品牌二次更名 Butler（AI 智能助手管家），品类句退役

- **状态**：Accepted
- **日期**：2026-11-14
- **决策者**：hiclaw520 + AI（brainstorm 五问逐项裁决）
- **关联**：取代 [ADR-007](ADR-007-品牌更名Kabao与白话词表.md) 的**品牌裁决部分**
  （其「两层词汇原则」继续有效）；[A1-03](../specs/architecture/A1-03-品牌与业务语言标准.md)
  v2（唯一事实来源）、[A1-02](../specs/architecture/A1-02-一核多端落地.md)、
  ADR-009（IA 裁决继续有效）、design-decisions D1/D2、conventions/03 v3（词表收编）、
  实施计划 `docs/superpowers/plans/2026-11-14-butler-repositioning-tasks.md`

## 背景

ADR-007 把品牌定为 Kabao（卡包）并采用市场白话词表 v1。实践中发现两处收窄：

1. **「卡包/账号」语系收窄产品心智**——产品实质是「替用户打理各家 AI 助手的管家」
   （导入、领取、体检、计量、调度、迁移），「卡包」隐喻停留在静态收纳，没有表达
   「管家替你干活」的核心叙事；竞品（doubao / workbuddy 等）也均为直述型命名。
2. **用户裁决**（2026-11-14，五问）：①品牌工程层一起改名（三选项中最彻底）；
   ②新名显示「AI 智能助手管家」、工程标识 butler；③IA 六页按用户列词
   （仪表盘/应用/账户/流量/日志/设置）；④视觉保现三主题换名复用；
   ⑤路线 A 改名先行、IA 随后（新页文案在词表 v2 定稿后写）。

先例：ADR-007 已建立「全深度一次到位 + 数据自动迁移」的更名方法论
（187+ 触点、CreditDaddy v0.3.0 迁移先例），本次复用同一机制，半径约 900 处命中、五批实施。

## 决策

**产品名定「AI 智能助手管家」，工程标识 Butler，全工程层换名，品类句概念退役。** 要点：

1. **映射总表**（实施唯一口径，完整表见任务书）：Python 六包 butler-core/-engine/
   -connectors/-server/-cli/-mcp；import 名 butler_core/butler_engine/butler_connectors/
   butler_mcp；npm @butler/sdk、butler-desktop；CLI `butler` / `butler-mcp`；
   env `BUTLER_*`；数据库 `butler.db`（数据目录基名 `butler`）；存储键
   `butler.settings.v1`；桌面端 Butler / com.butler.app；仓库远端 `ai-butler`；
   FastAPI title / MCP server 名 / 内部 job 名全部 butler 化。
   外层目录名（packages/core 等）与 `src/server`、`src/cli` 模块名不动。
2. **两层词汇原则延续**（ADR-007）：协议七字面量、连接器业务码字典、领域实体名
   （Account/Run/Event）、signal 五分类字面量**不动**；用户可见词按**词表 v2** 全量
   换白话（收编 conventions/03 v3）。
3. **词表 v2**：新增正式词——智能助手管家（产品名）、应用 App、账户 Account、
   仪表盘 Dashboard、流量 Traffic、日志 Logs、导入 Import、领取 Claim、
   体检 Health check、余额/额度 Balance/Quota、提醒 Alert、时间表 Schedule；
   退役禁用——卡、卡包、泊位、账号（→账户）、用量（页名级→流量；域内数据语境
   保留）、航海系全词。连接器原始返回文本不算 UI 文案（数据直渲染纪律不变）。
4. **品类句退役**：原「Kabao · AI 账号管家」为独立品类句；产品名本身即
   「AI 智能助手管家」，不再维护第二行句式（英文对标 AI Assistant Butler，
   仅文档/关于页用）。
5. **数据自动迁移加两腿**（复用 A1-03 §7 机制）：db 腿 = 首运检测
   kabao.db（旧品牌数据）→ 幂等搬移为 butler.db，旧库旧目录保留不删，写审计，
   显式 `BUTLER_DB` 不迁移；localStorage 腿 = 读 `butler.settings.v1` 缺失则读
   `kabao.settings.v1` 写入新键，旧键保留。双端并行期另一端合入后重跑即触发同一迁移。
6. **主题显示名**：卡纸与墨（浅）→**纸墨**（浅·默认）；墨夜/暖纸不变；
   机制、token 值、`THEME_NAMES` 内部值（paper/dark/warm）全不动。

**明确排除项**：协议字面量与业务码字典不动；git 历史不改写；历史裁决文档
（ADR-001..010、A0-01、docs/superpowers/ 历史任务书）保留原词，新文档标注取代关系；
API 语义零变化；本次不新增功能（新 IA 站稳后下一阶段立项）。

## 后果

**正面**：

- 「管家」直述产品实质（替你打理），对齐调度/迁移的产品方向，圈外零学习成本
- 单一词汇体系延续，工程层与产品层边界更清晰（品类句退役少维护一行句式）
- 数据迁移复用已验证机制（幂等/保留/审计/双端协调），风险有先例兜底

**负面/约束**：

- 二次更名半径约 900 处 → 五批串行、每批九项门禁，批2 机械替换以 459 测试全绿为准
- 词表 v2 与现行页名（账号/用量/记录）在阶段一存在过渡态 → 页名级换词随阶段二
  六页 IA 一次到位（路线 A 的既定时序，非遗漏）
- 远端改名需用户手工（Gitee 网页）→ 批5 时点执行，旧 URL 自动重定向兜底
