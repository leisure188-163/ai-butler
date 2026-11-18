"""自定义平台（2026-11-18）：草稿渲染 → 声明式连接器文件 → 装载。

覆盖点：
- 渲染出的 manifest/声明与内置连接器同构（id/kind/credential/五段式齐全）
- 完整装载链校验（manifest schema + 声明式 schema + 主凭据交叉校验）
- 撞内置 id 拒绝、非法编码/空 cookie 拒绝、adapter 拒绝
- 删除后不再出现在目录列表
"""

from __future__ import annotations

import pytest
import yaml

from butler_connectors.custom import (
    CustomPlatformDraft,
    delete_custom_platform,
    list_custom_platforms,
    render_bundle,
    save_custom_platform,
)
from butler_connectors.manifest import ManifestInvalid, _Strict
from butler_connectors.paths import custom_connectors_root
from butler_connectors.registry import load_registry


def _draft(**overlap) -> CustomPlatformDraft:
    payload = {
        "code": "demo_site",
        "display": "Demo Site",
        "domain": "demo.example.com",
        "cookies": ["sid"],
        "status": {
            "request": {"method": "GET", "url": "https://demo.example.com/api/status"},
            "checked_in_path": "data.checked_in",
        },
        "claim": {
            "request": {"method": "POST", "url": "https://demo.example.com/api/claim"},
            "expect_ok": "0",
        },
        "schedule_times": ["08:35"],
    }
    payload.update(overlap)
    return CustomPlatformDraft.model_validate(payload)


def test_render_bundle_shape():
    bundle = render_bundle(_draft())
    manifest = bundle["manifest.yaml"]
    assert manifest["id"] == "demo_site"
    assert manifest["kind"] == "web"
    assert manifest["credential"] == {"kinds": ["browser_cookie"], "unlock": "browser"}
    assert manifest["capabilities"]["provision.run"]["entry"] == "declarative/provision.run.yaml"
    assert manifest["schedule"]["provision.run"]["times"] == ["08:35"]
    assert manifest["usage"] is False

    provision = bundle["declarative/provision.run.yaml"]
    assert provision["auth"]["kind"] == "browser_cookie"
    assert provision["auth"]["domain"] == "demo.example.com"
    assert provision["auth"]["cookies"] == ["sid"]
    # 状态判定用单布尔模式时，不带 list_path（避免判定语义含糊）
    assert provision["status"]["checked_in_path"] == "data.checked_in"
    assert "list_path" not in provision["status"]
    assert provision["claim"]["confirm_by_status"] is True
    assert provision["business_codes"] == {"401": "EXPIRED", "403": "NO_AUTH"}

    capture = bundle["declarative/session.import.yaml"]
    assert capture["auth"]["browser"] == "chrome"


def test_save_then_load(tmp_path):
    save_custom_platform(_draft(), tmp_path)
    registry = load_registry(custom_root=tmp_path)
    assert "demo_site" in registry.ids()
    platform = registry.get("demo_site")
    assert platform.display == "Demo Site"
    assert set(platform.declarative) == {"provision.run", "session.import"}
    assert "demo_site" in registry.provision_ports(vault=None)


def test_save_overwrites_existing(tmp_path):
    save_custom_platform(_draft(), tmp_path)
    save_custom_platform(_draft(display="Demo Two", schedule_times=[]), tmp_path)
    manifest = yaml.safe_load((tmp_path / "demo_site" / "manifest.yaml").read_text(encoding="utf-8"))
    assert manifest["display"] == "Demo Two"
    assert "schedule" not in manifest


def test_collision_with_builtin_rejected(tmp_path):
    """落盘前校验就撞车：内置 id 不许被自定义目录覆盖（连文件都不写）。"""
    with pytest.raises(ManifestInvalid, match="与内置同 id"):
        save_custom_platform(_draft(code="trae_cn", domain="trae.cn"), tmp_path)
    assert not (tmp_path / "trae_cn").exists()


def test_invalid_code_rejected():
    with pytest.raises(ManifestInvalid, match="平台编码"):
        _draft(code="Demo-Site")


def test_empty_cookies_rejected():
    with pytest.raises(ManifestInvalid, match="cookie"):
        _draft(cookies=[])


def test_adapter_capability_rejected(tmp_path):
    """自定义目录放开 adapter = 放开任意代码装载，装载期必须拒绝。"""
    target = tmp_path / "evil_site"
    (target / "declarative").mkdir(parents=True)
    (target / "manifest.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "evil_site",
                "display": "Evil",
                "kind": "web",
                "capabilities": {
                    "provision.run": {"kind": "adapter", "entry": "evil.module:port"}
                },
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ManifestInvalid, match="只支持声明式能力"):
        load_registry(custom_root=tmp_path)


def test_entry_escape_rejected(tmp_path):
    """声明式 entry 不许跳出连接器目录（自定义目录文件不由项目维护）。"""
    out = tmp_path / "escape_site"
    out.mkdir()
    (tmp_path / "secret.yaml").write_text(
        yaml.safe_dump({"auth": {"kind": "browser_cookie"}}), encoding="utf-8"
    )
    (out / "manifest.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "escape_site",
                "display": "Escape",
                "kind": "web",
                "capabilities": {
                    "provision.run": {"kind": "declarative", "entry": "../secret.yaml"}
                },
                "credential": {"kinds": ["browser_cookie"], "unlock": "browser"},
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ManifestInvalid, match="必须位于连接器目录内"):
        load_registry(custom_root=tmp_path)


def test_list_and_delete(tmp_path):
    save_custom_platform(_draft(), tmp_path)
    assert list_custom_platforms(tmp_path) == [{"code": "demo_site", "display": "Demo Site"}]
    assert delete_custom_platform("demo_site", tmp_path) is True
    assert list_custom_platforms(tmp_path) == []
    assert delete_custom_platform("demo_site", tmp_path) is False
    with pytest.raises(ManifestInvalid):
        delete_custom_platform("../x", tmp_path)


def test_custom_root_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("BUTLER_CUSTOM_CONNECTORS", str(tmp_path / "mine"))
    assert custom_connectors_root() == tmp_path / "mine"


def test_strict_model_rejects_unknown_field():
    """草稿模型沿用 extra=forbid：前端多传字段直接爆，不静默吞。"""
    with pytest.raises(Exception):
        CustomPlatformDraft.model_validate(
            {
                "code": "demo_site",
                "display": "Demo",
                "domain": "d.com",
                "cookies": ["c"],
                "status": {
                    "request": {"url": "https://d.com/s"},
                    "checked_in_path": "ok",
                },
                "claim": {"request": {"url": "https://d.com/c"}},
                "extra_field": 1,
            }
        )
