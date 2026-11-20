"""账户域用例（A2-04 §4）：注册账户 + 多账号枚举导入。

唯一性（ADR-034/035，2026-11-20 用户裁决）：
- ``account_id`` 是不透明主键，新账户生成 ``acc_<8hex>``，**永不由昵称/平台拼接**；
- ``(platform_code, source_key)`` 是真实身份锚点，有 source_key 时优先按它认回；
- 没有 source_key 时用 ``device_ref``（本机 profile/设备绑定）兜底幂等；
- ``account_code`` 是**人工维护后缀**，同步时留空，等用户关联登录账户时再填；
  只有调用方显式给了非空 code（存量兼容/手建）才回落 code 匹配；
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
    validate_account_code,
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
        account_code: str = "",
        account_id: str | None = None,
        identity: AccountIdentity | None = None,
        origin: str = "connector",
        device_ref: str | None = None,
    ) -> Account:
        platform = platform.strip()
        code = validate_account_code(account_code)
        new_identity = identity or AccountIdentity()
        rows = self.accounts.list_by_platform(platform)

        # 1) 真实身份优先：source_key 命中即同一人，改名/改 code 都不新建。
        if new_identity.source_key:
            for row in rows:
                if row.identity.source_key == new_identity.source_key:
                    return self._touch(row, account_name, new_identity, device_ref)

        # 2) 没有真实身份时，用本机绑定（profile/设备）兜底幂等；同一绑定换成
        #    另一个 source_key = 本机换了账号，旧卡保留、新账号另建，绝不并卡。
        if device_ref:
            for row in rows:
                if row.device_ref != device_ref:
                    continue
                old_key = row.identity.source_key
                if (
                    new_identity.source_key
                    and old_key
                    and old_key != new_identity.source_key
                ):
                    continue
                return self._touch(row, account_name, new_identity, device_ref)

        # 3) 只有调用方显式给了人工 code 才按 code 认回（手建/存量兼容）。
        if code:
            for row in rows:
                if row.account_code != code:
                    continue
                if account_id is not None and row.id != account_id:
                    raise AccountAlreadyExists(
                        f"account_code={code!r} 已登记为 {row.id!r}，"
                        f"与显式 id {account_id!r} 冲突"
                    )
                old_key = row.identity.source_key
                if (
                    new_identity.source_key
                    and old_key
                    and old_key != new_identity.source_key
                ):
                    raise AccountConflict(
                        f"{platform} 的 account_code={code!r} 已被另一个身份占用"
                        f"（{old_key!r} ≠ {new_identity.source_key!r}）"
                    )
                return self._touch(row, account_name, new_identity, device_ref)

        # 4) 新账户：account_code 默认留空（人工关联前不生成），id 不透明。
        aid = account_id or new_account_id(self.accounts)
        if self.accounts.get(aid) is not None:
            raise AccountAlreadyExists(f"account_id {aid!r} 已被占用")

        account = Account(
            id=aid,
            platform_code=platform,
            account_name=account_name.strip(),
            created_at=now_utc(),
            account_code=code,
            identity=new_identity,
            origin=origin,
            device_ref=device_ref,
            last_seen_at=now_utc(),
        )
        self.accounts.save(account)
        return account

    def _touch(
        self,
        row: Account,
        account_name: str,
        identity: AccountIdentity,
        device_ref: str | None,
    ) -> Account:
        """认回既有账户：刷新显示名/真实身份/本机绑定，但绝不改人工 code。"""

        merged_identity = row.identity
        if identity.source_key and (
            not row.identity.source_key
            or row.identity.source_key.startswith(LEGACY_SOURCE_PREFIX)
        ):
            merged_identity = replace(
                merged_identity,
                source_key=identity.source_key,
                **{
                    field: getattr(identity, field)
                    for field in ("nickname", "email", "uid", "org")
                    if getattr(identity, field)
                },
            )
        elif identity.nickname or identity.email or identity.uid or identity.org:
            merged_identity = replace(
                merged_identity,
                **{
                    field: getattr(identity, field)
                    for field in ("nickname", "email", "uid", "org")
                    if getattr(identity, field)
                },
            )
        name = account_name.strip() or row.account_name
        merged = replace(
            row,
            account_name=name,
            identity=merged_identity,
            device_ref=device_ref or row.device_ref,
            last_seen_at=now_utc(),
        )
        self.accounts.save(merged)
        return merged

    def import_from_source(self, draft: AccountDraft) -> list[Account]:
        """枚举本机多 profile（ADR-003 §3），逐账号入库。"""

        if self.source is None:
            return [
                self.execute(
                    draft.platform_code,
                    draft.account_name,
                    account_code=draft.account_code,
                )
            ]
        registered: list[Account] = []
        for key, display in self.source.enumerate_accounts(draft.platform_code):
            registered.append(
                self.execute(
                    draft.platform_code,
                    display,
                    identity=AccountIdentity(source_key=key),
                    device_ref=key,
                )
            )
        return registered
