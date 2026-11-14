"""doubao_cn 适配器离线测试：PROTOCOL §3 判定表逐场景 + 引擎 PROTOCOL_CHANGED 联动。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import pytest

from butler_core.execution.ports import Capabilities, ProvisionRequest
from butler_core.execution.domain import Action, ActionKind
from butler_core.shared.results import Status, UnknownEngineCode
from butler_core.execution.domain import RunResult
from butler_connectors.cdp import CdpConnection, CdpError
from butler_connectors.doubao_cn import adapter
from butler_connectors.transport import HttpResponse, TransportError


# --- 假件（A2-02 §8：不起浏览器，离线测全链）---

@dataclass
class FakeConn:
    closed: bool = False

    def close(self) -> None:
        self.closed = True


@dataclass
class FakeEnv:
    """localenv.LocalEnv 同形状假束。"""

    version: str = "2.35.8"
    slept: list[float] = field(default_factory=list)

    def resolve_port(self) -> int:
        return 9222

    def read_version(self) -> str:
        return self.version

    def locate_exe(self):
        return None

    def process_pids(self) -> list[int]:
        return []

    def kill_pid(self, pid: int) -> None: ...

    def spawn_detached(self, exe) -> None: ...

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)


@dataclass
class FakeChannel:
    """cdp.CdpChannel 同形状假通道：探针失败可编排，点击/求值留痕。"""

    probe_errors: list[CdpError | None] = field(default_factory=list)
    pages: list[dict] = field(default_factory=list)  # 字段名避开方法 targets()（防遮蔽）
    eval_results: list[object] = field(default_factory=list)
    conn: FakeConn = field(default_factory=FakeConn)
    opened: list[str] = field(default_factory=list)
    clicks: list[tuple[int, int]] = field(default_factory=list)
    port: int = 9222  # 与真 CdpChannel 同形（PENDING 摘要引用端口）

    def probe(self) -> dict:
        err = self.probe_errors.pop(0) if self.probe_errors else None
        if err is not None:
            raise err
        return {"Browser": "Chrome/147.0.7727.149"}

    def targets(self) -> list[dict]:
        return list(self.pages)

    def attach(self, target: dict) -> FakeConn:
        return self.conn

    def open_activity(self, url: str, *, wait: float = 15.0) -> FakeConn:
        self.opened.append(url)
        return self.conn

    def cookies(self, conn, url: str = "https://www.doubao.com") -> list[dict]:
        return [
            {"name": "sessionid", "value": "s3cret-session"},
            {"name": "msToken", "value": "tok"},
            {"name": "sessionid", "value": "dup-ignored"},  # 按 name 去重先到先得
        ]

    def evaluate(self, conn, expression: str, *, wait: float = 20.0):
        if not self.eval_results:
            return None
        item = self.eval_results.pop(0)
        if isinstance(item, CdpError):
            raise item
        return item

    def click(self, conn, x: int, y: int) -> None:
        self.clicks.append((x, y))


class FakeTransport:
    """按序回放 HTTP 响应/异常；请求留痕。"""

    def __init__(self, responses: list) -> None:
        self.responses = list(responses)
        self.requests: list = []

    def __call__(self, request, *, deadline):
        self.requests.append(request)
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def ok(payload: dict) -> HttpResponse:
    return HttpResponse(status_code=200, payload=payload)


def detail_payload(checked: bool, days: int = 5, amount: int = 200) -> dict:
    """detail 判定字段路径（PROTOCOL §2）：data.tasks[campaign_code=daily_signin].daily_checkin。"""
    return {
        "code": 0,
        "data": {
            "tasks": [
                {
                    "campaign_code": "daily_signin",
                    "daily_checkin": {
                        "checked_in_today": checked,
                        "continuous_days": days,
                        "reward": {"reward_amount": amount},
                        "last_checkin_date": "2026-11-11",
                    },
                }
            ]
        },
    }


def make_port(transport=None, *, env=None, channel=None, dry_run=False):
    return adapter.butler.build_port(
        vault=object(),
        transport=transport,
        env=env if env is not None else FakeEnv(),
        channel=channel if channel is not None else FakeChannel(),
    )


def request(dry_run: bool = False) -> ProvisionRequest:
    return ProvisionRequest(
        kind=ActionKind.PROVISION_RUN,
        target="doubao_cn",
        account_id="doubao_cn:main",
        params={},
        deadline=datetime.now(UTC) + timedelta(seconds=240),
        dry_run=dry_run,
    )


# --- 判定表（PROTOCOL §3）---

def test_probe_unreachable_is_pending_with_dock_hint():
    channel = FakeChannel(probe_errors=[CdpError("refused")])
    result = make_port(channel=channel).run(request())
    assert result.status is Status.PENDING
    assert result.repair_hint is not None and result.repair_hint.action_id == "dock"
    assert "remote-debugging-port" in result.evidence[0].summary


def test_version_unreadable_is_failed():
    env = FakeEnv(version="")
    result = make_port(env=env).run(request())
    assert result.status is Status.FAILED
    assert "version_code" in result.evidence[0].summary


def test_version_bad_shape_is_failed():
    env = FakeEnv(version="147.0.7727.149")  # Chromium 内核号不是应用版本
    result = make_port(env=env).run(request())
    assert result.status is Status.FAILED


def test_checked_in_today_is_already_without_click():
    transport = FakeTransport([ok(detail_payload(checked=True))])
    channel = FakeChannel(pages=[{"type": "page", "url": "https://www.doubao.com/pc/agent-explore",
                                    "webSocketDebuggerUrl": "ws://p"}])
    result = make_port(transport, channel=channel).run(request())
    assert result.status is Status.ALREADY
    assert channel.clicks == []  # 权威判定后绝不点击
    assert "连签 5 天" in result.evidence[0].summary


def test_click_then_recheck_true_is_claimed():
    transport = FakeTransport([ok(detail_payload(False)), ok(detail_payload(True))])
    channel = FakeChannel(pages=[{"type": "page", "url": "https://www.doubao.com/x",
                                    "webSocketDebuggerUrl": "ws://p"}],
                          eval_results=[{"x": 10, "y": 20, "text": "立即签到"}])
    result = make_port(transport, channel=channel).run(request())
    assert result.status is Status.CLAIMED
    assert channel.clicks == [(10, 20)]
    assert len(transport.requests) == 2  # 点击前 detail + 复查 detail
    assert "立即签到" in result.evidence[0].summary


def test_click_then_recheck_false_is_failed():
    transport = FakeTransport([ok(detail_payload(False)), ok(detail_payload(False))])
    channel = FakeChannel(pages=[{"type": "page", "url": "https://www.doubao.com/x",
                                    "webSocketDebuggerUrl": "ws://p"}],
                          eval_results=[{"x": 1, "y": 2, "text": "签到"}])
    result = make_port(transport, channel=channel).run(request())
    assert result.status is Status.FAILED
    assert "仍未签" in result.evidence[0].summary  # 点击已送达但状态未变更（旧系统同语义）


def test_no_button_failed_with_page_text_summary():
    transport = FakeTransport([ok(detail_payload(False))])
    channel = FakeChannel(pages=[{"type": "page", "url": "https://www.doubao.com/x",
                                    "webSocketDebuggerUrl": "ws://p"}],
                          eval_results=[None, None, None, "每日签到 +200 额度（页面诊断摘要）"])
    result = make_port(transport, channel=channel).run(request())
    assert result.status is Status.FAILED
    assert "页面诊断摘要" in result.evidence[0].summary  # 找不到按钮 = 协议事故显式报


def test_detail_710012001_is_no_auth_with_dock_hint():
    transport = FakeTransport([ok({"code": 710012001, "msg": "login required"})])
    channel = FakeChannel(pages=[{"type": "page", "url": "https://www.doubao.com/x",
                                    "webSocketDebuggerUrl": "ws://p"}])
    result = make_port(transport, channel=channel).run(request())
    assert result.status is Status.NO_AUTH
    assert result.repair_hint is not None and result.repair_hint.action_id == "dock"


def test_detail_code_2_raises_unknown_engine_code():
    """code=2 刻意不在方言 → UnknownEngineCode → 用例层转 PROTOCOL_CHANGED（引擎集成见下）。"""
    transport = FakeTransport([ok({"code": 2, "msg": "campaign not found"})])
    channel = FakeChannel(pages=[{"type": "page", "url": "https://www.doubao.com/x",
                                    "webSocketDebuggerUrl": "ws://p"}])
    with pytest.raises(UnknownEngineCode) as excinfo:
        make_port(transport, channel=channel).run(request())
    assert excinfo.value.code == "2"


def test_detail_unknown_code_raises_unknown_engine_code():
    transport = FakeTransport([ok({"code": 99999})])
    channel = FakeChannel(pages=[{"type": "page", "url": "https://www.doubao.com/x",
                                    "webSocketDebuggerUrl": "ws://p"}])
    with pytest.raises(UnknownEngineCode):
        make_port(transport, channel=channel).run(request())


def test_detail_710010702_is_failed_with_hint():
    transport = FakeTransport([ok({"code": 710010702, "msg": "system error"})])
    channel = FakeChannel(pages=[{"type": "page", "url": "https://www.doubao.com/x",
                                    "webSocketDebuggerUrl": "ws://p"}])
    result = make_port(transport, channel=channel).run(request())
    assert result.status is Status.FAILED
    assert "手工点一次" in result.evidence[0].summary  # 三义码不猜


def test_detail_transport_error_is_failed():
    transport = FakeTransport([TransportError("boom")])
    channel = FakeChannel(pages=[{"type": "page", "url": "https://www.doubao.com/x",
                                    "webSocketDebuggerUrl": "ws://p"}])
    result = make_port(transport, channel=channel).run(request())
    assert result.status is Status.FAILED


def test_dry_run_skips_click():
    transport = FakeTransport([ok(detail_payload(False))])
    channel = FakeChannel(pages=[{"type": "page", "url": "https://www.doubao.com/x",
                                    "webSocketDebuggerUrl": "ws://p"}])
    result = make_port(transport, channel=channel).run(request(dry_run=True))
    assert result.status is Status.SKIPPED
    assert channel.clicks == []


def test_no_target_opens_activity_page():
    transport = FakeTransport([ok(detail_payload(True))])
    channel = FakeChannel(pages=[])  # 客户端刚启动只有内部页
    result = make_port(transport, channel=channel).run(request())
    assert channel.opened == [adapter._ACTIVITY_URL]
    assert result.status is Status.ALREADY


def test_detail_request_contract():
    """公共查询参数/头/体形状对齐 PROTOCOL §2（spike + 旧仓库 api 契约）。"""
    transport = FakeTransport([ok(detail_payload(True))])
    channel = FakeChannel(pages=[{"type": "page", "url": "https://www.doubao.com/x",
                                    "webSocketDebuggerUrl": "ws://p"}])
    make_port(transport, channel=channel).run(request())
    req = transport.requests[0]
    assert req.url.startswith("https://www.doubao.com/alice/ug/campaign/v3/detail/?")
    assert "version_code=23508" in req.url and "aid=497858" in req.url
    assert req.headers["Cookie"].startswith("sessionid=s3cret-session")  # 去重后首个生效
    assert "SamanthaDoubao/2.35.8" in req.headers["User-Agent"]
    assert req.body == {"campaign_group_code": adapter.CAMPAIGN_GROUP_CODE}


def test_evidence_never_carries_cookie_values():
    transport = FakeTransport([ok(detail_payload(False)), ok(detail_payload(True))])
    channel = FakeChannel(pages=[{"type": "page", "url": "https://www.doubao.com/x",
                                    "webSocketDebuggerUrl": "ws://p"}],
                          eval_results=[{"x": 1, "y": 2, "text": "签到"}])
    result = make_port(transport, channel=channel).run(request())
    for evidence in result.evidence:
        assert "s3cret-session" not in evidence.summary  # 脱敏：凭据明文绝不入 evidence


def test_capabilities():
    caps = make_port().capabilities()
    assert caps.dry_run is True
    assert caps.idempotency_window == "daily"


def test_engine_publishes_protocol_changed_on_code_2():
    """引擎联动：code=2 → FAILED 落账 + PROTOCOL_CHANGED 事件（用例层统一探测路径）。"""
    from butler_core.execution.usecases.execute_action import ExecuteAction, RunRequest

    @dataclass
    class FakeLedger:
        saved: list = field(default_factory=list)

        def find_by_idempotency_key(self, key):
            return None

        def save(self, run):
            self.saved.append(run)

    @dataclass
    class FakeSink:
        events: list = field(default_factory=list)

        def publish(self, event):
            self.events.append(event)

    transport = FakeTransport([ok({"code": 2})])
    channel = FakeChannel(pages=[{"type": "page", "url": "https://www.doubao.com/x",
                                    "webSocketDebuggerUrl": "ws://p"}])
    ledger, sink = FakeLedger(), FakeSink()
    usecase = ExecuteAction(ledger=ledger, sink=sink, ports=lambda action: make_port(transport, channel=channel))
    run = usecase.execute(
        RunRequest(
            action=Action(kind=ActionKind.PROVISION_RUN, target="doubao_cn"),
            account_id="doubao_cn:main",
            window="2026-11-11",
        )
    )
    assert run.result.status is Status.FAILED
    assert any(e.type.value == "PROTOCOL_CHANGED" for e in sink.events)
