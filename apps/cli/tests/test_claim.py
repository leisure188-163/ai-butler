"""CLI claim 账户参数化测试（遗留项收口）：CliRunner + FakeKit，不碰真数据根。

覆盖：默认 main / --account 选卡 / 卡不存在显式报错并列出已有卡 / 未知连接器。
连接器注册表真装载（manifest 本地读，不碰网络）；RunRequest 账户编址断言捕获。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from cli.main import app


class FakeExecuteAction:
    """CLI 契约：Run 必回、result 可为 None（预算内未终态路径）。"""

    def __init__(self) -> None:
        self.requests: list = []

    def execute(self, req):
        self.requests.append(req)
        return SimpleNamespace(
            action=SimpleNamespace(target=req.action.target),
            account_id=req.account_id,
            result=None,
        )


class FakeAccounts:
    def __init__(self, ids: list[str]) -> None:
        self._ids = set(ids)

    def get(self, account_id: str):
        return SimpleNamespace(id=account_id) if account_id in self._ids else None

    def list_by_app(self, app: str):
        return [
            SimpleNamespace(id=i) for i in sorted(self._ids) if i.startswith(app + ":")
        ]


class FakeKit:
    def __init__(self, ids: list[str]) -> None:
        self.accounts = FakeAccounts(ids)
        self.execute_action = FakeExecuteAction()
        self.vault = SimpleNamespace()  # 连接器端口构造期只持有引用，不触真 vault

    def register_provision_ports(self, **kw) -> None: ...

    def close(self) -> None: ...


@pytest.fixture()
def fake_kit(monkeypatch: pytest.MonkeyPatch) -> FakeKit:
    kit = FakeKit(["trae_cn:main", "trae_cn:second"])
    monkeypatch.setattr("cli.main._kit", lambda: kit)
    return kit


runner = CliRunner()


def test_默认main账户(fake_kit: FakeKit) -> None:
    result = runner.invoke(app, ["claim", "trae_cn"])
    assert result.exit_code == 0
    assert fake_kit.execute_action.requests[0].account_id == "trae_cn:main"


def test_account选项_选第二张卡(fake_kit: FakeKit) -> None:
    result = runner.invoke(app, ["claim", "trae_cn", "--account", "second"])
    assert result.exit_code == 0
    assert fake_kit.execute_action.requests[0].account_id == "trae_cn:second"


def test_卡不存在_显式报错并列已有卡(fake_kit: FakeKit) -> None:
    result = runner.invoke(app, ["claim", "trae_cn", "--account", "nope"])
    assert result.exit_code == 2
    assert "卡不存在" in result.output
    assert "trae_cn:main" in result.output and "trae_cn:second" in result.output
    assert fake_kit.execute_action.requests == []  # 校验失败不触执行


def test_未知连接器_显式报错(fake_kit: FakeKit) -> None:
    result = runner.invoke(app, ["claim", "no_such_app"])
    assert result.exit_code == 2
    assert "连接器未接入" in result.output


def test_未导入应用_提示先import(fake_kit: FakeKit) -> None:
    result = runner.invoke(app, ["claim", "workbuddy_cn"])
    assert result.exit_code == 2
    assert "未导入" in result.output
