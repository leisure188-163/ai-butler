"""自定义平台 API（2026-11-18）：落盘 + 热加载 + 名册出现/消失。

端到端链路 = 声明式连接器目录（BUTLER_CUSTOM_CONNECTORS 指向 tmp）→
POST 校验落盘 → 热重载端口与名册 → GET /platforms 能看到 → DELETE 后消失。
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient


def _client(tmp_path: Path, monkeypatch) -> TestClient:
    monkeypatch.setenv("BUTLER_DB", str(tmp_path / "butler.db"))
    monkeypatch.setenv("BUTLER_CUSTOM_CONNECTORS", str(tmp_path / "connectors"))
    monkeypatch.setenv("BUTLER_SCHEDULE", "0")  # 关调度：热重载不启动 job
    monkeypatch.setenv("BUTLER_SYSTEM_NOTIFY", "0")
    from server.main import app

    return TestClient(app)


def _payload(code: str = "demo_site") -> dict:
    return {
        "code": code,
        "display": "Demo Site",
        "domain": "demo.example.com",
        "cookies": ["sid"],
        "status": {
            "request": {"method": "GET", "url": "https://demo.example.com/api/status"},
            "checked_in_path": "data.checked_in",
        },
        "claim": {
            "request": {"method": "POST", "url": "https://demo.example.com/api/claim"},
            "expect_ok": "0",
        },
        "schedule_times": ["08:35"],
    }


def test_create_lists_in_roster(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        resp = client.post("/api/v1/platforms/custom", json=_payload())
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["code"] == "demo_site"
        assert body["schedule_times"] == ["08:35"]
        assert "热加载" in body["message"]

        # 目录里真的落了连接器文件（不是只写一行数据库记录）
        target = tmp_path / "connectors" / "demo_site"
        assert (target / "manifest.yaml").is_file()
        assert (target / "declarative" / "provision.run.yaml").is_file()

        assert client.get("/api/v1/platforms/custom").json() == [
            {"code": "demo_site", "display": "Demo Site"}
        ]

        rows = {row["id"]: row for row in client.get("/api/v1/platforms").json()}
        assert "demo_site" in rows
        row = rows["demo_site"]
        assert row["platform_name"] == "Demo Site"
        assert row["kind"] == "web"
        assert row["capabilities"] == ["provision.run", "session.import"]
        assert row["credential_kinds"] == ["browser_cookie"]
        assert row["schedule_times"] == ["08:35"]
        assert row["active"] is True


def test_delete_removes_from_roster(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        assert client.post("/api/v1/platforms/custom", json=_payload()).status_code == 200
        resp = client.delete("/api/v1/platforms/custom/demo_site")
        assert resp.status_code == 200, resp.text
        assert resp.json()["deleted"] is True
        assert client.get("/api/v1/platforms/custom").json() == []
        rows = {row["id"] for row in client.get("/api/v1/platforms").json()}
        assert "demo_site" not in rows
        # 再删一次 = 404（如实提示，不假装成功）
        assert client.delete("/api/v1/platforms/custom/demo_site").status_code == 404


def test_builtin_collision_409(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        payload = _payload(code="trae_cn")
        assert client.post("/api/v1/platforms/custom", json=payload).status_code == 409


def test_invalid_code_422(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        assert client.post("/api/v1/platforms/custom", json=_payload(code="Bad-Code")).status_code == 422


def test_missing_cookies_422(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        payload = _payload()
        payload["cookies"] = []
        resp = client.post("/api/v1/platforms/custom", json=payload)
        assert resp.status_code == 422
        assert "cookie" in resp.json()["detail"]


def test_delete_builtin_409(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        assert client.delete("/api/v1/platforms/custom/trae_cn").status_code == 409
