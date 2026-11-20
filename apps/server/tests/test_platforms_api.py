"""平台域端点契约：名册投影 / 改名 / 同步平台 / 导入 / 批量（ADR-021 / ADR-031 / R2）。

从 test_api.py 拆出（门禁单文件 600 行硬上限）：本文件只覆盖 /api/v1/platforms
（含 import-all）与 /api/v1/runs/claim-all；账户、执行、用量、体检留在 test_api.py。
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi.testclient import TestClient

from butler_core.execution.domain import ActionKind, RunResult
from butler_core.execution.ports import routing_ports
from butler_core.shared.results import Status


def _client(tmp_path: Path) -> TestClient:
    """独立 app 实例（各自 tmp_path 库）；与 test_api.py 的同名夹具各持一份、互不干扰。"""
    os.environ["BUTLER_DB"] = str(tmp_path / "butler.db")
    os.environ["BUTLER_SCHEDULE"] = "0"  # 关调度：用量 job 启动补扫会与假件端口竞态
    os.environ["BUTLER_SYSTEM_NOTIFY"] = "0"  # 测试不真弹系统通知（ADR-015）
    from server.main import app

    return TestClient(app)


class _FakePort:
    """精确执行端口假件（claim-all 用）：固定回同一 RunResult。"""

    def __init__(self, result: RunResult):
        self._result = result

    def capabilities(self):
        from butler_core.execution.ports import Capabilities

        return Capabilities(dry_run=True)

    def run(self, req):
        return self._result


class _UsagePort:
    """用量端口假件：按队列逐次吐 UsageResult（dock 顺带采集用）。"""

    def __init__(self, results):
        self._results = list(results)
        self.calls = []

    def collect(self, req):
        self.calls.append(req)
        return self._results.pop(0)


class _BoomUsagePort:
    """collect 即炸的假件：CollectUsage 应收进 outcome.error 而非打断编排。"""

    def collect(self, req):
        raise RuntimeError("本机客户端不在")


def _usage_result(remaining: float, *, total: float = 3200, collected_at=None):
    from datetime import datetime, timezone

    from butler_core.shared.ids import new_id
    from butler_core.usage.domain import (
        PackageQuota,
        UsageAggregate,
        UsageResult,
        UsageSnapshot,
    )

    now = collected_at or datetime.now(timezone.utc)
    pkg = PackageQuota(
        package_id="add_on_quota",
        name="加量包",
        total=total,
        used=total - remaining,
        remaining=remaining,
        unit="credits",
    )
    return UsageResult(
        snapshot=UsageSnapshot(
            id=new_id(),
            account_id="trae_cn:main",
            target="trae_cn",
            collected_at=now,
            packages=(pkg,),
        ),
        aggregate=UsageAggregate(
            id=new_id(),
            account_id="trae_cn:main",
            target="trae_cn",
            collected_at=now,
            summary={"consumed_amount": total - remaining},
        ),
        ledger=None,
    )


class _StubRegistry:
    """dock 假件：绕开真连接器的本机扫描，按真 dock 语义注册号册并回报账号。"""

    def __init__(self, accounts):
        self._accounts = accounts

    def get(self, target):
        from types import SimpleNamespace

        # 测试替身保留 manifest.usage 语义：agentrouter 是纯签到连接器。
        return SimpleNamespace(
            manifest=SimpleNamespace(id=target, usage=target != "agentrouter")
        )

    def dock(self, ctx, *, target):
        from butler_connectors.registry import DockOutcome

        for acc in self._accounts:
            platform = acc.split(":")[0]
            ctx.register.execute(platform, platform)  # 真 dock 同款：身份落册
        return [DockOutcome(target=target, accounts=list(self._accounts))]


class _BatchRegistry:
    """批量 dock 假件：逐 target 注册 {target}:main（import-all 的编排面专用）。"""

    def __init__(self, targets, kinds=None):
        self._targets = list(targets)
        self._kinds = dict(kinds or {})

    def platforms(self):
        from types import SimpleNamespace

        return [
            SimpleNamespace(manifest=SimpleNamespace(id=t, kind=self._kinds.get(t, "")))
            for t in self._targets
        ]

    def dock(self, ctx, *, target):
        from butler_connectors.registry import DockOutcome

        ctx.register.execute(target, target)
        return [DockOutcome(target=target, accounts=[f"{target}:main"])]


def _sync_registry(client):
    """stub registry 后按组合根同步语义重建名册（server main 装配同款投影）。"""
    from butler_core.platforms.domain import PlatformEntry
    from butler_core.shared.time import now_utc

    kit = client.app.state.kit
    facts = []
    for conn in client.app.state.registry.platforms():
        m = conn.manifest
        facts.append(
            PlatformEntry(
                platform_code=m.id,
                platform_name=getattr(m, "display", m.id),
                created_at=now_utc(),
                platform_kind=getattr(m, "kind", ""),
                capabilities=tuple(sorted(getattr(m, "capabilities", ()))),
                credential_kinds=(),
                schedule_times=(),
            )
        )
    kit.sync_platforms.execute(tuple(facts))


def test_apps_hidden_retired_web_connectors(tmp_path):
    """退役连接器不再出现在应用名册；存活网页版也不自动纳册（2026-11-19 裁决：
    同步只纳本机客户端，网页版走「未导入的平台」人工导入）。"""
    with _client(tmp_path) as client:
        ids = [row["id"] for row in client.get("/api/v1/platforms").json()]
        assert "chatgpt_web" not in ids
        assert "claude_web" not in ids  # 退役：连未导入清单也不进
        assert "agentrouter" not in ids  # 存活网页版：只在未导入清单里


def test_remove_platform_移出名册后回到未导入(tmp_path):
    """移出名册（2026-11-19）：删平台事实行 → 名册消失、未导入清单回来；
    再删同一条 = 404；账户表不受影响。"""
    with _client(tmp_path) as client:
        assert client.delete("/api/v1/platforms/trae_cn").status_code == 200
        ids = [row["id"] for row in client.get("/api/v1/platforms").json()]
        assert "trae_cn" not in ids
        assert "trae_cn" in {
            c["platform_code"] for c in client.get("/api/v1/platforms/unimported").json()
        }
        assert client.delete("/api/v1/platforms/trae_cn").status_code == 404


def test_unimported_lists_web_connectors_for_manual_import(tmp_path):
    """未导入清单（2026-11-19）：客户端自动纳册后不在清单；存活网页版在清单。"""
    with _client(tmp_path) as client:
        cands = client.get("/api/v1/platforms/unimported").json()
        codes = [c["platform_code"] for c in cands]
        assert codes == ["agentrouter"]
        assert cands[0]["kind"] == "web"
        assert "doubao_cn" not in codes  # 客户端已自动纳册
        assert client.post("/api/v1/platforms/nope/adopt").status_code == 422


def test_patch_platform_name_生效且同步不覆盖(tmp_path):
    """ADR-031：平台名可改，改后同步不覆盖；空串 = 恢复连接器申报名；编码不可改。"""
    with _client(tmp_path) as client:
        row = next(r for r in client.get("/api/v1/platforms").json() if r["id"] == "trae_cn")
        assert row["platform_name"] == "Trae CN"
        assert row["name_is_default"] is True

        patched = client.patch(
            "/api/v1/platforms/trae_cn", json={"platform_name": "Trae 主号"}
        ).json()
        assert patched["platform_name"] == "Trae 主号"
        assert patched["name_is_default"] is False
        assert patched["id"] == "trae_cn"  # 编码是锚点，改名不动它

        _sync_registry(client)  # 模拟下一轮启动时的 manifest 同步
        again = next(r for r in client.get("/api/v1/platforms").json() if r["id"] == "trae_cn")
        assert again["platform_name"] == "Trae 主号"  # 用户的名字没被冲掉

        reset = client.patch("/api/v1/platforms/trae_cn", json={"platform_name": ""}).json()
        assert reset["platform_name"] == "Trae CN"  # 空串 = 恢复连接器申报名
        assert reset["name_is_default"] is True


def test_patch_platform_icon_写入与校验(tmp_path):
    """平台图标（2026-11-19）：png data URI 可写、随列表返回；非 png / 超长 400；空串清空。"""
    with _client(tmp_path) as client:
        # 先显式清空：本机装了对应客户端时启动探测会写图标，不能假设库里一定为空
        cleared_first = client.patch("/api/v1/platforms/trae_cn", json={"icon": ""}).json()
        assert cleared_first["icon"] == ""

        uri = "data:image/png;base64,AAAA"
        patched = client.patch("/api/v1/platforms/trae_cn", json={"icon": uri}).json()
        assert patched["icon"] == uri

        listed = next(r for r in client.get("/api/v1/platforms").json() if r["id"] == "trae_cn")
        assert listed["icon"] == uri  # 图标跟着平台数据走：列表即可拿到

        # 只认 png data URI（前端上传前已转码），其他形态显式 400
        assert (
            client.patch("/api/v1/platforms/trae_cn", json={"icon": "https://x/y.png"}).status_code
            == 400
        )
        oversized = "data:image/png;base64," + "A" * 200_001
        assert (
            client.patch("/api/v1/platforms/trae_cn", json={"icon": oversized}).status_code == 400
        )

        cleared = client.patch("/api/v1/platforms/trae_cn", json={"icon": ""}).json()
        assert cleared["icon"] == ""  # 空串 = 清空（回落内置图标）


def test_resync_platforms_从空名册回填(tmp_path):
    """「同步平台」运行期回填（ADR-031）：平台表被清空后不重启后端也能刷回名册。

    同时钉住两条边界：①「接入」不建名册（表空时 import-all 候选为 0）；
    ②回填走首插语义，已改过的平台名不被覆盖。
    """
    import sqlite3

    with _client(tmp_path) as client:
        db = tmp_path / "butler.db"
        conn = sqlite3.connect(db)
        conn.execute("DELETE FROM plat_platform")
        conn.commit()
        conn.close()

        assert client.get("/api/v1/platforms").json() == []  # 名册真的空了
        assert client.post("/api/v1/platforms/import-all").json() == []  # 接入不建名册

        rows = client.post("/api/v1/platforms/resync").json()
        ids = sorted(r["id"] for r in rows)
        assert "doubao_cn" in ids and "trae_cn" in ids
        assert "agentrouter" not in ids  # 网页版不随同步自动纳册
        assert all(r["name_is_default"] for r in rows)  # 首插落的是连接器申报名

        client.patch("/api/v1/platforms/trae_cn", json={"platform_name": "Trae 主号"})
        again = {r["id"]: r for r in client.post("/api/v1/platforms/resync").json()}
        assert again["trae_cn"]["platform_name"] == "Trae 主号"  # 名字归用户，回填不覆盖


def test_import_skips_usage_error_for_checkin_only_connector(tmp_path):
    """纯签到连接器没有 usage 端口：import 不把“无额度可采”报成 issue。"""
    with _client(tmp_path) as client:
        kit = client.app.state.kit
        client.app.state.registry = _StubRegistry(["agentrouter:main"])
        kit.collect_usage.ports = {}

        out = client.post("/api/v1/platforms/agentrouter/import").json()
        assert out["accounts"] == ["agentrouter:main"]
        assert out["issues"] == []


def test_import_triggers_usage_collect_and_reports_errors(tmp_path):
    """R2-F dock 顺带采集：导入成功即产第一帧；采集失败如实进 issues，不打断导入。"""
    with _client(tmp_path) as client:
        kit = client.app.state.kit
        client.app.state.registry = _StubRegistry(["trae_cn:main"])
        kit.collect_usage.ports = {"trae_cn": _UsagePort([_usage_result(2000)])}

        out = client.post("/api/v1/platforms/trae_cn/import").json()
        assert out["accounts"] == ["trae_cn:main"]
        assert out["issues"] == []  # 采集成功：issues 无噪音

        radar = client.get("/api/v1/usage/radar").json()
        assert radar[0]["packages"][0]["remaining"] == 2000.0  # 第一帧已入库

        # 采集失败 → issues 如实上报（红线 5），导入本身不受累
        kit.collect_usage.ports = {"trae_cn": _BoomUsagePort()}
        out2 = client.post("/api/v1/platforms/trae_cn/import").json()
        assert out2["accounts"] == ["trae_cn:main"]
        assert any("用量采集" in i and "本机客户端不在" in i for i in out2["issues"])


# --- 一键批量（import-all / claim-all）：编排语义在 server，端零入参 ---


def test_import_all_skips_docked_and_reports_collect_errors(tmp_path):
    """一键导入：只导未导入的；顺带采集失败如实进 issues，不拖累别家。"""
    with _client(tmp_path) as client:
        kit = client.app.state.kit
        client.app.state.registry = _BatchRegistry(["trae_cn", "qoder_cn", "doubao_cn"])
        _sync_registry(client)  # 名册随 stub 重建（ADR-021/022：DB 为真相源）
        kit.register_account.execute("trae_cn", "Trae CN")  # 已导入 → 跳过
        kit.collect_usage.ports = {}  # 显式接管端口面：全部采集失败 → issues

        rows = client.post("/api/v1/platforms/import-all").json()
        assert [r["target"] for r in rows] == ["doubao_cn", "qoder_cn"]  # 名册序：platform_code 排序
        for row in rows:
            assert row["accounts"] == [f"{row['target']}:main"]
            assert any("用量采集" in i for i in row["issues"])


def test_import_all_skips_web_even_when_roster_has_it(tmp_path):
    """扫描本机只自动接客户端（2026-11-19 用户裁决）：名册里的网页版不自动 dock。"""
    with _client(tmp_path) as client:
        client.app.state.registry = _BatchRegistry(
            ["agentrouter", "trae_cn"], {"agentrouter": "web", "trae_cn": "client"}
        )
        _sync_registry(client)

        rows = client.post("/api/v1/platforms/import-all").json()
        assert [r["target"] for r in rows] == ["trae_cn"]


def test_import_all_empty_when_nothing_to_dock(tmp_path):
    with _client(tmp_path) as client:
        client.app.state.registry = _BatchRegistry([])
        _sync_registry(client)  # 空 facts → 全部落 deprecated，名册为空
        assert client.post("/api/v1/platforms/import-all").json() == []


def test_import_all_include_docked_rescans_all_client_platforms(tmp_path):
    """扫描本机（2026-11-20 修复）：include_docked=true 时已有账户的平台也重扫。

    修复前「平台已有账户就整块跳过」：多账号客户端（豆包双账号）漏接的第二个账号
    永远补不进来，前端还会误报「本机客户端账户均已接入」——那句话在有漏接账号时是假话。
    全量重扫靠 (platform, account_code) 幂等回放：只补新增账号、不重复建号、不动既有账户。
    """
    with _client(tmp_path) as client:
        kit = client.app.state.kit
        client.app.state.registry = _BatchRegistry(["trae_cn", "qoder_cn"])
        _sync_registry(client)
        kit.register_account.execute("trae_cn", "Trae CN")  # 已导入 → 默认批量跳过
        kit.collect_usage.ports = {}  # 采集端口全失败 → issues，不影响账户落册

        default_rows = client.post("/api/v1/platforms/import-all").json()
        assert [r["target"] for r in default_rows] == ["qoder_cn"]  # 「接入全部」只补零账户平台

        scanned = client.post("/api/v1/platforms/import-all?include_docked=true").json()
        assert [r["target"] for r in scanned] == ["qoder_cn", "trae_cn"]  # 「扫描本机」全量重扫
        # 幂等回放：已导入的 trae_cn 仍是 1 行账户，不重复建号
        assert len([a for a in kit.accounts.list_all() if a.platform_code == "trae_cn"]) == 1


def test_claim_all_claims_docked_and_replays(tmp_path):
    """一键领取：逐已导入账户发起；同窗口再点 → 幂等回放同 Run（不重复领取）。"""
    with _client(tmp_path) as client:
        kit = client.app.state.kit
        kit.execute_action.ports = routing_ports(
            {ActionKind.PROVISION_RUN: _FakePort(RunResult(status=Status.CLAIMED))}, {}
        )
        kit.register_account.execute("trae_cn", "Trae CN")
        kit.register_account.execute("doubao_cn", "Doubao CN")

        rows = client.post("/api/v1/runs/claim-all").json()
        assert {r["account_id"] for r in rows} == {"trae_cn:main", "doubao_cn:main"}
        assert all(r["status"] == "CLAIMED" for r in rows)

        again = client.post("/api/v1/runs/claim-all").json()
        assert {r["id"] for r in again} == {r["id"] for r in rows}


def test_claim_all_empty_when_no_accounts(tmp_path):
    with _client(tmp_path) as client:
        assert client.post("/api/v1/runs/claim-all").json() == []


# --- 接入源（ADR-033）---


_PROVIDER = {
    "platform_code": "my_relay",
    "platform_name": "我的中转",
    "kind": "relay",
    "base_url": "https://relay.example.com/v1",
    "protocol": "openai",
    "models": ["gpt-4o-mini"],
    "credential_kinds": ["api_key"],
}


def test_create_provider_落名册且不参与退役同步(tmp_path):
    with _client(tmp_path) as client:
        resp = client.post("/api/v1/platforms/providers", json=_PROVIDER)
        assert resp.status_code == 200, resp.text
        row = resp.json()
        assert row["origin"] == "user"
        assert row["name_is_default"] is False  # 用户接入源没有默认名
        assert row["account_ids"] == []
        assert {p["id"] for p in client.get("/api/v1/platforms").json()} >= {"my_relay"}

        # 重复编码 = 409（编码是锚点，不覆盖）
        assert client.post("/api/v1/platforms/providers", json=_PROVIDER).status_code == 409


def test_create_provider_形状校验(tmp_path):
    with _client(tmp_path) as client:
        bad_code = {**_PROVIDER, "platform_code": "Bad:Code"}
        assert client.post("/api/v1/platforms/providers", json=bad_code).status_code == 400
        bad_protocol = {**_PROVIDER, "protocol": "openai-compatible"}
        assert client.post("/api/v1/platforms/providers", json=bad_protocol).status_code == 400
        no_url = {**_PROVIDER, "base_url": ""}
        assert client.post("/api/v1/platforms/providers", json=no_url).status_code == 400
        bad_kind = {**_PROVIDER, "kind": "app"}
        assert client.post("/api/v1/platforms/providers", json=bad_kind).status_code == 400


def test_patch_provider_只改连接事实_用户源可改(tmp_path):
    with _client(tmp_path) as client:
        client.post("/api/v1/platforms/providers", json=_PROVIDER)
        out = client.patch(
            "/api/v1/platforms/my_relay",
            json={"base_url": "https://relay2.example.com/v1",
                  "models": ["gpt-4o-mini", "gpt-4o"]},
        )
        assert out.status_code == 200, out.text
        row = out.json()
        assert row["base_url"] == "https://relay2.example.com/v1"
        assert row["protocol"] == "openai"
        assert row["models"] == ["gpt-4o-mini", "gpt-4o"]
        # 海外协议已下线：PATCH 显式拒绝
        bad = client.patch("/api/v1/platforms/my_relay", json={"protocol": "anthropic"})
        assert bad.status_code == 400
        # 用户接入源不能把名字清空（没有 manifest 默认名可回落）
        assert client.patch("/api/v1/platforms/my_relay", json={"platform_name": ""}).status_code == 400


def test_patch_connector_platform_拒绝改连接事实(tmp_path):
    with _client(tmp_path) as client:
        kit = client.app.state.kit
        from butler_core.platforms.domain import PlatformEntry
        from butler_core.shared.time import now_utc

        kit.platforms.upsert(
            PlatformEntry(
                platform_code="doubao_cn", platform_name="豆包", created_at=now_utc(),
                platform_kind="client", capabilities=("provision.run",),
                credential_kinds=("cookie",),
            )
        )
        resp = client.patch(
            "/api/v1/platforms/doubao_cn",
            json={"base_url": "https://evil.example.com"},
        )
        assert resp.status_code == 400
        assert "连接事实" in resp.json()["detail"]
