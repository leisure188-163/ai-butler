#!/usr/bin/env python3
"""全库 schema 生成视图导出（data/sql/ 按业务域分文件的唯一生成入口）。

做法：在临时目录用 6 个域适配器把全部表真实建一遍（与运行时同一 DDL 常量），
再 dump `sqlite_master`，按业务域分文件写出——每域一个 `<域>.sql`
（accounts / execution / usage / health / vault / audit）。

权威单源仍是各域适配器的 DDL 常量（A4-01 §5「SQL 只存在于 butler_engine 适配器层」）；
data/sql/ 是**生成视图**，勿手改。重新生成：`uv run python scripts/dump_db_schema.py`。

纪律：出现未知表/索引（映射表之外）= 显式报错退出（红线 5），逼着更新本脚本的
分域映射，防止视图与库静默漂移；映射登记了却没有任何库对象同样报错。
"""
from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "sql"

# 库对象 → 业务域 key（新表/索引必须先登记所属域，否则脚本报错退出）
_SECTIONS: dict[str, str] = {
    # 账户域（accounts/sqlite.py + accounts/platform_sqlite.py；ADR-021 域前缀表名）
    "acc_account": "accounts",
    "acc_platform": "accounts",
    "uq_acc_account_platform_code_key": "accounts",
    "idx_acc_account_platform_code": "accounts",
    "idx_acc_platform_active": "accounts",
    # 执行域（ledger/sqlite.py）
    "exe_run": "execution",
    "idx_exe_run_idempotency": "execution",
    # 用量域（usage/sqlite.py）
    "usage_snapshot": "usage",
    "usage_aggregate": "usage",
    "usage_quota_ledger": "usage",
    "usage_sample": "usage",
    "idx_usage_snapshot_account": "usage",
    "idx_usage_aggregate_account": "usage",
    "idx_usage_quota_ledger_account": "usage",
    "idx_usage_sample_account": "usage",
    # 健康域（health/state.py）
    "health_state": "health",
    # 保管层（vault/layered.py；A4-01 §4 凭据元数据）
    "vault_item": "vault",
    "vault_history": "vault",
    # shared 内核（audit/sqlite.py；A4-01 §4 审计）
    "audit_log": "audit",
}

# 域 key →（生成文件名，域标签）；登记顺序即各文件内输出顺序
_DOMAIN_FILES: dict[str, tuple[str, str]] = {
    "accounts": ("accounts.sql", "账户域 · accounts/sqlite.py + accounts/platform_sqlite.py"),
    "execution": ("execution.sql", "执行域 · ledger/sqlite.py"),
    "usage": ("usage.sql", "用量域 · usage/sqlite.py"),
    "health": ("health.sql", "健康域 · health/state.py"),
    "vault": ("vault.sql", "保管层 · vault/layered.py"),
    "audit": ("audit.sql", "shared 内核 · audit/sqlite.py"),
}

_FILE_HEADER = """\
-- butler.db · {label}（生成视图 · {table_count} 张表{index_note}）
--
-- 权威单源 = 域适配器 DDL 常量（A4-01 §5：SQL 只存在于 butler_engine 适配器层，
-- 表按域分置）；本文件由 scripts/dump_db_schema.py 生成，**勿手改**。
-- 重新生成：uv run python scripts/dump_db_schema.py
-- 运行库落项目内 data/database/butler.db（BUTLER_DB 可覆盖）。
"""


def _build_temp_db(tmp: Path) -> None:
    """用与运行时相同的适配器把全部表建齐（避开 keychain：vault 只挂 memory 层）。"""
    from butler_engine.accounts.sqlite import SqliteAccountRepository
    from butler_engine.accounts.platform_sqlite import SqlitePlatformRepository
    from butler_engine.audit.sqlite import SqliteAuditLog
    from butler_engine.health.state import SqliteHealthStateStore
    from butler_engine.ledger.sqlite import SqliteRunLedger
    from butler_engine.usage.sqlite import SqliteUsageStore
    from butler_engine.vault.backends import MemoryVaultBackend
    from butler_engine.vault.layered import LayeredVault

    db = str(tmp / "butler.db")
    SqliteAccountRepository(db)
    SqlitePlatformRepository(db)
    SqliteRunLedger(db)
    SqliteUsageStore(db)
    SqliteHealthStateStore(db)
    audit = SqliteAuditLog(db)
    LayeredVault(db, {"memory": MemoryVaultBackend()}, default_backend="memory", audit=audit)


def _dump(tmp: Path) -> list[tuple[str, str, str]]:
    conn = sqlite3.connect(str(tmp / "butler.db"))
    rows = conn.execute(
        "SELECT type, name, sql FROM sqlite_master "
        "WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    conn.close()
    known = set(_SECTIONS)
    unknown = sorted(name for _type, name, _sql in rows if name not in known)
    if unknown:
        raise SystemExit(
            f"发现映射表之外的库对象 {unknown}——先在 scripts/dump_db_schema.py "
            "_SECTIONS 登记所属域，再重跑（红线 5：显式报错不静默）"
        )
    return rows


def _grouped(rows: list[tuple[str, str, str]]) -> dict[str, list[tuple[str, str, str]]]:
    """按域分组；组内顺序 = _DOMAIN_FILES 各域对象在 _SECTIONS 的登记顺序。"""
    grouped: dict[str, list[tuple[str, str, str]]] = {
        domain: [] for domain in _DOMAIN_FILES
    }
    for row in rows:
        grouped[_SECTIONS[row[1]]].append(row)
    empty = sorted(domain for domain, items in grouped.items() if not items)
    if empty:
        raise SystemExit(
            f"域 {empty} 在 _SECTIONS 里没有登记任何库对象——映射与 _DOMAIN_FILES "
            "不一致，先核对再重跑（红线 5：显式报错不静默）"
        )
    return grouped


def main() -> int:
    # ignore_cleanup_errors：Windows 下适配器 sqlite 连接句柄释放有时序延迟，
    # 临时目录清理可能 WinError 32——残留目录交给系统清理，不影响产物正确性
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        tmp = Path(td)
        _build_temp_db(tmp)
        rows = _dump(tmp)
    grouped = _grouped(rows)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    for domain, (filename, label) in _DOMAIN_FILES.items():
        items = grouped[domain]
        tables = sum(1 for t, _n, _s in items if t == "table")
        indexes = sum(1 for t, _n, _s in items if t != "table")
        header = _FILE_HEADER.format(
            label=label,
            table_count=tables,
            index_note=f" / {indexes} 个索引" if indexes else "",
        ).rstrip("\n")
        parts: list[str] = [header]
        for _type, _name, sql in items:
            parts.append(sql.strip() + ";")
        out = OUT_DIR / filename
        out.write_text("\n".join(parts) + "\n", encoding="utf-8")
        written.append(f"{out.relative_to(ROOT)}（{tables} 表 / {indexes} 索引）")
    print("已生成 " + "、".join(written))
    return 0


if __name__ == "__main__":
    sys.exit(main())
