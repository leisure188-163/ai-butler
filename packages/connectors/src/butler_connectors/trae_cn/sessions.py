"""trae_cn 会话扫描器（R5-S1，ADR-013 裁决 1/2）：SessionSourcePort.scan_sessions 实装。

- **只读**（plans/03 §0 纪律）：state.vscdb 一律 ``file:...?mode=ro`` 打开，
  只查 key 名不取值（key 含账户前缀即可绑定；value 可能含敏感内容）
- 对象 = workspace kind（ADR-013 首批；PROTOCOL §10：conversation 正文在
  服务端，本地不可迁）：
  - ``User/workspaceStorage/<hash>/state.vscdb`` → 每 (工作区, 账户前缀) 一条
    sighting（location 指到工作区目录）
  - ``User/globalStorage/state.vscdb`` → 每 账户前缀 一条 sighting
  - ``User/settings.json`` / ``User/snippets/`` / ``User/History/`` → 客户端
    全局上下文，无账户前缀 → device_ref=None 如实产出（绑定由用例侧分列）
- 客户端运行中持锁/文件缺失 = 如实跳过该候选（不猜形状，plans/02 §0 同款）
- 路径数据根可注入（测试用 tmp_path 造假目录；生产 = 平台默认路径）
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Iterable
from pathlib import Path

from butler_core.accounts.domain import SessionKind, SessionLevel, SessionSighting

_AHA_KEY_PREFIX = re.compile(r"^(\d{8,20})[:_]")  # PROTOCOL §10：账户数字 id 前缀
_DEFAULT_DATA_ROOT = Path.home() / "Library" / "Application Support" / "Trae CN"


def _account_prefixes(vscdb: Path) -> set[str]:
    """只读枚举 state.vscdb ItemTable key 里的账户数字前缀（读不了 = 空集如实）。"""
    if not vscdb.is_file():
        return set()
    try:
        conn = sqlite3.connect(f"file:{vscdb}?mode=ro", uri=True)
    except sqlite3.Error:
        return set()
    prefixes: set[str] = set()
    try:
        rows = conn.execute("SELECT key FROM ItemTable").fetchall()
        for (key,) in rows:
            match = _AHA_KEY_PREFIX.match(key or "")
            if match:
                prefixes.add(match.group(1))
    except sqlite3.Error:
        return set()  # 锁死/损坏：如实空集，不猜
    finally:
        conn.close()
    return prefixes


class TraeSessionScanner:
    """实现 SessionSourcePort.scan_sessions（只读枚举，形状见模块 docstring）。"""

    provider = "trae_cn"

    def __init__(self, data_root: Path = _DEFAULT_DATA_ROOT) -> None:
        self._root = data_root

    def scan_sessions(self, provider: str) -> Iterable[SessionSighting]:
        if provider != self.provider:
            return []  # 通道不匹配：如实空（不是错误）
        user = self._root / "User"
        sightings: list[SessionSighting] = []
        # 工作区级：workspaceStorage/<hash>/（绑定 = 该库里的账户前缀）
        workspace_storage = user / "workspaceStorage"
        if workspace_storage.is_dir():
            for ws_dir in sorted(p for p in workspace_storage.iterdir() if p.is_dir()):
                for device in sorted(_account_prefixes(ws_dir / "state.vscdb")):
                    sightings.append(
                        SessionSighting(
                            location=str(ws_dir),
                            kind=SessionKind.WORKSPACE,
                            level=SessionLevel.LOCAL,
                            device_ref=device,
                        )
                    )
        # 全局级：globalStorage/state.vscdb（账户前缀 keys 同款）
        for device in sorted(_account_prefixes(user / "globalStorage" / "state.vscdb")):
            sightings.append(
                SessionSighting(
                    location=str(user / "globalStorage" / "state.vscdb"),
                    kind=SessionKind.WORKSPACE,
                    level=SessionLevel.LOCAL,
                    device_ref=device,
                )
            )
        # 客户端全局上下文：settings / snippets / History（无账户前缀 → 如实 unbound）
        for rel in ("settings.json", "snippets", "History"):
            candidate = user / rel
            if candidate.exists():
                sightings.append(
                    SessionSighting(
                        location=str(candidate),
                        kind=SessionKind.WORKSPACE,
                        level=SessionLevel.LOCAL,
                        device_ref=None,
                    )
                )
        return sightings


def build_session_source() -> TraeSessionScanner:
    """Registry.session_source 工厂（显式契约，禁猜类名）。"""
    return TraeSessionScanner()
