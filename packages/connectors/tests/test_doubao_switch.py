"""doubao_cn 会话级自动切号离线测试（ADR-007 决策 8，2026-11-17 用户裁决）。

覆盖：switch 编排逐场景（chip/键盘焦点导航/翻转超时）+ adapter 守卫接线 +
旧活动页关净 + dock 拉起 settle（bug ①回归）+ 修复提示语境（bug ②回归）+
身份登记簿。激活路径 = 键盘导航（指针点击对 Radix menuitem 不生效，真机实证）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from butler_core.execution.ports import ProvisionRequest
from butler_core.execution.domain import ActionKind
from butler_core.shared.results import Status
from butler_connectors.cdp import CdpError
from butler_connectors.doubao_cn import adapter
from butler_connectors.doubao_cn import identity as doubao_identity
from butler_connectors.doubao_cn.identity import ActiveIdentity
from butler_connectors.doubao_cn.switch import SwitchError, switch_session
from butler_connectors.transport import HttpResponse, TransportError

MAIN_SEC_UID = "MS4wTESTMAIN000000"
B_SEC_UID = "MS4wTESTBBBB000000"
MAIN_NICK = "逍遥酒鬼"
B_NICK = "Leisure520"

CHIP = {"x": 125, "y": 836}  # 2026-11-17 真机取证坐标
_BLANK = {"x": 500, "y": 400}  # 收尾空白点击（收起弹层）

#: 菜单项真实项序（2026-11-17 真机取证：设置..订阅..账户两行..添加账号..退出）
_MENU_ITEMS = (
    "设置", "外观设置", "检查更新", "帮助与更多", "免费用豆包工作",
    "豆包订阅升级", B_NICK, MAIN_NICK, "添加账号", "退出登录",
)


def focus_path(target_nick: str) -> list[dict]:
    """键盘导航的逐步焦点状态脚本：菜单容器起点 → 逐项 → 目标。"""
    states = [{"inMenu": True, "active": "container"}]
    for item in _MENU_ITEMS:
        if item == target_nick:
            break
        states.append({"inMenu": True, "active": item})
    states.append({"inMenu": True, "active": target_nick})
    return states


# --- 假件（A2-02 §8：离线假束；时钟可注入，翻转轮询不真等）---


@dataclass
class FakeClock:
    """sleep 推进虚拟时间、monotonic 读回——离线测轮询 deadline。"""

    now: float = 0.0

    def sleep(self, seconds: float) -> None:
        self.now += seconds

    def monotonic(self) -> float:
        return self.now


@dataclass
class FakeConn:
    closed: bool = False
    calls: list = field(default_factory=list)

    def call(self, method, params=None, *, wait=8.0):
        self.calls.append(method)
        return {}

    def close(self):
        self.closed = True


@dataclass
class FakeChannel:
    """cdp.CdpChannel 同形状假通道；Enter 激活后身份翻转（单会话存活语义）。"""

    identity: dict | None = field(
        default_factory=lambda: {"sec_uid": B_SEC_UID, "nickname": B_NICK}
    )
    flip_after_enter: dict | None = None  # Enter 按下后身份翻转到此
    pages: list = field(default_factory=list)
    focus_states: list = field(default_factory=list)  # 键盘导航逐步焦点状态
    eval_results: list = field(default_factory=list)
    clicks: list = field(default_factory=list)
    keys: list = field(default_factory=list)
    closed_targets: list = field(default_factory=list)
    opened: list = field(default_factory=list)
    conn: FakeConn = field(default_factory=FakeConn)

    def probe(self) -> dict:
        return {"Browser": "Chrome/147.0.7727.149"}

    def targets(self) -> list[dict]:
        pages = list(self.pages)
        if self.identity is not None:
            pages.insert(
                0,
                {
                    "type": "page",
                    "url": "doubao://doubao-chat/chat",
                    "webSocketDebuggerUrl": "ws://chat",
                    "id": "chat-target",
                },
            )
        return pages

    def attach(self, target) -> FakeConn:
        return self.conn

    def open_activity(self, url: str, *, wait: float = 15.0) -> FakeConn:
        self.opened.append(url)
        return self.conn

    def cookies(self, conn, url: str = "https://www.doubao.com") -> list[dict]:
        return [{"name": "sessionid", "value": "s3cret-session"}]

    def evaluate(self, conn, expression: str, *, wait: float = 20.0):
        if "for_ban_appeal_sec_user_id" in expression:  # 身份查询（identity.py）
            if self.flip_after_enter is not None and "Enter" in self.keys:
                return dict(self.flip_after_enter)
            return dict(self.identity) if self.identity else None
        if "activeElement" in expression:  # 菜单焦点状态（键盘导航每步读取）
            if not self.focus_states:
                return None
            item = self.focus_states.pop(0)
            if isinstance(item, Exception):
                raise item
            return item
        if not self.eval_results:
            return None
        item = self.eval_results.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def click(self, conn, x: int, y: int) -> None:
        self.clicks.append((x, y))

    def key(self, conn, code: str) -> None:
        self.keys.append(code)

    def close_target(self, target_id: str) -> None:
        self.closed_targets.append(target_id)
        self.pages = [p for p in self.pages if str(p.get("id")) != target_id]


@dataclass
class FakeEnv:
    version: str = "2.36.8"
    slept: list = field(default_factory=list)
    clock: FakeClock | None = None  # 挂钩时钟：sleep 与 monotonic 必须同一时间源

    def resolve_port(self) -> int:
        return 9222

    def read_version(self) -> str:
        return self.version

    def locate_exe(self):
        return None

    def process_pids(self) -> list[int]:
        return []

    def kill_pid(self, pid) -> None: ...

    def spawn_detached(self, exe) -> None: ...

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        if self.clock is not None:
            self.clock.now += seconds


@dataclass
class OpsEnv(FakeEnv):
    """留痕版环境束：kill/spawn/sleep 全记录（settle 顺序断言用）。"""

    ops: list = field(default_factory=list)

    def locate_exe(self):
        return Path("C:/fake/Doubao.exe")

    def process_pids(self) -> list[int]:
        return [11, 22]

    def kill_pid(self, pid) -> None:
        self.ops.append(f"kill:{pid}")

    def spawn_detached(self, exe) -> None:
        self.ops.append("spawn")

    def sleep(self, seconds: float) -> None:
        self.ops.append(f"sleep:{seconds}")


class FakeTransport:
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


def detail_payload(checked: bool, days: int = 10, amount: int = 200) -> dict:
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
                    },
                }
            ]
        },
    }


@pytest.fixture(autouse=True)
def _identity_registry(tmp_path, monkeypatch):
    """每测试独立身份文件：main 基线预置（run 匹配前提）。"""
    path = tmp_path / "doubao_identity.json"
    monkeypatch.setenv("DOUBAO_IDENTITY_PATH", str(path))
    monkeypatch.setenv("DOUBAO_REQUEST_CAPTURE", "0")  # 默认测试不落请求快照
    doubao_identity.save_main_baseline(
        ActiveIdentity(sec_uid=MAIN_SEC_UID, nickname=MAIN_NICK)
    )
    yield path


def make_port(transport=None, *, channel=None, env=None, clock: FakeClock | None = None):
    if env is None:
        env = FakeEnv(clock=clock)  # sleep 与 monotonic 强制同一时间源（防 deadline 失效）
    return adapter.butler.build_port(
        vault=object(),
        transport=transport,
        env=env,
        channel=channel if channel is not None else FakeChannel(),
        monotonic=clock.monotonic if clock is not None else None,
    )


def request_for(account_id: str, *, dry_run: bool = False) -> ProvisionRequest:
    return ProvisionRequest(
        kind=ActionKind.PROVISION_RUN,
        target="doubao_cn",
        account_id=account_id,
        params={},
        deadline=datetime.now(UTC) + timedelta(seconds=240),
        dry_run=dry_run,
    )


def request_main() -> ProvisionRequest:
    return request_for("doubao_cn:main")


def request_b() -> ProvisionRequest:
    return request_for(f"doubao_cn:{doubao_identity.derive_key(B_SEC_UID)}")


# --- switch 编排逐场景（switch_session 直测）---


def test_switch_happy_path_arrows_to_row_enters_and_verifies_flip():
    channel = FakeChannel(
        flip_after_enter={"sec_uid": MAIN_SEC_UID, "nickname": MAIN_NICK},
        focus_states=focus_path(MAIN_NICK),
        eval_results=[CHIP],
    )
    clock = FakeClock()
    got = switch_session(
        channel, ActiveIdentity(sec_uid=MAIN_SEC_UID, nickname=MAIN_NICK),
        sleep=clock.sleep, monotonic=clock.monotonic,
    )
    assert got.sec_uid == MAIN_SEC_UID
    assert channel.keys[-1] == "Enter"  # 目标项聚焦后 Enter 激活
    assert channel.keys.count("ArrowDown") == 8  # 容器起点 → 8 项前序 → 目标
    assert channel.clicks == [(CHIP["x"], CHIP["y"])]  # 只点 chip 开弹层
    assert "Page.bringToFront" in channel.conn.calls  # 失焦点击不开（11-16 实证）
    assert channel.conn.closed  # 单会话存活：旧连接用毕即关，不复用


def test_switch_chip_missing_raises_switch_error():
    channel = FakeChannel(eval_results=[None])
    with pytest.raises(SwitchError, match="chip"):
        switch_session(
            channel, ActiveIdentity(sec_uid=MAIN_SEC_UID, nickname=MAIN_NICK),
            sleep=FakeClock().sleep, monotonic=FakeClock().monotonic,
        )


def test_switch_focus_never_reaches_target_dismisses_then_raises():
    """两次尝试焦点都到不了目标 → 逐次收起弹层（chip×2 + 空白×2），再显式抛。"""
    channel = FakeChannel(
        eval_results=[CHIP, _BLANK, CHIP, _BLANK],  # chip → 遍历 → 收尾 → 重开再收
        focus_states=[{"inMenu": True, "active": "其他项"}] * 28,
    )
    clock = FakeClock()
    with pytest.raises(SwitchError, match="无法聚焦"):
        switch_session(
            channel, ActiveIdentity(sec_uid=MAIN_SEC_UID, nickname=MAIN_NICK),
            sleep=clock.sleep, monotonic=clock.monotonic,
        )
    assert len(channel.clicks) == 4  # chip×2 + 收尾空白×2（每次尝试后各收一次）
    assert channel.keys.count("Enter") == 0  # 焦点不在目标上绝不按 Enter


def test_switch_no_chat_target_raises():
    channel = FakeChannel(identity=None)  # targets() 无 chat 页
    with pytest.raises(SwitchError, match="找不到 chat 页"):
        switch_session(
            channel, ActiveIdentity(sec_uid=MAIN_SEC_UID, nickname=MAIN_NICK),
            sleep=FakeClock().sleep, monotonic=FakeClock().monotonic,
        )


def test_switch_target_without_nickname_raises():
    channel = FakeChannel()
    with pytest.raises(SwitchError, match="昵称"):
        switch_session(
            channel, ActiveIdentity(sec_uid=MAIN_SEC_UID, nickname=""),
            sleep=FakeClock().sleep, monotonic=FakeClock().monotonic,
        )


def test_switch_flip_timeout_raises_with_fake_clock():
    """身份永不翻转 → deadline 到期显式抛（时钟可注入，不真等 45s）。"""
    channel = FakeChannel(
        focus_states=focus_path(MAIN_NICK),  # flip_after_enter=None
        eval_results=[CHIP],
    )
    clock = FakeClock()
    with pytest.raises(SwitchError, match="未翻转"):
        switch_session(
            channel, ActiveIdentity(sec_uid=MAIN_SEC_UID, nickname=MAIN_NICK),
            sleep=clock.sleep, monotonic=clock.monotonic,
        )
    assert clock.now >= 45.0  # 虚拟时钟走满 deadline 才判超时（翻转含会话重载）


# --- adapter 守卫接线（决策 8）---


def test_b_active_main_request_auto_switches_and_claims():
    """B 活跃请求 main：键盘切号成功 → 旧活动页关净 → 新开活动页 → detail 已签
    → ALREADY；切号留痕进 evidence 首位（台账可审计）。"""
    channel = FakeChannel(
        flip_after_enter={"sec_uid": MAIN_SEC_UID, "nickname": MAIN_NICK},
        focus_states=focus_path(MAIN_NICK),
        eval_results=[CHIP],
        pages=[{  # 旧活动页：切号后残留旧账户会话（B 的）——必须关净
            "type": "page",
            "url": "https://www.doubao.com/pc/agent-explore",
            "webSocketDebuggerUrl": "ws://stale",
            "id": "stale-act",
        }],
    )
    clock = FakeClock()
    transport = FakeTransport([ok(detail_payload(True))])
    result = make_port(transport, channel=channel, clock=clock).run(request_main())
    assert result.status is Status.ALREADY
    assert "自动切号到「逍遥酒鬼」" in result.evidence[0].summary
    assert channel.closed_targets == ["stale-act"]  # 旧页关净（防签错账户）
    assert channel.opened == [adapter._ACTIVITY_URL]  # 新页 = 新会话 Cookie
    assert channel.keys[-1] == "Enter"
    assert len(transport.requests) == 1  # detail 已签：只查一次，无点击复查


def test_main_active_b_request_auto_switches_to_registered_b():
    """main 活跃请求 B：B 已在登记簿（others）→ 切到 B 成功 → 真实编排。"""
    doubao_identity.save_identity_registry(
        [
            ActiveIdentity(sec_uid=MAIN_SEC_UID, nickname=MAIN_NICK),
            ActiveIdentity(sec_uid=B_SEC_UID, nickname=B_NICK),
        ]
    )
    channel = FakeChannel(
        identity={"sec_uid": MAIN_SEC_UID, "nickname": MAIN_NICK},
        flip_after_enter={"sec_uid": B_SEC_UID, "nickname": B_NICK},
        focus_states=focus_path(B_NICK),
        eval_results=[CHIP, {"x": 10, "y": 20, "text": "立即签到"}],  # 切完后的签到按钮
    )
    transport = FakeTransport([ok(detail_payload(False)), ok(detail_payload(True))])
    result = make_port(transport, channel=channel).run(request_b())
    assert result.status is Status.CLAIMED
    assert "自动切号到「Leisure520」" in result.evidence[0].summary


def test_auto_switch_failure_is_pending_with_identity_hint():
    """切号失败 → PENDING 且提示为身份语境（bug ②回归：不再误用端口语境）。"""
    channel = FakeChannel(eval_results=[None])  # chip 定位失败
    result = make_port(channel=channel).run(request_main())
    assert result.status is Status.PENDING
    assert result.repair_hint is not None
    assert "人工切换" in result.repair_hint.reason
    assert "调试端口" not in result.repair_hint.reason


def test_auto_switch_flip_timeout_is_pending():
    """激活了切换项但身份不翻转 → PENDING（不盲签，A2-02 §6 红线）。

    env.sleep 与 monotonic 必须同一时钟源（否则 deadline 永不生效死循环）——
    这正是本测试用 clock 驱动 FakeEnv 的原因。
    """
    channel = FakeChannel(focus_states=focus_path(MAIN_NICK))  # flip_after_enter=None
    env = FakeEnv(clock=FakeClock())
    transport = FakeTransport([])
    result = make_port(
        transport, channel=channel, env=env, clock=env.clock
    ).run(request_main())
    assert result.status is Status.PENDING
    assert "自动切号" in result.evidence[0].summary
    assert transport.requests == []  # 绝不带着不确定身份发 detail


def test_switch_target_unregistered_is_pending():
    """目标账户未登记（无定位依据）→ PENDING 指引先 dock 登记，不猜。"""
    result = make_port(channel=FakeChannel()).run(request_for("doubao_cn:u1a2b3c4d"))
    assert result.status is Status.PENDING
    assert "不在已登记身份中" in result.evidence[0].summary


def test_stale_activity_page_unclosable_is_pending():
    """旧活动页关不动 → 显式暂缓签到（绝不附着旧 Cookie 页开签）。"""
    channel = FakeChannel(
        flip_after_enter={"sec_uid": MAIN_SEC_UID, "nickname": MAIN_NICK},
        focus_states=focus_path(MAIN_NICK),
        eval_results=[CHIP],
        pages=[{"type": "page", "url": "https://www.doubao.com/x",
                "webSocketDebuggerUrl": "ws://stale", "id": "stuck"}],
    )
    clock = FakeClock()

    def boom(target_id: str) -> None:
        raise CdpError("close refused")

    channel.close_target = boom
    transport = FakeTransport([ok(detail_payload(True))])
    result = make_port(transport, channel=channel, clock=clock).run(request_main())
    assert result.status is Status.PENDING
    assert "暂缓签到" in result.evidence[0].summary
    assert transport.requests == []  # 没关净就不发任何请求


# --- bug ①：dock 拉起 settle（杀净 → 落定 → 拉起）---


def test_ensure_running_settles_after_kill_before_spawn():
    env = OpsEnv()
    issues = adapter._ensure_running(env, FakeChannel())
    assert issues == []  # 首轮 probe 即就绪
    ops = env.ops
    assert ops[0] == "kill:11" and ops[1] == "kill:22"
    spawn_at = ops.index("spawn")
    assert ops[spawn_at - 1] == f"sleep:{adapter._KILL_SETTLE_SECONDS}"  # 先落定再拉起
    assert ops[spawn_at + 1] == "sleep:1.5"  # 拉起后轮询绑定


# --- 身份登记簿（identity.py registry）---


def test_registry_roundtrip_persists_main_and_others():
    doubao_identity.save_identity_registry(
        [
            ActiveIdentity(sec_uid=MAIN_SEC_UID, nickname=MAIN_NICK),
            ActiveIdentity(sec_uid=B_SEC_UID, nickname=B_NICK),
        ]
    )
    reg = doubao_identity.load_identity_registry()
    assert reg.main is not None and reg.main.sec_uid == MAIN_SEC_UID
    assert len(reg.others) == 1
    assert reg.others[0].account_key == doubao_identity.derive_key(B_SEC_UID)
    assert reg.others[0].nickname == B_NICK


def test_registry_back_compat_with_baseline_only_file():
    """旧形状文件（只有 main 基线）→ others 空，不炸。"""
    reg = doubao_identity.load_identity_registry()
    assert reg.main is not None and reg.main.sec_uid == MAIN_SEC_UID
    assert reg.others == ()


def test_registry_empty_read_keeps_existing_entries():
    """采集故障（身份列表为空）不覆盖旧簿——保留既有登记。"""
    doubao_identity.save_identity_registry(
        [
            ActiveIdentity(sec_uid=MAIN_SEC_UID, nickname=MAIN_NICK),
            ActiveIdentity(sec_uid=B_SEC_UID, nickname=B_NICK),
        ]
    )
    doubao_identity.save_identity_registry([])
    reg = doubao_identity.load_identity_registry()
    assert len(reg.others) == 1  # 旧登记仍在


def test_registry_single_current_identity_keeps_registered_others():
    """单会话采集只拿到 main 时，已登记的其它账户不能被覆盖空。

    真机形态：豆包同一时刻只有一个活跃 chat target，dock 采集通常只返回
    当前账户；若此时把 others 重写为空，接下来的自动切号就失去目标。
    """
    doubao_identity.save_identity_registry(
        [
            ActiveIdentity(sec_uid=MAIN_SEC_UID, nickname=MAIN_NICK),
            ActiveIdentity(sec_uid=B_SEC_UID, nickname=B_NICK),
        ]
    )
    doubao_identity.save_identity_registry(
        [ActiveIdentity(sec_uid=MAIN_SEC_UID, nickname=MAIN_NICK)]
    )
    reg = doubao_identity.load_identity_registry()
    assert reg.main is not None and reg.main.sec_uid == MAIN_SEC_UID
    assert len(reg.others) == 1
    assert reg.others[0].sec_uid == B_SEC_UID
    assert reg.others[0].nickname == B_NICK
