"""doubao_cn 用量通道（R2，PROTOCOL §7.2）：quota/records 入账流水裸读。

- 零凭据设计（ADR-007）：CDP 现取 Cookie（现取现用不入 vault），复用签到
  通道的环境束（version_code 运行时派生）与活动页连接（有页附着，无页新开）
- quota/records = 入账 ledger（本机全量 15 条全为正值实证）：cursor 翻页
  （上限 10 页防御）；detail/UI 无余额 → snapshot=None aggregate=None 如实
  申报（绝不造空快照充数）
- probe 失败 CdpError 上抛（客户端不可达 = 暂态，CollectUsage 收进
  outcome.error，不打断编排）
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from butler_core.usage.ports import UsageRequest, UsageResult

from butler_core.shared.ids import new_id
from butler_core.usage.domain import QuotaLedgerEntry

from butler_connectors.cdp import CdpChannel, CdpError, pick_activity_target
from butler_connectors.doubao_cn.adapter import (
    _ACTIVITY_URL,
    _BASE,
    _COMMON_QUERY,
    CONN_ID as _TARGET,
)
from butler_connectors.doubao_cn.identity import (
    load_main_baseline,
    read_all_identities,
    resolve_account_key,
)
from butler_connectors.doubao_cn.localenv import real_env, version_code
from butler_connectors.transport import HttpRequest, Transport, TransportError, httpx_transport

#: 用量通道 UA（spike 实证串；用量端口 M2 仍裁，裸读未收编进 ADR-017 零裸请求）。
_UA_TEMPLATE = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36 SamanthaDoubao/{version}"
)

_RECORDS_PATH = "/alice/ug/campaign/quota/records/"
_MAX_PAGES = 10  # 翻页防御（本机全量 15 条实证远小于此）
_PAGE_SIZE = 100


def _num(value: Any) -> float | None:
    """数值化：int/float 直收；数字串收编（2026-11-12 真机实证 amount 全量为
    type=str，16/16——workbuddy *Precise 数字串兜底同款形状适应）；bool/非数拒绝。"""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


class DoubaoUsagePort:
    """doubao 用量端口：CDP 取会话 + 流水翻页（无余额快照可取）。"""

    def __init__(
        self, *, transport: Transport | None = None, env=None, channel=None, auth=None, kinds: tuple[str, ...] = ()
    ) -> None:
        self.transport = transport if transport is not None else httpx_transport()
        self.env = env if env is not None else real_env()
        self.channel = channel if channel is not None else CdpChannel(self.env.resolve_port())
        self.auth = auth  # registry 透传（零凭据设计：不用，仅存证契约面）
        self.kinds = kinds

    def collect(self, req: UsageRequest) -> UsageResult:
        self.channel.probe()  # CdpError 上抛：客户端不可达 = 暂态（dock 可自动拉起）
        version = self.env.read_version()
        vcode = version_code(version) if version else None
        if not vcode:
            raise ValueError("读不到豆包客户端版本——无法派生 version_code（PROTOCOL §1：写死版本正是故障本身）")
        # 多账户身份守卫：流水接口按会话返回当前活跃账户的数据——目标非活跃时
        # 采了必错挂（A2-02 §6 红线），如实返回空 ledger（不做未激活账户的采集）。
        # 双会话并存口径同 adapter：main 基线命中任一 chat target 即 main 活跃。
        try:
            identities = read_all_identities(self.channel)
        except Exception:
            identities = []
        baseline = load_main_baseline()
        main_active = baseline is not None and any(
            i.sec_uid == baseline.sec_uid for i in identities
        )
        active_key = "main" if main_active else (
            resolve_account_key(identities[0]) if identities else None
        )
        if active_key is None or f"{_TARGET}:{active_key}" != req.account_id:
            return UsageResult(snapshot=None, aggregate=None, ledger=())
        target = pick_activity_target(self.channel.targets())
        conn = (
            self.channel.attach(target)
            if target is not None
            else self.channel.open_activity(_ACTIVITY_URL)
        )
        try:
            cookie_header = self._cookie_header(conn)
            return self._ledger(req, cookie_header, vcode, version)
        finally:
            conn.close()  # 编排全程在连接存活期内，finally 才关（同签到通道纪律）

    # --- 会话现取 ---

    def _cookie_header(self, conn) -> str:
        pairs: dict[str, str] = {}
        for cookie in self.channel.cookies(conn):
            name, value = cookie.get("name"), cookie.get("value")
            if name and value:
                pairs.setdefault(name, value)  # 同名先到先得（同签到通道语义）
        if not pairs:
            raise ValueError("Network.getCookies 返回空——会话异常?")
        return "; ".join(f"{name}={value}" for name, value in pairs.items())

    # --- 流水翻页 ---

    def _ledger(
        self, req: UsageRequest, cookie_header: str, vcode: int, version: str
    ) -> UsageResult:
        entries: list[QuotaLedgerEntry] = []
        cursor = ""
        for _ in range(_MAX_PAGES):
            response = self.transport(
                HttpRequest(
                    method="POST",
                    url=f"{_BASE}{_RECORDS_PATH}?version_code={vcode}&{'&'.join(_COMMON_QUERY)}",
                    headers={
                        "Cookie": cookie_header,
                        "Content-Type": "application/json",
                        "Origin": _BASE,
                        "Referer": _ACTIVITY_URL,
                        "User-Agent": _UA_TEMPLATE.format(version=version),
                    },
                    body={"cursor": cursor, "page_size": _PAGE_SIZE},
                ),
                deadline=req.deadline,
            )
            if not response.ok:
                raise TransportError(f"quota/records HTTP {response.status_code}")
            payload = response.payload if isinstance(response.payload, dict) else {}
            code = payload.get("code")
            if code is not None and str(code) != "0":
                raise ValueError(f"quota/records 业务失败 code={code}——三义码不猜（红线 5）")
            data = payload.get("data")
            data = data if isinstance(data, dict) else {}
            for rec in data.get("records") or []:
                entries.append(self._entry(req, rec))
            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")
            if not isinstance(cursor, str) or not cursor:
                raise ValueError("has_more 为真但缺 next_cursor（协议形状已变?）")
        return UsageResult(snapshot=None, aggregate=None, ledger=tuple(entries))

    @staticmethod
    def _entry(req: UsageRequest, rec: Any) -> QuotaLedgerEntry:
        if not isinstance(rec, dict) or not rec.get("record_id"):
            raise ValueError(f"流水缺 record_id（协议形状已变?）: {str(rec)[:120]}")
        amount = _num(rec.get("amount"))
        if amount is None:
            raise ValueError(f"流水 {rec.get('record_id')!r} amount 非数值（协议形状已变?）")
        ms = _num(rec.get("create_time_ms"))
        occurred_at = (
            datetime.fromtimestamp(ms / 1000, tz=timezone.utc) if ms is not None and ms > 0 else None
        )
        return QuotaLedgerEntry(
            record_id=str(rec["record_id"]),
            account_id=req.account_id,
            target=req.target,
            amount=amount,
            unit=str(rec.get("unit") or ""),
            occurred_at=occurred_at,
            kind=str(rec.get("task_name") or rec.get("task_code") or ""),
            raw=rec,  # 服务端原话（脱敏责任在领域层约定：流水本身无凭据字段）
        )


def build_usage_port(*, vault, transport=None, auth=None, kinds=()) -> DoubaoUsagePort:
    """registry usage.collect entry：vault/auth/kinds 收下但零凭据设计不用（ADR-007）。"""
    return DoubaoUsagePort(transport=transport, auth=auth, kinds=tuple(kinds))
