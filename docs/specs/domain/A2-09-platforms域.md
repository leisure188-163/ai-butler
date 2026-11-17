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
| `client_version` | TEXT NOT NULL DEFAULT '' | 本机客户端版本（同步时经 provision 端口只读探测；'' = 探不到/网页平台=未知，2026-11-18 裁决；列序在 capabilities 之前） |
| `capabilities` | TEXT JSON | ActionKind.value 列表（core 词表） |
| `credential_kinds` | TEXT JSON | 凭据 kinds 声明 |
| `schedule_times` | TEXT JSON | HH:MM 触发时间并集 |
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
