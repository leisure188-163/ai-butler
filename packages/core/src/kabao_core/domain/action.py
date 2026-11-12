"""动作模型（A2-01 §3）：Action = (kind, target, params)。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Mapping

from kabao_core.domain.errors import DomainError


class ActionKind(StrEnum):
    """动作类型全集（A2-01 §3）。gateway.route 只读配置，M3 落地。"""

    PROVISION_RUN = "provision.run"
    PROVISION_CLAIM = "provision.claim"
    USAGE_COLLECT = "usage.collect"
    USAGE_QUERY = "usage.query"
    SESSION_EXPORT = "session.export"
    SESSION_IMPORT = "session.import"
    HEALTH_CHECK = "health.check"
    GATEWAY_ROUTE = "gateway.route"

    @property
    def is_idempotent_write(self) -> bool:
        """领取类写动作：幂等键去重适用（session.import 自 M4 起加入）。"""
        return self in _IDEMPOTENT_KINDS


_IDEMPOTENT_KINDS = frozenset({ActionKind.PROVISION_RUN, ActionKind.PROVISION_CLAIM})


class ActionInvalid(DomainError):
    pass


@dataclass(frozen=True)
class Action:
    """Action = (kind, target, params)（A2-01 §3）。

    target 是 Connector id（如 trae_cn）；Provider 下沉为实现细节，不进 UI 导航
    （A2-01 §1）。params 语义上不可变——运行期变更是实现 bug。
    """

    kind: ActionKind
    target: str
    params: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.target.strip():
            raise ActionInvalid("target（connector id）不能为空")
