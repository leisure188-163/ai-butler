"""AgentRouter（New API 系）网页登录即签到连接器（A2-02 §3 adapter 级）。

协议事实（2026-11-16 真机取证，见同目录 PROTOCOL.md）：
- 站点只提供“登录即签到”：登录响应/前端 user 快照里的 ``checked_in`` 为 true
  即表示当日 $25 已到账；没有独立的签到按钮，也没有可用的 POST /api/user/checkin
  路由（POST 返回 404）。
- 登录态在浏览器页面里，Chrome v20 cookie 不可解（A2-03 §7）；因此本连接器
  不复用 cookie 捕获，而是经本机 Chromium 调试端口（9222）读取页面前端
  自己维护的 ``localStorage.user`` 非密快照（web_ui.py 通用底座）。
- 不读取、不保存 token/cookie；只把 user_id/checked_in 等状态作为证据。

停靠：页面已登录 → 注册 agentrouter:main + 写一枚 ``browser_session``
定位凭据（domain/port/user_id，非密，仅用于账户台账与审计）。
领取：checked_in=true → ALREADY；false → PENDING + relogin 修复提示
（AgentRouter 必须退出后重新登录才会触发签到，不能静默代点）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from butler_connectors.registry import DockContext, DockOutcome
from butler_connectors.web_ui import WebPageState, WebPageUnavailable, read_page, state_digest
from butler_core.accounts.domain import Secret
from butler_core.execution.domain import ActionKind, Evidence, RepairHint, RunResult
from butler_core.execution.ports import Capabilities, ProvisionRequest
from butler_core.shared.results import Status

CONN_ID = "agentrouter"
DISPLAY = "AgentRouter"
DOMAIN = "ps.air-outer.com"
DEBUG_PORT = 9222


def _state() -> WebPageState:
    return read_page(DEBUG_PORT, DOMAIN)


def _display_for(state: WebPageState) -> str:
    return f"{DISPLAY}（{state.username}）" if state.username else DISPLAY


def _no_auth(why: str) -> RunResult:
    return RunResult(
        status=Status.NO_AUTH,
        evidence=(Evidence(summary=why),),
        repair_hint=RepairHint(
            reason=(
                "浏览器里的 AgentRouter 登录态不可用——请打开 https://ps.air-outer.com/login "
                "重新登录；若 GitHub 登录后回调到 agentrouter.org，把域名前缀换成 "
                "ps.air-outer.com 再打开（code/state 一次性）；该站点登录成功即完成当日签到"
            ),
            action_id="relogin",
        ),
    )


@dataclass
class AgentRouterPort:
    """provision.run 端口：只读页面状态，不代点登录。"""

    vault: Any = None
    transport: Any = None

    def capabilities(self) -> Capabilities:
        return Capabilities(dry_run=True, idempotency_window="daily")

    def run(self, req: ProvisionRequest) -> RunResult:
        if req.kind is not ActionKind.PROVISION_RUN:
            return RunResult(
                status=Status.FAILED,
                evidence=(Evidence(summary=f"{DISPLAY} 不支持动作 {req.kind.value}"),),
            )
        try:
            state = _state()
        except WebPageUnavailable as exc:
            return _no_auth(str(exc))
        except Exception as exc:
            return RunResult(
                status=Status.FAILED,
                evidence=(Evidence(summary=f"{DISPLAY} 页面读取失败：{exc}"),),
            )

        if state.checked_in:
            return RunResult(
                status=Status.ALREADY,
                evidence=(
                    Evidence(
                        summary=(
                            "今日已登录签到（checked_in=true，登录时 $25 已到账）——"
                            f"{state_digest(state, display=DISPLAY)}"
                        )
                    ),
                ),
            )
        if req.dry_run:
            return RunResult(
                status=Status.SKIPPED,
                evidence=(Evidence(summary="dry_run：登录态有效但今日 checked_in=false"),),
            )
        return RunResult(
            status=Status.PENDING,
            evidence=(
                Evidence(
                    summary=(
                        "登录态有效，但今日签到尚未触发：AgentRouter 在登录时发放 $25，"
                        "没有独立签到接口——请退出后重新登录"
                    )
                ),
            ),
            repair_hint=RepairHint(
                reason="退出 AgentRouter 后重新登录，登录成功即完成当日签到",
                action_id="relogin",
            ),
        )


def build_port(*, vault: Any, transport: Any) -> AgentRouterPort:
    """registry.provision_ports 的 adapter 工厂（A2-02 §3）。"""
    return AgentRouterPort(vault=vault, transport=transport)


def dock(ctx: DockContext) -> DockOutcome:
    """session.import：页面已登录即登记账户；不新开标签、不碰 cookie。"""
    try:
        state = _state()
    except WebPageUnavailable as exc:
        return DockOutcome(target=CONN_ID, issues=[f"{CONN_ID}: {exc}"])
    except Exception as exc:
        return DockOutcome(target=CONN_ID, issues=[f"{CONN_ID}: 页面读取失败：{exc}"])

    account = ctx.register.execute(CONN_ID, _display_for(state), account_key="main")
    if ctx.vault is not None:
        marker = json.dumps(
            {"domain": DOMAIN, "port": DEBUG_PORT, "user_id": state.user_id},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        ctx.vault.store(account.id, "browser_session", Secret(marker))
    return DockOutcome(target=CONN_ID, accounts=[account.id])


class _Butler:
    """manifest entry=adapter.butler：两个能力共用同一模块的两个钩子。"""

    build_port = staticmethod(build_port)
    dock = staticmethod(dock)


butler = _Butler()

