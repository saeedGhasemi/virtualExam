"""What a teacher's settings page («تنظیمات استاد») changes elsewhere on the site.

The page stores one JSON payload per teacher (views._teacher_settings_payload). This module is where each saved
option takes effect:

- «پیش‌فرض آزمون»                -> wizard_defaults(): the starting values of a new exam in the wizard
- «تصحیح خودکار سؤالات عینی»     -> wizard_defaults(): correction_mode of a new exam
- «بانک سؤال»                     -> the new-question form (difficulty, autosave), its structure picker, sharing on save
- «بایگانی خودکار»                -> archive_stale_drafts(): drafts untouched for DRAFT_ARCHIVE_DAYS go to the archive
- «تصحیح و بازخورد»               -> grading_views (rubric or a single score, rounding, feedback box, score lock)
- «حریم خصوصی»                    -> public_teacher_cards(): what students see about their teacher
- «تقویم تاریخ»                   -> calendar_for_request() + core_extras: Jalali or Gregorian dates on teacher pages
- «پوسته، جدول فشرده، راهنما، میانبرها» -> ui_context(): the teacher console (teacher/modern.html)
- «کانال‌ها، ایمیل اعلان، نحوه دریافت، عدم مزاحمت» -> in-app muting, browser notifications and send_due_emails()
"""
import json
import logging
from datetime import timedelta

from django.conf import settings
from django.db import connection
from django.utils import timezone

logger = logging.getLogger(__name__)

DRAFT_ARCHIVE_DAYS = 90
DIGEST_HOUR = 8  # «خلاصه روزانه» goes out once a day from this local hour (outside the quiet hours)
SETTINGS_KEY_PREFIX = 'teacher_settings.'
EMAIL_CURSOR_PREFIX = 'teacher_email_cursor.'
EMAIL_SETTLE_SECONDS = 10


def prefs(teacher_id) -> dict:
    from .views import _teacher_settings_payload

    return _teacher_settings_payload(teacher_id) if teacher_id else {}


def is_teacher(profile_id) -> bool:
    from .views import erd_row

    return bool(profile_id and erd_row("SELECT 1 AS ok FROM user_roles WHERE user_id = %s AND role = 'teacher'", [profile_id]))


# ---------------------------------------------------------------- exams and questions

def wizard_defaults(teacher_id) -> dict:
    """«پیش‌فرض آزمون» and «تصحیح خودکار سؤالات عینی» as the wizard's starting field values for a new exam."""
    values = prefs(teacher_id)
    if not values:
        return {}
    instant = values.get('result_release') == 'instant'
    if not values.get('show_result_after_publish', True):
        score_mode = 'manual'  # «نمایش نمرات به دانشجو» off: only when the teacher releases them
    else:
        score_mode = 'immediate' if instant else 'after_publish'
    return {
        'duration_minutes': str(values.get('default_exam_duration') or '60'),
        'max_attempts': str(values.get('default_attempts') or '1'),
        'shuffle_questions': values.get('question_order', 'random') == 'random',
        'negative_marking': bool(values.get('negative_marking')),
        'score_display_mode': score_mode,
        'correct_answer_display_mode': ('immediate' if instant else 'after_publish') if values.get('show_correct_answer') else 'manual',
        'correction_mode': 'auto_then_manual' if values.get('auto_grade_objective', True) else 'manual',
    }


def share_new_question(teacher_id, question_id) -> None:
    """«اشتراک‌گذاری سؤالات: اساتید هم‌درس»: a new published question with a course is shared on save."""
    from .views import erd_execute

    if prefs(teacher_id).get('sharing_mode') != 'department':
        return
    erd_execute(
        'UPDATE questions SET shared_at = %s WHERE id = %s AND teacher_id = %s AND course_id IS NOT NULL '
        'AND COALESCE(is_published, false) = true AND archived_at IS NULL AND shared_at IS NULL',
        [timezone.now(), question_id, teacher_id],
    )


def archive_stale_drafts(now=None) -> list:
    """«بایگانی خودکار»: unpublished drafts not edited for DRAFT_ARCHIVE_DAYS move to the archive (restorable there)."""
    from .views import erd_execute, erd_rows

    now = now or timezone.now()
    archived = []
    for teacher_id, values in _all_teacher_prefs():
        if not values.get('auto_archive'):
            continue
        rows = erd_rows(
            'SELECT id FROM questions WHERE teacher_id = %s AND COALESCE(is_published, false) = false AND archived_at IS NULL '
            'AND updated_at < %s',
            [teacher_id, now - timedelta(days=DRAFT_ARCHIVE_DAYS)],
        )
        for row in rows:
            erd_execute('UPDATE questions SET archived_at = %s WHERE id = %s AND archived_at IS NULL', [now, row['id']])
            archived.append(str(row['id']))
    return archived


# ---------------------------------------------------------------- grading

def grading_rules(teacher_id) -> dict:
    values = prefs(teacher_id)
    return {
        'use_rubric': values.get('essay_grading_default', 'rubric') != 'manual',
        'integer_scores': values.get('rounding') == 'integer',
        'feedback': values.get('text_feedback', True),
        'lock_after_publish': bool(values.get('lock_score_after_publish')),
    }


# ---------------------------------------------------------------- what students see

def public_teacher_cards(teacher_ids) -> dict:
    """teacher id -> {name, bio, email} as a student sees them, following «نمایش پروفایل به دانشجویان»,
    «نمایش ایمیل», «نمایش بیوگرافی» and the display name of the teacher's personal tab."""
    from .views import erd_rows

    ids = [str(teacher_id) for teacher_id in dict.fromkeys(teacher_ids) if teacher_id]
    if not ids:
        return {}
    placeholders = ', '.join(['%s'] * len(ids))
    rows = erd_rows(
        f"""
        SELECT p.id, p.full_name, p.email, tp.display_name, tp.bio, COALESCE(tp.show_bio, true) AS show_bio
        FROM profiles p LEFT JOIN teacher_profiles tp ON tp.user_id = p.id
        WHERE p.id IN ({placeholders})
        """,
        ids,
    )
    cards = {}
    for row in rows:
        values = prefs(row['id'])
        public = values.get('show_name_to_students', True)
        cards[str(row['id'])] = {
            'name': (row.get('display_name') or '').strip() or row.get('full_name') or '',
            'bio': (row.get('bio') or '').strip() if public and row.get('show_bio') else '',
            'email': (row.get('email') or '') if public and values.get('show_email_in_class') else '',
        }
    return cards


# ---------------------------------------------------------------- the teacher console

def calendar_for(teacher_id) -> str:
    return 'gregorian' if prefs(teacher_id).get('date_format') == 'میلادی' else 'jalali'


# «راهنمای سریع» (quick links + Alt+Shift shortcuts) on the console pages. Admins and academic managers reach those
# pages too (question bank, import, OSCE), so every entry points at the page *their* role opens; a role without such a
# page has no entry. key = the shortcut letter (Alt+Shift+key), None = link only.
QUICK_LINKS = {
    'teacher': [
        ('n', 'ایجاد آزمون جدید', 'core:teacher_exam_create'),
        ('q', 'بانک سؤال', 'core:teacher_questions'),
        ('g', 'تصحیح پاسخ‌ها', 'core:teacher_reviews'),
        ('r', 'نتایج آزمون‌ها', 'core:teacher_results'),
        (None, 'تنظیمات', 'core:teacher_settings'),
        ('h', 'داشبورد', 'core:teacher_panel'),
    ],
    'admin': [
        ('n', 'ایجاد آزمون جدید', 'core:super_admin_exam_create'),
        ('q', 'بانک سؤال', 'core:teacher_questions'),
        ('r', 'گزارش‌ها و نتایج', 'core:super_admin_reports'),
        (None, 'تنظیمات سامانه', 'core:super_admin_settings'),
        ('h', 'داشبورد', 'core:super_admin_dashboard'),
    ],
    'academic_manager': [
        ('n', 'ایجاد آزمون جدید', 'core:super_admin_exam_create'),
        ('q', 'بانک سؤال', 'core:teacher_questions'),
        ('r', 'گزارش‌ها و نتایج', 'core:exam_manager_reports'),
        ('h', 'داشبورد', 'core:exam_manager_dashboard'),
    ],
}


def quick_links(role) -> list[dict]:
    from django.urls import reverse

    return [{'key': key or '', 'label': label, 'url': reverse(name)} for key, label, name in QUICK_LINKS.get(role, [])]


def ui_context(teacher_id, role='teacher') -> dict:
    values = prefs(teacher_id)
    return {
        'quick_links': quick_links(role),
        'theme': values.get('theme') if values.get('theme') in ('light', 'dark', 'system') else 'light',
        'compact_tables': bool(values.get('compact_tables')),
        'quick_help': values.get('quick_help', True),
        'shortcuts': values.get('show_page_meta', True),
        'browser_notifications': bool(values.get('browser_channel')) and values.get('system_channel', True),
        'email_ready': bool(settings.EMAIL_HOST),
    }


# ---------------------------------------------------------------- notifications

def in_app_muted(user_id) -> bool:
    """«درون سامانه» off: a teacher's notification is kept, but arrives already read (no badge, no alert)."""
    return is_teacher(user_id) and not prefs(user_id).get('system_channel', True)


def in_quiet_hours(values, now=None) -> bool:
    """«بازه عدم مزاحمت» (it may cross midnight, e.g. 22:00 to 07:00)."""
    start, end = values.get('quiet_start') or '', values.get('quiet_end') or ''
    if not start or not end or start == end:
        return False
    current = timezone.localtime(now or timezone.now()).strftime('%H:%M')
    return start <= current < end if start < end else (current >= start or current < end)


def browser_feed(teacher_id, since) -> dict:
    """Unread notifications newer than `since` for the browser notifications of the teacher console."""
    from .views import erd_datetime, erd_rows

    values = prefs(teacher_id)
    if not values.get('browser_channel') or not values.get('system_channel', True):
        return {'items': [], 'enabled': False}
    since_at = erd_datetime(since) if since else None
    rows = erd_rows(
        'SELECT id, title, message, link, created_at FROM notifications WHERE user_id = %s AND COALESCE(is_read, false) = false '
        'ORDER BY created_at DESC LIMIT 10',
        [teacher_id],
    )
    items = [row for row in rows if not since_at or (erd_datetime(row['created_at']) or since_at) > since_at]
    quiet = in_quiet_hours(values)
    return {
        'enabled': True,
        'quiet': quiet,
        'now': timezone.now().isoformat(),
        'items': [] if quiet else [
            {'id': str(row['id']), 'title': row.get('title') or 'اعلان جدید', 'body': row.get('message') or '', 'link': row.get('link') or ''}
            for row in reversed(items)
        ],
    }


def _all_teacher_prefs():
    """(teacher id, preferences) for every teacher who saved the settings page."""
    with connection.cursor() as cursor:
        cursor.execute('SELECT key, value FROM system_settings WHERE key LIKE %s', [SETTINGS_KEY_PREFIX + '%'])
        rows = cursor.fetchall()
    for key, value in rows:
        teacher_id = key[len(SETTINGS_KEY_PREFIX):]
        if teacher_id == 'demo':
            continue
        try:
            stored = value if isinstance(value, dict) else json.loads(value or '{}')
        except (TypeError, ValueError):
            continue
        if isinstance(stored, dict):
            yield teacher_id, prefs(teacher_id)


def _cursor(teacher_id):
    """(token, state) of the teacher's e-mail cursor, or (None, None) before the first run.

    The token (the description column, plain text) is what the compare-and-set below compares; the state is JSON."""
    with connection.cursor() as cursor:
        cursor.execute('SELECT description, value FROM system_settings WHERE key = %s', [EMAIL_CURSOR_PREFIX + teacher_id])
        row = cursor.fetchone()
    if not row:
        return None, None
    state = row[1]
    if isinstance(state, str):
        try:
            state = json.loads(state)
        except ValueError:
            state = {}
    return row[0], state if isinstance(state, dict) else {}


def _move_cursor(teacher_id, token, state) -> bool:
    """Compare-and-set, so two processes running the due tasks never e-mail the same notifications twice."""
    key, new_token = EMAIL_CURSOR_PREFIX + teacher_id, f"cursor:{state['at']}"
    with connection.cursor() as cursor:
        if token is None:
            cursor.execute(
                'INSERT INTO system_settings (key, value, description) VALUES (%s, %s, %s) ON CONFLICT(key) DO NOTHING',
                [key, json.dumps(state), new_token],
            )
        else:
            cursor.execute('UPDATE system_settings SET value = %s, description = %s WHERE key = %s AND description = %s',
                           [json.dumps(state), new_token, key, token])
        return cursor.rowcount == 1


def send_due_emails(now=None) -> list:
    """«ایمیل» channel: a teacher's notifications are e-mailed («فوری»: within a minute; «خلاصه روزانه»: once a day),
    never inside «بازه عدم مزاحمت» (they go out when it ends). Needs EMAIL_HOST; returns the teachers e-mailed."""
    from django.core.mail import send_mail

    from .views import erd_datetime, erd_row, erd_rows

    if not settings.EMAIL_HOST:
        return []
    now = now or timezone.now()
    local = timezone.localtime(now)
    sent = []
    for teacher_id, values in _all_teacher_prefs():
        if not values.get('email_channel') or in_quiet_hours(values, now):
            continue
        # Only notifications older than EMAIL_SETTLE_SECONDS: one still being saved by a running request is not skipped.
        upto = now - timedelta(seconds=EMAIL_SETTLE_SECONDS)
        token, state = _cursor(teacher_id)
        cursor_at = erd_datetime(state.get('at')) if state else None
        if token is None or cursor_at is None:  # first run: start from now, no backlog of old notifications
            if token is None:
                _move_cursor(teacher_id, None, {'at': upto.isoformat(), 'digest_day': ''})
            continue
        daily = values.get('delivery_mode') == 'daily'
        if daily and (local.hour < DIGEST_HOUR or (state or {}).get('digest_day') == local.date().isoformat()):
            continue
        rows = erd_rows(
            'SELECT title, message FROM notifications WHERE user_id = %s AND created_at > %s AND created_at <= %s '
            'ORDER BY created_at LIMIT 50',
            [teacher_id, cursor_at, upto],
        )
        if not rows and not daily:
            continue
        new_state = {'at': upto.isoformat(), 'digest_day': local.date().isoformat() if daily else (state or {}).get('digest_day', '')}
        if not _move_cursor(teacher_id, token, new_state) or not rows:
            continue
        profile = erd_row('SELECT email FROM profiles WHERE id = %s', [teacher_id]) or {}
        recipient = (values.get('notification_email') or profile.get('email') or '').strip()
        if not recipient:
            continue
        if daily:
            subject = f'خلاصه‌ی روزانه‌ی متاکوییز: {len(rows)} اعلان'
        else:
            subject = (rows[0].get('title') or 'اعلان جدید متاکوییز') if len(rows) == 1 else f'{len(rows)} اعلان جدید در متاکوییز'
        body = '\n\n'.join(f"• {row.get('title') or ''}\n{row.get('message') or ''}" for row in rows)
        try:
            send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [recipient], fail_silently=False)
            sent.append(teacher_id)
        except Exception:
            logger.exception('Sending notification e-mail to teacher %s failed.', teacher_id)
    return sent
