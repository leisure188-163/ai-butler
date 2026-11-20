"""账户写入端点契约（ADR-033）：接入源绑定 / 手建 / 编辑 / 多槽凭据。

从 test_api.py 拆出（门禁单文件 600 行硬上限）：本文件只覆盖
`POST/PATCH /accounts` 与凭据槽位端点；接入源创建端点名册投影见
test_platforms_api.py。
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi.testclient import TestClient


def _client(tmp_path: Path) -> TestClient:
    os.environ["BUTLER_DB"] = str(tmp_path / "butler.db")
    os.environ["BUTLER_SCHEDULE"] = "0"
    os.environ["BUTLER_SYSTEM_NOTIFY"] = "0"
    from server.main import app

    return TestClient(app)


def _create_provider(client: TestClient) -> dict:
    resp = client.post(
        "/api/v1/platforms/providers",
        json={
            "platform_code": "my_relay",
            "platform_name": "我的中转",
            "kind": "relay",
            "base_url": "https://relay.example.com/v1",
            "protocol": "openai",
            "models": ["gpt-4o-mini"],
            "credential_kinds": ["api_key"],
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_provider_创建后账户可绑定(tmp_path):
    with _client(tmp_path) as client:
        provider = _create_provider(client)
        assert provider["origin"] == "user"
        assert provider["name_is_default"] is False
        assert provider["kind"] == "relay"
        assert provider["base_url"] == "https://relay.example.com/v1"

        created = client.post(
            "/api/v1/accounts",
            json={
                "platform_code": "my_relay",
                "account_code": "key1",
                "account_name": "主 key",
                "kind": "api_key",
                "secret": "sk-1",
                "label": "主 key",
            },
        )
        assert created.status_code == 200, created.text
        row = created.json()
        assert row["account_id"].startswith("acc_")  # 不透明主键，不再由平台/编码拼接
        assert row["account_code"] == "key1"
        assert row["origin"] == "manual"
        assert row["account_label"] == "主 key"  # 只显示账户自身，不拼平台名
        assert row["credentials"][0]["slot"] == "default"
        assert row["credentials"][0]["label"] == "主 key"


def test_手建账户_平台不存在与凭据类型校验(tmp_path):
    with _client(tmp_path) as client:
        assert client.post(
            "/api/v1/accounts",
            json={"platform_code": "no_such", "account_name": "x"},
        ).status_code == 404
        _create_provider(client)
        # 平台只申报了 api_key
        assert client.post(
            "/api/v1/accounts",
            json={"platform_code": "my_relay", "account_name": "x",
                  "kind": "cookie", "secret": "c"},
        ).status_code == 400
        # kind 与 secret 必须成对
        assert client.post(
            "/api/v1/accounts",
            json={"platform_code": "my_relay", "account_name": "x", "kind": "api_key"},
        ).status_code == 400
        assert client.post(
            "/api/v1/accounts",
            json={"platform_code": "my_relay", "account_name": "x"},
        ).status_code == 200  # 无凭据手建允许


def test_手建账户_编码重复409(tmp_path):
    with _client(tmp_path) as client:
        _create_provider(client)
        body = {"platform_code": "my_relay", "account_code": "key1", "account_name": "主 key"}
        assert client.post("/api/v1/accounts", json=body).status_code == 200
        assert client.post("/api/v1/accounts", json=body).status_code == 409


def test_patch账户_别名启停与身份(tmp_path):
    with _client(tmp_path) as client:
        _create_provider(client)
        account_id = client.post(
            "/api/v1/accounts",
            json={"platform_code": "my_relay", "account_code": "key1",
                  "account_name": "我的中转 · 主 key"},
        ).json()["account_id"]
        patched = client.patch(
            f"/api/v1/accounts/{account_id}",
            json={"alias": "中转主号", "active": False,
                  "base_url": "https://relay2.example.com/v1",
                  "identity": {"nickname": "逍遥酒鬼", "source_key": "sk_uid_1"}},
        )
        assert patched.status_code == 200, patched.text
        row = patched.json()
        assert row["alias"] == "中转主号"
        assert row["account_label"] == "中转主号"
        assert row["active"] is False
        assert row["base_url"] == "https://relay2.example.com/v1"
        assert row["identity"]["nickname"] == "逍遥酒鬼"
        assert row["account_code"] == "key1"  # 编址不动

        assert client.patch(
            f"/api/v1/accounts/{account_id}", json={"base_url": "ftp://x"}
        ).status_code == 400
        assert client.patch(
            f"/api/v1/accounts/{account_id}", json={"account_name": " "}
        ).status_code == 400


def test_凭据多槽位_追加与撤销(tmp_path):
    with _client(tmp_path) as client:
        _create_provider(client)
        account_id = client.post(
            "/api/v1/accounts",
            json={"platform_code": "my_relay", "account_code": "key1",
                  "account_name": "我的中转", "kind": "api_key", "secret": "sk-1"},
        ).json()["account_id"]
        added = client.post(
            f"/api/v1/accounts/{account_id}/credentials",
            json={"kind": "api_key", "secret": "sk-2", "slot": "backup", "label": "备用"},
        )
        assert added.status_code == 200, added.text
        assert added.json()["slot"] == "backup"
        assert added.json()["label"] == "备用"

        rows = client.get("/api/v1/accounts").json()
        slots = {c["slot"] for c in rows[0]["credentials"]}
        assert slots == {"default", "backup"}

        revoked = client.delete(f"/api/v1/accounts/{account_id}/credentials/api_key/backup")
        assert revoked.status_code == 200
        assert revoked.json()["revoked"] is True
        assert client.delete(
            f"/api/v1/accounts/{account_id}/credentials/api_key/backup"
        ).status_code == 404  # 已撤销 = 幂等 404
        # 默认槽仍在，未被连坐（撤销行保留可见，revoked=true）
        creds = {c["slot"]: c for c in client.get("/api/v1/accounts").json()[0]["credentials"]}
        assert creds["default"]["revoked"] is False
        assert creds["backup"]["revoked"] is True
