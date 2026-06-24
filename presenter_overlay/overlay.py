"""GUI оверлея на PySide6 (аналог ChatView + контроллеров окон).

Полупрозрачная безрамочная панель поверх всех окон + маленькая круглая
кнопка-лаунчер. Оба окна по возможности исключаются из захвата экрана.
Распознанные слова сразу появляются в поле ввода (state.draft_changed).
"""

from __future__ import annotations

import html as _html
import re

from PySide6.QtCore import QEvent, Qt, QPoint, QPointF, QRect, QRectF, QSize, QTimer
from PySide6.QtGui import (
    QAction,
    QColor,
    QFont,
    QKeySequence,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QKeySequenceEdit,
    QLabel,
    QLineEdit,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from . import audio, screenshot
from .config import AUDIO_MODELS, DEFAULT_API_KEY, VISION_MODELS
from .hotkeys import HotkeyManager
from .native import apply_glass, keep_above, macos_accessibility_trusted
from .screen_privacy import exclude_from_capture
from .state import AppState

PANEL_RADIUS = 22

# Светлая «liquid glass» тема (как в макете Суфлёр standalone):
#   акцент  #2f6bff,  активный микрофон  #18a558,  опасное действие  #c63a2e.
# Подложка панели рисуется в _paint_glass(); QSS оформляет контролы.
PANEL_QSS = """
QWidget#panel {
    background: transparent;   /* стеклянный фон рисуется в paintEvent + нативно */
}
QLabel { color: #3a4250; }
QLabel#title { color: #26242e; font-weight: 600; }
QLabel#sectionLabel { color: #3a4250; font-weight: 600; }
QLabel#dragHandle {
    color: #3a4250; font-weight: 600; padding: 4px 8px;
    border-radius: 8px; background: transparent;
}
QLabel#dragHandle:hover { background: rgba(20,24,32,18); color: #20242e; }
QLabel#caption { color: #8a909c; }

/* Иконочные кнопки в шапке (шестерёнка и т.п.) */
QPushButton#icon {
    background: rgba(255,255,255,150); color: #5b6472;
    border: 1px solid rgba(20,24,32,18);
    padding: 5px 9px; border-radius: 10px; font-size: 14px;
}
QPushButton#icon:hover { background: rgba(255,255,255,220); color: #20242e; }

/* Микрофон-чип в шапке (зелёный, когда слушает) */
QPushButton#micChip {
    background: rgba(20,24,32,16); color: #7b8290;
    border: none; border-radius: 14px; padding: 5px 12px; font-weight: 600;
}
QPushButton#micChip:hover { background: rgba(20,24,32,26); }
QPushButton#micChip[active="true"] {
    background: rgba(24,165,88,38); color: #0f7a40;
}

/* Круглые кнопки composer'а (скриншот / отправка) */
QPushButton#send {
    background: #2f6bff; color: #fff; border: none;
    border-radius: 13px; padding: 8px 12px; font-size: 16px;
}
QPushButton#send:hover { background: #2860f0; }
QPushButton#send:disabled { background: rgba(20,24,32,28); color: #aab; }
QPushButton#ghost {
    background: rgba(255,255,255,150); color: #3a4250;
    border: 1px solid rgba(20,24,32,20); border-radius: 13px;
    padding: 8px 12px; font-size: 16px;
}
QPushButton#ghost:hover { background: rgba(255,255,255,225); color: #20242e; }

/* Чипы-подсказки (Подробнее / Ещё вариант) */
QPushButton#chip {
    background: rgba(255,255,255,150); color: #4a5260;
    border: 1px solid rgba(20,24,32,20); border-radius: 14px;
    padding: 6px 13px; font-weight: 600;
}
QPushButton#chip:hover { background: rgba(255,255,255,225); color: #20242e; }
QPushButton#chip:disabled { color: #b3b8c2; background: rgba(255,255,255,90); }

QPushButton#primary {
    background: #2f6bff; color: #fff; border: none;
    border-radius: 10px; padding: 8px 16px; font-weight: 600;
}
QPushButton#primary:hover { background: #2860f0; }
QPushButton#flat {
    background: rgba(255,255,255,150); color: #4a5260;
    border: 1px solid rgba(20,24,32,20);
    border-radius: 10px; padding: 7px 14px; font-weight: 600;
}
QPushButton#flat:hover { background: rgba(255,255,255,225); color: #20242e; }

/* Вкладки настроек */
QPushButton#tab {
    background: transparent; color: #8a909c; border: none;
    border-radius: 9px; padding: 7px 12px; font-weight: 600;
}
QPushButton#tab:hover { color: #4a5260; }
QPushButton#tab[active="true"] {
    color: #2f6bff; background: rgba(47,107,255,22);
}

QPushButton#quit {
    background: rgba(220,72,60,26); color: #c63a2e;
    border: 1px solid rgba(220,72,60,76);
    border-radius: 12px; padding: 10px 14px; font-weight: 600;
}
QPushButton#quit:hover { background: rgba(220,72,60,55); color: #a32a20; }

QPlainTextEdit, QLineEdit, QComboBox {
    background: rgba(255,255,255,160); color: #20242e;
    border: 1px solid rgba(20,24,32,24); border-radius: 11px; padding: 7px;
    selection-background-color: rgba(47,107,255,120);
    selection-color: #fff;
}
QPlainTextEdit:focus, QLineEdit:focus, QComboBox:focus {
    border: 1px solid rgba(47,107,255,150);
}
QComboBox::drop-down { border: none; width: 22px; }
QComboBox QAbstractItemView {
    background: #ffffff; color: #20242e; border: 1px solid rgba(20,24,32,30);
    selection-background-color: rgba(47,107,255,150); selection-color: #fff;
    outline: none;
}
QKeySequenceEdit QLineEdit { background: rgba(255,255,255,160); }

/* Тумблеры-переключатели (auto-answer и т.п.) */
QCheckBox { color: #3a4250; spacing: 10px; }
QCheckBox::indicator {
    width: 40px; height: 22px; border-radius: 11px;
    background: rgba(20,24,32,40); border: none;
}
QCheckBox::indicator:checked { background: #2f6bff; }

QSlider::groove:horizontal {
    height: 4px; border-radius: 2px; background: rgba(20,24,32,30);
}
QSlider::sub-page:horizontal { background: #2f6bff; border-radius: 2px; }
QSlider::handle:horizontal {
    width: 16px; height: 16px; margin: -6px 0; border-radius: 8px;
    background: #ffffff; border: 1px solid rgba(20,24,32,40);
}

QScrollArea { border: none; background: transparent; }
QWidget#msgContainer { background: transparent; }
QWidget#tabPage { background: transparent; }
QFrame#transcriptBar {
    background: rgba(255,255,255,120); border: 1px solid rgba(20,24,32,16);
    border-radius: 12px;
}
QFrame#divider { border: none; background: rgba(20,24,32,16); }
"""


class DragMixin:
    """Свободное перетаскивание безрамочного окна за любую неинтерактивную точку.

    Кнопки/поля ввода/список сообщений обрабатывают мышь сами, а клики по фону,
    шапке, рамке и пустым областям двигают всё окно.
    """

    def _init_drag(self):
        self._drag_pos = None

    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.LeftButton:
            # Сначала пробуем системное перетаскивание — на macOS/Windows/Wayland
            # оно надёжнее ручного move() для безрамочных окон.
            handle = self.windowHandle()
            if handle is not None and getattr(self, "_use_system_move", True):
                try:
                    if handle.startSystemMove():
                        event.accept()
                        return
                except Exception:
                    pass
            # Фолбэк: ручное перетаскивание
            self._drag_pos = (
                event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            )
            event.accept()

    def mouseMoveEvent(self, event):  # noqa: N802
        if self._drag_pos is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event):  # noqa: N802
        self._drag_pos = None


class DragHandle(QLabel):
    """Явная «ручка» для перетаскивания окна (надёжнее системного move).

    Двигает верхнеуровневое окно вручную, поэтому работает на любой платформе
    независимо от поведения startSystemMove.
    """

    def __init__(self, text: str):
        super().__init__(text)
        self._offset = None
        self.setObjectName("dragHandle")
        self.setAlignment(Qt.AlignCenter)
        self.setCursor(Qt.OpenHandCursor)
        self.setToolTip("Тяни, чтобы переместить окно")

    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.LeftButton:
            win = self.window()
            self._offset = event.globalPosition().toPoint() - win.frameGeometry().topLeft()
            self.setCursor(Qt.ClosedHandCursor)
            event.accept()

    def mouseMoveEvent(self, event):  # noqa: N802
        if self._offset is not None and event.buttons() & Qt.LeftButton:
            self.window().move(event.globalPosition().toPoint() - self._offset)
            event.accept()

    def mouseReleaseEvent(self, event):  # noqa: N802
        self._offset = None
        self.setCursor(Qt.OpenHandCursor)


class RegionSelector(QWidget):
    """Полупрозрачный полноэкранный слой для выделения области скриншота мышью."""

    def __init__(self, on_done):
        super().__init__()
        self.on_done = on_done
        self._start = None
        self._end = None
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setCursor(Qt.CrossCursor)
        scr = QApplication.primaryScreen().geometry()
        self.setGeometry(scr)

    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        self.raise_()
        self.activateWindow()
        self.grabKeyboard()
        try:
            exclude_from_capture(int(self.winId()))
        except Exception:
            pass

    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.LeftButton:
            self._start = event.position().toPoint()
            self._end = self._start
            self.update()

    def mouseMoveEvent(self, event):  # noqa: N802
        if self._start is not None:
            self._end = event.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, event):  # noqa: N802
        if event.button() == Qt.LeftButton and self._start is not None:
            rect = QRect(self._start, self._end).normalized()
            self.releaseKeyboard()
            self.close()
            if rect.width() > 5 and rect.height() > 5:
                tl = self.mapToGlobal(rect.topLeft())
                self.on_done({"x": tl.x(), "y": tl.y(), "w": rect.width(), "h": rect.height()})
            else:
                self.on_done(None)

    def keyPressEvent(self, event):  # noqa: N802
        if event.key() == Qt.Key_Escape:
            self.releaseKeyboard()
            self.close()
            self.on_done(None)

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor(0, 0, 0, 110))
        if self._start is not None and self._end is not None:
            rect = QRect(self._start, self._end).normalized()
            p.setCompositionMode(QPainter.CompositionMode_Clear)
            p.fillRect(rect, QColor(0, 0, 0, 0))
            p.setCompositionMode(QPainter.CompositionMode_SourceOver)
            pen = QPen(QColor(0, 200, 255, 235))
            pen.setWidth(2)
            p.setPen(pen)
            p.drawRect(rect)
        p.setPen(QColor(255, 255, 255, 230))
        p.drawText(
            self.rect().adjusted(0, 24, 0, 0),
            Qt.AlignHCenter | Qt.AlignTop,
            "Выдели область скриншота мышью  ·  Esc — отмена",
        )
        p.end()


class RegionFrame(QWidget):
    """Тонкая click-through рамка, показывающая выбранную область скриншота."""

    MARGIN = 4

    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
            | Qt.WindowTransparentForInput | Qt.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)

    def set_region(self, region):
        if not region:
            self.hide()
            return
        m = self.MARGIN
        self.setGeometry(
            int(region["x"]) - m, int(region["y"]) - m,
            int(region["w"]) + 2 * m, int(region["h"]) + 2 * m,
        )
        self.show()
        self.raise_()
        try:
            exclude_from_capture(int(self.winId()))
            keep_above(int(self.winId()))
        except Exception:
            pass

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        pen = QPen(QColor(0, 200, 255, 235))
        pen.setWidth(2)
        p.setPen(pen)
        r = self.rect().adjusted(1, 1, -2, -2)
        p.drawRoundedRect(r, 6, 6)
        p.setPen(QColor(0, 200, 255, 235))
        p.drawText(r.adjusted(4, 2, 0, 0), Qt.AlignTop | Qt.AlignLeft, "📷 область")
        p.end()


def _paint_glass(widget, radius: int, solid: bool = False, opacity: int = 75) -> None:
    """Рисует светлую «liquid glass» подложку панели. solid=True — почти
    непрозрачный светлый фон (режим настроек, чтобы текст читался); иначе —
    матовое стекло с регулируемой плотностью (opacity 25..100 %), чтобы ответы
    были видны на любом фоне рабочего стола."""
    painter = QPainter(widget)
    painter.setRenderHint(QPainter.Antialiasing)
    rect = QRectF(widget.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)

    if solid:
        painter.fillPath(path, QColor(248, 249, 251, 252))
        # Внутренний верхний блик (как глянец стекла)
        highlight = QLinearGradient(rect.topLeft(), QPointF(rect.left(), rect.top() + 70))
        highlight.setColorAt(0.0, QColor(255, 255, 255, 200))
        highlight.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.fillPath(path, highlight)
        pen = QPen(QColor(255, 255, 255, 180))
        pen.setWidthF(1.0)
        painter.setPen(pen)
        painter.drawPath(path)
        painter.end()
        return

    # Плотность фона: 25..100 % → альфа 150..250
    o = max(25, min(100, int(opacity)))
    a = int(150 + (o - 25) / 75.0 * (250 - 150))

    # Светлый вертикальный градиент — сверху чуть светлее
    grad = QLinearGradient(rect.topLeft(), rect.bottomLeft())
    grad.setColorAt(0.0, QColor(252, 253, 255, min(255, a + 6)))
    grad.setColorAt(0.45, QColor(250, 251, 253, a))
    grad.setColorAt(1.0, QColor(243, 245, 249, min(255, a + 8)))
    painter.fillPath(path, grad)

    # Верхний световой блик
    highlight = QLinearGradient(rect.topLeft(), QPointF(rect.left(), rect.top() + 70))
    highlight.setColorAt(0.0, QColor(255, 255, 255, 200))
    highlight.setColorAt(1.0, QColor(255, 255, 255, 0))
    painter.fillPath(path, highlight)

    # Тонкая светлая рамка
    pen = QPen(QColor(255, 255, 255, 190))
    pen.setWidthF(1.0)
    painter.setPen(pen)
    painter.drawPath(path)
    painter.end()


class ToggleSwitch(QCheckBox):
    """Чекбокс в виде iOS-тумблера: подпись слева, переключатель справа.

    Наследует QCheckBox, поэтому isChecked()/setChecked() работают как прежде —
    остальной код (сохранение настроек) не меняется.
    """

    _TW = 42
    _TH = 24

    def __init__(self, text: str = ""):
        super().__init__(text)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(30)

    def sizeHint(self):  # noqa: N802
        base = super().sizeHint()
        return QSize(max(base.width() + self._TW + 16, 240), max(base.height(), 30))

    def hitButton(self, pos):  # noqa: N802
        return self.rect().contains(pos)

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        tw, th = self._TW, self._TH
        tx = self.width() - tw
        ty = (self.height() - th) // 2
        on = self.isChecked()

        # Подпись слева
        p.setPen(QColor(58, 66, 80))
        text_rect = self.rect().adjusted(0, 0, -(tw + 12), 0)
        p.drawText(
            text_rect,
            Qt.AlignLeft | Qt.AlignVCenter | Qt.TextWordWrap,
            self.text(),
        )

        # Дорожка
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(47, 107, 255) if on else QColor(20, 24, 32, 40))
        p.drawRoundedRect(QRectF(tx, ty, tw, th), th / 2, th / 2)

        # Бегунок
        d = th - 4
        kx = tx + (tw - d - 2) if on else tx + 2
        p.setBrush(QColor(255, 255, 255))
        p.drawEllipse(QRectF(kx, ty + 2, d, d))
        p.end()


class ChatPanel(QWidget, DragMixin):
    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        self._init_drag()
        self._show_settings = False
        self._privacy_applied = False
        self._status_text = "Слушаю…"
        self.on_quit = None           # задаётся из OverlayApp
        self.on_settings_saved = None  # переназначение хоткеев из OverlayApp
        self.on_screenshot = None      # снимок экрана из OverlayApp
        self.on_select_region = None   # выделить область скриншота
        self.on_clear_region = None    # сбросить область (весь экран)

        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setObjectName("panel")
        self.setStyleSheet(PANEL_QSS)
        self.resize(500, 560)

        self._build_ui()
        self._connect_state()

    def paintEvent(self, event):  # noqa: N802
        _paint_glass(
            self, PANEL_RADIUS, solid=self._show_settings, opacity=self.state.bg_opacity
        )

    # --- построение UI ---

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Header
        header = QHBoxLayout()
        header.setContentsMargins(14, 10, 14, 8)
        self.mic_btn = QPushButton("🎙 Микрофон")
        self.mic_btn.setObjectName("micChip")
        self.mic_btn.setCursor(Qt.PointingHandCursor)
        self.mic_btn.clicked.connect(self.state.toggle_listening)

        # Перетаскиваемая ручка-заголовок (большая зона захвата по центру шапки)
        title = DragHandle("⠿  Суфлёр  ⠿")

        self.settings_btn = QPushButton("⚙")
        self.settings_btn.setObjectName("icon")
        self.settings_btn.setCursor(Qt.PointingHandCursor)
        self.settings_btn.clicked.connect(self._toggle_settings)

        header.addWidget(self.mic_btn)
        header.addWidget(title, 1)
        header.addWidget(self.settings_btn)
        root.addLayout(header)

        line = QFrame()
        line.setObjectName("divider")
        line.setFixedHeight(1)
        root.addWidget(line)

        # --- Чат-страница ---
        self.chat_page = QWidget()
        chat_layout = QVBoxLayout(self.chat_page)
        chat_layout.setContentsMargins(0, 0, 0, 0)
        chat_layout.setSpacing(0)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.msg_container = QWidget()
        self.msg_container.setObjectName("msgContainer")
        self.msg_layout = QVBoxLayout(self.msg_container)
        self.msg_layout.setContentsMargins(12, 12, 12, 12)
        self.msg_layout.setSpacing(8)
        self.msg_layout.addStretch(1)
        self.scroll.setWidget(self.msg_container)
        chat_layout.addWidget(self.scroll, 1)

        # Живой транскрипт
        self.transcript_bar = QFrame()
        self.transcript_bar.setObjectName("transcriptBar")
        tb = QVBoxLayout(self.transcript_bar)
        tb.setContentsMargins(10, 6, 10, 6)
        self.transcript_caption = QLabel("Слушаю — текст появляется в поле ввода")
        self.transcript_caption.setObjectName("caption")
        self.transcript_caption.setWordWrap(True)
        self.transcript_input_lbl = QLabel("")
        self.transcript_input_lbl.setObjectName("caption")
        tb.addWidget(self.transcript_caption)
        tb.addWidget(self.transcript_input_lbl)
        self.transcript_bar.setVisible(False)
        chat_layout.addWidget(self.transcript_bar)

        # Кнопка «Подробнее» — развёрнутый ответ по последнему вопросу
        more_row = QHBoxLayout()
        more_row.setContentsMargins(10, 0, 10, 0)
        self.more_btn = QPushButton("🔎 Подробнее")
        self.more_btn.setObjectName("chip")
        self.more_btn.setCursor(Qt.PointingHandCursor)
        self.more_btn.setToolTip("Получить более развёрнутый ответ на последний вопрос")
        self.more_btn.clicked.connect(self._ask_more)
        self.more_btn.setEnabled(False)
        self.variant_btn = QPushButton("🔄 Ещё вариант")
        self.variant_btn.setObjectName("chip")
        self.variant_btn.setCursor(Qt.PointingHandCursor)
        self.variant_btn.setToolTip("Сформировать другой вариант ответа")
        self.variant_btn.clicked.connect(self._ask_variant)
        self.variant_btn.setEnabled(False)
        more_row.addWidget(self.more_btn)
        more_row.addWidget(self.variant_btn)
        more_row.addStretch(1)
        chat_layout.addLayout(more_row)

        # Поле ввода
        input_row = QHBoxLayout()
        input_row.setContentsMargins(10, 8, 10, 10)
        self.input = QPlainTextEdit()
        self.input.setPlaceholderText("Спросить вручную…")
        self.input.setFixedHeight(64)
        self.input.textChanged.connect(self._on_input_edited)
        self.input.installEventFilter(self)  # Enter — отправка, Shift+Enter — перенос
        self.shot_btn = QPushButton("📷")
        self.shot_btn.setObjectName("ghost")
        self.shot_btn.setFixedSize(44, 44)
        self.shot_btn.setCursor(Qt.PointingHandCursor)
        self.shot_btn.setToolTip("Скриншот экрана → в модель")
        self.shot_btn.clicked.connect(self._screenshot)
        self.send_btn = QPushButton("➤")
        self.send_btn.setObjectName("send")
        self.send_btn.setFixedSize(44, 44)
        self.send_btn.setCursor(Qt.PointingHandCursor)
        self.send_btn.clicked.connect(self._send)
        input_row.addWidget(self.input, 1)
        input_row.addWidget(self.shot_btn)
        input_row.addWidget(self.send_btn)
        chat_layout.addLayout(input_row)

        root.addWidget(self.chat_page, 1)

        # --- Страница настроек ---
        self.settings_page = self._build_settings_page()
        self.settings_page.setVisible(False)
        root.addWidget(self.settings_page, 1)

        self._suppress_input_signal = False

    def _build_settings_page(self) -> QWidget:
        """Настройки в виде вкладок (Вид / Аудио / Модели / Скриншот / Клавиши)
        с постоянным футером (Сохранить / Очистить / Закрыть). Все виджеты те же,
        что и раньше, — переразложены по страницам, логика сохранения не меняется."""
        container = QWidget()
        outer = QVBoxLayout(container)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # --- панель вкладок ---
        self._tab_defs = [
            ("view", "Вид"), ("audio", "Аудио"), ("models", "Модели"),
            ("shot", "Скриншот"), ("keys", "Клавиши"),
        ]
        tabbar = QHBoxLayout()
        tabbar.setContentsMargins(12, 10, 12, 8)
        tabbar.setSpacing(4)
        self._tab_buttons = {}
        for key, label in self._tab_defs:
            b = QPushButton(label)
            b.setObjectName("tab")
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=key: self._select_tab(k))
            self._tab_buttons[key] = b
            tabbar.addWidget(b)
        tabbar.addStretch(1)
        outer.addLayout(tabbar)

        div = QFrame()
        div.setObjectName("divider")
        div.setFixedHeight(1)
        outer.addWidget(div)

        # --- содержимое вкладок ---
        self.settings_stack = QStackedWidget()
        builders = {
            "view": self._page_view,
            "audio": self._page_audio,
            "models": self._page_models,
            "shot": self._page_shot,
            "keys": self._page_keys,
        }
        for key, _ in self._tab_defs:
            page = builders[key]()
            page.setObjectName("tabPage")
            page.setAutoFillBackground(False)
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            scroll.setFrameShape(QFrame.NoFrame)
            scroll.viewport().setAutoFillBackground(False)
            scroll.setWidget(page)
            self.settings_stack.addWidget(scroll)
        outer.addWidget(self.settings_stack, 1)

        # --- постоянный футер ---
        div2 = QFrame()
        div2.setObjectName("divider")
        div2.setFixedHeight(1)
        outer.addWidget(div2)

        footer = QHBoxLayout()
        footer.setContentsMargins(14, 10, 14, 14)
        footer.setSpacing(8)
        save = QPushButton("Сохранить")
        save.setObjectName("primary")
        save.setCursor(Qt.PointingHandCursor)
        save.clicked.connect(self._save_settings)
        clear = QPushButton("Очистить чат")
        clear.setObjectName("flat")
        clear.setCursor(Qt.PointingHandCursor)
        clear.clicked.connect(self.state.clear_chat)
        quit_btn = QPushButton("✕ Закрыть")
        quit_btn.setObjectName("quit")
        quit_btn.setCursor(Qt.PointingHandCursor)
        quit_btn.clicked.connect(self._quit_app)
        footer.addWidget(save)
        footer.addWidget(clear)
        footer.addStretch(1)
        footer.addWidget(quit_btn)
        outer.addLayout(footer)

        # Не даём выпадающим спискам растягивать страницу по ширине
        for combo in (
            self.mic_combo, self.lang_combo, self.whisper_combo,
            self.model_combo, self.mode_combo, self.audio_model_combo,
            self.vision_combo,
        ):
            self._narrow_combo(combo)

        self._select_tab("view")
        return container

    # --- вкладки настроек ---

    def _select_tab(self, key: str):
        for k, btn in self._tab_buttons.items():
            active = "true" if k == key else "false"
            btn.setProperty("active", active)
            btn.style().unpolish(btn)
            btn.style().polish(btn)
        idx = [k for k, _ in self._tab_defs].index(key)
        self.settings_stack.setCurrentIndex(idx)

    @staticmethod
    def _new_page() -> tuple:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(16, 14, 16, 16)
        lay.setSpacing(10)
        return page, lay

    def _field_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setObjectName("sectionLabel")
        return lbl

    def _page_view(self) -> QWidget:
        page, lay = self._new_page()
        lay.addWidget(self._field_label("Фон оверлея"))
        lay.addWidget(self._caption("Плотность области ответов"))
        bg_row = QHBoxLayout()
        self.bg_slider = QSlider(Qt.Horizontal)
        self.bg_slider.setRange(25, 100)
        self.bg_slider.setValue(int(self.state.bg_opacity))
        self.bg_slider.valueChanged.connect(self._on_bg_opacity)
        self.bg_value_lbl = QLabel(f"{int(self.state.bg_opacity)}%")
        self.bg_value_lbl.setObjectName("caption")
        bg_row.addWidget(self.bg_slider, 1)
        bg_row.addWidget(self.bg_value_lbl)
        lay.addLayout(bg_row)

        self.bg_preview = QLabel("Пример ответа на этом фоне — текст должен оставаться читаемым.")
        self.bg_preview.setWordWrap(True)
        self.bg_preview.setMinimumHeight(48)
        lay.addWidget(self.bg_preview)
        self._update_bg_preview(int(self.state.bg_opacity))
        lay.addStretch(1)
        return page

    def _page_audio(self) -> QWidget:
        page, lay = self._new_page()
        mic_row = QHBoxLayout()
        mic_row.addWidget(self._field_label("Микрофон"))
        mic_row.addStretch(1)
        refresh = QPushButton("Обновить")
        refresh.setObjectName("flat")
        refresh.setCursor(Qt.PointingHandCursor)
        refresh.clicked.connect(self._reload_mics)
        mic_row.addWidget(refresh)
        lay.addLayout(mic_row)
        self.mic_combo = QComboBox()
        lay.addWidget(self.mic_combo)

        lay.addWidget(self._field_label("Язык распознавания (Whisper)"))
        self.lang_combo = QComboBox()
        for code, label in [("ru", "Русский"), ("en", "English"), ("auto", "Авто")]:
            self.lang_combo.addItem(label, code)
        self._select_data(self.lang_combo, self.state.language)
        lay.addWidget(self.lang_combo)

        lay.addWidget(self._field_label("Модель Whisper"))
        lay.addWidget(self._caption("Больше = точнее, но медленнее"))
        self.whisper_combo = QComboBox()
        for size in ["tiny", "base", "small", "medium", "large-v3"]:
            self.whisper_combo.addItem(size, size)
        self._select_data(self.whisper_combo, self.state.whisper_model)
        lay.addWidget(self.whisper_combo)

        lay.addWidget(self._field_label("Режим ответа"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("Текст: Whisper → DeepSeek", "text")
        self.mode_combo.addItem("Аудио: модель слушает звук напрямую", "audio")
        self._select_data(self.mode_combo, self.state.response_mode)
        lay.addWidget(self.mode_combo)

        self.auto_check = ToggleSwitch("Авто-ответ — модель отвечает сама, без кнопки")
        self.auto_check.setChecked(self.state.auto_answer)
        lay.addWidget(self.auto_check)

        self.stop_after_send_check = ToggleSwitch(
            "Выключать микрофон после отправки (➤)"
        )
        self.stop_after_send_check.setChecked(self.state.stop_mic_after_send)
        lay.addWidget(self.stop_after_send_check)
        lay.addStretch(1)
        return page

    def _page_models(self) -> QWidget:
        page, lay = self._new_page()
        lay.addWidget(self._field_label("API-ключ DeepSeek / OpenRouter"))
        self.api_field = QLineEdit(self.state.api_key)
        self.api_field.setEchoMode(QLineEdit.Password)
        self.api_field.setPlaceholderText("sk-…")
        lay.addWidget(self.api_field)
        note = QLabel("Хранится локально в ~/.config/presenter-overlay.")
        note.setObjectName("caption")
        note.setWordWrap(True)
        lay.addWidget(note)

        lay.addWidget(self._field_label("Модель ответа (текстовый режим)"))
        self.model_combo = QComboBox()
        self.model_combo.addItem("deepseek-chat (V3)", "deepseek-chat")
        self.model_combo.addItem("deepseek-reasoner (R1)", "deepseek-reasoner")
        self._select_data(self.model_combo, self.state.model)
        lay.addWidget(self.model_combo)

        lay.addWidget(self._field_label("Аудио-модель"))
        lay.addWidget(self._caption("Аудио-режим; можно ввести свою"))
        self.audio_model_combo = QComboBox()
        self.audio_model_combo.setEditable(True)
        for mid, label in AUDIO_MODELS:
            self.audio_model_combo.addItem(label, mid)
        cur_idx = self.audio_model_combo.findData(self.state.audio_model)
        if cur_idx >= 0:
            self.audio_model_combo.setCurrentIndex(cur_idx)
            self.audio_model_combo.setEditText(self.state.audio_model)
        else:
            self.audio_model_combo.setEditText(self.state.audio_model)
        self.audio_model_combo.activated.connect(
            lambda i: self.audio_model_combo.setEditText(
                self.audio_model_combo.itemData(i) or self.audio_model_combo.currentText()
            )
        )
        lay.addWidget(self.audio_model_combo)

        lay.addWidget(self._field_label("Vision-модель для скриншотов"))
        self.vision_combo = QComboBox()
        self.vision_combo.setEditable(True)
        for mid, label in VISION_MODELS:
            self.vision_combo.addItem(label, mid)
        vi = self.vision_combo.findData(self.state.vision_model)
        if vi >= 0:
            self.vision_combo.setCurrentIndex(vi)
        self.vision_combo.setEditText(self.state.vision_model)
        self.vision_combo.activated.connect(
            lambda i: self.vision_combo.setEditText(
                self.vision_combo.itemData(i) or self.vision_combo.currentText()
            )
        )
        lay.addWidget(self.vision_combo)
        lay.addStretch(1)
        return page

    def _page_shot(self) -> QWidget:
        page, lay = self._new_page()
        lay.addWidget(self._field_label("Что делать со скриншотом"))
        lay.addWidget(self._caption("Инструкция модели"))
        self.shot_prompt_field = QPlainTextEdit(self.state.screenshot_prompt)
        self.shot_prompt_field.setPlaceholderText(
            "Напр.: найди ошибки и предложи фикс; или допиши код/текст на экране"
        )
        self.shot_prompt_field.setFixedHeight(74)
        lay.addWidget(self.shot_prompt_field)

        region_row = QHBoxLayout()
        sel_btn = QPushButton("Выделить область")
        sel_btn.setObjectName("flat")
        sel_btn.setCursor(Qt.PointingHandCursor)
        sel_btn.clicked.connect(self._select_region)
        full_btn = QPushButton("Весь экран")
        full_btn.setObjectName("flat")
        full_btn.setCursor(Qt.PointingHandCursor)
        full_btn.clicked.connect(self._clear_region)
        region_row.addWidget(sel_btn)
        region_row.addWidget(full_btn)
        lay.addLayout(region_row)

        self.region_lbl = QLabel()
        self.region_lbl.setObjectName("caption")
        self.region_lbl.setWordWrap(True)
        self._update_region_label()
        lay.addWidget(self.region_lbl)
        lay.addStretch(1)
        return page

    def _page_keys(self) -> QWidget:
        page, lay = self._new_page()
        lay.addWidget(self._caption(
            "Горячие клавиши работают вне фокуса окна. Кликни в поле и нажми сочетание."
        ))

        def _hk_row(label: str, edit: QKeySequenceEdit) -> QHBoxLayout:
            row = QHBoxLayout()
            cap = QLabel(label)
            cap.setObjectName("sectionLabel")
            cap.setFixedWidth(140)
            row.addWidget(cap)
            edit.setMaximumSequenceLength(1)
            row.addWidget(edit, 1)
            clr = QPushButton("✕")
            clr.setObjectName("flat")
            clr.setFixedWidth(34)
            clr.setCursor(Qt.PointingHandCursor)
            clr.clicked.connect(edit.clear)
            row.addWidget(clr)
            return row

        self.hk_mic = QKeySequenceEdit(QKeySequence(self.state.hotkey_toggle_mic))
        self.hk_send = QKeySequenceEdit(QKeySequence(self.state.hotkey_send))
        self.hk_shot = QKeySequenceEdit(QKeySequence(self.state.hotkey_screenshot))
        lay.addLayout(_hk_row("Микрофон вкл/выкл", self.hk_mic))
        lay.addLayout(_hk_row("Отправить запрос", self.hk_send))
        lay.addLayout(_hk_row("Скриншот → модель", self.hk_shot))

        hk_note = QLabel(
            "На macOS дай доступ в Системные настройки → Конфиденциальность → "
            "Универсальный доступ."
        )
        hk_note.setObjectName("caption")
        hk_note.setWordWrap(True)
        lay.addWidget(hk_note)

        lay.addWidget(self._field_label("Контекст для промпта"))
        self.context_field = QPlainTextEdit(self.state.prompt_context)
        self.context_field.setPlaceholderText(
            "Например: тема созвона, продукт, роль собеседника, важные факты…"
        )
        self.context_field.setFixedHeight(80)
        lay.addWidget(self.context_field)
        lay.addStretch(1)
        return page

    @staticmethod
    def _narrow_combo(combo: QComboBox):
        # Комбобокс не должен диктовать ширину по самому длинному пункту
        combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        combo.setMinimumContentsLength(6)
        combo.setMinimumWidth(0)
        combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        try:
            combo.view().setTextElideMode(Qt.ElideRight)
        except Exception:
            pass

    def _on_bg_opacity(self, value: int):
        self.state.bg_opacity = value
        self.bg_value_lbl.setText(f"{value}%")
        self._update_bg_preview(value)
        self.update()  # перерисовать фон чата

    def _update_bg_preview(self, value: int):
        o = max(25, min(100, int(value)))
        a = int(150 + (o - 25) / 75.0 * (250 - 150))
        self.bg_preview.setStyleSheet(
            f"background: rgba(250,251,253,{a}); color: #20242e;"
            "border: 1px solid rgba(20,24,32,16);"
            "border-radius: 14px; padding: 12px;"
        )

    def _quit_app(self):
        if callable(self.on_quit):
            self.on_quit()

    def _caption(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setObjectName("caption")
        return lbl

    @staticmethod
    def _select_data(combo: QComboBox, value: str):
        idx = combo.findData(value)
        if idx >= 0:
            combo.setCurrentIndex(idx)

    # --- связь с состоянием ---

    def _connect_state(self):
        s = self.state
        s.messages_changed.connect(self._render_messages)
        s.draft_changed.connect(self._apply_draft)
        s.listening_changed.connect(self._on_listening)
        s.audio_level_changed.connect(self._on_audio_level)
        s.sending_changed.connect(self._on_sending)
        s.status_changed.connect(self._on_status)
        s.input_name_changed.connect(self._on_input_name)

    # --- обработчики UI ---

    def _toggle_settings(self):
        self._show_settings = not self._show_settings
        self.settings_btn.setText("✕" if self._show_settings else "⚙")
        self.chat_page.setVisible(not self._show_settings)
        self.settings_page.setVisible(self._show_settings)
        if self._show_settings:
            self._reload_mics()

    def _reload_mics(self):
        self.mic_combo.clear()
        self.mic_combo.addItem("Авто: микрофон", "")
        for dev in self.state.available_audio_inputs():
            # Помечаем источники системного звука, чтобы их было легко найти.
            label = (f"🔊 {dev.name}  (системный звук)"
                     if audio.is_loopback(dev.name) else f"🎙 {dev.name}")
            self.mic_combo.addItem(label, dev.id)
        self._select_data(self.mic_combo, self.state.selected_audio_input_id)

    def _save_settings(self):
        s = self.state
        s.api_key = self.api_field.text().strip() or DEFAULT_API_KEY
        s.selected_audio_input_id = self.mic_combo.currentData() or ""
        s.language = self.lang_combo.currentData()
        s.whisper_model = self.whisper_combo.currentData()
        s.model = self.model_combo.currentData()
        s.response_mode = self.mode_combo.currentData()
        s.auto_answer = self.auto_check.isChecked()
        s.audio_model = self.audio_model_combo.currentText().strip() or s.audio_model
        s.stop_mic_after_send = self.stop_after_send_check.isChecked()
        s.bg_opacity = self.bg_slider.value()
        s.hotkey_toggle_mic = self.hk_mic.keySequence().toString(QKeySequence.PortableText)
        s.hotkey_send = self.hk_send.keySequence().toString(QKeySequence.PortableText)
        s.hotkey_screenshot = self.hk_shot.keySequence().toString(QKeySequence.PortableText)
        s.vision_model = self.vision_combo.currentText().strip() or s.vision_model
        s.screenshot_prompt = self.shot_prompt_field.toPlainText().strip() or s.screenshot_prompt
        s.prompt_context = self.context_field.toPlainText()
        s.save_settings()
        # Перезапускаем прослушивание, чтобы новый режим/авто-ответ применились.
        if s.is_listening:
            s.stop_listening()
            s.start_listening()
        self._on_listening(s.is_listening)  # обновить подсказку/кнопку под режим
        if callable(self.on_settings_saved):
            self.on_settings_saved()       # переназначить горячие клавиши
        self._toggle_settings()

    def _on_input_edited(self):
        if self._suppress_input_signal:
            return
        self.state.draft = self.input.toPlainText()
        self._update_send_enabled()

    def _apply_draft(self, text: str):
        # Текст из распознавания: обновляем поле, не зациклив сигнал.
        self._suppress_input_signal = True
        self.input.setPlainText(text)
        cursor = self.input.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self.input.setTextCursor(cursor)
        self._suppress_input_signal = False
        has_text = bool(text.strip())
        self._update_send_enabled()
        if self.state.is_listening:
            if has_text:
                self._status_text = "✓ Текст распознан — можно нажать ➤"
                self.transcript_input_lbl.setText("📝 " + text[-160:])
            else:
                self.transcript_input_lbl.setText("")

    def eventFilter(self, obj, event):  # noqa: N802
        if obj is self.input and event.type() == QEvent.KeyPress:
            if event.key() in (Qt.Key_Return, Qt.Key_Enter):
                if not (event.modifiers() & Qt.ShiftModifier):
                    self._send()
                    return True  # Enter — отправка
        return super().eventFilter(obj, event)

    def _send(self):
        # Есть напечатанный/распознанный текст — шлём его как вопрос.
        # Пусто и аудио-режим — отправляем записанный звук (flush).
        text = self.input.toPlainText().strip()
        if text:
            self.state.send(self.input.toPlainText())
        elif self.state.response_mode == "audio":
            self.state.send_now()

    def _screenshot(self):
        if callable(self.on_screenshot):
            self.on_screenshot()

    def _ask_more(self):
        self.state.ask_more_detail()

    def _ask_variant(self):
        self.state.ask_another_variant()

    def _select_region(self):
        if callable(self.on_select_region):
            self.on_select_region()

    def _clear_region(self):
        if callable(self.on_clear_region):
            self.on_clear_region()
        self._update_region_label()

    def _update_region_label(self):
        r = self.state.screenshot_region
        if r:
            self.region_lbl.setText(
                f"Область: {r['w']}×{r['h']} в точке ({r['x']}, {r['y']}). "
                "Скриншот будет только этой зоны."
            )
        else:
            self.region_lbl.setText("Область: весь экран.")

    def _update_send_enabled(self):
        has_text = bool(self.state.draft.strip())
        if has_text:
            enable = not self.state.is_sending
        elif self.state.response_mode == "audio":
            # пусто, но в аудио-режиме можно отправить записанный звук
            enable = self.state.is_listening and not self.state.is_sending
        else:
            enable = False
        self.send_btn.setEnabled(enable)

    def _on_listening(self, listening: bool):
        self.mic_btn.setText("● Слушаю" if listening else "🎙 Микрофон")
        self.mic_btn.setProperty("active", "true" if listening else "false")
        self.mic_btn.style().unpolish(self.mic_btn)
        self.mic_btn.style().polish(self.mic_btn)
        self.transcript_bar.setVisible(listening)
        audio_mode = self.state.response_mode == "audio"
        if listening:
            self._status_text = "Слушаю…"
            self.transcript_caption.setText("Слушаю…")
            self.transcript_input_lbl.setText("")
        # Поле всегда редактируемое — можно печатать вопрос вручную в любом режиме.
        self.input.setReadOnly(False)
        if audio_mode:
            self.input.setPlaceholderText(
                "Печатайте вопрос или говорите и жмите ➤ для отправки звука"
            )
        else:
            self.input.setPlaceholderText(
                "Говорите или печатайте…" if listening else "Спросить вручную…"
            )
        self._update_send_enabled()

    def _on_audio_level(self, level: float):
        bars = "▁▂▃▄▅▆▇█"
        idx = min(len(bars) - 1, int(level * len(bars)))
        meter = bars[idx]
        live = "🔴" if level > 0.04 else "⚪"
        self.transcript_caption.setText(f"{live} {self._status_text}   {meter} {int(level*100)}%")

    def _on_sending(self, sending: bool):
        self._update_send_enabled()

    def _on_status(self, text: str):
        self._status_text = text
        self.transcript_caption.setText(text)

    def _on_input_name(self, name: str):
        if name:
            self.transcript_input_lbl.setText(f"Вход: {name}")

    def _render_messages(self):
        # Убираем все бабблы (кроме финального stretch)
        while self.msg_layout.count() > 1:
            item = self.msg_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        for msg in self.state.messages:
            self.msg_layout.insertWidget(self.msg_layout.count() - 1, _bubble(msg))
        # «Подробнее» доступно, когда есть готовый ответ модели
        has_answer = any(
            m.role == "assistant" and m.text and m.text != "…"
            for m in self.state.messages
        )
        enable_followups = has_answer and not self.state.is_sending
        self.more_btn.setEnabled(enable_followups)
        self.variant_btn.setEnabled(enable_followups)
        QTimer.singleShot(30, self._scroll_to_bottom)

    def _scroll_to_bottom(self):
        bar = self.scroll.verticalScrollBar()
        bar.setValue(bar.maximum())

    # --- показ + приватность ---

    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        # always-on-top нужно подтверждать при каждом показе (особенно поверх
        # полноэкранных презентаций на macOS)
        QTimer.singleShot(0, lambda: keep_above(int(self.winId())))
        if not self._privacy_applied:
            self._privacy_applied = True
            QTimer.singleShot(50, self._apply_native_effects)

    def _apply_native_effects(self):
        wid = int(self.winId())
        # Стеклянный фон (реальное размытие на macOS/Windows)
        try:
            apply_glass(wid, PANEL_RADIUS)
        except Exception:
            pass
        # Поверх всех окон, включая полноэкранные
        try:
            keep_above(wid)
        except Exception:
            pass
        # Исключение из захвата экрана
        try:
            ok, msg = exclude_from_capture(wid)
            if not ok:
                self.state._append_system("⚠ " + msg)
        except Exception as exc:  # noqa: BLE001
            self.state._append_system(f"⚠ Скрытие от захвата недоступно: {exc}")


class MessageBubble(QFrame):
    def __init__(self, text: str, role: str):
        super().__init__()
        self._role = role
        lay = QVBoxLayout(self)
        lay.setContentsMargins(13, 9, 13, 9)
        lbl = QLabel()
        lbl.setWordWrap(True)
        lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        # Цвет текста: реплики пользователя — белые на синем,
        # ответы/системные — тёмные на светлом стекле.
        text_color = "#ffffff" if role == "user" else "#20242e"
        lbl.setStyleSheet(f"color: {text_color}; background: transparent;")
        # Ответы модели рендерим как markdown (код, списки, жирный),
        # реплики пользователя/системы — обычным текстом.
        if role == "assistant" and text != "…":
            lbl.setTextFormat(Qt.RichText)
            lbl.setText(render_markdown(text))
        else:
            lbl.setTextFormat(Qt.PlainText)
            lbl.setText(text)
        lay.addWidget(lbl)
        if role == "user":
            bg = "#2f6bff"
            border = "none"
            radius = "16px 16px 4px 16px"
            self.setMaximumWidth(420)
        elif role == "system":
            bg = "rgba(47,107,255,18)"
            border = "1px solid rgba(47,107,255,40)"
            radius = "14px"
            self.setMaximumWidth(460)
        else:
            bg = "rgba(255,255,255,180)"
            border = "1px solid rgba(255,255,255,180)"
            radius = "16px 16px 16px 4px"
            # ответам даём максимум ширины — код читабельнее
            self.setMaximumWidth(480)
        self.setStyleSheet(
            f"QFrame {{ background: {bg}; border: {border}; border-radius: {radius}; }}"
        )


_CODE_BG = "#11151c"


def _format_code(code: str) -> str:
    """Код для блока: экранируем, сохраняем отступы (&nbsp; только в начале строк),
    внутренние пробелы оставляем обычными — чтобы длинные строки переносились."""
    lines = code.split("\n")
    out = []
    for ln in lines:
        stripped = ln.lstrip(" ")
        indent = len(ln) - len(stripped)
        out.append("&nbsp;" * indent + _html.escape(stripped))
    return "<br>".join(out)


def _inline_md(seg: str) -> str:
    esc = _html.escape(seg)
    # inline `code`
    esc = re.sub(
        r"`([^`]+)`",
        r'<code style="background:#11151c; color:#e6edf3; '
        r'font-family:Menlo,Consolas,monospace;">&nbsp;\1&nbsp;</code>',
        esc,
    )
    # **bold** и __bold__
    esc = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", esc)
    esc = re.sub(r"__([^_]+)__", r"<b>\1</b>", esc)
    # построчно: заголовки # и списки -/*
    html_lines = []
    for ln in esc.split("\n"):
        s = ln.strip()
        m = re.match(r"^(#{1,6})\s+(.*)", s)
        if m:
            html_lines.append(f"<b>{m.group(2)}</b>")
        elif re.match(r"^[-*+]\s+", s):
            html_lines.append("&nbsp;•&nbsp;" + re.sub(r"^[-*+]\s+", "", s))
        else:
            html_lines.append(ln)
    return "<br>".join(html_lines)


def render_markdown(text: str) -> str:
    """Лёгкий markdown→HTML для красивого вывода ответов модели (блоки кода,
    inline-код, жирный, списки). Рендерится в QLabel как RichText."""
    text = (text or "").replace("\r\n", "\n")
    parts = text.split("```")
    out = []
    for i, seg in enumerate(parts):
        if i % 2 == 1:  # содержимое блока кода
            lines = seg.split("\n")
            # убираем строку с названием языка (одно слово в начале)
            if lines and lines[0].strip() and " " not in lines[0].strip() and len(lines) > 1:
                lines = lines[1:]
            code = "\n".join(lines).strip("\n")
            out.append(
                f'<div style="background:{_CODE_BG}; color:#e6edf3; padding:6px; '
                f'font-family:Menlo,Consolas,monospace; font-size:12px;">'
                f"{_format_code(code)}</div>"
            )
        else:
            out.append(_inline_md(seg))
    return "".join(out)


def _bubble(msg) -> QWidget:
    wrap = QWidget()
    h = QHBoxLayout(wrap)
    h.setContentsMargins(0, 0, 0, 0)
    bubble = MessageBubble(msg.text, msg.role)
    if msg.role == "user":
        h.addStretch(1)
        h.addWidget(bubble)
    else:
        h.addWidget(bubble)
        h.addStretch(1)
    return wrap


class LauncherButton(QWidget, DragMixin):
    """Маленькая круглая кнопка на рабочем столе для показа/скрытия панели."""

    SIZE = 64

    def __init__(self, state: AppState, on_toggle, on_quit):
        super().__init__()
        self.state = state
        self.on_toggle = on_toggle
        self.on_quit = on_quit
        self._init_drag()
        # Для кнопки используем ручное перетаскивание, чтобы отличать клик от drag.
        self._use_system_move = False
        self._press_pos = None
        self._privacy_applied = False

        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(self.SIZE, self.SIZE)
        self.setCursor(Qt.PointingHandCursor)
        self._level = 0.0
        self.state.audio_level_changed.connect(self._set_level)
        self.state.listening_changed.connect(lambda _: self.update())

    def _set_level(self, level: float):
        self._level = level
        self.update()

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = self.rect().adjusted(4, 4, -4, -4)
        path = QPainterPath()
        path.addEllipse(rect)
        # Светлое матовое стекло
        p.fillPath(path, QColor(250, 251, 253, 240))
        if self.state.is_listening:
            width = 2 + int(self._level * 6)
            pen = p.pen()
            pen.setColor(QColor(24, 165, 88, 220))  # зелёный, когда слушает
            pen.setWidth(max(2, width))
            p.setPen(pen)
        else:
            pen = p.pen()
            pen.setColor(QColor(47, 107, 255, 150))  # синий акцент в покое
            pen.setWidth(2)
            p.setPen(pen)
        p.drawEllipse(rect)
        p.setPen(QColor(58, 66, 80))
        font = QFont()
        font.setPointSize(20)
        p.setFont(font)
        p.drawText(rect, Qt.AlignCenter, "◉" if self.state.is_listening else "💬")

    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.RightButton:
            self._show_menu(event.globalPosition().toPoint())
            return
        self._press_pos = event.globalPosition().toPoint()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):  # noqa: N802
        super().mouseReleaseEvent(event)
        if self._press_pos is not None and event.button() == Qt.LeftButton:
            moved = (event.globalPosition().toPoint() - self._press_pos).manhattanLength()
            if moved < 6:  # это клик, а не перетаскивание
                self.on_toggle()
        self._press_pos = None

    def _show_menu(self, pos: QPoint):
        menu = QMenu(self)
        toggle = QAction("Показать / скрыть панель", self)
        toggle.triggered.connect(self.on_toggle)
        quit_act = QAction("Выход", self)
        quit_act.triggered.connect(self.on_quit)
        menu.addAction(toggle)
        menu.addSeparator()
        menu.addAction(quit_act)
        menu.exec(pos)

    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        QTimer.singleShot(0, lambda: keep_above(int(self.winId())))
        if not self._privacy_applied:
            self._privacy_applied = True
            QTimer.singleShot(50, lambda: exclude_from_capture(int(self.winId())))


class OverlayApp:
    """Связывает панель и кнопку, управляет показом/скрытием."""

    def __init__(self, state: AppState):
        self.state = state
        # Основной UI — веб-интерфейс 1:1 с макетом (QWebEngineView). Если
        # QtWebEngine недоступен, безопасно откатываемся на нативную Qt-панель.
        self.panel = self._make_panel(state)
        self.panel.on_quit = self.quit
        self.panel.on_settings_saved = self.apply_hotkeys
        self.panel.on_screenshot = self.take_and_send_screenshot
        self.panel.on_select_region = self.select_region
        self.panel.on_clear_region = self.clear_region
        self._panel_visible = False
        self.launcher = LauncherButton(
            state, on_toggle=self.toggle_panel, on_quit=self.quit
        )
        self.region_frame = RegionFrame()
        self._region_selector = None
        self.state.hotkey_screenshot_requested.connect(self.take_and_send_screenshot)
        self.hotkeys = HotkeyManager()
        self._hotkey_prompted = False
        self._trust_timer = None
        self.apply_hotkeys()
        self._position_windows()
        self.region_frame.set_region(self.state.screenshot_region)

    def _make_panel(self, state: AppState):
        """Веб-панель (1:1 макет) с фолбэком на нативную Qt-панель."""
        try:
            from .webview import WebChatPanel
            return WebChatPanel(state)
        except Exception as exc:  # noqa: BLE001 — нет QtWebEngine и т.п.
            state._append_system(
                "⚠ Веб-интерфейс недоступен (нет QtWebEngine?), использую "
                f"нативный вид. Детали: {exc}"
            )
            return ChatPanel(state)

    # --- область скриншота ---

    def select_region(self):
        # Прячем оверлей/рамку, чтобы они не мешали выделению
        self.launcher.hide()
        self.region_frame.hide()
        panel_was = self._panel_visible
        if panel_was:
            self.panel.hide()
        QApplication.processEvents()
        self._region_selector = RegionSelector(
            on_done=lambda region: self._on_region_selected(region, panel_was)
        )
        self._region_selector.show()

    def _on_region_selected(self, region, panel_was):
        if region:  # None — отмена, область не меняем
            self.state.screenshot_region = region
            self.state.save_settings()
        self.launcher.show()
        self.region_frame.set_region(self.state.screenshot_region)
        if panel_was:
            self.panel.show()
            self.panel.raise_()
            self.panel._update_region_label()

    def clear_region(self):
        self.state.screenshot_region = None
        self.state.save_settings()
        self.region_frame.hide()

    def _region_for_capture(self):
        """Возвращает (область в логических координатах относительно экрана,
        логический размер экрана) — масштаб в физические пиксели вычислит сам
        capture_screen по фактическому размеру снимка."""
        r = self.state.screenshot_region
        scr = QApplication.primaryScreen()
        geo = scr.geometry()
        logical_size = (geo.width(), geo.height())
        if not r:
            return None, logical_size
        region_local = {
            "x": r["x"] - geo.x(),
            "y": r["y"] - geo.y(),
            "w": r["w"],
            "h": r["h"],
        }
        return region_local, logical_size

    def take_and_send_screenshot(self):
        """Скрыть оверлей, снять экран, вернуть оверлей и отправить снимок."""
        if not screenshot.is_available():
            self.state._append_system(
                "⚠ Скриншоты недоступны: " + screenshot.unavailable_reason()
            )
            return
        self._panel_was_visible = self._panel_visible
        self.launcher.hide()
        self.region_frame.hide()  # рамку тоже прячем, чтобы не попала в кадр
        if self._panel_visible:
            self.panel.hide()
        QApplication.processEvents()
        # Небольшая задержка, чтобы окна успели исчезнуть до снимка
        QTimer.singleShot(180, self._capture_after_hide)

    def _capture_after_hide(self):
        png = None
        err = ""
        try:
            region_local, logical_size = self._region_for_capture()
            png = screenshot.capture_screen(
                region=region_local, logical_size=logical_size
            )
        except Exception as exc:  # noqa: BLE001
            err = str(exc)
        # Возвращаем рамку области
        self.region_frame.set_region(self.state.screenshot_region)
        # Возвращаем оверлей и показываем панель (чтобы увидеть ответ)
        self.launcher.show()
        if not self._panel_visible:
            self.toggle_panel()
        else:
            self.panel.show()
            self.panel.raise_()
        if png:
            r = self.state.screenshot_region
            label = (
                f"🖼 (скриншот области {r['w']}×{r['h']})" if r else "🖼 (скриншот экрана)"
            )
            self.state.send_screenshot(png, label)
        else:
            self.state._append_system(f"⚠ Не удалось сделать скриншот: {err}")

    def apply_hotkeys(self):
        """Переназначить глобальные горячие клавиши из настроек."""
        bindings = {}
        if self.state.hotkey_toggle_mic:
            bindings[self.state.hotkey_toggle_mic] = self.state.hotkey_toggle_requested.emit
        if self.state.hotkey_send:
            bindings[self.state.hotkey_send] = self.state.hotkey_send_requested.emit
        if self.state.hotkey_screenshot:
            bindings[self.state.hotkey_screenshot] = self.state.hotkey_screenshot_requested.emit

        self._desired_bindings = bindings
        self._activate_hotkeys(first=True)

    def _activate_hotkeys(self, first: bool = False):
        bindings = getattr(self, "_desired_bindings", {})
        if not bindings:
            self.hotkeys.stop()
            self._stop_trust_timer()
            return

        if not HotkeyManager.is_available():
            if first:
                self.state._append_system(
                    "⚠ Горячие клавиши недоступны: " + HotkeyManager.unavailable_reason()
                )
            return

        # macOS: пока процесс не «доверен», слушатель не запускаем (иначе спам
        # «This process is not trusted!»). Просим доступ системным диалогом —
        # он добавит в список ИМЕННО этот процесс. Дальше периодически
        # перепроверяем: как только доступ дан, хоткеи включатся сами.
        prompt = first and not self._hotkey_prompted
        if not macos_accessibility_trusted(prompt=prompt):
            if prompt:
                self._hotkey_prompted = True
                self.state._append_system(
                    "⚠ Горячим клавишам нужен доступ macOS. Включи это приложение в "
                    "Системные настройки → Конфиденциальность → «Универсальный "
                    "доступ» И «Мониторинг ввода». Как только включишь — хоткеи "
                    "активируются автоматически (если нет — полностью перезапусти "
                    "приложение)."
                )
            self._start_trust_timer()
            return

        self._stop_trust_timer()
        ok, msg = self.hotkeys.apply(bindings)
        if ok:
            self.state._append_system("✓ Горячие клавиши включены.")
        else:
            self.state._append_system("⚠ Не удалось включить горячие клавиши: " + msg)

    def _start_trust_timer(self):
        if self._trust_timer is None:
            self._trust_timer = QTimer()
            self._trust_timer.setInterval(2500)
            self._trust_timer.timeout.connect(lambda: self._activate_hotkeys(first=False))
        if not self._trust_timer.isActive():
            self._trust_timer.start()

    def _stop_trust_timer(self):
        if self._trust_timer is not None and self._trust_timer.isActive():
            self._trust_timer.stop()

    def _position_windows(self):
        screen = QApplication.primaryScreen()
        geo = screen.availableGeometry()
        # Высота окна не больше экрана — иначе настройки «вылезают» за край.
        max_h = max(360, geo.height() - 60)
        self.panel.setMaximumHeight(max_h)
        if self.panel.height() > max_h:
            self.panel.resize(self.panel.width(), max_h)
        self.panel.move(geo.right() - self.panel.width() - 20, geo.top() + 30)
        self.launcher.move(geo.right() - 90, geo.bottom() - 100)

    def show(self):
        self.launcher.show()

    def toggle_panel(self):
        self._panel_visible = not self._panel_visible
        if self._panel_visible:
            self.panel.show()
            self.panel.raise_()
            self.panel.activateWindow()
            self.state.refresh_audio_inputs()
        else:
            self.panel.hide()

    def quit(self):
        try:
            self.hotkeys.stop()
        except Exception:
            pass
        self.state.stop_listening()
        QApplication.quit()
