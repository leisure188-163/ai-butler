"""每 profile 一账户槽（ADR-011，browser.py 多 profile 捕获）离线测试。

从 test_browser_capture 按域拆出（conventions/4 §2.2）：编键语义（main 存量
卡位 + slug 键）、目录去重、逐 profile 隔离与事故出账。链路替身与 fixture
复用 capture 模块的（mac CBC 链 + 真注册表）。
"""

import json

from test_browser_capture import (
    COOKIES,
    MemAccounts,
    MemVault,
    _capture_kind,
    capture_spec,
    mac_env,  # noqa: F401 - pytest fixture（mac CBC 链 + Keychain 替身）
    make_cookie_db,
    mac_rows,
    registry,  # noqa: F401 - pytest fixture（真包注册表）
)

from butler_core.accounts.usecases.register_account import RegisterAccount
from butler_connectors.browser import capture_cookies
from butler_connectors.registry import DockContext


def test_two_profiles_two_slots(tmp_path, mac_env):
    """每 profile 一账户（ADR-011）：Default→main（存量卡位）、Profile 1→slug 键。"""
    make_cookie_db(
        tmp_path / "Chrome" / "Default" / "Cookies",
        mac_rows(mac_env, {COOKIES[0]: (b"v-d-0", 0), COOKIES[1]: (b"v-d-1", 0)}),
    )
    make_cookie_db(
        tmp_path / "Chrome" / "Profile 1" / "Cookies",
        mac_rows(mac_env, {COOKIES[0]: (b"v-p-0", 0), COOKIES[1]: (b"v-p-1", 0)}),
    )
    captured, issues = _capture_kind(
        capture_spec().auth, "chatgpt_web", [str(tmp_path / "Chrome/*/Cookies")]
    )
    assert issues == [], issues
    assert [(c.account_code, c.profile_dir) for c in captured] == [
        ("main", "Default"),
        ("profile-1", "Profile 1"),
    ]
    assert [c["value"] for c in json.loads(captured[0].envelope)["cookies"]] == ["v-d-0", "v-d-1"]
    assert [c["value"] for c in json.loads(captured[1].envelope)["cookies"]] == ["v-p-0", "v-p-1"]


def test_two_slots_full_chain_via_registry(tmp_path, mac_env, registry):
    """注册表全链：双 profile → 双账户槽入库 + 展示名带 profile 目录事实。"""
    make_cookie_db(
        tmp_path / "Chrome" / "Default" / "Cookies",
        mac_rows(mac_env, {COOKIES[0]: (b"v-d-0", 0), COOKIES[1]: (b"v-d-1", 0)}),
    )
    make_cookie_db(
        tmp_path / "Chrome" / "Profile 1" / "Cookies",
        mac_rows(mac_env, {COOKIES[0]: (b"v-p-0", 0), COOKIES[1]: (b"v-p-1", 0)}),
    )
    accounts = MemAccounts()
    vault = MemVault()
    platform = registry.get("chatgpt_web")
    outcome = capture_cookies(
        platform,
        platform.declarative["session.import"],
        ("browser_cookie",),
        DockContext(
            vault=vault,
            register=RegisterAccount(accounts=accounts),
            storage_override=[str(tmp_path / "Chrome/*/Cookies")],
        ),
    )
    assert outcome.issues == [], outcome.issues
    assert outcome.accounts == ["chatgpt_web:main", "chatgpt_web:profile-1"]
    assert accounts.rows["chatgpt_web:main"].account_name == "ChatGPT"
    assert accounts.rows["chatgpt_web:profile-1"].account_name == "ChatGPT（Profile 1）"
    assert (
        json.loads(vault.items[("chatgpt_web:main", "browser_cookie")][0].expose())["cookies"][0]["value"]
        == "v-d-0"
    )
    assert (
        json.loads(vault.items[("chatgpt_web:profile-1", "browser_cookie")][0].expose())["cookies"][0]["value"]
        == "v-p-0"
    )


def test_rescan_replays_existing_slots(tmp_path, mac_env, registry):
    """重扫幂等回放：同身份重复停靠不覆盖不改号（register_account 幂等）。"""
    make_cookie_db(
        tmp_path / "Chrome" / "Default" / "Cookies",
        mac_rows(mac_env, {COOKIES[0]: (b"v-d-0", 0), COOKIES[1]: (b"v-d-1", 0)}),
    )
    make_cookie_db(
        tmp_path / "Chrome" / "Profile 1" / "Cookies",
        mac_rows(mac_env, {COOKIES[0]: (b"v-p-0", 0), COOKIES[1]: (b"v-p-1", 0)}),
    )
    accounts = MemAccounts()
    platform = registry.get("chatgpt_web")

    def dock_once():
        return capture_cookies(
            platform,
            platform.declarative["session.import"],
            ("browser_cookie",),
            DockContext(
                vault=MemVault(),
                register=RegisterAccount(accounts=accounts),
                storage_override=[str(tmp_path / "Chrome/*/Cookies")],
            ),
        )

    first = dock_once()
    second = dock_once()
    assert first.accounts == second.accounts == ["chatgpt_web:main", "chatgpt_web:profile-1"]


def test_same_profile_dual_layout_dedup(tmp_path, mac_env):
    """同 profile 目录新旧布局并配（legacy Cookies + Network/Cookies）：
    目录去重只取首个库（路径序），不出重复账户槽。"""
    make_cookie_db(
        tmp_path / "Chrome" / "Default" / "Cookies",
        mac_rows(mac_env, {COOKIES[0]: (b"v-old-0", 0), COOKIES[1]: (b"v-old-1", 0)}),
    )
    make_cookie_db(
        tmp_path / "Chrome" / "Default" / "Network" / "Cookies",
        mac_rows(mac_env, {COOKIES[0]: (b"v-new-0", 0), COOKIES[1]: (b"v-new-1", 0)}),
    )
    captured, issues = _capture_kind(
        capture_spec().auth,
        "chatgpt_web",
        [str(tmp_path / "Chrome/*/Cookies"), str(tmp_path / "Chrome/*/Network/Cookies")],
    )
    assert issues == [], issues
    assert len(captured) == 1
    assert captured[0].account_code == "main" and captured[0].profile_dir == "Default"
    assert [c["value"] for c in json.loads(captured[0].envelope)["cookies"]] == ["v-old-0", "v-old-1"]


def test_incomplete_profile_falls_through(tmp_path, mac_env):
    """首个 profile 缺名单 → 非事故静候下一个；Profile 1 凑齐 = main 槽。"""
    make_cookie_db(
        tmp_path / "Chrome" / "Default" / "Cookies",
        mac_rows(mac_env, {COOKIES[0]: (b"v-d-0", 0)}),
    )
    make_cookie_db(
        tmp_path / "Chrome" / "Profile 1" / "Cookies",
        mac_rows(mac_env, {COOKIES[0]: (b"v-p-0", 0), COOKIES[1]: (b"v-p-1", 0)}),
    )
    captured, issues = _capture_kind(
        capture_spec().auth, "chatgpt_web", [str(tmp_path / "Chrome/*/Cookies")]
    )
    assert issues == [], issues
    assert captured[0].account_code == "main"  # 缺名单不是事故：Profile 1 首个凑齐保存量卡位
    envelope = json.loads(captured[0].envelope)
    assert [c["value"] for c in envelope["cookies"]] == ["v-p-0", "v-p-1"]


def test_profile_failure_falls_through_to_next(tmp_path, mac_env):
    """逐 profile 隔离：首个库读不了（垃圾形状）→ 记原因换下一个；凑齐者胜。"""
    bad = tmp_path / "Chrome" / "Default" / "Cookies"
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_bytes(b"this is not a sqlite database")
    make_cookie_db(
        tmp_path / "Chrome" / "Profile 1" / "Cookies",
        mac_rows(mac_env, {COOKIES[0]: (b"v-ok-0", 0), COOKIES[1]: (b"v-ok-1", 0)}),
    )
    captured, issues = _capture_kind(
        capture_spec().auth, "chatgpt_web", [str(tmp_path / "Chrome/*/Cookies")]
    )
    assert captured, "坏库换下一个后应有凑齐槽"
    envelope = json.loads(captured[0].envelope)
    assert [c["value"] for c in envelope["cookies"]] == ["v-ok-0", "v-ok-1"]


def test_all_profiles_failed_reports_first_issue(tmp_path, mac_env):
    """全 profile 失败 → 报首个显式原因（库序确定），不再误报未登录。"""
    bad = tmp_path / "Chrome" / "Default" / "Cookies"
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_bytes(b"garbage bytes, not a database")
    captured, issues = _capture_kind(
        capture_spec().auth, "chatgpt_web", [str(tmp_path / "Chrome/*/Cookies")]
    )
    assert captured == []
    assert issues and "查询失败" in issues[0]
    assert "未登录" not in issues[0]
