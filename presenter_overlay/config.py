"""Конфигурация и хранение настроек.

Настройки лежат в JSON-файле в домашней папке пользователя
(аналог UserDefaults из macOS-версии), чтобы ключ и параметры сохранялись
между запусками на любой ОС.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict

# Ключ по умолчанию берётся из переменной окружения, чтобы НЕ хранить секрет
# в репозитории (GitHub push protection блокирует пуш с реальными ключами).
# Можно задать PRESENTER_OVERLAY_API_KEY / OPENROUTER_API_KEY в окружении,
# либо просто ввести ключ в настройках панели (он сохранится локально).
DEFAULT_API_KEY = (
    os.environ.get("PRESENTER_OVERLAY_API_KEY")
    or os.environ.get("OPENROUTER_API_KEY")
    or ""
)

# Язык распознавания по умолчанию.
DEFAULT_LANGUAGE = "ru"

# Модель Whisper по умолчанию (faster-whisper): tiny / base / small / medium / large-v3.
# base — компромисс скорости и качества для CPU.
DEFAULT_WHISPER_MODEL = "base"

DEFAULT_MODEL = "deepseek-chat"

# Плотность (непрозрачность) фона области ответов, 25..100 (%).
DEFAULT_BG_OPACITY = 75

# Режим работы:
#   "text"  — Whisper распознаёт → текст уходит в DeepSeek (по умолчанию)
#   "audio" — звук фразы уходит напрямую в аудио-модель (без Whisper)
DEFAULT_RESPONSE_MODE = "text"

# Авто-ответ: завершённая фраза автоматически отправляется модели,
# не нужно жать кнопку отправки.
DEFAULT_AUTO_ANSWER = False

# Модель для прямого аудио-режима (должна принимать аудио на вход через OpenRouter).
# По умолчанию — Gemini 2.5 Flash: проверено, что у неё есть живые эндпоинты,
# дёшево ($0.30/1M текста, $1/1M аудио) и стабильно.
DEFAULT_AUDIO_MODEL = "google/gemini-2.5-flash"

# Аудио-модели OpenRouter с подтверждёнными эндпоинтами (id | подпись).
AUDIO_MODELS = [
    ("google/gemini-2.5-flash", "Gemini 2.5 Flash — дёшево, рекомендуется"),
    ("openai/gpt-audio-mini", "GPT Audio Mini (дешевле OpenAI)"),
    ("openai/gpt-audio", "GPT Audio (OpenAI, дороже)"),
    ("google/gemini-2.5-pro", "Gemini 2.5 Pro (дороже, точнее)"),
]

# Старые дефолты, которые у части аккаунтов OpenRouter не работали — мигрируем.
_DEPRECATED_AUDIO_MODELS = {
    "openai/gpt-4o-audio-preview",
    "google/gemini-2.0-flash-001",
}

# Vision-модель для скриншотов (должна принимать изображения).
DEFAULT_VISION_MODEL = "google/gemini-2.5-flash"
VISION_MODELS = [
    ("google/gemini-2.5-flash", "Gemini 2.5 Flash — дёшево, рекомендуется"),
    ("openai/gpt-4o-mini", "GPT-4o mini (OpenAI)"),
    ("openai/gpt-4o", "GPT-4o (OpenAI, дороже)"),
    ("google/gemini-2.5-pro", "Gemini 2.5 Pro (точнее, дороже)"),
]

# Что делать со скриншотом по умолчанию (можно изменить в настройках).
DEFAULT_SCREENSHOT_PROMPT = (
    "Посмотри на скриншот экрана и помоги по существу: если есть ошибки — укажи "
    "их и предложи исправление; если это незавершённый текст или код — допиши; "
    "иначе кратко ответь по тому, что на экране. Отвечай на русском."
)


def _config_path() -> Path:
    # Уважает XDG на Linux, иначе кладёт рядом с домашней папкой.
    base = os.environ.get("XDG_CONFIG_HOME")
    root = Path(base) if base else Path.home() / ".config"
    folder = root / "presenter-overlay"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "settings.json"


class Settings:
    """Простое key-value хранилище настроек с сохранением в JSON."""

    def __init__(self) -> None:
        self._path = _config_path()
        self._data: Dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        try:
            if self._path.exists():
                self._data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self._data = {}

    def save(self) -> None:
        try:
            self._path.write_text(
                json.dumps(self._data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError:
            pass

    def get(self, key: str, default: Any = "") -> Any:
        value = self._data.get(key, default)
        return value if value is not None else default

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value

    # --- Типизированные удобные свойства ---

    @property
    def api_key(self) -> str:
        saved = self.get("deepseek_key", "")
        return saved if saved else DEFAULT_API_KEY

    @property
    def model(self) -> str:
        return self.get("deepseek_model", DEFAULT_MODEL) or DEFAULT_MODEL

    @property
    def prompt_context(self) -> str:
        return self.get("prompt_context", "")

    @property
    def language(self) -> str:
        return self.get("language", DEFAULT_LANGUAGE) or DEFAULT_LANGUAGE

    @property
    def whisper_model(self) -> str:
        return self.get("whisper_model", DEFAULT_WHISPER_MODEL) or DEFAULT_WHISPER_MODEL

    @property
    def audio_input_id(self) -> str:
        return self.get("audio_input_id", "")

    @property
    def response_mode(self) -> str:
        return self.get("response_mode", DEFAULT_RESPONSE_MODE) or DEFAULT_RESPONSE_MODE

    @property
    def auto_answer(self) -> bool:
        return bool(self.get("auto_answer", DEFAULT_AUTO_ANSWER))

    @property
    def bg_opacity(self) -> int:
        try:
            return int(self.get("bg_opacity", DEFAULT_BG_OPACITY))
        except (TypeError, ValueError):
            return DEFAULT_BG_OPACITY

    @property
    def hotkey_toggle_mic(self) -> str:
        return self.get("hotkey_toggle_mic", "")

    @property
    def hotkey_send(self) -> str:
        return self.get("hotkey_send", "")

    @property
    def hotkey_screenshot(self) -> str:
        return self.get("hotkey_screenshot", "")

    @property
    def screenshot_region(self):
        """Область скриншота в логических координатах {x,y,w,h} или None (весь экран)."""
        r = self.get("screenshot_region", None)
        if isinstance(r, dict) and all(k in r for k in ("x", "y", "w", "h")):
            return r
        return None

    @property
    def vision_model(self) -> str:
        return self.get("vision_model", DEFAULT_VISION_MODEL) or DEFAULT_VISION_MODEL

    @property
    def screenshot_prompt(self) -> str:
        return self.get("screenshot_prompt", DEFAULT_SCREENSHOT_PROMPT) or DEFAULT_SCREENSHOT_PROMPT

    @property
    def stop_mic_after_send(self) -> bool:
        # По умолчанию в аудио-режиме после ручной отправки микрофон выключается.
        return bool(self.get("stop_mic_after_send", True))

    @property
    def audio_model(self) -> str:
        value = self.get("audio_model", DEFAULT_AUDIO_MODEL) or DEFAULT_AUDIO_MODEL
        # Авто-миграция: старые дефолты у части аккаунтов OpenRouter не работали.
        if value in _DEPRECATED_AUDIO_MODELS:
            return DEFAULT_AUDIO_MODEL
        return value
