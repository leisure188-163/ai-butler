"""豆包会话级自动切号（2026-11-17 用户裁决，修订 ADR-007 决策 7 → 决策 8）。

取证基线（2026-11-17 真机，Chrome/147，PROTOCOL §9 修订）：
- 双账户注册后头像菜单**存在切换列表**（各账户一行，文本精确等于昵称）——
  11-16「无一键切换列表」只在单账户时期成立，决策 7 的取证前提已变化
- 菜单为 Radix popper 弹层：弹层须先 ``Page.bringToFront`` 聚焦窗口
  （失焦点击不开，11-16 实证）；**指针点击对 Radix menuitem 不生效**
  （完整信任三连点在 item 精确中心仍不触发 select，四路径实证）——
  **键盘导航（ArrowDown 逐项 + 焦点文本精确校验）+ Enter 是可靠激活路径**
- 切换 = **单会话存活**语义（用户确认）：旧 chat target 消亡、新 target 承载
  新会话——激活切换项后旧连接即失效，翻转验证必须重枚举 targets 重读身份

硬边界（不自动化）：登录态过期后的重新登录（扫码/手机号）与「添加账号」
直通登录页路径——均人工参与（ADR-007 决策 8；ADR-015 失效可见可修不变）。
"""

from __future__ import annotations

import time
from collections.abc import Callable

from butler_connectors.cdp import CdpChannel, CdpError
from butler_connectors.doubao_cn.identity import (
    ActiveIdentity,
    load_main_baseline,
    load_identity_registry,
    read_all_identities,
    resolve_account_key,
)

Sleep = Callable[[float], None]
Monotonic = Callable[[], float]

_SWITCH_SETTLE_SECONDS = 1.5  # 点 chip 后等弹层动画（§6 settle 同语义）
_MENU_ATTEMPTS = 2  # chip 点击是开关切换：若弹层先前已被打开，首击会先关——两次必达
_KEY_STEPS_MAX = 14  # 菜单项焦点步数上限（设置..订阅..账户..添加账号..退出 ≈10 项）
_KEY_STEP_SETTLE = 0.15  # 每步 ArrowDown 后等焦点落定
_FLIP_POLL_INTERVAL = 2.0
_FLIP_DEADLINE_SECONDS = 45.0  # 翻转含客户端会话重载（E2E 实测可超 20s，留足余量）


class SwitchError(RuntimeError):
    """自动切号失败（chip 定位 / 焦点无法到达目标项 / 翻转超时）——调用方落 PENDING 显式指引。"""


_LOCATE_CHIP_JS = """(() => {
  const vh = window.innerHeight;
  for (const btn of document.querySelectorAll('button')) {
    const r = btn.getBoundingClientRect();
    if (!r.width || !r.height || r.x > 300 || r.y < vh - 80) continue;
    if (!btn.querySelector('img.rounded-full')) continue;
    const t = (btn.textContent || '').trim();
    if (t && t.length < 30) return {x: Math.round(r.x + r.width/2),
                                     y: Math.round(r.y + r.height/2), text: t};
  }
  return null;
})()"""

#: 菜单焦点状态：activeElement 是否为菜单项 + 其文本（截断防超长）。
#: 键盘导航每步读取一次——**仅当焦点在 menuitem 上且文本精确等于昵称时按
#: Enter**，「添加账号」/「退出登录」永不误触（比坐标点击更安全的激活方式）。
#: 注意：不查 `[role=menu]` 容器做 contains——真机实证文档内多个 open 菜单
#: 元素时 querySelector 首个匹配可能不含焦点项（2026-11-17 probe5 取证），
#: 以焦点元素自身 closest('[role=menuitem]') 判定才可靠。
_ACTIVE_ITEM_JS = """(() => {
  const el = document.activeElement;
  if (!el) return null;
  const item = el.closest ? el.closest('[role=menuitem]') : null;
  return {active: (el.textContent || '').trim().slice(0, 30),
          inMenu: !!item};
})()"""


def resolve_target_identity(key: str) -> ActiveIdentity | None:
    """account_code → 已登记身份（基线与其他账户同按 code 匹配，无 main 特判）。

    未登记 → None（自动切号无定位依据，调用方显式 PENDING 指引先 dock 登记）。
    """
    baseline = load_main_baseline()
    if baseline is not None and resolve_account_key(baseline) == key:
        return baseline
    for other in load_identity_registry().others:
        if other.account_code == key:
            return ActiveIdentity(sec_uid=other.sec_uid, nickname=other.nickname)
    return None


def switch_session(
    channel: CdpChannel,
    target: ActiveIdentity,
    *,
    sleep: Sleep = time.sleep,
    monotonic: Monotonic = time.monotonic,
) -> ActiveIdentity:
    """把客户端会话切到 target 账户并验证身份翻转（单会话存活语义）。

    编排（PROTOCOL §9 修订）：bringToFront 聚焦 → 点头像 chip 开弹层 →
    键盘导航到昵称行（焦点文本精确校验）→ Enter 激活 → 旧连接即弃（页面
    重载）→ 轮询身份翻转。失败路径显式抛 SwitchError；目标无昵称同样显式抛
    （无定位依据不猜）。
    """
    if not target.sec_uid or not target.nickname:
        raise SwitchError("目标身份缺 sec_uid/昵称（登记簿信息不足）——无法安全切号")
    chat = next(
        (t for t in channel.targets() if "doubao-chat/chat" in str(t.get("url"))), None
    )
    if chat is None:
        raise SwitchError("找不到 chat 页 target——客户端主窗口未运行")
    conn = channel.attach(chat)
    try:
        conn.call("Page.bringToFront")  # 失焦点击弹不开（11-16 实证）
        activated = False
        for _ in range(_MENU_ATTEMPTS):
            chip = channel.evaluate(conn, _LOCATE_CHIP_JS, wait=10)
            if not isinstance(chip, dict) or not chip.get("x"):
                raise SwitchError("左下角头像 chip 未定位到——客户端界面可能已改版")
            channel.click(conn, int(chip["x"]), int(chip["y"]))
            sleep(_SWITCH_SETTLE_SECONDS)
            if _focus_target_and_enter(channel, conn, target.nickname, sleep):
                activated = True
                break
            _dismiss_menu(channel, conn, sleep)  # 收起弹层，下次尝试重新打开
        if not activated:
            raise SwitchError(
                f"切换列表中无法聚焦「{target.nickname}」——账户可能未在客户端登录，或菜单未弹出"
            )
    finally:
        conn.close()  # 切换触发页面重载（单会话存活）：旧连接必失效，不复用
    return _wait_identity_flip(channel, target, sleep=sleep, monotonic=monotonic)


def _focus_target_and_enter(channel: CdpChannel, conn, nickname: str, sleep: Sleep) -> bool:
    """键盘导航到目标菜单项并 Enter 激活；焦点从未到达目标 → False。

    ArrowDown 逐项移动 Radix 焦点，每步核对 activeElement 文本；**精确等于
    昵称才按 Enter**——菜单内其他项（设置/添加账号/退出登录）零误触。
    """
    for _ in range(_KEY_STEPS_MAX):
        state = channel.evaluate(conn, _ACTIVE_ITEM_JS, wait=8)
        if isinstance(state, dict) and state.get("inMenu"):
            if state.get("active") == nickname:
                channel.key(conn, "Enter")
                sleep(_KEY_STEP_SETTLE)
                return True
        channel.key(conn, "ArrowDown")
        sleep(_KEY_STEP_SETTLE)
    return False


def _dismiss_menu(channel: CdpChannel, conn, sleep: Sleep) -> None:
    """失败收尾：点聊天区空白处收起弹层，给用户留干净界面。

    收尾失败（页面已在重载等）不掩盖主错误——SwitchError 照常抛出。
    """
    try:
        spot = channel.evaluate(
            conn,
            "({x: Math.round(window.innerWidth / 2),"
            " y: Math.round(window.innerHeight * 0.45)})",
            wait=8,
        )
        if isinstance(spot, dict) and spot.get("x"):
            channel.click(conn, int(spot["x"]), int(spot["y"]))
            sleep(0.3)
    except CdpError:
        pass


def _wait_identity_flip(
    channel: CdpChannel,
    target: ActiveIdentity,
    *,
    sleep: Sleep,
    monotonic: Monotonic,
) -> ActiveIdentity:
    """轮询身份翻转：target sec_uid 出现任一 chat target 即成功。

    翻转期间旧 target 消亡/新 target 建立，读取短暂为空属过渡态——轮询继续；
    到期仍未翻转 = 显式 SwitchError（绝不带不确定身份继续）。
    """
    deadline = monotonic() + _FLIP_DEADLINE_SECONDS
    while monotonic() < deadline:
        sleep(_FLIP_POLL_INTERVAL)
        identities = read_all_identities(channel)
        if any(i.sec_uid == target.sec_uid for i in identities):
            return ActiveIdentity(sec_uid=target.sec_uid, nickname=target.nickname)
    raise SwitchError(
        f"Enter 激活后 {_FLIP_DEADLINE_SECONDS:.0f}s 内身份未翻转到「{target.nickname}」"
        "——可能需要人工确认弹窗或会话已失效"
    )
