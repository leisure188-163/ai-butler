"""接入扫描（dock）：本机凭据存储发现 → 账号注册 → 凭据入库（最小 kinds）。

- 扫描器按 auth.kind 分发（与 unlock 同构：kind 决定"怎么读怎么解"）；
  未知 kind 显式报错（红线 5）
- 扫到的登录态**解码一次**只为两件事：验协议形状 + 取有效期元数据
  （JWT exp → vault.expires_at）；明文即刻丢弃，入库的是原始密文信封
- 找不到存储 / 键 / 字段 = DockOutcome.issues（如实，不静默编造）
"""

from __future__ import annotations

import json
from pathlib import Path

from butler_core.accounts.domain import Secret

from butler_connectors.dock_storage import dpapi_envelope, glob_dirs, mac_envelope
from butler_connectors.manifest import AuthSpec, DeclarativeSpec, ManifestInvalid
from butler_connectors.paths import expand_storage_path
from butler_connectors.qoder_identity import qoder_display, qoder_main_identity, qoder_region
from butler_connectors.qoder_runtime import (
    MAC_APP_NAMES as _MAC_APP_NAMES,
    MAC_APP_ROOTS as _MAC_APP_ROOTS,
    UMID_REL_MAC as _UMID_REL_MAC,
    UMID_REL_WIN as _UMID_REL_WIN,
    client_version as _client_version,
    hostname as _hostname,
    locate_umid as _locate_umid_impl,
    machine_os as _machine_os,
    region_versions as _region_versions,
    registry_install_roots as _registry_install_roots,
    run_runtime_info as _run_runtime_info,
)
from butler_connectors.registry import ConnectorPlatform, DockContext, DockOutcome

#: 兼容旧模块内调用名（本文件只用别名，不复制实现）。
_glob_dirs = glob_dirs
_dpapi_envelope = dpapi_envelope
_mac_envelope = mac_envelope


def scan_storage(
    platform: ConnectorPlatform, spec: DeclarativeSpec, kinds: tuple[str, ...], ctx: DockContext
) -> DockOutcome:
    """声明式连接器停靠：只支持 storage 型 auth（其余 kind = adapter 地盘）。"""
    auth = spec.auth
    candidates = ctx.storage_override if ctx.storage_override is not None else auth.storage
    if not candidates:
        return DockOutcome(
            target=platform.manifest.id,
            issues=[f"{platform.manifest.id}: 没有候选扫描路径（声明里 auth.storage 为空）"],
        )
    try:
        facts_list = _scan_kind(
            auth,
            platform.manifest.id,
            candidates,
            kinds,
            existing_main_identity=qoder_main_identity(ctx, platform.manifest.id),
        )
    except StorageNotFound as exc:
        return DockOutcome(target=platform.manifest.id, issues=[str(exc)])
    except ManifestInvalid as exc:  # 采集器/扫描器的显式事故 → 如实出账
        return DockOutcome(target=platform.manifest.id, issues=[str(exc)])

    accounts: list[str] = []
    issues: list[str] = []
    for facts in facts_list:
        if "_issue" in facts:
            # 主扫描出的账在这里如实落榜：不注册账号（免孤儿）、不走异常路径
            # （store 期 raise 曾逃出本函数，靠 registry 兜底成「停靠扫描异常」）
            issues.append(facts["_issue"])
            continue
        account = ctx.register.execute(
            platform.manifest.id,
            facts.get("_display") or platform.display,
            account_code=facts.get("_account_key", "main"),
        )
        _store_credentials(
            ctx, account.id, facts, kinds, auth.kind,
            main_cookie_names=tuple(auth.cookies),
        )
        accounts.append(account.id)
    return DockOutcome(target=platform.manifest.id, accounts=accounts, issues=issues)


class StorageNotFound(Exception):
    """本机没有可解锁的登录态（如实上报给 DockOutcome.issues）。"""


def _scan_kind(
    auth: AuthSpec,
    conn_id: str,
    candidates: list[str],
    kinds: tuple[str, ...],
    *,
    existing_main_identity: str | None = None,
) -> list[dict[str, str]]:
    """kind 分发扫认证事实。返回每个 profile 的 kind → Secret 源值（还没进 vault）。

    多 profile 只在 dpapi_gcm_v10 落地（Qoder CN/Global 双数据目录）；其余
    storage kind 仍返回单元素列表，保持既有单账号语义。
    """
    if auth.kind == "ss_aes":
        return [_scan_ss_aes(auth, conn_id, candidates)]
    if auth.kind == "dpapi_gcm_v10":
        profiles = _scan_dpapi_gcm_v10(
            conn_id, candidates, existing_main_identity=existing_main_identity
        )
        good = [facts for facts in profiles if "_issue" not in facts]
        if good:
            # 机器身份是同一台机器的共享头组：只采集一次，再复制给其余 profile。
            _collect_extra_kinds(good[0], conn_id, candidates, kinds)
            for facts in good[1:]:
                for kind in kinds:
                    if kind in good[0] and kind not in facts:
                        facts[kind] = good[0][kind]
        return profiles
    raise ManifestInvalid(f"{conn_id}: dock 扫描器不支持凭据 kind {auth.kind!r}")


# --- dpapi_gcm_v10（qoder_cn）：glob 数据目录 → 自包含信封（ADR-006）---


def _scan_dpapi_gcm_v10(
    conn_id: str,
    candidates: list[str],
    *,
    existing_main_identity: str | None = None,
) -> list[dict[str, str]]:
    """Qoder 数据目录（glob）：逐目录扫描 auth.v1.dat，返回每账户一份 facts。

    Windows 信封自包含（dat + key_b64，unlock.session_from_dpapi_gcm_v10 解链），
    运行时解锁不再依赖本机文件布局；mac 信封只带 dat——钥匙在 Keychain
    （"Qoder Platform Safe Storage"），解锁时现取（ADR-008 决策 3：现用现取，密钥不入 vault）。
    解码一次只为验形 + 取 expiresAt/user 元数据，明文即刻丢弃，入库的是信封原文。

    多账户身份锚点：同一 user id 只保留首份登录态；Qoder CN 首账户沿用
    account_code=main 兼容存量卡。已有 :main 卡时，只有同一 user id 才能继续
    使用 main；切换后的新 CN 账户用 cn-<hash> 新增，绝不覆盖旧主卡。Qoder
    Global 与额外 CN profile 用稳定 hash key。同一产品域内多个 CN profile 仍
    以数据目录为单位，不解析 auth-profile-overlays。
    """
    import hashlib
    import sys

    from butler_connectors.unlock import session_from_dpapi_gcm_v10

    profiles: list[dict[str, str]] = []
    seen_dirs: set[Path] = set()
    seen_users: dict[str, Path] = {}
    used_main = False
    for pattern in candidates:
        base = expand_storage_path(pattern)
        if base is None:
            continue  # 平台不适用：换下一个候选
        for data_dir in _glob_dirs(base):
            resolved = data_dir.resolve()
            if resolved in seen_dirs:
                continue  # 候选 glob 重叠（com.qoder.platform* 会覆盖同一目录）
            seen_dirs.add(resolved)
            dat = data_dir / "auth.v1.dat"
            if not dat.is_file():
                continue
            try:
                if sys.platform == "darwin":
                    envelope = _mac_envelope(dat)
                else:
                    state = data_dir / "Local State"
                    if not state.is_file():
                        continue
                    envelope = _dpapi_envelope(dat, state)
                session = session_from_dpapi_gcm_v10(envelope)  # 形状校验（明文即丢）
            except (OSError, ValueError, RuntimeError) as exc:
                tail = (
                    # mac 钥匙在 Keychain：登录态文件在而解锁失败 → 钥匙侧问题
                    "mac 钥匙在 Keychain（Qoder Platform Safe Storage）——确认客户端"
                    "登录过一次、未拒绝 Keychain 访问后重扫"
                    if sys.platform == "darwin"
                    else "请在桌面端重新登录后重扫"
                )
                profiles.append(
                    {"_issue": f"{data_dir}: 登录态解不开（{exc}）——{tail}"}
                )
                continue

            user = session.get("user") if isinstance(session.get("user"), dict) else {}
            identity = str(user.get("id") or "")
            if identity:
                previous = seen_users.get(identity)
                if previous is not None:
                    profiles.append(
                        {
                            "_issue": (
                                f"{data_dir}: 与 {previous} 是同一 user id（{identity}），"
                                "跳过重复登录态"
                            )
                        }
                    )
                    continue
                seen_users[identity] = data_dir

            region = qoder_region(session, data_dir, sys.platform)
            if region == "cn" and (
                (identity and identity == existing_main_identity)
                or (existing_main_identity is None and not used_main)
            ):
                account_code = "main"  # 兼容存量 qoder_cn:main
                used_main = True
            else:
                suffix = hashlib.sha1(
                    (identity or str(resolved)).encode("utf-8")
                ).hexdigest()[:8]
                account_code = f"{region}-{suffix}"

            facts = {
                "dpapi_gcm_v10": envelope,
                "_auth_dir": str(data_dir),
                "_account_key": account_code,
                "_display": qoder_display(region, user),
                "_region": region,
            }
            expires = session.get("expiresAt")
            if isinstance(expires, str) and expires:
                facts["_expires"] = expires
            profiles.append(facts)

    if not profiles:
        raise StorageNotFound(
            f"{conn_id}: 未发现可解锁登录态（候选: {candidates}）——"
            "安装桌面端并登录一次后重扫"
        )
    return profiles


# --- 附加 kind 采集器（kind 驱动注册表，A2-02 §3：特殊以 kind 形态扩展）---

_COLLECTORS: dict[str, object] = {}


def _collect_extra_kinds(
    facts: dict[str, str], conn_id: str, candidates: list[str], kinds: tuple[str, ...]
) -> None:
    """主扫描不产、manifest 申报了的 kind → 逐个跑采集器（缺采集器在上游显式报）。"""
    for kind in kinds:
        if kind in facts:
            continue
        collector = _COLLECTORS.get(kind)
        if collector is not None:
            facts.update(collector(conn_id, facts, candidates))


def _collect_umid_cosy(
    conn_id: str, facts: dict[str, str], candidates: list[str]
) -> dict[str, str]:
    """Cosy 机器身份头组采集（kind=umid_cosy）：跑客户端自带 runtime-info 组件。

    标识不编造（PROTOCOL qoder_cn §1）；找不到组件/字段不齐 = 显式爆——
    绝不退回"普通请求"（旧系统缺头静默空列表的陷阱，ADR-006 §4 显式化）。
    """
    import base64
    import json

    exe = _locate_umid()
    if exe is None:
        import sys

        order = (
            "QODER_UMID_EXE 环境变量 → /Applications（或 ~/Applications）下的 "
            "Qoder.app / Qoder CN.app（.platform 旧形态亦兼容）"
            if sys.platform == "darwin"
            else "QODER_UMID_EXE 环境变量 → 常见安装目录 → 卸载注册表"
        )
        raise ManifestInvalid(
            f"{conn_id}: 未定位到客户端 runtime-info 组件（定位顺序: {order}）"
            "——确认桌面客户端已安装后重扫"
        )
    identity = _run_runtime_info(exe)
    payload = {
        "cosy_machine_token": str(identity.get("machineToken", "") or ""),
        "cosy_machine_code": str(identity.get("machineCode", "") or ""),
        "cosy_machine_type": str(identity.get("machineType", "") or ""),
        "cosy_machine_id": _read_machine_id(facts, candidates),
        "cosy_machine_os": _machine_os(),
        "cosy_machine_hostname": _hostname(),
        "cosy_version": _client_version(exe),
    }
    # 双客户端分区（2026-11-19）：同一台机器装了 Qoder/Koder CN 两套时，各账户的
    # Cosy-Version 应与其产品域的真实客户端一致（decl_auth 按账户域取 cosy_version_<region>）
    for region, version in _region_versions().items():
        if version:
            payload[f"cosy_version_{region}"] = version
    missing = sorted(k for k, v in payload.items() if not v)
    if missing:
        raise ManifestInvalid(
            f"{conn_id}: 机器身份采集不完整（缺 {missing}）——runtime-info 输出或"
            "数据目录形状已变（PROTOCOL qoder_cn §6），排查后重扫"
        )
    value = base64.b64encode(
        json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).decode("ascii")
    return {"umid_cosy": value}


_COLLECTORS["umid_cosy"] = _collect_umid_cosy

#: Qoder runtime 探针实现见 qoder_runtime（2026-11-19 拆分，conventions/4 §2.2）——
#: 同名薄包装保持测试 monkeypatch 面不变（_MAC_APP_ROOTS/_MAC_APP_NAMES 走参数传入）。


def _locate_umid():
    """runtime-info 定位：环境覆盖 → 平台默认位置（实现见 qoder_runtime）。"""
    return _locate_umid_impl(roots=_MAC_APP_ROOTS, names=_MAC_APP_NAMES)


def _read_machine_id(facts: dict[str, str], candidates: list[str]) -> str:
    """auth.machine-id：优先登录态所在数据目录，其余候选目录兜底。"""
    dirs: list[Path] = []
    auth_dir = facts.get("_auth_dir")
    if auth_dir:
        dirs.append(Path(auth_dir))
    for pattern in candidates:
        base = expand_storage_path(pattern)
        if base is not None:
            dirs.extend(_glob_dirs(base))
    for data_dir in dirs:
        try:
            value = (data_dir / "auth.machine-id").read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if value:
            return value
    return ""




def _scan_ss_aes(auth: AuthSpec, conn_id: str, candidates: list[str]) -> dict[str, str]:
    """Trae CN storage.json：信封(base64) + 键名里的 Aha 数字设备号。"""
    from butler_connectors.ssaes import decode_stored, open_envelope

    facts: dict[str, str] = {}
    for raw in candidates:
        path = expand_storage_path(raw)
        if path is None or not path.is_file():
            continue  # 平台不适用 / 候选不存在：换下一个（全落空在上游如实上报）
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue  # 文件不可读/非 JSON：换下一个候选（设备重命名等情况）
        envelope, device_dn = _extract_ss_aes(data, conn_id)
        if envelope is None:
            continue
        try:
            open_envelope(decode_stored(envelope))  # 形状校验（明文即丢）
        except (ValueError, RuntimeError) as exc:
            facts["_issue"] = f"登录态信封解不开（{exc}）——请在桌面端重新登录后重扫"
            return facts
        facts["ss_aes"] = envelope
        if device_dn:
            facts["device_dn"] = device_dn
        return facts
    if not facts:
        raise StorageNotFound(
            f"{conn_id}: 未发现可解锁登录态（候选: {candidates}）——"
            "安装桌面端并登录一次后重扫"
        )
    return facts


_STORAGE_KEY = "iCubeAuthInfo://icube.cloudide"
_AHA_PREFIX = "iCubeAuthInfo://icube-dc:"
#: 候选键：优先认证信封键；键名缺省时宽容到任意 iCubeAuthInfo:// 键（取证结论）
_ANY_AUTH_PREFIX = "iCubeAuthInfo://"


def _extract_ss_aes(storage: dict, conn_id: str) -> tuple[str | None, str | None]:
    if not isinstance(storage, dict):
        return None, None
    value = storage.get(_STORAGE_KEY)
    if not isinstance(value, str) or not value:
        value = next(
            (
                v
                for k, v in storage.items()
                if k.startswith(_ANY_AUTH_PREFIX)
                and not k.startswith(_AHA_PREFIX)
                and isinstance(v, str)
            ),
            None,
        )
    device = None
    for k in storage:
        if not k.startswith(_AHA_PREFIX):
            continue
        digits = k[len(_AHA_PREFIX) :].strip()
        if digits.isdigit() and 8 <= len(digits) <= 20:
            device = digits
            break
    return value, device


def _store_credentials(
    ctx: DockContext,
    account_id: str,
    facts: dict[str, str],
    kinds: tuple[str, ...],
    main_kind: str,
    *,
    main_cookie_names: tuple[str, ...] = (),
) -> None:
    """凭据入库：只入 manifest 申报的 kinds（最小授权），先校验后入库。"""
    scanned = {k for k in facts if not k.startswith("_")}
    missing = [k for k in kinds if k not in scanned]
    if missing:
        # 半套凭据照样领不动（设备号缺失会导致领取 9004）——不静默入库半套（红线 5）
        raise ManifestInvalid(
            f"{account_id}: 扫描未取得申报凭据 kind={missing}"
        )
    for kind in kinds:
        value = facts[kind]
        expires = (
            _expires_for(kind, value, cookie_names=main_cookie_names)
            if kind == main_kind
            else None
        )
        ctx.vault.store(account_id, kind, Secret(value), expires_at=expires)


def _expires_for(kind: str, value: str, *, cookie_names: tuple[str, ...] = ()):
    """主凭据有效期：ss_aes = JWT exp；dpapi_gcm_v10 = 会话 expiresAt（ISO）；
    browser_cookie = **必需名单内**各 cookie 最早者（A2-03 §1）——信封里的
    其它短命 cookie（__cf_bm 等）不参与，避免把仍有会话的账号误判 expired。"""
    import json
    from datetime import UTC, datetime

    from butler_connectors._jwt import jwt_exp
    from butler_connectors.unlock import session_from_dpapi_gcm_v10

    try:
        if kind == "ss_aes":
            from butler_connectors.ssaes import decode_stored, open_envelope

            info = open_envelope(decode_stored(value))
            token = info.get("token")
            if isinstance(token, str) and token:
                return jwt_exp(token)
            return None
        if kind == "dpapi_gcm_v10":
            session = session_from_dpapi_gcm_v10(value)
            raw = session.get("expiresAt")
            if isinstance(raw, str) and raw:
                parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
            return None
        if kind == "browser_cookie":
            envelope = json.loads(value)
            items = [
                item for item in envelope.get("cookies", [])
                if isinstance(item, dict)
            ]
            if cookie_names:
                names = set(cookie_names)
                items = [item for item in items if item.get("name") in names]
            dates = [
                datetime.fromisoformat(item["expires_at"])
                for item in items
                if item.get("expires_at")
            ]
            return min(dates) if dates else None
    except (ValueError, RuntimeError):
        return None  # 扫描阶段已形状校验过；此处失败只是有效期未知——如实
    return None
