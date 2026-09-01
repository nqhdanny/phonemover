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
    'wizard.title': 'Transfer Wizard',
    'wizard.close': 'Close',
    'wizard.log_placeholder': 'Transfer log…',
    'step.connect_iphone': '1. Connect iPhone',
    'step.backup': '2. Back up iPhone',
    'step.connect_huawei': '3. Connect HUAWEI phone',
    'step.import': '4. Import data',
    'step.done': '5. Done',
    'step.connect_iphone.instr': 'Connect your iPhone with a USB cable. If prompted on the phone, tap "Trust This Computer".',
    'step.backup.instr': 'Backing up your iPhone. This may take several minutes depending on the amount of data. Keep the phone connected.',
    'step.connect_huawei.instr': 'When the backup finishes, unplug the iPhone and connect your HUAWEI phone. Enable USB debugging on the HUAWEI phone.',
    'step.import.instr': 'Installing the helper app on your HUAWEI phone and importing your data. Keep the phone unlocked.',
    'step.done.instr_ok': 'Transfer complete! All selected data has been imported to your HUAWEI phone.',
    'step.done.instr_partial': 'Transfer finished with some items skipped. Review the log for details.',
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
    'wizard.title': 'Мастер переноса',
    'wizard.close': 'Закрыть',
    'wizard.log_placeholder': 'Журнал переноса…',
    'step.connect_iphone': '1. Подключите iPhone',
    'step.backup': '2. Резервное копирование iPhone',
    'step.connect_huawei': '3. Подключите телефон HUAWEI',
    'step.import': '4. Импорт данных',
    'step.done': '5. Готово',
    'step.connect_iphone.instr': 'Подключите iPhone кабелем USB. Если телефон запросит — нажмите «Доверять этому компьютеру».',
    'step.backup.instr': 'Выполняется резервное копирование iPhone. Это может занять несколько минут. Не отключайте телефон.',
    'step.connect_huawei.instr': 'После завершения копирования отключите iPhone и подключите телефон HUAWEI. Включите отладку по USB на телефоне HUAWEI.',
    'step.import.instr': 'Устанавливается вспомогательное приложение на телефон HUAWEI и импортируются данные. Держите телефон разблокированным.',
    'step.done.instr_ok': 'Перенос завершён! Все выбранные данные импортированы на телефон HUAWEI.',
    'step.done.instr_partial': 'Перенос завершён, часть данных пропущена. Смотрите журнал.',
}


def t(key: str, **kwargs) -> str:
    """Translate a key into the current language, with optional formatting."""
    table = _RU if _current == 'ru' else _EN
    s = table.get(key, _EN.get(key, key))
    if kwargs:
        s = s.format(**kwargs)
    return s