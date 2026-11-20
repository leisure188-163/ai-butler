"""doubao_cn 适配器离线测试：PROTOCOL §3 判定表逐场景 + 引擎 PROTOCOL_CHANGED 联动。

detail 已改活动页上下文 fetch（ADR-017，零裸请求）：假通道按序回放
detail fetch 结果（detail_results）与页面求值结果（eval_results），
并留痕 fetch 表达式（detail_calls）供契约测试断言「零手拼头/凭据」。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import pytest

from butler_core.execution.ports import Capabilities, ProvisionRequest
from butler_core.execution.domain import Action, ActionKind
from butler_core.shared.results import Status, UnknownEngineCode
from butler_core.execution.domain import RunResult
from butler_connectors.cdp import CdpError
from butler_connectors.doubao_cn import adapter


# --- 假件（A2-02 §8：不起浏览器，离线测全链）---

@dataclass
class FakeConn:
    closed: bool = False
    calls: list = field(default_factory=list)

    def call(self, method, params=None, *, wait=8.0):
        self.calls.append(method)
        return {}

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
    """cdp.CdpChannel 同形状假通道：探针失败可编排，detail fetch/求值留痕。"""

    probe_errors: list[CdpError | None] = field(default_factory=list)
    pages: list[dict] = field(default_factory=list)  # 字段名避开方法 targets()（防遮蔽）
    detail_results: list[object] = field(default_factory=list)  # detail fetch 按序回放
    eval_results: list[object] = field(default_factory=list)  # 找按钮/页面文本按序回放
    detail_calls: list[str] = field(default_factory=list)  # fetch JS 表达式留痕（契约测试）
    detail_awaits: list[bool] = field(default_factory=list)  # awaitPromise 语义留痕
    conn: FakeConn = field(default_factory=FakeConn)
    opened: list[str] = field(default_factory=list)
    clicks: list[tuple[int, int]] = field(default_factory=list)
    port: int = 9222  # 与真 CdpChannel 同形（PENDING 摘要引用端口）
    identity: dict | None = field(
        default_factory=lambda: {"sec_uid": MAIN_SEC_UID, "nickname": "逍遥酒鬼"}
    )  # None = 主窗口不可达（读身份 PENDING 场景）

    def probe(self) -> dict:
        err = self.probe_errors.pop(0) if self.probe_errors else None
        if err is not None:
            raise err
        return {"Browser": "Chrome/147.0.7727.149"}

    def targets(self) -> list[dict]:
        pages = list(self.pages)
        if self.identity is not None:
            pages.insert(0, {"type": "page", "url": "doubao://doubao-chat/chat",
                             "webSocketDebuggerUrl": "ws://chat"})
        return pages

    def attach(self, target: dict) -> FakeConn:
        return self.conn

    def open_activity(self, url: str, *, wait: float = 15.0) -> FakeConn:
        self.opened.append(url)
        return self.conn

    def evaluate(self, conn, expression: str, *, wait: float = 20.0,
                 await_promise: bool = False):
        if "for_ban_appeal_sec_user_id" in expression:  # 活跃身份查询（identity.py）
            return dict(self.identity) if self.identity else None
        if "/alice/ug/campaign/v3/detail/" in expression:  # detail 页面 fetch（ADR-017）
            self.detail_calls.append(expression)
            self.detail_awaits.append(await_promise)
            return self._next(self.detail_results)
        return self._next(self.eval_results)

    @staticmethod
    def _next(queue: list):
        if not queue:
            return None  # 队列耗尽 = 页面没可取内容（chip 定位失败等场景按 None 走）
        item = queue.pop(0)
        if isinstance(item, CdpError):
            raise item
        return item

    def click(self, conn, x: int, y: int) -> None:
        self.clicks.append((x, y))


MAIN_SEC_UID = "MS4wTESTMAIN000000"  # main 基线假身份
B_SEC_UID = "MS4wTESTBBBB000000"  # 第二账户假身份

from butler_connectors.doubao_cn import identity as doubao_identity  # noqa: E402


@pytest.fixture(autouse=True)
def _main_identity_baseline(tmp_path, monkeypatch):
    """每个测试独立身份基线文件：main 基线预置 MAIN_SEC_UID（run 匹配的前提）。"""
    path = tmp_path / "doubao_identity.json"
    monkeypatch.setenv("DOUBAO_IDENTITY_PATH", str(path))
    monkeypatch.setenv("DOUBAO_REQUEST_CAPTURE", "0")  # 默认测试不装页面旁路
    doubao_identity.save_main_baseline(
        doubao_identity.ActiveIdentity(sec_uid=MAIN_SEC_UID, nickname="逍遥酒鬼")
    )
    yield path


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


def make_port(*, env=None, channel=None):
    return adapter.butler.build_port(
        vault=object(),
        env=env if env is not None else FakeEnv(),
        channel=channel if channel is not None else FakeChannel(),
    )


def request(dry_run: bool = False) -> ProvisionRequest:
    return ProvisionRequest(
        kind=ActionKind.PROVISION_RUN,
        target="doubao_cn",
        account_id="doubao_cn:逍遥酒鬼",
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
    channel = FakeChannel(
        pages=[{"type": "page", "url": "https://www.doubao.com/pc/agent-explore",
                "webSocketDebuggerUrl": "ws://p"}],
        detail_results=[detail_payload(checked=True)],
    )
    result = make_port(channel=channel).run(request())
    assert result.status is Status.ALREADY
    assert channel.clicks == []  # 权威判定后绝不点击
    assert "连签 5 天" in result.evidence[0].summary


def test_click_then_recheck_true_is_claimed():
    channel = FakeChannel(
        pages=[{"type": "page", "url": "https://www.doubao.com/x",
                "webSocketDebuggerUrl": "ws://p"}],
        detail_results=[detail_payload(False), detail_payload(True)],
        eval_results=[{"x": 10, "y": 20, "text": "立即签到"}],
    )
    result = make_port(channel=channel).run(request())
    assert result.status is Status.CLAIMED
    assert channel.clicks == [(10, 20)]
    assert len(channel.detail_calls) == 2  # 点击前 detail + 复查 detail
    assert "立即签到" in result.evidence[0].summary


def test_click_then_recheck_false_is_failed(tmp_path, monkeypatch):
    monkeypatch.setenv("DOUBAO_FAILURE_DIR", str(tmp_path))
    channel = FakeChannel(
        pages=[{"type": "page", "url": "https://www.doubao.com/x",
                "webSocketDebuggerUrl": "ws://p"}],
        detail_results=[detail_payload(False)] + [detail_payload(False)] * len(adapter._RECHECK_DELAYS),
        eval_results=[{"x": 1, "y": 2, "text": "签到"}],
    )
    result = make_port(channel=channel).run(request())
    assert result.status is Status.FAILED
    # 点击已送达但退避复查 3 次仍未签（PROTOCOL §3 FAILED 行，2026-11-16 语义）
    assert f"复查 {len(adapter._RECHECK_DELAYS)} 次仍未签" in result.evidence[0].summary
    # +1 = 失败留证时再读一次 detail（2026-11-19 evidence.record_failure）
    assert len(channel.detail_calls) == 2 + len(adapter._RECHECK_DELAYS)
    # 失败现场包必须落盘：stage=click_no_flip（本篇的核心断言）
    files = list(tmp_path.glob("doubao_failures-*.jsonl"))
    assert files, "失败但没落现场包"
    record = json.loads(files[0].read_text(encoding="utf-8").splitlines()[-1])
    assert record["stage"] == "click_no_flip"
    assert record["click"]["text"] == "签到"
    assert "dom" in record and "page_text" in record


def test_click_recheck_retry_then_true_is_claimed():
    """复查退避：前两次未翻转、第三次已签 → CLAIMED（2026-11-16 真机失败根因）。"""
    channel = FakeChannel(
        pages=[{"type": "page", "url": "https://www.doubao.com/x",
                "webSocketDebuggerUrl": "ws://p"}],
        detail_results=[
            detail_payload(False),
            detail_payload(False),
            detail_payload(False),
            detail_payload(True),
        ],
        eval_results=[{"x": 1, "y": 2, "text": "立即签到"}],
    )
    result = make_port(channel=channel).run(request())
    assert result.status is Status.CLAIMED
    assert "复查第 3 次" in result.evidence[0].summary
    assert len(channel.detail_calls) == 4


def test_click_recheck_detail_error_then_true_is_claimed():
    """复查中 detail 瞬时故障不误判失败——继续退避重试。"""
    channel = FakeChannel(
        pages=[{"type": "page", "url": "https://www.doubao.com/x",
                "webSocketDebuggerUrl": "ws://p"}],
        detail_results=[detail_payload(False), CdpError("timeout"), detail_payload(True)],
        eval_results=[{"x": 1, "y": 2, "text": "签到"}],
    )
    result = make_port(channel=channel).run(request())
    assert result.status is Status.CLAIMED
    assert "复查第 2 次" in result.evidence[0].summary  # 第 1 次复查遇瞬时故障不计失败


def test_no_button_failed_with_page_text_summary():
    channel = FakeChannel(
        pages=[{"type": "page", "url": "https://www.doubao.com/x",
                "webSocketDebuggerUrl": "ws://p"}],
        detail_results=[detail_payload(False)],
        eval_results=[None, None, None, "每日签到 +200 额度（页面诊断摘要）"],
    )
    result = make_port(channel=channel).run(request())
    assert result.status is Status.FAILED
    assert "页面诊断摘要" in result.evidence[0].summary  # 找不到按钮 = 协议事故显式报


def test_detail_710012001_is_no_auth_with_dock_hint():
    channel = FakeChannel(
        pages=[{"type": "page", "url": "https://www.doubao.com/x",
                "webSocketDebuggerUrl": "ws://p"}],
        detail_results=[{"code": 710012001, "msg": "login required"}],
    )
    result = make_port(channel=channel).run(request())
    assert result.status is Status.NO_AUTH
    assert result.repair_hint is not None and result.repair_hint.action_id == "dock"


def test_detail_code_2_raises_unknown_engine_code():
    """code=2 刻意不在方言 → UnknownEngineCode → 用例层转 PROTOCOL_CHANGED（引擎集成见下）。"""
    channel = FakeChannel(
        pages=[{"type": "page", "url": "https://www.doubao.com/x",
                "webSocketDebuggerUrl": "ws://p"}],
        detail_results=[{"code": 2, "msg": "campaign not found"}],
    )
    with pytest.raises(UnknownEngineCode) as excinfo:
        make_port(channel=channel).run(request())
    assert excinfo.value.code == "2"


def test_detail_unknown_code_raises_unknown_engine_code():
    channel = FakeChannel(
        pages=[{"type": "page", "url": "https://www.doubao.com/x",
                "webSocketDebuggerUrl": "ws://p"}],
        detail_results=[{"code": 99999}],
    )
    with pytest.raises(UnknownEngineCode):
        make_port(channel=channel).run(request())


def test_detail_710010702_is_failed_with_hint():
    channel = FakeChannel(
        pages=[{"type": "page", "url": "https://www.doubao.com/x",
                "webSocketDebuggerUrl": "ws://p"}],
        detail_results=[{"code": 710010702, "msg": "system error"}],
    )
    result = make_port(channel=channel).run(request())
    assert result.status is Status.FAILED
    assert "手工点一次" in result.evidence[0].summary  # 三义码不猜


def test_detail_fetch_error_is_failed():
    channel = FakeChannel(
        pages=[{"type": "page", "url": "https://www.doubao.com/x",
                "webSocketDebuggerUrl": "ws://p"}],
        detail_results=[CdpError("boom")],
    )
    result = make_port(channel=channel).run(request())
    assert result.status is Status.FAILED


def test_detail_http_non_2xx_is_transport_failure():
    """非 2xx = 传输层失败（旧裸 HTTP 语义保持，ADR-017 哨兵键回传）。"""
    channel = FakeChannel(
        pages=[{"type": "page", "url": "https://www.doubao.com/x",
                "webSocketDebuggerUrl": "ws://p"}],
        detail_results=[{"butler_http_status": 403}],
    )
    result = make_port(channel=channel).run(request())
    assert result.status is Status.FAILED
    assert "HTTP 403" in result.evidence[0].summary


def test_dry_run_skips_click():
    channel = FakeChannel(
        pages=[{"type": "page", "url": "https://www.doubao.com/x",
                "webSocketDebuggerUrl": "ws://p"}],
        detail_results=[detail_payload(False)],
    )
    result = make_port(channel=channel).run(request(dry_run=True))
    assert result.status is Status.SKIPPED
    assert channel.clicks == []


def test_no_target_opens_activity_page():
    channel = FakeChannel(pages=[], detail_results=[detail_payload(True)])
    result = make_port(channel=channel).run(request())
    assert channel.opened == [adapter._ACTIVITY_URL]
    assert result.status is Status.ALREADY


def test_detail_fetch_contract():
    """页面上下文 fetch 形状对齐 PROTOCOL §2（ADR-017：零裸请求，凭据零手拼）。"""
    channel = FakeChannel(
        pages=[{"type": "page", "url": "https://www.doubao.com/x",
                "webSocketDebuggerUrl": "ws://p"}],
        detail_results=[detail_payload(True)],
    )
    make_port(channel=channel).run(request())
    expr = channel.detail_calls[0]
    assert "/alice/ug/campaign/v3/detail/?" in expr
    assert "version_code=23508" in expr and "aid=497858" in expr
    assert adapter.CAMPAIGN_GROUP_CODE in expr
    # 凭据/签名/设备头全部浏览器原生自带——连接器绝不手拼（ADR-017 核心）
    assert "Cookie" not in expr
    assert "msToken" not in expr and "a_bogus" not in expr
    assert "User-Agent" not in expr
    # 11-16 实证：async fetch 不传 awaitPromise 会被序列化成 {}（空对象误判）
    assert channel.detail_awaits == [True]


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

    channel = FakeChannel(
        pages=[{"type": "page", "url": "https://www.doubao.com/x",
                "webSocketDebuggerUrl": "ws://p"}],
        detail_results=[{"code": 2}],
    )
    ledger, sink = FakeLedger(), FakeSink()
    usecase = ExecuteAction(ledger=ledger, sink=sink, ports=lambda action: make_port(channel=channel))
    run = usecase.execute(
        RunRequest(
            action=Action(kind=ActionKind.PROVISION_RUN, target="doubao_cn"),
            account_id="doubao_cn:逍遥酒鬼",
            window="2026-11-11",
        )
    )
    assert run.result.status is Status.FAILED
    assert any(e.type.value == "PROTOCOL_CHANGED" for e in sink.events)


# --- 多账户身份守卫（ADR-003 落地 / ADR-007 决策 7：切号不自动化）---

def request_b() -> ProvisionRequest:
    """目标 = 第二账户：实际昵称编址（2026-11-18 用户裁决，不用派生占位）。"""
    return ProvisionRequest(
        kind=ActionKind.PROVISION_RUN,
        target="doubao_cn",
        account_id="doubao_cn:小号",
        params={},
        deadline=datetime.now(UTC) + timedelta(seconds=240),
        dry_run=False,
    )


def test_identity_unreadable_is_pending():
    """主窗口不可达 → 身份读不到就 PENDING（绝不盲签，A2-02 §6 红线）。"""
    result = make_port(channel=FakeChannel(identity=None)).run(request())
    assert result.status is Status.PENDING
    assert "活跃账户身份" in result.evidence[0].summary


def test_b_active_main_request_auto_switch_fails_offline_is_pending():
    """B 活跃而请求 main → 自动切号尝试（决策 8）；离线假件下 chip 定位失败
    → PENDING 且修复提示语境正确（身份语境，非端口语境——bug ② 回归）。"""
    channel = FakeChannel(identity={"sec_uid": B_SEC_UID, "nickname": "小号"})
    result = make_port(channel=channel).run(request())
    assert result.status is Status.PENDING
    summary = result.evidence[0].summary
    assert "小号" in summary and "自动切号" in summary and "doubao_cn:逍遥酒鬼" in summary
    assert result.repair_hint is not None and result.repair_hint.action_id == "dock"
    assert "人工切换" in result.repair_hint.reason  # 语境 = 身份不符，不是端口
    assert "调试端口" not in result.repair_hint.reason


def test_b_active_b_request_proceeds_already():
    """B 活跃且请求 B → 匹配通过，现行编排继续（detail 已签 → ALREADY）。"""
    channel = FakeChannel(
        identity={"sec_uid": B_SEC_UID, "nickname": "小号"},
        pages=[{"type": "page", "url": "https://www.doubao.com/x",
                "webSocketDebuggerUrl": "ws://p"}],
        detail_results=[detail_payload(True)],
    )
    result = make_port(channel=channel).run(request_b())
    assert result.status is Status.ALREADY
    assert "detail 权威判定" in result.evidence[0].summary


def test_baseline_missing_is_pending_with_dock_hint():
    """基线文件缺失 → PENDING 提示先 dock 首采（防把 B 误当 main）。"""
    import os as _os
    from butler_connectors.doubao_cn.identity import identity_path as _ip
    _os.remove(_ip())  # fixture 预置的基线删掉，模拟首装
    result = make_port().run(request())
    assert result.status is Status.PENDING
    assert "基线" in result.evidence[0].summary


def test_dock_registers_b_account_when_active(tmp_path, monkeypatch):
    """dock：基线已建且活跃=B → 幂等登记 B（account_code 派生）。"""
    monkeypatch.setenv("DOUBAO_IDENTITY_PATH", str(tmp_path / "dock-id.json"))
    doubao_identity.save_main_baseline(
        doubao_identity.ActiveIdentity(sec_uid=MAIN_SEC_UID, nickname="逍遥酒鬼")
    )

    @dataclass
    class RegisterSpy:
        calls: list = field(default_factory=list)

        def execute(self, platform, account_name, *, account_code="main", account_id=None, identity=None):
            self.calls.append((platform, account_name, account_code))
            from types import SimpleNamespace
            return SimpleNamespace(id=f"{platform}:{account_code}")

    @dataclass
    class Ctx:
        register: RegisterSpy

    channel = FakeChannel(identity={"sec_uid": B_SEC_UID, "nickname": "小号"})
    spy = RegisterSpy()
    outcome = adapter.butler.dock(Ctx(register=spy), env=FakeEnv(), channel=channel)
    assert outcome.accounts == ["doubao_cn:逍遥酒鬼", "doubao_cn:小号"]
    assert spy.calls[0] == ("doubao_cn", "Doubao CN · 逍遥酒鬼", "逍遥酒鬼")
    assert spy.calls[1] == ("doubao_cn", "小号", "小号")


def test_dock_registers_registered_other_when_channel_only_has_main(tmp_path, monkeypatch):
    """dock：客户端只有 main 活跃，但登记簿已有 B → B 也要登记成卡。"""
    monkeypatch.setenv("DOUBAO_IDENTITY_PATH", str(tmp_path / "dock-registry.json"))
    doubao_identity.save_identity_registry(
        [
            doubao_identity.ActiveIdentity(sec_uid=MAIN_SEC_UID, nickname="逍遥酒鬼"),
            doubao_identity.ActiveIdentity(sec_uid=B_SEC_UID, nickname="小号"),
        ]
    )

    @dataclass
    class RegisterSpy:
        calls: list = field(default_factory=list)

        def execute(self, platform, account_name, *, account_code="main", account_id=None, identity=None):
            self.calls.append((platform, account_name, account_code))
            from types import SimpleNamespace
            return SimpleNamespace(id=f"{platform}:{account_code}")

    @dataclass
    class Ctx:
        register: RegisterSpy

    channel = FakeChannel(identity={"sec_uid": MAIN_SEC_UID, "nickname": "逍遥酒鬼"})
    spy = RegisterSpy()
    outcome = adapter.butler.dock(Ctx(register=spy), env=FakeEnv(), channel=channel)
    assert outcome.accounts == ["doubao_cn:逍遥酒鬼", "doubao_cn:小号"]
    assert spy.calls[0] == ("doubao_cn", "Doubao CN · 逍遥酒鬼", "逍遥酒鬼")
    assert spy.calls[1] == ("doubao_cn", "小号", "小号")


def test_dock_first_visit_saves_main_baseline(tmp_path, monkeypatch, request_ctx=None):
    """dock 首采：无基线时把当前活跃身份存为 main 基线。"""
    monkeypatch.setenv("DOUBAO_IDENTITY_PATH", str(tmp_path / "first.json"))

    @dataclass
    class RegisterOk:
        def execute(self, platform, account_name, *, account_code="main", account_id=None, identity=None):
            from types import SimpleNamespace
            return SimpleNamespace(id=f"{platform}:{account_code}")

    @dataclass
    class Ctx:
        register: RegisterOk

    channel = FakeChannel()  # 默认 main 身份
    adapter.butler.dock(Ctx(register=RegisterOk()), env=FakeEnv(), channel=channel)
    baseline = doubao_identity.load_main_baseline()
    assert baseline is not None and baseline.sec_uid == MAIN_SEC_UID


