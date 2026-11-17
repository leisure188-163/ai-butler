"""失败转移编排单元测试（R4-G5，ADR-012 裁决 5）：Fake 端口 + 真限流器，零 mock IO。

覆盖：成功即回 / 5xx 转移 / 401 失效凭据后转移 / 429 转移 / 与账户无关的 4xx
不转移原样回传 / 候选空 NoRoute / 未注册 platform 如实记 skipped / 缺凭据
skipped / 账户缺失 skipped / 全部失败汇总 / Meter 失败不打断 / 每尝试都入账。
pytest 无 asyncio 插件：异步场景用 asyncio.run() 包同步测试（test_limiter 先例）。
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from butler_core.accounts.domain import Account, Secret, account_identity
from butler_gateway.forwarder import (
    AllAttemptsFailedError,
    Forwarder,
    NoRouteError,
)
from butler_gateway.limiter import AccountLimiter
from butler_gateway.routing import RouteTable
from butler_gateway.upstream import (
    UpstreamCall,
    UpstreamFailure,
    UpstreamReply,
    register_upstream,
)


def _account(account_id: str, platform: str) -> Account:
    return Account(
        id=account_identity(platform, account_id.split(":", 1)[1]),
        platform=platform,
        display_name=account_id,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


class FakeAccounts:
    def __init__(self, accounts: list[Account]) -> None:
        self._by_id = {a.id: a for a in accounts}

    def get(self, account_id: str) -> Account | None:
        return self._by_id.get(account_id)


class FakePool:
    def __init__(self, *, missing: set[str] | None = None) -> None:
        self._missing = missing or set()
        self.invalidated: list[tuple[str, str]] = []

    def acquire(self, account_id: str, kind: str) -> Secret:
        if account_id in self._missing:
            from butler_core.accounts.ports import CredentialMissing

            raise CredentialMissing(f"缺凭据 kind={kind}")
        return Secret(_value="tok-" + account_id)

    def invalidate(self, account_id: str, kind: str) -> None:
        self.invalidated.append((account_id, kind))


class FakeMeter:
    def __init__(self, *, fail: bool = False) -> None:
        self.rows: list[dict] = []
        self._fail = fail

    def record(
        self,
        *,
        account_id: str,
        model: str,
        tokens_in: int = 0,
        tokens_out: int = 0,
        duration_ms: float | None = None,
    ) -> bool:
        self.rows.append(
            {"account_id": account_id, "model": model, "tokens_in": tokens_in, "tokens_out": tokens_out}
        )
        return not self._fail


class FakeUpstream:
    """脚本化上游：逐次调用按脚本回放（reply / failure）。"""

    platform = "trae_cn"
    credential_kind = "ss_aes"

    def __init__(self, script: list) -> None:
        self.script = list(script)
        self.calls: list[str] = []

    async def forward(self, account_id: str, credential: Secret, call: UpstreamCall) -> UpstreamReply:
        self.calls.append(account_id)
        assert credential.expose().startswith("tok-")
        step = self.script.pop(0)
        if isinstance(step, UpstreamFailure):
            raise step
        return step


def _ok_body() -> dict:
    return {"choices": [], "usage": {"prompt_tokens": 11, "completion_tokens": 7}}


def _parse_openai(body: dict) -> tuple[int, int]:
    usage = body.get("usage") or {}
    return (usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0))


def _make(
    script: list,
    *,
    accounts: FakeAccounts | None = None,
    meter: FakeMeter | None = None,
    pool: FakePool | None = None,
    routes: RouteTable | None = None,
) -> tuple[Forwarder, FakeMeter, FakePool]:
    register_upstream(FakeUpstream(script), replace=True)
    meter = meter or FakeMeter()
    pool = pool or FakePool()
    forwarder = Forwarder(
        routes=routes
        or RouteTable.from_dict(
            {"routes": [{"model": "m1", "accounts": ["trae_cn:main", "trae_cn:second"]}]}
        ),
        accounts=accounts
        or FakeAccounts([_account("trae_cn:main", "trae_cn"), _account("trae_cn:second", "trae_cn")]),
        pool=pool,
        limiter=AccountLimiter(),
        meter=meter,
    )
    return forwarder, meter, pool


def _run(script: list, **kw):
    forwarder, meter, pool = _make(script, **kw)

    async def scenario():
        outcome = await forwarder.forward("m1", {"model": "m1"}, usage_parser=_parse_openai)
        return outcome, meter, pool

    return asyncio.run(scenario())


# ── 干净路径 ──

def test_首候选成功_一次尝试即回_计量带usage() -> None:
    outcome, meter, _ = _run([UpstreamReply(status=200, body=_ok_body())])
    assert outcome.kind == "ok" and outcome.status == 200
    assert len(outcome.attempts) == 1 and outcome.attempts[0].outcome == "ok"
    assert meter.rows and meter.rows[0]["tokens_in"] == 11 and meter.rows[0]["tokens_out"] == 7
    assert outcome.body["usage"]["completion_tokens"] == 7  # 上游原话透传


# ── 转移语义 ──

def test_首候选5xx_转移第二候选成功() -> None:
    outcome, meter, _ = _run(
        [UpstreamReply(status=502, body={}), UpstreamReply(status=200, body=_ok_body())]
    )
    assert outcome.kind == "ok"
    assert [a.outcome for a in outcome.attempts] == ["error:status_502", "ok"]
    assert len(meter.rows) == 2  # 失败尝试也入账（0/0）


def test_首候选429_转移第二候选() -> None:
    outcome, _, _ = _run(
        [UpstreamReply(status=429, body={}), UpstreamReply(status=200, body=_ok_body())]
    )
    assert outcome.kind == "ok" and outcome.attempts[0].outcome == "error:status_429"


def test_401凭据被拒_先失效凭据再转移() -> None:
    outcome, _, pool = _run(
        [UpstreamReply(status=401, body={}), UpstreamReply(status=200, body=_ok_body())]
    )
    assert outcome.kind == "ok"
    assert pool.invalidated == [("trae_cn:main", "ss_aes")]
    assert outcome.attempts[0].outcome == "error:cred_rejected"


def test_connect失败_转移() -> None:
    outcome, _, _ = _run(
        [UpstreamFailure("connect", detail="refused"), UpstreamReply(status=200, body=_ok_body())]
    )
    assert outcome.kind == "ok" and outcome.attempts[0].outcome == "error:connect"


def test_与账户无关的400_不转移_原样回传() -> None:
    outcome, meter, _ = _run([UpstreamReply(status=400, body={"error": {"message": "bad"}})])
    assert outcome.kind == "passthrough" and outcome.status == 400
    assert outcome.body == {"error": {"message": "bad"}}
    assert len(outcome.attempts) == 1  # 不再试第二候选
    assert meter.rows and meter.rows[0]["tokens_in"] == 0  # 上游体无 usage → 0/0 如实


# ── skipped 如实记录 ──

def test_候选空_NoRoute显式错() -> None:
    forwarder, _, _ = _make([])
    with pytest.raises(NoRouteError):
        asyncio.run(forwarder.forward("unknown-model", {}, usage_parser=_parse_openai))


def test_未注册app_如实记skipped_转下一候选() -> None:
    outcome, _, _ = _run(
        [UpstreamReply(status=200, body=_ok_body())],
        accounts=FakeAccounts(
            [
                Account(
                    id=account_identity("qoder_cn", "main"),
                    platform="qoder_cn",
                    display_name="q",
                    created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                ),
                _account("trae_cn:second", "trae_cn"),
            ]
        ),
        routes=RouteTable.from_dict(
            {"routes": [{"model": "m1", "accounts": ["qoder_cn:main", "trae_cn:second"]}]}
        ),
    )
    assert outcome.kind == "ok"
    assert outcome.attempts[0].outcome == "skipped:upstream_not_ready:qoder_cn"
    assert outcome.attempts[1].outcome == "ok"


def test_缺凭据_如实记skipped() -> None:
    outcome, _, _ = _run(
        [UpstreamReply(status=200, body=_ok_body())],
        pool=FakePool(missing={"trae_cn:main"}),
    )
    assert outcome.kind == "ok"
    assert outcome.attempts[0].outcome == "skipped:credential_missing"


def test_账户缺失_如实记skipped() -> None:
    outcome, _, _ = _run(
        [UpstreamReply(status=200, body=_ok_body())],
        accounts=FakeAccounts([_account("trae_cn:second", "trae_cn")]),
    )
    assert outcome.kind == "ok"
    assert outcome.attempts[0].outcome == "skipped:account_missing"


def test_全部失败_汇总逐尝试台账() -> None:
    forwarder, _, _ = _make([UpstreamReply(status=500, body={}), UpstreamReply(status=500, body={})])
    with pytest.raises(AllAttemptsFailedError) as exc_info:
        asyncio.run(forwarder.forward("m1", {}, usage_parser=_parse_openai))
    assert [a.account_id for a in exc_info.value.attempts] == ["trae_cn:main", "trae_cn:second"]


# ── 台账语义 ──

def test_Meter失败_返回False_不打断转发() -> None:
    outcome, meter, _ = _run(
        [UpstreamReply(status=200, body=_ok_body())], meter=FakeMeter(fail=True)
    )
    assert outcome.kind == "ok"  # 转发成功不受 Meter 失败影响（台账语义）
    assert meter.rows  # 且确实尝试过入账


def test_每尝试都有duration_ms() -> None:
    outcome, _, _ = _run(
        [UpstreamReply(status=500, body={}), UpstreamReply(status=200, body=_ok_body())]
    )
    assert all(a.duration_ms is not None for a in outcome.attempts)
