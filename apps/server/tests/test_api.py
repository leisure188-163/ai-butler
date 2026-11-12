"""主控 server · Kabao API 契约冒烟（M0 三页数据源）。

- 三端点形状 + 端零映射抽查：响应里的 level/status 是 core 出产字面量原样传递，
  server 不做语义映射（红线 2 的机检补位——响应成员必须 ∈ core 词表）
- 注意 PROVISION_RUN 是幂等写动作：同 (kind, account, window) 会回放，
  想要不同 Run 就换窗口
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi.testclient import TestClient

from kabao_core.application.ports import routing_ports
from kabao_core.application.usecases import RunRequest
from kabao_core.domain.action import Action, ActionKind
from kabao_core.domain.results import Status
from kabao_core.domain.run import RunResult
from kabao_core.domain.vault import Secret


def _client(tmp_path: Path) -> TestClient:
    os.environ["KABAO_DB"] = str(tmp_path / "kabao.db")
    from server.main import app

    return TestClient(app)


class FakePort:
    def __init__(self, result: RunResult):
        self._result = result

    def capabilities(self):
        from kabao_core.application.ports import Capabilities

        return Capabilities(dry_run=True)

    def run(self, req):
        return self._result


def _run_action(client: TestClient, kind: ActionKind, status: Status, window: str,
                account_id: str = "acc1") -> None:
    kit = client.app.state.kit
    # M1 起 lifespan 装配了真连接器端口（target 精确匹配优先）——测试显式
    # 接管端口选择器，避免真端口抢跑（真 vault 无凭据 → NO_AUTH 假信号）
    kit.execute_action.ports = routing_ports(
        {kind: FakePort(RunResult(status=status))}, {}
    )
    kit.execute_action.execute(
        RunRequest(
            action=Action(kind=kind, target="trae_cn"),
            account_id=account_id,
            window=window,
        )
    )


def test_health_and_empty_pages(tmp_path):
    with _client(tmp_path) as client:
        assert client.get("/health").json() == {"status": "ok"}
        assert client.get("/api/v1/accounts").json() == []  # 全新港：无泊位
        assert client.get("/api/v1/runs").json() == []
        assert client.get("/api/v1/pending").json() == []


def test_accounts_report_core_semantics_unchanged(tmp_path):
    with _client(tmp_path) as client:
        kit = client.app.state.kit
        kit.vault.store("acc1", "cookie", Secret("x"), expires_at=None)
        rows = client.get("/api/v1/accounts").json()
        assert rows == [
            {
                "account_id": "acc1",
                "provider": "",  # vault-only 账号：号册无记录，如实空串
                "display_name": "acc1",  # 缺省回落 account_id
                "level": "healthy",  # core 出产字面量，server 原样传递
                "signal": "ok",  # core 出产视觉分类（端零映射）
                "evidence": [],
                "repair_hint": None,
                "credentials": [
                    {"account_id": "acc1", "kind": "cookie", "level": "healthy",
                     "signal": "ok", "expires_at": None}
                ],
            }
        ]


def test_runs_and_pending_use_core_status_literals(tmp_path):
    with _client(tmp_path) as client:
        _run_action(client, ActionKind.PROVISION_RUN, Status.CLAIMED, window="w-1")
        _run_action(client, ActionKind.PROVISION_RUN, Status.NO_AUTH, window="w-2")

        runs = client.get("/api/v1/runs").json()
        assert {row["status"] for row in runs} <= {s.value for s in Status}
        assert [row["status"] for row in runs] == ["NO_AUTH", "CLAIMED"]  # 新→旧

        pending = client.get("/api/v1/pending").json()
        assert [row["status"] for row in pending] == ["NO_AUTH"]  # attention 聚合


def test_runs_limit_clamped(tmp_path):
    with _client(tmp_path) as client:
        for i in range(3):
            _run_action(client, ActionKind.HEALTH_CHECK, Status.CLAIMED, window=f"w-{i}")
        assert len(client.get("/api/v1/runs", params={"limit": 2}).json()) == 2


def test_bad_limit_is_422(tmp_path):
    with _client(tmp_path) as client:
        assert client.get("/api/v1/runs", params={"limit": 0}).status_code == 422


def test_post_runs_manual_supply(tmp_path):
    """POST /runs 冒烟（2026-11-11 真机验收抓到 timedelta 漏 import 后补防回归）。"""
    with _client(tmp_path) as client:
        kit = client.app.state.kit
        kit.execute_action.ports = routing_ports(
            {ActionKind.PROVISION_RUN: FakePort(RunResult(status=Status.CLAIMED))}, {}
        )
        row = client.post("/api/v1/runs", json={"target": "trae_cn"}).json()
        assert row["status"] == "CLAIMED"  # core 出产字面量原样传递
        assert row["signal"] == "ok"
        # 幂等：同窗口重复发起 → 回放同 Run（服务端不重复领取）
        replay = client.post("/api/v1/runs", json={"target": "trae_cn"}).json()
        assert replay["id"] == row["id"]


def test_post_runs_unknown_target_is_404(tmp_path):
    """未接入连接器显式 404（不静默——曾因裸 KeyError 变 500）。"""
    with _client(tmp_path) as client:
        resp = client.post("/api/v1/runs", json={"target": "no_such_app"})
        assert resp.status_code == 404
        assert "未接入" in resp.json()["detail"]
