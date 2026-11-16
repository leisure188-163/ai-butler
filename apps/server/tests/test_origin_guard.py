"""ADR-014 浏览器边界验收：OriginGuard 三态 + CORS 收窄 + DNS rebinding 挡板。

为什么这个测试必须存在：CORS 只约束"读"，跨站"写"能不能送达只有服务端能挡——
这层漏了，用户访问任意网页都等于把本机主控 API 交出去。所以本组用例钉死：
- 未授权 Origin 的**读**和**写**都 403，且写请求确实没有落账
- 开发服务器 Origin / 回环同源 / 无 Origin（curl·CLI·MCP·桌面壳）三态放行
- Host 与 Origin 同为攻击者域名（DNS rebinding）不放行
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from server.security import DEFAULT_ALLOWED_ORIGINS, allowed_origins, origin_allowed

_EVIL = "https://evil.example"


def _client(tmp_path: Path, base_url: str = "http://127.0.0.1:8000") -> TestClient:
    os.environ["BUTLER_DB"] = str(tmp_path / "butler.db")
    os.environ["BUTLER_SCHEDULE"] = "0"
    from server.main import app

    return TestClient(app, base_url=base_url)


# ── 拦截态：跨站页面 ──

def test_cross_site_read_blocked(tmp_path):
    with _client(tmp_path) as client:
        r = client.get("/api/v1/accounts", headers={"Origin": _EVIL})
        assert r.status_code == 403
        assert "跨站页面禁止访问" in r.json()["detail"]
        assert "access-control-allow-origin" not in r.headers  # 不给跨站任何读的机会


def test_cross_site_write_blocked_without_side_effect(tmp_path):
    with _client(tmp_path) as client:
        r = client.post("/api/v1/runs", json={}, headers={"Origin": _EVIL})
        assert r.status_code == 403
        # 真没执行：不带 Origin 的本地读取看不到任何 Run
        assert client.get("/api/v1/runs").json() == []


def test_cross_site_preflight_blocked(tmp_path):
    with _client(tmp_path) as client:
        r = client.options(
            "/api/v1/accounts",
            headers={"Origin": _EVIL, "Access-Control-Request-Method": "GET"},
        )
        assert r.status_code == 403  # 预检也拿不到放行


def test_dns_rebinding_host_and_origin_blocked(tmp_path):
    """Host 与 Origin 都是攻击者域名（rebinding）→ 不做同源放行。"""
    with _client(tmp_path, base_url="http://evil.example:8000") as client:
        r = client.get("/api/v1/accounts", headers={"Origin": "http://evil.example:8000"})
        assert r.status_code == 403


# ── 放行态 ──

def test_dev_server_origin_allowed(tmp_path):
    with _client(tmp_path) as client:
        origin = "http://localhost:5173"
        r = client.get("/api/v1/accounts", headers={"Origin": origin})
        assert r.status_code == 200
        assert r.headers["access-control-allow-origin"] == origin


def test_dev_server_post_allowed(tmp_path):
    """Vite 代理转发同源 POST 会带 5173 Origin，不能被误伤。"""
    with _client(tmp_path) as client:
        r = client.post(
            "/api/v1/runs",
            json={},
            headers={"Origin": "http://127.0.0.1:5173"},
        )
        # 放行到路由（载荷非法由路由自己 422 判，不是 403）
        assert r.status_code != 403


def test_same_origin_loopback_allowed(tmp_path):
    """桌面壳/自托管页直连 127.0.0.1:8000 → Origin 与 Host 同为回环。"""
    with _client(tmp_path) as client:
        r = client.get(
            "/api/v1/accounts", headers={"Origin": "http://127.0.0.1:8000"}
        )
        assert r.status_code == 200


def test_no_origin_local_tools_allowed(tmp_path):
    """curl / CLI / MCP / 网关控制面不带 Origin —— 不是浏览器攻击面。"""
    with _client(tmp_path) as client:
        assert client.get("/api/v1/accounts").status_code == 200


# ── 白名单构造 ──

def test_allowed_origins_env_append(monkeypatch):
    monkeypatch.setenv("BUTLER_ALLOWED_ORIGINS", "http://192.168.1.9:5173/, ,")
    got = allowed_origins()
    assert DEFAULT_ALLOWED_ORIGINS[0] in got  # 默认项不丢
    assert "http://192.168.1.9:5173" in got  # 追加项去尾部斜杠
    assert got.count("http://192.168.1.9:5173") == 1  # 空项被剔、重复不叠


@pytest.mark.parametrize(
    ("origin", "host", "expect"),
    [
        ("http://localhost:5173", "127.0.0.1:8000", True),  # 静态白名单
        ("http://127.0.0.1:8000", "127.0.0.1:8000", True),  # 回环同源
        ("http://127.0.0.1:8000", "localhost:8000", False),  # 端口/主机不同名 = 非同源
        ("http://evil.example", "evil.example", False),  # 非回环一律不放
        ("null", "127.0.0.1:8000", False),  # file:// 的 null Origin 不放（桌面壳走直连）
        ("", "127.0.0.1:8000", False),  # 畸形 Origin 不猜
    ],
)
def test_origin_allowed_matrix(origin, host, expect):
    assert origin_allowed(origin, host) is expect
