"""qoder_cn 用量通道（R2，PROTOCOL §7.1）：v2/me/usage 直读 qoderUsage 快照。

- 鉴权复用 provision 声明式主链：Bearer dt- token + Cosy-ClientType "10" +
  机器身份 8 头组（fill_auth_headers 单源；缺机器头 → 静默空列表的老坑在
  此端点同样成立）
- 基址按账户切：main/cn-* 走 openapi.qoder.com.cn，global-* 走
  openapi.qoder.sh（跨 host 会 401 TOKEN_EXPIRE，PROTOCOL §8.2）
- userQuota（套餐）/ addOnQuota（加量包）各自成包：total ≤ 0 = 无此配额，
  不造空包（真机实况：套餐全 0、加量包 2300/1786/514）
- expiresAt/refreshAt = 9999 占位（真机取证）→ cycle_end=None（当前形态
  无月度重置语义）；将来带套餐须重新取证重置语义
- qoderUsage 原话进 aggregate（不派生）；无流水通道 → ledger=None 如实申报
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from butler_core.usage.ports import UsageRequest, UsageResult

from butler_core.shared.ids import new_id
from butler_core.usage.domain import PackageQuota, UsageAggregate, UsageSnapshot
from butler_core.accounts.domain import Secret

from butler_connectors.decl import account_base_url, fill_auth_headers
from butler_connectors.transport import (
    HttpRequest,
    Transport,
    TransportError,
    httpx_transport,
)
from butler_connectors.unlock import unlock_all

_DEFAULT_USAGE_BASE = "https://openapi.qoder.com.cn"
_USAGE_PATH = "/sash/api/v2/me/usage"
_FAR_FUTURE_MS = 253402185600000  # ≈9999-12 占位阈值（真机实测 253402214400000）


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _num(value: Any) -> float | None:
    """宽载数值：bool 不算数；数值返回 float，其余（含 None）None。"""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


class QoderUsagePort:
    """qoder 用量端口：usage 端点快照 + 聚合原话（无流水）。"""

    def __init__(
        self,
        *,
        vault,
        transport: Transport | None = None,
        auth=None,
        kinds: tuple[str, ...] = (),
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._vault = vault
        self.transport = transport if transport is not None else httpx_transport()
        self.auth = auth
        self.kinds = kinds
        self._clock = clock if clock is not None else _now_utc

    def collect(self, req: UsageRequest) -> UsageResult:
        secrets: dict[str, Secret] = {}
        for kind in self.kinds:
            secrets[kind] = self._vault.load(req.account_id, [kind])[0]  # 缺失显式上抛
        fields = unlock_all(self.kinds, secrets)
        headers = fill_auth_headers(self.auth, fields)
        base = account_base_url(self.auth, req.account_id) or _DEFAULT_USAGE_BASE
        response = self.transport(
            HttpRequest(method="GET", url=base + _USAGE_PATH, headers=headers),
            deadline=req.deadline,
        )
        if not response.ok:
            raise TransportError(f"usage HTTP {response.status_code}")
        payload = response.payload if isinstance(response.payload, dict) else {}
        usage = payload.get("qoderUsage")
        if not isinstance(usage, dict):
            raise ValueError("响应缺 qoderUsage（协议形状已变?）")
        collected_at = self._clock()
        cycle_end = self._cycle_end(usage.get("expiresAt"))
        packages = tuple(
            pkg
            for pkg in (
                self._package("plan_quota", "套餐配额", usage.get("userQuota"), cycle_end),
                self._package("add_on_quota", "加量包", usage.get("addOnQuota"), cycle_end),
            )
            if pkg is not None
        )
        return UsageResult(
            snapshot=UsageSnapshot(
                id=new_id(),
                account_id=req.account_id,
                target=req.target,
                collected_at=collected_at,
                packages=packages,
            ),
            aggregate=UsageAggregate(
                id=new_id(),
                account_id=req.account_id,
                target=req.target,
                collected_at=collected_at,
                summary=usage,  # qoderUsage 原话（totalUsagePercentage/quota 形状全保留）
            ),
            ledger=None,
        )

    @staticmethod
    def _package(package_id: str, name: str, spec: Any, cycle_end: datetime | None) -> PackageQuota | None:
        if not isinstance(spec, dict):
            return None
        total = _num(spec.get("total"))
        if total is None or total <= 0:
            return None  # 全 0 = 无此配额（真机实况：套餐配额当前账号无），不造空包
        used = _num(spec.get("used")) or 0.0
        remaining = _num(spec.get("remaining"))
        if remaining is None:
            remaining = max(total - used, 0.0)
        return PackageQuota(
            package_id=package_id,
            name=name,
            total=total,
            used=used,
            remaining=remaining,
            unit=str(spec.get("unit") or "credits"),
            cycle_end=cycle_end,
        )

    @staticmethod
    def _cycle_end(expires_at: Any) -> datetime | None:
        ms = _num(expires_at)
        if ms is None or ms >= _FAR_FUTURE_MS:
            return None  # 9999 占位 = 无月度重置语义（真机取证 PROTOCOL §7.1）
        return datetime.fromtimestamp(ms / 1000, tz=timezone.utc)


def build_usage_port(*, vault, transport=None, auth=None, kinds=()) -> QoderUsagePort:
    """registry usage.collect entry（契约对齐 adapter build_port 注入面）。"""
    return QoderUsagePort(vault=vault, transport=transport, auth=auth, kinds=tuple(kinds))
