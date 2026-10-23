"""OSCE exam builder: an OSCE exam is an ordered set of stations owned by one teacher.

Every query is scoped to ``request.erd_profile_id`` (the teacher), so changing an id in the URL
never reaches another teacher's exam or station; out-of-scope ids answer 404.
"""
import json
import logging
import math
import re
import uuid
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.http import Http404, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from .rich_text import clean_delta, delta_length, delta_to_html
from .uploads import signature_ok
from .views import (
    _store_upload,
    _teacher_modern_context,
    _teacher_question_course_options,
    erd_execute,
    erd_role_required,
    erd_row,
    erd_rows,
)

logger = logging.getLogger(__name__)

STATION_TYPES = {
    'clinical': {'label': 'ایستگاه بالینی', 'description': 'شرح حال و معاینه بیمار و مهارت‌های بالینی'},
    'skill': {'label': 'ایستگاه مهارتی', 'description': 'اجرای یک مهارت عملی روی بیمار، مانکن یا شبیه‌ساز'},
    'communication': {'label': 'ایستگاه ارتباطی', 'description': 'گفتگو با بیمار یا همراه و مهارت‌های ارتباطی'},
    'knowledge': {'label': 'ایستگاه دانشی', 'description': 'تفسیر یافته‌ها، تحلیل اطلاعات و تصمیم‌گیری بالینی'},
}
STATION_TYPE_ABOUT = {
    'clinical': ('در این ایستگاه دانشجو با یک بیمار واقعی یا استانداردشده یا مانکن روبه‌رو می‌شود و باید شرح حال بگیرد، معاینه انجام دهد و بر اساس یافته‌ها تصمیم‌گیری کند.',
                 ['مهارت اخذ شرح حال', 'مهارت معاینه فیزیکی', 'تفسیر یافته‌های بالینی', 'ارتباط با بیمار و همراه', 'تصمیم‌گیری و برنامه‌ریزی']),
    'skill': ('دانشجو یک مهارت عملی مشخص را روی بیمار، مانکن یا شبیه‌ساز اجرا می‌کند و مراحل انجام کار ارزیابی می‌شود.',
              ['آمادگی و رعایت اصول ایمنی', 'ترتیب صحیح مراحل', 'دقت و مهارت دستی', 'رعایت کنترل عفونت']),
    'communication': ('دانشجو با بیمار یا همراه گفتگو می‌کند؛ مهارت‌های ارتباطی، همدلی و انتقال اطلاعات سنجیده می‌شود.',
                      ['شروع و معرفی مناسب', 'گوش دادن فعال و همدلی', 'انتقال روشن اطلاعات', 'جمع‌بندی و پایان گفتگو']),
    'knowledge': ('دانشجو داده‌هایی مثل تصویر، نوار قلب یا نتایج آزمایش را تفسیر می‌کند و درباره‌ی آن‌ها تصمیم می‌گیرد.',
                  ['تفسیر داده‌های پاراکلینیک', 'استدلال بالینی', 'تشخیص افتراقی', 'تصمیم‌گیری درمانی']),
}
EXECUTION_MODES = {
    'standardized_patient': 'بیمار استانداردشده',
    'mannequin': 'مانکن',
    'real_patient': 'بیمار واقعی',
    'virtual_simulation': 'شبیه‌سازی مجازی',
}
ASSESSMENT_METHODS = {
    'checklist': 'چک‌لیست مشاهده مستقیم',
    'global_rating': 'ارزیابی کلی (Global Rating)',
    'combined': 'ترکیبی',
}
DIFFICULTIES = {'easy': 'آسان', 'medium': 'متوسط', 'hard': 'سخت'}
DOMAIN_SUGGESTIONS = ['قلب و عروق', 'قلب و عروق کودکان', 'تنفس', 'گوارش', 'اعصاب', 'اورژانس', 'کودکان', 'زنان و مامایی', 'جراحی', 'روان‌پزشکی']

# Station tabs in builder order. Only the implemented ones are reachable; the rest are shown as «در حال توسعه».
STATION_TABS = [
    ('basic', 'اطلاعات پایه', True),
    ('type', 'نوع ایستگاه', True),
    ('scenario', 'سناریو و محتوا', True),
    ('instructions', 'دستورالعمل دانشجو', True),
    ('criteria', 'معیارهای ارزیابی', True),
    ('resources', 'تجهیزات و منابع', True),
    ('timing', 'زمان و مدیریت', True),
    ('settings', 'تنظیمات تکمیلی', True),
]
IMPLEMENTED_TABS = [key for key, _label, enabled in STATION_TABS if enabled]

TITLE_MAX = 200
CODE_MAX = 30
DOMAIN_MAX = 120
DESCRIPTION_MAX = 500
OBJECTIVE_MAX = 200
OBJECTIVES_LIMIT = 20
DURATION_MAX = 180
LIST_PAGE_SIZE = 20
RICH_TEXT_MAX = 2000
INSTRUCTIONS_MAX = 1500
NOTES_MAX = 500
SHORT_FIELD_MAX = 200
FILES_PER_LIST = 10
MB = 1024 * 1024

PATIENT_GENDERS = {'male': 'مرد', 'female': 'زن', 'boy': 'پسر', 'girl': 'دختر'}
PATIENT_ROLES = {
    'self': 'خود بیمار پاسخ می‌دهد',
    'parent': 'والد همراه دارد',
    'companion': 'همراه بیمار پاسخ می‌دهد',
}
# Rich-text sections of the scenario tab: (key, label, placeholder).
SCENARIO_SECTIONS = [
    ('story', 'سناریوی بیمار', 'شرح حال، شکایت، سابقه و یافته‌هایی که دانشجو با آن روبه‌رو می‌شود...'),
    ('examiner_guide', 'راهنمای ارزیاب', 'نکاتی که ارزیاب هنگام اجرای ایستگاه باید بداند...'),
    ('marking_notes', 'نکات کلیدی (Marking)', 'پاسخ‌ها و رفتارهای کلیدی مورد انتظار برای نمره‌دهی...'),
    ('patient_script', 'وضعیت و نقش بیمار', 'نقش، احساسات و پاسخ‌هایی که بیمار استانداردشده باید ارائه کند...'),
]
INSTRUCTION_TEMPLATE = [
    'شما قرار است بیمار را در این ایستگاه ارزیابی کنید.',
    'لطفاً موارد زیر را انجام دهید:',
    'خود را معرفی کنید و از بیمار یا همراه او شرح حال کوتاه و هدفمند بگیرید.',
    'معاینه‌ی لازم را به‌طور کامل انجام دهید.',
    'یافته‌های مهم را برای بیمار یا همراه توضیح دهید.',
    'در پایان، پیشنهاد اولیه‌ی خود را برای اقدامات بعدی بیان کنید.',
]
# Allowed upload kinds: extensions and size limit; leading bytes are also checked server-side.
UPLOAD_KINDS = {
    'image': ({'jpg', 'jpeg', 'png', 'webp'}, 10 * MB),
    'video': ({'mp4', 'webm'}, 100 * MB),
    'audio': ({'mp3', 'wav', 'ogg', 'm4a'}, 20 * MB),
    'pdf': ({'pdf'}, 20 * MB),
}
SCENARIO_MEDIA_KINDS = ('image', 'video', 'audio', 'pdf')
INSTRUCTION_FILE_EXTENSIONS = {'pdf', 'jpg', 'jpeg', 'png', 'mp4'}
INSTRUCTION_FILE_MAX = 20 * MB
PATIENT_PHOTO_MAX = 2 * MB

CRITERION_TYPES = {'binary': 'چک‌لیست (بله/خیر)', 'scale': 'مقیاس ۱-۵'}
CRITERIA_LIMIT = 60
GLOBAL_LIMIT = 10
CRITERION_TEXT_MAX = 300
POINTS_MAX = Decimal('100')
TEMPLATE_TITLE_MAX = 120
TEMPLATES_PER_TEACHER = 50
SCORING_MODES = {
    'per_item': ('امتیازدهی هر معیار', 'هر معیار امتیاز مستقل دارد (امتیاز کل = مجموع).'),
    'pass_fail': ('نمره‌دهی بله/خیر (قبول/مردود)', 'بر اساس حد نصاب از پیش تعیین‌شده.'),
}
DEFAULT_SCALE_LEVELS = [
    {'label': 'عالی', 'description': 'به‌طور کامل و صحیح'},
    {'label': 'خوب', 'description': 'با اشکالات جزئی'},
    {'label': 'متوسط', 'description': 'با کمک انجام می‌دهد'},
    {'label': 'ضعیف تا متوسط', 'description': 'ناقص انجام می‌دهد'},
    {'label': 'ضعیف', 'description': 'انجام نمی‌دهد'},
]
DEFAULT_CRITERIA_DISPLAY = {
    'show_descriptions': True, 'show_item_points': True, 'show_running_total': True, 'show_examiner_notes': False,
}
CRITERIA_DISPLAY_OPTIONS = [
    ('show_descriptions', 'نمایش توضیحات معیارها'),
    ('show_item_points', 'نمایش امتیاز هر معیار'),
    ('show_running_total', 'نمایش جمع امتیاز در حین ارزیابی'),
    ('show_examiner_notes', 'نمایش فضای یادداشت برای ممتحن'),
]


RESOURCE_STATUS = {'required': 'ضروری', 'optional': 'اختیاری'}
RESOURCE_TABLES = {
    # prefix: (label, row limit, has status column, has note column)
    'equipment': ('تجهیزات', 40, True, False),
    'supplies': ('مواد مصرفی و ملزومات', 40, True, False),
    'staff': ('نیروی انسانی', 20, False, True),
}
RESOURCE_NAME_MAX = 120
RESOURCE_NOTE_MAX = 150
RESOURCE_FILE_EXTENSIONS = {'pdf', 'jpg', 'jpeg', 'png', 'mp4'}
RESOURCE_FILE_MAX = 50 * MB
EXECUTION_PATTERNS = {
    'rotation': ('چرخشی (گردشی)', 'دانشجویان بین ایستگاه‌ها به صورت چرخشی جابه‌جا می‌شوند.'),
    'static': ('ایستا (ثابت)', 'دانشجویان در این ایستگاه باقی می‌مانند.'),
    'mixed': ('ترکیبی', 'ترکیب چرخشی و ایستا.'),
}
ALERT_TYPES = {'audio_visual': 'صوتی و دیداری', 'visual': 'فقط دیداری', 'audio': 'فقط صوتی'}
ALERT_OPTIONS = [
    ('timer_student', 'نمایش تایمر برای دانشجو'),
    ('one_minute_warning', 'نمایش هشدار ۱ دقیقه مانده'),
    ('end_sound', 'اعلان صوتی پایان زمان'),
    ('timer_examiner', 'نمایش تایمر برای ارزیاب'),
]
ACCESS_SCOPES = {'selected': 'فقط دانشجویان انتخاب‌شده', 'course': 'همه دانشجویان درس'}
EXAM_DISPLAY_OPTIONS = [
    ('show_remaining_time', 'نمایش زمان باقی‌مانده'),
    ('show_progress', 'نمایش پیشرفت آزمون'),
    ('show_station_number', 'نمایش شماره ایستگاه'),
]
EXAM_SECURITY_TOGGLES = [
    ('show_result_after', 'نمایش نتیجه پس از اتمام آزمون'),
    ('allow_review', 'امکان بازنگری پاسخ‌ها'),
]
EXAM_NOTIFY_OPTIONS = [
    ('notify_students', 'ارسال اطلاع‌رسانی نتایج به دانشجویان'),
    ('notify_teachers', 'ارسال گزارش به اساتید'),
    ('save_reports', 'ذخیره گزارش‌های آزمون'),
]
TAG_MAX = 30
TAGS_LIMIT = 10
GROUPS_MAX = 50
TIME_RE = re.compile(r'^([01]\d|2[0-3]):([0-5]\d)$')


def _item(text, kind, points, required=False, guide=''):
    return {'text': text, 'type': kind, 'points': points, 'required': required, 'guide': guide}


# Built-in starter checklists shown under «قالب‌های آماده».
BUILTIN_CRITERIA_TEMPLATES = [
    {'id': 'general_exam', 'title': 'معاینه فیزیکی عمومی', 'subtitle': 'چک‌لیست معاینه جسمانی کامل', 'items': [
        _item('معرفی خود و کسب رضایت از بیمار', 'binary', '1', True),
        _item('شستن دست‌ها و رعایت اصول کنترل عفونت', 'binary', '1', True),
        _item('حفظ حریم و آسایش بیمار', 'binary', '1'),
        _item('بررسی علائم حیاتی', 'scale', '2'),
        _item('انجام معاینه سیستماتیک از سر تا پا', 'scale', '3', guide='مشاهده، لمس، دق و سمع به ترتیب'),
        _item('گزارش دقیق یافته‌ها', 'scale', '2'),
    ]},
    {'id': 'pediatric_cardiac', 'title': 'معاینه قلب کودکان', 'subtitle': 'معیارهای استاندارد معاینه قلب', 'items': [
        _item('معرفی خود و کسب رضایت از کودک/والدین', 'binary', '2', True, 'خود را معرفی می‌کند و هدف را توضیح می‌دهد.'),
        _item('شستشوی دست و رعایت اصول کنترل عفونت', 'binary', '1', True, 'قبل از معاینه دست‌ها را می‌شوید.'),
        _item('برقراری ارتباط مناسب با کودک', 'scale', '3', True, 'با زبان مناسب سن کودک ارتباط برقرار می‌کند.'),
        _item('انجام معاینه فیزیکی قلب به ترتیب صحیح', 'binary', '8', True, 'به ترتیب: مشاهده، لمس، دق، سمع.'),
        _item('تشخیص یافته‌های مهم و غیرطبیعی', 'scale', '4', guide='یافته‌های اصلی (سوفل، کلیک و ...) را بیان می‌کند.'),
        _item('جمع‌بندی و ارائه برنامه مدیریتی', 'scale', '2', guide='نتیجه‌گیری و پیشنهاد اقدامات بعدی را بیان می‌کند.'),
    ]},
    {'id': 'communication', 'title': 'برقراری ارتباط با بیمار/والدین', 'subtitle': 'ارزیابی مهارت‌های ارتباطی', 'items': [
        _item('شروع مناسب گفتگو و معرفی خود', 'binary', '1', True),
        _item('استفاده از پرسش‌های باز', 'scale', '2'),
        _item('گوش دادن فعال و ابراز همدلی', 'scale', '3'),
        _item('توضیح اطلاعات به زبان ساده', 'scale', '2'),
        _item('بررسی درک بیمار یا همراه', 'binary', '1'),
        _item('جمع‌بندی و پایان مناسب گفتگو', 'binary', '1'),
    ]},
    {'id': 'interpretation', 'title': 'تست‌های تشخیصی (Interpretation)', 'subtitle': 'تفسیر تصاویر و داده‌های پاراکلینیک', 'items': [
        _item('شناسایی نوع تست و بررسی کیفیت آن', 'binary', '1'),
        _item('توصیف یافته‌های طبیعی', 'scale', '2'),
        _item('شناسایی یافته‌های غیرطبیعی', 'scale', '3', True),
        _item('تفسیر یافته‌ها در بافت بالینی بیمار', 'scale', '3'),
        _item('پیشنهاد اقدام تشخیصی یا درمانی بعدی', 'scale', '1'),
    ]},
    {'id': 'decision', 'title': 'تصمیم‌گیری بالینی', 'subtitle': 'ارزیابی منطق و استدلال بالینی', 'items': [
        _item('جمع‌آوری اطلاعات کلیدی', 'scale', '2'),
        _item('مطرح‌کردن تشخیص‌های افتراقی مناسب', 'scale', '3'),
        _item('انتخاب محتمل‌ترین تشخیص', 'binary', '2', True),
        _item('ارائه برنامه درمانی مناسب', 'scale', '3'),
        _item('توجه به ایمنی بیمار', 'binary', '1', True),
    ]},
]


def _json_value(value, fallback):
    """JSON columns come back as parsed values on PostgreSQL and as text on SQLite."""
    if value is None or value == '':
        return fallback
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        logger.warning('Unparseable OSCE JSON column value: %r', value)
        return fallback


def _upload_kind(name: str) -> str:
    extension = (name.rsplit('.', 1)[-1] if '.' in name else '').lower()
    return next((kind for kind, (extensions, _limit) in UPLOAD_KINDS.items() if extension in extensions), '')


def _store_file(uploaded, allowed_extensions, max_bytes) -> tuple[dict | None, str | None]:
    """Validate and store one upload under MEDIA_ROOT/osce-media. Returns (file record, error)."""
    extension = (uploaded.name.rsplit('.', 1)[-1] if '.' in uploaded.name else '').lower()
    if extension not in allowed_extensions:
        return None, f'نوع فایل «{uploaded.name}» مجاز نیست.'
    if not signature_ok(uploaded, extension):
        return None, f'محتوای فایل «{uploaded.name}» با پسوند آن هم‌خوانی ندارد.'
    url, error = _store_upload(uploaded, 'osce-media', allowed_extensions, max_bytes)
    if error:
        return None, error
    return {'url': url, 'name': uploaded.name[:150], 'size': uploaded.size, 'kind': _upload_kind(uploaded.name)}, None


def _merge_files(existing, remove_urls, uploads, allowed_extensions, max_bytes_for) -> tuple[list, list]:
    """Keep stored files not marked for removal, then append validated new uploads."""
    errors = []
    kept = [item for item in existing if isinstance(item, dict) and item.get('url') not in remove_urls]
    for uploaded in uploads:
        if len(kept) >= FILES_PER_LIST:
            errors.append(f'حداکثر {FILES_PER_LIST} فایل در این بخش مجاز است.')
            break
        record, error = _store_file(uploaded, allowed_extensions, max_bytes_for(uploaded.name))
        if error:
            errors.append(error)
        else:
            kept.append(record)
    return kept, errors


def _owned_osce(teacher_id, osce_id) -> dict:
    row = erd_row(
        'SELECT id, title, course_id, status, settings FROM osce_exams WHERE id = %s AND teacher_id = %s',
        [str(osce_id), teacher_id],
    )
    if not row:
        raise Http404('آزمون OSCE پیدا نشد.')
    row['id'] = str(row['id'])
    row['course_id'] = str(row['course_id']) if row.get('course_id') else ''
    row['settings'] = _json_value(row.get('settings'), {})
    return row


def _stations(osce_id) -> list[dict]:
    rows = erd_rows(
        """
        SELECT id, position, title, code, station_type, domain, difficulty, duration_minutes,
               is_active, description, objectives, details
        FROM osce_stations WHERE osce_exam_id = %s ORDER BY position, created_at
        """,
        [osce_id],
    )
    for row in rows:
        row['id'] = str(row['id'])
        row['objectives'] = _json_value(row.get('objectives'), [])
        row['details'] = _json_value(row.get('details'), {})
        row['is_active'] = bool(row.get('is_active'))
        row['type_label'] = STATION_TYPES.get(row['station_type'], {}).get('label', '')
    return rows


def _renumber(osce_id, ordered_ids):
    for position, station_id in enumerate(ordered_ids, start=1):
        erd_execute('UPDATE osce_stations SET position = %s WHERE id = %s AND osce_exam_id = %s', [position, station_id, osce_id])


def _next_free_code(stations) -> str:
    used = {station['code'] for station in stations}
    number = len(stations) + 1
    while f'OSCE-{number:02d}' in used:
        number += 1
    return f'OSCE-{number:02d}'


def _clean_int(value, low, high):
    try:
        number = int(str(value or '').strip().translate(str.maketrans('۰۱۲۳۴۵۶۷۸۹', '0123456789')))
    except ValueError:
        return None
    return number if low <= number <= high else None


def _basic_payload(post, station_count: int) -> tuple[dict, list[str]]:
    """Validate the «اطلاعات پایه» tab. ``station_count`` bounds the requested position."""
    errors = []
    title = (post.get('title') or '').strip()
    code = (post.get('code') or '').strip()
    station_type = post.get('station_type') or ''
    difficulty = post.get('difficulty') or ''
    domain = (post.get('domain') or '').strip()
    description = (post.get('description') or '').strip()
    objectives = [item.strip() for item in post.getlist('objectives') if item.strip()]
    duration = _clean_int(post.get('duration_minutes'), 1, DURATION_MAX)
    position = _clean_int(post.get('position'), 1, max(station_count, 1))
    if not title:
        errors.append('عنوان ایستگاه الزامی است.')
    elif len(title) > TITLE_MAX:
        errors.append(f'عنوان ایستگاه حداکثر {TITLE_MAX} نویسه است.')
    if not code:
        errors.append('کد ایستگاه الزامی است.')
    elif len(code) > CODE_MAX:
        errors.append(f'کد ایستگاه حداکثر {CODE_MAX} نویسه است.')
    if station_type not in STATION_TYPES:
        errors.append('نوع ایستگاه نامعتبر است.')
    if difficulty not in DIFFICULTIES:
        errors.append('سطح دشواری نامعتبر است.')
    if len(domain) > DOMAIN_MAX:
        errors.append(f'حوزه حداکثر {DOMAIN_MAX} نویسه است.')
    if len(description) > DESCRIPTION_MAX:
        errors.append(f'توضیحات ایستگاه حداکثر {DESCRIPTION_MAX} نویسه است.')
    if len(objectives) > OBJECTIVES_LIMIT:
        errors.append(f'حداکثر {OBJECTIVES_LIMIT} هدف آموزشی مجاز است.')
    if any(len(item) > OBJECTIVE_MAX for item in objectives):
        errors.append(f'هر هدف آموزشی حداکثر {OBJECTIVE_MAX} نویسه است.')
    if duration is None:
        errors.append(f'مدت زمان ایستگاه باید عددی بین ۱ تا {DURATION_MAX} دقیقه باشد.')
    if position is None:
        errors.append('جایگاه ایستگاه در برنامه آزمون نامعتبر است.')
    return {
        'title': title, 'code': code, 'station_type': station_type, 'difficulty': difficulty,
        'domain': domain, 'description': description, 'objectives': objectives,
        'duration_minutes': duration, 'position': position, 'is_active': bool(post.get('is_active')),
    }, errors


def _type_payload(post) -> tuple[dict, list[str]]:
    """Validate the «نوع ایستگاه» tab."""
    errors = []
    station_type = post.get('station_type') or ''
    execution_mode = post.get('execution_mode') or ''
    assessment_method = post.get('assessment_method') or ''
    if station_type not in STATION_TYPES:
        errors.append('نوع ایستگاه را انتخاب کنید.')
    if execution_mode not in EXECUTION_MODES:
        errors.append('شیوه اجرا را انتخاب کنید.')
    if assessment_method not in ASSESSMENT_METHODS:
        errors.append('روش ارزیابی را انتخاب کنید.')
    return {
        'station_type': station_type,
        'details': {
            'execution_mode': execution_mode,
            'assessment_method': assessment_method,
            'needs_standardized_patient': bool(post.get('needs_standardized_patient')),
            'examiner_present': bool(post.get('examiner_present')),
        },
    }, errors


def _scenario_payload(post, files, station) -> tuple[dict, list, list[str]]:
    """Validate the «سناریو و محتوا» tab. Returns (scenario details, station objectives, errors)."""
    errors = []
    previous = station['details'].get('scenario', {})
    patient = {
        'age': (post.get('patient_age') or '').strip(),
        'gender': post.get('patient_gender') or '',
        'chief_complaint': (post.get('patient_chief_complaint') or '').strip(),
        'role': post.get('patient_role') or '',
        'photo': previous.get('patient', {}).get('photo') or None,
    }
    if patient['gender'] and patient['gender'] not in PATIENT_GENDERS:
        errors.append('جنسیت بیمار نامعتبر است.')
    if patient['role'] and patient['role'] not in PATIENT_ROLES:
        errors.append('نقش بیمار نامعتبر است.')
    if len(patient['age']) > 40 or len(patient['chief_complaint']) > SHORT_FIELD_MAX:
        errors.append('سن یا شکایت اصلی بیمار بیش از حد طولانی است.')
    if station['details'].get('needs_standardized_patient') and not all(
            [patient['age'], patient['gender'], patient['chief_complaint'], patient['role']]):
        errors.append('این ایستگاه به بیمار استانداردشده نیاز دارد؛ سن، جنسیت، شکایت اصلی و نقش بیمار را کامل کنید.')
    if post.get('remove_patient_photo'):
        patient['photo'] = None
    if files.get('patient_photo'):
        record, error = _store_file(files['patient_photo'], {'jpg', 'jpeg', 'png', 'webp'}, PATIENT_PHOTO_MAX)
        if error:
            errors.append(error)
        else:
            patient['photo'] = record

    sections = {}
    for key, label, _placeholder in SCENARIO_SECTIONS:
        delta = clean_delta(post.get(f'scenario_{key}'))
        if delta_length(delta) > RICH_TEXT_MAX:
            errors.append(f'متن «{label}» حداکثر {RICH_TEXT_MAX} نویسه است.')
        sections[key] = delta
    notes = (post.get('scenario_notes') or '').strip()
    if len(notes) > NOTES_MAX:
        errors.append(f'یادداشت‌های تکمیلی حداکثر {NOTES_MAX} نویسه است.')

    objectives = list(station['objectives'])
    new_objective = (post.get('new_objective') or '').strip()
    if new_objective:
        if len(new_objective) > OBJECTIVE_MAX or len(objectives) >= OBJECTIVES_LIMIT:
            errors.append(f'هدف جدید حداکثر {OBJECTIVE_MAX} نویسه است و کل هدف‌ها حداکثر {OBJECTIVES_LIMIT} مورد.')
        elif new_objective not in objectives:
            objectives.append(new_objective)
    focus = [item for item in post.getlist('focus_objectives') if item in objectives]
    if new_objective in objectives and new_objective not in focus:
        focus.append(new_objective)

    media, media_errors = _merge_files(
        previous.get('media', []), set(post.getlist('remove_media')), files.getlist('scenario_media'),
        set().union(*(UPLOAD_KINDS[kind][0] for kind in SCENARIO_MEDIA_KINDS)),
        lambda name: UPLOAD_KINDS.get(_upload_kind(name), (None, 0))[1],
    )
    errors += media_errors
    return {'patient': patient, **sections, 'notes': notes, 'focus_objectives': focus, 'media': media}, objectives, errors


def _instructions_payload(post, files, station) -> tuple[dict, list[str]]:
    """Validate the «دستورالعمل دانشجو» tab."""
    errors = []
    previous = station['details'].get('instructions', {})
    body = clean_delta(post.get('instructions_body'))
    if not delta_length(body):
        errors.append('متن دستورالعمل دانشجو الزامی است.')
    elif delta_length(body) > INSTRUCTIONS_MAX:
        errors.append(f'متن دستورالعمل دانشجو حداکثر {INSTRUCTIONS_MAX} نویسه است.')
    special_notes = (post.get('special_notes') or '').strip()
    if len(special_notes) > NOTES_MAX:
        errors.append(f'نکات ویژه حداکثر {NOTES_MAX} نویسه است.')
    attachments, file_errors = _merge_files(
        previous.get('attachments', []), set(post.getlist('remove_attachment')), files.getlist('instruction_files'),
        INSTRUCTION_FILE_EXTENSIONS, lambda _name: INSTRUCTION_FILE_MAX,
    )
    errors += file_errors
    return {
        'body': body,
        'attachments': attachments,
        'special_notes': special_notes,
        'show_remaining_time': bool(post.get('show_remaining_time')),
        'show_start_button': bool(post.get('show_start_button')),
        'show_task_list': bool(post.get('show_task_list')),
    }, errors


def _clean_points(value) -> Decimal | None:
    raw = str(value or '').strip().translate(str.maketrans('۰۱۲۳۴۵۶۷۸۹٫', '0123456789.'))
    try:
        number = Decimal(raw)
    except InvalidOperation:
        return None
    if not number.is_finite() or number <= 0 or number > POINTS_MAX or number.as_tuple().exponent < -2:
        return None
    return number


def _points_text(number: Decimal) -> str:
    return format(number.normalize(), 'f')


def _clean_items(rows, allowed_types, limit, label) -> tuple[list[dict], list[str]]:
    """Validate criterion rows given as dicts (text, type, points, required, guide)."""
    errors, items = [], []
    for index, row in enumerate(rows, start=1):
        text = str(row.get('text') or '').strip()
        guide = str(row.get('guide') or '').strip()
        if not text and not guide:
            continue  # an untouched blank row
        kind = row.get('type') if row.get('type') in allowed_types else ''
        points = _clean_points(row.get('points'))
        if not text:
            errors.append(f'{label} ردیف {index}: متن معیار الزامی است.')
        elif len(text) > CRITERION_TEXT_MAX or len(guide) > CRITERION_TEXT_MAX:
            errors.append(f'{label} ردیف {index}: متن و راهنما هر کدام حداکثر {CRITERION_TEXT_MAX} نویسه است.')
        if not kind:
            errors.append(f'{label} ردیف {index}: نوع معیار نامعتبر است.')
        if points is None:
            errors.append(f'{label} ردیف {index}: امتیاز باید عددی بزرگ‌تر از صفر و حداکثر {POINTS_MAX} با دو رقم اعشار باشد.')
        items.append({'text': text, 'type': kind, 'points': _points_text(points) if points is not None else str(row.get('points') or ''),
                      'required': bool(row.get('required')), 'guide': guide})
    if len(items) > limit:
        errors.append(f'{label}: حداکثر {limit} معیار مجاز است.')
    return items, errors


def _posted_rows(post, prefix) -> list[dict]:
    """Rows are parallel lists; each row carries a uid so «الزامی» checkboxes map to the right row."""
    uids = post.getlist(f'{prefix}_uid')
    texts, kinds = post.getlist(f'{prefix}_text'), post.getlist(f'{prefix}_type')
    points, guides = post.getlist(f'{prefix}_points'), post.getlist(f'{prefix}_guide')
    required = set(post.getlist(f'{prefix}_required'))
    if not (len(uids) == len(texts) == len(points) == len(guides)) or (kinds and len(kinds) != len(uids)):
        return [{'text': '', 'guide': 'invalid', 'type': '', 'points': ''}]
    return [
        {'text': texts[i], 'type': kinds[i] if kinds else 'scale', 'points': points[i], 'guide': guides[i], 'required': uids[i] in required}
        for i in range(len(uids))
    ]


def _criteria_total(items) -> Decimal:
    return sum((_clean_points(item.get('points')) or Decimal(0) for item in items), Decimal(0))


def _criteria_payload(post, station) -> tuple[dict, list[str]]:
    """Validate the «معیارهای ارزیابی» tab."""
    items, errors = _clean_items(_posted_rows(post, 'criteria'), CRITERION_TYPES, CRITERIA_LIMIT, 'چک‌لیست')
    global_items, global_errors = _clean_items(_posted_rows(post, 'global'), {'scale'}, GLOBAL_LIMIT, 'ارزیابی کلی')
    errors += global_errors
    method = station['details'].get('assessment_method') or 'checklist'
    if method in {'checklist', 'combined'} and not items:
        errors.append('حداقل یک معیار در چک‌لیست وارد کنید (روش ارزیابی این ایستگاه شامل چک‌لیست است).')
    if method in {'global_rating', 'combined'} and not global_items:
        errors.append('حداقل یک مورد ارزیابی کلی (Global Rating) وارد کنید (روش ارزیابی این ایستگاه شامل آن است).')

    labels, descriptions = post.getlist('level_label'), post.getlist('level_description')
    levels = [{'label': (labels[i] if i < len(labels) else '').strip(), 'description': (descriptions[i] if i < len(descriptions) else '').strip()}
              for i in range(len(DEFAULT_SCALE_LEVELS))]
    if any(not level['label'] or len(level['label']) > 40 or len(level['description']) > 120 for level in levels):
        errors.append('برای هر پنج سطح عملکرد عنوان (حداکثر ۴۰ نویسه) و توضیح کوتاه (حداکثر ۱۲۰ نویسه) وارد کنید.')

    scoring_mode = post.get('scoring_mode') or ''
    if scoring_mode not in SCORING_MODES:
        errors.append('شیوه نمره‌دهی را انتخاب کنید.')
    total = _criteria_total(items) + _criteria_total(global_items)
    pass_score = None
    if scoring_mode == 'pass_fail':
        pass_score = _clean_points(post.get('pass_score'))
        if pass_score is None or pass_score > total:
            errors.append('حد نصاب قبولی باید عددی بزرگ‌تر از صفر و حداکثر برابر امتیاز کل باشد.')
    return {
        'items': items,
        'global_items': global_items,
        'scale_levels': levels,
        'scoring_mode': scoring_mode,
        'pass_score': _points_text(pass_score) if pass_score is not None else '',
        'total_points': _points_text(total) if total else '0',
        'display': {key: bool(post.get(key)) for key, _label in CRITERIA_DISPLAY_OPTIONS},
    }, errors


def _teacher_templates(teacher_id) -> list[dict]:
    rows = erd_rows(
        'SELECT id, title, items, is_shared FROM osce_criteria_templates WHERE teacher_id = %s ORDER BY created_at DESC',
        [teacher_id],
    )
    return [_template_json(row) for row in rows]


def _template_json(row) -> dict:
    template_id = str(row['id'])
    return {
        'id': template_id, 'title': row['title'], 'items': _json_value(row['items'], []), 'is_shared': bool(row.get('is_shared')),
        'delete_url': reverse('core:teacher_osce_template_delete', args=[template_id]),
        'share_url': reverse('core:teacher_osce_template_share', args=[template_id]),
    }


def _posted_table(post, prefix, fields) -> list[dict] | None:
    """Parallel row lists; None when they do not line up (a tampered or broken form)."""
    columns = {field: post.getlist(f'{prefix}_{field}') for field in fields}
    lengths = {len(values) for values in columns.values()}
    if len(lengths) > 1:
        return None
    count = lengths.pop() if lengths else 0
    return [{field: str(columns[field][i]).strip() for field in fields} for i in range(count)]


def _resources_payload(post, files, station) -> tuple[dict, list[str]]:
    """Validate the «تجهیزات و منابع» tab."""
    errors, tables = [], {}
    previous = station['details'].get('resources', {})
    for prefix, (label, limit, has_status, has_note) in RESOURCE_TABLES.items():
        fields = ['name', 'count'] + (['status'] if has_status else []) + (['note'] if has_note else [])
        rows = _posted_table(post, prefix, fields)
        if rows is None:
            errors.append(f'داده‌های جدول «{label}» ناقص ارسال شده است؛ صفحه را دوباره بارگذاری کنید.')
            rows = []
        kept = []
        for index, row in enumerate(rows, start=1):
            if not row['name'] and not row.get('note'):
                continue
            count = _clean_int(row['count'], 1, 999)
            if not row['name'] or len(row['name']) > RESOURCE_NAME_MAX:
                errors.append(f'{label} ردیف {index}: نام الزامی و حداکثر {RESOURCE_NAME_MAX} نویسه است.')
            if count is None:
                errors.append(f'{label} ردیف {index}: تعداد باید عددی بین ۱ تا ۹۹۹ باشد.')
            if has_status and row['status'] not in RESOURCE_STATUS:
                errors.append(f'{label} ردیف {index}: وضعیت نامعتبر است.')
            if has_note and len(row['note']) > RESOURCE_NOTE_MAX:
                errors.append(f'{label} ردیف {index}: توضیحات حداکثر {RESOURCE_NOTE_MAX} نویسه است.')
            kept.append({**row, 'count': count if count is not None else row['count']})
        if len(kept) > limit:
            errors.append(f'«{label}» حداکثر {limit} ردیف مجاز است.')
        tables[prefix] = kept
    safety_notes = (post.get('safety_notes') or '').strip()
    if len(safety_notes) > NOTES_MAX:
        errors.append(f'نکات اجرایی و ایمنی حداکثر {NOTES_MAX} نویسه است.')
    resource_files, file_errors = _merge_files(
        previous.get('files', []), set(post.getlist('remove_resource_file')), files.getlist('resource_files'),
        RESOURCE_FILE_EXTENSIONS, lambda _name: RESOURCE_FILE_MAX,
    )
    errors += file_errors
    return {**tables, 'files': resource_files, 'safety_notes': safety_notes}, errors


def _examiner_options(teacher_id) -> list[dict]:
    """Teachers of the same org unit (plus the owner); examiners are limited to this list server-side."""
    rows = erd_rows(
        """
        SELECT p.id, p.full_name
        FROM teacher_profiles tp
        JOIN profiles p ON p.id = tp.user_id
        WHERE tp.user_id = %s
           OR (tp.org_unit_id IS NOT NULL
               AND tp.org_unit_id = (SELECT org_unit_id FROM teacher_profiles WHERE user_id = %s)
               AND COALESCE(tp.approval_status, 'approved') <> 'rejected')
        ORDER BY p.full_name
        LIMIT 300
        """,
        [teacher_id, teacher_id],
    )
    return [{'id': str(row['id']), 'name': row['full_name']} for row in rows]


def _timing_payload(post, station, examiner_ids) -> tuple[dict, dict, int | None, list[str]]:
    """Validate «زمان و مدیریت». Returns (station timing, exam rotation, activity minutes, errors)."""
    errors = []
    study = _clean_int(post.get('study_minutes'), 0, 60)
    activity = _clean_int(post.get('duration_minutes'), 1, DURATION_MAX)
    transition = _clean_int(post.get('transition_minutes'), 0, 30)
    capacity = _clean_int(post.get('capacity'), 1, 50)
    groups = _clean_int(post.get('groups_count'), 1, GROUPS_MAX)
    per_group = _clean_int(post.get('students_per_group'), 1, 50)
    start_time = (post.get('start_time') or '').strip()
    pattern = post.get('execution_pattern') or ''
    primary = post.get('primary_examiner') or ''
    second = post.get('second_examiner') or ''
    alert_type = post.get('alert_type') or ''
    if study is None:
        errors.append('زمان مطالعه باید بین ۰ تا ۶۰ دقیقه باشد.')
    if activity is None:
        errors.append(f'مدت زمان فعالیت باید بین ۱ تا {DURATION_MAX} دقیقه باشد.')
    if transition is None:
        errors.append('زمان استراحت/تعویض باید بین ۰ تا ۳۰ دقیقه باشد.')
    if pattern not in EXECUTION_PATTERNS:
        errors.append('حالت اجرای ایستگاه را انتخاب کنید.')
    if capacity is None:
        errors.append('ظرفیت همزمان ایستگاه باید بین ۱ تا ۵۰ باشد.')
    if groups is None or per_group is None:
        errors.append(f'تعداد گروه‌ها (۱ تا {GROUPS_MAX}) و تعداد دانشجو در هر گروه (۱ تا ۵۰) را درست وارد کنید.')
    if not TIME_RE.match(start_time):
        errors.append('ساعت شروع آزمون را به شکل ۰۹:۰۰ وارد کنید.')
    if primary not in examiner_ids:
        errors.append('ارزیاب اصلی را از فهرست انتخاب کنید.')
    if second and (second not in examiner_ids or second == primary):
        errors.append('ارزیاب دوم باید فردی غیر از ارزیاب اصلی و از همین فهرست باشد.')
    if alert_type not in ALERT_TYPES:
        errors.append('نوع هشدار نامعتبر است.')
    timing = {
        'study_minutes': study, 'transition_minutes': transition, 'execution_pattern': pattern, 'capacity': capacity,
        'primary_examiner': primary, 'second_examiner': second, 'concurrent_examiners': bool(post.get('concurrent_examiners')) and bool(second),
        'alerts': {key: bool(post.get(key)) for key, _label in ALERT_OPTIONS}, 'alert_type': alert_type,
    }
    rotation = {'groups_count': groups, 'students_per_group': per_group, 'start_time': start_time}
    return timing, rotation, activity, errors


def _fmt_time(moment: datetime) -> str:
    return moment.strftime('%H:%M')


def build_rotation_schedule(stations, rotation) -> dict | None:
    """Circuit rotation: each group visits every active station once, groups shifted by one station per round.

    All stations share one synchronized round (longest study+activity) and changeover (longest transition).
    More groups than stations run in successive circuits.
    """
    active = [item for item in stations if item['is_active']]
    if not active or not rotation or not TIME_RE.match(rotation.get('start_time') or ''):
        return None
    timings = [item['details'].get('timing', {}) for item in active]
    round_minutes = max((t.get('study_minutes') or 0) + item['duration_minutes'] for t, item in zip(timings, active))
    transition = max(t.get('transition_minutes') or 0 for t in timings)
    hour, minute = map(int, rotation['start_time'].split(':'))
    start = datetime(2000, 1, 1, hour, minute)
    count = len(active)
    groups = rotation.get('groups_count') or 1
    rows = []
    for group in range(groups):
        circuit, local = divmod(group, count)
        circuit_start = start + timedelta(minutes=circuit * count * (round_minutes + transition))
        cells = []
        for station_index in range(count):
            round_index = (station_index - local) % count
            begin = circuit_start + timedelta(minutes=round_index * (round_minutes + transition))
            cells.append(f'{_fmt_time(begin)} - {_fmt_time(begin + timedelta(minutes=round_minutes))}')
        rows.append({'group': group + 1, 'circuit': circuit + 1, 'cells': cells})
    circuits = math.ceil(groups / count)
    end = start + timedelta(minutes=circuits * count * (round_minutes + transition) - transition)
    return {
        'stations': [item['title'] for item in active], 'rows': rows, 'round_minutes': round_minutes,
        'transition_minutes': transition, 'circuits': circuits, 'end_time': _fmt_time(end),
        'crosses_midnight': end.day != start.day,
    }


def _ring_positions(stations) -> list[dict]:
    active = [item for item in stations if item['is_active']]
    nodes = []
    for index, item in enumerate(active):
        angle = math.radians(-90 + index * 360 / max(len(active), 1))
        nodes.append({'title': item['title'], 'number': index + 1,
                      'x': round(50 + 36 * math.cos(angle), 1), 'y': round(50 + 36 * math.sin(angle), 1)})
    return nodes


def _settings_payload(post) -> tuple[dict, list[str]]:
    """Validate the exam-level «تنظیمات تکمیلی» tab."""
    errors = []
    access = post.get('access_scope') or ''
    attempts = _clean_int(post.get('max_attempts'), 1, 5)
    pass_score = _clean_points(post.get('exam_pass_score'))
    negative = (post.get('negative_mark') or '0').strip()
    try:
        negative_value = Decimal(negative)
    except InvalidOperation:
        negative_value = None
    notes = (post.get('exam_notes') or '').strip()
    tags = []
    for tag in post.getlist('tags'):
        tag = tag.strip()
        if tag and tag not in tags:
            tags.append(tag)
    if access not in ACCESS_SCOPES:
        errors.append('محدودیت دسترسی به آزمون نامعتبر است.')
    if attempts is None:
        errors.append('محدودیت تعداد تلاش باید بین ۱ تا ۵ باشد.')
    if pass_score is None:
        errors.append('نمره قبولی آزمون باید عددی بزرگ‌تر از صفر و حداکثر ۱۰۰ باشد.')
    if negative_value is None or not negative_value.is_finite() or not Decimal(0) <= negative_value <= Decimal(1):
        errors.append('نمره منفی باید عددی بین ۰ و ۱ باشد.')
    if len(tags) > TAGS_LIMIT or any(len(tag) > TAG_MAX for tag in tags):
        errors.append(f'حداکثر {TAGS_LIMIT} برچسب، هر کدام حداکثر {TAG_MAX} نویسه.')
    if len(notes) > NOTES_MAX:
        errors.append(f'توضیحات تکمیلی حداکثر {NOTES_MAX} نویسه است.')
    settings = {
        'access_scope': access, 'max_attempts': attempts,
        'pass_score': _points_text(pass_score) if pass_score is not None else '',
        'negative_mark': negative if negative_value is not None else '0',
        'show_correct_after': bool(post.get('show_correct_after')),
        'tags': tags, 'notes': notes,
    }
    for key, _label in EXAM_DISPLAY_OPTIONS + EXAM_SECURITY_TOGGLES + EXAM_NOTIFY_OPTIONS:
        settings[key] = bool(post.get(key))
    return settings, errors


def _save_exam_settings(osce_id, settings):
    erd_execute(
        'UPDATE osce_exams SET settings = %s, updated_at = now() WHERE id = %s',
        [json.dumps(settings, ensure_ascii=False), osce_id],
    )


def _publish_issues(osce, stations) -> list[str]:
    """Everything that must be complete before an OSCE exam can be published."""
    issues = []
    active = [item for item in stations if item['is_active']]
    if not active:
        issues.append('آزمون حداقل یک ایستگاه فعال لازم دارد.')
    for item in active:
        name = f'ایستگاه {item["position"]} ({item["title"]})'
        details = item['details']
        if not details.get('execution_mode'):
            issues.append(f'{name}: نوع ایستگاه و شیوه اجرا ذخیره نشده است.')
        if not delta_length(details.get('instructions', {}).get('body', {})):
            issues.append(f'{name}: دستورالعمل دانشجو ثبت نشده است.')
        if not details.get('criteria'):
            issues.append(f'{name}: معیارهای ارزیابی تعریف نشده است.')
        if not details.get('timing', {}).get('primary_examiner'):
            issues.append(f'{name}: زمان‌بندی و ارزیاب اصلی تعیین نشده است.')
    if not osce['settings'].get('rotation'):
        issues.append('برنامه چرخش (تعداد گروه‌ها و ساعت شروع) در «زمان و مدیریت» ذخیره نشده است.')
    if not osce['settings'].get('exam'):
        issues.append('«تنظیمات تکمیلی» آزمون ذخیره نشده است.')
    return issues


def _reject_if_published(request, osce) -> bool:
    if osce['status'] == 'published':
        messages.error(request, 'این آزمون منتشر شده است؛ برای ویرایش ابتدا آن را به پیش‌نویس برگردانید.')
        return True
    return False


def _save_details(osce_id, station_id, details):
    with transaction.atomic():
        erd_execute(
            'UPDATE osce_stations SET details = %s, updated_at = now() WHERE id = %s AND osce_exam_id = %s',
            [json.dumps(details, ensure_ascii=False), station_id, osce_id],
        )
        erd_execute('UPDATE osce_exams SET updated_at = now() WHERE id = %s', [osce_id])


def _builder_context(request, osce, stations, station, tab, form=None, is_new=False):
    teacher_id = request.erd_profile_id
    index = next((i for i, item in enumerate(stations) if station and item['id'] == station['id']), 0)
    tab_index = IMPLEMENTED_TABS.index(tab)
    return _teacher_modern_context(
        request,
        'osce_builder',
        osce=osce,
        osce_is_new=is_new,
        osce_stations=stations,
        osce_station=station,
        osce_form=form or station or {},
        osce_tab=tab,
        osce_tabs=STATION_TABS,
        osce_prev_tab=IMPLEMENTED_TABS[tab_index - 1] if tab_index > 0 else '',
        osce_next_tab=IMPLEMENTED_TABS[tab_index + 1] if tab_index + 1 < len(IMPLEMENTED_TABS) else '',
        osce_prev_station=stations[index - 1] if station and index > 0 else None,
        osce_next_station=stations[index + 1] if station and index + 1 < len(stations) else None,
        osce_station_types=STATION_TYPES,
        osce_type_about=STATION_TYPE_ABOUT,
        osce_execution_modes=EXECUTION_MODES,
        osce_assessment_methods=ASSESSMENT_METHODS,
        osce_difficulties=DIFFICULTIES,
        osce_domain_suggestions=DOMAIN_SUGGESTIONS,
        osce_course_options=_teacher_question_course_options(teacher_id),
        osce_position_options=range(1, max(len(stations), 1) + 1),
        osce_station_count=len(stations),
        osce_patient_genders=PATIENT_GENDERS,
        osce_patient_roles=PATIENT_ROLES,
        osce_scenario_sections=SCENARIO_SECTIONS,
        osce_instruction_template=INSTRUCTION_TEMPLATE,
        osce_criterion_types=CRITERION_TYPES,
        osce_scoring_modes=SCORING_MODES,
        osce_default_levels=DEFAULT_SCALE_LEVELS,
        osce_default_display=DEFAULT_CRITERIA_DISPLAY,
        osce_display_options=CRITERIA_DISPLAY_OPTIONS,
        osce_builtin_templates=BUILTIN_CRITERIA_TEMPLATES if tab == 'criteria' else [],
        osce_my_templates=_teacher_templates(teacher_id) if tab == 'criteria' else [],
        osce_library_url=reverse('core:teacher_osce_template_library'),
        osce_resource_status=RESOURCE_STATUS,
        osce_execution_patterns=EXECUTION_PATTERNS,
        osce_alert_types=ALERT_TYPES,
        osce_alert_options=ALERT_OPTIONS,
        osce_access_scopes=ACCESS_SCOPES,
        osce_exam_display_options=EXAM_DISPLAY_OPTIONS,
        osce_exam_security_toggles=EXAM_SECURITY_TOGGLES,
        osce_exam_notify_options=EXAM_NOTIFY_OPTIONS,
        osce_examiner_options=_examiner_options(teacher_id) if tab == 'timing' else [],
        osce_rotation=(osce.get('settings') or {}).get('rotation', {}),
        osce_exam_settings=(osce.get('settings') or {}).get('exam', {}),
        osce_schedule=build_rotation_schedule(stations, (osce.get('settings') or {}).get('rotation')) if tab == 'timing' else None,
        osce_ring=_ring_positions(stations) if tab == 'timing' else [],
        osce_is_published=osce.get('status') == 'published',
        osce_instructions_html=delta_to_html((form or station or {}).get('details', {}).get('instructions', {}).get('body', {})),
    )


def _builder_url(osce_id, station_id=None, tab='basic'):
    url = reverse('core:teacher_osce_builder', args=[osce_id])
    if station_id:
        url += f'?station={station_id}&tab={tab}'
    return url


@erd_role_required('teacher')
def teacher_osce_list(request):
    rows = erd_rows(
        """
        SELECT o.id, o.title, o.status, o.updated_at, COUNT(s.id) AS station_count
        FROM osce_exams o LEFT JOIN osce_stations s ON s.osce_exam_id = o.id
        WHERE o.teacher_id = %s
        GROUP BY o.id, o.title, o.status, o.updated_at
        ORDER BY o.updated_at DESC
        """,
        [request.erd_profile_id],
    )
    page = Paginator(rows, LIST_PAGE_SIZE).get_page(request.GET.get('page'))
    for row in page.object_list:
        row['id'] = str(row['id'])
    return render(request, 'teacher/modern.html', _teacher_modern_context(request, 'osce_list', osce_page=page))


@erd_role_required('teacher')
def teacher_osce_create(request):
    """Create the OSCE exam together with its first station (the «اطلاعات پایه» tab)."""
    teacher_id = request.erd_profile_id
    if not teacher_id:
        raise Http404('پروفایل استاد پیدا نشد.')
    course_ids = {str(row['id']) for row in _teacher_question_course_options(teacher_id)}
    if request.method == 'POST':
        exam_title = (request.POST.get('exam_title') or '').strip() or 'آزمون OSCE بدون عنوان'
        course_id = request.POST.get('course_id') or ''
        payload, errors = _basic_payload(request.POST, 1)
        if len(exam_title) > TITLE_MAX:
            errors.append(f'عنوان آزمون حداکثر {TITLE_MAX} نویسه است.')
        if course_id and course_id not in course_ids:
            errors.append('درس انتخاب‌شده معتبر نیست.')
        if not errors:
            osce_id, station_id = str(uuid.uuid4()), str(uuid.uuid4())
            with transaction.atomic():
                erd_execute(
                    'INSERT INTO osce_exams (id, teacher_id, course_id, title, status, settings) VALUES (%s, %s, %s, %s, %s, %s)',
                    [osce_id, teacher_id, course_id or None, exam_title, 'draft', '{}'],
                )
                erd_execute(
                    """
                    INSERT INTO osce_stations (id, osce_exam_id, position, title, code, station_type, domain, difficulty,
                                               duration_minutes, is_active, description, objectives, details)
                    VALUES (%s, %s, 1, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    [station_id, osce_id, payload['title'], payload['code'], payload['station_type'], payload['domain'],
                     payload['difficulty'], payload['duration_minutes'], payload['is_active'], payload['description'],
                     json.dumps(payload['objectives'], ensure_ascii=False), '{}'],
                )
            messages.success(request, 'آزمون OSCE و ایستگاه اول ذخیره شد.')
            return redirect(_builder_url(osce_id, station_id, 'type' if request.POST.get('next') else 'basic'))
        for error in errors:
            messages.error(request, error)
        form = {**payload, 'exam_title': exam_title, 'course_id': course_id}
    else:
        form = {'code': 'OSCE-01', 'station_type': 'clinical', 'difficulty': 'medium', 'duration_minutes': 10,
                'position': 1, 'is_active': True, 'objectives': []}
    osce = {'id': '', 'title': form.get('exam_title', ''), 'course_id': form.get('course_id', '')}
    return render(request, 'teacher/modern.html', _builder_context(request, osce, [], None, 'basic', form, is_new=True))


@erd_role_required('teacher')
def teacher_osce_builder(request, osce_id):
    osce = _owned_osce(request.erd_profile_id, osce_id)
    stations = _stations(osce['id'])
    if not stations:
        # Every station was deleted: show the empty state with only «افزودن ایستگاه جدید».
        return render(request, 'teacher/modern.html', _builder_context(request, osce, [], None, 'basic'))
    requested = request.POST.get('station_id') or request.GET.get('station')
    station = next((item for item in stations if item['id'] == requested), None)
    if requested and station is None:
        raise Http404('ایستگاه پیدا نشد.')
    station = station or stations[0]
    tab = request.POST.get('tab') or request.GET.get('tab') or 'basic'
    if tab not in IMPLEMENTED_TABS:
        tab = 'basic'
    if request.method != 'POST':
        return render(request, 'teacher/modern.html', _builder_context(request, osce, stations, station, tab))
    if _reject_if_published(request, osce):
        return redirect(_builder_url(osce['id'], station['id'], tab))

    if tab == 'basic':
        payload, errors = _basic_payload(request.POST, len(stations))
        if not errors:
            try:
                with transaction.atomic():
                    erd_execute(
                        """
                        UPDATE osce_stations
                        SET title = %s, code = %s, station_type = %s, domain = %s, difficulty = %s, duration_minutes = %s,
                            is_active = %s, description = %s, objectives = %s, updated_at = now()
                        WHERE id = %s AND osce_exam_id = %s
                        """,
                        [payload['title'], payload['code'], payload['station_type'], payload['domain'], payload['difficulty'],
                         payload['duration_minutes'], payload['is_active'], payload['description'],
                         json.dumps(payload['objectives'], ensure_ascii=False), station['id'], osce['id']],
                    )
                    order = [item['id'] for item in stations if item['id'] != station['id']]
                    order.insert(payload['position'] - 1, station['id'])
                    _renumber(osce['id'], order)
                    erd_execute('UPDATE osce_exams SET updated_at = now() WHERE id = %s', [osce['id']])
            except IntegrityError:
                errors.append('این کد ایستگاه قبلاً در همین آزمون استفاده شده است.')
        form = {**station, **payload}
    elif tab == 'scenario':
        scenario, objectives, errors = _scenario_payload(request.POST, request.FILES, station)
        details = {**station['details'], 'scenario': scenario}
        if not errors:
            with transaction.atomic():
                erd_execute(
                    'UPDATE osce_stations SET objectives = %s WHERE id = %s AND osce_exam_id = %s',
                    [json.dumps(objectives, ensure_ascii=False), station['id'], osce['id']],
                )
                _save_details(osce['id'], station['id'], details)
        form = {**station, 'objectives': objectives, 'details': details}
    elif tab == 'instructions':
        instructions, errors = _instructions_payload(request.POST, request.FILES, station)
        details = {**station['details'], 'instructions': instructions}
        if not errors:
            _save_details(osce['id'], station['id'], details)
        form = {**station, 'details': details}
    elif tab == 'criteria':
        criteria, errors = _criteria_payload(request.POST, station)
        details = {**station['details'], 'criteria': criteria}
        if not errors:
            _save_details(osce['id'], station['id'], details)
        form = {**station, 'details': details}
    elif tab == 'resources':
        resources, errors = _resources_payload(request.POST, request.FILES, station)
        details = {**station['details'], 'resources': resources}
        if not errors:
            _save_details(osce['id'], station['id'], details)
        form = {**station, 'details': details}
    elif tab == 'timing':
        examiner_ids = {item['id'] for item in _examiner_options(request.erd_profile_id)}
        timing, rotation, activity, errors = _timing_payload(request.POST, station, examiner_ids)
        details = {**station['details'], 'timing': timing}
        if not errors:
            with transaction.atomic():
                erd_execute(
                    'UPDATE osce_stations SET duration_minutes = %s WHERE id = %s AND osce_exam_id = %s',
                    [activity, station['id'], osce['id']],
                )
                _save_details(osce['id'], station['id'], details)
                _save_exam_settings(osce['id'], {**osce['settings'], 'rotation': rotation})
        form = {**station, 'duration_minutes': activity or station['duration_minutes'], 'details': details}
        osce = {**osce, 'settings': {**osce['settings'], 'rotation': rotation}}
    elif tab == 'settings':
        exam_settings, errors = _settings_payload(request.POST)
        if not errors:
            _save_exam_settings(osce['id'], {**osce['settings'], 'exam': exam_settings})
        osce = {**osce, 'settings': {**osce['settings'], 'exam': exam_settings}}
        form = station
    else:
        payload, errors = _type_payload(request.POST)
        if not errors:
            details = {**station['details'], **payload['details']}
            with transaction.atomic():
                erd_execute(
                    'UPDATE osce_stations SET station_type = %s, details = %s, updated_at = now() WHERE id = %s AND osce_exam_id = %s',
                    [payload['station_type'], json.dumps(details, ensure_ascii=False), station['id'], osce['id']],
                )
                erd_execute('UPDATE osce_exams SET updated_at = now() WHERE id = %s', [osce['id']])
        form = {**station, 'station_type': payload['station_type'] or station['station_type'],
                'details': {**station['details'], **payload['details']}}

    if errors:
        for error in errors:
            messages.error(request, error)
        return render(request, 'teacher/modern.html', _builder_context(request, osce, stations, station, tab, form))
    messages.success(request, 'تغییرات ایستگاه ذخیره شد.')
    if request.POST.get('next') and tab == IMPLEMENTED_TABS[-1]:
        return redirect('core:teacher_osce_preview', osce_id=osce['id'])
    next_tab = IMPLEMENTED_TABS[IMPLEMENTED_TABS.index(tab) + 1] if request.POST.get('next') and tab != IMPLEMENTED_TABS[-1] else tab
    return redirect(_builder_url(osce['id'], station['id'], next_tab))


@require_POST
@erd_role_required('teacher')
def teacher_osce_station_add(request, osce_id):
    osce = _owned_osce(request.erd_profile_id, osce_id)
    if _reject_if_published(request, osce):
        return redirect(_builder_url(osce['id']))
    with transaction.atomic():
        stations = _stations(osce['id'])
        station_id = str(uuid.uuid4())
        position = len(stations) + 1
        erd_execute(
            """
            INSERT INTO osce_stations (id, osce_exam_id, position, title, code, station_type, domain, difficulty,
                                       duration_minutes, is_active, description, objectives, details)
            VALUES (%s, %s, %s, %s, %s, 'clinical', '', 'medium', 10, %s, '', '[]', '{}')
            """,
            [station_id, osce['id'], position, f'ایستگاه {position}', _next_free_code(stations), True],
        )
        erd_execute('UPDATE osce_exams SET updated_at = now() WHERE id = %s', [osce['id']])
    messages.success(request, 'ایستگاه جدید اضافه شد؛ اطلاعات آن را تکمیل کنید.')
    return redirect(_builder_url(osce['id'], station_id))


@require_POST
@erd_role_required('teacher')
def teacher_osce_station_delete(request, osce_id, station_id):
    osce = _owned_osce(request.erd_profile_id, osce_id)
    if _reject_if_published(request, osce):
        return redirect(_builder_url(osce['id']))
    stations = _stations(osce['id'])
    if str(station_id) not in {item['id'] for item in stations}:
        raise Http404('ایستگاه پیدا نشد.')
    with transaction.atomic():
        erd_execute('DELETE FROM osce_stations WHERE id = %s AND osce_exam_id = %s', [str(station_id), osce['id']])
        _renumber(osce['id'], [item['id'] for item in stations if item['id'] != str(station_id)])
        erd_execute('UPDATE osce_exams SET updated_at = now() WHERE id = %s', [osce['id']])
    messages.success(request, 'ایستگاه حذف شد.')
    return redirect('core:teacher_osce_builder', osce_id=osce['id'])


@require_POST
@erd_role_required('teacher')
def teacher_osce_station_reorder(request, osce_id):
    osce = _owned_osce(request.erd_profile_id, osce_id)
    if osce['status'] == 'published':
        return JsonResponse({'ok': False, 'error': 'آزمون منتشر شده است.'}, status=409)
    try:
        order = [str(item) for item in json.loads(request.body or b'{}').get('order', [])]
    except (ValueError, AttributeError):
        return JsonResponse({'ok': False, 'error': 'درخواست نامعتبر است.'}, status=400)
    current = {item['id'] for item in _stations(osce['id'])}
    if len(order) != len(current) or set(order) != current:
        return JsonResponse({'ok': False, 'error': 'فهرست ایستگاه‌ها با آزمون هم‌خوانی ندارد.'}, status=400)
    with transaction.atomic():
        _renumber(osce['id'], order)
        erd_execute('UPDATE osce_exams SET updated_at = now() WHERE id = %s', [osce['id']])
    return JsonResponse({'ok': True})


@require_POST
@erd_role_required('teacher')
def teacher_osce_settings(request, osce_id):
    osce = _owned_osce(request.erd_profile_id, osce_id)
    if _reject_if_published(request, osce):
        return redirect(_builder_url(osce['id']))
    title = (request.POST.get('exam_title') or '').strip()
    course_id = request.POST.get('course_id') or ''
    course_ids = {str(row['id']) for row in _teacher_question_course_options(request.erd_profile_id)}
    if not title or len(title) > TITLE_MAX:
        messages.error(request, f'عنوان آزمون الزامی و حداکثر {TITLE_MAX} نویسه است.')
    elif course_id and course_id not in course_ids:
        messages.error(request, 'درس انتخاب‌شده معتبر نیست.')
    else:
        erd_execute(
            'UPDATE osce_exams SET title = %s, course_id = %s, updated_at = now() WHERE id = %s AND teacher_id = %s',
            [title, course_id or None, osce['id'], request.erd_profile_id],
        )
        messages.success(request, 'مشخصات آزمون ذخیره شد.')
    station_id = request.POST.get('station_id') or ''
    if station_id not in {item['id'] for item in _stations(osce['id'])}:
        station_id = None
    return redirect(_builder_url(osce['id'], station_id))


@require_POST
@erd_role_required('teacher')
def teacher_osce_template_save(request):
    """Save the current checklist as one of the teacher's own templates (JSON in, JSON out)."""
    teacher_id = request.erd_profile_id
    if not teacher_id:
        raise Http404('پروفایل استاد پیدا نشد.')
    try:
        data = json.loads(request.body or b'{}')
    except ValueError:
        return JsonResponse({'ok': False, 'error': 'درخواست نامعتبر است.'}, status=400)
    title = str(data.get('title') or '').strip()
    rows = data.get('items') if isinstance(data.get('items'), list) else []
    items, errors = _clean_items([row for row in rows if isinstance(row, dict)], CRITERION_TYPES, CRITERIA_LIMIT, 'قالب')
    if not title or len(title) > TEMPLATE_TITLE_MAX:
        errors.insert(0, f'عنوان قالب الزامی و حداکثر {TEMPLATE_TITLE_MAX} نویسه است.')
    if not items:
        errors.append('قالب باید حداقل یک معیار داشته باشد.')
    count = erd_row('SELECT COUNT(*) AS n FROM osce_criteria_templates WHERE teacher_id = %s', [teacher_id])['n']
    if count >= TEMPLATES_PER_TEACHER:
        errors.append(f'حداکثر {TEMPLATES_PER_TEACHER} قالب شخصی مجاز است؛ ابتدا قالب‌های قدیمی را حذف کنید.')
    if errors:
        return JsonResponse({'ok': False, 'error': errors[0]}, status=400)
    template_id = str(uuid.uuid4())
    try:
        with transaction.atomic():
            erd_execute(
                'INSERT INTO osce_criteria_templates (id, teacher_id, title, items) VALUES (%s, %s, %s, %s)',
                [template_id, teacher_id, title, json.dumps(items, ensure_ascii=False)],
            )
    except IntegrityError:
        return JsonResponse({'ok': False, 'error': 'قالبی با همین عنوان دارید؛ عنوان دیگری انتخاب کنید.'}, status=400)
    return JsonResponse({'ok': True, 'template': _template_json({'id': template_id, 'title': title, 'items': items, 'is_shared': False})})


@require_POST
@erd_role_required('teacher')
def teacher_osce_template_delete(request, template_id):
    row = erd_row('SELECT id FROM osce_criteria_templates WHERE id = %s AND teacher_id = %s', [str(template_id), request.erd_profile_id])
    if not row:
        raise Http404('قالب پیدا نشد.')
    erd_execute('DELETE FROM osce_criteria_templates WHERE id = %s AND teacher_id = %s', [str(template_id), request.erd_profile_id])
    return JsonResponse({'ok': True})


@erd_role_required('teacher')
def teacher_osce_preview(request, osce_id):
    """Read-only summary of the whole exam plus the publish readiness check."""
    osce = _owned_osce(request.erd_profile_id, osce_id)
    stations = _stations(osce['id'])
    examiners = {item['id']: item['name'] for item in _examiner_options(request.erd_profile_id)}
    for item in stations:
        details = item['details']
        item['instructions_html'] = delta_to_html(details.get('instructions', {}).get('body', {}))
        item['story_html'] = delta_to_html(details.get('scenario', {}).get('story', {}))
        timing = details.get('timing', {})
        item['primary_examiner_name'] = examiners.get(timing.get('primary_examiner'), '')
        item['second_examiner_name'] = examiners.get(timing.get('second_examiner'), '')
    return render(request, 'teacher/modern.html', _teacher_modern_context(
        request, 'osce_preview',
        osce=osce, osce_stations=stations, osce_issues=_publish_issues(osce, stations),
        osce_schedule=build_rotation_schedule(stations, osce['settings'].get('rotation')),
        osce_station_types=STATION_TYPES, osce_execution_modes=EXECUTION_MODES, osce_assessment_methods=ASSESSMENT_METHODS,
        osce_criterion_types=CRITERION_TYPES, osce_resource_status=RESOURCE_STATUS, osce_execution_patterns=EXECUTION_PATTERNS,
        osce_difficulties=DIFFICULTIES, osce_access_scopes=ACCESS_SCOPES, osce_exam_settings=osce['settings'].get('exam', {}),
    ))


@require_POST
@erd_role_required('teacher')
def teacher_osce_publish(request, osce_id):
    osce = _owned_osce(request.erd_profile_id, osce_id)
    if request.POST.get('action') == 'unpublish':
        erd_execute("UPDATE osce_exams SET status = 'draft', updated_at = now() WHERE id = %s AND teacher_id = %s",
                    [osce['id'], request.erd_profile_id])
        messages.success(request, 'آزمون به پیش‌نویس برگشت و دوباره قابل ویرایش است.')
        return redirect('core:teacher_osce_preview', osce_id=osce['id'])
    issues = _publish_issues(osce, _stations(osce['id']))
    if issues:
        messages.error(request, 'آزمون هنوز آماده انتشار نیست؛ موارد فهرست‌شده را کامل کنید.')
        return redirect('core:teacher_osce_preview', osce_id=osce['id'])
    erd_execute("UPDATE osce_exams SET status = 'published', updated_at = now() WHERE id = %s AND teacher_id = %s",
                [osce['id'], request.erd_profile_id])
    messages.success(request, 'آزمون OSCE منتشر شد.')
    return redirect('core:teacher_osce_preview', osce_id=osce['id'])


LIBRARY_LIMIT = 50


@require_POST
@erd_role_required('teacher')
def teacher_osce_template_share(request, template_id):
    """Owner shares or unshares a template with the org-unit library."""
    try:
        shared = bool(json.loads(request.body or b'{}').get('shared'))
    except (ValueError, AttributeError):
        return JsonResponse({'ok': False, 'error': 'درخواست نامعتبر است.'}, status=400)
    row = erd_row('SELECT id FROM osce_criteria_templates WHERE id = %s AND teacher_id = %s', [str(template_id), request.erd_profile_id])
    if not row:
        raise Http404('قالب پیدا نشد.')
    erd_execute('UPDATE osce_criteria_templates SET is_shared = %s WHERE id = %s AND teacher_id = %s',
                [shared, str(template_id), request.erd_profile_id])
    return JsonResponse({'ok': True, 'shared': shared})


@erd_role_required('teacher')
def teacher_osce_template_library(request):
    """Templates shared by other teachers of the same org unit (searchable, capped)."""
    query = (request.GET.get('q') or '').replace('%', '').replace('_', '').strip()[:100]
    params = [request.erd_profile_id, request.erd_profile_id]
    search = ''
    if query:
        search = ' AND t.title ILIKE %s'
        params.append(f'%{query}%')
    rows = erd_rows(
        f"""
        SELECT t.id, t.title, t.items, p.full_name AS author
        FROM osce_criteria_templates t
        JOIN teacher_profiles tp ON tp.user_id = t.teacher_id
        JOIN profiles p ON p.id = t.teacher_id
        WHERE t.is_shared
          AND t.teacher_id <> %s
          AND tp.org_unit_id IS NOT NULL
          AND tp.org_unit_id = (SELECT org_unit_id FROM teacher_profiles WHERE user_id = %s)
          {search}
        ORDER BY t.created_at DESC
        LIMIT {LIBRARY_LIMIT}
        """,
        params,
    )
    return JsonResponse({'ok': True, 'templates': [
        {'id': str(row['id']), 'title': row['title'], 'author': row['author'], 'items': _json_value(row['items'], [])}
        for row in rows
    ]})
