"""Точка входа PresenterOverlay (Суфлёр).

Запуск:  python -m presenter_overlay
"""

from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from .native import set_app_background
from .overlay import OverlayApp
from .state import AppState


def main() -> int:
    # QtWebEngine (веб-интерфейс) требует общего OpenGL-контекста —
    # атрибут нужно выставить ДО создания QApplication.
    try:
        QApplication.setAttribute(Qt.AA_ShareOpenGLContexts, True)
    except Exception:
        pass

    app = QApplication(sys.argv)
    app.setApplicationName("PresenterOverlay")
    # Не закрывать приложение, когда скрыта последняя панель —
    # кнопка-лаунчер остаётся на экране.
    app.setQuitOnLastWindowClosed(False)

    # macOS: фоновая утилита без иконки в Dock — оверлей остаётся поверх
    # и не прячется при переключении окон.
    set_app_background()

    state = AppState()
    state.refresh_audio_inputs()

    overlay = OverlayApp(state)
    overlay.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
