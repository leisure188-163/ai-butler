"""G3 路由表（裁决 5/6）：解析校验 / 查找语义 / 文件装载三态。

- 裁决 5：账户顺序 = 优先级；失败转移由调用方（G5）按序重试，表只给候选
- 红线 5：配置非法显式报错——缺 routes 键 / 空模型 / 空账户 / 重复模型 /
  非数组 accounts / 坏 JSON 一律 ValueError，绝不静默降级
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from butler_gateway.routing import RouteTable, load_routes


# ── RouteTable.from_dict：解析 + 校验 ──

def test_from_dict_parses_ordered_rules() -> None:
    table = RouteTable.from_dict(
        {
            "routes": [
                {"model": "gpt-x", "accounts": ["a1", "a2"]},
                {"model": "claude-y", "accounts": ["b1"]},
            ]
        }
    )
    assert table.route("gpt-x") == ("a1", "a2")  # 顺序 = 优先级（裁决 5）
    assert table.route("claude-y") == ("b1",)
    assert table.route("unknown-model") == ()  # 未知模型 = 空候选（M1 精确匹配）
    assert table.account_ids == frozenset({"a1", "a2", "b1"})


def test_from_dict_rejects_missing_routes_key() -> None:
    with pytest.raises(ValueError, match="routes"):
        RouteTable.from_dict({})


def test_from_dict_rejects_non_object_rule() -> None:
    with pytest.raises(ValueError, match="须为对象"):
        RouteTable.from_dict({"routes": ["gpt-x"]})


def test_from_dict_rejects_non_list_accounts() -> None:
    """accounts 传字符串等非数组：显式拒绝，不静默按字符拆（红线 5）。"""
    with pytest.raises(ValueError, match="须为数组"):
        RouteTable.from_dict({"routes": [{"model": "m", "accounts": "a1"}]})


def test_from_dict_rejects_empty_model_or_accounts() -> None:
    with pytest.raises(ValueError, match="不得为空"):
        RouteTable.from_dict({"routes": [{"model": "", "accounts": ["a"]}]})
    with pytest.raises(ValueError, match="不得为空"):
        RouteTable.from_dict({"routes": [{"model": "m", "accounts": []}]})
    with pytest.raises(ValueError, match="不得为空"):
        RouteTable.from_dict({"routes": [{"model": "m", "accounts": ["a", ""]}]})


def test_from_dict_rejects_duplicate_model() -> None:
    data = {
        "routes": [
            {"model": "m", "accounts": ["a"]},
            {"model": "m", "accounts": ["b"]},  # 歧义配置：同一模型两条规则
        ]
    }
    with pytest.raises(ValueError, match="重复"):
        RouteTable.from_dict(data)


# ── load_routes：文件三态（缺 = 空表合法、合法装载、非法显式报错）──

def test_load_routes_missing_file_is_empty_table(tmp_path: Path) -> None:
    """文件缺失 = 空表（合法初始态）：服务首次启动无需先造配置。"""
    table = load_routes(tmp_path / "gateway-routes.json")
    assert table.rules == ()
    assert table.route("any") == ()


def test_load_routes_valid_file(tmp_path: Path) -> None:
    path = tmp_path / "gateway-routes.json"
    path.write_text(
        json.dumps({"routes": [{"model": "m1", "accounts": ["a", "b"]}]}),
        encoding="utf-8",
    )
    table = load_routes(path)
    assert table.route("m1") == ("a", "b")


def test_load_routes_bad_json_explicit_error(tmp_path: Path) -> None:
    path = tmp_path / "gateway-routes.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError, match="解析失败"):
        load_routes(path)


def test_load_routes_bad_schema_explicit_error(tmp_path: Path) -> None:
    path = tmp_path / "gateway-routes.json"
    path.write_text(json.dumps({"routes": [{"model": "m", "accounts": []}]}), encoding="utf-8")
    with pytest.raises(ValueError, match="校验失败"):
        load_routes(path)
