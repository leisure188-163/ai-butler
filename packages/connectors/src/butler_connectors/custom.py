"""自定义平台草稿 → 声明式连接器文件（2026-11-18）。

自定义平台不是新执行器：把用户填的「状态请求 / 领取请求 / 判定」渲染成与内置
连接器同构的 ``manifest.yaml + declarative/*.yaml``，交给同一套
``DeclarativeProvisionPort`` 执行（调度、凭据、台账、事件全部沿用）。

纪律：
- 只产出 ``browser_cookie`` 凭据形态——网页登录态从本机 Chrome cookie 库捕获，
  与内置网页连接器（chatgpt_web / claude_web）同一条链路，不新开凭据采集通道
- 落盘前先在临时目录完整装载一遍（manifest schema + 声明式 schema + 主凭据交叉
  校验 + entry 路径校验），校验不过绝不写正式目录（坏文件不进运行期）
- ``custom`` 目录只承载声明式能力；adapter（任意代码装载）在装载期显式拒绝
"""

from __future__ import annotations

import re
import shutil
import tempfile
from pathlib import Path
from typing import Any, Literal

import yaml

from butler_connectors.manifest import MANIFEST_NAME, ManifestInvalid, _Strict
from pydantic import Field

_CODE_RE = re.compile(r"^[a-z][a-z0-9_]{1,31}$")

#: 入口文件名（目录内相对路径，与内置连接器命名一致）
PROVISION_ENTRY = "declarative/provision.run.yaml"
CAPTURE_ENTRY = "declarative/session.import.yaml"

#: Chrome cookie 库候选（平台宏，paths.expand_storage_path 展开；跨三平台铺开）
_COOKIE_STORAGE = [
    "%LOCALAPPDATA%/Google/Chrome/User Data/*/Network/Cookies",
    "%LOCALAPPDATA%/Google/Chrome/User Data/*/Cookies",
    "~/Library/Application Support/Google/Chrome/*/Network/Cookies",
    "~/Library/Application Support/Google/Chrome/*/Cookies",
    "~/.config/google-chrome/*/Network/Cookies",
]

#: 自定义平台缺省业务码方言（HTTP 码 ≠ 业务码时由声明覆盖；见 ADR-004）
_DEFAULT_CODES = {"401": "EXPIRED", "403": "NO_AUTH"}


class RequestDraft(_Strict):
    """一次 HTTP 请求草稿（body 为 JSON 映射；GET 允许空）。"""

    method: Literal["GET", "POST"] = "POST"
    url: str
    body: dict[str, Any] = Field(default_factory=dict)


class StatusDraft(_Strict):
    """状态判定草稿：``checked_in_path``（单布尔）或 ``code_path+expect_ok``（业务码）。"""

    request: RequestDraft
    checked_in_path: str = ""
    code_path: str = "code"
    expect_ok: str = "0"


class ClaimDraft(_Strict):
    """领取请求草稿（业务码判定；受理后以 status 复查为准）。"""

    request: RequestDraft
    code_path: str = "code"
    expect_ok: str = "0"
    retry_on_codes: list[str] = Field(default_factory=list)


class CustomPlatformDraft(_Strict):
    """前端提交的自定义平台草稿（browser_cookie 形态）。

    ``cookies`` = 登录态必需名单（全在才算已登录），与内置网页连接器语义一致。
    """

    code: str
    display: str
    domain: str
    cookies: list[str]
    status: StatusDraft
    claim: ClaimDraft
    business_codes: dict[str, str] = Field(default_factory=lambda: dict(_DEFAULT_CODES))
    schedule_times: list[str] = Field(default_factory=list)
    budget_seconds: int = 120

    def model_post_init(self, __context: Any) -> None:
        if not _CODE_RE.match(self.code):
            raise ManifestInvalid(
                f"平台编码 {self.code!r} 非法：小写字母开头，仅 a-z/0-9/_，2-32 位"
            )
        if not self.display.strip():
            raise ManifestInvalid("平台名称不能为空")
        if not self.domain.strip():
            raise ManifestInvalid("登录域名不能为空（用于匹配 cookie 库里的站点）")
        if not self.cookies:
            raise ManifestInvalid("登录态 cookie 名单不能为空（至少一个 cookie 名）")
        if bool(self.status.checked_in_path) == bool(self.status.code_path):
            # checked_in_path 模式不读业务码；两者都填 = 判定语义含糊
            if self.status.checked_in_path and self.status.code_path != "code":
                raise ManifestInvalid(
                    "状态判定二选一：单布尔（checked_in_path）或业务码（code_path/expect_ok）"
                )
        for t in self.schedule_times:
            if not re.match(r"^[0-2][0-9]:[0-5][0-9]$", t):
                raise ManifestInvalid(f"调度时间 {t!r} 非法（应为 HH:MM）")


def render_bundle(draft: CustomPlatformDraft) -> dict[str, Any]:
    """草稿 → 三份 YAML 内容（manifest / provision.run / session.import）。"""
    status_decl: dict[str, Any] = {
        "request": draft.status.request.model_dump(),
        "code_path": draft.status.code_path,
        "expect_ok": draft.status.expect_ok,
    }
    if draft.status.checked_in_path:
        status_decl["checked_in_path"] = draft.status.checked_in_path

    claim_decl: dict[str, Any] = {
        "request": draft.claim.request.model_dump(),
        "code_path": draft.claim.code_path,
        "expect_ok": draft.claim.expect_ok,
        "confirm_by_status": True,
    }
    if draft.claim.retry_on_codes:
        claim_decl["retry"] = {
            "on_codes": list(draft.claim.retry_on_codes),
            "backoff_seconds": [30, 60, 120],
        }

    provision = {
        "auth": {
            "kind": "browser_cookie",
            "domain": draft.domain,
            "cookies": list(draft.cookies),
            "reauth_status_codes": [401, 403],
            "storage": list(_COOKIE_STORAGE),
        },
        "status": status_decl,
        "claim": claim_decl,
        "business_codes": dict(draft.business_codes),
        "window": {"refresh_at": "00:00"},
    }

    capture = {
        "auth": {
            "kind": "browser_cookie",
            "browser": "chrome",
            "domain": draft.domain,
            "cookies": list(draft.cookies),
            "storage": list(_COOKIE_STORAGE),
        }
    }

    manifest: dict[str, Any] = {
        "id": draft.code,
        "display": draft.display.strip(),
        "kind": "web",
        "capabilities": {
            "provision.run": {
                "kind": "declarative",
                "entry": PROVISION_ENTRY,
                "budget_seconds": draft.budget_seconds,
            },
            "session.import": {
                "kind": "declarative",
                "entry": CAPTURE_ENTRY,
                "budget_seconds": 60,
            },
        },
        "credential": {"kinds": ["browser_cookie"], "unlock": "browser"},
        "usage": False,
    }
    if draft.schedule_times:
        manifest["schedule"] = {"provision.run": {"times": list(draft.schedule_times)}}

    return {
        "manifest.yaml": manifest,
        PROVISION_ENTRY: provision,
        CAPTURE_ENTRY: capture,
    }


def _write_bundle(root: Path, bundle: dict[str, Any]) -> None:
    (root / "declarative").mkdir(parents=True, exist_ok=True)
    for rel, data in bundle.items():
        (root / rel).write_text(
            yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )


def validate_bundle(code: str, bundle: dict[str, Any]) -> None:
    """完整装载一遍（与运行期同一条校验链）；失败抛 ManifestInvalid。"""
    from butler_connectors.registry import load_registry

    with tempfile.TemporaryDirectory(prefix="butler-custom-") as tmp:
        _write_bundle(Path(tmp) / code, bundle)
        load_registry(custom_root=Path(tmp))


def save_custom_platform(draft: CustomPlatformDraft, root: Path) -> None:
    """校验通过后落盘（同 code 覆盖 = 更新）。"""
    bundle = render_bundle(draft)
    validate_bundle(draft.code, bundle)
    target = root / draft.code
    if target.is_dir():
        # 先清掉旧目录内的声明式文件，避免更新后残留旧 entry
        shutil.rmtree(target)
    _write_bundle(target, bundle)


def delete_custom_platform(code: str, root: Path) -> bool:
    """删除自定义平台目录；返回是否真的删了（不存在 = False，端侧如实提示）。"""
    if not _CODE_RE.match(code):
        raise ManifestInvalid(f"平台编码 {code!r} 非法")
    target = root / code
    if not target.is_dir():
        return False
    shutil.rmtree(target)
    return True


def list_custom_platforms(root: Path) -> list[dict[str, str]]:
    """扫描自定义目录（只认有 manifest 的子目录），返回 code/display。"""
    if not root.is_dir():
        return []
    out: list[dict[str, str]] = []
    for child in sorted(root.iterdir()):
        path = child / MANIFEST_NAME
        if not child.is_dir() or not path.is_file():
            continue
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            continue
        out.append({"code": child.name, "display": str(data.get("display", child.name))})
    return out
