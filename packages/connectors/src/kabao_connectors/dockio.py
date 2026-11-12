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

from kabao_core.domain.vault import Secret

from kabao_connectors.manifest import AuthSpec, DeclarativeSpec, ManifestInvalid
from kabao_connectors.paths import expand_storage_path
from kabao_connectors.registry import ConnectorApp, DockContext, DockOutcome


def scan_storage(
    app: ConnectorApp, spec: DeclarativeSpec, kinds: tuple[str, ...], ctx: DockContext
) -> DockOutcome:
    """声明式连接器停靠：只支持 storage 型 auth（其余 kind = adapter 地盘）。"""
    auth = spec.auth
    candidates = ctx.storage_override if ctx.storage_override is not None else auth.storage
    if not candidates:
        return DockOutcome(
            target=app.manifest.id,
            issues=[f"{app.manifest.id}: 没有候选扫描路径（声明里 auth.storage 为空）"],
        )
    try:
        facts = _scan_kind(auth, app.manifest.id, candidates, kinds)
    except StorageNotFound as exc:
        return DockOutcome(target=app.manifest.id, issues=[str(exc)])
    except ManifestInvalid as exc:  # 采集器/扫描器的显式事故 → 如实出账
        return DockOutcome(target=app.manifest.id, issues=[str(exc)])

    if "_issue" in facts:
        # 主扫描出的账在这里如实落榜：不注册账号（免孤儿）、不走异常路径
        # （store 期 raise 曾逃出本函数，靠 registry 兜底成「停靠扫描异常」）
        return DockOutcome(target=app.manifest.id, issues=[facts["_issue"]])

    account = ctx.register.execute(app.manifest.id, app.display)
    _store_credentials(ctx, account.id, facts, kinds, auth.kind)
    return DockOutcome(target=app.manifest.id, accounts=[account.id])


class StorageNotFound(Exception):
    """本机没有可解锁的登录态（如实上报给 DockOutcome.issues）。"""


def _scan_kind(
    auth: AuthSpec, conn_id: str, candidates: list[str], kinds: tuple[str, ...]
) -> dict[str, str]:
    """kind 分发扫认证事实。返回 kind → Secret 源值（还没进 vault 的明文）。"""
    if auth.kind == "ss_aes":
        return _scan_ss_aes(auth, conn_id, candidates)
    if auth.kind == "dpapi_gcm_v10":
        facts = _scan_dpapi_gcm_v10(conn_id, candidates)
        if "_issue" not in facts:  # 主扫描已如实出账就不再附加采集——否则采集器的
            # 定位失败会顶掉真因（真机 mac 抓过：DPAPI 解锁失败被 umid 定位失败掩盖）
            _collect_extra_kinds(facts, conn_id, candidates, kinds)
        return facts
    raise ManifestInvalid(f"{conn_id}: dock 扫描器不支持凭据 kind {auth.kind!r}")


# --- dpapi_gcm_v10（qoder_cn）：glob 数据目录 → 自包含信封（ADR-004）---


def _scan_dpapi_gcm_v10(conn_id: str, candidates: list[str]) -> dict[str, str]:
    """Qoder 数据目录（glob）：auth.v1.dat + Local State → 自包含信封。

    信封自包含（dat + key_b64，unlock.session_from_dpapi_gcm_v10 解链），
    运行时解锁不再依赖本机文件布局；解码一次只为验形 + 取 expiresAt 元数据，
    明文即刻丢弃，入库的是信封原文。
    """
    from kabao_connectors.unlock import session_from_dpapi_gcm_v10

    for pattern in candidates:
        base = expand_storage_path(pattern)
        if base is None:
            continue  # 平台不适用：换下一个候选
        for data_dir in _glob_dirs(base):
            dat = data_dir / "auth.v1.dat"
            state = data_dir / "Local State"
            if not (dat.is_file() and state.is_file()):
                continue
            try:
                envelope = _dpapi_envelope(dat, state)
                session = session_from_dpapi_gcm_v10(envelope)  # 形状校验（明文即丢）
            except (OSError, ValueError, RuntimeError) as exc:
                import sys

                tail = (
                    "重新登录不解决——mac 解锁分支待取证，导入暂不可用"
                    if sys.platform == "darwin"
                    else "请在桌面端重新登录后重扫"
                )
                return {"_issue": f"{data_dir}: 登录态解不开（{exc}）——{tail}"}
            facts = {"dpapi_gcm_v10": envelope, "_auth_dir": str(data_dir)}
            expires = session.get("expiresAt")
            if isinstance(expires, str) and expires:
                facts["_expires"] = expires
            return facts
    raise StorageNotFound(
        f"{conn_id}: 未发现可解锁登录态（候选: {candidates}）——"
        "安装桌面端并登录一次后重扫"
    )


def _glob_dirs(base: Path) -> list[Path]:
    """候选末段含通配 = 目录 glob（按名排序稳定）；否则视为目录本身。"""
    if "*" in str(base) or "?" in str(base):
        return sorted(p for p in base.parent.glob(base.name) if p.is_dir())
    return [base] if base.is_dir() else []


def _dpapi_envelope(dat: Path, state: Path) -> str:
    """组自包含信封：base64(JSON{dat: b64(文件字节), key_b64: Local State 原文})。"""
    import base64
    import json

    try:
        state_data = json.loads(state.read_text(encoding="utf-8"))
        key_b64 = state_data["os_crypt"]["encrypted_key"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ValueError(f"Local State 形状不符: {exc}") from exc
    if not isinstance(key_b64, str) or not key_b64:
        raise ValueError("Local State 缺 os_crypt.encrypted_key")
    payload = {
        "dat": base64.b64encode(dat.read_bytes()).decode("ascii"),
        "key_b64": key_b64,
    }
    return base64.b64encode(
        json.dumps(payload, separators=(",", ":")).encode("utf-8")
    ).decode("ascii")


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
    绝不退回"普通请求"（旧系统缺头静默空列表的陷阱，ADR-004 §4 显式化）。
    """
    import base64
    import json

    exe = _locate_umid()
    if exe is None:
        import sys

        order = (
            "QODER_UMID_EXE 环境变量 → /Applications（或 ~/Applications）下的 Qoder.app"
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

_UMID_REL_WIN = ("resources", "umid", "runtime-info.exe")
_UMID_REL_MAC = ("Contents", "Resources", "umid", "runtime-info")
#: mac 应用查找根（~/Applications 兜用户级安装）；2026-11-12 本机取证：
#/Applications/Qoder.app/Contents/Resources/umid/runtime-info 存在且可运行
_MAC_APP_ROOTS = ("/Applications", "~/Applications")
_MAC_APP_NAMES = ("Qoder.app", "Qoder CN.app")


def _locate_umid():
    """runtime-info 定位：环境覆盖 → 平台默认位置（win: 常见目录+卸载注册表；mac: .app 束）。"""
    import os
    import sys

    override = os.environ.get("QODER_UMID_EXE")
    if override:
        path = Path(override).expanduser()
        if path.is_file():
            return path
    roots: list[Path] = []
    rel = _UMID_REL_WIN
    if sys.platform == "darwin":
        rel = _UMID_REL_MAC
        roots.extend(
            Path(os.path.expanduser(base)) / name
            for base in _MAC_APP_ROOTS
            for name in _MAC_APP_NAMES
        )
    else:
        for var in ("LOCALAPPDATA", "ProgramFiles", "ProgramFiles(x86)"):
            base = os.environ.get(var)
            if base:
                roots.extend(Path(base) / name for name in ("Qoder CN", "Qoder"))
        roots.extend(_registry_install_roots())
    for root in roots:
        candidate = root.joinpath(*rel)
        if candidate.is_file():
            return candidate
    return None


def _registry_install_roots() -> list[Path]:
    """卸载注册表 Qoder* 条目：InstallLocation 优先，DisplayIcon 所在目录兜底。

    （2026-11-11 真机取证：本机 InstallLocation 为空，DisplayIcon 给出安装目录。）
    """
    try:
        import winreg
    except ImportError:  # 非 Windows：mac 分支待真机取证（M1 暂缓）
        return []
    roots: list[Path] = []
    hives = [
        (winreg.HKEY_CURRENT_USER, 0),
        (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_32KEY),
        (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_64KEY),
    ]
    for hive, flag in hives:
        try:
            key = winreg.OpenKey(
                hive,
                r"Software\Microsoft\Windows\CurrentVersion\Uninstall",
                0,
                winreg.KEY_READ | flag,
            )
        except OSError:
            continue
        with key:
            index = 0
            while True:
                try:
                    sub = winreg.EnumKey(key, index)
                    index += 1
                except OSError:
                    break
                try:
                    with winreg.OpenKey(key, sub) as entry:
                        try:
                            display, _ = winreg.QueryValueEx(entry, "DisplayName")
                        except OSError:
                            continue  # 无 DisplayName 的系统组件条目，跳过
                        if "Qoder" not in str(display):
                            continue
                        # 2026-11-11 真机取证：子键常为 GUID 型且 InstallLocation
                        # 值缺失——每个值独立容错，缺值换下一个（整键吞错曾让
                        # DisplayIcon 兜底永远轮不到，真机定位落空）
                        for name in ("InstallLocation", "DisplayIcon"):
                            try:
                                value, _ = winreg.QueryValueEx(entry, name)
                            except OSError:
                                continue  # 该值缺失：试下一个
                            if isinstance(value, str) and value.strip():
                                root = Path(value.split(",")[0].strip())
                                if root.suffix:  # DisplayIcon 指向 .ico → 取所在目录
                                    root = root.parent
                                if str(root) and root.is_dir() and root not in roots:
                                    roots.append(root)
                                break
                except OSError:
                    continue
    return roots


def _run_runtime_info(exe) -> dict:
    """无参运行官方组件（2026-11-11 取证：--account-stdin 报 invalid_input，用无参）。"""
    import subprocess

    proc = subprocess.run(
        [str(exe)], capture_output=True, timeout=15, cwd=str(exe.parent)
    )
    for line in reversed(proc.stdout.decode("utf-8", "replace").splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except ValueError:
            continue
        if isinstance(data, dict):
            return data
    raise ManifestInvalid(
        f"runtime-info 输出解析失败（exit={proc.returncode}）——组件输出形状已变?"
    )


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


def _client_version(exe) -> str:
    """Cosy-Version 来源：安装根 build-manifest.json 的 productVersion（取证 risk.py）。"""
    try:
        manifest = json.loads(
            (exe.parent.parent / "build-manifest.json").read_text(encoding="utf-8")
        )
    except (OSError, ValueError):
        return ""
    version = manifest.get("productVersion")
    return str(version) if version else ""


def _machine_os() -> str:
    """Cosy-MachineOS：客户端 SDK 口径（取证 risk.py）——``{arch}_windows``。"""
    import platform
    import sys

    machine = platform.machine().lower()
    arch = {"amd64": "x86_64", "x86_64": "x86_64", "aarch64": "aarch64", "arm64": "aarch64"}.get(
        machine, machine
    )
    if sys.platform == "darwin":  # mac 解锁分支暂缓，OS 口径先对齐备查
        return f"{'arm64' if arch == 'aarch64' else 'x64'}_darwin"
    return f"{arch}_windows"


def _hostname() -> str:
    import socket

    return socket.gethostname()


def _scan_ss_aes(auth: AuthSpec, conn_id: str, candidates: list[str]) -> dict[str, str]:
    """Trae CN storage.json：信封(base64) + 键名里的 Aha 数字设备号。"""
    from kabao_connectors.ssaes import decode_stored, open_envelope

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
        expires = _expires_for(kind, value) if kind == main_kind else None
        ctx.vault.store(account_id, kind, Secret(value), expires_at=expires)


def _expires_for(kind: str, value: str):
    """主凭据有效期：ss_aes = JWT exp；dpapi_gcm_v10 = 会话 expiresAt（ISO）。"""
    from datetime import UTC, datetime

    from kabao_connectors._jwt import jwt_exp
    from kabao_connectors.unlock import session_from_dpapi_gcm_v10

    try:
        if kind == "ss_aes":
            from kabao_connectors.ssaes import decode_stored, open_envelope

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
    except (ValueError, RuntimeError):
        return None  # 扫描阶段已形状校验过；此处失败只是有效期未知——如实
    return None
