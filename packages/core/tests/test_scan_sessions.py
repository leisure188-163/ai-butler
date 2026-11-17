"""会话扫描入库用例测试（R5-S1）：绑定解析 / 幂等 / unbound 如实分列。"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from butler_core.accounts.domain import (
    Account,
    AccountInvalid,
    Secret,
    SessionKind,
    SessionLevel,
    SessionSighting,
    account_identity,
)
from butler_core.accounts.ports import CredentialMissing
from butler_core.accounts.usecases.scan_sessions import ScanSessions


def _account(account_id: str) -> Account:
    app, key = account_id.split(":", 1)
    return Account(
        id=account_identity(app, key),
        app=app,
        display_name=account_id,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


class FakeRepo:
    def __init__(self, accounts: list[Account]) -> None:
        self._by_id = {a.id: a for a in accounts}
        self.saved: list[Account] = []

    def save(self, account: Account) -> None:
        self._by_id[account.id] = account
        self.saved.append(account)

    def get(self, account_id: str) -> Account | None:
        return self._by_id.get(account_id)

    def list_by_app(self, app: str) -> list[Account]:
        return [a for a in self._by_id.values() if a.app == app]

    def list_all(self) -> list[Account]:
        return list(self._by_id.values())


class FakeVault:
    def __init__(self, device_by_account: dict[str, str]) -> None:
        self._devices = device_by_account

    def load(self, account_id: str, kinds: list[str]) -> list[Secret]:
        if account_id not in self._devices:
            raise CredentialMissing(f"缺凭据 kind={kinds}")
        return [Secret(_value=self._devices[account_id])]

    # 其余 VaultPort 方法本用例不触（Fake 只实现被用到的）
    def store(self, *a, **kw) -> None: ...
    def rotate(self, *a, **kw) -> None: ...
    def health(self): return []


class FakeSource:
    def __init__(self, sightings: list[SessionSighting]) -> None:
        self._sightings = sightings

    def scan_sessions(self, app: str) -> list[SessionSighting]:
        return self._sightings

    def enumerate_accounts(self, app: str):
        return []


def _make(
    sightings: list[SessionSighting],
    *,
    devices: dict[str, str] | None = None,
    repo: FakeRepo | None = None,
):
    repo = repo or FakeRepo([_account("trae_cn:main")])
    usecase = ScanSessions(
        source=FakeSource(sightings),
        accounts=repo,
        vault=FakeVault(devices or {"trae_cn:main": "1352866089939851"}),
    )
    return usecase, repo


def test_绑定命中_入库workspace会话() -> None:
    usecase, repo = _make(
        [
            SessionSighting(
                location="/ws/a", kind=SessionKind.WORKSPACE, device_ref="1352866089939851"
            )
        ]
    )
    outcome = usecase.scan("trae_cn")
    assert outcome.added == 1 and outcome.accounts == ("trae_cn:main",)
    saved = repo.get("trae_cn:main")
    assert saved.sessions[0].kind == SessionKind.WORKSPACE
    assert saved.sessions[0].level == SessionLevel.LOCAL


def test_重复扫描_幂等不重复入库() -> None:
    sighting = SessionSighting(
        location="/ws/a", kind=SessionKind.WORKSPACE, device_ref="1352866089939851"
    )
    usecase, repo = _make([sighting])
    usecase.scan("trae_cn")
    outcome = usecase.scan("trae_cn")
    assert outcome.added == 0  # (location, kind, level) 已存在
    assert len(repo.get("trae_cn:main").sessions) == 1


def test_无前缀观测_如实unbound不入库() -> None:
    usecase, repo = _make(
        [SessionSighting(location="/User/settings.json", kind=SessionKind.WORKSPACE)]
    )
    outcome = usecase.scan("trae_cn")
    assert outcome.added == 0 and outcome.scanned == 1
    assert [u.location for u in outcome.unbound] == ["/User/settings.json"]
    assert repo.get("trae_cn:main").sessions == ()


def test_device_dn无人持有_unbound如实() -> None:
    usecase, _ = _make(
        [
            SessionSighting(
                location="/ws/b", kind=SessionKind.WORKSPACE, device_ref="9999999999"
            )
        ]
    )
    outcome = usecase.scan("trae_cn")
    assert outcome.added == 0 and len(outcome.unbound) == 1


def test_缺device_dn凭据_该账户跳过绑定() -> None:
    repo = FakeRepo([_account("trae_cn:main")])
    usecase = ScanSessions(
        source=FakeSource(
            [SessionSighting(location="/ws/c", kind=SessionKind.WORKSPACE, device_ref="123")]
        ),
        accounts=repo,
        vault=FakeVault({}),  # 无任何 device_dn
    )
    outcome = usecase.scan("trae_cn")
    assert outcome.added == 0 and len(outcome.unbound) == 1


def test_session_构造校验_空location显式拒绝() -> None:
    from butler_core.accounts.domain import Session

    with pytest.raises(AccountInvalid):
        Session(account_id="trae_cn:main", location="  ", kind=SessionKind.WORKSPACE)
