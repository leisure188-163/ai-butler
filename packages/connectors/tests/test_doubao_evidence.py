"""豆包失败留证与点击前身份硬断言（2026-11-19 用户裁决）。

拆分自 test_doubao_adapter.py（单文件 600 行硬上限）。两块能力各测语义：

- ``evidence.assert_identity``：连读两次必须都命中目标；读不到 = 未知 = 不放行
- ``snapshot.record_failure_evidence``：现场包落盘、签名类脱敏、
  ``landing/checkin`` 请求单独归到 ``checkin_requests``（判「平台拒绝」的抓手）
"""

from __future__ import annotations

import json

import pytest

from butler_connectors.doubao_cn import evidence, snapshot

MAIN_SEC_UID = "MS4wTESTMAIN000000"
B_SEC_UID = "MS4wTESTBBBB000000"


class FakeConn:
    def close(self) -> None: ...


class FakeIdentChannel:
    """只实现身份查询链路：targets() → attach() → evaluate（read_all_identities 的形状）。"""

    def __init__(self, identity: dict | None) -> None:
        self.identity = identity

    def targets(self) -> list[dict]:
        return [
            {
                "type": "page",
                "url": "doubao://doubao-chat/chat",
                "webSocketDebuggerUrl": "ws://chat",
            }
        ]

    def attach(self, target: dict) -> FakeConn:
        return FakeConn()

    def evaluate(self, conn, expression: str, **kwargs):
        if "for_ban_appeal_sec_user_id" in expression:
            return dict(self.identity) if self.identity else None
        return None


def test_assert_identity_passes_for_two_matching_reads():
    channel = FakeIdentChannel({"sec_uid": MAIN_SEC_UID, "nickname": "逍遥酒鬼"})
    assert evidence.assert_identity(
        channel, "doubao_cn", "doubao_cn:逍遥酒鬼", sleep=lambda _s: None
    ) is None


def test_assert_identity_blocks_when_account_not_flipped():
    channel = FakeIdentChannel({"sec_uid": B_SEC_UID, "nickname": "小号"})
    reason = evidence.assert_identity(
        channel, "doubao_cn", "doubao_cn:逍遥酒鬼", sleep=lambda _s: None
    )
    assert reason is not None
    assert "身份断言未过" in reason and "小号" in reason


def test_assert_identity_blocks_when_identity_unreadable():
    """主窗口读不到身份（None）→ 不放行：未知不等于通过。"""
    channel = FakeIdentChannel(None)
    assert evidence.assert_identity(
        channel, "doubao_cn", "doubao_cn:逍遥酒鬼", sleep=lambda _s: None
    ) is not None


def test_failure_evidence_redacts_signature_and_flags_checkin(tmp_path, monkeypatch):
    """现场包：签名类只存 hash；带 landing/checkin 的请求单列（判「平台拒绝」）。"""
    monkeypatch.setenv("DOUBAO_FAILURE_DIR", str(tmp_path))
    entries = [
        {
            "transport": "fetch",
            "method": "POST",
            "url": "https://www.doubao.com/alice/ug/campaign/landing/checkin"
            "?msToken=SECRET_MS&a_bogus=SECRET_AB",
            "headers": {"Cookie": "session=SECRET_COOKIE"},
            "body": '{"scene":"pc_incentive_task_mvp_v3"}',
            "response": {"status": 200, "body": '{"code":710010702,"msg":"系统错误"}'},
        },
        {
            "transport": "fetch",
            "method": "POST",
            "url": "https://www.doubao.com/alice/ug/campaign/v3/detail/",
            "headers": {},
            "body": "{}",
            "response": {"status": 200, "body": '{"code":0}'},
        },
    ]
    path = snapshot.record_failure_evidence(
        account_id="doubao_cn:逍遥酒鬼",
        stage="click_no_flip",
        click={"text": "立即签到", "x": 100, "y": 200},
        checks=3,
        detail={"code": 0, "data": {"progress": {"total_amount": 4950}}},
        dom={"items": [{"text": "立即签到"}]},
        page_text="签到领额度，每周一翻倍",
        entries=entries,
    )
    record = json.loads(path.read_text(encoding="utf-8").splitlines()[-1])
    assert record["stage"] == "click_no_flip"
    assert len(record["checkin_requests"]) == 1  # 只有 landing/checkin 算
    blob = path.read_text(encoding="utf-8")
    for secret in ("SECRET_MS", "SECRET_AB", "SECRET_COOKIE"):
        assert secret not in blob, f"{secret} 没脱敏"
    assert "sha256:" in blob  # 敏感值以 hash 留痕
    assert record["detail"]["data"]["progress"]["total_amount"] == 4950


def test_failure_evidence_no_button_has_no_requests(tmp_path, monkeypatch):
    """点空/找不按钮：stage=no_button、checkin_requests 空 = 界面侧问题，非平台拒绝。"""
    monkeypatch.setenv("DOUBAO_FAILURE_DIR", str(tmp_path))
    path = snapshot.record_failure_evidence(
        account_id="doubao_cn:逍遥酒鬼",
        stage="no_button",
        click=None,
        checks=0,
        detail={"code": 0},
        dom={"items": []},
        page_text="签到领额度",
        entries=[],
    )
    record = json.loads(path.read_text(encoding="utf-8").splitlines()[-1])
    assert record["stage"] == "no_button"
    assert record["checkin_requests"] == []
    assert record["click"] is None
