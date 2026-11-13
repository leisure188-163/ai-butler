# Butler 重定位设计 · 去卡包化 + 六页 IA（2026-11-14）

> 状态：设计已与用户逐问逐节确认（品牌处置 / 新名 / IA 页集 / 视觉基调 / 实施路线五问，
> 两阶段设计双通过）。本文是任务书的上位输入；实施裁决落 ADR，进度落 STATUS。
> 上位依据：[ADR-007](../../adr/ADR-007-品牌更名Kabao与白话词表.md)（两层词汇原则）、
> [A3-01](../../specs/application/A3-01-信息架构与核心页面.md)（现行 IA）、
> [design-decisions](../../design-decisions.md) D1–D4。

## 0. 一句话

产品从「Kabao（卡包）· AI 账号管家」重定位为 **「AI 智能助手管家」**（工程标识 **Butler**），
IA 从四页（账号/用量/记录/设置）改为六页（**仪表盘/应用/账户/流量/日志/设置**）。
两阶段串行：**阶段一全深度改名（结构不动）→ 阶段二六页 IA（纯前端，契约零改动）**。

## 1. 用户裁决记录（brainstorm 五问，2026-11-14）

1. **品牌处置**：工程层一起改名（三选项中最彻底——repo/package/SDK/db/设置键全换）。
2. **新名**：显示「AI 智能助手管家」；工程标识 butler（仓 ai-butler、包 butler_core、
   @butler/sdk、BUTLER_ 前缀、butler.db）。
3. **IA 页集**：六页按用户列词——仪表盘、应用、账户、流量、日志（+设置）；
   词表 v2 以「账户/流量」为正式词。
4. **视觉基调**：保现三主题，换名复用（卡纸与墨→纸墨；token 值与组件不动，
   工力全花在结构与页上）。
5. **实施路线**：A 改名先行、IA 随后（两阶段串行，新页文案在词表 v2 定稿后写）。

## 2. 阶段一 · 全深度改名批（页面结构不动，纯换名换词）

### 2.1 改名映射总表（旧 → 新）

| 层 | 旧 | 新 |
|---|---|---|
| Python 发行包 ×6 | kabao-core / -engine / -connectors / -cli / -mcp / -server | butler-core / -engine / -connectors / -cli / -mcp / -server |
| Python import 名 | kabao_core / kabao_engine / kabao_connectors / kabao_mcp | butler_core / butler_engine / butler_connectors / butler_mcp（server、cli 模块名本就无 kabao，只动 dist 名与文案） |
| src 内层目录 | packages/*/src/kabao_* | packages/*/src/butler_*（packages/core 等外层目录名不动） |
| npm | @kabao/sdk、kabao-desktop | @butler/sdk、butler-desktop（web 包名不变） |
| CLI 命令 | `kabao`、`kabao-mcp` | `butler`、`butler-mcp` |
| 环境变量前缀 | `KABAO_` | `BUTLER_` |
| 数据库 | kabao.db | butler.db（首运自动迁移，旧库保留） |
| 前端存储键 | kabao.settings.v1 | butler.settings.v1（读旧键兼容一次搬迁，旧键不删） |
| 品类句 | Kabao · AI 账号管家 | 产品名即「AI 智能助手管家」（英文对标 AI Assistant Butler，仅文档/关于页用） |
| 主题显示名 | 卡纸与墨（浅）/ 墨夜 / 暖纸 | **纸墨**（浅·默认）/ 墨夜 / 暖纸（机制、token 值、THEME_NAMES 内部值 paper/dark/warm 全不动） |
| 仓库远端 | gitee hiclaw_520/ai-kabao | ai-butler（Gitee 网页改名=用户手工步；本地切 remote + 文档） |
| 文档自称 | Kabao（卡包） | Butler（智能助手管家） |

### 2.2 数据与设置迁移（复用 A1-03 §7 现成机制）

- 首运检测 kabao.db → 幂等搬移为 butler.db，历史文件保留不删，写审计事件
  （上次更名的迁移机器直接扩展一档，先例 CreditDaddy v0.3.0）
- localStorage：读 butler.settings.v1，缺失则读 kabao.settings.v1 并写入新键（旧键保留）
- 双端（Windows）协调：env/db 改名合入后另一端重跑即触发同一迁移，幂等覆盖

### 2.3 词表 v2（conventions/03 v3 收编强制）

- **新增正式词**：智能助手管家（产品名）、应用 App、账户 Account、仪表盘 Dashboard、
  流量 Traffic、日志 Logs、导入 Import、领取 Claim、体检 Health check、余额/额度
  Balance/Quota、提醒 Alert、时间表 Schedule
- **退役禁用**：卡、卡包、泊位、账号（→账户）、用量（页名级→流量；域内数据语境保留）、
  航海系全词
- **工程层不动**（ADR-007 两层原则延续）：协议七字面量、连接器业务码、
  领域实体名（Account/Run/Event）
- 连接器**原始返回文本不算 UI 文案**，不扫（数据直渲染纪律不变）

### 2.4 批次切分（每批过 `verify_project.py --test` 九项门禁）

1. **批1 文档先行**：ADR-011（更名裁决）+ A1-03 v2 + conventions/03 v3 +
   conventions/00（变量入口新值）+ design-decisions D1/D2 换名
2. **批2 Python 六包**：pyproject/dist/src 内层目录/import/门禁脚本全换——纯机械替换，
   459 测试全绿为准
3. **批3 npm + web**：@butler/sdk、存储键迁移、UI 文案换词、主题显示名换名
4. **批4 底座**：env 前缀、db 自动迁移腿、CLI 命令、server OpenAPI 标题
5. **批5 收尾**：全库文档措辞清扫（docs ~137 处，历史裁决文档除外）+
   repo remote 切 ai-butler + STATUS 里程碑记账

### 2.5 明确不动

协议字面量与连接器 PROTOCOL.md 业务码字典、git 历史不改写、API 语义零变化、
**历史裁决文档**（ADR-007 等记录更名史者保留原词，新文档标注取代关系）、
A0-01 旧系统资产文档。

## 3. 阶段二 · 六页 IA 批（纯前端，契约零改动）

### 3.1 导航与路由

- 侧栏六项平铺：**仪表盘（默认）/ 应用 / 账户 / 流量 / 日志 / 设置**
- hash：`#/dashboard`、`#/apps`、`#/accounts`、`#/traffic`、`#/logs`、`#/settings`
- 重定向表 v2：`#/home→#/dashboard`、`#/alerts→#/dashboard`、
  `#/wallet→#/accounts`、`#/card→#/accounts`、`#/radar→#/traffic`、
  `#/usage→#/traffic`、`#/log→#/logs`（`#/accounts`、`#/settings` 原链有效）
- 提醒角标挂「仪表盘」项（「今天有事吗」的回答者在首页；账户项不挂）
- 品牌区单行「AI 智能助手管家」；品类句概念退役；≤900px 顶条同样显示主名
  （原「隐藏品类句」规则删除）

### 3.2 仪表盘（新页 = 默认首页）

三块，全部复用现有件（矩阵表/结果徽/行+发丝线），**不开新端点**，聚合走前端 computed：

1. **今日一句话结论**——沿用现账户页 headline 谓词
   （X 个账户状态正常 / N 项待处理 / 还没有接入任何应用）
2. **常驻待办栏三节整体迁入**（TodoRail：已自动完成 / 需要你处理 / 即将到期，
   含证据折叠与能力驱动按钮）——账户页不再挂待办栏
3. **速览行**（只数数、signal 驱动、端零映射）：账户健康分布 · 今日自动动作 ·
   流量速览（最近采集一句话 + 最低额度账户）· 最近一条日志

### 3.3 应用（新页 = 应用注册表）

- 表：应用 | 能力 | 时间表 | 账户数 | 状态汇总 | 动作——数据全部现成
  （AppItem 已带 capabilities/schedule_times/account_id）；多账户应用显示计数
  （与 ADR-010 一人多账号占位自然衔接，实现仍不做）
- 未接入应用 = 虚线邀请行「＋ 导入 {应用名}」（从账户页迁来）；
  **一键导入（n）移到本页页头**（导入语义归应用域）
- 点行展开：能力清单 / 班次 / 该应用账户跳转（渐进披露）

### 3.4 账户页（瘦身为纯矩阵）

- 移除：TodoRail（→仪表盘）、应用空槽行（→应用页）、一键导入按钮（→应用页）
- 保留：9 列矩阵、筛选、批量条、行展开详情、一键领取（n）（领取语义归账户域）
- **顺带销挂账 0①**：拆 MatrixTable 子组件（496 行软警戒处置，conventions/04 §2.2）

### 3.5 流量页 / 日志页（改名 + 换词）

- 流量 = 现 UsagePage 换名换词（「额度雷达」语系全换词表 v2）；「立即采集」保留
- 日志 = 现 LogPage 换名；表结构零变化

### 3.6 设置页

三节不变；主题名「纸墨（浅）/ 墨夜 / 暖纸」；
关于节 = 产品名「AI 智能助手管家」+ 版本 + 数据位置 butler.db + 仓库与接口文档外链。

### 3.7 工程落位（conventions/04 §2.4 纪律）

- pages/ 新增 DashboardPage、AppsPage；AccountsPage 瘦身并拆 MatrixTable；
  SideNav 六项；TodoRail 归仪表盘
- composables / api.ts **零新增端点**；hash 路由表与重定向表 v2 落 useHashRoute
- **server / engine / connectors / sdk / mcp 源码零改动**——阶段二是纯 apps/web 批

### 3.8 验收

每批九项门禁 + 终验；浏览器走查复用 2026-11-14 矩阵走查方法
（双断点 × 三主题 × 计数核对；真实动作按钮留用户自点）。

## 4. 明确不做

- **新功能**（用户「还有其他的功能等等」）= 新 IA 站稳后下一阶段单独立项
- 一人多账号仍为 ADR-010 占位（应用页「账户数」列是其展示面，不实现）
- 契约零改动（无 gen:sdk、openapi.sha256 不动）；server/engine/connectors/sdk/mcp 源码零改动
- 视觉重做不做（保三主题换名复用）

## 5. 风险与缓解

- **半径 ~900 处命中**（packages 654 / apps 109 / docs 137）→ 五批切分、每批门禁；
  批2 机械替换以测试全绿为准
- **数据安全**：迁移幂等、旧库旧键保留、审计事件
- **远端改名时序**：Gitee 手工改名 → 本地 remote 切换 → push（Gitee 旧 URL 自动重定向，风险低）
- **漏改**：新页文案在词表 v2 定稿后才写（路线 A 的核心理由）；批5 全库清扫兜底

## 6. 验收标准（Definition of Done）

- **阶段一**：工作区 `grep -ri kabao --exclude-dir=.git` 仅剩迁移兼容逻辑中的旧键检测
  与历史裁决文档；六包 dist/import 全绿（459 测试）；butler.db 首运迁移实测通过；
  仓 remote = ai-butler
- **阶段二**：六页双断点 × 三主题走查全过 + 旧 hash 7 条重定向 + 一键导入（n）/
  一键领取（n）/ 角标计数与 server 实数吻合 + 契约零改动 +
  server/engine/connectors/sdk/mcp 五包源码零 diff
- **文档**：ADR-011 / ADR-012、A1-03 v2、conventions/03 v3、conventions/00 更新、
  A3-01 v2、design-decisions D1/D2 换名、STATUS 里程碑记账
