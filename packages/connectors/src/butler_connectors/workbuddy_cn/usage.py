"""workbuddy_cn 用量通道（R2，PROTOCOL §7.1）：get-user-resource 85 包分账本。

- 现用现取零 vault（ADR-006 决策 3）：session_chain（可注入）= 定位凭据 →
  解析/解密 → 内存建头，返回 (headers, endpoint)；401/403 = 登录态失效显式
  上抛（CollectUsage 收进 outcome.error）
- 时间戳必须是字符串（Go 结构体 string，传数字 400 unmarshal 实证踩坑）；
  当月月初/月末（本机时区）圈定计费周期
- Capacity* 缺失回退 *Precise 字符串版（JS number 精度防御）；CycleEndTime
  无时区字样 → 按 +08:00 归一（服务端日历实证）
- workbuddy 只有包快照（无聚合/流水通道）→ aggregate=None ledger=None 如实
"""

from __future__ import annotations

import calendar
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any

from butler_core.usage.ports import UsageRequest, UsageResult

from butler_core.shared.ids import new_id
from butler_core.usage.domain import PackageQuota, UsageSnapshot

from butler_connectors.transport import HttpRequest, Transport, TransportError, httpx_transport

_GET_USER_RESOURCE_PATH = "/v2/billing/meter/get-user-resource"
_PRODUCT_CODE = "p_tcaca"  # 个人版产品码（PROTOCOL §7.1 实证；企业分支不适用个人账号）
_MAX_PAGES = 5  # 翻页防御（TotalCount 一直不满足也不许死循环）
_PAGE_SIZE = 200
_CN_TZ = timezone(timedelta(hours=8))  # CycleEndTime 无时区字样，按北京时间归一


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _num(primary: Any, fallback: Any = None) -> float | None:
    """宽载数值：bool 不算数；数值直取，数字字符串（*Precise）转换兜底。"""
    for value in (primary, fallback):
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value)
            except ValueError:
                continue
    return None


def _parse_cn_time(value: Any) -> datetime | None:
    """CycleEndTime（"2026-12-01 00:00:00" 无时区）→ +08:00 感知时刻。"""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d %H:%M:%S").replace(tzinfo=_CN_TZ)
    except ValueError as exc:
        raise ValueError(f"CycleEndTime 形状不符（协议形状已变?）: {value!r}") from exc


def _data_node(payload: dict) -> dict:
    """data.Response.Data 取数（PROTOCOL §7.1）；外层 data 信封两形都认
    （同 adapter._dig 的信封防御），路径全缺显式爆，不静默当空。"""
    for node in (payload.get("data"), payload):
        response = node.get("Response") if isinstance(node, dict) else None
        data = response.get("Data") if isinstance(response, dict) else None
        if isinstance(data, dict):
            return data
    raise ValueError("get-user-resource 响应缺 data.Response.Data（协议形状已变?）")


def _real_session_chain(deadline: datetime) -> tuple[dict[str, str], str]:
    """真实凭据链（ADR-006，与签到通道同链路）：定位凭据文件 → 解析/解密 →
    内存建头，用后即弃；endpoint 取凭据内声明（可覆盖），缺省官方端点。"""
    from butler_connectors.workbuddy_cn.credentials import find_auth_file, load_session_retry
    from butler_connectors.workbuddy_cn.localenv import InvalidOverride, real_env
    from butler_connectors.workbuddy_cn.session import (
        AUTH_HELPER_TIMEOUT,
        DEFAULT_ENDPOINT,
        AuthError,
        build_headers,
        decrypt_envelope,
        resolve_session,
    )

    path, _looked_in = find_auth_file()
    if path is None:
        raise AuthError("MISSING_SESSION")
    data = load_session_retry(path)
    remaining = (deadline - datetime.now(deadline.tzinfo)).total_seconds()
    timeout = min(AUTH_HELPER_TIMEOUT, max(remaining, 0.0))

    def _decrypt(envelope: dict) -> str:
        try:
            candidates = real_env().locate_runtime_candidates()
        except InvalidOverride:
            raise AuthError("INVALID_RUNTIME_PATH") from None
        return decrypt_envelope(envelope, candidates=candidates, timeout=timeout)

    session = resolve_session(data, decrypt=_decrypt)
    headers = build_headers(session)
    endpoint = session["auth"].get("endpoint") or DEFAULT_ENDPOINT
    return headers, endpoint


class WorkbuddyUsagePort:
    """workbuddy 用量端口：凭据链现取 + 包分账本快照（当月计费周期）。"""

    def __init__(
        self,
        *,
        transport: Transport | None = None,
        session_chain: Callable[[datetime], tuple[dict[str, str], str]] | None = None,
        clock: Callable[[], datetime] | None = None,
        auth=None,
        kinds: tuple[str, ...] = (),
    ) -> None:
        self.transport = transport if transport is not None else httpx_transport()
        self._chain = session_chain if session_chain is not None else _real_session_chain
        self._clock = clock if clock is not None else _now_utc
        self.auth = auth  # registry 透传（现用现取零 vault：不用，仅存证契约面）
        self.kinds = kinds

    def collect(self, req: UsageRequest) -> UsageResult:
        headers, endpoint = self._chain(req.deadline)  # 凭据链失败显式上抛
        now = self._clock().astimezone()  # 本机时区（计费周期按服务端日历月）
        begin = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        last_day = calendar.monthrange(now.year, now.month)[1]
        end = now.replace(day=last_day, hour=23, minute=59, second=59, microsecond=0)
        accounts: list[dict] = []
        for page in range(1, _MAX_PAGES + 1):
            node = _data_node(self._post_page(endpoint, headers, req.deadline, page, begin, end))
            accounts.extend(a for a in node.get("Accounts") or [] if isinstance(a, dict))
            declared = node.get("TotalCount")
            if isinstance(declared, int):
                if len(accounts) >= declared:
                    break
            elif not node.get("Accounts"):
                break  # 无 TotalCount 形状时：空页即止（防御旧形状）
        return UsageResult(
            snapshot=UsageSnapshot(
                id=new_id(),
                account_id=req.account_id,
                target=req.target,
                collected_at=self._clock(),
                packages=tuple(self._package(acc) for acc in accounts),
            ),
            aggregate=None,
            ledger=None,
        )

    # --- 请求与映射 ---

    def _post_page(
        self,
        endpoint: str,
        headers: dict[str, str],
        deadline: datetime,
        page: int,
        begin: datetime,
        end: datetime,
    ) -> dict:
        response = self.transport(
            HttpRequest(
                method="POST",
                url=f"{endpoint}{_GET_USER_RESOURCE_PATH}",
                headers=headers,
                body={
                    "PageNumber": page,
                    "PageSize": _PAGE_SIZE,
                    "ProductCode": _PRODUCT_CODE,
                    "Status": [0, 3],  # 0=在用 3=已耗尽（PROTOCOL §7.1 实证枚举）
                    # 字符串陷阱（Go 结构体）：传数字 400 unmarshal 错误（首探实证）
                    "PackageEndTimeRangeBegin": str(int(begin.timestamp())),
                    "PackageEndTimeRangeEnd": str(int(end.timestamp())),
                },
            ),
            deadline=deadline,
        )
        if response.status_code in (401, 403):
            raise RuntimeError(
                f"服务端拒绝（HTTP {response.status_code}）——登录态失效，重新登录客户端后重试"
            )
        if not response.ok:
            raise TransportError(f"get-user-resource HTTP {response.status_code}")
        return response.payload if isinstance(response.payload, dict) else {}

    @staticmethod
    def _package(acc: dict) -> PackageQuota:
        resource_id = acc.get("ResourceId")
        if not resource_id:
            raise ValueError(f"包缺 ResourceId（协议形状已变?）: {str(acc)[:120]}")
        total = _num(acc.get("CapacitySize"), acc.get("CapacitySizePrecise"))
        used = _num(acc.get("CapacityUsed"), acc.get("CapacityUsedPrecise"))
        remaining = _num(acc.get("CapacityRemain"), acc.get("CapacityRemainPrecise"))
        if total is None or remaining is None:
            raise ValueError(f"包 {resource_id} 缺额度数值（Capacity* 与 *Precise 均缺，协议形状已变?）")
        name = (
            acc.get("PackageName")
            or acc.get("SubProductName")
            or acc.get("ProductName")
            or resource_id
        )
        status_value = acc.get("Status")
        return PackageQuota(
            package_id=str(resource_id),
            name=str(name),
            total=total,
            used=used if used is not None else 0.0,
            remaining=remaining,
            unit=str(acc.get("CapacityUnit") or ""),
            cycle_end=_parse_cn_time(acc.get("CycleEndTime")),
            status=str(status_value) if status_value is not None else "",  # 0=在用是合法原话
        )


def build_usage_port(*, vault, transport=None, auth=None, kinds=()) -> WorkbuddyUsagePort:
    """registry usage.collect entry：vault/auth/kinds 收下但现用现取零 vault 不用（ADR-006）。"""
    return WorkbuddyUsagePort(transport=transport, auth=auth, kinds=tuple(kinds))
