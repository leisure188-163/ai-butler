# ADR-019 · 术语再统一 platform 与 accounts 表 v3（自增代理键 + is_active）

- 状态：已采纳（2026-11-17 用户裁决）
- 背景：ADR-018 把 provider 统一为 app 后，用户指出「应用」家族里有网页版产品，
  app 一词不贴切；同时要求把「整数自增 id + 审计字段」立为全库约束，且
  `enabled` 是数据库关键字不宜作列名。
- 决策：
  1. 全库术语 app → **platform**（平台）：连接器家族、accounts.platform 列、
     server 路由 `/platforms`、PlatformOut 契约、web 页名「平台」。保留不改：
     FastAPI/Typer 框架实例变量 `app`、AppBadge 组件名、`AppsPage.vue` 文件名、
     scheduling 域 `Trigger.enabled`（调度触发器自有字段，非 DB 列）、
     第三方 LLM provider 描述。
  2. accounts 表 v3：每表代理键 `id INTEGER PRIMARY KEY AUTOINCREMENT`；
     规范 id `{platform}:{account_key}` 降级为业务键 `account_id`（UNIQUE，
     编址不变）；`enabled` → `is_active`；save 用 UPSERT（ON CONFLICT
     account_id）保代理键不漂移。
  3. 全库 DDL 约定收编进 A4-01 §5：代理键 + created_at/updated_at 必备 +
     禁用数据库关键字列名；其余 8 张表分批跟进。
- 后果：老库（v1 provider / v2 app 两种形状）走重建式迁移，行数据零丢失；
  路由 `/apps` → `/platforms` 是破坏性契约变更（前端与 SDK 同步重生成）。
