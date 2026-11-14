"""A2-01 §2 / ADR-002：结果词汇单源的行为基线。

- 字面量冻结：oracle 对齐，多一个少一个都是协议事故
- 谓词表：端零映射的语义唯一出处
- 方言注册表：数据驱动、重复注册显式报错、未知码不静默兜底（红线 5）
"""

import pytest
from dataclasses import FrozenInstanceError

from butler_core.shared.results import DialectError, ResultKind, Status, UnknownEngineCode, from_engine, register_dialect

# A2-01 §2 清单：字面量为 oracle 对齐固定值
EXPECTED_LITERALS = {
    "CLAIMED",
    "ALREADY",
    "NO_AUTH",
    "EXPIRED",
    "FAILED",
    "PENDING",
    "SKIPPED",
}


def test_status_literals_frozen():
    assert {s.value for s in Status} == EXPECTED_LITERALS
    assert len(Status) == 7


def test_status_is_str_enum():
    assert isinstance(Status.CLAIMED, str)
    assert str(Status.ALREADY) == "ALREADY"  # 序列化即字面量，oracle 零损耗


# 谓词表语义（ADR-002 评审定的映射，见 results.py 表内注释）
EXPECTED_KINDS = {
    Status.CLAIMED: (True, False, False),
    Status.ALREADY: (True, False, False),
    Status.NO_AUTH: (False, True, False),
    Status.EXPIRED: (False, True, False),
    Status.FAILED: (False, False, True),
    Status.PENDING: (False, False, False),
    Status.SKIPPED: (False, False, False),
}


def test_kind_table():
    for status, expected in EXPECTED_KINDS.items():
        assert status.kind == ResultKind(*expected)


# 视觉信号桶（A3-01 §4 渲染纪律的 core 单源；UI 只消费这五词）
EXPECTED_SIGNALS = {
    Status.CLAIMED: "ok",
    Status.ALREADY: "ok",
    Status.NO_AUTH: "attention",
    Status.EXPIRED: "attention",
    Status.FAILED: "danger",
    Status.PENDING: "quiet",
    Status.SKIPPED: "quiet",
}


def test_signal_buckets():
    for status, signal in EXPECTED_SIGNALS.items():
        assert status.kind.signal == signal


def test_kind_is_frozen_dataclass():
    with pytest.raises(FrozenInstanceError):
        Status.FAILED.kind.is_pass = True  # type: ignore[misc]


def test_from_engine_legacy_identity():
    for status in Status:
        assert from_engine(status.value) is status


def test_from_engine_strict_no_normalization():
    with pytest.raises(UnknownEngineCode):
        from_engine(" claimed")  # 不做 trim
    with pytest.raises(UnknownEngineCode):
        from_engine("claimed")  # 不做大小写归一


def test_from_engine_unknown_code_carries_context():
    register_dialect("dialect_ctx", {"KNOWN": Status.CLAIMED})
    with pytest.raises(UnknownEngineCode) as ei:
        from_engine("VOUCHER_GONE", dialect="dialect_ctx")
    assert ei.value.code == "VOUCHER_GONE"
    assert ei.value.dialect == "dialect_ctx"


def test_from_engine_unknown_dialect():
    with pytest.raises(DialectError):
        from_engine("CLAIMED", dialect="no_such_dialect")


def test_register_and_translate():
    register_dialect(
        "dialect_ok",
        {"已领取": Status.ALREADY, "口令失效": Status.EXPIRED},
    )
    assert from_engine("已领取", dialect="dialect_ok") is Status.ALREADY
    assert from_engine("口令失效", dialect="dialect_ok") is Status.EXPIRED


def test_register_duplicate_name_rejected():
    register_dialect("dialect_dup", {"X": Status.CLAIMED})
    with pytest.raises(DialectError):
        register_dialect("dialect_dup", {"Y": Status.FAILED})


def test_register_rejects_non_status_values():
    with pytest.raises(DialectError):
        register_dialect("dialect_bad_value", {"X": "CLAIMED"})  # type: ignore[dict-item]


def test_register_rejects_blank_name():
    with pytest.raises(DialectError):
        register_dialect("   ", {"X": Status.CLAIMED})


def test_register_copies_mapping():
    raw = {"X": Status.CLAIMED}
    register_dialect("dialect_copy", raw)
    raw["X"] = Status.FAILED  # 事后篡改调用方字典，不影响已注册方言
    assert from_engine("X", dialect="dialect_copy") is Status.CLAIMED


def test_builtin_legacy_protected():
    with pytest.raises(DialectError):
        register_dialect("legacy", {"X": Status.CLAIMED})
