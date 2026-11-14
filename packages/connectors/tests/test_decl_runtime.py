"""声明式引擎全算法（decl.py）：结果判定 × 退避重试 × dry_run × 凭据缺失。

假 transport 逐次响应剧本化（离线，无 IO）；解锁字段 monkeypatch 稳态注入，
凭据缺失走真 CredentialMissing 路径。
"""

from datetime import UTC, datetime, timedelta

import pytest

from butler_core.accounts.ports import CredentialMissing

from butler_core.execution.ports import ProvisionRequest
from butler_core.execution.domain import ActionKind
from butler_core.shared.results import Status, UnknownEngineCode
from butler_core.accounts.domain import Secret

from butler_connectors.transport import HttpResponse

CONN = "testco"  # 方言在 conftest 预注册


def request(dry_run: bool = False, budget=timedelta(seconds=240)) -> ProvisionRequest:
    return ProvisionRequest(
        kind=ActionKind.PROVISION_RUN,
        target=CONN,
        account_id="testco:main",
        params={},
        deadline=datetime.now(UTC) + budget,
        dry_run=dry_run,
    )


class FakeVault:
    """kinds 请求缺 → CredentialMissing（真实 NO_AUTH 路径）。"""

    def load(self, account_id: str, kinds: list[str]) -> list[Secret]:
        if any(kind == "missing" for kind in kinds):
            raise CredentialMissing(f"缺 kind={kinds}")
        return [Secret("stub") for _ in kinds]


class FakeTransport:
    """剧本：每次调用弹一个响应；记录形状与 deadline（预算硬界）。"""

    def __init__(self, script: list[HttpResponse]):
        self.script = script
        self.calls: list[tuple[str, str, dict, object]] = []

    def __call__(self, req, *, deadline: datetime) -> HttpResponse:
        assert deadline.tzinfo is not None, "deadline 必须带时区"
        self.calls.append((req.method, req.url, dict(req.headers), req.body))
        if not self.script:
            raise AssertionError("剧本耗尽：实现对协议又多发了请求（契约漂移）")
        return self.script.pop(0)


def ok(payload: dict) -> HttpResponse:
    return HttpResponse(status_code=200, payload=payload)


def _stub_with(monkeypatch, fields: dict) -> None:
    import butler_connectors.decl as decl

    monkeypatch.setattr(
        decl, "unlock_all", lambda kinds, secrets: dict(fields), raising=True
    )


@pytest.fixture(autouse=True)
def stable_unlock(monkeypatch):
    """稳态解锁产物（绕开真实 base64/JWT 解码——那是 test_ss_aes 的职责）。"""
    _stub_with(monkeypatch, {"token": "T", "device_dn": "12345678"})


def make_port(transport, vault=None, sleep=None):
    from butler_connectors.decl import DeclarativeProvisionPort
    from butler_connectors.manifest import DeclarativeSpec

    spec = DeclarativeSpec.model_validate(
        {
            "auth": {
                "kind": "ss_aes",
                "token_header": {"name": "Authorization", "prefix": "JWT "},
                "static_headers": {"X-Region": "cn"},
                "dynamic_headers": {"x-device-id": "{device_dn}"},
            },
            "status": {
                "request": {"method": "POST", "url": "https://t.test/status", "body": {}},
                "checked_in_path": "checked_in",
            },
            "claim": {
                "request": {"method": "POST", "url": "https://t.test/claim", "body": {}},
                "confirm_by_status": True,
                "retry": {"on_codes": ["9074"], "backoff_seconds": [30, 60, 120]},
            },
            "business_codes": {"1001": "NO_AUTH", "9004": "FAILED", "9074": "PENDING"},
        }
    )
    return DeclarativeProvisionPort(
        conn_id=CONN,
        display="TestCo",
        spec=spec,
        vault=vault or FakeVault(),
        transport=transport,
        kinds=("ss_aes", "device_dn"),
        sleep=sleep,
        now=lambda: datetime.now(UTC),
    )


def test_status_already_checked_in():
    transport = FakeTransport([ok({"code": 0, "checked_in": True})])
    result = make_port(transport).run(request())
    assert result.status is Status.ALREADY


def test_dry_run_skips_claim():
    transport = FakeTransport([ok({"code": 0, "checked_in": False})])
    result = make_port(transport).run(request(dry_run=True))
    assert result.status is Status.SKIPPED
    assert len(transport.calls) == 1  # 只查了 status，未发 claim


def test_claim_success_with_confirm():
    transport = FakeTransport(
        [
            ok({"code": 0, "checked_in": False}),  # status 预查
            ok({"code": 0}),  # claim 受理
            ok({"code": 0, "checked_in": True}),  # 复查
        ]
    )
    result = make_port(transport).run(request())
    assert result.status is Status.CLAIMED
    assert "复查确认" in result.evidence[0].summary
    assert len(transport.calls) == 3


def test_claim_pending_when_confirm_negative():
    transport = FakeTransport(
        [ok({"code": 0, "checked_in": False}), ok({"code": 0}), ok({"code": 0, "checked_in": False})]
    )
    result = make_port(transport).run(request())
    assert result.status is Status.PENDING
    assert "排队/延迟" in result.evidence[0].summary


def test_retry_backoff_then_success():
    transport = FakeTransport(
        [
            ok({"code": 0, "checked_in": False}),
            ok({"code": 9074}),
            ok({"code": 9074}),
            ok({"code": 0}),
            ok({"code": 0, "checked_in": True}),
        ]
    )
    waits: list[int] = []
    result = make_port(transport, sleep=waits.append).run(request())
    assert result.status is Status.CLAIMED
    assert waits == [30, 60]  # 退避时长如实
    claim_calls = [c for c in transport.calls if c[1].endswith("/claim")]
    assert len(claim_calls) == 3


def test_retry_exhausted_reports_last_code_pending():
    transport = FakeTransport(
        [ok({"code": 0, "checked_in": False})] + [ok({"code": 9074})] * 4
    )
    result = make_port(transport, sleep=lambda s: None).run(request())
    assert result.status is Status.PENDING
    assert "退避重试" in result.evidence[0].summary


def test_business_code_translated_to_no_auth():
    transport = FakeTransport([ok({"code": 0, "checked_in": False}), ok({"code": 1001})])
    result = make_port(transport).run(request())
    assert result.status is Status.NO_AUTH
    assert result.repair_hint is not None and result.repair_hint.action_id == "dock"
    assert result.evidence[0].raw_code == "1001"


def test_business_code_failed_keeps_raw_code():
    transport = FakeTransport([ok({"code": 0, "checked_in": False}), ok({"code": 9004})])
    result = make_port(transport).run(request())
    assert result.status is Status.FAILED
    assert result.evidence[0].raw_code == "9004"


def test_unknown_code_raises_protocol_probe():
    transport = FakeTransport([ok({"code": 0, "checked_in": False}), ok({"code": 12345})])
    with pytest.raises(UnknownEngineCode):
        make_port(transport).run(request())


def test_missing_credentials_no_auth():
    class MissingVault:
        def load(self, account_id: str, kinds):
            raise CredentialMissing(f"缺 kind={kinds}")

    result = make_port(FakeTransport([]), vault=MissingVault()).run(request())
    assert result.status is Status.NO_AUTH
    assert result.repair_hint.action_id == "dock"


def test_missing_aux_credential_failed_with_dock_hint():
    """缺辅凭据（机器身份）：登录态在但头组不全 → FAILED + 重新停靠 hint（ADR-004 §4）。

    与缺主凭据（NO_AUTH，修复 = 重登）分开——重登治不了没停靠。
    """

    class MissingAuxVault:
        def load(self, account_id: str, kinds):
            if "device_dn" in kinds:
                raise CredentialMissing("缺 kind=['device_dn']")
            return [Secret("stub")]

    result = make_port(FakeTransport([]), vault=MissingAuxVault()).run(request())
    assert result.status is Status.FAILED
    assert result.repair_hint is not None
    assert result.repair_hint.action_id == "dock"
    assert "重新停靠" in result.repair_hint.reason
    assert "device_dn" in result.evidence[0].raw_code


def test_headers_shape_passes_protocol(monkeypatch):
    """Authorization 前缀 + 静态头 + 动态设备号 —— 按声明原样发出。"""
    _stub_with(monkeypatch, {"token": "T", "device_dn": "12345678"})
    transport = FakeTransport([ok({"code": 0, "checked_in": True})])
    make_port(transport).run(request())
    method, url, headers, body = transport.calls[0]
    assert headers == {
        "X-Region": "cn",
        "Authorization": "JWT T",
        "x-device-id": "12345678",
    }


def test_missing_template_field_failed(monkeypatch):
    """解锁产物缺模板字段（device_dn 没扫到等）→ FAILED + 显式证据，不静默发半套头。"""
    _stub_with(monkeypatch, {"token": "T"})  # 缺 device_dn
    transport = FakeTransport([])
    result = make_port(transport).run(request())
    assert result.status is Status.FAILED
    assert "凭据或声明事故" in result.evidence[0].summary


def test_http_500_is_failed_not_retry():
    transport = FakeTransport(
        [ok({"code": 0, "checked_in": False}), HttpResponse(status_code=500, payload={})]
    )
    result = make_port(transport).run(request())
    assert result.status is Status.FAILED
    assert "HTTP 500" in result.evidence[0].summary
