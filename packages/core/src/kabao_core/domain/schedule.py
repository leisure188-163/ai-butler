"""领取窗口（A2-01 §3 + A2-02 §4）：签到日 ≠ 自然日，规则 core 单源。

幂等键 = (kind, account_id, 窗口)——窗口不是日历日，而是从结算时刻
``refresh_at``（如 Qoder 每日 10:00 刷新）划出来的"业务日"。结算点之前
发起的领取属于上一个业务窗，重复触发自然回放上一窗的台账记录（零重复领取）。
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

from kabao_core.domain.errors import DomainError

_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class WindowInvalid(DomainError):
    """refresh_at 非法（形如 HH:MM，24 小时制）——配置事故显式报错，红线 5。"""


def _parse_anchor(refresh_at: str) -> tuple[int, int]:
    if not _TIME_RE.match(refresh_at):
        raise WindowInvalid(f"refresh_at 必须是 HH:MM（24 小时制），得到 {refresh_at!r}")
    return int(refresh_at[:2]), int(refresh_at[3:])


def claim_window(now: datetime, refresh_at: str = "00:00") -> str:
    """计算 now 所属的领区窗口日（ISO 日期字符串）。

    结算时刻按**本机墙钟**解读（refresh_at 是用户所在地的活动结算点），
    UTC 输入先换成本地时区再裁界；now 落在结算点之前 → 属于前一日窗口。
    """
    hour, minute = _parse_anchor(refresh_at)
    local = now.astimezone()
    anchor = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if local < anchor:
        anchor -= timedelta(days=1)
    return anchor.date().isoformat()
