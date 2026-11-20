#!/usr/bin/env python3
"""全库 schema 基线快照导出（data/sql/ 按业务域分文件；ADR-036）。

做法：临时库跑迁移链（db/migrations/*.sql 编号迁移），dump `sqlite_master`，
按业务域分文件写出——每域一个 `<域>.sql`（accounts / execution / usage /
health / vault / audit）。

权威单源 = **迁移链**（ADR-036：`butler_engine/db/migrations/*.sql`）；
data/sql/ 是**迁移链基线快照 + DBA 审查入口**（多人协作 / 多服务共享库时
审查表结构从这里读），勿手改。重新生成：`uv run python scripts/dump_db_schema.py`；
CI/提交前校验快照未漂移：`uv run python scripts/dump_db_schema.py --check`。

纪律：出现未知表/索引（映射表之外）= 显式报错退出（红线 5），逼着更新本脚本的
分域映射，防止快照与迁移链静默漂移；映射登记了却没有任何库对象同样报错。
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "sql"

#: 迁移记账表（migrations/__init__.py 自举，ADR-036）：不入基线快照
_MIGRATION_TABLE = "db_migration"

# 库对象 → 业务域 key（新表/索引必须先登记所属域，否则脚本报错退出）
_SECTIONS: dict[str, str] = {
    # 账户域（accounts/sqlite.py；ADR-021 域前缀表名）
    "acc_account": "acc",
    "uq_acc_account_platform_code_key": "acc",
    "uq_acc_account_platform_source_key": "acc",
    "idx_acc_account_platform_code": "acc",
    # 平台域（platforms/sqlite.py；ADR-022 第六业务域）
    "plat_platform": "plat",
    "idx_plat_platform_active": "plat",
    # 执行域（ledger/sqlite.py）
    "exe_claim": "exe",
    "idx_exe_claim_idempotency": "exe",
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
    "acc": ("acc.sql", "账户域"),
    "plat": ("plat.sql", "平台域"),
    "exe": ("exe.sql", "执行域"),
    "usage": ("usage.sql", "用量域"),
    "health": ("health.sql", "健康域"),
    "vault": ("vault.sql", "保管层"),
    "audit": ("audit.sql", "shared 内核（审计）"),
}

_FILE_HEADER = """\
-- butler.db · {label}（基线快照 · {table_count} 张表{index_note}）
--
-- 权威单源 = 迁移链 butler_engine/db/migrations/*.sql（ADR-036）；本文件由
-- scripts/dump_db_schema.py 生成，**勿手改**——改表 = 新增迁移文件 + 重跑本脚本。
-- 校验快照未漂移：uv run python scripts/dump_db_schema.py --check
-- 运行库落项目内 data/database/butler.db（BUTLER_DB 可覆盖）。
"""


def _build_temp_db(tmp: Path) -> None:
    """临时库跑迁移链建全库（权威单源 = db/migrations/*.sql，ADR-036）。"""
    from butler_engine.db.conn import connect
    from butler_engine.db.migrations import migrate

    conn = connect(str(tmp / "butler.db"))
    migrate(conn)
    conn.close()


def _dump(tmp: Path) -> list[tuple[str, str, str]]:
    conn = sqlite3.connect(str(tmp / "butler.db"))
    rows = conn.execute(
        "SELECT type, name, sql FROM sqlite_master "
        "WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%' "
        f"AND name != '{_MIGRATION_TABLE}'"
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


def _render(grouped: dict[str, list[tuple[str, str, str]]]) -> dict[str, str]:
    """渲染 {文件名: 全文}（含域头注释）。"""
    out: dict[str, str] = {}
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
        out[filename] = "\n".join(parts) + "\n"
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="全库 schema 基线快照导出/校验")
    parser.add_argument(
        "--check", action="store_true",
        help="只校验：重演迁移链与 data/sql/*.sql 比对，不一致退出 1",
    )
    args = parser.parse_args()

    # ignore_cleanup_errors：Windows 下 sqlite 连接句柄释放有时序延迟，
    # 临时目录清理可能 WinError 32——残留目录交给系统清理，不影响产物正确性
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        tmp = Path(td)
        _build_temp_db(tmp)
        rows = _dump(tmp)
    grouped = _grouped(rows)
    rendered = _render(grouped)

    if args.check:
        drifted = [
            filename for filename, content in rendered.items()
            if (OUT_DIR / filename).read_text(encoding="utf-8") != content
        ]
        if drifted:
            print(f"data/sql 快照与迁移链漂移：{drifted}——"
                  "跑 uv run python scripts/dump_db_schema.py 重新生成并提交", file=sys.stderr)
            return 1
        print(f"校验通过：data/sql/ {len(rendered)} 个文件与迁移链逐字一致")
        return 0

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    for filename, content in rendered.items():
        out = OUT_DIR / filename
        out.write_text(content, encoding="utf-8")
        label = _DOMAIN_FILES[next(k for k, v in _DOMAIN_FILES.items() if v[0] == filename)][1]
        tables = content.count("CREATE TABLE")
        indexes = content.count("CREATE UNIQUE INDEX") + content.count("CREATE INDEX")
        written.append(f"{out.relative_to(ROOT)}（{label}：{tables} 表 / {indexes} 索引）")
    print("已生成 " + "、".join(written))
    return 0


if __name__ == "__main__":
    sys.exit(main())
