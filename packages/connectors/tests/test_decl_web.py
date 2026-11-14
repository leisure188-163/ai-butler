"""探针端口（DeclarativeHealthPort）与两家网页连接器装载——离线 FakeTransport。

A2-03 §6：HTTP 200→ALREADY、401→EXPIRED、403→NO_AUTH、未知码上抛（协议变更
探测）、非本通道动作拒绝、缺凭据 NO_AUTH、证据摘要（区域 403 ≠ 会话挑战）；
解锁走真 browser_cookie loader（Cookie 头单源不 mock）。
"""

import json
from datetime import UTC, datetime, timedelta

import pytest

from butler_core.accounts.ports import CredentialMissing

from butler_core.execution.ports import ProvisionRequest
from butler_core.execution.domain import ActionKind
from butler_core.shared.results import Status, UnknownEngineCode, from_engine, register_dialect
from butler_core.accounts.domain import Secret

from butler_connectors.decl import DeclarativeHealthPort
from butler_connectors.manifest import ProbeSpec
from butler_connectors.transport import HttpResponse, TransportError

CONN = "webco"
register_dialect(CONN, {"401": Status.EXPIRED, "403": Status.NO_AUTH})  # 单测自带方言（装载期注册发生在 load_registry）
ENVELOPE = json.dumps(
    {
        "browser": "chrome",
        "domain": "webco.test",
        "cookies": [{"name": "__Secure-next-auth.session-token", "value": "V-1"}],
    }
)


class CookieVault:
    """vault 替身：返回真 browser_cookie 信封（解锁链全真）。"""

    def __init__(self, envelope: str = ENVELOPE) -> None:
        self.envelope = envelope

    def load(self, account_id: str, kinds):
        return [Secret(self.envelope)]


class MissingVault:
    def load(self, account_id: str, kinds):
        raise CredentialMissing(f"缺 kind={kinds}")


class FakeTransport:
    """剧本：每次调用弹一个响应（Exception 项 = 直接抛，如 TransportError）。"""

    def __init__(self, script):
        self.script = list(script)
        self.calls: list[tuple[str, str, dict]] = []

    def __call__(self, req, *, deadline):
        assert deadline.tzinfo is not None, "deadline 必须带时区"
        self.calls.append((req.method, req.url, dict(req.headers)))
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def probe_spec() -> ProbeSpec:
    return ProbeSpec.model_validate(
        {
            "auth": {"kind": "browser_cookie"},
            "probe": {
                "request": {
                    "method": "GET",
                    "url": "https://webco.test/api/auth/session",
                },
                "ok_status": 200,
            },
            "codes": {"401": "EXPIRED", "403": "NO_AUTH"},
        }
    )


def make_port(transport, vault=None) -> DeclarativeHealthPort:
    return DeclarativeHealthPort(
        conn_id=CONN,
        display="WebCo",
        spec=probe_spec(),
        vault=vault or CookieVault(),
        transport=transport,
        kinds=("browser_cookie",),
    )


def request(kind: ActionKind = ActionKind.HEALTH_CHECK) -> ProvisionRequest:
    return ProvisionRequest(
        kind=kind,
        target=CONN,
        account_id="webco:main",
        params={},
        deadline=datetime.now(UTC) + timedelta(seconds=60),
        dry_run=False,
    )


# --- 探针七词映射 ---


def test_http_ok_is_already():
    """healthy = silent：期望态已达成 → ALREADY（A2-03 §3 裁决）。"""
    transport = FakeTransport([HttpResponse(status_code=200, payload={"ok": True})])
    result = make_port(transport).run(request())
    assert result.status is Status.ALREADY
    assert "会话有效" in result.evidence[0].summary
    method, url, headers = transport.calls[0]
    assert (method, url) == ("GET", "https://webco.test/api/auth/session")
    assert headers["Cookie"] == "__Secure-next-auth.session-token=V-1"  # 真解锁链


def test_401_expired_with_dock_hint():
    transport = FakeTransport([HttpResponse(status_code=401, payload={})])
    result = make_port(transport).run(request())
    assert result.status is Status.EXPIRED
    assert result.evidence[0].raw_code == "401"
    assert result.repair_hint is not None and result.repair_hint.action_id == "dock"
    assert "重新导入" in result.repair_hint.reason


def test_403_no_auth_carries_response_digest():
    """挑战/区域 403 分流靠 evidence 摘要：error 字段进证据（不吞协议形状）。"""
    transport = FakeTransport(
        [
            HttpResponse(
                status_code=403,
                payload={"error": {"type": "permission_error", "message": "region unavailable"}},
            )
        ]
    )
    result = make_port(transport).run(request())
    assert result.status is Status.NO_AUTH
    assert "permission_error" in result.evidence[0].summary
    assert "region unavailable" in result.evidence[0].summary
    assert result.repair_hint is not None and result.repair_hint.action_id == "dock"


def test_unknown_status_raises_protocol_probe():
    """未声明 HTTP 码（500）= 协议变更探测 → UnknownEngineCode 上抛（ExecuteAction
    统一 FAILED + PROTOCOL_CHANGED）。"""
    transport = FakeTransport([HttpResponse(status_code=500, payload={})])
    with pytest.raises(UnknownEngineCode):
        make_port(transport).run(request())


def test_wrong_verb_refused_without_transport():
    """网页通道无领取概念：非 health.check 动作显式拒绝，请求不出门。"""
    transport = FakeTransport([])
    result = make_port(transport).run(request(ActionKind.PROVISION_RUN))
    assert result.status is Status.FAILED
    assert "provision.run" in result.evidence[0].summary
    assert transport.calls == []


def test_missing_credential_no_auth():
    """主凭据缺失 = 无登录态 → NO_AUTH + dock 修复（不是 FAILED）。"""
    result = make_port(FakeTransport([]), vault=MissingVault()).run(request())
    assert result.status is Status.NO_AUTH
    assert "缺凭据" in result.evidence[0].summary
    assert result.evidence[0].raw_code == "browser_cookie"
    assert result.repair_hint is not None and result.repair_hint.action_id == "dock"


def test_transport_error_is_failed_not_session_verdict():
    """探针发不出去 ≠ 会话失效：TransportError → FAILED（网络语义）。"""
    transport = FakeTransport([TransportError("connection refused")])
    result = make_port(transport).run(request())
    assert result.status is Status.FAILED
    assert "探针不可达" in result.evidence[0].summary


def test_capabilities_no_dry_run():
    """探针不支持 dry_run（只读动作，无降级空间）。"""
    assert make_port(FakeTransport([])).capabilities().dry_run is False


# --- 装载与注册表接线（真包）---


@pytest.fixture(scope="module")
def registry():
    from butler_connectors.registry import load_registry

    return load_registry()


def test_web_connectors_loaded_with_shapes(registry):
    assert {"chatgpt_web", "claude_web"} <= set(registry.ids())
    chatgpt = registry.get("chatgpt_web")
    assert chatgpt.display == "ChatGPT"
    assert set(chatgpt.declarative) == {"session.import", "health.check"}
    assert chatgpt.manifest.credential.kinds == ["browser_cookie"]
    capture = chatgpt.declarative["session.import"]
    assert capture.auth.domain == "chatgpt.com"
    assert capture.auth.cookies == [
        "__Secure-next-auth.session-token.0",
        "__Secure-next-auth.session-token.1",
    ]
    probe = chatgpt.declarative["health.check"]
    assert probe.probe.request.url == "https://chatgpt.com/api/auth/session"
    assert probe.probe.ok_status == 200
    claude = registry.get("claude_web")
    assert claude.declarative["session.import"].auth.domain == "claude.ai"


def test_http_codes_registered_as_dialect(registry):
    """ProbeSpec.codes 装载期注册方言（ADR-004 唯一翻译点）。"""
    assert from_engine("401", dialect="chatgpt_web") is Status.EXPIRED
    assert from_engine("403", dialect="chatgpt_web") is Status.NO_AUTH
    assert from_engine("401", dialect="claude_web") is Status.EXPIRED


def test_provision_ports_skip_web_connectors(registry):
    """未申报 provision.run 的连接器跳过（一键领取不数它们）。"""
    ports = registry.provision_ports(vault=None, transport=None)
    assert "chatgpt_web" not in ports and "claude_web" not in ports
    assert {"trae_cn", "qoder_cn", "doubao_cn", "workbuddy_cn"} <= set(ports)


def test_health_ports_built_for_web_connectors(registry):
    from butler_connectors.decl import DeclarativeHealthPort as Port

    sentinel = object()
    ports = registry.health_ports(vault=None, transport=sentinel)
    assert set(ports) == {"chatgpt_web", "claude_web"}
    assert isinstance(ports["chatgpt_web"], Port)
    assert ports["chatgpt_web"]._call is sentinel  # 注入面透传（离线测试必需）
    assert ports["chatgpt_web"]._kinds == ("browser_cookie",)


def test_web_connectors_have_no_schedule(registry):
    """探针调度不进本批（A2-03 §3）：web 连接器无调度条目。"""
    targets = {entry["target"] for entry in registry.schedule_entries()}
    assert "chatgpt_web" not in targets and "claude_web" not in targets


def test_dock_dispatch_falls_to_session_import(registry, monkeypatch):
    """dock 分发回落：无 provision.run → 走 browser.capture_cookies（A2-03 §4）。"""
    import butler_connectors.browser as browser_mod

    from butler_connectors.registry import DockContext, DockOutcome

    seen: dict = {}

    def fake_capture(app, spec, kinds, ctx):
        seen["target"] = app.manifest.id
        seen["spec"] = type(spec).__name__
        seen["kinds"] = kinds
        return DockOutcome(target=app.manifest.id, accounts=["fake"])

    monkeypatch.setattr(browser_mod, "capture_cookies", fake_capture)
    outcomes = registry.dock(DockContext(vault=None, register=None), target="claude_web")
    assert outcomes == [DockOutcome(target="claude_web", accounts=["fake"])]
    assert seen == {
        "target": "claude_web",
        "spec": "CaptureSpec",
        "kinds": ("browser_cookie",),
    }


def test_dock_web_without_cookies_reports_not_logged_in(registry, tmp_path):
    """分发落地的真实捕获通道：候选全空 → 未发现 cookie 库（非「未申报能力」）。"""
    from butler_connectors.registry import DockContext

    ctx = DockContext(
        vault=None,
        register=None,
        storage_override=[str(tmp_path / "Chrome/*/Cookies")],
    )
    outcomes = registry.dock(ctx, target="chatgpt_web")
    assert outcomes[0].accounts == []
    assert outcomes[0].issues and "未发现 Chrome cookie 库" in outcomes[0].issues[0]
