"""协议面鉴权（ADR-012 裁决 4）：随机 key 生成 + 收紧落盘 + Bearer 校验原语。

- key 兼容 OpenAI/Anthropic 客户端的 Bearer 习惯（``Authorization: Bearer <key>``）
- key 只落本地文件（"仅当前用户可读写"），不进日志、不进 vault、不进契约响应——
  /health 只暴露 sha256 指纹前 12 位（核对身份用，不可反推）
- 启动时无 key 则生成，已有则沿用（幂等：重启不换 key，客户端不用改配置）
- G1 只交付原语；协议面路由（G5）以 ``require_bearer`` 依赖挂载

权限口径（2026-11-16 修正）：**"0600" 只是 POSIX 的说法**。NTFS 不承载 POSIX
权限位，``os.chmod(path, 0o600)`` 在 Windows 上只切只读位、实测 mode 仍是
0o666——同机其他账户照样可读。Windows 一律走 ``icacls`` 撤销继承 + 只授权
当前账户；icacls 不可用时如实告警（不静默假装安全）。
"""

from __future__ import annotations

import getpass
import logging
import os
import secrets
import subprocess
import sys
from pathlib import Path

from fastapi import HTTPException, Request

_KEY_BYTES = 32  # token_urlsafe(32) ≈ 43 字符，熵 256bit

logger = logging.getLogger(__name__)


def generate_key() -> str:
    return secrets.token_urlsafe(_KEY_BYTES)


def load_or_create(key_path: Path) -> str:
    """读 key；不存在则生成并写入（O_EXCL 防并发首启双写竞态）。"""
    for _attempt in range(2):
        if key_path.exists():
            key = key_path.read_text(encoding="utf-8").strip()
            if not key:
                raise SystemExit(
                    f"鉴权 key 文件为空: {key_path}——删除该文件让它重新生成，"
                    "或手工写入一个非空 key（红线 5：不静默兜底）"
                )
            harden_permissions(key_path)
            return key
        key = generate_key()
        key_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            continue  # 并发首启：对方已写好，回读即用
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(key + "\n")
        harden_permissions(key_path)
        return key
    raise SystemExit(f"鉴权 key 文件写入失败（并发竞态未收敛）: {key_path}")


def harden_permissions(path: Path, *, run=subprocess.run) -> bool:
    """把 key 文件收紧到"仅当前用户可读写"；返回是否真正收紧。

    - POSIX：``chmod 0600``（唯一能表达"仅所有者"的机制）
    - Windows：``icacls /inheritance:r /grant:r <user>:F``——撤销继承的
      Users/Authenticated Users 访问，只留当前账户；``run`` 可注入（测试）
    - 失败一律 **显式告警并返回 False**，绝不静默当成成功（红线 5）：
      权限没收回来的 key 文件等于把网关口令摊给同机其他账户
    """
    if sys.platform != "win32":
        os.chmod(path, 0o600)
        return True
    user = os.environ.get("USERNAME") or getpass.getuser()
    if not user:
        logger.warning(
            "网关 key 权限未收紧（无法确定当前账户名）: %s——该文件仍对同机其他账户可读",
            path,
        )
        return False
    try:
        proc = run(
            ["icacls", str(path), "/inheritance:r", "/grant:r", f"{user}:F"],
            capture_output=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning(
            "网关 key 权限未收紧（icacls 不可用: %s）: %s——该文件仍对同机其他账户可读",
            exc,
            path,
        )
        return False
    if proc.returncode != 0:  # type: ignore[union-attr]
        logger.warning(
            "网关 key 权限未收紧（icacls 返回 %s: %s）: %s",
            proc.returncode,  # type: ignore[union-attr]
            _output_tail(proc),  # type: ignore[arg-type]
            path,
        )
        return False
    return True


def _output_tail(proc) -> str:
    """取 icacls 输出的最后一行做告警原文。

    **不做 `text=True`**：Windows 控制台代码页（GBK）与 subprocess 的 UTF-8
    解码在读线程里撞车（会抛 UnicodeDecodeError，把告警本身吞掉）。这里按字节
    取回，先试 UTF-8、再试 mbcs（Windows ANSI）、最后有损解码，永不抛。
    """
    blob = proc.stderr or proc.stdout or b""
    if isinstance(blob, str):  # 注入的假 run 直接给字符串
        return (blob.strip().splitlines() or [""])[-1][:200]
    for encoding in ("utf-8", "mbcs"):
        if encoding == "mbcs" and sys.platform != "win32":
            continue
        try:
            text = blob.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
        return (text.strip().splitlines() or [""])[-1][:200]
    return blob.decode("utf-8", "replace").strip()[:200]


def key_fingerprint(key: str) -> str:
    """/health 暴露的 key 指纹（sha256 前 12 位）——可核对、不可反推。"""
    import hashlib

    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]


def check_bearer(authorization: str | None, key: str) -> bool:
    """Bearer 校验原语。恒时比较，防时序侧信道。"""
    if not authorization:
        return False
    scheme, _, token = authorization.strip().partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return False
    return secrets.compare_digest(token.strip(), key)


def require_bearer(request: Request) -> None:
    """协议面鉴权依赖（G5 挂载点，裁决 4）：key 来自 app.state（lifespan 装载）。"""
    if not check_bearer(request.headers.get("Authorization"), request.app.state.gateway_key):
        raise HTTPException(status_code=401, detail="invalid bearer key")
