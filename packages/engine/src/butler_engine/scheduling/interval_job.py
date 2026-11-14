"""进程内定时 job（A4-01 §1 到期监控的"每日 job"形态，M0 无 cron 依赖）。

- start() 立即跑一次（启动补扫），之后按 interval 循环
- 单次执行异常不杀死 job（logging.exception 记录，与事件订阅者同款隔离）
- 非守护可 Working：daemon=True，进程生命周期随主进程——桌面包 M2 复查
"""

from __future__ import annotations

import logging
import threading
from datetime import timedelta

logger = logging.getLogger(__name__)


class IntervalJob:
    def __init__(self, fn, *, interval: timedelta, name: str = "butler-job"):
        self._fn = fn
        self._interval = interval
        self._name = name
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def run_once(self) -> None:
        """同步手动触发：测试与运维先扫一遍用。"""
        self._fn()

    def start(self) -> None:
        if self.running:
            raise RuntimeError(f"{self._name} 已在运行")
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, name=self._name, daemon=True
        )
        self._thread.start()

    def stop(self, *, timeout: float = 5.0) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)
        self._thread = None

    # --- 内部 ---

    def _loop(self) -> None:
        while True:
            try:
                self._fn()
            except Exception:
                # 单次失败不打死 job，也不静默——异常如实进日志（红线 5）
                logger.exception("定时任务 %s 单次执行失败（已隔离，继续下一轮）", self._name)
            if self._stop.wait(self._interval.total_seconds()):
                return
