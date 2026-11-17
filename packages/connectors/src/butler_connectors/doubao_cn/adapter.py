"""doubao_cn 连接器（ADR-007）：CDP 界面通道端口实现——豆包专属的只有编排。

- registry adapter 契约（registry._load_entry）：``adapter.butler`` 提供
  build_port / dock 两钩子；vault 参数保留（契约签名）但零凭据设计不使用
- 编排（PROTOCOL §3 判定表）：probe → 版本派生 → 活动页 → Cookie 现取 →
  detail 权威判定 →（未签）界面受信任点击 → 复查；PENDING = 客户端不可达（暂态）
- 方言装载期自注册（ADR-004）：code=2 刻意不注册——未知码 → UnknownEngineCode
  → 用例层统一 FAILED + PROTOCOL_CHANGED（活动换季探测）
- CDP 原语在 cdp.py（通用）；本机环境在 localenv.py（doubao 专属）
"""

from __future__ import annotations

import os
import time
from dataclasses import replace
from datetime import datetime

from butler_core.execution.ports import Capabilities, ProvisionPort, ProvisionRequest
from butler_core.shared.results import Status, from_engine
from butler_core.execution.domain import Evidence, RepairHint, RunResult

from butler_connectors.cdp import (
    CdpChannel,
    CdpConnection,
    CdpError,
    pick_activity_target,
)
from butler_connectors.doubao_cn.identity import (
    ActiveIdentity,
    derive_key,
    load_identity_registry,
    load_main_baseline,
    read_all_identities,
    resolve_account_key,
    save_identity_registry,
)
from butler_connectors.doubao_cn.localenv import LocalEnv, real_env, version_code
from butler_connectors.doubao_cn import snapshot as request_snapshot
from butler_connectors.doubao_cn.switch import (
    SwitchError,
    resolve_target_identity,
    switch_session,
)
from butler_connectors.registry import DockContext, DockOutcome
from butler_connectors.transport import HttpRequest, TransportError, httpx_transport

CONN_ID = "doubao_cn"
DISPLAY = "Doubao CN"

#: 换季时更新此常量（PROTOCOL §6）：detail 回 code=2 = campaign not found。
CAMPAIGN_GROUP_CODE = "pc_incentive_task_mvp_v3"

_BASE = "https://www.doubao.com"
_ACTIVITY_URL = f"{_BASE}/pc/agent-explore"
_DETAIL_PATH = "/alice/ug/campaign/v3/detail/"
#: AGW 公共查询参数（PROTOCOL §2：缺一不可；version_code 运行时派生前置）。
_COMMON_QUERY = (
    "language=zh",
    "device_platform=web",
    "doubao_device_platform=web",
    "aid=497858",
    "real_aid=497858",
    "pkg_type=release_version",
)
_UA_TEMPLATE = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36 SamanthaDoubao/{version}"
)

from butler_connectors.doubao_cn.results import (
    daily_checkin as _daily_checkin,
    failed as _failed,
    pending as _pending,
)
from butler_connectors.doubao_cn.ui_js import (
    _FIND_CLICK_JS,
    _FIND_RETRIES,
    _KILL_SETTLE_SECONDS,
    _PAGE_TEXT_JS,
    _RECHECK_DELAYS,
    _SETTLE_SECONDS,
    _TRACE_INSTALL_JS,
    _TRACE_READ_JS,
)


class DoubaoCdpProvisionPort(ProvisionPort):
    """豆包签到端口：detail 权威判定 + 界面受信任点击；dry_run 只查不点。

    PENDING = 客户端调试端口不可达（暂态，dock 可自动拉起）；除 PENDING 外
    全部按 PROTOCOL §3 判定表显式落状态，绝不静默兜底（红线 5）。
    """

    def __init__(
        self, *, transport, env: LocalEnv, channel: CdpChannel, sleep=time.sleep,
        monotonic=time.monotonic, capture: bool = False,
    ) -> None:
        self.transport = transport
        self.env = env
        self.channel = channel
        self.sleep = sleep
        self.monotonic = monotonic  # 切号翻转轮询的时钟（可注入，离线测试不真等）
        self.capture = capture  # 请求快照（脱敏 JSONL）；失败不阻断签到
        self._switch_note: str | None = None

    def capabilities(self) -> Capabilities:
        return Capabilities(dry_run=True, idempotency_window="daily")

    def run(self, req: ProvisionRequest) -> RunResult:
        try:
            self.channel.probe()
        except CdpError as exc:
            return _pending(
                f"豆包客户端调试端口不可达（{exc}）——运行停靠（dock）自动拉起，"
                f"或手动带 --remote-debugging-port={self.channel.port} 重启客户端"
            )
        version = self.env.read_version()
        vcode = version_code(version) if version else None
        if not vcode:
            return _failed(
                "读不到豆包客户端版本（DOUBAO_VERSION 可覆盖）——无法派生 version_code"
                "（PROTOCOL §1：写死版本正是故障本身）"
            )
        # 多账户身份守卫（A2-02 §6 红线：绝不签错账户）。目标未活跃 → 会话级
        # 自动切号（ADR-007 决策 8，2026-11-17 用户裁决修订决策 7：切换列表
        # 真机取证存在 + 单会话存活语义，PROTOCOL §9）；切号失败/复核不符仍
        # 保守 PENDING，绝不盲签。
        try:
            identities = read_all_identities(self.channel)
        except Exception:  # 身份只读辅助路径：读失败降级空 → 走 PENDING（暂态语义）
            identities = []
        if not identities:
            return _pending(
                "读不到豆包活跃账户身份（主窗口/聊天页不可达）——打开客户端主窗口后重试"
            )
        baseline = load_main_baseline()
        if baseline is None:
            return _pending(
                "豆包 main 账户身份基线未建立——确认客户端当前登录的是主用账户后，"
                "执行一次停靠（dock/导入）建立基线"
            )
        self._switch_note = None
        pending = self._ensure_target_active(req, baseline, identities)
        if pending is not None:
            return pending
        try:
            conn = self._activity_conn()
        except CdpError as exc:
            return _failed(f"活动页不可用（{exc}）——建页失败属协议事故，绝不静默")
        try:
            result = self._orchestrate(conn, req, version=version, vcode=vcode)
        finally:
            conn.close()
        if self._switch_note:
            # 切号留痕进台账 evidence（审计可见：这次签到经历了会话切换）
            result = replace(
                result, evidence=(Evidence(self._switch_note),) + tuple(result.evidence)
            )
        return result

    # --- 多账户守卫与会话级切号（ADR-007 决策 8）---

    def _ensure_target_active(
        self, req: ProvisionRequest, baseline, identities: list
    ) -> RunResult | None:
        """活跃账户 ≠ 目标 → 自动切号并复核；成功 None，失败返回语境正确的 PENDING。"""
        main_active = any(i.sec_uid == baseline.sec_uid for i in identities)
        active_key = "main" if main_active else resolve_account_key(identities[0])
        if f"{CONN_ID}:{active_key}" == req.account_id:
            return None
        others = [i.nickname or resolve_account_key(i) for i in identities
                  if i.sec_uid != baseline.sec_uid]
        who = "、".join(others) or identities[0].nickname or active_key
        fail = self._auto_switch(req.account_id.removeprefix(f"{CONN_ID}:"))
        if fail is not None:
            return _pending(
                f"豆包客户端当前活跃账户是「{who}」，目标 {req.account_id} 未激活；{fail}",
                hint="自动切号未成功——可在客户端左下角头像菜单人工切换后重试"
                     "（暂态，不算失败；登录/添加账号仍需人工）",
            )
        # 单会话存活语义：旧活动页可能残留旧账户 Cookie——关净后由
        # _activity_conn 开新页（新页 Cookie 现取 = 新会话），杜绝签错账户。
        stale = self._close_stale_activity_pages()
        if stale is not None:
            return _pending(stale)
        flipped = read_all_identities(self.channel)
        main_now = any(i.sec_uid == baseline.sec_uid for i in flipped)
        active_now = (
            "main" if main_now else (resolve_account_key(flipped[0]) if flipped else "")
        )
        if f"{CONN_ID}:{active_now}" != req.account_id:
            return _pending(
                f"自动切号后身份复核不符（活跃={active_now or '未知'}，"
                f"目标 {req.account_id}）——绝不盲签（A2-02 §6 红线）",
                hint="切换复核失败——人工在客户端头像菜单确认当前账户后重试",
            )
        return None

    def _auto_switch(self, want_key: str) -> str | None:
        """会话级自动切号。None = 成功；str = 失败原因（PENDING 语境原文）。"""
        target = resolve_target_identity(want_key)
        if target is None or not target.sec_uid:
            return (
                f"目标 {CONN_ID}:{want_key} 不在已登记身份中——自动切号无定位依据；"
                "先人工切到该账户执行一次停靠（dock）登记，之后即可自动切换"
            )
        try:
            switched = switch_session(
                self.channel, target, sleep=self.sleep, monotonic=self.monotonic
            )
        except (SwitchError, CdpError) as exc:
            return f"自动切号到「{target.nickname or want_key}」失败: {exc}"
        self._switch_note = f"自动切号到「{switched.nickname or want_key}」（会话级切换）"
        return None

    def _close_stale_activity_pages(self) -> str | None:
        """切号后关净旧活动页（残留旧账户会话）。None = 干净；str = 显式暂缓。"""
        for _ in range(10):  # 有界：每成功一次少一个 target，正常 1-2 个
            target = pick_activity_target(self.channel.targets())
            if target is None:
                return None
            try:
                self.channel.close_target(str(target.get("id") or ""))
            except CdpError as exc:
                return (
                    f"切号后旧活动页无法关闭（{exc}）——可能残留旧账户会话，"
                    "为不签错账户暂缓签到；重启客户端（dock）后重试"
                )
        return "切号后旧活动页关闭循环超界——客户端 target 状态异常，暂缓签到"

    # --- 编排步骤 ---

    def _orchestrate(
        self, conn: CdpConnection, req: ProvisionRequest, *, version: str, vcode: int
    ) -> RunResult:
        try:
            cookie_header = self._cookie_header(conn)
        except CdpError as exc:
            return _failed(f"CDP 取 Cookie 失败（{exc}）")
        try:
            payload = self._detail(
                cookie_header, vcode, version, req.deadline, req.account_id
            )
        except TransportError as exc:
            return _failed(f"detail 查询失败（只读接口）: {exc}")
        code = str((payload or {}).get("code"))
        if code != "0":
            return self._business_code(code, payload)
        checkin = _daily_checkin(payload)
        if checkin is None:
            return _failed(
                "detail 形状不符（无 daily_signin 任务项）——协议可能已变更", raw_code=code
            )
        if checkin.get("checked_in_today"):
            return RunResult(
                Status.ALREADY,
                evidence=(
                    Evidence(
                        f"detail 权威判定：今日已签（连签 {checkin.get('continuous_days')} 天）",
                        raw_code=code,
                    ),
                ),
            )
        if req.dry_run:
            return RunResult(
                Status.SKIPPED,
                evidence=(Evidence("今日未签；dry_run 只查不点（不发界面点击）", raw_code=code),),
            )
        return self._click_and_confirm(
            conn, cookie_header, vcode, version, req.deadline, code, req.account_id
        )

    def _activity_conn(self) -> CdpConnection:
        """活动页连接：已有 doubao 页则附上去，没有才经 createTarget 开（省资源）。"""
        target = pick_activity_target(self.channel.targets())
        if target is not None:
            return self.channel.attach(target)
        return self.channel.open_activity(_ACTIVITY_URL)

    def _cookie_header(self, conn: CdpConnection) -> str:
        pairs: dict[str, str] = {}
        for cookie in self.channel.cookies(conn):
            name, value = cookie.get("name"), cookie.get("value")
            if name and value:
                pairs.setdefault(name, value)  # 按 name 去重先到先得（旧系统同语义）
        if not pairs:
            raise CdpError("Network.getCookies 返回空——会话异常?")
        return "; ".join(f"{name}={value}" for name, value in pairs.items())

    def _detail(
        self,
        cookie_header: str,
        vcode: int,
        version: str,
        deadline: datetime,
        account_id: str,
    ) -> dict:
        """detail 只读查询（M1 唯一裸 HTTP 接口，PROTOCOL §2 契约形状）。

        capture 开启时每请求写一份脱敏快照（成功/失败/复查），用于对比
        「我们发的 detail」与「客户端页面自己发的 checkin」——快照失败不
        影响签到；默认关闭（取证改走 CDP Network 域旁听，PROTOCOL §2.1）。
        """
        query = "&".join((f"version_code={vcode}", *_COMMON_QUERY))
        request = HttpRequest(
            method="POST",
            url=f"{_BASE}{_DETAIL_PATH}?{query}",
            headers={
                "Cookie": cookie_header,
                "Content-Type": "application/json",
                "Origin": _BASE,
                "Referer": _ACTIVITY_URL,
                "User-Agent": _UA_TEMPLATE.format(version=version),
            },
            body={"campaign_group_code": CAMPAIGN_GROUP_CODE},
        )
        try:
            response = self.transport(request, deadline=deadline)
        except TransportError as exc:
            self._snapshot_detail(
                account_id=account_id,
                version=version,
                vcode=vcode,
                request=request,
                error=str(exc),
            )
            raise
        self._snapshot_detail(
            account_id=account_id,
            version=version,
            vcode=vcode,
            request=request,
            response=response,
        )
        if not response.ok:
            raise TransportError(f"HTTP {response.status_code}")
        payload = response.payload
        return payload if isinstance(payload, dict) else {}

    def _snapshot_detail(self, **kwargs) -> None:
        """best-effort 写 detail 快照；任何 IO/序列化故障都不得阻断签到。"""
        if not self.capture:
            return
        try:
            request_snapshot.record_detail(**kwargs)
        except Exception:
            return

    def _business_code(self, code: str, payload: dict) -> RunResult:
        if code == "710012001":  # 登录过期（方言 NO_AUTH 语义 + 修复指引）
            return RunResult(
                Status.NO_AUTH,
                evidence=(Evidence("登录过期——重开豆包客户端登录后重新停靠（dock）", raw_code=code),),
                repair_hint=RepairHint("豆包登录态已过期", "dock"),
            )
        from_engine(code, dialect=CONN_ID)  # 已知码过校验；未知码（含 2 换季）上抛给用例层
        message = str(payload.get("msg") or payload.get("message") or "")
        return _failed(
            f"detail 业务失败 code={code} {message}——三义码不猜：手工点一次签到"
            "可判别会话降权 vs 平台故障",
            raw_code=code,
        )

    def _click_and_confirm(
        self,
        conn: CdpConnection,
        cookie_header: str,
        vcode: int,
        version: str,
        deadline: datetime,
        raw_code: str,
        account_id: str,
    ) -> RunResult:
        box = None
        for _ in range(_FIND_RETRIES):
            try:
                box = self.channel.evaluate(conn, _FIND_CLICK_JS)
            except CdpError as exc:
                return _failed(f"查找签到按钮失败: {exc}", raw_code=raw_code)
            if box:
                break
            self.sleep(_SETTLE_SECONDS)
        if not box:
            try:
                page_text = str(self.channel.evaluate(conn, _PAGE_TEXT_JS) or "")
            except CdpError:
                page_text = ""
            return _failed(
                f"页面上找不到签到按钮（可能界面改版；页面文本摘要: {page_text[:120]!r}）",
                raw_code=raw_code,
            )
        self._install_trace(conn)
        try:
            self.channel.click(conn, int(box["x"]), int(box["y"]))
        except CdpError as exc:
            return _failed(f"界面点击失败: {exc}", raw_code=raw_code)
        self.sleep(_SETTLE_SECONDS)
        text = str(box.get("text") or "")
        trace = self._read_trace(conn)
        # 复查退避重试（PROTOCOL §3）：点击送达≠状态即时翻转——任一次
        # checked_in_today=true 即 CLAIMED，全部 false 才判 FAILED
        last_transport_error: TransportError | None = None
        try:
            for attempt, extra in enumerate(_RECHECK_DELAYS, start=1):
                if attempt > 1:
                    self.sleep(extra)
                try:
                    payload = self._detail(
                        cookie_header, vcode, version, deadline, account_id
                    )
                except TransportError as exc:
                    last_transport_error = exc
                    continue
                checkin = _daily_checkin(payload)
                if checkin is not None and checkin.get("checked_in_today"):
                    amount = (checkin.get("reward") or {}).get("reward_amount")
                    return RunResult(
                        Status.CLAIMED,
                        evidence=(
                            Evidence(
                                f"界面点击「{text}」后复查已签：+{amount} 额度"
                                f"（连签 {checkin.get('continuous_days')} 天，"
                                f"复查第 {attempt} 次）",
                                raw_code=raw_code,
                            ),
                        ),
                    )
            if last_transport_error is not None:
                return _failed(
                    f"点击后复查 detail 失败: {last_transport_error}", raw_code=raw_code
                )
            return _failed(
                f"已在客户端界面点击「{text}」但复查 {len(_RECHECK_DELAYS)} 次仍未签"
                "——服务端/账号侧异常，可手工点一次确认",
                raw_code=raw_code,
            )
        finally:
            latest = self._read_trace(conn)
            if isinstance(latest, dict):
                trace = latest
            self._snapshot_trace(account_id, text, box, trace)

    def _install_trace(self, conn: CdpConnection) -> None:
        """安装只读页面旁路；capture=False 时不产生任何额外 CDP 调用。"""
        if not self.capture:
            return
        try:
            self.channel.evaluate(conn, _TRACE_INSTALL_JS)
        except CdpError:
            return

    def _read_trace(self, conn: CdpConnection):
        if not self.capture:
            return None
        try:
            value = self.channel.evaluate(conn, _TRACE_READ_JS)
        except CdpError:
            return None
        return value if isinstance(value, dict) else None

    def _snapshot_trace(self, account_id: str, text: str, box: dict, trace) -> None:
        if not self.capture:
            return
        entries = trace.get("entries") if isinstance(trace, dict) else []
        try:
            request_snapshot.record_checkin_trace(
                account_id=account_id,
                click_text=text,
                click_xy=(int(box["x"]), int(box["y"])),
                entries=entries,
            )
        except Exception:
            return


# --- registry adapter 钩子面与停靠 ---

def _ensure_running(env: LocalEnv, channel: CdpChannel) -> list[str]:
    """杀无端口实例 → 带端口重启 → 轮询就绪（ADR-007 决策 5；仅显式 dock 触发，
    调度触发的 run() 绝不杀进程——不可达即 PENDING）。"""
    exe = env.locate_exe()
    if exe is None:
        import sys

        if sys.platform == "darwin":
            return [
                f"{CONN_ID}: 调试端口不可达且未定位到豆包客户端"
                "（/Applications 或 ~/Applications）——确认已安装豆包后重扫，"
                "或用 DOUBAO_EXE 指定客户端主程序"
            ]
        return [
            f"{CONN_ID}: 调试端口不可达且未定位到客户端 exe——手动带 "
            "--remote-debugging-port 启动豆包后重扫"
        ]
    for pid in env.process_pids():
        env.kill_pid(pid)  # probe 已失败 = 端口没开，现存实例都是无端口实例
    # 杀净落定再拉起（2026-11-17 真机实证修复：杀完立即拉起撞单实例锁竞态，
    # 分离接力脚本「杀 → settle 6s → 拉起」5s 内 9222 绑定一次成功）
    env.sleep(_KILL_SETTLE_SECONDS)
    env.spawn_detached(exe)
    for _ in range(10):  # ~15s 轮询就绪
        env.sleep(1.5)
        try:
            channel.probe()
            return []
        except CdpError:
            continue
    return [f"{CONN_ID}: 客户端已带调试端口拉起但 probe 超时未就绪——稍后重扫"]


class _Butler:
    """registry adapter 钩子面：entry = ``adapter.butler``（registry._load_entry）。"""

    def build_port(
        self,
        *,
        vault,
        transport=None,
        env: LocalEnv | None = None,
        channel: CdpChannel | None = None,
        monotonic=None,
    ) -> DoubaoCdpProvisionPort:
        # vault 参数保留（registry 契约签名）；零凭据设计不使用（ADR-007 决策 2）
        env = env if env is not None else real_env()
        return DoubaoCdpProvisionPort(
            transport=transport if transport is not None else httpx_transport(),
            env=env,
            channel=channel if channel is not None else CdpChannel(env.resolve_port()),
            sleep=env.sleep,  # 重试/落定间隔走环境束：测试假束离线、真机 time.sleep
            monotonic=monotonic if monotonic is not None else time.monotonic,
            # 页面级 fetch/XHR 猴补在字节反爬页上默认禁用（2026-11-17 裁决：
            # 原生函数被包装存在指纹检测风险，生产 run 必须零注入；取证走
            # CDP Network 域旁听，页面 JS 不可见）——显式 =1 才装（PROTOCOL §2.1）
            capture=os.environ.get("DOUBAO_REQUEST_CAPTURE", "0").lower()
            not in {"0", "false", "off", "no"},
        )

    def dock(
        self,
        ctx: DockContext,
        *,
        env: LocalEnv | None = None,
        channel: CdpChannel | None = None,
    ) -> DockOutcome:
        """cdp_probe 环境体检（零凭据入库）：probe 可达即过；不可达才自动拉起。"""
        env = env if env is not None else real_env()
        channel = channel if channel is not None else CdpChannel(env.resolve_port())
        try:
            channel.probe()
        except CdpError:
            issues = _ensure_running(env, channel)
            if issues:
                return DockOutcome(target=CONN_ID, issues=issues)
        account = ctx.register.execute(CONN_ID, DISPLAY)
        accounts = [account.id]
        # 多账户（ADR-003 落地）：dock 采集全部会话身份 → 写登记簿（main + others，
        # 自动切号的定位依据，ADR-007 决策 8）→ 其余身份逐一登记
        try:
            identities = read_all_identities(channel)
        except Exception:  # 身份只读辅助路径：读失败不阻断 dock 主流程（体检/登记）
            identities = []
        if identities:
            save_identity_registry(identities)
        # 当前客户端可能只有一条活跃 chat target（会话级单活跃），但登记簿里
        # 仍保留已见过的其它账户；dock 要把这些账户也登记成卡，否则用户在
        # 菜单里切过号后，卡包里会看不到第二张卡（ADR-003/ADR-007 决策 8）。
        candidates = list(identities)
        registry = load_identity_registry()
        candidates.extend(
            ActiveIdentity(sec_uid=item.sec_uid, nickname=item.nickname)
            for item in registry.others
        )
        for identity in candidates:
            if not identity.sec_uid:
                continue
            baseline = load_main_baseline()
            if baseline is None:
                continue  # 登记簿已把首个可读身份立为 main 基线（首采语义不变）
            if identity.sec_uid != baseline.sec_uid:
                key = derive_key(identity.sec_uid)
                extra = ctx.register.execute(
                    CONN_ID, identity.nickname or DISPLAY, account_key=key
                )
                if extra.id not in accounts:
                    accounts.append(extra.id)
        return DockOutcome(target=CONN_ID, accounts=accounts)


butler = _Butler()

#: 方言装载期自注册（ADR-004）：code=2 刻意不注册——换季走 UnknownEngineCode
#: → 用例层 FAILED + PROTOCOL_CHANGED（与声明式连接器同一条探测路径）。
from butler_core.shared.results import register_dialect

register_dialect(CONN_ID, {"710012001": Status.NO_AUTH, "710010702": Status.FAILED})
