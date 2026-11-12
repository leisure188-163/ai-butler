"""豆包本机环境束（ADR-005 决策 2/5）：exe 定位 / 版本读取 / 进程操作 / 拉起。

- 全部平台依赖收进 LocalEnv 数据类（A2-02 §8 工厂注入）：测试传假束离线测 dock
- M1 自动拉起仅 Windows；mac 分支 locate_exe 返回 None（dock 出 issue 显式指引，
  不静默——probe 可达时 mac 全链可用，只差自动拉起）
- version_code = 主*10000+次*100+修订（PROTOCOL doubao_cn §1；写死版本在客户端
  升级后会回 710010702——版本必须运行时读）
"""

from __future__ import annotations

import csv
import io
import os
import re
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

_DEFAULT_PORT = 9222
_PROCESS_NAME = "Doubao.exe"
_VERSION_RE = re.compile(r"^(\d{1,2})\.(\d{1,2})(?:\.(\d{1,2}))?$")


def version_code(version: str) -> int | None:
    """``2.35.8`` → ``23508``；形状非法 None（调用方显式爆，不猜）。"""
    match = _VERSION_RE.match(version.strip())
    if not match:
        return None
    major, minor, patch = match.group(1), match.group(2), match.group(3) or "0"
    return int(major) * 10000 + int(minor) * 100 + int(patch)


@dataclass(frozen=True)
class LocalEnv:
    """豆包本机环境操作束（A2-02 §8）：真实实现绑 winreg/subprocess；测试传假束。"""

    resolve_port: Callable[[], int]
    read_version: Callable[[], str]  # "" = 读不到（调用方显式爆，不猜）
    locate_exe: Callable[[], Path | None]  # None = 未定位（未安装/平台不支持）
    process_pids: Callable[[], list[int]]
    kill_pid: Callable[[int], None]
    spawn_detached: Callable[[Path], None]
    sleep: Callable[[float], None]


def real_env() -> LocalEnv:
    """真实环境束：winreg 注册表 + tasklist/taskkill + 脱离进程的 Popen。"""
    return LocalEnv(
        resolve_port=_resolve_port,
        read_version=_read_version,
        locate_exe=_locate_exe,
        process_pids=_process_pids,
        kill_pid=_kill_pid,
        spawn_detached=_spawn_detached,
        sleep=time.sleep,
    )


def _resolve_port() -> int:
    """DOUBAO_CDP_PORT 优先（非法值显式 ValueError），缺省 9222（PROTOCOL §1）。"""
    raw = os.environ.get("DOUBAO_CDP_PORT")
    if raw:
        return int(raw)  # 形状非法让 ValueError 显式上抛——不静默回默认口
    return _DEFAULT_PORT


def _read_version() -> str:
    """版本：DOUBAO_VERSION 覆盖优先；否则卸载注册表 DisplayVersion（^Doubao）。"""
    override = (os.environ.get("DOUBAO_VERSION") or "").strip()
    if override:
        return override
    return _registry_display_version()


def _registry_display_version() -> str:
    """豆包条目的 DisplayVersion（PROTOCOL §1 实测口径）；非 Windows/未安装 ""。"""
    for values in _registry_entries():
        if values.get("DisplayVersion"):
            return values["DisplayVersion"]
    return ""


def _registry_entries() -> list[dict[str, str]]:
    """HKCU 卸载注册表里的豆包条目（PROTOCOL §1 实测定稿口径）。

    匹配 = 子键名 ``Doubao*`` 优先，DisplayName ``Doubao*``/``豆包`` 兜底——
    真机 DisplayName 是中文"豆包"，按 DisplayName 前缀匹配会漏；值缺失逐条容错。
    """
    if sys.platform != "win32":
        return []
    try:
        import winreg
    except ImportError:  # pragma: no cover - win32 上必可 import
        return []
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Uninstall",
            0,
            winreg.KEY_READ,
        )
    except OSError:
        return []
    out: list[dict[str, str]] = []
    with key:
        index = 0
        while True:
            try:
                sub = winreg.EnumKey(key, index)
                index += 1
            except OSError:
                break
            values: dict[str, str] = {}
            try:
                with winreg.OpenKey(key, sub) as entry:
                    for name in ("DisplayName", "DisplayVersion", "DisplayIcon"):
                        try:
                            values[name] = str(winreg.QueryValueEx(entry, name)[0]).strip()
                        except OSError:
                            continue  # 值缺失换下一个（dockio 同款逐值容错）
            except OSError:
                continue
            display = values.get("DisplayName", "")
            if not (sub.startswith("Doubao") or display.startswith("Doubao") or display == "豆包"):
                continue
            out.append(values)
    return out


def _locate_exe() -> Path | None:
    """exe 定位（PROTOCOL §1）：DOUBAO_EXE 覆盖 → 卸载注册表 DisplayIcon 父目录
    + app/Doubao.exe；非 Windows None（mac 自动拉起 M1 未实现，显式走 issue）。"""
    override = os.environ.get("DOUBAO_EXE")
    if override:
        path = Path(override)
        return path if path.is_file() else None
    if sys.platform != "win32":
        return None
    for root in _registry_install_roots():
        candidate = root / "app" / _PROCESS_NAME
        if candidate.is_file():
            return candidate
    return None


def _registry_install_roots() -> list[Path]:
    """豆包条目 DisplayIcon 父目录——真机指向**带引号**的 icon.ico，剥引号取目录。"""
    roots: list[Path] = []
    for values in _registry_entries():
        icon = values.get("DisplayIcon", "")
        if not icon:
            continue
        path = Path(icon.split(",")[0].strip().strip('"'))
        if path.suffix:  # DisplayIcon 指向 exe/ico → 取所在目录
            path = path.parent
        if path.is_dir():
            roots.append(path)
    return roots


def _process_pids() -> list[int]:
    """Doubao.exe 进程 PID（tasklist CSV；非 Windows 返回空——拉起链路本就不可用）。"""
    if sys.platform != "win32":
        return []
    proc = subprocess.run(
        ["tasklist", "/FI", f"IMAGENAME eq {_PROCESS_NAME}", "/FO", "CSV", "/NH"],
        capture_output=True,
        timeout=15,
    )
    pids: list[int] = []
    for row in csv.reader(io.StringIO(proc.stdout.decode("utf-8", "replace"))):
        if len(row) >= 2 and row[0].strip() == _PROCESS_NAME:
            try:
                pids.append(int(row[1]))
            except ValueError:
                continue
    return pids


def _kill_pid(pid: int) -> None:
    proc = subprocess.run(
        ["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True, timeout=15
    )
    if proc.returncode != 0:
        raise RuntimeError(f"taskkill PID {pid} 失败（exit={proc.returncode}）")


def _spawn_detached(exe: Path) -> None:
    """带调试端口脱离拉起（父进程退出后客户端继续跑）。"""
    kwargs: dict = {"close_fds": True}
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    subprocess.Popen(
        [str(exe), f"--remote-debugging-port={_resolve_port()}"], **kwargs
    )
