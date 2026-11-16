"""网关 key 文件权限验收（ADR-012 裁决 4 / 2026-11-16 修正）。

钉死的事实：**NTFS 上 0o600 是假安全**——os.chmod 只切只读位，实测 mode 仍
0o666，同机其他账户可读。所以：
- POSIX 断言真 0600；
- Windows 断言走 icacls 且"失败必告警、不假装成功、不阻断启动"（失败 = False）。
"""

from __future__ import annotations

import logging
import os
import stat
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from butler_gateway import auth

_POSIX = sys.platform != "win32"


# ── POSIX ──

@pytest.mark.skipif(not _POSIX, reason="POSIX 权限位语义（Windows 由 icacls 用例覆盖）")
def test_posix_hardened_to_0600(tmp_path: Path) -> None:
    key_file = tmp_path / "gateway-auth-key"
    key_file.write_text("k", encoding="utf-8")
    os.chmod(key_file, 0o644)
    assert auth.harden_permissions(key_file) is True
    assert stat.S_IMODE(key_file.stat().st_mode) == 0o600


# ── Windows / icacls（用假 run 注入，CI 与 macOS 上照跑）──

def _fake_run(returncode: int, *, stdout: str = "", stderr: str = "", raises=None):
    calls: list[list[str]] = []

    def run(cmd, **kw):
        calls.append(list(cmd))
        if raises is not None:
            raise raises
        return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)

    return run, calls


def test_windows_uses_icacls(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(auth.sys, "platform", "win32")
    monkeypatch.setenv("USERNAME", "tester")
    run, calls = _fake_run(0, stdout="已处理 1 个文件")
    key_file = tmp_path / "gateway-auth-key"
    key_file.write_text("k", encoding="utf-8")

    assert auth.harden_permissions(key_file, run=run) is True
    assert calls[0][0] == "icacls"
    assert str(key_file) in calls[0]
    assert "/inheritance:r" in calls[0]  # 先撤销继承，否则 Users 组仍在
    assert "tester:F" in calls[0]


def test_windows_icacls_failure_warns_not_raises(tmp_path: Path, monkeypatch, caplog) -> None:
    monkeypatch.setattr(auth.sys, "platform", "win32")
    monkeypatch.setenv("USERNAME", "tester")
    run, _ = _fake_run(5, stderr="拒绝访问")
    with caplog.at_level(logging.WARNING):
        ok = auth.harden_permissions(tmp_path / "k", run=run)
    assert ok is False  # 不假装成功
    assert "未收紧" in caplog.text


def test_windows_icacls_missing_warns_not_raises(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(auth.sys, "platform", "win32")
    monkeypatch.setenv("USERNAME", "tester")
    run, _ = _fake_run(0, raises=FileNotFoundError("icacls 不存在"))
    assert auth.harden_permissions(tmp_path / "k", run=run) is False


def test_windows_unknown_user_skips_with_warning(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(auth.sys, "platform", "win32")
    monkeypatch.delenv("USERNAME", raising=False)
    monkeypatch.setattr(auth.getpass, "getuser", lambda: "")  # 账户名不可得
    run, calls = _fake_run(0)
    assert auth.harden_permissions(tmp_path / "k", run=run) is False
    assert calls == []  # 不拿空用户名去乱授权


# ── 收紧失败不影响可用性 ──

def test_load_or_create_survives_hardening_failure(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(auth, "harden_permissions", lambda *a, **k: False)
    key = auth.load_or_create(tmp_path / "gateway-auth-key")
    assert len(key) >= 40
    assert auth.load_or_create(tmp_path / "gateway-auth-key") == key
