# ADR-024 · exe_run 改名 exe_claim（领取记录）并补审计三件

- 状态：已采纳（2026-11-17 用户裁决）
- 背景：原表名 `exe_run` 用了泛化的 run 命名；实际动作语义随平台而异——
  有的领积分、有的领 token，不能一概而论。且该表缺统一审计三件
  （id 为 TEXT 业务键、无 created_at/updated_at），违反 06-SQL规范 §1.1。
- 决策：
  1. 表改名 `exe_claim`（域前缀 exe + 实体 claim = 领取记录）；原运行 id
     改列 `run_id TEXT NOT NULL UNIQUE`（业务键），主键补
     `id INTEGER PRIMARY KEY AUTOINCREMENT`（全库统一代理键）。
  2. 补 `created_at`/`updated_at`（首插落 created_at = started_at；
     幂等回放走 ON CONFLICT(run_id) DO UPDATE，只刷 updated_at，不动 created_at）。
  3. 幂等索引随名：`idx_exe_claim_idempotency`。
  4. 代码层 Run 术语（core 领域模型、端侧 `/runs` 契约）保留不变——本轮只
     收编表名与审计纪律，SDK/前端零改动。
- 迁移（幂等，零数据丢失）：`runs` → `exe_run`（ADR-021 链）→ 旧行原样
  搬入 `exe_claim`（created_at=started_at，updated_at=COALESCE(finished_at,
  started_at)）→ DROP 旧表旧索引。
