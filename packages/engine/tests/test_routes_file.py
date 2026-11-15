"""路由表 JSON 文件存储测试（R4-G6）：tmp_path 真文件 + 原子写 + 缺失/非法语义。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from butler_core.execution.gateway_routes import RouteTable
from butler_engine.gateway.routes_file import FileGatewayRoutesStore


@pytest.fixture()
def store(tmp_path: Path) -> FileGatewayRoutesStore:
    return FileGatewayRoutesStore(tmp_path / "gateway-routes.json")


def test_缺失_空表合法初始态(store: FileGatewayRoutesStore) -> None:
    assert store.load().rules == ()


def test_save_load_往返保真(store: FileGatewayRoutesStore) -> None:
    table = RouteTable.from_dict(
        {"routes": [{"model": "gpt-x", "accounts": ["trae_cn:main", "trae_cn:second"]}]}
    )
    store.save(table)
    assert store.load() == table
    # 落盘内容 = 声明式 JSON（网关 load_routes 同一文件可直接装载）
    data = json.loads(store.path.read_text(encoding="utf-8"))
    assert data == {"routes": [{"model": "gpt-x", "accounts": ["trae_cn:main", "trae_cn:second"]}]}


def test_save_原子替换_无tmp残留(store: FileGatewayRoutesStore) -> None:
    store.save(RouteTable.from_dict({"routes": [{"model": "m1", "accounts": ["a:main"]}]}))
    store.save(RouteTable.from_dict({"routes": [{"model": "m2", "accounts": ["b:main"]}]}))
    assert [r.model for r in store.load().rules] == ["m2"]  # 整表替换
    assert not store.path.with_suffix(".json.tmp").exists()  # 无半截文件残留


def test_load_非法文件_显式报错(tmp_path: Path) -> None:
    path = tmp_path / "gateway-routes.json"
    path.write_text("not-json", encoding="utf-8")
    with pytest.raises(ValueError, match="解析失败"):
        FileGatewayRoutesStore(path).load()
    path.write_text('{"routes": "bad"}', encoding="utf-8")
    with pytest.raises(ValueError, match="校验失败"):
        FileGatewayRoutesStore(path).load()


def test_save_建父目录(tmp_path: Path) -> None:
    store = FileGatewayRoutesStore(tmp_path / "sub" / "gateway-routes.json")
    assert not store.path.parent.exists()
    store.save(RouteTable(rules=()))
    assert store.path.exists()  # 空表也如实落盘（替换即真相）
