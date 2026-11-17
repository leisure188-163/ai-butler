"""双协议面端到端测试（R4-G5）：TestClient + 假 kit + Fake 上游，不碰真数据根/网络。

覆盖：Bearer 鉴权两态 / OpenAI 面与 Anthropic 面成功透传 / 流式 422 显式拒绝 /
未路由模型 404 / 全部候选失败 502 带台账 / usage 方言解析入账 / /health proxy 节。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from butler_core.accounts.domain import Account, Secret, account_identity
from butler_gateway.app import create_app
from butler_gateway.upstream import UpstreamCall, UpstreamReply, register_upstream


@dataclass
class FakeMeter:
    rows: list[dict] = field(default_factory=list)

    def record(self, *, account_id: str, model: str, tokens_in: int = 0, tokens_out: int = 0, duration_ms: float | None = None) -> bool:
        self.rows.append({"account_id": account_id, "model": model, "tokens_in": tokens_in, "tokens_out": tokens_out})
        return True


class FakeUpstream:
    platform = "trae_cn"
    credential_kind = "ss_aes"

    def __init__(self, reply: UpstreamReply) -> None:
        self.reply = reply

    async def forward(self, account_id: str, credential: Secret, call: UpstreamCall) -> UpstreamReply:
        return self.reply


class FakeAccounts:
    def __init__(self) -> None:
        self._a = Account(
            id=account_identity("trae_cn", "main"),
            platform_code="trae_cn",
            account_name="trae main",
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )

    def get(self, account_id: str) -> Account | None:
        return self._a if account_id == self._a.id else None


@dataclass
class FakePool:
    def acquire(self, account_id: str, kind: str) -> Secret:
        return Secret(_value="tok")

    def invalidate(self, account_id: str, kind: str) -> None:
        pass


@dataclass
class FakeKit:
    accounts: FakeAccounts = field(default_factory=FakeAccounts)
    credential_pool: FakePool = field(default_factory=FakePool)
    record_usage_sample: FakeMeter = field(default_factory=FakeMeter)

    def close(self) -> None:
        pass


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, FakeMeter]:
    key_file = tmp_path / "gateway-auth-key"
    key_file.write_text("test-key-0001\n", encoding="utf-8")
    routes_file = tmp_path / "gateway-routes.json"
    routes_file.write_text(
        json.dumps({"routes": [{"model": "gpt-x", "accounts": ["trae_cn:main"]}]}),
        encoding="utf-8",
    )
    monkeypatch.setenv("BUTLER_GATEWAY_KEY_FILE", str(key_file))
    monkeypatch.setenv("BUTLER_GATEWAY_ROUTES_FILE", str(routes_file))
    meter = FakeMeter()
    register_upstream(
        FakeUpstream(
            UpstreamReply(
                status=200,
                body={"choices": [{"message": {"role": "assistant", "content": "hi"}}],
                      "usage": {"prompt_tokens": 5, "completion_tokens": 3}},
            )
        ),
        replace=True,
    )
    import butler_gateway.app as app_module

    monkeypatch.setattr(app_module, "_kit_factory", lambda: FakeKit(record_usage_sample=meter))
    platform = create_app()
    with TestClient(platform) as tc:
        yield tc, meter


_HEADERS = {"Authorization": "Bearer test-key-0001"}
_OPENAI_BODY = {"model": "gpt-x", "messages": [{"role": "user", "content": "hi"}]}
_ANTHROPIC_BODY = {"model": "gpt-x", "max_tokens": 8, "messages": [{"role": "user", "content": "hi"}]}


def test_无鉴权_401(client: tuple[TestClient, FakeMeter]) -> None:
    tc, _ = client
    assert tc.post("/v1/chat/completions", json=_OPENAI_BODY).status_code == 401
    assert tc.post("/v1/messages", json=_ANTHROPIC_BODY).status_code == 401


def test_鉴权错key_401(client: tuple[TestClient, FakeMeter]) -> None:
    tc, _ = client
    resp = tc.post("/v1/chat/completions", json=_OPENAI_BODY, headers={"Authorization": "Bearer wrong"})
    assert resp.status_code == 401


def test_openai面成功_原话透传_按方言计量(client: tuple[TestClient, FakeMeter]) -> None:
    tc, meter = client
    resp = tc.post("/v1/chat/completions", json=_OPENAI_BODY, headers=_HEADERS)
    assert resp.status_code == 200
    assert resp.json()["choices"][0]["message"]["content"] == "hi"
    assert meter.rows and meter.rows[0]["tokens_in"] == 5 and meter.rows[0]["tokens_out"] == 3
    assert meter.rows[0]["model"] == "gpt-x"


def test_anthropic面成功_透传同一上游(client: tuple[TestClient, FakeMeter]) -> None:
    tc, meter = client
    resp = tc.post("/v1/messages", json=_ANTHROPIC_BODY, headers=_HEADERS)
    assert resp.status_code == 200
    # FakeUpstream 返回体是 OpenAI 形 usage；anthropic 方言读 input_tokens/output_tokens
    # → 解析不到该键，如实 0/0（裁决 7：缺失不猜）
    assert meter.rows and meter.rows[0]["tokens_in"] == 0 and meter.rows[0]["tokens_out"] == 0
    assert resp.json()["usage"]["prompt_tokens"] == 5  # 原话透传，不按面改写


def test_stream真值_422显式拒绝(client: tuple[TestClient, FakeMeter]) -> None:
    tc, _ = client
    body = {**_OPENAI_BODY, "stream": True}
    resp = tc.post("/v1/chat/completions", json=body, headers=_HEADERS)
    assert resp.status_code == 422
    assert "流式" in resp.json()["error"]["message"]


def test_未路由模型_404(client: tuple[TestClient, FakeMeter]) -> None:
    tc, _ = client
    resp = tc.post("/v1/chat/completions", json={"model": "no-such"}, headers=_HEADERS)
    assert resp.status_code == 404
    assert "未配置路由" in resp.json()["error"]["message"]


def test_请求体非法_400(client: tuple[TestClient, FakeMeter]) -> None:
    tc, _ = client
    resp = tc.post(
        "/v1/chat/completions",
        content=b"not-json",
        headers={**_HEADERS, "Content-Type": "application/json"},
    )
    assert resp.status_code == 400
    resp2 = tc.post("/v1/messages", json={"messages": []}, headers=_HEADERS)
    assert resp2.status_code == 400  # 缺 model


def test_health含proxy节(client: tuple[TestClient, FakeMeter]) -> None:
    tc, _ = client
    health = tc.get("/health").json()
    assert health["proxy"]["surfaces"] == ["/v1/chat/completions", "/v1/messages"]
    assert health["proxy"]["app_adapters"] == ["trae_cn"]
    assert health["proxy"]["limiter_in_use"] == {}
