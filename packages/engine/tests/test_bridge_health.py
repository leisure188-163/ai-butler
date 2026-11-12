"""R3-2：bridge 每日体检轮询（register_health_ports → start_health_scans → Run 落账）。"""

import pytest

from kabao_core.application.ports import Capabilities
from kabao_core.application.usecases import ProvisionRequest
from kabao_core.domain.action import Action, ActionKind
from kabao_core.domain.results import Status
from kabao_core.domain.run import RunResult
from kabao_core.domain.vault import Secret
from kabao_engine.bridge import build_engine


class FakeHealthPort:
    def __init__(self, result: RunResult, error: Exception | None = None) -> None:
        self.calls: list[ProvisionRequest] = []
        self._result = result
        self._error = error

    def capabilities(self) -> Capabilities:
        return Capabilities(dry_run=False)

    def run(self, req: ProvisionRequest) -> RunResult:
        self.calls.append(req)
        if self._error is not None:
            raise self._error
        return self._result


def test_register_health_ports_routes_and_refuses_dupes(tmp_path):
    kit = build_engine(tmp_path / "kabao.db")
    try:
        fake = FakeHealthPort(RunResult(status=Status.ALREADY))
        kit.register_health_ports(targets={"chatgpt_web": fake})
        # 同一条 target 路由进 ExecuteAction（health.check 动作可达探针端口）
        action = Action(kind=ActionKind.HEALTH_CHECK, target="chatgpt_web")
        assert kit.execute_action.ports(action) is fake
        # 重复挂载不同对象 = 装配 bug，显式拒绝；replace=True 才可重装
        with pytest.raises(ValueError, match="探针端口重复挂载"):
            kit.register_health_ports(
                targets={"chatgpt_web": FakeHealthPort(RunResult(status=Status.ALREADY))}
            )
        kit.register_health_ports(
            targets={"chatgpt_web": FakeHealthPort(RunResult(status=Status.ALREADY))},
            replace=True,
        )
        # 与已挂 provision 端口的 target 撞车 = 一 target 一端口纪律，显式拒绝
        kit.register_provision_ports(targets={"trae_cn": fake})
        with pytest.raises(ValueError, match="撞车"):
            kit.register_health_ports(
                targets={"trae_cn": FakeHealthPort(RunResult(status=Status.ALREADY))}
            )
    finally:
        kit.close()


def test_daily_health_scan_job(tmp_path):
    """端显式启动（同到期/用量扫描纪律），_daily_health 全账号一轮；Run 落账可读回。"""
    kit = build_engine(tmp_path / "kabao.db")
    fake = FakeHealthPort(RunResult(status=Status.ALREADY))
    kit.register_health_ports(targets={"chatgpt_web": fake})
    kit.register_account.execute("chatgpt_web", "ChatGPT")  # 名册账号：provider 有探针
    kit.register_account.execute("trae_cn", "Trae")  # provider 无探针端口 → 跳过
    kit.vault.store("acc-lonely", "cookie", Secret("x"), expires_at=None)  # vault-only → 跳过
    try:
        assert kit.health_job is None  # 默认不启动，由端显式 start

        kit._daily_health()  # 同步驱动一轮（start 的补扫跑同一 fn）
        assert [req.account_id for req in fake.calls] == ["chatgpt_web:main"]
        assert fake.calls[0].kind is ActionKind.HEALTH_CHECK

        runs = kit.ledger.list_recent(limit=10)
        assert [r.result.status for r in runs] == [Status.ALREADY]
        assert runs[0].action.kind is ActionKind.HEALTH_CHECK

        kit.start_health_scans()  # 启动即补扫一轮（IntervalJob 语义，异步）
        assert kit.health_job is not None and kit.health_job.running
        kit.start_health_scans()  # 幂等：running 时不叠加
        assert kit.health_job.running
    finally:
        kit.close()
    assert kit.health_job is None  # close 排空 job（同 checkin/scan/usage）


def test_daily_health_isolates_account_failures(tmp_path):
    """单账号适配器异常：ExecuteAction 落账 FAILED 后上抛，job 兜住不拖累其余账号。"""
    kit = build_engine(tmp_path / "kabao.db")
    boom = FakeHealthPort(RunResult(status=Status.ALREADY), error=RuntimeError("探针炸了"))
    ok = FakeHealthPort(RunResult(status=Status.ALREADY))
    kit.register_health_ports(targets={"chatgpt_web": boom, "claude_web": ok})
    kit.register_account.execute("chatgpt_web", "ChatGPT")
    kit.register_account.execute("claude_web", "Claude")
    try:
        kit._daily_health()  # 不抛——boom 账号进 WARNING，ok 账号照常体检
        assert [req.account_id for req in ok.calls] == ["claude_web:main"]
        statuses = {r.action.target: r.result.status for r in kit.ledger.list_recent(limit=10)}
        assert statuses["claude_web"] is Status.ALREADY
        assert statuses["chatgpt_web"] is Status.FAILED  # 适配器异常如实落账
    finally:
        kit.close()
