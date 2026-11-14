"""Butler CLI（执行器/排障用，非主入口——决策见 STATUS）。

卡包命令词表（A1-03 §4）：cards（卡=账号）/ apps（应用）/ import（导入）/
claim（领取）/ check（体检）/ records（领取记录）。全部经 bridge 触达引擎
（规约 R4），短命令即开即关。
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(help="Butler · 你的 AI 卡包（执行器/排障）")
cards = typer.Typer(help="卡（账号）管理")
app.add_typer(cards, name="cards")
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


@app.command("apps")
def apps() -> None:
    """应用名册：已接入连接器 × 导入状态（与 server GET /apps 同源投影）。"""
    kit = _kit()
    try:
        imported = {a.provider: a.id for a in kit.accounts.list_all()}
        table = Table("应用", "能力", "凭据", "时间表", "卡")
        for app_obj in _registry().apps():
            m = app_obj.manifest
            schedule = m.schedule.get("provision.run")
            table.add_row(
                f"{app_obj.display} ({m.id})",
                ", ".join(sorted(m.capabilities)),
                ", ".join(m.credential.kinds) if m.credential else "—",
                " ".join(schedule.times) if schedule else "—",
                imported.get(m.id) or "[yellow]未导入[/yellow]",
            )
        console.print(table)
    finally:
        kit.close()


@app.command("import")
def import_cmd(target: str) -> None:
    """导入：扫本机客户端 → 账号入卡包 → 凭据入库（结果如实分列，不静默）。"""
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


@app.command()
def claim(
    target: str,
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
        _mount_ports(kit)
        entry = next(
            (e for e in registry.schedule_entries() if e["target"] == target), None
        )
        window = claim_window(datetime.now(), entry["refresh_at"] if entry else "00:00")
        run = kit.execute_action.execute(
            RunRequest(
                action=Action(kind=ActionKind.PROVISION_RUN, target=target),
                account_id=f"{target}:main",
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


@app.command()
def records(limit: int = typer.Option(30, help="最多展示条数")) -> None:
    """领取记录：最近 Run。"""
    kit = _kit()
    try:
        table = Table("时间", "动作", "应用", "卡", "结果码")
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


@app.command()
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
    app()
