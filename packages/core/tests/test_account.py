"""Account 聚合 + RegisterAccount 用例（A2-01 §1）：名册幂等。"""

from datetime import UTC, datetime
from typing import Callable

import pytest

from butler_core.accounts.ports import AccountRepository
from butler_core.accounts.usecases.register_account import RegisterAccount
from butler_core.accounts.domain import Account, main_account_id
from butler_core.shared.errors import DomainError
from butler_core.execution.domain import now_utc


class MemAccounts(AccountRepository):
    def __init__(self) -> None:
        self._rows: dict[str, Account] = {}

    def save(self, account: Account) -> None:
        self._rows[account.id] = account

    def get(self, account_id: str) -> Account | None:
        return self._rows.get(account_id)

    def list_by_platform(self, platform: str) -> list[Account]:
        return [a for a in self._rows.values() if a.platform_code == platform]

    def list_all(self) -> list[Account]:
        return list(self._rows.values())

    def remove(self, account_id):
        return self.rows.pop(account_id, None) is not None


def test_main_account_id_policy():
    assert main_account_id("trae_cn") == "trae_cn:main"
    with pytest.raises(DomainError):
        main_account_id(" ")


def test_register_is_idempotent_same_device():
    repo = MemAccounts()
    uc = RegisterAccount(accounts=repo)
    first = uc.execute("trae_cn", "Trae CN", device_ref="install-1")
    again = uc.execute("trae_cn", "Trae 改了个显示名", device_ref="install-1")
    assert first.id == again.id  # 同一本机绑定认回，不新建
    assert again.account_name == "Trae 改了个显示名"  # 显示名随客户端刷新
    assert first.account_code == ""  # ADR-035：同步不生成人工后缀
    assert repo.get(first.id).account_name == "Trae 改了个显示名"


def test_register_invalid_display():
    uc = RegisterAccount(accounts=MemAccounts())
    with pytest.raises(DomainError):
        uc.execute("trae_cn", "   ")


def test_account_fields_shape():
    account = Account(
        id="trae_cn:main",
        platform_code="trae_cn",
        account_name="Trae CN",
        created_at=datetime(2026, 11, 11, tzinfo=UTC),
    )
    assert account.platform_code == "trae_cn"
    with pytest.raises(DomainError):
        Account(id="", platform_code="trae_cn", account_name="x", created_at=now_utc())
