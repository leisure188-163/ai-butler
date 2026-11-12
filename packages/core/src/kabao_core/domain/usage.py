"""用量领域模型（R2 块①）：三实体 + 阈值谓词 + 耗尽预测。

- 三实体都挂 account_id（A2-01 §1）：
  · UsageSnapshot —— t 时刻额度状态（PackageQuota 嵌套子结构），是耗尽预测
    与 QUOTA_LOW 变更检测的原料
  · UsageAggregate —— 服务端聚合用量**原话**（不派生、不重算，语义以服务端为准）
  · QuotaLedgerEntry —— 入账流水（record_id 唯一键幂等去重）
- 逐调用明细（UsageSample：tokens_in/out/model/ts/source，A2-01 §1）**原样保留
  给 R4** 反代逐调用通道——四家真机取证双通道 UNSUPPORTED（PROTOCOL §7），
  本模块三实体是聚合口径，不承载逐调用语义（加注记不改义）。
- 数值不取整：面额/余量以服务端原值为准（workbuddy *Precise 字符串字段的
  转换责任在适配器）；单位（credits/POINT）是方言原话，端零映射直渲染。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Mapping

from kabao_core.domain.errors import DomainError


class UsageInvalid(DomainError):
    pass


QUOTA_LOW_RATIO = 0.2  # QUOTA_LOW 默认阈值：remaining/total ≤ 20%（提醒规则节可覆盖）
_MIN_FORECAST_GAP_SECONDS = 3600.0  # 耗尽预测最小帧距 1h：更近的差分外推不可信（宁缺毋滥）


@dataclass(frozen=True)
class PackageQuota:
    """单个资源包的额度状态（UsageSnapshot 嵌套子结构）。

    total/used/remaining/unit/cycle_end/status 均为服务端原话投影——适配器
    负责方言归一（trae 29 包 / qoder addOnQuota / workbuddy 85 包 / doubao 无包）。
    """

    package_id: str
    name: str
    total: float
    used: float
    remaining: float
    unit: str = ""
    cycle_end: datetime | None = None  # 周期结束（月度重置语义的 UI 提示字段）
    status: str = ""  # 服务端包状态原话（如 ACTIVE / 0=在用 3=已耗尽）

    def __post_init__(self) -> None:
        if not self.package_id.strip():
            raise UsageInvalid("PackageQuota 需要非空 package_id")
        if self.total < 0 or self.used < 0 or self.remaining < 0:
            raise UsageInvalid(f"PackageQuota {self.package_id!r} 数值不可为负")


@dataclass(frozen=True)
class UsageSnapshot:
    """额度快照：t 时刻该账号全部资源包的额度状态（相邻快照差分 = 耗尽预测）。"""

    id: str
    account_id: str
    target: str  # connector id
    collected_at: datetime
    packages: tuple[PackageQuota, ...] = ()

    def __post_init__(self) -> None:
        if not self.account_id.strip() or not self.target.strip():
            raise UsageInvalid("UsageSnapshot 需要非空 account_id 与 target")


@dataclass(frozen=True)
class UsageAggregate:
    """用量聚合：服务端返回的聚合用量原话（summary 不派生不重算，端零映射）。"""

    id: str
    account_id: str
    target: str
    collected_at: datetime
    summary: Mapping[str, Any]

    def __post_init__(self) -> None:
        if not self.account_id.strip() or not self.target.strip():
            raise UsageInvalid("UsageAggregate 需要非空 account_id 与 target")


@dataclass(frozen=True)
class QuotaLedgerEntry:
    """入账流水：一笔额度入账（如签到 +200）。record_id 是幂等去重唯一键。

    amount 全为正值（doubao quota/records 实证：只有入账无消耗记录）——
    负值 = 协议形状变化，领域层显式拒绝（红线 5）。
    """

    record_id: str
    account_id: str
    target: str
    amount: float
    unit: str
    occurred_at: datetime | None = None  # 服务端时间（create_time_ms 归一）
    kind: str = ""  # 入账类型/来源原话（如「签到」/ task_name）
    raw: Mapping[str, Any] | None = None  # 服务端原话（脱敏责任在适配器）

    def __post_init__(self) -> None:
        if not self.record_id.strip():
            raise UsageInvalid("QuotaLedgerEntry 需要非空 record_id（幂等去重键）")
        if not self.account_id.strip() or not self.target.strip():
            raise UsageInvalid("QuotaLedgerEntry 需要非空 account_id 与 target")
        if self.amount < 0:
            raise UsageInvalid(f"流水 {self.record_id!r} amount 不可为负（入账流水语义）")


@dataclass(frozen=True)
class UsageResult:
    """采集端口结果：三段可空（块①设计字面）。

    - snapshot / aggregate：通道不可得 = None（如实申报，不造空数据）
    - ledger：None = 流水通道不可得；() = 取到了但本期无新流水；非空 = 入账记录
    """

    snapshot: UsageSnapshot | None = None
    aggregate: UsageAggregate | None = None
    ledger: tuple[QuotaLedgerEntry, ...] | None = None


# --- 谓词（core 单源，端零映射，红线 2）---


def quota_ratio(pkg: PackageQuota) -> float | None:
    """余量占比 remaining/total；total ≤ 0 = 无总额信息 → None（谓词不猜）。"""
    if pkg.total <= 0:
        return None
    return pkg.remaining / pkg.total


def is_quota_low(pkg: PackageQuota, *, threshold: float = QUOTA_LOW_RATIO) -> bool:
    """QUOTA_LOW 谓词：占比 ≤ 阈值且**尚未耗尽**（阈值 core 单源）。

    remaining ≤ 0 = 已耗尽终态（历史签到/裂变包永不恢复），没有行动价值，
    不算低额（2026-11-12 真机回归：否则几十个历史包淹没告警）。无总额信息的包不算低。
    """
    if pkg.remaining <= 0:
        return False
    ratio = quota_ratio(pkg)
    return ratio is not None and ratio <= threshold


# --- 耗尽预测（相邻快照差分，块①设计）---


@dataclass(frozen=True)
class ExhaustionForecast:
    """单包耗尽预测：相邻快照差分的外推（不是承诺——如实给速率与依据）。

    per_day 正 = 每天消耗多少；负 = 在回血（签到/月度重置）→ 不预测耗尽。
    """

    package_id: str
    name: str
    unit: str
    remaining: float
    per_day: float
    days_left: float | None  # per_day ≤ 0 → None（按当前速率不会耗尽）
    exhausted_on: Any | None  # date | None：per_day > 0 才有（预计耗尽日）


def forecast_exhaustion(
    previous: UsageSnapshot | None, current: UsageSnapshot
) -> tuple[ExhaustionForecast, ...]:
    """相邻快照差分预测：不足两帧返回 ()——UI 显「采集中」（块①设计字面）。

    只对两帧都出现的包外推；新包（上一帧无）无历史速率，不猜。
    两帧间隔 < MIN_FORECAST_GAP 同样返回 ()（2026-11-12 真机回归：启动补采 +
    手动采集仅隔几分钟 → 差分外推爆炸）——太新鲜的差分不可信，宁缺毋滥。
    """
    if previous is None:
        return ()
    dt = (current.collected_at - previous.collected_at).total_seconds()
    if dt <= 0 or dt < _MIN_FORECAST_GAP_SECONDS:
        return ()
    days = dt / 86400
    prev_by_id = {p.package_id: p for p in previous.packages}
    out: list[ExhaustionForecast] = []
    for pkg in current.packages:
        prev = prev_by_id.get(pkg.package_id)
        if prev is None:
            continue
        per_day = (prev.remaining - pkg.remaining) / days
        days_left: float | None = None
        exhausted_on = None
        if per_day > 0:
            days_left = pkg.remaining / per_day
            exhausted_on = (current.collected_at + timedelta(days=days_left)).date()
        out.append(
            ExhaustionForecast(
                package_id=pkg.package_id,
                name=pkg.name,
                unit=pkg.unit,
                remaining=pkg.remaining,
                per_day=per_day,
                days_left=days_left,
                exhausted_on=exhausted_on,
            )
        )
    return tuple(out)
