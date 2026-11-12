"""vault kind → 解锁字段的适配器（最小授权：只解申报 kinds）。

约定：每个 vault kind 一个 Loader，输入 Secret，输出"字段字典"。
声明式引擎把全部 kinds 的字段合并后填 header 模板；缺字段 = 凭据/协议
事故，显式报错（红线 5）。凭据明文绝不进字段字典之外的地方。
"""

from __future__ import annotations

from typing import Mapping

from kabao_core.domain.vault import Secret


class UnknownCredentialKind(KeyError):
    """manifest 申报了没有 Loader 的凭据 kind——拒绝接入（红线 5）。"""


def load_ss_aes(secret: Secret) -> dict[str, str]:
    from kabao_connectors.ssaes import decode_stored, open_envelope

    info = open_envelope(decode_stored(secret.expose()))
    token = info.get("token")
    if not isinstance(token, str) or not token:
        # 协议形状变化：信封里没有 token——不能静默发无鉴权请求（红线 5）
        raise ValueError("SS_AES 登录态 JSON 缺少 token 字段（协议形状已变?）")
    fields = {"token": token}
    version = info.get("version")
    if isinstance(version, str) and version:
        fields["app_version"] = version
    return fields


def load_raw(kind: str, secret: Secret) -> dict[str, str]:
    """原样读过：设备身份等"非加密凭据"（dock 时明文入库，vault 加密存放）。"""
    return {kind: secret.expose()}


# --- dpapi_gcm_v10（qoder_cn，ADR-004）：DPAPI 包裹密钥 + AES-256-GCM ---

#: 会话信封与密钥块的协议常量（qoder PROTOCOL §1，2026-11-11 真机取证）
_DPAPI_MAGIC = b"DPAPI"  # Local State os_crypt.encrypted_key 解 base64 后的前缀
_V10_MAGIC = b"v10"  # auth.v1.dat 文件头 3 字节
_GCM_NONCE_LEN = 12  # raw[3:15] = nonce；raw[15:] = 密文+tag
_GCM_MIN_LEN = 3 + 12 + 16  # 前缀 + nonce + 最短 tag


def dpapi_unprotect(blob: bytes) -> bytes:
    """Windows DPAPI CryptUnprotectData（当前用户作用域）；非 Windows 显式爆。"""
    import ctypes
    import sys

    if sys.platform != "win32":
        raise RuntimeError("DPAPI 仅 Windows 可用（mac 解锁分支待真机取证后另落）")

    class _DataBlob(ctypes.Structure):
        _fields_ = [
            ("cb", ctypes.c_ulong),
            ("pb", ctypes.POINTER(ctypes.c_char)),
        ]

    buf = ctypes.create_string_buffer(blob, len(blob))
    data_in = _DataBlob(len(blob), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    data_out = _DataBlob()
    ok = ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(data_in), None, None, None, None, 0, ctypes.byref(data_out)
    )
    if not ok:
        raise RuntimeError(
            f"CryptUnprotectData 失败（错误码 {ctypes.GetLastError()}）——"
            "密钥块非本机当前用户加密（换机/换用户停靠无效）"
        )
    out = ctypes.string_at(data_out.pb, data_out.cb)
    ctypes.windll.kernel32.LocalFree(data_out.pb)
    return out


def session_from_dpapi_gcm_v10(envelope_b64: str, *, dpapi=None) -> dict:
    """解 dpapi_gcm_v10 自包含信封 → 会话 JSON dict（dock 验形与 loader 共用单源）。

    信封（dock 组装，自包含才有 vault 最小授权——运行时解锁不依赖本机文件布局）：
    ``base64(JSON{dat, key_b64})``，dat = base64(auth.v1.dat 原始字节)，
    key_b64 = Local State ``os_crypt.encrypted_key`` 原文。
    解链：key_b64 → b64decode → 剥 DPAPI 前缀 → CryptUnprotectData → AES 密钥；
    dat → b64decode → ``v10``+nonce+密文 → AES-256-GCM → JSON。
    dpapi 参数可注入（测试 / 非 Windows 离线验证解链逻辑）。
    """
    import base64
    import json

    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    try:
        envelope = json.loads(base64.b64decode(envelope_b64))
        key_blob = base64.b64decode(envelope["key_b64"])
        raw = base64.b64decode(envelope["dat"])
    except (ValueError, KeyError, TypeError) as exc:
        raise ValueError(f"dpapi_gcm_v10 信封形状不符: {exc}") from exc
    if not key_blob.startswith(_DPAPI_MAGIC):
        raise ValueError("密钥块缺 DPAPI 前缀（Local State 形状已变?）")
    if not raw.startswith(_V10_MAGIC):
        raise ValueError(f"auth.v1.dat 文件头未知: {raw[:3]!r}")
    if len(raw) < _GCM_MIN_LEN:
        raise ValueError("auth.v1.dat 过短——可能正被客户端改写，稍后重扫")
    decrypt = dpapi if dpapi is not None else dpapi_unprotect
    key = decrypt(key_blob[len(_DPAPI_MAGIC) :])
    try:
        plain = AESGCM(key).decrypt(
            raw[3 : 3 + _GCM_NONCE_LEN], raw[3 + _GCM_NONCE_LEN :], None
        )
        session = json.loads(plain.decode("utf-8"))
    except (InvalidTag, UnicodeDecodeError, ValueError) as exc:
        raise ValueError(f"会话解密失败（密钥或密文不符）: {exc}") from exc
    if not isinstance(session, dict) or not session.get("token"):
        raise ValueError("解密产物缺 token 字段（协议形状已变?）")
    return session


def load_dpapi_gcm_v10(secret: Secret) -> dict[str, str]:
    """Qoder 登录态：信封解出会话，字段只出 token（有效期由 dock 存 vault 元数据）。"""
    session = session_from_dpapi_gcm_v10(secret.expose())
    return {"token": str(session["token"])}


def load_umid_cosy(secret: Secret) -> dict[str, str]:
    """Cosy 机器身份头组（dock 时 runtime-info 采集）：base64(JSON) 平铺成模板字段。

    字段名即 dynamic_headers 模板引用名（cosy_machine_* / cosy_version）；
    采了什么平铺什么，缺头在 header 拼装时显式爆（TemplateFieldMissing）。
    """
    import base64
    import json

    try:
        payload = json.loads(base64.b64decode(secret.expose()))
    except (ValueError, TypeError) as exc:
        raise ValueError(f"umid_cosy 凭据形状不符: {exc}") from exc
    if not isinstance(payload, dict) or not payload:
        raise ValueError("umid_cosy 凭据内容为空（dock 采集事故?）")
    fields: dict[str, str] = {}
    for key, value in payload.items():
        if not isinstance(key, str) or not key or not isinstance(value, (str, int, float, bool)):
            raise ValueError(f"umid_cosy 字段 {key!r} 形状非法（应为标量）")
        fields[key] = str(value)
    return fields


def unlock(kind: str, secret: Secret) -> dict[str, str]:
    """kind 分发。未知 kind 显式爆——不静默当原样读（防止误把密文当明文用）。"""
    if kind == "ss_aes":
        return load_ss_aes(secret)
    if kind == "dpapi_gcm_v10":
        return load_dpapi_gcm_v10(secret)
    if kind == "umid_cosy":
        return load_umid_cosy(secret)
    _RAW_KINDS = frozenset({"device_dn", "app_version"})
    if kind in _RAW_KINDS:
        return load_raw(kind, secret)
    raise UnknownCredentialKind(kind)


def unlock_all(
    kinds: tuple[str, ...], secrets: Mapping[str, Secret]
) -> dict[str, str]:
    """按申报 kinds 解锁并合并字段。缺 kind = 调用方在 load 层已显式处理。"""
    merged: dict[str, str] = {}
    for kind in kinds:
        merged.update(unlock(kind, secrets[kind]))
    return merged
