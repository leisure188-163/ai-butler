"""浏览器会话捕获（browser.py）全链离线测试（A2-03 §6）：真 SQLite + 真 cryptography。

mac CBC 链注入 Keychain 替身（monkeypatch unlock.macos_safe_storage_password）、
win GCM 链注入 DPAPI 替身；两态导入语义、每 profile 一账户槽（ADR-011）、
同 profile 目录去重、临时件用后即删、钥匙拒绝显式出账。真机验收另批（A2-03 §7）。
"""

import base64
import hashlib
import json
import sqlite3
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.padding import PKCS7

from butler_core.accounts.ports import AccountRepository
from butler_core.accounts.usecases.register_account import RegisterAccount
from butler_connectors.dockio import _expires_for
from butler_connectors import unlock
from butler_connectors.browser import _capture_kind, _cookie_dbs, _webkit_to_iso, capture_cookies
from butler_connectors.manifest import CaptureSpec
from butler_connectors.registry import DockContext, load_registry


def test_browser_cookie_expiry_uses_required_names_only():
    """信封里的短命辅助 cookie 不参与有效期，避免把有效会话误判 expired。"""
    envelope = json.dumps(
        {
            "cookies": [
                {"name": "__cf_bm", "expires_at": "2026-01-01T00:00:00+00:00"},
                {"name": COOKIES[0], "expires_at": "2026-12-01T00:00:00+00:00"},
                {"name": COOKIES[1], "expires_at": "2026-11-20T00:00:00+00:00"},
            ]
        }
    )
    expires = _expires_for("browser_cookie", envelope, cookie_names=COOKIES)
    assert expires == datetime(2026, 11, 20, tzinfo=UTC)


def test_cookie_dbs_ignores_component_directories(tmp_path):
    """Chrome 组件目录里的同名 Cookies 文件不是 profile 库，不能参与捕获。"""
    component = tmp_path / "Chrome" / "ActorSafetyLists" / "Cookies"
    component.parent.mkdir(parents=True)
    component.write_bytes(b"not-a-cookie-db")
    system_profile = tmp_path / "Chrome" / "System Profile" / "Cookies"
    system_profile.parent.mkdir(parents=True)
    system_profile.write_bytes(b"not-a-cookie-db")
    profile_db = tmp_path / "Chrome" / "Default" / "Cookies"
    profile_db.parent.mkdir(parents=True)
    profile_db.write_bytes(b"cookie-db")
    dbs = _cookie_dbs([str(tmp_path / "Chrome/*/Cookies")])
    assert dbs == [profile_db]


def first_envelope(captured) -> str:
    """_capture_kind 新返回形（captured, issues）：取首槽信封。"""
    return captured[0].envelope

MAC_SECRET = b"chrome-safe-storage-pass"
WIN_KEY = bytes(range(32))  # GCM 链 32B（AES-256）
DOMAIN = "chatgpt.com"
COOKIES = ("__Secure-next-auth.session-token.0", "__Secure-next-auth.session-token.1")

EXPIRED = datetime(2026, 1, 1, tzinfo=UTC)
FUTURE = datetime(2027, 3, 1, tzinfo=UTC)


def capture_spec() -> CaptureSpec:
    return CaptureSpec.model_validate(
        {"auth": {"kind": "browser_cookie", "browser": "chrome", "domain": DOMAIN, "cookies": list(COOKIES)}}
    )


def webkit_micros(dt: datetime) -> int:
    return int((dt - datetime(1601, 1, 1, tzinfo=UTC)).total_seconds() * 1_000_000)


def cbc_seal(plain: bytes, key: bytes, host: str = DOMAIN) -> bytes:
    """mac 链真形状（A1-04 §4.1-8，2026-11-14 定论）：v10 + 单条 CBC 链——
    明文 = sha256(host)[:32] ‖ PKCS7(plain)，IV = 16 空格（域绑定头随链加密）。"""
    header = hashlib.sha256(host.encode()).digest()
    padder = PKCS7(128).padder()
    padded = padder.update(plain) + padder.finalize()
    enc = Cipher(algorithms.AES(key), modes.CBC(b" " * 16)).encryptor()
    return b"v10" + enc.update(header + padded) + enc.finalize()


def cbc_seal_prefixed(plain: bytes, key: bytes, junk: bytes = bytes(range(16))) -> bytes:
    """mac 链前缀形状（2026-11-13 真机取证）：v10 + 16B 未定论段 + 16B IV + 密文。"""
    padder = PKCS7(128).padder()
    padded = padder.update(plain) + padder.finalize()
    iv = bytes(16)
    enc = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    return b"v10" + junk + iv + enc.update(padded) + enc.finalize()


def gcm_seal(plain: bytes, key: bytes) -> bytes:
    """win 链加密（与 decrypt_chromium_cookie(gcm=True) 互逆）：v10 + nonce + GCM。"""
    nonce = bytes(12)
    return b"v10" + nonce + AESGCM(key).encrypt(nonce, plain, None)


def make_cookie_db(path: Path, rows: list[tuple[str, str, bytes | None, str | None, int]]) -> None:
    """协议同形 cookie 库：host_key/name/value/encrypted_value/expires_utc。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "CREATE TABLE cookies ("
            "host_key TEXT, name TEXT, value TEXT, encrypted_value BLOB, expires_utc INTEGER)"
        )
        conn.executemany("INSERT INTO cookies VALUES (?, ?, ?, ?, ?)", rows)
        conn.commit()
    finally:
        conn.close()


def mac_rows(key: bytes, spec: dict[str, tuple[bytes, int]]) -> list[tuple]:
    """spec: cookie 名 → (明文, webkit 微秒)。host = domain 精确。"""
    return [
        (DOMAIN, name, None, cbc_seal(plain, key), micros)
        for name, (plain, micros) in spec.items()
    ]


@pytest.fixture
def mac_env(monkeypatch) -> bytes:
    """mac 平台面 + Keychain 替身；返回真派生钥匙（加密侧与解密侧同链）。"""
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(
        unlock, "macos_safe_storage_password", lambda service: MAC_SECRET
    )
    return unlock.chromium_cookie_key(MAC_SECRET)


@pytest.fixture
def win_env(monkeypatch) -> bytes:
    """win 平台面 + DPAPI 替身。"""
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(unlock, "dpapi_unprotect", lambda blob: WIN_KEY)
    return WIN_KEY


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

    def list_by_platform(self, platform):
        return [a for a in self.rows.values() if a.platform_code == platform]

    def list_all(self):
        return list(self.rows.values())

    def remove(self, account_id):
        return self.rows.pop(account_id, None) is not None


@pytest.fixture(scope="module")
def registry():
    return load_registry()


def _capture_via_registry(registry, storage_glob: str, vault: MemVault):
    """按真实注册表 chatgpt_web 停靠（manifest/kinds/声明 YAML 全真，只有浏览器替身）。"""
    platform = registry.get("chatgpt_web")
    return capture_cookies(
        platform,
        platform.declarative["session.import"],
        ("browser_cookie",),
        DockContext(
            vault=vault,
            register=RegisterAccount(accounts=MemAccounts()),
            storage_override=[storage_glob],
        ),
    )


# --- mac CBC 链 ---


def test_capture_full_chain_expired_cookie_still_imports(tmp_path, mac_env, registry):
    """两态语义：名单凑齐但已过期 → 照常出卡（expires_at 为过去值，如实）。"""
    db = tmp_path / "Chrome" / "Default" / "Cookies"
    make_cookie_db(
        db,
        mac_rows(
            mac_env,
            {COOKIES[0]: (b"v-half-a", webkit_micros(EXPIRED)), COOKIES[1]: (b"v-half-b", 0)},
        ),
    )
    vault = MemVault()
    outcome = _capture_via_registry(registry, str(tmp_path / "Chrome/*/Cookies"), vault)
    assert outcome.issues == [], outcome.issues
    assert len(outcome.accounts) == 1 and outcome.accounts[0].startswith("acc_")

    stored, expires_at = vault.items[(outcome.accounts[0], "browser_cookie")]
    envelope = json.loads(stored.expose())
    assert envelope["browser"] == "chrome" and envelope["domain"] == DOMAIN
    assert [c["name"] for c in envelope["cookies"]] == list(COOKIES)  # 名单序 = 信封序
    assert envelope["cookies"][0]["value"] == "v-half-a"
    assert envelope["cookies"][0]["expires_at"].startswith("2026-01-01")  # 过期值原样
    assert "expires_at" not in envelope["cookies"][1]  # 会话 cookie（0）→ 无到期
    assert expires_at == EXPIRED  # vault 元数据 = 名单内最早者（过期照存）


def test_capture_not_logged_in_falls_to_issues(tmp_path, mac_env, registry):
    """名单不齐 = 未登录（非错误）→ issues 如实，不注册账号。"""
    db = tmp_path / "Chrome" / "Default" / "Cookies"
    make_cookie_db(db, mac_rows(mac_env, {COOKIES[0]: (b"v-only", webkit_micros(FUTURE))}))
    outcome = _capture_via_registry(registry, str(tmp_path / "Chrome/*/Cookies"), MemVault())
    assert outcome.accounts == []
    assert outcome.issues and "未登录" in outcome.issues[0] and DOMAIN in outcome.issues[0]


def test_capture_no_cookie_db(tmp_path, mac_env, registry):
    outcome = _capture_via_registry(registry, str(tmp_path / "Chrome/*/Cookies"), MemVault())
    assert outcome.accounts == []
    assert outcome.issues and "未发现 Chrome cookie 库" in outcome.issues[0]


def test_capture_empty_override_issues(tmp_path, mac_env, registry):
    """storage_override 显式空列表 → 无候选（声明层事故如实出账）。"""
    platform = registry.get("chatgpt_web")
    outcome = capture_cookies(
        platform,
        capture_spec(),
        ("browser_cookie",),
        DockContext(vault=MemVault(), register=RegisterAccount(accounts=MemAccounts()), storage_override=[]),
    )
    assert outcome.issues and "没有候选 cookie 库" in outcome.issues[0]


def test_legacy_plaintext_column_accepted(tmp_path, mac_env):
    """legacy 明文 value 列（无密文）：原样收，如实。"""
    db = tmp_path / "Chrome" / "Default" / "Cookies"
    make_cookie_db(
        db,
        [
            (DOMAIN, COOKIES[0], "plain-a", None, webkit_micros(FUTURE)),
            (DOMAIN, COOKIES[1], "plain-b", None, 0),
        ],
    )
    captured, _ = _capture_kind(
        capture_spec().auth, "chatgpt_web", [str(db)]
    )
    envelope = json.loads(first_envelope(captured))
    assert [c["value"] for c in envelope["cookies"]] == ["plain-a", "plain-b"]


def test_key_failure_is_explicit_issue(tmp_path, mac_env, monkeypatch, registry):
    """钥匙取不到 → 显式 issue 指向 Keychain 服务名（mac 尾巴），不静默。"""
    make_cookie_db(
        tmp_path / "Chrome" / "Default" / "Cookies",
        mac_rows(mac_env, {COOKIES[0]: (b"v-0", 0), COOKIES[1]: (b"v-1", 0)}),
    )

    def no_key(service):
        raise RuntimeError("Keychain 未取到 'Chrome Safe Storage'")

    monkeypatch.setattr(unlock, "macos_safe_storage_password", no_key)
    outcome = _capture_via_registry(registry, str(tmp_path / "Chrome/*/Cookies"), MemVault())
    assert outcome.accounts == []
    assert outcome.issues and "浏览器钥匙取不到" in outcome.issues[0]
    assert "Chrome Safe Storage" in outcome.issues[0]


def test_decrypt_failure_is_explicit_issue(tmp_path, mac_env, registry):
    """钥匙不匹配 → 解密失败显式出账（红线 5，不静默跳行）。"""
    other_key = unlock.chromium_cookie_key(b"different-secret")
    make_cookie_db(
        tmp_path / "Chrome" / "Default" / "Cookies",
        mac_rows(other_key, {COOKIES[0]: (b"v-0", 0), COOKIES[1]: (b"v-1", 0)}),
    )
    outcome = _capture_via_registry(registry, str(tmp_path / "Chrome/*/Cookies"), MemVault())
    assert outcome.accounts == []
    assert outcome.issues and "cookie 解不开" in outcome.issues[0]


def test_temp_copy_deleted_after_capture(tmp_path, mac_env, monkeypatch, registry):
    """密文库临时拷贝用后即删（取证纪律；明文 cookie 绝不落盘）。"""
    import tempfile as tempfile_mod

    made: list[str] = []
    real_mkstemp = tempfile_mod.mkstemp

    def spy(*args, **kwargs):
        fd, name = real_mkstemp(*args, **kwargs)
        made.append(name)
        return fd, name

    monkeypatch.setattr(tempfile_mod, "mkstemp", spy)
    make_cookie_db(
        tmp_path / "Chrome" / "Default" / "Cookies",
        mac_rows(mac_env, {COOKIES[0]: (b"v-0", 0), COOKIES[1]: (b"v-1", 0)}),
    )
    outcome = _capture_via_registry(registry, str(tmp_path / "Chrome/*/Cookies"), MemVault())
    assert outcome.issues == [], outcome.issues
    assert made, "捕获流程应创建过临时拷贝"
    assert all(not Path(name).exists() for name in made)


# --- win GCM 链 ---


def test_capture_windows_gcm_chain(tmp_path, win_env, registry):
    """win 链端到端（替身 DPAPI）：Local State 钥匙块 → GCM 解密 → 信封。"""
    db = tmp_path / "User Data" / "Default" / "Cookies"
    rows = [
        (DOMAIN, name, None, gcm_seal(plain, win_env), micros)
        for name, (plain, micros) in {
            COOKIES[0]: (b"v-w-0", webkit_micros(FUTURE)),
            COOKIES[1]: (b"v-w-1", 0),
        }.items()
    ]
    make_cookie_db(db, rows)
    (tmp_path / "User Data" / "Local State").write_text(
        json.dumps(
            {"os_crypt": {"encrypted_key": base64.b64encode(b"DPAPI" + b"wrapped").decode()}}
        ),
        encoding="utf-8",
    )
    vault = MemVault()
    outcome = _capture_via_registry(registry, str(tmp_path / "User Data/*/Cookies"), vault)
    assert outcome.issues == [], outcome.issues
    assert len(outcome.accounts) == 1 and outcome.accounts[0].startswith("acc_")
    stored, expires_at = vault.items[(outcome.accounts[0], "browser_cookie")]
    envelope = json.loads(stored.expose())
    assert [c["value"] for c in envelope["cookies"]] == ["v-w-0", "v-w-1"]
    assert expires_at == FUTURE


def test_capture_windows_missing_local_state(tmp_path, win_env, registry):
    """Local State 缺失 = 钥匙无处取 → StorageNotFound 如实出账。"""
    db = tmp_path / "User Data" / "Default" / "Cookies"
    make_cookie_db(
        db,
        [
            (DOMAIN, name, None, gcm_seal(b"v", win_env), 0)
            for name in COOKIES
        ],
    )
    outcome = _capture_via_registry(registry, str(tmp_path / "User Data/*/Cookies"), MemVault())
    assert outcome.accounts == []
    assert outcome.issues and "Local State" in outcome.issues[0]


# --- 机械 ---


def test_verify_mac_cookie_header(tmp_path, mac_env):
    """域绑定头校验（A1-04 §4.1-8）：真形状 → True；host 篡改/短形状 → False。"""
    from butler_connectors.unlock import verify_mac_cookie_header

    blob = cbc_seal(b"v", mac_env)
    assert verify_mac_cookie_header(blob, mac_env, DOMAIN) is True
    assert verify_mac_cookie_header(blob, mac_env, "evil.com") is False
    assert verify_mac_cookie_header(b"v10" + bytes(20), mac_env, DOMAIN) is False  # 短形状
    assert verify_mac_cookie_header(b"v11" + bytes(64), mac_env, DOMAIN) is False  # 非 v10


def test_domain_header_mismatch_is_explicit_issue(tmp_path, mac_env, registry):
    """头不符（host 与密文域绑定标签不一致）→ 显式出账，不静默入库（红线 5）。"""
    from butler_connectors.unlock import verify_mac_cookie_header

    # 行 host = 带点域（入库真实形状），但密文头按裸域构造 → 校验必败
    db = tmp_path / "Chrome" / "Default" / "Cookies"
    make_cookie_db(db, mac_rows(mac_env, {COOKIES[0]: (b"v-0", 0), COOKIES[1]: (b"v-1", 0)}))
    # 重建：把行 host 改成 ".chatgpt.com"（仍命中 domain 过滤），密文头按裸域生成
    import sqlite3 as sqlite3_mod

    conn = sqlite3_mod.connect(db)
    try:
        conn.execute("UPDATE cookies SET host_key = ?", (f".{DOMAIN}",))
        conn.commit()
    finally:
        conn.close()
    outcome = _capture_via_registry(registry, str(tmp_path / "Chrome/*/Cookies"), MemVault())
    assert outcome.accounts == []
    assert outcome.issues and "域绑定头不符" in outcome.issues[0]
    assert verify_mac_cookie_header(cbc_seal(b"x", mac_env, f".{DOMAIN}"), mac_env, f".{DOMAIN}")


def test_mac_cbc_dual_shape_decrypt():
    """双形状自识别：经典（体=密文）与前缀（16B 段+IV）都能解回明文。"""
    from butler_connectors.unlock import decrypt_chromium_cookie

    key = unlock.chromium_cookie_key(MAC_SECRET)
    assert decrypt_chromium_cookie(cbc_seal(b"classic-value", key), key, gcm=False) == b"classic-value"
    assert (
        decrypt_chromium_cookie(cbc_seal_prefixed(b"prefixed-value", key), key, gcm=False)
        == b"prefixed-value"
    )


def test_mac_cbc_short_body_rejected():
    """非 v10 头 / 块长不齐显式爆（形状已变探测）。"""
    from butler_connectors.unlock import decrypt_chromium_cookie

    key = unlock.chromium_cookie_key(MAC_SECRET)
    with pytest.raises(ValueError, match="密文头未知"):
        decrypt_chromium_cookie(b"v11" + bytes(16), key, gcm=False)
    with pytest.raises(ValueError, match="两种形状均不符"):
        decrypt_chromium_cookie(b"v10" + bytes(3), key, gcm=False)  # 块长不齐且前缀形不够长


def test_webkit_epoch_conversion():
    assert _webkit_to_iso(0) is None
    assert _webkit_to_iso(-5) is None  # 负值同会话 cookie 处理
    assert _webkit_to_iso(webkit_micros(EXPIRED)) == "2026-01-01T00:00:00+00:00"
    assert _webkit_to_iso(webkit_micros(FUTURE)) == "2027-03-01T00:00:00+00:00"


def test_webkit_micros_roundtrip(tmp_path, mac_env):
    """加密侧用 webkit_micros、解密侧 _webkit_to_iso：互逆无漂移（时区保全）。"""
    iso = _webkit_to_iso(webkit_micros(datetime(2026, 6, 15, 12, 30, 45, tzinfo=UTC)))
    assert iso == "2026-06-15T12:30:45+00:00"


# --- 2026-11-13 Windows 真机验收批（A2-03 §7 回填）：现代布局/锁库兜底/逐 profile 隔离/v20 ---


def test_capture_windows_network_layout(tmp_path, win_env, registry):
    """现代 Chrome 布局（≥96：<profile>/Network/Cookies）+ Local State 跨级发现。"""
    db = tmp_path / "User Data" / "Default" / "Network" / "Cookies"
    rows = [
        (DOMAIN, name, None, gcm_seal(plain, win_env), micros)
        for name, (plain, micros) in {
            COOKIES[0]: (b"v-net-0", webkit_micros(FUTURE)),
            COOKIES[1]: (b"v-net-1", 0),
        }.items()
    ]
    make_cookie_db(db, rows)
    (tmp_path / "User Data" / "Local State").write_text(
        json.dumps(
            {"os_crypt": {"encrypted_key": base64.b64encode(b"DPAPI" + b"wrapped").decode()}}
        ),
        encoding="utf-8",
    )
    vault = MemVault()
    outcome = _capture_via_registry(
        registry, str(tmp_path / "User Data/*/Network/Cookies"), vault
    )
    assert outcome.issues == [], outcome.issues
    assert len(outcome.accounts) == 1 and outcome.accounts[0].startswith("acc_")
    stored, _ = vault.items[(outcome.accounts[0], "browser_cookie")]
    assert [c["value"] for c in json.loads(stored.expose())["cookies"]] == ["v-net-0", "v-net-1"]


def test_locked_db_falls_back_to_immutable_read(tmp_path, mac_env, registry, monkeypatch):
    """活动库被浏览器锁死（拷贝 PermissionError，Windows 真 Chrome 形状）
    → SQLite immutable 只读直开兜底，捕获照常走通。"""
    import shutil as shutil_mod

    def locked(src, dst):
        raise PermissionError(13, "另一个程序正在使用此文件，进程无法访问")

    monkeypatch.setattr(shutil_mod, "copyfile", locked)
    db = tmp_path / "Chrome" / "Default" / "Cookies"
    make_cookie_db(
        db,
        mac_rows(mac_env, {COOKIES[0]: (b"v-lock-0", 0), COOKIES[1]: (b"v-lock-1", 0)}),
    )
    vault = MemVault()
    outcome = _capture_via_registry(registry, str(tmp_path / "Chrome/*/Cookies"), vault)
    assert outcome.issues == [], outcome.issues
    assert len(outcome.accounts) == 1 and outcome.accounts[0].startswith("acc_")
    stored, _ = vault.items[(outcome.accounts[0], "browser_cookie")]
    assert [c["value"] for c in json.loads(stored.expose())["cookies"]] == ["v-lock-0", "v-lock-1"]


def test_locked_db_immutable_open_failure_stays_explicit_issue(
    tmp_path, mac_env, registry, monkeypatch
):
    """真机回归（2026-11-13 Windows）：锁死 + immutable 直开的 connect 也失败
    → ProfileUnreadable 如实出账（当时 connect 在 try 外裸抛，逃逸成笼统异常）。"""
    import shutil as shutil_mod
    import sqlite3 as sqlite3_mod

    def locked(src, dst):
        raise PermissionError(13, "另一个程序正在使用此文件，进程无法访问")

    def no_open(*args, **kwargs):
        raise sqlite3_mod.OperationalError("unable to open database file")

    db = tmp_path / "Chrome" / "Default" / "Cookies"
    make_cookie_db(
        db,
        mac_rows(mac_env, {COOKIES[0]: (b"v-x-0", 0), COOKIES[1]: (b"v-x-1", 0)}),
    )
    monkeypatch.setattr(shutil_mod, "copyfile", locked)
    monkeypatch.setattr(sqlite3_mod, "connect", no_open)
    outcome = _capture_via_registry(registry, str(tmp_path / "Chrome/*/Cookies"), MemVault())
    assert outcome.accounts == []
    assert outcome.issues and "只读直开失败" in outcome.issues[0]
    assert "关闭浏览器后重扫" in outcome.issues[0]


def test_v20_appbound_cookie_explicit_issue(tmp_path, win_env):
    """v20 应用绑定加密（Chrome 127+ Windows 真机取证全量形状）：
    显式落榜、文案自足、不误导「重扫」。"""
    from butler_connectors.browser import _capture_kind

    db = tmp_path / "User Data" / "Default" / "Cookies"
    make_cookie_db(db, [(DOMAIN, name, None, b"v20" + bytes(40), 0) for name in COOKIES])
    (tmp_path / "User Data" / "Local State").write_text(
        json.dumps(
            {"os_crypt": {"encrypted_key": base64.b64encode(b"DPAPI" + b"wrapped").decode()}}
        ),
        encoding="utf-8",
    )
    captured, issues = _capture_kind(
        capture_spec().auth, "chatgpt_web", [str(tmp_path / "User Data/*/Cookies")]
    )
    assert captured == []
    assert issues and "v20" in issues[0] and "应用绑定" in issues[0]
    assert "重扫" not in issues[0]


def test_decrypt_rejects_v20_with_shape_error():
    """v20 = CookieShapeError（显式形状申报）；v11 等未知头照旧 ValueError。"""
    from butler_connectors.unlock import CookieShapeError, decrypt_chromium_cookie

    with pytest.raises(CookieShapeError, match="应用绑定"):
        decrypt_chromium_cookie(b"v20" + bytes(40), WIN_KEY, gcm=True)
    with pytest.raises(ValueError, match="密文头未知"):
        decrypt_chromium_cookie(b"v11" + bytes(40), WIN_KEY, gcm=True)


