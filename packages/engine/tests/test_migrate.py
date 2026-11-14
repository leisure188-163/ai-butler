"""一次性迁移（A1-05 §4）：旧库搬移优先级 / 幂等 / 凭据前缀收口 / 审计。"""

from butler_engine.db.migrate import (
    legacy_db_candidates,
    migrate_legacy_db,
    migrate_legacy_vault,
)


def test_legacy_db_source_priority(tmp_path):
    root = tmp_path / "data" / "butler"
    cwd = tmp_path / "repo"
    sources = legacy_db_candidates(root, cwd)
    assert sources[0] == tmp_path / "data" / "kabao" / "kabao.db"
    assert sources[1] == cwd / "kabao.db"
    assert sources[2] == tmp_path / "data" / "ai-marina" / "marina.db"
    assert sources[3] == cwd / "marina.db"


def test_first_migration_moves_kabao_db_and_writes_log(tmp_path):
    root = tmp_path / "data" / "butler"
    root.mkdir(parents=True)
    old = tmp_path / "data" / "kabao"
    old.mkdir()
    (old / "kabao.db").write_bytes(b"old")
    (old / "kabao.db-wal").write_bytes(b"wal")
    logs: list[str] = []
    target = root / "butler.db"

    migrated = migrate_legacy_db(target, root, tmp_path, log=logs.append)

    assert migrated == old / "kabao.db"
    assert target.read_bytes() == b"old"
    assert (root / "butler.db-wal").read_bytes() == b"wal"
    assert old.is_dir()  # 目录保留
    assert logs and "迁移" in logs[0]  # 审计日志


def test_idempotent_skip_and_brand_priority(tmp_path):
    root = tmp_path / "data" / "butler"
    root.mkdir(parents=True)
    target = root / "butler.db"
    target.write_bytes(b"current")
    old = tmp_path / "data" / "kabao"
    old.mkdir()
    (old / "kabao.db").write_bytes(b"old")

    assert migrate_legacy_db(target, root, tmp_path) is None
    assert target.read_bytes() == b"current"
    assert (old / "kabao.db").read_bytes() == b"old"


def test_kabao_source_wins_over_marina(tmp_path):
    root = tmp_path / "data" / "butler"
    root.mkdir(parents=True)
    (tmp_path / "data" / "kabao").mkdir()
    (tmp_path / "data" / "kabao" / "kabao.db").write_bytes(b"kabao")
    (tmp_path / "data" / "ai-marina").mkdir()
    (tmp_path / "data" / "ai-marina" / "marina.db").write_bytes(b"marina")
    target = root / "butler.db"

    migrate_legacy_db(target, root, tmp_path)

    assert target.read_bytes() == b"kabao"


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
