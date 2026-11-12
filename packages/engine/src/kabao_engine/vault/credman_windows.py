"""Windows 凭据管理器后端（A4-01 §1 Deutschen）：ctypes 调 advapi32，纯标准库。

- CRED_TYPE_GENERIC + CRED_PERSIST_ENTERPRISE；blob = utf-8 秘密
- 与 keychain 同构：put 覆盖写 / get 未命中显式报错 / delete 幂等
- ctypes 结构在 `_make_real_api` 里延迟创建——本文件 import 不-touch win32，
  非 Windows 平台注入假 api 也能单测（逻辑与系统调用解耦）
"""

from __future__ import annotations

import sys
from types import SimpleNamespace
from typing import Any, Callable

from kabao_engine.vault.errors import VaultAccessError, VaultCredentialMissing

# wincred.h 常量
_CRED_TYPE_GENERIC = 1
_CRED_PERSIST_ENTERPRISE = 2
_ERR_NOT_FOUND = 1168  # ERROR_NOT_FOUND


def _make_real_api() -> Callable[..., Any]:
    """在 Windows 上构造真 ctypes 适配；调用即加载 advapi32。"""
    import ctypes

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)

    class FILETIME(ctypes.Structure):
        _fields_ = [
            ("dwLowDateTime", ctypes.c_uint32),
            ("dwHighDateTime", ctypes.c_uint32),
        ]

    class CREDENTIAL(ctypes.Structure):
        _fields_ = [
            ("Flags", ctypes.c_uint32),
            ("Type", ctypes.c_uint32),
            ("TargetName", ctypes.c_wchar_p),
            ("Comment", ctypes.c_wchar_p),
            ("LastWritten", FILETIME),
            ("CredentialBlobSize", ctypes.c_uint32),
            ("CredentialBlob", ctypes.POINTER(ctypes.c_byte)),
            ("Persist", ctypes.c_uint32),
            ("AttributeCount", ctypes.c_uint32),
            ("Attributes", ctypes.c_void_p),
            ("TargetAlias", ctypes.c_wchar_p),
            ("UserName", ctypes.c_wchar_p),
        ]

    def write(target: str, blob: bytes) -> None:
        buf = (ctypes.c_byte * len(blob)).from_buffer_copy(blob)
        cred = CREDENTIAL(
            Flags=0,
            Type=_CRED_TYPE_GENERIC,
            TargetName=target,
            Comment="Kabao vault",
            CredentialBlobSize=len(blob),
            CredentialBlob=ctypes.cast(buf, ctypes.POINTER(ctypes.c_byte)),
            Persist=_CRED_PERSIST_ENTERPRISE,
            AttributeCount=0,
            Attributes=None,
            TargetAlias=None,
            UserName=None,
        )
        if not advapi32.CredWriteW(ctypes.byref(cred), 0):
            code = ctypes.get_last_error()
            raise VaultAccessError(f"凭据管理器 {target!r} 写入失败（win32 错误码 {code}）")

    def read(target: str) -> bytes:
        pcred = ctypes.POINTER(CREDENTIAL)()
        if not advapi32.CredReadW(target, _CRED_TYPE_GENERIC, 0, ctypes.byref(pcred)):
            code = ctypes.get_last_error()
            if code == _ERR_NOT_FOUND:
                raise VaultCredentialMissing(f"凭据管理器没有 {target!r} 的记录")
            raise VaultAccessError(f"凭据管理器 {target!r} 读取失败（win32 错误码 {code}）")
        cred = pcred.contents
        size = cred.CredentialBlobSize
        blob = ctypes.string_at(cred.CredentialBlob, size) if size else b""
        advapi32.CredFree(pcred)  # 释放 win 侧内存后立即用
        return blob

    def delete(target: str) -> None:
        if not advapi32.CredDeleteW(target, _CRED_TYPE_GENERIC, 0):
            code = ctypes.get_last_error()
            if code != _ERR_NOT_FOUND:
                raise VaultAccessError(f"凭据管理器 {target!r} 删除失败（win32 错误码 {code}）")
        # 找不到 = 已删过，幂等返回

    return SimpleNamespace(write=write, read=read, delete=delete)


class WindowsCredmanBackend:
    """Windows 凭据管理器（DPAPI 保护）后端。target 名 = prefix + ":" + ref。

    旧品牌条目读穿迁移（A1-03 §8）：新 prefix 未命中时读一次旧 marina.vault，
    读到即回写新 prefix（旧条目保留作备份），对调用方透明。
    """

    name = "credman"

    def __init__(
        self,
        *,
        target_prefix: str = "kabao.vault",
        legacy_target_prefix: str = "marina.vault",
        api_factory: Callable[[], Any] | None = None,
    ):
        self._prefix = target_prefix
        self._legacy = legacy_target_prefix
        if api_factory is not None:
            self._api = api_factory()
        elif sys.platform.startswith("win"):
            self._api = _make_real_api()
        else:
            raise VaultAccessError(
                "WindowsCredmanBackend 需要注入 api_factory 或运行在 Windows 上"
            )

    def _target(self, ref: str) -> str:
        return f"{self._prefix}:{ref}"

    def put(self, ref: str, value: str) -> None:
        self._api.write(self._target(ref), value.encode("utf-8"))

    def get(self, ref: str) -> str:
        try:
            return self._api.read(self._target(ref)).decode("utf-8")
        except VaultCredentialMissing:
            if not self._legacy or self._legacy == self._prefix:
                raise
            legacy_target = f"{self._legacy}:{ref}"
            value = self._api.read(legacy_target).decode("utf-8")  # 未命中同样抛 Missing
            try:
                self.put(ref, value)  # 读穿迁移；失败不阻断读取，下次再试
            except VaultAccessError:
                pass
            return value

    def delete(self, ref: str) -> None:
        self._api.delete(self._target(ref))
