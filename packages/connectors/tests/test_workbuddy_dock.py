"""dock offline tests: pure health check + guidance (ADR-008 decision 4), zero network zero decryption zero process launch."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

from butler_connectors.workbuddy_cn import adapter
from butler_connectors.workbuddy_cn.localenv import InvalidOverride


def envelope_token() -> dict:  # same fake envelope as adapter tests (duplicated to avoid cross-test-file import)
    inner = {
        "suite": 1,
        "keyId": "0123456789abcdef",
        "nonce": base64.b64encode(b"n" * 12).decode(),
        "authTag": base64.b64encode(b"t" * 16).decode(),
        "ciphertext": base64.b64encode(b"c" * 8).decode(),
    }
    return {
        "$wbEncrypted": 1,
        "envelope": base64.b64encode(json.dumps(inner).encode()).decode(),
    }


@dataclass
class FakeRegister:
    calls: list[tuple[str, str, str | None]] = field(default_factory=list)

    def execute(self, platform: str, account_name: str, *, account_code: str | None = None, account_id: str | None = None, identity=None):
        self.calls.append((platform, account_name, account_code))
        return SimpleNamespace(id=f"{platform}:{account_code or 'main'}")


@dataclass
class FakeCtx:
    register: FakeRegister = field(default_factory=FakeRegister)
    vault: object = None  # fetched on demand, zero vault: dock never touches the vault (ADR-008 decision 3)


def write_auth(tmp_path, monkeypatch, token) -> Path:
    path = tmp_path / "wb.info"
    path.write_text(
        json.dumps({"auth": {"accessToken": token}, "account": {"uid": "u-1"}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("WORKBUDDY_AUTH_FILE", str(path))
    return path


def env_with(candidates):
    return SimpleNamespace(locate_runtime_candidates=lambda: candidates)


def test_all_pass_registers_account(tmp_path, monkeypatch):
    write_auth(tmp_path, monkeypatch, "plain-tok")
    ctx = FakeCtx()
    outcome = adapter.butler.dock(ctx, env=env_with(list))
    assert outcome.issues == []
    assert outcome.accounts == ["workbuddy_cn:main"]
    assert ctx.register.calls == [("workbuddy_cn", "WorkBuddy CN", None)]


def test_missing_file_issue_without_register(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKBUDDY_AUTH_FILE", str(tmp_path / "nope.info"))
    outcome = adapter.butler.dock(FakeCtx(), env=env_with(list))
    assert outcome.accounts == []
    assert "客户端登录" in outcome.issues[0]


def test_corrupt_json_issue(tmp_path, monkeypatch):
    path = tmp_path / "wb.info"
    path.write_text("not json", encoding="utf-8")
    monkeypatch.setenv("WORKBUDDY_AUTH_FILE", str(path))
    outcome = adapter.butler.dock(FakeCtx(), env=env_with(list))
    assert "不可读" in outcome.issues[0]


def test_empty_session_missing_fields_issue(tmp_path, monkeypatch):
    path = tmp_path / "wb.info"
    path.write_text(json.dumps({"auth": {}, "account": {}}), encoding="utf-8")
    monkeypatch.setenv("WORKBUDDY_AUTH_FILE", str(path))
    outcome = adapter.butler.dock(FakeCtx(), env=env_with(list))
    assert "登录" in outcome.issues[0]  # MISSING_SESSION human-readable copy


def test_plaintext_skips_runtime_check(tmp_path, monkeypatch):
    write_auth(tmp_path, monkeypatch, "plain-tok")

    def boom():
        raise AssertionError("plaintext credentials must not look up runtime")

    outcome = adapter.butler.dock(
        FakeCtx(), env=SimpleNamespace(locate_runtime_candidates=boom)
    )
    assert outcome.issues == []


def test_envelope_without_runtime_issue(tmp_path, monkeypatch):
    write_auth(tmp_path, monkeypatch, envelope_token())
    outcome = adapter.butler.dock(FakeCtx(), env=env_with([]))
    assert outcome.accounts == []
    assert "WORKBUDDY_EXE" in outcome.issues[0]


def test_envelope_without_runtime_mac_message(tmp_path, monkeypatch):
    """mac runtime 缺位：如实报 mac 解锁链待取证 + WORKBUDDY_EXE 逃生口（不误导重装）。"""
    import sys

    monkeypatch.setattr(sys, "platform", "darwin")
    write_auth(tmp_path, monkeypatch, envelope_token())
    outcome = adapter.butler.dock(FakeCtx(), env=env_with([]))
    assert outcome.accounts == []
    assert "mac 解锁链待真机取证" in outcome.issues[0]
    assert "安装 WorkBuddy 客户端" not in outcome.issues[0]  # 客户端可能已装：不误导
    assert "WORKBUDDY_EXE" in outcome.issues[0]


def test_invalid_override_issue(tmp_path, monkeypatch):
    write_auth(tmp_path, monkeypatch, envelope_token())

    def bad():
        raise InvalidOverride("WORKBUDDY_EXE 不是可用的可执行文件")

    outcome = adapter.butler.dock(
        FakeCtx(), env=SimpleNamespace(locate_runtime_candidates=bad)
    )
    assert "WORKBUDDY_EXE" in outcome.issues[0]


def test_dock_idempotent_on_registry_side(tmp_path, monkeypatch):
    write_auth(tmp_path, monkeypatch, "plain-tok")
    register = FakeRegister()
    ctx = FakeCtx(register=register)
    first = adapter.butler.dock(ctx, env=env_with(list))
    second = adapter.butler.dock(ctx, env=env_with(list))
    assert first.accounts == second.accounts == ["workbuddy_cn:main"]


# --- ADR-025 扩展：account_code = account.nickname 实际昵称 ---


def test_plaintext_nickname_registers_with_code(tmp_path, monkeypatch):
    path = tmp_path / "wb.info"
    path.write_text(
        json.dumps({"auth": {"accessToken": "plain-tok"}, "account": {"uid": "u-1", "nickname": " 逍遥酒鬼 "}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("WORKBUDDY_AUTH_FILE", str(path))
    ctx = FakeCtx()
    outcome = adapter.butler.dock(ctx, env=env_with(list))
    assert outcome.issues == []
    assert outcome.accounts == ["workbuddy_cn:逍遥酒鬼"]
    assert ctx.register.calls == [("workbuddy_cn", "WorkBuddy CN · 逍遥酒鬼", "逍遥酒鬼")]


def test_envelope_nickname_decrypts_to_code(tmp_path, monkeypatch):
    path = tmp_path / "wb.info"
    path.write_text(
        json.dumps({"auth": {"accessToken": envelope_token()}, "account": {"uid": "u-1", "nickname": envelope_token()}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("WORKBUDDY_AUTH_FILE", str(path))
    seen = {}

    def fake_decrypt_field(raw, *, candidates):
        seen["raw"] = raw
        seen["candidates"] = candidates
        return "Leisure520"

    monkeypatch.setattr(adapter, "decrypt_field", fake_decrypt_field)
    ctx = FakeCtx()
    outcome = adapter.butler.dock(ctx, env=env_with(["exe"]))
    assert outcome.issues == []
    assert outcome.accounts == ["workbuddy_cn:Leisure520"]
    assert ctx.register.calls == [("workbuddy_cn", "WorkBuddy CN · Leisure520", "Leisure520")]
    assert seen["candidates"] == ["exe"]


def test_envelope_nickname_decrypt_failure_falls_back_to_main(tmp_path, monkeypatch):
    """昵称解密失败不阻塞 dock：默认编址登记 + 如实记 note（红线 5，不静默）。"""
    from butler_connectors.workbuddy_cn.session import AuthError

    path = tmp_path / "wb.info"
    path.write_text(
        json.dumps({"auth": {"accessToken": envelope_token()}, "account": {"uid": "u-1", "nickname": envelope_token()}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("WORKBUDDY_AUTH_FILE", str(path))

    def boom(raw, *, candidates):
        raise AuthError("KEY_MISMATCH")

    monkeypatch.setattr(adapter, "decrypt_field", boom)
    ctx = FakeCtx()
    outcome = adapter.butler.dock(ctx, env=env_with(["exe"]))
    assert outcome.accounts == ["workbuddy_cn:main"]
    assert any("昵称" in issue for issue in outcome.issues)
    assert ctx.register.calls == [("workbuddy_cn", "WorkBuddy CN", None)]


def test_missing_nickname_registers_default(tmp_path, monkeypatch):
    write_auth(tmp_path, monkeypatch, "plain-tok")  # account 无 nickname 字段
    ctx = FakeCtx()
    outcome = adapter.butler.dock(ctx, env=env_with(list))
    assert outcome.issues == []
    assert outcome.accounts == ["workbuddy_cn:main"]
    assert ctx.register.calls == [("workbuddy_cn", "WorkBuddy CN", None)]
