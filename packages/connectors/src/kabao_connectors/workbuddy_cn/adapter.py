"""workbuddy_cn connector (ADR-006): encrypted-credential decryption-chain port implementation — WorkBuddy-specific is only the credential chain.

- registry adapter contract (registry._load_entry): ``adapter.kabao`` provides build_port / dock
  hooks (manifest/dock 入册见同 Task）；vault 参数保留（契约签名）但现用现取零 vault（ADR-006
  决策 3：客户端 30 天自动刷新并重写凭据文件，入库即过期）
- Orchestration (PROTOCOL §3 decision table): locate credential → parse/decrypt → status query (claim only if
  unsigned) → claim → recheck; 401/403/active/already-signed/credit/error codes all land as explicit statuses
- Dialect loading-phase self-registration (ADR-002): dialect = {"10001": ALREADY} (claim 400 already-signed code);
  other unknown claim codes deliberately unregistered → UnknownEngineCode → use case layer FAILED +
  PROTOCOL_CHANGED (red line 5)
- Decryption primitives in native_helper.py (generic); local environment in localenv.py (workbuddy-specific)
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from kabao_core.application.ports import (
    Capabilities,
    ProvisionPort,
    ProvisionRequest,
)
from kabao_core.domain.results import Status, from_engine
from kabao_core.domain.run import Evidence, RepairHint, RunResult

from kabao_connectors.registry import DockContext, DockOutcome
from kabao_connectors.transport import HttpRequest, TransportError
from kabao_connectors.workbuddy_cn.credentials import find_auth_file, load_session_retry
from kabao_connectors.workbuddy_cn.localenv import InvalidOverride, WorkbuddyEnv, real_env
from kabao_connectors.workbuddy_cn.session import (
    AUTH_HELPER_TIMEOUT,
    DEFAULT_ENDPOINT,
    AuthError,
    build_headers,
    decrypt_envelope,
    resolve_session,
    token_format,
    validate_session,
)

CONN_ID = "workbuddy_cn"
DISPLAY = "WorkBuddy CN"

_BASE = DEFAULT_ENDPOINT  # credential auth.endpoint can override (PROTOCOL §1, only if valid https)
_STATUS_PATH = "/v2/billing/meter/checkin-activity-status"
_CLAIM_PATH = "/v2/billing/meter/daily-checkin"


def _failed(summary: str, *, raw_code: str | None = None) -> RunResult:
    return RunResult(Status.FAILED, evidence=(Evidence(summary, raw_code=raw_code),))


def _no_auth(exc: AuthError, *, extra: str = "") -> RunResult:
    """Credential-layer failure → NO_AUTH + fixed human-readable copy + dock guidance (AUTH_REASONS single source)."""
    return RunResult(
        Status.NO_AUTH,
        evidence=(Evidence(f"{exc}{extra}"),),
        repair_hint=RepairHint(str(exc), "dock"),
    )


def _short_json(body: Any, limit: int = 200) -> str:
    """Debug summary: flatten to one line and truncate; claim responses contain no token (redaction invariant, PROTOCOL §4)."""
    try:
        text = json.dumps(body, ensure_ascii=False)
    except (TypeError, ValueError):
        text = repr(body)
    text = " ".join(text.split())
    return text[:limit] + ("…" if len(text) > limit else "")


def _fmt_credit(value: Any) -> Any:
    """Credit display: int if convertible, else as-is (old repo fields.fmt_credit same semantics)."""
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return value


_WRAPPERS = ("data", "result", "resp", "response")


def _dig(obj: Any, key: str) -> Any:
    """Find a field in responses possibly wrapped by data/result envelopes (old repo fields.dig same semantics)."""
    if isinstance(obj, dict):
        if obj.get(key) is not None:
            return obj[key]
        for wrapper in _WRAPPERS:
            inner = obj.get(wrapper)
            if isinstance(inner, dict):
                found = _dig(inner, key)
                if found is not None:
                    return found
    return None


def _checked_in(status: dict) -> bool:
    return _dig(status, "today_checked_in") in (True, 1)


def _already(status: dict, *, via: str = "") -> RunResult:
    """"Signed today" evidence assembly (old repo checkin._already same semantics: credit/streak/cumulative optional)."""
    parts: list[str] = []
    today_credit = _dig(status, "today_credit") or _dig(status, "daily_credit")
    if today_credit is not None:
        parts.append(f"今日 +{_fmt_credit(today_credit)}")
    streak_days = _dig(status, "streak_days")
    if streak_days is not None:
        parts.append(f"连续 {streak_days} 天")
    total_credits = _dig(status, "total_credits")
    if total_credits is not None:
        parts.append(f"累计 {_fmt_credit(total_credits)} 积分")
    prefix = via or "今日已签过"
    summary = f"{prefix}（{'，'.join(parts)}）" if parts else prefix
    return RunResult(Status.ALREADY, evidence=(Evidence(summary),))


def _claimed(credit: Any, status: dict) -> RunResult:
    """Claim success evidence (old repo checkin._claimed_report same semantics: streak optional, don't print None)."""
    bonus = "，且为连签奖励日" if _dig(status, "is_streak_day") else ""
    total = _dig(status, "total_credits")
    cum = f"，累计 {_fmt_credit(total)} 积分" if total is not None else ""
    streak_days = _dig(status, "streak_days")
    if streak_days is not None:
        streak = f"（连续 {streak_days} 天{cum}）"
    elif cum:
        streak = f"（{cum.lstrip('，')}）"
    else:
        streak = ""
    return RunResult(
        Status.CLAIMED,
        evidence=(Evidence(f"成功领取 {_fmt_credit(credit)} 积分{bonus}{streak}"),),
    )


class WorkbuddyProvisionPort(ProvisionPort):
    """WorkBuddy sign-in port: decryption chain fetched on demand + status-driven decisions; dry_run only queries.

    Credentials fetched and decrypted per run (ADR-006 decision 3): locate file → parse (transient lock retry) →
    subprocess decryption only for envelopes → build headers in memory, discard after use; except PENDING, all
    statuses land explicitly per the PROTOCOL §3 decision table, never silent fallback (red line 5).
    """

    def __init__(self, *, transport, env: WorkbuddyEnv) -> None:
        self.transport = transport
        self.env = env

    def capabilities(self) -> Capabilities:
        return Capabilities(dry_run=True, idempotency_window="daily")

    def run(self, req: ProvisionRequest) -> RunResult:
        path, looked_in = find_auth_file()
        if path is None:
            return _no_auth(
                AuthError("MISSING_SESSION"),
                extra=f"（检查过: {'; '.join(looked_in)}）",
            )
        try:
            data = load_session_retry(path)
        except (OSError, ValueError) as exc:
            return _no_auth(
                AuthError("INVALID_FORMAT"),
                extra=f"（凭据文件不可读: {type(exc).__name__}）",
            )
        try:
            session = resolve_session(
                data,
                decrypt=lambda envelope: self._decrypt(envelope, req.deadline),
            )
            headers = build_headers(session)
        except AuthError as exc:
            return _no_auth(exc)
        endpoint = session["auth"].get("endpoint") or _BASE
        try:
            http, payload = self._post(endpoint, _STATUS_PATH, headers, req.deadline)
        except TransportError as exc:
            return _failed(f"status 查询失败: {exc}")
        if http in (401, 403):
            return self._auth_reject(http)
        if not 200 <= http < 300:
            return _failed(f"status 接口返回异常（HTTP {http}）", raw_code=str(http))
        status = payload if isinstance(payload, dict) else {}
        if _dig(status, "active") is False:
            name = _dig(status, "activity_name")
            return RunResult(
                Status.PENDING,
                evidence=(Evidence("签到活动未开启" + (f"（{name}）" if name else "")),),
            )
        if _checked_in(status):
            return _already(status)
        if req.dry_run:
            return RunResult(
                Status.SKIPPED,
                evidence=(Evidence("今日未签；dry_run 只查不领（不发 claim 请求）"),),
            )
        return self._claim(endpoint, headers, req.deadline, status)

    # --- Orchestration steps ---

    def _post(
        self, endpoint: str, path: str, headers: dict[str, str], deadline: datetime
    ) -> tuple[int, Any]:
        """POST with empty body (PROTOCOL §2: old repo net.post sends directly without payload); TransportError propagates."""
        response = self.transport(
            HttpRequest(method="POST", url=f"{endpoint}{path}", headers=headers),
            deadline=deadline,
        )
        return response.status_code, response.payload

    def _decrypt(self, envelope: dict, deadline: datetime) -> str:
        """Envelope decryption: candidates from env; timeout = min(10s, remaining budget) (budget discipline same as transport)."""
        remaining = (deadline - datetime.now(deadline.tzinfo)).total_seconds()
        timeout = min(AUTH_HELPER_TIMEOUT, max(remaining, 0.0))
        try:
            candidates = self.env.locate_runtime_candidates()
        except InvalidOverride:
            raise AuthError("INVALID_RUNTIME_PATH") from None
        return decrypt_envelope(envelope, candidates=candidates, timeout=timeout)

    def _claim(self, endpoint: str, headers: dict, deadline: datetime, status: dict) -> RunResult:
        try:
            http, payload = self._post(endpoint, _CLAIM_PATH, headers, deadline)
        except TransportError as exc:
            return _failed(f"claim 请求失败: {exc}")
        if http in (401, 403):
            return self._auth_reject(http)
        if self._claim_already(http, payload):
            return self._recheck(
                endpoint, headers, deadline, status,
                via="今日已签过（服务端判定已领取）",
            )
        credit = payload.get("credit") if isinstance(payload, dict) else None
        if credit is not None:
            return self._recheck(endpoint, headers, deadline, status, credit=credit)
        if isinstance(payload, dict) and ("code" in payload or "msg" in payload):
            raw = payload.get("code")
            if raw is not None:
                # Dialect decision ({"10001": ALREADY}): unknown codes → UnknownEngineCode (red line 5, use
                # case layer FAILED + PROTOCOL_CHANGED, not silent fallback)
                from_engine(str(raw), dialect=CONN_ID)
                return self._recheck(
                    endpoint, headers, deadline, status,
                    via="今日已签过（服务端判定已领取）",
                )
            return _failed(f"领取失败: {payload.get('msg')}（HTTP {http}）", raw_code=str(http))
        return _failed(f"未识别的领取返回: {_short_json(payload)}", raw_code=str(http))

    @staticmethod
    def _claim_already(http: int, payload: Any) -> bool:
        """All three "claim already done" forms compatible (PROTOCOL §4): null (limited to 2xx) / 400+10001 / msg contains 「已签」.

        Divergence from old oracle: old is_already(None) unconditionally True — 5xx empty body would misjudge, add 2xx guard.
        """
        if payload is None:
            return 200 <= http < 300
        if isinstance(payload, dict):
            msg = str(payload.get("msg") or "")
            if payload.get("code") == 10001 or "已签" in msg:
                return True
        return False

    def _recheck(
        self,
        endpoint: str,
        headers: dict,
        deadline: datetime,
        fallback: dict,
        *,
        via: str = "",
        credit: Any = None,
    ) -> RunResult:
        """Post-claim status recheck (authoritative): on failure fall back to first status, never degrade result (PROTOCOL §4)."""
        fresh: dict = {}
        try:
            http, payload = self._post(endpoint, _STATUS_PATH, headers, deadline)
            if 200 <= http < 300 and isinstance(payload, dict):
                fresh = payload
        except TransportError:
            pass  # recheck failure is not fatal: evidence falls back to first status (same as old repo)
        source = fresh or fallback
        if credit is not None:
            return _claimed(credit, source)
        return _already(source, via=via)

    @staticmethod
    def _auth_reject(http: int) -> RunResult:
        """401→EXPIRED (login expired) / 403→NO_AUTH — must not conclude login expired from 403 (old repo original semantics)."""
        if http == 401:
            return RunResult(
                Status.EXPIRED,
                evidence=(Evidence("服务端拒绝认证（HTTP 401）", raw_code="401"),),
                repair_hint=RepairHint(
                    "登录态已过期——重新登录 WorkBuddy 客户端后重扫（dock）", "dock"
                ),
            )
        return RunResult(
            Status.NO_AUTH,
            evidence=(
                Evidence("服务端拒绝此操作（HTTP 403）——不能据此判断登录过期", raw_code="403"),
            ),
            repair_hint=RepairHint("检查账号权限或活动条件", "dock"),
        )


# --- registry adapter hook surface and docking ---


class _Kabao:
    """registry adapter hook surface: entry = ``adapter.kabao`` (registry._load_entry)."""

    def build_port(
        self,
        *,
        vault,
        transport=None,
        env: WorkbuddyEnv | None = None,
    ) -> WorkbuddyProvisionPort:
        # vault parameter kept (registry contract signature); fetched on demand, zero vault (ADR-006 decision 3)
        from kabao_connectors.transport import httpx_transport

        return WorkbuddyProvisionPort(
            transport=transport if transport is not None else httpx_transport(),
            env=env if env is not None else real_env(),
        )

    def dock(self, ctx: DockContext, *, env: WorkbuddyEnv | None = None) -> DockOutcome:
        """Pure health check + guidance (ADR-006 decision 4): four read-only items, zero network zero decryption, no auto-launch."""
        env = env if env is not None else real_env()
        issues = self._checkup(env)
        if issues:
            return DockOutcome(target=CONN_ID, issues=issues)
        account = ctx.register.execute(CONN_ID, DISPLAY)
        return DockOutcome(target=CONN_ID, accounts=[account.id])

    def _checkup(self, env: WorkbuddyEnv) -> list[str]:
        """Four health-check items (PROTOCOL §5 scenario 1): file → JSON → session shape → runtime (envelope form only)."""
        path, looked_in = find_auth_file()
        if path is None:
            return [
                f"{CONN_ID}: 未找到凭据文件——打开 WorkBuddy 客户端登录后重扫（dock）"
                f"（检查过: {'; '.join(looked_in)}）"
            ]
        try:
            data = load_session_retry(path)
        except (OSError, ValueError) as exc:
            return [f"{CONN_ID}: 凭据文件不可读或非 JSON（{type(exc).__name__}）——重新登录客户端"]
        try:
            validate_session(data)
            fmt = token_format(data["auth"]["accessToken"])
        except AuthError as exc:
            return [f"{CONN_ID}: {exc}"]
        if fmt != "sym-v1":
            return []  # plaintext token: decryption chain needs no runtime, health check ends here
        try:
            candidates = env.locate_runtime_candidates()
        except InvalidOverride as exc:
            return [f"{CONN_ID}: {exc}"]
        if not candidates:
            return [
                f"{CONN_ID}: 凭据为加密信封但未找到客户端 runtime——"
                "安装 WorkBuddy 客户端，或用 WORKBUDDY_EXE 指定其 exe"
            ]
        return []


kabao = _Kabao()

#: Dialect loading-phase self-registration (ADR-002): claim 400 already-signed code; 401/403 are HTTP-layer
#: decisions, not in the dialect (PROTOCOL §3); other unknown codes deliberately unregistered →
#: UnknownEngineCode → use case layer FAILED + PROTOCOL_CHANGED (red line 5).
from kabao_core.domain.results import register_dialect  # noqa: E402

register_dialect(CONN_ID, {"10001": Status.ALREADY})
