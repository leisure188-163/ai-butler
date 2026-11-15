"""Meter 用例（R4，ADR-012 裁决 7）：网关逐调用计量入账。

- 口径：tokens 优先读上游响应 usage 字段（G5 协议面解析后传入）；缺失 =
  0/0 如实入账（请求级计数 = 样本条数本身），绝不猜数；请求时长 duration_ms
  一并记——「转发必有计量」的落点
- source 固定 "gateway"（A2-06 §2：无来源样本拒绝入账）
- 台账语义（A2-06 §2 不变量 1）：样本写入失败不影响转发主流程——落审计行
  （actor=gateway-meter，outcome=error:<E>）后返回 False；成功不再写审计
  （样本本身就是持久事实，audit 只补「失败即丢了」这一事实）
- 输入非法（负 token / 空 model）= 调用方协议面 bug：UsageInvalid 显式上抛
  不吞（红线 5）；时钟可注入（core 用例同款先例）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Protocol

from butler_core.shared.ids import new_id
from butler_core.shared.time import now_utc
from butler_core.usage.domain import UsageInvalid, UsageSample
from butler_core.usage.ports import UsageStore


class MeterAuditSink(Protocol):
    """审计落账口（engine SqliteAuditLog 同款 record 签名）。"""

    def record(
        self,
        *,
        actor: str,
        action: str,
        outcome: str,
        account_id: str | None = None,
        credential_ref: str | None = None,
    ) -> None: ...


@dataclass
class RecordUsageSample:
    """一次转发请求 = 一条 gateway 样本；写入失败审计留痕并返回 False。"""

    store: UsageStore
    audit: MeterAuditSink
    clock: Callable[[], datetime] = field(default=now_utc)

    def record(
        self,
        *,
        account_id: str,
        model: str,
        tokens_in: int = 0,
        tokens_out: int = 0,
        duration_ms: float | None = None,
    ) -> bool:
        sample = UsageSample(
            id=new_id(),
            account_id=account_id,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            model=model,
            ts=self.clock(),
            source="gateway",
            duration_ms=duration_ms,
        )
        try:
            self.store.append_sample(sample)
        except Exception as exc:  # noqa: BLE001 —— 台账语义：主流程不受影响，但留痕
            self.audit.record(
                actor="gateway-meter",
                action="meter.record",
                outcome=f"error:{type(exc).__name__}",
                account_id=account_id,
            )
            return False
        return True
