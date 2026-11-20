"""平台域适配器（A2-09，ADR-021/022）：连接器平台事实落库，DB 为真相源。

组合根（server 装配层）启动时从连接器 manifest 抽纯数据 facts → SyncPlatforms
用例 → 本适配器 UPSERT + 缺失平台落 deprecated。web `/platforms` 名册读本表
+ 台账并账，不再每次装配穿连接器包拼装（端零映射）。

表名带域前缀（ADR-021 全库表名纪律）：plat_platform。

表结构真相源 = `butler_engine/db/migrations/`（ADR-036）：本模块零 DDL，
构造经 `open_db` 迁移链保证 schema 最新；改表 = 新增编号迁移文件。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from butler_core.platforms.ports import PlatformRepository
from butler_core.platforms.domain import PlatformEntry

from butler_engine.db.conn import connect
from butler_engine.db.migrations import open_db

#: 列清单（与 001_initial.sql 列序一致；upsert/get 按 this 顺序读写，id 不在内）
_COLS = (
    "platform_code, platform_name, platform_kind, client_version, icon, "
    "capabilities, credential_kinds, schedule_times, schedule_override, "
    "base_url, protocol, models_json, origin, "
    "is_active, deprecated_at, created_at, updated_at"
)


def _dump(values: tuple[str, ...]) -> str:
    import json

    return json.dumps(list(values), ensure_ascii=False)


def _load_values(raw: str) -> tuple[str, ...]:
    import json

    try:
        return tuple(json.loads(raw or "[]"))
    except ValueError:
        return ()  # 坏行如实空，不炸名册（红线 5：不静默造数据）


def _load_override(raw: str | None) -> tuple[str, ...] | None:
    """'' = 跟随 manifest（None）；JSON 数组 = 用户覆盖（含空数组=不排班）。"""
    if not raw:
        return None
    return _load_values(raw)


class SqlitePlatformRepository(PlatformRepository):
    def __init__(self, db_path: str | Path) -> None:
        self._db = str(db_path)
        open_db(self._db)  # 构造即 schema 最新（迁移链保证，ADR-036）

    def _connect(self):
        return connect(self._db)  # 迁移已在 __init__ 完成，操作期直连

    def upsert(self, entry: PlatformEntry) -> None:
        """接入/启动同步落库：INSERT 时写 platform_name，UPDATE 时**不写**（ADR-031）。

        名称一旦落库即归用户：连接器改名不再覆盖用户已经看过、可能已经改过的名字。
        icon 相反：探测到新图标就刷新（客户端升级换图要跟得上），探测为空则保留原值——
        这样用户给自定义平台上传的图标不会被一次"探不到"抹掉。
        """
        from butler_core.shared.time import now_utc

        created = entry.created_at.isoformat()
        with self._connect() as conn, conn:
            conn.execute(
                f"INSERT INTO plat_platform ({_COLS}) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT (platform_code) DO UPDATE SET "
                "platform_kind=excluded.platform_kind, "
                "client_version=excluded.client_version, "
                "icon=CASE WHEN excluded.icon <> '' THEN excluded.icon ELSE icon END, "
                "capabilities=excluded.capabilities, "
                "credential_kinds=excluded.credential_kinds, schedule_times=excluded.schedule_times, "
                "base_url=excluded.base_url, protocol=excluded.protocol, "
                "models_json=excluded.models_json, origin=excluded.origin, "
                "updated_at=excluded.updated_at",
                (
                    entry.platform_code,
                    entry.platform_name,
                    entry.platform_kind.strip(),
                    entry.client_version.strip(),
                    entry.icon,
                    _dump(entry.capabilities),
                    _dump(entry.credential_kinds),
                    _dump(entry.schedule_times),
                    _dump(entry.schedule_override) if entry.schedule_override is not None else "",
                    entry.base_url.strip(),
                    entry.protocol.strip(),
                    _dump(entry.models),
                    entry.origin,
                    1 if entry.is_active else 0,
                    entry.deprecated_at.isoformat() if entry.deprecated_at else None,
                    created,
                    now_utc().isoformat(),
                ),
            )

    def remove(self, platform_code: str) -> bool:
        """移出名册：只删平台事实行（账户/台账/凭据不动，见端口 docstring）。"""
        with self._connect() as conn, conn:
            cur = conn.execute(
                "DELETE FROM plat_platform WHERE platform_code = ?", (platform_code,)
            )
            return cur.rowcount > 0

    def deprecate_missing(self, platform_codes: frozenset[str]) -> list[str]:
        from butler_core.shared.time import now_utc

        now = now_utc().isoformat()
        with self._connect() as conn, conn:
            rows = conn.execute(
                "SELECT platform_code FROM plat_platform "
                "WHERE deprecated_at IS NULL AND origin = 'connector' AND platform_code NOT IN "
                f"({', '.join('?' * len(platform_codes)) or "''"})",
                tuple(platform_codes),
            ).fetchall()
            stale = [r[0] for r in rows]
            for code in stale:
                # 2026-11-18 修：落 deprecated 必须同时置 is_active=0。
                # 只写 deprecated_at 会留下「已退役但仍 active」的幽灵平台，
                # 名册照样列出、claim-all 遍历到它就会 KeyError（连接器已下线）。
                conn.execute(
                    "UPDATE plat_platform SET deprecated_at = ?, is_active = 0, updated_at = ? "
                    "WHERE platform_code = ?",
                    (now, now, code),
                )
        return stale

    def update_profile(
        self,
        platform_code: str,
        *,
        platform_name: str | None = None,
        is_active: bool | None = None,
        icon: str | None = None,
        base_url: str | None = None,
        protocol: str | None = None,
        models: tuple[str, ...] | None = None,
        credential_kinds: tuple[str, ...] | None = None,
    ) -> PlatformEntry | None:
        """改平台名 / 启停 / 图标 / 接入源连接事实（None = 不动）。不存在 → None。

        平台编码是锚点，本方法没有改写它的入口（ADR-031）；origin 也不可改。
        base_url/protocol/models（ADR-033）只应作用于用户接入源，调用方负责拒绝越权。
        """
        from butler_core.shared.time import now_utc

        sets: list[str] = []
        args: list[object] = []
        if platform_name is not None:
            sets.append("platform_name = ?")
            args.append(platform_name)
        if is_active is not None:
            sets.append("is_active = ?")
            args.append(1 if is_active else 0)
        if icon is not None:
            sets.append("icon = ?")
            args.append(icon)
        if base_url is not None:
            sets.append("base_url = ?")
            args.append(base_url)
        if protocol is not None:
            sets.append("protocol = ?")
            args.append(protocol)
        if models is not None:
            sets.append("models_json = ?")
            args.append(_dump(models))
        if credential_kinds is not None:
            sets.append("credential_kinds = ?")
            args.append(_dump(credential_kinds))
        if not sets:
            return self.get(platform_code)
        sets.append("updated_at = ?")
        args.extend([now_utc().isoformat(), platform_code])
        with self._connect() as conn, conn:
            cur = conn.execute(
                f"UPDATE plat_platform SET {', '.join(sets)} WHERE platform_code = ?", args
            )
            if cur.rowcount == 0:
                return None
            row = conn.execute(
                f"SELECT {_COLS} FROM plat_platform WHERE platform_code = ?",
                (platform_code,),
            ).fetchone()
        return _load(row)

    def set_schedule_override(
        self, platform_code: str, times: tuple[str, ...] | None
    ) -> PlatformEntry | None:
        """写调度覆盖（None = 恢复跟随 manifest）。平台不存在 → None（调用方显式 404）。"""
        from butler_core.shared.time import now_utc

        stored = _dump(times) if times is not None else ""
        with self._connect() as conn, conn:
            cur = conn.execute(
                "UPDATE plat_platform SET schedule_override = ?, updated_at = ? "
                "WHERE platform_code = ?",
                (stored, now_utc().isoformat(), platform_code),
            )
            if cur.rowcount == 0:
                return None
            row = conn.execute(
                f"SELECT {_COLS} FROM plat_platform WHERE platform_code = ?",
                (platform_code,),
            ).fetchone()
        return _load(row)

    def get(self, platform_code: str) -> PlatformEntry | None:
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT {_COLS} FROM plat_platform WHERE platform_code = ?",
                (platform_code,),
            ).fetchone()
        return _load(row)

    def list_all(self) -> list[PlatformEntry]:
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT {_COLS} FROM plat_platform ORDER BY platform_code"
            ).fetchall()
        return [_load(r) for r in rows]


def _load(row) -> PlatformEntry | None:
    if row is None:
        return None
    return PlatformEntry(
        platform_code=row[0],
        platform_name=row[1],
        platform_kind=row[2] or "",
        client_version=row[3] or "",
        icon=row[4] or "",
        capabilities=_load_values(row[5]),
        credential_kinds=_load_values(row[6]),
        schedule_times=_load_values(row[7]),
        schedule_override=_load_override(row[8]),
        base_url=row[9] or "",
        protocol=row[10] or "",
        models=_load_values(row[11]),
        origin=row[12] or "connector",
        is_active=bool(row[13]),
        deprecated_at=datetime.fromisoformat(row[14]) if row[14] else None,
        created_at=datetime.fromisoformat(row[15]),
    )

