"""连接器测试固件：测试方言预注册（ADR-004）+ 停停靠 fixture 工具。"""

import base64
import hashlib
import json
from datetime import UTC, datetime

import pytest


@pytest.fixture(scope="session", autouse=True)
def register_testco_dialect():
    from butler_core.shared.results import Status, register_dialect

    register_dialect(
        "testco",
        {"1001": Status.NO_AUTH, "9004": Status.FAILED, "9074": Status.PENDING},
    )


# --- Trae storage.json 协议 fixture（test_ss_aes.seal 的复用出口）---


def make_jwt(exp_epoch: int) -> str:
    header = base64.urlsafe_b64encode(b'{"alg":"RS256","typ":"JWT"}').rstrip(b"=").decode()
    payload = base64.urlsafe_b64encode(
        json.dumps({"sub": "u", "exp": exp_epoch}, separators=(",", ":")).encode()
    ).rstrip(b"=").decode()
    return f"{header}.{payload}.sig"


def make_login_state(exp_epoch: int, master: bytes = bytes(range(32))) -> dict:
    """构造协议同形的登录态：SS_AES 信封(内含 token) + storage.json 双键。"""
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives.padding import PKCS7

    from butler_connectors.ssaes import HEADER, SALT

    info = {"token": make_jwt(exp_epoch), "userId": "u-1"}
    body = json.dumps(info, separators=(",", ":")).encode()
    digest = hashlib.sha512(hashlib.sha512(master).digest() + SALT).digest()
    key, iv = digest[:16], digest[16:32]
    payload = hashlib.sha512(body).digest() + body  # 协议：明文前 64B = sha512(body)
    padding = PKCS7(128)
    padder = padding.padder()
    padded = padder.update(payload) + padder.finalize()
    encryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    ct = encryptor.update(padded) + encryptor.finalize()
    raw = HEADER + master + ct
    envelope = base64.b64encode(raw).decode("ascii")
    return {
        "iCubeAuthInfo://icube-dc:1234567890123456": {"other": 1},  # 设备号在键名
        "iCubeAuthInfo://icube.cloudide": envelope,
        "telemetry.devDeviceId": "uuid-goes-here",
        "iCubeLastVersion": "1.2.3",
    }


def wrap_storage_payload(info: dict, exp_epoch: int) -> dict:
    """storage.json 顶层形状（真设备号 + 信封）。"""
    del info
    return make_login_state(exp_epoch)


def frozen_epoch() -> int:
    return int(datetime(2026, 12, 25, tzinfo=UTC).timestamp())

