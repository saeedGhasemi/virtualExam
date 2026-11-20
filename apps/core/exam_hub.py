"""«مدیریت آزمون»: one page per exam for its teacher and for academic managers / admins, from the user's mock-ups.

Tabs (same URL, ?tab=…, swapped without reload by live-region.js):
  overview  «نمای کلی»        exam info, KPIs, question make-up by subject, readiness checklist, state banner
  live      «پایش زنده»       every eligible student: progress, connection, attention, status; ?attempt=<id> = one
                               participant (question grid, connection timeline, «افزودن زمان», «ارسال پیام»)
  grading   «تصحیح»            manually graded answers of the exam (grading itself: grading_views.teacher_grading_detail)
  results   «نتایج و تحلیل»   item analysis (p, discrimination, option spread) or ?view=students; ?student=<attempt id>
                               = the student's report card; «انتشار نتایج»; ?export=xlsx
  events    «رخدادها»          the attempts' monitoring events with a review status + note per event
  review    «موارد نیازمند بررسی»  objections, negative-discrimination questions, questions flagged by a note
  settings  «تنظیمات»          title / schedule / attempts / shuffle / result display (limited by who may change what)

Data: exam_attempts (+ extra_minutes, last_seen_at, migration 0064), attempt_answers, activity_audit_log rows with
entity_type 'exam_attempt' (events the exam page reports, «افزودن زمان», «پیام ناظر»; a review is kept in the row's
metadata['review']) and entity_type 'exam' action 'exam_review_note' (notes on questions, «یادداشت بازبینی»).
The exam page checks in through `student_attempt_live` (views.py side: attempt.html) every ~20 s: that sets
last_seen_at («متصل»), returns the remaining time (so added time reaches the open page) and delivers proctor messages.
Template: templates/exam_hub/hub.html (+ _<tab>.html); static/css/exam-hub.css, static/js/exam-hub.js.
"""
import json
import uuid
from datetime import timedelta

from django.contrib import messages
from django.core.paginator import Paginator
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.html import strip_tags
from django.views.decorators.http import require_POST

from .exam_report import (
    _EXAM_REPORT_SQL,
    _LATEST_ATTEMPTS,
    CHOICE_KINDS,
    EXAM_MODE_LABELS,
    EXECUTION_MODE_LABELS,
    _report_questions,
)
from .views import (
    EXAM_STAFF_ROLE_LABELS,
    RESULT_DISPLAY_MODES,
    STUDENT_AVATAR_SQL,
    _erd_exam_in_manager_scope,
    _exam_audience_student_ids,
    _exam_result_visibility,
    _exam_score_scale,
    _exam_status_with_approval,
    _jalali_long_date,
    _posted_max_attempts,
    _set_exam_results_published,
    _sx_answer_files,
    _sx_attempt_ends_at,
    _sx_attempt_extra_sql,
    _sx_dt,
    _sx_exam_cutoff,
    _sx_exam_rules,
    _sx_float,
    _sx_json,
    _sx_percent,
    _sx_result_question_rows,
    _sx_result_status,
    _sx_type_label,
    _teacher_exam_editable,
    _media_kind,
    erd_count,
    erd_datetime,
    erd_execute,
    erd_has_column,
    erd_profile_for_user,
    erd_role_required,
    erd_row,
    erd_rows,
    exam_timing_problem,
    exam_access_code,
    log_activity,
)

TABS = (
    ('overview', 'نمای کلی', 'home'),
    ('live', 'پایش زنده', 'live'),
    ('grading', 'تصحیح', 'check'),
    ('results', 'نتایج و تحلیل', 'chart'),
    ('events', 'رخدادها', 'list'),
    ('review', 'موارد نیازمند بررسی', 'flag'),
    ('settings', 'تنظیمات', 'gear'),
)
TAB_KEYS = {key for key, _label, _icon in TABS}
PAGE_SIZE = 10
CONNECTED_SECONDS = 75          # the exam page checks in every ~20 s; quieter than this = «قطع اتصال»
LIVE_POLL_SECONDS = 20
ADD_TIME_CHOICES = (5, 10, 15, 20, 30, 45, 60)
ADD_TIME_REASON_MAX = 140
MESSAGE_MAX = 300
NOTE_MAX = 200
TITLE_MAX = 50

# activity-log action -> (group, label, icon, needs review by default)
EVENT_KINDS = {
    'exam_disconnected': ('connection', 'قطع اتصال', 'wifi-off', False),
    'exam_reconnected': ('connection', 'اتصال مجدد', 'wifi', False),
    'exam_tab_hidden': ('focus', 'خروج از صفحه', 'focus', True),
    'exam_fullscreen_exit': ('focus', 'خروج از تمام‌صفحه', 'focus', True),
    'exam_copy': ('copy', 'کپی متن', 'copy', True),
    'exam_paste': ('copy', 'چسباندن متن', 'copy', True),
    'exam_screenshot': ('security', 'تلاش برای تصویر صفحه', 'shield', True),
    'exam_camera_off': ('security', 'قطع دوربین', 'camera', True),
    'exam_mic_off': ('security', 'قطع میکروفون', 'camera', True),
    'exam_navigation_attempt': ('security', 'تلاش برای خروج', 'door', True),
    'exam_devtools': ('security', 'ابزار توسعه‌دهنده', 'shield', True),
    'attempt_device_takeover': ('device', 'تغییر دستگاه', 'device', True),
    'exam_time_extended': ('staff', 'افزودن زمان', 'clock', False),
    'exam_proctor_message': ('staff', 'پیام ناظر', 'message', False),
}
EVENT_GROUPS = {
    'connection': 'تغییر اتصال', 'focus': 'تغییر تمرکز', 'copy': 'کپی / چسباندن', 'security': 'امنیت',
    'device': 'دستگاه', 'staff': 'اقدام ناظر',
}
REVIEW_STATES = {'seen': 'مرور شد', 'review': 'نیازمند بررسی', 'none': 'بدون اقدام'}
EVENT_RANGES = {'': 'کل بازه زمانی', 'hour': 'یک ساعت اخیر', 'today': 'امروز'}
ATTENTION_ACTIONS = ('exam_tab_hidden', 'exam_fullscreen_exit')
CONNECTION_ACTIONS = ('exam_disconnected', 'exam_reconnected')
LIVE_STATES = {
    'answering': ('در حال پاسخ‌گویی', 'blue'),
    'offline': ('قطع اتصال', 'red'),
    'submitted': ('ارسال شده', 'green'),
    'not_started': ('شروع نکرده', 'grey'),
}
ANSWER_KINDS = {'text': 'متنی', 'audio': 'صوتی', 'image': 'تصویری', 'video': 'ویدیویی', 'file': 'فایل'}
GRADING_STATES = {'pending': 'در انتظار تصحیح', 'graded': 'تصحیح‌شده', 'all': 'همه'}
MANUAL_TYPES = ('essay', 'descriptive', 'media_response', 'short_answer')
REVIEW_KINDS = {'objection': 'اعتراض به نمره', 'negative': 'تمایز منفی', 'flagged': 'سؤال مهم'}
REVIEW_ITEM_STATES = {'open': 'در حال بررسی', 'done': 'بررسی و ثبت شد', 'answered': 'پاسخ داده شد'}
OBJECTION_DONE = ('resolved', 'accepted', 'rejected', 'answered', 'closed')


# ---------------------------------------------------------------- access

def _role_of(request):
    return 'teacher' if getattr(request, 'erd_role', None) == 'teacher' else 'manager'


def _hub_exam(request, exam_id):
    """The exam row when this account may open its management page (else 404) and what it may do there."""
    role = _role_of(request)
    profile_id = str(request.erd_profile_id)
    exam = erd_row(_EXAM_REPORT_SQL, [exam_id])
    if not exam:
        raise Http404('آزمون پیدا نشد.')
    staff_role = ''
    if role == 'teacher':
        is_owner = str(exam.get('teacher_id')) == profile_id
        if not is_owner:
            staff = erd_row('SELECT role FROM exam_staff WHERE exam_id = %s AND teacher_id = %s LIMIT 1', [exam_id, profile_id])
            if not staff:
                raise Http404('آزمون پیدا نشد.')
            staff_role = staff.get('role') or ''
    else:
        if not _erd_exam_in_manager_scope(request, exam_id):
            raise Http404('آزمون پیدا نشد.')
        is_owner = False
    manager = role == 'manager'
    for column in ('start_at', 'end_at', 'results_published_at', 'registration_end_at', 'approved_at'):
        exam[column] = erd_datetime(exam.get(column))
    if exam['start_at'] and not exam['end_at'] and exam.get('duration_minutes'):
        exam['end_at'] = exam['start_at'] + timedelta(minutes=int(exam['duration_minutes']))
    exam['id'] = str(exam['id'])
    exam['can'] = {
        'live': manager or is_owner or bool(staff_role),
        'grade': is_owner or staff_role == 'co_grader',
        'publish': manager or is_owner,
        'settings': manager or is_owner,
        'schedule': manager or (is_owner and _teacher_exam_editable(exam)),
        'review': manager or is_owner or bool(staff_role),
    }
    exam['role'] = role
    exam['staff_role_label'] = EXAM_STAFF_ROLE_LABELS.get(staff_role, '')
    return exam


def _urls(role, exam_id):
    prefix = 'teacher_exam' if role == 'teacher' else 'super_admin_exam'
    return {
        'hub': reverse(f'core:{prefix}_hub', args=[exam_id]),
        'action': reverse(f'core:{prefix}_hub_action', args=[exam_id]),
        'list': reverse('core:teacher_exams' if role == 'teacher' else 'core:super_admin_exams'),
        'report': reverse(f'core:{prefix}_report', args=[exam_id]),
        'preview': f"{reverse('core:exam_preview', args=[exam_id])}?new=1",
    }


def _state(exam, now):
    """(key, label, tone) as the exam lists show it."""
    if exam.get('is_cancelled'):
        return 'cancelled', 'لغو شده', 'red'
    if not exam.get('is_published'):
        if exam.get('lifecycle_status') == 'pending_approval':
            return 'pending_approval', 'در انتظار تأیید', 'amber'
        if exam.get('lifecycle_status') == 'approved':  # approved, publication scheduled
            return 'scheduled', 'زمان‌بندی انتشار', 'blue'
        return 'draft', 'پیش‌نویس', 'violet'
    start_at, end_at = exam.get('start_at'), exam.get('end_at')
    if start_at and start_at <= now and (not end_at or now <= end_at):
        return 'running', 'در حال برگزاری', 'green'
    if end_at and end_at < now:
        return 'finished', 'پایان‌یافته', 'grey'
    return 'scheduled', 'برنامه‌ریزی شده', 'blue'


def _time(value, seconds=False):
    value = erd_datetime(value) if value and not hasattr(value, 'hour') else value
    if not value:
        return ''
    return timezone.localtime(value).strftime('%H:%M:%S' if seconds else '%H:%M')


def _duration_label(minutes):
    minutes = int(minutes or 0)
    hours, rest = divmod(minutes, 60)
    if not hours:
        return ''
    return f'{hours} ساعت' + (f' و {rest} دقیقه' if rest else '')


def _hms(seconds):
    seconds = max(int(seconds or 0), 0)
    return f'{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}'


def _answer_snippet(value, limit=140):
    parsed = _sx_json(value, value)
    if isinstance(parsed, dict):
        if isinstance(parsed.get('ops'), list):
            parsed = ''.join(str(op.get('insert')) for op in parsed['ops'] if isinstance(op, dict) and isinstance(op.get('insert'), str))
        else:
            parsed = parsed.get('text') or parsed.get('html') or parsed.get('value') or ''
    if isinstance(parsed, list):
        parsed = ' | '.join(str(item) for item in parsed if item not in (None, ''))
    text = ' '.join(strip_tags(str(parsed or '')).split())
    return text if len(text) <= limit else text[:limit].rstrip() + '…'


def _metadata(row):
    data = _sx_json(row.get('metadata'), {}) or {}
    return data if isinstance(data, dict) else {}


# ---------------------------------------------------------------- shared numbers

def _audience(exam_id):
    """Eligible students with name, number, faculty, avatar; and how many group members there are in all."""
    ids = _exam_audience_student_ids(exam_id)
    total = erd_row(
        """
        SELECT COUNT(DISTINCT m.student_user_id) AS n FROM exam_assignments ea
        JOIN student_group_members m ON m.group_id = ea.group_id WHERE ea.exam_id = %s
        """,
        [exam_id],
    )
    return ids, max(int((total or {}).get('n') or 0), len(ids))


def _students(ids):
    if not ids:
        return {}
    marks = ', '.join(['%s'] * len(ids))
    rows = erd_rows(
        f"""
        SELECT p.id, COALESCE(NULLIF(p.full_name, ''), p.username, 'دانشجو') AS name, {STUDENT_AVATAR_SQL} AS avatar_url,
               COALESCE(NULLIF(sp.student_number, ''), p.identifier, '') AS code,
               COALESCE(NULLIF(sp.department, ''), NULLIF(sp.field_of_study, ''), '') AS faculty
        FROM profiles p LEFT JOIN student_profiles sp ON sp.user_id = p.id
        WHERE p.id IN ({marks})
        """,
        ids,
    )
    return {str(row['id']): row for row in rows}


def _question_count(exam_id):
    return erd_count('exam_questions', 'exam_id = %s', [exam_id])


def _attempts(exam_id):
    """Every attempt of the exam with its answered count, newest attempt per student last."""
    last_seen = 'ea.last_seen_at' if erd_has_column('exam_attempts', 'last_seen_at') else 'NULL'
    return erd_rows(
        f"""
        SELECT ea.id, ea.student_id, ea.started_at, ea.submitted_at, ea.status, ea.score, ea.max_score, ea.is_graded,
               {_sx_attempt_extra_sql()} AS extra_minutes, {last_seen} AS last_seen_at,
               (SELECT COUNT(*) FROM attempt_answers aa WHERE aa.attempt_id = ea.id AND aa.answer IS NOT NULL
                  AND CAST(aa.answer AS TEXT) NOT IN ('', '""', '[]', 'null')) AS answered
        FROM exam_attempts ea WHERE ea.exam_id = %s
        ORDER BY ea.started_at NULLS FIRST
        """,
        [exam_id],
    )


def _attempt_events(attempt_ids, actions=None, since=None):
    attempt_ids = [str(item) for item in attempt_ids if item]
    if not attempt_ids:
        return []
    marks = ', '.join(['%s'] * len(attempt_ids))
    actions = list(actions or EVENT_KINDS)
    params = attempt_ids + actions
    since_sql = ''
    if since:
        since_sql, params = ' AND l.created_at >= %s', params + [since]
    return erd_rows(
        f"""
        SELECT l.id, l.action, l.entity_id, l.reason, l.metadata, l.created_at
        FROM activity_audit_log l
        WHERE l.entity_type = 'exam_attempt' AND CAST(l.entity_id AS TEXT) IN ({marks})
          AND l.action IN ({', '.join(['%s'] * len(actions))}){since_sql}
        ORDER BY l.created_at DESC
        """,
        params,
    )


def _deadline(exam, rules, attempt):
    started = _sx_dt(attempt.get('started_at'))
    if not started:
        return None
    cutoff = _sx_exam_cutoff(exam.get('end_at'), rules.get('registration_end_at'))
    return _sx_attempt_ends_at(started, exam.get('duration_minutes'), cutoff, attempt.get('extra_minutes'))


def _live_state(attempt, events_by_attempt, now):
    """'answering' / 'offline' / 'submitted' for one attempt (None: not started)."""
    if attempt.get('submitted_at') or attempt.get('status') in ('submitted', 'graded'):
        return 'submitted'
    events = events_by_attempt.get(str(attempt['id']), [])  # newest first
    last_seen = erd_datetime(attempt.get('last_seen_at'))
    for event in events:
        if event['action'] in CONNECTION_ACTIONS:
            dropped = erd_datetime(event['created_at'])
            if event['action'] == 'exam_disconnected' and (not last_seen or (dropped and dropped >= last_seen)):
                return 'offline'
            break
    # connected = the page checked in (or, before its first check-in, started / reported something) lately; an
    # attempt nobody has heard from for longer is not shown as connected
    moments = [last_seen, erd_datetime(attempt.get('started_at'))]
    moments += [erd_datetime(e['created_at']) for e in events[:1]]
    seen = max((m for m in moments if m), default=None)
    return 'answering' if seen and (now - seen).total_seconds() <= CONNECTED_SECONDS else 'offline'


# ---------------------------------------------------------------- overview

def _overview(exam, now):
    exam_id = exam['id']
    questions = _report_questions(exam_id)
    eligible, members = _audience(exam_id)
    subjects = {}
    for item in questions:
        name = (item.get('tags') or ['سایر مباحث'])[0]
        subjects.setdefault(name, 0)
        subjects[name] += 1
    total_q = len(questions) or 1
    composition = [{'name': name, 'count': count, 'share': round(count * 100 / total_q)}
                   for name, count in sorted(subjects.items(), key=lambda pair: -pair[1])][:6]
    kinds = {item['type_label'] for item in questions}
    total_points = sum(item['points_value'] for item in questions)
    scale = _exam_score_scale(exam)
    groups = erd_rows(
        """
        SELECT COALESCE(NULLIF(sg.course_name, ''), sg.group_code, 'گروه') AS name, sg.group_code
        FROM exam_assignments ea JOIN student_groups sg ON sg.id = ea.group_id
        WHERE ea.exam_id = %s ORDER BY sg.course_name, sg.group_code
        """,
        [exam_id],
    )
    group_names = [f"{row['name']}{(' - ' + row['group_code']) if row['group_code'] and row['group_code'] not in row['name'] else ''}" for row in groups]
    rules = _sx_exam_rules(exam_id)
    checklist = [
        (bool(exam.get('start_at')), 'زمان و تاریخ برگزاری تعیین شده است.', 'زمان و تاریخ برگزاری هنوز تعیین نشده است.'),
        (bool(exam.get('duration_minutes')), f"مدت زمان آزمون ({exam.get('duration_minutes') or 0} دقیقه) تنظیم شده است.", 'مدت زمان آزمون تنظیم نشده است.'),
        (bool(questions), f'تعداد سؤال ({len(questions)}) مشخص شده است.', 'هنوز سؤالی به آزمون اضافه نشده است.'),
        (bool(eligible), f'گروه‌های مجاز ({len(eligible)} نفر) انتخاب شده‌اند.', 'هیچ دانشجویی برای آزمون انتخاب نشده است.'),
        (bool(questions) and all(item['points_value'] > 0 for item in questions), 'بارم همه‌ی سؤال‌ها تعیین شده است.', 'بارم بعضی سؤال‌ها صفر است.'),
        (bool(rules['settings_enforced']), 'تنظیمات نمایش و ترتیب سؤال‌ها انجام شده است.', 'تنظیمات نمایش با مقادیر پیش‌فرض اجرا می‌شود.'),
        (bool(exam.get('is_published')), 'آزمون تأیید و منتشر شده است.', 'آزمون هنوز منتشر نشده است.'),
    ]
    checks = [{'ok': ok, 'text': good if ok else bad} for ok, good, bad in checklist]
    banner = None
    state = exam['state']
    if state in ('running', 'finished'):
        counts = erd_row(
            """
            SELECT COUNT(DISTINCT student_id) AS started,
                   COUNT(DISTINCT CASE WHEN submitted_at IS NULL AND status = 'in_progress' THEN student_id END) AS answering,
                   COUNT(DISTINCT CASE WHEN submitted_at IS NOT NULL THEN student_id END) AS submitted
            FROM exam_attempts WHERE exam_id = %s
            """,
            [exam_id],
        ) or {}
        banner = {k: int(counts.get(k) or 0) for k in ('started', 'answering', 'submitted')}
        banner['absent'] = max(len(eligible) - banner['started'], 0)
        if state == 'running' and exam.get('end_at'):
            banner['remaining'] = int((exam['end_at'] - now).total_seconds())
            banner['remaining_label'] = _hms(banner['remaining'])
        if state == 'finished':
            graded = erd_rows(
                _LATEST_ATTEMPTS + 'SELECT ea.score, ea.max_score FROM exam_attempts ea WHERE ea.id IN (SELECT id FROM latest) '
                'AND COALESCE(ea.is_graded, false) = true AND ea.max_score > 0', [exam_id])
            scores = [_sx_float(row['score'], 0) * scale / _sx_float(row['max_score'], 1) for row in graded]
            banner['average'] = f'{sum(scores) / len(scores):.2f}'.rstrip('0').rstrip('.') if scores else ''
            banner['ungraded'] = erd_count(
                'attempt_answers', 'COALESCE(needs_manual_grading, false) = true AND attempt_id IN '
                '(SELECT id FROM exam_attempts WHERE exam_id = %s AND submitted_at IS NOT NULL)', [exam_id])
    elif state == 'scheduled' and exam.get('start_at'):
        banner = {'starts_in': int((exam['start_at'] - now).total_seconds())}
    return {
        'eligible': len(eligible),
        'members': members,
        'question_count': len(questions),
        'composition': composition,
        'kind_label': next(iter(kinds)) if len(kinds) == 1 else ('ترکیبی' if kinds else '-'),
        'total_points': f'{scale:g}' if exam.get('total_score') else f'{total_points:g}',
        'groups': group_names,
        'checks': checks,
        'ready': all(check['ok'] for check in checks[:5]),
        'mode_label': EXAM_MODE_LABELS.get(exam.get('exam_mode') or 'standard', 'آزمون عادی'),
        'type_label': exam.get('exam_type') or 'آزمون',
        'execution_label': EXECUTION_MODE_LABELS.get(exam.get('execution_mode') or 'web', 'آنلاین'),
        'banner': banner,
    }


# ---------------------------------------------------------------- live monitor

def _live(exam, request, now):
    exam_id = exam['id']
    rules = _sx_exam_rules(exam_id)
    eligible, _members = _audience(exam_id)
    attempts = _attempts(exam_id)
    latest = {}
    for attempt in attempts:  # one row per student: the newest attempt
        latest[str(attempt['student_id'])] = attempt
    ids = list(dict.fromkeys(eligible + list(latest)))
    people = _students(ids)
    events = _attempt_events([a['id'] for a in latest.values()])
    by_attempt = {}
    for event in events:
        by_attempt.setdefault(str(event['entity_id']), []).append(event)
    question_count = _question_count(exam_id) or 1
    rows = []
    for student_id in ids:
        person = people.get(student_id) or {'name': 'دانشجو', 'code': '', 'faculty': '', 'avatar_url': ''}
        attempt = latest.get(student_id)
        row = {**person, 'student_id': student_id, 'attempt_id': '', 'progress': 0, 'attention': 'normal',
               'last_label': '—', 'connection': ''}
        if attempt:
            state = _live_state(attempt, by_attempt, now)
            mine = by_attempt.get(str(attempt['id']), [])
            last = max([erd_datetime(attempt.get('last_seen_at'))] + [erd_datetime(e['created_at']) for e in mine[:1]]
                       + [erd_datetime(attempt.get('started_at'))], key=lambda moment: moment or now - timedelta(days=9999))
            row.update({
                'attempt_id': str(attempt['id']),
                'state': state,
                'progress': min(100, round(int(attempt.get('answered') or 0) * 100 / question_count)),
                'attention': 'low' if any(e['action'] in ATTENTION_ACTIONS for e in mine) else 'normal',
                'connection': 'offline' if state == 'offline' else ('online' if state == 'answering' else ''),
                'last_label': _time(erd_datetime(attempt.get('submitted_at')) or last) or '—',
            })
        else:
            row['state'] = 'not_started'
        row['state_label'], row['state_tone'] = LIVE_STATES[row['state']]
        rows.append(row)
    counts = {key: sum(1 for row in rows if row['state'] == key) for key in LIVE_STATES}
    total = len(rows) or 1
    kpis = {
        'eligible': len(eligible),
        'not_started': counts['not_started'], 'not_started_pct': round(counts['not_started'] * 100 / total, 1),
        'offline': counts['offline'], 'offline_pct': round(counts['offline'] * 100 / total, 1),
        'online': counts['answering'], 'online_pct': round(counts['answering'] * 100 / total, 1),
        'submitted': counts['submitted'],
    }
    end_at = exam.get('end_at')
    kpis['remaining'] = max(int((end_at - now).total_seconds()), 0) if exam['state'] == 'running' and end_at else 0
    kpis['remaining_label'] = _hms(kpis['remaining'])
    kpis['duration_label'] = _hms(int(exam.get('duration_minutes') or 0) * 60)

    # filters
    get = request.GET
    groups = _student_groups(exam_id)
    filters = {
        'q': (get.get('q') or '').strip()[:100],
        'state': get.get('state') if get.get('state') in LIVE_STATES else '',
        'faculty': (get.get('faculty') or '').strip()[:100],
        'group': get.get('group') if get.get('group') in groups['names'] else '',
    }
    faculties = sorted({row['faculty'] for row in rows if row['faculty']})
    listed = [
        row for row in rows
        if (not filters['state'] or row['state'] == filters['state'])
        and (not filters['faculty'] or row['faculty'] == filters['faculty'])
        and (not filters['group'] or row['student_id'] in groups['members'].get(filters['group'], ()))
        and (not filters['q'] or filters['q'] in row['name'] or filters['q'] in str(row['code']))
    ]
    order = {'offline': 0, 'answering': 1, 'submitted': 2, 'not_started': 3}
    listed.sort(key=lambda row: (order[row['state']], row['name']))
    for index, row in enumerate(listed, start=1):
        row['index'] = index
    feed = []
    names = {str(a['id']): (people.get(str(a['student_id'])) or {}).get('name', 'دانشجو') for a in latest.values()}
    for event in events[:6]:
        kind = EVENT_KINDS.get(event['action'])
        if kind:
            feed.append({'name': names.get(str(event['entity_id']), 'دانشجو'), 'label': kind[1], 'icon': kind[2],
                         'tone': 'red' if kind[0] in ('security', 'device') or event['action'] == 'exam_disconnected' else (
                             'amber' if kind[0] in ('focus', 'copy') else 'green'),
                         'time': _time(event['created_at'])})
    return {
        'kpis': kpis, 'rows': listed, 'total_rows': len(rows), 'filters': filters, 'faculties': faculties,
        'groups': sorted(groups['names']),
        'states': LIVE_STATES, 'feed': feed, 'poll': LIVE_POLL_SECONDS if exam['state'] == 'running' else 0,
        'rules_attention': bool(rules.get('track_tab_exit') or rules.get('fullscreen_required')),
    }


def _student_groups(exam_id):
    """The exam's groups by display name, with their members (for «همه گروه‌ها»)."""
    rows = erd_rows(
        """
        SELECT COALESCE(NULLIF(sg.course_name, ''), 'گروه') AS name, sg.group_code, m.student_user_id
        FROM exam_assignments ea JOIN student_groups sg ON sg.id = ea.group_id
        LEFT JOIN student_group_members m ON m.group_id = sg.id
        WHERE ea.exam_id = %s
        """,
        [exam_id],
    )
    members = {}
    for row in rows:
        name = f"{row['name']}{(' - ' + row['group_code']) if row['group_code'] else ''}"
        members.setdefault(name, set())
        if row['student_user_id']:
            members[name].add(str(row['student_user_id']))
    return {'names': set(members), 'members': members}


def _live_attempt(exam, attempt_id, now):
    attempt = erd_row(
        f"""
        SELECT ea.id, ea.student_id, ea.started_at, ea.submitted_at, ea.status, {_sx_attempt_extra_sql()} AS extra_minutes,
               {'ea.last_seen_at' if erd_has_column('exam_attempts', 'last_seen_at') else 'NULL'} AS last_seen_at
        FROM exam_attempts ea WHERE ea.id = %s AND ea.exam_id = %s
        """,
        [attempt_id, exam['id']],
    ) if attempt_id else None
    if not attempt:
        raise Http404('شرکت‌کننده پیدا نشد.')
    person = _students([str(attempt['student_id'])]).get(str(attempt['student_id'])) or {}
    rules = _sx_exam_rules(exam['id'])
    deadline = _deadline(exam, rules, attempt)
    events = _attempt_events([attempt['id']])
    state = _live_state(attempt, {str(attempt['id']): events}, now)
    questions = erd_rows(
        """
        SELECT eq.order_index, eq.question_id,
               CASE WHEN aa.answer IS NOT NULL AND CAST(aa.answer AS TEXT) NOT IN ('', '""', '[]', 'null') THEN 1 ELSE 0 END AS answered,
               COALESCE(aa.marked_for_review, false) AS marked
        FROM exam_questions eq
        LEFT JOIN attempt_answers aa ON aa.attempt_id = %s AND aa.question_id = eq.question_id
        WHERE eq.exam_id = %s ORDER BY eq.order_index NULLS LAST, eq.id
        """,
        [attempt['id'], exam['id']],
    )
    grid = [{'n': index, 'answered': bool(row['answered']), 'marked': bool(row['marked'])} for index, row in enumerate(questions, start=1)]
    answered = sum(1 for cell in grid if cell['answered'])
    remaining = max(int((deadline - now).total_seconds()), 0) if deadline and state != 'submitted' else 0
    timeline = []
    for event in events:
        kind = EVENT_KINDS.get(event['action'])
        if not kind:
            continue
        meta = _metadata(event)
        text = kind[1]
        if event['action'] == 'exam_time_extended':
            text = f"افزودن {meta.get('minutes', '')} دقیقه زمان"
        elif event['action'] == 'exam_proctor_message':
            text = 'پیام ناظر: ' + _answer_snippet(meta.get('text'), 60)
        timeline.append({'label': text, 'icon': kind[2], 'time': _time(event['created_at']),
                         'tone': 'red' if event['action'] == 'exam_disconnected' or kind[0] in ('security', 'device') else (
                             'amber' if kind[0] in ('focus', 'copy') else 'green')})
    timeline.append({'label': 'ورود و شروع آزمون', 'icon': 'start', 'time': _time(attempt['started_at']), 'tone': 'green'})
    if attempt.get('submitted_at'):
        timeline.insert(0, {'label': 'ارسال نهایی آزمون', 'icon': 'check', 'time': _time(attempt['submitted_at']), 'tone': 'green'})
    return {
        'attempt': attempt, 'person': person, 'grid': grid, 'answered': answered, 'question_count': len(grid),
        'answered_pct': round(answered * 100 / len(grid)) if grid else 0,
        'state': state, 'state_label': LIVE_STATES[state][0], 'state_tone': LIVE_STATES[state][1],
        'started_label': _time(attempt['started_at']), 'remaining': remaining, 'remaining_label': _hms(remaining),
        'duration_label': _hms((int(exam.get('duration_minutes') or 0) + int(attempt.get('extra_minutes') or 0)) * 60),
        'extra_minutes': int(attempt.get('extra_minutes') or 0),
        'open': state != 'submitted' and remaining > 0,
        'timeline': timeline[:12], 'add_time_choices': ADD_TIME_CHOICES,
        'reason_max': ADD_TIME_REASON_MAX, 'message_max': MESSAGE_MAX,
        'poll': LIVE_POLL_SECONDS if state != 'submitted' else 0,
    }


# ---------------------------------------------------------------- grading queue

def _grading(exam, request):
    exam_id = exam['id']
    get = request.GET
    status = get.get('status') if get.get('status') in GRADING_STATES else 'pending'
    filters = {
        'status': status,
        'q': (get.get('q') or '').strip()[:100],
        'question': (get.get('question') or '').strip()[:8],
        'kind': get.get('kind') if get.get('kind') in ANSWER_KINDS else '',
        'sort': 'oldest' if get.get('sort') == 'oldest' else 'newest',
    }
    scope_sql, scope_params = '', []
    if exam['role'] == 'teacher' and not exam['can']['grade']:
        scope_sql, scope_params = ' AND q.teacher_id = %s', [str(request.erd_profile_id)]
    may_grade = exam['role'] == 'teacher'  # teachers see only answers they may grade (exam owner, co-grader, question owner)
    first_grade = 'aa.first_grade' if erd_has_column('attempt_answers', 'first_grade') else 'NULL'
    rows = erd_rows(
        f"""
        SELECT aa.id, aa.attempt_id, aa.question_id, aa.answer, aa.answer_files, aa.points_awarded, aa.needs_manual_grading,
               aa.graded_at, ea.submitted_at, ea.student_id, q.type, q.scoring_settings, eq.order_index, {first_grade} AS first_grade,
               COALESCE(eq.points, q.default_points, 1) AS max_points
        FROM attempt_answers aa
        JOIN exam_attempts ea ON ea.id = aa.attempt_id
        JOIN questions q ON q.id = aa.question_id
        LEFT JOIN exam_questions eq ON eq.exam_id = ea.exam_id AND eq.question_id = q.id
        WHERE ea.exam_id = %s AND ea.submitted_at IS NOT NULL
          AND q.type IN ({', '.join(f"'{kind}'" for kind in MANUAL_TYPES)}){scope_sql}
        """,
        [exam_id, *scope_params],
    )
    ordered = {str(row['question_id']): index for index, row in enumerate(erd_rows(
        'SELECT question_id FROM exam_questions WHERE exam_id = %s ORDER BY order_index NULLS LAST, id', [exam_id]), start=1)}
    people = _students(list({str(row['student_id']) for row in rows}))
    items = []
    for row in rows:
        files = _sx_answer_files(row.get('answer_files'))
        kind = 'text'
        media = None
        if files:
            file = files[0]
            found = file.get('kind') or _media_kind(file.get('name') or file.get('path'))
            kind = found if found in ('audio', 'image', 'video') else 'file'
            # answer files stream only to the exam's / question's teacher and co-graders (attempt_answer_file)
            media = {'url': reverse('core:attempt_answer_file', args=[row['attempt_id'], file['id']]) if may_grade else '',
                     'name': file.get('name') or 'فایل پاسخ'}
        pending = bool(row.get('needs_manual_grading'))
        settings_data = _sx_json(row.get('scoring_settings'), {}) or {}
        essay = (settings_data.get('essay') or {}) if isinstance(settings_data, dict) else {}
        person = people.get(str(row['student_id'])) or {}
        blind = bool(essay.get('blind_grading'))
        items.append({
            'id': str(row['id']), 'attempt_id': str(row['attempt_id']), 'files': files, 'kind': kind, 'kind_label': ANSWER_KINDS[kind], 'media': media,
            'snippet': _answer_snippet(row.get('answer')),
            'pending': pending, 'graded': bool(row.get('graded_at')) and not pending,
            'points': _sx_float(row.get('points_awarded'), 0), 'max_points': _sx_float(row.get('max_points'), 0),
            'question_no': ordered.get(str(row.get('question_id', '')), row.get('order_index') or 0),
            'submitted_at': erd_datetime(row.get('submitted_at')),
            'name': f'دانشجوی ناشناس #{str(row["id"]).replace("-", "")[:6].upper()}' if blind else person.get('name', 'دانشجو'),
            'code': '' if blind else person.get('code', ''), 'avatar_url': '' if blind else person.get('avatar_url', ''),
            'url': f"?tab=grading&answer={row['id']}" if may_grade else '',
        })
    counts = {'pending': sum(1 for i in items if i['pending']), 'graded': sum(1 for i in items if i['graded']), 'all': len(items)}
    graded_scores = [(i['points'], i['max_points']) for i in items if i['graded'] and i['max_points']]
    average = sum(p for p, _m in graded_scores) / len(graded_scores) if graded_scores else None
    max_avg = sum(m for _p, m in graded_scores) / len(graded_scores) if graded_scores else 0
    listed = [
        i for i in items
        if (status == 'all' or (status == 'pending' and i['pending']) or (status == 'graded' and i['graded']))
        and (not filters['kind'] or i['kind'] == filters['kind'])
        and (not filters['question'] or str(i['question_no']) == filters['question'])
        and (not filters['q'] or filters['q'] in i['name'] or filters['q'] in str(i['code']))
    ]
    listed.sort(key=lambda i: (i['submitted_at'] or timezone.now()), reverse=filters['sort'] == 'newest')
    page = Paginator(listed, PAGE_SIZE).get_page(get.get('page'))
    for index, item in enumerate(page.object_list, start=page.start_index()):
        item['index'] = index
    return {
        'filters': filters, 'counts': counts, 'page': page, 'rows': page.object_list,
        'percent': round(counts['graded'] * 100 / counts['all']) if counts['all'] else 0,
        'average': f'{average:.2f}'.rstrip('0').rstrip('.') if average is not None else '',
        'average_of': f'{max_avg:g}' if graded_scores else '',
        'question_numbers': sorted({i['question_no'] for i in items if i['question_no']}),
        'kinds': ANSWER_KINDS, 'states': GRADING_STATES,
    }


# ---------------------------------------------------------------- results / item analysis

def _item_analysis(exam):
    """Questions with p (share of the points earned), discrimination (upper − lower 27 %) and the option spread.

    p is the standard difficulty / facility index: the mean score on the question as a share of its points (for a
    one-answer question the share who got it right; partial credit and essays count what they earned, like Moodle's
    «Facility index»). score_pct = p in percent is what «میانگین نمره (٪)» shows, so it always agrees with «سختی».
    Answers still waiting for the teacher's grade are left out of their question's p instead of counting as zero."""
    exam_id = exam['id']
    items = _report_questions(exam_id)
    graded_by = 'aa.graded_by' if erd_has_column('attempt_answers', 'graded_by') else 'NULL'
    rows = erd_rows(
        _LATEST_ATTEMPTS + f"""
        SELECT ea.id AS attempt_id, ea.score, ea.max_score, aa.question_id, aa.points_awarded, aa.is_correct,
               COALESCE(aa.needs_manual_grading, false) AS needs_manual_grading, {graded_by} AS graded_by,
               COALESCE(eq.points, q.default_points, 1) AS max_points
        FROM exam_attempts ea
        JOIN attempt_answers aa ON aa.attempt_id = ea.id
        JOIN exam_questions eq ON eq.exam_id = ea.exam_id AND eq.question_id = aa.question_id
        JOIN questions q ON q.id = aa.question_id
        WHERE ea.id IN (SELECT id FROM latest)
        """,
        [exam_id],
    )
    totals, marks, waiting = {}, {}, {}
    for row in rows:
        attempt = str(row['attempt_id'])
        max_points = _sx_float(row['max_points'], 0) or 1
        if row.get('needs_manual_grading') and not row.get('graded_by') and not _sx_float(row['points_awarded'], 0):
            waiting.setdefault(str(row['question_id']), set()).add(attempt)  # not graded yet: no evidence either way
            totals.setdefault(attempt, 0)
            continue
        share = 1.0 if row.get('is_correct') in (True, 1, '1', 't', 'true') else max(min(_sx_float(row['points_awarded'], 0) / max_points, 1), 0)
        marks.setdefault(str(row['question_id']), {})[attempt] = share
        totals[attempt] = totals.get(attempt, 0) + share * max_points
    ranked = sorted(totals, key=lambda attempt: totals[attempt])
    cut = max(1, round(len(ranked) * 0.27)) if len(ranked) >= 4 else 0
    lower, upper = set(ranked[:cut]), set(ranked[-cut:]) if cut else set()
    for item in items:
        scores = marks.get(item['id'], {})
        pending = waiting.get(item['id'], set())
        n = len(ranked) - len(pending)
        p = sum(scores.values()) / n if n > 0 else None
        d = None
        if cut and not pending:
            d = sum(scores.get(a, 0) for a in upper) / cut - sum(scores.get(a, 0) for a in lower) / cut
        item['p'] = round(p, 2) if p is not None else None
        item['d'] = round(d, 2) if d is not None else None
        item['score_pct'] = round(p * 100) if p is not None else None
        item['waiting'] = len(pending)
        flags = []
        if d is not None and d < 0:
            flags.append(('negative', 'تمایز منفی', 'red'))
        if p is not None and n and p < 0.3:
            flags.append(('hard', 'دشوار', 'amber'))
        if p is not None and n and p > 0.9:
            flags.append(('easy', 'آسان', 'blue'))
        item['flags'] = [{'key': k, 'label': label, 'tone': tone} for k, label, tone in flags]
        item['short'] = item['text'] if len(item['text']) <= 60 else item['text'][:60].rstrip() + '…'
        if item['type'] in CHOICE_KINDS:
            letters = ['الف', 'ب', 'ج', 'د', 'هـ', 'و', 'ز', 'ح']
            for number, option in enumerate(item['options']):
                option['letter_fa'] = letters[number] if number < len(letters) else str(number + 1)
    return items, len(ranked)


def _results(exam, request):
    get = request.GET
    view = 'items' if get.get('view') == 'items' else 'summary'
    items, takers = _item_analysis(exam)
    scale = _exam_score_scale(exam)
    graded = erd_rows(
        _LATEST_ATTEMPTS + 'SELECT ea.score, ea.max_score FROM exam_attempts ea WHERE ea.id IN (SELECT id FROM latest) '
        'AND COALESCE(ea.is_graded, false) = true AND ea.max_score > 0', [exam['id']])
    scores = [_sx_float(row['score'], 0) * scale / _sx_float(row['max_score'], 1) for row in graded]
    with_d = [i['d'] for i in items if i['d'] is not None]
    kpis = {
        'questions': len(items),
        'score_pct': round(sum(i['score_pct'] for i in scored) / len(scored)) if (scored := [i for i in items if i['score_pct'] is not None]) else None,
        'discrimination': f'{sum(with_d) / len(with_d):.2f}' if with_d else '—',
        'negative': sum(1 for i in items if any(f['key'] == 'negative' for f in i['flags'])),
        'average': f'{sum(scores) / len(scores):.2f}'.rstrip('0').rstrip('.') if scores else '—',
        'scale': f'{scale:g}', 'takers': takers,
    }
    filters = {
        'q': (get.get('q') or '').strip()[:100],
        'flag': get.get('flag') if get.get('flag') in ('negative', 'hard', 'easy', 'ok') else '',
        'type': (get.get('type') or '').strip()[:30],
    }
    listed = [
        i for i in items
        if (not filters['q'] or filters['q'] in i['text'] or filters['q'] == str(i['index']))
        and (not filters['type'] or i['type_label'] == filters['type'])
        and (not filters['flag'] or (filters['flag'] == 'ok' and not i['flags']) or any(f['key'] == filters['flag'] for f in i['flags']))
    ]
    try:
        selected_no = int(get.get('q_no') or 0)
    except ValueError:
        selected_no = 0
    selected = next((i for i in items if i['index'] == selected_no), None) or (listed[0] if listed else (items[0] if items else None))
    page = Paginator(listed, PAGE_SIZE).get_page(get.get('page')) if view == 'items' else None
    students = _result_students(exam, get) if view == 'summary' else None
    for item in items:
        p = item['p']
        item['level'] = (None if p is None else ('آسان', 'green') if p >= 0.7 else ('متوسط', 'amber') if p >= 0.4 else ('سخت', 'red'))
        negative = any(f['key'] == 'negative' for f in item['flags'])
        item['verdict'] = 'bad' if negative else ('warn' if item['d'] is not None and item['d'] < 0.3 else 'ok')
    visibility = _exam_result_visibility(exam)
    return {
        'view': view, 'kpis': kpis, 'items': items, 'page': page, 'rows': page.object_list if page else [],
        'filters': filters, 'types': sorted({i['type_label'] for i in items}), 'selected': selected,
        'prev_no': selected['index'] - 1 if selected and selected['index'] > 1 else 0,
        'next_no': selected['index'] + 1 if selected and selected['index'] < len(items) else 0,
        'students': students, 'mini': items[:5], 'published': bool(exam.get('results_published_at')),
        'published_label': _jalali_long_date(exam.get('results_published_at')) if exam.get('results_published_at') else '',
        'score_shown': visibility['score'],
    }


def _result_students(exam, get):
    scale = _exam_score_scale(exam)
    rows = erd_rows(
        _LATEST_ATTEMPTS + """
        SELECT ea.id, ea.student_id, ea.score, ea.max_score, ea.is_graded, ea.submitted_at, ea.started_at
        FROM exam_attempts ea WHERE ea.id IN (SELECT id FROM latest)
        """,
        [exam['id']],
    )
    people = _students([str(row['student_id']) for row in rows])
    out = []
    for row in rows:
        person = people.get(str(row['student_id'])) or {}
        graded = bool(row.get('is_graded')) and row.get('score') is not None and _sx_float(row.get('max_score'), 0) > 0
        score = _sx_float(row['score'], 0) * scale / _sx_float(row['max_score'], 1) if graded else None
        label, tone, _pending = _sx_result_status({**row, 'passing_score': exam.get('passing_score'),
                                                   'passing_percent': exam.get('passing_percent'),
                                                   'percent': _sx_percent(row['score'], row['max_score'])})
        out.append({**person, 'attempt_id': str(row['id']), 'score': score,
                    'score_label': f'{score:.2f}'.rstrip('0').rstrip('.') if score is not None else '—',
                    'percent': _sx_percent(row['score'], row['max_score']) if graded else None,
                    'status_label': label, 'status_tone': {'green': 'green', 'red': 'red'}.get(tone, 'amber'),
                    'submitted_label': _time(row['submitted_at'])})
    for row in out:
        row['outcome'] = 'pass' if row['status_label'] == 'قبول' else ('fail' if row['status_label'] == 'مردود' else 'pending')
    scored = [row['score'] for row in out if row['score'] is not None]
    bands = []
    for number in range(5):  # 0–4 … 16–20, stretched to the exam's own scale
        low, high = number * scale / 5, (number + 1) * scale / 5
        count = sum(1 for score in scored if low <= score < high or (number == 4 and score >= high))
        bands.append({'key': str(number), 'label': f'{low:g}–{high:g}', 'count': count,
                      'tone': 'red' if number < 2 else ('amber' if number == 2 else 'green')})
    peak = max([band['count'] for band in bands] + [1])
    axis = max(5, -(-peak // 5) * 5)
    for band in bands:
        band['height'] = round(band['count'] * 100 / axis)
    passed = sum(1 for row in out if row['outcome'] == 'pass')
    failed = sum(1 for row in out if row['outcome'] == 'fail')
    decided = passed + failed
    summary = {
        'takers': len(out), 'passed': passed, 'failed': failed, 'pending': len(out) - decided,
        'pass_pct': round(passed * 100 / decided) if decided else 0, 'fail_pct': round(failed * 100 / decided) if decided else 0,
        'average': f'{sum(scored) / len(scored):.2f}'.rstrip('0').rstrip('.') if scored else '—',
        'bands': bands, 'axis': [axis * step // 5 for step in range(5, -1, -1)],
    }
    q = (get.get('q') or '').strip()[:100]
    outcome = get.get('outcome') if get.get('outcome') in ('pass', 'fail', 'pending') else ''
    band = get.get('band') if get.get('band') in {b['key'] for b in bands} else ''
    listed = [
        row for row in out
        if (not q or q in row.get('name', '') or q in str(row.get('code', '')))
        and (not outcome or row['outcome'] == outcome)
        and (not band or (row['score'] is not None and (int(band) * scale / 5 <= row['score'] < (int(band) + 1) * scale / 5
                                                         or (band == '4' and row['score'] >= scale))))
    ]
    listed.sort(key=lambda row: (row['score'] is None, -(row['score'] or 0), row.get('name', '')))
    for index, row in enumerate(listed, start=1):
        row['rank'] = index
    page = Paginator(listed, PAGE_SIZE).get_page(get.get('page'))
    return {'page': page, 'rows': page.object_list, 'all': listed, 'filters': {'q': q, 'outcome': outcome, 'band': band},
            'scale': f'{scale:g}', 'summary': summary,
            'outcomes': {'pass': 'قبول', 'fail': 'مردود', 'pending': 'در انتظار تصحیح'}}


def _student_card(exam, attempt_id, get):
    attempt = erd_row(
        """
        SELECT ea.id, ea.student_id, ea.score, ea.max_score, ea.is_graded, ea.started_at, ea.submitted_at, ea.status
        FROM exam_attempts ea WHERE ea.id = %s AND ea.exam_id = %s
        """,
        [attempt_id, exam['id']],
    ) if attempt_id else None
    if not attempt:
        raise Http404('کارنامه پیدا نشد.')
    person = _students([str(attempt['student_id'])]).get(str(attempt['student_id'])) or {}
    rows = _sx_result_question_rows(attempt['id'], attempt['student_id'])
    tone_labels = {'good': ('صحیح', 'green'), 'bad': ('نادرست', 'red'), 'partial': ('ناقص', 'amber'), 'empty': ('بدون پاسخ', 'grey')}
    for row in rows:
        row['status_label'], row['status_tone'] = tone_labels[row['tone']]
        chosen = [o['label'] for o in row['options'] if o.get('chosen')]
        keys = [o['label'] for o in row['options'] if o.get('correct')]
        row['student_answer'] = _answer_snippet('، '.join(chosen) if row['options'] else row['answer_text'], 60) or '—'
        row['key_answer'] = _answer_snippet('، '.join(keys), 60) if row['options'] else '—'
        row['short'] = _answer_snippet(row['text'], 70)
        row['feedback_short'] = _answer_snippet(row['feedback'] or row['explanation'], 70) or '—'
    status_filter = get.get('status') if get.get('status') in tone_labels else ''
    subject = (get.get('subject') or '').strip()[:100]
    q = (get.get('q') or '').strip()[:100]
    listed = [r for r in rows if (not status_filter or r['tone'] == status_filter) and (not subject or r['subject'] == subject)
              and (not q or q in r['text'] or q in (r['feedback'] or ''))]
    page = Paginator(listed, PAGE_SIZE).get_page(get.get('page'))
    scale = _exam_score_scale(exam)
    graded = bool(attempt.get('is_graded')) and _sx_float(attempt.get('max_score'), 0) > 0
    percent = _sx_percent(attempt['score'], attempt['max_score']) if graded else 0
    started, submitted = erd_datetime(attempt.get('started_at')), erd_datetime(attempt.get('submitted_at'))
    status_label, status_tone, _pending = _sx_result_status({**attempt, 'passing_score': exam.get('passing_score'),
                                                             'passing_percent': exam.get('passing_percent'), 'percent': percent})
    return {
        'attempt_id': str(attempt['id']), 'person': person, 'page': page, 'rows': page.object_list,
        'filters': {'status': status_filter, 'subject': subject, 'q': q}, 'tones': {k: v[0] for k, v in tone_labels.items()},
        'subjects': sorted({r['subject'] for r in rows if r['subject']}),
        'total': len(rows), 'good': sum(1 for r in rows if r['tone'] == 'good'),
        'bad': sum(1 for r in rows if r['tone'] in ('bad', 'partial')), 'empty': sum(1 for r in rows if r['tone'] == 'empty'),
        'percent': percent, 'graded': graded,
        'score': f"{_sx_float(attempt['score'], 0) * scale / _sx_float(attempt['max_score'], 1):.2f}".rstrip('0').rstrip('.') if graded else '—',
        'scale': f'{scale:g}', 'status_label': status_label, 'status_tone': status_tone,
        'submitted': bool(submitted),
        'start_label': f"{_jalali_long_date(started, with_weekday=False)}، {_time(started)}" if started else '—',
        'end_label': f"{_jalali_long_date(submitted, with_weekday=False)}، {_time(submitted)}" if submitted else '—',
        'minutes': int((submitted - started).total_seconds() // 60) if started and submitted else None,
        'published': _exam_result_visibility(exam)['score'],
        'objection': erd_row('SELECT subject FROM objections WHERE attempt_id = %s LIMIT 1', [attempt['id']]),
    }


def _xlsx_items(exam, items):
    from openpyxl import Workbook

    book = Workbook()
    sheet = book.active
    sheet.title = 'تحلیل سؤال'
    sheet.sheet_view.rightToLeft = True
    sheet.append(['#', 'متن سؤال', 'نوع', 'میانگین نمره (٪)', 'شاخص دشواری (p)', 'شاخص تمایز', 'پرچم‌ها'])
    for item in items:
        sheet.append([item['index'], item['text'], item['type_label'], item['score_pct'], item['p'], item['d'],
                      '، '.join(f['label'] for f in item['flags'])])
    response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = f'attachment; filename="exam-{exam["id"][:8]}-analysis.xlsx"'
    book.save(response)
    return response


def _xlsx_students(exam, students):
    from openpyxl import Workbook

    book = Workbook()
    sheet = book.active
    sheet.title = 'نتایج دانشجویان'
    sheet.sheet_view.rightToLeft = True
    sheet.append(['ردیف', 'نام دانشجو', 'شماره دانشجویی', f"نمره (از {students['scale']})", 'درصد', 'وضعیت'])
    for row in students['all']:
        sheet.append([row['rank'], row.get('name', ''), row.get('code', ''), row['score'], row['percent'], row['status_label']])
    response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = f'attachment; filename="exam-{exam["id"][:8]}-results.xlsx"'
    book.save(response)
    return response


def _xlsx_review(exam, review):
    from openpyxl import Workbook

    book = Workbook()
    sheet = book.active
    sheet.title = 'موارد نیازمند بررسی'
    sheet.sheet_view.rightToLeft = True
    sheet.append(['ردیف', 'نوع مورد', 'سؤال', 'دانشجو', 'شرح مورد', 'شواهد و توضیحات', 'وضعیت رسیدگی'])
    for index, row in enumerate(review['all'], start=1):
        sheet.append([index, row['kind_label'], row['question_no'], row['student'], row['title'], ' | '.join(row['evidence']),
                      row['status_label']])
    response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = f'attachment; filename="exam-{exam["id"][:8]}-review.xlsx"'
    book.save(response)
    return response


# ---------------------------------------------------------------- events

def _event_review(event, meta=None):
    meta = meta if meta is not None else _metadata(event)
    review = meta.get('review') if isinstance(meta.get('review'), dict) else {}
    kind = EVENT_KINDS.get(event['action'])
    status = review.get('status') if review.get('status') in REVIEW_STATES else ('review' if kind and kind[3] else 'none')
    return status, str(review.get('note') or '')


def _events(exam, request, now):
    get = request.GET
    attempts = erd_rows('SELECT id, student_id FROM exam_attempts WHERE exam_id = %s', [exam['id']])
    owner = {str(a['id']): str(a['student_id']) for a in attempts}
    people = _students(list(set(owner.values())))
    filters = {
        'range': get.get('range') if get.get('range') in EVENT_RANGES else '',
        'student': (get.get('student') or '').strip()[:40] if (get.get('student') or '') in people else '',
        'group': get.get('group') if get.get('group') in EVENT_GROUPS else '',
        'status': get.get('status') if get.get('status') in REVIEW_STATES else '',
        'q': (get.get('q') or '').strip()[:100],
    }
    since = None
    if filters['range'] == 'hour':
        since = now - timedelta(hours=1)
    elif filters['range'] == 'today':
        since = timezone.localtime(now).replace(hour=0, minute=0, second=0, microsecond=0)
    events = _attempt_events(owner, since=since)
    rows = []
    for event in events:
        kind = EVENT_KINDS[event['action']]
        meta = _metadata(event)
        status, note = _event_review(event, meta)
        student_id = owner.get(str(event['entity_id']), '')
        person = people.get(student_id) or {}
        description = event.get('reason') or kind[1]
        if event['action'] == 'exam_time_extended':
            description = f"افزودن {meta.get('minutes', '')} دقیقه — {meta.get('reason', '')}"
        elif event['action'] == 'exam_proctor_message':
            description = 'پیام: ' + _answer_snippet(meta.get('text'), 80)
        created = erd_datetime(event['created_at'])
        rows.append({
            'id': str(event['id']), 'action': event['action'], 'group': kind[0], 'label': EVENT_GROUPS[kind[0]],
            'kind_label': kind[1], 'icon': kind[2], 'description': description, 'status': status,
            'status_label': REVIEW_STATES[status], 'note': note, 'student_id': student_id,
            'name': person.get('name', 'دانشجو'), 'code': person.get('code', ''), 'avatar_url': person.get('avatar_url', ''),
            'time': _time(created, seconds=True), 'created_at': created,
            'date_label': f"{_jalali_long_date(created, with_weekday=False)}، {_time(created, seconds=True)}",
            'attempt_id': str(event['entity_id']),
        })
    kpis = {
        'total': len(rows),
        'connection': sum(1 for r in rows if r['group'] == 'connection'),
        'focus': sum(1 for r in rows if r['group'] == 'focus'),
        'review': sum(1 for r in rows if r['status'] == 'review'),
        'seen': sum(1 for r in rows if r['status'] == 'seen'),
    }
    listed = [
        r for r in rows
        if (not filters['student'] or r['student_id'] == filters['student'])
        and (not filters['group'] or r['group'] == filters['group'])
        and (not filters['status'] or r['status'] == filters['status'])
        and (not filters['q'] or filters['q'] in r['name'] or filters['q'] in str(r['code']) or filters['q'] in r['description'])
    ]
    page = Paginator(listed, PAGE_SIZE).get_page(get.get('page'))
    selected_id = get.get('event') or ''
    selected = next((r for r in rows if r['id'] == selected_id), None) or (page.object_list[0] if page.object_list else None)
    trail = [r for r in rows if selected and r['attempt_id'] == selected['attempt_id']][:6] if selected else []
    return {
        'kpis': kpis, 'page': page, 'rows': page.object_list, 'filters': filters, 'selected': selected, 'trail': trail,
        'ranges': EVENT_RANGES, 'groups': EVENT_GROUPS, 'states': REVIEW_STATES,
        'students': sorted(({'id': k, 'name': v['name']} for k, v in people.items()), key=lambda s: s['name']),
        'note_max': NOTE_MAX,
    }


# ---------------------------------------------------------------- review («موارد نیازمند بررسی»)

def _review_notes(exam_id):
    rows = erd_rows(
        """
        SELECT id, metadata, created_at FROM activity_audit_log
        WHERE entity_type = 'exam' AND CAST(entity_id AS TEXT) = %s AND action = 'exam_review_note'
        ORDER BY created_at
        """,
        [str(exam_id)],
    )
    notes = {}
    for row in rows:
        meta = _metadata(row)
        key = str(meta.get('key') or '')
        if key:
            entry = notes.setdefault(key, {'notes': [], 'status': 'open', 'flagged': False})
            if meta.get('note'):
                entry['notes'].append({'text': meta['note'], 'at': erd_datetime(row['created_at'])})
            if meta.get('status') in REVIEW_ITEM_STATES:
                entry['status'] = meta['status']
            if meta.get('flag'):
                entry['flagged'] = True
    return notes


def _review(exam, request):
    get = request.GET
    notes = _review_notes(exam['id'])
    items, _takers = _item_analysis(exam)
    by_id = {i['id']: i for i in items}
    out = []
    for item in items:
        negative = any(f['key'] == 'negative' for f in item['flags'])
        key = f"q:{item['id']}"
        entry = notes.get(key) or {}
        if not negative and not entry.get('flagged'):
            continue
        evidence = [f"ضریب تمایز: {item['d']}" if item['d'] is not None else '', f"میانگین نمره‌ی سؤال: {item['score_pct']}٪" if item['score_pct'] is not None else '',
                    f"شاخص دشواری: {item['p']}" if item['p'] is not None else '']
        evidence += [n['text'] for n in entry.get('notes', [])]
        out.append({
            'key': key, 'kind': 'negative' if negative else 'flagged', 'question_no': item['index'], 'student': '',
            'title': ('ضریب تمایز منفی برای این سؤال؛ عملکرد دانشجویان قوی در آن ضعیف‌تر بوده است.' if negative
                      else 'این سؤال برای بازبینی علامت خورده است.'),
            'evidence': [e for e in evidence if e], 'status': entry.get('status', 'open'),
            'notes': len(entry.get('notes', [])), 'detail_url': f"?tab=results&view=items&q_no={item['index']}",
        })
    objections = erd_rows(
        """
        SELECT o.id, o.student_id, o.question_id, o.subject, o.message, o.status, o.teacher_response, o.resolved_at
        FROM objections o WHERE o.exam_id = %s ORDER BY o.resolved_at NULLS FIRST
        """,
        [exam['id']],
    )
    people = _students(list({str(o['student_id']) for o in objections}))
    for objection in objections:
        key = f"o:{objection['id']}"
        entry = notes.get(key) or {}
        person = people.get(str(objection['student_id'])) or {}
        item = by_id.get(str(objection.get('question_id') or ''))
        done = (objection.get('status') or '') in OBJECTION_DONE or objection.get('resolved_at')
        status = entry.get('status') or ('answered' if done else 'open')
        evidence = [f"پیام دانشجو: {_answer_snippet(objection.get('message'), 120)}"]
        if objection.get('teacher_response'):
            evidence.append(f"پاسخ: {_answer_snippet(objection['teacher_response'], 120)}")
        evidence += [n['text'] for n in entry.get('notes', [])]
        out.append({
            'key': key, 'kind': 'objection', 'question_no': item['index'] if item else '',
            'student': f"{person.get('name', 'دانشجو')} ({person.get('code', '')})" if person.get('code') else person.get('name', 'دانشجو'),
            'title': objection.get('subject') or 'درخواست بررسی نمره', 'evidence': evidence,
            'status': status if status in REVIEW_ITEM_STATES else 'open', 'notes': len(entry.get('notes', [])),
            'detail_url': (reverse('core:teacher_objection_detail', args=[objection['id']]) if exam['role'] == 'teacher'
                           else (f"?tab=results&view=items&q_no={item['index']}" if item else '')),
        })
    for row in out:
        row['kind_label'] = REVIEW_KINDS[row['kind']]
        row['status_label'] = REVIEW_ITEM_STATES[row['status']]
    kinds = [k for k in REVIEW_KINDS if get.get(f'k_{k}')] or list(REVIEW_KINDS)
    states = [s for s in REVIEW_ITEM_STATES if get.get(f's_{s}')]
    question = (get.get('question') or '').strip()[:6]
    student = (get.get('student') or '').strip()[:100]
    q = (get.get('q') or '').strip()[:100]
    listed = [
        r for r in out
        if r['kind'] in kinds and (not states or r['status'] in states)
        and (not question or str(r['question_no']) == question) and (not student or student in r['student'])
        and (not q or q in r['title'] or q in str(r['question_no']) or q in r['student'] or any(q in e for e in r['evidence']))
    ]
    page = Paginator(listed, PAGE_SIZE).get_page(get.get('page'))
    for index, row in enumerate(page.object_list, start=page.start_index()):
        row['index'] = index
    return {
        'kpis': {k: sum(1 for r in out if r['kind'] == k) for k in REVIEW_KINDS} | {'total': len(out)},
        'page': page, 'rows': page.object_list, 'all': listed, 'kinds': REVIEW_KINDS, 'states': REVIEW_ITEM_STATES,
        'kind_counts': {k: sum(1 for r in out if r['kind'] == k) for k in REVIEW_KINDS},
        'state_counts': {s: sum(1 for r in out if r['status'] == s) for s in REVIEW_ITEM_STATES},
        'filters': {'kinds': kinds if len(kinds) < len(REVIEW_KINDS) or any(get.get(f'k_{k}') for k in REVIEW_KINDS) else list(REVIEW_KINDS),
                    'states': states, 'question': question, 'student': student, 'q': q},
        # «پاکسازی» has something to clear (the panel's «اعمال فیلتر» / «پاکسازی» buttons: dirty-form.js)
        'is_filtered': len(kinds) < len(REVIEW_KINDS) or bool(states or question or student or q),
        'note_max': NOTE_MAX,
    }


# ---------------------------------------------------------------- settings

def _settings(exam):
    rules = _sx_exam_rules(exam['id'])
    start, end = exam.get('start_at'), exam.get('end_at')
    groups = _overview_groups(exam['id'])
    return {
        'title_max': TITLE_MAX,
        'groups': groups,
        'start_value': timezone.localtime(start).strftime('%Y-%m-%dT%H:%M') if start else '',
        'end_value': timezone.localtime(end).strftime('%Y-%m-%dT%H:%M') if end else '',
        'start_date': timezone.localtime(start).strftime('%Y-%m-%d') if start else '',
        'start_time': timezone.localtime(start).strftime('%H:%M') if start else '',
        'end_date': timezone.localtime(end).strftime('%Y-%m-%d') if end else '',
        'end_time': timezone.localtime(end).strftime('%H:%M') if end else '',
        'start_label': f"{_jalali_long_date(start)}، ساعت {_time(start)}" if start else 'تعیین نشده',
        'end_label': f"{_jalali_long_date(end)}، ساعت {_time(end)}" if end else 'تعیین نشده',
        'max_attempts': exam.get('max_attempts') if exam.get('max_attempts') is not None else 1,
        'autosave': rules['autosave_interval_seconds'], 'autosave_on': rules['autosave_enabled'],
        'settings_enforced': rules['settings_enforced'],
        'score_mode': exam.get('score_display_mode') or ('immediate' if exam.get('show_results_immediately') else 'after_publish'),
        'key_shown': (exam.get('correct_answer_display_mode') or 'after_publish') != 'manual',
        'shuffle': bool(exam.get('shuffle_questions')),
        'autosave_choices': ((0, 'پس از هر تغییر'), (15, 'هر ۱۵ ثانیه'), (30, 'هر ۳۰ ثانیه'), (60, 'هر ۶۰ ثانیه')),
        'edit_url': (reverse('core:teacher_exam_edit', args=[exam['id']]) if exam['role'] == 'teacher'
                     else reverse('core:super_admin_exam_edit', args=[exam['id']])),
        'can_full_edit': exam['role'] == 'manager' or exam['can']['schedule'],
    }


def _overview_groups(exam_id):
    rows = erd_rows(
        """
        SELECT COALESCE(NULLIF(sg.course_name, ''), 'گروه') AS name, sg.group_code
        FROM exam_assignments ea JOIN student_groups sg ON sg.id = ea.group_id
        WHERE ea.exam_id = %s ORDER BY sg.course_name, sg.group_code
        """,
        [exam_id],
    )
    return [f"{row['name']}{(' - ' + row['group_code']) if row['group_code'] else ''}" for row in rows]


# ---------------------------------------------------------------- grading one answer (mock-up «تصحیح پاسخ»)

def _grade_answer(exam, request, answer_id):
    """The grading screen inside the hub; the form posts to grading_views.teacher_grading_detail with hub=<this page>."""
    from .grading_views import _SCOPED_FROM, _grading_answer, grader_params, grading_detail_context

    if exam['role'] != 'teacher':
        raise Http404('پاسخ پیدا نشد.')
    teacher_id = request.erd_profile_id
    row = _grading_answer(teacher_id, answer_id)
    attempt = erd_row('SELECT exam_id, student_id FROM exam_attempts WHERE id = %s', [row['attempt_id']])
    if not attempt or str(attempt['exam_id']) != exam['id']:
        raise Http404('پاسخ پیدا نشد.')
    context = grading_detail_context(request, row)
    siblings = erd_rows(
        f"SELECT aa.id, aa.needs_manual_grading, aa.graded_at {_SCOPED_FROM} AND aa.attempt_id = %s "
        'ORDER BY eq.order_index NULLS LAST, aa.id',
        [*grader_params(teacher_id), str(row['attempt_id'])],
    )
    ids = [str(item['id']) for item in siblings]
    position = ids.index(str(row['id'])) if str(row['id']) in ids else 0
    order = [str(item['question_id']) for item in erd_rows(
        'SELECT question_id FROM exam_questions WHERE exam_id = %s ORDER BY order_index NULLS LAST, id', [exam['id']])]
    person = _students([str(attempt['student_id'])]).get(str(attempt['student_id'])) or {}
    if context.get('grading_blind'):
        person = {'name': context['grading']['student_name'], 'code': '', 'faculty': '', 'avatar_url': ''}
    return {
        **context,
        'person': person,
        'question_no': order.index(str(row['question_id'])) + 1 if str(row['question_id']) in order else '',
        'position': position + 1, 'count': len(ids),
        'graded': sum(1 for item in siblings if item['graded_at'] and not item['needs_manual_grading']),
        'prev_id': ids[position - 1] if position > 0 else '', 'next_id': ids[position + 1] if position + 1 < len(ids) else '',
        'post_url': reverse('core:teacher_grading_detail', args=[row['id']]),
        'kind_label': {'essay': 'پاسخ تشریحی', 'descriptive': 'پاسخ تشریحی', 'short_answer': 'پاسخ کوتاه',
                       'media_response': 'پاسخ صوتی / تصویری'}.get(row.get('question_type'), 'پاسخ تشریحی'),
        'feedback_max': 2000,
    }


# ---------------------------------------------------------------- page

# The tab strip is the same on every view (user's choice): its own full-width row under the title, icons, underline.
HEAD = {'tabs': 'full', 'icons': True, 'style': 'line'}
TAB_ICONS = {'overview': 'home', 'live': 'live', 'grading': 'checkcircle', 'results': 'chart', 'events': 'list',
             'review': 'flag', 'settings': 'gear'}

def _tab_url(base, **params):
    from urllib.parse import urlencode

    return f'{base}?{urlencode({k: v for k, v in params.items() if v not in (None, "")})}'


def _hub_page(request, exam_id):
    exam = _hub_exam(request, exam_id)
    now = timezone.now()
    exam['state'], exam['state_label'], exam['state_tone'] = _state(exam, now)
    exam['state_label'] = _exam_status_with_approval(exam['state_label'], exam)  # same badge as on the exam lists
    urls = _urls(exam['role'], exam['id'])
    tab = request.GET.get('tab') if request.GET.get('tab') in TAB_KEYS else 'overview'
    context = {
        'exam': exam, 'urls': urls, 'tab': tab, 'code': exam_access_code(exam['id']),
        'tabs': [{'key': key, 'label': label, 'icon': TAB_ICONS[key], 'url': _tab_url(urls['hub'], tab=key)}
                 for key, label, _icon in TABS],
        'title': exam.get('title') or 'آزمون',
        'duration_label': _duration_label(exam.get('duration_minutes')),
        'start_label': _jalali_long_date(exam.get('start_at')) if exam.get('start_at') else '',
        'start_time': _time(exam.get('start_at')),
        'end_time': _time(exam.get('end_at')),
    }
    sub = ''
    if tab == 'overview':
        context['overview'] = _overview(exam, now)
    elif tab == 'live':
        if request.GET.get('attempt'):
            context['person'] = _live_attempt(exam, request.GET.get('attempt'), now)
            sub = 'جزئیات شرکت‌کننده'
        else:
            context['live'] = _live(exam, request, now)
    elif tab == 'grading' and request.GET.get('answer'):
        context['grade'] = _grade_answer(exam, request, request.GET.get('answer'))
        sub = 'تصحیح پاسخ'
    elif tab == 'grading':
        context['grading'] = _grading(exam, request)
        context['overview'] = {'question_count': _question_count(exam['id'])}
        sub = 'صف تصحیح'
    elif tab == 'results':
        if request.GET.get('student'):
            context['card'] = _student_card(exam, request.GET.get('student'), request.GET)
            sub = 'کارنامه دانشجو'
        else:
            results = _results(exam, request)
            if request.GET.get('export') == 'xlsx':
                return _xlsx_items(exam, results['items']) if results['view'] == 'items' else _xlsx_students(exam, results['students'])
            context['results'] = results
            sub = 'تحلیل سؤال' if results['view'] == 'items' else ''
    elif tab == 'events':
        context['events'] = _events(exam, request, now)
    elif tab == 'review':
        context['review'] = _review(exam, request)
        if request.GET.get('export') == 'xlsx':
            return _xlsx_review(exam, context['review'])
    elif tab == 'settings':
        context['settings'] = _settings(exam)
    context['tab_label'] = next(label for key, label, _i in TABS if key == tab)
    context['sub_label'] = sub
    view = tab
    if 'person' in context:
        view = 'person'
    elif 'grade' in context:
        view = 'grade'
    elif 'card' in context:
        view = 'card'
    elif tab == 'results' and context['results']['view'] == 'items':
        view = 'items'
    context['view'] = view
    context['head'] = HEAD
    return render(request, 'exam_hub/hub.html', context)


@erd_role_required('teacher')
def teacher_exam_hub(request, exam_id):
    return _hub_page(request, exam_id)


@erd_role_required('academic_manager', 'admin')
def super_admin_exam_hub(request, exam_id):
    return _hub_page(request, exam_id)


# ---------------------------------------------------------------- actions (POST)

def _log_on_attempt(request, attempt_id, action, reason, metadata):
    profile = erd_profile_for_user(request.user)
    erd_execute(
        """
        INSERT INTO activity_audit_log (id, actor_id, action, entity_type, entity_id, reason, metadata)
        VALUES (%s, %s, %s, 'exam_attempt', %s, %s, %s)
        """,
        [str(uuid.uuid4()), profile['id'] if profile else None, action, str(attempt_id), reason,
         json.dumps(metadata, ensure_ascii=False)],
    )


def _hub_action(request, exam_id):
    exam = _hub_exam(request, exam_id)
    exam['state'], _label, _tone = _state(exam, timezone.now())
    urls = _urls(exam['role'], exam['id'])
    action = request.POST.get('action') or ''
    back = request.POST.get('back') or ''
    back = back if back.startswith('?') else '?tab=overview'

    def done(message, ok=True):
        (messages.success if ok else messages.error)(request, message)
        return redirect(f"{urls['hub']}{back}")

    if action in ('add_time', 'send_message'):
        if not exam['can']['live']:
            raise Http404('اجازه‌ی این کار را ندارید.')
        attempt = erd_row(
            f"SELECT id, student_id, started_at, submitted_at, status, {_sx_attempt_extra_sql('exam_attempts')} AS extra_minutes "
            'FROM exam_attempts WHERE id = %s AND exam_id = %s',
            [request.POST.get('attempt') or '', exam['id']],
        )
        if not attempt:
            raise Http404('شرکت‌کننده پیدا نشد.')
        if attempt.get('submitted_at') or attempt.get('status') != 'in_progress':
            return done('آزمون این دانشجو ارسال شده است؛ دیگر نمی‌توان زمان یا پیام فرستاد.', ok=False)
        if action == 'add_time':
            try:
                minutes = int(request.POST.get('minutes') or 0)
            except ValueError:
                minutes = 0
            reason = ' '.join((request.POST.get('reason') or '').split())[:ADD_TIME_REASON_MAX]
            if minutes not in ADD_TIME_CHOICES:
                return done('مدت زمان افزوده را از فهرست انتخاب کنید.', ok=False)
            if not reason:
                return done('دلیل افزودن زمان را بنویسید.', ok=False)
            if not erd_has_column('exam_attempts', 'extra_minutes'):
                return done('این امکان پس از به‌روزرسانی پایگاه داده فعال می‌شود.', ok=False)
            erd_execute('UPDATE exam_attempts SET extra_minutes = COALESCE(extra_minutes, 0) + %s WHERE id = %s', [minutes, attempt['id']])
            _log_on_attempt(request, attempt['id'], 'exam_time_extended', f'{minutes} دقیقه به زمان دانشجو افزوده شد.',
                            {'minutes': minutes, 'reason': reason})
            return done(f'{minutes} دقیقه به زمان این دانشجو افزوده شد.')
        text = (request.POST.get('message') or '').strip()[:MESSAGE_MAX]
        if not text:
            return done('متن پیام را بنویسید.', ok=False)
        _log_on_attempt(request, attempt['id'], 'exam_proctor_message', 'پیام ناظر برای دانشجو فرستاده شد.',
                        {'text': text, 'delivered': False})
        return done('پیام برای دانشجو فرستاده شد؛ در صفحه‌ی آزمونش نمایش داده می‌شود.')

    if action == 'event_review':
        if not exam['can']['review']:
            raise Http404('اجازه‌ی این کار را ندارید.')
        event = erd_row(
            """
            SELECT l.id, l.action, l.metadata FROM activity_audit_log l
            WHERE l.id = %s AND l.entity_type = 'exam_attempt'
              AND CAST(l.entity_id AS TEXT) IN (SELECT CAST(id AS TEXT) FROM exam_attempts WHERE exam_id = %s)
            """,
            [request.POST.get('event') or '', exam['id']],
        )
        if not event:
            raise Http404('رخداد پیدا نشد.')
        status = request.POST.get('status')
        meta = _metadata(event)
        old_status, old_note = _event_review(event, meta)
        note = (request.POST.get('note') if 'note' in request.POST else old_note) or ''
        meta['review'] = {'status': status if status in REVIEW_STATES else old_status, 'note': note.strip()[:NOTE_MAX],
                          'by': str(request.erd_profile_id), 'at': timezone.now().isoformat()}
        erd_execute('UPDATE activity_audit_log SET metadata = %s WHERE id = %s', [json.dumps(meta, ensure_ascii=False), event['id']])
        return done('بررسی رخداد ثبت شد.')

    if action == 'review_note':
        if not exam['can']['review']:
            raise Http404('اجازه‌ی این کار را ندارید.')
        key = (request.POST.get('key') or '')[:80]
        if not key.startswith(('q:', 'o:')):
            raise Http404('مورد پیدا نشد.')
        note = ' '.join((request.POST.get('note') or '').split())[:NOTE_MAX]
        status = request.POST.get('status') if request.POST.get('status') in REVIEW_ITEM_STATES else ''
        flag = bool(request.POST.get('flag'))
        if not (note or status or flag):
            return done('یادداشت را بنویسید.', ok=False)
        erd_execute(
            """
            INSERT INTO activity_audit_log (id, actor_id, action, entity_type, entity_id, reason, metadata)
            VALUES (%s, %s, 'exam_review_note', 'exam', %s, %s, %s)
            """,
            [str(uuid.uuid4()), str(request.erd_profile_id), exam['id'], 'یادداشت بازبینی آزمون',
             json.dumps({'key': key, 'note': note, 'status': status, 'flag': flag}, ensure_ascii=False)],
        )
        return done('یادداشت بازبینی ثبت شد.' if note or flag else 'وضعیت رسیدگی ثبت شد.')

    if action in ('publish_results', 'unpublish_results'):
        if not exam['can']['publish']:
            raise Http404('اجازه‌ی این کار را ندارید.')
        notified = _set_exam_results_published(request, exam['id'], action == 'publish_results')
        return done(f'نتایج منتشر شد و برای {notified} دانشجو اعلان ارسال شد.' if action == 'publish_results' else 'انتشار نتایج لغو شد.')

    if action == 'settings':
        if not exam['can']['settings']:
            raise Http404('اجازه‌ی این کار را ندارید.')
        return _save_settings(request, exam, done)
    raise Http404('درخواست نامعتبر است.')


def _save_settings(request, exam, done):
    from .views import _parse_exam_wizard_datetime

    post = request.POST
    current = _settings(exam)
    updates = {}
    if post.get('score_display_mode') in RESULT_DISPLAY_MODES and post['score_display_mode'] != current['score_mode']:
        updates['score_display_mode'] = post['score_display_mode']
    if bool(post.get('show_key')) != current['key_shown']:  # an 'immediate' key stays as it is while the box stays on
        updates['correct_answer_display_mode'] = 'after_publish' if post.get('show_key') else 'manual'
    if exam['can']['schedule']:
        title = ' '.join((post.get('title') or '').split())[:TITLE_MAX]
        if not title:
            return done('عنوان آزمون نمی‌تواند خالی باشد.', ok=False)
        try:
            duration = max(1, min(int(post.get('duration_minutes') or exam.get('duration_minutes') or 90), 1440))
        except ValueError:
            return done('مدت آزمون باید عدد باشد.', ok=False)
        start = _parse_exam_wizard_datetime(post.get('start_at')) or exam.get('start_at')
        end = _parse_exam_wizard_datetime(post.get('end_at'))
        if start and not end:
            end = start + timedelta(minutes=duration)
        if start and end and end <= start:
            return done('پایان آزمون باید بعد از شروع آن باشد.', ok=False)

        def minute(value):
            return timezone.localtime(value).replace(second=0, microsecond=0) if value else None

        scheduled = {'title': title, 'duration_minutes': duration, 'start_at': start, 'end_at': end,
                     'max_attempts': _posted_max_attempts(post), 'shuffle_questions': bool(post.get('shuffle_questions'))}
        saved = {'title': exam.get('title') or '', 'duration_minutes': exam.get('duration_minutes') or 90,  # the form's default
                 'start_at': exam.get('start_at'), 'end_at': exam.get('end_at'),
                 'max_attempts': current['max_attempts'], 'shuffle_questions': current['shuffle']}
        for column, value in scheduled.items():
            old = saved[column]
            same = minute(value) == minute(old) if column in ('start_at', 'end_at') else value == old
            unposted_end = not old and not (post.get('end_at') or '').strip()
            if column == 'end_at' and unposted_end and 'start_at' not in updates and 'duration_minutes' not in updates:
                same = True  # no end stored and none posted: the end filled in from the duration is not a change
            if not same:
                updates[column] = value
        if 'start_at' in updates or 'end_at' in updates:
            # the same time rules as the wizard: not in the past, at most a year ahead, and still in order with the
            # exam's saved access / last-entry times (those are changed in the wizard's «ویرایش کامل»)
            row = erd_row('SELECT * FROM exams WHERE id = %s', [exam['id']]) or {}
            times = {name: erd_datetime(row.get(name)) for name in ('registration_start_at', 'last_entry_at', 'registration_end_at')}
            if problem := exam_timing_problem({**times, 'start_at': start, 'end_at': end}, saved=row):
                return done(problem, ok=False)
        if current['settings_enforced'] and post.get('autosave_interval_seconds') is not None:
            try:
                autosave = max(0, min(int(post.get('autosave_interval_seconds') or 0), 300))
            except ValueError:
                autosave = current['autosave']
            if autosave != current['autosave']:
                updates['autosave_interval_seconds'] = autosave
    columns = [column for column in updates if erd_has_column('exams', column)]
    if not columns:
        # nothing differs from what is saved: say so instead of claiming a save (the button is disabled until a change)
        messages.info(request, 'تغییری ثبت نشد؛ تنظیمات آزمون همان مقادیر قبلی است.')
        return redirect(f"{_urls(exam['role'], exam['id'])['hub']}?tab=settings")
    erd_execute(f"UPDATE exams SET {', '.join(f'{c} = %s' for c in columns)} WHERE id = %s",
                [updates[c] for c in columns] + [exam['id']])
    log_activity(request.user, 'exam_settings_updated', 'تنظیمات آزمون از صفحه‌ی مدیریت آزمون ذخیره شد.', request,
                 {'exam_id': exam['id'], 'fields': columns})
    return done('تنظیمات آزمون ذخیره شد.')


@require_POST
@erd_role_required('teacher')
def teacher_exam_hub_action(request, exam_id):
    return _hub_action(request, exam_id)


@require_POST
@erd_role_required('academic_manager', 'admin')
def super_admin_exam_hub_action(request, exam_id):
    return _hub_action(request, exam_id)


# ---------------------------------------------------------------- the open exam page checks in

@erd_role_required('student')
def student_attempt_live(request, attempt_id):
    """Called by the exam page every ~20 s (background): marks the student «متصل», returns the remaining seconds (with
    any «افزودن زمان») and hands over proctor messages not delivered yet."""
    attempt = erd_row(
        f"""
        SELECT ea.id, ea.exam_id, ea.started_at, ea.submitted_at, ea.status, {_sx_attempt_extra_sql()} AS extra_minutes,
               COALESCE(e.duration_minutes, 90) AS duration_minutes, e.end_at, COALESCE(e.is_cancelled, false) AS is_cancelled
        FROM exam_attempts ea JOIN exams e ON e.id = ea.exam_id
        WHERE ea.id = %s AND ea.student_id = %s
        """,
        [attempt_id, request.erd_profile_id],
    )
    if not attempt:
        raise Http404('تلاش آزمون پیدا نشد.')
    # Closed on the server (submitted, expired, the exam cancelled): the page reloads and the server shows what next.
    if attempt.get('submitted_at') or (attempt.get('status') or 'in_progress') not in ('in_progress', '') or attempt.get('is_cancelled'):
        return JsonResponse({'ok': True, 'open': False})
    now = timezone.now()
    if erd_has_column('exam_attempts', 'last_seen_at'):
        erd_execute('UPDATE exam_attempts SET last_seen_at = %s WHERE id = %s', [now, attempt['id']])
    rules = _sx_exam_rules(attempt['exam_id'])
    deadline = _deadline({'end_at': attempt.get('end_at'), 'duration_minutes': attempt.get('duration_minutes')}, rules, attempt)
    pending = []
    for row in reversed(_attempt_events([attempt['id']], actions=['exam_proctor_message'])):
        meta = _metadata(row)
        if meta.get('delivered'):
            continue
        pending.append({'text': str(meta.get('text') or ''), 'time': _time(row['created_at'])})
        meta['delivered'] = True
        erd_execute('UPDATE activity_audit_log SET metadata = %s WHERE id = %s', [json.dumps(meta, ensure_ascii=False), row['id']])
    return JsonResponse({
        'ok': True, 'open': True,
        'remaining_seconds': max(int((deadline - now).total_seconds()), 0) if deadline else None,
        'messages': pending,
    })


# Exam lists: where «مدیریت آزمون» / «نظارت زنده» / «نتایج و گزارش‌ها» lead.
HUB_STATES = ('scheduled', 'running', 'finished')


def hub_url(role, exam_id, tab='overview'):
    name = 'core:teacher_exam_hub' if role == 'teacher' else 'core:super_admin_exam_hub'
    return f"{reverse(name, args=[exam_id])}?tab={tab}"

