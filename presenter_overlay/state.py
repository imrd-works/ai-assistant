"""Состояние приложения (аналог AppState.swift).

Связывает распознавание речи (Whisper), клиент DeepSeek и UI через сигналы Qt,
чтобы колбэки из фоновых потоков безопасно обновляли интерфейс.
"""

from __future__ import annotations

import threading
from typing import List

from PySide6.QtCore import QObject, QTimer, Signal

from . import audio, llm
from .config import Settings
from .transcriber import WhisperTranscriber


class AppState(QObject):
    # Сигналы для UI (эмитятся из любых потоков, доставляются в UI-поток)
    messages_changed = Signal()
    draft_changed = Signal(str)        # текст поля ввода (живая диктовка)
    listening_changed = Signal(bool)
    audio_level_changed = Signal(float)
    sending_changed = Signal(bool)
    status_changed = Signal(str)
    input_name_changed = Signal(str)
    # Финальная фраза из фонового потока → в UI-поток (для авто-ответа)
    _final_phrase = Signal(str)
    _final_audio = Signal(object)
    # Запросы от глобальных хоткеев (эмитятся из потока pynput → в UI-поток)
    hotkey_toggle_requested = Signal()
    hotkey_send_requested = Signal()
    hotkey_screenshot_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.settings = Settings()

        self.messages: List[llm.ChatMessage] = []
        self.is_listening = False
        self.is_sending = False
        self.draft = ""
        self.live_transcript = ""
        self.audio_input_name = ""

        # настройки
        self.api_key = self.settings.api_key
        self.model = self.settings.model
        self.prompt_context = self.settings.prompt_context
        self.language = self.settings.language
        self.whisper_model = self.settings.whisper_model
        self.selected_audio_input_id = self.settings.audio_input_id
        self.response_mode = self.settings.response_mode   # "text" | "audio"
        self.auto_answer = self.settings.auto_answer
        self.audio_model = self.settings.audio_model
        self.hotkey_toggle_mic = self.settings.hotkey_toggle_mic
        self.hotkey_send = self.settings.hotkey_send
        self.stop_mic_after_send = self.settings.stop_mic_after_send
        self.bg_opacity = self.settings.bg_opacity
        self.hotkey_screenshot = self.settings.hotkey_screenshot
        self.vision_model = self.settings.vision_model
        self.screenshot_prompt = self.settings.screenshot_prompt
        self.screenshot_region = self.settings.screenshot_region  # {x,y,w,h} или None

        self._dictation_base = ""
        self._transcriber: WhisperTranscriber | None = None

        # Финальные фразы обрабатываем строго в UI-потоке (безопасно для списка)
        self._final_phrase.connect(self._on_final_phrase)
        self._final_audio.connect(self._on_final_audio)
        # Хоткеи приходят из потока pynput — сигналы доставят их в UI-поток
        self.hotkey_toggle_requested.connect(self.toggle_listening)
        self.hotkey_send_requested.connect(self._on_hotkey_send)

    # --- устройства ---

    def available_audio_inputs(self) -> List[audio.AudioInputDevice]:
        return audio.available_input_devices()

    def refresh_audio_inputs(self) -> None:
        devices = self.available_audio_inputs()
        if self.selected_audio_input_id and not any(
            d.id == self.selected_audio_input_id for d in devices
        ):
            self.selected_audio_input_id = ""
        self.audio_input_name = audio.device_name_for(self.selected_audio_input_id)
        self.input_name_changed.emit(self.audio_input_name)

    def _effective_device_index(self):
        if self.selected_audio_input_id:
            idx = audio.resolve_device_index(self.selected_audio_input_id)
            if idx is not None:
                return idx
        pref = audio.preferred_microphone(self.available_audio_inputs())
        return pref.index if pref else None

    # --- настройки ---

    def save_settings(self) -> None:
        self.settings.set("deepseek_key", self.api_key)
        self.settings.set("deepseek_model", self.model)
        self.settings.set("prompt_context", self.prompt_context)
        self.settings.set("language", self.language)
        self.settings.set("whisper_model", self.whisper_model)
        self.settings.set("audio_input_id", self.selected_audio_input_id)
        self.settings.set("response_mode", self.response_mode)
        self.settings.set("auto_answer", self.auto_answer)
        self.settings.set("audio_model", self.audio_model)
        self.settings.set("hotkey_toggle_mic", self.hotkey_toggle_mic)
        self.settings.set("hotkey_send", self.hotkey_send)
        self.settings.set("stop_mic_after_send", self.stop_mic_after_send)
        self.settings.set("bg_opacity", self.bg_opacity)
        self.settings.set("hotkey_screenshot", self.hotkey_screenshot)
        self.settings.set("vision_model", self.vision_model)
        self.settings.set("screenshot_prompt", self.screenshot_prompt)
        self.settings.set("screenshot_region", self.screenshot_region)
        self.settings.save()

    # --- микрофон ---

    def toggle_listening(self) -> None:
        if self.is_listening:
            self.stop_listening()
        else:
            self.start_listening()

    def start_listening(self) -> None:
        audio_mode = self.response_mode == "audio"
        # В авто-режиме (и всегда в аудио-режиме) фразы независимы — не копим текст.
        existing = "" if (self.auto_answer or audio_mode) else self.draft.strip()
        self._dictation_base = (existing + " ") if existing else ""

        self._transcriber = WhisperTranscriber(
            model_size=self.whisper_model,
            language=self.language,
            mode="audio" if audio_mode else "whisper",
        )
        self._transcriber.reset_after_final = self.auto_answer and not audio_mode
        # Текст: всегда фиксируем фразы (живой текст). Аудио: авто-фиксация только
        # при авто-ответе; иначе фраза копится и уходит по кнопке «Отправить».
        self._transcriber.auto_finalize = (not audio_mode) or self.auto_answer
        self._transcriber.on_update = self._on_transcript
        self._transcriber.on_final = self._final_phrase.emit
        self._transcriber.on_final_audio = self._final_audio.emit
        self._transcriber.on_audio_level = self.audio_level_changed.emit
        self._transcriber.on_status = self.status_changed.emit
        self._transcriber.on_error = self._on_transcriber_error

        self.refresh_audio_inputs()
        device_index = self._effective_device_index()

        try:
            self._transcriber.start(device_index)
            self.is_listening = True
            self.listening_changed.emit(True)
            self.audio_input_name = audio.device_name_for(self.selected_audio_input_id)
            self.input_name_changed.emit(self.audio_input_name)
        except Exception as exc:  # noqa: BLE001
            self.is_listening = False
            self.listening_changed.emit(False)
            self.audio_level_changed.emit(0.0)
            self._append_system(f"Не удалось включить микрофон: {exc}")

    def stop_listening(self) -> None:
        if self._transcriber:
            self._transcriber.stop()
        self.is_listening = False
        self.listening_changed.emit(False)
        self.audio_level_changed.emit(0.0)

    def _on_transcript(self, text: str) -> None:
        self.live_transcript = text
        self.draft = text if not self._dictation_base else self._dictation_base + text
        self.draft_changed.emit(self.draft)

    def _on_transcriber_error(self, message: str) -> None:
        self.is_listening = False
        self.listening_changed.emit(False)
        self.audio_level_changed.emit(0.0)
        self._append_system(f"Микрофон остановлен: {message}")

    # --- авто-ответ (вызывается в UI-потоке через сигналы) ---

    def _on_final_phrase(self, phrase: str) -> None:
        """Завершённая фраза распознана. В авто-режиме сразу шлём её модели."""
        if self.auto_answer and phrase.strip():
            self.draft = ""
            self.draft_changed.emit("")
            self._dispatch_text(phrase.strip())

    def _on_final_audio(self, wav_bytes: bytes) -> None:
        """Аудио-режим: звук фразы уходит напрямую в аудио-модель."""
        self.status_changed.emit("Отправляю аудио в модель…")
        self.messages.append(llm.ChatMessage(role="user", text="🎤 (аудио-фраза)"))
        placeholder = llm.ChatMessage(role="assistant", text="…")
        self.messages.append(placeholder)
        self.messages_changed.emit()
        threading.Thread(
            target=self._do_audio_request, args=(wav_bytes, placeholder), daemon=True
        ).start()

    def send_screenshot(self, png_bytes: bytes, label: str = "🖼 (скриншот экрана)") -> None:
        """Отправить скриншот в vision-модель с пользовательским промптом."""
        self.status_changed.emit("Отправляю скриншот в модель…")
        self.messages.append(llm.ChatMessage(role="user", text=label))
        placeholder = llm.ChatMessage(role="assistant", text="…")
        self.messages.append(placeholder)
        self.messages_changed.emit()
        threading.Thread(
            target=self._do_vision_request, args=(png_bytes, placeholder), daemon=True
        ).start()

    def _do_vision_request(self, png_bytes: bytes, placeholder) -> None:
        try:
            reply = llm.complete_vision(
                api_key=self.api_key,
                model=self.vision_model,
                prompt=self.screenshot_prompt,
                png_bytes=png_bytes,
            )
            placeholder.text = reply
        except Exception as exc:  # noqa: BLE001
            placeholder.text = f"Ошибка скриншот-запроса: {exc}"
        finally:
            self.messages_changed.emit()

    def _do_audio_request(self, wav_bytes: bytes, placeholder) -> None:
        try:
            reply = llm.complete_audio(
                api_key=self.api_key,
                model=self.audio_model,
                prompt_context=self.prompt_context,
                wav_bytes=wav_bytes,
            )
            placeholder.text = reply
        except Exception as exc:  # noqa: BLE001
            placeholder.text = f"Ошибка аудио-запроса: {exc}"
        finally:
            self.messages_changed.emit()

    # --- отправка в DeepSeek (текст) ---

    def send(self, text: str) -> None:
        """Ручная отправка из поля ввода."""
        trimmed = (text or "").strip()
        if not trimmed or self.is_sending:
            return
        self.draft = ""
        self.draft_changed.emit("")
        self._dictation_base = ""
        self._restart_listening_after_send()
        self._dispatch_text(trimmed)

    def send_now(self) -> None:
        """Аудио-режим: немедленно отправить накопленную фразу (кнопка ➤).

        Если включён stop_mic_after_send — после отправки микрофон выключается,
        чтобы не слать лишних запросов. Выключаем с задержкой, чтобы рабочий
        поток успел захватить и отправить накопленный звук.
        """
        if self._transcriber and self.is_listening:
            self.status_changed.emit("Отправляю аудио в модель…")
            self._transcriber.flush()
            if self.stop_mic_after_send:
                QTimer.singleShot(600, self.stop_listening)

    def _on_hotkey_send(self) -> None:
        """Отправка по горячей клавише — учитывает текущий режим."""
        if self.response_mode == "audio":
            self.send_now()
        else:
            self.send(self.draft)

    def ask_more_detail(self) -> None:
        """Запросить более развёрнутый ответ по последнему вопросу (1 клик)."""
        if self.is_sending:
            return
        if not any(m.role == "user" for m in self.messages):
            return
        self._dispatch_text(
            "Подробнее: дай более развёрнутый и детальный ответ на мой предыдущий "
            "вопрос — с пояснениями, шагами и примерами, но по делу."
        )

    def ask_another_variant(self) -> None:
        """Сформировать другой вариант ответа на последний вопрос (1 клик)."""
        if self.is_sending:
            return
        if not any(m.role == "user" for m in self.messages):
            return
        self._dispatch_text(
            "Дай другой вариант ответа на мой предыдущий вопрос — иначе "
            "сформулируй, другим подходом, не повторяй прошлый ответ."
        )

    def _dispatch_text(self, trimmed: str) -> None:
        self.live_transcript = ""
        self.messages.append(llm.ChatMessage(role="user", text=trimmed))
        history = list(self.messages)
        placeholder = llm.ChatMessage(role="assistant", text="…")
        self.messages.append(placeholder)
        self.messages_changed.emit()

        self.is_sending = True
        self.sending_changed.emit(True)
        threading.Thread(
            target=self._do_request, args=(history, placeholder), daemon=True
        ).start()

    def _do_request(self, history, placeholder) -> None:
        try:
            reply = llm.complete(
                api_key=self.api_key,
                model=self.model,
                prompt_context=self.prompt_context,
                messages=history,
            )
            placeholder.text = reply
        except Exception as exc:  # noqa: BLE001
            placeholder.text = f"Ошибка запроса: {exc}"
        finally:
            self.is_sending = False
            self.sending_changed.emit(False)
            self.messages_changed.emit()

    def _restart_listening_after_send(self) -> None:
        # Не перезапускаем поток (это перезагружало бы модель Whisper и теряло
        # звук) — просто сбрасываем накопленный текст, прослушивание продолжается.
        if self.is_listening and self._transcriber:
            self._transcriber.reset_text()
        self.live_transcript = ""
        self._dictation_base = ""

    def clear_chat(self) -> None:
        self.messages.clear()
        self.live_transcript = ""
        self.draft = ""
        self._dictation_base = ""
        self.draft_changed.emit("")
        self.messages_changed.emit()

    def _append_system(self, text: str) -> None:
        self.messages.append(llm.ChatMessage(role="system", text=text))
        self.messages_changed.emit()
