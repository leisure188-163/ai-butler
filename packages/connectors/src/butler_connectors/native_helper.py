"""native_helper generic primitives (ADR-006 decision 2): JSON-stdin subprocess runner.

Runs helper scripts in the client's bundled Electron runtime (workbuddy_cn/helper.js): request via stdin, reply
via stdout; this module is responsible for protocol shape — hard timeout, read/write byte caps, reason whitelist,
env stripping; it takes no responsibility for business reasons (only whitelisted reasons pass through as-is).
Same injectable-port shape as cdp.py: exe/script/timeout/env_filter/script_flag all given by the caller, so tests
run Python fake helpers without launching Electron.
"""

from __future__ import annotations

import contextlib
import json
import subprocess
import threading
import time
from collections.abc import Callable, Iterable
from typing import Any

#: Default input/output/error channel caps (bytes), same constants as the old repo.
DEFAULT_INPUT_LIMIT = 65536
DEFAULT_OUTPUT_LIMIT = 65536
DEFAULT_ERR_LIMIT = 8192


class NativeHelperError(RuntimeError):
    """Helper subprocess failure; ``reason`` is a stable error category, translated by the caller."""

    def __init__(self, reason: str, message: str = "") -> None:
        self.reason = reason
        super().__init__(reason if not message else f"{reason}: {message}")


def run_json_stdin_helper(
    exe: str,
    script: str,
    request: dict[str, Any],
    *,
    timeout: float,
    allowed_reasons: Iterable[str],
    input_limit: int = DEFAULT_INPUT_LIMIT,
    output_limit: int = DEFAULT_OUTPUT_LIMIT,
    err_limit: int = DEFAULT_ERR_LIMIT,
    env_filter: Callable[[dict[str, str]], dict[str, str]] | None = None,
    script_flag: str = "-e",
) -> dict[str, Any]:
    """Hand ``request`` (JSON) to ``exe <script_flag> <script>`` via stdin and read back the JSON reply.

    All pipes have byte caps and the whole run has a hard timeout; captured content never enters exception text.
    No protocol reply/over cap/timed out uniformly → HELPER_TIMEOUT or HELPER_PROTOCOL; request unserializable/over
    cap → INVALID_FORMAT; version field force-injected to 1 (helper.js dispatches by version).
    """
    try:
        data = json.dumps(dict(request, version=1), ensure_ascii=True).encode("ascii")
    except (TypeError, ValueError) as exc:
        raise NativeHelperError("INVALID_FORMAT", type(exc).__name__) from None
    if len(data) > input_limit:
        raise NativeHelperError("INVALID_FORMAT")
    if timeout <= 0:
        raise NativeHelperError("HELPER_TIMEOUT")
    env = (env_filter or (lambda base: base))({})  # env base = empty dict (decontamination semantics)
    try:
        process = subprocess.Popen(  # parameters controlled by the caller (domain credential logic)
            [exe, script_flag, script],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            shell=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except OSError as exc:
        raise NativeHelperError("RUNTIME_UNAVAILABLE", type(exc).__name__) from None
    output: dict[str, bytes] = {}
    failed = threading.Event()
    _communicate(process, data, output, failed, output_limit, err_limit, timeout)
    return _collect_reply(process, output, failed, allowed_reasons)


def _communicate(
    process: subprocess.Popen[Any],
    data: bytes,
    output: dict[str, bytes],
    failed: threading.Event,
    output_limit: int,
    err_limit: int,
    timeout: float,
) -> None:
    """Concurrently read/write three pipes, kill on cap overflow; final join + kill fallback, timeout → HELPER_TIMEOUT."""
    deadline = time.monotonic() + timeout

    def read_pipe(name: str, pipe: Any, limit: int) -> None:
        try:
            captured = pipe.read(limit + 1)  # read one extra byte to detect overflow
            if len(captured) > limit:
                failed.set()
                process.kill()
            else:
                output[name] = captured
        except OSError:
            failed.set()

    def write_pipe() -> None:
        try:
            process.stdin.write(data)
            process.stdin.close()
        except OSError:
            failed.set()

    workers = [
        threading.Thread(target=read_pipe, args=("stdout", process.stdout, output_limit), daemon=True),
        threading.Thread(target=read_pipe, args=("stderr", process.stderr, err_limit), daemon=True),
        threading.Thread(target=write_pipe, daemon=True),
    ]
    for worker in workers:
        worker.start()
    try:
        process.wait(timeout=max(0.001, deadline - time.monotonic()))
    except subprocess.TimeoutExpired:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=10)
        raise NativeHelperError("HELPER_TIMEOUT") from None
    for worker in workers:
        worker.join(max(0.0, deadline - time.monotonic()))
    if any(worker.is_alive() for worker in workers):
        raise NativeHelperError("HELPER_TIMEOUT")
    for pipe in (process.stdin, process.stdout, process.stderr):
        with contextlib.suppress(Exception):
            pipe.close()
    if failed.is_set():
        raise NativeHelperError("HELPER_PROTOCOL")


def _collect_reply(
    process: subprocess.Popen[Any],
    output: dict[str, bytes],
    failed: threading.Event,
    allowed_reasons: Iterable[str],
) -> dict[str, Any]:
    """Parse and validate the helper reply; anything protocol-suspicious is rejected — never forward suspect data."""
    try:
        reply = json.loads(output.get("stdout", b"").decode("utf-8"))
    except (ValueError, UnicodeError):
        raise NativeHelperError("HELPER_PROTOCOL") from None
    if (
        not isinstance(reply, dict)
        or type(reply.get("version")) is not int
        or reply["version"] != 1
    ):
        raise NativeHelperError("HELPER_PROTOCOL")
    if reply.get("ok") is False and process.returncode == 1:
        reason = reply.get("reason")
        if isinstance(reason, str) and reason in allowed_reasons:
            raise NativeHelperError(reason)
        raise NativeHelperError("HELPER_PROTOCOL")
    if reply.get("ok") is not True or process.returncode != 0 or failed.is_set():
        raise NativeHelperError("HELPER_PROTOCOL")
    return reply
