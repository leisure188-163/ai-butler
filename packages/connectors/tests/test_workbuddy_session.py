"""session offline tests: validation chain / token forms / header assembly / decryption chain candidate traversal (fake runner, no Electron)."""

from __future__ import annotations

import base64
import json

import pytest

from butler_connectors.native_helper import NativeHelperError
from butler_connectors.workbuddy_cn import session
from butler_connectors.workbuddy_cn.session import (
    AUTH_REASONS,
    AuthError,
    build_headers,
    decrypt_envelope,
    helper_env,
    helper_js,
    resolve_session,
    token_format,
    validate_session,
)

_PLAIN = {
    "auth": {"accessToken": "abcDEF123._~+/==", "domain": "www.workbuddy.cn"},
    "account": {"uid": "u-1", "enterpriseId": "e-9"},
}


def _envelope(*, suite=1, key_id="0123456789abcdef", nonce_len=12) -> dict:
    inner = {
        "suite": suite,
        "keyId": key_id,
        "nonce": base64.b64encode(b"n" * nonce_len).decode(),
        "authTag": base64.b64encode(b"t" * 16).decode(),
        "ciphertext": base64.b64encode(b"c" * 8).decode(),
    }
    return {
        "$wbEncrypted": 1,
        "envelope": base64.b64encode(json.dumps(inner).encode()).decode(),
    }


def test_auth_error_fixed_copy():
    assert str(AuthError("MISSING_SESSION")) == AUTH_REASONS["MISSING_SESSION"]
    assert AuthError("WHATEVER").reason == "WHATEVER"  # unknown reason → default human-readable copy


def test_validate_requires_auth_and_account():
    with pytest.raises(AuthError) as exc:
        validate_session({})
    assert exc.value.reason == "MISSING_SESSION"
    with pytest.raises(AuthError) as exc:
        validate_session({"auth": None, "account": {"uid": "u"}})
    assert exc.value.reason == "MISSING_SESSION"
    with pytest.raises(AuthError) as exc:
        validate_session({"auth": "str", "account": {"uid": "u"}})
    assert exc.value.reason == "INVALID_FORMAT"


def test_validate_requires_token_and_uid():
    with pytest.raises(AuthError) as exc:
        validate_session({"auth": {}, "account": {"uid": "u"}})
    assert exc.value.reason == "MISSING_SESSION"
    with pytest.raises(AuthError) as exc:
        validate_session({"auth": {"accessToken": "t"}, "account": {}})
    assert exc.value.reason == "MISSING_SESSION"


def test_validate_field_charset():
    with pytest.raises(AuthError) as exc:
        validate_session(dict(_PLAIN, account={"uid": "user name"}))  # space ∉ [\x21-\x7e]
    assert exc.value.reason == "INVALID_FORMAT"
    with pytest.raises(AuthError) as exc:
        validate_session(dict(_PLAIN, auth={"accessToken": "t", "domain": "域名"}))
    assert exc.value.reason == "INVALID_FORMAT"


def test_validate_endpoint_strict():
    for endpoint in (
        "http://copilot.tencent.com",  # not https
        "https://x.com/?a=1",  # with query
        "https://x.com/#frag",  # with fragment
        "https://u:p@x.com",  # userinfo
        "not a url",  # no scheme
        "https://x.com:99999",  # illegal port
    ):
        bad = {"auth": {"accessToken": "t", "endpoint": endpoint}, "account": {"uid": "u"}}
        with pytest.raises(AuthError) as exc:
            validate_session(bad)
        assert exc.value.reason == "INVALID_FORMAT"
    validate_session(
        {"auth": {"accessToken": "t", "endpoint": "https://alt.example.com:8443"},
         "account": {"uid": "u"}}  # explicit legal port passes
    )


def test_token_format_plaintext():
    assert token_format("abcDEF123._~+/==") == "plaintext"
    with pytest.raises(AuthError) as exc:
        token_format("bad token!")
    assert exc.value.reason == "INVALID_FORMAT"
    with pytest.raises(AuthError):
        token_format("x" * 32769)


def test_token_format_envelope_ok():
    assert token_format(_envelope()) == "sym-v1"


def test_token_format_unsupported_envelope():
    for bad in (
        {"$wbEncrypted": 2, "envelope": _envelope()["envelope"]},
        {"$wbEncrypted": 1},  # missing envelope
        {"$wbEncrypted": "1", "envelope": _envelope()["envelope"]},
        {"wbEncrypted": 1, "envelope": _envelope()["envelope"]},
    ):
        with pytest.raises(AuthError) as exc:
            token_format(bad)
        assert exc.value.reason == "UNSUPPORTED_ENVELOPE"


def test_token_format_envelope_suite_mismatch():
    with pytest.raises(AuthError) as exc:
        token_format(_envelope(suite=2))
    assert exc.value.reason == "UNSUPPORTED_ENVELOPE"


def test_token_format_envelope_bad_nonce():
    with pytest.raises(AuthError) as exc:
        token_format(_envelope(nonce_len=11))  # nonce must be 12B
    assert exc.value.reason == "INVALID_FORMAT"


def test_build_headers_full_and_minimal():
    assert build_headers(_PLAIN) == {
        "Accept": "application/json",
        "Authorization": "Bearer abcDEF123._~+/==",
        "Content-Type": "application/json",
        "X-User-Id": "u-1",
        "User-Agent": "WorkBuddy",
        "X-Enterprise-Id": "e-9",
        "X-Tenant-Id": "e-9",
        "X-Domain": "www.workbuddy.cn",
    }
    minimal = build_headers({"auth": {"accessToken": "t"}, "account": {"uid": "u"}})
    assert "X-Enterprise-Id" not in minimal and "X-Domain" not in minimal


def test_build_headers_invalid_token_never_leaks():
    with pytest.raises(AuthError) as exc:
        build_headers({"auth": {"accessToken": "bad token!"}, "account": {"uid": "u"}})
    assert exc.value.reason == "INVALID_FORMAT"
    assert "bad token" not in str(exc.value)  # token never enters exception text


class RecordingRunner:
    """Fake runner: replays the script (NativeHelperError | dict) in order, leaving call artifacts."""

    def __init__(self, script: list) -> None:
        self.script = list(script)
        self.calls: list[dict] = []

    def __call__(self, exe, script_text, request, **kw) -> dict:
        self.calls.append({"exe": exe, "script": script_text, "request": request, **kw})
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def test_decrypt_candidates_traversal():
    runner = RecordingRunner(
        [NativeHelperError("KEY_MISMATCH"), {"version": 1, "ok": True, "accessToken": "plain-tok"}]
    )
    token = decrypt_envelope(_envelope(), candidates=["a.exe", "b.exe"], runner=runner)
    assert token == "plain-tok"
    assert [c["exe"] for c in runner.calls] == ["a.exe", "b.exe"]  # KEY_MISMATCH switches to next


def test_decrypt_all_key_mismatch():
    runner = RecordingRunner(
        [NativeHelperError("KEY_MISMATCH"), NativeHelperError("KEY_MISMATCH")]
    )
    with pytest.raises(AuthError) as exc:
        decrypt_envelope(_envelope(), candidates=["a.exe", "b.exe"], runner=runner)
    assert exc.value.reason == "KEY_MISMATCH"


def test_decrypt_other_reason_maps_to_auth_error():
    runner = RecordingRunner([NativeHelperError("RUNTIME_UNAVAILABLE")])
    with pytest.raises(AuthError) as exc:
        decrypt_envelope(_envelope(), candidates=["a.exe"], runner=runner)
    assert exc.value.reason == "RUNTIME_UNAVAILABLE"


def test_decrypt_no_candidates():
    with pytest.raises(AuthError) as exc:
        decrypt_envelope(_envelope(), candidates=[])
    assert exc.value.reason == "RUNTIME_NOT_FOUND"


def test_decrypt_bad_reply_shapes():
    runner = RecordingRunner([{"version": 1, "ok": True, "accessToken": "t", "extra": 1}])
    with pytest.raises(AuthError) as exc:
        decrypt_envelope(_envelope(), candidates=["a.exe"], runner=runner)
    assert exc.value.reason == "HELPER_PROTOCOL"
    runner = RecordingRunner([{"version": 1, "ok": True, "accessToken": "bad token!"}])
    with pytest.raises(AuthError) as exc:
        decrypt_envelope(_envelope(), candidates=["a.exe"], runner=runner)
    assert exc.value.reason == "HELPER_PROTOCOL"


def test_decrypt_runner_args():
    runner = RecordingRunner([{"version": 1, "ok": True, "accessToken": "t"}])
    envelope = _envelope()
    decrypt_envelope(envelope, candidates=["a.exe"], runner=runner, timeout=3.5)
    call = runner.calls[0]
    assert call["request"] == {"operation": "decrypt", "value": envelope}
    assert call["timeout"] == 3.5
    assert call["allowed_reasons"] == session._ALLOWED_HELPER_REASONS
    assert call["env_filter"] is session.helper_env
    assert call["script"].startswith("'use strict';")


def test_resolve_plaintext_skips_decrypt():
    def boom(_envelope):
        raise AssertionError("plaintext token must not enter the decryption chain")

    resolved = resolve_session(_PLAIN, decrypt=boom)
    assert resolved["auth"]["accessToken"] == "abcDEF123._~+/=="


def test_resolve_envelope_uses_decrypt():
    data = {"auth": {"accessToken": _envelope()}, "account": {"uid": "u"}}
    resolved = resolve_session(data, decrypt=lambda _e: "plain-tok-999")
    assert resolved["auth"]["accessToken"] == "plain-tok-999"


def test_resolve_envelope_decrypt_bad_token():
    data = {"auth": {"accessToken": _envelope()}, "account": {"uid": "u"}}
    with pytest.raises(AuthError) as exc:
        resolve_session(data, decrypt=lambda _e: "bad token!")
    assert exc.value.reason == "HELPER_PROTOCOL"


def test_helper_env_strips_and_forces_node_mode():
    env = helper_env(
        {
            "NODE_OPTIONS": "x",
            "ELECTRON_RUN_AS_NODE": "0",
            "WORKBUDDY_EXE": "y",
            "BUTLER_DB": "z",
            "SystemRoot": r"C:\Windows",
        }
    )
    assert "NODE_OPTIONS" not in env
    assert "WORKBUDDY_EXE" not in env
    assert "BUTLER_DB" not in env
    assert env["ELECTRON_RUN_AS_NODE"] == "1"
    assert env["SystemRoot"] == r"C:\Windows"


def test_helper_js_content():
    assert helper_js().startswith("'use strict';")
