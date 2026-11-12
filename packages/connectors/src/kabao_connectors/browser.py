"""浏览器会话捕获（A2-03 §2，R3 网页会话通道）：读 Chrome cookie 库出会话信封。

与 dockio 平行的第二条「读本机状态」通道：
- 发现 cookie 库（storage 候选，平台宏 + glob 文件）→ **字节拷贝临时件**
  （浏览器运行中持锁；try/finally 用后即删——拷贝的是密文库，取证纪律照 M1）
- host（domain 精确或点后缀）× 必需名单过滤 → 逐条解密（unlock 单源）
- 两态导入语义：无任何 profile 凑齐名单 = 未登录如实落榜（不注册账号）；
  名单凑齐但已过期 = 照常出卡（expires_at 为过去值，健康分级如实示 EXPIRED）
- 钥匙拒绝 / 解密失败 → DockOutcome.issues（红线 5，不静默不降级）
"""

from __future__ import annotations

from pathlib import Path

from kabao_connectors.manifest import AuthSpec, CaptureSpec, ManifestInvalid
from kabao_connectors.paths import expand_storage_path
from kabao_connectors.registry import ConnectorApp, DockContext, DockOutcome


class StorageNotFound(Exception):
    """本机没有可捕获的浏览器会话（如实上报给 DockOutcome.issues）。"""


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
        facts = _capture_kind(auth, app.manifest.id, candidates)
    except StorageNotFound as exc:
        return DockOutcome(target=app.manifest.id, issues=[str(exc)])
    except ManifestInvalid as exc:  # 显式事故 → 如实出账（与 dockio 同纪律）
        return DockOutcome(target=app.manifest.id, issues=[str(exc)])

    if "_issue" in facts:
        return DockOutcome(target=app.manifest.id, issues=[facts["_issue"]])

    from kabao_connectors.dockio import _store_credentials

    account = ctx.register.execute(app.manifest.id, app.display)
    _store_credentials(ctx, account.id, facts, kinds, auth.kind)
    return DockOutcome(target=app.manifest.id, accounts=[account.id])


def _capture_kind(
    auth: AuthSpec, conn_id: str, candidates: list[str], *, key_provider=None, dpapi=None
) -> dict[str, str]:
    """捕获主流程：facts = {"browser_cookie": 信封}，或 _issue / StorageNotFound。"""
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
        return {"_issue": f"浏览器钥匙取不到（{exc}）——{tail}"}

    for db in dbs:
        try:
            captured = _capture_profile(db, auth, key, gcm)
        except (OSError, ValueError) as exc:
            return {"_issue": f"{db}: cookie 解不开（{exc}）——浏览器或库形状已变，重扫"}
        if captured is not None:
            return {"browser_cookie": captured}
    raise StorageNotFound(
        f"{conn_id}: 未登录（Chrome 无 {auth.domain} 完整会话 cookie）——"
        "浏览器登录后重扫（未登录不是错误，A1-04 §4.1）"
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
        out.extend(files)
    return out


def _chrome_key(example_db: Path, *, key_provider=None, dpapi=None) -> tuple[bytes, bool]:
    """浏览器 cookie 钥匙：(key, gcm)。mac = Keychain CLI → PBKDF2（16B/CBC）；
    win = Local State os_crypt.encrypted_key → DPAPI（32B/GCM）。
    A2-03 §1：钥匙只进内存，绝不入 vault 信封（现用现取，ADR-006 决策 3 同款）。"""
    import base64
    import json
    import sys

    if sys.platform == "darwin":
        from kabao_connectors.unlock import chromium_cookie_key, macos_safe_storage_password

        secret = (key_provider or macos_safe_storage_password)("Chrome Safe Storage")
        return chromium_cookie_key(secret), False

    from kabao_connectors.unlock import dpapi_unprotect

    state = example_db.parent.parent / "Local State"  # <User Data>/<profile>/Cookies → User Data 根
    if not state.is_file():
        raise StorageNotFound(f"未发现 Chrome Local State（候选: {state}）")
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
    """单 profile 捕获：凑齐必需名单 → 信封 JSON；名单不齐 → None（换下一个 profile）。"""
    from kabao_connectors.unlock import decrypt_chromium_cookie

    rows = _read_cookie_rows(db, auth.domain)
    wanted: dict[str, str | None] = {name: None for name in auth.cookies}
    expires: dict[str, int] = {}
    for name, encrypted, legacy, expires_utc in rows:
        if name not in wanted or wanted[name] is not None:
            continue  # 每名只取首行（同名跨 host 的重复 cookie 无增量）
        if encrypted:
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


def _read_cookie_rows(db: Path, domain: str) -> list[tuple[str, bytes, str | None, int]]:
    """密文临时拷贝 → 查 host 匹配行（name, encrypted_value, value, expires_utc）。

    拷贝的是密文库（用后即删，绝不落明文）；SQLite 打开临时件只读查询。
    """
    import os
    import shutil
    import sqlite3
    import tempfile

    fd, tmp = tempfile.mkstemp(prefix="kabao-cookies-", suffix=".sqlite")
    os.close(fd)
    try:
        shutil.copyfile(db, tmp)
        conn = sqlite3.connect(tmp)
        try:
            return [
                (row[0], row[1], row[2], row[3])
                for row in conn.execute(
                    "SELECT name, encrypted_value, value, expires_utc FROM cookies "
                    "WHERE host_key = ? OR host_key LIKE ?",
                    (domain, f"%.{domain}"),
                )
            ]
        finally:
            conn.close()
    finally:
        os.unlink(tmp)


def _webkit_to_iso(micros: int) -> str | None:
    """WebKit 纪元（1601-01-01 起微秒）→ ISO8601；0 = 会话 cookie → None。"""
    if micros <= 0:
        return None
    from datetime import UTC, datetime, timedelta

    epoch = datetime(1601, 1, 1, tzinfo=UTC)
    return (epoch + timedelta(microseconds=micros)).isoformat()
