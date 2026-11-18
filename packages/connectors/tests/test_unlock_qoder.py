"""dpapi_gcm_v10 / umid_cosy 解锁链（ADR-006 kind 化凭据，qoder_cn）。

DPAPI 是真机 API——测试注入替身只替 CryptUnprotectData 一步；
信封形状 / v10 前缀 / AES-256-GCM 链路用真 cryptography 走全。
"""

import base64
import json

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from butler_core.accounts.domain import Secret
from butler_connectors import unlock
from butler_connectors.unlock import (
    UnknownCredentialKind,
    load_dpapi_gcm_v10,
    load_umid_cosy,
    session_from_dpapi_gcm_v10,
)

TEST_KEY = bytes(range(32))  # AES-256 密钥替身（DPAPI 解出的"真"密钥）


def fake_dpapi(blob: bytes) -> bytes:
    """DPAPI 替身：解不出真密钥就爆（保持失败语义）。"""
    del blob
    return TEST_KEY


def seal_envelope(session: dict, *, magic: bytes = b"DPAPI", file_magic: bytes = b"v10") -> str:
    """按协议同形组信封：base64(JSON{dat: b64(v10+nonce+ct), key_b64: b64(DPAPI+wrapped)})。"""
    nonce = bytes(range(12))
    ct = AESGCM(TEST_KEY).encrypt(nonce, json.dumps(session).encode("utf-8"), None)
    dat = file_magic + nonce + ct
    payload = {
        "dat": base64.b64encode(dat).decode("ascii"),
        "key_b64": base64.b64encode(magic + b"wrapped-key-blob").decode("ascii"),
    }
    return base64.b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")


@pytest.fixture(autouse=True)
def patched_dpapi(monkeypatch):
    monkeypatch.setattr(unlock, "dpapi_unprotect", fake_dpapi)


def test_dpapi_gcm_v10_loader_fields():
    envelope = seal_envelope({"token": "T-1", "expiresAt": "2026-11-17T00:59:05.212Z"})
    assert load_dpapi_gcm_v10(Secret(envelope)) == {"token": "T-1"}


def test_session_roundtrip_keeps_full_payload():
    envelope = seal_envelope({"token": "T-1", "uid": "u", "expiresAt": "2026-12-01"})
    session = session_from_dpapi_gcm_v10(envelope)
    assert session["uid"] == "u"  # dock 取 expiresAt 元数据用全量会话


def test_dpapi_missing_magic_rejected():
    envelope = seal_envelope({"token": "T"}, magic=b"XXXX")
    with pytest.raises(ValueError, match="DPAPI"):
        session_from_dpapi_gcm_v10(envelope)


def test_dat_bad_file_magic_rejected():
    envelope = seal_envelope({"token": "T"}, file_magic=b"v99")
    with pytest.raises(ValueError, match="文件头"):
        session_from_dpapi_gcm_v10(envelope)


def test_tampered_ciphertext_rejected():
    envelope = seal_envelope({"token": "T"})
    raw = json.loads(base64.b64decode(envelope))
    dat = bytearray(base64.b64decode(raw["dat"]))
    dat[-1] ^= 0xFF  # 篡改密文末字节 → GCM tag 校验必败
    raw["dat"] = base64.b64encode(bytes(dat)).decode()
    tampered = base64.b64encode(json.dumps(raw).encode()).decode()
    with pytest.raises(ValueError, match="解密失败"):
        session_from_dpapi_gcm_v10(tampered)


def test_session_without_token_rejected():
    envelope = seal_envelope({"uid": "u"})
    with pytest.raises(ValueError, match="token"):
        session_from_dpapi_gcm_v10(envelope)


def test_umid_cosy_flattens_to_template_fields():
    payload = {
        "cosy_machine_token": "MT",
        "cosy_machine_code": "MC",
        "cosy_machine_type": "MTY",
        "cosy_machine_id": "36-char-machine-id",
        "cosy_machine_os": "x86_64_windows",
        "cosy_machine_hostname": "DESK",
        "cosy_version": "0.4.8",
    }
    secret = Secret(base64.b64encode(json.dumps(payload).encode()).decode())
    fields = load_umid_cosy(secret)
    assert fields["cosy_machine_token"] == "MT"
    assert fields["cosy_version"] == "0.4.8"  # 数字形态版本也归一成 str


def test_umid_cosy_empty_rejected():
    secret = Secret(base64.b64encode(b"{}").decode())
    with pytest.raises(ValueError, match="为空"):
        load_umid_cosy(secret)


def test_unknown_kind_still_rejected():
    with pytest.raises(UnknownCredentialKind):
        unlock.unlock("dpapi_gcm_v99", Secret("x"))


# --- mac 分支（2026-11-12 真机取证：Keychain safeStorage + PBKDF2 + AES-128-CBC）---

MAC_SECRET = b"t" * 24  # Keychain 口令替身（真机实测 24 字节）


def fake_keychain() -> bytes:
    return MAC_SECRET


def seal_mac_envelope(
    session: dict, *, secret: bytes = MAC_SECRET, file_magic: bytes = b"v10"
) -> str:
    """按 mac 协议同形组信封：base64(JSON{dat: b64(v10 + AES-128-CBC 密文)})，无 key_b64。"""
    import hashlib

    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    key = hashlib.pbkdf2_hmac(
        "sha1", secret, unlock._PBKDF2_SALT, unlock._PBKDF2_ITERS, unlock._CBC_KEY_LEN
    )
    plain = json.dumps(session).encode("utf-8")
    pad = unlock._CBC_KEY_LEN - len(plain) % unlock._CBC_KEY_LEN
    encryptor = Cipher(algorithms.AES(key), modes.CBC(unlock._CBC_IV)).encryptor()
    dat = file_magic + encryptor.update(plain + bytes([pad]) * pad) + encryptor.finalize()
    payload = {"dat": base64.b64encode(dat).decode("ascii")}
    return base64.b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")


def test_mac_envelope_roundtrip():
    envelope = seal_mac_envelope({"token": "T-M", "expiresAt": "2026-12-02T13:37:13Z"})
    session = session_from_dpapi_gcm_v10(envelope, key_provider=fake_keychain)
    assert session["token"] == "T-M"
    assert session["expiresAt"] == "2026-12-02T13:37:13Z"


def test_mac_loader_uses_keychain_key_source(monkeypatch):
    monkeypatch.setattr(unlock, "macos_safe_storage_password", fake_keychain)
    envelope = seal_mac_envelope({"token": "T-M"})
    assert load_dpapi_gcm_v10(Secret(envelope)) == {"token": "T-M"}


def test_mac_wrong_secret_rejected():
    envelope = seal_mac_envelope({"token": "T-M"}, secret=b"x" * 24)
    with pytest.raises(ValueError, match="解密失败"):
        session_from_dpapi_gcm_v10(envelope, key_provider=fake_keychain)


def test_mac_tampered_ciphertext_rejected():
    envelope = seal_mac_envelope({"token": "T-M"})
    raw = json.loads(base64.b64decode(envelope))
    dat = bytearray(base64.b64decode(raw["dat"]))
    dat[10] ^= 0xFF  # 篡改首密文块 → 解出乱码（CBC 无 tag，靠补位/JSON 验形兜住）
    raw["dat"] = base64.b64encode(bytes(dat)).decode()
    tampered = base64.b64encode(json.dumps(raw).encode()).decode()
    with pytest.raises(ValueError, match="解密失败"):
        session_from_dpapi_gcm_v10(tampered, key_provider=fake_keychain)


def test_mac_short_dat_rejected():
    payload = {"dat": base64.b64encode(b"v10abc").decode("ascii")}
    envelope = base64.b64encode(json.dumps(payload).encode()).decode()
    with pytest.raises(ValueError, match="过短"):
        session_from_dpapi_gcm_v10(envelope, key_provider=fake_keychain)


def test_keychain_failure_is_explicit(monkeypatch):
    """候选名全 miss 时显式爆（2026-11-18 mac Global 取证：候选序见 unlock._MACOS_KEYCHAIN_SERVICES）。"""
    import subprocess
    import types

    seen: list[str] = []

    def fake_run(cmd, **kwargs):
        seen.append(cmd[cmd.index("-s") + 1])
        return types.SimpleNamespace(returncode=44, stdout=b"", stderr=b"denied")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(RuntimeError, match="Keychain"):
        unlock.macos_safe_storage_password()
    assert "Qoder App Safe Storage" in seen  # 真机实测量产名（Global 客户端）
    assert "Qoder Platform Safe Storage" in seen  # 旧记录名保留为候选


def test_keychain_first_hit_wins(monkeypatch):
    """第一个命中的候选名即用——不再读后续候选（一次授权弹窗原则）。"""
    import subprocess
    import types

    reads: list[str] = []

    def fake_run(cmd, **kwargs):
        name = cmd[cmd.index("-s") + 1]
        reads.append(name)
        if name == "Qoder App Safe Storage":
            return types.SimpleNamespace(returncode=0, stdout=b"secret-24-bytes!!\n")
        return types.SimpleNamespace(returncode=44, stdout=b"", stderr=b"not found")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert unlock.macos_safe_storage_password() == b"secret-24-bytes!!"
    assert reads == ["Qoder App Safe Storage"]


def test_keychain_read_darwin_only(monkeypatch):
    import sys

    monkeypatch.setattr(sys, "platform", "win32")
    with pytest.raises(RuntimeError, match="macOS"):
        unlock.macos_safe_storage_password()
