"""workbuddy session: validation, auth headers, plaintext/encrypted credential resolution (ADR-008 decisions 2/3).

The credential file is automatically written by the desktop client after login; the old accessToken is plaintext,
the new version is a ``$wbEncrypted`` envelope — the latter is decrypted by the client's bundled runtime in a hidden
subprocess (helper.js, imported verbatim, no modifications), returning the access token only through an in-memory
pipe; no refresh token handling (login and renewal remain the client's responsibility).
token never enters exception text: AuthError only carries the fixed AUTH_REASONS human-readable copy.
(The old repo's SENSITIVE redaction registry is not ported: the Butler side has no emit layer, token never enters
logs/exceptions/evidence — the adapter evidence is all fixed templates + server fields, invariant pinned by tests.)
"""

from __future__ import annotations

import base64
import json
import re
import urllib.parse
from collections.abc import Callable
from pathlib import Path
from typing import Any

from butler_connectors.native_helper import (
    DEFAULT_INPUT_LIMIT,
    NativeHelperError,
    run_json_stdin_helper,
)

#: Timeout and pipe caps for interacting with the credential helper subprocess (same constants as the old repo).
AUTH_HELPER_TIMEOUT = 10.0
TOKEN_LIMIT = 32768
MAX_ENVELOPE_B64 = DEFAULT_INPUT_LIMIT - 1024

DEFAULT_ENDPOINT = "https://copilot.tencent.com"

AUTH_REASONS = {
    "INVALID_FORMAT": "登录凭据格式无效，请检查凭据来源和客户端版本",
    "MISSING_SESSION": "本地缺少登录会话或必要字段，请先登录客户端",
    "UNSUPPORTED_ENVELOPE": "尚不支持此加密凭据格式，请更新脚本；重新登录不会改变加密格式",
    "RUNTIME_NOT_FOUND": "未找到 WorkBuddy 客户端，请用 WORKBUDDY_EXE 指定其可执行文件",
    "INVALID_RUNTIME_PATH": "WORKBUDDY_EXE 不是可用的可执行文件，请核对路径",
    "RUNTIME_UNAVAILABLE": "客户端运行时不支持所需的原生存储接口，请检查客户端和脚本版本",
    "KEY_MISMATCH": "凭据与所选客户端的密钥不匹配，请用 WORKBUDDY_EXE 指定对应客户端",
    "DECRYPT_FAILED": "加密凭据认证失败，请检查客户端版本及凭据是否完整",
    "HELPER_TIMEOUT": "凭据处理超时，已停止子进程，请稍后重试",
    "HELPER_PROTOCOL": "客户端凭据助手返回无效结果，请检查客户端和脚本版本",
}

#: Only these non-sensitive fixed reasons may pass through; token never enters exception text.
_ALLOWED_HELPER_REASONS = frozenset(
    {
        "INVALID_FORMAT",
        "UNSUPPORTED_ENVELOPE",
        "RUNTIME_UNAVAILABLE",
        "KEY_MISMATCH",
        "DECRYPT_FAILED",
        "HELPER_TIMEOUT",
        "HELPER_PROTOCOL",
    }
)


class AuthError(RuntimeError):
    """Credential-layer failure; only fixed, non-sensitive messages cross the credential boundary."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(
            AUTH_REASONS.get(reason, "本地未找到有效登录会话，请先登录客户端")
        )


def valid_token(token: object) -> bool:
    return (
        isinstance(token, str)
        and 0 < len(token) <= TOKEN_LIMIT
        and re.fullmatch(r"[A-Za-z0-9._~+/-]+=*", token) is not None
    )


def validate_session(session: Any) -> None:
    """Dual structure and format validation; any shape beyond legal fields is rejected as INVALID_FORMAT.

    (Public: dock health check reuses it.)
    """
    if not isinstance(session, dict):
        raise AuthError("INVALID_FORMAT")
    for field in ("auth", "account"):
        if session.get(field) is None:
            raise AuthError("MISSING_SESSION")
        if not isinstance(session[field], dict):
            raise AuthError("INVALID_FORMAT")
    auth = session["auth"]
    token_attr = auth.get("accessToken")
    uid = session["account"].get("uid")
    if token_attr in (None, "") or uid in (None, ""):
        raise AuthError("MISSING_SESSION")
    for source, fields in (
        (session["account"], ("uid", "enterpriseId")),
        (session["auth"], ("domain",)),
    ):
        for field in fields:
            value = source.get(field)
            if value not in (None, "") and (
                not isinstance(value, str)
                or re.fullmatch(r"[\x21-\x7e]{1,2048}", value) is None
            ):
                raise AuthError("INVALID_FORMAT")
    endpoint = auth.get("endpoint")
    if endpoint in (None, ""):
        return
    if not isinstance(endpoint, str) or re.search(r"[\s\x00-\x1f\x7f]", endpoint):
        raise AuthError("INVALID_FORMAT")
    try:
        parsed = urllib.parse.urlsplit(endpoint)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError()
        _port = parsed.port  # explicit port completes legality validation here, no logging
    except ValueError:
        raise AuthError("INVALID_FORMAT") from None


def token_format(value: Any) -> str:
    """Identify token form: "plaintext" (plain string) or "sym-v1" (supported envelope)."""
    if isinstance(value, str):
        if not valid_token(value):
            raise AuthError("INVALID_FORMAT")
        return "plaintext"
    if not isinstance(value, dict):
        raise AuthError("INVALID_FORMAT")
    if (
        set(value) != {"$wbEncrypted", "envelope"}
        or type(value.get("$wbEncrypted")) is not int
        or int(value["$wbEncrypted"]) != 1
    ):
        raise AuthError("UNSUPPORTED_ENVELOPE")
    try:
        encoded = value["envelope"]
        if not isinstance(encoded, str) or not 0 < len(encoded) <= MAX_ENVELOPE_B64:
            raise ValueError()
        raw = base64.b64decode(encoded, validate=True)
        if base64.b64encode(raw).decode("ascii") != encoded:
            raise ValueError()
        envelope = json.loads(raw.decode("utf-8"))
        if not isinstance(envelope, dict) or type(envelope.get("suite")) is not int:
            raise ValueError()
        if envelope["suite"] != 1:
            raise AuthError("UNSUPPORTED_ENVELOPE")
        if set(envelope) != {"suite", "keyId", "nonce", "authTag", "ciphertext"}:
            raise ValueError()
        if (
            not isinstance(envelope["keyId"], str)
            or re.fullmatch(r"[0-9a-f]{16}", envelope["keyId"]) is None
        ):
            raise ValueError()
        for field, length in (("nonce", 12), ("authTag", 16), ("ciphertext", None)):
            data = envelope[field]
            if not isinstance(data, str):
                raise ValueError()
            decoded = base64.b64decode(data, validate=True)
            if base64.b64encode(decoded).decode("ascii") != data or (
                length is not None and len(decoded) != length
            ):
                raise ValueError()
        return "sym-v1"
    except (ValueError, TypeError, KeyError):
        raise AuthError("INVALID_FORMAT") from None


def build_headers(session: dict) -> dict[str, str]:
    """Build API auth headers from the session; token never enters logs or exception text."""
    validate_session(session)
    auth = session.get("auth") or {}
    account = session.get("account") or {}
    token = auth.get("accessToken")
    uid = account.get("uid")
    if not valid_token(token):
        raise AuthError("INVALID_FORMAT")
    headers = {
        "Accept": "application/json",
        "Authorization": "Bearer %s" % token,
        "Content-Type": "application/json",
        "X-User-Id": uid,
        "User-Agent": "WorkBuddy",
    }
    if account.get("enterpriseId"):
        headers["X-Enterprise-Id"] = account["enterpriseId"]
        headers["X-Tenant-Id"] = account["enterpriseId"]
    if auth.get("domain"):
        headers["X-Domain"] = auth["domain"]
    return headers


def helper_env(base: dict[str, str]) -> dict[str, str]:
    """Helper subprocess env: strip variables that could interfere (project prefix changed to BUTLER_), run Electron in Node mode."""
    env = {
        key: value
        for key, value in base.items()
        if not key.upper().startswith(("NODE_", "ELECTRON_", "WORKBUDDY_", "BUTLER_"))
    }
    env["ELECTRON_RUN_AS_NODE"] = "1"
    return env


def helper_js() -> str:
    """Helper JS content (same-directory helper.js; old-repo artifact imported verbatim until the
    ADR-025 extension added the optional expect=field decrypt branch — default token contract unchanged)."""
    return Path(__file__).with_name("helper.js").read_text(encoding="utf-8")


def _decrypt_via(
    payload: dict[str, Any],
    *,
    candidates: list[Path],
    timeout: float = AUTH_HELPER_TIMEOUT,
    runner=run_json_stdin_helper,
) -> str:
    """Shared decryption loop: try candidate runtimes in order, switch to next on KEY_MISMATCH (ADR-008 decision 6)."""
    if not candidates:
        raise AuthError("RUNTIME_NOT_FOUND")
    script = helper_js()
    for exe in candidates:
        try:
            reply = runner(
                str(exe),
                script,
                payload,
                timeout=timeout,
                allowed_reasons=_ALLOWED_HELPER_REASONS,
                env_filter=helper_env,
            )
        except NativeHelperError as exc:
            if exc.reason == "KEY_MISMATCH":
                continue  # coexisting multiple versions is the norm: try next candidate
            raise AuthError(
                exc.reason if exc.reason in AUTH_REASONS else "HELPER_PROTOCOL"
            ) from None
        if set(reply) != {"version", "ok", "accessToken"}:
            raise AuthError("HELPER_PROTOCOL")
        return str(reply["accessToken"])
    raise AuthError("KEY_MISMATCH")  # all candidates' keys mismatch


def decrypt_envelope(
    envelope: dict[str, Any],
    *,
    candidates: list[Path],
    timeout: float = AUTH_HELPER_TIMEOUT,
    runner=run_json_stdin_helper,
) -> str:
    """Envelope → plaintext token: shape-checked per token contract."""
    value = _decrypt_via({"operation": "decrypt", "value": envelope}, candidates=candidates, timeout=timeout, runner=runner)
    if not valid_token(value):
        raise AuthError("HELPER_PROTOCOL")
    return value


def decrypt_field(
    envelope: dict[str, Any],
    *,
    candidates: list[Path],
    timeout: float = AUTH_HELPER_TIMEOUT,
    runner=run_json_stdin_helper,
) -> str:
    """Envelope → arbitrary plaintext field (e.g. account.nickname, ADR-025 extension): helper
    expect=field skips the token charset check; only non-empty ≤ TOKEN_LIMIT is enforced."""
    value = _decrypt_via(
        {"operation": "decrypt", "expect": "field", "value": envelope},
        candidates=candidates,
        timeout=timeout,
        runner=runner,
    )
    if not value or len(value) > TOKEN_LIMIT:
        raise AuthError("HELPER_PROTOCOL")
    return value


def resolve_session(data: dict, *, decrypt: Callable[[dict], str]) -> dict:
    """Validate the session and decrypt the encrypted token into plaintext; plaintext used as-is (fetch and use on demand, never persisted)."""
    validate_session(data)
    token = data["auth"]["accessToken"]
    if token_format(token) != "plaintext":
        token = decrypt(token)
        if not valid_token(token):
            raise AuthError("HELPER_PROTOCOL")
    return dict(data, auth=dict(data["auth"], accessToken=token))
