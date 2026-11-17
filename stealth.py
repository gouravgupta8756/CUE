"""stealth.py - Windows par window ko screen capture se exclude karta hai (SetWindowDisplayAffinity)."""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from typing import Any

WDA_NONE = 0x00
WDA_MONITOR = 0x01               # capture me window kaali dikhti hai (purane Windows ke liye)
WDA_EXCLUDEFROMCAPTURE = 0x11    # capture me window dikhti hi nahi (Win10 2004+)

_MIN_BUILD_EXCLUDE = 19041       # Windows 10 version 2004
_IS_WINDOWS = sys.platform == "win32"


def is_supported() -> bool:
    """True agar yahan WDA_EXCLUDEFROMCAPTURE chal sakta hai (Windows 10 build 19041+)."""
    return _IS_WINDOWS and sys.getwindowsversion().build >= _MIN_BUILD_EXCLUDE  # type: ignore[attr-defined]


def _user32() -> Any:
    """user32.dll load karta hai aur zaroori function signatures set karta hai."""
    user32 = ctypes.WinDLL("user32", use_last_error=True)  # type: ignore[attr-defined]
    user32.SetWindowDisplayAffinity.argtypes = [wintypes.HWND, wintypes.DWORD]
    user32.SetWindowDisplayAffinity.restype = wintypes.BOOL
    user32.GetWindowDisplayAffinity.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowDisplayAffinity.restype = wintypes.BOOL
    return user32


def _set_affinity(hwnd: int, affinity: int) -> str | None:
    """Affinity set karta hai. Success par None, warna error message."""
    user32 = _user32()
    if user32.SetWindowDisplayAffinity(hwnd, affinity):
        return None
    err = ctypes.get_last_error()  # type: ignore[attr-defined]
    detail = ctypes.FormatError(err).strip()  # type: ignore[attr-defined]
    return f"SetWindowDisplayAffinity fail hua (WinError {err}: {detail})"


def get_affinity(hwnd: int) -> int | None:
    """Window ki current display affinity padhta hai (verify karne ke liye). Non-Windows par None."""
    if not _IS_WINDOWS or not hwnd:
        return None
    value = wintypes.DWORD(0)
    if _user32().GetWindowDisplayAffinity(hwnd, ctypes.byref(value)):
        return int(value.value)
    return None


def exclude_from_capture(hwnd: int, fallback_monitor: bool = False) -> str | None:
    """Window ko screenshot/screen-share/recording se hide karta hai.

    Returns:
        None agar lag gaya, warna warning string.
        macOS/Linux par kuch nahi karta (safe no-op) aur warning deta hai.

    fallback_monitor: purane Windows (build < 19041) par WDA_MONITOR lagata hai,
    jisme window capture me gayab ki jagah kaali dikhti hai.
    """
    if not _IS_WINDOWS:
        return f"stealth: {sys.platform} par supported nahi (sirf Windows 10 2004+). No-op."
    if not hwnd:
        return "stealth: invalid hwnd (0). Window show hone ke baad call karo."

    if not is_supported():
        build = sys.getwindowsversion().build  # type: ignore[attr-defined]
        if fallback_monitor:
            err = _set_affinity(hwnd, WDA_MONITOR)
            return err or f"stealth: Windows build {build} purana hai, WDA_MONITOR lagaya (capture me window kaali dikhegi)."
        return f"stealth: Windows build {build} par WDA_EXCLUDEFROMCAPTURE nahi chalta (build 19041+ chahiye)."

    return _set_affinity(hwnd, WDA_EXCLUDEFROMCAPTURE)


def include_in_capture(hwnd: int) -> str | None:
    """Exclusion hata deta hai (settings me toggle ke liye). Success par None."""
    if not _IS_WINDOWS:
        return f"stealth: {sys.platform} par supported nahi. No-op."
    if not hwnd:
        return "stealth: invalid hwnd (0)."
    return _set_affinity(hwnd, WDA_NONE)


def exclude_widget_from_capture(widget: Any, **kwargs: Any) -> str | None:
    """Qt widget (QWidget) ke liye shortcut: winId() se hwnd nikal kar exclude_from_capture chalata hai.

    Widget .show() ho chuka hona chahiye, warna native window handle nahi banta.
    """
    try:
        hwnd = int(widget.winId())
    except Exception as exc:  # noqa: BLE001
        return f"stealth: widget se hwnd nahi mila ({exc})"
    return exclude_from_capture(hwnd, **kwargs)


if __name__ == "__main__":
    from PyQt6.QtCore import QTimer, Qt
    from PyQt6.QtWidgets import QApplication, QLabel

    app = QApplication(sys.argv)
    win = QLabel("CUE stealth test\n\nWin+Shift+S ya Snipping Tool se screenshot lo.\nYe window capture me nahi dikhni chahiye.")
    win.setAlignment(Qt.AlignmentFlag.AlignCenter)
    win.setWindowFlags(
        Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
    )
    win.setStyleSheet("background:#1e1e2e; color:#cdd6f4; font-size:14px; padding:16px;")
    win.resize(460, 180)
    win.show()

    def apply() -> None:
        """Show ke baad affinity lagata hai aur read-back se verify karta hai."""
        warning = exclude_widget_from_capture(win)
        if warning:
            print("WARNING:", warning)
        else:
            affinity = get_affinity(int(win.winId()))
            ok = affinity == WDA_EXCLUDEFROMCAPTURE
            print(f"Lag gaya. affinity={affinity and hex(affinity)} verified={ok}")
        print("45 sec me auto-exit. Ab screenshot/screen-share karke check karo.")

    QTimer.singleShot(300, apply)
    QTimer.singleShot(45_000, app.quit)
    sys.exit(app.exec()) 