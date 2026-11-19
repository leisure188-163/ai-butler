"""旧库（单表口径）→ 分域 schema 的一次性数据搬迁。

背景：2026-11-17/18 把 `accounts` / `runs` / `usage_*` 等单数聚合表重构成按域
前缀的 `acct_account` / `exe_claim` / `usage_snapshot` …（A4-01 §5 表按域分置）。
老机器上的库仍是旧表名，直接启动只会看到空账户/空平台——本脚本把数据搬进新库。

用法（默认只预览，不写盘）：

    uv run python scripts/migrate_db_schema_v2.py --source data/database/butler.db
    uv run python scripts/migrate_db_schema_v2.py --source data/database/butler.db --write

`--write` 会：备份旧库 → 生成 `butler.db.migrated`（建新 schema + 搬数据）→
提示把迁移库替换为正式库。不做自动替换，避免脚本误覆盖运行中的库。
"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

SQL_DIR = Path(__file__).resolve().parent.parent / "data" / "sql"

# 旧表 → 新表；`columns` 是显式列清单，`select` 负责字段改名与补默认值。
MAPPINGS: list[tuple[str, str, str, str]] = [
    (
        "accounts",
        "acc_account",
        "account_id, platform_code, account_code, account_name, base_url, device_ref,"
        " sessions, entitlement_json, is_active, created_at, updated_at, deleted_at",
        "SELECT id, provider,"
        " CASE WHEN instr(id, ':') > 0 THEN substr(id, instr(id, ':') + 1) ELSE 'main' END,"
        " COALESCE(display_name, provider), NULL, NULL, COALESCE(sessions, '[]'), NULL,"
        " 1, created_at, created_at, NULL FROM legacy.accounts",
    ),
    (
        "runs",
        "exe_claim",
        "run_id, kind, target, params_json, account_id, idempotency_key, started_at,"
        " budget_seconds, finished_at, status, result_json, created_at, updated_at",
        "SELECT id, kind, target, COALESCE(params_json,'{}'), COALESCE(account_id,''),"
        " COALESCE(idempotency_key,''), COALESCE(started_at, strftime('%Y-%m-%dT%H:%M:%f+00:00','now')),"
        " COALESCE(budget_seconds, 0), finished_at, status, result_json,"
        " COALESCE(started_at, strftime('%Y-%m-%dT%H:%M:%f+00:00','now')),"
        " COALESCE(finished_at, started_at, strftime('%Y-%m-%dT%H:%M:%f+00:00','now')) FROM legacy.runs",
    ),
    (
        "audit",
        "audit_log",
        "seq, ts, actor, account_id, credential_ref, action, outcome",
        "SELECT seq, ts, actor, account_id, credential_ref, action, outcome FROM legacy.audit",
    ),
    (
        "vault_items",
        "vault_item",
        "account_id, kind, backend, expires_at, created_at, rotated_at, revoked_at, revoked_reason",
        "SELECT account_id, kind, backend, expires_at, created_at, rotated_at, revoked_at,"
        " COALESCE(revoked_reason, '') FROM legacy.vault_items",
    ),
    (
        "vault_history",
        "vault_history",
        "account_id, kind, archived_ref, rotated_at",
        "SELECT account_id, kind, archived_ref, rotated_at FROM legacy.vault_history",
    ),
    (
        "quota_ledger",
        "usage_quota_ledger",
        "account_id, record_id, target, occurred_at, amount, unit, kind, raw_json",
        "SELECT account_id, record_id, target, occurred_at, COALESCE(amount, 0),"
        " COALESCE(unit, 'POINT'), kind, raw_json FROM legacy.quota_ledger",
    ),
    (
        "usage_snapshots",
        "usage_snapshot",
        "id, account_id, target, collected_at, packages_json",
        "SELECT id, account_id, target, collected_at, packages_json FROM legacy.usage_snapshots",
    ),
    (
        "usage_aggregates",
        "usage_aggregate",
        "id, account_id, target, collected_at, summary_json",
        "SELECT id, account_id, target, collected_at, summary_json FROM legacy.usage_aggregates",
    ),
    (
        "usage_samples",
        "usage_sample",
        "id, account_id, tokens_in, tokens_out, model, ts, source, duration_ms",
        "SELECT id, account_id, tokens_in, tokens_out, model, ts, source, duration_ms"
        " FROM legacy.usage_samples",
    ),
    (
        "health_state",
        "health_state",
        "key, value, updated_at",
        "SELECT key, value, updated_at FROM legacy.health_state",
    ),
]

# 旧库已有的表名（用于判断是否真的需要迁移）
LEGACY_TABLES = {"accounts", "runs", "quota_ledger", "usage_snapshots", "vault_items"}


@dataclass
class Step:
    legacy: str
    target: str
    rows: int


def table_names(conn: sqlite3.Connection) -> set[str]:
    return {r[0] for r in conn.execute(
        "select name from sqlite_master where type='table'"
    )}


def count(conn: sqlite3.Connection, table: str) -> int:
    try:
        return conn.execute(f"select count(*) from {table}").fetchone()[0]
    except sqlite3.Error:
        return 0


def build_schema(target: Path) -> None:
    """按 data/sql/*.sql 建立新 schema（DDL 单源 = 各域适配器，此处只回放）。"""
    sql_files = sorted(SQL_DIR.glob("*.sql"))
    if not sql_files:
        raise SystemExit(f"未找到 schema 文件：{SQL_DIR}")
    conn = sqlite3.connect(target)
    try:
        for sql_file in sql_files:
            conn.executescript(sql_file.read_text(encoding="utf-8"))
        conn.commit()
    finally:
        conn.close()


def migrate(source: Path, target: Path) -> list[Step]:
    old = sqlite3.connect(source)
    old.row_factory = sqlite3.Row
    new = sqlite3.connect(target)
    steps: list[Step] = []
    try:
        new.execute("ATTACH DATABASE ? AS legacy", (str(source),))
        for legacy_table, target_table, columns, select_sql in MAPPINGS:
            if legacy_table not in table_names(old):
                steps.append(Step(legacy_table, target_table, -1))
                continue
            before = count(new, target_table)
            new.execute(
                f"INSERT OR IGNORE INTO {target_table} ({columns}) {select_sql}"
            )
            after = count(new, target_table)
            steps.append(Step(legacy_table, target_table, after - before))
        new.commit()
    finally:
        new.close()
        old.close()
    return steps


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="旧库 → 分域 schema 数据搬迁")
    parser.add_argument("--source", required=True, help="旧库路径")
    parser.add_argument("--target", help="迁移后新库路径（默认 <source>.migrated）")
    parser.add_argument("--write", action="store_true", help="真正写盘（默认只预览）")
    args = parser.parse_args(argv)

    source = Path(args.source).resolve()
    if not source.exists():
        raise SystemExit(f"旧库不存在：{source}")
    target = Path(args.target).resolve() if args.target else source.with_suffix(
        source.suffix + ".migrated"
    )

    conn = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    try:
        tables = table_names(conn)
        if not (tables & LEGACY_TABLES):
            print(f"该库已是新 schema（无旧表）：{source}")
            print("已有表：" + ", ".join(sorted(tables)))
            return 0
    finally:
        conn.close()

    if not args.write:
        print(f"[预览] 源库：{source}")
        print(f"[预览] 目标：{target}")
        for legacy_table, target_table, _, select_sql in MAPPINGS:
            print(f"  {legacy_table:18} → {target_table}")
        print("加 --write 真正执行。")
        return 0

    if target.exists():
        raise SystemExit(f"目标已存在，先自行处理：{target}")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = source.with_name(f"{source.name}.bak-{stamp}")
    shutil.copyfile(source, backup)
    print(f"已备份旧库 → {backup.name}")

    build_schema(target)
    steps = migrate(source, target)
    print(f"已生成迁移库 → {target}")
    for step in steps:
        if step.rows < 0:
            print(f"  {step.legacy:18} → {step.target:20} 旧表不存在，跳过")
        else:
            print(f"  {step.legacy:18} → {step.target:20} 搬入 {step.rows} 行")
    print(
        "\n下一步：确认服务已停，把迁移库替换为正式库（原库已备份）：\n"
        f"  Move-Item -Force {target} {source}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
