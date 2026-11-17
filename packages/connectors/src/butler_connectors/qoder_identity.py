"""Qoder CN/Global 的账户区域与显示名判定（从 dockio 拆出控制行数）。

只读会话/user 元数据；不扫描、不注册。Windows 的双数据目录属于同一产品，
不能只凭目录名一刀切：优先看 avatar 域与 authenticationContext。
"""

from __future__ import annotations

from pathlib import Path


def qoder_region(session: dict, data_dir: Path, platform: str) -> str:
    """判定产品域：优先会话里的头像域/认证上下文，其次数据目录名与平台。

    Qoder CN：avatar 域 qoder.com.cn；Qoder Global：qoder.com，且会话多
    authenticationContext。mac 的 com.qoder.app 是 CN 客户端（旧目录名），
    Windows 的 com.qoder.app 是 Global，不能只凭目录名一刀切。
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
    if name.startswith("com.qodercn.app"):
        return "cn"
    if name.startswith("com.qoder.app"):
        return "global" if platform == "win32" else "cn"
    return "cn"


def qoder_display(region: str, user: dict) -> str:
    """账户显示名：区域 + 客户端里的 name/email（没有就交给 app.display）。"""
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
