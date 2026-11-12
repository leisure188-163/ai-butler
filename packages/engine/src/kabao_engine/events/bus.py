"""进程内 asyncio 事件总线（A4-01 §3）——core EventSink 端口的落地实现。

- publish() 是同步入口（core 端口签名固定）；总线在自己的 loop 线程里分发
- 订阅者逐个顺序调用、彼此错误隔离（A4-01 §5：一个订阅者失败不影响主流程）
- 队列满 → publish 显式报错，绝不静默丢事件（红线 5）
- drain() 等待已入队事件全部分发完成：测试与关闭路径用，防静默丢账
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import threading
from typing import Awaitable, Callable, Union

from kabao_core.domain.event import Event

logger = logging.getLogger(__name__)

Handler = Callable[[Event], Union[None, Awaitable[None]]]


class EventPublishError(RuntimeError):
    """事件入队失败（总线阻塞 / 已关闭）——显式报错，不静默丢。"""


class EventBus:
    """进程内事件总线。端与用例只依赖 core 的 EventSink 端口形状。

    订阅者可为 async（挂起等待不阻塞总线）；同步处理器会阻塞分发线程，
    必须快速返回（SQLite 落账量级 OK），慢等待请写 async。
    """

    def __init__(self, *, queue_size: int = 1000, put_timeout: float = 5.0) -> None:
        self._queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=queue_size)
        self._handlers: list[Handler] = []
        self._lock = threading.Lock()
        self._put_timeout = put_timeout
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._pending = 0  # 已入队未分发完的事件数（drain 用）
        self._cond = threading.Condition()

    # --- 订阅 ---

    def subscribe(self, handler: Handler) -> None:
        with self._lock:
            self._handlers.append(handler)

    # --- 发布（core EventSink 端口）---

    def publish(self, event: Event) -> None:
        loop = self._ensure_started()
        with self._cond:
            self._pending += 1
        try:
            future = asyncio.run_coroutine_threadsafe(self._put(event), loop)
            future.result(timeout=self._put_timeout)
        except Exception as e:
            with self._cond:
                self._pending -= 1
                self._cond.notify_all()
            raise EventPublishError(
                f"事件 {event.type.value} 入队失败（总线阻塞或已关闭？）: {e}"
            ) from e

    async def _put(self, event: Event) -> None:
        await self._queue.put(event)

    # --- 生命周期 ---

    def drain(self, timeout: float = 5.0) -> bool:
        """等待已入队事件全部分发完成。返回是否在超时前排空。"""
        with self._cond:
            return self._cond.wait_for(lambda: self._pending == 0, timeout=timeout)

    def close(self, *, timeout: float = 5.0) -> None:
        """排空后停止总线。幂等。"""
        if self._loop is None or self._loop.is_closed():
            return
        self.drain(timeout=timeout)
        if not self._queue.empty():
            logger.warning(
                "事件总线关闭时队列仍有 %d 个未分发事件", self._queue.qsize()
            )
        loop, thread = self._loop, self._thread
        # 优雅停止：取消所有挂起协程（含 queue.get），而不是 loop.stop() 硬打断——
        # 后者会让总线线程带着 "Event loop stopped before Future completed" 退出
        def _cancel_all():
            for task in asyncio.all_tasks(loop):
                task.cancel()

        loop.call_soon_threadsafe(_cancel_all)
        if thread is not None:
            thread.join(timeout=timeout)
        loop.close()
        self._loop = None
        self._thread = None

    # --- 内部 ---

    def _ensure_started(self) -> asyncio.AbstractEventLoop:
        with self._lock:
            if self._loop is None or self._loop.is_closed():
                self._loop = asyncio.new_event_loop()
                self._thread = threading.Thread(
                    target=self._run_loop, name="kabao-event-bus", daemon=True
                )
                self._thread.start()
            return self._loop

    def _run_loop(self) -> None:
        assert self._loop is not None
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._dispatch_forever())
        except asyncio.CancelledError:
            pass  # close() 的优雅取消，不是故障

    async def _dispatch_forever(self) -> None:
        while True:
            event = await self._queue.get()
            with self._lock:
                handlers = list(self._handlers)
            for handler in handlers:
                try:
                    outcome = handler(event)
                    if inspect.isawaitable(outcome):
                        await outcome  # async 订阅者：挂起不阻塞总线
                except Exception:
                    # 错误隔离：一个订阅者失败不影响其他订阅者与主流程（A4-01 §5）
                    logger.exception(
                        "事件订阅者执行失败（已隔离）: %s", event.type.value
                    )
            with self._cond:
                self._pending -= 1
                self._cond.notify_all()
