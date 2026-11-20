"""Butler CLI（执行器/排障用，非主入口——决策见 STATUS）。

卡包命令词表（A1-03 §4）：cards（卡=账户）/ apps（平台）/ import（导入）/
claim（领取）/ check（体检）/ records（领取记录）。全部经 bridge 触达引擎
（规约 R4），短命令即开即关。
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta

import typer
from rich.console import Console
from rich.table import Table

if sys.platform == "win32":
    # Windows GBK 控制台：rich 的 ✔/表格边框字符触发 UnicodeEncodeError——
    # 输出流强制 UTF-8（等效 PYTHONIOENCODING=utf-8；非 TTY/测试桩无 reconfigure 则跳过）
    for _stream in (sys.stdout, sys.stderr):
        if _stream is not None and hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="replace")

platform = typer.Typer(help="Butler · 你的 AI 卡包（执行器/排障）")
cards = typer.Typer(help="卡（账号）管理")
platform.add_typer(cards, name="cards")
db = typer.Typer(help="数据库迁移链（ADR-036）")
platform.add_typer(db, name="db")
console = Console()


def _kit():
    from butler_engine.bridge import build_engine, default_db_path

    return build_engine(os.environ.get("BUTLER_DB") or default_db_path())


def _registry():
    """连接器注册表（ADR-005）：CLI 与 server 同源装载。"""
    from butler_connectors.registry import load_registry

    return load_registry()


def _mount_ports(kit) -> None:
    """手动命令需要端口路由：挂 target 级连接器端口（不启调度——短命令即开即关）。"""
    kit.register_provision_ports(
        targets=_registry().provision_ports(vault=kit.vault, transport=None)
    )


def _unknown_target(target: str) -> None:
    from butler_connectors.registry import load_registry

    console.print(
        f"[red]连接器未接入: {target!r}[/red]（可用: {', '.join(load_registry().ids())}）"
    )
    raise typer.Exit(code=2)


def _db_path() -> str:
    from butler_engine.bridge import default_db_path

    return os.environ.get("BUTLER_DB") or default_db_path()


@db.command("migrate")
def db_migrate() -> None:
    """追跑迁移链到最新（幂等；存量旧库走 baseline 记账，ADR-036）。"""
    from butler_engine.bridge import ensure_db_migrated

    applied = ensure_db_migrated(_db_path())
    if applied:
        console.print("[green]✔ 已应用迁移[/green] " + "、".join(f"{v:03d}" for v in applied))
    else:
        console.print("[green]已是最新[/green]，无需迁移")


@db.command("status")
def db_status() -> None:
    """查看库路径、当前迁移版本与已应用记录。"""
    from butler_engine.bridge import db_migration_status

    path = _db_path()
    status = db_migration_status(path)
    current, latest = status["current"], status["latest"]
    console.print(f"库：{path}")
    console.print(f"版本：{current:03d} / 最新 {latest:03d}（{status['latest_name']}）"
                  + ("[green]· 已是最新[/green]" if current >= latest else "[yellow]· 待迁移[/yellow]"))
    if status["applied"]:
        table = Table("版本", "迁移", "记账时间")
        for version, name, applied_at in status["applied"]:
            table.add_row(f"{version:03d}", name, applied_at)
        console.print(table)


@platform.command("platforms")
def platforms() -> None:
    """平台名册：plat_platform 名册表 × 导入状态（与 server GET /platforms 同源投影）。"""
    kit = _kit()
    try:
        imported: dict[str, list[str]] = {}
        for account in kit.accounts.list_all():
            imported.setdefault(account.platform_code, []).append(account.id)
        table = Table("平台", "能力", "凭据", "时间表", "账户")
        for platform in kit.platforms.list_all():  # 名册表（ADR-021/022，DB 为真相源）
            if platform.deprecated_at is not None or not platform.is_active:
                continue  # 退役/停用平台不出现在名册
            table.add_row(
                f"{platform.platform_name} ({platform.platform_code})",
                ", ".join(sorted(platform.capabilities)) or "—",
                ", ".join(platform.credential_kinds) or "—",
                " ".join(platform.schedule_times) or "—",
                ", ".join(imported.get(platform.platform_code, [])) or "[yellow]未导入[/yellow]",
            )
        console.print(table)
    finally:
        kit.close()


@platform.command("import")
def import_cmd(target: str) -> None:
    """导入：扫本机客户端 → 账户注册 → 凭据入库（结果如实分列，不静默）。"""
    from butler_connectors.registry import DockContext

    kit = _kit()
    try:
        registry = _registry()
        if target not in registry.ids():
            _unknown_target(target)
        [outcome] = registry.dock(
            DockContext(vault=kit.vault, register=kit.register_account), target=target
        )
        for acc in outcome.accounts:
            console.print(f"[green]✔ 已导入[/green] {acc}")
        for issue in outcome.issues:
            console.print(f"[yellow]· {issue}[/yellow]")
        if not outcome.accounts and not outcome.issues:
            console.print("[yellow]没有发现可导入的账号[/yellow]")
    finally:
        kit.close()


@platform.command()
def claim(
    target: str,
    account: str = typer.Option(
        None, "--account", "-a",
        help="账户 key（完整卡号 = <target>:<key>；省略 = 该平台第一张卡）",
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="只演练不落账"),
) -> None:
    """手动领取：立即跑一次 provision.run（窗口按 core 时间表规则）。"""
    from butler_core.execution.usecases.execute_action import RunRequest
    from butler_core.execution.domain import Action, ActionKind
    from butler_core.scheduling.domain import claim_window

    kit = _kit()
    try:
        registry = _registry()
        try:
            app_obj = registry.get(target)
        except KeyError:
            _unknown_target(target)
        if account is None:
            # 省略 --account = 该平台第一张卡（2026-11-18 起卡号用实际昵称，
            # 不再假定 main 占位存在）
            known = kit.accounts.list_by_platform(target)
            if not known:
                console.print(f"[red]该平台暂无卡（未导入）——先跑 import {target}[/red]")
                raise typer.Exit(code=2)
            account = known[0].account_code
        account_id = f"{target}:{account}"
        if kit.accounts.get(account_id) is None:
            known = [a.id for a in kit.accounts.list_by_platform(target)]
            console.print(
                f"[red]卡不存在: {account_id}[/red]"
                f"（该平台已有: {', '.join(known) or '未导入——先跑 import'}）"
            )
            raise typer.Exit(code=2)
        _mount_ports(kit)
        entry = next(
            (e for e in registry.schedule_entries() if e["target"] == target), None
        )
        window = claim_window(datetime.now(), entry["refresh_at"] if entry else "00:00")
        run = kit.execute_action.execute(
            RunRequest(
                action=Action(kind=ActionKind.PROVISION_RUN, target=target),
                account_id=account_id,
                window=window,
                dry_run=dry_run,
                budget=timedelta(seconds=app_obj.provision_budget("provision.run")),
            )
        )
        result = run.result
        head = f"{run.action.target} · {run.account_id}"
        if result is None:
            console.print(f"[yellow]{head} —— 未终态（预算内未完成）[/yellow]")
            return
        color = {"ok": "green", "notice": "yellow", "attention": "red", "danger": "red"}.get(
            result.kind.signal, "white"
        )
        console.print(f"[{color}]{head} → {result.status.value}[/{color}]")
        for ev in result.evidence:
            console.print(f"  · {ev.summary}" + (f"（码 {ev.raw_code}）" if ev.raw_code else ""))
        if result.repair_hint:
            console.print(
                f"  → 修复建议：{result.repair_hint.reason}（动作 {result.repair_hint.action_id}）"
            )
    finally:
        kit.close()


@cards.command("list")
def cards_list() -> None:
    """卡一览：账号 × 健康。"""
    kit = _kit()
    try:
        accounts: dict[str, list] = {}
        for hp in kit.vault.health():
            accounts.setdefault(hp.account_id, []).append(hp)
        table = Table("卡", "健康", "证据", "凭证")
        for account_id in accounts:
            health = kit.assess_account_health.execute(account_id)
            kinds = ", ".join(hp.kind for hp in accounts[account_id])
            table.add_row(account_id, health.level.value, "; ".join(health.evidence), kinds)
        console.print(table)
    finally:
        kit.close()


@platform.command()
def records(limit: int = typer.Option(30, help="最多展示条数")) -> None:
    """领取记录：最近 Run。"""
    kit = _kit()
    try:
        table = Table("时间", "动作", "平台", "卡", "结果码")
        for run in kit.ledger.list_recent(limit=max(1, min(limit, 200))):
            result = run.result
            table.add_row(
                run.started_at.strftime("%m-%d %H:%M"),
                run.action.kind.value,
                run.action.target,
                run.account_id,
                result.status.value if result else "—（未终态）",
            )
        console.print(table)
    finally:
        kit.close()


@platform.command()
def check() -> None:
    """体检：立即跑一次凭据到期扫描（日常由每日 job 自动执行）。"""
    kit = _kit()
    try:
        events = kit.scan_credential_expiry.execute()
        if not events:
            console.print("[green]无事发生[/green]——没有新的到期信号")
        for event in events:
            console.print(
                f"[yellow]{event.type.value}[/yellow] 卡 {event.account_id} "
                f"kind={event.payload.get('kind')}"
            )
    finally:
        kit.close()


if __name__ == "__main__":
    platform()
