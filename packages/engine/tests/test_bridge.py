"""bridge 端到端基线（R4）：端只经 bridge 触达引擎，六边形回路闭合。

ExecuteAction → 事件总线 → 审计落账 + 通知中心 → 台账持久化（跨 kit 重启可查）。
"""

import json

from butler_core.execution.usecases.execute_action import RunRequest
from butler_core.execution.domain import Action, ActionKind
from butler_core.shared.events import EventType, Severity
from butler_core.shared.results import Status
from butler_core.execution.domain import RunResult
from butler_engine.bridge import build_engine


class FakePort:
    """M0 无 Connector，测试注入；M1 起这里换真连接器。"""

    def __init__(self, result):
        self._result = result
        self.calls = []

    def capabilities(self):
        from butler_core.execution.ports import Capabilities

        return Capabilities(dry_run=True)

    def run(self, req):
        self.calls.append(req)
        return self._result


def test_end_to_end_claim_flow(tmp_path):
    db = tmp_path / "butler.db"
    kit = build_engine(db)
    req = lambda: RunRequest(  # noqa: E731  同窗口请求
        action=Action(kind=ActionKind.PROVISION_RUN, target="trae_cn"),
        account_id="acc1",
        window="2026-11-10",
    )

    # 第一次：NO_AUTH（失败 → attention 进待处理）
    kit.register_provision_ports(
        kinds={ActionKind.PROVISION_RUN: FakePort(RunResult(status=Status.NO_AUTH))}
    )
    first = kit.execute_action.execute(req())
    assert first.result.status is Status.NO_AUTH

    assert kit.bus.drain()  # 事件分发完成（审计 + 通知都已消费）
    audit_rows = json.loads(kit.audit.export_json())
    assert len(audit_rows) == 1  # 领取类写动作 → 审计
    assert audit_rows[0]["outcome"] == "NO_AUTH"
    assert len(kit.notify.items) == 1  # attention 级 → 应用内通知可见
    assert kit.notify.items[0].severity is Severity.BADGE

    # 失败可重试：这次成功领取
    kit.register_provision_ports(
        kinds={ActionKind.PROVISION_RUN: FakePort(RunResult(status=Status.CLAIMED))}
    )
    claimed = kit.execute_action.execute(req())
    assert claimed.id != first.id
    assert claimed.result.status is Status.CLAIMED

    # 同窗口重复触发 → 回放，绝不重复领取
    assert kit.execute_action.execute(req()).id == claimed.id

    # 台账持久化：换一个 kit（模拟重启），幂等命中依然有效
    kit.close()
    kit2 = build_engine(db)
    kit2.register_provision_ports(
        kinds={ActionKind.PROVISION_RUN: FakePort(RunResult(status=Status.CLAIMED))}
    )
    assert kit2.execute_action.execute(req()).id == claimed.id
    kit2.close()
