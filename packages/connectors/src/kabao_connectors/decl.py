"""声明式 provision 引擎（三级扩展第一级，A2-02 §4 五段式 → RunResult）。

执行语义（协议结论来自各连接器 PROTOCOL.md，判定算法在此单源）：
1. 解锁：vault 按申报 kinds 取凭据 → 字段字典 → 填 header 模板（缺字段显式爆）
2. status 先行：已被领过 → ALREADY（省一次 claim）；dry_run → SKIPPED（只报告）
3. claim：retry.on_codes 命中 → 按 backoff_seconds 退避重试（受 deadline 硬约束）
4. 结果翻译：非 ok 业务码经 ADR-002 方言 from_engine(...)；未知码把
   UnknownEngineCode 抛给 ExecuteAction（FAILED + PROTOCOL_CHANGED 事件）；
   响应缺关键字段 = 协议形状变化的探测点，同路处理
5. confirm_by_status：claim 受理后以 status 复查为准（结果权威）
"""

from __future__ import annotations

import time as _time
from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime
from typing import Any

from kabao_core.application.ports import (
    Capabilities,
    CredentialMissing,
    ProvisionPort,
    ProvisionRequest,
    VaultPort,
)
from kabao_core.domain.action import ActionKind
from kabao_core.domain.errors import DomainError
from kabao_core.domain.results import Status, UnknownEngineCode, from_engine
from kabao_core.domain.run import Evidence, RepairHint, RunResult
from kabao_core.domain.vault import Secret

from kabao_connectors.manifest import AuthSpec, DeclarativeSpec, ProbeSpec, RequestSpec
from kabao_connectors.transport import HttpRequest, Transport, TransportError
from kabao_connectors.unlock import unlock_all


class TemplateFieldMissing(DomainError):
    """dynamic header 模板引用的字段在解锁产物里不存在——显式报错（红线 5）。"""


class _Verdict(Exception):
    """已翻译成 Status 的业务态（统一收口成 RunResult）。"""

    def __init__(self, status: Status, raw_code: str, note: str = "") -> None:
        self.status = status
        self.raw_code = raw_code
        self.note = note


class _StatusOk:
    """status 判定产物：单布尔模式只看 checked_in；列表模式另带筛选后的待领项。"""

    __slots__ = ("checked_in", "pending", "list_mode")

    def __init__(
        self,
        checked_in: bool,
        pending: tuple[dict, ...] = (),
        list_mode: bool = False,
    ) -> None:
        self.checked_in = checked_in
        self.pending = pending
        self.list_mode = list_mode


def _path_get(payload: Any, dotted: str) -> tuple[bool, Any]:
    """点路径取值；不存在返回 (False, None)。层级由声明指定（显式约定）。"""
    node = payload
    for part in dotted.split("."):
        if isinstance(node, dict) and part in node:
            node = node[part]
        else:
            return False, None
    return True, node


class _FieldMap(dict):
    """模板字段查找：缺字段 = 声明与解锁产物不一致，显式爆。"""

    def __missing__(self, key: str) -> str:
        raise TemplateFieldMissing(f"header 模板引用的字段 {key!r} 不在解锁产物里")


def _matches(item: dict, filter_: dict[str, str]) -> bool:
    """列表项等值筛选：声明的键值对全部命中才算（值经 str 归一，显式声明驱动）。"""
    return all(str(item.get(key)) == value for key, value in filter_.items())


def fill_auth_headers(auth: AuthSpec, fields: Mapping[str, str]) -> dict[str, str]:
    """解锁字段 → 鉴权头组（token 头 + 静态头 + 动态模板）。

    声明式 provision、用量适配（R2）与探针（R3）共用的拼装单源：缺字段显式爆
    （红线 5）。browser_cookie kind 的字段 cookie 整体进 Cookie 头（A2-03 §1）。
    """
    merged = dict(auth.static_headers)
    if auth.kind == "browser_cookie":
        if "cookie" not in fields:
            raise TemplateFieldMissing("cookie（browser_cookie 解锁产物缺失，凭据事故）")
        merged["Cookie"] = fields["cookie"]
    elif auth.token_header is not None:
        if "token" not in fields:
            raise TemplateFieldMissing("token（解锁产物无 token，凭据事故）")
        merged[auth.token_header.name] = auth.token_header.prefix + fields["token"]
    for name, template in auth.dynamic_headers.items():
        merged[name] = template.format_map(_FieldMap(fields))
    return merged


#: 主凭据缺失 / 凭据被拒时的修复文案（按通道分流；kind 形态扩展，非 per-app）
_NO_AUTH_TAIL = {
    "browser_cookie": "重新导入：浏览器登录后重扫（dock）",
}
_NO_AUTH_TAIL_DEFAULT = "重新停靠（dock）本机客户端后重试"


def _no_auth_note(kind: str) -> str:
    return _NO_AUTH_TAIL.get(kind, _NO_AUTH_TAIL_DEFAULT)


def _resolve_auth_headers(
    auth: AuthSpec, vault: VaultPort, account_id: str, kinds: tuple[str, ...]
) -> dict[str, str]:
    """按申报 kinds 解锁并拼鉴权头（provision 与探针共用；缺主凭据 = NO_AUTH 态）。"""
    secrets: dict[str, Secret] = {}
    for kind in kinds:
        try:
            secrets[kind] = vault.load(account_id, [kind])[0]
        except CredentialMissing as exc:
            if kind == auth.kind:
                # 主凭据（登录态）缺失 = 无鉴权 → NO_AUTH（修复 = 重登 + 停靠/重扫）
                raise _Verdict(
                    Status.NO_AUTH, kind, note=f"缺凭据 kind={kind}——{_no_auth_note(auth.kind)}"
                ) from exc
            # 辅凭据（机器身份等）缺失 = 登录态在但头组不全——ADR-004 §4：
            # 缺机器身份 → FAILED + repair_hint（重新停靠），绝不静默空列表
            raise _Verdict(
                Status.FAILED,
                kind,
                note=f"缺凭据 kind={kind}（登录态在，身份未停靠）——{_no_auth_note(auth.kind)}",
            ) from exc
    fields = unlock_all(kinds, secrets)
    return fill_auth_headers(auth, fields)


def _verdict_to_result(display: str, verdict: _Verdict, *, default_no_auth: str) -> RunResult:
    evidence = Evidence(
        summary=f"{display} 业务码 {verdict.raw_code}"
        + (f"（{verdict.note}）" if verdict.note else ""),
        raw_code=verdict.raw_code,
    )
    hint = None
    if verdict.status is Status.NO_AUTH:
        hint = RepairHint(reason=verdict.note or default_no_auth, action_id="dock")
    elif verdict.status is Status.FAILED and verdict.note:
        # 带 note 的 FAILED = 缺辅凭据（机器身份）等"停靠可修"态（ADR-004 §4）；
        # 无 note 的 FAILED（方言业务码事故）维持无 hint 原语义
        hint = RepairHint(reason=verdict.note, action_id="dock")
    return RunResult(status=verdict.status, evidence=(evidence,), repair_hint=hint)


class DeclarativeProvisionPort(ProvisionPort):
    """一个声明式连接器的 provision.run 执行体（结构化实现，不继承）。"""

    def __init__(
        self,
        conn_id: str,
        display: str,
        spec: DeclarativeSpec,
        vault: VaultPort,
        transport: Transport,
        kinds: tuple[str, ...],
        *,
        sleep: Any = None,  # None = 真实等待；测试注入零等待
        now: Any = datetime.now,  # 秒级时钟注入
    ) -> None:
        self._id = conn_id
        self._display = display
        self._spec = spec
        self._vault = vault
        self._call = transport
        self._kinds = kinds
        self._sleep = sleep
        self._now = now

    # --- ProvisionPort ---

    def capabilities(self) -> Capabilities:
        return Capabilities(dry_run=True, idempotency_window="daily")

    def run(self, req: ProvisionRequest) -> RunResult:
        try:
            headers = self._headers(req)
        except _Verdict as verdict:
            return self._verdict_result(verdict)
        except (DomainError, KeyError, ValueError) as exc:
            return self._failed(f"凭据或声明事故：{exc}")
        except UnknownEngineCode:
            raise

        try:
            ok = self._status(headers, req.deadline)
            if ok.checked_in:
                summary = (
                    "status 复查：本期活动均已领取（无待领项）"
                    if ok.list_mode
                    else "status 复查：本窗口已领取"
                )
                return RunResult(
                    status=Status.ALREADY,
                    evidence=(Evidence(summary=summary),),
                )
            if ok.list_mode and not ok.pending:
                return RunResult(
                    status=Status.PENDING,
                    evidence=(
                        Evidence(
                            summary="status 复查：列表无待领项也无已领项——活动未开始或已结束（如实上报）"
                        ),
                    ),
                )
            if req.dry_run:
                detail = (
                    f"dry_run 只报告不领取：将领 {len(ok.pending)} 项"
                    if ok.list_mode
                    else "dry_run 只报告不领取：本窗口可领取"
                )
                return RunResult(
                    status=Status.SKIPPED,
                    evidence=(Evidence(summary=detail),),
                )
            return self._claim(headers, req, ok)
        except _Verdict as verdict:
            return self._verdict_result(verdict)
        except TransportError as exc:
            return self._failed(str(exc))
        except (DomainError, KeyError, ValueError) as exc:
            # 响应形状与声明不符等协议事故 → FAILED 留证据；UnknownEngineCode
            # 不在这里吞（协议变更探测由 ExecuteAction 统一收口产事件）
            if isinstance(exc, UnknownEngineCode):
                raise
            return self._failed(f"声明执行事故：{exc}")
        except UnknownEngineCode:
            raise

    # --- 解锁与拼头 ---

    def _headers(self, req: ProvisionRequest) -> dict[str, str]:
        return _resolve_auth_headers(self._spec.auth, self._vault, req.account_id, self._kinds)

    # --- 请求与判定 ---

    def _status(self, headers: dict[str, str], deadline: datetime) -> _StatusOk:
        spec = self._spec.status
        resp = self._send(spec.request, headers, deadline)
        if not resp.ok:
            raise TransportError(f"status HTTP {resp.status_code}")
        if spec.code_path:
            # 有外壳业务码的协议（trae）；code_path 留空 = 无外壳（qoder 取证
            # 2026-11-11：顶层即业务字段，HTTP 200 即 ok）
            found, code = _path_get(resp.payload, spec.code_path)
            if not found:
                raise UnknownEngineCode(f"{spec.code_path} 缺失", self._id)
            if str(code) != spec.expect_ok:
                raise _Verdict(from_engine(str(code), dialect=self._id), str(code))
        if spec.list_path:
            return self._status_list(resp.payload, spec)
        found, checked = _path_get(resp.payload, spec.checked_in_path)
        if not found or not isinstance(checked, bool):
            raise UnknownEngineCode(f"{spec.checked_in_path} 缺失或非布尔", self._id)
        return _StatusOk(checked_in=checked)

    def _status_list(self, payload: Any, spec) -> _StatusOk:
        """列表模式三分类（qoder PROTOCOL §3）：有待领→领取；有已领→ALREADY；都无→PENDING。"""
        found, listing = _path_get(payload, spec.list_path)
        if not found or not isinstance(listing, list):
            raise UnknownEngineCode(f"{spec.list_path} 缺失或非列表", self._id)
        pending = tuple(
            item
            for item in listing
            if isinstance(item, dict) and _matches(item, spec.item_filter)
        )
        done = (
            tuple(
                item
                for item in listing
                if isinstance(item, dict) and _matches(item, spec.done_filter)
            )
            if spec.done_filter
            else ()
        )
        if pending:
            return _StatusOk(checked_in=False, pending=pending, list_mode=True)
        if done:
            return _StatusOk(checked_in=True, list_mode=True)
        return _StatusOk(checked_in=False, list_mode=True)  # 双空：PENDING 由 run 定夺

    def _claim(
        self, headers: dict[str, str], req: ProvisionRequest, ok: _StatusOk
    ) -> RunResult:
        if self._spec.claim.each:
            return self._claim_each(headers, req, ok.pending)
        spec = self._spec.claim
        backoff = list(spec.retry.backoff_seconds)
        attempt = 0
        while True:
            resp = self._send(spec.request, headers, req.deadline)
            if not resp.ok:
                raise TransportError(f"claim HTTP {resp.status_code}")
            found, code = _path_get(resp.payload, spec.code_path)
            if not found:
                raise UnknownEngineCode(f"{spec.code_path} 缺失", self._id)
            if str(code) == spec.expect_ok:
                if not spec.confirm_by_status:
                    return RunResult(
                        status=Status.CLAIMED,
                        evidence=(Evidence(summary="claim 受理（按响应为准）"),),
                    )
                return self._confirm(headers, req.deadline)
            verdict = _Verdict(
                from_engine(str(code), dialect=self._id), str(code)
            )
            retryable = str(code) in set(spec.retry.on_codes)
            if not retryable or attempt >= len(backoff):
                if attempt:
                    verdict.note = f"退避重试 {attempt} 次后仍未通过，如实上报"
                raise verdict
            self._sleep_for(backoff[attempt], req)
            attempt += 1

    def _claim_each(
        self, headers: dict[str, str], req: ProvisionRequest, pending: tuple[dict, ...]
    ) -> RunResult:
        """列表模式逐项领取：claim url 引用列表项字段，逐项 POST（幂等）。

        HTTP ok 即受理（qoder claim 响应不回显业务码，PROTOCOL §3）；
        HTTP 不 ok 按 backoff 退避重试；全部完成后以 status 复查定论（结果权威）。
        """
        spec = self._spec.claim
        backoff = list(spec.retry.backoff_seconds)
        total = len(pending)
        for idx, item in enumerate(pending, 1):
            url = spec.request.url.format_map(_FieldMap(item))
            attempt = 0
            while True:
                resp = self._send(spec.request, headers, req.deadline, url_override=url)
                if resp.ok:
                    break
                if attempt >= len(backoff):
                    raise TransportError(
                        f"claim 第 {idx}/{total} 项 HTTP {resp.status_code}"
                    )
                self._sleep_for(backoff[attempt], req)
                attempt += 1
        if not spec.confirm_by_status:
            return RunResult(
                status=Status.CLAIMED,
                evidence=(Evidence(summary=f"逐项领取 {total} 项受理（按响应为准）"),),
            )
        try:
            recheck = self._status(headers, req.deadline)
        except _Verdict as verdict:
            return self._verdict_result(verdict)
        if recheck.checked_in:
            return RunResult(
                status=Status.CLAIMED,
                evidence=(
                    Evidence(summary=f"逐项领取 {total} 项受理，status 复查确认待领清空"),
                ),
            )
        remain = len(recheck.pending)
        return RunResult(
            status=Status.PENDING,
            evidence=(
                Evidence(
                    summary=f"逐项领取受理，复查仍有 {remain} 项待领（服务端延迟，如实上报）"
                ),
            ),
        )

    def _confirm(
        self, headers: dict[str, str], deadline: datetime
    ) -> RunResult:
        try:
            ok = self._status(headers, deadline)
        except _Verdict as verdict:
            return self._verdict_result(verdict)
        if ok.checked_in:
            return RunResult(
                status=Status.CLAIMED,
                evidence=(Evidence(summary="claim 受理，status 复查确认领取生效"),),
            )
        return RunResult(
            status=Status.PENDING,
            evidence=(
                Evidence(summary="claim 受理，但复查未见领取状态（服务端排队/延迟，如实上报）"),
            ),
        )

    # --- 机械 ---

    def _send(
        self,
        request_spec: RequestSpec,
        headers: dict[str, str],
        deadline: datetime,
        *,
        url_override: str | None = None,
    ):
        merged = {**headers, **request_spec.headers}
        return self._call(
            HttpRequest(
                method=request_spec.method,
                url=url_override or request_spec.url,
                headers=merged,
                body=dict(request_spec.body) if request_spec.body else None,
            ),
            deadline=deadline,
        )

    def _sleep_for(self, seconds: int, req: ProvisionRequest) -> None:
        """退避等待：注入或真实等待；硬性剩余预算由 transport 按 deadline 执行。"""
        sleeper = self._sleep if self._sleep is not None else _time.sleep
        sleeper(seconds)

    def _verdict_result(self, verdict: _Verdict) -> RunResult:
        return _verdict_to_result(
            self._display,
            verdict,
            default_no_auth="凭据被拒——打开客户端重新登录后重新停靠（dock）",
        )

    def _failed(self, why: str) -> RunResult:
        return RunResult(status=Status.FAILED, evidence=(Evidence(summary=why),))


def _response_digest(resp: object) -> str:
    """响应摘要（探针 evidence 用，A2-03 §3）：取常见错误字段，截断脱敏。"""
    payload = getattr(resp, "payload", None)
    if not isinstance(payload, dict):
        return ""
    parts = [
        found[1]
        for path in ("error.type", "error.details.error_code", "error.message", "type")
        if (found := _path_get(payload, path))[0] and isinstance(found[1], str) and found[1]
    ]
    digest = "/".join(dict.fromkeys(parts))[:160]  # 去重拼接 + 截断
    return digest


class DeclarativeHealthPort:
    """声明式探针端口（A2-03 §3，R3 health.check 通道）。

    实现 core ProvisionPort 协议结构（capabilities + run）——复用既有
    路由/台账/事件机制，core 零改动。非 health.check 动作显式拒绝（网页通道
    无领取概念，A1-04 §6）。七词映射：HTTP ok = ALREADY（期望态已达成，
    healthy = silent）；映射码经 ADR-002 方言；未知码上抛给 ExecuteAction
    （FAILED + PROTOCOL_CHANGED）。
    """

    def __init__(
        self,
        conn_id: str,
        display: str,
        spec: ProbeSpec,
        vault: VaultPort,
        transport: Transport,
        kinds: tuple[str, ...],
    ) -> None:
        self._id = conn_id
        self._display = display
        self._spec = spec
        self._vault = vault
        self._call = transport
        self._kinds = kinds

    def capabilities(self) -> Capabilities:
        return Capabilities(dry_run=False)

    def run(self, req: ProvisionRequest) -> RunResult:
        if req.kind is not ActionKind.HEALTH_CHECK:
            return RunResult(
                status=Status.FAILED,
                evidence=(
                    Evidence(
                        summary=f"{self._display} 不支持动作 {req.kind.value}（网页通道仅体检探针）"
                    ),
                ),
            )
        try:
            headers = _resolve_auth_headers(
                self._spec.auth, self._vault, req.account_id, self._kinds
            )
        except _Verdict as verdict:
            return self._verdict_result(verdict)
        except (DomainError, KeyError, ValueError) as exc:
            return RunResult(
                status=Status.FAILED,
                evidence=(Evidence(summary=f"凭据或声明事故：{exc}"),),
            )

        try:
            resp = self._send(self._spec.probe.request, headers, req.deadline)
        except TransportError as exc:
            return RunResult(
                status=Status.FAILED,
                evidence=(Evidence(summary=f"探针不可达（网络/可达性，非会话结论）：{exc}"),),
            )
        code = str(resp.status_code)
        if resp.status_code == self._spec.probe.ok_status:
            return RunResult(
                status=Status.ALREADY,
                evidence=(Evidence(summary=f"探针 HTTP {code}：会话有效"),),
            )
        digest = _response_digest(resp)
        verdict = _Verdict(
            from_engine(code, dialect=self._id), code, note=digest
        )
        return self._verdict_result(verdict)

    def _send(
        self, request_spec: RequestSpec, headers: dict[str, str], deadline: datetime
    ):
        merged = {**headers, **request_spec.headers}
        return self._call(
            HttpRequest(
                method=request_spec.method,
                url=request_spec.url,
                headers=merged,
                body=dict(request_spec.body) if request_spec.body else None,
            ),
            deadline=deadline,
        )

    def _verdict_result(self, verdict: _Verdict) -> RunResult:
        result = _verdict_to_result(
            self._display,
            verdict,
            default_no_auth="会话失效或遇风控挑战——浏览器重新登录后重新导入（dock）",
        )
        if verdict.status is Status.EXPIRED and result.repair_hint is None:
            # A2-03 §3：探针 EXPIRED 的修复同样是重新导入（provision 通道不带此 hint）
            return replace(
                result,
                repair_hint=RepairHint(
                    reason=verdict.note or "会话已过期——浏览器重新登录后重新导入（dock）",
                    action_id="dock",
                ),
            )
        return result
