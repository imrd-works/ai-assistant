"""Захват микрофона (кроссплатформенно через sounddevice / PortAudio).

Аналог CoreAudio-части из macOS-версии: список устройств ввода и непрерывный
поток аудио в 16 кГц моно (формат, который ожидает Whisper).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, List, Optional

import numpy as np

try:
    import sounddevice as sd
except OSError as exc:  # PortAudio не установлен в системе
    sd = None
    _SD_IMPORT_ERROR: Optional[Exception] = exc
except ImportError as exc:
    sd = None
    _SD_IMPORT_ERROR = exc
else:
    _SD_IMPORT_ERROR = None

SAMPLE_RATE = 16_000  # Whisper работает в 16 кГц
BLOCK_SIZE = 1600     # 0.1 c аудио на блок


@dataclass
class AudioInputDevice:
    id: str          # стабильный идентификатор (имя + индекс)
    name: str
    index: int


class AudioError(Exception):
    pass


def available_input_devices() -> List[AudioInputDevice]:
    """Список устройств ввода. Пустой, если PortAudio недоступен."""
    if sd is None:
        return []
    devices: List[AudioInputDevice] = []
    try:
        for index, dev in enumerate(sd.query_devices()):
            if dev.get("max_input_channels", 0) > 0:
                name = dev.get("name", f"Audio Input {index}")
                devices.append(
                    AudioInputDevice(id=f"{index}:{name}", name=name, index=index)
                )
    except Exception:
        return []
    return devices


_LOOPBACK_HINTS = (
    "blackhole", "loopback", "monitor", "stereo mix", "стерео микшер",
    "vb-audio", "vb-cable", "cable output", "soundflower", "wasapi",
    "what u hear", "what you hear",
)


def is_loopback(name: str) -> bool:
    """Похоже ли устройство на источник СИСТЕМНОГО звука (loopback)."""
    low = name.lower()
    return any(h in low for h in _LOOPBACK_HINTS)


def preferred_microphone(devices: List[AudioInputDevice]) -> Optional[AudioInputDevice]:
    for d in devices:
        low = d.name.lower()
        if "microphone" in low or "mic" in low or "микрофон" in low:
            return d
    return devices[0] if devices else None


def resolve_device_index(device_id: str) -> Optional[int]:
    """Превращает сохранённый id в актуальный индекс устройства."""
    if not device_id:
        return None
    devices = available_input_devices()
    for d in devices:
        if d.id == device_id:
            return d.index
    # id мог устареть (устройство переподключили) — попробуем по имени
    name = device_id.split(":", 1)[-1]
    for d in devices:
        if d.name == name:
            return d.index
    return None


def device_name_for(device_id: str) -> str:
    devices = available_input_devices()
    if device_id:
        for d in devices:
            if d.id == device_id:
                return d.name
    pref = preferred_microphone(devices)
    return pref.name if pref else "по умолчанию"


def rms_level(samples: np.ndarray) -> float:
    """Нормализованный уровень громкости 0..1 (как в macOS-версии)."""
    if samples.size == 0:
        return 0.0
    mean_square = float(np.mean(np.square(samples, dtype=np.float64)))
    root = math.sqrt(mean_square)
    return min(max(root * 18.0, 0.0), 1.0)


def _resample_to_16k(mono: np.ndarray, src_rate: int) -> np.ndarray:
    """Линейный ресемплинг моно-сигнала в 16 кГц (качества хватает для речи)."""
    if src_rate == SAMPLE_RATE or mono.size == 0:
        return mono.astype(np.float32, copy=False)
    n_out = int(round(mono.size * SAMPLE_RATE / float(src_rate)))
    if n_out <= 0:
        return np.zeros(0, dtype=np.float32)
    x_old = np.linspace(0.0, 1.0, mono.size, endpoint=False)
    x_new = np.linspace(0.0, 1.0, n_out, endpoint=False)
    return np.interp(x_new, x_old, mono).astype(np.float32)


class AudioCapture:
    """Непрерывный захват аудио. На каждый блок вызывает on_block(float32 mono 16к).

    Поток открывается на НАТИВНОЙ частоте/каналах устройства (так надёжнее —
    многие устройства, включая BlackHole, не умеют 16 кГц/моно напрямую), а затем
    сигнал сводится в моно и ресемплится в 16 кГц для Whisper.
    """

    def __init__(self) -> None:
        self._stream: Optional["sd.InputStream"] = None
        self.on_block: Optional[Callable[[np.ndarray], None]] = None
        self._src_rate = SAMPLE_RATE

    @staticmethod
    def is_available() -> bool:
        return sd is not None

    @staticmethod
    def unavailable_reason() -> str:
        if sd is not None:
            return ""
        return (
            "Не удалось загрузить PortAudio/sounddevice. Установи библиотеку "
            "(pip install sounddevice) и системный PortAudio. "
            f"Детали: {_SD_IMPORT_ERROR}"
        )

    def _device_params(self, device_index: Optional[int]):
        """Нативная частота и число входных каналов устройства."""
        src_rate = 48000
        channels = 1
        try:
            idx = device_index
            if idx is None:
                idx = sd.default.device[0]
            info = sd.query_devices(idx)
            src_rate = int(round(info.get("default_samplerate") or 48000))
            max_in = int(info.get("max_input_channels") or 1)
            channels = 2 if max_in >= 2 else 1
        except Exception:
            pass
        return src_rate, channels

    def start(self, device_index: Optional[int]) -> None:
        if sd is None:
            raise AudioError(self.unavailable_reason())
        self.stop()

        src_rate, channels = self._device_params(device_index)
        self._src_rate = src_rate

        def make_callback(n_ch: int):
            def _callback(indata, frames, time_info, status):  # noqa: ANN001
                if self.on_block is None:
                    return
                if n_ch > 1 and indata.ndim > 1 and indata.shape[1] > 1:
                    mono = np.mean(indata, axis=1)
                else:
                    mono = indata.reshape(-1)
                mono16 = _resample_to_16k(
                    np.ascontiguousarray(mono, dtype=np.float32), self._src_rate
                )
                if mono16.size:
                    self.on_block(mono16)
            return _callback

        # Пробуем несколько конфигураций — от нативной к запасным.
        attempts = [
            (src_rate, channels),
            (src_rate, 1),
            (48000, 1),
            (44100, 1),
            (None, 1),  # None → частота по умолчанию PortAudio
        ]
        last_exc: Optional[Exception] = None
        for rate, ch in attempts:
            try:
                self._src_rate = int(rate) if rate else SAMPLE_RATE
                self._stream = sd.InputStream(
                    samplerate=rate if rate else None,
                    blocksize=0,  # PortAudio выберет оптимальный размер блока
                    device=device_index,
                    channels=ch,
                    dtype="float32",
                    callback=make_callback(ch),
                )
                self._stream.start()
                # Уточняем реальную частоту потока, если PortAudio её изменил.
                try:
                    self._src_rate = int(self._stream.samplerate)
                except Exception:
                    pass
                return
            except Exception as exc:  # PortAudioError и пр.
                last_exc = exc
                self._stream = None
                continue

        raise AudioError(
            "Не удалось открыть аудиовход. Проверь выбранное устройство и системные "
            f"разрешения на микрофон. Детали: {last_exc}"
        )

    def stop(self) -> None:
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
