"""SqliteRunLedger 行为基线：序列化往返、幂等查询语义（A4-01 §5）。"""

from datetime import timedelta

from butler_core.execution.domain import Action, ActionKind
from butler_core.shared.results import Status
from butler_core.execution.domain import Evidence, RepairHint, Run, RunResult
from butler_engine.ledger.sqlite import SqliteRunLedger


def _run(run_id: str, key: str, result: RunResult | None) -> Run:
    run = Run(
        id=run_id,
        action=Action(
            kind=ActionKind.PROVISION_RUN,
            target="trae_cn",
            params={"channel": "platform"},
        ),
        account_id="acc1",
        idempotency_key=key,
        budget=timedelta(seconds=9),
    )
    if result is not None:
        run.finish(result)
    return run


def test_roundtrip_with_full_result(tmp_path):
    ledger = SqliteRunLedger(tmp_path / "m.db")
    source = _run(
        "r1",
        "provision.run:acc1:w",
        RunResult(
            status=Status.NO_AUTH,
            evidence=(Evidence(summary="登录态失效", raw_code="TOKEN_INVALID"),),
            repair_hint=RepairHint(reason="凭据已过期，请重新打开客户端登录", action_id="reopen_client"),
        ),
    )
    ledger.save(source)
    loaded = ledger.find_by_idempotency_key("provision.run:acc1:w")
    assert loaded is not None
    assert loaded.id == "r1"
    assert loaded.action.kind is ActionKind.PROVISION_RUN
    assert loaded.action.target == "trae_cn"
    assert loaded.action.params == {"channel": "platform"}
    assert loaded.account_id == "acc1"
    assert loaded.budget == timedelta(seconds=9)
    assert loaded.result is not None and loaded.result.status is Status.NO_AUTH
    assert loaded.result.evidence[0].raw_code == "TOKEN_INVALID"
    assert loaded.result.repair_hint is not None
    assert loaded.result.repair_hint.action_id == "reopen_client"


def test_non_terminal_run_roundtrip(tmp_path):
    ledger = SqliteRunLedger(tmp_path / "m.db")
    ledger.save(_run("r2", "provision.run:acc1:w", None))
    loaded = ledger.find_by_idempotency_key("provision.run:acc1:w")
    assert loaded is not None and loaded.result is None


def test_find_prefers_pass_run(tmp_path):
    ledger = SqliteRunLedger(tmp_path / "m.db")
    ledger.save(_run("r_fail", "k", RunResult(status=Status.FAILED)))
    ledger.save(_run("r_pass", "k", RunResult(status=Status.CLAIMED)))
    loaded = ledger.find_by_idempotency_key("k")
    assert loaded is not None and loaded.id == "r_pass"  # 命中成功 → 回放它


def test_find_returns_latest_when_no_pass(tmp_path):
    ledger = SqliteRunLedger(tmp_path / "m.db")
    ledger.save(_run("r_old", "k", RunResult(status=Status.FAILED)))
    ledger.save(_run("r_new", "k", RunResult(status=Status.FAILED)))
    loaded = ledger.find_by_idempotency_key("k")
    assert loaded is not None and loaded.id == "r_new"  # 无成功 → 最新一条（可重试）


def test_empty_key_returns_none(tmp_path):
    ledger = SqliteRunLedger(tmp_path / "m.db")
    assert ledger.find_by_idempotency_key("") is None
