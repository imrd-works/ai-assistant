"""Глобальные горячие клавиши (работают, даже когда окно не в фокусе).

Используется pynput. На macOS требуется разрешение
System Settings → Privacy & Security → Accessibility для приложения/терминала,
из которого запущен оверлей — иначе системные хоткеи не будут приходить.

Сочетания хранятся в «портативном» виде Qt (например, "Ctrl+Alt+M") и
переводятся в формат pynput ("<ctrl>+<alt>+m") при запуске слушателя.
"""

from __future__ import annotations

from typing import Callable, Dict, Tuple

try:
    from pynput import keyboard
except Exception as exc:  # noqa: BLE001 — библиотека может быть не установлена
    keyboard = None
    _IMPORT_ERROR = exc
else:
    _IMPORT_ERROR = None


_MODIFIERS = {
    "ctrl": "<ctrl>", "control": "<ctrl>",
    "alt": "<alt>", "option": "<alt>", "opt": "<alt>",
    "shift": "<shift>",
    "meta": "<cmd>", "cmd": "<cmd>", "command": "<cmd>",
    "super": "<cmd>", "win": "<cmd>",
}

_SPECIAL = {
    "space": "<space>", "return": "<enter>", "enter": "<enter>",
    "esc": "<esc>", "escape": "<esc>", "tab": "<tab>",
    "backspace": "<backspace>", "delete": "<delete>", "del": "<delete>",
    "up": "<up>", "down": "<down>", "left": "<left>", "right": "<right>",
    "home": "<home>", "end": "<end>", "pageup": "<page_up>", "pagedown": "<page_down>",
}


def qt_to_pynput(seq_str: str) -> str:
    """'Ctrl+Alt+M' → '<ctrl>+<alt>+m'. Пустая строка → ''."""
    seq_str = (seq_str or "").strip()
    if not seq_str:
        return ""
    out = []
    for part in seq_str.split("+"):
        key = part.strip().lower()
        if not key:
            continue
        if key in _MODIFIERS:
            out.append(_MODIFIERS[key])
        elif key in _SPECIAL:
            out.append(_SPECIAL[key])
        elif key.startswith("f") and key[1:].isdigit():
            out.append(f"<{key}>")
        elif len(key) == 1:
            out.append(key)
        else:
            out.append(key)
    return "+".join(out)


class HotkeyManager:
    """Слушает глобальные сочетания и вызывает колбэки (в своём потоке pynput!).

    Колбэки должны быть потокобезопасными — например, эмитить сигнал Qt.
    """

    def __init__(self) -> None:
        self._listener = None

    @staticmethod
    def is_available() -> bool:
        return keyboard is not None

    @staticmethod
    def unavailable_reason() -> str:
        if keyboard is not None:
            return ""
        return f"pynput не установлен (pip install pynput). Детали: {_IMPORT_ERROR}"

    def apply(self, bindings: Dict[str, Callable[[], None]]) -> Tuple[bool, str]:
        """bindings: {'Ctrl+Alt+M': callback, ...} в портативном виде Qt."""
        self.stop()
        if keyboard is None:
            return False, self.unavailable_reason()

        mapping: Dict[str, Callable[[], None]] = {}
        for qt_combo, cb in bindings.items():
            combo = qt_to_pynput(qt_combo)
            if combo:
                mapping[combo] = cb
        if not mapping:
            return False, "нет назначенных сочетаний"

        try:
            self._listener = keyboard.GlobalHotKeys(mapping)
            self._listener.daemon = True
            self._listener.start()
            return True, ""
        except Exception as exc:  # noqa: BLE001
            self._listener = None
            return False, f"не удалось запустить хоткеи: {exc}"

    def stop(self) -> None:
        if self._listener is not None:
            try:
                self._listener.stop()
            except Exception:
                pass
            self._listener = None
