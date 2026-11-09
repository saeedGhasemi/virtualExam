"""«تنظیمات ظاهری» of the system settings (super_admin_settings → general tab), applied to every page.

The admin's four values live in `system_settings` (JSON-encoded, Persian labels as stored values):
theme_mode, primary_color, font_size. `appearance_context` (a context processor) puts the
validated values on <html> of every base template; `static/css/appearance.css` and `static/js/appearance.js`
do the rest (dark theme, text size, recolouring the blue brand family to the chosen colour).
"""
import json
import re

from django.db import DatabaseError, connection, transaction

DEFAULT_COLOR = '#2563EB'
COLOR_PRESETS = [
    ('#2563EB', 'آبی'),
    ('#8B5CF6', 'بنفش'),
    ('#22C55E', 'سبز'),
    ('#F59E0B', 'کهربایی'),
    ('#F97316', 'نارنجی'),
    ('#EF4444', 'قرمز'),
]
# stored (Persian) value → value on <html data-mq-…>
THEME_CHOICES = [('روشن', 'light'), ('تیره', 'dark')]
FONT_SIZE_CHOICES = [('کوچک', 'small'), ('متوسط', 'medium'), ('بزرگ', 'large')]

APPEARANCE_CHOICES = {
    'theme_mode': THEME_CHOICES,
    'font_size': FONT_SIZE_CHOICES,
}
APPEARANCE_DEFAULTS = {
    'theme_mode': 'روشن',
    'primary_color': DEFAULT_COLOR,
    'font_size': 'متوسط',
}
_HEX = re.compile(r'^#?([0-9a-fA-F]{6}|[0-9a-fA-F]{3})$')
_PERSIAN_DIGITS = str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩', '01234567890123456789')


def normalize_color(value):
    """'#2563eb' / '2563EB' / '#25e' → '#2563EB'; anything else → None."""
    match = _HEX.match(str(value or '').strip().translate(_PERSIAN_DIGITS))
    if not match:
        return None
    digits = match.group(1)
    if len(digits) == 3:
        digits = ''.join(ch * 2 for ch in digits)
    return f'#{digits.upper()}'


def clean_appearance_value(key, value):
    """A posted/stored value for one of the four keys, or its default when it isn't one of the options."""
    if key == 'primary_color':
        return normalize_color(value) or DEFAULT_COLOR
    choices = APPEARANCE_CHOICES.get(key)
    if choices is None:
        return value
    text = str(value or '').strip()
    labels = {label for label, _ in choices}
    if text in labels:
        return text
    by_code = {code: label for label, code in choices}  # tolerate 'dark', 'large', …
    return by_code.get(text.lower(), APPEARANCE_DEFAULTS[key])


def _decode(raw):
    if raw in (None, ''):
        return None
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw
    return raw


def stored_appearance():
    """The four saved values (validated, Persian labels / '#RRGGBB')."""
    values = dict(APPEARANCE_DEFAULTS)
    try:
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(
                'SELECT key, value FROM system_settings WHERE key IN (%s, %s, %s)',
                list(APPEARANCE_DEFAULTS),
            )
            rows = cursor.fetchall()
    except DatabaseError:
        return values
    for key, raw in rows:
        decoded = _decode(raw)
        if decoded not in (None, ''):
            values[key] = clean_appearance_value(key, decoded)
    return values


def appearance_attrs(values):
    codes = {key: dict(choices)[values[key]] for key, choices in APPEARANCE_CHOICES.items()}
    color = values['primary_color']
    return {
        'theme': codes['theme_mode'],
        'font': codes['font_size'],
        # only a non-default colour makes appearance.js recolour the page
        'accent': '' if color == DEFAULT_COLOR else color,
        'color': color,
    }


def appearance_context(request):
    cached = getattr(request, '_mq_appearance', None)
    if cached is None:
        cached = appearance_attrs(stored_appearance())
        try:
            request._mq_appearance = cached
        except AttributeError:
            pass
    return {'mq_appearance': cached}
