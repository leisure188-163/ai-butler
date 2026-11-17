"""连接器注册表（registry）：装载 / 方言注册 / 调度条目 / manifest 校验。"""

import pytest
import yaml

from butler_core.execution.domain import ActionKind
from butler_core.shared.results import Status, UnknownEngineCode, from_engine
from butler_connectors.manifest import ConnectorManifest, ManifestInvalid
from butler_connectors.registry import DockContext, load_registry


@pytest.fixture(scope="module")
def registry():
    return load_registry()


def test_trae_loaded_with_shape(registry):
    assert registry.ids() == [
        "agentrouter",  # 网页登录即签到（adapter：浏览器页面状态读取）
        "chatgpt_web",  # R3 网页会话通道（A2-03）：仅 session.import + health.check
        "claude_web",
        "doubao_cn",
        "qoder_cn",
        "trae_cn",
        "workbuddy_cn",
    ]  # 按目录名排序
    app = registry.get("trae_cn")
    assert app.display == "Trae CN"
    assert app.manifest.capabilities[ActionKind.PROVISION_RUN.value].kind == "declarative"
    qoder = registry.get("qoder_cn")  # ADR-006：声明式扩展接入，零 per-app 代码
    assert qoder.display == "Qoder"  # CN/Global 双账户同一 provider
    assert qoder.manifest.credential.kinds == ["dpapi_gcm_v10", "umid_cosy"]
    workbuddy = registry.get("workbuddy_cn")  # ADR-008：端口实现接入（加密凭据解密链）
    assert workbuddy.display == "WorkBuddy CN"
    assert workbuddy.manifest.capabilities[ActionKind.PROVISION_RUN.value].kind == "adapter"
    assert workbuddy.manifest.credential is None  # 现用现取零 vault：不申报 kind
    router = registry.get("agentrouter")
    assert router.manifest.capabilities[ActionKind.PROVISION_RUN.value].kind == "adapter"
    assert router.manifest.credential.kinds == ["browser_session"]
    web = registry.get("chatgpt_web")  # A2-03：网页连接器无 provision.run，无调度
    assert "provision.run" not in web.manifest.capabilities
    assert web.manifest.credential.kinds == ["browser_cookie"]


def test_capability_ids_constrained_to_actionkind():
    bad = dict(_BAD_MANIFEST)
    bad["capabilities"] = {"provision.gift": {"kind": "adapter", "entry": "a.b"}}
    with pytest.raises(ManifestInvalid, match="ActionKind"):
        ConnectorManifest.model_validate(bad)


_BAD_MANIFEST = {
    "id": "x",
    "display": "X",
    "capabilities": {},
    "credential": {"kinds": ["ss_aes"], "unlock": "local-client"},
}


def test_manifest_extra_field_rejected():
    """声明里出现 schema 外字段（私货）→ 必须爆，不静默忽略（红线 5）。"""
    bad = dict(_BAD_MANIFEST)
    bad["capabilities"] = {
        ActionKind.PROVISION_RUN.value: {"kind": "declarative", "entry": "x.yaml"}
    }
    bad["sneaky_key"] = "nope"  # 私货
    with pytest.raises(Exception) as exc:
        ConnectorManifest.model_validate(bad)
    assert "sneaky_key" in str(exc.value)


def test_dialect_registered_adr002(registry):
    assert from_engine("1001", dialect="trae_cn") is Status.NO_AUTH
    assert from_engine("9074", dialect="trae_cn") is Status.PENDING
    assert from_engine("9004", dialect="trae_cn") is Status.FAILED
    with pytest.raises(UnknownEngineCode):
        from_engine("54321", dialect="trae_cn")


def test_schedule_entries_shape(registry):
    assert registry.schedule_entries() == [
        {
            "target": "agentrouter",
            "times": ["00:05", "09:05"],
            "refresh_at": "00:00",
            "budget_seconds": 120,
        },
        {
            "target": "doubao_cn",
            "times": ["09:15", "13:15", "19:15", "23:15"],
            "refresh_at": "00:00",  # adapter 必须显式（declarative 回落不适用）
            "budget_seconds": 240,
        },
        {
            "target": "qoder_cn",
            "times": ["10:05", "13:05", "19:05", "23:05"],
            "refresh_at": "10:00",
            "budget_seconds": 240,
        },
        {
            "target": "trae_cn",
            "times": ["09:05", "13:05", "19:05", "23:05"],
            "refresh_at": "00:00",
            "budget_seconds": 240,
        },
        {
            "target": "workbuddy_cn",
            "times": ["09:15", "13:15", "19:15", "23:15"],
            "refresh_at": "00:00",  # adapter 必须显式（同 doubao）
            "budget_seconds": 120,
        },
    ]


def test_dock_unknown_connector_rejected(registry):
    from io import StringIO

    import typer  # 占位防误删说明：DockContext 属 registry 模块面

    with pytest.raises(KeyError, match="ghost"):
        registry.dock(DockContext(vault=None, register=None), target="ghost")


def test_adapter_build_port_receives_transport(monkeypatch):
    """adapter 契约：build_port 收 (vault=, transport=)——与 declarative 共用注入面。"""
    import sys
    import types
    from pathlib import Path

    mod = types.ModuleType("butler_connectors.stub_boot.adapter")
    seen: dict = {}

    class _Boot:
        def build_port(self, *, vault, transport=None):
            seen.update(vault=vault, transport=transport)
            return object()

    mod.butler = _Boot()
    monkeypatch.setitem(sys.modules, "butler_connectors.stub_boot.adapter", mod)
    from butler_connectors.registry import ConnectorApp, Registry

    manifest = ConnectorManifest.model_validate(
        {
            "id": "stub_boot",
            "display": "Stub",
            "capabilities": {
                "provision.run": {"kind": "adapter", "entry": "adapter.butler"}
            },
        }
    )
    registry = Registry({"stub_boot": ConnectorApp(manifest=manifest, root=Path("."))})
    sentinel_vault, sentinel_transport = object(), object()
    registry.provision_ports(vault=sentinel_vault, transport=sentinel_transport)
    assert seen["vault"] is sentinel_vault
    assert seen["transport"] is sentinel_transport


def test_workbuddy_adapter_port_built_via_registry(registry):
    """Registry assembly surface: workbuddy adapter port produced by provision_ports, transport passes through."""
    from butler_connectors.workbuddy_cn.adapter import WorkbuddyProvisionPort

    sentinel = object()
    ports = registry.provision_ports(vault=None, transport=sentinel)
    port = ports["workbuddy_cn"]
    assert isinstance(port, WorkbuddyProvisionPort)
    assert port.transport is sentinel


def test_usage_ports_loaded_for_all_four(registry):
    """R2：申报 usage.collect 的连接器装载为用量端口；auth/kinds 按主链透传。"""
    from butler_connectors.doubao_cn.usage import DoubaoUsagePort
    from butler_connectors.qoder_cn.usage import QoderUsagePort
    from butler_connectors.trae_cn.usage import TraeUsagePort
    from butler_connectors.workbuddy_cn.usage import WorkbuddyUsagePort

    sentinel = object()
    ports = registry.usage_ports(vault=None, transport=sentinel)
    assert set(ports) == {"trae_cn", "qoder_cn", "doubao_cn", "workbuddy_cn"}
    assert isinstance(ports["trae_cn"], TraeUsagePort)
    assert isinstance(ports["qoder_cn"], QoderUsagePort)
    assert isinstance(ports["doubao_cn"], DoubaoUsagePort)
    assert isinstance(ports["workbuddy_cn"], WorkbuddyUsagePort)
    # 复用 provision 鉴权链的通道拿到 auth 声明与 kinds；纯 adapter 通道为空
    assert ports["trae_cn"].auth is not None
    assert ports["trae_cn"].kinds == ("ss_aes", "device_dn")
    assert ports["qoder_cn"].auth is not None
    assert ports["qoder_cn"].kinds == ("dpapi_gcm_v10", "umid_cosy")
    assert ports["doubao_cn"].auth is None and ports["doubao_cn"].kinds == ()
    assert ports["workbuddy_cn"].transport is sentinel


def test_usage_collect_declarative_rejected():
    """usage.collect 只认 adapter（用量编排各家专属）——其他 kind 显式爆。"""
    from pathlib import Path

    from butler_connectors.registry import ConnectorApp, Registry

    manifest = ConnectorManifest.model_validate(
        {
            "id": "stub_boot",
            "display": "Stub",
            "capabilities": {
                "usage.collect": {"kind": "declarative", "entry": "x.yaml"}
            },
        }
    )
    registry = Registry({"stub_boot": ConnectorApp(manifest=manifest, root=Path("."))})
    with pytest.raises(ManifestInvalid, match="adapter"):
        registry.usage_ports(vault=None, transport=None)


def test_load_registry_imports_adapter_entry(monkeypatch, tmp_path):
    """装载即 import adapter entry：方言自注册生效 + 坏 entry 装载期显式爆。"""
    import sys
    import types

    from butler_connectors import registry as registry_mod

    mod = types.ModuleType("butler_connectors.stub_boot.adapter")

    class _Boot:
        def build_port(self, *, vault, transport=None): ...

        def dock(self, ctx): ...

    mod.butler = _Boot()
    # 观察点：load_registry 对 adapter 能力必须触发 _load_entry_module（真实现走 importlib，
    # sys.modules 预插假模块即命中，无需起真包）
    seen: list[tuple[str, str]] = []
    real_load = registry_mod._load_entry_module

    def spy(conn_id, entry):
        seen.append((conn_id, entry))
        return real_load(conn_id, entry)

    monkeypatch.setattr(registry_mod, "_load_entry_module", spy)
    monkeypatch.setitem(sys.modules, "butler_connectors.stub_boot.adapter", mod)
    monkeypatch.setattr(
        registry_mod, "package_root", lambda conn_id=None: _fake_package(tmp_path)
    )
    registry_mod.load_registry()
    assert seen == [("stub_boot", "adapter.butler")]  # 装载即 import 发生过


def test_load_registry_bad_adapter_entry_raises(monkeypatch, tmp_path):
    """坏 adapter entry（模块不存在）装载期显式爆，不留到首次 run（红线 5）。"""
    import pytest

    from butler_connectors import registry as registry_mod

    monkeypatch.setattr(
        registry_mod, "package_root", lambda conn_id=None: _fake_package(
            tmp_path, entry="ghost.butler"
        )
    )
    with pytest.raises(ImportError):
        registry_mod.load_registry()


def _fake_package(tmp_path, entry: str = "adapter.butler"):
    """临时包根里的一枚假 adapter 连接器目录（manifest.yaml）。"""
    root = tmp_path / "stub_boot"
    root.mkdir(parents=True, exist_ok=True)
    (root / "manifest.yaml").write_text(
        "id: stub_boot\n"
        "display: Stub\n"
        "capabilities:\n"
        "  provision.run:\n"
        f"    kind: adapter\n    entry: {entry}\n",
        encoding="utf-8",
    )
    return tmp_path
