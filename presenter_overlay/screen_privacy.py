"""Исключение окна из захвата экрана (записи/демонстрации).

Это главная фишка «Суфлёра»: панель видна тебе, но не попадает в запись экрана
и в демонстрацию через Zoom/Meet/QuickTime.

Реализация платформенная:
  - Windows: SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE)
  - macOS:   NSWindow.sharingType = NSWindowSharingNone (через pyobjc)
  - Linux:   надёжного системного аналога нет (X11/Wayland) — вернём предупреждение.

Функция принимает «winId» окна Qt (int) и возвращает (ok, message).
"""

from __future__ import annotations

import sys
from typing import Tuple

WDA_EXCLUDEFROMCAPTURE = 0x00000011  # Windows 10 2004+
WDA_MONITOR = 0x00000001              # запасной вариант для старых Windows


def exclude_from_capture(win_id: int) -> Tuple[bool, str]:
    if sys.platform.startswith("win"):
        return _windows(win_id)
    if sys.platform == "darwin":
        return _macos(win_id)
    return (
        False,
        "Linux: системного способа скрыть окно от захвата экрана нет. "
        "Окно будет видно в записи/демонстрации.",
    )


def _windows(win_id: int) -> Tuple[bool, str]:
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        user32.SetWindowDisplayAffinity.argtypes = [wintypes.HWND, wintypes.DWORD]
        user32.SetWindowDisplayAffinity.restype = wintypes.BOOL
        hwnd = wintypes.HWND(int(win_id))

        if user32.SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE):
            return True, "Окно исключено из захвата экрана (Windows)."
        # Старые версии Windows не знают EXCLUDEFROMCAPTURE
        if user32.SetWindowDisplayAffinity(hwnd, WDA_MONITOR):
            return True, "Окно скрыто от захвата (режим MONITOR, старая Windows)."
        return False, "SetWindowDisplayAffinity не сработала."
    except Exception as exc:  # noqa: BLE001
        return False, f"Windows: не удалось скрыть окно: {exc}"


def _macos(win_id: int) -> Tuple[bool, str]:
    try:
        import objc
        from AppKit import NSApp, NSWindowSharingNone

        # Qt winId() на macOS — это указатель на NSView. Поднимаемся к окну.
        view = objc.objc_object(c_void_p=int(win_id))
        window = view.window()
        if window is None:
            # запасной путь: пройтись по окнам приложения
            for w in NSApp().windows():
                w.setSharingType_(NSWindowSharingNone)
            return True, "macOS: sharingType=.none применён ко всем окнам."
        window.setSharingType_(NSWindowSharingNone)
        return True, "Окно исключено из захвата экрана (macOS, sharingType=.none)."
    except Exception as exc:  # noqa: BLE001
        return False, f"macOS: не удалось применить sharingType: {exc}"
