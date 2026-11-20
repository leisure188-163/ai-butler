"""凭据池实现（ADR-012 裁决 3）：vault 现用现取 + 短 TTL 缓存 + 读取全审计。

- 每一次 acquire 都落池级审计（actor=gateway-pool，outcome=hit|miss|error:<E>）；
  miss 路径的解密由 LayeredVault.load 自带 vault 级审计——两层事实都留痕，
  不存在未审计的凭据读取（plans/02 §0 红线级：不得绕行 vault 审计路径）
- 缓存策略 = CachePolicy(kind, ttl_seconds) 数据表（A2-02 §3 判据：kind 数据
  而非 per-platform 分支）；未声明 kind → ttl 0 = 严格现用现取（保守默认）
- TTL 时钟可注入（测试确定性，core 用例同款先例）
- 缓存命中的 Secret 是同一明文载体对象（Secret repr 恒 [REDACTED]，A4-01 §1）
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from typing import Protocol

from butler_core.accounts.domain import CachePolicy, Secret, vault_ref
from butler_core.accounts.ports import VaultPort


class _AuditSink(Protocol):
    """审计落账口（LayeredVault 同款 record 签名；credential_ref 入库前强制哈希）。"""

    def record(
        self,
        *,
        actor: str,
        action: str,
        outcome: str,
        account_id: str | None = None,
        credential_ref: str | None = None,
    ) -> None: ...


class VaultCredentialPool:
    """VaultPort 的池化包装：热路径缓存 + 全审计；G3 Router/G5 协议面消费。"""

    def __init__(
        self,
        vault: VaultPort,
        audit: _AuditSink,
        *,
        policies: Mapping[str, CachePolicy] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._vault = vault
        self._audit = audit
        self._policies = dict(policies or {})
        self._clock = clock
        self._cache: dict[tuple[str, str, str], tuple[Secret, float]] = {}

    def acquire(self, account_id: str, kind: str, slot: str = "default") -> Secret:
        """取凭据：命中缓存不触 vault（池级审计 hit）；否则现用现取（miss）。

        槽位（ADR-033）：默认只取 default 槽；多 key 场景由调用方显式指定 slot。
        缺凭据等 vault 异常原样上抛（红线 5，端零映射），调用方决定协议面语义。
        """
        ref = vault_ref(account_id, kind, slot)
        key = (account_id, kind, slot)
        now = self._clock()
        cached = self._cache.get(key)
        if cached is not None and now < cached[1]:
            self._audit.record(
                actor="gateway-pool",
                action="pool.acquire",
                outcome="hit",
                account_id=account_id,
                credential_ref=ref,
            )
            return cached[0]
        try:
            (secret,) = self._vault.load(account_id, [kind], slot=slot)  # 最小授权
        except Exception as exc:  # 审计后原样上抛
            self._audit.record(
                actor="gateway-pool",
                action="pool.acquire",
                outcome=f"error:{type(exc).__name__}",
                account_id=account_id,
                credential_ref=ref,
            )
            raise
        self._cache.pop(key, None)  # 清掉过期项
        ttl = self._policies.get(kind, CachePolicy(kind=kind)).ttl_seconds
        if ttl > 0:
            self._cache[key] = (secret, now + ttl)
        self._audit.record(
            actor="gateway-pool",
            action="pool.acquire",
            outcome="miss",
            account_id=account_id,
            credential_ref=ref,
        )
        return secret

    def invalidate(self, account_id: str, kind: str, slot: str = "default") -> None:
        self._cache.pop((account_id, kind, slot), None)
