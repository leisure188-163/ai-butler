"""账户编辑用例（ADR-033 裁决 1/5）：只改显示/运营字段，永不改编址。

可改：alias / account_name / is_active / base_url / identity。
不可改：account_id / account_code / platform_code / origin（编址与来源是事实，
        改它属于迁移动作，不提供入口）。
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from butler_core.accounts.domain import Account, AccountIdentity, AccountInvalid
from butler_core.accounts.ports import AccountRepository


@dataclass
class UpdateAccount:
    accounts: AccountRepository

    def execute(
        self,
        account_id: str,
        *,
        alias: str | None = None,
        account_name: str | None = None,
        is_active: bool | None = None,
        base_url: str | None = None,
        identity: AccountIdentity | None = None,
    ) -> Account:
        account = self.accounts.get(account_id)
        if account is None:
            raise AccountInvalid(f"账户不存在：{account_id}")
        changes: dict[str, object] = {}
        if alias is not None:
            changes["alias"] = alias.strip()
        if account_name is not None:
            name = account_name.strip()
            if not name:
                raise AccountInvalid("account_name 不能改为空")
            changes["account_name"] = name
        if is_active is not None:
            changes["is_active"] = is_active
        if base_url is not None:
            changes["base_url"] = base_url.strip()
        if identity is not None:
            changes["identity"] = identity
        updated = replace(account, **changes)
        self.accounts.save(updated)
        return updated
