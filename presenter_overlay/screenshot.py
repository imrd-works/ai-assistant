"""Захват экрана (кроссплатформенно через mss) → PNG-байты.

Используется для отправки скриншота в vision-модель: одна горячая клавиша —
снимок основного экрана уходит в нейросеть с твоим промптом.
"""

from __future__ import annotations

import numpy as np

try:
    import mss
    import mss.tools
except Exception as exc:  # noqa: BLE001 — библиотека может быть не установлена
    mss = None
    _IMPORT_ERROR = exc
else:
    _IMPORT_ERROR = None


def is_available() -> bool:
    return mss is not None


def unavailable_reason() -> str:
    if mss is not None:
        return ""
    return f"Не установлен mss (pip install mss). Детали: {_IMPORT_ERROR}"


def capture_screen(monitor: int = 1, region: dict | None = None,
                   logical_size: tuple | None = None) -> bytes:
    """PNG-байты снимка. Если задан region={x,y,w,h} в ЛОГИЧЕСКИХ координатах
    (относительно левого-верхнего угла экрана) и logical_size=(W,H) — снимаем
    весь экран и обрезаем до области, вычисляя масштаб из фактического размера
    снимка (надёжно при любом Retina/масштабировании)."""
    if mss is None:
        raise RuntimeError(unavailable_reason())
    with mss.mss() as sct:
        mons = sct.monitors
        idx = monitor if 0 <= monitor < len(mons) else (1 if len(mons) > 1 else 0)
        shot = sct.grab(mons[idx])
        w, h = int(shot.size.width), int(shot.size.height)

        if (region and logical_size and region.get("w", 0) > 0
                and region.get("h", 0) > 0 and logical_size[0] and logical_size[1]):
            # реальный масштаб = физические пиксели снимка / логические точки экрана
            sx = w / float(logical_size[0])
            sy = h / float(logical_size[1])
            left = max(0, int(round(region["x"] * sx)))
            top = max(0, int(round(region["y"] * sy)))
            right = min(w, int(round((region["x"] + region["w"]) * sx)))
            bottom = min(h, int(round((region["y"] + region["h"]) * sy)))
            if right > left and bottom > top:
                img = np.frombuffer(shot.rgb, dtype=np.uint8).reshape(h, w, 3)
                crop = np.ascontiguousarray(img[top:bottom, left:right])
                ch, cw = crop.shape[0], crop.shape[1]
                return mss.tools.to_png(crop.tobytes(), (cw, ch))

        return mss.tools.to_png(shot.rgb, shot.size)
