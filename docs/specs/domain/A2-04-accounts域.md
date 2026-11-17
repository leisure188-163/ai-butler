# A2-04 · 账户域（accounts）

> 状态：**生效 v2.0（2026-11-17，ADR-018）**　总纲：[A2-01](A2-01-领域模型与动作模型.md) ·
> 结构：[A1-05 §2](../architecture/A1-05-按业务域重写总设计.md)
> 用户词：**账户**（Account）/ **应用**（App，2026-11-17 用户裁决，退役 Provider）/ **导入**（Import）。
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
  identity = (app, account_key)；account_key 缺省 "main"
  同一 App 下 account_key 唯一；删除账户 = 软删除（deleted_at 落库，
  台账/审计保留 account_id）
Credential：kind(ss_aes/cookie/oauth/api-key) / 密文 / 有效期 / 轮换历史
  ——凭据必须绑定 account，禁止按应用共享（ADR-003 §5）
Entitlement：余额 / 连签 / 上次领取窗口（按账号隔离；随聚合落 entitlement_json）
Session：存储位置 / 可迁移级别(local|inject|server)
```

不变量：
1. account_id 是全系统外键——Run/Event/Sample 一律挂它
2. 凭据明文永不离开 vault 端口背后（core 只见句柄与元数据）
3. `(app, account_key)` 缺省落位规则：存量单账号数据迁移时
   account_key = "main"，零信息丢失（迁移测试钉死，A1-05 §5 P4）

### 2.1 accounts 表 v2（2026-11-17，ADR-018）

统一审计字段 `id / created_at / updated_at` 所有表必备（本表先行立范式，
其余域分批跟进）；DDL 权威单源 = `butler_engine/accounts/sqlite.py` `_SCHEMA`，
生成视图 `data/sql/accounts.sql`（勿手改）。

| 列 | 类型 | 语义 |
|---|---|---|
| `id` | TEXT PK | 规范 id `{app}:{account_key}`（编址不变） |
| `app` | TEXT NOT NULL | 连接器/应用 id（原 provider，改名） |
| `account_key` | TEXT NOT NULL DEFAULT 'main' | 应用内账号序；`UNIQUE(app, account_key)` 数据库级兜底不变量 |
| `display_name` | TEXT NOT NULL | 应用名（账号册出产） |
| `base_url` | TEXT | 账户级 API 基址（Qoder CN/Global 双 host 事实落库；空 = 用连接器缺省） |
| `device_ref` | TEXT | 供应商侧账户标识绑定；unbound 如实 NULL（§4.1） |
| `sessions` | TEXT JSON DEFAULT '[]' | 会话清单（随聚合整体替换，§4.1） |
| `entitlement_json` | TEXT | Entitlement 聚合落库（balance/streak/last_claim_window） |
| `enabled` | INTEGER DEFAULT 1 | 用户管理开关；调度 tick 跳过停用账户（停用是运营动作，≠健康熔断） |
| `created_at` | TEXT NOT NULL | 创建时间 |
| `updated_at` | TEXT NOT NULL | 统一审计列；save 时写当前时刻，老库回填 created_at |
| `deleted_at` | TEXT | 软删除标记（不变量 3 落库） |

索引：`uq_accounts_app_key (app, account_key)` 唯一 + `idx_accounts_app (app)`。
老库自迁移幂等：`provider` 列 RENAME → `app`、缺列 ALTER 纯增量、
account_key 按 id 反推回填、updated_at 回填 created_at、旧 `idx_accounts_provider` DROP。

## 3. 端口（accounts/ports.py）

- `VaultPort`：凭据存取/解锁（engine 实现；本地凭据解锁链，承袭 M1 收敛裁决 ADR-008）
- `CredentialPool`：凭据池端口（ADR-012 裁决 3：现用现取 + 短 TTL 缓存，策略 =
  `CachePolicy` kind 数据；网关反代热路径唯一取凭据入口，任何 acquire 含缓存
  命中全审计；缺凭据显式抛承 VaultPort.load 语义）
- `SessionSourcePort`：本机会话/凭据扫描与导入（dock/浏览器通道的数据面）；
  R5-S1 增 `scan_sessions(app)`——只读枚举 `SessionSighting`
  (location, kind, level, device_ref=供应商侧账户标识)，绑定不可得如实 None
- `AccountRepoPort`：账户集合的持久化（Repository 接口隔离，A1-02 §6）；
  `list_by_app(app)` 列多账号

## 4. 用例

| 用例 | 语义 |
|---|---|
| `register_account` | 建立 App 下账户并落库；`(app, account_key)` 冲突 → 显式拒绝 |
| 导入多账号 | SessionSourcePort 枚举本机多 profile/多开，逐账号入库（ADR-003 §3；连接器侧逐家取证随 P5 落地，见 A2-02 §5 沙箱） |
| `scan_sessions`（R5-S1，ADR-013） | 只读枚举 → device_ref 绑定（vault device 类凭据匹配）→ 组 Session 追加聚合（(location,kind,level) 去重幂等）→ repo 回写；绑定不可得 = 如实 unbound 分列不入库 |

### 4.1 会话实体与绑定（R5-S1）

- `Session`：account_id / location / kind（`SessionKind`: workspace \| conversation，
  ADR-013 裁决 1 首批只 workspace）/ level（`SessionLevel`: local \| inject \| server）
- 持久化：accounts 表 `sessions` JSON 列（随聚合整体替换；老库 ALTER 自迁移）
- 绑定键约定：扫描器 device_ref = 供应商侧账户标识；trae = state.vscdb key
  账户数字前缀（PROTOCOL §10）。**device_dn ≠ 账户 id**——trae 绑定数据面
  待 dock 增捕 `aha_account_id`（S1.5，storage.json `icube_gtm`/`checkin1024.*`
  键名明文可取，非敏感）；本机真跑 38 观测全 unbound = 台账语义如实呈现

## 5. 事件联动

- 凭据到期/将到期事件（CREDENTIAL_EXPIRING / CREDENTIAL_EXPIRED）由 health 域
  扫描产出，事件源头是本域的凭据事实；severity 与通知口径见 A4-01。

## 6. 禁止

- ❌ 账户状态/健康分级逻辑写进本域（那是 health 域的）；`enabled` 是用户管理
  开关（运营动作事实），不是健康评级
- ❌ UI 导航出现 app id（实现细节下沉）
- ❌ 凭据形状/解密逻辑散出 vault 端口
- ❌ 术语回潮：新代码禁用 provider 指代应用（A1-03 退役词；外部机制如
  第三方 LLM provider 描述除外）
