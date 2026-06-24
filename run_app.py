"""Точка входа для PyInstaller (он не умеет запускать пакет через -m).

Локально по-прежнему можно запускать `python -m presenter_overlay`.
"""

import sys

from presenter_overlay.app import main

if __name__ == "__main__":
    sys.exit(main())
