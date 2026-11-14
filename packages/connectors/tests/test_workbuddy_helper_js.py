"""helper.js verbatim import guard (ADR-006 decision 2: JS/orchestration shape = protocol contract, rewriting is forbidden)."""

from pathlib import Path

HELPER = (
    Path(__file__).parents[1]
    / "src"
    / "butler_connectors"
    / "workbuddy_cn"
    / "helper.js"
)


def test_helper_js_verbatim_markers():
    """Key protocol markers must exist verbatim: bindings/AAD/suite/plumbing caps/whitelisted reasons/destructive cleanup."""
    text = HELPER.read_text(encoding="utf-8")
    assert text.startswith("'use strict';")
    for marker in (
        "electron_browser_workbuddy_storage",  # client internal binding (atRestSecretKey source)
        "loggerGet",
        "aes-256-gcm",
        "'WB-AAD\\0'",  # AAD fixed prefix
        "atRestSecretKey",
        "keyId",
        "65536",  # plumbing caps
        "KEY_MISMATCH",
        "RUNTIME_UNAVAILABLE",
        "UNSUPPORTED_ENVELOPE",
        "$wbEncrypted",
        "key.fill(0)",  # destructive cleanup
    ):
        assert marker in text, marker
