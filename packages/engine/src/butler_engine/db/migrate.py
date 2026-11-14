"""一次性迁移（A1-05 §4）：旧品牌数据库与凭据前缀统一收口到 butler。

设计约束：
- **幂等**：目标 butler.db 已存在即跳过；同一次运行重复调用零动作
- **保留目录**：旧数据库所在目录不删；主库文件按既有语义搬移改名
- **显式覆盖优先**：端层传了 BUTLER_DB 时不调用本模块（见 bridge.default_db_path）
- **审计**：每次搬移与凭据迁移都写日志（A1-03 §7）
- 运行时代码零 legacy 分支：凭据旧前缀只由 migrate_legacy_vault 显式读一次
"""

from __future__ import annotations

import shutil
from collections.abc import Iterable
from pathlib import Path
from typing import Callable

Logger = Callable[[str], None]

LEGACY_DB_SOURCES = ("kabao", "ai-marina")
LEGACY_VAULT_PREFIX = "marina.vault"


def legacy_db_candidates(root: Path, cwd: Path) -> list[Path]:
    """旧库源优先级（A1-03 §7）：品牌目录 kabao → CWD kabao →
    上一代 ai-marina → CWD marina。目录/文件名都是历史字面量，仅此处出现。"""

    parent = root.parent
    return [
        parent / "kabao" / "kabao.db",
        cwd / "kabao.db",
        parent / "ai-marina" / "marina.db",
        cwd / "marina.db",
    ]


def migrate_legacy_db(
    target: Path, root: Path, cwd: Path, *, log: Logger | None = None
) -> Path | None:
    """把优先级最高的旧库搬成 butler.db（含 -wal/-shm）；返回源，未迁移返回 None。"""

    if target.exists():
        return None  # 幂等：已迁移或用户已有新库
    for legacy in legacy_db_candidates(root, cwd):
        if not legacy.exists():
            continue
        for suffix in ("", "-wal", "-shm"):
            src = Path(str(legacy) + suffix)
            if src.exists():
                shutil.move(str(src), str(target) + suffix)
        if log:
            log(f"已迁移历史数据库 {legacy} → {target}")
        return legacy
    return None


def migrate_legacy_vault(
    backends: Iterable[object], refs: Iterable[str], *, log: Logger | None = None
) -> list[str]:
    """显式遍历已知凭据引用，把 marina.vault 旧前缀条目回写到新前缀。

    backends 只需实现可选的 `migrate_legacy_refs(refs)`；不支持的后端跳过。
    旧条目保留不删（天然备份），迁移失败不吞（由后端决定显式报错语义）。
    """

    migrated: list[str] = []
    refs = list(refs)
    for backend in backends:
        method = getattr(backend, "migrate_legacy_refs", None)
        if method is None:
            continue
        done = method(refs)
        for ref in done:
            if log:
                log(f"已迁移历史凭据前缀 {LEGACY_VAULT_PREFIX} → butler.vault: {ref}")
        migrated.extend(done)
    return migrated
