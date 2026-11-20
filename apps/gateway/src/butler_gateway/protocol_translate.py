"""网关跨协议互译（ADR-033 后续）：OpenAI ↔ Anthropic 请求/响应纯函数。

- 只做**有损可解释**的字段映射：文本、system、工具调用/结果、max_tokens、
  temperature/top_p/stop、tool_choice、usage、stop_reason。
- 不支持的形状（图片/多模态、n>1、top_k、thinking、response_format 等）显式抛
  ``TranslationError``，由 ProviderUpstream 转成 400/502，**不静默丢弃语义**。
- Gemini 未纳入本模块（ADR-033：协议互译后续阶段；网关对 gemini 接入源显式 skipped）。
"""

from __future__ import annotations

import json
import time
from typing import Any

_OPENAI_ALLOWED = {
    "model", "messages", "max_tokens", "max_completion_tokens", "temperature",
    "top_p", "stop", "tools", "tool_choice", "stream", "n", "user",
}
_ANTHROPIC_ALLOWED = {
    "model", "messages", "max_tokens", "temperature", "top_p", "stop_sequences",
    "tools", "tool_choice", "system", "metadata", "stream",
}


class TranslationError(ValueError):
    """协议形状无法无损映射（调用方映射 400/502，不吞）。"""


def translate_request(payload: dict, src: str, dst: str) -> dict:
    """客户端协议 → 上游协议；同协议原样返回（不复制、不改写）。"""
    if src == dst:
        return payload
    if src == "openai" and dst == "anthropic":
        return openai_to_anthropic_request(payload)
    if src == "anthropic" and dst == "openai":
        return anthropic_to_openai_request(payload)
    raise TranslationError(f"不支持的互译方向 {src}->{dst}")


def translate_response(body: dict, src: str, dst: str, *, model: str) -> dict:
    """上游协议 → 客户端协议；同协议原样返回。"""
    if src == dst:
        return body
    if src == "anthropic" and dst == "openai":
        return anthropic_to_openai_response(body, model=model)
    if src == "openai" and dst == "anthropic":
        return openai_to_anthropic_response(body, model=model)
    raise TranslationError(f"不支持的互译方向 {src}->{dst}")


def error_body(protocol: str, message: str) -> dict:
    """按客户端协议生成错误体（otranslation 失败/上游错误统一用）。"""
    if protocol == "anthropic":
        return {"type": "error", "error": {"type": "invalid_request_error", "message": message}}
    return {"error": {"message": message}}


# ── 请求：OpenAI → Anthropic ──


def openai_to_anthropic_request(payload: dict) -> dict:
    _reject_unknown(payload, _OPENAI_ALLOWED, protocol="openai")
    if payload.get("stream"):
        raise TranslationError("流式请求暂不支持跨协议互译")
    if payload.get("n", 1) != 1:
        raise TranslationError("n>1 暂不支持跨协议互译")
    messages = payload.get("messages")
    if not isinstance(messages, list) or not messages:
        raise TranslationError("messages 必须为非空数组")

    system_parts: list[str] = []
    converted: list[dict] = []
    for msg in messages:
        if not isinstance(msg, dict):
            raise TranslationError("messages 每项必须是对象")
        role = msg.get("role")
        if role == "system":
            system_parts.append(_openai_text(msg.get("content")))
        elif role == "user":
            converted.append({"role": "user", "content": _openai_text(msg.get("content"))})
        elif role == "assistant":
            blocks = _openai_assistant_blocks(msg)
            if not blocks:
                raise TranslationError("assistant 消息既无文本也无 tool_calls")
            converted.append({"role": "assistant", "content": blocks})
        elif role == "tool":
            block = {
                "type": "tool_result",
                "tool_use_id": msg.get("tool_call_id") or "",
                "content": _openai_text(msg.get("content")),
            }
            if not block["tool_use_id"]:
                raise TranslationError("tool 消息缺 tool_call_id")
            if converted and converted[-1]["role"] == "user" and all(
                isinstance(b, dict) and b.get("type") == "tool_result"
                for b in converted[-1]["content"]
            ):
                converted[-1]["content"].append(block)
            else:
                converted.append({"role": "user", "content": [block]})
        else:
            raise TranslationError(f"不支持的消息角色 {role!r}")

    out: dict = {
        "model": payload.get("model"),
        "max_tokens": _max_tokens(payload),
        "messages": converted,
    }
    if system_parts:
        out["system"] = "\n".join(system_parts)
    for src_key, dst_key in (("temperature", "temperature"), ("top_p", "top_p")):
        if src_key in payload:
            out[dst_key] = payload[src_key]
    if payload.get("stop") is not None:
        stop = payload["stop"]
        out["stop_sequences"] = [stop] if isinstance(stop, str) else list(stop)
    if payload.get("tools") is not None:
        out["tools"] = _openai_tools_to_anthropic(payload["tools"])
    if payload.get("tool_choice") is not None:
        out["tool_choice"] = _openai_tool_choice_to_anthropic(payload["tool_choice"])
    if payload.get("user") is not None:
        out["metadata"] = {"user_id": str(payload["user"])}
    return out


def _openai_assistant_blocks(msg: dict) -> list[dict]:
    blocks: list[dict] = []
    text = _openai_text(msg.get("content"))
    if text:
        blocks.append({"type": "text", "text": text})
    for call in msg.get("tool_calls") or []:
        fn = call.get("function") if isinstance(call, dict) else None
        if not isinstance(fn, dict):
            raise TranslationError("tool_calls 形状非法")
        blocks.append(
            {
                "type": "tool_use",
                "id": call.get("id") or "",
                "name": fn.get("name") or "",
                "input": _loads_arguments(fn.get("arguments")),
            }
        )
    return blocks


def _openai_tools_to_anthropic(tools: Any) -> list[dict]:
    if not isinstance(tools, list) or not tools:
        raise TranslationError("tools 必须为非空数组")
    out: list[dict] = []
    for tool in tools:
        fn = tool.get("function") if isinstance(tool, dict) else None
        if not isinstance(fn, dict):
            raise TranslationError("tools 只支持 type=function")
        out.append(
            {
                "name": fn.get("name") or "",
                "description": fn.get("description") or "",
                "input_schema": fn.get("parameters") or {"type": "object", "properties": {}},
            }
        )
    return out


def _openai_tool_choice_to_anthropic(choice: Any) -> dict:
    if choice == "auto":
        return {"type": "auto"}
    if choice == "required":
        return {"type": "any"}
    if choice == "none":
        return {"type": "none"}
    if isinstance(choice, dict):
        fn = choice.get("function") or {}
        if choice.get("type") == "function" and fn.get("name"):
            return {"type": "tool", "name": fn["name"]}
    raise TranslationError("tool_choice 形状暂不支持")


# ── 请求：Anthropic → OpenAI ──


def anthropic_to_openai_request(payload: dict) -> dict:
    _reject_unknown(payload, _ANTHROPIC_ALLOWED, protocol="anthropic")
    if payload.get("stream"):
        raise TranslationError("流式请求暂不支持跨协议互译")
    messages = payload.get("messages")
    if not isinstance(messages, list) or not messages:
        raise TranslationError("messages 必须为非空数组")

    out_messages: list[dict] = []
    system = payload.get("system")
    if system is not None:
        out_messages.append({"role": "system", "content": _anthropic_text(system)})
    for msg in messages:
        if not isinstance(msg, dict):
            raise TranslationError("messages 每项必须是对象")
        role = msg.get("role")
        content = msg.get("content")
        if role == "assistant":
            text, tool_calls = _anthropic_assistant_to_openai(content)
            entry: dict = {"role": "assistant", "content": text}
            if tool_calls:
                entry["tool_calls"] = tool_calls
            out_messages.append(entry)
        elif role == "user":
            out_messages.extend(_anthropic_user_to_openai(content))
        else:
            raise TranslationError(f"不支持的消息角色 {role!r}（system 请放顶层 system 字段）")

    out: dict = {
        "model": payload.get("model"),
        "messages": out_messages,
        "max_tokens": payload.get("max_tokens", 4096),
    }
    if "temperature" in payload:
        out["temperature"] = payload["temperature"]
    if "top_p" in payload:
        out["top_p"] = payload["top_p"]
    if payload.get("stop_sequences") is not None:
        out["stop"] = list(payload["stop_sequences"])
    if payload.get("tools") is not None:
        out["tools"] = _anthropic_tools_to_openai(payload["tools"])
    if payload.get("tool_choice") is not None:
        out["tool_choice"] = _anthropic_tool_choice_to_openai(payload["tool_choice"])
    metadata = payload.get("metadata")
    if isinstance(metadata, dict) and metadata.get("user_id"):
        out["user"] = str(metadata["user_id"])
    return out


def _anthropic_assistant_to_openai(content: Any) -> tuple[str | None, list[dict]]:
    if isinstance(content, str):
        return content, []
    if not isinstance(content, list):
        raise TranslationError("assistant content 形状非法")
    texts: list[str] = []
    calls: list[dict] = []
    for block in content:
        if not isinstance(block, dict):
            raise TranslationError("content block 形状非法")
        if block.get("type") == "text":
            texts.append(block.get("text") or "")
        elif block.get("type") == "tool_use":
            calls.append(
                {
                    "id": block.get("id") or "",
                    "type": "function",
                    "function": {
                        "name": block.get("name") or "",
                        "arguments": json.dumps(block.get("input") or {}, ensure_ascii=False),
                    },
                }
            )
        else:
            raise TranslationError(f"assistant 不支持 content 类型 {block.get('type')!r}")
    return ("".join(texts) or None), calls


def _anthropic_user_to_openai(content: Any) -> list[dict]:
    if isinstance(content, str):
        return [{"role": "user", "content": content}]
    if not isinstance(content, list):
        raise TranslationError("user content 形状非法")
    texts: list[str] = []
    results: list[dict] = []
    for block in content:
        if not isinstance(block, dict):
            raise TranslationError("content block 形状非法")
        if block.get("type") == "text":
            texts.append(block.get("text") or "")
        elif block.get("type") == "tool_result":
            results.append(
                {
                    "role": "tool",
                    "tool_call_id": block.get("tool_use_id") or "",
                    "content": _anthropic_text(block.get("content")),
                }
            )
        else:
            raise TranslationError(f"user 不支持 content 类型 {block.get('type')!r}")
    out = results
    if texts:
        out.append({"role": "user", "content": "".join(texts)})
    if not out:
        raise TranslationError("user 消息没有可用内容")
    return out


def _anthropic_tools_to_openai(tools: Any) -> list[dict]:
    if not isinstance(tools, list) or not tools:
        raise TranslationError("tools 必须为非空数组")
    return [
        {
            "type": "function",
            "function": {
                "name": tool.get("name") or "",
                "description": tool.get("description") or "",
                "parameters": tool.get("input_schema") or {"type": "object", "properties": {}},
            },
        }
        for tool in tools
        if isinstance(tool, dict)
    ]


def _anthropic_tool_choice_to_openai(choice: Any) -> Any:
    if not isinstance(choice, dict):
        raise TranslationError("tool_choice 形状暂不支持")
    kind = choice.get("type")
    if kind == "auto":
        return "auto"
    if kind == "any":
        return "required"
    if kind == "none":
        return "none"
    if kind == "tool" and choice.get("name"):
        return {"type": "function", "function": {"name": choice["name"]}}
    raise TranslationError("tool_choice 形状暂不支持")


# ── 响应：Anthropic → OpenAI ──


def anthropic_to_openai_response(body: dict, *, model: str) -> dict:
    content = body.get("content")
    if not isinstance(content, list):
        raise TranslationError("Anthropic 响应缺 content 数组")
    texts: list[str] = []
    tool_calls: list[dict] = []
    for block in content:
        if not isinstance(block, dict):
            raise TranslationError("Anthropic content block 形状非法")
        if block.get("type") == "text":
            texts.append(block.get("text") or "")
        elif block.get("type") == "tool_use":
            tool_calls.append(
                {
                    "id": block.get("id") or "",
                    "type": "function",
                    "function": {
                        "name": block.get("name") or "",
                        "arguments": json.dumps(block.get("input") or {}, ensure_ascii=False),
                    },
                }
            )
        else:
            raise TranslationError(f"Anthropic 响应不支持 content 类型 {block.get('type')!r}")

    message: dict = {"role": "assistant", "content": "".join(texts) or None}
    if tool_calls:
        message["tool_calls"] = tool_calls
    usage = body.get("usage") if isinstance(body.get("usage"), dict) else {}
    return {
        "id": body.get("id") or f"chatcmpl-{int(time.time())}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": body.get("model") or model,
        "choices": [
            {
                "index": 0,
                "message": message,
                "finish_reason": _anthropic_stop_to_openai(body.get("stop_reason")),
            }
        ],
        "usage": {
            "prompt_tokens": _int(usage.get("input_tokens")),
            "completion_tokens": _int(usage.get("output_tokens")),
            "total_tokens": _int(usage.get("input_tokens")) + _int(usage.get("output_tokens")),
        },
    }


def _anthropic_stop_to_openai(reason: Any) -> str:
    return {
        "end_turn": "stop",
        "stop_sequence": "stop",
        "max_tokens": "length",
        "tool_use": "tool_calls",
    }.get(reason, "stop")


# ── 响应：OpenAI → Anthropic ──


def openai_to_anthropic_response(body: dict, *, model: str) -> dict:
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        raise TranslationError("OpenAI 响应缺 choices 数组")
    choice = choices[0]
    message = choice.get("message") if isinstance(choice, dict) else None
    if not isinstance(message, dict):
        raise TranslationError("OpenAI 响应缺 message 对象")

    blocks: list[dict] = []
    text = message.get("content")
    if isinstance(text, str) and text:
        blocks.append({"type": "text", "text": text})
    for call in message.get("tool_calls") or []:
        fn = call.get("function") if isinstance(call, dict) else None
        if not isinstance(fn, dict):
            raise TranslationError("OpenAI 响应 tool_calls 形状非法")
        blocks.append(
            {
                "type": "tool_use",
                "id": call.get("id") or "",
                "name": fn.get("name") or "",
                "input": _loads_arguments(fn.get("arguments")),
            }
        )
    if not blocks:
        raise TranslationError("OpenAI 响应既无文本也无 tool_calls")

    usage = body.get("usage") if isinstance(body.get("usage"), dict) else {}
    return {
        "id": body.get("id") or f"msg_{int(time.time())}",
        "type": "message",
        "role": "assistant",
        "model": body.get("model") or model,
        "content": blocks,
        "stop_reason": _openai_finish_to_anthropic(choice.get("finish_reason")),
        "stop_sequence": None,
        "usage": {
            "input_tokens": _int(usage.get("prompt_tokens")),
            "output_tokens": _int(usage.get("completion_tokens")),
        },
    }


def _openai_finish_to_anthropic(reason: Any) -> str:
    return {
        "stop": "end_turn",
        "length": "max_tokens",
        "tool_calls": "tool_use",
        "content_filter": "end_turn",
    }.get(reason, "end_turn")


# ── 共用小工具 ──


def _reject_unknown(payload: dict, allowed: set[str], *, protocol: str) -> None:
    extra = [k for k, v in payload.items() if k not in allowed and v is not None]
    if extra:
        raise TranslationError(f"{protocol} 字段暂不支持跨协议互译：{', '.join(sorted(extra))}")


def _openai_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if not isinstance(part, dict):
                raise TranslationError("content part 形状非法")
            if part.get("type") not in ("text", "input_text"):
                raise TranslationError(f"仅支持文本内容，收到 {part.get('type')!r}")
            parts.append(part.get("text") or "")
        return "".join(parts)
    raise TranslationError("content 形状非法")


def _anthropic_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "text":
                raise TranslationError("仅支持文本 content block")
            parts.append(block.get("text") or "")
        return "".join(parts)
    raise TranslationError("content 形状非法")


def _max_tokens(payload: dict) -> int:
    value = payload.get("max_tokens") or payload.get("max_completion_tokens") or 4096
    if not isinstance(value, int) or value <= 0:
        raise TranslationError("max_tokens 必须为正整数")
    return value


def _loads_arguments(raw: Any) -> dict:
    if isinstance(raw, dict):
        return raw
    if raw in (None, ""):
        return {}
    if not isinstance(raw, str):
        raise TranslationError("tool arguments 形状非法")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise TranslationError("tool arguments 不是合法 JSON") from exc
    if not isinstance(value, dict):
        raise TranslationError("tool arguments 必须是 JSON 对象")
    return value


def _int(value: Any) -> int:
    return value if isinstance(value, int) and value >= 0 else 0


__all__ = [
    "TranslationError",
    "anthropic_to_openai_request",
    "anthropic_to_openai_response",
    "error_body",
    "openai_to_anthropic_request",
    "openai_to_anthropic_response",
    "translate_request",
    "translate_response",
]
