"""macOS Keychain 后端（A4-01 §1）：subprocess 调 `security` 命令，纯标准库。

- service 固定 kabao.vault；ref 作 account 字段——Keychain 侧无业务语义
- 旧品牌条目读穿迁移（A1-03 §8）：新 service 未命中时读一次旧 marina.vault，
  读到即回写新 service（旧条目保留作备份），对调用方透明
- 已知局限（如实记录）：`security` 的 -w 需要秘密经 argv 传递，进程列表
  可短暂看到明文；macOS 本机单用户场景可接受，桌面打包 M2 复查
- runner 可注入：测试用假 runner 验签名与错误处理，不碰真钥匙串
"""

from __future__ import annotations

import subprocess
from typing import Callable

from kabao_engine.vault.errors import VaultAccessError, VaultCredentialMissing

# security(1) 的"找不到"退出码：44（钥匙串条目不存在）
_NOT_FOUND = 44

Runner = Callable[..., "subprocess.CompletedProcess[str]"]


class KeychainBackend:
    """macOS 钥匙串后端。cmd 需要本机装有 security 命令（macOS 全系统自带）。"""

    name = "keychain"

    def __init__(
        self,
        *,
        service: str = "kabao.vault",
        legacy_service: str = "marina.vault",
        runner: Runner | None = None,
    ):
        self._service = service
        self._legacy = legacy_service
        self._run: Runner = runner if runner is not None else subprocess.run

    # --- SecretBackend ---

    def put(self, ref: str, value: str) -> None:
        """-U：存在即覆盖，不存在即新增——store / rotate 复用。"""
        proc = self._run(
            ["security", "add-generic-password", "-U", "-s", self._service,
             "-a", ref, "-w", value],
            capture_output=True, text=True,
        )
        self._ok(proc, f"写入 {ref}")

    def get(self, ref: str) -> str:
        try:
            return self._read(self._service, ref)
        except VaultCredentialMissing:
            if not self._legacy or self._legacy == self._service:
                raise
            value = self._read(self._legacy, ref)  # 未命中同样抛 Missing
            try:
                self.put(ref, value)  # 读穿迁移；失败不阻断读取，下次再试
            except VaultAccessError:
                pass
            return value

    def delete(self, ref: str) -> None:
        proc = self._run(
            ["security", "delete-generic-password", "-s", self._service, "-a", ref],
            capture_output=True, text=True,
        )
        if proc.returncode == _NOT_FOUND:
            return  # 删除语义幂等：没有就算删过
        self._ok(proc, f"删除 {ref}")

    # --- 内部 ---

    def _read(self, service: str, ref: str) -> str:
        proc = self._run(
            ["security", "find-generic-password", "-s", service, "-a", ref, "-w"],
            capture_output=True, text=True,
        )
        if proc.returncode == _NOT_FOUND:
            raise VaultCredentialMissing(f"钥匙串没有 {ref!r} 的记录")
        self._ok(proc, f"读取 {ref}")
        return proc.stdout.rstrip("\n")

    @staticmethod
    def _ok(proc: "subprocess.CompletedProcess[str]", what: str) -> None:
        if proc.returncode != 0:
            raise VaultAccessError(
                f"Keychain {what} 失败（退出码 {proc.returncode}）: {proc.stderr.strip()}"
            )
