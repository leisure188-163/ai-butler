"""AgentRouter adapter（登录即签到）离线测试：页面状态 → 七词结果。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from butler_connectors.agentrouter import adapter
from butler_connectors.registry import DockContext
from butler_connectors.web_ui import WebPageState, WebPageUnavailable
from butler_core.execution.domain import ActionKind
from butler_core.execution.ports import ProvisionRequest
from butler_core.shared.results import Status


def _state(*, checked_in: bool) -> WebPageState:
    return WebPageState(
        user_id=437667,
        username="github_437667",
        checked_in=checked_in,
        last_login_time=1794800998,
        quota=0,
        url="https://ps.air-outer.com/console",
    )


def _request(*, dry_run: bool = False) -> ProvisionRequest:
    return ProvisionRequest(
        kind=ActionKind.PROVISION_RUN,
        target="agentrouter",
        account_id="agentrouter:main",
        params={},
        deadline=datetime.now(timezone.utc) + timedelta(seconds=60),
        dry_run=dry_run,
    )


@pytest.fixture()
def port() -> adapter.AgentRouterPort:
    return adapter.AgentRouterPort()


def test_checked_in_is_already(port, monkeypatch):
    monkeypatch.setattr(adapter, "_state", lambda: _state(checked_in=True))
    result = port.run(_request())
    assert result.status is Status.ALREADY
    assert result.repair_hint is None
    assert "checked_in=true" in result.evidence[0].summary


def test_not_checked_in_triggers_auto_relogin(port, monkeypatch):
    monkeypatch.setattr(adapter, "_state", lambda: _state(checked_in=False))
    monkeypatch.setattr(adapter, "_relogin", lambda: _state(checked_in=True))
    result = port.run(_request())
    assert result.status is Status.CLAIMED
    assert result.repair_hint is None
    assert "自动退出并重新登录" in result.evidence[0].summary


def test_auto_relogin_failure_is_no_auth_with_relogin(port, monkeypatch):
    monkeypatch.setattr(adapter, "_state", lambda: _state(checked_in=False))

    def _fail():
        raise adapter.ReloginError("GitHub 未返回 OAuth 回调")

    monkeypatch.setattr(adapter, "_relogin", _fail)
    result = port.run(_request())
    assert result.status is Status.NO_AUTH
    assert result.repair_hint is not None
    assert result.repair_hint.action_id == "relogin"
    assert "自动重登未完成" in result.evidence[0].summary


def test_auto_relogin_still_not_checked_in_is_pending(port, monkeypatch):
    monkeypatch.setattr(adapter, "_state", lambda: _state(checked_in=False))
    monkeypatch.setattr(adapter, "_relogin", lambda: _state(checked_in=False))
    result = port.run(_request())
    assert result.status is Status.PENDING
    assert result.repair_hint is not None
    assert result.repair_hint.action_id == "relogin"


def test_not_checked_in_dry_run_is_skipped(port, monkeypatch):
    monkeypatch.setattr(adapter, "_state", lambda: _state(checked_in=False))
    monkeypatch.setattr(adapter, "_relogin", lambda: pytest.fail("dry_run 不应触发重登"))
    result = port.run(_request(dry_run=True))
    assert result.status is Status.SKIPPED


def test_rewrite_host_keeps_oauth_query():
    from butler_connectors.web_ui import rewrite_host

    url = (
        "https://agentrouter.org/oauth/github?code=once&iss=https%3A%2F%2Fgithub.com"
        "&state=abc"
    )
    assert rewrite_host(url, "ps.air-outer.com") == (
        "https://ps.air-outer.com/oauth/github?code=once&iss=https%3A%2F%2Fgithub.com"
        "&state=abc"
    )


def test_unavailable_page_attempts_forced_relogin(port, monkeypatch):
    def _raise() -> WebPageState:
        raise WebPageUnavailable("ps.air-outer.com 页面未登录")

    calls: list[bool] = []

    def _relogin(*, force_login: bool = False) -> WebPageState:
        calls.append(force_login)
        return _state(checked_in=True)

    monkeypatch.setattr(adapter, "_state", _raise)
    monkeypatch.setattr(adapter, "_relogin", _relogin)
    result = port.run(_request())
    assert result.status is Status.CLAIMED
    assert calls == [True]


def test_unavailable_page_relogin_failure_is_no_auth(port, monkeypatch):
    def _raise() -> WebPageState:
        raise WebPageUnavailable("浏览器未打开 ps.air-outer.com 页面")

    def _fail(*, force_login: bool = False) -> WebPageState:
        raise adapter.ReloginError("浏览器未打开 ps.air-outer.com 页面")

    monkeypatch.setattr(adapter, "_state", _raise)
    monkeypatch.setattr(adapter, "_relogin", _fail)
    result = port.run(_request())
    assert result.status is Status.NO_AUTH
    assert result.repair_hint is not None
    assert result.repair_hint.action_id == "relogin"


def test_unavailable_page_dry_run_does_not_relogin(port, monkeypatch):
    def _raise() -> WebPageState:
        raise WebPageUnavailable("ps.air-outer.com 页面未登录")

    monkeypatch.setattr(adapter, "_state", _raise)
    monkeypatch.setattr(
        adapter, "_relogin", lambda **_: pytest.fail("dry_run 不应触发重登")
    )
    result = port.run(_request(dry_run=True))
    assert result.status is Status.NO_AUTH


def test_non_provision_action_rejected(port):
    req = ProvisionRequest(
        kind=ActionKind.HEALTH_CHECK,
        target="agentrouter",
        account_id="agentrouter:main",
        params={},
        deadline=datetime.now(timezone.utc) + timedelta(seconds=60),
    )
    result = port.run(req)
    assert result.status is Status.FAILED


def test_dock_registers_and_stores_marker(monkeypatch):
    calls: list[tuple] = []

    class Register:
        def execute(self, provider: str, display: str, *, account_key: str):
            calls.append(("register", provider, display, account_key))
            return SimpleNamespace(id="agentrouter:main")

    class Vault:
        def store(self, account_id: str, kind: str, secret, **_kwargs):
            calls.append(("store", account_id, kind, secret.expose()))

    monkeypatch.setattr(adapter, "_state", lambda: _state(checked_in=True))
    outcome = adapter.dock(DockContext(vault=Vault(), register=Register()))
    assert outcome.accounts == ["agentrouter:main"]
    assert calls[0][0] == "register"
    assert calls[1][0] == "store"
    assert '"user_id":437667' in calls[1][3]
