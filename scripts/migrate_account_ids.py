"""一次性账户主键重置（ADR-034，2026-11-20 用户裁决 B）。

把存量 ``{platform}:{account_code}`` 主键重发为不透明 ``acc_<8hex>``，并同步：
- ``acc_account.account_id`` + 新增 ``source_key`` 列；
- ``vault_item`` / ``vault_history`` 的账户引用与 Windows 凭据管理器条目
  （新引用先复制，旧引用保留不删，可回滚）；
- ``exe_claim`` / ``usage_*`` / ``audit_log`` / ``_acc_account_old_*`` 的账户列；
- ``health_state`` 的 ``acct:/cred:`` 键；
- ``gateway-routes.json`` 里显式 account_id 字段（当前为空）。

默认 dry-run；``--apply`` 才写库。写库前必须已有备份目录。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

from butler_core.accounts.domain import vault_ref
from butler_engine.accounts.sqlite import SqliteAccountRepository
from butler_engine.vault.credman_windows import WindowsCredmanBackend

#: 参与迁移的账户表（存在才更新）。
_ACCOUNT_TABLES = (
    "exe_claim",
    "usage_snapshot",
    "usage_aggregate",
    "usage_quota_ledger",
    "usage_sample",
    "vault_item",
    "vault_history",
    "audit_log",
    "_acc_account_old_20261120",
)


def _new_id(old_id: str, taken: set[str]) -> str:
    n = 1
    while True:
        digest = hashlib.sha256(f"butler-account-reset-v1|{n}|{old_id}".encode()).hexdigest()[:8]
        candidate = f"acc_{digest}"
        if candidate not in taken:
            taken.add(candidate)
            return candidate
        n += 1


def _source_keys(rows: list[dict], doubao_registry: dict | None) -> dict[str, str]:
    """给每条存量账户一个稳定身份键。

    豆包/AgentRouter 有真实外部 id；其余连接器当前未回填，用 ``legacy:<code>``
    占位并在首次真实 dock 时由 RegisterAccount 吸收。
    """
    out: dict[str, str] = {}
    for row in rows:
        platform = row["platform_code"]
        code = row["account_code"]
        name = row["account_name"] or ""
        key = ""
        if platform == "doubao_cn" and doubao_registry:
            if doubao_registry.get("main_nickname") == code:
                key = doubao_registry.get("main_sec_uid", "")
            else:
                for item in doubao_registry.get("others") or []:
                    if item.get("account_code") == code or item.get("nickname") == code:
                        key = item.get("sec_uid", "")
                        break
        elif platform == "agentrouter":
            marker = "github_"
            if marker in name:
                tail = name.split(marker, 1)[1].split("）", 1)[0].strip()
                if tail:
                    key = f"github_{tail}"
        if not key:
            key = f"legacy:{code}"
        out[row["account_id"]] = key
    return out


def _nickname(row: dict) -> str:
    name = (row["account_name"] or "").strip()
    if "·" in name:
        return name.rsplit("·", 1)[1].strip()
    return ""


def _merge_identity(raw: str | None, nickname: str) -> str | None:
    data: dict = {}
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                data = parsed
        except ValueError:
            data = {}
    data.pop("source_key", None)
    if nickname:
        data.setdefault("nickname", nickname)
    return json.dumps(data, ensure_ascii=False) if data else None


def _load_rows(con: sqlite3.Connection) -> list[dict]:
    con.row_factory = sqlite3.Row
    return [dict(r) for r in con.execute(
        "SELECT id, account_id, platform_code, account_code, account_name, identity_json "
        "FROM acc_account ORDER BY id"
    )]


def _copy_vault(con: sqlite3.Connection, mapping: dict[str, str], backend: WindowsCredmanBackend) -> None:
    for row in con.execute("SELECT account_id, kind, slot, backend FROM vault_item").fetchall():
        old = row["account_id"]
        if old not in mapping:
            continue
        if row["backend"] != "credman":
            raise SystemExit(f"保险库后端 {row['backend']!r} 不在本迁移脚本支持范围：{old}")
        old_ref = vault_ref(old, row["kind"], row["slot"] or "default")
        new_ref = vault_ref(mapping[old], row["kind"], row["slot"] or "default")
        try:
            secret = backend.get(old_ref)
        except Exception as exc:  # noqa: BLE001 - 迁移必须显式中止
            raise SystemExit(f"读取旧凭据失败 {old_ref!r}: {exc}") from exc
        backend.put(new_ref, secret)
        print(f"vault copy {old_ref} -> {new_ref}")

    for row in con.execute("SELECT seq, account_id, archived_ref FROM vault_history").fetchall():
        old = row["account_id"]
        if old not in mapping:
            continue
        old_ref = row["archived_ref"]
        new_ref = mapping[old] + old_ref[len(old):]
        try:
            secret = backend.get(old_ref)
        except Exception as exc:  # noqa: BLE001
            raise SystemExit(f"读取历史凭据失败 {old_ref!r}: {exc}") from exc
        backend.put(new_ref, secret)
        con.execute(
            "UPDATE vault_history SET account_id = ?, archived_ref = ? WHERE seq = ?",
            (mapping[old], new_ref, row["seq"]),
        )
        print(f"vault history {old_ref} -> {new_ref}")


def _update_health(con: sqlite3.Connection, mapping: dict[str, str], new_ids: set[str]) -> None:
    rows = con.execute("SELECT key FROM health_state").fetchall()
    for row in rows:
        key = row[0]
        new_key = key
        if key.startswith("acct:"):
            suffix = key[len("acct:"):]
            if suffix in mapping:
                new_key = f"acct:{mapping[suffix]}"
            elif suffix not in new_ids:
                con.execute("DELETE FROM health_state WHERE key = ?", (key,))
                print(f"health drop stale {key}")
                continue
        elif key.startswith("cred:"):
            rest = key[len("cred:"):]
            for old, new in mapping.items():
                if rest.startswith(old + ":"):
                    new_key = f"cred:{new}{rest[len(old):]}"
                    break
            else:
                account = rest.rsplit(":", 1)[0]
                if account not in new_ids:
                    con.execute("DELETE FROM health_state WHERE key = ?", (key,))
                    print(f"health drop stale {key}")
                    continue
        if new_key != key:
            con.execute("UPDATE health_state SET key = ? WHERE key = ?", (new_key, key))
            print(f"health {key} -> {new_key}")


def _update_json(path: Path, mapping: dict[str, str]) -> None:
    if not path.is_file():
        return
    data = json.loads(path.read_text(encoding="utf-8"))
    routes = data.get("routes") if isinstance(data, dict) else None
    if not isinstance(routes, list):
        return
    changed = False
    for route in routes:
        if isinstance(route, dict) and route.get("account_id") in mapping:
            route["account_id"] = mapping[route["account_id"]]
            changed = True
    if changed:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"routes updated {path}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="data/database/butler.db")
    parser.add_argument("--doubao-registry", default="data/doubao_identity.json")
    parser.add_argument("--routes", default="data/database/gateway-routes.json")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--backup-dir", default="")
    args = parser.parse_args()

    db = Path(args.db).resolve()
    if not db.is_file():
        raise SystemExit(f"数据库不存在：{db}")
    if args.apply and not args.backup_dir:
        raise SystemExit("--apply 必须同时给 --backup-dir（先备份再迁移）")

    if args.apply:
        backup = Path(args.backup_dir)
        backup.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%H%M%S")
        shutil.copy2(db, backup / f"butler-pre-account-reset-{stamp}.db")
        print(f"backup {backup / f'butler-pre-account-reset-{stamp}.db'}")

    # 触发 engine 幂等建列/重排（source_key + 唯一索引）。
    SqliteAccountRepository(db)

    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    rows = _load_rows(con)
    taken = {r["account_id"] for r in rows}
    mapping = {r["account_id"]: _new_id(r["account_id"], taken) for r in rows}

    registry = None
    path = Path(args.doubao_registry)
    if path.is_file():
        registry = json.loads(path.read_text(encoding="utf-8"))
    source_keys = _source_keys(rows, registry)

    print("\n账户映射：")
    for row in rows:
        print(
            f"  {row['account_id']}  ->  {mapping[row['account_id']]}"
            f"  source_key={source_keys[row['account_id']]!r}"
        )
    if not args.apply:
        print("\ndry-run：未写库。加 --apply 执行。")
        return 0

    backend = WindowsCredmanBackend()
    _copy_vault(con, mapping, backend)

    with con:
        for row in rows:
            old = row["account_id"]
            new = mapping[old]
            con.execute(
                "UPDATE acc_account SET account_id = ?, source_key = ?, identity_json = ? "
                "WHERE id = ?",
                (new, source_keys[old], _merge_identity(row["identity_json"], _nickname(row)), row["id"]),
            )
        for table in _ACCOUNT_TABLES:
            if not con.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone():
                continue
            cols = {r[1] for r in con.execute(f'PRAGMA table_info("{table}")')}
            if "account_id" not in cols:
                continue
            for old, new in mapping.items():
                n = con.execute(
                    f'UPDATE "{table}" SET account_id = ? WHERE account_id = ?', (new, old)
                ).rowcount
                if n:
                    print(f"{table}: {old} -> {new} ({n} rows)")
        _update_health(con, mapping, set(mapping.values()))

    _update_json(Path(args.routes), mapping)

    out_dir = Path(args.backup_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "account-id-map.json").write_text(
        json.dumps(
            {
                "mapping": mapping,
                "source_keys": source_keys,
                "accounts": [
                    {
                        "old_id": r["account_id"],
                        "new_id": mapping[r["account_id"]],
                        "platform_code": r["platform_code"],
                        "account_code": r["account_code"],
                        "account_name": r["account_name"],
                    }
                    for r in rows
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\n完成，映射写入 {out_dir / 'account-id-map.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
