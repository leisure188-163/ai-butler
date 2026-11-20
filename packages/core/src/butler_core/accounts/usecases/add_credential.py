"""追加凭据槽位用例（ADR-033 裁决 3）。

只负责形状校验与入库；账户是否存在由端侧先查（core 不跨聚合读名册）。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from butler_core.accounts.domain import Credential, Secret
from butler_core.accounts.ports import VaultPort


@dataclass
class AddCredential:
    vault: VaultPort

    def execute(
        self,
        account_id: str,
        kind: str,
        secret: Secret,
        *,
        slot: str = "default",
        label: str = "",
        expires_at: datetime | None = None,
    ) -> Credential:
        credential = Credential(
            account_id=account_id,
            kind=kind,
            slot=slot,
            label=label,
            expires_at=expires_at,
        )
        self.vault.store(
            account_id,
            kind,
            secret,
            slot=credential.slot,
            label=credential.label,
            expires_at=expires_at,
        )
        return credential
