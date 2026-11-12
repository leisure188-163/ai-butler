"""doubao dock 离线测试：cdp_probe 体检 + 自动拉起编排（ADR-005 决策 2/5）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace

from kabao_connectors.cdp import CdpError
from kabao_connectors.doubao_cn import adapter


@dataclass
class FakeRegister:
    calls: list[tuple[str, str]] = field(default_factory=list)

    def execute(self, provider: str, display_name: str, *, account_id: str | None = None):
        self.calls.append((provider, display_name))
        return SimpleNamespace(id=f"{provider}:main")


@dataclass
class FakeCtx:
    register: FakeRegister = field(default_factory=FakeRegister)
    vault: object = None  # 零凭据设计：dock 绝不碰 vault


@dataclass
class FakeDockEnv:
    exe: object | None = None
    pids: list[int] = field(default_factory=list)
    killed: list[int] = field(default_factory=list)
    spawned: list[object] = field(default_factory=list)
    slept: list[float] = field(default_factory=list)

    def resolve_port(self) -> int:
        return 9222

    def read_version(self) -> str:
        return "2.35.8"

    def locate_exe(self):
        return self.exe

    def process_pids(self) -> list[int]:
        return list(self.pids)

    def kill_pid(self, pid: int) -> None:
        self.killed.append(pid)

    def spawn_detached(self, exe) -> None:
        self.spawned.append(exe)

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)


class ScriptedChannel:
    """probe 按脚本回放（None = 可达）；用尽后保持最后状态。"""

    def __init__(self, script: list[CdpError | None], *, hold: bool = True) -> None:
        self.script = list(script)
        self.hold = hold  # True = 脚本用尽后重复最后一项（超时场景用）
        self.last_is_error = False

    def probe(self) -> dict:
        if self.script:
            err = self.script.pop(0)
        elif self.hold and self.last_is_error:
            raise CdpError("still down")
        else:
            err = None
        self.last_is_error = err is not None
        if err is not None:
            raise err
        return {}


def test_probe_ok_registers_account_without_vault():
    ctx, env = FakeCtx(), FakeDockEnv()
    outcome = adapter.kabao.dock(ctx, env=env, channel=ScriptedChannel([None]))
    assert outcome.issues == []
    assert outcome.accounts == ["doubao_cn:main"]
    assert env.spawned == [] and env.killed == []  # 可达即过，不动进程
    assert ctx.register.calls == [("doubao_cn", "Doubao CN")]


def test_probe_fail_relaunches_and_registers():
    exe = object()
    env = FakeDockEnv(exe=exe, pids=[11, 22])
    channel = ScriptedChannel([CdpError("down"), None, None])  # 首次不可达，拉起后可达
    ctx = FakeCtx()
    outcome = adapter.kabao.dock(ctx, env=env, channel=channel)
    assert outcome.issues == []
    assert outcome.accounts == ["doubao_cn:main"]
    assert env.killed == [11, 22]  # 无端口实例全杀（probe 已失败 = 端口没开）
    assert env.spawned == [exe]
    assert env.slept  # 轮询就绪发生过


def test_probe_fail_no_exe_is_explicit_issue():
    env = FakeDockEnv(exe=None)  # 未安装 / mac 自动拉起未实现
    outcome = adapter.kabao.dock(FakeCtx(), env=env, channel=ScriptedChannel([CdpError("down")]))
    assert outcome.accounts == []
    assert outcome.issues and "remote-debugging-port" in outcome.issues[0]


def test_probe_fail_no_exe_mac_message(monkeypatch):
    """mac 文案对本平台诚实：不指向 exe 定位，报 mac 分支未实现 + DOUBAO_EXE 逃生口。"""
    import sys

    monkeypatch.setattr(sys, "platform", "darwin")
    env = FakeDockEnv(exe=None)
    outcome = adapter.kabao.dock(FakeCtx(), env=env, channel=ScriptedChannel([CdpError("down")]))
    assert outcome.accounts == []
    assert "mac 分支未实现自动拉起" in outcome.issues[0]
    assert "DOUBAO_EXE" in outcome.issues[0]
    assert "未定位到客户端 exe" not in outcome.issues[0]


def test_relaunch_timeout_is_explicit_issue():
    env = FakeDockEnv(exe=object(), pids=[1])
    channel = ScriptedChannel([CdpError("down")], hold=True)  # 拉起后仍不可达
    outcome = adapter.kabao.dock(FakeCtx(), env=env, channel=channel)
    assert outcome.accounts == []
    assert outcome.issues and "超时" in outcome.issues[0]
    assert len(env.slept) == 10  # ~15s 轮询后放弃（显式，不无限等）


def test_dock_is_idempotent_on_registry_side():
    register = FakeRegister()
    ctx = FakeCtx(register=register)
    first = adapter.kabao.dock(ctx, env=FakeDockEnv(), channel=ScriptedChannel([None]))
    second = adapter.kabao.dock(ctx, env=FakeDockEnv(), channel=ScriptedChannel([None]))
    assert first.accounts == second.accounts == ["doubao_cn:main"]  # 名册位幂等（core 语义）
