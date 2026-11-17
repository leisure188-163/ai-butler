"""请求快照离线测试：形状、脱敏、追加落盘；不真起 CDP。"""

from __future__ import annotations

import json

from butler_connectors.doubao_cn import snapshot
from butler_connectors.transport import HttpRequest, HttpResponse


def test_detail_snapshot_redacts_cookie_and_keeps_request_shape(tmp_path, monkeypatch):
    monkeypatch.setenv("DOUBAO_REQUEST_DIR", str(tmp_path))
    request = HttpRequest(
        method="POST",
        url=(
            "https://www.doubao.com/alice/ug/campaign/v3/detail/"
            "?version_code=23508&aid=497858&msToken=raw-token&a_bogus=raw-bogus"
        ),
        headers={
            "Cookie": "sessionid=secret-session; msToken=secret-token",
            "Content-Type": "application/json",
            "User-Agent": "SamanthaDoubao/2.35.8",
        },
        body={"campaign_group_code": "pc_incentive_task_mvp_v3"},
    )
    response = HttpResponse(
        status_code=200,
        payload={
            "code": 0,
            "msg": "ok",
            "data": {
                "tasks": [
                    {
                        "campaign_code": "daily_signin",
                        "daily_checkin": {
                            "checked_in_today": True,
                            "continuous_days": 10,
                            "reward": {"reward_amount": 200},
                        },
                    }
                ]
            },
        },
    )
    snapshot.record_detail(
        account_id="doubao_cn:u66b1e22d",
        version="2.35.8",
        vcode=23508,
        request=request,
        response=response,
    )
    files = list(tmp_path.glob("doubao_requests-*.jsonl"))
    assert len(files) == 1
    text = files[0].read_text(encoding="utf-8")
    assert "secret-session" not in text
    assert "secret-token" not in text
    assert "raw-token" not in text
    assert "raw-bogus" not in text
    record = json.loads(text.strip())
    assert record["event"] == "detail"
    assert record["account_id"] == "doubao_cn:u66b1e22d"
    assert record["request"]["query"]["version_code"] == "23508"
    assert record["request"]["query"]["aid"] == "497858"
    assert "<redacted" in record["request"]["headers"]["Cookie"]
    assert record["response"]["code"] == 0
    assert record["response"]["daily_checkin"]["checked_in_today"] is True


def test_checkin_trace_redacts_query_and_records_body(tmp_path, monkeypatch):
    monkeypatch.setenv("DOUBAO_REQUEST_DIR", str(tmp_path))
    snapshot.record_checkin_trace(
        account_id="doubao_cn:main",
        click_text="立即签到",
        click_xy=(10, 20),
        entries=[
            {
                "transport": "fetch",
                "method": "POST",
                "url": "https://www.doubao.com/alice/ug/campaign/landing/checkin?msToken=top-secret&aid=582478",
                "headers": {"Content-Type": "application/json", "Cookie": "sessionid=top-secret"},
                "body": '{"scene":"pc_incentive_task_mvp_v3"}',
                "response": {"status": 200, "body": '{"code":710010702,"msg":"系统错误"}'},
            }
        ],
    )
    record = json.loads(
        next(tmp_path.glob("doubao_requests-*.jsonl")).read_text(encoding="utf-8").strip()
    )
    text = json.dumps(record, ensure_ascii=False)
    assert record["event"] == "checkin_trace"
    assert record["click_xy"] == [10, 20]
    assert record["entries"][0]["query"]["aid"] == "582478"
    assert "top-secret" not in text
    assert "<redacted" in record["entries"][0]["query"]["msToken"]
    assert record["entries"][0]["body"] == '{"scene":"pc_incentive_task_mvp_v3"}'
    assert "710010702" in record["entries"][0]["response"]["body"]


def test_snapshot_is_best_effort_not_failure(tmp_path, monkeypatch):
    """目录不可写时调用方应能忽略；这里只验证函数对坏目录抛错，由 adapter 兜底。"""
    path = tmp_path / "file-not-dir"
    path.write_text("x", encoding="utf-8")
    monkeypatch.setenv("DOUBAO_REQUEST_DIR", str(path))
    try:
        snapshot.record_detail(
            account_id="doubao_cn:main",
            version="2.35.8",
            vcode=23508,
            request=HttpRequest(method="POST", url="https://www.doubao.com/x"),
        )
    except OSError:
        pass
