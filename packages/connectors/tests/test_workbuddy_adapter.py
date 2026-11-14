"""adapter offline tests (A2-02 §8): FakeTransport replayed in order / env bundle injectable / real credentials never touched.

Redaction invariant assertions included: token/Authorization/envelope never enter RunResult text.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from butler_core.execution.ports import ProvisionRequest
from butler_core.execution.usecases.execute_action import ExecuteAction, RunRequest
from butler_core.execution.domain import Action, ActionKind
from butler_core.shared.results import Status, UnknownEngineCode, from_engine
from butler_connectors.transport import HttpResponse, TransportError
from butler_connectors.workbuddy_cn import adapter
from butler_connectors.workbuddy_cn.adapter import (
    CONN_ID,
    WorkbuddyProvisionPort,
)
from butler_connectors.workbuddy_cn.localenv import InvalidOverride, WorkbuddyEnv
from butler_connectors.workbuddy_cn.session import AuthError

_PLAIN_TOKEN = "plain-tok-123"
_PLAIN_SESSION = {
    "auth": {"accessToken": _PLAIN_TOKEN, "domain": "www.workbuddy.cn"},
    "account": {"uid": "u-1", "enterpriseId": "e-9"},
}
_STATUS_OK = {"active": True, "today_checked_in": False}
_STATUS_DONE = {
    "active": True,
    "today_checked_in": True,
    "streak_days": 3,
    "total_credits": 300,
}


def envelope_token() -> dict:
    """Fake envelope (valid shape is enough; adapter tests don't decrypt for real)."""
    inner = {
        "suite": 1,
        "keyId": "0123456789abcdef",
        "nonce": base64.b64encode(b"n" * 12).decode(),
        "authTag": base64.b64encode(b"t" * 16).decode(),
        "ciphertext": base64.b64encode(b"c" * 8).decode(),
    }
    return {
        "$wbEncrypted": 1,
        "envelope": base64.b64encode(json.dumps(inner).encode()).decode(),
    }


def write_auth(tmp_path, monkeypatch, token) -> Path:
    path = tmp_path / "wb.info"
    path.write_text(
        json.dumps({"auth": {"accessToken": token}, "account": {"uid": "u-1"}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("WORKBUDDY_AUTH_FILE", str(path))
    return path


def ok(payload, status_code=200):
    return HttpResponse(status_code=status_code, payload=payload)


@dataclass
class FakeTransport:
    responses: list
    requests: list = field(default_factory=list)

    def __call__(self, request, *, deadline):
        self.requests.append(request)
        item = self.responses.pop(0)
        if isinstance(item, TransportError):
            raise item
        return item


def make_port(transport, *, env=None):
    return WorkbuddyProvisionPort(
        transport=transport,
        env=env if env is not None else WorkbuddyEnv(locate_runtime_candidates=lambda: []),
    )


def request(**kw) -> ProvisionRequest:
    return ProvisionRequest(
        kind=ActionKind.PROVISION_RUN,
        target="workbuddy_cn",
        account_id="workbuddy_cn:main",
        params={},
        deadline=datetime.now(timezone.utc) + timedelta(seconds=60),
        **kw,
    )


# --- Credential chain (PROTOCOL §3 first four rows) ---


def test_missing_auth_file_no_auth(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKBUDDY_AUTH_FILE", str(tmp_path / "nope.info"))
    result = make_port(FakeTransport([])).run(request())
    assert result.status is Status.NO_AUTH
    assert "检查过" in result.evidence[0].summary
    assert result.repair_hint is not None and result.repair_hint.action_id == "dock"


def test_corrupt_json_invalid_format(tmp_path, monkeypatch):
    path = tmp_path / "wb.info"
    path.write_text("not json", encoding="utf-8")
    monkeypatch.setenv("WORKBUDDY_AUTH_FILE", str(path))
    result = make_port(FakeTransport([])).run(request())
    assert result.status is Status.NO_AUTH
    assert "不可读" in result.evidence[0].summary


# --- Status query decision table (PROTOCOL §3) ---


def test_status_401_expired_with_url_contract(tmp_path, monkeypatch):
    write_auth(tmp_path, monkeypatch, _PLAIN_TOKEN)
    transport = FakeTransport([ok(None, status_code=401)])
    result = make_port(transport).run(request())
    assert result.status is Status.EXPIRED
    assert result.repair_hint is not None
    req = transport.requests[0]
    assert req.url == "https://copilot.tencent.com/v2/billing/meter/checkin-activity-status"
    assert req.headers["Authorization"] == f"Bearer {_PLAIN_TOKEN}"


def test_status_403_no_auth_not_expired(tmp_path, monkeypatch):
    write_auth(tmp_path, monkeypatch, _PLAIN_TOKEN)
    result = make_port(FakeTransport([ok(None, status_code=403)])).run(request())
    assert result.status is Status.NO_AUTH
    assert "不能据此判断登录过期" in result.evidence[0].summary


def test_status_5xx_failed_raw_code(tmp_path, monkeypatch):
    write_auth(tmp_path, monkeypatch, _PLAIN_TOKEN)
    result = make_port(FakeTransport([ok(None, status_code=502)])).run(request())
    assert result.status is Status.FAILED
    assert result.evidence[0].raw_code == "502"


def test_status_transport_error_failed(tmp_path, monkeypatch):
    write_auth(tmp_path, monkeypatch, _PLAIN_TOKEN)
    result = make_port(FakeTransport([TransportError("network unreachable")])).run(request())
    assert result.status is Status.FAILED


def test_active_false_pending(tmp_path, monkeypatch):
    write_auth(tmp_path, monkeypatch, _PLAIN_TOKEN)
    result = make_port(
        FakeTransport([ok({"active": False, "activity_name": "每日签到"})])
    ).run(request())
    assert result.status is Status.PENDING
    assert "每日签到" in result.evidence[0].summary


def test_already_checked_in_single_request(tmp_path, monkeypatch):
    write_auth(tmp_path, monkeypatch, _PLAIN_TOKEN)
    transport = FakeTransport([ok(_STATUS_DONE)])
    result = make_port(transport).run(request())
    assert result.status is Status.ALREADY
    assert "连续 3 天" in result.evidence[0].summary
    assert len(transport.requests) == 1  # already signed = zero claim


def test_dry_run_skips_claim(tmp_path, monkeypatch):
    write_auth(tmp_path, monkeypatch, _PLAIN_TOKEN)
    transport = FakeTransport([ok(_STATUS_OK)])
    result = make_port(transport).run(request(dry_run=True))
    assert result.status is Status.SKIPPED
    assert len(transport.requests) == 1


# --- claim path (PROTOCOL §3 last three rows + §4 three already-signed forms) ---


def test_claimed_with_recheck_evidence(tmp_path, monkeypatch):
    write_auth(tmp_path, monkeypatch, _PLAIN_TOKEN)
    transport = FakeTransport([ok(_STATUS_OK), ok({"credit": 100}), ok(_STATUS_DONE)])
    result = make_port(transport).run(request())
    assert result.status is Status.CLAIMED
    assert "成功领取 100 积分" in result.evidence[0].summary
    assert "连续 3 天" in result.evidence[0].summary
    assert len(transport.requests) == 3
    assert transport.requests[1].url.endswith("/v2/billing/meter/daily-checkin")


def test_claimed_recheck_fails_falls_back(tmp_path, monkeypatch):
    write_auth(tmp_path, monkeypatch, _PLAIN_TOKEN)
    first = {"active": True, "today_checked_in": False, "streak_days": 3}
    transport = FakeTransport([ok(first), ok({"credit": 100}), TransportError("抖动")])
    result = make_port(transport).run(request())
    assert result.status is Status.CLAIMED  # recheck failure does not degrade result
    assert "连续 3 天" in result.evidence[0].summary


def test_claim_transport_error_failed(tmp_path, monkeypatch):
    write_auth(tmp_path, monkeypatch, _PLAIN_TOKEN)
    result = make_port(FakeTransport([ok(_STATUS_OK), TransportError("boom")])).run(request())
    assert result.status is Status.FAILED


def test_claim_null_2xx_is_already(tmp_path, monkeypatch):
    write_auth(tmp_path, monkeypatch, _PLAIN_TOKEN)
    transport = FakeTransport([ok(_STATUS_OK), ok(None), ok(_STATUS_DONE)])
    result = make_port(transport).run(request())
    assert result.status is Status.ALREADY
    assert "服务端判定已领取" in result.evidence[0].summary


def test_claim_null_5xx_not_already(tmp_path, monkeypatch):
    """Divergence from old oracle: old is_already(None) unconditionally True, 5xx empty body would misjudge → add 2xx guard."""
    write_auth(tmp_path, monkeypatch, _PLAIN_TOKEN)
    result = make_port(
        FakeTransport([ok(_STATUS_OK), ok(None, status_code=502)])
    ).run(request())
    assert result.status is Status.FAILED
    assert "未识别的领取返回" in result.evidence[0].summary


def test_claim_success_envelope_code0_rechecks(tmp_path, monkeypatch):
    """业务成功信封（code=0 msg=OK，2026-11-14 mac 真机取证，PROTOCOL §4 补）：
    无 credit 字段 → 复查账本确认，不误判 FAILED。"""
    write_auth(tmp_path, monkeypatch, _PLAIN_TOKEN)
    transport = FakeTransport([ok(_STATUS_OK), ok({"code": 0, "msg": "OK"}), ok(_STATUS_DONE)])
    result = make_port(transport).run(request())
    assert result.status is Status.ALREADY
    assert "领取请求受理" in result.evidence[0].summary
    assert "连续 3 天" in result.evidence[0].summary
    assert len(transport.requests) == 3


def test_claim_success_envelope_5xx_not_success(tmp_path, monkeypatch):
    """code=0 但非 2xx：不视为成功信封 → 未知码显式上抛（红线 5，用例层转 FAILED）。"""
    from butler_core.shared.results import UnknownEngineCode

    write_auth(tmp_path, monkeypatch, _PLAIN_TOKEN)
    with pytest.raises(UnknownEngineCode):
        make_port(
            FakeTransport([ok(_STATUS_OK), ok({"code": 0, "msg": "OK"}, status_code=502)])
        ).run(request())


def test_claim_400_10001_already(tmp_path, monkeypatch):
    write_auth(tmp_path, monkeypatch, _PLAIN_TOKEN)
    transport = FakeTransport(
        [ok(_STATUS_OK), ok({"code": 10001, "msg": "已签过"}, status_code=400), ok(_STATUS_DONE)]
    )
    result = make_port(transport).run(request())
    assert result.status is Status.ALREADY
    assert "服务端判定已领取" in result.evidence[0].summary


def test_claim_msg_yiqian_already(tmp_path, monkeypatch):
    write_auth(tmp_path, monkeypatch, _PLAIN_TOKEN)
    transport = FakeTransport([ok(_STATUS_OK), ok({"msg": "今日已签过"}), ok(_STATUS_DONE)])
    result = make_port(transport).run(request())
    assert result.status is Status.ALREADY


def test_claim_string_code_uses_dialect(tmp_path, monkeypatch):
    write_auth(tmp_path, monkeypatch, _PLAIN_TOKEN)
    transport = FakeTransport([ok(_STATUS_OK), ok({"code": "10001"}), ok(_STATUS_DONE)])
    result = make_port(transport).run(request())
    assert result.status is Status.ALREADY  # string code goes through dialect {"10001": ALREADY}


def test_claim_unknown_code_raises(tmp_path, monkeypatch):
    write_auth(tmp_path, monkeypatch, _PLAIN_TOKEN)
    with pytest.raises(UnknownEngineCode) as exc:
        make_port(FakeTransport([ok(_STATUS_OK), ok({"code": 50001, "msg": "??"})])).run(
            request()
        )
    assert exc.value.code == "50001"
    assert exc.value.dialect == "workbuddy_cn"


def test_claim_msg_only_failed(tmp_path, monkeypatch):
    write_auth(tmp_path, monkeypatch, _PLAIN_TOKEN)
    result = make_port(
        FakeTransport([ok(_STATUS_OK), ok({"msg": "系统繁忙"}, status_code=400)])
    ).run(request())
    assert result.status is Status.FAILED
    assert "系统繁忙" in result.evidence[0].summary


def test_claim_unrecognized_payload_failed(tmp_path, monkeypatch):
    write_auth(tmp_path, monkeypatch, _PLAIN_TOKEN)
    result = make_port(FakeTransport([ok(_STATUS_OK), ok([1, 2, 3])])).run(request())
    assert result.status is Status.FAILED
    assert "未识别的领取返回" in result.evidence[0].summary


# --- Decryption chain integration (mock decrypt_envelope; real chain covered by session tests + live machine) ---


def test_envelope_decrypt_builds_bearer(tmp_path, monkeypatch):
    write_auth(tmp_path, monkeypatch, envelope_token())
    monkeypatch.setattr(
        adapter,
        "decrypt_envelope",
        lambda envelope, *, candidates, timeout: "plain-tok-999",
    )
    transport = FakeTransport([ok(_STATUS_DONE)])
    result = make_port(transport).run(request())
    assert result.status is Status.ALREADY
    assert transport.requests[0].headers["Authorization"] == "Bearer plain-tok-999"


def test_key_mismatch_maps_no_auth(tmp_path, monkeypatch):
    write_auth(tmp_path, monkeypatch, envelope_token())

    def mismatch(envelope, *, candidates, timeout):
        raise AuthError("KEY_MISMATCH")

    monkeypatch.setattr(adapter, "decrypt_envelope", mismatch)
    result = make_port(FakeTransport([])).run(request())
    assert result.status is Status.NO_AUTH
    assert result.repair_hint is not None
    assert "WORKBUDDY_EXE" in result.repair_hint.reason


def test_invalid_runtime_override_no_auth(tmp_path, monkeypatch):
    write_auth(tmp_path, monkeypatch, envelope_token())

    def bad_override():
        raise InvalidOverride("WORKBUDDY_EXE 不是可用的可执行文件")

    result = make_port(
        FakeTransport([]),
        env=WorkbuddyEnv(locate_runtime_candidates=bad_override),
    ).run(request())
    assert result.status is Status.NO_AUTH
    assert "WORKBUDDY_EXE" in result.evidence[0].summary


def test_token_never_in_result(tmp_path, monkeypatch):
    write_auth(tmp_path, monkeypatch, envelope_token())
    monkeypatch.setattr(
        adapter,
        "decrypt_envelope",
        lambda envelope, *, candidates, timeout: _PLAIN_TOKEN,
    )
    result = make_port(FakeTransport([ok(_STATUS_DONE)])).run(request())
    text = repr(result)
    assert _PLAIN_TOKEN not in text and "Bearer" not in text
    assert "$wbEncrypted" not in text


def test_session_endpoint_overrides_base(tmp_path, monkeypatch):
    path = tmp_path / "wb.info"
    path.write_text(
        json.dumps(
            {
                "auth": {"accessToken": _PLAIN_TOKEN, "endpoint": "https://alt.example.com"},
                "account": {"uid": "u-1"},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("WORKBUDDY_AUTH_FILE", str(path))
    transport = FakeTransport([ok(None, status_code=401)])
    make_port(transport).run(request())
    assert transport.requests[0].url.startswith("https://alt.example.com/v2/billing/meter/")


# --- Capability / dialect / use-case integration ---


def test_capabilities_declared():
    caps = make_port(FakeTransport([])).capabilities()
    assert caps.dry_run is True and caps.multi_account is False
    assert caps.idempotency_window == "daily"


def test_dialect_single_entry():
    assert from_engine("10001", dialect=CONN_ID) is Status.ALREADY
    with pytest.raises(UnknownEngineCode):
        from_engine("10002", dialect=CONN_ID)


def test_execute_action_unknown_code_becomes_failed_with_event(tmp_path, monkeypatch):
    """Use case integration (ADR-004): UnknownEngineCode → FAILED + PROTOCOL_CHANGED event."""
    write_auth(tmp_path, monkeypatch, _PLAIN_TOKEN)
    saved: list = []
    events: list = []

    class FakeLedger:
        def find_by_idempotency_key(self, key):
            return None

        def save(self, run):
            saved.append(run)

    class FakeSink:
        def publish(self, event):
            events.append(event)

    port = make_port(FakeTransport([ok(_STATUS_OK), ok({"code": 50001})]))
    usecase = ExecuteAction(ledger=FakeLedger(), sink=FakeSink(), ports=lambda action: port)
    run = usecase.execute(
        RunRequest(
            action=Action(kind=ActionKind.PROVISION_RUN, target="workbuddy_cn"),
            account_id="workbuddy_cn:main",
            window="2026-11-11",
        )
    )
    assert run.result is not None and run.result.status is Status.FAILED
    assert run.result.evidence[0].raw_code == "50001"
    assert any(e.type.value == "PROTOCOL_CHANGED" for e in events)  # 用例层先 RUN_FINISHED 后探测事件
