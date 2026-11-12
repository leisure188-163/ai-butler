"""连接器身份与声明式 schema（A2-02 §2/§4）—— pydantic 严校验（extra=forbid）。

manifest 是注册表发现的唯一入口；声明里出现 schema 外字段直接爆——
协议逆向结论必须先写成 PROTOCOL.md 与 schema，不允许声明里"私货"字段
静默被忽略（红线 5）。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from kabao_core.domain.action import ActionKind
from kabao_core.domain.errors import DomainError
from kabao_core.domain.schedule import WindowInvalid, claim_window  # noqa: F401

MANIFEST_NAME = "manifest.yaml"

#: 能力 id 必须是 core ActionKind 的字面量——连接器能力矩阵与世界模型对齐，
#: 未登记进 ActionKind 的新能力要先改 core（A2-02 §2：新动词须历法）
_CAPABILITY_IDS = frozenset(k.value for k in ActionKind)


class ManifestInvalid(DomainError):
    """manifest/声明式配置非法：拒绝接入并如实报错，不静默降级（红线 5）。"""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class HeaderPair(_Strict):
    """鉴权头模板：name + 前缀（值来自解锁字段）。"""

    name: str
    prefix: str = ""


class AuthSpec(_Strict):
    """凭据解锁声明：kind 引 vault 凭据类型（kinds 之一），unlock 语义由实现承载。"""

    kind: str
    storage: list[str] = Field(default_factory=list)  # 本机凭据存储候选路径（平台宏）
    token_header: HeaderPair | None = None
    static_headers: dict[str, str] = Field(default_factory=dict)
    dynamic_headers: dict[str, str] = Field(default_factory=dict)  # "{field}" 模板


class RequestSpec(_Strict):
    method: Literal["GET", "POST"] = "POST"
    url: str
    headers: dict[str, str] = Field(default_factory=dict)
    body: dict[str, Any] = Field(default_factory=dict)


class StatusSection(_Strict):
    request: RequestSpec
    code_path: str = "code"
    expect_ok: str = "0"
    checked_in_path: str = ""  # 单布尔模式（trae：checked_in true/false）
    list_path: str = ""  # 列表模式：数组所在点路径（qoder：campaigns）
    item_filter: dict[str, str] = Field(default_factory=dict)  # 待领项等值筛选
    done_filter: dict[str, str] = Field(default_factory=dict)  # 已领项等值筛选

    from pydantic import model_validator

    @model_validator(mode="after")
    def _one_mode(self):
        """判定模式互斥：单布尔（checked_in_path）或列表（list_path）二选一。"""
        if bool(self.checked_in_path) == bool(self.list_path):
            raise ManifestInvalid(
                "status 判定模式二选一：checked_in_path（单布尔）或 "
                "list_path（列表谓词）——同时缺省或同时声明都拒绝"
            )
        if self.list_path and not self.item_filter:
            raise ManifestInvalid("list_path 列表模式必须声明 item_filter（待领项筛选）")
        return self


class RetrySpec(_Strict):
    on_codes: list[str] = Field(default_factory=list)
    backoff_seconds: list[int] = Field(default_factory=lambda: [30, 60, 120])


class ClaimSection(_Strict):
    request: RequestSpec
    code_path: str = "code"
    expect_ok: str = "0"
    confirm_by_status: bool = True
    each: str = ""  # 列表模式：引用 status 列表段（筛选后逐项领取）
    retry: RetrySpec = Field(default_factory=RetrySpec)


class WindowSpec(_Strict):
    refresh_at: str = "00:00"


class DeclarativeSpec(_Strict):
    """五段式声明（A2-02 §4）：auth/status/claim/business_codes/window。"""

    auth: AuthSpec
    status: StatusSection
    claim: ClaimSection
    business_codes: dict[str, str]
    window: WindowSpec = Field(default_factory=WindowSpec)

    from pydantic import model_validator

    @model_validator(mode="after")
    def _each_refs_list(self):
        """claim.each 是对 status 列表段的命名引用——引用不存在的段 = 声明事故。"""
        if self.claim.each and self.claim.each != self.status.list_path:
            raise ManifestInvalid(
                f"claim.each {self.claim.each!r} 必须与 status.list_path "
                f"{self.status.list_path!r} 一致（逐项模式的项来自该段筛选）"
            )
        return self


class CapabilitySpec(_Strict):
    kind: Literal["declarative", "adapter"]
    entry: str
    budget_seconds: int = 240


class CredentialSpec(_Strict):
    kinds: list[str]
    unlock: str


class ScheduleSpec(_Strict):
    times: list[str]
    refresh_at: str | None = None  # 缺省回落 declarative window.refresh_at

    from pydantic import model_validator

    @model_validator(mode="before")
    @classmethod
    def _accept_bare_list(cls, data):
        """manifest 紧凑形态：``schedule.provision.run: [times...]``。"""
        if isinstance(data, list):
            return {"times": data}
        return data


class ConnectorManifest(_Strict):
    """连接器身份 + 能力矩阵（A2-02 §2）。"""

    id: str
    display: str
    capabilities: dict[str, CapabilitySpec]
    credential: CredentialSpec | None = None
    schedule: dict[str, ScheduleSpec] = Field(default_factory=dict)

    def model_post_init(self, __context: Any) -> None:
        bad = set(self.capabilities) - _CAPABILITY_IDS
        if bad:
            raise ManifestInvalid(
                f"{self.id}: 能力 id {sorted(bad)} 不在 ActionKind 词表 "
                f"{sorted(_CAPABILITY_IDS)} 中——新增动词先改 core"
            )
        if self.credential is not None:
            for cap in self.capabilities.values():
                if cap.kind == "declarative":
                    main = _declarative_main_auth(self.id, cap.entry)
                    if main not in self.credential.kinds:
                        raise ManifestInvalid(
                            f"{self.id}: 声明式能力主凭据 kind {main!r} 未在 "
                            f"credential.kinds {self.credential.kinds} 申报（最小授权穿透）"
                        )


def _declarative_main_auth(conn_id: str, entry: str) -> str:
    """声明式能力主凭据 kind：读 entry YAML 的 auth.kind 做交叉校验。"""
    import yaml

    from kabao_connectors.paths import package_root

    path = package_root(conn_id) / entry
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as e:
        raise ManifestInvalid(f"{conn_id}: 声明式 entry 缺失: {entry}") from e
    kind = (data or {}).get("auth", {}).get("kind", "")
    if not kind:
        raise ManifestInvalid(f"{conn_id}: {entry} 缺少 auth.kind")
    return str(kind)
