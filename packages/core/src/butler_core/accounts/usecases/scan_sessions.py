"""会话扫描入库用例（R5-S1，ADR-013 裁决 1/5）：只读枚举 + 账户绑定 + 幂等入库。

- 干净路径：SessionSourcePort.scan_sessions（适配器只读观测）→ device_ref
  解析账户（vault.load device_dn 匹配）→ 命中者组装 Session 追加进
  account.sessions（按 (location, kind, level) 去重，重复扫描幂等）→
  repo.save 整体回写
- 绑定不可得（device_ref=None 或无账户持有该 device_dn）= **如实分列
  unbound**，不入库不猜归属（会话必须挂 account_id，编造绑定 = 串账户）
- 侧效应失败（repo.save 异常）= 显式上抛不吞（扫描入库是主流程，不是台账
  可以让的侧效应）；适配器读不了的 sighting 适配器侧已如实跳过
- vault.load 缺 device_dn = 该账户未停靠/老停靠数据——如实跳过绑定，
  不是错误（扫描可重复跑，停靠补 device_dn 后下次扫描自然绑定）
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from butler_core.accounts.domain import Account, Session, SessionSighting
from butler_core.accounts.ports import AccountRepository, CredentialMissing, SessionSourcePort, VaultPort


@dataclass(frozen=True)
class ScanSessionsOutcome:
    """扫描结果如实分列：入库数/涉及账户/未绑定观测（原文回传，端零映射）。"""

    scanned: int
    added: int
    accounts: tuple[str, ...]
    unbound: tuple[SessionSighting, ...]


@dataclass
class ScanSessions:
    """会话扫描入库：枚举（端口）→ 绑定（vault device_dn）→ 幂等入库（repo）。"""

    source: SessionSourcePort
    accounts: AccountRepository
    vault: VaultPort

    def scan(self, app: str) -> ScanSessionsOutcome:
        sightings = list(self.source.scan_sessions(app))
        device_owner = self._device_owner_map(app)
        added = 0
        touched: dict[str, Account] = {}
        unbound: list[SessionSighting] = []
        for sighting in sightings:
            account = (
                device_owner.get(sighting.device_ref) if sighting.device_ref else None
            )
            if account is None:
                unbound.append(sighting)
                continue
            session = Session(
                account_id=account.id,
                location=sighting.location,
                kind=sighting.kind,
                level=sighting.level,
            )
            if any(
                s.location == session.location
                and s.kind == session.kind
                and s.level == session.level
                for s in account.sessions
            ):
                continue  # 幂等：重复扫描不重复入库
            updated = replace(account, sessions=(*account.sessions, session))
            self.accounts.save(updated)
            touched[account.id] = updated
            added += 1
        return ScanSessionsOutcome(
            scanned=len(sightings),
            added=added,
            accounts=tuple(sorted(touched)),
            unbound=tuple(unbound),
        )

    def _device_owner_map(self, app: str) -> dict[str, Account]:
        """app 账户 → device_dn 映射（一次 vault.load/账户；缺 = 如实跳过）。"""
        owners: dict[str, Account] = {}
        for account in self.accounts.list_by_app(app):
            try:
                secrets = self.vault.load(account.id, ["device_dn"])
            except CredentialMissing:
                continue
            if secrets and secrets[0].expose().strip():
                owners[secrets[0].expose().strip()] = account
        return owners
