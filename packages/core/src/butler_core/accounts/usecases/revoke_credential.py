"""撤销单个凭据槽位（ADR-033 裁决 3）。

整账户撤销仍走 `DeleteAccount`（删除账户时 purge 全部槽位与历史）。
"""

from __future__ import annotations

from dataclasses import dataclass

from butler_core.accounts.ports import VaultPort


@dataclass
class RevokeCredential:
    vault: VaultPort

    def execute(
        self,
        account_id: str,
        kind: str,
        *,
        slot: str = "default",
        reason: str = "user_revoked",
    ) -> bool:
        return self.vault.revoke_slot(account_id, kind, slot, reason=reason or "user_revoked")
