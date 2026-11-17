"""G1 骨架验收（ADR-012）：key 管理 / Bearer 原语 / /health 可观测 / 主控可达两态。

- 不碰真网络：主控探测走 httpx.MockTransport
- 不碰真数据根：key 文件经 BUTLER_GATEWAY_KEY_FILE 指 tmp_path
"""

from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from butler_gateway import auth, config

# NTFS 不承载 POSIX 权限位（st_mode 恒为 0o666 系），0o600 断言仅在 POSIX 有意义
_POSIX_PERMS = sys.platform != "win32"


# ── 鉴权 key 管理（裁决 4）──

def test_key_generate_then_reload_idempotent(tmp_path: Path) -> None:
    key_file = tmp_path / "gateway-auth-key"
    first = auth.load_or_create(key_file)
    assert first and len(first) >= 40  # token_urlsafe(32) ≈ 43 字符
    if _POSIX_PERMS:
        assert stat.S_IMODE(key_file.stat().st_mode) == 0o600
    assert auth.load_or_create(key_file) == first  # 重启不换 key（客户端零改动）


def test_key_file_empty_rejected(tmp_path: Path) -> None:
    key_file = tmp_path / "k"
    key_file.write_text("   \n", encoding="utf-8")
    with pytest.raises(SystemExit):
        auth.load_or_create(key_file)


def test_key_perms_widened_get_fixed(tmp_path: Path) -> None:
    key_file = tmp_path / "k"
    key_file.write_text("abc\n", encoding="utf-8")
    os.chmod(key_file, 0o644)
    assert auth.load_or_create(key_file) == "abc"
    if _POSIX_PERMS:
        assert stat.S_IMODE(key_file.stat().st_mode) == 0o600  # 危险状态不留存


def test_check_bearer_cases() -> None:
    assert auth.check_bearer("Bearer abc", "abc")
    assert auth.check_bearer("bearer abc", "abc")  # scheme 大小写不敏感
    assert not auth.check_bearer(None, "abc")
    assert not auth.check_bearer("Basic abc", "abc")
    assert not auth.check_bearer("Bearer wrong", "abc")
    assert not auth.check_bearer("Bearer", "abc")  # 空 token


def test_key_fingerprint_stable_and_short() -> None:
    fp = auth.key_fingerprint("some-key")
    assert len(fp) == 12
    assert fp == auth.key_fingerprint("some-key")


# ── 配置解析（红线 5：非法显式报错）──

def test_port_env_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BUTLER_GATEWAY_PORT", raising=False)
    assert config.gateway_port() == 8100
    monkeypatch.setenv("BUTLER_GATEWAY_PORT", "abc")
    with pytest.raises(SystemExit):
        config.gateway_port()
    monkeypatch.setenv("BUTLER_GATEWAY_PORT", "70000")
    with pytest.raises(SystemExit):
        config.gateway_port()


# ── /health 可观测 + 主控可达性（裁决 2）──

def _make_client(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    handler,
) -> TestClient:
    monkeypatch.setenv("BUTLER_GATEWAY_KEY_FILE", str(tmp_path / "gateway-auth-key"))
    monkeypatch.setenv(
        "BUTLER_GATEWAY_ROUTES_FILE", str(tmp_path / "gateway-routes.json")
    )
    monkeypatch.setenv("BUTLER_SERVER_URL", "http://control.test")
    # 测试隔离（2026-11-16 落地）：platform lifespan 会 build_engine(default_db_path())——
    # 不隔离则读写真实数据根，真库被占/被锁时引发 disk I/O error（四次事故）
    monkeypatch.setenv("BUTLER_DB", str(tmp_path / "butler.db"))
    import butler_gateway.app as gw_app

    monkeypatch.setattr(
        gw_app, "_transport_factory", lambda: httpx.MockTransport(handler)
    )
    return TestClient(gw_app.create_app())


def test_health_with_server_up(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"status": "ok"})

    with _make_client(monkeypatch, tmp_path, handler) as client:
        resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["bind"] == "127.0.0.1"  # 裁决 4：只绑回环
    assert body["auth_key_file"].endswith("gateway-auth-key")
    assert len(body["auth_key_fingerprint"]) == 12
    ctl = body["control"]
    assert ctl["server_url"] == "http://control.test"
    assert ctl["reachable"] is True
    assert isinstance(ctl["latency_ms"], float)
    assert ctl["error"] is None
    assert calls and calls[0].url.path == "/health"
    assert body["routes"]["rule_count"] == 0  # 路由文件缺失 = 空表（合法初始态）


def test_health_with_server_down_still_ok(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with _make_client(monkeypatch, tmp_path, handler) as client:
        body = client.get("/health").json()
    assert body["status"] == "ok"  # 网关自身活着，主控不可达是如实上报的事实
    assert body["control"]["reachable"] is False
    assert "ConnectError" in body["control"]["error"]
    assert body["control"]["latency_ms"] is None


def test_health_reflects_loaded_routes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """G3：/health 暴露路由表装载态——文件规则进 health 可观测（网关只读）。"""
    routes_path = tmp_path / "gateway-routes.json"
    routes_path.write_text(
        json.dumps({"routes": [{"model": "m1", "accounts": ["a", "b", "c"]}]}),
        encoding="utf-8",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "ok"})

    with _make_client(monkeypatch, tmp_path, handler) as client:
        body = client.get("/health").json()
    routes = body["routes"]
    assert routes["rules_file"].endswith("gateway-routes.json")
    assert routes["rule_count"] == 1
    assert routes["models"] == ["m1"]
    assert routes["account_count"] == 3


def test_probe_ttl_reuses_result(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(200, json={"status": "ok"})

    with _make_client(monkeypatch, tmp_path, handler) as client:
        first = client.get("/health").json()
        second = client.get("/health").json()
    assert len(calls) == 1  # TTL 窗口内不重复探测
    assert first["control"]["checked_at"] == second["control"]["checked_at"]
