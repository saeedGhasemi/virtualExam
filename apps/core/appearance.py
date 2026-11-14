"""«تنظیمات ظاهری» of the system settings (super_admin_settings → general tab), applied to every page.

The admin's four values live in `system_settings` (JSON-encoded, Persian labels as stored values):
theme_mode, primary_color, font_size. `appearance_context` (a context processor) puts the
validated values on <html> of every base template; `static/css/appearance.css` and `static/js/appearance.js`
do the rest (dark theme, text size, recolouring the blue brand family to the chosen colour).

Every account also has its own «تنظیمات ظاهری» (`partials/my_appearance.html` on each role's account page): the
same three options as the admin's, previewed on the page and stored with «ذخیره تغییرات» as codes in
`system_settings` under `user_appearance.<profile id>` ({"theme": light|dark, "font": small|medium|large,
"color": "#RRGGBB"}). Until a user saves, they see the admin's values ('' = not set); anonymous pages (login) always
show the admin's. A teacher who never saved keeps the old «نمایش پوسته: تیره» of their teacher settings.
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


def _load_settings(keys):
    """{key: decoded value} of the given system_settings rows ({} when the table can't be read)."""
    keys = list(keys)
    try:
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(
                f'SELECT key, value FROM system_settings WHERE key IN ({", ".join(["%s"] * len(keys))})',
                keys,
            )
            rows = cursor.fetchall()
    except DatabaseError:
        return {}
    return {key: _decode(raw) for key, raw in rows}


def _system_values(rows):
    values = dict(APPEARANCE_DEFAULTS)
    for key in APPEARANCE_DEFAULTS:
        decoded = rows.get(key)
        if decoded not in (None, ''):
            values[key] = clean_appearance_value(key, decoded)
    return values


def stored_appearance():
    """The admin's saved values (validated, Persian labels / '#RRGGBB')."""
    return _system_values(_load_settings(APPEARANCE_DEFAULTS))


def appearance_attrs(values):
    codes = {key: dict(choices)[values[key]] for key, choices in APPEARANCE_CHOICES.items()}
    color = values['primary_color']
    return {
        'theme': codes['theme_mode'],
        'font': codes['font_size'],
        # only a non-default colour makes appearance.js recolour the page
        'accent': '' if color == DEFAULT_COLOR else color,
        'color': color,
        'theme_label': values['theme_mode'],  # Persian, for «پیش‌فرض سامانه: …» on the «ظاهر من» card
        'font_label': values['font_size'],
    }


# ---------------------------------------------------------------- «ظاهر من» (per-user override)

USER_KEY_PREFIX = 'user_appearance.'
TEACHER_KEY_PREFIX = 'teacher_settings.'  # the teacher's old «نمایش پوسته» (teacher_preferences)
PERSONAL_EMPTY = {'theme': '', 'font': '', 'color': ''}
PERSONAL_CHOICES = {  # for partials/my_appearance.html: exactly the admin's options (label, code)
    'themes': THEME_CHOICES,
    'fonts': FONT_SIZE_CHOICES,
    'colors': COLOR_PRESETS,
    'color_values': [hex_value for hex_value, _name in COLOR_PRESETS],
}


def clean_personal(values):
    """Posted / stored personal values → {'theme', 'font', 'color'} codes ('' = not set: the admin's value)."""
    values = values if isinstance(values, dict) else {}
    theme = str(values.get('theme') or '').strip().lower()
    font = str(values.get('font') or '').strip().lower()
    return {
        'theme': theme if theme in {code for _label, code in THEME_CHOICES} else '',
        'font': font if font in {code for _label, code in FONT_SIZE_CHOICES} else '',
        'color': normalize_color(values.get('color')) or '',
    }


def _personal_values(rows, profile_id):
    saved = rows.get(f'{USER_KEY_PREFIX}{profile_id}')
    if isinstance(saved, dict):
        return clean_personal(saved)
    personal = dict(PERSONAL_EMPTY)
    teacher = rows.get(f'{TEACHER_KEY_PREFIX}{profile_id}')
    if isinstance(teacher, dict) and teacher.get('theme') == 'dark':
        personal['theme'] = 'dark'
    return personal


def _personal_keys(profile_id):
    return [f'{USER_KEY_PREFIX}{profile_id}', f'{TEACHER_KEY_PREFIX}{profile_id}']


def personal_appearance(profile_id):
    """The account's «ظاهر من» codes (with the teacher fallback), all '' when nothing is set."""
    if not profile_id:
        return dict(PERSONAL_EMPTY)
    return _personal_values(_load_settings(_personal_keys(profile_id)), profile_id)


def save_personal_appearance(profile_id, values):
    """Store the account's «ظاهر من»; returns the cleaned values."""
    cleaned = clean_personal(values)
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO system_settings (key, value, description, updated_by)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_by = excluded.updated_by
            """,
            [f'{USER_KEY_PREFIX}{profile_id}', json.dumps(cleaned), 'Personal appearance', profile_id],
        )
    return cleaned


def save_posted_appearance(profile_id, post):
    """The card's fields (mqa_*) posted with a host page's «ذخیره تغییرات»; True when they were there and saved."""
    if not profile_id or 'mqa_theme' not in post:
        return False
    save_personal_appearance(profile_id, {
        'theme': post.get('mqa_theme'), 'font': post.get('mqa_font'), 'color': post.get('mqa_color'),
    })
    return True


def merged_attrs(system_attrs, personal):
    """<html data-mq-…> values: each «ظاهر من» value that is set wins over the admin's."""
    color = personal.get('color') or system_attrs['color']
    return {
        'theme': personal.get('theme') or system_attrs['theme'],
        'font': personal.get('font') or system_attrs['font'],
        'accent': '' if color == DEFAULT_COLOR else color,
        'color': color,
    }


def _request_profile_id(request):
    user = getattr(request, 'user', None)
    if not user or not getattr(user, 'is_authenticated', False):
        return None
    from .views import erd_profile_for_user  # views imports this module

    try:
        profile = erd_profile_for_user(user)
    except DatabaseError:
        return None
    return profile['id'] if profile else None


def appearance_context(request):
    cached = getattr(request, '_mq_appearance', None)
    if cached is None:
        profile_id = _request_profile_id(request)
        keys = list(APPEARANCE_DEFAULTS) + ['system_logo', 'password_policy'] + (_personal_keys(profile_id) if profile_id else [])
        rows = _load_settings(keys)
        system = appearance_attrs(_system_values(rows))
        personal = _personal_values(rows, profile_id) if profile_id else dict(PERSONAL_EMPTY)
        from .system_settings import clean_choice, logo_url_ok  # the admin's uploaded logo (system settings → «لوگو / هویت سامانه»)

        logo = rows.get('system_logo')
        cached = {'effective': merged_attrs(system, personal), 'system': system, 'personal': personal,
                  'logo': logo if logo_url_ok(logo) else '',
                  'pw_policy': clean_choice('password_policy', rows.get('password_policy'))}
        try:
            request._mq_appearance = cached
        except AttributeError:
            pass
    return {
        'mq_appearance': cached['effective'],
        'mq_system_appearance': cached['system'],
        'mq_personal_appearance': cached['personal'],
        'mq_personal_choices': PERSONAL_CHOICES,
        'mq_brand_logo': cached['logo'],  # partials/brand_logo.html shows it in place of the built-in mark
        'mq_pw_policy': cached['pw_policy'],  # «سیاست گذرواژه» for field-rules.js (<html data-mq-pw-policy>)
    }
