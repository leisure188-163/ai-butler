"""trae_cn 用量通道（R2，PROTOCOL §7.1）：ent_usage 聚合原话 + 包分账本快照。

- 鉴权复用 provision 声明式主链（registry.usage_ports 透传 auth/kinds）：
  ss_aes 登录态 → Authorization Cloud-IDE-JWT；device_dn → x-device-id
  （fill_auth_headers 单源拼装，缺字段显式爆）
- usage_summary 原样进 aggregate（不派生，语义以服务端为准）；user_entitlement_pack_list
  逐包映射快照：credits_limit 非数值（无 credits 语义）或 <0（-1=无限）→ 跳过
  ——无余量语义的包造不出 PackageQuota，如实不猜
- trae 无流水通道（PROTOCOL §7.3 双通道 UNSUPPORTED）→ ledger=None 如实申报
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from kabao_core.application.ports import UsageRequest, UsageResult, new_id
from kabao_core.domain.usage import PackageQuota, UsageAggregate, UsageSnapshot
from kabao_core.domain.vault import Secret

from kabao_connectors.decl import fill_auth_headers
from kabao_connectors.transport import (
    HttpRequest,
    Transport,
    TransportError,
    httpx_transport,
)
from kabao_connectors.unlock import unlock_all

_ENT_USAGE_URL = "https://api.trae.cn/trae/api/v2/pay/ide_user_ent_usage"


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _num(value: Any) -> float | None:
    """宽载数值转换：bool 不算数（Python bool 是 int 子类），其余数值返回 float。"""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


class TraeUsagePort:
    """trae 用量端口：声明式主链鉴权 + ent_usage 快照/聚合（无流水）。"""

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
        self.auth = auth  # registry.usage_ports 透传（声明式主链 AuthSpec）
        self.kinds = kinds
        self._clock = clock if clock is not None else _now_utc

    def collect(self, req: UsageRequest) -> UsageResult:
        secrets: dict[str, Secret] = {}
        for kind in self.kinds:
            # 凭据缺失显式上抛（CredentialMissing）——CollectUsage 收进 outcome.error
            secrets[kind] = self._vault.load(req.account_id, [kind])[0]
        fields = unlock_all(self.kinds, secrets)
        headers = fill_auth_headers(self.auth, fields)
        response = self.transport(
            HttpRequest(
                method="POST",
                url=_ENT_USAGE_URL,
                headers=headers,
                body={"require_usage": True, "req_source": 1},  # 数字枚举（§7.1 传字符串 400 实证）
            ),
            deadline=req.deadline,
        )
        if not response.ok:
            raise TransportError(f"usage HTTP {response.status_code}")
        payload = response.payload if isinstance(response.payload, dict) else {}
        code = payload.get("code")
        if code is not None and str(code) != "0":
            raise ValueError(f"usage 业务失败 code={code}——三义码不猜（红线 5）")
        collected_at = self._clock()
        return UsageResult(
            snapshot=UsageSnapshot(
                id=new_id(),
                account_id=req.account_id,
                target=req.target,
                collected_at=collected_at,
                packages=tuple(self._packages(payload.get("user_entitlement_pack_list"))),
            ),
            aggregate=UsageAggregate(
                id=new_id(),
                account_id=req.account_id,
                target=req.target,
                collected_at=collected_at,
                summary=payload.get("usage_summary") or {},  # 服务端聚合原话，不派生
            ),
            ledger=None,
        )

    # --- 包分账本映射 ---

    def _packages(self, listing: Any) -> list[PackageQuota]:
        packages: list[PackageQuota] = []
        for pack in listing or []:
            if not isinstance(pack, dict):
                continue
            base = pack.get("entitlement_base_info")
            if not isinstance(base, dict):
                continue
            quota = base.get("quota")
            limit = _num(quota.get("credits_limit")) if isinstance(quota, dict) else None
            if limit is None or limit < 0:
                continue  # 无 credits 语义（None）/ 无限包（-1）→ 无余量语义，不造包
            usage = pack.get("usage")
            used = _num(usage.get("credits_amount")) if isinstance(usage, dict) else None
            used = used if used is not None else 0.0
            package_id = self._stabilize_id(base, pack)
            if package_id is None:
                continue  # id 与回退依据全缺 → 耗尽预测键无法稳定，跳过不猜
            packages.append(
                PackageQuota(
                    package_id=package_id,
                    name=str(base.get("display_desc") or pack.get("group_name") or package_id),
                    total=limit,
                    used=used,
                    remaining=max(limit - used, 0.0),
                    unit="credits",
                    cycle_end=self._cycle_end(pack.get("expire_time")),
                    status=str(pack.get("status") or ""),
                )
            )
        return packages

    @staticmethod
    def _stabilize_id(base: dict, pack: dict) -> str | None:
        """包 id：entitlement_id 优先；缺则合成 group_name:expire（31 天滚动包可区分）。"""
        ent_id = str(base.get("entitlement_id") or "")
        if ent_id:
            return ent_id
        group = str(pack.get("group_name") or "")
        expire = str(pack.get("expire_time") or "")
        if group or expire:
            return f"{group}:{expire}"
        return None

    @staticmethod
    def _cycle_end(expire_time: Any) -> datetime | None:
        num = _num(expire_time)
        if num is None or num <= 0:
            return None
        return datetime.fromtimestamp(num, tz=timezone.utc)


def build_usage_port(*, vault, transport=None, auth=None, kinds=()) -> TraeUsagePort:
    """registry usage.collect entry（契约对齐 adapter build_port 注入面）。"""
    return TraeUsagePort(vault=vault, transport=transport, auth=auth, kinds=tuple(kinds))
