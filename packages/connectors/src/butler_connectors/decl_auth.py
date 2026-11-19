"""声明式鉴权头模板与按账户基址（A2-02 §4；从 decl.py 拆出控制行数）。

单一职责：解锁字段 → header 模板 / account_code → 产品域基址。provision、
health 与 usage 适配器共用；缺字段显式爆，不静默少发头（红线 5）。
"""

from __future__ import annotations

from collections.abc import Mapping

from butler_core.shared.errors import DomainError

from butler_connectors.manifest import AuthSpec


class TemplateFieldMissing(DomainError):
    """dynamic header 模板引用的字段在解锁产物里不存在——显式报错（红线 5）。"""


class _FieldMap(dict):
    """模板字段查找：缺字段 = 声明与解锁产物不一致，显式爆。"""

    def __missing__(self, key: str) -> str:
        raise TemplateFieldMissing(f"header 模板引用的字段 {key!r} 不在解锁产物里")


def fill_auth_headers(
    auth: AuthSpec, fields: Mapping[str, str], *, account_id: str = ""
) -> dict[str, str]:
    """解锁字段 → 鉴权头组（token 头 + 静态头 + 动态模板）。

    声明式 provision、用量适配（R2）与探针（R3）共用的拼装单源：缺字段显式爆
    （红线 5）。browser_cookie kind 的字段 cookie 整体进 Cookie 头（A2-03 §1）。

    account_id 给了就按账户产品域取 ``<字段>_<区域>`` 的值（2026-11-19）：
    同一台机器装了国际版/国内版两套客户端时，Cosy-Version 必须与账户所属
    产品域的真实客户端一致，否则发给 CN 账户的是国际版版本号。
    """
    fields = _scoped_fields(auth, fields, account_id)
    merged = dict(auth.static_headers)
    if auth.kind == "browser_cookie":
        if "cookie" not in fields:
            raise TemplateFieldMissing("cookie（browser_cookie 解锁产物缺失，凭据事故）")
        merged["Cookie"] = fields["cookie"]
    elif auth.token_header is not None:
        if "token" not in fields:
            raise TemplateFieldMissing("token（解锁产物无 token，凭据事故）")
        merged[auth.token_header.name] = auth.token_header.prefix + fields["token"]
    for name, template in auth.dynamic_headers.items():
        merged[name] = template.format_map(_FieldMap(fields))
    return merged


def account_key(auth: AuthSpec, account_id: str) -> str:
    """account_code → 声明的产品域键（精确优先，其次 ``-`` 前缀，最后 main）。

    未声明 base_urls / 账户 id 无 ``:`` 时返回空串（单域连接器）。
    """
    if not auth.base_urls or ":" not in account_id:
        return ""
    key = account_id.split(":", 1)[1]
    for candidate in (key, key.split("-", 1)[0], "main"):
        if candidate in auth.base_urls:
            return candidate
    return ""


def _scoped_fields(auth: AuthSpec, fields: Mapping[str, str], account_id: str) -> Mapping[str, str]:
    """``<字段>_<域键>`` 覆盖 ``<字段>``：域键 = 该账户产品域在 base_urls 里的**同 host 键**。

    为什么按 host 归组而不是账户键：CN 域有 main / cn 两个键指向同一 host，
    账户键是 main 时仍须取 cosy_version_cn（同一台机器装了国际版/国内版两套
    客户端时，Cosy-Version 必须与账户所连产品域的真实客户端一致）。
    """
    key = account_key(auth, account_id)
    if not key:
        return fields
    host = _url_host(auth.base_urls.get(key, ""))
    keys = [key]
    keys.extend(
        other
        for other, url in auth.base_urls.items()
        if other != key and _url_host(url) == host
    )
    overrides: dict[str, str] = {}
    for name, value in fields.items():
        if not value:
            continue
        for candidate in keys:
            suffix = f"_{candidate}"
            if name.endswith(suffix) and len(name) > len(suffix):
                overrides[name[: -len(suffix)]] = value
                break
    if not overrides:
        return fields
    merged = dict(fields)
    merged.update(overrides)
    return merged


def _url_host(url: str) -> str:
    """基址 → host（无 netloc 时原样返回，用于同域归组比较）。"""
    from urllib.parse import urlparse

    parsed = urlparse(url)
    return parsed.netloc.lower() or url.strip().lower()


def account_base_url(auth: AuthSpec, account_id: str) -> str:
    """按 account_code 选择产品域基址；精确键优先，其次 ``-`` 前缀，最后 main。

    未声明 base_urls 的连接器返回空串——调用方据此保留 RequestSpec.url 原样。
    """
    key = account_key(auth, account_id)
    return auth.base_urls[key].rstrip("/") if key else ""
