"""SQLite 迁移器（ADR-036）：全库 schema 真相源 = 本目录编号迁移文件。

取代域适配器 DDL 常量 + `__init__` 隐式自迁移（旧裁决 06-SQL规范/A4-01 §5）。
为开源后的**多人协作、DBA 审查、多服务共享一个库**做准备：

- **编号迁移文件**：`NNN_描述.sql`，随源码/包分发（迁移历史是源码资产）；
  forward-only，❌ 禁止 down-migration（回滚 = 备份还原，与 journal_mode=OFF 一致）。
- **版本表 `db_migration`**（version/name/checksum/applied_at）由本模块**自举**
  （先于迁移链建表，不作迁移条目——06-SQL规范的唯一例外）。不用
  `PRAGMA user_version`：多服务共享库时版本必须可见可查。
- **幂等追跑**：已应用版本按 checksum 校验文件未被篡改（改历史迁移 = 红线 5），
  改表 = 新增编号迁移文件；编号必须从 001 起连续无空洞/重复。
- **存量库 baseline**：迁移链首跑但业务表已在（开源切换前的旧库）→ 校验
  acc_account 列集 = v4 基线后记 001 为已应用（不执行 SQL）；不符显式退出，
  开源切换时刻不背 v1/v2/v3 兼容。
- **原子性如实登记**：journal_mode=OFF 无回滚日志，"执行迁移"与"记账"之间
  的崩溃窗口靠备份兜底（与 conn.py 既有纪律一致，不做伪原子）。

旧品牌库搬移（ai-marina → butler.db）仍在 `butler_engine.db.migrate`，
与本模块无关。
"""

from __future__ import annotations

import hashlib
import importlib.resources
import sqlite3
from pathlib import Path

from butler_engine.db.conn import connect

_VERSION_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS db_migration (
    version    INTEGER PRIMARY KEY,
    name       TEXT NOT NULL,
    checksum   TEXT NOT NULL,
    applied_at TEXT NOT NULL
);
"""

#: 存量库 baseline 探测表与权威列集（= 001_initial.sql 的 acc_account，v4 形状）
_BASELINE_PROBE = "acc_account"
_BASELINE_COLS = frozenset({
    "id", "platform_code", "source_key", "account_id", "account_code",
    "account_name", "alias", "base_url", "device_ref", "identity_json",
    "origin", "last_seen_at", "sessions", "entitlement_json", "is_active",
    "created_at", "updated_at", "deleted_at",
})


class MigrationError(RuntimeError):
    """迁移链完整性破坏（篡改/空洞/重复/缺文件）——显式报错不静默（红线 5）。"""


def _discover() -> list[tuple[int, str, str]]:
    """读本目录迁移文件：(version, filename, sql)。编号必须 001 起连续无空洞。"""
    files = importlib.resources.files(__package__)
    found: list[tuple[int, str, str]] = []
    for item in sorted(files.iterdir(), key=lambda p: p.name):
        if not item.name.endswith(".sql"):
            continue
        stem = item.name.removesuffix(".sql")
        version_part, sep, _desc = stem.partition("_")
        if not version_part.isdigit() or not sep:
            raise MigrationError(f"迁移文件名必须 NNN_描述.sql：{item.name}")
        sql = item.read_text(encoding="utf-8").replace("\r\n", "\n")
        found.append((int(version_part), item.name, sql))
    return found


def _validate_numbering(files: list[tuple[int, str, str]]) -> None:
    for expected, (version, name, _sql) in enumerate(files, start=1):
        if version != expected:
            raise MigrationError(
                f"迁移编号空洞/不连续：期望 {expected:03d}，实际 {version:03d}（{name}）"
            )


def _checksum(sql: str) -> str:
    return hashlib.sha256(sql.encode("utf-8")).hexdigest()


def _record(conn: sqlite3.Connection, version: int, name: str, sql: str) -> None:
    conn.execute(
        "INSERT INTO db_migration (version, name, checksum, applied_at)"
        " VALUES (?, ?, ?, datetime('now'))",
        (version, name, _checksum(sql)),
    )
    conn.commit()


def migrate(
    conn: sqlite3.Connection, files: list[tuple[int, str, str]] | None = None
) -> list[int]:
    """幂等追跑到最新；返回本次新应用的版本号列表（baseline 记账也计入）。"""
    files = _discover() if files is None else sorted(files, key=lambda m: m[0])
    if not files:
        raise MigrationError("迁移文件列表为空")
    _validate_numbering(files)
    conn.execute(_VERSION_TABLE_DDL)
    applied = dict(conn.execute("SELECT version, checksum FROM db_migration"))
    missing = sorted(set(applied) - {v for v, _n, _s in files})
    if missing:
        raise MigrationError(
            f"已应用迁移 {missing} 在当前安装的迁移文件里不存在（安装被回退？禁止降级运行）"
        )
    applied_now: list[int] = []
    for version, name, sql in files:
        recorded = applied.get(version)
        if recorded is not None:
            if recorded != _checksum(sql):
                raise MigrationError(
                    f"迁移 {version:03d}（{name}）已应用但文件内容与记账 checksum 不符"
                    "——迁移被篡改 = 红线 5；禁止改历史迁移，改表请新增迁移文件"
                )
            continue
        # 存量库 baseline：链首 + 无任何记账 + 业务表已在 → 校验形状后只记账不执行
        if version == files[0][0] and not applied:
            cols = {r[1] for r in conn.execute(f"PRAGMA table_info({_BASELINE_PROBE})")}
            if cols:
                if cols != _BASELINE_COLS:
                    raise SystemExit(
                        f"存量库 {_BASELINE_PROBE} 列集与本版本 001 基线不符"
                        f"（现有 {len(cols)} 列，基线 {len(_BASELINE_COLS)} 列）——"
                        "请先用旧版本把库升到 v4 形状再换用本版本（开源切换不背 v1/v2/v3 兼容）"
                    )
                _record(conn, version, name, sql)
                applied_now.append(version)
                continue
        conn.executescript(sql)
        _record(conn, version, name, sql)
        applied_now.append(version)
    return applied_now


def current_version(conn: sqlite3.Connection) -> int:
    """当前已应用的最大迁移版本；未迁移/无版本表返回 0。"""
    if conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='db_migration'"
    ).fetchone() is None:
        return 0
    row = conn.execute("SELECT MAX(version) FROM db_migration").fetchone()
    return row[0] or 0


def migration_status(conn: sqlite3.Connection) -> dict:
    """只读状态快照（CLI `butler db status` 用；不建表不迁移）。"""
    files = _discover()
    applied: list[tuple] = []
    if conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='db_migration'"
    ).fetchone() is not None:
        applied = conn.execute(
            "SELECT version, name, applied_at FROM db_migration ORDER BY version"
        ).fetchall()
    return {
        "current": current_version(conn),
        "latest": files[-1][0],
        "latest_name": files[-1][1],
        "applied": applied,
    }


def ensure_migrated(target: "str | Path | sqlite3.Connection") -> list[int]:
    """统一迁移入口：接连接或库路径均可，幂等追跑到最新。"""
    conn = target if isinstance(target, sqlite3.Connection) else connect(target)
    return migrate(conn)


def open_db(db_path: "str | Path") -> sqlite3.Connection:
    """全调用点统一入口（ADR-036 起）：connect() + ensure_migrated()。"""
    conn = connect(db_path)
    migrate(conn)
    return conn
