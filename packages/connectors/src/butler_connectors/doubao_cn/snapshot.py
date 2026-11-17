"""豆包请求快照（只读取证，不改变任何出站请求）。

背景：2026-11-17 签到 702 取证需要区分「连接器拼的 detail 请求」和「客户端
页面自己发的 checkin 请求」。本模块把两者脱敏后追加到本地 JSONL，供后续
成功/失败样本对照；绝不保存 Cookie/Authorization/msToken/a_bogus 等明文。

- detail：连接器唯一的裸 HTTP 请求（query/body/headers + 业务响应摘要）
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

from butler_connectors.transport import HttpRequest, HttpResponse

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


def _response_summary(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    daily = None
    for task in (data.get("tasks") or []):
        if isinstance(task, dict) and task.get("campaign_code") == "daily_signin":
            daily = task.get("daily_checkin")
            break
    return {
        "code": payload.get("code"),
        "msg": payload.get("msg"),
        "message": payload.get("message"),
        "daily_checkin": _trim(daily),
    }


def _append(record: dict[str, Any]) -> Path:
    directory = snapshot_dir()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"doubao_requests-{datetime.now().strftime('%Y-%m-%d')}.jsonl"
    line = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")
    return path


def record_detail(
    *,
    account_id: str,
    version: str,
    vcode: int | None,
    request: HttpRequest,
    response: HttpResponse | None = None,
    error: str | None = None,
) -> Path:
    """记录一次 detail 请求/响应（连接器自己拼的裸 HTTP 请求）。"""
    record: dict[str, Any] = {
        "ts": _now(),
        "event": "detail",
        "account_id": account_id,
        "version": version,
        "version_code": vcode,
        "request": {
            "method": request.method,
            "url": redact_url(request.url),
            "query": redact_query(request.url),
            "body": _trim(request.body),
            "headers": redact_headers(request.headers),
        },
        "response": _response_summary(response.payload) if response is not None else None,
        "http_status": response.status_code if response is not None else None,
    }
    if error:
        record["error"] = error
    return _append(record)


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
