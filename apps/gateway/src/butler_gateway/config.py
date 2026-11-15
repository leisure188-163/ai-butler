"""网关进程配置的唯一解析口（ADR-012 裁决 4：绑定 127.0.0.1、不设用户体系）。

- 端口默认 8100，`BUTLER_GATEWAY_PORT` 整数覆盖；非法值显式报错退出（红线 5）
- 鉴权 key 文件默认 = 数据根 `gateway-auth-key`（`BUTLER_GATEWAY_KEY_FILE` 覆盖，
  测试/便携模式）；数据根复用 butler_engine.bridge.default_db_path() 的目录
  （A4-01 §5 数据布局；端只准经 bridge 触引擎）
- 主控 server 地址默认 `http://127.0.0.1:8000`，`BUTLER_SERVER_URL` 覆盖
- 路由表文件默认 = 数据根 `gateway-routes.json`（`BUTLER_GATEWAY_ROUTES_FILE`
  覆盖，测试/便携模式）；声明式规则、网关只读（ADR-012 裁决 6，G3）
"""

from __future__ import annotations

import os
from pathlib import Path

DEFAULT_PORT = 8100
DEFAULT_SERVER_URL = "http://127.0.0.1:8000"
KEY_FILE_NAME = "gateway-auth-key"
ROUTES_FILE_NAME = "gateway-routes.json"


def gateway_host() -> str:
    """绑定面。裁决 4 是硬约束：只绑回环，绝不暴露局域网（ToS 边界，A1-01 §6）。"""
    return "127.0.0.1"


def gateway_port() -> int:
    raw = os.environ.get("BUTLER_GATEWAY_PORT")
    if not raw:
        return DEFAULT_PORT
    try:
        port = int(raw)
    except ValueError as exc:
        raise SystemExit(f"BUTLER_GATEWAY_PORT 非法: {raw!r}（须为整数）") from exc
    if not 1 <= port <= 65535:
        raise SystemExit(f"BUTLER_GATEWAY_PORT 越界: {port}（须在 1-65535）")
    return port


def key_file() -> Path:
    explicit = os.environ.get("BUTLER_GATEWAY_KEY_FILE")
    if explicit:
        return Path(explicit).expanduser()
    from butler_engine.bridge import default_db_path  # 端触引擎只经 bridge（ADR-001）

    return default_db_path().parent / KEY_FILE_NAME


def routes_file() -> Path:
    explicit = os.environ.get("BUTLER_GATEWAY_ROUTES_FILE")
    if explicit:
        return Path(explicit).expanduser()
    from butler_engine.bridge import default_db_path  # 端触引擎只经 bridge（ADR-001）

    return default_db_path().parent / ROUTES_FILE_NAME


def server_url() -> str:
    return (os.environ.get("BUTLER_SERVER_URL") or DEFAULT_SERVER_URL).rstrip("/")
