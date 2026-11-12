#!/usr/bin/env python3
"""启用提交信息强制校验钩子（幂等，可重复执行）。

pnpm install 时由 scripts/setup_hooks.cjs 自动调用（node/npm 环境无需手动）；
纯 Python / 未跑 install 的环境手动执行一次：python scripts/install_hooks.py
原理：git config core.hooksPath .githooks —— 本仓库的 .githooks/ 即钩子目录。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HOOKS_DIR = ".githooks"


def main() -> int:
    # 与 verify_project.py 同样的控制台防护：不可编码字符降级，不在启用入口崩溃
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, OSError, ValueError):
            pass
    root = Path(__file__).resolve().parent.parent
    if not (root / HOOKS_DIR / "commit-msg").is_file():
        print(f"FAIL: 找不到 {HOOKS_DIR}/commit-msg（请在仓库根执行）")
        return 1
    r = subprocess.run(["git", "config", "--local", "core.hooksPath", HOOKS_DIR],
                       capture_output=True, text=True, cwd=root)
    if r.returncode != 0:
        print(f"FAIL: git 不可用（非 git 仓库或未安装 git）: {r.stderr.strip()}")
        return 1
    print("已启用提交信息强制校验: core.hooksPath = .githooks")
    return 0


if __name__ == "__main__":
    sys.exit(main())
