"""停靠扫描端到端（dockio / trae_cn storage.json 协议形状 → 号册 + vault）。"""

import base64
import json

import pytest

from butler_core.accounts.ports import AccountRepository
from butler_core.accounts.usecases.register_account import RegisterAccount
from butler_core.accounts.domain import Account
from butler_core.accounts.domain import Secret

from butler_connectors.registry import DockContext, load_registry
from conftest import frozen_epoch, make_login_state  # noqa: F401 由 pytest 根目录可见


class MemVault:
    def __init__(self) -> None:
        self.items: dict[tuple[str, str], object] = {}

    def store(self, account_id, kind, secret, *, expires_at=None, backend=None):
        self.items[(account_id, kind)] = (secret, expires_at)

    def load(self, account_id, kinds):
        return [self.items[(account_id, kind)][0] for kind in kinds]


class MemAccounts(AccountRepository):
    def __init__(self) -> None:
        self.rows: dict[str, Account] = {}

    def save(self, account: Account) -> None:
        self.rows[account.id] = account

    def get(self, account_id):
        return self.rows.get(account_id)

    def list_by_provider(self, provider):
        return [a for a in self.rows.values() if a.provider == provider]

    def list_all(self):
        return list(self.rows.values())


@pytest.fixture
def storage_file(tmp_path):
    path = tmp_path / "storage.json"
    path.write_text(
        json.dumps(make_login_state(frozen_epoch()), ensure_ascii=False),
        encoding="utf-8",
    )
    return path


@pytest.fixture
def ctx(storage_file):
    return DockContext(
        vault=MemVault(),
        register=RegisterAccount(accounts=MemAccounts()),
        storage_override=[str(storage_file)],
    )


def test_dock_registers_account_and_stores_credentials(ctx):
    registry = load_registry()
    [outcome] = registry.dock(ctx, target="trae_cn")
    assert outcome.accounts == ["trae_cn:main"]
    assert outcome.issues == []

    account = ctx.register.accounts.get("trae_cn:main")
    assert account.display_name == "Trae CN"

    import sys

    from butler_connectors.ssaes import decode_stored, open_envelope

    envelope, expires = ctx.vault.items[("trae_cn:main", "ss_aes")]
    info = open_envelope(decode_stored(envelope.expose()))
    assert info["token"].startswith("ey")  # 解码形态耦合最小化：JWT 形状
    device, _ = ctx.vault.items[("trae_cn:main", "device_dn")]
    assert device.expose() == "1234567890123456"  # 键名里的 Aha 数字号
    assert expires is not None and expires.year == 2026  # JWT exp 元数据


def test_dock_skips_when_no_storage(ctx, tmp_path):
    ctx.storage_override = [str(tmp_path / "不存在的目录" / "storage.json")]
    registry = load_registry()
    [outcome] = registry.dock(ctx, target="trae_cn")
    assert outcome.accounts == []  # 无人可停靠
    assert outcome.issues and "登录态" in outcome.issues[0]


def test_dock_is_idempotent(ctx):
    """重复停靠同名册位：不再新建账号；凭据刷新覆盖（rotate 语义走的同槽）。"""
    registry = load_registry()
    registry.dock(ctx, target="trae_cn")
    registry.dock(ctx, target="trae_cn")
    assert len(ctx.register.accounts.list_all()) == 1
    assert len(ctx.vault.items) == 2  # ss_aes + device_dn 两 kind
