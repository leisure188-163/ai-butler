"""上游适配端口与注册表（R4-G5，ADR-012 裁决 5 / A2-02 §3）：provider 插件。

- A2-02 §3：gateway provider 插件**禁止声明式**——适配器是代码注册，不是配置
- G5 M1 只立端口与注册表：各 provider 推理通道取证未回收（plans/02 §3；
  ADR-012 后果「取证不全 = 不开工该 provider」），**不编造请求形状**——
  未注册 provider 在转移编排（forwarder）中如实记 skipped，绝不猜头/猜体
- 适配器实现方职责：凭证 kind 声明、鉴权头组装、端点/请求体形状、
  （取证回收后）流式支持
- 适配器契约：仅账户级失败（connect/timeout/5xx/429/凭据被拒）抛
  ``UpstreamFailure``；请求本身非法（上游 4xx 其他类）以 ``UpstreamReply``
  状态码原样回传，由 forwarder 判定「不转移」
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from butler_core.accounts.domain import Secret


@dataclass(frozen=True)
class UpstreamCall:
    """一次上游调用：兼容面已解析的请求体原话（不派生、不改写）。"""

    payload: dict
    model: str


@dataclass(frozen=True)
class UpstreamReply:
    """上游回复原话：HTTP 状态 + JSON 体（无体 = {}）。端零映射透传。"""

    status: int
    body: dict


class UpstreamFailure(Exception):
    """一次上游尝试失败（账户级，可转移）。detail 禁含凭据/明文 token（A2-02 §8）。"""

    def __init__(self, outcome: str, *, status: int | None = None, detail: str = "") -> None:
        super().__init__(detail or outcome)
        self.outcome = outcome  # connect / timeout / status_5xx / status_429 / cred_rejected
        self.status = status
        self.detail = detail


class ProviderUpstream(Protocol):
    """provider 上游适配器：转发一次非流式推理调用（异步）。"""

    @property
    def provider(self) -> str:
        """connector id（与 Account.provider 同源编址）。"""
        ...

    @property
    def credential_kind(self) -> str:
        """本 provider 转发所需的最小授权凭据 kind（一次只解密一个）。"""
        ...

    async def forward(
        self, account_id: str, credential: Secret, call: UpstreamCall
    ) -> UpstreamReply:
        """转发一次调用；账户级失败抛 UpstreamFailure（转移语义见模块 docstring）。"""
        ...


_REGISTRY: dict[str, ProviderUpstream] = {}


def register_upstream(adapter: ProviderUpstream, *, replace: bool = False) -> None:
    """注册 provider 适配器；重复注册显式拒绝（replace=True 才可重装）。"""
    existing = _REGISTRY.get(adapter.provider)
    if existing is not None and existing is not adapter and not replace:
        raise ValueError(
            f"provider {adapter.provider!r} 上游适配器重复注册（显式 replace=True 才可重装）"
        )
    _REGISTRY[adapter.provider] = adapter


def upstream_for(provider: str) -> ProviderUpstream | None:
    """按 provider 取适配器；未注册返回 None（调用方如实记 skipped，不猜）。"""
    return _REGISTRY.get(provider)


def registered_providers() -> tuple[str, ...]:
    """已注册 provider 清单（/health 观测面用，稳定排序）。"""
    return tuple(sorted(_REGISTRY))
