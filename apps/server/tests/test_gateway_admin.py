"""网关路由管理面契约测试（R4-G6）：TestClient + BUTLER_DB 注入临时库。

覆盖：GET 空表初始态 / PUT 合法表落盘回读 / PUT 非法表 422（含模型重复）/
落盘内容与网关装载同源（gateway load_routes 可直接装载）。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from butler_gateway.routing import load_routes


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, Path]:
    monkeypatch.setenv("BUTLER_DB", str(tmp_path / "butler.db"))
    monkeypatch.setenv("BUTLER_SCHEDULE", "0")
    from server.main import create_app

    app = create_app()
    with TestClient(app) as tc:
        routes_file = tmp_path / "gateway-routes.json"
        yield tc, routes_file


_VALID = {"routes": [{"model": "gpt-x", "accounts": ["trae_cn:main", "trae_cn:second"]}]}


def test_初始_空表合法态(client: tuple[TestClient, Path]) -> None:
    tc, routes_file = client
    resp = tc.get("/api/v1/gateway/routes")
    assert resp.status_code == 200
    body = resp.json()
    assert body["routes"] == []
    assert "重启" in body["takes_effect"]  # 生效时机如实注明
    assert not routes_file.exists()  # 只读不落盘


def test_put_合法表_落盘回读_网关同源可装载(client: tuple[TestClient, Path]) -> None:
    tc, routes_file = client
    resp = tc.put("/api/v1/gateway/routes", json=_VALID)
    assert resp.status_code == 200
    assert resp.json()["routes"] == _VALID["routes"]
    assert routes_file.exists()  # server 管、网关只读：同一文件
    table = load_routes(routes_file)  # 网关装载口径直接验证（校验单源）
    assert table.route("gpt-x") == ("trae_cn:main", "trae_cn:second")
    # GET 回读与网关装载结果一致
    assert tc.get("/api/v1/gateway/routes").json()["routes"] == _VALID["routes"]


def test_put_非法表_422_不落盘(client: tuple[TestClient, Path]) -> None:
    tc, routes_file = client
    bad = {"routes": [{"model": "m", "accounts": ["a:main"]},
                      {"model": "m", "accounts": ["b:main"]}]}
    resp = tc.put("/api/v1/gateway/routes", json=bad)
    assert resp.status_code == 422
    assert "重复路由规则" in resp.json()["detail"]
    assert not routes_file.exists()  # 校验失败绝不落盘


def test_put_缺字段_422(client: tuple[TestClient, Path]) -> None:
    tc, _ = client
    assert tc.put("/api/v1/gateway/routes", json={"routes": [{"model": "m"}]}).status_code == 422
    assert tc.put("/api/v1/gateway/routes", json={"routes": []}).status_code == 200  # 空表=清空合法
