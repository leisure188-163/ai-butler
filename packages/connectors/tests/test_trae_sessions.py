"""trae 会话扫描器测试（R5-S1）：tmp_path 造假数据根 + 真 SQLite，只读语义钉死。"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from butler_connectors.trae_cn.sessions import TraeSessionScanner, build_session_source


def _make_vscdb(path: Path, keys: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE IF NOT EXISTS ItemTable (key TEXT PRIMARY KEY, value BLOB)")
    conn.executemany(
        "INSERT OR REPLACE INTO ItemTable (key, value) VALUES (?, ?)",
        [(k, b"x") for k in keys],
    )
    conn.commit()
    conn.close()


def _make_root(tmp_path: Path) -> Path:
    root = tmp_path / "Trae CN"
    _make_vscdb(
        root / "User" / "workspaceStorage" / "hash1" / "state.vscdb",
        ["1352866089939851:draft:session:abc:code", "other.key"],
    )
    _make_vscdb(
        root / "User" / "workspaceStorage" / "hash2" / "state.vscdb",
        ["2363270254575433:AI.agent.mode"],
    )
    _make_vscdb(
        root / "User" / "globalStorage" / "state.vscdb",
        ["1352866089939851_ai-chat:sessionRelation:globalModeMap", "plain"],
    )
    (root / "User" / "settings.json").write_text("{}", encoding="utf-8")
    return root


def test_工作区与全局按前缀绑定_全局上下文如实unbound(tmp_path: Path) -> None:
    scanner = TraeSessionScanner(data_root=_make_root(tmp_path))
    sightings = list(scanner.scan_sessions("trae_cn"))
    bound = [s for s in sightings if s.device_ref]
    unbound = [s for s in sightings if s.device_ref is None]
    # 工作区 hash1 → 135…；hash2 → 236…；globalStorage → 135…：共 3 条绑定观测
    assert {(Path(s.location).name, s.device_ref) for s in bound} == {
        ("hash1", "1352866089939851"),
        ("hash2", "2363270254575433"),
        ("state.vscdb", "1352866089939851"),
    }
    assert all(s.kind.value == "workspace" and s.level.value == "local" for s in sightings)
    assert {Path(u.location).name for u in unbound} == {"settings.json"}


def test_缺workspaceStorage目录_如实空(tmp_path: Path) -> None:
    scanner = TraeSessionScanner(data_root=tmp_path)
    assert list(scanner.scan_sessions("trae_cn")) == []


def test_通道不匹配_如实空(tmp_path: Path) -> None:
    scanner = TraeSessionScanner(data_root=tmp_path)
    assert list(scanner.scan_sessions("qoder_cn")) == []


def test_坏库_如实跳过不爆(tmp_path: Path) -> None:
    root = tmp_path / "Trae CN"
    bad = root / "User" / "workspaceStorage" / "hash1" / "state.vscdb"
    bad.parent.mkdir(parents=True)
    bad.write_bytes(b"not-a-sqlite")
    sightings = list(TraeSessionScanner(data_root=root).scan_sessions("trae_cn"))
    assert sightings == []  # 坏库如实空集，不猜形状


def test_工厂契约() -> None:
    scanner = build_session_source()
    assert scanner.platform_code == "trae_cn"
