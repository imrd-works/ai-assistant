@echo off
REM Запуск на Windows. Создаёт venv при первом запуске.
cd /d "%~dp0"

if not exist ".venv" (
  echo Создаю виртуальное окружение...
  python -m venv .venv
  call .venv\Scripts\activate.bat
  python -m pip install --upgrade pip
) else (
  call .venv\Scripts\activate.bat
)

REM Доустанавливаем зависимости при каждом запуске (например pynput для хоткеев)
pip install -q -r requirements.txt

python -m presenter_overlay
