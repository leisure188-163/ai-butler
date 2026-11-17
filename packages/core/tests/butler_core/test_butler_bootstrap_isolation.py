"""装配根 + 依赖恒等式机检（A1-05 §2）：域 domain.py 只准 import shared。"""

import ast
from pathlib import Path

from butler_core.accounts.ports import AccountRepository
from butler_core.bootstrap import Kit, build_kit, execute_action
from butler_core.execution.ports import RunLedger
from butler_core.shared.events import EventSink
from butler_core.usage.ports import UsageStore

DOMAINS = {"accounts", "execution", "usage", "health", "scheduling"}


class _Accounts(AccountRepository):
    def save(self, account): pass
    def get(self, account_id): return None
    def list_by_app(self, app): return []
    def list_all(self): return []


class _Ledger(RunLedger):
    def save(self, run): pass
    def find_by_idempotency_key(self, key): return None
    def list_for_account(self, account_id, *, limit): return []
    def list_recent(self, *, limit): return []


class _Sink(EventSink):
    def publish(self, event): pass


class _Store(UsageStore):
    def save_snapshot(self, snapshot): pass
    def list_snapshots(self, account_id, *, limit): return []
    def save_aggregate(self, aggregate): pass
    def latest_aggregate(self, account_id): return None
    def append_ledger(self, entries): return 0
    def list_ledger(self, account_id, *, limit): return []
    def append_sample(self, sample): pass
    def list_samples(self, account_id=None, *, limit): return []


def test_build_kit_assembles_five_domains():
    kit = build_kit(ledger=_Ledger(), sink=_Sink(), accounts=_Accounts(),
                    usage_store=_Store())
    assert isinstance(kit, Kit)
    assert kit.execute_action is not None
    assert kit.register_account is not None
    assert kit.list_pending is not None
    assert kit.collect_usage is not None
    assert execute_action(_Ledger(), _Sink()) is not None


def test_domain_modules_import_only_shared():
    root = Path(__file__).resolve().parents[2] / "src" / "butler_core"
    for domain in DOMAINS:
        path = root / domain / "domain.py"
        assert path.exists(), path
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                parts = node.module.split(".")
                if parts[0] != "butler_core":
                    continue
                assert parts[1] == "shared", f"{path.name} 违规跨域 import {node.module}"
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("butler_core."):
                        assert alias.name.split(".")[1] == "shared"


def test_no_framework_in_core():
    root = Path(__file__).resolve().parents[2] / "src" / "butler_core"
    forbidden = {"fastapi", "sqlalchemy", "typer", "pydantic", "httpx"}
    for py in root.rglob("*.py"):
        tree = ast.parse(py.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert node.module.split(".")[0] not in forbidden
