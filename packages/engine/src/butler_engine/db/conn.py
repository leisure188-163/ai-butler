"""SQLite 连接单源（A4-01 §5 数据根条款）：全引擎适配器统一从这里拿连接。

为什么单源（2026-11-16 收口）：journal_mode=OFF 的口径曾复制在五个适配器里，
第六个（accounts）抄漏——同一段纪律靠复制必然漂移。连接纪律只写这一处：

- **journal_mode=OFF**：本机文件虚拟化层拦截 home 目录 sqlite 伴生文件
  （-wal/-shm/-journal 创建即被回收，2026-11-16 四次 disk I/O error 实证），
  无伴生文件才能写库。代价如实登记：OFF 无回滚日志，**崩溃/掉电可能损坏
  库文件本身**（不是"丢最后一条写"），定期备份是唯一兜底（STATUS 剩余挂账）。
- 每操作一连接：连接不跨线程共享，线程安全由"不共享"保证。
- 忙等沿用 Python sqlite3 默认 5 秒：双进程（主控 + 网关）写同一库时靠它排队，
  超时 SQLITE_BUSY 由调用方按各自台账语义显式处理（不静默）。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path


def connect(db_path: str | Path) -> sqlite3.Connection:
    """开一条新连接并套上引擎统一 journal 口径（纪律见模块 docstring）。"""
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=OFF")
    return conn
