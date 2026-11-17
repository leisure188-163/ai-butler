"""豆包活跃账户身份与登记簿（多账户 ADR-003 落地；ADR-007 决策 8）。

身份信号（真机取证，Windows / 豆包 2.36.8）：
- ``localStorage.for_ban_appeal_sec_user_id``：稳定加密用户 ID（account_code 派生源）
- 左下角账户 chip 按钮文本：账户昵称（display / 切号列表行匹配用）

本模块职责：**只读身份判定**（每次编排前核实客户端活跃账户，与目标
account_id 匹配才动手，绝不签错账户——A2-02 §6 红线）+ **身份登记簿**
（main 基线 + others，switch.py 会话级自动切号的定位依据，ADR-007 决策 8）。
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

from butler_connectors.cdp import CdpChannel, CdpConnection, CdpError

_IDENTITY_JS = (
    "(() => {"
    "const secUid = localStorage.getItem('for_ban_appeal_sec_user_id') || '';"
    "let nickname = '';"
    "const vh = window.innerHeight;"
    "for (const btn of document.querySelectorAll('button')) {"
    "  const r = btn.getBoundingClientRect();"
    "  if (!r.width || !r.height || r.x > 300 || r.y < vh - 80) continue;"
    "  if (!btn.querySelector('img.rounded-full')) continue;"
    "  const t = (btn.textContent || '').trim();"
    "  if (t && t.length < 30) { nickname = t; break; }"
    "}"
    "return {sec_uid: secUid, nickname: nickname};"
    "})()"
)


@dataclass(frozen=True)
class ActiveIdentity:
    """客户端当前活跃账户身份（只读取证）。"""

    sec_uid: str
    nickname: str


def read_all_identities(channel: CdpChannel) -> list[ActiveIdentity]:
    """收集全部 chat 页 target 的身份（真机实证：豆包客户端双账户会话并存于
    两个 chat target（``doubao://doubao-chat/chat`` 与带会话 id 后缀变体），
    各自 localStorage 的 sec_uid 不同，且 CDP target 顺序不稳定——单取首个
    会漂移，必须全收集。去重保序。"""
    identities: list[ActiveIdentity] = []
    seen: set[str] = set()
    for target in channel.targets():
        if "doubao-chat/chat" not in str(target.get("url")):
            continue
        conn: CdpConnection | None = None
        try:
            conn = channel.attach(target)
            value = channel.evaluate(conn, _IDENTITY_JS, wait=10)
        except CdpError:
            continue
        finally:
            if conn is not None:
                conn.close()
        if not isinstance(value, dict):
            continue
        sec_uid = str(value.get("sec_uid") or "")
        if not sec_uid or sec_uid in seen:
            continue
        seen.add(sec_uid)
        identities.append(
            ActiveIdentity(sec_uid=sec_uid, nickname=str(value.get("nickname") or ""))
        )
    return identities


def read_active_identity(channel: CdpChannel) -> ActiveIdentity | None:
    """兼容入口：取首个可读身份（顺序不稳定，新代码请用 read_all_identities）。"""
    identities = read_all_identities(channel)
    return identities[0] if identities else None


def derive_key(sec_uid: str) -> str:
    """非 main 账户的 account_code：sec_uid 派生（稳定唯一）。"""
    digest = hashlib.sha256(sec_uid.encode("utf-8")).hexdigest()[:8]
    return f"u{digest}"


def identity_path() -> Path:
    """main 身份基线缓存文件路径（DOUBAO_IDENTITY_PATH 可覆盖，测试注入）。"""
    raw = os.environ.get("DOUBAO_IDENTITY_PATH")
    return Path(raw) if raw else Path.home() / ".butler" / "doubao_identity.json"


def load_main_baseline() -> ActiveIdentity | None:
    """读 main 账户身份基线；无缓存 → None（需 dock 首采建立）。"""
    path = identity_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    sec_uid = str(data.get("main_sec_uid") or "")
    if not sec_uid:
        return None
    return ActiveIdentity(sec_uid=sec_uid, nickname=str(data.get("main_nickname") or ""))


def save_main_baseline(identity: ActiveIdentity) -> None:
    """写 main 基线（dock 首采）。写失败显式抛——基线是签到正确性的前提。"""
    path = identity_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {"main_sec_uid": identity.sec_uid, "main_nickname": identity.nickname},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


@dataclass(frozen=True)
class OtherIdentity:
    """非 main 已登记身份（登记簿条目，自动切号的定位依据）。"""

    sec_uid: str
    nickname: str
    account_code: str


@dataclass(frozen=True)
class IdentityRegistry:
    """身份登记簿：main 基线 + 其他已登记账户（dock 采集，自动切号用）。"""

    main: ActiveIdentity | None
    others: tuple[OtherIdentity, ...]


def load_identity_registry() -> IdentityRegistry:
    """读登记簿；旧形状文件（只有 main 基线）兼容——others 为空元组。"""
    path = identity_path()
    data: dict = {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            data = loaded
    except (OSError, ValueError):
        pass  # 文件缺失/坏档 → 走基线兜底（load_main_baseline 同语义）
    main_sec = str(data.get("main_sec_uid") or "")
    if main_sec:
        main = ActiveIdentity(sec_uid=main_sec, nickname=str(data.get("main_nickname") or ""))
    else:
        main = load_main_baseline()
    others: list[OtherIdentity] = []
    for item in data.get("others") or []:
        if not isinstance(item, dict):
            continue
        sec = str(item.get("sec_uid") or "")
        if not sec:
            continue
        others.append(
            OtherIdentity(
                sec_uid=sec,
                nickname=str(item.get("nickname") or ""),
                account_code=str(item.get("account_code") or derive_key(sec)),
            )
        )
    return IdentityRegistry(main=main, others=tuple(others))


def save_identity_registry(identities: list[ActiveIdentity]) -> None:
    """dock 采集后写登记簿：main = 既有基线或首个身份，其余入 others。

    读不到身份（空表）不覆盖旧簿——保留既有登记，避免采集故障抹掉定位依据。
    写失败显式抛（与 save_main_baseline 同纪律）。
    """
    if not identities:
        return
    baseline = load_main_baseline()
    main = baseline if baseline is not None else identities[0]
    # 采集到的当前会话通常只有一条（豆包会话级单活跃），不能因此丢掉
    # 已登记的其它账户：切号目标必须留在登记簿里（ADR-007 决策 8）。
    existing = {item.sec_uid: item for item in load_identity_registry().others}
    for identity in identities:
        if not identity.sec_uid or identity.sec_uid == main.sec_uid:
            continue
        existing[identity.sec_uid] = OtherIdentity(
            sec_uid=identity.sec_uid,
            nickname=identity.nickname,
            account_code=derive_key(identity.sec_uid),
        )
    others = [
        {
            "sec_uid": item.sec_uid,
            "nickname": item.nickname,
            "account_code": item.account_code,
        }
        for item in existing.values()
    ]
    path = identity_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "main_sec_uid": main.sec_uid,
                "main_nickname": main.nickname,
                "others": others,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def resolve_account_key(identity: ActiveIdentity) -> str:
    """当前活跃身份对应的 account_code：main 基线命中 → "main"，否则派生 key。"""
    baseline = load_main_baseline()
    if baseline is not None and identity.sec_uid == baseline.sec_uid:
        return "main"
    return derive_key(identity.sec_uid)
