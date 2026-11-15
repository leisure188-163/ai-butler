# engine 适配器 + bridge 装配模式

> engine = 出站适配器层（COLA infrastructure 对照）。只实现 core 端口，不发明业务规则。

## 1. Sqlite*Store 模式

按域分目录：`packages/engine/src/butler_engine/<域>/sqlite.py`。先例：`usage/sqlite.py`。

```python
"""<域> 存储（A2-0x §n）：SQLite(WAL) 单库、每操作一连接、<排序契约>。"""

_SCHEMA = """
CREATE TABLE IF NOT EXISTS usage_samples (
    ...,
    PRIMARY KEY (account_id, record_id)   -- 复合主键 = 应用侧幂等
);
CREATE INDEX IF NOT EXISTS idx_... ;
"""

class SqliteUsageStore(UsageStore):        # 直接实现 core 端口
    def __init__(self, db_path: Path) -> None: ...
    def _connect(self) -> sqlite3.Connection: ...
    def append_sample(self, sample: UsageSample) -> None:
        with closing(self._connect()) as conn, conn:
            ...
```

纪律：
- 模块 docstring 声明：单库/WAL、每操作一连接、读序契约（如 ts 倒序）
- DDL = `_SCHEMA` 常量（建表 + `CREATE INDEX`）；只增不改的时序/台账表**不加** UPDATE 语义
- 幂等靠复合主键 `INSERT OR REPLACE`/`ON CONFLICT`，不靠先查后写
- 分页守卫在 store 层：`limit <= 0 → []`（`usage/sqlite.py:105-107`）
- 敏感字段不落明文（走 vault 层，`engine/vault/`）

## 2. 表设计纪律（提炼自通用 database-design，取适用子集）

ai-butler 是单机 SQLite、core 端口 + engine `_SCHEMA` 直写 DDL（无 SQLAlchemy/Alembic），因此：

适用（违反 = 打回）：
- 主键由应用侧生成（`shared.ids.new_id()`），禁依赖自增——为换库留路
- 禁无 `WHERE` 的 UPDATE/DELETE；生产列表禁 `SELECT *`
- 歧义字段加业务前缀（`status` → `run_status`）；索引 `idx_{表}_{字段}`
- 方言保留字作表名/列名 → **必须改名**，引号/转义规避同样不合规
- 时序/日志/审计表适用「例外条款」：只增不改，无 version/is_deleted，时间字段用业务语义名
- 批量写入控制条数；禁循环内逐条调用（N+1）

不适用（勿套用）：多租户 `tenant_id`、`version` 乐观锁、`is_deleted` 逻辑删、Alembic 迁移、金额 Numeric（本库额度用 float 且字段注释声明单位）——这些属通用 skill 的多租户/PostgreSQL 语境。

**schema 单一事实来源**：DDL 只活在 `_SCHEMA`；改表后必须跑 `scripts/dump_db_schema.py` 重新生成 `db/schema.sql`（表数计数动态，防漂移）。

## 3. bridge / kit 装配

`packages/engine/src/butler_engine/bridge.py` 是**唯一出桥**（ADR-001：端只准 `from butler_engine.bridge import ...`，机检）。

- `EngineKit` 数据类列举全部能力（`bridge.py:90-117`）
- 新能力装配 = 改 `build_engine()`（`bridge.py:323-384`）：构造适配器 → 塞进 EngineKit；需要配置就加 kwarg（先例：`pool_policies` → `VaultCredentialPool(vault, audit, policies=pool_policies)`，`bridge.py:357`）
- 注册类端口（同端口多实现）加 `register_*_ports()` 方法：带防撞车断言 + `replace=True` 重装配语义（`bridge.py:119-137`）
- 审计叠加 = EventBus 订阅（`AuditSubscriber`），不是手写审计行
- core 侧组装根 `packages/core/src/butler_core/bootstrap.py`（`Kit`/`build_kit`），只认端口协议

改动后同步：`EngineKit` 字段 ↔ `build_engine` 构造 ↔ bridge docstring 能力清单，三处一致。

## 4. 配置与拒启

- 文件配置源 = 数据根 JSON（如 `gateway-routes.json`），env `BUTLER_*` 覆盖
- **缺失 = 空表合法；非法 = 拒启**（显式 ValueError/SystemExit，`butler_gateway/routing.py` `load_routes` 先例）——缺失给默认值、坏数据必须停机，是本仓库一致语义
