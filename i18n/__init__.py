"""Lightweight EN/RU translation for PhoneMover.

We deliberately avoid Qt Linguist's .ts/.qm toolchain (extra build step) and use
a plain dict lookup instead. Keys are stable identifiers; strings are translated
via t(key). See ADR-004.

Usage:
    from i18n import t, set_language, LANGUAGES
    set_language('ru')
    print(t('app.title'))
"""

from __future__ import annotations

from typing import Callable

LANGUAGES = ('en', 'ru')
DEFAULT_LANGUAGE = 'en'

_current: str = DEFAULT_LANGUAGE


def set_language(lang: str) -> None:
    global _current
    if lang in LANGUAGES:
        _current = lang


def current_language() -> str:
    return _current


_EN: dict[str, str] = {
    'app.title': 'PhoneMover',
    'app.subtitle': 'iPhone to HUAWEI data transfer',
    'app.version': 'PhoneMover v{version}',
    'nav.transfer': 'Transfer',
    'nav.settings': 'Settings',
    'device.scanning': 'Scanning for iPhone…',
    'device.not_found': 'No iPhone detected. Connect your iPhone and tap Refresh.',
    'device.found': 'iPhone detected',
    'device.refresh': 'Refresh',
    'data.title': 'Select data to transfer',
    'data.contacts': 'Contacts',
    'data.photos': 'Photos',
    'data.videos': 'Videos',
    'data.music': 'Music',
    'data.calendar': 'Calendar',
    'data.notes': 'Notes',
    'data.bookmarks': 'Bookmarks',
    'data.reminders': 'Reminders',
    'dest.title': 'Destination (HUAWEI phone)',
    'dest.folder': 'Backup folder',
    'dest.hint': 'iPhone backup will be saved here. Transferred data lands in <folder>\\PhoneMover_out\\',
    'dest.browse': 'Browse…',
    'action.start': 'Start Transfer',
    'action.cancel': 'Cancel',
    'progress.waiting': 'Waiting to start…',
    'progress.backup': 'Backing up iPhone…',
    'progress.migrating': 'Transferring data…',
    'progress.importing': 'Importing to HUAWEI…',
    'progress.done': 'Transfer complete',
    'progress.failed': 'Transfer failed',
    'progress.types': '{done}/{total} types migrated',
    'lang.en': 'English',
    'lang.ru': 'Русский',
    'result.summary': 'Result: {succeeded} of {total} types succeeded.',
    'error.backup': 'Backup failed: {msg}',
}


_RU: dict[str, str] = {
    'app.title': 'PhoneMover',
    'app.subtitle': 'Перенос данных iPhone → HUAWEI',
    'app.version': 'PhoneMover v{version}',
    'nav.transfer': 'Перенос',
    'nav.settings': 'Настройки',
    'device.scanning': 'Поиск iPhone…',
    'device.not_found': 'iPhone не обнаружен. Подключите устройство и нажмите «Обновить».',
    'device.found': 'iPhone обнаружен',
    'device.refresh': 'Обновить',
    'data.title': 'Выберите данные для переноса',
    'data.contacts': 'Контакты',
    'data.photos': 'Фото',
    'data.videos': 'Видео',
    'data.music': 'Музыка',
    'data.calendar': 'Календарь',
    'data.notes': 'Заметки',
    'data.bookmarks': 'Закладки',
    'data.reminders': 'Напоминания',
    'dest.title': 'Назначение (телефон HUAWEI)',
    'dest.folder': 'Папка резервной копии',
    'dest.hint': 'Резервная копия iPhone сохраняется сюда. Перенесённые данные окажутся в <папка>\\PhoneMover_out\\',
    'dest.browse': 'Обзор…',
    'action.start': 'Начать перенос',
    'action.cancel': 'Отмена',
    'progress.waiting': 'Ожидание запуска…',
    'progress.backup': 'Резервное копирование iPhone…',
    'progress.migrating': 'Перенос данных…',
    'progress.importing': 'Импорт на HUAWEI…',
    'progress.done': 'Перенос завершён',
    'progress.failed': 'Перенос не удался',
    'progress.types': 'Перенесено типов: {done}/{total}',
    'lang.en': 'English',
    'lang.ru': 'Русский',
    'result.summary': 'Итог: успешно {succeeded} из {total} типов.',
    'error.backup': 'Ошибка резервного копирования: {msg}',
}


def t(key: str, **kwargs) -> str:
    """Translate a key into the current language, with optional formatting."""
    table = _RU if _current == 'ru' else _EN
    s = table.get(key, _EN.get(key, key))
    if kwargs:
        s = s.format(**kwargs)
    return s