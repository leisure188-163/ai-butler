# A2-04 · 账户域（accounts）

> 状态：**生效 v3.0（2026-11-20，ADR-033）**　总纲：[A2-01](A2-01-领域模型与动作模型.md) ·
> 结构：[A1-05 §2](../architecture/A1-05-按业务域重写总设计.md)
> 用户词：**账户**（Account）/ **应用**（App，2026-11-17 用户裁决，退役 Provider）/ **导入**（Import）/ **接入源**（Provider，ADR-033 仅指用户手建的上游）。
> 本域是全部业务标识的锚点。

## 1. 职责与边界

- 管：App、Account 集合（多账号，ADR-003）、Credential、Entitlement、Session、
  账户注册与凭据导入入口、vault 端口（预警窗常量随域）。
- 不管：执行动作（execution）、用量计算（usage）、健康评级规则（health）——
  本域只提供账户事实，评级与动作由对应域消费。

## 2. 实体与不变量

```
App：Connector 的产品级身份（id + display + capabilities 申报源）
Account（聚合根）：
  address = (platform_code, account_code)；account_code 缺省 "main"，创建后冻结
  identity = AccountIdentity(nickname/email/uid/org/source_key)：真实身份，只显示/匹配
  origin = connector(连接器导入) | manual(用户手建)
  同一平台下 account_code 唯一；删除账户 = 软删除（deleted_at 落库，
  台账/审计保留 account_id）
Credential：kind(ss_aes/cookie/oauth/api-key) / slot(默认 default) / label /
  有效期 / 轮换历史
  ——凭据必须绑定 account，禁止按应用共享（ADR-003 §5）
Entitlement：余额 / 连签 / 上次领取窗口（按账号隔离；随聚合落 entitlement_json）
Session：存储位置 / 可迁移级别(local|inject|server)
```

不变量：
1. account_id 是全系统外键——Run/Event/Sample 一律挂它
2. 凭据明文永不离开 vault 端口背后（core 只见句柄与元数据）
3. `(platform_code, account_code)` 缺省落位规则：存量单账号数据迁移时
   account_code = "main"，零信息丢失（迁移测试钉死，A1-05 §5 P4）
4. **编址冻结（ADR-033）**：`account_code` 创建后不再跟随昵称/身份变化；
   `save()` 在适配器侧守卫生效（库中 platform_code/account_code 与传入不一致 → `AccountInvalid`）
5. **身份与来源分离（ADR-033）**：昵称/邮箱/uid 只进 `identity`，编址只用
   `(platform_code, account_code)`；连接器侧可用 `identity.source_key` 认回旧账户，
   取不到就不猜

### 2.1 acc_account 表 v3（2026-11-17，ADR-018/019/020；表名纪律 ADR-021）

统一审计字段 `id / created_at / updated_at` 所有表必备（本表先行立范式，
其余域分批跟进）；每表代理键 `id INTEGER PRIMARY KEY AUTOINCREMENT`（DDL
约定见 A4-01 §5）。DDL 权威单源 = `butler_engine/accounts/sqlite.py`
`_SCHEMA`，生成视图 `data/sql/acc.sql`（勿手改，文件名 = 表名域前缀）。表名带域前缀
`acc_account`（ADR-021 表名纪律）。

| 列 | 类型 | 语义 |
|---|---|---|
| `id` | INTEGER PK AUTOINCREMENT | 全库统一代理键（ADR-019） |
| `account_id` | TEXT NOT NULL UNIQUE | 规范 id `{platform}:{account_code}`（原表主键，降级为业务键；编址不变） |
| `platform_code` | TEXT NOT NULL | 连接器/平台 id（provider→app→platform→platform_code，ADR-018/019/020） |
| `account_code` | TEXT NOT NULL DEFAULT 'main' | 平台内账号序（原 account_key，ADR-020）；`UNIQUE(platform_code, account_code)` 数据库级兜底不变量；ADR-033 起创建后冻结 |
| `account_name` | TEXT NOT NULL | 账户名（ADR-020 列名 code 化；ADR-023 显示列按业务命名） |
| `alias` | TEXT NOT NULL DEFAULT '' | 用户别名（ADR-030）；显示优先级最高 |
| `base_url` | TEXT | 账户级 API 基址（Qoder CN/Global 双 host 与接入源账户覆盖；空 = 用接入源缺省） |
| `device_ref` | TEXT | 供应商侧账户标识绑定；unbound 如实 NULL（§4.1） |
| `identity_json` | TEXT | AccountIdentity 落库（nickname/email/uid/org/source_key）；空身份 = NULL（ADR-033） |
| `origin` | TEXT NOT NULL DEFAULT 'connector' | connector / manual（ADR-033） |
| `last_seen_at` | TEXT | 最近一次连接器看到该账户（运营字段，ADR-033） |
| `sessions` | TEXT JSON DEFAULT '[]' | 会话清单（随聚合整体替换，§4.1） |
| `entitlement_json` | TEXT | Entitlement 聚合落库（balance/streak/last_claim_window） |
| `is_active` | INTEGER DEFAULT 1 | 用户管理开关（不用 enabled——数据库关键字风险，ADR-019）；调度 tick 跳过停用账户（停用是运营动作，≠健康熔断） |
| `created_at` | TEXT NOT NULL | 创建时间 |
| `updated_at` | TEXT NOT NULL | 统一审计列；save 时写当前时刻，老库回填 created_at |
| `deleted_at` | TEXT | 软删除标记（不变量 3 落库） |

索引：`uq_acc_account_platform_code_key (platform_code, account_code)` 唯一 + `idx_acc_account_platform_code (platform_code)`。
save = `INSERT … ON CONFLICT (account_id) DO UPDATE`（UPSERT 保代理键不漂移；
ADR-033 起 UPSERT 不再改写 platform_code/account_code）。
老库自迁移幂等：v1/v2 形状（TEXT 主键 + provider/app 列）走重建式迁移（Python 回填
account_code/updated_at 后旧表让位换 v3，行数据零丢失）；v3 形状缺列 ALTER 纯增量，
物理列序按 `_DDL_COLS` 重建校正（ADR-033）。

### 2.2 显示标签单源（ADR-033）

`account_label(account)` 在 core 单源计算，端侧与前端只消费结果，不落库：

`alias > identity.nickname > account_name 的「平台名 · 」后缀 > account_name > account_code`

不新增 `display_name` 列（SQL 规范 06 禁止该列名）；重名不唯一，后续如需消歧再加短码。

### 2.3 凭据槽位（ADR-033）

- 同一账户可有多份同 kind 凭据：`slot` 区分（`[A-Za-z0-9_-]{1,24}`），`label` 只做显示（≤40）。
- `vault_ref` 保持兼容：默认槽 `{account}:{kind}`（存量秘密零迁移），
  非默认槽 `{account}:{kind}@{slot}`，轮换归档再追加 `#{seq}`。
- `vault_item` 唯一键 = `(account_id, kind, slot)`；`credential pool` 缓存键同为三元组。
- 整账户撤销仍走 `revoke()`（全部槽位）；单槽撤销走 `revoke_slot()`。

## 3. 端口（accounts/ports.py）

- `VaultPort`：凭据存取/轮换/撤销（engine 实现；本地凭据解锁链，承袭 M1 收敛裁决 ADR-008）。
  ADR-033 起 `store/load/rotate` 带 `slot`/`label`；`revoke_slot(account, kind, slot, reason)`
  撤销单槽（非抽象默认方法：老替身不实现即显式 NotImplementedError，不静默假成功）
- `CredentialPool`：凭据池端口（ADR-012 裁决 3：现用现取 + 短 TTL 缓存，策略 =
  `CachePolicy` kind 数据；网关反代热路径唯一取凭据入口，任何 acquire 含缓存
  命中全审计；缺凭据显式抛承 VaultPort.load 语义；缓存键 = (account, kind, slot)）
- `SessionSourcePort`：本机会话/凭据扫描与导入（dock/浏览器通道的数据面）；
  R5-S1 增 `scan_sessions(app)`——只读枚举 `SessionSighting`
  (location, kind, level, device_ref=供应商侧账户标识)，绑定不可得如实 None
- `AccountRepoPort`：账户集合的持久化（Repository 接口隔离，A1-02 §6）；
  `list_by_platform(app)` 列多账号

## 4. 用例

| 用例 | 语义 |
|---|---|
| `register_account` | 连接器扫描的幂等回放；`(platform_code, account_code)` 已存在 → 返回既有账户不改号；带 `identity.source_key` 时按稳定身份键认回旧账户，不新建卡（ADR-033） |
| `create_account`（ADR-033） | 用户手建（API 型接入源/漏扫小号）：`account_code` 缺省由端侧生成后冻结；可带首份凭据（凭据先写、账户落库失败则 `purge` 回滚） |
| `update_account`（ADR-033） | 只改 alias / account_name / is_active / base_url / identity；编址与 origin 无改写入口 |
| `add_credential` / `revoke_credential`（ADR-033） | 追加/撤销单个凭据槽位；形状校验在 core，账户存在性由端侧先查 |
| 导入多账号 | SessionSourcePort 枚举本机多 profile/多开，逐账号入库（ADR-003 §3；连接器侧逐家取证随 P5 落地，见 A2-02 §5 沙箱） |
| `scan_sessions`（R5-S1，ADR-013） | 只读枚举 → device_ref 绑定（vault device 类凭据匹配）→ 组 Session 追加聚合（(location,kind,level) 去重幂等）→ repo 回写；绑定不可得 = 如实 unbound 分列不入库 |

### 4.1 会话实体与绑定（R5-S1）

- `Session`：account_id / location / kind（`SessionKind`: workspace \| conversation，
  ADR-013 裁决 1 首批只 workspace）/ level（`SessionLevel`: local \| inject \| server）
- 持久化：acc_account 表 `sessions` JSON 列（随聚合整体替换；老库 ALTER 自迁移）
- 绑定键约定：扫描器 device_ref = 供应商侧账户标识；trae = state.vscdb key
  账户数字前缀（PROTOCOL §10）。**device_dn ≠ 账户 id**——trae 绑定数据面
  待 dock 增捕 `aha_account_id`（S1.5，storage.json `icube_gtm`/`checkin1024.*`
  键名明文可取，非敏感）；本机真跑 38 观测全 unbound = 台账语义如实呈现

## 5. 事件联动

- 凭据到期/将到期事件（CREDENTIAL_EXPIRING / CREDENTIAL_EXPIRED）由 health 域
  扫描产出，事件源头是本域的凭据事实；severity 与通知口径见 A4-01。

## 账户删除与名册真相源（2026-11-19 用户裁决）

- **`GET /api/v1/accounts` 只读 `acc_account`**：账户数据的唯一真相源是账户表。
  此前「账户册 ∪ vault 凭据账号」会把删掉账户行的凭据顶成幽灵账户，造成删不干净的错觉；
  现在 `vault_item` 只作为账户的附属投影（凭据列），不再单独造账户行。
- **`DELETE /api/v1/accounts/{account_id}` = 账户行 + 关联凭据一并删除**：
  `DeleteAccount` 用例先 `vault.purge(account_id)`（主引用、`#seq` 历史归档、`vault_item`
  与 `vault_history` 行全删，不留 revoked 行），再 `accounts.remove`；账户不存在 404，
  不会误清同名凭据。返回清掉的凭据条数（`credentials_deleted`）。
- **不碰平台与台账**：平台名册、`exe_claim` 历史与审计保留；删除账户后重新导入本机客户端
  即可恢复（新凭据重新入库）。

## 5.1 写入端点（ADR-033，2026-11-20）

| 端点 | 语义 |
|---|---|
| `POST /api/v1/accounts` | 手建账户：平台必须存在且未退役；`account_code` 缺省 `acc_<8hex>` 并冻结；kind/secret 成对；平台申报了 credential_kinds 时校验类型；重复编码 409 |
| `PATCH /api/v1/accounts/{account_id}` | 改 alias / account_name / active / base_url / identity（`model_fields_set` 区分「没传」与「传了空」）；编址不可改 |
| `POST /api/v1/accounts/{account_id}/credentials` | 追加凭据槽位（kind/secret/slot/label/expires_at） |
| `DELETE /api/v1/accounts/{account_id}/credentials/{kind}/{slot}` | 撤销单槽；不存在或已撤销 404 |

响应新增字段：`account_label` / `identity` / `origin` / `base_url` / `active` / `last_seen_at`；
凭据新增 `slot` / `label`。`AccountOut` 里的 `account_label` 由 core `account_label()` 单源计算。

## 6. 禁止

- ❌ 账户状态/健康分级逻辑写进本域（那是 health 域的）；`is_active` 是用户管理
  开关（运营动作事实），不是健康评级
- ❌ UI 导航出现 app id（实现细节下沉）
- ❌ 凭据形状/解密逻辑散出 vault 端口
- ❌ 术语回潮：新代码禁用 provider 指代应用（A1-03 退役词；外部机制如
  第三方 LLM provider 描述除外）
