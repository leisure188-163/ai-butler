"""连接器注册表（A2-02 §2）：装载 manifest → 组建端口 / 停靠 / 调度条目。

纪律：
- 只读 manifest 与声明式 YAML，不 import 业务代码（声明式连接器的全部逻辑
  就在 YAML + 共享运行时里）；adapter 型连接器动态 import 其 entry 模块
  （entry = "module.attribute"，模块内实现 core 端口——三级扩展第二级；
  其 build_port 契约 = ``(vault=, transport=)``，transport 与声明式共用注入面）
- 业务码方言在装载期注册（ADR-002）：business_codes = raw code → Status
- dock 分发：声明式连接器的接入扫描 = 共享 dockio（storage 发现 → 凭据入库）；
  adapter 连接器在包内 onboard.py 的 ``dock(ctx)`` 自带扫描
- 调度条目输出纯数据（dict）：engine 不 import 本包（ADR-003），
  端的组装层把字典转成 engine 的 ScheduleEntry
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from kabao_core.application.ports import ProvisionPort
from kabao_core.application.usecases import RegisterAccount
from kabao_core.domain.results import Status, register_dialect

from kabao_connectors.manifest import (
    MANIFEST_NAME,
    ConnectorManifest,
    DeclarativeSpec,
    ManifestInvalid,
)
from kabao_connectors.paths import package_root


@dataclass(frozen=True)
class ConnectorApp:
    """一枚已装载的连接器：manifest + 包根 + 声明式规格（如有）。"""

    manifest: ConnectorManifest
    root: Path
    declarative: dict[str, DeclarativeSpec] = field(default_factory=dict)

    @property
    def display(self) -> str:
        return self.manifest.display

    def provision_budget(self, capability: str = "provision.run") -> int:
        return self.manifest.capabilities[capability].budget_seconds


@dataclass
class DockContext:
    """停靠注入包：core 对象由端组装传入，连接器不自己找全局（A2-02 §5）。

    storage_override：候选路径覆盖（端配置/测试注入）；默认用声明里的 auth.storage。
    """

    vault: Any  # VaultPort
    register: RegisterAccount
    storage_override: list[str] | None = None


@dataclass(frozen=True)
class DockOutcome:
    """一次停靠扫描的如实报告：接进来的账号 + 没接进去的原因。"""

    target: str
    accounts: list[str] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)


class Registry:
    """连接器家族注册表：端（server/cli）组装层的唯一入口。"""

    def __init__(self, apps: dict[str, ConnectorApp]) -> None:
        if not apps:
            raise ManifestInvalid("连接器注册表为空——包内需至少一个连接器")
        self._apps = apps

    def ids(self) -> list[str]:
        return sorted(self._apps)

    def get(self, target: str) -> ConnectorApp:
        try:
            return self._apps[target]
        except KeyError:
            raise KeyError(f"连接器未接入: {target!r}（可用: {self.ids()}）") from None

    def apps(self) -> list[ConnectorApp]:
        return [self._apps[i] for i in self.ids()]

    # --- 端口与调度（组装层消费）---

    def provision_ports(
        self, vault: Any, transport: Any = None
    ) -> dict[str, ProvisionPort]:
        """target → ProvisionPort。声明式 → 共享运行时；adapter → 动态 import。"""
        ports: dict[str, ProvisionPort] = {}
        for target, app in self._apps.items():
            cap = app.manifest.capabilities["provision.run"]
            kinds = tuple(app.manifest.credential.kinds) if app.manifest.credential else ()
            if cap.kind == "declarative":
                ports[target] = _build_decl_port(
                    target, app, app.declarative["provision.run"], vault, transport, kinds
                )
            elif cap.kind == "adapter":
                ports[target] = _load_entry(app, cap.entry).build_port(
                    vault=vault, transport=transport
                )
            else:  # pragma: no cover - schema 已限定枚举
                raise ManifestInvalid(f"{target}: 未知能力类型 {cap.kind}")
        return ports

    def usage_ports(self, vault: Any, transport: Any = None) -> dict[str, Any]:
        """target → UsagePort（R2 用量通道）。仅装载申报了 usage.collect 的连接器。

        kind 必须为 adapter：用量通道是各家专属编排（翻页/包映射/CDP 取数），
        声明式五段表达不了。auth/kinds 透传给复用 provision 鉴权链的通道
        （trae/qoder）；纯 adapter 连接器（doubao/workbuddy）无声明式主链，
        两者为空，通道自备环境束。
        """
        ports: dict[str, Any] = {}
        for target, app in self._apps.items():
            cap = app.manifest.capabilities.get("usage.collect")
            if cap is None:
                continue
            if cap.kind != "adapter":
                raise ManifestInvalid(
                    f"{target}: usage.collect 仅支持 adapter（用量编排各家专属），got {cap.kind!r}"
                )
            kinds = tuple(app.manifest.credential.kinds) if app.manifest.credential else ()
            declarative = app.declarative.get("provision.run")
            auth = declarative.auth if declarative is not None else None
            ports[target] = _load_entry(app, cap.entry)(
                vault=vault, transport=transport, auth=auth, kinds=kinds
            )
        return ports

    def schedule_entries(self) -> list[dict[str, Any]]:
        """调度条目（纯数据，engine 端组装层转 ScheduleEntry）。"""
        out: list[dict[str, Any]] = []
        for target, app in self._apps.items():
            schedule = app.manifest.schedule.get("provision.run")
            if schedule is None:
                continue
            refresh = schedule.refresh_at
            if refresh is None:
                refresh = app.declarative["provision.run"].window.refresh_at
            out.append(
                {
                    "target": target,
                    "times": list(schedule.times),
                    "refresh_at": refresh,
                    "budget_seconds": app.provision_budget("provision.run"),
                }
            )
        return out

    # --- 停靠（dock 分发）---

    def dock(self, ctx: DockContext, target: str | None = None) -> list[DockOutcome]:
        """接入扫描：target=None = 全家族逐个停靠（单点失败不拖累别家）。"""
        targets = [target] if target else self.ids()
        outcomes: list[DockOutcome] = []
        for tid in targets:
            app = self.get(tid)
            cap = app.manifest.capabilities["provision.run"]
            try:
                if cap.kind == "declarative":
                    outcome = _onboard_declarative(
                        app,
                        app.declarative["provision.run"],
                        tuple(app.manifest.credential.kinds) if app.manifest.credential else (),
                        ctx,
                    )
                else:
                    outcome = _load_entry(app, cap.entry).dock(ctx)
            except Exception as exc:  # 单家失败显式出账，不拖累其余
                outcome = DockOutcome(target=tid, issues=[f"停靠扫描异常: {exc}"])
            outcomes.append(outcome)
        return outcomes


# --- 装载 ---


def load_registry() -> Registry:
    """扫描包内每个连接器子目录的 manifest.yaml；装载即注册方言（ADR-002）。

    幂等：同映射重复注册不报错（reload 安全），映射不同 = 装配 bug 显式爆。
    """
    apps: dict[str, ConnectorApp] = {}
    for child in sorted(package_root().iterdir()):
        manifest_path = child / MANIFEST_NAME
        if not child.is_dir() or not manifest_path.is_file():
            continue
        manifest = ConnectorManifest.model_validate(
            yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        )
        if manifest.id != child.name:
            raise ManifestInvalid(
                f"manifest.id {manifest.id!r} 与目录名 {child.name!r} 不一致"
            )
        for spec in manifest.capabilities.values():
            if spec.kind == "adapter":
                # 装载即 import：adapter 模块自注册业务码方言（ADR-002 装载期），
                # 坏 entry 也在装载期显式爆，不留到首次 run（红线 5）
                _load_entry_module(manifest.id, spec.entry)
        declarative = {
            cap: _load_declarative(manifest.id, spec.entry)
            for cap, spec in manifest.capabilities.items()
            if spec.kind == "declarative"
        }
        for data in declarative.values():
            register_dialect(
                manifest.id,
                {code: Status[name] for code, name in data.business_codes.items()},
            )
        apps[manifest.id] = ConnectorApp(
            manifest=manifest, root=child, declarative=declarative
        )
    return Registry(apps)


def _load_declarative(conn_id: str, entry: str) -> DeclarativeSpec:
    path = package_root(conn_id) / entry
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ManifestInvalid(f"{conn_id}/{entry}: 声明式 YAML 应为映射")
    try:
        return DeclarativeSpec.model_validate(data)
    except Exception as exc:
        raise ManifestInvalid(f"{conn_id}/{entry} 声明非法: {exc}") from exc


def _load_entry_module(conn_id: str, entry: str) -> Any:
    module_name = entry.partition(".")[0]
    return importlib.import_module(f"kabao_connectors.{conn_id}.{module_name}")


def _load_entry(app: ConnectorApp, entry: str) -> Any:
    """adapter 连接器的 entry 形如 ``module.attribute`` → 模块函数/对象。"""
    module = _load_entry_module(app.manifest.id, entry)
    return getattr(module, entry.partition(".")[2])


# --- 声明式端口与停靠的实现衔接 ---


def _build_decl_port(
    target: str,
    app: ConnectorApp,
    spec: DeclarativeSpec,
    vault: Any,
    transport: Any,
    kinds: tuple[str, ...],
):
    from kabao_connectors.decl import DeclarativeProvisionPort
    from kabao_connectors.transport import httpx_transport

    return DeclarativeProvisionPort(
        conn_id=target,
        display=app.display,
        spec=spec,
        vault=vault,
        transport=transport if transport is not None else httpx_transport(),
        kinds=kinds,
    )


def _onboard_declarative(
    app: ConnectorApp, spec: DeclarativeSpec, kinds: tuple[str, ...], ctx: DockContext
) -> DockOutcome:
    """声明式连接器的停靠：共享 dockio 扫描本机凭据存储 → 注册 → 入库。"""
    from kabao_connectors.dockio import scan_storage

    return scan_storage(app, spec, kinds, ctx)
