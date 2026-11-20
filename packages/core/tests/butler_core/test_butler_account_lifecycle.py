"""账户生命周期与编址冻结（ADR-033）：手建 / 编辑 / 多槽凭据 / 标签单源。"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from butler_core.accounts.domain import (
    Account,
    AccountAlreadyExists,
    AccountIdentity,
    AccountInvalid,
    Credential,
    Secret,
    account_label,
    vault_ref,
)
from butler_core.accounts.ports import AccountRepository, VaultPort
from butler_core.accounts.usecases.add_credential import AddCredential
from butler_core.accounts.usecases.create_account import CreateAccount
from butler_core.accounts.usecases.register_account import RegisterAccount
from butler_core.accounts.usecases.revoke_credential import RevokeCredential
from butler_core.accounts.usecases.update_account import UpdateAccount


class MemoryAccounts(AccountRepository):
    def __init__(self, *, fail_save: bool = False):
        self.rows: dict[str, Account] = {}
        self.fail_save = fail_save

    def save(self, account):
        if self.fail_save:
            raise RuntimeError("磁盘写失败")
        self.rows[account.id] = account

    def get(self, account_id):
        return self.rows.get(account_id)

    def list_by_platform(self, platform):
        return [a for a in self.rows.values() if a.platform_code == platform]

    def list_all(self):
        return list(self.rows.values())

    def remove(self, account_id):
        return self.rows.pop(account_id, None) is not None


class MemoryVault(VaultPort):
    """只记调用的假件：验用例是否把 slot/label 正确传到保险库。"""

    def __init__(self, *, fail_store: bool = False):
        self.stored: list[dict] = []
        self.purged: list[str] = []
        self.revoked_slots: list[tuple[str, str, str]] = []
        self.fail_store = fail_store

    def store(self, account_id, kind, secret, *, slot="default", label="", expires_at=None):
        if self.fail_store:
            raise RuntimeError("保险库不可用")
        self.stored.append(
            {"account_id": account_id, "kind": kind, "slot": slot, "label": label}
        )

    def load(self, account_id, kinds, *, slot="default"):
        raise NotImplementedError

    def rotate(self, account_id, kind, new_secret, *, slot="default", expires_at=None):
        raise NotImplementedError

    def revoke(self, account_id, *, reason):
        return 0

    def purge(self, account_id):
        self.purged.append(account_id)
        return 0

    def health(self):
        return []

    def revoke_slot(self, account_id, kind, slot, *, reason):
        self.revoked_slots.append((account_id, kind, slot))
        return True


def test_account_label_优先级_alias到code():
    base = dict(platform_code="doubao_cn", created_at=datetime(2026, 11, 20, tzinfo=UTC))
    assert (
        account_label(
            Account(id="doubao_cn:u1", account_code="u1", account_name="豆包 · 小号",
                    alias="小号 A", identity=AccountIdentity(nickname="逍遥酒鬼"), **base)
        )
        == "小号 A"
    )
    assert (
        account_label(
            Account(id="doubao_cn:u1", account_code="u1", account_name="豆包 · 小号",
                    identity=AccountIdentity(nickname="逍遥酒鬼"), **base)
        )
        == "逍遥酒鬼"
    )
    assert (
        account_label(
            Account(id="doubao_cn:u1", account_code="u1", account_name="豆包 · 小号", **base)
        )
        == "小号"
    )
    # 无「·」后缀 = 原名；原名空（构造禁止）时退回 code
    assert (
        account_label(
            Account(id="doubao_cn:u1", account_code="u1", account_name="豆包主号", **base)
        )
        == "豆包主号"
    )


def test_credential_slot形状与标签限长():
    assert Credential(account_id="a:main", kind="token", slot="backup-2").slot == "backup-2"
    for bad in ("", "主 key", "a:b", "x" * 25):
        with pytest.raises(AccountInvalid):
            Credential(account_id="a:main", kind="token", slot=bad)
    with pytest.raises(AccountInvalid):
        Credential(account_id="a:main", kind="token", label="x" * 41)


def test_vault_ref_默认槽保持旧形状():
    assert vault_ref("a:main", "token") == "a:main:token"
    assert vault_ref("a:main", "token", "backup") == "a:main:token@backup"


def test_create_account_带首凭据落槽位():
    accounts, vault = MemoryAccounts(), MemoryVault()
    uc = CreateAccount(accounts=accounts, vault=vault)
    acc = uc.execute(
        "my_relay", "key1", "我的中转 · 主 key",
        kind="api_key", secret=Secret("sk-1"), slot="primary", label="主 key",
    )
    assert acc.id == "my_relay:key1"
    assert acc.origin == "manual"
    assert accounts.get("my_relay:key1") is not None
    assert vault.stored == [
        {"account_id": "my_relay:key1", "kind": "api_key", "slot": "primary", "label": "主 key"}
    ]
    with pytest.raises(AccountAlreadyExists):
        uc.execute("my_relay", "key1", "重复", kind="api_key", secret=Secret("sk-2"))


def test_create_account_落库失败回滚凭据():
    accounts, vault = MemoryAccounts(fail_save=True), MemoryVault()
    uc = CreateAccount(accounts=accounts, vault=vault)
    with pytest.raises(RuntimeError):
        uc.execute("my_relay", "key1", "我的中转", kind="api_key", secret=Secret("sk-1"))
    assert vault.stored  # 凭据先写
    assert vault.purged == ["my_relay:key1"]  # 账户没落库 → 清掉无主秘密
    assert accounts.list_all() == []


def test_create_account_形状校验_不产生半成品():
    accounts, vault = MemoryAccounts(), MemoryVault()
    uc = CreateAccount(accounts=accounts, vault=vault)
    with pytest.raises(AccountInvalid):
        uc.execute("my_relay", "key1", "x", label="无明文的标签")  # 无 secret 却声明标签
    with pytest.raises(AccountInvalid):
        uc.execute("my_relay", "key1", "x", secret=Secret("sk-1"))  # 有 secret 但无 kind
    with pytest.raises(AccountInvalid):
        uc.execute("my_relay", "key1", "x", kind="api_key", secret=Secret("sk-1"),
                   slot="主 key")  # 槽位非法
    assert accounts.list_all() == [] and vault.stored == []


def test_update_account_只改运营字段且不改编址():
    accounts = MemoryAccounts()
    accounts.save(
        Account(id="my_relay:key1", platform_code="my_relay", account_code="key1",
                account_name="旧名", created_at=datetime(2026, 11, 20, tzinfo=UTC))
    )
    updated = UpdateAccount(accounts=accounts).execute(
        "my_relay:key1", alias="主 key", account_name="新名", is_active=False,
        base_url="https://relay.example.com/v1",
    )
    assert (updated.account_code, updated.id) == ("key1", "my_relay:key1")  # 编址不变
    assert updated.alias == "主 key" and updated.account_name == "新名"
    assert updated.is_active is False
    with pytest.raises(AccountInvalid):
        UpdateAccount(accounts=accounts).execute("my_relay:key1", account_name="  ")
    with pytest.raises(AccountInvalid):
        UpdateAccount(accounts=accounts).execute("ghost", alias="x")


def test_register_account_按source_key认回旧卡():
    accounts = MemoryAccounts()
    uc = RegisterAccount(accounts=accounts)
    first = uc.execute("doubao_cn", "豆包 · 小号", account_code="u1",
                       identity=AccountIdentity(source_key="sec_uid_1"))
    # 同一个人换了昵称和 code：仍认回 u1，不新建卡
    again = uc.execute("doubao_cn", "豆包 · 改了个名", account_code="u2",
                       identity=AccountIdentity(source_key="sec_uid_1"))
    assert again.id == first.id
    assert len(accounts.list_by_platform("doubao_cn")) == 1
    # 没有 source_key 就不猜：另一个 code 正常建新卡
    other = uc.execute("doubao_cn", "豆包 · 另一个人", account_code="u3")
    assert other.id == "doubao_cn:u3"
    assert len(accounts.list_by_platform("doubao_cn")) == 2


def test_add_and_revoke_credential_传对槽位():
    vault = MemoryVault()
    add = AddCredential(vault=vault)
    cred = add.execute("a:main", "token", Secret("sk-1"), slot="backup", label="备用")
    assert (cred.slot, cred.label) == ("backup", "备用")
    assert vault.stored[0]["slot"] == "backup"

    revoke = RevokeCredential(vault=vault)
    assert revoke.execute("a:main", "token", slot="backup", reason="轮换") is True
    assert vault.revoked_slots == [("a:main", "token", "backup")]
