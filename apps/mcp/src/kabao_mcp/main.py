"""Kabao MCP stdio 薄壳：把卡包三动作（查额度/查用量/触发领取）暴露给 LLM 客户端。

宿主形态（ADR-008）：stdio 宿主走 server 契约 API——本包零 core/engine import，
纯 HTTP 投影；status/signal 字面量 core 出产直传（端零映射，红线 2）。
server 不可达/HTTP 报错 → 显式转述给 LLM（红线 5），绝不静默兜底。

启动：uv run kabao-mcp（stdio）；base URL 经 KABAO_SERVER_URL 覆盖。
SDK：官方 mcp 2.x（MCPServer；v1 的 FastMCP 已改名）。
"""
from __future__ import annotations

import json
import os
from typing import Any

import httpx
from mcp.server.mcpserver import MCPServer

_DEFAULT_BASE_URL = "http://127.0.0.1:8000"
_READ_TIMEOUT = 30.0
_RUN_TIMEOUT = 180.0  # 领取预算内可能跑满（provision_budget），读端点用不到


class _ServerError(RuntimeError):
    """server 不可达 / HTTP ≥400——工具层原样转述，不加工不降级。"""


# 测试注入口（生产恒 None）：httpx.MockTransport 从这里进
_transport: httpx.BaseTransport | None = None


def _base_url() -> str:
    return os.environ.get("KABAO_SERVER_URL", _DEFAULT_BASE_URL).rstrip("/")


def _http_client(timeout: float) -> httpx.Client:
    if _transport is not None:
        return httpx.Client(transport=_transport, base_url=_base_url(), timeout=timeout)
    return httpx.Client(base_url=_base_url(), timeout=timeout)


def _fetch_json(
    client: httpx.Client, method: str, path: str, json_body: dict | None = None
) -> Any:
    try:
        resp = client.request(method, path, json=json_body)
    except httpx.HTTPError as exc:
        raise _ServerError(
            f"Kabao server 不可达（{_base_url()}，{exc.__class__.__name__}）。"
            "请先启动主控服务：uv run uvicorn server.main:app --port 8000"
        ) from exc
    if resp.status_code >= 400:
        try:
            detail = resp.json().get("detail") or resp.text
        except ValueError:
            detail = resp.text
        raise _ServerError(
            f"Kabao server HTTP {resp.status_code}（{method} {path}）：{detail}"
        )
    return resp.json()


# --- 投影（shape 投影不含语义决策；provider 过滤是选取不是映射）---


def _filter_provider(rows: list[dict], provider: str | None) -> list[dict]:
    if not provider or not provider.strip():
        return rows
    needle = provider.strip().casefold()
    return [
        r
        for r in rows
        if needle in str(r.get("provider", "")).casefold()
        or needle in str(r.get("display_name", "")).casefold()
    ]


def _quota_view(row: dict) -> dict:
    return {
        "account_id": row.get("account_id"),
        "provider": row.get("provider"),
        "display_name": row.get("display_name"),
        "collected_at": row.get("collected_at"),
        "packages": [
            {
                "package_id": p.get("package_id"),
                "name": p.get("name"),
                "total": p.get("total"),
                "used": p.get("used"),
                "remaining": p.get("remaining"),
                "unit": p.get("unit"),
                "cycle_end": p.get("cycle_end"),
                "status": p.get("status"),
            }
            for p in row.get("packages") or []
        ],
        "forecasts": row.get("forecasts") or [],
        "quota_low": row.get("quota_low") or [],
    }


def _usage_view(row: dict) -> dict:
    return {
        "account_id": row.get("account_id"),
        "provider": row.get("provider"),
        "display_name": row.get("display_name"),
        "aggregate_collected_at": row.get("aggregate_collected_at"),
        "aggregate_summary": row.get("aggregate_summary"),
        "recent_ledger": [
            {
                "amount": e.get("amount"),
                "unit": e.get("unit"),
                "kind": e.get("kind"),
                "occurred_at": e.get("occurred_at"),
            }
            for e in row.get("recent_ledger") or []
        ],
    }


def _dump(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _quota_text(provider: str | None = None) -> str:
    try:
        with _http_client(_READ_TIMEOUT) as client:
            rows = _fetch_json(client, "GET", "/api/v1/usage/radar")
    except _ServerError as exc:
        return str(exc)
    return _dump([_quota_view(r) for r in _filter_provider(rows, provider)])


def _usage_text(provider: str | None = None) -> str:
    try:
        with _http_client(_READ_TIMEOUT) as client:
            rows = _fetch_json(client, "GET", "/api/v1/usage/radar")
    except _ServerError as exc:
        return str(exc)
    return _dump([_usage_view(r) for r in _filter_provider(rows, provider)])


def _claim_text(target: str) -> str:
    try:
        with _http_client(_RUN_TIMEOUT) as client:
            run = _fetch_json(client, "POST", "/api/v1/runs", {"target": target})
    except _ServerError as exc:
        return str(exc)
    return _dump(
        {
            "target": run.get("target"),
            "account_id": run.get("account_id"),
            "status": run.get("status"),
            "signal": run.get("signal"),
            "evidence": [e.get("summary") for e in run.get("evidence") or []],
            "repair_reason": run.get("repair_reason"),
            "repair_action_id": run.get("repair_action_id"),
        }
    )


mcp = MCPServer(
    "kabao",
    instructions=(
        "Kabao（卡包）：本地优先的 AI 账号管家。工具返回 JSON 文本；"
        "先用查额度/查用量认识卡包里的卡（provider = 连接器 id），再触发领取。"
    ),
)


@mcp.tool()
def query_quota(provider: str | None = None) -> str:
    """查额度：每张卡（账号）当前额度包余额、耗尽预测与低额包列表。

    provider 可选过滤（连接器 id 或应用名，如 trae_cn / Trae CN，支持部分匹配）。
    packages 为空 = 该卡尚未采集过额度。quota_low 里的 package_id 是低额包。
    """
    return _quota_text(provider)


@mcp.tool()
def query_usage(provider: str | None = None) -> str:
    """查用量：每张卡（账号）的累计用量汇总与最近额度入账流水。

    provider 可选过滤（连接器 id 或应用名，支持部分匹配）。
    aggregate_summary 为 null = 尚未采集过用量。
    """
    return _usage_text(provider)


@mcp.tool()
def claim_now(target: str) -> str:
    """领取：为一家应用立即跑一次领取（签到/领积分/领权益的统一动作）。

    target = 连接器 id（先查额度/查用量，取结果里的 provider 字段）。
    返回 status 协议字面量：CLAIMED=已领取 / ALREADY=今日已领 / FAILED=失败 /
    NO_AUTH=需要登录 / PENDING=待处理 / EXPIRED=已过期 / SKIPPED=已跳过；
    status 为 null = 预算内未完成。
    """
    return _claim_text(target)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
