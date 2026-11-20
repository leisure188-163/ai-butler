"""手建账户用例（ADR-033 裁决 1/2/3）。

与 `RegisterAccount` 的分工：RegisterAccount 是连接器扫描的幂等回放，本用例是
用户在账户页显式创建（API 型接入源、连接器没扫到的小号）。

不变式：
- `account_code` 由调用方给定后即冻结；本用例不接受后续改写。
- 首份凭据与账户同一用例写入：凭据写失败则账户行不落库；账户行写失败则回滚凭据。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from butler_core.accounts.domain import (
    Account,
    AccountAlreadyExists,
    AccountIdentity,
    AccountInvalid,
    Credential,
    Secret,
    account_identity,
)
from butler_core.accounts.ports import AccountRepository, VaultPort
from butler_core.shared.time import now_utc


@dataclass
class CreateAccount:
    accounts: AccountRepository
    vault: VaultPort | None = None

    def execute(
        self,
        platform: str,
        account_code: str,
        account_name: str,
        *,
        alias: str = "",
        base_url: str = "",
        identity: AccountIdentity | None = None,
        kind: str = "",
        secret: Secret | None = None,
        slot: str = "default",
        label: str = "",
        expires_at: datetime | None = None,
    ) -> Account:
        aid = account_identity(platform, account_code)
        if self.accounts.get(aid) is not None:
            raise AccountAlreadyExists(f"账户已存在：{aid}（编址冻结，不覆盖）")
        if secret is None:
            if kind or label or expires_at is not None:
                raise AccountInvalid("未提供明文时不能声明 kind/label/expires_at")
        else:
            if not kind.strip():
                raise AccountInvalid("带首份凭据创建时必须声明 kind")
            if self.vault is None:
                raise AccountInvalid("本部署未装配保险库，不能带凭据创建账户")
        # 先验形状再落库：槽位/标签非法时不产生半成品账户
        credential = Credential(
            account_id=aid, kind=kind, slot=slot, label=label, expires_at=expires_at
        ) if secret is not None else None

        account = Account(
            id=aid,
            platform_code=platform.strip(),
            account_name=account_name.strip(),
            created_at=now_utc(),
            account_code=account_code.strip(),
            alias=alias.strip(),
            base_url=base_url.strip(),
            identity=identity or AccountIdentity(),
            origin="manual",
            last_seen_at=now_utc(),
        )
        if credential is not None and secret is not None and self.vault is not None:
            self.vault.store(
                aid,
                kind,
                secret,
                slot=credential.slot,
                label=credential.label,
                expires_at=expires_at,
            )
        try:
            self.accounts.save(account)
        except Exception:
            if credential is not None and self.vault is not None:
                self.vault.purge(aid)  # 回滚刚写的凭据，避免无主秘密
            raise
        return account
