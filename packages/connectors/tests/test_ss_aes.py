"""SS_AES 信封解锁（trae_cn/PROTOCOL.md §1.1 的实现基线）。

测试加密器（fixture 端）按协议同形状封口：测试只依赖"协议事实"，
不依赖生产代码——round-trip 通过即证明实现与常量自洽；篡改路径全部显式爆。
"""

import base64
import hashlib
import json

import pytest
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.padding import PKCS7

from butler_connectors.ssaes import (
    HEADER,
    MASTER_KEY_LEN,
    EnvelopeInvalid,
    decode_stored,
    open_envelope,
)


def derived_pair(master: bytes) -> tuple[bytes, bytes]:
    """协议派生单源复刻（测试封口用）：sha512(sha512(master) ‖ salt) → key,iv。"""
    import hashlib

    from butler_connectors.ssaes import SALT

    digest = hashlib.sha512(hashlib.sha512(master).digest() + SALT).digest()
    return digest[:16], digest[16:32]


def seal(body: bytes, master: bytes) -> bytes:
    """测试端封口（协议同形）：头 + 主密钥 + AES-128-CBC(PKCS7)。

    iv 不是自由参数——信封里没有 iv，甲乙双方都从 master 派生（协议事实）。
    """
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives.padding import PKCS7

    key, iv = derived_pair(master)
    padding = PKCS7(128).padder()
    padded = padding.update(body) + padding.finalize()
    encryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    ct = encryptor.update(padded) + encryptor.finalize()
    return HEADER + master + ct


def envelope_for(info: dict, master: bytes = bytes(range(32))) -> str:
    body = json.dumps(info, separators=(",", ":")).encode()
    raw = seal(hashlib.sha512(body).digest() + body, master)
    return base64.b64encode(raw).decode("ascii")


LOGIN_STATE = {
    "token": "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJ1IiwiZXhwIjoxNzYzMjU0NDAwfQ.sig",
    "uid": "u-1",
}


def test_round_trip():
    data = open_envelope(decode_stored(envelope_for(LOGIN_STATE)))
    assert data["token"] == LOGIN_STATE["token"]


def test_wrong_header_rejected():
    raw = bytearray(decode_stored(envelope_for(LOGIN_STATE)))
    raw[0] = 0
    with pytest.raises(EnvelopeInvalid):
        open_envelope(bytes(raw))


def test_tampered_body_rejected_checksum():
    raw = bytearray(decode_stored(envelope_for(LOGIN_STATE)))
    raw[-1] ^= 0xFF  # 改最后一字节（PKCS7 填充区）
    with pytest.raises(EnvelopeInvalid):  # 填充或校验和必然失配
        open_envelope(bytes(raw))


def test_non_base64_value_rejected():
    with pytest.raises(EnvelopeInvalid):
        decode_stored("not*b64!")


def test_short_envelope_rejected():
    with pytest.raises(EnvelopeInvalid):
        open_envelope(HEADER + bytes(range(30)))
