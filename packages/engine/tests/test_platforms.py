"""平台册（acc_platform）适配器与同步用例测试（ADR-021）。

真 SQLite tmp_path；同步语义 = upsert 全量事实 + 缺失平台落 deprecated（幂等，
不删行）。表名纪律见 A4-01 §5。
"""

from __future__ import annotations

from butler_core.platforms.domain import PlatformEntry
from butler_core.platforms.usecases.sync_platforms import SyncPlatforms
from butler_engine.platforms.sqlite import SqlitePlatformRepository

from datetime import datetime, UTC


def _entry(code: str, name: str, created_at: datetime) -> PlatformEntry:
    return PlatformEntry(
        platform_code=code,
        platform_name=name,
        created_at=created_at,
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
