# -*- coding: utf-8 -*-
"""
用 Windows DPAPI 加密 API Key（仅 Windows）。

DPAPI 的密钥由 Windows 管理，绑定当前用户和这台电脑：
    - 只拷贝 settings.json 到别的电脑 / 别的 Windows 账号，解不开；
    - 同一个 Windows 账号下的程序仍然可以解密（防的是文件被看到 / 被同步 / 被备份）。
非 Windows 平台，或者 DPAPI 调用失败时，返回 None，由调用方退回明文保存。
"""

from __future__ import annotations

import base64
import ctypes
import sys
from typing import Optional

IS_WINDOWS = sys.platform.startswith("win")
_CRYPTPROTECT_UI_FORBIDDEN = 0x1

if IS_WINDOWS:
    from ctypes import wintypes

    class _DataBlob(ctypes.Structure):
        _fields_ = [
            ("cbData", wintypes.DWORD),
            ("pbData", ctypes.POINTER(ctypes.c_char)),
        ]

    try:
        _crypt32 = ctypes.windll.crypt32
        _kernel32 = ctypes.windll.kernel32
        _crypt32.CryptProtectData.argtypes = [
            ctypes.POINTER(_DataBlob),
            wintypes.LPCWSTR,
            ctypes.POINTER(_DataBlob),
            ctypes.c_void_p,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(_DataBlob),
        ]
        _crypt32.CryptProtectData.restype = wintypes.BOOL
        _crypt32.CryptUnprotectData.argtypes = [
            ctypes.POINTER(_DataBlob),
            ctypes.POINTER(wintypes.LPWSTR),
            ctypes.POINTER(_DataBlob),
            ctypes.c_void_p,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(_DataBlob),
        ]
        _crypt32.CryptUnprotectData.restype = wintypes.BOOL
        _kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        _kernel32.LocalFree.restype = ctypes.c_void_p
    except Exception:  # noqa: BLE001 - 老系统 / 受限环境里不要拖垮桌宠
        _crypt32 = None
        _kernel32 = None
else:
    _DataBlob = None
    _crypt32 = None
    _kernel32 = None


def _make_blob(data: bytes):
    buffer = ctypes.create_string_buffer(data, len(data))
    blob = _DataBlob(
        len(data),
        ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)),
    )
    return blob, buffer


def _read_blob(blob) -> bytes:
    if not blob.pbData or not blob.cbData:
        return b""
    try:
        return ctypes.string_at(blob.pbData, blob.cbData)
    finally:
        _kernel32.LocalFree(blob.pbData)


def available() -> bool:
    return bool(IS_WINDOWS and _crypt32 is not None)


def protect(secret: str) -> Optional[str]:
    """把明文加密成 base64 字符串；失败返回 None。"""
    if not available() or not secret:
        return None
    try:
        data = secret.encode("utf-8")
        in_blob, keep_alive = _make_blob(data)
        out_blob = _DataBlob()
        ok = _crypt32.CryptProtectData(
            ctypes.byref(in_blob),
            "DeepSeekWhalePet API key",
            None,
            None,
            None,
            _CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.byref(out_blob),
        )
        del keep_alive
        if not ok:
            return None
        encrypted = _read_blob(out_blob)
        if not encrypted:
            return None
        return base64.b64encode(encrypted).decode("ascii")
    except Exception:  # noqa: BLE001
        return None


def unprotect(token: str) -> Optional[str]:
    """把 base64 密文解回明文；不是这台电脑/这个用户加密的会返回 None。"""
    if not available() or not token:
        return None
    try:
        encrypted = base64.b64decode(token.encode("ascii"), validate=True)
        in_blob, keep_alive = _make_blob(encrypted)
        out_blob = _DataBlob()
        ok = _crypt32.CryptUnprotectData(
            ctypes.byref(in_blob),
            None,
            None,
            None,
            None,
            _CRYPTPROTECT_UI_FORBIDDEN,
            ctypes.byref(out_blob),
        )
        del keep_alive
        if not ok:
            return None
        clear = _read_blob(out_blob)
        if not clear:
            return None
        return clear.decode("utf-8")
    except Exception:  # noqa: BLE001
        return None


__all__ = ["available", "protect", "unprotect"]
