"""Qoder CN/Global 的账户区域与显示名判定（从 dockio 拆出控制行数）。

只读会话/user 元数据；不扫描、不注册。Windows 的双数据目录属于同一产品，
不能只凭目录名一刀切：优先看 avatar 域与 authenticationContext。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from butler_core.accounts.ports import CredentialMissing, CredentialRevoked

from butler_connectors.unlock import session_from_dpapi_gcm_v10


def qoder_main_identity(ctx: Any, conn_id: str) -> str | None:
    """已有 ``:main`` 卡的登录 user id；切换 CN 账户时用于避免覆盖旧主卡。

    返回 None = 还没有 :main（首账户可用 main）；返回空串 = 有 :main 但
    当前无法解码（一律用 hash key，宁可新增也不覆盖旧卡）。
    """
    loader = getattr(ctx.vault, "load", None)
    if loader is None:
        return None
    try:
        secret = loader(f"{conn_id}:main", ["dpapi_gcm_v10"])[0]
    except CredentialRevoked:
        return ""
    except CredentialMissing:
        return None
    except (IndexError, KeyError):
        return None
    except (OSError, RuntimeError, ValueError):
        return ""
    try:
        session = session_from_dpapi_gcm_v10(secret.expose())
    except (OSError, RuntimeError, ValueError):
        return ""
    user = session.get("user") if isinstance(session.get("user"), dict) else {}
    return str(user.get("id") or "")


def qoder_region(session: dict, data_dir: Path, platform: str) -> str:
    """判定产品域：优先会话里的头像域/认证上下文，其次数据目录名与平台。

    Qoder CN：avatar 域 qoder.com.cn；Qoder Global：qoder.com，且会话多
    authenticationContext。mac 的 com.qoder.platform 是 CN 客户端（旧目录名），
    Windows 的 com.qoder.platform 是 Global，不能只凭目录名一刀切。
    """
    user = session.get("user") if isinstance(session.get("user"), dict) else {}
    avatar = str(user.get("avatarUrl") or "")
    if "qoder.com.cn" in avatar:
        return "cn"
    if "qoder.com" in avatar:
        return "global"
    if "authenticationContext" in session:
        return "global"
    name = data_dir.name.casefold()
    if name.startswith("com.qodercn.platform"):
        return "cn"
    if name.startswith("com.qoder.platform"):
        return "global" if platform == "win32" else "cn"
    return "cn"


def qoder_display(region: str, user: dict) -> str:
    """账户显示名：区域 + 客户端里的 name/email（没有就交给 platform.display）。"""
    label = next(
        (
            str(user.get(key))
            for key in ("name", "email", "phone", "id")
            if user.get(key)
        ),
        "",
    )
    if not label:
        return ""
    return f"Qoder {'CN' if region == 'cn' else 'Global'} · {label}"
