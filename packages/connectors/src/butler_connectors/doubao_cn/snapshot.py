"""豆包请求快照（只读取证，不改变任何出站请求）。

背景：2026-11-17 签到 702 取证需要区分「连接器拼的 detail 请求」和「客户端
页面自己发的 checkin 请求」。**ADR-017（2026-11-17）落地后 detail 改页面上下文
fetch，连接器不再自组任何 HTTP 请求**——原 detail 请求快照（record_detail）
随之退役：capture=1 时页面旁路（_TRACE_INSTALL_JS）会连带记录 detail fetch
（JS 可见 URL 无签名——记录面局限），请求级取证首选 CDP Network 域旁听
（PROTOCOL §2.1）。本模块现仅剩 checkin 点击轨迹：

- checkin：活动页内 fetch/XHR 的 URL/请求体/响应摘要（由 adapter 的页面旁路抓取）
- 默认目录 ``~/.butler/doubao_requests``，``DOUBAO_REQUEST_DIR`` 可覆盖
- 快照失败不阻断签到：adapter 以 best-effort 调用
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import parse_qsl, urlsplit

#: 这些头/查询参数只存 hash + 长度，不落明文（会话凭据/签名/设备指纹）。
_SENSITIVE_KEYS = frozenset(
    {
        "cookie",
        "set-cookie",
        "authorization",
        "proxy-authorization",
        "x-api-key",
        "x-csrf-token",
        "x-xsrf-token",
        "x-tt-token",
        "msToken".lower(),
        "a_bogus",
        "x-bogus",
        "verifyfp",
        "web_id",
        "tea_uuid",
    }
)
_MAX_TEXT = 4000


def snapshot_dir() -> Path:
    """快照目录：DOUBAO_REQUEST_DIR 优先，否则 ~/.butler/doubao_requests。"""
    raw = os.environ.get("DOUBAO_REQUEST_DIR")
    return Path(raw) if raw else Path.home() / ".butler" / "doubao_requests"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _redact_value(value: Any) -> str:
    text = str(value)
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
    return f"<redacted sha256:{digest} len={len(text)}>"


def redact_query(url: str) -> dict[str, Any]:
    """查询参数脱敏：敏感键保留键名但值只存 hash；其余原样。"""
    parsed = urlsplit(url)
    out: dict[str, Any] = {}
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        out[key] = _redact_value(value) if key.lower() in _SENSITIVE_KEYS else value
    return out


def redact_url(url: str) -> str:
    """只保留 path + 脱敏 query；不把 msToken 等拼回 URL。"""
    parsed = urlsplit(url)
    if not parsed.query:
        return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    pairs = []
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        shown = _redact_value(value) if key.lower() in _SENSITIVE_KEYS else value
        pairs.append(f"{key}={shown}")
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}?{'&'.join(pairs)}"


def redact_headers(headers: Mapping[str, Any] | None) -> dict[str, str]:
    """头脱敏：敏感头只存 hash；保留头名便于对照请求形状。"""
    out: dict[str, str] = {}
    if not headers:
        return out
    for key, value in headers.items():
        name = str(key)
        out[name] = _redact_value(value) if name.lower() in _SENSITIVE_KEYS else str(value)
    return out


def _trim(value: Any) -> Any:
    """截断过长字符串；小 dict/list 保留结构，过大才退化成截断 JSON 文本。"""
    if value is None:
        return None
    if isinstance(value, str):
        return value[:_MAX_TEXT]
    if isinstance(value, (dict, list)):
        try:
            text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        except (TypeError, ValueError):
            return str(value)[:_MAX_TEXT]
        return value if len(text) <= _MAX_TEXT else text[:_MAX_TEXT]
    return value


def _append(record: dict[str, Any]) -> Path:
    directory = snapshot_dir()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"doubao_requests-{datetime.now().strftime('%Y-%m-%d')}.jsonl"
    line = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")
    return path


def failure_dir() -> Path:
    """失败现场目录：DOUBAO_FAILURE_DIR 优先，否则 ~/.butler/doubao_failures。"""
    raw = os.environ.get("DOUBAO_FAILURE_DIR")
    return Path(raw) if raw else Path.home() / ".butler" / "doubao_failures"


def record_failure_evidence(
    *,
    account_id: str,
    stage: str,
    click: dict[str, Any] | None,
    checks: int,
    detail: Any,
    dom: Any,
    page_text: str,
    entries: Any,
) -> Path:
    """落一份「签到失败现场包」——把判定失败的那一刻的页面与请求证据留档。

    目的（2026-11-19 用户裁决）：下次失败不必猜。三类失败各自可区分：

    - ``no_button``：页面上找不到「立即签到」→ 界面改版/未加载/账户无资格
    - ``click_no_flip`` + entries 有 ``landing/checkin`` → **平台拒绝**（702 族）
    - ``click_no_flip`` + entries 空 → **点击没落到按钮上**（坐标/遮挡）
    - ``identity_mismatch``：点击前身份硬断言未过（绝不出手，见 adapter）

    ``detail`` 是失败时刻的完整 detail 返回（本地文件，含昵称/额度等原始值）；
    ``entries`` 走 ``record_checkin_trace`` 同一套脱敏（签名类只存 hash）。
    """
    safe_entries: list[dict[str, Any]] = []
    if isinstance(entries, list):
        for entry in entries[:20]:
            if not isinstance(entry, dict):
                continue
            response = entry.get("response")
            safe_entries.append(
                {
                    "transport": entry.get("transport"),
                    "method": entry.get("method"),
                    "url": redact_url(str(entry.get("url") or "")),
                    "query": redact_query(str(entry.get("url") or "")),
                    "headers": redact_headers(entry.get("headers")),
                    "body": _trim(entry.get("body")),
                    "response": (
                        {
                            "status": response.get("status"),
                            "body": _trim(response.get("body")),
                        }
                        if isinstance(response, dict)
                        else None
                    ),
                }
            )
    directory = failure_dir()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"doubao_failures-{datetime.now().strftime('%Y-%m-%d')}.jsonl"
    line = json.dumps(
        {
            "ts": _now(),
            "event": "failure_evidence",
            "account_id": account_id,
            "stage": stage,
            "click": click,
            "recheck_count": checks,
            "checkin_requests": [e for e in safe_entries if "landing/checkin" in str(e.get("url"))],
            "entries": safe_entries,
            "dom": dom,
            "page_text": page_text[:_MAX_TEXT],
            "detail": _trim(detail),
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")
    return path


def record_checkin_trace(
    *,
    account_id: str,
    click_text: str,
    click_xy: tuple[int, int] | None,
    entries: Any,
) -> Path:
    """记录活动页内捕获到的 checkin/detail 请求（已由 adapter 做敏感值脱敏）。"""
    safe_entries: list[dict[str, Any]] = []
    if isinstance(entries, list):
        for entry in entries[:20]:
            if not isinstance(entry, dict):
                continue
            response = entry.get("response")
            safe_entries.append(
                {
                    "transport": entry.get("transport"),
                    "method": entry.get("method"),
                    "url": redact_url(str(entry.get("url") or "")),
                    "query": redact_query(str(entry.get("url") or "")),
                    "headers": redact_headers(entry.get("headers")),
                    "body": _trim(entry.get("body")),
                    "response": (
                        {
                            "status": response.get("status"),
                            "body": _trim(response.get("body")),
                        }
                        if isinstance(response, dict)
                        else None
                    ),
                }
            )
    return _append(
        {
            "ts": _now(),
            "event": "checkin_trace",
            "account_id": account_id,
            "click_text": click_text,
            "click_xy": list(click_xy) if click_xy else None,
            "entries": safe_entries,
        }
    )
