# Kabao R2 · 用量采集 + 额度雷达 + MCP · 设计文档

- 日期：2026-11-12（设计与实现同批收官；**2026-11-13 后补归档**）
- 状态：已实现并真机验收（Windows/mac 双机四家实测），门禁全绿
- 范围：core 用量领域 + engine 台账/job + 四家连接器用量适配 + server 雷达域
  API + web 雷达页 + apps/mcp stdio 薄壳（ADR-008）
- 关联：ADR-005（doubao CDP 通道）、ADR-008（MCP 薄壳）、A2-01 §1、A2-02、
  A3-01 §六页 IA

## 1. 背景与目标

R1 后卡包已有「账号 + 凭据 + 领取」主干；用户对各家 AI 编程助手的
**权益用量**（套餐余额/签到入账/耗尽节奏）零可见——「额度雷达」是 R2 的
产品目标：一页看全各家余量、入账流水与耗尽预测，并把三个查询/动作
（查额度/查用量/触发领取）暴露给 LLM 客户端（MCP）。

**目标**

1. 用量取证先行：四家逐家取证可得通道，结论回填 PROTOCOL §7。
2. core 用量领域单源（三实体 + 阈值谓词 + 耗尽预测），端零映射（红线 2）。
3. engine 用量台账三表 + 每日采集 job + dock 顺带采集。
4. 四家连接器用量适配真机全通；server 雷达域两端点契约派生。
5. web 额度雷达页（六页 IA 收编）；MCP stdio 薄壳三工具。

**非目标**

- 逐调用 tokens 明细（UsageSample 语义）：四家真机取证双通道全
  UNSUPPORTED——三实体按聚合口径设计，逐调用语义原样保留给 R4 反代通道，
  不发明不造数据（红线 5）。
- doubao 读 CDP 用量页面：ADR-005 裁决不做（UI 只有累计获得，与 detail
  重复，无增量价值）。

## 2. 取证先行：用量三型重定义

四家真机取证（2026-11-12，Windows/mac 只读）核心结论：**逐调用 tokens
双通道（请求头/响应体）全 UNSUPPORTED**。可得的只有三型：

| 型 | 语义 | 四家可得性 |
|---|---|---|
| 聚合用量 | 服务端聚合统计原话 | trae ent_usage / qoder qoderUsage / workbuddy（并入包） / doubao ✗ |
| 额度快照 | t 时刻资源包状态 | trae 29 包 / qoder 基础+付费 / workbuddy 85 包分账本 / doubao ✗（无包概念） |
| 入账流水 | 签到/裂变入账记录 | doubao quota-records（翻页）/ 其余三家 ✗ |

「额度雷达输入四家 API 全可得」——快照/聚合/流水三型按家拼装，缺失通道
如实 None（不造空数据）。

## 3. 领域模型（core/domain/usage.py，块①）

三实体全挂 account_id（A2-01 §1）：

- **UsageSnapshot**：t 时刻全部资源包状态；`PackageQuota` 嵌套
  （package_id/name/total/used/remaining/unit/cycle_end/status 全为服务端
  原话投影——适配器负责方言归一，数值不取整，credits/POINT 单位端零映射）。
- **UsageAggregate**：服务端聚合用量原话（summary Mapping，不派生不重算）。
- **QuotaLedgerEntry**：入账流水；`record_id` 幂等去重唯一键；amount 全正值
  （doubao 实证只有入账）——负值 = 协议形状变化，领域层显式拒绝（红线 5）。
- **UsageResult**：采集端口结果三段可空（snapshot/aggregate/ledger；
  ledger 的 None = 通道不可得，() = 无新流水——语义分开如实申报）。

谓词与预测（core 单源）：

- `is_quota_low(pkg, threshold=0.2)`：占比 ≤ 20% **且未耗尽**（remaining ≤ 0
  = 已耗尽终态，历史签到/裂变包永不恢复，不算低额——真机回归：否则几十个
  历史包淹没告警）；无总额信息（total ≤ 0）不算，谓词不猜。
- `forecast_exhaustion(previous, current)`：相邻快照差分外推；不足两帧或
  帧距 < 1h 返回 `()`（真机回归：启动补采与手动采集仅隔几分钟，差分爆炸
  ——宁缺毋滥，UI 显「采集中」）；新包无历史速率不猜；per_day ≤ 0（回血）
  不预测耗尽。

## 4. 引擎（engine/usage/sqlite.py + bridge）

- **三表**：usage_snapshots（快照全量留底，相邻帧差分原料）/
  usage_aggregates（summary_json 原话）/ quota_ledger（(account_id,
  record_id) 主键 = INSERT OR IGNORE 幂等去重）。SQLite(WAL) 单库、每操作
  一连接，与 runs 台账同款纪律；排序契约 = 时间新→旧、同刻 rowid 决胜
  （不赌 uuid 字典序）。Repository 接口隔离（UsageStore 端口，SQL 不出模块）。
- **每日用量 job**：`start_usage_scans()`（IntervalJob 语义：启动即补采
  第一帧——耗尽预测需要历史帧，补采即攒原料）。
- **dock 顺带采集**：导入成功即产第一帧；采集失败如实进 issues，**不打断
  导入**（R2-F，`test_import_all_skips_docked_and_reports_collect_errors`）。

## 5. 连接器适配（四家 usage.py，真机全通）

| 连接器 | 通道 | 快照 | 聚合 | 流水 | 方言要点（协议发现） |
|---|---|---|---|---|---|
| trae_cn | ent_usage（复用 provision 凭据装配） | ✓ user_entitlement_pack_list | ✓ usage_summary 原话 | ✗ None | credits 语义；credits_limit < 0（-1=无限）不建包（如实）；无流水通道（PROTOCOL §7.3 双通道 UNSUPPORTED） |
| qoder_cn | v2/me/usage 直投影 qoderUsage | ✓ userQuota + addOnQuota 组包 | ✓ | ✗ None | total=0 建空包如实；expiresAt/refreshAt=9999 占位 → cycle_end=None（待登录态补证）；缺客户端头 = 拒绝（与端侧同口径） |
| doubao_cn | quota/records（**零凭据**：CDP 读 Cookie，ADR-005） | ✗ None | ✗ None | ✓ 流水翻页（cursor，≤10 页） | 15 条全正值实证（入账语义）；probe 失败 CdpError 上抛 → outcome.error 如实 |
| workbuddy_cn | get-user-resource（凭据现用现取，ADR-006） | ✓ 85 包分账本 | ✗ None | ✗ None | 时间字段必须字符串（Go unmarshal 400 实证）；Capacity* 缺失用 *Precise 字符串兜底转换；CycleEndTime 月末时区 +08:00 破半天——月内计算不取边界 |

授权装配全部复用既有 kind 机制（ss_aes/dpapi_gcm_v10/umid_cosy →
fill_auth_headers 单源），零平行代码（kind 收敛原则）。

## 6. server 雷达域（routes/usage.py，契约派生）

- `POST /usage/collect`：全账号采集，逐账号 CollectUsage，**单账号失败不
  拖累其余**（outcome 分列 snapshot_saved/aggregate_saved/ledger_saved/
  quota_low/error，如实不造总结论）。
- `GET /usage/radar`：每账号一行——最新快照包列表 + 相邻差分预测
  （不足两帧 = 空列表 → UI「采集中」）+ `quota_low`（core `is_quota_low`
  现算的包 id，投影非决策）+ 聚合原话 + 最近 10 条流水。
- **一键批量**（2026-11-12 增补）：`POST /apps/import-all` + `/runs/claim-all`
  ——编排语义归 server，端零入参；真机实测：导入对无客户端家如实报修复
  建议；领取幂等回放当日班次 Run 不重打。
- 契约流水线照旧：`pnpm gen:sdk` 再生成，types.ts 派生零手写（红线 4）。

## 7. web 额度雷达页（RadarPage.vue，六页 IA 收编）

- 数据自持：`GET /usage/radar` + 手动 `POST /usage/collect`，不搭 App 轮询便车。
- 渲染纪律（红线 2）：forecast 缺失如实显「采集中」；quota_low 是 core 谓词
  出产的包名列表（布尔标记）；aggregate_summary 原话折叠直渲染不重排。
- 视觉（钱包视觉语言批对齐）：face 色横幅节头；活跃包平铺 + 历史耗尽折叠
  （status 原话判别，端零映射）。

## 8. MCP stdio 薄壳（apps/mcp，ADR-008）

- **宿主形态**：官方 mcp 2.x MCPServer（v1 FastMCP 已更名）stdio；
  **纯 HTTP 投影 server 契约 API——零 core/engine import**，server 零改动
  无契约再生成。
- **三工具**：`query_quota`（GET /usage/radar 拆额度面：packages/forecasts/
  quota_low）、`query_usage`（同源拆用量面：aggregate_summary/recent_ledger）、
  `claim_now`（POST /runs 直传）；可选 provider 过滤（选取不是映射）。
- **红线 5**：server 不可达/HTTP ≥400 → 显式转述附启动命令
  （`uv run uvicorn server.main:app --port 8000`），绝不静默兜底。
- **启动**：`uv run kabao-mcp`（stdio；`KABAO_SERVER_URL` 覆盖 base URL）。
- 验收：stdio 真客户端冒烟（握手/列工具/无 server 调用全过）+ MockTransport
  单测；真 LLM 客户端注册验收挂账（见 §11）。

## 9. 红线映射

- 红线 2（端零映射）：quota_low/forecast/signal 全 core 出产；web/MCP 只投影
- 红线 4（契约先行）：两端点 + 一键批量全走 gen:sdk 再生成，DTO 派生零手写
- 红线 5（显式报错）：负值流水拒绝/9999 占位如实/通道缺失 None/doubao probe
  失败上抛/MCP server 不可达显式转述——无一静默
- 红线 7（门禁）：每批实跑 `verify_project.py --test` 全绿（本批后 Windows
  首跑口径已加固，见 STATUS 2026-11-13 段）

## 10. 验收记录（真机）

- 四家连接器用量适配：trae（29 包 + 聚合）/ qoder（2300/1786/514 等）/
  doubao（流水 15 条全正值 + 翻页）/ workbuddy（85 包分账本 remain 1894）
  ——真机采集全通，协议发现回填各家 PROTOCOL §7。
- doubao CDP 读用量无增量价值（UI 只有累计获得，与 detail 重复）——
  ADR-005 三选一裁决「不做」，材料齐。
- MCP stdio 冒烟 + 一键批量真机实测（导入如实分列/领取幂等回放）。

## 11. 挂账（随实现回填）

1. MCP 真机 LLM 客户端验收：注册命令 `uv run kabao-mcp`，待用户在真
   LLM 客户端（Claude Code/Cursor 等）注册后全链验证（本仓已过 stdio
   冒烟 + MockTransport 单测）。
2. qoder expiresAt/refreshAt=9999 占位的真实 cycle 语义待登录态补证。
3. workbuddy 85 包分账本的分组语义（主套餐/加餐包名原话）UI 尚按原话平铺，
   分组聚合待雷达页迭代。
4. 耗尽预测帧距下限 1h 的产品语义（是否可调）随使用反馈再定。
