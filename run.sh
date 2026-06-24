#!/usr/bin/env bash
# Запуск на macOS / Linux. Создаёт venv при первом запуске.
set -e
cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
  echo "Создаю виртуальное окружение…"
  python3 -m venv .venv
  ./.venv/bin/pip install --upgrade pip
fi

# Доустанавливаем/обновляем зависимости при КАЖДОМ запуске
# (иначе новые пакеты, например pynput для хоткеев, не появятся).
./.venv/bin/pip install -q --disable-pip-version-check -r requirements.txt

echo "Запускаю оверлей…  (окно-кнопка появится в правом нижнем углу экрана)"
exec ./.venv/bin/python -m presenter_overlay
