"""NotificationCenter 行为基线（A4-01 §3）：阈值投递、渠道隔离。"""

from kabao_core.domain.event import Event, EventType, Severity
from kabao_engine.notify.center import InAppChannel, NotificationCenter


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
