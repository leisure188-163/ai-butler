"""可注入 HTTP 出站通道：适配器不直接碰 requests/httpx，协议形状全部来自声明。

- Transport 是端口（可注入）：默认实现 httpx；测试换假通道，离线测全链
- deadline 语义（A2-01 §3）：每次调用剩余预算裁超时；到点即停并如实上报，
  不静默延展——被放弃的请求可能仍在后台跑到自然结束（事实随 evidence 上报）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping, Protocol


class TransportError(RuntimeError):
    """网络/超时/解码层面的故障（区别于业务码）：默认当 FAIL 处理并留证据。

    ``status_code`` 只在「HTTP 非 2xx」时携带——声明式连接器据此把
    401/403 归为凭据失效（A2-02 §6），而不是普通 FAIL（避免登录态过期
    被误记成执行失败、进不了待办）。
    """

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class HttpRequest:
    method: str
    url: str
    headers: Mapping[str, str] = field(default_factory=dict)
    body: Any | None = None  # JSON-serializable；None = 无体


@dataclass(frozen=True)
class HttpResponse:
    status_code: int
    payload: Any  # 已解析 JSON（application/json 约定）

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300


class Transport(Protocol):
    """一次 HTTP 调用：调用方给形状 + deadline，实现负责真实出站。"""

    def __call__(self, request: HttpRequest, *, deadline: datetime) -> HttpResponse: ...


def httpx_transport() -> Transport:
    """默认实现（connectors 运行时依赖 httpx；engine/core 与它绝缘）。"""
    import httpx

    def call(request: HttpRequest, *, deadline: datetime) -> HttpResponse:
        remaining = (deadline - datetime.now(deadline.tzinfo)).total_seconds()
        if remaining <= 0:
            raise TransportError(f"时间预算已耗尽（剩余 {remaining:.3f}s），放弃出站")
        try:
            with httpx.Client(timeout=remaining) as client:
                resp = client.request(
                    request.method,
                    request.url,
                    headers=dict(request.headers),
                    json=request.body if request.body is not None else None,
                )
        except httpx.HTTPError as exc:  # 连接/超时/协议错误全算通道故障
            raise TransportError(f"HTTP {request.method} {request.url} 失败: {exc}") from exc
        try:
            payload = resp.json()
        except ValueError as exc:
            raise TransportError(
                f"响应不是合法 JSON（HTTP {resp.status_code}）: {exc}"
            ) from exc
        return HttpResponse(status_code=resp.status_code, payload=payload)

    return call
