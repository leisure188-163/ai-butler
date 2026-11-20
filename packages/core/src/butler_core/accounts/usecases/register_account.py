"""账户域用例（A2-04 §4）：注册账户 + 多账号枚举导入。

唯一性（ADR-034，2026-11-20 用户裁决）：
- ``account_id`` 是不透明主键，新账户生成 ``acc_<8hex>``，**永不由昵称/平台拼接**；
- ``(platform_code, source_key)`` 是真实身份锚点，有 source_key 时优先按它认回；
- 只有 source_key 未知时才回落 ``(platform_code, account_code)``；code 命中但两边
  source_key 都有值且不同 → ``AccountConflict``，绝不把两个真实账号并成一张卡；
- 存量 ``legacy:`` 占位键在连接器首次带来真实 source_key 时就地吸收，平滑迁移。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from uuid import uuid4

from butler_core.accounts.domain import (
    Account,
    AccountAlreadyExists,
    AccountConflict,
    AccountDraft,
    AccountIdentity,
)
from butler_core.accounts.ports import AccountRepository, SessionSourcePort
from butler_core.shared.time import now_utc

#: 迁移桥：存量账号回填的占位身份键前缀（不是真实外部 id）。
LEGACY_SOURCE_PREFIX = "legacy:"


def new_account_id(accounts: AccountRepository) -> str:
    """生成不透明账户主键；碰撞重试（8 hex 空间在单机名册足够）。"""
    while True:
        candidate = f"acc_{uuid4().hex[:8]}"
        if accounts.get(candidate) is None:
            return candidate


@dataclass
class RegisterAccount:
    accounts: AccountRepository
    source: SessionSourcePort | None = None

    def execute(
        self,
        platform: str,
        account_name: str,
        *,
        account_code: str = "main",
        account_id: str | None = None,
        identity: AccountIdentity | None = None,
        origin: str = "connector",
    ) -> Account:
        platform = platform.strip()
        code = account_code.strip() or "main"
        new_identity = identity or AccountIdentity()

        # 1) 真实身份优先：source_key 命中即同一人，改名/改 code 都不新建。
        if new_identity.source_key:
            for row in self.accounts.list_by_platform(platform):
                if row.identity.source_key == new_identity.source_key:
                    return row

        # 2) source_key 未命中时回落平台内 code；code 命中必须核对身份，冲突显式拒绝。
        for row in self.accounts.list_by_platform(platform):
            if row.account_code != code:
                continue
            if account_id is not None and row.id != account_id:
                raise AccountAlreadyExists(
                    f"account_code={code!r} 已登记为 {row.id!r}，与显式 id {account_id!r} 冲突"
                )
            old_key = row.identity.source_key
            if new_identity.source_key and old_key and old_key != new_identity.source_key:
                raise AccountConflict(
                    f"{platform} 的 account_code={code!r} 已被另一个身份占用"
                    f"（{old_key!r} ≠ {new_identity.source_key!r}）——请更换 code"
                )
            if new_identity.source_key and (
                not old_key or old_key.startswith(LEGACY_SOURCE_PREFIX)
            ):
                # 迁移桥：存量占位键让位给连接器带来的真实身份键。
                merged = replace(
                    row,
                    identity=replace(row.identity, **{
                        "source_key": new_identity.source_key,
                        **{
                            field: getattr(new_identity, field)
                            for field in ("nickname", "email", "uid", "org")
                            if getattr(new_identity, field)
                        },
                    }),
                    last_seen_at=now_utc(),
                )
                self.accounts.save(merged)
                return merged
            return row

        # 3) 新账户：保留调用方显式 id（迁移/测试），否则生成不透明主键。
        aid = account_id or new_account_id(self.accounts)
        if self.accounts.get(aid) is not None:
            raise AccountAlreadyExists(f"account_id {aid!r} 已被占用")

        account = Account(
            id=aid,
            platform_code=platform,
            account_name=account_name,
            created_at=now_utc(),
            account_code=code,
            identity=new_identity,
            origin=origin,
            last_seen_at=now_utc(),
        )
        self.accounts.save(account)
        return account

    def import_from_source(self, draft: AccountDraft) -> list[Account]:
        """枚举本机多 profile（ADR-003 §3），逐账号入库。"""

        if self.source is None:
            return [self.execute(draft.platform_code, draft.account_name, account_code=draft.account_code)]
        registered: list[Account] = []
        for key, display in self.source.enumerate_accounts(draft.platform_code):
            registered.append(
                self.execute(
                    draft.platform_code,
                    display,
                    account_code=key,
                    identity=AccountIdentity(source_key=key),
                )
            )
        return registered
