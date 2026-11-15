#!/usr/bin/env python3
"""全库 schema 生成视图导出（db/schema.sql 的唯一生成入口）。

做法：在临时目录用 6 个域适配器把全部 9 张表真实建一遍（与运行时同一 DDL 常量），
再 dump `sqlite_master`，按业务域分节写出 db/schema.sql。

权威单源仍是各域适配器的 DDL 常量（A4-01 §5「SQL 只存在于 butler_engine 适配器层」）；
本目录是**生成视图**，勿手改。重新生成：`uv run python scripts/dump_db_schema.py`。

纪律：出现未知表/索引（映射表之外）= 显式报错退出（红线 5），逼着更新本脚本的
分节映射，防止视图与库静默漂移。
"""
from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "db" / "schema.sql"

# 表/索引 → 业务域分节（顺序即输出顺序；新表必须先登记这里，否则脚本报错退出）
_SECTIONS: dict[str, str] = {
    # 账户域（accounts/sqlite.py）
    "accounts": "账户域 · accounts/sqlite.py",
    "idx_accounts_provider": "账户域 · accounts/sqlite.py",
    # 执行域（ledger/sqlite.py）
    "runs": "执行域 · ledger/sqlite.py",
    "idx_runs_idempotency": "执行域 · ledger/sqlite.py",
    # 用量域（usage/sqlite.py）
    "usage_snapshots": "用量域 · usage/sqlite.py",
    "usage_aggregates": "用量域 · usage/sqlite.py",
    "quota_ledger": "用量域 · usage/sqlite.py",
    "usage_samples": "用量域 · usage/sqlite.py",
    "idx_usage_snapshots_account": "用量域 · usage/sqlite.py",
    "idx_usage_aggregates_account": "用量域 · usage/sqlite.py",
    "idx_quota_ledger_account": "用量域 · usage/sqlite.py",
    "idx_usage_samples_account": "用量域 · usage/sqlite.py",
    # 健康域（health/state.py）
    "health_state": "健康域 · health/state.py",
    # 保管层（vault/layered.py；A4-01 §4 凭据元数据）
    "vault_items": "保管层 · vault/layered.py",
    "vault_history": "保管层 · vault/layered.py",
    # shared 内核（audit/sqlite.py；A4-01 §4 审计）
    "audit": "shared 内核 · audit/sqlite.py",
}

_ORDER = list(_SECTIONS)  # 输出顺序 = 映射登记顺序

_HEADER = """\
-- butler.db 全库 schema（生成视图 · {table_count} 张表）
--
-- 权威单源 = 各域适配器的 DDL 常量（A4-01 §5：SQL 只存在于 butler_engine 适配器层，
-- 表按域分置）；本文件是 scripts/dump_db_schema.py 的产物，**勿手改**。
-- 重新生成：uv run python scripts/dump_db_schema.py
-- 运行数据不入库仓库：butler.db 落平台标准用户数据根（BUTLER_DB 可覆盖，A4-01 §5）。
"""


def _build_temp_db(tmp: Path) -> None:
    """用与运行时相同的适配器把 8 张表建齐（避开 keychain：vault 只挂 memory 层）。"""
    from butler_engine.accounts.sqlite import SqliteAccountRepository
    from butler_engine.audit.sqlite import SqliteAuditLog
    from butler_engine.health.state import SqliteHealthStateStore
    from butler_engine.ledger.sqlite import SqliteRunLedger
    from butler_engine.usage.sqlite import SqliteUsageStore
    from butler_engine.vault.backends import MemoryVaultBackend
    from butler_engine.vault.layered import LayeredVault

    db = str(tmp / "butler.db")
    SqliteAccountRepository(db)
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
    known = set(_ORDER)
    unknown = sorted(name for _type, name, _sql in rows if name not in known)
    if unknown:
        raise SystemExit(
            f"发现映射表之外的库对象 {unknown}——先在 scripts/dump_db_schema.py "
            "_SECTIONS 登记分节，再重跑（红线 5：显式报错不静默）"
        )
    rows.sort(key=lambda r: _ORDER.index(r[1]))  # 按登记顺序输出
    return rows


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        _build_temp_db(tmp)
        rows = _dump(tmp)
    tables = sum(1 for t, _n, _s in rows if t == "table")
    indexes = sum(1 for t, _n, _s in rows if t != "table")
    parts: list[str] = [_HEADER.format(table_count=tables).rstrip("\n")]
    section: str | None = None
    for _type, name, sql in rows:
        sec = _SECTIONS[name]
        if sec != section:
            parts.append(f"\n-- ═══ {sec} ═══")
            section = sec
        parts.append(sql.strip() + ";")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(parts) + "\n", encoding="utf-8")
    print(f"已生成 {OUT.relative_to(ROOT)}：{tables} 张表 / {indexes} 个索引")
    return 0


if __name__ == "__main__":
    sys.exit(main())
