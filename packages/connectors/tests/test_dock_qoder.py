"""qoder dock 扫描（glob 数据目录 + 自包含信封 + umid 采集器）——离线全替身。

真 DPAPI / 真 runtime-info 由真机验收覆盖（PROTOCOL §5）；这里验：
目录发现、信封组装、kind 齐套校验、expiresAt 元数据、采集缺失显式 issue。
"""

import base64
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from butler_core.accounts.ports import AccountRepository
from butler_core.accounts.usecases.register_account import RegisterAccount
from butler_connectors import dockio, unlock
from butler_connectors.dockio import scan_storage
from butler_connectors.manifest import DeclarativeSpec
from butler_connectors.registry import DockContext, load_registry

from test_unlock_qoder import MAC_SECRET, TEST_KEY, seal_envelope, seal_mac_envelope

MACHINE_ID = "0123456789abcdef0123456789abcdef0123"  # 36 字符（取证口径）
assert len(MACHINE_ID) == 36


class MemVault:
    def __init__(self) -> None:
        self.items: dict[tuple[str, str], object] = {}

    def store(self, account_id, kind, secret, *, expires_at=None, backend=None):
        self.items[(account_id, kind)] = (secret, expires_at)


class MemAccounts(AccountRepository):
    def __init__(self) -> None:
        self.rows: dict[str, object] = {}

    def save(self, account) -> None:
        self.rows[account.id] = account

    def get(self, account_id):
        return self.rows.get(account_id)

    def list_by_provider(self, provider):
        return [a for a in self.rows.values() if a.provider == provider]

    def list_all(self):
        return list(self.rows.values())


def make_qoder_spec(storage_glob: str) -> DeclarativeSpec:
    return DeclarativeSpec.model_validate(
        {
            "auth": {
                "kind": "dpapi_gcm_v10",
                "storage": [storage_glob],
                "token_header": {"name": "Authorization", "prefix": "Bearer "},
                "dynamic_headers": {"Cosy-MachineId": "{cosy_machine_id}"},
            },
            "status": {
                "request": {"method": "GET", "url": "https://q.test/campaigns"},
                "code_path": "code",
                "list_path": "campaigns",
                "item_filter": {"claimStatus": "CLAIMABLE"},
                "done_filter": {"claimStatus": "CLAIMED"},
            },
            "claim": {
                "request": {
                    "method": "POST",
                    "url": "https://q.test/campaigns/{id}/claim",
                },
                "each": "campaigns",
                "retry": {"on_codes": [], "backoff_seconds": [5]},
            },
            "business_codes": {},
        }
    )


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    """Windows 侧同形数据目录：auth.v1.dat + Local State + auth.machine-id（平台面钉 win32）。"""
    monkeypatch.setattr(sys, "platform", "win32")
    root = tmp_path / "com.qodercn.app.stable"
    root.mkdir()
    envelope = seal_envelope({"token": "T-1", "expiresAt": "2026-11-17T00:59:05.212Z"})
    dat = base64.b64decode(json.loads(base64.b64decode(envelope))["dat"])
    (root / "auth.v1.dat").write_bytes(dat)  # 协议同形：v10+nonce+ct
    (root / "Local State").write_text(
        json.dumps(
            {
                "os_crypt": {
                    "encrypted_key": base64.b64encode(b"DPAPI" + b"wrapped").decode()
                }
            }
        ),
        encoding="utf-8",
    )
    (root / "auth.machine-id").write_text(MACHINE_ID, encoding="utf-8")
    monkeypatch.setattr(unlock, "dpapi_unprotect", lambda blob: TEST_KEY)
    return root


@pytest.fixture
def mac_data_dir(tmp_path, monkeypatch):
    """mac 同形数据目录（2026-11-12 取证）：dat-only + machine-id；Local State 无 os_crypt。"""
    monkeypatch.setattr(sys, "platform", "darwin")
    root = tmp_path / "com.qoder.app.stable"
    root.mkdir()
    envelope = seal_mac_envelope({"token": "T-M", "expiresAt": "2026-12-02T13:37:13Z"})
    dat = base64.b64decode(json.loads(base64.b64decode(envelope))["dat"])
    (root / "auth.v1.dat").write_bytes(dat)
    (root / "auth.machine-id").write_text(MACHINE_ID, encoding="utf-8")
    (root / "Local State").write_text('{"uninstall_metrics": {}}', encoding="utf-8")
    monkeypatch.setattr(unlock, "macos_safe_storage_password", lambda: MAC_SECRET)
    return root


@pytest.fixture
def umid_ready(monkeypatch):
    """runtime-info 定位/运行全替身（输出形状 = 2026-11-11 真机取证）。"""
    monkeypatch.setattr(dockio, "_locate_umid", lambda: Path("C:/fake/runtime-info.exe"))
    monkeypatch.setattr(
        dockio,
        "_run_runtime_info",
        lambda exe: {"machineToken": "MT", "machineCode": "MC", "machineType": "MTY"},
    )
    monkeypatch.setattr(dockio, "_client_version", lambda exe: "0.4.8")


def _dock(spec: DeclarativeSpec, vault: MemVault):
    """按真实注册表装载的 qoder_cn 停靠一次（kinds 取 manifest 申报）。"""
    return scan_storage(
        load_registry().get("qoder_cn"),
        spec,
        ("dpapi_gcm_v10", "umid_cosy"),
        DockContext(vault=vault, register=RegisterAccount(accounts=MemAccounts())),
    )


def test_dock_qoder_full_chain(data_dir, umid_ready):
    vault = MemVault()
    outcome = _dock(make_qoder_spec(str(data_dir.parent / "com.qodercn.app*")), vault)
    assert outcome.issues == [], outcome.issues
    assert outcome.accounts == ["qoder_cn:main"]

    envelope, expires = vault.items[("qoder_cn:main", "dpapi_gcm_v10")]
    assert expires is not None and expires.year == 2026  # 会话 expiresAt 元数据
    assert envelope.expose()  # 自包含信封（base64 文本）
    umid, _ = vault.items[("qoder_cn:main", "umid_cosy")]
    payload = json.loads(base64.b64decode(umid.expose()))
    assert payload["cosy_machine_id"] == MACHINE_ID
    assert payload["cosy_machine_token"] == "MT"
    os_str = payload["cosy_machine_os"]
    if sys.platform == "win32":
        assert os_str.endswith("_windows")  # SDK 口径（取证 risk.py）
    else:
        assert os_str.endswith("_darwin")  # _machine_os 按当前平台派生（组装形状回归）


def test_dock_qoder_missing_umid_component(data_dir, monkeypatch):
    """runtime-info 定位失败 → 显式 issue（绝不静默停靠半套凭据，ADR-006 §4）。"""
    monkeypatch.setattr(dockio, "_locate_umid", lambda: None)
    outcome = _dock(make_qoder_spec(str(data_dir.parent / "com.qodercn.app*")), MemVault())
    assert outcome.accounts == []
    assert outcome.issues and "runtime-info" in outcome.issues[0]


def test_dock_qoder_missing_umid_component_mac_order(mac_data_dir, monkeypatch):
    """mac 定位失败文案按平台报定位顺序（不指向卸载注册表）。"""
    monkeypatch.setattr(dockio, "_locate_umid", lambda: None)
    outcome = _dock(make_qoder_spec(str(mac_data_dir.parent / "com.qoder.app*")), MemVault())
    assert outcome.issues and "/Applications" in outcome.issues[0]
    assert "卸载注册表" not in outcome.issues[0]


def test_dock_qoder_unlock_failure_not_masked_by_umid(data_dir, monkeypatch):
    """主扫描解锁失败 = 唯一真因，附加采集器不得运行/掩盖（真机 mac 抓过）。"""

    def boom(_blob):
        raise RuntimeError("CryptUnprotectData 失败")

    monkeypatch.setattr(unlock, "dpapi_unprotect", boom)
    outcome = _dock(make_qoder_spec(str(data_dir.parent / "com.qodercn.app*")), MemVault())
    assert outcome.accounts == []
    assert len(outcome.issues) == 1
    assert outcome.issues[0] == (
        f"{data_dir}: 登录态解不开（CryptUnprotectData 失败）——请在桌面端重新登录后重扫"
    )


def test_dock_qoder_mac_keychain_failure_is_explicit(tmp_path, monkeypatch):
    """mac 钥匙取不到 → 显式 issue 指向 Keychain 服务名，不静默停靠。"""
    monkeypatch.setattr(sys, "platform", "darwin")
    root = tmp_path / "com.qoder.app.stable"
    root.mkdir()
    envelope = seal_mac_envelope({"token": "T-M"})
    dat = base64.b64decode(json.loads(base64.b64decode(envelope))["dat"])
    (root / "auth.v1.dat").write_bytes(dat)

    def no_key():
        raise RuntimeError("Keychain 未取到 'Qoder App Safe Storage'——确认客户端登录过")

    monkeypatch.setattr(unlock, "macos_safe_storage_password", no_key)
    outcome = _dock(make_qoder_spec(str(root.parent / "com.qoder.app*")), MemVault())
    assert outcome.accounts == []
    assert outcome.issues and "Qoder App Safe Storage" in outcome.issues[0]


def test_dock_qoder_no_data_dir(tmp_path, umid_ready):
    outcome = _dock(make_qoder_spec(str(tmp_path / "com.qodercn.app*")), MemVault())
    assert outcome.accounts == []
    assert outcome.issues and "未发现可解锁登录态" in outcome.issues[0]


# --- mac 解锁链 dock 面（2026-11-12 真机取证：信封只带 dat，钥匙 Keychain 现取）---


def test_dock_qoder_mac_full_chain(mac_data_dir, umid_ready):
    vault = MemVault()
    outcome = _dock(make_qoder_spec(str(mac_data_dir.parent / "com.qoder.app*")), vault)
    assert outcome.issues == [], outcome.issues
    assert outcome.accounts == ["qoder_cn:main"]

    stored, expires = vault.items[("qoder_cn:main", "dpapi_gcm_v10")]
    inner = json.loads(base64.b64decode(stored.expose()))
    assert set(inner) == {"dat"}  # 钥匙不进信封（Keychain 现取，密钥绝不入 vault）
    assert expires is not None and expires.year == 2026


def test_dock_qoder_mac_win_envelope_never_docks_on_darwin(tmp_path, monkeypatch):
    """mac 上拿到 Windows 形信封（有 key_b64）→ DPAPI 链显式爆，不静默走 mac 链。"""
    monkeypatch.setattr(sys, "platform", "darwin")
    root = tmp_path / "com.qoder.app.stable"
    root.mkdir()
    envelope = seal_envelope({"token": "T-1"})
    dat = base64.b64decode(json.loads(base64.b64decode(envelope))["dat"])
    (root / "auth.v1.dat").write_bytes(dat)
    (root / "Local State").write_text(
        json.dumps(
            {"os_crypt": {"encrypted_key": base64.b64encode(b"DPAPI+w").decode()}}
        ),
        encoding="utf-8",
    )
    outcome = _dock(make_qoder_spec(str(root.parent / "com.qoder.app*")), MemVault())
    assert outcome.accounts == []
    assert outcome.issues and "登录态解不开" in outcome.issues[0]


# --- 注册表定位的真形回归（2026-11-11 真机抓虫：GUID 子键 + 值缺失）---


class _FakeEntry:
    def __init__(self, values: dict):
        self._v = values

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeKey:
    def __init__(self, entries: dict):
        self._entries = entries

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _fake_winreg(monkeypatch, entries: dict):
    """winreg 替身：Uninstall 键下 GUID 子键 + 每值可独立缺失（真机形状）。"""
    import sys
    from types import SimpleNamespace

    fake = SimpleNamespace(
        HKEY_CURRENT_USER=0x80000001,
        HKEY_LOCAL_MACHINE=0x80000002,
        KEY_READ=0x20019,
        KEY_WOW64_32KEY=0x200,
        KEY_WOW64_64KEY=0x100,
    )
    uninstall_key = _FakeKey(entries)

    def open_key(parent, path_or_sub, reserved=0, flag=0):
        if isinstance(parent, _FakeKey):  # 内层：OpenKey(uninstall_key, 子键名)
            return _FakeEntry(parent._entries[path_or_sub])
        return uninstall_key  # 顶层：OpenKey(hive, Uninstall 路径)

    def enum_key(key, index):
        names = list(key._entries)
        if index >= len(names):
            raise OSError("枚举结束")
        return names[index]

    def query_value_ex(entry, name):
        if name not in entry._v:
            raise FileNotFoundError(name)  # 真机形状：InstallLocation 可缺
        return entry._v[name], 1

    fake.OpenKey = open_key
    fake.EnumKey = enum_key
    fake.QueryValueEx = query_value_ex
    monkeypatch.setitem(sys.modules, "winreg", fake)


def test_registry_guid_subkey_missing_install_location(tmp_path, monkeypatch):
    """值级缺失独立容错（曾整键吞错 → DisplayIcon 兜底永远轮不到，真机定位落空）。"""
    ico = tmp_path / "Qoder CN" / "uninstallerIcon.ico"
    ico.parent.mkdir()
    ico.write_bytes(b"icon")
    _fake_winreg(
        monkeypatch,
        {
            "{f160a86b-5726-553b-9fff-d78743c4373f}": {  # 真机：GUID 子键
                "DisplayName": "Qoder CN 0.4.8",
                # InstallLocation 值缺失（FileNotFoundError），DisplayIcon 指向 .ico
                "DisplayIcon": f"{ico},0",
            },
            "{no-display-entry}": {"SystemComponent": 1},  # 无 DisplayName：跳过
        },
    )
    from butler_connectors.dockio import _registry_install_roots

    assert _registry_install_roots() == [ico.parent]


def test_locate_umid_env_override(tmp_path, monkeypatch):
    """QODER_UMID_EXE 环境变量覆盖（PROTOCOL §6 排障口）。"""
    fake_exe = tmp_path / "runtime-info.exe"
    fake_exe.write_bytes(b"x")
    monkeypatch.setenv("QODER_UMID_EXE", str(fake_exe))
    from butler_connectors.dockio import _locate_umid

    assert _locate_umid() == fake_exe  # 覆盖优先，且不做存在性宽容


def test_locate_umid_mac_app_bundle(tmp_path, monkeypatch):
    """mac .app 束定位（2026-11-12 本机取证：Contents/Resources/umid/runtime-info）。"""
    umid_dir = tmp_path / "Qoder.app" / "Contents" / "Resources" / "umid"
    umid_dir.mkdir(parents=True)
    exe = umid_dir / "runtime-info"
    exe.write_bytes(b"x")
    monkeypatch.delenv("QODER_UMID_EXE", raising=False)
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(dockio, "_MAC_APP_ROOTS", (str(tmp_path),))
    assert dockio._locate_umid() == exe
