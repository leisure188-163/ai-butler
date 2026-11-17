"""声明式鉴权头模板与按账户基址（A2-02 §4；从 decl.py 拆出控制行数）。

单一职责：解锁字段 → header 模板 / account_key → 产品域基址。provision、
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


def fill_auth_headers(auth: AuthSpec, fields: Mapping[str, str]) -> dict[str, str]:
    """解锁字段 → 鉴权头组（token 头 + 静态头 + 动态模板）。

    声明式 provision、用量适配（R2）与探针（R3）共用的拼装单源：缺字段显式爆
    （红线 5）。browser_cookie kind 的字段 cookie 整体进 Cookie 头（A2-03 §1）。
    """
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


def account_base_url(auth: AuthSpec, account_id: str) -> str:
    """按 account_key 选择产品域基址；精确键优先，其次 ``-`` 前缀，最后 main。

    未声明 base_urls 的连接器返回空串——调用方据此保留 RequestSpec.url 原样。
    """
    if not auth.base_urls or ":" not in account_id:
        return ""
    key = account_id.split(":", 1)[1]
    for candidate in (key, key.split("-", 1)[0], "main"):
        if candidate in auth.base_urls:
            return auth.base_urls[candidate].rstrip("/")
    return ""
