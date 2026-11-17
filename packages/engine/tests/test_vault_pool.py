"""凭据池（ADR-012 裁决 3）：TTL 缓存 / 读取全审计 / kind 数据策略 / 显式缺凭据。

- 真 LayeredVault（memory 后端）+ 真 SqliteAuditLog，只把时钟换假件
- 审计断言直查 audit 表（actor='gateway-pool' 的行）
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from butler_core.accounts.domain import CachePolicy, Secret, vault_ref
from butler_engine.audit.sqlite import SqliteAuditLog
from butler_engine.bridge import build_engine
from butler_engine.vault.backends import MemoryVaultBackend
from butler_engine.vault.layered import LayeredVault
from butler_engine.vault.pool import VaultCredentialPool

_KIND = "session-token"


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _parts(tmp_path: Path, policies: dict[str, CachePolicy] | None = None):
    db = tmp_path / "butler.db"
    audit = SqliteAuditLog(db)
    vault = LayeredVault(
        db, {"memory": MemoryVaultBackend()}, default_backend="memory", audit=audit
    )
    clock = FakeClock()
    pool = VaultCredentialPool(vault, audit, policies=policies, clock=clock)
    return pool, vault, audit, clock, db


def _pool_rows(db: Path) -> list[tuple]:
    conn = sqlite3.connect(str(db))
    rows = conn.execute(
        "SELECT action, outcome, account_id, credential_ref FROM audit_log "
        "WHERE actor = 'gateway-pool' ORDER BY seq"
    ).fetchall()
    conn.close()
    return rows


def test_miss_then_hit_within_ttl(tmp_path: Path) -> None:
    pool, vault, _audit, clock, db = _parts(
        tmp_path, policies={_KIND: CachePolicy(kind=_KIND, ttl_seconds=30.0)}
    )
    vault.store("acct", _KIND, Secret("s3cret"))
    first = pool.acquire("acct", _KIND)
    second = pool.acquire("acct", _KIND)
    clock.advance(10.0)  # < TTL 30
    third = pool.acquire("acct", _KIND)
    assert first.expose() == second.expose() == third.expose() == "s3cret"
    outcomes = [r[1] for r in _pool_rows(db)]
    assert outcomes == ["miss", "hit", "hit"]


def test_ttl_expiry_goes_back_to_vault(tmp_path: Path) -> None:
    pool, vault, _audit, clock, db = _parts(
        tmp_path, policies={_KIND: CachePolicy(kind=_KIND, ttl_seconds=30.0)}
    )
    vault.store("acct", _KIND, Secret("v1"))
    pool.acquire("acct", _KIND)
    clock.advance(31.0)  # > TTL
    assert pool.acquire("acct", _KIND).expose() == "v1"
    outcomes = [r[1] for r in _pool_rows(db)]
    assert outcomes == ["miss", "miss"]


def test_undeclared_kind_never_caches(tmp_path: Path) -> None:
    """未声明 kind = 严格现用现取（保守默认，裁决 3）。"""
    pool, vault, _audit, _clock, db = _parts(tmp_path, policies=None)
    vault.store("acct", _KIND, Secret("v1"))
    pool.acquire("acct", _KIND)
    pool.acquire("acct", _KIND)
    outcomes = [r[1] for r in _pool_rows(db)]
    assert outcomes == ["miss", "miss"]


def test_policy_is_kind_data_not_branch(tmp_path: Path) -> None:
    """同一策略表里不同 kind 各走各的 TTL（A2-02 §3 判据）。"""
    policies = {
        "cached-kind": CachePolicy(kind="cached-kind", ttl_seconds=60.0),
    }
    pool, vault, _audit, _clock, db = _parts(tmp_path, policies=policies)
    vault.store("acct", "cached-kind", Secret("a"))
    vault.store("acct", "raw-kind", Secret("b"))
    pool.acquire("acct", "cached-kind")
    pool.acquire("acct", "cached-kind")  # hit
    pool.acquire("acct", "raw-kind")
    pool.acquire("acct", "raw-kind")  # 仍然 miss
    outcomes = [r[1] for r in _pool_rows(db)]
    assert outcomes == ["miss", "hit", "miss", "miss"]


def test_invalidate_forces_reload(tmp_path: Path) -> None:
    pool, vault, _audit, _clock, db = _parts(
        tmp_path, policies={_KIND: CachePolicy(kind=_KIND, ttl_seconds=60.0)}
    )
    vault.store("acct", _KIND, Secret("v1"))
    pool.acquire("acct", _KIND)
    pool.acquire("acct", _KIND)  # hit
    pool.invalidate("acct", _KIND)
    pool.acquire("acct", _KIND)  # 强制回 vault
    outcomes = [r[1] for r in _pool_rows(db)]
    assert outcomes == ["miss", "hit", "miss"]


def test_missing_kind_audits_error_and_raises(tmp_path: Path) -> None:
    pool, _vault, _audit, _clock, db = _parts(tmp_path)
    with pytest.raises(Exception):
        pool.acquire("ghost", _KIND)
    outcomes = [r[1] for r in _pool_rows(db)]
    assert len(outcomes) == 1
    assert outcomes[0].startswith("error:")  # 失败的读取也是事实，全审计


def test_pool_audit_hashes_credential_ref(tmp_path: Path) -> None:
    """credential_ref 入库前强制哈希（A4-01 §4），不落明文 ref。"""
    pool, vault, _audit, _clock, db = _parts(tmp_path)
    vault.store("acct", _KIND, Secret("v1"))
    pool.acquire("acct", _KIND)
    rows = _pool_rows(db)
    raw = vault_ref("acct", _KIND)
    assert rows[0][3] != raw
    assert len(rows[0][3]) == 64  # sha256 hex


def test_engine_kit_carries_pool(tmp_path: Path) -> None:
    """bridge 装配：EngineKit.credential_pool 就位，策略按 kind 注入。"""
    kit = build_engine(
        tmp_path / "butler.db",
        pool_policies={_KIND: CachePolicy(kind=_KIND, ttl_seconds=5.0)},
    )
    try:
        assert kit.credential_pool is not None
        with pytest.raises(Exception):
            kit.credential_pool.acquire("ghost", _KIND)  # 缺凭据显式抛，不触后端
    finally:
        kit.close()
