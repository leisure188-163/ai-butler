"""EventBus 行为基线：分发、错误隔离、背压显式报错、drain/close。"""

import asyncio
import threading
import time

import pytest

from butler_core.shared.events import Event, EventType, Severity
from butler_engine.events.bus import EventBus, EventPublishError


def _event() -> Event:
    return Event.new(EventType.RUN_FINISHED, severity=Severity.SILENT)


def test_publish_delivers_to_subscribers():
    bus = EventBus()
    seen: list[Event] = []
    bus.subscribe(seen.append)
    bus.publish(_event())
    assert bus.drain()
    assert len(seen) == 1
    bus.close()


def test_subscriber_failure_isolated():
    bus = EventBus()
    seen: list[Event] = []

    def bad(_event):
        raise RuntimeError("订阅者炸了")

    bus.subscribe(bad)
    bus.subscribe(seen.append)
    bus.publish(_event())  # 不得因 bad 抛错而失败
    assert bus.drain()
    assert len(seen) == 1
    bus.close()


def test_queue_full_raises_explicitly():
    bus = EventBus(queue_size=1, put_timeout=0.2)
    started = threading.Event()
    blocker = threading.Event()

    async def slow(_event):
        started.set()  # 确认已进入处理器（此时队列已空）
        await asyncio.to_thread(blocker.wait, 2)  # async 挂起，不阻塞总线

    bus.subscribe(slow)
    bus.publish(_event())  # 被慢订阅者取走消费
    assert started.wait(timeout=2)
    bus.publish(_event())  # 占满队列（size=1，无人消费）
    with pytest.raises(EventPublishError):  # 再入队 → 超时显式报错，不静默丢
        bus.publish(_event())
    blocker.set()
    assert bus.drain(timeout=2)
    bus.close()


def test_drain_waits_for_dispatch_completion():
    bus = EventBus()
    seen: list[Event] = []
    bus.subscribe(lambda e: (time.sleep(0.05), seen.append(e)))
    bus.publish(_event())
    assert bus.drain()
    assert len(seen) == 1  # drain 返回时分发已确完成
    bus.close()


def test_close_idempotent():
    bus = EventBus()
    bus.close()
    bus.close()  # 二次关闭安全
