"""协议面鉴权（ADR-012 裁决 4）：随机 key 生成 + 0600 落盘 + Bearer 校验原语。

- key 兼容 OpenAI/Anthropic 客户端的 Bearer 习惯（``Authorization: Bearer <key>``）
- key 只落本地文件（0600），不进日志、不进 vault、不进契约响应——/health 只暴露
  sha256 指纹前 12 位（核对身份用，不可反推）
- 启动时无 key 则生成，已有则沿用（幂等：重启不换 key，客户端不用改配置）
- G1 只交付原语；协议面路由（G5）以 ``require_bearer`` 依赖挂载
"""

from __future__ import annotations

import os
import secrets
import stat
from pathlib import Path

_KEY_BYTES = 32  # token_urlsafe(32) ≈ 43 字符，熵 256bit


def generate_key() -> str:
    return secrets.token_urlsafe(_KEY_BYTES)


def load_or_create(key_path: Path) -> str:
    """读 key；不存在则生成并 0600 写入（O_EXCL 防并发首启双写竞态）。"""
    for _attempt in range(2):
        if key_path.exists():
            key = key_path.read_text(encoding="utf-8").strip()
            if not key:
                raise SystemExit(
                    f"鉴权 key 文件为空: {key_path}——删除该文件让它重新生成，"
                    "或手工写入一个非空 key（红线 5：不静默兜底）"
                )
            _ensure_0600(key_path)
            return key
        key = generate_key()
        key_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            continue  # 并发首启：对方已写好，回读即用
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(key + "\n")
        os.chmod(key_path, 0o600)
        return key
    raise SystemExit(f"鉴权 key 文件写入失败（并发竞态未收敛）: {key_path}")


def _ensure_0600(path: Path) -> None:
    """权限纠偏：过宽立即收紧到 0600（危险状态不留存，非业务语义静默降级）。"""
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode != 0o600:
        os.chmod(path, 0o600)


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
