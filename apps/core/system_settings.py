"""«تنظیمات عمومی» of «تنظیمات سامانه» (views.super_admin_settings, ?tab=other): option lists and cleaning of the
general settings, the «آخرین تغییرات تنظیمات» log, the system logo and the site-wide IP restriction.

- Settings live in `system_settings` (JSON values). Choice settings (language, time zone, date format, password policy)
  are stored as codes from the lists below; anything else (old free-text labels, typos) is mapped to a code or falls
  back to the default (`clean_choice`). The page saves only the settings whose value changed and logs each change in
  `activity_audit_log` (action 'system_settings_bulk_updated' / 'system_settings_updated', metadata['changes'] =
  [{key, old, new}]); `recent_changes` turns those rows into the table at the bottom of the tab.
- The logo (`system_logo`) is an uploaded image re-encoded to PNG under MEDIA_ROOT/settings/ (`store_logo`); the
  default value means the built-in mark. `appearance.appearance_context` passes a valid uploaded logo to every page
  (`mq_brand_logo`) and `partials/brand_logo.html` shows it in place of the built-in mark.
- IP restriction (`ip_restriction` + `ip_allow_list` / `ip_block_list`, addresses or CIDR ranges, IPv4/IPv6):
  `IPRestrictionMiddleware` refuses every request (all roles, the sign-in page too) from a blocked address, and — when
  the allow list is not empty — from any address outside it. The page refuses to save lists that would shut out the
  admin who saves them (`ip_lockout_error`). The rule is read at most every RULE_TTL seconds per process.
  To lift a restriction from the server: `manage.py shell -c "from apps.core.system_settings import disable_ip_restriction; disable_ip_restriction()"`.
"""
import ipaddress
import json
import re
import time
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.db import DatabaseError, connection, transaction
from django.http import HttpResponseForbidden

# ---------------------------------------------------------------- choices (code, Persian label)
LANGUAGE_CHOICES = [('fa', 'فارسی (ایران)')]  # the interface exists in Persian only
TIMEZONE_CHOICES = [
    ('Asia/Tehran', 'تهران'),
    ('Asia/Kabul', 'کابل'),
    ('Asia/Dubai', 'دبی'),
    ('Asia/Baghdad', 'بغداد'),
    ('Europe/Istanbul', 'استانبول'),
    ('Asia/Karachi', 'کراچی'),
    ('Europe/Berlin', 'برلین'),
    ('Europe/London', 'لندن'),
    ('America/New_York', 'نیویورک'),
    ('UTC', 'زمان هماهنگ جهانی'),
]
DATE_FORMAT_CHOICES = [
    ('jalali', 'شمسی عددی — ۱۴۰۵/۰۸/۲۳'),
    ('jalali_long', 'شمسی با نام ماه — ۲۳ آبان ۱۴۰۵'),
]
PASSWORD_POLICY_CHOICES = [('weak', 'ضعیف'), ('medium', 'متوسط'), ('strong', 'قوی')]

CHOICE_DEFAULTS = {'default_language': 'fa', 'timezone': 'Asia/Tehran', 'date_format': 'jalali', 'password_policy': 'strong'}
_LEGACY = {  # values the old free-text boxes stored
    'default_language': {'فارسی': 'fa', 'fa-ir': 'fa', 'persian': 'fa', 'farsi': 'fa'},
    'timezone': {'تهران (utc+03:30)': 'Asia/Tehran', 'tehran': 'Asia/Tehran', 'iran': 'Asia/Tehran'},
    'date_format': {'هجری شمسی': 'jalali', 'شمسی': 'jalali', 'هجری شمسی (سال/ماه/روز)': 'jalali',
                    'هجری شمسی با نام ماه (روز ماه سال)': 'jalali_long'},
    'password_policy': {'قوی': 'strong', 'متوسط': 'medium', 'ضعیف': 'weak'},
}
GROUP_LABELS = {
    'basic': 'تنظیمات پایه سامانه', 'security': 'تنظیمات امنیتی', 'notifications': 'تنظیمات اعلان‌ها',
    'appearance': 'تنظیمات ظاهری', 'exam': 'تنظیمات آزمون و ثبت‌نام',
}
IP_LIST_KEYS = ('ip_allow_list', 'ip_block_list')
IP_LIST_MAX = 500  # characters, same as field-rules.js's «ip» kind
IP_LIST_ENTRIES = 50


def _utc_offset(code):
    try:
        offset = datetime.now(ZoneInfo(code)).utcoffset()
    except (ZoneInfoNotFoundError, ValueError):
        return ''
    minutes = int(offset.total_seconds() // 60)
    sign = '+' if minutes >= 0 else '-'
    minutes = abs(minutes)
    return f'UTC{sign}{minutes // 60:02d}:{minutes % 60:02d}'


def choices_for(key):
    if key == 'default_language':
        return LANGUAGE_CHOICES
    if key == 'timezone':
        return [(code, f'{label} ({_utc_offset(code)})' if _utc_offset(code) else label) for code, label in TIMEZONE_CHOICES]
    if key == 'date_format':
        return DATE_FORMAT_CHOICES
    if key == 'password_policy':
        return PASSWORD_POLICY_CHOICES
    return None


def clean_choice(key, value):
    """A posted/stored value of a choice setting as its code; unknown values → the default."""
    text = str(value if value is not None else '').strip()
    pairs = choices_for(key) or []
    codes = {code for code, _ in pairs}
    if text in codes:
        return text
    for code, label in pairs:
        if text == label or text.split(' (')[0] == label.split(' (')[0]:
            return code
    legacy = _LEGACY.get(key, {})
    return legacy.get(text.lower(), legacy.get(text, CHOICE_DEFAULTS[key]))


def choice_label(key, value):
    return dict(choices_for(key) or []).get(clean_choice(key, value), str(value or ''))


# ---------------------------------------------------------------- IP lists
def parse_ip_list(value):
    """(networks, error): addresses / CIDR ranges separated by commas, spaces or new lines."""
    text = str(value or '')
    if len(text) > IP_LIST_MAX:
        return [], f'فهرست IP حداکثر {IP_LIST_MAX} نویسه است.'
    parts = [part for part in re.split(r'[\s,،]+', text.strip()) if part]
    if len(parts) > IP_LIST_ENTRIES:
        return [], f'فهرست IP حداکثر {IP_LIST_ENTRIES} مورد است.'
    networks = []
    for part in parts:
        try:
            networks.append(ipaddress.ip_network(part, strict=False))
        except ValueError:
            return [], f'«{part}» نشانی IP یا محدوده‌ی معتبری نیست؛ مثلاً 192.168.1.10 یا 192.168.1.0/24.'
    return networks, ''


def normalize_ip_list(value):
    networks, error = parse_ip_list(value)
    if error:
        return None
    seen = []
    for network in networks:
        text = str(network.network_address) if network.num_addresses == 1 else str(network)
        if text not in seen:
            seen.append(text)
    return ', '.join(seen)


def _ip_in(ip, networks):
    try:
        address = ipaddress.ip_address(str(ip or '').strip())
    except ValueError:
        return False
    return any(address.version == network.version and address in network for network in networks)


def ip_allowed(ip, rule):
    """rule = {'allow': [networks], 'block': [networks]}."""
    if _ip_in(ip, rule['block']):
        return False
    return not rule['allow'] or _ip_in(ip, rule['allow'])


def ip_lockout_error(enabled, allow_text, block_text, current_ip):
    """Why these lists can't be saved by the admin at `current_ip` ('' when they can)."""
    allow, error = parse_ip_list(allow_text)
    if error:
        return f'IPهای مجاز: {error}'
    block, error = parse_ip_list(block_text)
    if error:
        return f'IPهای مسدود: {error}'
    if not enabled:
        return ''
    if not allow and not block:
        return 'برای فعال کردن محدودیت IP دست‌کم یک نشانی مجاز یا مسدود بنویسید.'
    if not ip_allowed(current_ip, {'allow': allow, 'block': block}):
        return (f'با این فهرست، دسترسی خود شما (IP فعلی: {current_ip or "نامشخص"}) قطع می‌شود؛ '
                'نشانی خودتان را به IPهای مجاز اضافه کنید یا از IPهای مسدود بردارید.')
    return ''


# ---------------------------------------------------------------- stored rule + middleware
RULE_TTL = 10  # seconds a process keeps the rule before reading it again
_rule_cache = {'at': None, 'rule': None}


def _decode(raw):
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw
    return raw


def _read(keys):
    try:
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(f'SELECT key, value FROM system_settings WHERE key IN ({", ".join(["%s"] * len(keys))})', list(keys))
            return {key: _decode(raw) for key, raw in cursor.fetchall()}
    except DatabaseError:
        return {}


def password_policy():
    """«سیاست گذرواژه» of the security settings: 'strong' | 'medium' | 'weak' (field_rules.PASSWORD_POLICIES)."""
    return clean_choice('password_policy', _read(('password_policy',)).get('password_policy'))


def ip_rule():
    """The active rule ({'allow', 'block'}) or None when the restriction is off."""
    now = time.monotonic()
    if _rule_cache['at'] is not None and now - _rule_cache['at'] < RULE_TTL:
        return _rule_cache['rule']
    values = _read(('ip_restriction',) + IP_LIST_KEYS)
    rule = None
    if values.get('ip_restriction') is True:
        allow, allow_error = parse_ip_list(values.get('ip_allow_list'))
        block, block_error = parse_ip_list(values.get('ip_block_list'))
        if not allow_error and not block_error and (allow or block):
            rule = {'allow': allow, 'block': block}
    _rule_cache.update(at=now, rule=rule)
    return rule


def forget_ip_rule():
    _rule_cache.update(at=None, rule=None)


def disable_ip_restriction():
    """Server-side way out (manage.py shell) when the allow list shut everybody out."""
    with connection.cursor() as cursor:
        cursor.execute("UPDATE system_settings SET value = %s WHERE key = 'ip_restriction'", [json.dumps(False)])
    forget_ip_rule()


BLOCKED_PAGE = (
    '<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8">'
    '<meta name="viewport" content="width=device-width,initial-scale=1"><title>دسترسی محدود است</title>'
    '<style>body{margin:0;min-height:100vh;display:grid;place-items:center;background:#f6f8fc;color:#111c36;'
    'font-family:Vazirmatn,Tahoma,sans-serif}main{max-width:28rem;margin:1rem;padding:1.5rem;border-radius:1rem;'
    'background:#fff;box-shadow:0 10px 30px -12px rgba(15,23,42,.25);line-height:1.9;text-align:center}'
    'h1{font-size:1.15rem;font-weight:700;margin:0 0 .5rem}p{margin:0;font-size:.92rem}</style></head>'
    '<body><main><h1>دسترسی از این شبکه مجاز نیست</h1>'
    '<p>مدیر سامانه دسترسی به متاکوییز را به نشانی‌های IP مشخصی محدود کرده است. اگر فکر می‌کنید اشتباهی رخ داده، '
    'با مدیر سامانه تماس بگیرید.</p></main></body></html>'
)


class IPRestrictionMiddleware:
    """Refuses requests from addresses the «محدودیت IP» setting doesn't allow (see the module docstring)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        rule = ip_rule()
        if rule:
            from .views import client_ip

            if not ip_allowed(client_ip(request), rule):
                return HttpResponseForbidden(BLOCKED_PAGE)
        return self.get_response(request)


# ---------------------------------------------------------------- logo
LOGO_DEFAULT = '/static/img/metaquiz-favicon.svg'
LOGO_FOLDER = 'settings'
LOGO_MAX_BYTES = 2 * 1024 * 1024
LOGO_MAX_SIDE = 512
LOGO_FORMATS = {'PNG', 'JPEG', 'WEBP', 'GIF'}
_LOGO_URL = re.compile(r'^logo-[0-9a-f]{32}\.png$')


def logo_url_ok(value):
    """True for a logo this page stored (MEDIA_URL/settings/logo-<hex>.png)."""
    text = str(value or '')
    prefix = f'{settings.MEDIA_URL}{LOGO_FOLDER}/'
    return text.startswith(prefix) and bool(_LOGO_URL.match(text[len(prefix):]))


def clean_logo_value(value, stored):
    """A posted «لوگو» value: the default, or the stored uploaded logo; anything else keeps what is stored."""
    text = str(value or '').strip()
    if text == LOGO_DEFAULT or (text == stored and logo_url_ok(text)):
        return text
    return stored if logo_url_ok(stored) else LOGO_DEFAULT


def store_logo(uploaded):
    """(url, error): the uploaded image checked with Pillow, re-encoded to PNG (≤ 512px) under MEDIA_ROOT/settings/."""
    from PIL import Image, ImageOps, UnidentifiedImageError

    if uploaded.size > LOGO_MAX_BYTES:
        return None, 'حجم لوگو باید حداکثر ۲ مگابایت باشد.'
    try:
        with Image.open(uploaded) as probe:
            probe.verify()
        uploaded.seek(0)
        image = Image.open(uploaded)
        if image.format not in LOGO_FORMATS:
            return None, 'لوگو باید تصویر PNG، JPG، WEBP یا GIF باشد.'
        if image.width * image.height > 25_000_000:
            return None, 'ابعاد تصویر لوگو بیش از حد بزرگ است.'
        image.load()
        image = ImageOps.exif_transpose(image).convert('RGBA')
        image.thumbnail((LOGO_MAX_SIDE, LOGO_MAX_SIDE))
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        return None, 'فایل انتخاب‌شده تصویر معتبری نیست؛ یک تصویر PNG، JPG، WEBP یا GIF انتخاب کنید.'
    folder = Path(settings.MEDIA_ROOT) / LOGO_FOLDER
    folder.mkdir(parents=True, exist_ok=True)
    name = f'logo-{uuid.uuid4().hex}.png'
    image.save(folder / name, 'PNG', optimize=True)
    return f'{settings.MEDIA_URL}{LOGO_FOLDER}/{name}', None


# ---------------------------------------------------------------- change log
def _unit(label):
    match = re.search(r'\(([^)]+)\)\s*$', str(label or ''))
    return match.group(1) if match else ''


def display_value(item, value):
    """{'text', 'color'} for one value of a setting in the change table."""
    key, kind = item['key'], item.get('type')
    if value is None or value == '':
        return {'text': '—', 'color': ''}
    if key == 'primary_color':
        from .appearance import normalize_color

        color = normalize_color(value)  # only a checked #RRGGBB reaches the style attribute
        return {'text': color or str(value), 'color': color or '', 'latin': True}
    if key == 'system_logo':
        return {'text': 'لوگوی بارگذاری‌شده' if logo_url_ok(value) else 'لوگوی پیش‌فرض', 'color': ''}
    if key in CHOICE_DEFAULTS:
        return {'text': choice_label(key, value), 'color': ''}
    if kind == 'boolean':
        return {'text': 'فعال' if value is True else 'غیرفعال', 'color': ''}
    if kind == 'number':
        unit = _unit(item.get('label'))
        return {'text': f'{value} {unit}'.strip(), 'color': ''}
    if key in IP_LIST_KEYS:
        return {'text': str(value), 'color': '', 'latin': True}
    return {'text': str(value), 'color': ''}


def recent_changes(schema_by_key, limit=10):
    """The latest single-setting changes (newest first) for «آخرین تغییرات تنظیمات»."""
    try:
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT a.metadata, a.created_at, p.full_name, p.username
                FROM activity_audit_log a
                LEFT JOIN profiles p ON p.id = a.actor_id
                WHERE a.action IN ('system_settings_bulk_updated', 'system_settings_updated')
                ORDER BY a.created_at DESC
                LIMIT 40
                """
            )
            rows = cursor.fetchall()
    except DatabaseError:
        return []
    out = []
    for metadata, created_at, full_name, username in rows:
        meta = _decode(metadata) if not isinstance(metadata, dict) else metadata
        for change in (meta or {}).get('changes') or [] if isinstance(meta, dict) else []:
            item = schema_by_key.get(change.get('key'))
            if not item:
                continue
            out.append({
                'group': GROUP_LABELS.get(item.get('group'), ''),
                'label': re.sub(r'\s*\([^)]*\)\s*$', '', item['label']),
                'values': [display_value(item, change.get('old')), display_value(item, change.get('new'))],
                'user': full_name or username or '—',
                'at': created_at,
            })
            if len(out) >= limit:
                return out
    return out
