"""应用层端口（核心向外的承诺，A2-01 §6）：适配器实现这些协议，用例只依赖端口。

- ProvisionPort 用 typing.Protocol（A2-01 §6 字面；结构化类型，适配器无需继承）；
- 台账 / 事件汇 / Vault / 健康状态用 ABC（沿脚手架既有风格）。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Mapping, Protocol
from uuid import uuid4

from kabao_core.domain.account import Account
from kabao_core.domain.action import Action, ActionKind
from kabao_core.domain.errors import DomainError
from kabao_core.domain.event import Event
from kabao_core.domain.health import HealthLevel
from kabao_core.domain.run import Run, RunResult
from kabao_core.domain.usage import (
    QuotaLedgerEntry,
    UsageAggregate,
    UsageResult,
    UsageSnapshot,
)
from kabao_core.domain.vault import CredentialHealth, Secret


def new_id() -> str:
    return uuid4().hex


# --- Kabao 动作执行端口（A2-01 §6）---

@dataclass(frozen=True)
class Capabilities:
    """能力如实申报：端口签名即能力边界，签名里没有的 = 申报不支持 → 用例层拒绝。"""

    dry_run: bool = False  # 支持 dry_run 只报告不领取
    multi_account: bool = False  # 同 Provider 多账户并行
    idempotency_window: str | None = None  # 幂等窗口语义（如 "daily"）；None = 无窗口概念


@dataclass(frozen=True)
class ProvisionRequest:
    """端口入参（AO）：deadline 是时间预算的硬边界（A2-01 §3）。"""

    kind: ActionKind
    target: str
    account_id: str
    params: Mapping[str, str]
    deadline: datetime
    dry_run: bool = False


class ProvisionPort(Protocol):
    """领取类端口（A2-01 §6 字面）：适配器不做语义决策、不解析日志、不维护映射表。"""

    def capabilities(self) -> Capabilities: ...

    def run(self, req: ProvisionRequest) -> RunResult: ...  # 结构化结果，不返回退出码


# --- 端口路由（ADR-003）：M1 起 target（连接器）维度的多路分发 ---

PortSelector = Callable[[Action], "ProvisionPort | None"]
"""端口选择器：用例层按 Action 选端口，None = 未接入（UnsupportedAction）。"""


def routing_ports(
    kind_ports: Mapping[ActionKind, ProvisionPort],
    target_ports: Mapping[str, ProvisionPort],
) -> PortSelector:
    """通用路由：target 精确匹配（连接器）优先，kind 兜底（通用端口）。

    target = connetor id（Action 契约），target 端口由连接器注册表产出
    （ADR-003）；kind 级端口留给跨连接器的通用能力（当前测试用）。
    """

    def select(action: Action) -> ProvisionPort | None:
        return target_ports.get(action.target) or kind_ports.get(action.kind)

    return select


class AccountRepository(ABC):
    """账号名册端口（A2-01 §1）：identity 落库，凭据仍在 vault。"""

    @abstractmethod
    def save(self, account: Account) -> None: ...

    @abstractmethod
    def get(self, account_id: str) -> Account | None: ...

    @abstractmethod
    def list_by_provider(self, provider: str) -> list[Account]: ...

    @abstractmethod
    def list_all(self) -> list[Account]: ...


class RunLedger(ABC):
    """Run 台账端口：幂等查询 + 落账 + 账号历史。SQL 只存在于 engine 适配器（A4-01 §5）。"""

    @abstractmethod
    def save(self, run: Run) -> None: ...

    @abstractmethod
    def find_by_idempotency_key(self, key: str) -> Run | None: ...

    @abstractmethod
    def list_for_account(self, account_id: str, *, limit: int) -> list[Run]:
        """该账号最近的 Run（新→旧）：健康中心读它判 NO_AUTH 连败（A4-01 §2）。"""

    @abstractmethod
    def list_recent(self, *, limit: int) -> list[Run]:
        """全库最近 Run（新→旧）：台账页与"待处理"聚合的数据源（A3-01）。"""


class EventSink(ABC):
    """事件总线端口：L0 实现进程内总线（A4-01 §3）；用例只发布，不关心订阅者。"""

    @abstractmethod
    def publish(self, event: Event) -> None: ...


class CredentialMissing(DomainError):
    """vault.load 缺凭据 kind 的端口语义错误：适配器实现应继承本类。"""


# --- L0 凭据保险库端口（A4-01 §1）---

class VaultPort(ABC):
    """凭据保险库端口：分层存储进 engine 适配器，core 只认这套 API。

    - store：加密入库 + 记录轮换历史
    - load：只解密调用方申报的最小 kinds 集合（最小授权，A2-02 §5）；
      缺 kind 抛 CredentialMissing——适配器错误类型继承本类（语义归 core）
    - rotate：换新 + 旧值进历史（可审计）
    - health：有效期/状态快照，喂给健康中心
    """

    @abstractmethod
    def store(
        self,
        account_id: str,
        kind: str,
        secret: Secret,
        *,
        expires_at: datetime | None = None,
    ) -> None: ...

    @abstractmethod
    def load(self, account_id: str, kinds: list[str]) -> list[Secret]: ...

    @abstractmethod
    def rotate(
        self,
        account_id: str,
        kind: str,
        new_secret: Secret,
        *,
        expires_at: datetime | None = None,
    ) -> None: ...

    @abstractmethod
    def health(self) -> list[CredentialHealth]: ...


class HealthStateStore(ABC):
    """健康扫描的记忆端口：记录"上一次已通知的级别"，变更才产事件（防每日重发）。"""

    @abstractmethod
    def get_credential_notified_level(self, account_id: str, kind: str) -> str | None: ...

    @abstractmethod
    def set_credential_notified_level(
        self, account_id: str, kind: str, level: HealthLevel
    ) -> None: ...

    @abstractmethod
    def get_account_level(self, account_id: str) -> HealthLevel | None: ...

    @abstractmethod
    def set_account_level(self, account_id: str, level: HealthLevel) -> None: ...


# --- R2 用量采集端口（块①设计）---


class UsageRequestInvalid(DomainError):
    """UsageRequest 形状非法（target / account_id 空白）。"""


@dataclass(frozen=True)
class UsageRequest:
    """用量采集入参（AO）：deadline 是时间预算的硬边界（与 ProvisionRequest 同纪律）。"""

    target: str  # connector id（路由键，同 ADR-003 target 精确选路）
    account_id: str
    deadline: datetime

    def __post_init__(self) -> None:
        if not self.target.strip() or not self.account_id.strip():
            raise UsageRequestInvalid("UsageRequest 需要非空 target 与 account_id")


class UsagePort(Protocol):
    """用量采集端口（R2）：适配器取数并归一 PackageQuota，不做语义决策、不派生指标。

    UsageResult 三段可空：通道不可得 = None（如实申报）；取到但空 = 空元组。
    """

    def collect(self, req: UsageRequest) -> UsageResult: ...


class UsageStore(ABC):
    """用量存储端口：三实体落库 + 账号维度读取（SQL 只在 engine 适配器，A4-01 §5 同纪律）。"""

    @abstractmethod
    def save_snapshot(self, snapshot: UsageSnapshot) -> None: ...

    @abstractmethod
    def list_snapshots(self, account_id: str, *, limit: int) -> list[UsageSnapshot]:
        """该账号快照（新→旧）：耗尽预测与 QUOTA_LOW 变更检测取前两帧。"""

    @abstractmethod
    def save_aggregate(self, aggregate: UsageAggregate) -> None: ...

    @abstractmethod
    def latest_aggregate(self, account_id: str) -> UsageAggregate | None: ...

    @abstractmethod
    def append_ledger(self, entries: Iterable[QuotaLedgerEntry]) -> int:
        """入账流水幂等落库（record_id 去重），返回新增条数。"""

    @abstractmethod
    def list_ledger(self, account_id: str, *, limit: int) -> list[QuotaLedgerEntry]: ...
