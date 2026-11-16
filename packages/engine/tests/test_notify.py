"""NotificationCenter 行为基线（A4-01 §3）：阈值投递、渠道隔离。"""

from butler_core.shared.events import Event, EventType, Severity
from butler_engine.notify.center import (
    InAppChannel,
    NotificationCenter,
    SystemChannel,
)


def _event(severity: Severity) -> Event:
    return Event.new(EventType.RUN_FINISHED, severity=severity, account_id="a")


def test_in_app_receives_badge_and_push_not_silent():
    in_app = InAppChannel()
    center = NotificationCenter([in_app])
    center.on_event(_event(Severity.SILENT))
    assert len(in_app.items) == 0  # 全部成功 = 零打扰
    center.on_event(_event(Severity.BADGE))
    center.on_event(_event(Severity.PUSH))
    assert len(in_app.items) == 2


def test_channel_failure_isolated():
    class BrokenChannel(InAppChannel):
        name = "broken"
        min_severity = Severity.BADGE

        def deliver(self, event):
            raise RuntimeError("渠道炸了")

    broken, in_app = BrokenChannel(), InAppChannel()
    center = NotificationCenter([broken, in_app])
    center.on_event(_event(Severity.BADGE))  # broken 抛错不得影响 in-app
    assert len(in_app.items) == 1


def test_system_channel_only_push_and_uses_injected_runner():
    """系统通知渠道：阈值 push 起；runner 可注入（测试不真弹窗）。"""
    hits: list[tuple[str, str]] = []
    system = SystemChannel(runner=lambda title, body: hits.append((title, body)))
    center = NotificationCenter([system])
    center.on_event(_event(Severity.BADGE))
    assert hits == []  # badge 只进应用内，不打扰系统层
    center.on_event(_event(Severity.PUSH))
    assert len(hits) == 1
    assert "Butler" in hits[0][0]


def test_system_channel_formats_health_change_with_level():
    hits: list[tuple[str, str]] = []
    system = SystemChannel(runner=lambda title, body: hits.append((title, body)))
    center = NotificationCenter([system])
    center.on_event(
        Event.new(
            EventType.ACCOUNT_HEALTH_CHANGED,
            severity=Severity.PUSH,
            account_id="qoder_cn:main",
            payload={"level": "invalid"},
        )
    )
    assert "qoder_cn:main" in hits[0][1]
    assert "invalid" in hits[0][1]  # 只复述 core 事实，不端侧翻译
