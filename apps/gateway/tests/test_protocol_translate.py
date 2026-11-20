"""跨协议互译（OpenAI ↔ Anthropic）：纯函数 + ProviderUpstream 闭环。"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime

import httpx
import pytest

from butler_core.accounts.domain import Secret
from butler_core.platforms.domain import PlatformEntry
from butler_gateway.protocol_translate import (
    TranslationError,
    anthropic_to_openai_request,
    anthropic_to_openai_response,
    openai_to_anthropic_request,
    openai_to_anthropic_response,
)
from butler_gateway.provider_upstream import ProviderUpstream
from butler_gateway.upstream import UpstreamCall, UpstreamFailure


def _provider(protocol: str, code: str = "my_relay") -> PlatformEntry:
    return PlatformEntry(
        platform_code=code,
        platform_name=code,
        created_at=datetime(2026, 11, 20, tzinfo=UTC),
        platform_kind="relay",
        base_url="https://relay.example.com",
        protocol=protocol,
        models=(),
        credential_kinds=("api_key",),
        origin="user",
        capabilities=(),
        schedule_times=(),
    )


# ── 请求方向 ──


def test_openai请求转anthropic_system工具与tool结果() -> None:
    payload = {
        "model": "m1",
        "messages": [
            {"role": "system", "content": "你是助手"},
            {"role": "user", "content": [{"type": "text", "text": "查一下"}]},
            {
                "role": "assistant",
                "content": "我来查",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "lookup", "arguments": '{"q":"x"}'},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call_1", "content": "结果"},
        ],
        "max_tokens": 128,
        "temperature": 0.2,
        "stop": ["END"],
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "lookup",
                    "description": "查询",
                    "parameters": {"type": "object", "properties": {"q": {"type": "string"}}},
                },
            }
        ],
        "tool_choice": {"type": "function", "function": {"name": "lookup"}},
    }

    out = openai_to_anthropic_request(payload)
    assert out["system"] == "你是助手"
    assert out["max_tokens"] == 128
    assert out["stop_sequences"] == ["END"]
    assert out["messages"][0] == {"role": "user", "content": "查一下"}
    assert out["messages"][1]["content"][0] == {"type": "text", "text": "我来查"}
    assert out["messages"][1]["content"][1] == {
        "type": "tool_use", "id": "call_1", "name": "lookup", "input": {"q": "x"}
    }
    assert out["messages"][2] == {
        "role": "user",
        "content": [{"type": "tool_result", "tool_use_id": "call_1", "content": "结果"}],
    }
    assert out["tools"][0]["name"] == "lookup"
    assert out["tools"][0]["input_schema"]["properties"]["q"]["type"] == "string"
    assert out["tool_choice"] == {"type": "tool", "name": "lookup"}


def test_anthropic请求转openai_system与工具结果拆角色() -> None:
    payload = {
        "model": "m1",
        "system": [{"type": "text", "text": "系统"}],
        "messages": [
            {"role": "user", "content": "开始"},
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "调用工具"},
                    {"type": "tool_use", "id": "t1", "name": "lookup", "input": {"q": "x"}},
                ],
            },
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": "t1", "content": "结果"},
                    {"type": "text", "text": "继续"},
                ],
            },
        ],
        "max_tokens": 64,
        "stop_sequences": ["END"],
        "tools": [
            {
                "name": "lookup",
                "description": "查询",
                "input_schema": {"type": "object", "properties": {"q": {"type": "string"}}},
            }
        ],
        "tool_choice": {"type": "any"},
    }

    out = anthropic_to_openai_request(payload)
    assert out["messages"][0] == {"role": "system", "content": "系统"}
    assert out["messages"][1] == {"role": "user", "content": "开始"}
    assistant = out["messages"][2]
    assert assistant["content"] == "调用工具"
    assert assistant["tool_calls"][0]["function"]["name"] == "lookup"
    assert json.loads(assistant["tool_calls"][0]["function"]["arguments"]) == {"q": "x"}
    assert out["messages"][3] == {"role": "tool", "tool_call_id": "t1", "content": "结果"}
    assert out["messages"][4] == {"role": "user", "content": "继续"}
    assert out["max_tokens"] == 64
    assert out["stop"] == ["END"]
    assert out["tools"][0]["function"]["parameters"]["properties"]["q"]["type"] == "string"
    assert out["tool_choice"] == "required"


# ── 响应方向 ──


def test_openai响应转anthropic() -> None:
    body = {
        "id": "chatcmpl-1",
        "model": "m1",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "答",
                    "tool_calls": [
                        {"id": "c1", "type": "function",
                         "function": {"name": "lookup", "arguments": '{"q":"x"}'}}
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ],
        "usage": {"prompt_tokens": 11, "completion_tokens": 7},
    }

    out = openai_to_anthropic_response(body, model="m1")
    assert out["type"] == "message"
    assert out["content"][0] == {"type": "text", "text": "答"}
    assert out["content"][1] == {"type": "tool_use", "id": "c1", "name": "lookup", "input": {"q": "x"}}
    assert out["stop_reason"] == "tool_use"
    assert out["usage"] == {"input_tokens": 11, "output_tokens": 7}


def test_anthropic响应转openai() -> None:
    body = {
        "id": "msg_1",
        "model": "m1",
        "content": [
            {"type": "text", "text": "答"},
            {"type": "tool_use", "id": "t1", "name": "lookup", "input": {"q": "x"}},
        ],
        "stop_reason": "max_tokens",
        "usage": {"input_tokens": 9, "output_tokens": 4},
    }

    out = anthropic_to_openai_response(body, model="m1")
    message = out["choices"][0]["message"]
    assert message["content"] == "答"
    assert message["tool_calls"][0]["id"] == "t1"
    assert json.loads(message["tool_calls"][0]["function"]["arguments"]) == {"q": "x"}
    assert out["choices"][0]["finish_reason"] == "length"
    assert out["usage"]["prompt_tokens"] == 9
    assert out["usage"]["total_tokens"] == 13


# ── 显式拒绝，不静默降级 ──


@pytest.mark.parametrize(
    "payload,fragment",
    [
        ({"model": "m", "messages": [{"role": "user",
          "content": [{"type": "image_url", "image_url": {"url": "https://x"}}]}]}, "仅支持文本"),
        ({"model": "m", "messages": [{"role": "user", "content": "hi"}], "n": 2}, "n>1"),
        ({"model": "m", "messages": [{"role": "user", "content": "hi"}],
          "response_format": {"type": "json_object"}}, "response_format"),
        ({"model": "m", "max_tokens": 10, "messages": [{"role": "user", "content": "hi"}],
          "top_k": 5}, "top_k"),
    ],
)
def test_不支持的形状显式抛(payload, fragment) -> None:
    if "max_tokens" in payload:  # Anthropic 形状
        with pytest.raises(TranslationError, match=fragment):
            anthropic_to_openai_request(payload)
    else:
        with pytest.raises(TranslationError, match=fragment):
            openai_to_anthropic_request(payload)


# ── ProviderUpstream 闭环 ──


def _call(protocol: str) -> UpstreamCall:
    if protocol == "anthropic":
        payload = {
            "model": "m1",
            "system": "sys",
            "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": 8,
        }
    else:
        payload = {
            "model": "m1",
            "messages": [{"role": "system", "content": "sys"},
                         {"role": "user", "content": "hi"}],
            "max_tokens": 8,
        }
    return UpstreamCall(payload=payload, model="m1", protocol=protocol)


def test_openai客户端打到anthropic接入源_请求与响应都换形() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.read())
        return httpx.Response(
            200,
            json={
                "id": "msg_1", "type": "message", "role": "assistant", "model": "m1",
                "content": [{"type": "text", "text": "答"}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 3, "output_tokens": 2},
            },
        )

    async def scenario():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            return await ProviderUpstream(_provider("anthropic"), client).forward(
                "my_relay:key1", Secret("sk-1"), _call("openai")
            )
        finally:
            await client.aclose()

    reply = asyncio.run(scenario())
    assert seen["path"] == "/v1/messages"
    assert seen["body"]["system"] == "sys"  # OpenAI system 已提到顶层
    assert seen["body"]["max_tokens"] == 8
    assert reply.body["object"] == "chat.completion"  # 响应已换回 OpenAI 形
    assert reply.body["choices"][0]["message"]["content"] == "答"
    assert reply.body["usage"]["prompt_tokens"] == 3


def test_anthropic客户端打到openai接入源_请求与响应都换形() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.read())
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-1", "object": "chat.completion", "model": "m1",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "答"},
                             "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 2},
            },
        )

    async def scenario():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            return await ProviderUpstream(_provider("openai"), client).forward(
                "my_relay:key1", Secret("sk-1"), _call("anthropic")
            )
        finally:
            await client.aclose()

    reply = asyncio.run(scenario())
    assert seen["path"] == "/v1/chat/completions"
    assert seen["body"]["messages"][0] == {"role": "system", "content": "sys"}
    assert reply.body["type"] == "message"
    assert reply.body["content"][0] == {"type": "text", "text": "答"}
    assert reply.body["usage"] == {"input_tokens": 3, "output_tokens": 2}


def test_互译失败按客户端协议回400且不转移() -> None:
    async def scenario():
        client = httpx.AsyncClient(transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={})
        ))
        try:
            return await ProviderUpstream(_provider("anthropic"), client).forward(
                "my_relay:key1",
                Secret("sk-1"),
                UpstreamCall(payload={"model": "m", "messages": [
                    {"role": "user", "content": [
                        {"type": "image_url", "image_url": {"url": "https://x"}}]}]},
                    model="m", protocol="openai"),
            )
        finally:
            await client.aclose()

    reply = asyncio.run(scenario())
    assert reply.status == 400
    assert "仅支持文本" in reply.body["error"]["message"]
