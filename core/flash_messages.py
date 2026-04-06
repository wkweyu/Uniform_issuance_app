from flask import flash


VALID_FLASH_CATEGORIES = {'success', 'info', 'warning', 'error'}
FLASH_CATEGORY_ALIASES = {
    'danger': 'error',
    'fatal': 'error',
    'message': 'info',
    'default': 'info',
}


def normalize_flash_category(category):
    if category is None:
        return 'info'

    normalized = str(category).strip().lower()
    if not normalized:
        return 'info'
    if normalized in VALID_FLASH_CATEGORIES:
        return normalized
    return FLASH_CATEGORY_ALIASES.get(normalized, 'info')


def flash_message(message, category='info'):
    flash(message, normalize_flash_category(category))
