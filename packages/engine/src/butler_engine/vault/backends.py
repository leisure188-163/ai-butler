"""秘密后端协议 + 内存后端（A4-01 §1 内存层：运行时解密产物，绝不落盘）。

后端只认 (ref, 文本秘密) 三原色；分层策略由 LayeredVault 依据元数据调度。
get 未命中 → VaultCredentialMissing 显式报错，绝不静默给空串。
"""

from __future__ import annotations

from typing import Protocol

from butler_engine.vault.errors import VaultCredentialMissing


class SecretBackend(Protocol):
    """秘密后端形状：机器名 + 存取删。实现不得打印秘密。"""

    name: str

    def put(self, ref: str, value: str) -> None: ...

    def get(self, ref: str) -> str: ...

    def delete(self, ref: str) -> None: ...


class MemoryVaultBackend:
    """字典后端：M0 测试与非桌面平台的显式降级层（进程退出即消失）。"""

    name = "memory"

    def __init__(self) -> None:
        self._items: dict[str, str] = {}

    def put(self, ref: str, value: str) -> None:
        self._items[ref] = value

    def get(self, ref: str) -> str:
        try:
            return self._items[ref]
        except KeyError as e:
            raise VaultCredentialMissing(f"内存层没有 {ref!r} 的记录") from e

    def delete(self, ref: str) -> None:
        self._items.pop(ref, None)
