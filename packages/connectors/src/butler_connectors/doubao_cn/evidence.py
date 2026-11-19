"""豆包失败留证与点击前身份硬断言（2026-11-19 用户裁决）。

从 adapter 拆出（单文件 600 行硬上限）。两块能力都只在「可能出问题」的路径生效：

1. ``assert_identity``：切号复核之后、点击之前的最后一道身份校验。连读两次
   必须都等于目标账户，否则返回不符描述——调用方转 PENDING，**本轮绝不出手**
   （A2-02 §6 红线：绝不签错账户）。
2. ``record_failure``：失败那一刻落一份现场包——detail 全文 + 签到区 DOM +
   点击坐标上真正吃到这一击的元素 + 页面内抓到的 checkin 请求轨迹。目的是把
   「点空」与「平台拒绝」分开：有 ``landing/checkin`` 请求 = 平台回了错；
   没有 = 这一击没落到按钮上/被遮挡。落盘走 ``snapshot.record_failure_evidence``
   （``~/.butler/doubao_failures/``，签名类只存 hash）。

两者都是 best-effort：断言读不到身份按「未知」处理（不放行），现场包写盘失败
不改变已经产生的判定（失败本身仍原样返回给上层）。
"""

from __future__ import annotations

from typing import Any, Callable

from butler_connectors.cdp import CdpChannel, CdpConnection, CdpError
from butler_connectors.doubao_cn import snapshot as request_snapshot
from butler_connectors.doubao_cn.identity import read_all_identities, resolve_account_key
from butler_connectors.doubao_cn.ui_js import (
    _PAGE_TEXT_JS,
    _SIGNIN_AREA_JS,
    _TOPMOST_AT_JS,
    _TRACE_READ_JS,
)

#: 断言读数（连读两次一致才算通过：单次可能撞上界面刷新瞬间的空档）。
_ASSERT_READS = 2
_ASSERT_GAP_SECONDS = 1.0


def read_active_keys(
    channel: CdpChannel, sleep: Callable[[float], None], reads: int = _ASSERT_READS
) -> list[str]:
    """连读活跃账户 key；读失败的位置用 "" 占位（调用方据此判定不放行）。"""
    seen: list[str] = []
    for attempt in range(reads):
        if attempt:
            sleep(_ASSERT_GAP_SECONDS)
        try:
            identities = read_all_identities(channel)
        except Exception:  # 身份只读辅助路径：读失败 = 未知，不放行
            seen.append("")
            continue
        seen.append(resolve_account_key(identities[0]) if identities else "")
    return seen


def assert_identity(
    channel: CdpChannel,
    conn_id: str,
    account_id: str,
    *,
    sleep: Callable[[float], None],
) -> str | None:
    """None = 断言通过（连读两次都命中目标）；str = 不符描述，调用方转 PENDING。"""
    seen = read_active_keys(channel, sleep)
    if len(seen) == _ASSERT_READS and all(f"{conn_id}:{key}" == account_id for key in seen):
        return None
    return (
        f"点击前身份断言未过（活跃={seen[-1] or '未知'}，目标 {account_id}）"
        "——绝不盲签（A2-02 §6 红线），本次未发任何界面点击"
    )


def _eval(channel: CdpChannel, conn: CdpConnection, js: str, default: Any) -> Any:
    try:
        return channel.evaluate(conn, js)
    except CdpError:
        return default


def record_failure(
    channel: CdpChannel,
    conn: CdpConnection,
    account_id: str,
    *,
    stage: str,
    click: dict | None,
    checks: int,
    detail: Any,
) -> None:
    """落失败现场包。stage ∈ {no_button, click_no_flip, detail_error}。"""
    dom: Any = _eval(channel, conn, _SIGNIN_AREA_JS, None)
    if click and isinstance(dom, dict):
        x, y = int(click.get("x") or 0), int(click.get("y") or 0)
        dom["topmost_at_click"] = _eval(channel, conn, _TOPMOST_AT_JS % (x, y), None)
    page_text = str(_eval(channel, conn, _PAGE_TEXT_JS, "") or "")
    trace = _eval(channel, conn, _TRACE_READ_JS, None)
    entries = trace.get("entries") if isinstance(trace, dict) else []
    try:
        request_snapshot.record_failure_evidence(
            account_id=account_id,
            stage=stage,
            click=click,
            checks=checks,
            detail=detail,
            dom=dom,
            page_text=page_text,
            entries=entries,
        )
    except Exception:  # 取证路径：写盘失败不能盖掉真实判定（best-effort）
        return
