"""结果词汇单源（A2-01 §2）：Status 枚举 + ResultKind 谓词 + from_engine 翻译。

- 字面量与旧系统方言严格对齐——行为验收 oracle 零损耗（A0-01 §2.2），
  禁止增改字面量。
- 端上只消费 ResultKind 谓词，禁止 `if status in [...]` 式语义映射表（红线 2）。
- from_engine 是唯一运行时翻译入口；方言注册表机制见 ADR-004。
- 未知业务码显式报错（红线 5），绝不静默兜底。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Mapping

__all__ = [
    "Status",
    "ResultKind",
    "DialectError",
    "UnknownEngineCode",
    "register_dialect",
    "from_engine",
]


class Status(StrEnum):
    """执行结果词汇。字面量为 oracle 对齐固定值（A2-01 §2），禁止增改。"""

    CLAIMED = "CLAIMED"  # 本次执行完成领取
    ALREADY = "ALREADY"  # 本窗口已领过（幂等命中）
    NO_AUTH = "NO_AUTH"  # 凭据缺失/失效
    EXPIRED = "EXPIRED"  # 登录态过期
    FAILED = "FAILED"  # 执行失败
    PENDING = "PENDING"  # 服务端判定暂不符合条件（如实上报，不算失败）
    SKIPPED = "SKIPPED"  # 计划内跳过（如通道不可用）

    @property
    def kind(self) -> ResultKind:
        """Status → 分类谓词。端上渲染只经此消费语义（A1-02 §3）。"""
        return _KIND_BY_STATUS[self]


@dataclass(frozen=True)
class ResultKind:
    """分类谓词：端上渲染只消费这些（A2-01 §2）。"""

    is_pass: bool
    is_attention: bool  # 需要用户处理（进"待处理"）
    is_fail: bool

    @property
    def signal(self) -> str:
        """视觉信号桶（A3-01 §4 渲染纪律）：UI 的染色分类由此出产。

        ok=达成 / attention=待处理 / danger=失败 / quiet=中性信息。
        UI 只按这五个词上 CSS class，不认识具体 Status 字面量（端零映射）。
        """

        if self.is_pass:
            return "ok"
        if self.is_attention:
            return "attention"
        if self.is_fail:
            return "danger"
        return "quiet"


# 谓词映射——业务语义唯一出处（端零映射，红线 2）：
#   CLAIMED / ALREADY  目标已达成（幂等命中也算达成）      → pass
#   NO_AUTH / EXPIRED  需要用户修凭据，配 repair_hint      → attention（进"待处理"）
#   FAILED             执行失败                            → fail
#   PENDING            暂不符合条件，用户无可动作          → 中性信息（全 False）
#   SKIPPED            计划内跳过                          → 中性信息（全 False）
_KIND_BY_STATUS: dict[Status, ResultKind] = {
    Status.CLAIMED: ResultKind(is_pass=True, is_attention=False, is_fail=False),
    Status.ALREADY: ResultKind(is_pass=True, is_attention=False, is_fail=False),
    Status.NO_AUTH: ResultKind(is_pass=False, is_attention=True, is_fail=False),
    Status.EXPIRED: ResultKind(is_pass=False, is_attention=True, is_fail=False),
    Status.FAILED: ResultKind(is_pass=False, is_attention=False, is_fail=True),
    Status.PENDING: ResultKind(is_pass=False, is_attention=False, is_fail=False),
    Status.SKIPPED: ResultKind(is_pass=False, is_attention=False, is_fail=False),
}


class DialectError(ValueError):
    """方言层错误：方言名非法、未注册或映射数据不合法。"""


class UnknownEngineCode(ValueError):
    """引擎返回了方言里没有注册的业务码——上游协议可能已变更。

    用例层必须显式处理：记 FAILED + evidence 保留原始码 + 产
    PROTOCOL_CHANGED 事件（A2-01 §5）。禁止吞掉或静默映射（红线 5）。
    """

    def __init__(self, code: str, dialect: str) -> None:
        self.code = code
        self.dialect = dialect
        super().__init__(
            f"方言 {dialect!r} 未注册的业务码: {code!r}（上游协议可能已变更）"
        )


_DIALECTS: dict[str, dict[str, Status]] = {
    # 内置 legacy 方言：旧系统说的就是这七个字面量，自映射即 oracle 对齐（A0-01 §2.2）。
    "legacy": {status.value: status for status in Status},
}


def register_dialect(name: str, mapping: Mapping[str, Status]) -> None:
    """注册连接器方言（业务码 → Status），加载期调用一次（ADR-004）。

    同名重载：映射**完全一致** = 注册表 reload 的幂等续订，不再报错；
    映射不一致 = 装配 bug，显式报错，绝不静默覆盖。
    """
    key = name.strip()
    if not key:
        raise DialectError("方言名不能为空")
    table = dict(mapping)
    for code, status in table.items():
        if not isinstance(status, Status):
            raise DialectError(
                f"方言 {key!r} 的码 {code!r} 映射值不是 Status: {status!r}"
            )
    if key in _DIALECTS:
        if _DIALECTS[key] == table:
            return
        raise DialectError(f"方言重复注册且映射冲突: {key!r}")
    _DIALECTS[key] = table  # 拷贝入册，防调用方事后篡改


def from_engine(text: str, *, dialect: str = "legacy") -> Status:
    """把引擎原始业务码翻译为 Status——唯一翻译入口（A2-01 §2）。

    严格字面匹配：不做 trim / 大小写归一——宽松匹配会掩盖协议变更，
    与行为对照 oracle"同输入同结果"冲突。
    未知方言 → DialectError；未知码 → UnknownEngineCode（不静默兜底，红线 5）。
    """
    table = _DIALECTS.get(dialect)
    if table is None:
        raise DialectError(f"方言未注册: {dialect!r}")
    try:
        return table[text]
    except KeyError:
        raise UnknownEngineCode(text, dialect) from None
