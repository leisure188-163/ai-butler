"""主控 server · Butler API 契约冒烟（M0 三页数据源）。

- 三端点形状 + 端零映射抽查：响应里的 level/status 是 core 出产字面量原样传递，
  server 不做语义映射（红线 2 的机检补位——响应成员必须 ∈ core 词表）
- 注意 PROVISION_RUN 是幂等写动作：同 (kind, account, window) 会回放，
  想要不同 Run 就换窗口
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi.testclient import TestClient

from butler_core.execution.ports import routing_ports
from butler_core.execution.usecases.execute_action import RunRequest
from butler_core.execution.domain import Action, ActionKind
from butler_core.shared.results import Status
from butler_core.execution.domain import Evidence, RepairHint, RunResult
from butler_core.accounts.domain import Secret


def _client(tmp_path: Path) -> TestClient:
    os.environ["BUTLER_DB"] = str(tmp_path / "butler.db")
    os.environ["BUTLER_SCHEDULE"] = "0"  # 关调度：用量 job 启动补扫会与假件端口竞态
    os.environ["BUTLER_SYSTEM_NOTIFY"] = "0"  # 测试不真弹系统通知（ADR-015）
    from server.main import app

    return TestClient(app)


class FakePort:
    def __init__(self, result: RunResult):
        self._result = result

    def capabilities(self):
        from butler_core.execution.ports import Capabilities

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
                "account_key": "acc1",  # 多账号维度（ADR-003）
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
                "sessions": [],  # R5-S1：名册投影带会话清单（vault-only 账号如实空）
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


def test_no_auth_run_enters_pending_with_relogin_hint(tmp_path):
    """登录态失效 → 待办可见 + 带修复动作（ADR-015 端到端契约）。"""
    with _client(tmp_path) as client:
        kit = client.app.state.kit
        kit.vault.store("acc1", "cookie", Secret("x"), expires_at=None)
        kit.execute_action.ports = routing_ports(
            {
                ActionKind.PROVISION_RUN: FakePort(
                    RunResult(
                        status=Status.NO_AUTH,
                        evidence=(
                            Evidence(
                                summary="鉴权被拒（HTTP 401）——登录态已失效",
                                raw_code="401",
                            ),
                        ),
                        repair_hint=RepairHint(
                            reason="登录态已失效——重新登录后重新扫描",
                            action_id="relogin",
                        ),
                    )
                )
            },
            {},
        )
        row = client.post(
            "/api/v1/runs", json={"target": "trae_cn", "account_id": "acc1"}
        ).json()
        assert row["status"] == "NO_AUTH"
        assert row["signal"] == "attention"
        assert row["repair_action_id"] == "relogin"
        pending = client.get("/api/v1/pending").json()
        assert [p["account_id"] for p in pending] == ["acc1"]


# --- R3 体检探针（health.check 走 /runs 通道，A2-03）---


def test_assembly_mounts_health_ports(tmp_path):
    """R3 接线：lifespan 装配探针端口（2026-11-13 真机抓到漏挂 → UnsupportedAction 500）。"""
    with _client(tmp_path) as client:
        kit = client.app.state.kit
        action = Action(kind=ActionKind.HEALTH_CHECK, target="chatgpt_web")
        assert kit.execute_action.ports(action) is not None  # 只验路由面，不触真网


def test_post_runs_health_check_window_free(tmp_path):
    """体检免窗口（非领取类写动作，无幂等键）；预算读能力 budget_seconds。"""
    with _client(tmp_path) as client:
        kit = client.app.state.kit
        kit.execute_action.ports = routing_ports(
            {}, {"chatgpt_web": FakePort(RunResult(status=Status.ALREADY))}
        )
        row = client.post(
            "/api/v1/runs", json={"target": "chatgpt_web", "kind": "health.check"}
        ).json()
        assert row["status"] == "ALREADY"  # core 出产字面量原样传递
        assert row["signal"] == "ok"

        resp = client.post(
            "/api/v1/runs", json={"target": "trae_cn", "kind": "health.check"}
        )
        assert resp.status_code == 422  # 未申报 health.check 能力，显式拒绝


# --- R2 用量雷达 ---


class FakeUsagePort:
    """用量端口假件：按队列逐次吐 UsageResult（同 FakePort 接管先例）。"""

    def __init__(self, results):
        self._results = list(results)
        self.calls = []

    def collect(self, req):
        self.calls.append(req)
        return self._results.pop(0)


def _usage_result(remaining: float, *, total: float = 3200, collected_at=None):
    from datetime import datetime, timezone

    from butler_core.shared.ids import new_id
    from butler_core.usage.domain import PackageQuota, UsageAggregate, UsageResult, UsageSnapshot

    now = collected_at or datetime.now(timezone.utc)
    pkg = PackageQuota(
        package_id="add_on_quota", name="加量包", total=total,
        used=total - remaining, remaining=remaining, unit="credits",
    )
    return UsageResult(
        snapshot=UsageSnapshot(
            id=new_id(), account_id="trae_cn:main", target="trae_cn", collected_at=now,
            packages=(pkg,),
        ),
        aggregate=UsageAggregate(
            id=new_id(), account_id="trae_cn:main", target="trae_cn",
            collected_at=now, summary={"consumed_amount": total - remaining},
        ),
        ledger=None,
    )


def test_usage_radar_empty_on_fresh_port(tmp_path):
    with _client(tmp_path) as client:
        assert client.get("/api/v1/usage/radar").json() == []


def test_usage_collect_then_radar_roundtrip(tmp_path):
    """采集 → 雷达读回：快照/聚合投影；两帧后预测非空（耗尽日 core 出产）。"""
    from datetime import datetime, timedelta, timezone

    with _client(tmp_path) as client:
        kit = client.app.state.kit
        account = kit.register_account.execute("trae_cn", "Trae CN")
        # 接管用量端口（假件，同 _run_action 接管先例）：两帧差分 500/天（不触低额线）
        t1 = datetime.now(timezone.utc)
        port = FakeUsagePort([
            _usage_result(2000, collected_at=t1),
            _usage_result(1500, collected_at=t1 + timedelta(days=1)),
        ])
        kit.collect_usage.ports = {"trae_cn": port}

        outcomes = client.post("/api/v1/usage/collect").json()
        assert outcomes == [
            {
                "account_id": account.id,
                "target": "trae_cn",
                "snapshot_saved": True,
                "aggregate_saved": True,
                "ledger_saved": 0,
                "quota_low": [],
                "error": None,
            }
        ]

        radar = client.get("/api/v1/usage/radar").json()
        assert len(radar) == 1
        row = radar[0]
        assert row["account_id"] == account.id
        assert row["provider"] == "trae_cn"
        assert row["packages"] == [
            {
                "package_id": "add_on_quota", "name": "加量包",
                "total": 3200.0, "used": 1200.0, "remaining": 2000.0,
                "unit": "credits", "cycle_end": None, "status": "",
            }
        ]
        assert row["forecasts"] == []  # 单帧不足 → 「采集中」
        assert row["aggregate_summary"] == {"consumed_amount": 1200.0}
        assert row["recent_ledger"] == []

        # 第二帧：差分 500/天 → 预测耗尽日（core 出产，端原样传）
        client.post("/api/v1/usage/collect")
        radar2 = client.get("/api/v1/usage/radar").json()
        forecasts = radar2[0]["forecasts"]
        assert len(forecasts) == 1
        assert forecasts[0]["package_id"] == "add_on_quota"
        assert forecasts[0]["per_day"] == 500.0
        assert forecasts[0]["days_left"] == 3.0  # 1500/500
        assert forecasts[0]["exhausted_on"] is not None


def test_usage_collect_low_quota_reports_core_predicate(tmp_path):
    """QUOTA_LOW：remaining/total ≤ 20%（core 谓词）→ outcome.quota_low 上报名。"""
    with _client(tmp_path) as client:
        kit = client.app.state.kit
        kit.register_account.execute("trae_cn", "Trae CN")
        kit.collect_usage.ports = {"trae_cn": FakeUsagePort([_usage_result(500)])}
        outcomes = client.post("/api/v1/usage/collect").json()
        assert outcomes[0]["quota_low"] == ["加量包"]  # 500/3200 ≈ 0.156 ≤ 0.2（core 谓词）


def test_usage_collect_missing_port_reports_error(tmp_path):
    """未接入用量通道的账号如实 error，不静默也不 500。"""
    with _client(tmp_path) as client:
        kit = client.app.state.kit
        kit.register_account.execute("doubao_cn", "Doubao CN")
        # 显式接管端口面（同 _run_action 纪律）：lifespan 挂了真端口，真机
        # Doubao 在跑时真端口会抢跑成功——测试必须与机器状态无关
        kit.collect_usage.ports = {}
        outcomes = client.post("/api/v1/usage/collect").json()
        assert len(outcomes) == 1
        assert outcomes[0]["target"] == "doubao_cn"
        assert outcomes[0]["snapshot_saved"] is False
        assert "error" in outcomes[0] and outcomes[0]["error"]


def test_usage_radar_shows_ledger_entries(tmp_path):
    """doubao 形态：无快照有流水——雷达行流水如实分列（R2 块①可得性矩阵）。"""
    from datetime import datetime, timezone

    from butler_core.shared.ids import new_id
    from butler_core.usage.domain import QuotaLedgerEntry, UsageResult

    with _client(tmp_path) as client:
        kit = client.app.state.kit
        account = kit.register_account.execute("doubao_cn", "Doubao CN")
        entry = QuotaLedgerEntry(
            record_id="r1", account_id=account.id, target="doubao_cn",
            amount=200, unit="POINT", occurred_at=datetime(2026, 11, 12, tzinfo=timezone.utc),
            kind="签到",
        )
        port = FakeUsagePort([UsageResult(ledger=(entry,))])
        kit.collect_usage.ports = {"doubao_cn": port}
        client.post("/api/v1/usage/collect")
        radar = client.get("/api/v1/usage/radar").json()
        row = radar[0]
        assert row["packages"] == []
        assert row["recent_ledger"] == [
            {
                "record_id": "r1", "amount": 200.0, "unit": "POINT",
                "kind": "签到", "occurred_at": "2026-11-12T00:00:00Z",
            }
        ]


class _BoomUsagePort:
    """collect 即炸的假件：CollectUsage 应收进 outcome.error 而非打断编排。"""

    def collect(self, req):
        raise RuntimeError("本机客户端不在")


class _StubRegistry:
    """dock 假件：绕开真连接器的本机扫描，按真 dock 语义注册号册并回报账号。"""

    def __init__(self, accounts):
        self._accounts = accounts

    def dock(self, ctx, *, target):
        from butler_connectors.registry import DockOutcome

        for acc in self._accounts:
            provider = acc.split(":")[0]
            ctx.register.execute(provider, provider)  # 真 dock 同款：身份落册
        return [DockOutcome(target=target, accounts=list(self._accounts))]


class _BatchRegistry:
    """批量 dock 假件：逐 target 注册 {target}:main（import-all 的编排面专用）。"""

    def __init__(self, targets):
        self._targets = list(targets)

    def apps(self):
        from types import SimpleNamespace

        return [SimpleNamespace(manifest=SimpleNamespace(id=t)) for t in self._targets]

    def dock(self, ctx, *, target):
        from butler_connectors.registry import DockOutcome

        ctx.register.execute(target, target)
        return [DockOutcome(target=target, accounts=[f"{target}:main"])]


def test_import_triggers_usage_collect_and_reports_errors(tmp_path):
    """R2-F dock 顺带采集：导入成功即产第一帧；采集失败如实进 issues，不打断导入。"""
    with _client(tmp_path) as client:
        kit = client.app.state.kit
        client.app.state.registry = _StubRegistry(["trae_cn:main"])
        kit.collect_usage.ports = {"trae_cn": FakeUsagePort([_usage_result(2000)])}

        out = client.post("/api/v1/apps/trae_cn/import").json()
        assert out["accounts"] == ["trae_cn:main"]
        assert out["issues"] == []  # 采集成功：issues 无噪音

        radar = client.get("/api/v1/usage/radar").json()
        assert radar[0]["packages"][0]["remaining"] == 2000.0  # 第一帧已入库

        # 采集失败 → issues 如实上报（红线 5），导入本身不受累
        kit.collect_usage.ports = {"trae_cn": _BoomUsagePort()}
        out2 = client.post("/api/v1/apps/trae_cn/import").json()
        assert out2["accounts"] == ["trae_cn:main"]
        assert any("用量采集" in i and "本机客户端不在" in i for i in out2["issues"])


# --- 一键批量（import-all / claim-all）：编排语义在 server，端零入参 ---


def test_import_all_skips_docked_and_reports_collect_errors(tmp_path):
    """一键导入：只泊未泊位的；顺带采集失败如实进 issues，不拖累别家。"""
    with _client(tmp_path) as client:
        kit = client.app.state.kit
        client.app.state.registry = _BatchRegistry(["trae_cn", "qoder_cn", "doubao_cn"])
        kit.register_account.execute("trae_cn", "Trae CN")  # 已泊位 → 跳过
        kit.collect_usage.ports = {}  # 显式接管端口面：全部采集失败 → issues

        rows = client.post("/api/v1/apps/import-all").json()
        assert [r["target"] for r in rows] == ["qoder_cn", "doubao_cn"]
        for row in rows:
            assert row["accounts"] == [f"{row['target']}:main"]
            assert any("用量采集" in i for i in row["issues"])


def test_import_all_empty_when_nothing_to_dock(tmp_path):
    with _client(tmp_path) as client:
        client.app.state.registry = _BatchRegistry([])
        assert client.post("/api/v1/apps/import-all").json() == []


def test_claim_all_claims_docked_and_replays(tmp_path):
    """一键领取：逐泊位发起；同窗口再点 → 幂等回放同 Run（不重复领取）。"""
    with _client(tmp_path) as client:
        kit = client.app.state.kit
        kit.execute_action.ports = routing_ports(
            {ActionKind.PROVISION_RUN: FakePort(RunResult(status=Status.CLAIMED))}, {}
        )
        kit.register_account.execute("trae_cn", "Trae CN")
        kit.register_account.execute("doubao_cn", "Doubao CN")

        rows = client.post("/api/v1/runs/claim-all").json()
        assert {r["account_id"] for r in rows} == {"trae_cn:main", "doubao_cn:main"}
        assert all(r["status"] == "CLAIMED" for r in rows)

        again = client.post("/api/v1/runs/claim-all").json()
        assert {r["id"] for r in again} == {r["id"] for r in rows}


def test_claim_all_empty_when_no_accounts(tmp_path):
    with _client(tmp_path) as client:
        assert client.post("/api/v1/runs/claim-all").json() == []
