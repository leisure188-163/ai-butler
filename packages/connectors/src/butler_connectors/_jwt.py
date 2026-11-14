"""JWT 瘦读取（只解 claim，不验签）：凭据有效期入库（vault.expires_at）用。

不验签是刻意的——过期元数据只需要 exp事实，签名验证是客户端的事；
取不到 exp 如实返回 None，调用方决定是否入库（不静默编造有效期）。
"""

from __future__ import annotations

import base64
import binascii
import json
from datetime import UTC, datetime
from typing import Any


def jwt_claims(token: str) -> dict[str, Any]:
    """解 JWT payload（无验签）。形不合法显式报错。"""
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError(f"不是 JWT 形状（{len(parts)} 段）: <token>")
    payload = parts[1]
    padding = "=" * (-len(payload) % 4)
    try:
        data = json.loads(base64.urlsafe_b64decode(payload + padding))
    except (binascii.Error, json.JSONDecodeError) as exc:
        raise ValueError(f"JWT payload 解不开: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("JWT payload 应为对象")
    return data


def jwt_exp(token: str) -> datetime | None:
    """取出 exp claim（epoch 秒）；没有就 None——不编造有效期。"""
    claims = jwt_claims(token)
    exp = claims.get("exp")
    if isinstance(exp, (int, float)) and exp > 0:
        return datetime.fromtimestamp(exp, tz=UTC)
    return None
