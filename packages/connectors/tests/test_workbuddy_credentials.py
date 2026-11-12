"""credentials offline tests: candidate hits/misses self-report, transient file-lock retries (sleep injectable)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from kabao_connectors.workbuddy_cn import credentials


def test_env_override_hits_file(tmp_path, monkeypatch):
    path = tmp_path / "wb.info"
    path.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("WORKBUDDY_AUTH_FILE", str(path))
    found, looked_in = credentials.find_auth_file()
    assert found == path
    assert looked_in == [str(path)]  # when overridden only this one is reported


def test_env_override_missing_reports_explicitly(tmp_path, monkeypatch):
    missing = tmp_path / "nope.info"
    monkeypatch.setenv("WORKBUDDY_AUTH_FILE", str(missing))
    found, looked_in = credentials.find_auth_file()
    assert found is None
    assert looked_in == [str(missing)]  # only reports that path, no fallback scan


def test_localappdata_hit(tmp_path, monkeypatch):
    monkeypatch.delenv("WORKBUDDY_AUTH_FILE", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    target = (
        tmp_path / "CodeBuddyExtension" / "Data" / "Public" / "auth" / "workbuddy-desktop.info"
    )
    target.parent.mkdir(parents=True)
    target.write_text("{}", encoding="utf-8")
    found, looked_in = credentials.find_auth_file()
    assert found == target
    assert len(looked_in) == 5  # all five candidates were checked
    assert looked_in[0] == str(target)


def test_xdg_cli_path_hit(tmp_path, monkeypatch):
    monkeypatch.delenv("WORKBUDDY_AUTH_FILE", raising=False)
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "home"))
    target = (
        tmp_path / "CodeBuddyExtension" / "Data" / "Public" / "auth"
        / "Tencent-Cloud.coding-copilot.info"
    )
    target.parent.mkdir(parents=True)
    target.write_text("{}", encoding="utf-8")
    found, _ = credentials.find_auth_file()
    assert found == target


def test_all_missed_lists_candidates(tmp_path, monkeypatch):
    monkeypatch.delenv("WORKBUDDY_AUTH_FILE", raising=False)
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    found, looked_in = credentials.find_auth_file()
    assert found is None
    assert len(looked_in) == 5


def test_load_session_parses_json(tmp_path):
    path = tmp_path / "wb.info"
    path.write_text(json.dumps({"auth": {"accessToken": "t"}}), encoding="utf-8")
    assert credentials.load_session(path)["auth"]["accessToken"] == "t"


def test_transient_lock_retries_then_succeeds(tmp_path, monkeypatch):
    path = tmp_path / "wb.info"
    path.write_text("{}", encoding="utf-8")
    slept: list[float] = []
    calls = {"n": 0}
    real_load = credentials.load_session

    def flaky(_path):
        calls["n"] += 1
        if calls["n"] < 3:
            raise PermissionError("client is rewriting the credential file")
        return real_load(_path)

    monkeypatch.setattr(credentials, "load_session", flaky)
    assert credentials.load_session_retry(path, sleep=slept.append) == {}
    assert slept == [2.0, 2.0]  # two retries, two waits, then success


def test_retry_exhausted_reraises(tmp_path, monkeypatch):
    path = tmp_path / "wb.info"
    path.write_text("{}", encoding="utf-8")

    def always_locked(_path):
        raise PermissionError("locked")

    monkeypatch.setattr(credentials, "load_session", always_locked)
    with pytest.raises(PermissionError):
        credentials.load_session_retry(path, sleep=lambda _s: None)
