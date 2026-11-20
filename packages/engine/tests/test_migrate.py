"""一次性迁移（A1-05 §4）：旧库搬移 / 幂等 / 凭据前缀收口 / 审计。"""

from butler_engine.db.migrate import (
    legacy_db_candidates,
    migrate_legacy_db,
    migrate_legacy_vault,
)


def test_legacy_db_source_is_marina_only(tmp_path):
    root = tmp_path / "data" / "butler"
    sources = legacy_db_candidates(root)
    assert sources == [tmp_path / "data" / "ai-marina" / "marina.db"]


def test_cwd_legacy_db_not_migrated(tmp_path):
    """CWD 源已移除（2026-11-16）：起进程目录里的同名旧库不再被隐式搬走。"""
    root = tmp_path / "data" / "butler"
    root.mkdir(parents=True)
    cwd = tmp_path / "repo"
    cwd.mkdir()
    legacy = cwd / "stray.db"
    legacy.write_bytes(b"stray")
    target = root / "butler.db"

    assert migrate_legacy_db(target, root) is None
    assert legacy.read_bytes() == b"stray"  # 原地不动，不搬不删
    assert not target.exists()


def test_first_migration_moves_legacy_db_and_writes_log(tmp_path):
    root = tmp_path / "data" / "butler"
    root.mkdir(parents=True)
    old = tmp_path / "data" / "ai-marina"
    old.mkdir()
    (old / "marina.db").write_bytes(b"old")
    (old / "marina.db-wal").write_bytes(b"wal")
    logs: list[str] = []
    target = root / "butler.db"

    migrated = migrate_legacy_db(target, root, log=logs.append)

    assert migrated == old / "marina.db"
    assert target.read_bytes() == b"old"
    assert (root / "butler.db-wal").read_bytes() == b"wal"
    assert old.is_dir()  # 目录保留
    assert logs and "迁移" in logs[0]  # 审计日志


def test_idempotent_skip_when_target_exists(tmp_path):
    root = tmp_path / "data" / "butler"
    root.mkdir(parents=True)
    target = root / "butler.db"
    target.write_bytes(b"current")
    old = tmp_path / "data" / "ai-marina"
    old.mkdir()
    (old / "marina.db").write_bytes(b"old")

    assert migrate_legacy_db(target, root) is None
    assert target.read_bytes() == b"current"
    assert (old / "marina.db").read_bytes() == b"old"


class _FakeBackend:
    def __init__(self):
        self.calls = []

    def migrate_legacy_refs(self, refs):
        self.calls.append(list(refs))
        return ["old:cookie"]


def test_migrate_legacy_vault_once_and_logs(tmp_path):
    backend = _FakeBackend()
    logs: list[str] = []
    migrated = migrate_legacy_vault(
        [backend, object()], ["old:cookie"], log=logs.append
    )
    assert migrated == ["old:cookie"]
    assert backend.calls == [["old:cookie"]]
    assert logs and "marina.vault" in logs[0]
