"""平台册（plat_platform）适配器与同步用例测试（ADR-021/022）。

真 SQLite tmp_path；同步语义 = upsert 全量事实 + 缺失平台落 deprecated（幂等，
不删行）。表名纪律见 A4-01 §5。
"""

from __future__ import annotations

from butler_core.platforms.domain import PlatformEntry
from butler_core.platforms.usecases.sync_platforms import SyncPlatforms
from butler_engine.platforms.sqlite import SqlitePlatformRepository

from datetime import datetime, UTC


def _entry(code: str, name: str, created_at: datetime, kind: str = "client") -> PlatformEntry:
    return PlatformEntry(
        platform_code=code,
        platform_name=name,
        created_at=created_at,
        platform_kind=kind,
        capabilities=("provision.run",),
        credential_kinds=("cookie",),
        schedule_times=("00:05",),
    )


def test_upsert_get_roundtrip(tmp_path) -> None:
    repo = SqlitePlatformRepository(tmp_path / "butler.db")
    created = datetime(2026, 11, 17, tzinfo=UTC)
    repo.upsert(_entry("doubao_cn", "豆包", created))
    loaded = repo.get("doubao_cn")
    assert loaded is not None
    assert loaded.platform_code == "doubao_cn"
    assert loaded.platform_name == "豆包"
    assert loaded.platform_kind == "client"
    assert loaded.client_version == ""
    assert loaded.capabilities == ("provision.run",)
    assert loaded.credential_kinds == ("cookie",)
    assert loaded.schedule_times == ("00:05",)
    assert loaded.is_active and loaded.deprecated_at is None


def test_upsert_重复_事实更新_幂等(tmp_path) -> None:
    repo = SqlitePlatformRepository(tmp_path / "butler.db")
    created = datetime(2026, 11, 17, tzinfo=UTC)
    repo.upsert(_entry("doubao_cn", "豆包", created))
    repo.upsert(_entry("doubao_cn", "豆包（更名）", created))
    assert repo.list_all()[0].platform_name == "豆包（更名）"
    assert len(repo.list_all()) == 1  # UPSERT 不漂移代理键


def test_sync_缺失平台落deprecated_幂等不删行(tmp_path) -> None:
    repo = SqlitePlatformRepository(tmp_path / "butler.db")
    sync = SyncPlatforms(platforms=repo)
    created = datetime(2026, 11, 17, tzinfo=UTC)
    facts = (_entry("doubao_cn", "豆包", created), _entry("trae_cn", "Trae", created))
    sync.execute(facts)
    assert repo.deprecate_missing(frozenset(f.platform_code for f in facts)) == []  # 全部在场 = 幂等空
    # 下一轮 facts 只剩 doubao → trae 落 deprecated
    deprecated = sync.execute((facts[0],))
    assert deprecated == ["trae_cn"]
    trae = repo.get("trae_cn")
    assert trae is not None and trae.deprecated_at is not None  # 不删行，审计可溯
    # 再跑一轮：已标记过 = 幂等空
    assert sync.execute((facts[0],)) == []
    assert repo.get("trae_cn") is not None


def test_空code_显式拒绝(tmp_path) -> None:
    import pytest

    from butler_core.platforms.domain import PlatformInvalid

    repo = SqlitePlatformRepository(tmp_path / "butler.db")
    with pytest.raises(PlatformInvalid):
        _entry("", "空 code", datetime(2026, 11, 17, tzinfo=UTC))


def test_平台类型_web与client_roundtrip(tmp_path) -> None:
    """platform_kind 词表落库往返；未知值显式拒绝（core 校验）。"""
    repo = SqlitePlatformRepository(tmp_path / "butler.db")
    created = datetime(2026, 11, 18, tzinfo=UTC)
    repo.upsert(_entry("agentrouter", "AgentRouter", created, kind="web"))
    repo.upsert(_entry("doubao_cn", "豆包", created, kind="client"))
    kinds = {p.platform_code: p.platform_kind for p in repo.list_all()}
    assert kinds == {"agentrouter": "web", "doubao_cn": "client"}


def test_老库补列后物理列序按DDL重建(tmp_path) -> None:
    """SQLite ADD COLUMN 只能追加：老库补列后须重建校正物理列序（零丢失）。"""
    import sqlite3

    db = tmp_path / "butler.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE plat_platform (
            id TEXT PRIMARY KEY,
            platform_code TEXT NOT NULL UNIQUE,
            platform_name TEXT NOT NULL,
            capabilities TEXT NOT NULL DEFAULT '[]',
            credential_kinds TEXT NOT NULL DEFAULT '[]',
            schedule_times TEXT NOT NULL DEFAULT '[]',
            is_active INTEGER NOT NULL DEFAULT 1,
            deprecated_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            client_version TEXT NOT NULL DEFAULT ''
        );
        """
    )
    conn.execute(
        "INSERT INTO plat_platform (id, platform_code, platform_name, created_at, updated_at, client_version) "
        "VALUES ('1', 'doubao_cn', '豆包', '2026-11-18T00:00:00+00:00', '2026-11-18T00:00:00+00:00', '2.36.8')"
    )
    conn.commit()
    conn.close()

    repo = SqlitePlatformRepository(db)  # 触发补列 + 列序重建
    cols = [
        r[1]
        for r in sqlite3.connect(db).execute("PRAGMA table_info(plat_platform)").fetchall()
    ]
    assert cols == [
        "id", "platform_code", "platform_name", "name_override", "platform_kind", "client_version",
        "capabilities", "credential_kinds", "schedule_times", "schedule_override",
        "is_active", "deprecated_at", "created_at", "updated_at",
    ]
    loaded = repo.get("doubao_cn")  # 行数据零丢失（含原 client_version）
    assert loaded is not None and loaded.client_version == "2.36.8"
    assert loaded.platform_kind == ""


def test_schedule_override_写入_恢复与不冲掉(tmp_path) -> None:
    """调度覆盖（2026-11-18）：写覆盖→读回；同步事实不覆盖用户覆盖；None 恢复默认。"""
    repo = SqlitePlatformRepository(tmp_path / "butler.db")
    created = datetime(2026, 11, 17, tzinfo=UTC)
    repo.upsert(_entry("doubao_cn", "豆包", created))
    assert repo.get("doubao_cn").schedule_override is None  # 默认跟随 manifest

    updated = repo.set_schedule_override("doubao_cn", ("21:15", "09:15"))
    assert updated is not None
    assert updated.schedule_override == ("21:15", "09:15")
    assert updated.schedule_times == ("00:05",)  # manifest 缺省不被改写（可恢复）

    # 下一轮 manifest 同步（不带 override）不得冲掉用户覆盖
    repo.upsert(_entry("doubao_cn", "豆包", created))
    assert repo.get("doubao_cn").schedule_override == ("21:15", "09:15")

    # 恢复默认 = None
    reset = repo.set_schedule_override("doubao_cn", None)
    assert reset is not None and reset.schedule_override is None

    # 平台不存在 = None（调用方显式 404）
    assert repo.set_schedule_override("nope", ("09:15",)) is None
