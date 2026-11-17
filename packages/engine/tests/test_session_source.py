"""会话扫描源装配测试（R5-S1）：register_session_source 防撞车 + 未装配如实 None。"""

from __future__ import annotations

import pytest

from butler_engine.bridge import build_engine


class FakeScanner:
    app = "trae_cn"

    def scan_sessions(self, app: str):
        return []

    def enumerate_accounts(self, app: str):
        return []


def test_未装配_session_scan如实None(tmp_path) -> None:
    kit = build_engine(tmp_path / "butler.db")
    assert kit.session_scan is None
    kit.close()


def test_装配后可用_重复装配显式拒绝(tmp_path) -> None:
    kit = build_engine(tmp_path / "butler.db")
    try:
        kit.register_session_source(FakeScanner())
        assert kit.session_scan is not None
        assert kit.session_scan.source.app == "trae_cn"
        with pytest.raises(ValueError, match="重复装配"):
            kit.register_session_source(FakeScanner())
    finally:
        kit.close()
