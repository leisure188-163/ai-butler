# A2-09 · platforms 域（平台册）

> 结构：[A1-05 §2](../architecture/A1-05-按业务域重写总设计.md)
> 上游：连接器 manifest（A2-02 §2）；下游：accounts（platform_code 引用）、
> scheduling（按平台排班）、execution（按平台路由端口）

## 1. 职责与边界

连接器平台事实（Platform）的落库与分发——**第六业务域**（ADR-022）。平台被
账户/调度/执行多域引用，独立成域避免寄居账户域造成引用倒挂；域间不互依
（A1-05 §2），其它域只持 `platform_code` 字符串引用。

- 管：平台事实（code/display/能力/凭据 kinds/排班）、启用开关、deprecated 生命周期
- 不管：连接器装载（connectors 包，A2-02）、账户名册（A2-04）、调度编排（A2-08）

## 2. 实体与不变量

### 2.1 plat_platform 表（ADR-021/022）

- **不变量 1**：DB 为真相源——启动时组合根从 manifest 抽纯数据 facts →
  `SyncPlatforms` 用例 → UPSERT 全量平台；manifest 里消失的平台落
  `deprecated_at`（**不删行**，审计可溯），幂等重复运行返回空
- **不变量 2**：`platform_code` UNIQUE；代理键 `id INTEGER PRIMARY KEY
  AUTOINCREMENT`（A4-01 §5），UPSERT（ON CONFLICT platform_code）保键不漂移
- **不变量 3**：`is_active` = 用户侧开关；停用平台不出现在名册与一键导入
  （退役是 manifest 事实，deprecated 是生命周期，两者分开）

| 列 | 类型 | 语义 |
|---|---|---|
| `id` | INTEGER PK AUTOINCREMENT | 全库统一代理键 |
| `platform_code` | TEXT NOT NULL UNIQUE | 平台 id（连接器 manifest.id） |
| `platform_name` | TEXT NOT NULL | 平台名（命名裁决 ADR-023：显示名列按业务命名，禁 display_name 通用名） |
| `platform_kind` | TEXT NOT NULL DEFAULT '' | 平台类型词表（core `PLATFORM_KINDS`）：`web`=网页版 / `client`=本机客户端；manifest 侧必填，'' 仅历史行兼容（2026-11-18 裁决；列序在 client_version 之前） |
| `client_version` | TEXT NOT NULL DEFAULT '' | 本机客户端版本（同步时经 provision 端口只读探测；'' = 探不到/网页平台=未知，2026-11-18 裁决；列序在 capabilities 之前）。事实源按连接器形态分两路：adapter 型实现 `read_client_version()`（豆包 = 卸载注册表 / Info.plist，WorkBuddy = `app_version`，Qoder = 版本目录 manifest），声明式型经 `version_probe` 按 conn_id 查表（Trae CN / WorkBuddy / Qoder）。通用口径见 `butler_connectors/app_version.py`：Windows 卸载注册表 `DisplayVersion`、mac `Info.plist CFBundleShortVersionString`，多版本并存取最新（2026-11-19） |
| `capabilities` | TEXT JSON | ActionKind.value 列表（core 词表） |
| `credential_kinds` | TEXT JSON | 凭据 kinds 声明 |
| `schedule_times` | TEXT JSON | HH:MM 触发时间并集（manifest 缺省事实，只读；不被用户编辑覆盖） |
| `schedule_override` | TEXT | 用户覆盖的调度执行时间：`''`=跟随 manifest，JSON 数组=覆盖（`[]`=不排班）；manifest 同步只更新事实列、**不覆盖本列** |
| `is_active` | INTEGER DEFAULT 1 | 用户开关（非数据库关键字，ADR-019） |
| `deprecated_at` | TEXT | manifest 缺失即落（不删行） |
| `created_at` / `updated_at` | TEXT NOT NULL | 统一审计列 |

DDL 权威单源 = `butler_engine/platforms/sqlite.py` `_SCHEMA`，生成视图
`data/sql/plat.sql`（勿手改，文件名 = 表名域前缀）。

## 3. 端口（platforms/ports.py）

- `PlatformRepository`：平台册持久化（upsert / deprecate_missing / get / list_all）

## 4. 用例

| 用例 | 语义 |
|---|---|
| `sync_platforms` | manifest facts 全量 upsert + 缺失平台落 deprecated（返回本次新标记 code） |

## 5. 端侧投影

- `GET /api/v1/platforms`：名册表 + 台账并账（account_ids 按账户域
  platform_code 归组）；deprecated / 停用平台不出现在响应
- 一键导入仍按 connectors registry 分发（需要活端口，名册只管事实）

## 6. 禁止

- ❌ 其它域 import 本域（只持 platform_code 字符串；域间互不依，A1-05 §2）
- ❌ 连接器装载/端口逻辑写进本域（那是 connectors 包 + 组合根的事）
- ❌ manifest 缺失就删行（deprecated 生命周期，审计可溯）

## 调度执行时间可编辑（2026-11-18 裁决）

- **写入口**：`PUT /platforms/{platform_code}/schedule`，body `{"times": ["09:15", ...]}`；
  `times=null` = 恢复跟随 manifest；`[]` = 该平台不排班（手动领取仍可用）。
- **校验**：HH:MM（与 `PlatformEntry.schedule_override` 同一正则）、去重升序；平台不存在 = 404。
- **生效**：server 落 DB 覆盖后重建调度条目（`compose_schedule_entries`：用户覆盖优先于 manifest 缺省）
  并 `kit.update_checkin_schedule(...)` 热替换（只换 entries、清触发去重集，job 不重启）→ **即刻生效**，
  无需重启主控。
- **启动路径同源**：组合根启动时同样走 `compose_schedule_entries`，与运行时改调度语义一致。
- **前端**：平台管理页「调度执行时间」详情行内「修改」→ 时间列表编辑（增删 HH:MM）→ 保存 / 恢复默认；
  被覆盖的行在展示上带「自定义」标记。

## 平台信息编辑（2026-11-18 裁决）

- **写入口**：`PATCH /platforms/{platform_code}`，body 只含要改的键：
  `platform_name`（显示名，空串 = 恢复 manifest 名，≤40 字）、`active`（启用状态）、
  `times`（调度执行时间，`null` = 恢复默认、`[]` = 不排班）。用 `model_fields_set` 区分
  "没传"与"传了 null"，未传的键一律不动。
- **不可编辑**：`platform_code`、`platform_kind`、`client_version`、`capabilities`、
  `credential_kinds` —— 都来自连接器 manifest 声明或本机探测，改了会和协议脱节。
- **生效**：写 DB 后重建调度条目并热替换 → 即刻生效；停用平台在 `compose_schedule_entries` 里被跳过。
- **GET 语义修正**：`/platforms` 只过滤 `deprecated_at`（退役），不再过滤 `is_active`；
  `PlatformOut` 新增 `active` 字段，`display` 取 `name_override or platform_name`。
