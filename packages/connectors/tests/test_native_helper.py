"""native_helper offline tests (A2-02 §8): do not launch Electron; fake helper = Python subprocess (sys.executable + "-c").

Windows Python subprocesses won't start without SystemRoot: the fake env bundle uniformly passes SystemRoot/TEMP/TMP
(the real path goes through session.helper_env stripping + ELECTRON_RUN_AS_NODE, covered by live-machine acceptance).
"""

from __future__ import annotations

import os
import sys
import tempfile

import pytest

from kabao_connectors.native_helper import (
    DEFAULT_INPUT_LIMIT,
    NativeHelperError,
    run_json_stdin_helper,
)

ALLOWED = frozenset({"INVALID_FORMAT", "KEY_MISMATCH", "HELPER_TIMEOUT", "HELPER_PROTOCOL"})


def py_env() -> dict[str, str]:
    """Windows Python subprocess must have SystemRoot; the fake bundle passes the minimal set uniformly."""
    return {
        "SystemRoot": os.environ.get("SystemRoot", r"C:\Windows"),
        "TEMP": os.environ.get("TEMP", tempfile.gettempdir()),
        "TMP": os.environ.get("TMP", tempfile.gettempdir()),
    }


def run_py(helper_src: str, request: dict, *, timeout: float = 10.0, env_filter=None, **kw) -> dict:
    return run_json_stdin_helper(
        sys.executable,
        helper_src,
        request,
        timeout=timeout,
        allowed_reasons=kw.pop("allowed_reasons", ALLOWED),
        env_filter=env_filter if env_filter is not None else (lambda _base: py_env()),
        script_flag="-c",
        **kw,
    )


ECHO = """
import json, sys
req = json.loads(sys.stdin.read())
sys.stdout.write(json.dumps({"version": 1, "ok": True, "echo": req}))
"""


def test_round_trip_injects_version():
    reply = run_py(ECHO, {"operation": "decrypt", "value": {"x": 1}})
    assert reply["echo"] == {"operation": "decrypt", "value": {"x": 1}, "version": 1}


def test_business_reason_passthrough():
    src = """
import json, sys
sys.stdin.read()
sys.stdout.write(json.dumps({"version": 1, "ok": False, "reason": "KEY_MISMATCH"}))
sys.exit(1)
"""
    with pytest.raises(NativeHelperError) as exc:
        run_py(src, {})
    assert exc.value.reason == "KEY_MISMATCH"


def test_unknown_reason_is_protocol_error():
    src = """
import json, sys
sys.stdin.read()
sys.stdout.write(json.dumps({"version": 1, "ok": False, "reason": "SOMETHING_ELSE"}))
sys.exit(1)
"""
    with pytest.raises(NativeHelperError) as exc:
        run_py(src, {})
    assert exc.value.reason == "HELPER_PROTOCOL"


def test_ok_false_with_exit_zero_is_protocol_error():
    src = """
import json, sys
sys.stdin.read()
sys.stdout.write(json.dumps({"version": 1, "ok": False, "reason": "KEY_MISMATCH"}))
"""
    with pytest.raises(NativeHelperError) as exc:
        run_py(src, {})
    assert exc.value.reason == "HELPER_PROTOCOL"


def test_garbage_stdout_is_protocol_error():
    src = "import sys; sys.stdout.write('not json')"
    with pytest.raises(NativeHelperError) as exc:
        run_py(src, {})
    assert exc.value.reason == "HELPER_PROTOCOL"


def test_hard_timeout_kills_process():
    src = "import time; time.sleep(5)"
    with pytest.raises(NativeHelperError) as exc:
        run_py(src, {}, timeout=0.5)
    assert exc.value.reason == "HELPER_TIMEOUT"


def test_output_over_limit_is_protocol_error():
    src = "import sys; sys.stdout.write('x' * 200)"
    with pytest.raises(NativeHelperError) as exc:
        run_py(src, {}, output_limit=64)
    assert exc.value.reason == "HELPER_PROTOCOL"


def test_input_over_limit_is_invalid_format():
    with pytest.raises(NativeHelperError) as exc:
        run_py(ECHO, {"blob": "x" * (DEFAULT_INPUT_LIMIT + 5000)})
    assert exc.value.reason == "INVALID_FORMAT"


def test_unserializable_request_is_invalid_format():
    with pytest.raises(NativeHelperError) as exc:
        run_py(ECHO, {"obj": object()})
    assert exc.value.reason == "INVALID_FORMAT"


def test_zero_timeout_short_circuits():
    with pytest.raises(NativeHelperError) as exc:
        run_py(ECHO, {}, timeout=0)
    assert exc.value.reason == "HELPER_TIMEOUT"


def test_env_filter_controls_child_env():
    src = """
import json, os, sys
sys.stdout.write(json.dumps({"version": 1, "ok": True, "marker": os.environ.get("MARKER")}))
"""
    reply = run_py(src, {}, env_filter=lambda _base: {**py_env(), "MARKER": "seen"})
    assert reply["marker"] == "seen"
