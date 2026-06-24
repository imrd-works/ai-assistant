# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller-спецификация для Суфлёр (Windows + macOS).

Сборка:
    pip install pyinstaller
    pyinstaller Sufler.spec

Результат:
    Windows → dist/Sufler/Sufler.exe (папка)
    macOS   → dist/Sufler.app
"""

import os
import sys
from PyInstaller.utils.hooks import collect_all

APP_NAME = "Sufler"

# Иконки опциональны — если файла нет, собираем без неё (без ошибки).
_ico = "packaging/icon.ico"
_icns = "packaging/icon.icns"
win_icon = _ico if os.path.exists(_ico) else None
mac_icon = _icns if os.path.exists(_icns) else None

# Веб-интерфейс (1:1 макет) обязательно кладём внутрь бандла.
datas = [("presenter_overlay/web/index.html", "presenter_overlay/web")]
binaries = []
hiddenimports = ["PySide6.QtWebEngineWidgets", "PySide6.QtWebChannel"]

# Тяжёлые ML/медиа-зависимости подбираем целиком, если установлены.
for pkg in ("faster_whisper", "ctranslate2", "av", "tokenizers", "onnxruntime"):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception:
        pass

a = Analysis(
    ["run_app.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    console=False,            # без чёрного окна консоли
    disable_windowed_traceback=False,
    icon=win_icon,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    name=APP_NAME,
)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name=APP_NAME + ".app",
        icon=mac_icon,
        bundle_identifier="com.sufler.overlay",
        info_plist={
            "CFBundleDisplayName": "Суфлёр",
            "CFBundleName": "Суфлёр",
            "NSMicrophoneUsageDescription":
                "Суфлёр слушает микрофон для распознавания речи.",
            "NSScreenCaptureUsageDescription":
                "Суфлёр делает скриншот экрана по запросу пользователя.",
            # Фоновое приложение без иконки в Dock (оверлей поверх окон).
            "LSUIElement": True,
        },
    )
