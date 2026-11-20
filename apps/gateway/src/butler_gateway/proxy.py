"""双协议面（R4-G5，ADR-012 裁决 1/4/5/7）：OpenAI-compatible + Anthropic-compatible。

- 路径 = 行业标准兼容路径：POST ``/v1/chat/completions``（OpenAI 形）、
  POST ``/v1/messages``（Anthropic 形）；鉴权 = ``auth.require_bearer``（裁决 4）
- M1 只做非流式：body.stream 真值 → 422 显式拒绝——上游流式形状取证未回收
  （plans/02 §3；ADR-012 后果「取证不全 = 不开工」），不猜形状，取证后增量
- usage 解析按协议方言收敛在本模块（forwarder 只认 (tokens_in, tokens_out)）：
  OpenAI = usage.prompt_tokens/completion_tokens；Anthropic =
  usage.input_tokens/output_tokens；缺失/形状不对 = 0/0 如实（裁决 7，不猜）
- 请求体上限 20 MiB（413）：本地单用户，LLM 聊天负载远小于此——防无界读
  占内存（fastapi 不代管 body 大小，2026-11-16 补）
- 响应 = 上游 JSON 原话透传（端零映射：不派生不改写）；错误体按各自方言
"""

from __future__ import annotations

import json
from dataclasses import asdict

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from butler_gateway import auth
from butler_gateway.forwarder import (
    AllAttemptsFailedError,
    ForwardOutcome,
    NoRouteError,
    UsageParser,
)

router = APIRouter(tags=["gateway-proxy"])

PROTOCOL_SURFACES: tuple[str, ...] = ("/v1/chat/completions", "/v1/messages")

#: 请求体上限：json.loads(bytes) 自动判编码；先量长再解析
_MAX_BODY_BYTES = 20 * 1024 * 1024


def _parse_usage(body: dict, *, in_key: str, out_key: str) -> tuple[int, int]:
    """按方言取 usage 两元组；缺失/非整数如实 0/0（裁决 7：不猜）。"""
    usage = body.get("usage")
    if not isinstance(usage, dict):
        return (0, 0)
    raw_in, raw_out = usage.get(in_key), usage.get(out_key)
    tokens_in = raw_in if isinstance(raw_in, int) and raw_in >= 0 else 0
    tokens_out = raw_out if isinstance(raw_out, int) and raw_out >= 0 else 0
    return (tokens_in, tokens_out)


def _usage_parser(protocol: str) -> UsageParser:
    if protocol == "openai":
        return lambda body: _parse_usage(body, in_key="prompt_tokens", out_key="completion_tokens")
    return lambda body: _parse_usage(body, in_key="input_tokens", out_key="output_tokens")


def _error_body(protocol: str, message: str, **extra: object) -> dict:
    """错误体按方言：OpenAI = {"error": {...}}；Anthropic = {"type":"error",...}。"""
    if protocol == "anthropic":
        return {"type": "error", "error": {"type": "gateway_error", "message": message, **extra}}
    return {"error": {"message": message, **extra}}


async def _handle(request: Request, protocol: str) -> JSONResponse:
    body_bytes = await request.body()
    if len(body_bytes) > _MAX_BODY_BYTES:
        return JSONResponse(
            _error_body(protocol, f"请求体超过上限 {_MAX_BODY_BYTES} 字节"), status_code=413
        )
    try:
        payload = json.loads(body_bytes)
    except Exception as exc:  # noqa: BLE001 —— 客户端请求体问题，映射 400（红线 5 允许的错误映射）
        return JSONResponse(
            _error_body(protocol, f"请求体非法 JSON：{type(exc).__name__}"), status_code=400
        )
    if not isinstance(payload, dict):
        return JSONResponse(_error_body(protocol, "请求体须为 JSON 对象"), status_code=400)
    if payload.get("stream"):
        return JSONResponse(
            _error_body(
                protocol,
                "流式转发未开工：上游流式形状取证未回收（plans/02 §3），M1 仅非流式",
            ),
            status_code=422,
        )
    model = payload.get("model")
    if not isinstance(model, str) or not model.strip():
        return JSONResponse(_error_body(protocol, "请求体缺 model 字段"), status_code=400)

    forwarder = request.app.state.forwarder
    try:
        outcome: ForwardOutcome = await forwarder.forward(
            model=model,
            payload=payload,
            usage_parser=_usage_parser(protocol),
            protocol=protocol,
        )
    except NoRouteError as exc:
        return JSONResponse(_error_body(protocol, str(exc)), status_code=404)
    except AllAttemptsFailedError as exc:
        return JSONResponse(
            _error_body(
                protocol,
                "全部候选账户失败",
                attempts=[asdict(a) for a in exc.attempts],
            ),
            status_code=502,
        )
    return JSONResponse(outcome.body, status_code=outcome.status)


@router.post("/v1/chat/completions", dependencies=[Depends(auth.require_bearer)])
async def openai_chat_completions(request: Request) -> JSONResponse:
    """OpenAI-compatible 协议面：鉴权 → 转移编排 → 计量 → 原话透传。"""
    return await _handle(request, "openai")


@router.post("/v1/messages", dependencies=[Depends(auth.require_bearer)])
async def anthropic_messages(request: Request) -> JSONResponse:
    """Anthropic-compatible 协议面：同上（方言差异 = usage 键与错误体形状）。"""
    return await _handle(request, "anthropic")
