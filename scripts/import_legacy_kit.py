#!/usr/bin/env python3
"""旧 auto-signin-kit 历史数据一次性导入 butler.db（runs 台账 + 账户）。

来源 = Windows 侧旧 kit 的 data/database/auto-signin-kit.db（连同 -wal/-shm
一起拷到本机）。源库全程**只拷不改不删**：先复制到临时工作区再读（规避
只读库 + 未 checkpoint WAL 的打开限制）。

四条纪律（对齐红线）：
- 备份：--commit 前先用 sqlite backup API 落 ``<target>.backup-legacy-<ts>``
- 幂等：行主键 ``legacy-kit:<tag>:<旧id>`` + INSERT OR IGNORE，重跑零动作
- 验证：导入行数逐表核对（源行数 = 插入数 + 跳过数），不符即报错退出
- 显式报错：未知域名 / 未知操作词 → 中止并列出分布（红线 5，不发明映射）

语义映射（旧 RESULT_LABELS 与新 Status 同源血统，逐词核对；知识资产见 A0-01）：
- 域：workbuddy→workbuddy_cn · qoder→qoder_cn · trae→trae_cn · doubao→doubao_cn
- 动作：operation auto/claim/backfill → provision.run（签到领取；backfill 是
  同动作的补录形态，形态差异保存在 params_json.legacy_kit.source/operation）
- 结果：CLAIMED→CLAIMED · ALREADY→ALREADY · FAILED→FAILED ·
  NO_AUTH→EXPIRED（旧义「登录过期」= EXPIRED「登录态过期」；字面不同义，
  因此旧 NO_AUTH 行**不会**参与健康扫描的 NO_AUTH 连败判定）·
  NETWORK→FAILED（网络异常是失败子类，原文在档案里）；
  ACTIVE/NO_ACTIVITY/OK/PARTIAL/UNKNOWN → status NULL（无诚实对应词，
  不发明——记录页显示 …，report/response 原文全量保存在档案）
- 账户：ask_accounts(domain,name) → ``{provider}:{slug}``（name=default → :main）；
  runs 的 account_name='default' → 该域**唯一**登记户（多户歧义显式报错），
  无登记户 → :main；登记户匹配不上 → 按名建隐式账户并在报告标注

写库安全边界（防炸 server 读路径 ledger._load_run）：
- kind 只写合法 ActionKind；status 列只写 Status 字面量或 NULL
- result_json 只写原生形状 {status,evidence,repair_hint} 或 NULL
- 旧行 verbatim 档案（request/response/report/result 原词/needs_attention 等）
  全量放 params_json.legacy_kit——该列 json.loads 不校验、UI 不消费、可追溯

用法：
- 干跑（默认）：uv run python scripts/import_legacy_kit.py --source <旧库.db>
- 真迁：uv run python scripts/import_legacy_kit.py --source <旧库.db> --commit
  （先停 butler server；目标 -wal 非空时拒绝，--allow-live-writer 显式覆盖）
- 时间换算：旧库为无时区本地时间，默认按 +08:00 折算 UTC（--tz-offset 调整）
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ── 映射表（唯一出处；改这里 = 改裁决，需随批更新本 docstring）────────────
DOMAIN_TO_PROVIDER = {
    "workbuddy": "workbuddy_cn",
    "qoder": "qoder_cn",
    "trae": "trae_cn",
    "doubao": "doubao_cn",
}
OPERATION_TO_KIND = {
    "auto": "provision.run",
    "claim": "provision.run",
    "backfill": "provision.run",
}
RESULT_TO_STATUS = {
    "CLAIMED": "CLAIMED",
    "ALREADY": "ALREADY",
    "FAILED": "FAILED",
    "NO_AUTH": "EXPIRED",
    "NETWORK": "FAILED",
}
RESULT_NULL = {"ACTIVE", "NO_ACTIVITY", "OK", "PARTIAL", "UNKNOWN"}  # → status NULL

_RUN_COLUMNS = (
    "id, domain, account_name, executed_at, operation, source, result, "
    "needs_attention, report, request, response, detail, created_at, updated_at"
)
_ACCT_COLUMNS = "id, domain, name, created_at"


def _slug(name: str) -> str:
    """账户 id 尾段：小写、非 [a-z0-9] 折叠为 '-'（与 ADR-011 目录 slug 同风格）。"""
    return re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")


def _to_utc_iso(raw: str | None, offset_hours: float) -> str | None:
    """旧库无时区本地时间 → UTC ISO；已是带时区 ISO 的原样折算。"""
    if not raw or not raw.strip():
        return None
    text = raw.strip()
    if "T" in text or text.endswith("Z"):
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = datetime.strptime(text, "%Y-%m-%d %H:%M:%S").replace(
            tzinfo=timezone(timedelta(hours=offset_hours))
        )
    return dt.astimezone(timezone.utc).isoformat()


def _target_db(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit).expanduser()
    env = os.environ.get("BUTLER_DB")
    if env:
        return Path(env).expanduser()
    from butler_engine.bridge import default_db_path

    return default_db_path()


def _stage_source(src: Path, work: Path) -> Path:
    """把源库三件套拷进临时工作区（只拷不改），返回工作副本路径。"""
    staged = work / "legacy-kit.db"
    for suffix in ("", "-wal", "-shm"):
        s = Path(str(src) + suffix)
        if s.exists():
            shutil.copy2(s, Path(str(staged) + suffix))
    return staged


def _verify_schema(conn: sqlite3.Connection) -> None:
    need = {
        "ask_signin_runs": {"id", "domain", "account_name", "executed_at",
                            "operation", "source", "result", "needs_attention",
                            "report", "request", "response", "detail", "created_at"},
        "ask_accounts": {"id", "domain", "name", "created_at"},
    }
    for table, cols in need.items():
        have = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        if not have:
            raise SystemExit(f"源库缺表 {table}——确认拷的是旧 kit 主库文件")
        missing = cols - have
        if missing:
            raise SystemExit(f"源库 {table} 缺列 {sorted(missing)}——旧 kit 版本差异，先人工核对再扩本脚本")


def _load_rows(conn: sqlite3.Connection) -> tuple[list[dict], list[dict]]:
    runs = [
        dict(zip(_RUN_COLUMNS.split(", "), row))
        for row in conn.execute(f"SELECT {_RUN_COLUMNS} FROM ask_signin_runs ORDER BY id")
    ]
    accounts = [
        dict(zip(_ACCT_COLUMNS.split(", "), row))
        for row in conn.execute(f"SELECT {_ACCT_COLUMNS} FROM ask_accounts ORDER BY id")
    ]
    return runs, accounts


def _plan(runs: list[dict], accounts: list[dict], tz: float, tag: str) -> dict:
    """把映射全部算好；任何显式报错在此抛出。返回计划 + 统计。"""
    warnings: list[str] = []
    accounts_by_domain: dict[str, list[dict]] = {}
    acct_plan: dict[tuple[str, str], str] = {}  # (domain, name) → butler 账户 id
    new_accounts: list[dict] = []  # {id, provider, account_name, created_at}

    for a in accounts:
        domain = (a["domain"] or "").strip()
        provider = DOMAIN_TO_PROVIDER.get(domain)
        if provider is None:
            raise SystemExit(f"未知域名 {domain!r}（账户 id={a['id']}）——把映射补进 DOMAIN_TO_PROVIDER 再跑")
        name = (a["name"] or "").strip()
        acct_id = f"{provider}:main" if name.lower() == "default" else f"{provider}:{_slug(name)}"
        if name.lower() != "default" and not _slug(name):
            raise SystemExit(f"账户名 {name!r} 无法折成 id 尾段（domain={domain}）——人工定 id 后再跑")
        accounts_by_domain.setdefault(domain, []).append({**a, "acct_id": acct_id})
        acct_plan[(domain, name)] = acct_id
        new_accounts.append({
            "id": acct_id,
            "provider": provider,
            "account_name": name,
            "created_at": _to_utc_iso(a["created_at"], tz),
        })

    run_plan: list[dict] = []
    op_dist: dict[str, int] = {}
    for r in runs:
        domain = (r["domain"] or "").strip()
        provider = DOMAIN_TO_PROVIDER.get(domain)
        if provider is None:
            raise SystemExit(f"未知域名 {domain!r}（旧 run id={r['id']}）——补 DOMAIN_TO_PROVIDER 再跑")
        op = (r["operation"] or "").strip()
        kind = OPERATION_TO_KIND.get(op)
        if kind is None:
            op_dist[op] = op_dist.get(op, 0) + 1
            continue  # 收集完一起报
        result_raw = (r["result"] or "").strip().upper()
        status = RESULT_TO_STATUS.get(result_raw)
        if status is None and result_raw not in RESULT_NULL:
            warnings.append(f"run id={r['id']} 结果词 {result_raw!r} 不在旧词表——按 NULL 处理（档案保全）")
        acct_name = (r["account_name"] or "").strip()
        if not acct_name or acct_name.lower() == "default":
            rows = accounts_by_domain.get(domain, [])
            if len(rows) > 1:
                raise SystemExit(
                    f"run id={r['id']} account_name='default' 但 {domain} 有 {len(rows)} 个登记户 "
                    f"{[x['name'] for x in rows]}——歧义，人工裁决后重跑"
                )
            acct_id = rows[0]["acct_id"] if rows else f"{provider}:main"
        elif (domain, acct_name) in acct_plan:
            acct_id = acct_plan[(domain, acct_name)]
        else:
            acct_id = f"{provider}:{_slug(acct_name)}"
            if not _slug(acct_name):
                raise SystemExit(f"run id={r['id']} 账户名 {acct_name!r} 无法折 id——人工裁决")
            new_accounts.append({"id": acct_id, "provider": provider,
                                 "account_name": acct_name, "created_at": None})
            warnings.append(f"run id={r['id']} 账户 {acct_name!r} 无登记户 → 隐式新建 {acct_id}")
        run_plan.append({
            "id": f"legacy-kit:{tag}:{r['id']}",
            "kind": kind,
            "target": provider,
            "account_id": acct_id,
            "idempotency_key": f"legacy-kit:{tag}:{r['id']}",
            "started_at": _to_utc_iso(r["executed_at"], tz),
            "status": status,
            "result_raw": result_raw,
            "report": r["report"],
            "operation": op,
            "source_row": r,
        })

    if op_dist:
        raise SystemExit(
            f"未知操作词分布 {op_dist}——逐词裁决补进 OPERATION_TO_KIND（或确认跳过）再跑"
        )
    # 隐式账户按 id 去重（同一账户多行 run 只建一次）
    seen: set[str] = set()
    dedup_accounts = [a for a in new_accounts if not (a["id"] in seen or seen.add(a["id"]))]
    return {"run_plan": run_plan, "new_accounts": dedup_accounts,
            "warnings": warnings, "op_dist": op_dist}


def _bundle(r: dict) -> dict:
    """旧行 verbatim 档案（params_json.legacy_kit）。JSON 列解析失败则存原串。"""
    def _j(v: str | None):
        if v is None or not str(v).strip():
            return None
        try:
            return json.loads(v)
        except (TypeError, ValueError):
            return v

    return {"legacy_kit": {
        "id": r["id"], "domain": r["domain"], "operation": r["operation"],
        "source": r["source"], "result": r["result"],
        "needs_attention": r["needs_attention"], "report": r["report"],
        "request": _j(r["request"]), "response": _j(r["response"]),
        "detail": _j(r["detail"]),
        "executed_at": r["executed_at"], "created_at": r["created_at"],
        "updated_at": r["updated_at"],
    }}


def _report(plan: dict, n_runs: int, n_accounts: int) -> None:
    dist: dict[str, int] = {}
    for row in plan["run_plan"]:
        key = f"{row['result_raw'] or '∅'} → {row['status'] or 'NULL'}"
        dist[key] = dist.get(key, 0) + 1
    print(f"源：runs {n_runs} 行 / accounts {n_accounts} 行")
    print(f"计划导入 runs {len(plan['run_plan'])} 行；账户写入（含已存在跳过）{len(plan['new_accounts'])} 个")
    print("结果词映射分布：")
    for k in sorted(dist):
        print(f"  {k}: {dist[k]}")
    for w in plan["warnings"]:
        print(f"  ⚠ {w}")


def _backup(target: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = Path(str(target) + f".backup-legacy-{stamp}")
    src = sqlite3.connect(str(target))
    dst = sqlite3.connect(str(backup_path))
    src.backup(dst)
    dst.close()
    src.close()
    return backup_path


def _commit(target: Path, plan: dict, tag: str) -> None:
    before = _count_imported(target, tag)
    conn = sqlite3.connect(str(target))
    conn.execute("PRAGMA busy_timeout=5000")
    try:
        conn.execute("BEGIN")
        for a in plan["new_accounts"]:
            conn.execute(
                "INSERT OR IGNORE INTO accounts (id, provider, account_name, created_at) "
                "VALUES (?, ?, ?, ?)",
                (a["id"], a["provider"], a["account_name"],
                 a["created_at"] or datetime.now(timezone.utc).isoformat()),
            )
        for row in plan["run_plan"]:
            evidence_summary = f"旧 kit：{row['report']}" if row["report"] else "旧 kit 历史记录"
            result_json = (
                json.dumps({"status": row["status"],
                            "evidence": [{"summary": evidence_summary, "raw_code": None}],
                            "repair_hint": None}, ensure_ascii=False)
                if row["status"] else None
            )
            conn.execute(
                "INSERT OR IGNORE INTO runs (id, kind, target, params_json, account_id, "
                "idempotency_key, started_at, budget_seconds, finished_at, status, result_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (row["id"], row["kind"], row["target"],
                 json.dumps(_bundle(row["source_row"]), ensure_ascii=False),
                 row["account_id"], row["idempotency_key"], row["started_at"],
                 0.0, row["started_at"], row["status"], result_json),
            )
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()
    got = _count_imported(target, tag)
    want = len(plan["run_plan"])
    if got != want:
        raise SystemExit(f"验证失败：库里 legacy-kit:{tag}:* 共 {got} 行 ≠ 计划 {want} 行——检查 {target}")
    print(f"✓ 本轮新增 {got - before} 行，库内共 {got} 行（幂等主键 legacy-kit:{tag}:*）")


def _count_imported(target: Path, tag: str) -> int:
    conn = sqlite3.connect(str(target))
    n = conn.execute("SELECT COUNT(*) FROM runs WHERE id LIKE ?",
                     (f"legacy-kit:{tag}:%",)).fetchone()[0]
    conn.close()
    return n


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--source", required=True, help="旧 kit 库文件路径（-wal/-shm 有则一并读）")
    ap.add_argument("--commit", action="store_true", help="真迁（默认干跑）")
    ap.add_argument("--target", default=None, help="目标 butler.db（默认数据根 / BUTLER_DB）")
    ap.add_argument("--tag", default="kit", help="源库标签（多来源时区分幂等键，默认 kit）")
    ap.add_argument("--tz-offset", type=float, default=8.0, help="旧库本地时间时区（小时，默认 +8）")
    ap.add_argument("--allow-live-writer", action="store_true",
                    help="目标 -wal 非空仍强制写入（默认拒绝——先停 server）")
    args = ap.parse_args()

    src = Path(args.source).expanduser()
    if not src.exists():
        raise SystemExit(f"源库不存在：{src}")
    target = _target_db(args.target)
    if not target.exists():
        raise SystemExit(f"目标库不存在：{target}（先跑一次 butler 让它建库）")
    wal = Path(str(target) + "-wal")
    if args.commit and wal.exists() and wal.stat().st_size > 0 and not args.allow_live_writer:
        raise SystemExit(f"目标 -wal 非空（{wal.stat().st_size}B）——先停 butler server 再 --commit")

    with tempfile.TemporaryDirectory() as td:
        staged = _stage_source(src, Path(td))
        conn = sqlite3.connect(str(staged))  # 工作副本可写，允许 sqlite 自行恢复 WAL
        _verify_schema(conn)
        runs, accounts = _load_rows(conn)
        conn.close()

    plan = _plan(runs, accounts, args.tz_offset, args.tag)
    _report(plan, len(runs), len(accounts))

    if not args.commit:
        print("\n（干跑未写库——加 --commit 执行真迁；真迁前先停 butler server）")
        return 0
    backup = _backup(target)
    _commit(target, plan, args.tag)
    print(f"✓ 备份：{backup}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
