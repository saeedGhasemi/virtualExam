"""The student's settings page: personal details, workspace and notification preferences, security and privacy.

Academic details (student number, field, degree, university, faculty) are recorded by the academic office and are
shown read-only. Preferences live in system_settings under ``student_settings.<profile id>``.
"""
import json
import logging
import re

from django.db import transaction

from .views import _clean_phone, _org_unit_path, _save_avatar_upload, erd_execute, erd_row, log_activity

logger = logging.getLogger(__name__)

SETTINGS_TABS = ('personal', 'workspace', 'security')
NAME_MAX = 60


def personal_info(student_id) -> dict:
    """Identity, academic and contact details shown on the «اطلاعات فردی» tab."""
    row = erd_row(
        """
        SELECT p.first_name, p.last_name, p.full_name, p.email, p.phone, p.avatar_url, p.identifier,
               sp.student_number, sp.field_of_study, sp.degree, sp.department, sp.org_unit_id
        FROM profiles p LEFT JOIN student_profiles sp ON sp.user_id = p.id
        WHERE p.id = %s
        """,
        [student_id],
    ) if student_id else None
    info = dict(row or {})
    if not (info.get('first_name') or info.get('last_name')):
        parts = (info.get('full_name') or '').split()
        info['first_name'], info['last_name'] = (parts[0], ' '.join(parts[1:])) if parts else ('', '')
    info['student_number'] = info.get('student_number') or info.get('identifier') or ''
    unit = _org_unit_path(info.get('org_unit_id'))
    info['university'] = unit.get('university', '')
    info['faculty'] = unit.get('faculty') or unit.get('department') or info.get('department') or ''
    phone = str(info.get('phone') or '')
    info['phone_masked'] = f'{phone[:4]}***{phone[-4:]}' if len(phone) >= 10 else phone
    return info


def readonly_fields(info) -> list:
    """The academic details on the personal tab, in the mockup's order."""
    return [
        {'label': 'شماره دانشجویی', 'icon': 'idcard', 'value': info.get('student_number')},
        {'label': 'رشته تحصیلی', 'icon': 'cap', 'value': info.get('field_of_study')},
        {'label': 'مقطع تحصیلی', 'icon': 'book', 'value': info.get('degree')},
        {'label': 'دانشگاه', 'icon': 'building', 'value': info.get('university')},
        {'label': 'دانشکده', 'icon': 'building', 'value': info.get('faculty'), 'wide': True},
    ]


def save_personal_info(request, student_id) -> list:
    """Validates and saves the «اطلاعات فردی» form; returns error messages (nothing is saved when there are any)."""
    post, errors = request.POST, []
    first_name = (post.get('first_name') or '').strip()
    last_name = (post.get('last_name') or '').strip()
    phone_posted = 'phone' in post  # the mobile input is only sent after «تغییر شماره» is pressed
    phone = _clean_phone(post.get('phone'))
    if not first_name or not last_name:
        errors.append('نام و نام خانوادگی الزامی است.')
    if len(first_name) > NAME_MAX or len(last_name) > NAME_MAX:
        errors.append(f'نام و نام خانوادگی هر کدام حداکثر {NAME_MAX} نویسه است.')
    if phone_posted and not re.fullmatch(r'09\d{9}', phone):
        errors.append('شماره همراه باید ۱۱ رقم و با ۰۹ شروع شود.')
    avatar_url = None
    if request.FILES.get('avatar'):
        avatar_url, avatar_error = _save_avatar_upload(request.FILES['avatar'], student_id)
        if avatar_error:
            errors.append(avatar_error)
    if errors:
        return errors

    with transaction.atomic():
        erd_execute(
            f"""
            UPDATE profiles SET first_name = %s, last_name = %s, full_name = %s,
                   {'phone = %s, ' if phone_posted else ''}{'avatar_url = %s, ' if avatar_url else ''}updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
            """,
            [first_name, last_name, f'{first_name} {last_name}',
             *([phone] if phone_posted else []), *([avatar_url] if avatar_url else []), student_id],
        )
        request.user.first_name, request.user.last_name = first_name, last_name
        request.user.save(update_fields=['first_name', 'last_name'])
    log_activity(request.user, 'profile_updated', 'ویرایش اطلاعات فردی دانشجو', request)
    return []


# Rows of the notification matrix. Only rows with notification types are sent today; the others are shown
# disabled («به‌زودی») until the system sends them. Turning a row off keeps the notification in the list but
# delivers it already read, so nothing a teacher sends is lost.
NOTIFICATION_ROWS = [
    {'key': 'new_exam', 'label': 'آزمون جدید', 'icon': 'list', 'types': ()},
    {'key': 'exam_reminder', 'label': 'یادآوری آزمون', 'icon': 'clock', 'types': ()},
    {'key': 'exam_change', 'label': 'تغییر زمان آزمون', 'icon': 'calendar', 'types': ()},
    {'key': 'results', 'label': 'اعلام نتایج', 'icon': 'chart', 'types': ()},
    {'key': 'objection_reply', 'label': 'پاسخ به درخواست بازبینی نمره', 'icon': 'message', 'types': ()},
    {'key': 'class_message', 'label': 'اطلاعیه کلاس', 'icon': 'bell', 'types': ('teacher_message', 'teacher_feedback')},
]
# The system runs in one language, time zone and calendar today; the tab shows them as fixed facts, not choices.
WORKSPACE_FIXED = [
    {'label': 'زبان سامانه', 'icon': 'globe', 'value': 'فارسی', 'note': 'تنها زبان موجود'},
    {'label': 'منطقه زمانی', 'icon': 'clock', 'value': 'تهران – (GMT+03:30) Asia/Tehran', 'note': 'تنها منطقه‌ی موجود'},
    {'label': 'نوع تقویم', 'icon': 'calendar', 'value': 'تقویم شمسی (هجری شمسی)', 'note': 'تنها تقویم موجود'},
]
MUTABLE_NOTIFICATIONS = {row['key']: row['types'] for row in NOTIFICATION_ROWS if row['types']}


def _settings_key(student_id) -> str:
    return f'student_settings.{student_id}'


def preferences(student_id) -> dict:
    values = {f'inapp_{key}': True for key in MUTABLE_NOTIFICATIONS}
    row = erd_row('SELECT value FROM system_settings WHERE key = %s', [_settings_key(student_id)]) if student_id else None
    stored = row['value'] if row else None
    if isinstance(stored, str):
        try:
            stored = json.loads(stored)
        except json.JSONDecodeError:
            logger.warning('unreadable settings of student %s', student_id)
            stored = None
    if isinstance(stored, dict):
        values.update(stored)
    return values


def _store_preferences(student_id, values) -> None:
    erd_execute(
        """
        INSERT INTO system_settings (key, value, description, updated_by)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_by = excluded.updated_by
        """,
        [_settings_key(student_id), json.dumps(values, ensure_ascii=False), 'Student panel preferences', student_id],
    )


def save_workspace(request, student_id) -> list:
    """Stores the notification switches of the «محیط کار و اعلان‌ها» tab."""
    values = preferences(student_id)
    for key in MUTABLE_NOTIFICATIONS:
        values[f'inapp_{key}'] = request.POST.get(f'inapp_{key}') == 'on'
    _store_preferences(student_id, values)
    return []


def notification_rows(values) -> list:
    return [{**row, 'enabled': bool(row['types']), 'on': values.get(f'inapp_{row["key"]}', False)} for row in NOTIFICATION_ROWS]


def notification_muted(user_id, notification_type) -> bool:
    """True when the user switched this kind of in-app notification off on the settings page."""
    key = next((key for key, types in MUTABLE_NOTIFICATIONS.items() if notification_type in types), None)
    return bool(key) and not preferences(user_id).get(f'inapp_{key}', True)
