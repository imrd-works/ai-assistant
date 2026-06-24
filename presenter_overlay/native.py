"""Нативные эффекты окна по платформам.

- glass-фон (реальное размытие позади окна, как «frosted glass» в iOS/macOS):
    macOS   → NSVisualEffectView (blendingMode = behindWindow)
    Windows → DWM acrylic (SetWindowCompositionAttribute)
    Linux   → нет системного API (используется нарисованный стеклянный фолбэк)
- always-on-top поверх всех окон, включая полноэкранные презентации:
    macOS   → NSWindow.level = floating + collectionBehavior (все Spaces, fullscreen)
    Windows → SetWindowPos(HWND_TOPMOST)

Все функции принимают Qt winId() (int) и не падают, если эффект недоступен.
"""

from __future__ import annotations

import sys
from typing import Tuple


# ----------------------------------------------------------------------------
# Glass-фон
# ----------------------------------------------------------------------------

def apply_glass(win_id: int, radius: int = 16) -> Tuple[bool, str]:
    if sys.platform == "darwin":
        # На macOS НЕ вставляем NSVisualEffectView поверх Qt-контента — он
        # перекрывает кнопки. Стеклянный вид даёт нарисованный фон (paintEvent),
        # который всегда находится ПОЗАДИ виджетов. Здесь только делаем само
        # окно прозрачным, чтобы скругление и полупрозрачность работали корректно.
        return _macos_transparent(win_id)
    if sys.platform.startswith("win"):
        return _windows_acrylic(win_id)
    return False, "linux-painted"


def _macos_transparent(win_id: int) -> Tuple[bool, str]:
    try:
        import objc
        from AppKit import NSColor

        view = objc.objc_object(c_void_p=int(win_id))
        window = view.window()
        if window is None:
            return False, "no NSWindow"
        window.setOpaque_(False)
        window.setBackgroundColor_(NSColor.clearColor())
        window.setHasShadow_(True)
        # Не прятать окно, когда приложение теряет фокус (переключение окон).
        window.setHidesOnDeactivate_(False)
        return True, "macos-painted-glass"
    except Exception as exc:  # noqa: BLE001
        return False, f"macos transparent error: {exc}"


def set_app_background() -> Tuple[bool, str]:
    """macOS: сделать приложение фоновой утилитой (без иконки в Dock).

    В таком режиме панель-оверлей не прячется при переключении между окнами
    других приложений и не «крадёт» фокус. Вызывать один раз после старта Qt.
    """
    if sys.platform != "darwin":
        return False, "n/a"
    try:
        from AppKit import NSApp

        app = NSApp()
        if app is None:
            return False, "no NSApp"
        # NSApplicationActivationPolicyAccessory = 1
        app.setActivationPolicy_(1)
        return True, "accessory"
    except Exception as exc:  # noqa: BLE001
        return False, f"accessory policy error: {exc}"


def _windows_acrylic(win_id: int) -> Tuple[bool, str]:
    try:
        import ctypes
        from ctypes import wintypes

        class ACCENTPOLICY(ctypes.Structure):
            _fields_ = [
                ("AccentState", ctypes.c_int),
                ("AccentFlags", ctypes.c_int),
                ("GradientColor", ctypes.c_uint),
                ("AnimationId", ctypes.c_int),
            ]

        class WINCOMPATTRDATA(ctypes.Structure):
            _fields_ = [
                ("Attribute", ctypes.c_int),
                ("Data", ctypes.POINTER(ACCENTPOLICY)),
                ("SizeOfData", ctypes.c_size_t),
            ]

        ACCENT_ENABLE_ACRYLICBLURBEHIND = 4
        WCA_ACCENT_POLICY = 19
        # Цвет в формате 0xAABBGGRR — лёгкая светлая подложка под стеклом
        # (под светлую «liquid glass» тему). RGB ≈ (250,251,253).
        tint = 0x99FDFBFA

        accent = ACCENTPOLICY(ACCENT_ENABLE_ACRYLICBLURBEHIND, 0, tint, 0)
        data = WINCOMPATTRDATA(
            WCA_ACCENT_POLICY, ctypes.pointer(accent), ctypes.sizeof(accent)
        )
        set_attr = ctypes.windll.user32.SetWindowCompositionAttribute
        set_attr.argtypes = [wintypes.HWND, ctypes.POINTER(WINCOMPATTRDATA)]
        set_attr.restype = wintypes.BOOL
        ok = set_attr(wintypes.HWND(int(win_id)), ctypes.pointer(data))
        return bool(ok), "windows-acrylic"
    except Exception as exc:  # noqa: BLE001
        return False, f"windows acrylic error: {exc}"


# ----------------------------------------------------------------------------
# Always-on-top (поверх всех окон и полноэкранных приложений)
# ----------------------------------------------------------------------------

def keep_above(win_id: int) -> Tuple[bool, str]:
    if sys.platform == "darwin":
        return _macos_keep_above(win_id)
    if sys.platform.startswith("win"):
        return _windows_topmost(win_id)
    return False, "linux"


def _macos_keep_above(win_id: int) -> Tuple[bool, str]:
    try:
        import objc

        view = objc.objc_object(c_void_p=int(win_id))
        window = view.window()
        if window is None:
            return False, "no NSWindow"

        NS_FLOATING_LEVEL = 3
        CAN_JOIN_ALL_SPACES = 1 << 0
        STATIONARY = 1 << 4
        FULLSCREEN_AUXILIARY = 1 << 8

        window.setLevel_(NS_FLOATING_LEVEL)
        window.setCollectionBehavior_(
            CAN_JOIN_ALL_SPACES | STATIONARY | FULLSCREEN_AUXILIARY
        )
        # Не прятать окно, когда приложение неактивно — иначе лаунчер/панель
        # исчезают при переключении на другое приложение.
        window.setHidesOnDeactivate_(False)
        return True, "macos-floating"
    except Exception as exc:  # noqa: BLE001
        return False, f"macos keep-above error: {exc}"


def macos_accessibility_trusted(prompt: bool = False) -> bool:
    """macOS: доверен ли текущий процесс для мониторинга ввода (хоткеи).

    Если prompt=True и доверия нет — система покажет диалог и добавит ИМЕННО
    этот процесс (а не другое приложение) в список «Универсальный доступ».
    На не-macOS всегда True.
    """
    if sys.platform != "darwin":
        return True
    try:
        from ApplicationServices import AXIsProcessTrustedWithOptions

        return bool(
            AXIsProcessTrustedWithOptions({"AXTrustedCheckOptionPrompt": bool(prompt)})
        )
    except Exception:
        try:
            from ApplicationServices import AXIsProcessTrusted

            return bool(AXIsProcessTrusted())
        except Exception:
            return True  # не смогли проверить — не блокируем


def macos_screen_recording_trusted(prompt: bool = False) -> bool:
    """macOS: есть ли доступ к «Записи экрана» (нужен для скриншота).

    Без него снимок будет чёрным. Если prompt=True и доступа нет — система
    покажет запрос и добавит процесс в список «Запись экрана» (применится после
    перезапуска). На не-macOS всегда True.
    """
    if sys.platform != "darwin":
        return True
    try:
        import Quartz

        ok = bool(Quartz.CGPreflightScreenCaptureAccess())
        if not ok and prompt:
            try:
                Quartz.CGRequestScreenCaptureAccess()
            except Exception:
                pass
        return ok
    except Exception:
        return True  # не смогли проверить — не блокируем


def _windows_topmost(win_id: int) -> Tuple[bool, str]:
    try:
        import ctypes
        from ctypes import wintypes

        HWND_TOPMOST = -1
        SWP_NOMOVE = 0x0002
        SWP_NOSIZE = 0x0001
        SWP_NOACTIVATE = 0x0010

        user32 = ctypes.windll.user32
        user32.SetWindowPos.argtypes = [
            wintypes.HWND, wintypes.HWND,
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            wintypes.UINT,
        ]
        ok = user32.SetWindowPos(
            wintypes.HWND(int(win_id)), wintypes.HWND(HWND_TOPMOST),
            0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE,
        )
        return bool(ok), "windows-topmost"
    except Exception as exc:  # noqa: BLE001
        return False, f"windows topmost error: {exc}"
