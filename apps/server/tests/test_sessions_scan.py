"""会话扫描端点测试（R5-S1）：TestClient + Fake 扫描源接管 kit.session_scan。

覆盖：扫描入库返回清单 / 404 / 503（未装配如实拒绝）。
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from butler_core.accounts.domain import (
    Account,
    Secret,
    SessionKind,
    SessionLevel,
    SessionSighting,
    account_identity,
)


class FakeScanner:
    app = "trae_cn"

    def scan_sessions(self, app: str):
        return [
            SessionSighting(
                location="/ws/a", kind=SessionKind.WORKSPACE, device_ref="1352866089939851"
            ),
            SessionSighting(location="/User/settings.json", kind=SessionKind.WORKSPACE),
        ]

    def enumerate_accounts(self, app: str):
        return []


class FakeVault:
    """vault.health 空 + device_dn 可读（绑定链路真走 core 用例）。"""

    def load(self, account_id: str, kinds: list[str]):
        from butler_core.accounts.domain import Secret

        return [Secret(_value="1352866089939851")]

    def health(self):
        return []

    def store(self, *a, **kw) -> None: ...
    def rotate(self, *a, **kw) -> None: ...


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("BUTLER_DB", str(tmp_path / "butler.db"))
    monkeypatch.setenv("BUTLER_SCHEDULE", "0")
    from server.main import create_app

    app = create_app()
    with TestClient(app) as tc:
        account = Account(
            id=account_identity("trae_cn", "main"),
            app="trae_cn",
            display_name="trae",
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        tc.app.state.kit.accounts.save(account)
        # Fake vault 与扫描源接管 kit（不动真数据根）
        monkeypatch.setattr(tc.app.state.kit, "vault", FakeVault(), raising=False)
        from butler_core.accounts.usecases.scan_sessions import ScanSessions

        tc.app.state.kit.session_scan = ScanSessions(
            source=FakeScanner(), accounts=tc.app.state.kit.accounts, vault=FakeVault()
        )
        yield tc


def test_扫描入库_清单与unbound如实分列(client: TestClient) -> None:
    resp = client.post("/api/v1/accounts/trae_cn:main/sessions/scan")
    assert resp.status_code == 200
    body = resp.json()
    assert body["account_id"] == "trae_cn:main"
    assert body["added"] == 1
    assert body["sessions"] == [
        {"location": "/ws/a", "kind": "workspace", "level": "local"}
    ]
    assert body["unbound_locations"] == ["/User/settings.json"]


def test_重复扫描幂等(client: TestClient) -> None:
    client.post("/api/v1/accounts/trae_cn:main/sessions/scan")
    body = client.post("/api/v1/accounts/trae_cn:main/sessions/scan").json()
    assert body["added"] == 0 and len(body["sessions"]) == 1


def test_卡不存在_404(client: TestClient) -> None:
    assert (
        client.post("/api/v1/accounts/trae_cn:nope/sessions/scan").status_code == 404
    )
