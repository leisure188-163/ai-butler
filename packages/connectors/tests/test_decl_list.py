"""声明式列表模式（qoder 形状，ADR-006）：三分类判定 × 逐项 claim × 复查确认。

假 transport 剧本化（离线，无 IO）；解锁字段 stub 注入，与 test_decl_runtime 同法。
"""

from datetime import UTC, datetime, timedelta

import pytest

from butler_core.execution.ports import ProvisionRequest
from butler_core.execution.domain import ActionKind
from butler_core.shared.results import Status
from butler_core.accounts.domain import Secret

from butler_connectors.manifest import DeclarativeSpec, ManifestInvalid
from butler_connectors.transport import HttpResponse

CONN = "qoder_cn"  # business_codes 空 —— 列表模式不解析业务码，方言登记留空


def request(dry_run: bool = False, account_id: str = f"{CONN}:main") -> ProvisionRequest:
    return ProvisionRequest(
        kind=ActionKind.PROVISION_RUN,
        target=CONN,
        account_id=account_id,
        params={},
        deadline=datetime.now(UTC) + timedelta(seconds=240),
        dry_run=dry_run,
    )


class FakeVault:
    def load(self, account_id: str, kinds: list[str]) -> list[Secret]:
        return [Secret("stub") for _ in kinds]


class FakeTransport:
    def __init__(self, script: list[HttpResponse]):
        self.script = script
        self.calls: list[tuple[str, str, dict, object]] = []

    def __call__(self, req, *, deadline: datetime) -> HttpResponse:
        self.calls.append((req.method, req.url, dict(req.headers), req.body))
        if not self.script:
            raise AssertionError("剧本耗尽：实现对协议又多发了请求（契约漂移）")
        return self.script.pop(0)


def ok(payload: dict) -> HttpResponse:
    return HttpResponse(status_code=200, payload=payload)


def item(cid: str, claim_status: str) -> dict:
    return {"id": cid, "claimStatus": claim_status, "title": f"活动{cid}"}


def make_port(transport, sleep=None, fields: dict | None = None):
    from butler_connectors.decl import DeclarativeProvisionPort

    spec = DeclarativeSpec.model_validate(
        {
            "auth": {
                "kind": "dpapi_gcm_v10",
                "token_header": {"name": "Authorization", "prefix": "Bearer "},
                "dynamic_headers": {
                    "Cosy-MachineId": "{cosy_machine_id}",
                    "Cosy-MachineToken": "{cosy_machine_token}",
                },
            },
            "status": {
                "request": {"method": "GET", "url": "https://q.test/campaigns"},
                "code_path": "code",
                "expect_ok": "0",
                "list_path": "campaigns",
                "item_filter": {"claimStatus": "CLAIMABLE"},
                "done_filter": {"claimStatus": "CLAIMED"},
            },
            "claim": {
                "request": {
                    "method": "POST",
                    "url": "https://q.test/campaigns/{id}/claim",
                },
                "each": "campaigns",
                "confirm_by_status": True,
                "retry": {"on_codes": [], "backoff_seconds": [5, 15]},
            },
            "business_codes": {},
        }
    )
    return DeclarativeProvisionPort(
        conn_id=CONN,
        display="Qoder CN",
        spec=spec,
        vault=FakeVault(),
        transport=transport,
        kinds=("dpapi_gcm_v10", "umid_cosy"),
        sleep=sleep,
        now=lambda: datetime.now(UTC),
    )


@pytest.fixture(autouse=True)
def stable_unlock(monkeypatch):
    import butler_connectors.decl as decl

    fields = {
        "token": "T",
        "cosy_machine_id": "mid",
        "cosy_machine_token": "mtok",
    }
    monkeypatch.setattr(
        decl, "unlock_all", lambda kinds, secrets: dict(fields), raising=True
    )


def test_list_pending_claimed_all_confirmed():
    transport = FakeTransport(
        [
            ok({"code": 0, "campaigns": [item("a1", "CLAIMABLE"), item("a2", "CLAIMABLE")]}),
            ok({}),  # claim a1（HTTP ok 即受理，响应体形状不参与判定）
            ok({}),  # claim a2
            ok({"code": 0, "campaigns": [item("a1", "CLAIMED"), item("a2", "CLAIMED")]}),
        ]
    )
    result = make_port(transport).run(request())
    assert result.status is Status.CLAIMED
    assert "2 项" in result.evidence[0].summary and "待领清空" in result.evidence[0].summary
    claim_urls = [c[1] for c in transport.calls if "/claim" in c[1]]
    assert claim_urls == [  # 逐项 url 引用列表项字段，顺序 = 列表序
        "https://q.test/campaigns/a1/claim",
        "https://q.test/campaigns/a2/claim",
    ]


def test_list_already_when_only_done():
    transport = FakeTransport(
        [ok({"code": 0, "campaigns": [item("a1", "CLAIMED")]})]
    )
    result = make_port(transport).run(request())
    assert result.status is Status.ALREADY
    assert len(transport.calls) == 1  # 不发无谓 claim


def test_base_url_selected_by_account_key_prefix():
    """同一连接器双产品域：global-* 账户走 global 基址，main/cn-* 走 CN。"""
    spec = DeclarativeSpec.model_validate(
        {
            "auth": {
                "kind": "dpapi_gcm_v10",
                "base_urls": {
                    "main": "https://cn.q.test",
                    "cn": "https://cn.q.test",
                    "global": "https://global.q.test",
                },
                "token_header": {"name": "Authorization", "prefix": "Bearer "},
                "dynamic_headers": {"Cosy-MachineId": "{cosy_machine_id}"},
            },
            "status": {
                "request": {"method": "GET", "url": "{base_url}/campaigns"},
                "code_path": "",
                "list_path": "campaigns",
                "item_filter": {"claimStatus": "CLAIMABLE"},
                "done_filter": {"claimStatus": "CLAIMED"},
            },
            "claim": {
                "request": {
                    "method": "POST",
                    "url": "{base_url}/campaigns/{campaignId}/claim",
                },
                "each": "campaigns",
                "retry": {"on_codes": [], "backoff_seconds": [5]},
            },
            "business_codes": {},
        }
    )
    from butler_connectors.decl import DeclarativeProvisionPort

    transport = FakeTransport(
        [
            ok({"campaigns": [{"campaignId": "g1", "claimStatus": "CLAIMABLE"}]}),
            ok({}),
            ok({"campaigns": [{"campaignId": "g1", "claimStatus": "CLAIMED"}]}),
        ]
    )
    port = DeclarativeProvisionPort(
        conn_id=CONN,
        display="Qoder",
        spec=spec,
        vault=FakeVault(),
        transport=transport,
        kinds=("dpapi_gcm_v10",),
        sleep=lambda s: None,
        now=lambda: datetime.now(UTC),
    )
    result = port.run(request(account_id="qoder_cn:global-abc12345"))
    assert result.status is Status.CLAIMED
    assert transport.calls[0][1] == "https://global.q.test/campaigns"
    assert transport.calls[1][1] == "https://global.q.test/campaigns/g1/claim"
    assert transport.calls[2][1] == "https://global.q.test/campaigns"

    # CN 首账户仍走 CN 基址
    transport2 = FakeTransport([ok({"campaigns": [item("a1", "CLAIMED")]})])
    port2 = DeclarativeProvisionPort(
        conn_id=CONN,
        display="Qoder",
        spec=spec,
        vault=FakeVault(),
        transport=transport2,
        kinds=("dpapi_gcm_v10",),
        sleep=lambda s: None,
        now=lambda: datetime.now(UTC),
    )
    port2.run(request())
    assert transport2.calls[0][1] == "https://cn.q.test/campaigns"


def test_list_empty_is_pending():
    transport = FakeTransport([ok({"code": 0, "campaigns": []})])
    result = make_port(transport).run(request())
    assert result.status is Status.PENDING
    assert "活动未开始或已结束" in result.evidence[0].summary


def test_no_envelope_code_http_ok_is_verdict_source():
    """无外壳业务码协议（qoder 真机取证 2026-11-11）：code_path 留空，HTTP 200 即 ok。

    与真机同形：顶层直接业务字段，两项均 CLAIMED → ALREADY。
    """
    from butler_connectors.decl import DeclarativeProvisionPort

    spec = DeclarativeSpec.model_validate(
        {
            "auth": {"kind": "dpapi_gcm_v10"},
            "status": {
                "request": {"method": "GET", "url": "https://q.test/campaigns"},
                "code_path": "",  # 无外壳码
                "list_path": "campaigns",
                "item_filter": {"claimStatus": "CLAIMABLE", "actionType": "CLAIM_BENEFIT"},
                "done_filter": {"claimStatus": "CLAIMED"},
            },
            "claim": {
                "request": {
                    "method": "POST",
                    "url": "https://q.test/campaigns/{campaignId}/claim",
                },
                "each": "campaigns",
                "retry": {"on_codes": [], "backoff_seconds": [5]},
            },
            "business_codes": {},
        }
    )
    transport = FakeTransport(
        [
            ok(
                {  # 真机 2026-11-11 实录形状（脱敏裁剪）
                    "uid": "u-36",
                    "showCampaign": True,
                    "claimable": False,
                    "campaigns": [
                        {
                            "campaignId": "c1",
                            "actionType": "CLAIM_BENEFIT",
                            "claimStatus": "CLAIMED",
                        },
                        {
                            "campaignId": "c2",
                            "actionType": "VIEW_DETAILS",  # 促销详情：不可领取型
                            "claimStatus": "CLAIMED",
                        },
                    ],
                }
            )
        ]
    )
    result = DeclarativeProvisionPort(
        conn_id="qoder_cn",
        display="Qoder CN",
        spec=spec,
        vault=FakeVault(),
        transport=transport,
        kinds=("dpapi_gcm_v10", "umid_cosy"),
        sleep=lambda s: None,
        now=lambda: datetime.now(UTC),
    ).run(request())
    assert result.status is Status.ALREADY
    assert len(transport.calls) == 1  # 不发无谓 claim（VIEW_DETAILS 也不会被误发）


def test_list_filter_leaves_unrelated_items_pending():
    """列表里只有不可领取项（INACTIVE）且无已领标记 → PENDING（三分类之'都无'）。"""
    transport = FakeTransport(
        [ok({"code": 0, "campaigns": [item("a9", "INACTIVE")]})]
    )
    result = make_port(transport).run(request())
    assert result.status is Status.PENDING


def test_list_dry_run_reports_item_count():
    transport = FakeTransport(
        [ok({"code": 0, "campaigns": [item("a1", "CLAIMABLE"), item("a2", "CLAIMABLE"), item("a3", "CLAIMABLE")]})]
    )
    result = make_port(transport).run(request(dry_run=True))
    assert result.status is Status.SKIPPED
    assert "将领 3 项" in result.evidence[0].summary
    assert len(transport.calls) == 1  # 只查了 status


def test_list_claim_http_fail_backoff_then_failed():
    transport = FakeTransport(
        [
            ok({"code": 0, "campaigns": [item("a1", "CLAIMABLE"), item("a2", "CLAIMABLE")]}),
            ok({}),  # a1 ok
            HttpResponse(status_code=429, payload={}),  # a2 限流
            HttpResponse(status_code=429, payload={}),
            HttpResponse(status_code=429, payload={}),  # 退避 [5,15] 用尽
        ]
    )
    waits: list[int] = []
    result = make_port(transport, sleep=waits.append).run(request())
    assert result.status is Status.FAILED
    assert "第 2/2 项 HTTP 429" in result.evidence[0].summary
    assert waits == [5, 15]  # 退避时长如实


def test_list_recheck_still_pending():
    transport = FakeTransport(
        [
            ok({"code": 0, "campaigns": [item("a1", "CLAIMABLE")]}),
            ok({}),
            ok({"code": 0, "campaigns": [item("a1", "CLAIMABLE")]}),  # 复查仍待领
        ]
    )
    result = make_port(transport).run(request())
    assert result.status is Status.PENDING
    assert "仍有 1 项" in result.evidence[0].summary


def test_list_missing_item_field_failed():
    """claim url 引用的列表项字段缺失 = 协议形状变化 → FAILED 显式证据。"""
    transport = FakeTransport(
        [
            ok({"code": 0, "campaigns": [{"claimStatus": "CLAIMABLE"}]}),  # 无 id
        ]
    )
    result = make_port(transport).run(request())
    assert result.status is Status.FAILED
    assert "声明执行事故" in result.evidence[0].summary


def test_each_must_reference_list_path():
    bad = {
        "auth": {"kind": "dpapi_gcm_v10"},
        "status": {
            "request": {"method": "GET", "url": "https://q.test/c"},
            "list_path": "campaigns",
            "item_filter": {"claimStatus": "CLAIMABLE"},
        },
        "claim": {
            "request": {"method": "POST", "url": "https://q.test/c/{id}/claim"},
            "each": "elsewhere",  # 引用了不存在的段
            "retry": {"on_codes": []},
        },
        "business_codes": {},
    }
    with pytest.raises(ManifestInvalid, match="list_path"):
        DeclarativeSpec.model_validate(bad)


def test_list_mode_requires_item_filter():
    bad = {
        "auth": {"kind": "dpapi_gcm_v10"},
        "status": {
            "request": {"method": "GET", "url": "https://q.test/c"},
            "list_path": "campaigns",
            "item_filter": {},  # 列表模式缺待领筛选
        },
        "claim": {"request": {"method": "POST", "url": "https://q.test/c/{id}/claim"}},
        "business_codes": {},
    }
    with pytest.raises(ManifestInvalid, match="item_filter"):
        DeclarativeSpec.model_validate(bad)
