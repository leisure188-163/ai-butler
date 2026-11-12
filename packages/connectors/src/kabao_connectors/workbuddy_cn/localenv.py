"""workbuddy local environment bundle (same shape as doubao localenv): runtime location + WORKBUDDY_EXE override.

The decryption chain needs the client's bundled Electron runtime (ADR-006 decisions 2/6): candidates are tried in
order, switching to the next on KEY_MISMATCH. Location order: WORKBUDDY_EXE explicit override (invalid path =
explicit error, not "not installed") > common install directories (Windows) / .app bundles (mac) > uninstall
registry (Windows only; HKCU/HKLM/WOW6432Node).
Entry match = DisplayName "WorkBuddy" prefix (case-insensitive, compatible with the "WorkBuddy AI" variant —
the old repo's regex can't match the AI variant; do not reuse); exe is taken from DisplayIcon
(strip quotes + strip the ",0" icon index; measured on this machine InstallLocation is empty for both entries
and DisplayIcon is the main exe itself).
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from kabao_connectors.paths import expand_storage_path


class InvalidOverride(RuntimeError):
    """The WORKBUDDY_EXE override value is invalid: explicit error, no silent fallback (red line 5)."""


@dataclass(frozen=True)
class WorkbuddyEnv:
    """Environment bundle: tests inject fake location; real machine uses real_env()."""

    locate_runtime_candidates: Callable[[], list[Path]]


def real_env() -> WorkbuddyEnv:
    return WorkbuddyEnv(locate_runtime_candidates=_locate_runtime_candidates)


#: Runtime exe name × install directory name variants (the two versions on this machine are WorkBuddy AI / WorkBuddy).
_RUNTIME_EXES = ("WorkBuddyAI.exe", "WorkBuddy.exe")
_INSTALL_DIRS = ("WorkBuddy", "WorkBuddyAI")
#: mac .app bundle names × main-binary path inside the bundle (2026-11-12 verified live: CFBundleExecutable is
#: the stock "Electron" — the fork's native binding lives in that binary; helper probe + decrypt both pass).
_MAC_APP_BASES = ("/Applications", "~/Applications")
_MAC_APP_NAMES = ("WorkBuddy.app", "WorkBuddyAI.app")
_MAC_MAIN_REL = ("Contents", "MacOS", "Electron")


def _locate_runtime_candidates() -> list[Path]:
    override = os.environ.get("WORKBUDDY_EXE", "").strip()
    if override:
        # %VAR% 宏统一用 connectors.paths 展开（posix expandvars 不认 %，Windows 专属）
        path = expand_storage_path(override)
        if path is None or not path.is_absolute() or not path.is_file():
            raise InvalidOverride(
                f"WORKBUDDY_EXE is not an existing absolute executable path: {override!r}"
            )
        return [path]
    found = _default_runtime_candidates()
    return found if found else _registry_runtime_candidates()


def _default_runtime_candidates() -> list[Path]:
    """Common install locations (PROTOCOL §1): mac .app bundles; Windows directories, registry only when all miss."""
    found: list[Path] = []
    if sys.platform == "darwin":
        for base in _MAC_APP_BASES:
            root = Path(os.path.expanduser(base))
            for name in _MAC_APP_NAMES:
                found.append(root.joinpath(name, *_MAC_MAIN_REL))
        return [p for p in found if p.is_file()]
    if sys.platform != "win32":
        return []
    roots: list[Path] = []
    if local := os.environ.get("LOCALAPPDATA"):
        roots.append(Path(local) / "Programs")
    if progfiles := os.environ.get("ProgramFiles"):
        roots.append(Path(progfiles))
    for root in roots:
        for sub in _INSTALL_DIRS:
            for exe in _RUNTIME_EXES:
                found.append(root / sub / exe)
    return [p for p in found if p.is_file()]  # 默认目录命中 = 只返回真实存在的 exe；全缺才走注册表


def _registry_runtime_candidates() -> list[Path]:
    found: list[Path] = []
    for entry in _registry_entries():
        exe = _exe_from_entry(entry)
        if exe is None:
            continue
        if all(os.path.normcase(str(exe)) != os.path.normcase(str(p)) for p in found):
            found.append(exe)  # normcase dedupe (the two entries on this machine differ only in case)
    return [p for p in found if p.is_file()]


def _exe_from_entry(entry: dict[str, str]) -> Path | None:
    """Registry entry → main exe candidate: try both names under InstallLocation first; fallback to DisplayIcon
    (strip quotes + split off "," icon index; suffixed = exe itself, unsuffixed = directory → append both names)."""
    location = entry.get("InstallLocation", "").strip().strip('"')
    if location:
        base = Path(location)
        for exe in _RUNTIME_EXES:
            if (base / exe).is_file():
                return base / exe
    icon = entry.get("DisplayIcon", "").split(",")[0].strip().strip('"')
    if icon:
        base = Path(icon)
        if base.suffix:  # suffixed = exe itself (measured form, ADR-006 decision 6)
            return base
        for exe in _RUNTIME_EXES:  # unsuffixed = directory form → append both names
            if (base / exe).is_file():
                return base / exe
    return None


def _registry_entries() -> list[dict[str, str]]:
    """Uninstall entries from three hives; non-Windows gets an empty table; winreg lazily imported (platform-specific)."""
    if sys.platform != "win32":
        return []
    import winreg

    hives = (
        (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
        (
            winreg.HKEY_LOCAL_MACHINE,
            r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
        ),
    )
    found: list[dict[str, str]] = []
    for hive, path in hives:
        try:
            with winreg.OpenKey(hive, path) as root:
                found.extend(_hive_entries(winreg, root))
        except OSError:
            continue  # hive missing/no permission: skip, don't interrupt candidate collection
    return found


def _hive_entries(winreg, root) -> list[dict[str, str]]:
    found: list[dict[str, str]] = []
    index = 0
    while True:
        try:
            subkey_name = winreg.EnumKey(root, index)
        except OSError:
            break
        index += 1
        try:
            subkey = winreg.OpenKey(root, subkey_name)
        except OSError:
            continue  # 子键打不开不匹配
        with subkey:  # 句柄活到三个值读完——先关再查 = 全部 QueryValueEx 失效（真机验收抓过）
            try:
                display, _ = winreg.QueryValueEx(subkey, "DisplayName")
            except OSError:
                continue  # entries without a DisplayName don't match
            if not str(display).casefold().startswith("workbuddy"):
                continue  # prefix match: compatible with the "WorkBuddy AI" variant
            values: dict[str, str] = {}
            for field in ("InstallLocation", "DisplayIcon"):
                try:
                    value, _ = winreg.QueryValueEx(subkey, field)
                    values[field] = str(value)
                except OSError:
                    continue  # missing single value tolerated per-entry
        found.append(values)
    return found
