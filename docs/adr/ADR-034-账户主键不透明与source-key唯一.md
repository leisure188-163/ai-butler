# ADR-034 账户主键彻底重置：不透明 account_id + source_key 唯一锚点

- 状态：已接受并已执行（2026-11-20 用户裁决 B「彻底重置」）
- 关联：ADR-003（一人多账号）、ADR-025（昵称编址，编址部分被本 ADR 取代）、ADR-029（凭据按账户隔离）、ADR-033（编址冻结/身份分离/槽位，其 §1 被本 ADR 取代）、A2-04、A2-09
- 触发：真库同步后检查发现 `account_id` 混入平台名、昵称、`main` 占位与哈希，无法作为账户唯一性依据。

## 背景与证据（迁移前真库）

- 8 个账户的 `account_id` 均为 `{platform_code}:{account_code}`，而 `account_code` 由各连接器自行定义：
  - 豆包用昵称（`doubao_cn:逍遥酒鬼`、`doubao_cn:Leisure520`）；
  - Qoder 用 `main` 或 `region-sha1`（`qoder_cn:global-020dbc5a`）；
  - Trae / WorkBuddy / AgentRouter 用 `main`。
- 8 条账户的 `identity_json` 全为 `NULL`；连接器没有回传稳定身份键。
- `RegisterAccount` 先按拼接 id 查找、命中即返回，导致：
  1. 同平台同昵称的两个真人被静默并成一张卡；
  2. 同一个人改昵称后可能重复建卡；
  3. `main` 是占位符，不是身份，多个不同账号共享同一主键语义。
- 表上虽然有 `UNIQUE(account_id)` 与 `UNIQUE(platform_code, account_code)`，但唯一性建立在“展示名/连接器键”上，不是建立在“真实人”上。

## 裁决

### 1. `account_id` 不透明、不可变

- 新账户 id 固定为 `acc_<8hex>`（`uuid4` 前 8 位并查重），不从平台、昵称、编码推导。
- 存量 8 条 id 全部重发（方案 B），依赖表同步迁移；不做“新旧并存”。
- `account_code` 保留为平台内连接器键（豆包昵称 / Qoder region-hash / 其余 main），仍受 `UNIQUE(platform_code, account_code)` 约束，但不再参与主键。

### 2. `source_key` 是唯一身份锚点

- `acc_account` 新增独立列 `source_key TEXT NOT NULL DEFAULT ''`。
- 唯一约束：`UNIQUE(platform_code, source_key) WHERE source_key <> ''`（空串不占用，允许未知身份）。
- 注册顺序：
  1. `source_key` 命中 → 认回既有账户（改名、改 code 都不新建）；
  2. 未命中 → 按 `(platform_code, account_code)` 查；
  3. code 命中但两边 source_key 都有值且不同 → `AccountConflict`，显式拒绝，**绝不静默复用**；
  4. 存量 `source_key = legacy:<code>` 占位键，在首次真实 dock 时就地吸收为真实键。
- 连接器回传口径：
  - 豆包：`sec_uid`；
  - Qoder：`user.id`；
  - Trae：Aha 设备号；
  - WorkBuddy：`account.uid`；
  - AgentRouter：`github_<user_id>`；
  - 浏览器抓取：会话内可得的稳定 id；取不到则留空。

### 3. 依赖迁移

一次性脚本 [`scripts/migrate_account_ids.py`](../../scripts/migrate_account_ids.py)，默认 dry-run，`--apply` 才写库：

- 重发 `acc_account.account_id`，回填 `source_key`，清理 `identity_json` 中重复的 source_key；
- 复制 Windows 凭据管理器条目到新 `vault_ref`（旧条目保留不删，可回滚），改写 `vault_item` / `vault_history`；
- 改写 `exe_claim` / `usage_snapshot` / `usage_aggregate` / `usage_quota_ledger` / `usage_sample` / `audit_log` / `_acc_account_old_*`；
- 改写 `health_state` 的 `acct:` / `cred:` 键，删除无法映射的陈旧键；
- 改写 `gateway-routes.json` 中显式 `account_id`；
- 输出 `account-id-map.json` 到备份目录。

## 执行结果（2026-11-20 真库）

- 迁移前备份：`data/database/backup-account-reset-20261120/butler.db`（`integrity_check=ok`）。
- 8 个账户新 id：`acc_a9fe6583`（豆包·逍遥酒鬼）、`acc_916d0c74`（豆包·Leisure520）、`acc_0f29fdb5`（Qoder main）、`acc_37fca3ef` / `acc_f9611b6a`（Qoder Global 两号）、`acc_d6b05268`（Trae）、`acc_ded94a26`（WorkBuddy）、`acc_019b0613`（AgentRouter）。
- source_key：豆包两条为 `sec_uid`，AgentRouter 为 `github_437667`；Qoder/Trae/WorkBuddy 存量为 `legacy:<code>` 占位，首次真实 dock 时吸收。
- 依赖行数不变：`audit_log 573`、`exe_claim 98`、`usage_snapshot 206`、`usage_aggregate 157`、`usage_quota_ledger 66`、`vault_item 9`、`vault_history 2`；`orphan_vault = 0`；9 条新凭据引用全部可读。
- 迁移后 `PRAGMA integrity_check = ok`；后端返回 8 账户 / 5 平台。

## 后果

- 账户唯一性由 `source_key` 承担，昵称只影响显示；同一真人改名不再漂移，不同真人同昵称不再合并。
- 旧复合 id 只保留在备份表与未映射的历史审计行（`doubao_cn:main` / `doubao_cn:u66b1e22d`），不再作为新写入。
- 回滚路径：停服 → 用备份库覆盖 `data/database/butler.db`；旧 `vault_ref` 未删除，可直接读取。
