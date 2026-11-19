"""Qoder 多版本目录与按区域取版本（2026-11-19 真机取证）。

真机事实：Qoder 升级后新版落 <安装根>/.qoder-versions/<版本>/，安装根 resources
停在旧壳——Global 壳 0.5.7/实跑 0.5.13，CN 壳 0.4.8/实跑 0.5.14。旧定位只读
安装根，报出去的版本与真实客户端不符（Cosy-Version 也随之错）。
"""

from __future__ import annotations

import sys
from pathlib import Path

from butler_connectors import qoder_runtime as qr

from butler_connectors.manifest import AuthSpec


def _touch_umid(root: Path, version: str | None = None) -> Path:
    """造一个 Windows 形状的 runtime-info（版本目录或安装根）。"""
    base = root / qr.VERSIONS_DIRNAME / version if version else root
    rel_dir = base / "resources" / "umid"
    rel_dir.mkdir(parents=True, exist_ok=True)
    exe = rel_dir / "runtime-info.exe"
    exe.write_bytes(b"x")
    if version:
        (base / "resources" / "build-manifest.json").write_text(
            f'{{"schemaVersion":1,"productVersion":"{version}"}}', encoding="utf-8"
        )
    return exe


def test_version_roots_按版本号降序_非数字沉底(tmp_path) -> None:
    root = tmp_path / "Qoder"
    for name in ("0.4.8", "0.5.13", "0.5.14", "nightly"):
        (root / ".qoder-versions" / name).mkdir(parents=True)
    names = [entry.name for entry in qr.version_roots(root)]
    assert names == ["0.5.14", "0.5.13", "0.4.8", "nightly"]


def test_version_roots_无多版本目录返回空(tmp_path) -> None:
    assert qr.version_roots(tmp_path / "Qoder") == []


def test_umid_within_优先最新版本目录(tmp_path) -> None:
    """安装根旧壳 + .qoder-versions 新版并存 → 取新版（真机 0.5.7 壳 / 0.5.13 实跑）。"""
    root = tmp_path / "Qoder"
    _touch_umid(root)  # 旧壳
    newest = _touch_umid(root, "0.5.13")
    _touch_umid(root, "0.5.12")
    assert qr.umid_within(root) == newest


def test_umid_within_无版本目录时退回安装根(tmp_path) -> None:
    root = tmp_path / "Qoder"
    shell = _touch_umid(root)
    assert qr.umid_within(root) == shell


def test_umid_within_版本目录无组件时继续往下找(tmp_path) -> None:
    """最新版本目录存在但没装 runtime-info（残缺升级）→ 退下一个版本再退壳。"""
    root = tmp_path / "Qoder"
    shell = _touch_umid(root)
    (root / qr.VERSIONS_DIRNAME / "0.5.14" / "resources").mkdir(parents=True)
    older = _touch_umid(root, "0.5.13")
    assert qr.umid_within(root) == older
    (older.parent).rename(older.parent.with_name("umid-gone"))
    assert qr.umid_within(root) == shell


def test_locate_umid_走版本目录(tmp_path, monkeypatch) -> None:
    root = tmp_path / "Qoder"
    _touch_umid(root)
    newest = _touch_umid(root, "0.5.13")
    monkeypatch.delenv("QODER_UMID_EXE", raising=False)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(qr, "install_roots", lambda **_kwargs: [root])
    assert qr.locate_umid() == newest
    assert qr.client_version(newest) == "0.5.13"


def test_region_of_root_按目录名分域(tmp_path) -> None:
    assert qr.region_of_root(tmp_path / "Qoder") == qr.REGION_GLOBAL
    assert qr.region_of_root(tmp_path / "Qoder CN") == qr.REGION_CN


def test_region_versions_每域各取一支(tmp_path, monkeypatch) -> None:
    """同机装两套客户端：Global/CN 各报自己的最新版本（Cosy-Version 按账户域选源）。"""
    global_root = tmp_path / "Qoder"
    cn_root = tmp_path / "Qoder CN"
    _touch_umid(global_root, "0.5.13")
    _touch_umid(cn_root, "0.5.14")
    monkeypatch.setattr(qr, "install_roots", lambda **_kwargs: [cn_root, global_root])
    versions = qr.region_versions()
    assert versions == {qr.REGION_CN: "0.5.14", qr.REGION_GLOBAL: "0.5.13"}


def test_installed_version_定不到组件返回空(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("QODER_UMID_EXE", raising=False)
    monkeypatch.setattr(qr, "install_roots", lambda **_kwargs: [tmp_path / "空目录"])
    assert qr.installed_version() == ""


def test_platform_client_version_探针按_conn_id_分流(monkeypatch) -> None:
    """声明式连接器经 version_probe 暴露版本：qoder_cn 有值，其余如实为空。"""
    from butler_connectors import version_probe

    monkeypatch.setattr(qr, "installed_version", lambda: "0.5.13")
    assert version_probe.client_version("qoder_cn") == "0.5.13"
    assert version_probe.client_version("trae_cn") == ""
    assert version_probe.client_version("没有这家") == ""


def _qoder_auth() -> AuthSpec:
    return AuthSpec(
        kind="dpapi_gcm_v10",
        base_urls={
            "main": "https://openapi.qoder.com.cn",
            "cn": "https://openapi.qoder.com.cn",
            "global": "https://openapi.qoder.sh",
        },
        static_headers={"Cosy-ClientType": "10"},
        dynamic_headers={"Cosy-Version": "{cosy_version}"},
    )


def test_头组按账户域取对应客户端版本() -> None:
    """CN 账户（main/cn-*）用 cosy_version_cn，Global 账户用 cosy_version_global。"""
    from butler_connectors.decl_auth import fill_auth_headers

    fields = {
        "cosy_version": "0.5.13",  # 平台级默认（定位首命中）
        "cosy_version_cn": "0.5.14",
        "cosy_version_global": "0.5.13",
    }
    auth = _qoder_auth()
    assert fill_auth_headers(auth, fields, account_id="qoder_cn:main")["Cosy-Version"] == "0.5.14"
    assert (
        fill_auth_headers(auth, fields, account_id="qoder_cn:global-020dbc5a")["Cosy-Version"]
        == "0.5.13"
    )
    # 未给账户（探针/无域连接器）：保持平台级默认
    assert fill_auth_headers(auth, fields)["Cosy-Version"] == "0.5.13"


def test_头组_无分区字段时行为不变() -> None:
    from butler_connectors.decl_auth import fill_auth_headers

    auth = _qoder_auth()
    fields = {"cosy_version": "0.5.13"}
    assert fill_auth_headers(auth, fields, account_id="qoder_cn:main")["Cosy-Version"] == "0.5.13"


def test_account_key_精确键优先再前缀再_main() -> None:
    from butler_connectors.decl_auth import account_base_url, account_key

    auth = _qoder_auth()
    assert account_key(auth, "qoder_cn:cn-x") == "cn"
    assert account_key(auth, "qoder_cn:global-699e39eb") == "global"
    assert account_key(auth, "qoder_cn:main") == "main"
    assert account_base_url(auth, "qoder_cn:global-699e39eb") == "https://openapi.qoder.sh"
    assert account_key(AuthSpec(kind="browser_cookie"), "x:main") == ""


def test_dock_采集双客户端分区版本(monkeypatch) -> None:
    """dock payload 同时写 cosy_version_global / _cn，供按账户域取用。"""
    from butler_connectors import dockio

    monkeypatch.setattr(dockio, "_locate_umid", lambda: Path("C:/fake/runtime-info.exe"))
    monkeypatch.setattr(
        dockio, "_run_runtime_info", lambda exe: {"machineToken": "t", "machineCode": "c", "machineType": "m"}
    )
    monkeypatch.setattr(dockio, "_read_machine_id", lambda facts, candidates: "mid")
    monkeypatch.setattr(dockio, "_machine_os", lambda: "x86_64_windows")
    monkeypatch.setattr(dockio, "_hostname", lambda: "host")
    monkeypatch.setattr(dockio, "_client_version", lambda exe: "0.5.13")
    monkeypatch.setattr(dockio, "_region_versions", lambda: {"global": "0.5.13", "cn": "0.5.14"})

    import base64
    import json

    value = dockio._collect_umid_cosy("qoder_cn", {}, [])["umid_cosy"]
    payload = json.loads(base64.b64decode(value))
    assert payload["cosy_version"] == "0.5.13"
    assert payload["cosy_version_global"] == "0.5.13"
    assert payload["cosy_version_cn"] == "0.5.14"
