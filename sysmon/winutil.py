"""Windows-only helpers. Every function fails soft so the app still runs elsewhere."""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys

_IS_WINDOWS = sys.platform == "win32"


def is_admin() -> bool:
    if not _IS_WINDOWS:
        return hasattr(os, "geteuid") and os.geteuid() == 0
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return False


def relaunch_as_admin() -> bool:
    """Start a new elevated copy of this app (UAC prompt). Returns True if it was launched."""
    if not _IS_WINDOWS:
        return False
    if getattr(sys, "frozen", False):
        exe, args = sys.executable, subprocess.list2cmdline(sys.argv[1:])
    else:
        exe, args = sys.executable, subprocess.list2cmdline([os.path.abspath(sys.argv[0]), *sys.argv[1:]])
    try:
        # ShellExecuteW returns a value > 32 on success.
        return ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, args, None, 1) > 32
    except (AttributeError, OSError):
        return False


def set_dark_title_bar(hwnd: int, dark: bool) -> None:
    """Make the native title bar match the app theme (Windows 10 2004+ / 11)."""
    if not _IS_WINDOWS:
        return
    DWMWA_USE_IMMERSIVE_DARK_MODE = 20
    value = ctypes.c_int(1 if dark else 0)
    try:
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            ctypes.c_void_p(hwnd), DWMWA_USE_IMMERSIVE_DARK_MODE, ctypes.byref(value), ctypes.sizeof(value)
        )
    except (AttributeError, OSError):
        pass


def set_app_user_model_id(app_id: str) -> None:
    """Give the app its own taskbar group and icon instead of python.exe's."""
    if not _IS_WINDOWS:
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
    except (AttributeError, OSError):
        pass


def volume_label(root: str) -> str:
    """'C:\\' -> 'Windows' (empty string if unknown)."""
    if not _IS_WINDOWS:
        return ""
    buf = ctypes.create_unicode_buffer(261)
    try:
        ok = ctypes.windll.kernel32.GetVolumeInformationW(
            ctypes.c_wchar_p(root), buf, len(buf), None, None, None, None, 0
        )
    except (AttributeError, OSError):
        return ""
    return buf.value if ok else ""


def show_in_explorer(path: str) -> None:
    """Open Explorer with `path` selected (or opened, if it is a directory)."""
    try:
        if os.path.isdir(path):
            os.startfile(path)  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
    except OSError:
        pass
