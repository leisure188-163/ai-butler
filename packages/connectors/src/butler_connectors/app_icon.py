"""本机客户端图标探测：平台册 `icon` 的通用事实源（2026-11-19 裁决）。

口径与 `app_version` 同族（不另造第二套安装位置判定）：Windows 先按 DisplayName
前缀、再按 DisplayIcon 的 exe 文件名匹配卸载注册表，取 DisplayIcon 指向的
exe/ico 本体；有多个命中时取 DisplayVersion 最大那条（"这台机器装的最新客户端"）。

提取链：`PrivateExtractIcons` 取 96px HICON → `GetIconInfo` 拿 hbmColor →
`GetDIBits` 取 32bpp 自顶向下 BGRA → 合成 RGBA → 用标准库 zlib 写成 PNG →
base64 data URI。全程纯 ctypes，不依赖 Pillow（本仓库 venv 没有图像库）。

只读、不拉起客户端；未安装/读不到/提取失败一律返回 ``""``（名册如实显示无图标，
前端回落身份色点），不猜、不造假（红线 5）。macOS 暂不实现（.icns 解析另立任务）。
"""

from __future__ import annotations

import base64
import ctypes
import struct
import sys
import zlib
from pathlib import Path

_SIZE = 96
_MAX_SIZE = 2_000_000  # 单张 PNG 字节上限：超过说明不是图标，宁可不要


def platform_icon(
    *,
    prefixes: tuple[str, ...],
    exe_names: tuple[str, ...] = (),
) -> str:
    """本机该平台客户端的图标 data URI；取不到返回 ``""``。

    ``prefixes`` 走 DisplayName 前缀（casefold），``exe_names`` 走 DisplayIcon
    文件名兜底——与 `app_version.display_version` 同口径，避免同族产品互认。
    """
    if sys.platform != "win32":
        return ""
    source = _icon_source(prefixes, exe_names)
    if source is None:
        return ""
    png = _extract_png(source)
    if not png:
        return ""
    return "data:image/png;base64," + base64.b64encode(png).decode("ascii")


def _icon_source(prefixes: tuple[str, ...], exe_names: tuple[str, ...]) -> Path | None:
    """卸载注册表 → DisplayIcon 本体路径（多命中取版本最大那条）。"""
    from butler_connectors.app_version import _registry_rows, _version_key

    best: tuple[tuple[int, ...], Path] | None = None
    for values in _registry_rows():
        display = values.get("DisplayName", "").casefold()
        raw = values.get("DisplayIcon", "").split(",")[0].strip().strip('"')
        if not raw:
            continue
        candidate = Path(raw)
        exe = candidate.name.casefold()
        matched = any(display.startswith(p.casefold()) for p in prefixes)
        if not matched and exe:
            matched = any(exe == e.casefold() for e in exe_names)
        if not matched or not candidate.is_file():
            continue
        key = _version_key(values.get("DisplayVersion", "").strip())
        if best is None or key > best[0]:
            best = (key, candidate)
    return best[1] if best else None


class _ICONINFO(ctypes.Structure):
    _fields_ = [
        ("fIcon", ctypes.c_int),
        ("xHotspot", ctypes.c_uint32),
        ("yHotspot", ctypes.c_uint32),
        ("hbmMask", ctypes.c_void_p),
        ("hbmColor", ctypes.c_void_p),
    ]


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", ctypes.c_uint32),
        ("biWidth", ctypes.c_int32),
        ("biHeight", ctypes.c_int32),
        ("biPlanes", ctypes.c_uint16),
        ("biBitCount", ctypes.c_uint16),
        ("biCompression", ctypes.c_uint32),
        ("biSizeImage", ctypes.c_uint32),
        ("biXPelsPerMeter", ctypes.c_int32),
        ("biYPelsPerMeter", ctypes.c_int32),
        ("biClrUsed", ctypes.c_uint32),
        ("biClrImportant", ctypes.c_uint32),
    ]


class _BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", _BITMAPINFOHEADER), ("bmiColors", ctypes.c_uint32 * 3)]


def _extract_png(source: Path) -> bytes:
    """exe/ico → 96px PNG 字节；任何一步失败返回 b""（调用方按"无图标"处理）。"""
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

    hicon = ctypes.c_void_p()
    icon_id = ctypes.c_uint32()
    user32.PrivateExtractIconsW.restype = ctypes.c_uint32
    user32.PrivateExtractIconsW.argtypes = [
        ctypes.c_wchar_p, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_uint32),
        ctypes.c_uint32, ctypes.c_uint32,
    ]
    count = user32.PrivateExtractIconsW(
        str(source), 0, _SIZE, _SIZE, ctypes.byref(hicon), ctypes.byref(icon_id), 1, 0
    )
    if not count or not hicon.value:
        return b""
    gdi32.DeleteObject.argtypes = [ctypes.c_void_p]
    user32.DestroyIcon.argtypes = [ctypes.c_void_p]
    try:
        info = _ICONINFO()
        user32.GetIconInfo.argtypes = [ctypes.c_void_p, ctypes.POINTER(_ICONINFO)]
        if not user32.GetIconInfo(hicon, ctypes.byref(info)) or not info.hbmColor:
            return b""
        try:
            bmp = _read_bitmap(gdi32, user32, ctypes.c_void_p(info.hbmColor))
        finally:
            gdi32.DeleteObject(ctypes.c_void_p(info.hbmColor))
            if info.hbmMask:
                gdi32.DeleteObject(ctypes.c_void_p(info.hbmMask))
        return _encode_png(*bmp) if bmp else b""
    finally:
        user32.DestroyIcon(hicon)


def _read_bitmap(gdi32, user32, hbm) -> tuple[int, int, bytes] | None:
    """HBITMAP → (width, height, RGBA bytes)；取不到维度/位数异常返回 None。"""
    class _BITMAP(ctypes.Structure):
        _fields_ = [
            ("bmType", ctypes.c_int32),
            ("bmWidth", ctypes.c_int32),
            ("bmHeight", ctypes.c_int32),
            ("bmWidthBytes", ctypes.c_int32),
            ("bmPlanes", ctypes.c_uint16),
            ("bmBitsPixel", ctypes.c_uint16),
            ("bmBits", ctypes.c_void_p),
        ]

    bm = _BITMAP()
    gdi32.GetObjectW.restype = ctypes.c_int
    gdi32.GetObjectW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
    if gdi32.GetObjectW(hbm, ctypes.sizeof(_BITMAP), ctypes.byref(bm)) != ctypes.sizeof(_BITMAP):
        return None
    width, height = int(bm.bmWidth), int(bm.bmHeight)
    if not width or not height or width > 1024 or height > 1024:
        return None

    dc = user32.GetDC(None)
    if not dc:
        return None
    try:
        bmi = _BITMAPINFO()
        bmi.bmiHeader.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = width
        bmi.bmiHeader.biHeight = -height  # 负高 = 自顶向下，省一次翻转
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = 0  # BI_RGB
        raw = (ctypes.c_ubyte * (width * height * 4))()
        gdi32.GetDIBits.restype = ctypes.c_int
        gdi32.GetDIBits.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32,
            ctypes.c_void_p, ctypes.POINTER(_BITMAPINFO), ctypes.c_uint32,
        ]
        if not gdi32.GetDIBits(dc, hbm, 0, height, raw, ctypes.byref(bmi), 0):
            return None
        pixels = bytes(raw)
    finally:
        user32.ReleaseDC(None, dc)

    # BGRA → RGBA；alpha 全 0 的老式图标（32bpp 但无 alpha 通道）按不透明处理
    has_alpha = any(pixels[i] for i in range(3, len(pixels), 4))
    out = bytearray(len(pixels))
    out[0::4] = pixels[2::4]
    out[1::4] = pixels[1::4]
    out[2::4] = pixels[0::4]
    out[3::4] = pixels[3::4] if has_alpha else b"\xff" * (width * height)
    return width, height, bytes(out)


def _encode_png(width: int, height: int, rgba: bytes) -> bytes:
    """手写 PNG（标准库 zlib）：8bit RGBA、无交错、filter 0。"""
    stride = width * 4
    raw = b"".join(b"\x00" + rgba[y * stride:(y + 1) * stride] for y in range(height))
    compressed = zlib.compress(raw, 9)
    if len(compressed) > _MAX_SIZE:
        return b""

    def chunk(tag: bytes, payload: bytes) -> bytes:
        body = tag + payload
        return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", compressed)
        + chunk(b"IEND", b"")
    )
