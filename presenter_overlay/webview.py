"""Веб-интерфейс оверлёра (1:1 с макетом) внутри Qt через QWebEngineView.

Идея: всё «лицо» приложения — это HTML/CSS из web/index.html (тот же дизайн,
что в макете). Логика остаётся в Python (AppState и нативные эффекты окна), а
связь UI ↔ Python идёт через QWebChannel:
  - сигналы Bridge → JS обновляет интерфейс;
  - слоты Bridge ← JS зовёт действия (микрофон, отправка, настройки и т.д.).

Так дизайн получается точь-в-точь как в браузере, а весь существующий backend
(audio/transcriber/llm/screenshot/native) переиспользуется без изменений.
"""

from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QObject, QUrl, Qt, QTimer, Signal, Slot
from PySide6.QtWidgets import QVBoxLayout, QWidget

from . import audio
from .config import AUDIO_MODELS, DEFAULT_API_KEY, VISION_MODELS
from .native import apply_glass, keep_above
from .overlay import PANEL_RADIUS, render_markdown
from .screen_privacy import exclude_from_capture
from .state import AppState

_INDEX_HTML = Path(__file__).resolve().parent / "web" / "index.html"


class Bridge(QObject):
    """Мост между JS-интерфейсом и AppState. Регистрируется в QWebChannel."""

    # Python → JS
    messagesChanged = Signal(str)
    draftChanged = Signal(str)
    listeningChanged = Signal(bool)
    sendingChanged = Signal(bool)
    statusChanged = Signal(str)
    regionLabelChanged = Signal(str)
    micListChanged = Signal(str)
    settingsLoaded = Signal(str)

    def __init__(self, state: AppState, panel: "WebChatPanel"):
        super().__init__()
        self.state = state
        self.panel = panel

        s = state
        s.messages_changed.connect(self._emit_messages)
        s.draft_changed.connect(self.draftChanged.emit)
        s.listening_changed.connect(self.listeningChanged.emit)
        s.sending_changed.connect(self.sendingChanged.emit)
        s.status_changed.connect(self.statusChanged.emit)

    # --- Python → JS payloads ---

    def _messages_json(self) -> str:
        out = []
        for m in self.state.messages:
            html = None
            if m.role == "assistant" and m.text and m.text != "…":
                html = render_markdown(m.text)
            out.append({"role": m.role, "text": m.text, "html": html})
        return json.dumps(out, ensure_ascii=False)

    def _emit_messages(self):
        self.messagesChanged.emit(self._messages_json())

    def _mics_json(self) -> str:
        cur = self.state.selected_audio_input_id
        items = [{"id": "", "label": "Авто: микрофон", "selected": cur == ""}]
        for dev in self.state.available_audio_inputs():
            label = (f"🔊 {dev.name}  (системный звук)"
                     if audio.is_loopback(dev.name) else f"🎙 {dev.name}")
            items.append({"id": dev.id, "label": label, "selected": dev.id == cur})
        return json.dumps(items, ensure_ascii=False)

    def _region_label(self) -> str:
        r = self.state.screenshot_region
        if r:
            return (f"Область: {r['w']}×{r['h']} в точке ({r['x']}, {r['y']}). "
                    "Скриншот будет только этой зоны.")
        return "Область: весь экран."

    def _settings_json(self) -> str:
        s = self.state
        data = {
            "api_key": s.api_key,
            "model": s.model,
            "language": s.language,
            "whisper_model": s.whisper_model,
            "response_mode": s.response_mode,
            "auto_answer": s.auto_answer,
            "stop_mic_after_send": s.stop_mic_after_send,
            "audio_model": s.audio_model,
            "vision_model": s.vision_model,
            "screenshot_prompt": s.screenshot_prompt,
            "prompt_context": s.prompt_context,
            "bg_opacity": int(s.bg_opacity),
            "hotkey_toggle_mic": s.hotkey_toggle_mic,
            "hotkey_send": s.hotkey_send,
            "hotkey_screenshot": s.hotkey_screenshot,
            "region_label": self._region_label(),
            "audio_models": [[mid, label] for mid, label in AUDIO_MODELS],
            "vision_models": [[mid, label] for mid, label in VISION_MODELS],
        }
        return json.dumps(data, ensure_ascii=False)

    # --- JS → Python slots ---

    @Slot()
    def ready(self):
        # Начальное состояние при загрузке страницы.
        self._emit_messages()
        self.draftChanged.emit(self.state.draft)
        self.listeningChanged.emit(self.state.is_listening)
        self.regionLabelChanged.emit(self._region_label())

    @Slot()
    def requestSettings(self):
        self.state.refresh_audio_inputs()
        self.micListChanged.emit(self._mics_json())
        self.settingsLoaded.emit(self._settings_json())

    @Slot()
    def toggleMic(self):
        self.state.toggle_listening()

    @Slot(str)
    def send(self, text: str):
        self.state.send(text)

    @Slot()
    def sendNow(self):
        if self.state.response_mode == "audio":
            self.state.send_now()

    @Slot()
    def askMore(self):
        self.state.ask_more_detail()

    @Slot()
    def askVariant(self):
        self.state.ask_another_variant()

    @Slot()
    def screenshot(self):
        if callable(self.panel.on_screenshot):
            self.panel.on_screenshot()

    @Slot()
    def selectRegion(self):
        if callable(self.panel.on_select_region):
            self.panel.on_select_region()

    @Slot()
    def clearRegion(self):
        if callable(self.panel.on_clear_region):
            self.panel.on_clear_region()
        self.regionLabelChanged.emit(self._region_label())

    @Slot()
    def reloadMics(self):
        self.state.refresh_audio_inputs()
        self.micListChanged.emit(self._mics_json())

    @Slot(int)
    def setBgOpacity(self, value: int):
        self.state.bg_opacity = int(value)

    @Slot(str)
    def setDraft(self, text: str):
        self.state.draft = text

    @Slot()
    def clearChat(self):
        self.state.clear_chat()

    @Slot()
    def quit(self):
        if callable(self.panel.on_quit):
            self.panel.on_quit()

    @Slot()
    def startDrag(self):
        try:
            handle = self.panel.windowHandle()
            if handle is not None:
                handle.startSystemMove()
        except Exception:
            pass

    @Slot(str)
    def saveSettings(self, payload: str):
        try:
            d = json.loads(payload or "{}")
        except json.JSONDecodeError:
            return
        s = self.state
        s.api_key = (d.get("api_key") or "").strip() or DEFAULT_API_KEY
        s.model = d.get("model") or s.model
        s.language = d.get("language") or s.language
        s.whisper_model = d.get("whisper_model") or s.whisper_model
        s.response_mode = d.get("response_mode") or s.response_mode
        s.auto_answer = bool(d.get("auto_answer"))
        s.stop_mic_after_send = bool(d.get("stop_mic_after_send"))
        s.audio_model = (d.get("audio_model") or "").strip() or s.audio_model
        s.vision_model = (d.get("vision_model") or "").strip() or s.vision_model
        s.screenshot_prompt = (d.get("screenshot_prompt") or "").strip() or s.screenshot_prompt
        s.prompt_context = d.get("prompt_context", s.prompt_context)
        try:
            s.bg_opacity = int(d.get("bg_opacity", s.bg_opacity))
        except (TypeError, ValueError):
            pass
        s.hotkey_toggle_mic = d.get("hotkey_toggle_mic", "")
        s.hotkey_send = d.get("hotkey_send", "")
        s.hotkey_screenshot = d.get("hotkey_screenshot", "")
        s.save_settings()
        # Перезапуск прослушивания, чтобы новый режим/авто-ответ применились.
        if s.is_listening:
            s.stop_listening()
            s.start_listening()
        if callable(self.panel.on_settings_saved):
            self.panel.on_settings_saved()  # переназначить горячие клавиши


class WebChatPanel(QWidget):
    """Безрамочное окно-оверлей с веб-интерфейсом внутри (QWebEngineView).

    Внешний интерфейс совместим с прежним ChatPanel — OverlayApp работает с ним
    одинаково (show/hide/raise_/move/resize, on_* колбэки, _update_region_label).
    """

    def __init__(self, state: AppState):
        super().__init__()
        self.state = state
        self._privacy_applied = False
        self.on_quit = None
        self.on_settings_saved = None
        self.on_screenshot = None
        self.on_select_region = None
        self.on_clear_region = None

        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.resize(430, 720)

        # Импортируем веб-движок лениво, чтобы отсутствие QtWebEngine не валило
        # весь модуль на этапе импорта (есть фолбэк на нативную панель).
        from PySide6.QtWebChannel import QWebChannel
        from PySide6.QtWebEngineWidgets import QWebEngineView

        self.view = QWebEngineView(self)
        self.view.setAttribute(Qt.WA_TranslucentBackground)
        self.view.page().setBackgroundColor(Qt.transparent)

        # Разрешаем локальной странице грузить qwebchannel.js из qrc и файлы.
        try:
            from PySide6.QtWebEngineCore import QWebEngineSettings
            st = self.view.settings()
            st.setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls, True)
            st.setAttribute(QWebEngineSettings.LocalContentCanAccessFileUrls, True)
        except Exception:
            pass

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.view)

        self.bridge = Bridge(state, self)
        self._channel = QWebChannel()
        self._channel.registerObject("bridge", self.bridge)
        self.view.page().setWebChannel(self._channel)
        self.view.load(QUrl.fromLocalFile(str(_INDEX_HTML)))

    # OverlayApp дергает это после смены области скриншота.
    def _update_region_label(self):
        self.bridge.regionLabelChanged.emit(self.bridge._region_label())

    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        QTimer.singleShot(0, lambda: keep_above(int(self.winId())))
        if not self._privacy_applied:
            self._privacy_applied = True
            QTimer.singleShot(50, self._apply_native_effects)

    def _apply_native_effects(self):
        wid = int(self.winId())
        for fn in (lambda: apply_glass(wid, PANEL_RADIUS), lambda: keep_above(wid)):
            try:
                fn()
            except Exception:
                pass
        try:
            ok, msg = exclude_from_capture(wid)
            if not ok:
                self.state._append_system("⚠ " + msg)
        except Exception as exc:  # noqa: BLE001
            self.state._append_system(f"⚠ Скрытие от захвата недоступно: {exc}")
