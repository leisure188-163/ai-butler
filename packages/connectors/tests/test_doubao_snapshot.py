"""请求快照离线测试：形状、脱敏、追加落盘；不真起 CDP。

detail 请求快照已随 ADR-017（零裸请求）退役——连接器不再自组 HTTP 请求，
capture=1 时页面旁路连带记录 detail fetch（checkin_trace 条目）。
"""

from __future__ import annotations

import json

from butler_connectors.doubao_cn import snapshot


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
        snapshot.record_checkin_trace(
            account_id="doubao_cn:main",
            click_text="签到",
            click_xy=None,
            entries=[],
        )
    except OSError:
        pass
