"""唯一出桥（ADR-001 / 规约 R4）：端只准 `from kabao_engine.bridge import ...`。

装配：SQLite(WAL) → 台账 / 审计 / 号册适配器 → 事件总线 → 订阅（审计落账 /
通知中心）→ Vault（秘密后端按平台选默认层）→ 健康扫描用例 → 到期/停靠/用量定时 job。
端拿 EngineKit 用，不许 import 引擎内部模块。

连接器接入（ADR-003）：端把连接器注册表产出的 target→端口映射交给
`register_provision_ports()`，用例层按 action.target 路由；engine 不 import
连接器包（依赖方向恒指 core）。
"""

from __future__ import annotations

import logging
import os
import shutil
import sys
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Mapping

from kabao_core.application.ports import ProvisionPort, UsagePort
from kabao_core.application.usecases import (
    AssessAccountHealth,
    CollectUsage,
    ExecuteAction,
    ListPending,
    RegisterAccount,
    RunRequest,
    ScanCredentialExpiry,
)
from kabao_core.bootstrap import execute_action as _assemble_execute_action
from kabao_core.bootstrap import list_pending as _assemble_list_pending
from kabao_core.bootstrap import register_account as _assemble_register_account
from kabao_core.domain.action import Action, ActionKind

from kabao_engine.accounts.sqlite import SqliteAccountRepository
from kabao_engine.audit.sqlite import AuditSubscriber, SqliteAuditLog
from kabao_engine.events.bus import EventBus
from kabao_engine.health.state import SqliteHealthStateStore
from kabao_engine.ledger.sqlite import SqliteRunLedger
from kabao_engine.notify.center import InAppChannel, NotificationCenter
from kabao_engine.scheduling.checkin import CheckinSchedule, ScheduleEntry
from kabao_engine.scheduling.interval_job import IntervalJob
from kabao_engine.usage.sqlite import SqliteUsageStore
from kabao_engine.vault.backends import MemoryVaultBackend, SecretBackend
from kabao_engine.vault.keychain_macos import KeychainBackend
from kabao_engine.vault.layered import LayeredVault

DEFAULT_DB = "kabao.db"


def default_db_path() -> Path:
    """平台标准用户数据根下的 kabao.db（A4-01 §5 数据布局）。

    macOS ~/Library/Application Support/kabao · Windows %APPDATA%/kabao ·
    Linux $XDG_DATA_HOME/kabao。**绝不落 CWD**；KABAO_DB 环境变量仍可整体覆盖
    （测试/便携模式，显式指定时不做任何迁移）。
    首次调用时把旧身份数据一次性搬入（A1-03 §8）：
    ① 旧品牌目录 ai-marina/marina.db（R1 更名前的数据根）；
    ② M0 遗留在 CWD 的 marina.db。
    旧目录与搬剩文件保留不删（天然备份）；迁移幂等（kabao.db 已存在即跳过）。
    """
    if sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support" / "kabao"
    elif sys.platform.startswith("win"):
        appdata = os.environ.get("APPDATA") or str(
            Path.home() / "AppData" / "Roaming"
        )
        root = Path(appdata) / "kabao"
    else:
        xdg = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
        root = Path(xdg) / "kabao"
    root.mkdir(parents=True, exist_ok=True)
    target = root / "kabao.db"
    if not target.exists():
        brand_legacy = root.parent / "ai-marina" / "marina.db"
        cwd_legacy = Path.cwd() / "marina.db"
        for legacy in (brand_legacy, cwd_legacy):
            if legacy.exists():
                for suffix in ("", "-wal", "-shm"):
                    src = Path(str(legacy) + suffix)
                    if src.exists():
                        shutil.move(str(src), str(target) + suffix)
                logger.info("已迁移历史数据库 %s → %s", legacy, target)
                break
    return target


DAILY_SCAN_INTERVAL = timedelta(days=1)  # A4-01 §1：每日 job 比对有效期
SCAN_JOB_NAME = "kabao-expiry-scan"
CHECKIN_TICK = timedelta(seconds=60)  # 导入触发 tick（实测粒度）——秒级不省预算
CHECKIN_JOB_NAME = "kabao-checkin"
USAGE_JOB_NAME = "kabao-usage-scan"  # R2：每日用量采集（雷达第二帧的定时来源）
HEALTH_JOB_NAME = "kabao-health-scan"  # R3-2：每日体检轮询（A2-03 §3 定时批次）

logger = logging.getLogger(__name__)


@dataclass
class EngineKit:
    """端侧拿到的全部引擎能力（组合根产物）。用完 close()。"""

    bus: EventBus
    ledger: SqliteRunLedger
    audit: SqliteAuditLog
    notify: InAppChannel
    accounts: SqliteAccountRepository
    execute_action: ExecuteAction
    register_account: RegisterAccount
    list_pending: ListPending
    vault: LayeredVault
    scan_credential_expiry: ScanCredentialExpiry
    assess_account_health: AssessAccountHealth
    usage_store: SqliteUsageStore
    collect_usage: CollectUsage
    scan_job: IntervalJob | None = None
    checkin_schedule: CheckinSchedule | None = None
    checkin_job: IntervalJob | None = None
    usage_job: IntervalJob | None = None
    health_job: IntervalJob | None = None
    _kind_ports: dict = field(default_factory=dict, init=False, repr=False)
    _target_ports: dict = field(default_factory=dict, init=False, repr=False)
    _usage_ports: dict = field(default_factory=dict, init=False, repr=False)
    _health_ports: dict = field(default_factory=dict, init=False, repr=False)

    def register_provision_ports(
        self,
        targets: Mapping[str, ProvisionPort] | None = None,
        kinds: Mapping[str, ProvisionPort] | None = None,
        *,
        replace: bool = False,
    ) -> None:
        """挂载连接器端口（ADR-003）：target 精确路由优先，kind 兜底。

        重复挂载同名 target = 注册表装配 bug，显式拒绝（红线 5）；
        显式 replace=True = 重装配（测试/热替换），替换而非静默叠加。
        """
        for tid, port in (targets or {}).items():
            if tid in self._target_ports and self._target_ports[tid] is not port:
                if not replace:
                    raise ValueError(f"连接器端口重复挂载: {tid!r}（显式 replace=True 才可重装）")
            self._target_ports[tid] = port
        self._kind_ports.update(kinds or {})
        self.execute_action.ports = self._selector()

    def register_usage_ports(
        self,
        targets: Mapping[str, UsagePort] | None = None,
        *,
        replace: bool = False,
    ) -> None:
        """挂载用量采集端口（R2）：target 精确路由（同 ADR-003 纪律）。

        重复挂载同名 target = 注册表装配 bug，显式拒绝；replace=True 供重装配。
        """
        for tid, port in (targets or {}).items():
            if tid in self._usage_ports and self._usage_ports[tid] is not port:
                if not replace:
                    raise ValueError(f"用量端口重复挂载: {tid!r}（显式 replace=True 才可重装）")
            self._usage_ports[tid] = port
        self.collect_usage.ports = dict(self._usage_ports)

    def register_health_ports(
        self,
        targets: Mapping[str, ProvisionPort] | None = None,
        *,
        replace: bool = False,
    ) -> None:
        """挂载探针端口（R3 health.check 通道，A2-03 §4）：随 register_provision_ports
        同一条 target 路由进 ExecuteAction（routing_ports 不变），另记探针名册供每日
        体检 job 选路——「有端口」与「该每日轮询」是同一份事实。

        重复挂载同名 target（含与 provision 端口撞车）= 装配 bug，显式拒绝（红线 5）。
        """
        for tid, port in (targets or {}).items():
            if tid in self._health_ports and self._health_ports[tid] is not port:
                if not replace:
                    raise ValueError(f"探针端口重复挂载: {tid!r}（显式 replace=True 才可重装）")
            if tid in self._target_ports and self._target_ports[tid] is not port:
                if not replace:
                    raise ValueError(
                        f"探针端口与连接器端口撞车: {tid!r}（一 target 一端口，红线 5）"
                    )
            self._health_ports[tid] = port
            self._target_ports[tid] = port
        self.execute_action.ports = self._selector()

    def attach_schedule(
        self, entries: list[ScheduleEntry], *, tick: timedelta = CHECKIN_TICK
    ) -> CheckinSchedule:
        """装配停靠触发器（不启动）。时间表来自连接器 manifest（A2-02 §2）。"""
        self.checkin_schedule = CheckinSchedule(
            execute_action=self.execute_action,
            accounts=self.accounts,
            entries=tuple(entries),
        )
        return self.checkin_schedule

    def start_checkin_schedule(
        self,
        entries: list[ScheduleEntry],
        *,
        tick: timedelta = CHECKIN_TICK,
        run_now: bool = True,
    ) -> None:
        """启动停靠调度（幂等）。不启动显式跳过。"""
        schedule = self.attach_schedule(entries, tick=tick)
        if self.checkin_job is None:
            self.checkin_job = IntervalJob(
                schedule.tick, interval=tick, name=CHECKIN_JOB_NAME
            )
        if not self.checkin_job.running:
            self.checkin_job.start()
        if run_now:
            schedule.tick()  # 启动补触发（与到期扫描 start 补扫同语义）

    # --- 停止路径 ---

    def _selector(self):
        from kabao_core.application.ports import routing_ports

        return routing_ports(self._kind_ports, self._target_ports)

    def start_expiry_scans(self, *, interval: timedelta = DAILY_SCAN_INTERVAL) -> None:
        """启动每日到期扫描（A4-01 §1 到期监控 job）。幂等。"""
        if self.scan_job is None:
            self.scan_job = IntervalJob(
                self._daily_scan, interval=interval, name=SCAN_JOB_NAME
            )
        if not self.scan_job.running:
            self.scan_job.start()

    def _daily_scan(self) -> None:
        """先扫凭据到期，再对名册全部账号重评健康（顺序即依赖方向）。"""
        self.scan_credential_expiry.execute()
        accounts = {hp.account_id for hp in self.vault.health()}
        for account in self.accounts.list_all():
            accounts.add(account.id)
        for account_id in accounts:
            self.assess_account_health.execute(account_id)

    def start_usage_scans(self, *, interval: timedelta = DAILY_SCAN_INTERVAL) -> None:
        """启动每日用量采集（R2：dock 顺带之外的第二条采集链，雷达两帧差的定时来源）。幂等。"""
        if self.usage_job is None:
            self.usage_job = IntervalJob(
                self._daily_usage, interval=interval, name=USAGE_JOB_NAME
            )
        if not self.usage_job.running:
            self.usage_job.start()

    def _daily_usage(self) -> None:
        """号册全账号采集一轮；无 provider 或装配里没有该目标用量端口的跳过
        （R3 网页连接器无采集通道——job 不为它们天天报错）。

        单账号失败收进 outcome.error（编排不中断）；job 语境无人消费 outcome，
        落 WARNING 日志留痕——不静默（红线 5）。
        """
        for account in self.accounts.list_all():
            if not account.provider or account.provider not in self._usage_ports:
                continue
            outcome = self.collect_usage.execute(account.provider, account.id)
            if outcome.error:
                logger.warning("每日用量采集失败 %s: %s", account.id, outcome.error)

    def start_health_scans(self, *, interval: timedelta = DAILY_SCAN_INTERVAL) -> None:
        """启动每日体检轮询（R3-2，A2-03 §3 定时批次）：启动即补扫一轮（IntervalJob 语义）。幂等。"""
        if self.health_job is None:
            self.health_job = IntervalJob(
                self._daily_health, interval=interval, name=HEALTH_JOB_NAME
            )
        if not self.health_job.running:
            self.health_job.start()

    def _daily_health(self) -> None:
        """号册全账号体检一轮；无 provider 或未挂探针端口的跳过（轮询名册 = 探针名册）。

        Run 照常落台账——EXPIRED/NO_AUTH 修复建议随 Run 出账，连败升级走
        AssessAccountHealth 既有链（体检是这个反馈回路的输入）。外层预算走
        RunRequest 默认（bridge 够不到连接器 manifest 的能力申报，手动发起
        路径才由端按 budget_seconds 传）；探针端口内部按 deadline 收口。
        单账号异常落 WARNING 不打断整轮（ExecuteAction 对适配器意外异常
        落账后原样上抛，这里兜住）——不静默（红线 5）。
        """
        for account in self.accounts.list_all():
            if not account.provider or account.provider not in self._health_ports:
                continue
            try:
                self.execute_action.execute(
                    RunRequest(
                        action=Action(
                            kind=ActionKind.HEALTH_CHECK, target=account.provider
                        ),
                        account_id=account.id,
                    )
                )
            except Exception as e:  # noqa: BLE001 —— job 编排不被单账号打断
                logger.warning("每日体检失败 %s: %s", account.id, e)

    def close(self) -> None:
        """排空事件、停定时 job 后关总线——关闭路径不丢账。"""
        for job_name in ("checkin_job", "scan_job", "usage_job", "health_job"):
            job: IntervalJob | None = getattr(self, job_name)
            if job is not None:
                job.stop()
                setattr(self, job_name, None)
        self.bus.close()


def _secret_backends() -> tuple[dict[str, SecretBackend], str]:
    """平台 → 秘密后端装配。默认层：macOS=keychain，Windows=credman，其余=memory。

    非 mac/win 平台显式降级为 memory（进程退出即消失）并大声日志告警——
    桌面目标平台只有 macOS/Windows（A1-02），这里绝不静默（红线 5）。
    """
    backends: dict[str, SecretBackend] = {"memory": MemoryVaultBackend()}
    if sys.platform == "darwin":
        backends["keychain"] = KeychainBackend()
        return backends, "keychain"
    if sys.platform.startswith("win"):
        from kabao_engine.vault.credman_windows import WindowsCredmanBackend

        backends["credman"] = WindowsCredmanBackend()
        return backends, "credman"
    logger.warning(
        "当前平台 %s 不支持持久凭据层，Vault 将只用 memory 层（数据不落盘）", sys.platform
    )
    return backends, "memory"


def build_engine(db_path: str | Path = DEFAULT_DB) -> EngineKit:
    """组装根：把适配器接到端口，构造用例（A1-02 §1：start 层职责）。

    provision 类端口由端按 ADR-003 注册（连接器注册表 → register_provision_ports）；
    未接入动作显式拒绝（UnsupportedAction）。每日扫描 job 默认不启动，由端
    （server/desktop 组合层）显式 start_expiry_scans()。
    """
    bus = EventBus()
    ledger = SqliteRunLedger(db_path)
    audit = SqliteAuditLog(db_path)
    in_app = InAppChannel()
    notification_center = NotificationCenter(channels=[in_app])

    bus.subscribe(AuditSubscriber(audit).on_event)     # 写操作审计（A4-01 §4）
    bus.subscribe(notification_center.on_event)        # 通知中心 = 事件唯一通知出口（§3）

    backends, default_backend = _secret_backends()
    vault = LayeredVault(
        db_path, backends, default_backend=default_backend, audit=audit
    )
    health_state = SqliteHealthStateStore(db_path)
    accounts = SqliteAccountRepository(db_path)

    expiry = ScanCredentialExpiry(vault=vault, sink=bus, states=health_state)
    assess = AssessAccountHealth(
        vault=vault, ledger=ledger, sink=bus, states=health_state
    )

    usage_store = SqliteUsageStore(db_path)
    collect_usage = CollectUsage(ports={}, store=usage_store, sink=bus)

    return EngineKit(
        bus=bus,
        ledger=ledger,
        audit=audit,
        notify=in_app,
        accounts=accounts,
        execute_action=_assemble_execute_action(ledger=ledger, sink=bus),
        register_account=_assemble_register_account(accounts),
        list_pending=_assemble_list_pending(ledger=ledger),
        vault=vault,
        scan_credential_expiry=expiry,
        assess_account_health=assess,
        usage_store=usage_store,
        collect_usage=collect_usage,
    )
