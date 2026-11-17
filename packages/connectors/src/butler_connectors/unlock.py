"""vault kind → 解锁字段的适配器（最小授权：只解申报 kinds）。

约定：每个 vault kind 一个 Loader，输入 Secret，输出"字段字典"。
声明式引擎把全部 kinds 的字段合并后填 header 模板；缺字段 = 凭据/协议
事故，显式报错（红线 5）。凭据明文绝不进字段字典之外的地方。
"""

from __future__ import annotations

from typing import Mapping

from butler_core.accounts.domain import Secret


class UnknownCredentialKind(KeyError):
    """manifest 申报了没有 Loader 的凭据 kind——拒绝接入（红线 5）。"""


def load_ss_aes(secret: Secret) -> dict[str, str]:
    from butler_connectors.ssaes import decode_stored, open_envelope

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


# --- dpapi_gcm_v10（qoder_cn，ADR-006）：登录态信封解锁（双平台单 kind）---
# Windows：DPAPI 包裹密钥（Local State os_crypt）+ AES-256-GCM；
# macOS（2026-11-12 真机取证）：钥匙在 Keychain（safeStorage 惯例）+ AES-128-CBC。

#: 会话信封与密钥块的协议常量（qoder PROTOCOL §1，2026-11-11 真机取证）
_DPAPI_MAGIC = b"DPAPI"  # Local State os_crypt.encrypted_key 解 base64 后的前缀
_V10_MAGIC = b"v10"  # auth.v1.dat 文件头 3 字节
_GCM_NONCE_LEN = 12  # raw[3:15] = nonce；raw[15:] = 密文+tag
_GCM_MIN_LEN = 3 + 12 + 16  # 前缀 + nonce + 最短 tag
#: mac 侧常量：auth.v1.dat 同为 ``v10`` 头，但内容 = AES-128-CBC（固定 16 空格 IV、
#: PKCS7 补位），钥匙 = Keychain 口令经 PBKDF2-HMAC-SHA1 派生（Chromium safeStorage
#: 惯例 salt/迭代数，与本机 Chrome mac 取证同链）。密文块长恰为 16 的倍数已实证。
_CBC_IV = b" " * 16
_PBKDF2_SALT = b"saltysalt"
_PBKDF2_ITERS = 1003
_CBC_KEY_LEN = 16
_MACOS_KEYCHAIN_SERVICE = "Qoder Platform Safe Storage"  # 实测名（dump-keychain 元数据取证）


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


def macos_safe_storage_password(service: str = _MACOS_KEYCHAIN_SERVICE) -> bytes:
    """mac Keychain safeStorage 口令（security CLI 读；口令只进内存，不落盘不进日志）。"""
    import subprocess
    import sys

    if sys.platform != "darwin":
        raise RuntimeError("safeStorage Keychain 读取仅 macOS 可用")
    proc = subprocess.run(
        ["security", "find-generic-password", "-w", "-s", service],
        capture_output=True,
        timeout=30,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"Keychain 未取到 {service!r}——确认 Qoder 客户端在本机登录过一次、"
            "未拒绝 Keychain 访问"
        )
    return proc.stdout.rstrip(b"\n")


def session_from_dpapi_gcm_v10(
    envelope_b64: str, *, dpapi=None, key_provider=None
) -> dict:
    """解 dpapi_gcm_v10 自包含信封 → 会话 JSON dict（dock 验形与 loader 共用单源）。

    信封（dock 组装）：``base64(JSON{dat, key_b64?})``，dat = base64(auth.v1.dat 原始字节)。
    Windows 信封自包含：key_b64 = Local State ``os_crypt.encrypted_key`` 原文 →
    b64decode → 剥 DPAPI 前缀 → CryptUnprotectData → AES 密钥；dat → ``v10``+nonce+密文
    → AES-256-GCM。
    mac 信封只带 dat（2026-11-12 取证：mac 的 Local State 无 os_crypt）——钥匙解锁时
    从 Keychain 现取（ADR-008 决策 3 同款：现用现取，密钥绝不入 vault），dat → ``v10``
    +CBC 密文 → AES-128-CBC → PKCS7。
    dpapi / key_provider 参数可注入（测试 / 非 Windows 离线验证解链逻辑）。
    """
    import base64
    import json

    try:
        envelope = json.loads(base64.b64decode(envelope_b64))
        raw = base64.b64decode(envelope["dat"])
    except (ValueError, KeyError, TypeError) as exc:
        raise ValueError(f"dpapi_gcm_v10 信封形状不符: {exc}") from exc
    if not raw.startswith(_V10_MAGIC):
        raise ValueError(f"auth.v1.dat 文件头未知: {raw[:3]!r}")
    key_b64 = envelope.get("key_b64")
    if isinstance(key_b64, str) and key_b64:
        return _session_from_win_gcm(raw, key_b64, dpapi=dpapi)
    return _session_from_mac_cbc(raw, key_provider)


def _require_session(session: object) -> dict:
    if not isinstance(session, dict) or not session.get("token"):
        raise ValueError("解密产物缺 token 字段（协议形状已变?）")
    return session  # type: ignore[no-any-return]


def _session_from_win_gcm(raw: bytes, key_b64: str, *, dpapi) -> dict:
    import base64
    import json

    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    key_blob = base64.b64decode(key_b64)
    if not key_blob.startswith(_DPAPI_MAGIC):
        raise ValueError("密钥块缺 DPAPI 前缀（Local State 形状已变?）")
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
    return _require_session(session)


def _session_from_mac_cbc(raw: bytes, key_provider) -> dict:
    import hashlib
    import json

    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    if len(raw) < 3 + _CBC_KEY_LEN:  # 最短 = 一个完整密文块
        raise ValueError("auth.v1.dat 过短——可能正被客户端改写，稍后重扫")
    secret = (key_provider or macos_safe_storage_password)()
    key = hashlib.pbkdf2_hmac("sha1", secret, _PBKDF2_SALT, _PBKDF2_ITERS, _CBC_KEY_LEN)
    decryptor = Cipher(algorithms.AES(key), modes.CBC(_CBC_IV)).decryptor()
    try:
        padded = decryptor.update(raw[3:]) + decryptor.finalize()
    except ValueError as exc:  # 密文块长非 16 倍数等
        raise ValueError(f"会话解密失败（密钥或密文不符）: {exc}") from exc
    pad = padded[-1]
    if not 1 <= pad <= _CBC_KEY_LEN or padded[-pad:] != bytes([pad]) * pad:
        raise ValueError("会话解密失败（PKCS7 补位不符——密钥或密文不符）")
    try:
        session = json.loads(padded[:-pad].decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ValueError(f"会话解密失败（密钥或密文不符）: {exc}") from exc
    return _require_session(session)


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


# --- browser_cookie（A2-03 §1，R3 网页捕获）：Chromium cookie 解链 + 信封 loader ---


class CookieShapeError(ValueError):
    """cookie 密文形状显式不可解（文案自足，直接进 DockOutcome.issues）。

    典型：v20（Chrome 127+ Windows 应用绑定加密，2026-11-13 真机取证全量
    形状）——与「形状已变请重扫」不同，这不是临时态，重扫无用。
    """


def chromium_cookie_key(secret: bytes) -> bytes:
    """Chrome mac cookie 钥匙派生：safeStorage 口令 → PBKDF2-HMAC-SHA1 → 16B 密钥。

    与 qoder safeStorage 同链（saltysalt/1003 轮，A1-04 §4.1 本机取证 528 条零失败）。
    """
    import hashlib

    return hashlib.pbkdf2_hmac("sha1", secret, _PBKDF2_SALT, _PBKDF2_ITERS, _CBC_KEY_LEN)


def decrypt_chromium_cookie(blob: bytes, key: bytes, *, gcm: bool) -> bytes:
    """v10 cookie 密文 → 明文。平台显式分派：mac=CBC（密钥 16B）、win=GCM（32B）。

    mac 链双形状自识别（经典 / 16B 段+IV 前缀，见函数体取证注）；win 链 =
    nonce(12) + AES-256-GCM（Chromium v80+ 标准形状，2026-11-13 Windows 真机
    验收：DPAPI 钥匙腿实解通过；cookie 腿真机全量 v20，见 CookieShapeError）。
    v20 = Chrome 127+ 应用绑定加密（Platform-Bound）：解密须冒充 Chrome 进程调
    IElevator COM，属对抗绕过——本通道不做（A1-04 §7 遇 challenge 如实落榜），
    显式形状错误指明原因，不误导「重扫」。
    密文非 v10/v20 头显式爆。
    """
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    if not blob.startswith(_V10_MAGIC):
        if blob.startswith(b"v20"):
            raise CookieShapeError(
                "cookie 密文为 v20（Chrome 127+ 应用绑定加密）——解密需冒充 Chrome 进程，"
                "属对抗绕过，本通道不做（A2-03 §7 挂账）"
            )
        raise ValueError(f"cookie 密文头未知: {blob[:3]!r}")
    body = blob[3:]
    if gcm:
        from cryptography.exceptions import InvalidTag
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        if len(key) != 32:
            raise ValueError(f"Windows cookie 钥匙应为 32 字节，得 {len(key)}")
        if len(body) < _GCM_NONCE_LEN + 16:
            raise ValueError("cookie 密文过短（nonce+tag 放不下）")
        try:
            return AESGCM(key).decrypt(body[:_GCM_NONCE_LEN], body[_GCM_NONCE_LEN:], None)
        except InvalidTag as exc:
            raise ValueError(f"cookie GCM 解密失败（钥匙或密文不符）: {exc}") from exc
    if len(key) != _CBC_KEY_LEN:
        raise ValueError(f"mac cookie 钥匙应为 16 字节，得 {len(key)}")
    # mac 形状定论（A1-04 §4.1-8，2026-11-14 真机闭环 528/528）：
    # 体 = E(IV=16空格, sha256(host_key)[:32] ‖ PKCS7(value))——单条 CBC 链，
    # 头 32B = 域绑定完整性标签。因此：
    # - 经典切法（IV=空格、体全解）必败：头 32B 是二进制哈希，UTF-8 过不了
    # - 「前缀」切法（IV=体[16:32]、密文=体[32:]）= 跳过头的载荷链——
    #   输出即 cookie 真值（CBC 链式延续的数学必然，非独立形状）
    # - 完整性可验：体[:32] 解密 == sha256(host_key)，browser.py 捕获层落地校验
    fallback: bytes | None = None
    for iv, ct in ((b" " * _CBC_KEY_LEN, body), (body[16 : 2 * _CBC_KEY_LEN], body[2 * _CBC_KEY_LEN :])):
        if not ct or len(ct) % _CBC_KEY_LEN != 0:
            continue
        decryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
        try:
            padded = decryptor.update(ct) + decryptor.finalize()
        except ValueError:
            continue
        pad = padded[-1]
        if not 1 <= pad <= _CBC_KEY_LEN or padded[-pad:] != bytes([pad]) * pad:
            continue
        plain = padded[:-pad]
        try:
            plain.decode("utf-8")
            return plain
        except UnicodeDecodeError:
            fallback = plain
    if fallback is not None:
        return fallback
    raise ValueError("cookie 解密失败（经典/前缀两种形状均不符——钥匙或形状已变）")


def verify_mac_cookie_header(blob: bytes, key: bytes, host_key: str) -> bool:
    """mac v10 cookie 域绑定头校验（A1-04 §4.1-8）：体[:32] 解密 == sha256(host_key)。

    单条 CBC 链（IV=16 空格）的头 32B = sha256(host_key)——不符 = 钥匙错位或
    库形状已变，capture 层据此显式落榜。形状短于两块/非 v10 = False（调用方
    决定语义），真机全量 528/528 通过。
    """
    import hashlib

    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    if not blob.startswith(_V10_MAGIC) or len(blob) < 3 + 2 * _CBC_KEY_LEN:
        return False
    dec = Cipher(algorithms.AES(key), modes.CBC(b" " * _CBC_KEY_LEN)).decryptor()
    header = (dec.update(blob[3 : 3 + 2 * _CBC_KEY_LEN]) + dec.finalize())
    return header == hashlib.sha256(host_key.encode("utf-8")).digest()


def load_browser_cookie(secret: Secret) -> dict[str, str]:
    """网页会话信封 → Cookie 头字段（fill_auth_headers 按 kind 装配，A2-03 §1）。"""
    import json

    try:
        envelope = json.loads(secret.expose())
    except ValueError as exc:
        raise ValueError(f"browser_cookie 信封形状不符: {exc}") from exc
    cookies = envelope.get("cookies") if isinstance(envelope, dict) else None
    if not isinstance(cookies, list) or not cookies:
        raise ValueError("browser_cookie 信封缺 cookies（捕获事故?）")
    pairs: list[str] = []
    for item in cookies:
        if not isinstance(item, dict):
            raise ValueError("browser_cookie cookies 项形状非法（应为 {name, value}）")
        name, value = item.get("name"), item.get("value")
        if not isinstance(name, str) or not name or not isinstance(value, str):
            raise ValueError(f"browser_cookie cookie 项 {name!r} 形状非法（name/value 必填）")
        pairs.append(f"{name}={value}")
    return {"cookie": "; ".join(pairs)}


def unlock(kind: str, secret: Secret) -> dict[str, str]:
    """kind 分发。未知 kind 显式爆——不静默当原样读（防止误把密文当明文用）。"""
    if kind == "ss_aes":
        return load_ss_aes(secret)
    if kind == "dpapi_gcm_v10":
        return load_dpapi_gcm_v10(secret)
    if kind == "umid_cosy":
        return load_umid_cosy(secret)
    if kind == "browser_cookie":
        return load_browser_cookie(secret)
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
