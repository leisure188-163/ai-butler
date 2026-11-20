"""账号名册适配器（A2-01 §1 → SQLite）：platform 索引 + 幂等 save。"""

from datetime import UTC, datetime

import pytest

from butler_core.accounts.domain import Account, AccountInvalid, AccountIdentity
from butler_engine.accounts.sqlite import SqliteAccountRepository


def acct(aid: str, platform: str, display: str) -> Account:
    return Account(
        id=aid, platform_code=platform, account_name=display,
        created_at=datetime(2026, 11, 11, 8, 0, tzinfo=UTC),
    )


def test_save_get_list_roundtrip(tmp_path):
    repo = SqliteAccountRepository(tmp_path / "butler.db")
    repo.save(acct("trae_cn:main", "trae_cn", "Trae CN"))
    repo.save(acct("qoder:main", "qoder", "Qoder"))

    loaded = repo.get("trae_cn:main")
    assert loaded is not None and loaded.platform_code == "trae_cn"
    assert len(repo.list_all()) == 2
    assert [a.id for a in repo.list_by_platform("trae_cn")] == ["trae_cn:main"]
    assert repo.get("ghost") is None


def test_save_upsert_idempotent(tmp_path):
    repo = SqliteAccountRepository(tmp_path / "butler.db")
    repo.save(acct("trae_cn:main", "trae_cn", "Trae CN"))
    repo.save(acct("trae_cn:main", "trae_cn", "Trae CN"))  # 组合根重启幂等
    assert len(repo.list_all()) == 1


def test_remove_只删账户行(tmp_path):
    repo = SqliteAccountRepository(tmp_path / "butler.db")
    repo.save(acct("trae_cn:main", "trae_cn", "Trae CN"))
    assert repo.remove("trae_cn:main") is True
    assert repo.get("trae_cn:main") is None
    assert repo.remove("trae_cn:main") is False  # 不存在 = False（端 404）


def test_persistence_across_instances(tmp_path):
    db = tmp_path / "butler.db"
    SqliteAccountRepository(db).save(acct("trae_cn:main", "trae_cn", "Trae CN"))
    assert SqliteAccountRepository(db).get("trae_cn:main") is not None


def test_identity_origin_last_seen_roundtrip(tmp_path):
    repo = SqliteAccountRepository(tmp_path / "butler.db")
    a = Account(
        id="doubao_cn:u1",
        platform_code="doubao_cn",
        account_code="u1",
        account_name="豆包 · 小号",
        created_at=datetime(2026, 11, 11, 8, 0, tzinfo=UTC),
        identity=AccountIdentity(nickname="逍遥酒鬼", source_key="sec_uid_1"),
        origin="manual",
        last_seen_at=datetime(2026, 11, 20, 2, 0, tzinfo=UTC),
    )
    repo.save(a)
    loaded = repo.get("doubao_cn:u1")
    assert loaded.identity.nickname == "逍遥酒鬼"
    assert loaded.identity.source_key == "sec_uid_1"
    assert loaded.origin == "manual"
    assert loaded.last_seen_at.isoformat() == a.last_seen_at.isoformat()


def test_空身份落NULL且读回空对象(tmp_path):
    repo = SqliteAccountRepository(tmp_path / "butler.db")
    repo.save(acct("trae_cn:main", "trae_cn", "Trae CN"))
    assert repo.get("trae_cn:main").identity.is_empty


def test_编址冻结_已登记code不一致时显式拒绝(tmp_path):
    import sqlite3

    db = tmp_path / "butler.db"
    repo = SqliteAccountRepository(db)  # 建表
    # 模拟历史脏行：account_id 与 account_code 不一致（旧迁移遗留）
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO acc_account (account_id, platform_code, account_code, account_name,"
        " created_at, updated_at) VALUES ('x:main','x','legacy','旧行',"
        " '2026-11-11T08:00:00+00:00','2026-11-11T08:00:00+00:00')"
    )
    conn.commit()
    conn.close()

    # 按规范 id 写回 = 想把 legacy 改成 main → 编址冻结，拒绝
    acc = acct("x:main", "x", "新名")
    with pytest.raises(AccountInvalid):
        repo.save(acc)

    # 同编址改名/改状态照常允许
    repo.save(acct("trae_cn:main", "trae_cn", "改名"))
    repo.save(acct("trae_cn:main", "trae_cn", "再改名"))
    assert repo.get("trae_cn:main").account_name == "再改名"
