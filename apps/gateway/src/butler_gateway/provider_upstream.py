"""用户接入源上游（ADR-033 后续）：手建 relay/local/api 的通用 HTTP 适配。

- 只做 **OpenAI 兼容**（2026-11-20 用户裁决：海外模型/协议不接入）：
  本地 Ollama/vLLM、国内中转与官方 OpenAI 兼容 API 全部走这一套。
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

#: 上游协议词表（网关只支持 OpenAI 兼容）
_SUPPORTED_PROTOCOLS = ("openai",)


def provider_url(base_url: str, protocol: str) -> str:
    """拼 OpenAI 兼容端点；base_url 已带完整路径则原样使用。

    例：`https://relay.example.com/v1` → `…/v1/chat/completions`；
    `https://relay.example.com` → `…/v1/chat/completions`。
    """
    if protocol != "openai":
        raise ValueError(f"不支持的接入源协议 {protocol!r}（仅 openai）")
    base = base_url.rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    if base.endswith("/v1"):
        return base + "/chat/completions"
    return base + "/v1/chat/completions"


def provider_headers(protocol: str, credential: Secret) -> dict[str, str]:
    """OpenAI 兼容鉴权头；protocol 仅作断言，防止未来误接其他协议。"""
    if protocol != "openai":
        raise ValueError(f"不支持的接入源协议 {protocol!r}（仅 openai）")
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
