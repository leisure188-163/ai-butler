"""用户接入源上游（ADR-033 后续）：手建 relay/local/api 的通用 HTTP 适配。

- 只接**同协议**：客户端命中 `/v1/chat/completions` 只发 protocol=openai 的接入源；
  `/v1/messages` 只发 protocol=anthropic。跨协议互译与 gemini 按 ADR-033 留待下一阶段，
  forwarder 侧显式记 skipped，不猜请求/响应形状。
- 连接事实全部来自平台册（base_url/protocol/credential_kinds），不在网关里复制配置；
  密钥来自 vault（默认槽），请求时现取。
- 仅账户级失败（connect/timeout）抛 ``UpstreamFailure``；上游 4xx/5xx 以
  ``UpstreamReply`` 原样回传，由 forwarder 按既有转移规则裁决。
"""

from __future__ import annotations

import httpx

from butler_core.accounts.domain import Secret
from butler_core.platforms.domain import PlatformEntry
from butler_gateway.upstream import AppUpstream, UpstreamCall, UpstreamFailure, UpstreamReply

#: 单次上游超时：本地/中转非流式推理，取 120s 上限；超时 = 账户级失败可转移
_TIMEOUT = httpx.Timeout(120.0, connect=10.0)

#: 上游协议 → 网关客户端协议面（同协议直通）
_SUPPORTED_PROTOCOLS = ("openai", "anthropic")


def provider_url(base_url: str, protocol: str) -> str:
    """按协议拼上游端点；base_url 已带完整路径则原样使用。

    例：`https://relay.example.com/v1` + openai → `…/v1/chat/completions`；
    `https://api.anthropic.com` + anthropic → `…/v1/messages`。
    """
    base = base_url.rstrip("/")
    if protocol == "openai":
        if base.endswith("/chat/completions"):
            return base
        if base.endswith("/v1"):
            return base + "/chat/completions"
        return base + "/v1/chat/completions"
    if protocol == "anthropic":
        if base.endswith("/messages"):
            return base
        if base.endswith("/v1"):
            return base + "/messages"
        return base + "/v1/messages"
    raise ValueError(f"不支持的接入源协议 {protocol!r}（仅 openai/anthropic）")


def provider_headers(protocol: str, credential: Secret) -> dict[str, str]:
    """按协议组装鉴权头；anthropic 固定最小版本头。"""
    if protocol == "anthropic":
        return {
            "x-api-key": credential.expose(),
            "anthropic-version": "2023-06-01",
        }
    return {"Authorization": f"Bearer {credential.expose()}"}


class ProviderUpstream:
    """一个接入源的适配器（每个平台实例一个；HTTP 客户端由 app lifespan 注入）。"""

    def __init__(self, entry: PlatformEntry, client: httpx.AsyncClient) -> None:
        self._entry = entry
        self._client = client

    @property
    def platform(self) -> str:
        return self._entry.platform_code

    @property
    def credential_kind(self) -> str:
        """接入源申报的第一种凭据；未申报回落 api_key（手建表单默认）。"""
        kinds = self._entry.credential_kinds
        return kinds[0] if kinds else "api_key"

    async def forward(
        self, account_id: str, credential: Secret, call: UpstreamCall
    ) -> UpstreamReply:
        url = provider_url(self._entry.base_url, self._entry.protocol)
        headers = provider_headers(self._entry.protocol, credential)
        try:
            response = await self._client.post(
                url, json=call.payload, headers=headers, timeout=_TIMEOUT
            )
        except httpx.TimeoutException as exc:
            raise UpstreamFailure("timeout", detail=f"接入源超时：{type(exc).__name__}") from exc
        except httpx.HTTPError as exc:
            raise UpstreamFailure("connect", detail=f"接入源不可达：{type(exc).__name__}") from exc

        try:
            body = response.json()
        except ValueError:
            # 2xx 非 JSON = 上游形状不对（账户级失败）；4xx/5xx 原样状态回传
            if response.status_code < 400:
                raise UpstreamFailure(
                    "status_5xx", status=response.status_code, detail="接入源返回非 JSON"
                )
            body = {}
        if not isinstance(body, dict):
            body = {}
        return UpstreamReply(status=response.status_code, body=body)


def supported_protocols() -> tuple[str, ...]:
    """网关当前可直接直通的接入源协议（health/测试用）。"""
    return _SUPPORTED_PROTOCOLS


__all__ = [
    "ProviderUpstream",
    "provider_headers",
    "provider_url",
    "supported_protocols",
]
