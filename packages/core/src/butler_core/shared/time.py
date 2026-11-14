"""时间单源（shared 内核）：core 内所有 UTC 时钟取值一律经此。"""

from __future__ import annotations

from datetime import datetime, timezone


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
