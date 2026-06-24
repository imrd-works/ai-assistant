"""Простая проверка обновлений через GitHub Releases.

Логика: при старте приложение в фоне спрашивает у GitHub последнюю версию,
сравнивает с текущей (__version__) и, если есть новее, сообщает в чат ссылку на
загрузку. Никаких блокировок UI, любые сетевые ошибки тихо игнорируются.

Чтобы включить — впиши свой репозиторий в UPDATE_REPO (или переменную окружения
PRESENTER_OVERLAY_REPO), например "ivan/presenter-overlay".
"""

from __future__ import annotations

import json
import os
import threading
import urllib.request

from . import __version__

# Репозиторий в формате "owner/repo". Пусто → проверка обновлений отключена.
UPDATE_REPO = os.environ.get("PRESENTER_OVERLAY_REPO", "")

_API = "https://api.github.com/repos/{repo}/releases/latest"
_TIMEOUT = 6


def _parse_version(text: str):
    """'v2.1.0' / '2.1.0' → (2, 1, 0). Нечисловые части → 0."""
    text = (text or "").strip().lstrip("vV")
    parts = []
    for chunk in text.split("."):
        num = "".join(ch for ch in chunk if ch.isdigit())
        parts.append(int(num) if num else 0)
    return tuple(parts) if parts else (0,)


def _is_newer(remote: str, current: str) -> bool:
    r, c = _parse_version(remote), _parse_version(current)
    n = max(len(r), len(c))
    r += (0,) * (n - len(r))
    c += (0,) * (n - len(c))
    return r > c


def check_for_update(repo: str = UPDATE_REPO, current: str = __version__):
    """Возвращает dict(version, url) если доступна новее, иначе None.

    Синхронная; кидать в фоновый поток (см. check_async)."""
    if not repo:
        return None
    try:
        req = urllib.request.Request(
            _API.format(repo=repo),
            headers={"Accept": "application/vnd.github+json",
                     "User-Agent": "presenter-overlay"},
        )
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None

    tag = data.get("tag_name") or data.get("name") or ""
    if not tag or not _is_newer(tag, current):
        return None
    return {
        "version": tag.lstrip("vV"),
        "url": data.get("html_url") or f"https://github.com/{repo}/releases/latest",
    }


def check_async(state, repo: str = UPDATE_REPO) -> None:
    """Фоновая проверка: при наличии обновления пишет сообщение в чат.

    state — AppState; используем потокобезопасный сигнал через _append_system,
    который сам эмитит messages_changed (доставляется в UI-поток)."""
    if not repo:
        return

    def _run():
        info = check_for_update(repo)
        if info:
            state._append_system(
                f"🔔 Доступно обновление: версия {info['version']}. "
                f"Скачать: {info['url']}"
            )

    threading.Thread(target=_run, daemon=True).start()
