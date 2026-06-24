"""Клиент к DeepSeek (API совместим с OpenAI).

Авто-роутинг по типу ключа:
  - sk-or-...  → OpenRouter (https://openrouter.ai/api/v1)
  - иначе      → нативный DeepSeek (https://api.deepseek.com)

Системный промпт делает из модели «суфлёра»: ей приходят обрывочные фразы из
распознавания речи (Whisper), и она должна по контексту восстановить смысл,
исправить ошибки распознавания и дать короткий готовый ответ.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import List, Dict

import requests


@dataclass
class ChatMessage:
    role: str  # "user" | "assistant" | "system"
    text: str


class APIError(Exception):
    pass


BASE_SYSTEM_PROMPT = (
    "Ты — незаметный суфлёр для человека во время живого разговора или выступления.\n"
    "Тебе приходят фразы из распознавания речи (Whisper): они могут быть обрывочными, "
    "с ошибками распознавания и без полного контекста.\n"
    "Сначала по смыслу и контексту мысленно исправь вероятные ошибки распознавания "
    "(похожие по звучанию слова, обрезанные окончания), затем дай ответ.\n"
    "Используй тему и дополнительный контекст ниже, чтобы восстановить самый вероятный "
    "смысл услышанного и дать самый близкий, практичный и применимый ответ.\n"
    "Отвечай на том же языке, кратко и по делу. Если это вопрос — дай готовый ответ, "
    "который можно сразу произнести вслух. Если это реплика без вопроса — предложи "
    "уместное продолжение или реакцию.\n"
    "Не выдумывай факты. Если уверенности мало, дай осторожную формулировку."
)


def build_messages_payload(
    prompt_context: str, messages: List[ChatMessage]
) -> List[Dict[str, str]]:
    trimmed_context = (prompt_context or "").strip()
    if trimmed_context:
        system_prompt = (
            f"{BASE_SYSTEM_PROMPT}\n\nКонтекст темы:\n{trimmed_context}"
        )
    else:
        system_prompt = BASE_SYSTEM_PROMPT

    payload: List[Dict[str, str]] = [{"role": "system", "content": system_prompt}]
    for m in messages:
        if m.role == "user":
            payload.append({"role": "user", "content": m.text})
        elif m.role == "assistant":
            if m.text and m.text != "…":
                payload.append({"role": "assistant", "content": m.text})
        elif m.role == "system":
            payload.append({"role": "system", "content": m.text})
    return payload


AUDIO_SYSTEM_PROMPT = (
    "Ты — незаметный суфлёр. Тебе приходит АУДИО речи (твой микрофон или "
    "системный звук разговора). Распознай речь сам и ответь по существу.\n"
    "Отвечай на языке говорящего, кратко и по делу. Если это вопрос — дай "
    "готовый ответ, который можно сразу произнести вслух. Если это реплика без "
    "вопроса — предложи уместное продолжение. Не выдумывай факты."
)


def _headers(api_key: str, is_openrouter: bool) -> Dict[str, str]:
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    if is_openrouter:
        headers["HTTP-Referer"] = "https://presenter.overlay.local"
        headers["X-Title"] = "PresenterOverlay"
    return headers


def _endpoint(is_openrouter: bool) -> str:
    return (
        "https://openrouter.ai/api/v1/chat/completions"
        if is_openrouter
        else "https://api.deepseek.com/chat/completions"
    )


def complete_audio(
    api_key: str,
    model: str,
    prompt_context: str,
    wav_bytes: bytes,
    timeout: float = 60.0,
) -> str:
    """Прямой аудио-режим: отправляет звук фразы в аудио-модель и возвращает ответ.

    Модель должна принимать аудио (например, openai/gpt-4o-audio-preview).
    Формат content — OpenAI-совместимый input_audio (base64 WAV).
    """
    if not api_key:
        raise APIError("Не задан API-ключ (открой настройки в панели)")

    is_openrouter = api_key.startswith("sk-or-")
    system_prompt = AUDIO_SYSTEM_PROMPT
    ctx = (prompt_context or "").strip()
    if ctx:
        system_prompt += f"\n\nКонтекст темы:\n{ctx}"

    b64 = base64.b64encode(wav_bytes).decode("ascii")
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Ответь на сказанное в аудио."},
                    {
                        "type": "input_audio",
                        "input_audio": {"data": b64, "format": "wav"},
                    },
                ],
            },
        ],
        "stream": False,
    }

    try:
        resp = requests.post(
            _endpoint(is_openrouter),
            headers=_headers(api_key, is_openrouter),
            json=body,
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise APIError(f"Сеть недоступна: {exc}") from exc

    if not (200 <= resp.status_code < 300):
        hint = {
            401: "Неверный API-ключ. Проверь ключ OpenRouter в настройках.",
            402: "Не хватает баланса на OpenRouter. Для аудио нужен баланс от "
                 "$0.50 — пополни кредиты на openrouter.ai → Credits.",
            404: "У выбранной модели нет доступных провайдеров. Выбери другую "
                 "аудио-модель в настройках.",
            429: "Слишком много запросов (rate limit). Подожди немного.",
        }.get(resp.status_code,
              "Проверь, что выбранная модель принимает аудио, и баланс OpenRouter.")
        raise APIError(f"HTTP {resp.status_code}: {hint}\n{resp.text or '—'}")

    try:
        content = resp.json()["choices"][0]["message"]["content"]
        if isinstance(content, list):  # некоторые модели возвращают части
            content = " ".join(
                part.get("text", "") for part in content if isinstance(part, dict)
            )
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise APIError(f"Не удалось разобрать ответ сервера: {exc}") from exc

    return (content or "").strip() or "(пустой ответ)"


def complete_vision(
    api_key: str,
    model: str,
    prompt: str,
    png_bytes: bytes,
    timeout: float = 90.0,
) -> str:
    """Отправляет скриншот (PNG) в vision-модель с инструкцией prompt.

    Модель должна принимать изображения (например, google/gemini-2.5-flash,
    openai/gpt-4o). Формат — OpenAI-совместимый image_url (data-URI base64).
    """
    if not api_key:
        raise APIError("Не задан API-ключ (открой настройки в панели)")

    is_openrouter = api_key.startswith("sk-or-")
    b64 = base64.b64encode(png_bytes).decode("ascii")
    instruction = (prompt or "").strip() or (
        "Посмотри на скриншот и помоги по существу того, что на экране."
    )
    body = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": instruction},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{b64}"},
                    },
                ],
            }
        ],
        "stream": False,
    }

    try:
        resp = requests.post(
            _endpoint(is_openrouter),
            headers=_headers(api_key, is_openrouter),
            json=body,
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise APIError(f"Сеть недоступна: {exc}") from exc

    if not (200 <= resp.status_code < 300):
        hint = {
            401: "Неверный API-ключ.",
            402: "Не хватает баланса на OpenRouter — пополни кредиты.",
            404: "У модели нет провайдеров или она не принимает изображения. "
                 "Выбери vision-модель (например, google/gemini-2.5-flash).",
            429: "Слишком много запросов, подожди немного.",
        }.get(resp.status_code, "Проверь vision-модель и баланс OpenRouter.")
        raise APIError(f"HTTP {resp.status_code}: {hint}\n{resp.text or '—'}")

    try:
        content = resp.json()["choices"][0]["message"]["content"]
        if isinstance(content, list):
            content = " ".join(
                p.get("text", "") for p in content if isinstance(p, dict)
            )
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise APIError(f"Не удалось разобрать ответ сервера: {exc}") from exc

    return (content or "").strip() or "(пустой ответ)"


def _resolve_model(model: str, is_openrouter: bool) -> str:
    if not is_openrouter:
        return model
    # OpenRouter требует префикс провайдера в имени модели.
    mapping = {
        "deepseek-reasoner": "deepseek/deepseek-r1",
        "deepseek-chat": "deepseek/deepseek-chat",
    }
    if model in mapping:
        return mapping[model]
    return model if "/" in model else f"deepseek/{model}"


def complete(
    api_key: str,
    model: str,
    prompt_context: str,
    messages: List[ChatMessage],
    timeout: float = 60.0,
) -> str:
    """Синхронный запрос к модели. Возвращает текст ответа или бросает APIError."""
    if not api_key:
        raise APIError("Не задан API-ключ DeepSeek (открой настройки в панели)")

    is_openrouter = api_key.startswith("sk-or-")
    url = (
        "https://openrouter.ai/api/v1/chat/completions"
        if is_openrouter
        else "https://api.deepseek.com/chat/completions"
    )
    resolved_model = _resolve_model(model, is_openrouter)

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    if is_openrouter:
        headers["HTTP-Referer"] = "https://presenter.overlay.local"
        headers["X-Title"] = "PresenterOverlay"

    body = {
        "model": resolved_model,
        "messages": build_messages_payload(prompt_context, messages),
        "stream": False,
    }

    try:
        resp = requests.post(url, headers=headers, json=body, timeout=timeout)
    except requests.RequestException as exc:
        raise APIError(f"Сеть недоступна: {exc}") from exc

    if not (200 <= resp.status_code < 300):
        raise APIError(f"HTTP {resp.status_code}: {resp.text or '—'}")

    try:
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise APIError(f"Не удалось разобрать ответ сервера: {exc}") from exc

    return (content or "").strip() or "(пустой ответ)"
