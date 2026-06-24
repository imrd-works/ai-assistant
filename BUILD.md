# Сборка и обновления

## Что где
- `run_app.py` — точка входа для PyInstaller (локально работает и `python -m presenter_overlay`).
- `Sufler.spec` — спецификация сборки (Windows + macOS), кладёт внутрь `web/index.html`.
- `packaging/windows/installer.iss` — установщик Windows (Inno Setup).
- `.github/workflows/build.yml` — CI: собирает по тегу и выкладывает в Releases.
- `presenter_overlay/updater.py` — проверка обновлений через GitHub Releases.

## Локальная сборка

Windows:
```bat
pip install -r requirements.txt pyinstaller
pyinstaller Sufler.spec --noconfirm
:: установщик (нужен Inno Setup):
iscc packaging\windows\installer.iss
:: готово: dist\Sufler-Setup-*.exe
```

macOS:
```bash
pip install -r requirements.txt pyinstaller
pyinstaller Sufler.spec --noconfirm
# .app лежит в dist/Sufler.app ; собрать dmg:
hdiutil create -volname "Суфлёр" -srcfolder dist/Sufler.app -ov -format UDZO dist/Sufler.dmg
```

## Автосборка (GitHub Actions)
1. Запушить проект в GitHub.
2. Поставить тег версии и запушить его:
   ```bash
   git tag v2.1.0
   git push origin v2.1.0
   ```
3. CI соберёт Windows-installer и macOS-dmg и прикрепит их к Release `v2.1.0`.

Версию приложения держи в `presenter_overlay/__init__.py` (`__version__`) — она должна совпадать с тегом.

## Как работают обновления
1. Включи проверку: задай свой репозиторий в `presenter_overlay/updater.py`
   (`UPDATE_REPO = "owner/repo"`) или переменной окружения `PRESENTER_OVERLAY_REPO`.
2. При старте приложение в фоне спрашивает у GitHub последний релиз и, если он
   новее `__version__`, пишет в чат сообщение со ссылкой на загрузку.
3. Выпуск обновления = новый тег → CI собирает → файлы в Releases → пользователи
   видят уведомление.

Это «простой» уровень (уведомление + ссылка). Тихий фоновый авто-апдейт можно
добавить позже через `tufup` (кроссплатформенно) или Sparkle/WinSparkle.

## Подпись (обязательно для массовой раздачи)
- macOS: Apple Developer ($99/год) + `codesign` + нотаризация (`notarytool`), иначе
  приложение не запустится у пользователей.
- Windows: сертификат для подписи кода + `signtool`, иначе SmartScreen предупреждает.
Секреты для подписи хранить в GitHub → Settings → Secrets и добавить шаги в workflow.
