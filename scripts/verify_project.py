#!/usr/bin/env python3
"""一核多端架构 · 生成项目验证器

用法:
    python verify_project.py --project /path/to/my-app [--test]

检查项（全部通过输出 PASS，否则逐条列出 FAIL）:
  1. 结构完整性 —— 必需文件全部存在（含核心/各端/契约流水线/设计决策记录）
  2. 核心纯净性 —— packages/core 源码禁止 import 任何框架
     (fastapi/sqlalchemy/typer/uvicorn/httpx/requests/pydantic/flask/django/starlette/rich/click/aiohttp)
     这是"一核多端"的铁律: 核心只依赖标准库
  3. 依赖方向性 —— 各端依赖核心(core)，核心不得反向依赖任何端
  4. 六边形桥闭合 —— 端只准经 packages/engine 的 bridge 触达引擎, 端间禁止互引
  5. Token 引用闭合 —— web 端引用的 var(--x) 必须在 tokens.css(或本文件)定义,
     防止"样式残缺但不报错"的隐性破损(真实事故: tokens.css 缺 --space-5 等);
     带显式回退值的 var(--x, fallback) 视为语义自洽放行
  6. 契约新鲜度 —— 重算 server openapi 指纹与 packages/sdk 记录比对
  7. 无空包残留 —— 改名/重构遗留的空包目录当场报错
  8. 文件长度上限 —— packages/apps/scripts 下代码文件 >600 行 FAIL
     (conventions/04 §2.2: 超长文件 = 认知负载黑洞, 按 域/职责 拆分;
      排除 gen/ node_modules 等派生物; 文档不进本检查)
  9. 测试通过性 —— (--test) uv run pytest 跑根 pyproject testpaths 全量
     (core/engine/connectors/server) + web 端 vue-tsc 类型检查
     (2026-11-12 起: types.ts 派生自 packages/sdk 契约, 字段漂移当场拦截)
"""
from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path

FORBIDDEN_IN_CORE = {
    "fastapi", "sqlalchemy", "typer", "uvicorn", "httpx", "requests",
    "pydantic", "flask", "django", "starlette", "rich", "click", "aiohttp",
}
def check_manifest(root: Path, pkg: str) -> list[str]:
    required = [
        "pyproject.toml", "pnpm-workspace.yaml", "package.json",
        f"packages/core/pyproject.toml",
        f"packages/core/src/{pkg}_core/__init__.py",
        "apps/server/pyproject.toml",
        "apps/server/src/server/main.py",
        "apps/server/src/server/routes/__init__.py",
        "apps/cli/pyproject.toml",
        "apps/web/package.json", "apps/web/vite.config.ts",
        "apps/web/src/styles/tokens.css",
        "docs/DESIGN-DECISIONS.md",   # 阶段 3.5 设计包流程的必产物(决策可追溯)
        "apps/desktop/main.py" if (root / "apps/desktop/main.py").exists()
        else "apps/desktop/main.js",
        "packages/sdk/generate.mjs",
        "packages/sdk/src/gen/schema.d.ts",  # 契约产物必须随仓库走
        "packages/sdk/src/gen/openapi.sha256",  # 契约指纹(新鲜度门禁比对基准)
        "scripts/verify_project.py",
        ".github/workflows/ci.yml",
        ".githooks/commit-msg",        # 提交信息强制校验钩子（README 提交与协作节）
        "scripts/install_hooks.py",    # 钩子启用器（sync.py/setup_hooks.cjs 之外的纯 Python 入口）
        "scripts/setup_hooks.cjs",     # pnpm install 自动启用钩子的 Node 收尾脚本
        ".env.example",  # docker-compose.yml 已删（2026-11-12）：postgres/JWT_SECRET
                         # 与 SQLite 单机架构漂移（M2 取证清单顺手项），非必需产物
    ]
    # ADR-012：butler_core 按业务域分包（shared + 五域）；旧包仍是分层结构。
    # 双包并存期按检出的包名走对应结构，删除旧包后只保留分支一。
    core_dir = f"packages/core/src/{pkg}_core"
    if pkg == "butler":
        required += [
            f"{core_dir}/{d}/__init__.py"
            for d in ("shared", "accounts", "execution", "usage", "health", "scheduling")
        ]
    else:
        required += [
            f"{core_dir}/domain/__init__.py",
            f"{core_dir}/application/__init__.py",
        ]
    missing = [p for p in required if not (root / p).exists()]
    # 测试目录至少要有一个测试文件(具体文件名随业务命名,不硬编码)
    tests_dir = root / "packages/core/tests"
    if not (tests_dir.is_dir() and any(tests_dir.glob("test_*.py"))):
        missing.append("packages/core/tests/test_*.py")
    return [f"缺少必需文件: {p}" for p in missing]


def check_core_purity(root: Path, pkg: str) -> list[str]:
    fails: list[str] = []
    core_src = root / f"packages/core/src/{pkg}_core"
    if not core_src.is_dir():
        return [f"核心目录不存在: {core_src}"]
    for py in core_src.rglob("*.py"):
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"))
        except SyntaxError as e:
            fails.append(f"语法错误 {py.relative_to(root)}: {e}")
            continue
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module.split(".")[0]]
            for n in names:
                if n in FORBIDDEN_IN_CORE:
                    fails.append(
                        f"核心纯净性违规: {py.relative_to(root)} import 了框架 '{n}'"
                    )
    # pyproject 依赖检查：兼容单行 dependencies = ["x"] 与多行数组
    proj = root / "packages/core/pyproject.toml"
    if proj.exists():
        text = proj.read_text(encoding="utf-8")
        m = re.search(r"^dependencies\s*=\s*\[(.*?)\]", text, re.DOTALL | re.MULTILINE)
        if m:
            for item in re.findall(r'"([^"]+)"', m.group(1)):
                base = item.split(">")[0].split("<")[0].split("=")[0].strip().lower()
                if base in FORBIDDEN_IN_CORE:
                    fails.append(f"核心 pyproject 声明了框架依赖: {item}")
    return fails


def check_dep_direction(root: Path) -> list[str]:
    fails: list[str] = []
    core_meta = root / "packages/core/pyproject.toml"
    if core_meta.exists():
        text = core_meta.read_text(encoding="utf-8")
        for kw in ("apps/", "fastapi", "typer"):
            if f'"{kw}' in text:
                fails.append(f"核心不得依赖任何端（packages/core/pyproject.toml 含 '{kw}'）")
    return fails


def check_domain_isolation(root: Path) -> list[str]:
    """ADR-012 依赖恒等式机检：业务域 domain.py 只准 import shared。

    域间编排必须经用例层组合端口；domain.py 直接 import 另一个业务域 = 边界失守。
    """
    core = root / "packages/core/src/butler_core"
    if not core.is_dir():
        return []
    domains = {"accounts", "execution", "usage", "health", "scheduling"}
    fails: list[str] = []
    for name in sorted(domains):
        path = core / name / "domain.py"
        if not path.exists():
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            mods: list[str] = []
            if isinstance(node, ast.ImportFrom) and node.module:
                mods = [node.module]
            elif isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            for mod in mods:
                parts = mod.split(".")
                if parts[0] == "butler_core" and len(parts) > 1 and parts[1] != "shared":
                    fails.append(
                        f"业务域边界违规: {path.relative_to(root)} import 了 {mod} "
                        "——domain.py 只准依赖 shared（A1-05 §2）"
                    )
    return fails


# 端间互触白名单: desktop 允许 import server 的启动装配入口(离线模式内嵌 uvicorn),
# 这是六边形拓扑里唯一的端间豁免(见 references/clients.md §2 关系矩阵)。
_END_IMPORT_WHITELIST = {"desktop": {"server"}}


def check_hexagonal(root: Path) -> list[str]:
    """六边形门禁(规约 R4 + 端间隔离,见 references/hexagonal-arch.md):

    1. 引擎必须提供 bridge.py 作为唯一出桥模块;
    2. 各端只允许 `from <engine>.bridge import ...` 触达引擎,
       直接 import 引擎内部子包即违规;
    3. 端之间禁止互相 import(白名单除外)。
    该类违规不崩构建——只是让"一核多端"退化成"多核各自为政",
    依赖方向错误会在数月后才以语义漂移的形式爆发,必须机器拦截。
    """
    eng_src = root / "packages/engine/src"
    ends_root = root / "apps"
    if not eng_src.is_dir() or not ends_root.is_dir():
        return []
    inner = [d.name for d in eng_src.iterdir()
             if d.is_dir() and (d / "__init__.py").exists()]
    if not inner:
        return []
    engpkg = inner[0]
    fails: list[str] = []
    if not (eng_src / engpkg / "bridge.py").exists():
        fails.append(f"引擎缺少 {engpkg}/bridge.py——端与引擎之间必须有唯一六边形桥")
    import re
    eng_imp = re.compile(
        rf"^\s*(?:from|import)\s+{engpkg}(?:\s+import\s+(\w+)|\.([\w.]+))", re.M)
    end_names = [d.name for d in ends_root.iterdir() if d.is_dir()]
    for end in end_names:
        for f in (ends_root / end).rglob("*.py"):
            text = f.read_text(encoding="utf-8", errors="ignore")
            for m in eng_imp.finditer(text):
                mod = m.group(1) or (m.group(2).split(".")[0] if m.group(2) else "")
                if mod and mod != "bridge":
                    fails.append(
                        f"{f.relative_to(root)} 直接 import {engpkg}.{mod}"
                        f"——端只允许经 {engpkg}.bridge 触达引擎(规约 R4)")
            for other in end_names:
                if other == end or other in _END_IMPORT_WHITELIST.get(end, ()):
                    continue
                if re.search(rf"^\s*(?:from|import)\s+{other}\b", text, re.M):
                    fails.append(
                        f"{f.relative_to(root)} import 了端 {other}"
                        "——端之间禁止互相引用(见 clients.md §2 关系矩阵)")
    return fails


_VAR_REF = re.compile(r"var\(\s*(--[\w-]+)\s*([,)])")
_VAR_DEF = re.compile(r"^\s*(--[\w-]+)\s*:", re.MULTILINE)


def check_token_closure(root: Path) -> list[str]:
    """web 端引用的每个 var(--x) 必须有定义(tokens.css 或引用所在文件)。

    背景: 该类破损不报错、不崩构建——页面只是"安静地变丑/残缺",
    人工 review 极易漏检,必须机器判定。
    例外: `var(--x, 回退值)` 带显式回退 = 作者已显式声明缺定义时的行为,
    CSS 语义自洽,不算"安静地残缺",放行(如逐卡 stagger 的 var(--i, 0))。
    """
    web_src = root / "apps/web/src"
    if not web_src.is_dir():
        return []
    tokens = web_src / "styles/tokens.css"
    defined: set[str] = set()
    if tokens.exists():
        defined |= set(_VAR_DEF.findall(tokens.read_text(encoding="utf-8")))
    fails: list[str] = []
    for f in [*web_src.rglob("*.css"), *web_src.rglob("*.vue")]:
        if not f.is_file():
            continue
        text = f.read_text(encoding="utf-8")
        local_defs = set(_VAR_DEF.findall(text))
        for name, has_fallback in set(_VAR_REF.findall(text)):
            if has_fallback == ",":
                continue  # 带显式回退值：语义自洽，放行
            if name not in defined and name not in local_defs:
                fails.append(
                    f"Token 引用未定义: {f.relative_to(root)} 引用 {name}"
                    f"(tokens.css 缺该变量)")
    return fails



def check_sdk_freshness(root: Path) -> list[str]:
    """契约新鲜度门禁: 重算 server 契约指纹,与 packages/sdk 生成时记录的比对。

    背景(真实事故): generate.mjs 存在却从未被执行,manifest 只查文件存在性,
    前端类型与后端契约静默漂移。此检查让"改了后端没重新生成 SDK"当场 FAIL。
    指纹 = `print(json.dumps(app.openapi()))` 输出的 sha256,
    由 generate.mjs 在生成时写入 src/gen/openapi.sha256。
    """
    gen_dir = root / "packages/sdk/src/gen"
    if not (gen_dir / "schema.d.ts").exists():
        return []  # 缺产物由结构完整性检查负责
    import hashlib
    import subprocess
    probe = ("uv run python -c "
             '"import json; from server.main import app; '
             'print(json.dumps(app.openapi()))"')
    r = subprocess.run(probe, shell=True, cwd=root,
                       capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        tail = ((r.stderr or "").strip().splitlines() or ["导出失败"])[-1]
        return [f"无法从 server.main 导出 openapi.json,契约新鲜度不可验证: {tail}"]
    current = hashlib.sha256(r.stdout.encode()).hexdigest()
    hash_file = gen_dir / "openapi.sha256"
    if not hash_file.exists():
        return ["缺少 packages/sdk/src/gen/openapi.sha256——运行 gen:sdk 记录契约指纹"]
    if hash_file.read_text(encoding="utf-8").strip() != current:
        return ["契约漂移: server 契约已变更但 SDK 未重新生成——运行 gen:sdk 后重试"]
    return []


def check_tests(root: Path) -> list[str]:
    import os
    import subprocess

    # Windows 编码口径（2026-11-13 真机）：子进程写 UTF-8（PYTHONIOENCODING）+
    # 父进程按 UTF-8 解（errors=replace）——默认两侧都跟控制台代码页（GBK），
    # 子进程任何 UTF-8 字节（如 pytest 输出里的 ✓）都让读线程 UnicodeDecodeError
    # 崩掉，门禁整条失明误报「核心测试未通过」。
    def run(cmd, **kw):
        env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
        return subprocess.run(
            cmd, capture_output=True, text=True,
            encoding="utf-8", errors="replace", env=env, **kw,
        )

    try:
        # 本仓定制（2026-11-11）：跑根 pyproject testpaths 全量（core/engine/
        # connectors/server）——skill 上游口径只跑 core，M1 装配后 server 路由
        # 的回归（如 timedelta 漏 import）不在其中会漏检
        r = run(["uv", "run", "pytest", "-q"], cwd=root, timeout=600)
    except FileNotFoundError:
        return ["uv 不可用（未安装或不在 PATH）: 无法运行核心测试，请安装 uv 或去掉 --test"]
    # stdout/stderr 理论上 capture_output 必非 None，但实测瞬态环境（shell profile
    # 部分初始化）下崩溃过一次 None + str——门禁崩溃 = 门禁失明，全部 or "" 设防
    tail = ((r.stdout or "") + (r.stderr or "")).strip().splitlines()[-1:] or [""]
    if r.returncode != 0:
        return [f"核心测试未通过: {tail[0]}"]
    # 本仓定制（2026-11-12）：web 端类型检查收编进门禁——types.ts 派生自
    # packages/sdk 契约（红线 2/4），server 改字段后 vue-tsc 必须当场报错；
    # pytest 只覆盖 Python 侧。shell=True 与契约指纹检查同款（Windows 下
    # pnpm 是 .cmd shim，list 形式解析不到）。
    probe = run("pnpm --version", shell=True)
    if probe.returncode != 0:
        return ["pnpm 不可用（未安装或不在 PATH）: 无法运行 web 端 vue-tsc 类型检查"]
    wt = run(
        "pnpm --dir apps/web exec vue-tsc --noEmit",
        shell=True, cwd=root, timeout=300,
    )
    if wt.returncode != 0:
        tails = ((wt.stdout or "") + (wt.stderr or "")).strip().splitlines()[-5:]
        return ["web 端类型检查未通过（契约漂移?）: " + " | ".join(tails)]
    return []


def check_empty_packages(root: Path) -> list[str]:
    """检查: 源码树里不许留空目录(改名/重构残留的死包)。

    2026-11-07 真实事故(open-work-kit): 重构把 ``owk_engine/store`` 改名
    ``ledger``,旧目录被清空但目录还在。Python 3 会把它当成**命名空间包**,
    于是 ``from owk_engine import store`` 不报错、里面却什么都没有 ——
    ``AttributeError`` 落到 best-effort 的 ``except`` 里被吞,整天的台账
    静默丢失,dashboard 一片空白而 CLI 输出一切正常。

    "空目录让导入假成功"会把断链伪装成健康,必须在自检里拦下。
    """
    fails: list[str] = []
    for src in sorted(p for p in (root / "packages").glob("*/src") if p.is_dir()):
        for d in sorted(p for p in src.rglob("*") if p.is_dir()):
            if "__pycache__" in d.parts:
                continue
            files = [f for f in d.rglob("*")
                     if f.is_file() and "__pycache__" not in f.parts]
            if not files:
                fails.append(f"空包目录(改名/重构残留?): {d.relative_to(root)}")
    return fails


FILE_HARD_LIMIT = 600  # 行（conventions/04 §2.2 硬上限；软警戒 400 归 review 把关）
_LENGTH_SCAN_SUFFIXES = ("*.py", "*.ts", "*.tsx", "*.vue", "*.js", "*.mjs")
_LENGTH_EXCLUDE_PARTS = {
    "node_modules", ".venv", "__pycache__", "gen", "dist", "coverage", "build",
}


def check_file_length(root: Path) -> list[str]:
    """文件长度硬上限门禁（conventions/04）：代码文件 >600 行 FAIL。

    背景: api.py 单文件混堆 10 端点/4 业务域到 482 行——超长文件不是
    一次事故,是持续的管理债,人工 review 拦不住线性增长,必须机检。
    只扫 packages/apps/scripts 源码树;gen/ 等派生物与文档不在此列。
    """
    fails: list[str] = []
    for scan_name in ("packages", "apps", "scripts"):
        scan = root / scan_name
        if not scan.is_dir():
            continue
        for pattern in _LENGTH_SCAN_SUFFIXES:
            for f in scan.rglob(pattern):
                if not f.is_file():
                    continue
                if any(part in _LENGTH_EXCLUDE_PARTS for part in f.parts):
                    continue
                lines = sum(1 for _ in f.open("rb"))
                if lines > FILE_HARD_LIMIT:
                    fails.append(
                        f"文件超长: {f.relative_to(root)} {lines} 行 > "
                        f"{FILE_HARD_LIMIT}（conventions/04 §2.2，按域/职责拆分）"
                    )
    return fails


def _safe_stdout() -> None:
    """Windows GBK 控制台防护: ✗/✓/— 等符号无法编码会让 print 崩溃。

    只把不可编码字符降级为 ?（中文正常显示），不改变控制台编码本身。
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, OSError, ValueError):
            pass


def main() -> int:
    _safe_stdout()
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True, help="生成的项目根目录")
    ap.add_argument("--test", action="store_true", help="同时运行核心层测试")
    args = ap.parse_args()
    root = Path(args.project).resolve()
    if not root.is_dir():
        print(f"FAIL: 项目目录不存在: {root}")
        return 2

    # 从 packages/core/src 推断包名
    src = root / "packages/core/src"
    pkgs = [d.name for d in src.iterdir() if d.is_dir() and d.name.endswith("_core")] if src.is_dir() else []
    pkg = pkgs[0].removesuffix("_core") if pkgs else "app"

    fails: list[str] = []
    fails += check_manifest(root, pkg)
    fails += check_core_purity(root, pkg)
    fails += check_dep_direction(root)
    fails += check_domain_isolation(root)
    fails += check_hexagonal(root)
    fails += check_token_closure(root)
    fails += check_sdk_freshness(root)
    fails += check_empty_packages(root)
    fails += check_file_length(root)
    if args.test:
        fails += check_tests(root)

    print(f"项目: {root}")
    print(f"包名: {pkg}_core")
    if fails:
        print(f"\nFAIL — {len(fails)} 项违规:")
        for f in fails:
            print(f"  ✗ {f}")
        return 1
    print("\nPASS — 结构完整、核心纯净、依赖方向正确、六边形桥闭合、Token 闭合、契约新鲜、无空包残留、文件长度合规" + ("、测试通过" if args.test else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
