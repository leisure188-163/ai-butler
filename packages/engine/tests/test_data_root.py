"""数据根（A4-01 §5 数据布局）：绝不落 CWD + 旧身份数据自动迁移（A1-03 §7）。

迁移源优先级：① 旧品牌目录 ai-marina/marina.db（R1 更名前数据根）；
② M0 遗留 CWD marina.db。旧文件保留不删、迁移幂等。
"""

import sys

from butler_engine.bridge import default_db_path


def test_migrates_legacy_brand_dir_db(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "linux")  # 走 XDG 分支，平台无关可测
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    old_brand = tmp_path / "data" / "ai-marina"
    old_brand.mkdir(parents=True)
    (old_brand / "marina.db").write_bytes(b"old-brand")
    (old_brand / "marina.db-wal").write_bytes(b"old-wal")
    cwd = tmp_path / "repo"
    cwd.mkdir()
    monkeypatch.chdir(cwd)

    got = default_db_path()

    assert got == tmp_path / "data" / "butler" / "butler.db"
    assert got.read_bytes() == b"old-brand"  # 旧品牌库已搬入新数据根
    assert (tmp_path / "data" / "butler" / "butler.db-wal").read_bytes() == b"old-wal"
    assert not (old_brand / "marina.db").exists()  # 库文件以搬移改名方式迁移
    assert old_brand.is_dir()  # 旧目录保留不删（天然备份）


def test_migrates_legacy_cwd_db_into_data_root(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    cwd = tmp_path / "repo"
    cwd.mkdir()
    (cwd / "marina.db").write_bytes(b"legacy")  # M0 遗留：默认落 CWD
    monkeypatch.chdir(cwd)

    got = default_db_path()

    assert got == tmp_path / "data" / "butler" / "butler.db"
    assert got.read_bytes() == b"legacy"  # 旧库已搬入数据根
    assert not (cwd / "marina.db").exists()


def test_brand_dir_wins_over_cwd_legacy(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    old_brand = tmp_path / "data" / "ai-marina"
    old_brand.mkdir(parents=True)
    (old_brand / "marina.db").write_bytes(b"old-brand")
    cwd = tmp_path / "repo"
    cwd.mkdir()
    (cwd / "marina.db").write_bytes(b"cwd-legacy")
    monkeypatch.chdir(cwd)

    got = default_db_path()

    assert got.read_bytes() == b"old-brand"  # 品牌目录优先（更新的官方数据根）
    assert (cwd / "marina.db").read_bytes() == b"cwd-legacy"  # CWD 遗留不再搬
    assert not (old_brand / "marina.db").exists()


def test_never_touches_legacies_when_target_exists(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    cwd = tmp_path / "repo"
    cwd.mkdir()
    (cwd / "marina.db").write_bytes(b"legacy")
    old_brand = tmp_path / "data" / "ai-marina"
    old_brand.mkdir(parents=True)
    (old_brand / "marina.db").write_bytes(b"old-brand")
    existing = tmp_path / "data" / "butler"
    existing.mkdir(parents=True)
    (existing / "butler.db").write_bytes(b"current")
    monkeypatch.chdir(cwd)

    got = default_db_path()

    assert got.read_bytes() == b"current"  # 已迁移（butler.db 在）→ 幂等跳过
    assert (cwd / "marina.db").read_bytes() == b"legacy"  # CWD 遗留不动
    assert (old_brand / "marina.db").read_bytes() == b"old-brand"  # 旧品牌库不动


def test_no_migration_when_env_overrides(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("BUTLER_DB", str(tmp_path / "explicit.db"))
    cwd = tmp_path / "repo"
    cwd.mkdir()
    (cwd / "marina.db").write_bytes(b"legacy")
    monkeypatch.chdir(cwd)

    from butler_engine.bridge import DEFAULT_DB

    assert DEFAULT_DB == "butler.db"
    # 显式 BUTLER_DB 由端层取用（build_engine(os.environ["BUTLER_DB"])），
    # 不经 default_db_path() —— 旧库原地保留
    assert not (tmp_path / "data" / "butler").exists()
