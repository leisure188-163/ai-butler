"""MCP 薄壳测试：MockTransport 假 server 走工具全路径（投影/过滤/报错直传）。

与真 server 的形状一致性由 server 侧 test_api.py 把关；这里钉的是薄壳
投影不越权（字段取舍、错误转述、provider 选取）与 MCP 工具注册面。
"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from kabao_mcp import main as mcp_main


def _radar_row(provider: str = "trae_cn", display: str = "Trae CN") -> dict:
    return {
        "account_id": f"{provider}:main",
        "provider": provider,
        "display_name": display,
        "collected_at": "2026-11-12T09:00:00",
        "packages": [
            {
                "package_id": "p1",
                "name": "月度包",
                "total": 100.0,
                "used": 40.0,
                "remaining": 60.0,
                "unit": "credits",
                "cycle_end": None,
                "status": "active",
            },
            {
                "package_id": "p0",
                "name": "旧包",
                "total": 50.0,
                "used": 50.0,
                "remaining": 0.0,
                "unit": "credits",
                "cycle_end": None,
                "status": "exhausted",
            },
        ],
        "forecasts": [
            {
                "package_id": "p1",
                "name": "月度包",
                "unit": "credits",
                "remaining": 60.0,
                "per_day": 3.0,
                "days_left": 20.0,
                "exhausted_on": "2026-12-02",
            }
        ],
        "quota_low": ["p1"],
        "aggregate_summary": {"total_tokens": 123},
        "aggregate_collected_at": "2026-11-12T09:00:00",
        "recent_ledger": [
            {
                "record_id": "r1",
                "amount": 100.0,
                "unit": "credits",
                "kind": "grant",
                "occurred_at": "2026-11-01T00:00:00",
            }
        ],
    }


def _mock_transport(
    rows: list[dict] | None = None,
    status: int = 200,
    detail: str | None = None,
    run: dict | None = None,
    seen: list[httpx.Request] | None = None,
):
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        if status >= 400:
            return httpx.Response(status, json={"detail": detail or "boom"})
        if request.url.path.endswith("/runs"):
            return httpx.Response(200, json=run or {})
        return httpx.Response(200, json=rows or [])

    return httpx.MockTransport(handler)


@pytest.fixture
def mock_transport(monkeypatch):
    def _install(transport: httpx.MockTransport) -> None:
        monkeypatch.setattr(mcp_main, "_transport", transport)

    return _install


def test_tools_registered():
    tools = asyncio.run(mcp_main.mcp.list_tools())
    assert {t.name for t in tools} == {"query_quota", "query_usage", "claim_now"}
    by_name = {t.name: t for t in tools}
    assert "provider" in by_name["query_quota"].description
    assert "CLAIMED" in by_name["claim_now"].description


def test_quota_view_projects_quota_fields(mock_transport):
    mock_transport(_mock_transport(rows=[_radar_row()]))
    out = json.loads(mcp_main._quota_text())
    [view] = out
    assert view["provider"] == "trae_cn"
    assert [p["package_id"] for p in view["packages"]] == ["p1", "p0"]
    assert view["forecasts"][0]["days_left"] == 20.0
    assert view["quota_low"] == ["p1"]
    assert "aggregate_summary" not in view
    assert "recent_ledger" not in view


def test_usage_view_projects_usage_fields(mock_transport):
    mock_transport(_mock_transport(rows=[_radar_row()]))
    out = json.loads(mcp_main._usage_text())
    [view] = out
    assert view["aggregate_summary"] == {"total_tokens": 123}
    assert view["recent_ledger"][0]["amount"] == 100.0
    assert "record_id" not in view["recent_ledger"][0]
    assert "packages" not in view
    assert "forecasts" not in view


def test_provider_filter_partial_and_casefold(mock_transport):
    mock_transport(
        _mock_transport(rows=[_radar_row(), _radar_row("doubao_cn", "豆包")])
    )
    out = json.loads(mcp_main._quota_text("TRAE"))
    assert [r["provider"] for r in out] == ["trae_cn"]
    out = json.loads(mcp_main._quota_text("豆包"))
    assert [r["provider"] for r in out] == ["doubao_cn"]
    out = json.loads(mcp_main._quota_text(None))
    assert len(out) == 2
    out = json.loads(mcp_main._quota_text("ghost"))
    assert out == []


def test_claim_now_posts_target_and_projects_run(mock_transport):
    seen: list[httpx.Request] = []
    run = {
        "id": "run-1",
        "kind": "provision.run",
        "target": "trae_cn",
        "account_id": "trae_cn:main",
        "started_at": "2026-11-12T09:00:00",
        "finished_at": "2026-11-12T09:00:01",
        "status": "CLAIMED",
        "signal": "ok",
        "evidence": [{"summary": "今日已领取 100 Credits", "raw_code": "200"}],
        "repair_reason": None,
        "repair_action_id": None,
    }
    mock_transport(_mock_transport(run=run, seen=seen))
    out = json.loads(mcp_main._claim_text("trae_cn"))
    assert seen[0].url.path == "/api/v1/runs"
    assert json.loads(seen[0].content) == {"target": "trae_cn"}
    assert out["status"] == "CLAIMED"
    assert out["evidence"] == ["今日已领取 100 Credits"]
    assert "raw_code" not in out


def test_server_unreachable_is_explicit(mock_transport):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    mock_transport(httpx.MockTransport(handler))
    for text in (
        mcp_main._quota_text(),
        mcp_main._usage_text(),
        mcp_main._claim_text("trae_cn"),
    ):
        assert "不可达" in text
        assert "uvicorn server.main:app" in text


def test_http_error_detail_passthrough(mock_transport):
    mock_transport(
        _mock_transport(
            status=404,
            detail="连接器未接入: 'ghost'（可用: ['trae_cn']）",
        )
    )
    text = mcp_main._claim_text("ghost")
    assert "HTTP 404" in text
    assert "连接器未接入" in text
    assert "可用" in text


def test_base_url_env_override(monkeypatch):
    monkeypatch.setenv("KABAO_SERVER_URL", "http://127.0.0.1:9000/")
    assert mcp_main._base_url() == "http://127.0.0.1:9000"
    monkeypatch.delenv("KABAO_SERVER_URL")
    assert mcp_main._base_url() == "http://127.0.0.1:8000"
