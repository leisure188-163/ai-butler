"""连接器身份与声明式 schema（A2-02 §2/§4）—— pydantic 严校验（extra=forbid）。

manifest 是注册表发现的唯一入口；声明里出现 schema 外字段直接爆——
协议逆向结论必须先写成 PROTOCOL.md 与 schema，不允许声明里"私货"字段
静默被忽略（红线 5）。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from butler_core.execution.domain import ActionKind
from butler_core.shared.errors import DomainError
from butler_core.scheduling.domain import WindowInvalid, claim_window

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
    #: 按账户切 API 基址：key = account_key（精确优先）或 ``-`` 前缀（如 global-<hash>）。
    #: 只对有多个产品域的连接器有意义；未声明时保持 RequestSpec.url 原样。
    base_urls: dict[str, str] = Field(default_factory=dict)
    token_header: HeaderPair | None = None
    static_headers: dict[str, str] = Field(default_factory=dict)
    dynamic_headers: dict[str, str] = Field(default_factory=dict)  # "{field}" 模板
    #: HTTP 状态码申报：命中即「登录态失效」，归 NO_AUTH 而非 FAILED（A2-02 §4）。
    #: 空 = 不申报（非鉴权类 4xx/5xx 继续按通道故障 FAILED 处理）。
    reauth_status_codes: list[int] = Field(default_factory=list)
    # --- browser_cookie 专用字段（A2-03 §2）：其余 kind 一律禁填 ---
    browser: str = ""  # 浏览器 kind（首批唯一值 chrome）
    domain: str = ""  # registrable domain（host 精确或点后缀匹配）
    cookies: list[str] = Field(default_factory=list)  # 必需名单：全在才算登录

    from pydantic import model_validator

    @model_validator(mode="after")
    def _kind_shape(self):
        """字段集按 kind 互斥：browser 三件套只属 browser_cookie。

        三件套必填约束在 CaptureSpec（捕获要「捕什么」）；探针 auth 只需 kind
        （拼 Cookie 头不读 domain/名单），storage 是发现候选（两类通道都可用）。
        """
        browser_fields = {"browser": self.browser, "domain": self.domain, "cookies": self.cookies}
        filled_browser = {k for k, v in browser_fields.items() if v}
        if self.kind != "browser_cookie" and filled_browser:
            raise ManifestInvalid(
                f"auth.kind={self.kind!r} 不接受浏览器字段 {sorted(filled_browser)}（browser 三件套只属 browser_cookie）"
            )
        if self.kind == "browser_cookie" and self.browser and self.browser != "chrome":
            raise ManifestInvalid(f"browser {self.browser!r} 未接入（首批唯一值 chrome，A1-04 §4）")
        return self


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


class CaptureSpec(_Strict):
    """session.import 声明（A2-03 §2，R3 网页捕获）：捕获无 status/claim/window
    语义（无领取概念，不发明），全部捕获语义承载在 auth 三件套里。"""

    auth: AuthSpec

    from pydantic import model_validator

    @model_validator(mode="after")
    def _capture_shape(self):
        """捕获要「捕什么、去哪认」：browser_cookie 必须给全 browser/domain/cookies。"""
        if self.auth.kind == "browser_cookie":
            missing = sorted(
                k
                for k, v in {
                    "browser": self.auth.browser,
                    "domain": self.auth.domain,
                    "cookies": self.auth.cookies,
                }.items()
                if not v
            )
            if missing:
                raise ManifestInvalid(
                    f"session.import auth 需要完整声明 browser/domain/cookies（缺 {missing}）"
                )
        return self


class ProbeSection(_Strict):
    """探针请求：HTTP status 即信号（网页会话没有 body 业务码外壳）。"""

    request: RequestSpec
    ok_status: int = 200


class ProbeSpec(_Strict):
    """health.check 声明（A2-03 §3，R3 探针）：auth + probe + HTTP 码字典。

    codes 是 HTTP status → Status 字面量名——装载期注册方言（ADR-004 唯一
    翻译点）；未声明的 status = 未知码，显式爆（协议变更探测）。
    """

    auth: AuthSpec
    probe: ProbeSection
    codes: dict[str, str]


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
    retired: bool = False  # 退役：代码保留审计/回滚，不再出现在应用名册与一键导入
    usage: bool = True  # 是否挂载用量采集；纯签到连接器可声明 false（如 agentrouter）

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

    from butler_connectors.paths import package_root

    path = package_root(conn_id) / entry
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as e:
        raise ManifestInvalid(f"{conn_id}: 声明式 entry 缺失: {entry}") from e
    kind = (data or {}).get("auth", {}).get("kind", "")
    if not kind:
        raise ManifestInvalid(f"{conn_id}: {entry} 缺少 auth.kind")
    return str(kind)
