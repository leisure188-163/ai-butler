"""Trae CN 桌面端 SS_AES 信封解锁（协议事实归 trae_cn/PROTOCOL.md，实现全新写）。

信封（A0-01 §2.1 只带走知识）：base64 字符串解码后 -
- 6 字节头 [116,99,5,16,0,0] + 内嵌随机 AES 主密钥 32 字节 + AES-128-CBC 密文
- 盐 = GLE ⊕ ZLE（两段 64 字节常量）
- 派生 = sha512(sha512(主密钥) ‖ 盐)：前 16 字节 key、次 16 字节 iv
- 明文前 64 字节 = sha512(body)（校验和），余下是登录态 JSON
- 认证信封 = AES-128-CBC + PKCS7 填充
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from typing import Any

HEADER = bytes([116, 99, 5, 16, 0, 0])
MASTER_KEY_LEN = 32
KEY_LEN = 16  # AES-128
_CHECKSUM_LEN = 64  # 明文头部 = sha512(body)

_GLE = bytes(
    [
        82, 9, 106, 213, 48, 54, 165, 56, 191, 64, 163, 158, 129, 243, 215, 251,
        124, 227, 57, 130, 155, 47, 255, 135, 52, 142, 67, 68, 196, 222, 233, 203,
        84, 123, 148, 50, 166, 194, 35, 61, 238, 76, 149, 11, 66, 250, 195, 78,
        8, 46, 161, 102, 40, 217, 36, 178, 118, 91, 162, 73, 109, 139, 209, 37,
    ]
)
_ZLE = bytes(
    [
        31, 221, 168, 51, 136, 7, 199, 49, 177, 18, 16, 89, 39, 128, 236, 95,
        96, 81, 127, 169, 25, 181, 74, 13, 45, 229, 122, 159, 147, 201, 156, 239,
        160, 224, 59, 77, 174, 42, 245, 176, 200, 235, 187, 60, 131, 83, 153, 97,
        23, 43, 4, 126, 186, 119, 214, 38, 225, 105, 20, 99, 85, 33, 12, 125,
    ]
)
SALT = bytes(a ^ b for a, b in zip(_GLE, _ZLE))


class EnvelopeInvalid(ValueError):
    """信封不属于 SS_AES 协议或内容被篡改——显式报错，绝不静默兜底。"""


def open_envelope(raw: bytes) -> dict[str, Any]:
    """解一个 SS_AES 信封，返回登录态 JSON（含 token）。"""
    if len(raw) <= len(HEADER) + MASTER_KEY_LEN + _CHECKSUM_LEN:
        raise EnvelopeInvalid(f"SS_AES 信封长度不足（{len(raw)}B）")
    if bytes(raw[:6]) != HEADER:
        raise EnvelopeInvalid(f"信封头不属于 SS_AES 方案（{list(raw[:6])}）")

    master = raw[6 : 6 + MASTER_KEY_LEN]
    ciphertext = bytes(raw[6 + MASTER_KEY_LEN :])
    digest = hashlib.sha512(hashlib.sha512(master).digest() + SALT).digest()
    key, iv = digest[:KEY_LEN], digest[KEY_LEN : 2 * KEY_LEN]
    plain = _decrypt_cbc(key, iv, ciphertext)

    body = plain[_CHECKSUM_LEN:]
    checksum = bytes(plain[:_CHECKSUM_LEN])
    if checksum != hashlib.sha512(body).digest():
        raise EnvelopeInvalid("SS_AES 明文校验和不匹配——登录态内容被篡改或协议已变")
    try:
        data = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EnvelopeInvalid(f"解锁后的登录态不是合法 JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise EnvelopeInvalid(f"登录态 JSON 应为对象，得到 {type(data).__name__}")
    return data


def decode_stored(value: str) -> bytes:
    """storage.json 里的值是 base64 字符串；严格校验可逆性（防双向漂移）。"""
    try:
        decoded = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise EnvelopeInvalid(f"登录态值不是合法 base64: {exc}") from exc
    if base64.b64encode(decoded).decode("ascii") != value:
        raise EnvelopeInvalid("登录态 base64 编码不可逆归一——信封已损坏")
    return decoded


def _decrypt_cbc(key: bytes, iv: bytes, ciphertext: bytes) -> bytes:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives.padding import PKCS7

    decryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    padded = decryptor.update(ciphertext) + decryptor.finalize()
    unpadder = PKCS7(KEY_LEN * 8).unpadder()
    try:
        plain = unpadder.update(padded) + unpadder.finalize()
    except ValueError as exc:
        raise EnvelopeInvalid(f"AES-CBC 填充不合法（协议已变?）: {exc}") from exc
    return plain
