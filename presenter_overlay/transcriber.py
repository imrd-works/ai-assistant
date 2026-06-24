"""Распознавание речи через локальный Whisper (faster-whisper).

Near-real-time: аудио непрерывно копится в буфер текущей фразы. Пока человек
говорит, каждые ~0.8 с буфер прогоняется через Whisper и частичный текст сразу
уходит в поле ввода (callback on_update). На паузе фраза «фиксируется» —
добавляется к committed_text, и начинается новая. Так все проговорённые слова
тут же видны на экране, а итоговый текст не теряется при паузах.

Ошибки распознавания потом исправляет DeepSeek по контексту (см. llm.py).
"""

from __future__ import annotations

import io
import queue
import threading
import time
import wave
from typing import Callable, Optional

import numpy as np

from .audio import SAMPLE_RATE, AudioCapture, rms_level


def encode_wav(audio: np.ndarray, sample_rate: int = SAMPLE_RATE) -> bytes:
    """float32 mono (-1..1) → WAV-байты (PCM 16-bit), для отправки аудио-модели."""
    clipped = np.clip(audio, -1.0, 1.0)
    pcm16 = (clipped * 32767.0).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm16.tobytes())
    return buf.getvalue()

try:
    from faster_whisper import WhisperModel
except Exception as exc:  # noqa: BLE001 — библиотека может быть не установлена
    WhisperModel = None
    _FW_IMPORT_ERROR: Optional[Exception] = exc
else:
    _FW_IMPORT_ERROR = None


# Параметры near-real-time распознавания
PARTIAL_INTERVAL = 0.6   # как часто прогонять текущую фразу через Whisper
SILENCE_TIMEOUT = 0.8    # пауза, после которой фраза считается законченной
VOICE_THRESHOLD = 0.012  # порог энергии для детекции речи (0..1)
MAX_SEGMENT_SEC = 25.0   # принудительная фиксация длинной фразы

# Пороги отсева «галлюцинаций» Whisper (выдумок на музыке/тишине).
# Смягчены, чтобы живая речь точно показывалась, но музыкальный мусор отсеивался.
NO_SPEECH_MAX = 0.75     # если вероятность «не речь» выше — отбрасываем
LOGPROB_MIN = -1.2       # слишком неуверенный текст — отбрасываем
COMPRESSION_MAX = 2.6    # очень повторяющийся текст (мусор) — отбрасываем

# Частые галлюцинации Whisper на не-речи (музыка, тишина, шум). Сравниваем по
# нормализованному тексту; короткие сегменты, целиком совпавшие — выкидываем.
HALLUCINATION_PHRASES = {
    "спокойная музыка", "тихая музыка", "играет музыка", "музыка",
    "грустная музыка", "тревожная музыка", "динамичная музыка",
    "аплодисменты", "смех", "продолжение следует", "продолжение следует...",
    "спасибо за просмотр", "спасибо за внимание", "субтитры",
    "субтитры сделал", "субтитры создал", "редактор субтитров",
    "корректор", "до новых встреч", "всем пока",
    "music", "thanks for watching", "thank you for watching",
    "please subscribe", "subscribe", "applause", "silence",
    "[музыка]", "[аплодисменты]", "(музыка)",
}


def _normalize(text: str) -> str:
    return text.strip().strip(".!?…-—\"'«»() ").lower()


class TranscriberError(Exception):
    pass


class WhisperTranscriber:
    """Управляет захватом аудио и потоковым распознаванием Whisper."""

    def __init__(
        self,
        model_size: str = "base",
        language: str = "ru",
        mode: str = "whisper",
    ) -> None:
        self.model_size = model_size
        self.language = language
        # "whisper" — распознаём текст; "audio" — отдаём звук фразы как WAV
        self.mode = mode
        # сбрасывать накопленный текст после каждой завершённой фразы
        # (нужно для авто-ответа, чтобы фразы были независимыми)
        self.reset_after_final = False
        # авто-фиксация фразы на паузе. Если False — фраза копится и уходит только
        # по ручному flush() (кнопка «Отправить» в аудио-режиме без авто-ответа).
        self.auto_finalize = True
        self._flush_event = threading.Event()

        self.on_update: Optional[Callable[[str], None]] = None
        self.on_final: Optional[Callable[[str], None]] = None        # текст фразы
        self.on_final_audio: Optional[Callable[[bytes], None]] = None  # WAV фразы
        self.on_audio_level: Optional[Callable[[float], None]] = None
        self.on_error: Optional[Callable[[str], None]] = None
        self.on_status: Optional[Callable[[str], None]] = None

        self._capture = AudioCapture()
        self._model: Optional["WhisperModel"] = None

        self._audio_q: "queue.Queue[np.ndarray]" = queue.Queue()
        self._worker: Optional[threading.Thread] = None
        self._stop_flag = threading.Event()

        self._committed_text = ""

    # --- Доступность ---

    def dependency_error(self) -> str:
        if not AudioCapture.is_available():
            return AudioCapture.unavailable_reason()
        # Whisper нужен только в текстовом режиме
        if self.mode == "whisper" and WhisperModel is None:
            return (
                "Не установлен faster-whisper. Выполни: pip install faster-whisper. "
                f"Детали: {_FW_IMPORT_ERROR}"
            )
        return ""

    # --- Жизненный цикл ---

    def start(self, device_index: Optional[int]) -> None:
        err = self.dependency_error()
        if err:
            raise TranscriberError(err)

        self.stop()
        self._stop_flag.clear()
        self._committed_text = ""
        # очищаем очередь
        while not self._audio_q.empty():
            try:
                self._audio_q.get_nowait()
            except queue.Empty:
                break

        self._capture.on_block = self._on_audio_block
        self._capture.start(device_index)

        self._worker = threading.Thread(target=self._run, daemon=True)
        self._worker.start()

    def reset_text(self) -> None:
        """Сбросить накопленный текст, не останавливая прослушивание/модель.

        Используется после ручной отправки: поле очищается, а распознавание
        продолжается без долгой перезагрузки модели Whisper.
        """
        self._committed_text = ""

    def flush(self) -> None:
        """Немедленно зафиксировать и отправить накопленную фразу (не дожидаясь
        тишины). Кнопка «Отправить» в аудио-режиме."""
        self._flush_event.set()

    def stop(self) -> None:
        self._stop_flag.set()
        self._capture.on_block = None
        self._capture.stop()
        worker = self._worker
        if worker and worker.is_alive() and worker is not threading.current_thread():
            worker.join(timeout=2.0)
        self._worker = None
        self._emit_level(0.0)

    # --- Внутреннее ---

    def _ensure_model(self) -> None:
        if self._model is not None:
            return
        self._emit_status(f"Загружаю модель Whisper «{self.model_size}»…")
        # int8 на CPU — самый универсальный и лёгкий режим.
        self._model = WhisperModel(
            self.model_size, device="cpu", compute_type="int8"
        )
        self._emit_status("Модель загружена. Говорите…")

    def _on_audio_block(self, block: np.ndarray) -> None:
        # Уровень считаем прямо в аудио-потоке (дёшево), сам блок — в очередь.
        self._emit_level(rms_level(block))
        self._audio_q.put(block)

    def _run(self) -> None:
        if self.mode == "whisper":
            try:
                self._ensure_model()
            except Exception as exc:  # noqa: BLE001
                self._emit_error(f"Не удалось загрузить Whisper: {exc}")
                return
        else:
            self._emit_status("Аудио-режим: слушаю, фраза уйдёт в модель целиком…")

        segment = np.zeros(0, dtype=np.float32)
        start_ts = time.monotonic()
        last_voice_ts = start_ts
        last_partial_ts = 0.0
        seg_started_ts = start_ts
        had_voice = False
        # Диагностика входа (помогает с BlackHole)
        blocks_seen = 0
        max_level = 0.0
        diag_done = False

        while not self._stop_flag.is_set():
            # Собираем все доступные блоки (с небольшим ожиданием)
            try:
                block = self._audio_q.get(timeout=0.1)
            except queue.Empty:
                block = None

            now = time.monotonic()

            if block is not None:
                blocks_seen += 1
                max_level = max(max_level, rms_level(block))
                segment = np.concatenate([segment, block])
                if rms_level(block) >= VOICE_THRESHOLD:
                    last_voice_ts = now
                    had_voice = True

            # Через 4 c проверяем, идёт ли вообще звук со входа
            if not diag_done and now - start_ts > 4.0:
                diag_done = True
                if blocks_seen == 0:
                    self._emit_status(
                        "Вход не отдаёт звук. Проверь выбранное устройство и "
                        "разрешение на микрофон."
                    )
                elif max_level < 0.004:
                    self._emit_status(
                        "Вход есть, но тишина. Если это BlackHole — направь вывод "
                        "системы в Multi-Output (звук должен идти и в BlackHole)."
                    )

            # Частичное распознавание, пока говорим (только в текстовом режиме)
            if (
                self.mode == "whisper"
                and had_voice
                and segment.size > SAMPLE_RATE * 0.4
                and now - last_partial_ts >= PARTIAL_INTERVAL
            ):
                last_partial_ts = now
                partial = self._transcribe(segment)
                if partial:
                    self._emit_update(self._combine(self._committed_text, partial))

            silent_for = now - last_voice_ts
            too_long = now - seg_started_ts > MAX_SEGMENT_SEC

            # Ручная отправка (кнопка) — фиксируем сразу, не дожидаясь тишины.
            flush_now = self._flush_event.is_set()
            if flush_now:
                self._flush_event.clear()

            # Авто-фиксация на паузе (если включена) или по таймауту длины
            auto_trigger = (
                had_voice and (
                    too_long or (self.auto_finalize and silent_for >= SILENCE_TIMEOUT)
                )
            )

            if segment.size > 0 and (flush_now or auto_trigger):
                self._finalize_segment(segment)
                # начинаем новую фразу
                segment = np.zeros(0, dtype=np.float32)
                had_voice = False
                seg_started_ts = now
                last_partial_ts = 0.0
            elif self.auto_finalize and not had_voice and segment.size > SAMPLE_RATE * 3:
                # авто-режим: копилась только тишина — не держим память
                segment = segment[-SAMPLE_RATE:]
                seg_started_ts = now

    def _finalize_segment(self, segment: np.ndarray) -> None:
        if self.mode == "audio":
            # Отдаём звук фразы целиком — модель сама «услышит» и ответит.
            if segment.size > SAMPLE_RATE * 0.3:
                self._emit_final_audio(encode_wav(segment))
            return

        final = self._transcribe(segment)
        if not final:
            return
        self._emit_final(final)
        if self.reset_after_final:
            self._committed_text = ""
            self._emit_update("")  # очищаем поле под следующую фразу
        else:
            self._committed_text = self._combine(self._committed_text, final)
            self._emit_update(self._committed_text)

    def _transcribe(self, audio: np.ndarray) -> str:
        if self._model is None or audio.size == 0:
            return ""
        try:
            # vad_filter=True (Silero VAD) отсекает не-речь (музыку/тишину), на
            # которой Whisper любит выдумывать «Спокойная музыка» и пр.
            # Дополнительно фильтруем сегменты по уверенности и чёрному списку.
            # vad_filter=False: Silero VAD на коротких частичных окнах глушил
            # живую речь, и текст не появлялся. Не-речь отсекаем сами — по энергии
            # (порог VOICE_THRESHOLD) + по no_speech_prob и чёрному списку ниже.
            language = None if self.language in ("", "auto") else self.language
            segments, _info = self._model.transcribe(
                audio,
                language=language,
                beam_size=1,
                temperature=0.0,
                vad_filter=False,
                condition_on_previous_text=False,
            )
            kept = [s.text.strip() for s in segments if self._is_real_speech(s)]
            return " ".join(t for t in kept if t).strip()
        except Exception as exc:  # noqa: BLE001
            self._emit_error(f"Ошибка распознавания: {exc}")
            return ""

    @staticmethod
    def _is_real_speech(seg) -> bool:
        """Отбраковывает галлюцинации Whisper на музыке/тишине."""
        no_speech = getattr(seg, "no_speech_prob", 0.0) or 0.0
        logprob = getattr(seg, "avg_logprob", 0.0) or 0.0
        compression = getattr(seg, "compression_ratio", 0.0) or 0.0
        if no_speech > NO_SPEECH_MAX:
            return False
        if logprob < LOGPROB_MIN:
            return False
        if compression > COMPRESSION_MAX:
            return False
        if _normalize(seg.text) in HALLUCINATION_PHRASES:
            return False
        return True

    @staticmethod
    def _combine(base: str, addition: str) -> str:
        base = base.strip()
        addition = addition.strip()
        if not base:
            return addition
        if not addition:
            return base
        return f"{base} {addition}"

    # --- безопасные вызовы колбэков ---

    def _emit_update(self, text: str) -> None:
        if self.on_update:
            self.on_update(text)

    def _emit_final(self, text: str) -> None:
        if self.on_final:
            self.on_final(text)

    def _emit_final_audio(self, wav_bytes: bytes) -> None:
        if self.on_final_audio:
            self.on_final_audio(wav_bytes)

    def _emit_level(self, level: float) -> None:
        if self.on_audio_level:
            self.on_audio_level(level)

    def _emit_error(self, message: str) -> None:
        if self.on_error:
            self.on_error(message)

    def _emit_status(self, message: str) -> None:
        if self.on_status:
            self.on_status(message)
