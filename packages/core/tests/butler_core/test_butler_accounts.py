"""账户域：多账号身份 / 冲突显式拒绝 / 凭据按账号隔离 / 凭据脱敏。"""

from datetime import datetime, timedelta, timezone

import pytest

from butler_core.accounts.domain import (
    Account,
    AccountAlreadyExists,
    AccountInvalid,
    Credential,
    CredentialHealth,
    EmptySecret,
    Secret,
    account_identity,
    main_account_id,
    vault_ref,
)
from butler_core.accounts.ports import AccountRepository
from butler_core.accounts.usecases.register_account import RegisterAccount
from butler_core.shared.health_level import HealthLevel


class MemoryAccounts(AccountRepository):
    def __init__(self):
        self.rows = {}

    def save(self, account):
        self.rows[account.id] = account

    def get(self, account_id):
        return self.rows.get(account_id)

    def list_by_platform(self, platform):
        return [a for a in self.rows.values() if a.platform_code == platform]

    def list_all(self):
        return list(self.rows.values())


def test_identity_default_key_and_collection():
    assert account_identity("trae_cn") == "trae_cn:main"
    assert main_account_id("trae_cn") == account_identity("trae_cn")
    a = Account(
        id=account_identity("trae_cn", "work"),
        platform_code="trae_cn",
        account_name="工作号",
        created_at=datetime.now(timezone.utc),
        account_code="work",
    )
    b = Account(
        id=account_identity("trae_cn", "personal"),
        platform_code="trae_cn",
        account_name="个人号",
        created_at=datetime.now(timezone.utc),
        account_code="personal",
    )
    assert a.identity != b.identity
    assert a.account_code == "work"


def test_account_id_must_match_identity():
    with pytest.raises(AccountInvalid):
        Account(id="wrong", platform_code="trae_cn", account_name="x",
                created_at=datetime.now(timezone.utc))


def test_credential_must_belong_to_account():
    with pytest.raises(AccountInvalid):
        Account(
            id=account_identity("trae_cn"), platform_code="trae_cn", account_name="x",
            created_at=datetime.now(timezone.utc),
            credentials=(Credential(account_id="other", kind="cookie"),),
        )


def test_register_multi_account_and_conflict():
    repo = MemoryAccounts()
    uc = RegisterAccount(accounts=repo)
    a = uc.execute("trae_cn", "工作号", account_code="work")
    b = uc.execute("trae_cn", "个人号", account_code="personal")
    assert len(repo.list_by_platform("trae_cn")) == 2
    assert a.id != b.id
    assert uc.execute("trae_cn", "工作号", account_code="work").id == a.id  # 幂等
    assert uc.execute("trae_cn", "改名了", account_code="work").id == a.id  # 不覆盖
    with pytest.raises(AccountAlreadyExists):
        uc.execute("trae_cn", "x", account_code="work", account_id="trae_cn:other")


def test_secret_redaction_and_empty_rejected():
    secret = Secret("abc")
    assert secret.expose() == "abc"
    assert repr(secret) == str(secret) == "[REDACTED]"
    with pytest.raises(EmptySecret):
        Secret("")


def test_vault_ref_and_credential_health():
    assert vault_ref("trae_cn:main", "cookie") == "trae_cn:main:cookie"
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    expiring = CredentialHealth.build(
        account_id="trae_cn:main", kind="cookie",
        expires_at=now + timedelta(days=1), clock=lambda: now,
    )
    assert expiring.level is HealthLevel.EXPIRING
