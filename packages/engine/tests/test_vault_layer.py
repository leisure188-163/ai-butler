"""LayeredVault + health state + 每日 job + bridge 装配基线（A4-01 §1/§4/§5）。

- 秘密往返走注入的 MemoryVaultBackend（不碰真钥匙串/凭据管理器）
- 存/取/轮换同步写审计（A4-01 §4：凭据存取/轮换触发点）
- rotate 旧值进 #seq 历史，可找回；load 缺 kind 显式报错（红线 5）
"""

import json
from datetime import datetime, timedelta, timezone

import pytest

from butler_core.health.domain import HealthLevel
from butler_core.accounts.domain import Secret, vault_ref
from butler_engine.audit.sqlite import SqliteAuditLog
from butler_engine.health.state import SqliteHealthStateStore
from butler_engine.scheduling.interval_job import IntervalJob
from butler_engine.vault.backends import MemoryVaultBackend
from butler_engine.vault.credman_windows import WindowsCredmanBackend
from butler_engine.vault.errors import (
    VaultCredentialMissing,
    VaultCredentialRevoked,
    VaultLayerUnavailable,
)
from butler_engine.vault.keychain_macos import KeychainBackend
from butler_engine.vault.layered import LayeredVault

_T0 = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)


def _vault(tmp_path, expires_at=None):
    audit = SqliteAuditLog(tmp_path / "a.db")
    vault = LayeredVault(
        tmp_path / "v.db",
        {"memory": MemoryVaultBackend()},
        default_backend="memory",
        audit=audit,
    )
    return vault, audit


def test_store_load_roundtrip(tmp_path):
    vault, _ = _vault(tmp_path)
    vault.store("acc1", "cookie", Secret("sid=abc; uid=42"))
    loaded = vault.load("acc1", ["cookie"])
    assert [s.expose() for s in loaded] == ["sid=abc; uid=42"]
    assert str(loaded[0]) == "[REDACTED]"  # 运出即脱敏


def test_store_requires_registered_backend(tmp_path):
    vault, _ = _vault(tmp_path)
    with pytest.raises(VaultLayerUnavailable):
        vault.store("a", "cookie", Secret("x"), backend="keychain")  # 未装配


def test_load_missing_kind_is_explicit(tmp_path):
    vault, audit = _vault(tmp_path)
    with pytest.raises(VaultCredentialMissing):
        vault.load("acc1", ["cookie"])
    rows = json.loads(audit.export_json())
    assert rows[-1]["outcome"] == "denied:missing:cookie"  # 读取被拒也进审计


def test_rotate_archives_old_and_audits(tmp_path):
    vault, audit = _vault(tmp_path)
    vault.store("acc1", "token", Secret("old-token"))
    vault.rotate("acc1", "token", Secret("new-token"))
    assert vault.load("acc1", ["token"])[0].expose() == "new-token"

    history = vault.history("acc1", "token")
    assert len(history) == 1
    old_ref = history[0][0]
    assert old_ref.startswith(vault_ref("acc1", "token") + "#")  # 旧值进历史引用
    assert vault._backend("memory").get(old_ref) == "old-token"  # 旧值仍可找回

    # 审计链：store → rotate → load（读取本身也进审计，A4-01 §4 存取触发点）
    kinds = [row["action"] for row in json.loads(audit.export_json()) if row["actor"] == "vault"]
    assert kinds == ["vault.store", "vault.rotate", "vault.load"]


def test_rotate_without_existing_refused(tmp_path):
    vault, _ = _vault(tmp_path)
    with pytest.raises(VaultCredentialMissing):
        vault.rotate("acc1", "token", Secret("x"))


def test_health_reports_expiry_levels(tmp_path):
    vault, _ = _vault(tmp_path)
    vault.store("acc1", "token", Secret("x"), expires_at=_T0)
    items = vault.health()
    assert len(items) == 1
    assert items[0].account_id == "acc1"
    assert items[0].kind == "token"
    assert items[0].level is HealthLevel.EXPIRED  # 有效期已过
    assert items[0].expires_at == _T0
    assert items[0].revoked_at is None


def test_revoke_archives_marks_and_blocks_load(tmp_path):
    """ADR-016：撤销 = 旧值进历史 + 主引用删除 + 行标记 revoked；可重新 store 恢复。"""
    vault, audit = _vault(tmp_path)
    vault.store("acc1", "token", Secret("old-token"))
    vault.store("acc1", "machine_id", Secret("machine-1"))

    assert vault.revoke("acc1", reason="登录态失效") == 2
    assert vault.revoke("acc1", reason="重复撤销") == 0  # 幂等

    with pytest.raises(VaultCredentialRevoked):
        vault.load("acc1", ["token"])
    with pytest.raises(VaultCredentialRevoked):
        vault.load("acc1", ["machine_id"])

    history = vault.history("acc1", "token")
    assert len(history) == 1
    old_ref = history[0][0]
    assert old_ref.startswith(vault_ref("acc1", "token") + "#")
    assert vault._backend("memory").get(old_ref) == "old-token"  # 证据仍在

    items = {hp.kind: hp for hp in vault.health()}
    assert items["token"].revoked_at is not None
    assert items["token"].revoked_at.tzinfo is not None  # 前端按本地时区正确显示
    assert items["token"].revoked_reason == "登录态失效"
    kinds = [row["action"] for row in json.loads(audit.export_json()) if row["actor"] == "vault"]
    assert "vault.revoke" in kinds

    vault.store("acc1", "token", Secret("new-token"))  # 重新停靠 = 清撤销标记
    assert vault.load("acc1", ["token"])[0].expose() == "new-token"
    assert {hp.kind: hp for hp in vault.health()}["token"].revoked_at is None


def test_purge_删除账户时凭据行与历史一并清除(tmp_path):
    """删除账户专用（2026-11-19）：不留 revoked 行、不留 history，后端秘密也删。"""
    vault, _ = _vault(tmp_path)
    vault.store("acc1", "cookie", Secret("sid=abc"))
    vault.rotate("acc1", "cookie", Secret("sid=new"))  # 产生 #1 历史归档
    vault.store("acc1", "token", Secret("tk"))
    assert vault.purge("acc1") == 2
    assert vault.health() == []
    # 主引用与历史归档都不可再解密（后端已删）
    with pytest.raises(VaultCredentialMissing):
        vault.load("acc1", ["cookie"])
    with pytest.raises(VaultCredentialMissing):
        vault.load("acc1", ["token"])
    assert vault.purge("acc1") == 0  # 幂等


def test_health_empty_expiry_is_healthy(tmp_path):
    vault, _ = _vault(tmp_path)
    vault.store("acc1", "session-file", Secret("x"))  # 无期限 = 长期凭据
    assert vault.health()[0].level is HealthLevel.HEALTHY


# --- 多槽位（ADR-033 裁决 3）：同账户同 kind 多 key ---


def test_多槽位_同账户同kind互不覆盖且各自寻址(tmp_path):
    vault, _ = _vault(tmp_path)
    vault.store("acc1", "token", Secret("primary"), label="主 key")
    vault.store("acc1", "token", Secret("backup"), slot="backup", label="备用 key")

    assert vault.load("acc1", ["token"])[0].expose() == "primary"  # 默认槽不变
    assert vault.load("acc1", ["token"], slot="backup")[0].expose() == "backup"

    health = {(h.kind, h.slot): h for h in vault.health()}
    assert set(health) == {("token", "default"), ("token", "backup")}
    assert health[("token", "backup")].label == "备用 key"


def test_多槽位_撤销单槽不动其它槽(tmp_path):
    vault, _ = _vault(tmp_path)
    vault.store("acc1", "token", Secret("primary"))
    vault.store("acc1", "token", Secret("backup"), slot="backup")

    assert vault.revoke_slot("acc1", "token", "backup", reason="备用 key 泄露") is True
    assert vault.load("acc1", ["token"])[0].expose() == "primary"  # 主槽仍可用
    with pytest.raises(VaultCredentialRevoked):
        vault.load("acc1", ["token"], slot="backup")
    assert vault.revoke_slot("acc1", "token", "backup", reason="重复") is False  # 幂等

    # 撤销归档只落 backup 槽历史，default 槽无历史
    assert vault.history("acc1", "token", slot="backup")
    assert vault.history("acc1", "token", slot="default") == []


def test_多槽位_轮换历史按槽隔离(tmp_path):
    vault, _ = _vault(tmp_path)
    vault.store("acc1", "token", Secret("b1"), slot="backup")
    vault.rotate("acc1", "token", Secret("b2"), slot="backup")
    history = vault.history("acc1", "token", slot="backup")
    assert len(history) == 1
    old_ref = history[0][0]
    assert old_ref.startswith(vault_ref("acc1", "token", "backup") + "#")
    assert vault._backend("memory").get(old_ref) == "b1"


def test_多槽位_purge清空全部槽(tmp_path):
    vault, _ = _vault(tmp_path)
    vault.store("acc1", "token", Secret("primary"))
    vault.store("acc1", "token", Secret("backup"), slot="backup")
    assert vault.purge("acc1") == 2
    assert vault.health() == []
    with pytest.raises(VaultCredentialMissing):
        vault.load("acc1", ["token"], slot="backup")


def test_旧表迁移_全部行落默认槽且秘密引用不变(tmp_path):
    """ADR-033：老库 vault_item（PK account_id, kind）重建后零迁移。"""
    import sqlite3

    db = tmp_path / "legacy.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE vault_item (
            account_id TEXT NOT NULL, kind TEXT NOT NULL, backend TEXT NOT NULL,
            expires_at TEXT, created_at TEXT, rotated_at TEXT,
            revoked_at TEXT, revoked_reason TEXT,
            PRIMARY KEY (account_id, kind)
        );
        CREATE TABLE vault_history (
            seq INTEGER PRIMARY KEY AUTOINCREMENT, account_id TEXT NOT NULL,
            kind TEXT NOT NULL, archived_ref TEXT NOT NULL, rotated_at TEXT NOT NULL
        );
        """
    )
    conn.execute(
        "INSERT INTO vault_item VALUES ('acc1','token','memory',NULL,"
        "'2026-11-10T12:00:00+00:00',NULL,NULL,'')"
    )
    conn.execute(
        "INSERT INTO vault_history (account_id, kind, archived_ref, rotated_at)"
        " VALUES ('acc1','token','acc1:token#0','2026-11-10T12:00:00+00:00')"
    )
    conn.commit()
    conn.close()

    legacy = LayeredVault(
        db, {"memory": MemoryVaultBackend()}, default_backend="memory",
        audit=SqliteAuditLog(tmp_path / "a2.db"),
    )
    cols = {r[1] for r in legacy._connect().execute("PRAGMA table_info(vault_item)")}
    assert {"slot", "id", "label", "updated_at"} <= cols
    rows = legacy.health()
    assert [(h.account_id, h.kind, h.slot) for h in rows] == [("acc1", "token", "default")]
    hist = legacy.history("acc1", "token", slot="default")
    assert hist[0][0] == "acc1:token#0"  # 历史槽位回填 default，归档引用不变



def test_memory_backend_missing_is_explicit(tmp_path):
    with pytest.raises(VaultCredentialMissing):
        MemoryVaultBackend().get("nope")


def test_persistence_across_instances(tmp_path):
    # memory 后端本身不跨进程——持久性 = SQLite 元数据（这个测试验的）
    # + 后端对象存活时 secrets 仍可达；真跨进程持久由 keychain/credman 层承担
    shared = MemoryVaultBackend()
    audit1, audit2 = SqliteAuditLog(tmp_path / "a.db"), SqliteAuditLog(tmp_path / "a.db")
    vault = LayeredVault(
        tmp_path / "v.db", {"memory": shared}, default_backend="memory", audit=audit1
    )
    vault.store("acc1", "cookie", Secret("persistent"))

    again = LayeredVault(
        tmp_path / "v.db", {"memory": shared}, default_backend="memory", audit=audit2
    )
    assert again.health()[0].kind == "cookie"  # 元数据从库重建
    assert again.load("acc1", ["cookie"])[0].expose() == "persistent"


# --- Windows 凭据管理器（假 api 驱动，不碰 ctypes）---


class FakeWinApi:
    """advapi32 形状：read/write/delete 语义用 dict 模拟。"""

    def __init__(self):
        self.data: dict[str, bytes] = {}

    def write(self, target, blob):
        self.data[target] = blob

    def read(self, target):
        try:
            return self.data[target]
        except KeyError as e:
            from butler_engine.vault.errors import VaultCredentialMissing

            raise VaultCredentialMissing(f"凭据管理器没有 {target!r} 的记录") from e

    def delete(self, target):
        self.data.pop(target, None)


def test_windows_backend_roundtrip_with_fake_api():
    api = FakeWinApi()
    backend = WindowsCredmanBackend(api_factory=lambda: api)
    backend.put("acc1:cookie", "dpapi-protected")
    assert backend.get("acc1:cookie") == "dpapi-protected"
    assert api.data["butler.vault:acc1:cookie"] == b"dpapi-protected"  # blob utf-8
    backend.delete("acc1:cookie")
    with pytest.raises(VaultCredentialMissing):
        backend.get("acc1:cookie")


def test_windows_backend_migrates_legacy_prefix_once():
    api = FakeWinApi()
    api.data["marina.vault:old:cookie"] = b"legacy-secret"  # 旧品牌条目
    backend = WindowsCredmanBackend(api_factory=lambda: api)
    assert backend.migrate_legacy_refs(["old:cookie"]) == ["old:cookie"]
    assert api.data["butler.vault:old:cookie"] == b"legacy-secret"  # 已回写新前缀
    assert api.data["marina.vault:old:cookie"] == b"legacy-secret"  # 旧条目保留
    assert backend.get("old:cookie") == "legacy-secret"  # 运行时只认新前缀
    with pytest.raises(VaultCredentialMissing):
        backend.get("ghost:cookie")  # 无运行时读穿分支


def test_windows_backend_does_not_overwrite_newer_value_with_legacy():
    """只回填不覆盖：新前缀已有值（如 dock 刚写的）时，旧前缀残留不得回退它。"""
    api = FakeWinApi()
    api.data["marina.vault:old:cookie"] = b"legacy-secret"  # 历史条目（旧值）
    api.data["butler.vault:old:cookie"] = b"newer-secret"  # 已迁移后又写入的新值
    backend = WindowsCredmanBackend(api_factory=lambda: api)
    assert backend.migrate_legacy_refs(["old:cookie"]) == []  # 不迁移、不覆盖
    assert api.data["butler.vault:old:cookie"] == b"newer-secret"
    assert backend.get("old:cookie") == "newer-secret"


def test_windows_backend_still_missing_when_no_legacy():
    api = FakeWinApi()
    backend = WindowsCredmanBackend(api_factory=lambda: api)
    with pytest.raises(VaultCredentialMissing):
        backend.get("ghost:cookie")


def test_windows_backend_refuses_off_windows_without_api():
    import sys

    if sys.platform.startswith("win"):  # 真 Windows 上本来就该能建
        pytest.skip("本机即 Windows")
    from butler_engine.vault.errors import VaultAccessError

    with pytest.raises(VaultAccessError):
        WindowsCredmanBackend(api_factory=None)


# --- macOS Keychain 后端（假 runner 驱动，不碰真钥匙串）---


class FakeRunner:
    """`security` 命令替换替身。按 security 语义解析旗标（-U 是布尔旗标）。"""

    def __init__(self):
        self.items: dict[tuple, str] = {}
        self.commands: list[list[str]] = []

    def _flags(self, cmd) -> dict[str, str | None]:
        flags: dict[str, str | None] = {}
        i = 1  # 0=security，1=子命令
        while i < len(cmd):
            token = cmd[i]
            if token in ("-s", "-a"):
                flags[token] = cmd[i + 1]
                i += 2
            elif token == "-w":
                # 命令末尾的 -w（无值）= "输出密码"；中间出现则是新密码值
                flags[token] = cmd[i + 1] if i + 1 < len(cmd) else None
                i += 2 if flags[token] is not None else 1
            else:
                i += 1  # 布尔旗标（-U 等）
        return flags

    def __call__(self, cmd, capture_output=True, text=True):
        self.commands.append(cmd)
        subcommand = cmd[1]
        flags = self._flags(cmd)
        key = (flags["-s"], flags["-a"])
        if subcommand == "add-generic-password":
            self.items[key] = flags["-w"]
            return _Result(0)
        if subcommand == "find-generic-password":
            if key not in self.items:
                return _Result(44, stderr="security: item not found")
            return _Result(0, stdout=self.items[key] + "\n")
        if subcommand == "delete-generic-password":
            if key in self.items:
                del self.items[key]
                return _Result(0)
            return _Result(44)
        raise AssertionError(f"未知 security 子命令 {cmd}")


class _Result:
    def __init__(self, returncode, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_keychain_backend_signature_and_roundtrip_with_fake_runner():
    runner = FakeRunner()
    backend = KeychainBackend(runner=runner)
    backend.put("acc1:token", "kc-secret")
    assert backend.get("acc1:token") == "kc-secret"
    # 命令签名审计：service 固定、秘密走 -w、-a 带 ref
    add = runner.commands[0]
    assert add[0] == "security" and "-U" in add and "-w" in add
    assert "-a" in add and add[add.index("-a") + 1] == "acc1:token"
    assert add[add.index("-s") + 1] == "butler.vault"


def test_keychain_migrates_legacy_service_once():
    runner = FakeRunner()
    runner.items[("marina.vault", "old:token")] = "legacy-secret"  # 旧品牌条目
    backend = KeychainBackend(runner=runner)
    assert backend.migrate_legacy_refs(["old:token"]) == ["old:token"]
    assert runner.items[("butler.vault", "old:token")] == "legacy-secret"  # 已回写
    assert runner.items[("marina.vault", "old:token")] == "legacy-secret"  # 旧条目保留
    assert backend.get("old:token") == "legacy-secret"  # 运行时只认新 service


def test_keychain_migration_does_not_overwrite_newer_value():
    runner = FakeRunner()
    runner.items[("marina.vault", "old:token")] = "legacy-secret"
    runner.items[("butler.vault", "old:token")] = "newer-secret"
    backend = KeychainBackend(runner=runner)
    assert backend.migrate_legacy_refs(["old:token"]) == []
    assert runner.items[("butler.vault", "old:token")] == "newer-secret"


def test_keychain_get_missing_maps_to_explicit_error():
    runner = FakeRunner()
    backend = KeychainBackend(runner=runner)
    with pytest.raises(VaultCredentialMissing):
        backend.get("ghost:token")


def test_keychain_failure_raises_access_error():
    def bad_runner(cmd, capture_output=True, text=True):
        return _Result(1, stderr="keychain is locked")

    backend = KeychainBackend(runner=bad_runner)
    from butler_engine.vault.errors import VaultAccessError

    with pytest.raises(VaultAccessError):
        backend.delete("acc1:token")


# --- 健康状态存储 ---


def test_health_state_store_roundtrip(tmp_path):
    store = SqliteHealthStateStore(tmp_path / "s.db")
    assert store.get_account_level("a1") is None
    store.set_account_level("a1", HealthLevel.INVALID)
    assert store.get_account_level("a1") is HealthLevel.INVALID
    store.set_account_level("a1", HealthLevel.EXPIRING)  # 覆盖更新
    assert store.get_account_level("a1") is HealthLevel.EXPIRING

    assert store.get_credential_notified_level("a1", "cookie") is None
    store.set_credential_notified_level("a1", "cookie", HealthLevel.EXPIRED)
    assert store.get_credential_notified_level("a1", "cookie") == HealthLevel.EXPIRED.value


# --- 每日 job ---


def test_interval_job_run_once_and_stop():
    calls = []
    job = IntervalJob(
        lambda: calls.append(1), interval=timedelta(hours=24), name="t"
    )
    job.run_once()
    assert len(calls) == 1
    assert not job.running
    job.start()
    assert job.running
    job.stop()
    assert not job.running


def test_interval_job_survives_bad_fn():
    import time

    state = {"n": 0}

    def flaky():
        state["n"] += 1
        if state["n"] == 1:
            raise RuntimeError("第一次炸")

    job = IntervalJob(flaky, interval=timedelta(milliseconds=15), name="flaky")
    job.start()
    try:
        deadline = time.time() + 2.0
        while time.time() < deadline and state["n"] < 2:
            time.sleep(0.01)
    finally:
        job.stop()
    assert state["n"] >= 2  # 第一次失败，第二次照跑（隔离语义）


# --- bridge 端到端：Vault → 扫描 → 事件 → 通知 ---


def test_bridge_scan_flow(tmp_path):
    from butler_engine.bridge import build_engine

    kit = build_engine(tmp_path / "butler.db")
    try:
        # EngineKit 装配完整性：Vault / 两个 L0 用例 / 扫描 job 未启动（端显式启动）
        assert kit.vault is not None
        assert kit.scan_credential_expiry.vault is kit.vault
        assert kit.assess_account_health.vault is kit.vault
        assert kit.scan_job is None
    finally:
        kit.close()


def test_bridge_default_backend_selection_docs():
    from butler_engine.bridge import _secret_backends

    backends, default = _secret_backends()
    if sys_platform_is_mac():
        assert default == "keychain"
    elif sys_platform_is_win():
        assert default == "credman"
    else:
        assert default == "memory"  # 显式降级 + 日志告警
    assert "memory" in backends  # 内存层永远在装配里


def sys_platform_is_mac():
    import sys

    return sys.platform == "darwin"


def sys_platform_is_win():
    import sys

    return sys.platform.startswith("win")
