"""迁移器测试（ADR-036）：空库全链 / 幂等 / 存量库 baseline / checksum 篡改 /
编号完整性 / v1 旧形状显式拒绝。

旧品牌库搬移（marina）的测试在 test_migrate.py，互不相干。
"""

from __future__ import annotations

import sqlite3

import pytest

from butler_engine.db.migrations import (
    MigrationError,
    current_version,
    ensure_migrated,
    migrate,
    open_db,
)


def _table_names(conn: sqlite3.Connection) -> set[str]:
    return {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    }


def test_空库全链_建齐全库与版本表(tmp_path):
    db = tmp_path / "new.db"
    conn = open_db(db)
    tables = _table_names(conn)
    for table in (
        "acc_account", "plat_platform", "exe_claim", "usage_snapshot",
        "usage_aggregate", "usage_quota_ledger", "usage_sample",
        "health_state", "vault_item", "vault_history", "audit_log",
    ):
        assert table in tables, table
    rows = conn.execute("SELECT version, name FROM db_migration ORDER BY version").fetchall()
    assert rows == [
        (1, "001_initial.sql"),
        (2, "002_conform_proxy_key_audit.sql"),
    ]
    assert current_version(conn) == 2


def test_002合规化重建_业务键与审计列落位(tmp_path):
    """002：TEXT/复合主键 → id 代理键 + 唯一业务键，审计三件补齐，行数据零丢失。"""
    db = tmp_path / "old.db"
    # 只应用到 001，手插旧形状行（001 的 TEXT 主键形状）
    from butler_engine.db.conn import connect
    from butler_engine.db.migrations import _discover

    files = _discover()
    conn = connect(db)
    migrate(conn, files[:1])
    conn.execute(
        "INSERT INTO usage_snapshot (id, account_id, target, collected_at, packages_json)"
        " VALUES ('snap-1', 'acc1', 'doubao_cn', '2026-11-20T00:00:00+00:00', '[]')"
    )
    conn.execute(
        "INSERT INTO usage_quota_ledger (account_id, record_id, target, occurred_at,"
        " amount, unit, kind, raw_json)"
        " VALUES ('acc1', 'r1', 'doubao_cn', '2026-11-20T01:00:00+00:00', 1.5, 'token',"
        " 'gift', NULL)"
    )
    conn.commit()
    conn.close()

    migrate(connect(db), files)  # 追跑 002
    conn = connect(db)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(usage_snapshot)")}
    assert {"id", "snapshot_id", "created_at", "updated_at"} <= cols
    row = conn.execute(
        "SELECT snapshot_id, account_id, created_at, updated_at"
        " FROM usage_snapshot WHERE account_id = 'acc1'"
    ).fetchone()
    assert row[0] == "snap-1"  # 业务键拷回零丢失
    assert row[2] == "2026-11-20T00:00:00+00:00"  # created_at 以业务时点落值
    ledger = conn.execute(
        "SELECT record_id, amount, created_at FROM usage_quota_ledger WHERE record_id = 'r1'"
    ).fetchone()
    assert ledger[0] == "r1" and ledger[1] == 1.5
    assert ledger[2] == "2026-11-20T01:00:00+00:00"
    conn.close()


def test_重复跑幂等_零新增应用(tmp_path):
    db = tmp_path / "new.db"
    conn = open_db(db)
    assert migrate(conn) == []  # 已是最新，追跑零动作
    assert current_version(conn) == 2
    assert migrate(conn) == []
    assert current_version(conn) == 2


def test_存量库baseline_记001不执行_数据保留(tmp_path):
    """v4 形状旧库（无版本表）首跑：校验列集 → 记 001 已应用（SQL 未执行），
    后续迁移（002）照常执行。"""
    from butler_engine.db.conn import connect
    from butler_engine.db.migrations import _discover

    db = tmp_path / "legacy.db"
    files = _discover()
    # 造一个真实 v4 形状旧库：跑 001 建全库 + 插行 + 抹掉版本表（回到无记账时代）
    conn = connect(db)
    migrate(conn, files[:1])
    conn.execute(
        "INSERT INTO acc_account (platform_code, account_id, account_name, created_at, updated_at)"
        " VALUES ('doubao_cn', 'doubao_cn:main', '主卡', '2026-01-01', '2026-01-01')"
    )
    conn.execute(
        "INSERT INTO usage_snapshot (id, account_id, target, collected_at, packages_json)"
        " VALUES ('snap-1', 'acc1', 'doubao_cn', '2026-01-01T00:00:00+00:00', '[]')"
    )
    conn.execute("DROP TABLE db_migration")
    conn.commit()
    conn.close()

    applied = ensure_migrated(str(db))
    assert applied[0] == 1  # baseline 记账，001 SQL 未执行
    assert applied[-1] == len(files)  # 其后迁移照常执行
    conn = sqlite3.connect(str(db))
    assert conn.execute("SELECT COUNT(*) FROM acc_account").fetchone()[0] == 1
    assert conn.execute("SELECT account_name FROM acc_account").fetchone()[0] == "主卡"
    rows = conn.execute("SELECT version FROM db_migration ORDER BY version").fetchall()
    assert [r[0] for r in rows] == [1, 2]
    # 002 合规化在存量库上照常生效：TEXT 主键 → snapshot_id 业务键，行拷回零丢失
    snap = conn.execute(
        "SELECT snapshot_id, created_at FROM usage_snapshot WHERE account_id = 'acc1'"
    ).fetchone()
    assert snap == ("snap-1", "2026-01-01T00:00:00+00:00")
    conn.close()


def test_v1旧形状_显式拒绝不静默(tmp_path):
    """旧 v1 形状（id TEXT 主键 + provider 列）列集不符 → 退出并提示先升旧版本。"""
    db = tmp_path / "v1.db"
    conn = sqlite3.connect(str(db))
    conn.execute(
        "CREATE TABLE acc_account ("
        " id TEXT PRIMARY KEY, provider TEXT NOT NULL, account_name TEXT NOT NULL,"
        " sessions TEXT NOT NULL DEFAULT '[]', created_at TEXT NOT NULL)"
    )
    conn.commit()
    conn.close()

    with pytest.raises(SystemExit, match="列集与本版本 001 基线不符"):
        ensure_migrated(str(db))


def test_checksum篡改_显式报错(tmp_path):
    """已应用迁移的文件内容被改 → checksum 不符 = 红线 5。"""
    conn = sqlite3.connect(":memory:")
    migrate(conn, [(1, "001_a.sql", "CREATE TABLE t1 (id INTEGER PRIMARY KEY);")])
    with pytest.raises(MigrationError, match="checksum 不符"):
        migrate(conn, [(1, "001_a.sql", "CREATE TABLE t1 (id TEXT PRIMARY KEY);")])


def test_编号空洞_显式报错():
    conn = sqlite3.connect(":memory:")
    files = [
        (1, "001_a.sql", "CREATE TABLE t1 (id INTEGER PRIMARY KEY);"),
        (3, "003_c.sql", "CREATE TABLE t3 (id INTEGER PRIMARY KEY);"),
    ]
    with pytest.raises(MigrationError, match="编号空洞"):
        migrate(conn, files)


def test_已应用版本文件缺失_显式报错():
    """装了 001+002 后 002 文件被删（安装回退）→ 拒绝运行。"""
    conn = sqlite3.connect(":memory:")
    files = [
        (1, "001_a.sql", "CREATE TABLE t1 (id INTEGER PRIMARY KEY);"),
        (2, "002_b.sql", "CREATE TABLE t2 (id INTEGER PRIMARY KEY);"),
    ]
    migrate(conn, files)
    with pytest.raises(MigrationError, match="不存在"):
        migrate(conn, files[:1])


def test_追跑多版本_按序应用(tmp_path):
    conn = sqlite3.connect(":memory:")
    first = "CREATE TABLE t1 (id INTEGER PRIMARY KEY);"
    second = "ALTER TABLE t1 ADD COLUMN label TEXT NOT NULL DEFAULT '';"
    assert migrate(conn, [(1, "001_a.sql", first)]) == [1]
    assert migrate(conn, [(1, "001_a.sql", first), (2, "002_b.sql", second)]) == [2]
    cols = {r[1] for r in conn.execute("PRAGMA table_info(t1)")}
    assert cols == {"id", "label"}
    assert current_version(conn) == 2
