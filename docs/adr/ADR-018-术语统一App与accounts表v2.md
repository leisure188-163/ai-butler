# ADR-018 · 术语统一 App 与 accounts 表 v2

日期：2026-11-17　状态：已裁决（用户裁决）　影响域：accounts / 全库术语 / 生成视图

## 背景

同一个"AI 产品身份"概念在端侧叫**应用**（`/apps`、`AppOut`、`registry.apps()`），
在 core/engine 数据层却叫 **Provider/`provider`**，两套词并存。同时 accounts 表
v1（id/provider/display_name/created_at/sessions）落后于 `Account` 聚合：
account_key 无显式列（唯一性不变量无数据库兜底）、软删除无落库、Entitlement
不持久化、无 updated_at 审计列、账户级 API 基址散在连接器代码（Qoder CN/Global
双 host 教训）。

## 决策

1. **术语统一**：用户裁决，全库退役 provider，统一为 **App/应用**
   （数据列 `app`、端口 `list_by_app`、DTO `AppOut`/`AccountOut.app`、领域类
   `App`）。第三方外部机制描述（如 WorkBuddy/Trae 内嵌 LLM provider 矩阵、
   `key_provider` 解密参数）不属本域概念，保留原文。词表收编见 A1-03 §3。
2. **accounts 表 v2**：显式 `account_key` + `UNIQUE(app, account_key)`；
   `base_url`/`device_ref`/`entitlement_json`/`enabled`/`deleted_at` 把聚合事实
   落全；统一审计字段 `id / created_at / updated_at`（本表先行立范式，其余域
   表分批跟进——`updated_at` 语义 = save 时刻；audit 是 append-only 台账不加）。
   `enabled` 是用户管理开关：调度 tick 跳过停用账户，与健康域熔断（A2-07）
   正交不互替。
3. **迁移纪律**：老库自迁移幂等（RENAME COLUMN + ALTER 纯增量 + 回填），不引入
   破坏性变更；schema 视图 `data/sql/accounts.sql` 随生成脚本刷新（勿手改）。

## 后果

- API 契约变化：`AccountOut/RadarAccountOut.provider` → `app`（SDK 已重生成，
  web 三处组件同步）；网关 `/health` 观测键 `provider_adapters` → `app_adapters`。
- 其余域表补 `updated_at` 为后续批次（A4-01 §5 schema 演进纪律走显式迁移）。
- A2-04 升 v2.0；A2-01/A2-02/A2-03/A1-02/A1-05 术语行同批回收（红线 8）。
