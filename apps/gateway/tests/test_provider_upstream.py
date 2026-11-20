"""用户接入源上游（ADR-033 后续）：URL/鉴权/错误映射 + 网关动态解析。"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import httpx
import pytest

from butler_core.accounts.domain import Account, Secret, account_identity
from butler_core.platforms.domain import PlatformEntry
from butler_gateway.forwarder import AllAttemptsFailedError, Forwarder
from butler_gateway.limiter import AccountLimiter
from butler_gateway.provider_upstream import (
    ProviderUpstream,
    provider_headers,
    provider_url,
    supported_protocols,
)
from butler_gateway.routing import RouteTable
from butler_gateway.upstream import UpstreamCall, UpstreamFailure


def _provider(**over) -> PlatformEntry:
    base = dict(
        platform_code="my_relay",
        platform_name="我的中转",
        created_at=datetime(2026, 11, 20, tzinfo=UTC),
        platform_kind="relay",
        base_url="https://relay.example.com/v1",
        protocol="openai",
        models=("gpt-4o-mini",),
        credential_kinds=("api_key",),
        origin="user",
        capabilities=(),
        schedule_times=(),
    )
    base.update(over)
    return PlatformEntry(**base)


def test_provider_url_拼接与完整路径() -> None:
    assert provider_url("https://relay.example.com/v1", "openai") == (
        "https://relay.example.com/v1/chat/completions"
    )
    assert provider_url("https://relay.example.com", "openai") == (
        "https://relay.example.com/v1/chat/completions"
    )
    assert provider_url("https://relay.example.com/v1/chat/completions", "openai") == (
        "https://relay.example.com/v1/chat/completions"
    )
    assert provider_url("https://api.anthropic.com/", "anthropic") == (
        "https://api.anthropic.com/v1/messages"
    )
    assert provider_url("https://proxy.example.com/v1/messages", "anthropic") == (
        "https://proxy.example.com/v1/messages"
    )
    with pytest.raises(ValueError, match="不支持的接入源协议"):
        provider_url("https://x.example.com", "gemini")


def test_provider_headers_按协议() -> None:
    assert provider_headers("openai", Secret("sk-1")) == {"Authorization": "Bearer sk-1"}
    headers = provider_headers("anthropic", Secret("ak-1"))
    assert headers["x-api-key"] == "ak-1"
    assert headers["anthropic-version"] == "2023-06-01"
    assert supported_protocols() == ("openai", "anthropic")


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_openai_直通_地址鉴权与响应原话() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = request.read().decode()
        return httpx.Response(
            200,
            json={"choices": [], "usage": {"prompt_tokens": 3, "completion_tokens": 2}},
        )

    async def scenario():
        client = _client(handler)
        try:
            return await ProviderUpstream(_provider(), client).forward(
                "my_relay:key1", Secret("sk-1"),
                UpstreamCall(payload={"model": "gpt-4o-mini"}, model="gpt-4o-mini"),
            )
        finally:
            await client.aclose()

    reply = asyncio.run(scenario())
    assert reply.status == 200 and reply.body["usage"]["prompt_tokens"] == 3
    assert seen["url"] == "https://relay.example.com/v1/chat/completions"
    assert seen["auth"] == "Bearer sk-1"
    assert '"model":"gpt-4o-mini"' in seen["body"].replace(" ", "")


def test_anthropic_直通_用x_api_key与messages路径() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["key"] = request.headers.get("x-api-key")
        return httpx.Response(200, json={"content": [], "usage": {"input_tokens": 1, "output_tokens": 2}})

    async def scenario():
        client = _client(handler)
        try:
            return await ProviderUpstream(
                _provider(platform_code="my_anthropic", protocol="anthropic",
                          base_url="https://api.anthropic.com"),
                client,
            ).forward("my_anthropic:key1", Secret("ak-1"),
                      UpstreamCall(payload={"model": "claude"}, model="claude", protocol="anthropic"))
        finally:
            await client.aclose()

    reply = asyncio.run(scenario())
    assert reply.status == 200
    assert seen["url"] == "https://api.anthropic.com/v1/messages"
    assert seen["key"] == "ak-1"


def test_上游401原样回传由forwarder失效凭据() -> None:
    async def scenario():
        client = _client(lambda request: httpx.Response(401, json={"error": "bad key"}))
        try:
            return await ProviderUpstream(_provider(), client).forward(
                "my_relay:key1", Secret("sk-bad"), UpstreamCall(payload={}, model="m")
            )
        finally:
            await client.aclose()

    reply = asyncio.run(scenario())
    assert reply.status == 401


def test_连接失败与超时映射为账户级失败() -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    async def scenario():
        client = _client(boom)
        try:
            await ProviderUpstream(_provider(), client).forward(
                "my_relay:key1", Secret("sk-1"), UpstreamCall(payload={}, model="m")
            )
        finally:
            await client.aclose()

    with pytest.raises(UpstreamFailure) as exc:
        asyncio.run(scenario())
    assert exc.value.outcome == "connect"


def test_2xx非JSON记为形状失败而不是空成功() -> None:
    async def scenario():
        client = _client(lambda request: httpx.Response(200, text="not json"))
        try:
            await ProviderUpstream(_provider(), client).forward(
                "my_relay:key1", Secret("sk-1"), UpstreamCall(payload={}, model="m")
            )
        finally:
            await client.aclose()

    with pytest.raises(UpstreamFailure) as exc:
        asyncio.run(scenario())
    assert exc.value.outcome == "status_5xx"


# ── forwarder 动态解析 ──


def _account(platform: str = "my_relay") -> Account:
    return Account(
        id=account_identity(platform, "key1"),
        platform_code=platform,
        account_name="key1",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


class FakeAccounts:
    def __init__(self, account: Account | None) -> None:
        self._account = account

    def get(self, account_id: str) -> Account | None:
        return self._account if self._account and self._account.id == account_id else None


class FakePlatforms:
    def __init__(self, entry: PlatformEntry | None) -> None:
        self._entry = entry

    def get(self, code: str) -> PlatformEntry | None:
        return self._entry if self._entry and self._entry.platform_code == code else None


class FakePool:
    def __init__(self) -> None:
        self.invalidated: list[tuple[str, str]] = []
        self.kinds: list[str] = []

    def acquire(self, account_id: str, kind: str) -> Secret:
        self.kinds.append(kind)
        return Secret("sk-1")

    def invalidate(self, account_id: str, kind: str) -> None:
        self.invalidated.append((account_id, kind))


class FakeMeter:
    def __init__(self) -> None:
        self.rows: list[dict] = []

    def record(self, *, account_id: str, model: str, tokens_in: int = 0,
               tokens_out: int = 0, duration_ms: float | None = None) -> bool:
        self.rows.append({"account_id": account_id, "tokens_in": tokens_in, "tokens_out": tokens_out})
        return True


class FakeProvider:
    def __init__(self, entry: PlatformEntry) -> None:
        self._entry = entry

    @property
    def credential_kind(self) -> str:
        return self._entry.credential_kinds[0] if self._entry.credential_kinds else "api_key"

    async def forward(self, account_id, credential, call):
        from butler_gateway.upstream import UpstreamReply

        assert call.protocol == self._entry.protocol
        return UpstreamReply(status=200, body={"usage": {"prompt_tokens": 1, "completion_tokens": 1}})


def _forwarder(entry: PlatformEntry | None, *, account: Account | None = None,
               with_platforms: bool = True) -> tuple[Forwarder, FakePool]:
    pool = FakePool()
    forwarder = Forwarder(
        routes=RouteTable.from_dict({"routes": [{"model": "m1", "accounts": [entry.platform_code + ":key1"] if entry else ["ghost:main"]}]}),
        accounts=FakeAccounts(account if account is not None else (_account(entry.platform_code) if entry else None)),
        pool=pool,
        limiter=AccountLimiter(),
        meter=FakeMeter(),
        platforms=FakePlatforms(entry) if with_platforms else None,
        provider_factory=FakeProvider if entry else None,
    )
    return forwarder, pool


def _parse(body: dict) -> tuple[int, int]:
    usage = body.get("usage") or {}
    return (usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0))


def test_forwarder_用户接入源同协议直通() -> None:
    entry = _provider()
    forwarder, pool = _forwarder(entry)

    async def scenario():
        return await forwarder.forward("m1", {"model": "gpt-4o-mini"},
                                       usage_parser=_parse, protocol="openai")

    outcome = asyncio.run(scenario())
    assert outcome.kind == "ok"
    assert pool.kinds == ["api_key"]  # 用接入源申报的第一种凭据


def test_forwarder_协议不匹配与gemini显式跳过() -> None:
    for entry, protocol, reason in (
        (_provider(platform_code="my_anthropic", protocol="anthropic"), "openai",
         "provider_protocol_mismatch"),
        (_provider(platform_code="my_gemini", protocol="gemini"), "openai",
         "provider_protocol_unsupported"),
        (_provider(platform_code="my_cookie", credential_kinds=("cookie",)), "openai",
         "provider_credential_unsupported"),
    ):
        forwarder, _ = _forwarder(entry, account=_account(entry.platform_code))

        async def scenario():
            return await forwarder.forward("m1", {"model": "m"}, usage_parser=_parse, protocol=protocol)

        with pytest.raises(AllAttemptsFailedError) as exc:
            asyncio.run(scenario())
        assert reason in exc.value.attempts[0].outcome


def test_forwarder_无平台册时保持旧skipped语义() -> None:
    forwarder, _ = _forwarder(_provider(), with_platforms=False)

    async def scenario():
        return await forwarder.forward("m1", {"model": "m"}, usage_parser=_parse, protocol="openai")

    with pytest.raises(AllAttemptsFailedError) as exc:
        asyncio.run(scenario())
    assert exc.value.attempts[0].outcome.startswith("skipped:upstream_not_ready")


def test_gateway端到端_用户接入源直通(monkeypatch, tmp_path) -> None:
    """App 装配闭环：平台册 → 账户/密钥 → 路由文件 → 真请求打到接入源。"""
    import json

    from fastapi.testclient import TestClient

    from butler_engine.bridge import build_engine
    from butler_gateway.app import create_app

    db = tmp_path / "butler.db"
    kit = build_engine(db)
    kit.create_platform.execute(
        "my_relay", "我的中转", kind="relay",
        base_url="https://relay.example.com/v1", protocol="openai",
        credential_kinds=("api_key",),
    )
    kit.create_account.execute(
        "my_relay", "key1", "我的中转 · 主 key",
        kind="api_key", secret=Secret("sk-live"), label="主 key",
    )
    kit.close()

    routes = tmp_path / "gateway-routes.json"
    routes.write_text(
        json.dumps({"routes": [{"model": "m1", "accounts": ["my_relay:key1"]}]}),
        encoding="utf-8",
    )
    monkeypatch.setenv("BUTLER_GATEWAY_KEY_FILE", str(tmp_path / "gateway-auth-key"))
    monkeypatch.setenv("BUTLER_GATEWAY_ROUTES_FILE", str(routes))
    monkeypatch.setenv("BUTLER_SERVER_URL", "http://control.test")
    monkeypatch.setenv("BUTLER_DB", str(db))

    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "control.test":
            return httpx.Response(200, json={"status": "ok"})
        seen["host"] = request.url.host
        seen["path"] = request.url.path
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(
            200, json={"choices": [], "usage": {"prompt_tokens": 5, "completion_tokens": 2}}
        )

    import butler_gateway.app as gw_app

    monkeypatch.setattr(gw_app, "_transport_factory", lambda: httpx.MockTransport(handler))
    app = create_app()
    with TestClient(app) as client:
        resp = client.post(
            "/v1/chat/completions",
            headers={"Authorization": f"Bearer {app.state.gateway_key}"},
            json={"model": "m1", "messages": [{"role": "user", "content": "hi"}]},
        )
    assert resp.status_code == 200, resp.text
    assert seen == {
        "host": "relay.example.com",
        "path": "/v1/chat/completions",
        "auth": "Bearer sk-live",
    }
    assert resp.json()["usage"]["prompt_tokens"] == 5
