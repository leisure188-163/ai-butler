"""AgentRouter（New API 系）网页登录即签到连接器（A2-02 §3 adapter 级）。

协议事实（2026-11-16 真机取证，见同目录 PROTOCOL.md）：
- 站点只提供“登录即签到”：登录响应/前端 user 快照里的 ``checked_in`` 为 true
  即表示当日 $25 已到账；没有独立的签到按钮，也没有可用的 POST /api/user/checkin
  路由（POST 返回 404）。
- 登录态在浏览器页面里，Chrome v20 cookie 不可解（A2-03 §7）；因此本连接器
  不复用 cookie 捕获，而是经本机浏览器的 CDP 调试端口（缺省 9222，
  ``AGENTROUTER_CDP_PORT`` 可覆盖）读取页面前端自己维护的
  ``localStorage.user`` 非密快照（web_ui.py 通用底座）。
- 端口归属先校验（ADR-026）：端口上若是客户端应用内窗口（如 doubao://），
  显式失败并提示配专用浏览器，绝不往别人的窗口里开页。
- 不读取、不保存 token/cookie；只把 user_id/checked_in 等状态作为证据。

停靠：页面已登录 → 注册 agentrouter:main + 写一枚 ``browser_session``
定位凭据（domain/port/user_id，非密，仅用于账户台账与审计）。
领取：checked_in=true → ALREADY；false → 自动执行「退出 → GitHub 登录 →
回调前缀替换」→ CLAIMED（登录即签到）；任何一步失败转 NO_AUTH/PENDING +
relogin，不假装成功。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from butler_connectors.cdp import CdpChannel, CdpError, http_json, ws_connect
from butler_connectors.registry import DockContext, DockOutcome
from butler_connectors.web_ui import (
    PortNotBrowser,
    WebPageState,
    WebPageUnavailable,
    click_selector,
    click_text,
    find_page,
    open_page,
    read_page,
    require_browser_port,
    rewrite_host,
    state_digest,
    wait_for_page,
)
from butler_core.accounts.domain import AccountIdentity, Secret
from butler_core.execution.domain import ActionKind, Evidence, RepairHint, RunResult
from butler_core.execution.ports import Capabilities, ProvisionRequest
from butler_core.shared.results import Status

CONN_ID = "agentrouter"
DISPLAY = "AgentRouter"
DOMAIN = "ps.air-outer.com"
DEBUG_PORT = 9222  # 缺省调试端口（AGENTROUTER_CDP_PORT 未设时；ADR-026）
PORT_ENV = "AGENTROUTER_CDP_PORT"
LOGIN_PATH = "/login"
CALLBACK_DOMAIN = "agentrouter.org"
CONSOLE_PATH = "/console"
CALLBACK_TIMEOUT = 75.0


class ReloginError(RuntimeError):
    """自动退出/重登链路未完成；调用方转成可修复的 NO_AUTH/PENDING。"""


class BrowserPortError(CdpError):
    """浏览器调试端口不可用（配置非法/被客户端应用占用）——环境问题，不转 relogin。"""


def _debug_port() -> int:
    """生效端口：AGENTROUTER_CDP_PORT 优先（非法值显式报错，不静默回缺省），缺省 9222。"""
    raw = (os.environ.get(PORT_ENV) or "").strip()
    if not raw:
        return DEBUG_PORT
    try:
        port = int(raw)
    except ValueError:
        raise BrowserPortError(f"{PORT_ENV}={raw!r} 不是端口号——改成 1-65535 的整数") from None
    if not 1 <= port <= 65535:
        raise BrowserPortError(f"{PORT_ENV}={port} 超出端口范围 1-65535")
    return port


def _page(port: int | None = None) -> dict:
    """取目标页；关掉时经 CDP 自动开控制台，不再把"页面没开"当登录失败。

    控制台优先：若该 Chromium 已保存站点会话，打开后直接是 /console；
    没有会话时由站点自己落到 /login，后续仍走 _relogin 的 GitHub 链路。

    端口归属先校验（ADR-026）：9222 被豆包客户端等应用占用时显式失败——
    绝不往别人的客户端窗口里开外站页面。
    """
    port = port if port is not None else _debug_port()
    channel = CdpChannel(port, http_get=http_json, ws_factory=ws_connect)
    try:
        require_browser_port(channel)
    except PortNotBrowser as exc:
        raise BrowserPortError(
            f"{exc}；用 {PORT_ENV}=<专用浏览器端口> 指向一个已登录 https://{DOMAIN} "
            "的浏览器（浏览器需带 --remote-debugging-port 启动）"
        ) from exc
    page = find_page(port, DOMAIN, channel=channel)
    if page is not None:
        return page
    return open_page(
        port,
        DOMAIN,
        f"https://{DOMAIN}{CONSOLE_PATH}",
        channel=channel,
    )


def _state() -> WebPageState:
    port = _debug_port()
    _page(port)
    return read_page(port, DOMAIN)


def _display_for(state: WebPageState) -> str:
    return f"{DISPLAY}（{state.username}）" if state.username else DISPLAY


def _relogin(*, force_login: bool = False) -> WebPageState:
    """自动执行「退出 → GitHub 登录 → 回调前缀替换」，返回重登后的页面状态。

    在 checked_in=false（含页面在登录页、localStorage 用户被清）时调用；不读取/保存
    GitHub 凭据，依赖浏览器已有 GitHub 会话。任何一步找不到控件/跳转超时都抛
    ReloginError，由 run() 转成人工 relogin
    提示，绝不假装签到成功。
    """
    port = _debug_port()
    channel = CdpChannel(port, http_get=http_json, ws_factory=ws_connect)
    try:
        page = _page(port)
    except WebPageUnavailable as exc:
        raise ReloginError(str(exc)) from exc
    path = urlsplit(page.get("url") or "").path

    with channel.attach(page) as conn:
        conn.call("Page.bringToFront", wait=3.0)
        if force_login and not path.startswith(LOGIN_PATH):
            # 页面在控制台但 localStorage 已经没有用户（会话被清/页面刚恢复）：
            # 直接回登录页，避免在无用户菜单的页面上空点。
            conn.call(
                "Page.navigate",
                {"url": f"https://{DOMAIN}{LOGIN_PATH}"},
                wait=5.0,
            )
            channel.sleep(1.5)
        elif path.startswith(CONSOLE_PATH):
            if not click_selector(
                channel,
                conn,
                'header button[aria-haspopup="true"]:not([aria-label])',
            ):
                raise ReloginError("找不到右上角用户菜单")
            channel.sleep(0.4)
            if not click_text(channel, conn, "退出", selector='[role="menuitem"]'):
                raise ReloginError("找不到「退出」菜单项")
        elif not path.startswith(LOGIN_PATH):
            raise ReloginError(f"当前页面不是登录页/控制台：{path}")

    login = wait_for_page(
        port, DOMAIN, path_prefix=LOGIN_PATH, timeout=8.0, channel=channel
    )
    if login is None:
        raise ReloginError("退出后没有回到登录页")
    with channel.attach(login) as conn:
        conn.call("Page.bringToFront", wait=3.0)
        if not click_text(channel, conn, "使用 GitHub", selector="button"):
            raise ReloginError("找不到「使用 GitHub 继续」按钮")

    callback = wait_for_page(
        port,
        CALLBACK_DOMAIN,
        path_prefix="/oauth/github",
        timeout=CALLBACK_TIMEOUT,
        channel=channel,
    )
    if callback is None:
        raise ReloginError("GitHub 未返回 OAuth 回调（可能需要重新登录 GitHub）")
    with channel.attach(callback) as conn:
        conn.call("Page.bringToFront", wait=3.0)
        conn.call("Page.navigate", {"url": rewrite_host(callback["url"], DOMAIN)})

    console = wait_for_page(
        port, DOMAIN, path_prefix=CONSOLE_PATH, timeout=20.0, channel=channel
    )
    if console is None:
        raise ReloginError("回调后没有进入控制台")
    return read_page(port, DOMAIN)


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


def _after_relogin(state: WebPageState) -> RunResult:
    """自动重登后的统一结果：真签到 → CLAIMED，否则 PENDING 并提示人工。"""
    if state.checked_in:
        return RunResult(
            status=Status.CLAIMED,
            evidence=(
                Evidence(
                    summary=(
                        "已自动退出并重新登录，登录即签到完成——"
                        f"{state_digest(state, display=DISPLAY)}"
                    )
                ),
            ),
        )
    return RunResult(
        status=Status.PENDING,
        evidence=(
            Evidence(
                summary=(
                    "自动重登已完成，但站点未标记 checked_in=true——"
                    f"{state_digest(state, display=DISPLAY)}"
                )
            ),
        ),
        repair_hint=RepairHint(
            reason="自动重登后仍未签到，请确认 GitHub 登录完成，再点「重新登录」重试",
            action_id="relogin",
        ),
    )


@dataclass
class AgentRouterPort:
    """provision.run 端口：读页面状态；未签到时自动退出并重新登录。"""

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
            # 页面在登录页 / localStorage 用户被清：也尝试自动回登录，
            # 而不是直接判死；GitHub 会话也失效时仍转人工 relogin。
            if req.dry_run:
                return _no_auth(str(exc))
            try:
                state = _relogin(force_login=True)
            except ReloginError as relogin_exc:
                return _no_auth(f"自动重登未完成：{relogin_exc}")
            except Exception as relogin_exc:  # noqa: BLE001
                return _no_auth(
                    f"自动重登异常：{type(relogin_exc).__name__}: {relogin_exc}"
                )
            return _after_relogin(state)
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

        try:
            state = _relogin()
        except ReloginError as exc:
            return _no_auth(f"自动重登未完成：{exc}")
        except Exception as exc:  # noqa: BLE001 —— 浏览器链路异常转成可修复态
            return _no_auth(f"自动重登异常：{type(exc).__name__}: {exc}")

        return _after_relogin(state)


def build_port(*, vault: Any, transport: Any) -> AgentRouterPort:
    """registry.provision_ports 的 adapter 工厂（A2-02 §3）。"""
    return AgentRouterPort(vault=vault, transport=transport)


def dock(ctx: DockContext) -> DockOutcome:
    """session.import：页面已登录即登记账户；页面关闭自动开控制台，不碰 cookie。"""
    try:
        state = _state()
    except WebPageUnavailable as exc:
        return DockOutcome(target=CONN_ID, issues=[f"{CONN_ID}: {exc}"])
    except Exception as exc:
        return DockOutcome(target=CONN_ID, issues=[f"{CONN_ID}: 页面读取失败：{exc}"])

    account = ctx.register.execute(
        CONN_ID,
        _display_for(state),
        account_code="main",
        identity=AccountIdentity(
            nickname=_display_for(state),
            source_key=f"github_{state.user_id}" if getattr(state, "user_id", None) else "",
        ),
    )
    if ctx.vault is not None:
        marker = json.dumps(
            {"domain": DOMAIN, "port": _debug_port(), "user_id": state.user_id},
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

