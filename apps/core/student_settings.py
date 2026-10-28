"""The student's settings page: personal details, workspace and notification preferences, security and privacy.

Academic details (student number, field, degree, university, faculty) are recorded by the academic office and are
shown read-only. Preferences live in system_settings under ``student_settings.<profile id>``.
"""
import re

from django.db import transaction

from .views import _clean_phone, _org_unit_path, _save_avatar_upload, erd_execute, erd_row, log_activity

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
