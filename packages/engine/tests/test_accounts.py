"""账号名册适配器（A2-01 §1 → SQLite）：provider 索引 + 幂等 save。"""

from datetime import UTC, datetime

from kabao_core.domain.account import Account
from kabao_engine.accounts.sqlite import SqliteAccountRepository


def acct(aid: str, provider: str, display: str) -> Account:
    return Account(
        id=aid, provider=provider, display_name=display,
        created_at=datetime(2026, 11, 11, 8, 0, tzinfo=UTC),
    )


def test_save_get_list_roundtrip(tmp_path):
    repo = SqliteAccountRepository(tmp_path / "kabao.db")
    repo.save(acct("trae_cn:main", "trae_cn", "Trae CN"))
    repo.save(acct("qoder:main", "qoder", "Qoder"))

    loaded = repo.get("trae_cn:main")
    assert loaded is not None and loaded.provider == "trae_cn"
    assert len(repo.list_all()) == 2
    assert [a.id for a in repo.list_by_provider("trae_cn")] == ["trae_cn:main"]
    assert repo.get("ghost") is None


def test_save_upsert_idempotent(tmp_path):
    repo = SqliteAccountRepository(tmp_path / "kabao.db")
    repo.save(acct("trae_cn:main", "trae_cn", "Trae CN"))
    repo.save(acct("trae_cn:main", "trae_cn", "Trae CN"))  # 组合根重启幂等
    assert len(repo.list_all()) == 1


def test_persistence_across_instances(tmp_path):
    db = tmp_path / "kabao.db"
    SqliteAccountRepository(db).save(acct("trae_cn:main", "trae_cn", "Trae CN"))
    assert SqliteAccountRepository(db).get("trae_cn:main") is not None
