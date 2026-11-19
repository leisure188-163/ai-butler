"""Qoder 客户端 runtime 探针（从 dockio 拆出，conventions/4 §2.2 文件长度红线）。

只放「定位官方 runtime-info 组件 + 采集设备事实」这一类职责：
``_locate_umid`` / ``_registry_install_roots`` / ``_run_runtime_info`` /
``_client_version`` / ``_machine_os`` / ``_hostname``。

拆分口径：dockio 保留同名薄包装（`_locate_umid` 等）以便测试的 monkeypatch 面
不变——``_MAC_APP_ROOTS`` / ``_MAC_APP_NAMES`` 仍可在 dockio 侧被替换后生效。
"""

from __future__ import annotations

import json
from pathlib import Path

from butler_connectors.manifest import ManifestInvalid

#: 官方 runtime-info 组件相对安装根的路径（win / mac 两种束形态）
UMID_REL_WIN = ("resources", "umid", "runtime-info.exe")
UMID_REL_MAC = ("Contents", "Resources", "umid", "runtime-info")
#: 多版本目录（2026-11-19 真机取证）：Qoder 升级后新版落
#: ``<安装根>/.qoder-versions/<版本>/``，安装根 resources 常停在旧壳——
#: 本机 Global 壳 0.5.7/实际跑 0.5.13，CN 壳 0.4.8/实际跑 0.5.14。
VERSIONS_DIRNAME = ".qoder-versions"
#: mac 应用查找根（~/Applications 兜用户级安装）；两种束形态并存（与 workbuddy
#: localenv 同因）：2026-11-12 记录为 /Applications/Qoder.platform/…，2026-11-18
#: 本机 Global 实测为 /Applications/Qoder.app/…（Contents/Resources/umid/runtime-info
#: arm64 Mach-O 实跑通过）——候选序尝试，先命中先执行
MAC_APP_ROOTS = ("/Applications", "~/Applications")
MAC_APP_NAMES = ("Qoder.app", "Qoder CN.app", "Qoder.platform", "Qoder CN.platform")


def _umid_rel() -> tuple[str, ...]:
    import sys

    return UMID_REL_MAC if sys.platform == "darwin" else UMID_REL_WIN


def _version_key(name: str) -> tuple[int, ...]:
    """目录名当版本号排序（0.5.14 > 0.5.13 > 0.4.8）：非数字段一律 -1 沉底。"""
    return tuple(int(part) if part.isdigit() else -1 for part in name.split("."))


def version_roots(root) -> list[Path]:
    """安装根下的历史版本目录，按版本号降序（无该目录 = 老装法，返回空）。"""
    base = Path(root) / VERSIONS_DIRNAME
    if not base.is_dir():
        return []
    dirs = [entry for entry in base.iterdir() if entry.is_dir()]
    return sorted(dirs, key=lambda entry: _version_key(entry.name), reverse=True)


def umid_within(root) -> Path | None:
    """在一个安装根里找 runtime-info：先版本目录（最新版优先），再安装根 resources。"""
    root = Path(root)
    rel = _umid_rel()
    for version_root in version_roots(root):
        candidate = version_root.joinpath(*rel)
        if candidate.is_file():
            return candidate
    candidate = root.joinpath(*rel)
    return candidate if candidate.is_file() else None


def install_roots(*, roots: tuple[str, ...] = MAC_APP_ROOTS, names: tuple[str, ...] = MAC_APP_NAMES):
    """候选安装根（环境覆盖不在此列）：win 常见目录 + 卸载注册表；mac 束候选序。"""
    import os
    import sys

    located: list[Path] = []
    if sys.platform == "darwin":
        located.extend(Path(os.path.expanduser(base)) / name for base in roots for name in names)
        return located
    for var in ("LOCALAPPDATA", "ProgramFiles", "ProgramFiles(x86)"):
        base = os.environ.get(var)
        if base:
            located.extend(Path(base) / name for name in ("Qoder CN", "Qoder"))
    located.extend(registry_install_roots())
    return located


def locate_umid(
    *,
    roots: tuple[str, ...] = MAC_APP_ROOTS,
    names: tuple[str, ...] = MAC_APP_NAMES,
):
    """runtime-info 定位：环境覆盖 → 平台默认位置（win: 常见目录+卸载注册表；mac: 束候选序）。"""
    import os

    override = os.environ.get("QODER_UMID_EXE")
    if override:
        path = Path(override).expanduser()
        if path.is_file():
            return path
    for root in install_roots(roots=roots, names=names):
        found = umid_within(root)
        if found is not None:
            return found
    return None


def registry_install_roots() -> list[Path]:
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


def run_runtime_info(exe) -> dict:
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


def client_version(exe) -> str:
    """Cosy-Version 来源：安装根 build-manifest.json 的 productVersion（取证 risk.py）。"""
    try:
        manifest = json.loads(
            (exe.parent.parent / "build-manifest.json").read_text(encoding="utf-8")
        )
    except (OSError, ValueError):
        return ""
    version = manifest.get("productVersion")
    return str(version) if version else ""


def machine_os() -> str:
    """Cosy-MachineOS：客户端 SDK 口径（取证 risk.py）——``{arch}_windows``。"""
    import platform
    import sys

    machine = platform.machine().lower()
    arch = {
        "amd64": "x86_64",
        "x86_64": "x86_64",
        "aarch64": "aarch64",
        "arm64": "aarch64",
    }.get(machine, machine)
    if sys.platform == "darwin":  # mac 解锁分支暂缓，OS 口径先对齐备查
        return f"{'arm64' if arch == 'aarch64' else 'x64'}_darwin"
    return f"{arch}_windows"


#: 产品域区域（与 auth.base_urls 的键同源）：CN 走 openapi.qoder.com.cn，Global 走 .sh
REGION_CN = "cn"
REGION_GLOBAL = "global"


def region_of_root(root) -> str:
    """安装根 → 区域：国际版目录名为 ``Qoder``，国内版为 ``Qoder CN``。"""
    return REGION_CN if "CN" in Path(root).name.upper() else REGION_GLOBAL


def region_umids(
    *, roots: tuple[str, ...] = MAC_APP_ROOTS, names: tuple[str, ...] = MAC_APP_NAMES
) -> dict[str, Path]:
    """本机每个区域各一支 runtime-info（首命中者）：同一台机器装了两套客户端时按域分。"""
    found: dict[str, Path] = {}
    for root in install_roots(roots=roots, names=names):
        region = region_of_root(root)
        if region in found:
            continue
        umid = umid_within(root)
        if umid is not None:
            found[region] = umid
    return found


def region_versions() -> dict[str, str]:
    """区域 → 客户端版本（Cosy-Version 按账户域选，见 decl_auth 的 scoped 覆盖）。"""
    return {region: client_version(umid) for region, umid in region_umids().items()}


def installed_version() -> str:
    """平台册 client_version 的事实源：本机已安装（取最新版本目录）的客户端版本。

    纯只读探测，不拉起客户端；定不到组件或读不到 manifest 返回 ""（= 未知）。
    """
    umid = locate_umid()
    return client_version(umid) if umid is not None else ""


def hostname() -> str:
    import socket

    return socket.gethostname()
