"""失败转移编排（R4-G5，ADR-012 裁决 5：固定优先级 + 故障转移）。

- 干净路径：循 RouteTable 候选（先 = 优先）逐账户尝试——resolve 账户 →
  platform 上游适配器 → 凭据池 acquire（全审计）→ limiter 持槽 → 上游转发；
  首个成功即回
- 转移语义（仅账户级失败转移）：connect/timeout/5xx/429 → 转下一候选；
  401/403 = 凭据被拒 → pool.invalidate 后转下一候选；其余 4xx = 请求本身
  问题（与账户无关）→ 不转移，原样回传客户端
- 计量与留痕（裁决 7 + 台账语义）：每次尝试（成功/失败）逐调用 Meter 入账
  ——tokens 读上游 usage（由协议面 usage_parser 出产），缺失 0/0 不猜；
  Meter 失败返回 False 不打断转发（R4-G4 RecordUsageSample 台账语义）；
  候选账户不存在 / 适配器未注册 / 缺凭据 = 如实记 skipped 后转下一候选
- 意外异常（凭据池 vault 级等）原样上抛（红线 5），协议面决定 5xx 语义
- 阻塞调用一律 asyncio.to_thread（2026-11-16）：账户读 / 凭据池（credman
  ctypes、vault 写）/ Meter 落账（SQLite，双进程写同库时忙等最坏 5s）都是
  同步磁盘 I/O——本进程定位「常驻 + 高并发」（A1-02），同步 I/O 停在事件
  循环上会卡死全部并发请求，真上游适配器落地前必须先还清这笔债
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from butler_core.accounts.domain import Account
from butler_core.accounts.ports import AccountRepository, CredentialMissing, CredentialPool
from butler_core.platforms.domain import PlatformEntry
from butler_core.platforms.ports import PlatformRepository

from butler_gateway.limiter import AccountLimiter
from butler_gateway.routing import RouteTable
from butler_gateway.upstream import (
    AppUpstream,
    UpstreamCall,
    UpstreamFailure,
    UpstreamReply,
    upstream_for,
)

#: usage 解析器：协议面出产（方言差异收敛在协议面），缺失如实 0/0
UsageParser = Callable[[dict], tuple[int, int]]


@dataclass(frozen=True)
class AttemptRecord:
    """一次候选账户尝试的台账行（502 汇总/审计视图用；禁含凭据明文）。"""

    account_id: str
    outcome: str  # ok / passthrough / skipped:<原因> / error:<类>
    status: int | None
    tokens_in: int
    tokens_out: int
    duration_ms: float | None
    detail: str = ""
    body: dict | None = None  # ok / passthrough 时携带上游 JSON 原话（透传用）


@dataclass(frozen=True)
class ForwardOutcome:
    """一次转发请求的结果：ok = 成功；passthrough = 与账户无关的 4xx 原样回传。"""

    kind: str  # ok / passthrough
    status: int
    body: dict
    attempts: tuple[AttemptRecord, ...]


class NoRouteError(Exception):
    """模型未配置路由规则（协议面映射 404）。"""


class AllAttemptsFailedError(Exception):
    """全部候选账户失败（协议面映射 502，携带逐尝试台账）。"""

    def __init__(self, attempts: tuple[AttemptRecord, ...]) -> None:
        super().__init__(f"全部候选账户失败（{len(attempts)} 次尝试）")
        self.attempts = attempts


class MeterSink(Protocol):
    """Meter 端口形状（engine RecordUsageSample.record 同款签名，台账语义）。"""

    def record(
        self,
        *,
        account_id: str,
        model: str,
        tokens_in: int = 0,
        tokens_out: int = 0,
        duration_ms: float | None = None,
    ) -> bool: ...


@dataclass
class Forwarder:
    """转移编排器：一个请求持一候选一槽，逐候选按序重试（不嵌套，limiter 契约）。"""

    routes: RouteTable
    accounts: AccountRepository
    pool: CredentialPool
    limiter: AccountLimiter
    meter: MeterSink
    platforms: PlatformRepository | None = None
    provider_factory: Callable[[PlatformEntry], AppUpstream] | None = None

    async def forward(
        self,
        model: str,
        payload: dict,
        *,
        usage_parser: UsageParser,
        protocol: str = "openai",
    ) -> ForwardOutcome:
        """按优先级逐候选转发；语义见模块 docstring（三段 + 转移规则）。"""
        candidates = self.routes.route(model)
        if not candidates:
            raise NoRouteError(f"模型 {model!r} 未配置路由规则")
        attempts: list[AttemptRecord] = []
        for account_id in candidates:
            record = await self._attempt(
                account_id,
                model=model,
                payload=payload,
                usage_parser=usage_parser,
                protocol=protocol,
            )
            attempts.append(record)
            if record.outcome == "ok":
                return ForwardOutcome(
                    kind="ok",
                    status=record.status or 200,
                    body=record.body or {},
                    attempts=tuple(attempts),
                )
            if record.outcome == "passthrough":
                return ForwardOutcome(
                    kind="passthrough",
                    status=record.status or 400,
                    body=record.body or {},
                    attempts=tuple(attempts),
                )
        raise AllAttemptsFailedError(tuple(attempts))

    async def _attempt(
        self,
        account_id: str,
        *,
        model: str,
        payload: dict,
        usage_parser: UsageParser,
        protocol: str,
    ) -> AttemptRecord:
        started = time.perf_counter()
        # 阻塞调用一律 to_thread（模块 docstring 末条）：不让同步 I/O 停在事件循环
        account = await asyncio.to_thread(self.accounts.get, account_id)
        if account is None:
            return self._skipped(account_id, "skipped:account_missing", started)
        adapter = upstream_for(account.platform_code)
        if adapter is None:
            adapter, skipped = await self._provider_adapter(account, protocol, started)
            if skipped is not None:
                return skipped
        if adapter is None:  # 静态/动态都取不到（防御；不会静默转成成功）
            return self._skipped(
                account_id,
                f"skipped:upstream_not_ready:{account.platform_code}",
                started,
                detail="推理通道取证未回收，该 platform 未开工（plans/02 §3）",
            )
        try:
            credential = await asyncio.to_thread(
                self.pool.acquire, account_id, adapter.credential_kind
            )
        except CredentialMissing as exc:
            return self._skipped(account_id, "skipped:credential_missing", started, detail=str(exc))
        # 凭据池其他异常（vault 级）原样上抛——红线 5，协议面决定 5xx 语义

        async with self.limiter.slot(account_id):
            try:
                reply = await adapter.forward(
                    account_id,
                    credential,
                    UpstreamCall(payload=payload, model=model, protocol=protocol),
                )
            except UpstreamFailure as exc:
                return await self._failure(account_id, model, exc, started, usage_parser)
            # 适配器意外异常不吞：limiter 槽由上下文释放，异常冒泡（红线 5）

            tokens_in, tokens_out = usage_parser(reply.body)
            await self._meter(account_id, model, tokens_in, tokens_out, started)
            if reply.status < 400:
                return self._record(
                    account_id, "ok", reply.status, tokens_in, tokens_out, started, body=reply.body
                )
            if reply.status in (401, 403):
                # 凭据被拒即失效（vault 写 + 审计，同样不让它停在事件循环上）
                await asyncio.to_thread(
                    self.pool.invalidate, account_id, adapter.credential_kind
                )
                return self._record(
                    account_id,
                    "error:cred_rejected",
                    reply.status,
                    tokens_in,
                    tokens_out,
                    started,
                    detail="凭据被上游拒绝，已失效缓存并转下一候选",
                )
            if reply.status == 429 or reply.status >= 500:
                return self._record(
                    account_id, f"error:status_{reply.status}", reply.status, tokens_in, tokens_out, started
                )
            return self._record(
                account_id, "passthrough", reply.status, tokens_in, tokens_out, started, body=reply.body
            )

    # ── 动态接入源解析（ADR-033）──

    async def _provider_adapter(
        self, account: Account, protocol: str, started: float
    ) -> tuple[AppUpstream | None, AttemptRecord | None]:
        """静态适配器缺失时，按平台册解析用户接入源；不可用如实 skipped。"""
        if self.platforms is None:
            return None, None
        platform = await asyncio.to_thread(self.platforms.get, account.platform_code)
        if platform is None or platform.origin != "user":
            return None, None
        if platform.deprecated_at is not None:
            return None, self._skipped(
                account.id, f"skipped:provider_deprecated:{platform.platform_code}", started
            )
        if platform.protocol not in ("openai", "anthropic"):
            return None, self._skipped(
                account.id,
                f"skipped:provider_protocol_unsupported:{platform.protocol}",
                started,
                detail="gemini 接入源暂未开工（ADR-033：协议互译留待下一阶段）",
            )
        if platform.protocol != protocol:
            return None, self._skipped(
                account.id,
                f"skipped:provider_protocol_mismatch:{platform.protocol}->{protocol}",
                started,
                detail="接入源只接同协议请求；跨协议互译未开工（ADR-033）",
            )
        credential_kind = platform.credential_kinds[0] if platform.credential_kinds else "api_key"
        if credential_kind not in ("api_key", "token"):
            return None, self._skipped(
                account.id,
                f"skipped:provider_credential_unsupported:{credential_kind}",
                started,
                detail="接入源上游目前只支持 api_key/token（Bearer）凭据",
            )
        if self.provider_factory is None:
            return None, self._skipped(
                account.id, "skipped:provider_upstream_unavailable", started
            )
        return self.provider_factory(platform), None

    # ── 台账行构造 ──

    async def _meter(
        self, account_id: str, model: str, tokens_in: int, tokens_out: int, started: float
    ) -> None:
        # Meter 失败返回 False 不打断转发（台账语义，R4-G4）；record 内部审计留痕。
        # SQLite 写是同步 I/O → to_thread（模块 docstring 末条）
        await asyncio.to_thread(
            self.meter.record,
            account_id=account_id,
            model=model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            duration_ms=round((time.perf_counter() - started) * 1000, 1),
        )

    def _skipped(
        self, account_id: str, outcome: str, started: float, *, detail: str = ""
    ) -> AttemptRecord:
        return AttemptRecord(
            account_id=account_id,
            outcome=outcome,
            status=None,
            tokens_in=0,
            tokens_out=0,
            duration_ms=round((time.perf_counter() - started) * 1000, 1),
            detail=detail,
        )

    def _record(
        self,
        account_id: str,
        outcome: str,
        status: int,
        tokens_in: int,
        tokens_out: int,
        started: float,
        *,
        detail: str = "",
        body: dict | None = None,
    ) -> AttemptRecord:
        return AttemptRecord(
            account_id=account_id,
            outcome=outcome,
            status=status,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            duration_ms=round((time.perf_counter() - started) * 1000, 1),
            detail=detail,
            body=body,
        )

    async def _failure(
        self,
        account_id: str,
        model: str,
        exc: UpstreamFailure,
        started: float,
        usage_parser: UsageParser,
    ) -> AttemptRecord:
        # 失败尝试也入账（请求级计数：缺失 0/0 如实，裁决 7）
        tokens_in, tokens_out = usage_parser({})
        await self._meter(account_id, model, tokens_in, tokens_out, started)
        return AttemptRecord(
            account_id=account_id,
            outcome=f"error:{exc.outcome}",
            status=exc.status,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            duration_ms=round((time.perf_counter() - started) * 1000, 1),
            detail=exc.detail,
        )
