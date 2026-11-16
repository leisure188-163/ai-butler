"""浏览器会话捕获（A2-03 §2，R3 网页会话通道）：读 Chrome cookie 库出会话信封。

与 dockio 平行的第二条「读本机状态」通道：
- 发现 cookie 库（storage 候选，平台宏 + glob 文件；新旧布局两候选——
  Chrome ≥96 库在 <profile>/Network/Cookies）→ **字节拷贝临时件**
  （密文库，try/finally 用后即删；活动库被浏览器锁死 → SQLite immutable
  只读直开兜底，2026-11-13 Windows 真机取证）
- host（domain 精确或点后缀）× 必需名单过滤 → 逐条解密（unlock 单源）
- **每 profile 一账户**（ADR-011，2026-11-14 mac 真机取证：双 profile 均实存
  会话令牌）：逐 profile 捕获、各自成账户槽——首个凑齐者 = `main`（存量兼容），
  后续按 profile 目录名 slug 编键；同 profile 目录新旧布局并配只取首个库
- **逐 profile 隔离**：单库锁死/解不开 → 记原因换下一个 profile，不中断不静默
- 两态导入语义：无任何 profile 凑齐名单 = 未登录如实落榜（不注册账号）；
  名单凑齐但已过期 = 照常出卡（expires_at 为过去值，健康分级如实示 EXPIRED）
- 钥匙拒绝 / 解密失败 → DockOutcome.issues（红线 5，不静默不降级）；
  v20（Chrome 127+ 应用绑定加密）显式落榜，不做对抗解密（A2-03 §7）
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from butler_connectors.manifest import AuthSpec, CaptureSpec, ManifestInvalid
from butler_connectors.paths import expand_storage_path
from butler_connectors.registry import ConnectorApp, DockContext, DockOutcome


class StorageNotFound(Exception):
    """本机没有可捕获的浏览器会话（如实上报给 DockOutcome.issues）。"""


class ProfileUnreadable(ValueError):
    """单个 profile 库读不了（文案自足，直接进 DockOutcome.issues）。

    典型：活动库被运行中的浏览器锁死（Windows 真 Chrome 实证连 Python
    open 都进不去，2026-11-13）；语义 = profile 级事故，捕获流程换下一个
    profile 继续，不中断不静默。
    """


@dataclass(frozen=True)
class CapturedProfile:
    """一个凑齐名单的 profile 账户槽：编键 + 展示名事实 + 信封。"""

    profile_dir: str  # 库所在 profile 目录名（展示名与编键的事实来源）
    account_key: str  # 首个 = main（存量兼容）；后续 = 目录名 slug（去重后缀）
    envelope: str  # browser_cookie 信封 JSON


def capture_cookies(
    app: ConnectorApp,
    spec: CaptureSpec,
    kinds: tuple[str, ...],
    ctx: DockContext,
) -> DockOutcome:
    """声明式网页连接器的捕获入库：与 dockio.scan_storage 同构的编排。"""
    auth = spec.auth
    candidates = ctx.storage_override if ctx.storage_override is not None else auth.storage
    if not candidates:
        return DockOutcome(
            target=app.manifest.id,
            issues=[f"{app.manifest.id}: 没有候选 cookie 库（声明里 auth.storage 为空）"],
        )
    try:
        captured, capture_issues = _capture_kind(auth, app.manifest.id, candidates)
    except StorageNotFound as exc:
        return DockOutcome(target=app.manifest.id, issues=[str(exc)])
    except ManifestInvalid as exc:  # 显式事故 → 如实出账（与 dockio 同纪律）
        return DockOutcome(target=app.manifest.id, issues=[str(exc)])

    if not captured:
        if capture_issues:  # 无 profile 凑齐但有过显式事故：报首个原因（库序确定），不误报未登录
            return DockOutcome(target=app.manifest.id, issues=[capture_issues[0]])
        return DockOutcome(
            target=app.manifest.id,
            issues=[
                f"{app.manifest.id}: 未登录（Chrome 无 {auth.domain} 完整会话 cookie）——"
                "浏览器登录后重扫（未登录不是错误，A1-04 §4.1）"
            ],
        )

    from butler_connectors.dockio import _store_credentials

    accounts: list[str] = []
    for item in captured:
        display = (
            app.display
            if item.account_key == "main"
            else f"{app.display}（{item.profile_dir}）"
        )
        account = ctx.register.execute(app.manifest.id, display, account_key=item.account_key)
        _store_credentials(
            ctx, account.id, {"browser_cookie": item.envelope}, kinds, auth.kind,
            main_cookie_names=tuple(auth.cookies),
        )
        accounts.append(account.id)
    return DockOutcome(target=app.manifest.id, accounts=accounts)


def _capture_kind(
    auth: AuthSpec, conn_id: str, candidates: list[str], *, key_provider=None, dpapi=None
) -> tuple[list[CapturedProfile], list[str]]:
    """捕获主流程：逐 profile 出账户槽（ADR-011）。

    返回 (凑齐名单的 profile 列表, 显式事故列表)；列表全空且无事故 = 未登录
    （StorageNotFound，非错误）。钥匙一次取用，全槽共享（同一浏览器）。
    """
    from butler_connectors.unlock import CookieShapeError

    dbs = _cookie_dbs(candidates)
    if not dbs:
        raise StorageNotFound(
            f"{conn_id}: 未发现 Chrome cookie 库（候选: {candidates}）——"
            f"安装 Chrome 并在浏览器登录 {auth.domain} 后重扫"
        )
    try:
        key, gcm = _chrome_key(dbs[0], key_provider=key_provider, dpapi=dpapi)
    except StorageNotFound:
        raise
    except (OSError, ValueError, RuntimeError) as exc:
        import sys

        tail = (
            "mac 钥匙在 Keychain（Chrome Safe Storage）——确认 Chrome 本机登录过一次、"
            "未拒绝 Keychain 访问后重扫（首次读取会弹授权框，拒绝 = 导入失败，A1-04 §3）"
            if sys.platform == "darwin"
            else "请在 Chrome 可用环境下重扫（Windows 钥匙在 Local State，DPAPI 当前用户作用域）"
        )
        return [], [f"浏览器钥匙取不到（{exc}）——{tail}"]

    captured: list[CapturedProfile] = []
    issues: list[str] = []
    seen_dirs: set[str] = set()  # 同 profile 目录新旧布局并配：首个库（路径序）获胜
    used_keys: set[str] = set()
    main_taken = False
    for db in dbs:
        profile = _profile_of(db)
        if profile in seen_dirs:
            continue
        seen_dirs.add(profile)
        try:
            envelope = _capture_profile(db, auth, key, gcm)
        except CookieShapeError as exc:  # 形状显式申报（v20 等）：文案自足
            issues.append(f"{db}: {exc}")
            continue
        except ProfileUnreadable as exc:  # 读库失败（锁死/形状）：文案自足
            issues.append(f"{db}: {exc}")
            continue
        except (OSError, ValueError) as exc:
            issues.append(f"{db}: cookie 解不开（{exc}）——浏览器或库形状已变，重扫")
            continue
        if envelope is None:
            continue  # 名单不齐 = 该 profile 无登录态：非事故，静候下一个
        if not main_taken:
            account_key = "main"  # 首个凑齐者保存量卡位（重导幂等回放）
            main_taken = True
        else:
            slug = _profile_slug(profile)
            account_key = slug
            ordinal = 2
            while account_key in used_keys or account_key == "main":
                account_key = f"{slug}-{ordinal}"
                ordinal += 1
        used_keys.add(account_key)
        captured.append(
            CapturedProfile(profile_dir=profile, account_key=account_key, envelope=envelope)
        )
    return captured, issues


def _profile_of(db: Path) -> str:
    """库所在 profile 目录名：旧布局 <profile>/Cookies；新布局 <profile>/Network/Cookies。"""
    return db.parent.name if db.parent.name != "Network" else db.parent.parent.name


def _profile_slug(name: str) -> str:
    """profile 目录名 → 账户键 slug：小写、空格连字；空名兜底 profile（显式事实仍留展示名）。"""
    slug = name.strip().lower().replace(" ", "-").replace("_", "-")
    return slug or "profile"


def _is_profile_db(db: Path) -> bool:
    """只认 Chrome 用户 profile（Default / Profile N）的 cookie 库。

    组件目录（ActorSafetyLists 等）和 System Profile 里的同名 Cookies 文件
    不是用户会话库，必须排除，否则会拿错库并报“no such table: cookies”。
    """
    profile = db.parent.parent if db.parent.name == "Network" else db.parent
    name = profile.name
    return name == "Default" or (
        name.startswith("Profile ") and name[len("Profile "):].isdigit()
    )


def _cookie_dbs(candidates: list[str]) -> list[Path]:
    """候选展开为 cookie 库文件：含通配（任意段，如 Chrome 的 profile 段）=
    glob 展开取文件，路径排序稳定。"""
    import glob as _glob

    out: list[Path] = []
    for raw in candidates:
        base = expand_storage_path(raw)
        if base is None:
            continue  # 平台不适用：换下一个候选
        if "*" in raw or "?" in raw:
            files = sorted(Path(p) for p in _glob.glob(str(base)) if Path(p).is_file())
        else:
            files = [base] if base.is_file() else []
        out.extend(p for p in files if _is_profile_db(p))
    return out


def _chrome_key(example_db: Path, *, key_provider=None, dpapi=None) -> tuple[bytes, bool]:
    """浏览器 cookie 钥匙：(key, gcm)。mac = Keychain CLI → PBKDF2（16B/CBC）；
    win = Local State os_crypt.encrypted_key → DPAPI（32B/GCM）。
    A2-03 §1：钥匙只进内存，绝不入 vault 信封（现用现取，ADR-008 决策 3 同款）。"""
    import base64
    import json
    import sys

    if sys.platform == "darwin":
        from butler_connectors.unlock import chromium_cookie_key, macos_safe_storage_password

        secret = (key_provider or macos_safe_storage_password)("Chrome Safe Storage")
        return chromium_cookie_key(secret), False

    from butler_connectors.unlock import dpapi_unprotect

    # Local State 在 <User Data> 根：旧布局 <profile>/Cookies 差两级，
    # 现代布局（≥96）<profile>/Network/Cookies 差三级——向上逐级查找，布局无关
    state = next(
        (
            parent / "Local State"
            for parent in (example_db.parent, *example_db.parents)
            if (parent / "Local State").is_file()
        ),
        None,
    )
    if state is None:
        raise StorageNotFound(f"未发现 Chrome Local State（{example_db} 及其上层目录都没有）")
    try:
        data = json.loads(state.read_text(encoding="utf-8"))
        key_b64 = data["os_crypt"]["encrypted_key"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ValueError(f"Local State 形状不符: {exc}") from exc
    if not isinstance(key_b64, str) or not key_b64:
        raise ValueError("Local State 缺 os_crypt.encrypted_key")
    blob = base64.b64decode(key_b64)
    if not blob.startswith(b"DPAPI"):
        raise ValueError("密钥块缺 DPAPI 前缀（Local State 形状已变?）")
    decrypt = dpapi if dpapi is not None else dpapi_unprotect
    return decrypt(blob[len(b"DPAPI") :]), True


def _capture_profile(db: Path, auth: AuthSpec, key: bytes, gcm: bool) -> str | None:
    """单 profile 捕获：凑齐必需名单 → 信封 JSON；名单不齐 → None（换下一个 profile）。

    mac 链（gcm=False）落地域绑定头校验（A1-04 §4.1-8）：头 32B 解密
    ≠ sha256(host_key) = 钥匙错位/库形状已变 → ValueError 显式出账，不静默。
    """
    from butler_connectors.unlock import decrypt_chromium_cookie, verify_mac_cookie_header

    rows = _read_cookie_rows(db, auth.domain)
    wanted: dict[str, str | None] = {name: None for name in auth.cookies}
    expires: dict[str, int] = {}
    for name, host_key, encrypted, legacy, expires_utc in rows:
        if name not in wanted or wanted[name] is not None:
            continue  # 每名只取首行（同名跨 host 的重复 cookie 无增量）
        if encrypted:
            if not gcm and not verify_mac_cookie_header(encrypted, key, host_key):
                raise ValueError(
                    f"cookie {name!r}（host={host_key}）域绑定头不符——"
                    "钥匙错位或库形状已变，重扫"
                )
            plain = decrypt_chromium_cookie(encrypted, key, gcm=gcm)
            try:
                wanted[name] = plain.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ValueError(f"cookie {name!r} 明文非 UTF-8（形状已变?）: {exc}") from exc
        elif legacy:
            wanted[name] = legacy  # legacy 明文列（无密文）：原样收，如实
        else:
            continue  # 密文与明文皆空：视为该 profile 无此 cookie
        expires[name] = expires_utc
    if any(value is None for value in wanted.values()):
        return None

    cookies: list[dict] = []
    for name in auth.cookies:  # 名单顺序 = 信封顺序（确定性与探针头稳定）
        item: dict = {"name": name, "value": wanted[name]}
        iso = _webkit_to_iso(expires.get(name, 0))
        if iso:
            item["expires_at"] = iso
        cookies.append(item)
    import json

    return json.dumps(
        {"browser": auth.browser, "domain": auth.domain, "cookies": cookies},
        separators=(",", ":"),
        ensure_ascii=True,
    )


def _read_cookie_rows(db: Path, domain: str) -> list[tuple[str, str, bytes, str | None, int]]:
    """cookie 行只读读取（name, host_key, encrypted_value, value, expires_utc），
    两条路（A2-03 §2，2026-11-13 Windows 真机取证补）：

    ①字节拷贝临时件 → 临时件只读查询（拷的是密文库，用后即删，绝不落明文）；
    ②活动库被浏览器锁死（Windows 真 Chrome：连 Python open 都 PermissionError，
      SQLite immutable 直开同样进不去）→ SQLite ``immutable=1`` 只读直开原库
      ——零锁零写，对浏览器零影响；明文照旧只在内存。

    失败一律 ProfileUnreadable（文案自足：锁死指关浏览器，形状指重扫）。
    """
    import os
    import sqlite3

    sql = (
        "SELECT name, host_key, encrypted_value, value, expires_utc FROM cookies "
        "WHERE host_key = ? OR host_key LIKE ?"
    )
    args = (domain, f"%.{domain}")
    tmp = _temp_copy_encrypted_db(db)
    locked = tmp is None  # 浏览器锁死 → immutable 只读直开（connect 也可能失败，同 try 兜住）
    try:
        if locked:
            from urllib.parse import quote

            conn = sqlite3.connect(f"file:{quote(db.as_posix())}?immutable=1", uri=True)
        else:
            conn = sqlite3.connect(tmp)
        try:
            return _query_rows(conn, sql, args)
        finally:
            conn.close()
    except sqlite3.Error as exc:
        raise ProfileUnreadable(
            f"cookie 库被浏览器锁住且只读直开失败（{exc}）——关闭浏览器后重扫"
            if locked
            else f"cookie 库查询失败（{exc}）——库形状已变，重扫"
        ) from exc
    finally:
        if not locked:
            os.unlink(tmp)  # 密文临时件用后即删（取证纪律）


def _temp_copy_encrypted_db(db: Path) -> Path | None:
    """密文库字节拷贝到临时件；浏览器锁死（PermissionError）→ None（immutable 兜底）；
    其余拷贝事故 → ProfileUnreadable。临时件失败时同样即删。"""
    import os
    import shutil
    import tempfile

    fd, tmp = tempfile.mkstemp(prefix="butler-cookies-", suffix=".sqlite")
    os.close(fd)
    try:
        shutil.copyfile(db, tmp)
    except PermissionError:
        os.unlink(tmp)
        return None
    except OSError as exc:
        os.unlink(tmp)
        raise ProfileUnreadable(f"cookie 库拷贝失败（{exc}）——关闭浏览器后重扫") from exc
    return tmp


def _query_rows(conn, sql: str, args: tuple) -> list[tuple[str, str, bytes, str | None, int]]:
    return [(row[0], row[1], row[2], row[3], row[4]) for row in conn.execute(sql, args)]


def _webkit_to_iso(micros: int) -> str | None:
    """WebKit 纪元（1601-01-01 起微秒）→ ISO8601；0 = 会话 cookie → None。"""
    if micros <= 0:
        return None
    from datetime import UTC, datetime, timedelta

    epoch = datetime(1601, 1, 1, tzinfo=UTC)
    return (epoch + timedelta(microseconds=micros)).isoformat()
