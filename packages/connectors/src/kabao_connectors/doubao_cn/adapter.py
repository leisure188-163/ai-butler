"""doubao_cn 连接器（ADR-005）：CDP 界面通道端口实现——豆包专属的只有编排。

- registry adapter 契约（registry._load_entry）：``adapter.kabao`` 提供
  build_port / dock 两钩子；vault 参数保留（契约签名）但零凭据设计不使用
- 编排（PROTOCOL §3 判定表）：probe → 版本派生 → 活动页 → Cookie 现取 →
  detail 权威判定 →（未签）界面受信任点击 → 复查；PENDING = 客户端不可达（暂态）
- 方言装载期自注册（ADR-002）：code=2 刻意不注册——未知码 → UnknownEngineCode
  → 用例层统一 FAILED + PROTOCOL_CHANGED（活动换季探测）
- CDP 原语在 cdp.py（通用）；本机环境在 localenv.py（doubao 专属）
"""

from __future__ import annotations

import json
import time
from datetime import datetime

from kabao_core.application.ports import (
    Capabilities,
    ProvisionPort,
    ProvisionRequest,
)
from kabao_core.domain.results import Status, from_engine
from kabao_core.domain.run import Evidence, RepairHint, RunResult

from kabao_connectors.cdp import (
    CdpChannel,
    CdpConnection,
    CdpError,
    pick_activity_target,
)
from kabao_connectors.doubao_cn.localenv import LocalEnv, real_env, version_code
from kabao_connectors.registry import DockContext, DockOutcome
from kabao_connectors.transport import HttpRequest, TransportError, httpx_transport

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

#: 签到按钮文案精确匹配（PROTOCOL §6 ①：模糊匹配会误点"签到领额度"类标题）。
_BUTTON_TEXTS = ("立即签到", "今日签到", "签到")

#: 找按钮 + 滚动扫找 + 中心坐标（语义 = PROTOCOL §6 ①②③，页面契约非代码搬运）。
_FIND_CLICK_JS = """
(() => {
  const want = %s;
  const pick = () => [...document.querySelectorAll('*')].find(el =>
      el.children.length <= 2 &&
      want.includes((el.textContent || '').trim()) &&
      getComputedStyle(el).pointerEvents !== 'none');
  let el = pick();
  if (!el) {
    const step = Math.round(window.innerHeight * 0.7);
    for (let pos = 0; pos <= document.body.scrollHeight; pos += step) {
      window.scrollTo(0, pos);
      el = pick();
      if (el) break;
    }
  }
  if (!el) return null;
  el.scrollIntoView({block: 'center'});
  const r = el.getBoundingClientRect();
  if (r.width <= 0 || r.height <= 0) return null;
  return {x: Math.round(r.x + r.width / 2), y: Math.round(r.y + r.height / 2),
          text: (el.textContent || '').trim()};
})()
""" % json.dumps(list(_BUTTON_TEXTS))

#: 找不到按钮时的页面诊断摘要（脱敏：纯文本，且只取前段）。
_PAGE_TEXT_JS = "document.body.innerText.slice(0, 300)"

_SETTLE_SECONDS = 3.0  # 点击后等客户端 SDK 发完请求（PROTOCOL §6 ⑤）
_FIND_RETRIES = 3  # 活动页可能还在加载（PROTOCOL §6 ⑥）


def _daily_checkin(payload: dict) -> dict | None:
    """detail 判定字段路径（PROTOCOL §2）：data.tasks[campaign_code=daily_signin]。"""
    for task in (payload.get("data") or {}).get("tasks") or []:
        if task.get("campaign_code") == "daily_signin":
            return task.get("daily_checkin") or {}
    return None


def _failed(summary: str, *, raw_code: str | None = None) -> RunResult:
    return RunResult(Status.FAILED, evidence=(Evidence(summary, raw_code=raw_code),))


def _pending(summary: str) -> RunResult:
    return RunResult(
        Status.PENDING,
        evidence=(Evidence(summary),),
        repair_hint=RepairHint("豆包客户端未带调试端口运行（暂态，不算失败）", "dock"),
    )


class DoubaoCdpProvisionPort(ProvisionPort):
    """豆包签到端口：detail 权威判定 + 界面受信任点击；dry_run 只查不点。

    PENDING = 客户端调试端口不可达（暂态，dock 可自动拉起）；除 PENDING 外
    全部按 PROTOCOL §3 判定表显式落状态，绝不静默兜底（红线 5）。
    """

    def __init__(
        self, *, transport, env: LocalEnv, channel: CdpChannel, sleep=time.sleep
    ) -> None:
        self.transport = transport
        self.env = env
        self.channel = channel
        self.sleep = sleep

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
        try:
            conn = self._activity_conn()
        except CdpError as exc:
            return _failed(f"活动页不可用（{exc}）——建页失败属协议事故，绝不静默")
        try:
            # 编排全程在连接存活期内（finally 才关）：点击与复查都在 close 之前
            return self._orchestrate(conn, req, version=version, vcode=vcode)
        finally:
            conn.close()

    # --- 编排步骤 ---

    def _orchestrate(
        self, conn: CdpConnection, req: ProvisionRequest, *, version: str, vcode: int
    ) -> RunResult:
        try:
            cookie_header = self._cookie_header(conn)
        except CdpError as exc:
            return _failed(f"CDP 取 Cookie 失败（{exc}）")
        try:
            payload = self._detail(cookie_header, vcode, version, req.deadline)
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
            conn, cookie_header, vcode, version, req.deadline, code
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
        self, cookie_header: str, vcode: int, version: str, deadline: datetime
    ) -> dict:
        """detail 只读查询（M1 唯一裸 HTTP 接口，PROTOCOL §2 契约形状）。"""
        query = "&".join((f"version_code={vcode}", *_COMMON_QUERY))
        response = self.transport(
            HttpRequest(
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
            ),
            deadline=deadline,
        )
        if not response.ok:
            raise TransportError(f"HTTP {response.status_code}")
        payload = response.payload
        return payload if isinstance(payload, dict) else {}

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
        try:
            self.channel.click(conn, int(box["x"]), int(box["y"]))
        except CdpError as exc:
            return _failed(f"界面点击失败: {exc}", raw_code=raw_code)
        self.sleep(_SETTLE_SECONDS)
        try:
            payload = self._detail(cookie_header, vcode, version, deadline)
        except TransportError as exc:
            return _failed(f"点击后复查 detail 失败: {exc}", raw_code=raw_code)
        checkin = _daily_checkin(payload)
        text = str(box.get("text") or "")
        if checkin is not None and checkin.get("checked_in_today"):
            amount = (checkin.get("reward") or {}).get("reward_amount")
            return RunResult(
                Status.CLAIMED,
                evidence=(
                    Evidence(
                        f"界面点击「{text}」后复查已签：+{amount} 额度"
                        f"（连签 {checkin.get('continuous_days')} 天）",
                        raw_code=raw_code,
                    ),
                ),
            )
        return _failed(
            f"已在客户端界面点击「{text}」但复查仍未签——服务端/账号侧异常，"
            "可手工点一次确认",
            raw_code=raw_code,
        )


# --- registry adapter 钩子面与停靠 ---

def _ensure_running(env: LocalEnv, channel: CdpChannel) -> list[str]:
    """杀无端口实例 → 带端口重启 → 轮询就绪（ADR-005 决策 5；仅显式 dock 触发，
    调度触发的 run() 绝不杀进程——不可达即 PENDING）。"""
    exe = env.locate_exe()
    if exe is None:
        import sys

        if sys.platform == "darwin":
            return [
                f"{CONN_ID}: 调试端口不可达——mac 分支未实现自动拉起。手动带 "
                "--remote-debugging-port 启动豆包客户端后重扫（probe 可达即全链可用；"
                "或用 DOUBAO_EXE 指定客户端主程序走自动拉起，mac 路径待取证）"
            ]
        return [
            f"{CONN_ID}: 调试端口不可达且未定位到客户端 exe——手动带 "
            "--remote-debugging-port 启动豆包后重扫"
        ]
    for pid in env.process_pids():
        env.kill_pid(pid)  # probe 已失败 = 端口没开，现存实例都是无端口实例
    env.spawn_detached(exe)
    for _ in range(10):  # ~15s 轮询就绪
        env.sleep(1.5)
        try:
            channel.probe()
            return []
        except CdpError:
            continue
    return [f"{CONN_ID}: 客户端已带调试端口拉起但 probe 超时未就绪——稍后重扫"]


class _Kabao:
    """registry adapter 钩子面：entry = ``adapter.kabao``（registry._load_entry）。"""

    def build_port(
        self,
        *,
        vault,
        transport=None,
        env: LocalEnv | None = None,
        channel: CdpChannel | None = None,
    ) -> DoubaoCdpProvisionPort:
        # vault 参数保留（registry 契约签名）；零凭据设计不使用（ADR-005 决策 2）
        env = env if env is not None else real_env()
        return DoubaoCdpProvisionPort(
            transport=transport if transport is not None else httpx_transport(),
            env=env,
            channel=channel if channel is not None else CdpChannel(env.resolve_port()),
            sleep=env.sleep,  # 重试/落定间隔走环境束：测试假束离线、真机 time.sleep
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
        return DockOutcome(target=CONN_ID, accounts=[account.id])


kabao = _Kabao()

#: 方言装载期自注册（ADR-002）：code=2 刻意不注册——换季走 UnknownEngineCode
#: → 用例层 FAILED + PROTOCOL_CHANGED（与声明式连接器同一条探测路径）。
from kabao_core.domain.results import register_dialect  # noqa: E402

register_dialect(CONN_ID, {"710012001": Status.NO_AUTH, "710010702": Status.FAILED})
