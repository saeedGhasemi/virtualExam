"""Teacher «دانشجویان» section: student list, a student's profile tabs, private notes, messages and exports.

Everything is scoped to the groups this teacher teaches (owner or co-teacher, not archived) and to this teacher's
own published exams. A student outside those groups, or a changed id in a URL or a posted form, answers 404.
"""
import logging
import uuid
from datetime import date, datetime, time
from io import BytesIO

from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.http import Http404, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.html import strip_tags
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .templatetags.core_extras import _gregorian_to_jalali, fa_digits
from .views import (
    JALALI_MONTH_NAMES,
    _jalali_long_date,
    _sx_percent,
    _teacher_modern_context,
    _teacher_semester_label,
    create_notification,
    erd_datetime,
    erd_execute,
    erd_has_column,
    erd_role_required,
    erd_row,
    erd_rows,
    log_activity,
)

logger = logging.getLogger(__name__)

DONE_STATUSES = "('submitted', 'graded', 'completed')"
LIST_PAGE_SIZES = (10, 20, 50)
EXAMS_PAGE_SIZE = 10
NOTE_MAX_LENGTH = 1000
MESSAGE_TITLE_MAX_LENGTH = 120
MESSAGE_MAX_RECIPIENTS = 500
TREND_EXAMS = 6
HARD_QUESTION_RATE = 0.4  # a question fewer than 40% of the class answered correctly

LIST_TABS = {
    'all': 'همه دانشجویان',
    'review': 'نیازمند بررسی',
    'absent': 'غایب‌ها',
    'unfinished': 'آزمون‌های ناتمام',
}
STUDENT_STATUSES = {
    'ok': ('فعال', 'is-ok'),
    'review': ('نیازمند بررسی', 'is-warn'),
    'warning': ('هشدار', 'is-danger'),
    'absent': ('غایب', 'is-danger'),
    'new': ('بدون سابقه آزمون', 'is-muted'),
}
EXAM_STATES = {
    'done': ('تکمیل‌شده', 'is-ok'),
    'grading': ('نیازمند تصحیح', 'is-warn'),
    'in_progress': ('در حال انجام', 'is-blue'),
    'unfinished': ('ناتمام', 'is-blue'),
    'open': ('در حال برگزاری', 'is-blue'),
    'upcoming': ('پیش‌رو', 'is-muted'),
    'absent': ('غایب', 'is-danger'),
}
PROFILE_TABS = {
    'overview': 'نمای کلی',
    'courses': 'درس‌ها و کلاس‌ها',
    'exams': 'آزمون‌ها و نتایج',
    'analytics': 'تحلیل عملکرد',
    'notes': 'یادداشت‌ها',
}
ACADEMIC_STATUSES = {
    'active': ('فعال', 'is-ok'),
    'inactive': ('غیرفعال', 'is-muted'),
    'suspended': ('تعلیق', 'is-danger'),
    'graduated': ('فارغ‌التحصیل', 'is-blue'),
    'withdrawn': ('انصراف', 'is-muted'),
}


# ---------------------------------------------------------------- scope

def _own_groups_condition() -> str:
    """WHERE fragment (alias sg, params [teacher_id, teacher_id]) for the groups this teacher teaches."""
    condition = '(sg.teacher_id = %s OR sg.id IN (SELECT group_id FROM group_teachers WHERE teacher_id = %s))'
    if erd_has_column('student_groups', 'is_archived'):
        condition += ' AND COALESCE(sg.is_archived, false) = false'
    return condition


def _valid_id(value) -> str | None:
    try:
        uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None
    return str(value)


def own_groups(teacher_id) -> list:
    rows = erd_rows(
        f"""
        SELECT sg.id, sg.course_id, sg.course_name, sg.group_code, sg.academic_year, sg.semester, sg.is_active,
               COALESCE(c.code, '') AS course_code,
               COALESCE(NULLIF(owner.full_name, ''), owner.username, '') AS owner_name
        FROM student_groups sg
        LEFT JOIN courses c ON c.id = sg.course_id
        LEFT JOIN profiles owner ON owner.id = sg.teacher_id
        WHERE {_own_groups_condition()}
        ORDER BY sg.course_name, sg.group_code
        """,
        [teacher_id, teacher_id],
    )
    for row in rows:
        row['id'] = str(row['id'])
        row['course_id'] = str(row['course_id']) if row['course_id'] else ''
        row['label'] = _group_label(row)
        row['term_label'] = _teacher_semester_label(row['semester'], row['academic_year'])
    return rows


def _group_label(group) -> str:
    code = str(group.get('group_code') or '').strip()
    return fa_digits(f"{group.get('course_name') or 'کلاس'}{f' - گروه {code}' if code else ''}")


def own_group_or_404(teacher_id, group_id) -> dict:
    group = next((row for row in own_groups(teacher_id) if row['id'] == str(group_id)), None)
    if not group:
        raise Http404('گروه پیدا نشد.')
    return group


def scoped_student_or_404(teacher_id, student_id) -> dict:
    """The student's identity, only when they belong to a group this teacher teaches."""
    student_id = _valid_id(student_id)
    if not student_id:
        raise Http404('دانشجو پیدا نشد.')
    row = erd_row(
        f"""
        SELECT p.id, COALESCE(NULLIF(p.full_name, ''), p.username, 'دانشجو') AS name,
               COALESCE(NULLIF(sp.student_number, ''), p.identifier, '') AS code,
               COALESCE(p.email, '') AS email, COALESCE(p.phone, '') AS phone,
               COALESCE(p.avatar_url, '') AS avatar_url, COALESCE(p.birth_date, '') AS birth_date,
               COALESCE(sp.field_of_study, '') AS field_of_study, COALESCE(sp.degree, '') AS degree,
               COALESCE(sp.entry_year, '') AS entry_year, COALESCE(sp.academic_status, '') AS academic_status
        FROM profiles p
        LEFT JOIN student_profiles sp ON sp.user_id = p.id
        WHERE p.id = %s AND EXISTS (
            SELECT 1 FROM student_group_members sgm JOIN student_groups sg ON sg.id = sgm.group_id
            WHERE sgm.student_user_id = p.id AND {_own_groups_condition()}
        )
        """,
        [student_id, teacher_id, teacher_id],
    )
    if not row:
        raise Http404('دانشجو پیدا نشد.')
    row['id'] = str(row['id'])
    row['initial'] = row['name'][:1]
    row['status_label'], row['status_tone'] = ACADEMIC_STATUSES.get(
        (row['academic_status'] or 'active').lower(), (row['academic_status'], 'is-muted'),
    )
    return row


def _scoped_student_ids(teacher_id, student_ids) -> list:
    """The posted ids, de-duplicated; any id outside this teacher's students is a 404 (a tampered form)."""
    wanted = list(dict.fromkeys(item for item in student_ids if item))
    if not wanted or len(wanted) > MESSAGE_MAX_RECIPIENTS or any(not _valid_id(item) for item in wanted):
        raise Http404('دانشجو پیدا نشد.')
    marks = ', '.join(['%s'] * len(wanted))
    found = {
        str(row['student_user_id']) for row in erd_rows(
            f"""
            SELECT DISTINCT sgm.student_user_id FROM student_group_members sgm
            JOIN student_groups sg ON sg.id = sgm.group_id
            WHERE sgm.student_user_id IN ({marks}) AND {_own_groups_condition()}
            """,
            [*wanted, teacher_id, teacher_id],
        )
    }
    if found != set(wanted):
        raise Http404('دانشجو پیدا نشد.')
    return wanted


def _audience_cte() -> str:
    """CTEs (param: teacher_id): this teacher's published, non-cancelled exams and, for each, the students it is
    open to — direct assignment, or group assignment minus exclusions — the same rule students are held to."""
    return f"""
        teacher_exams AS (
            SELECT e.id, e.title, e.course_id, e.start_at, e.end_at, e.passing_score
            FROM exams e
            WHERE e.teacher_id = %s AND COALESCE(e.is_published, false) = true AND COALESCE(e.is_cancelled, false) = false
        ),
        audience AS (
            SELECT ea.exam_id, ea.student_profile_id AS student_id
            FROM exam_assignments ea JOIN teacher_exams te ON te.id = ea.exam_id
            WHERE ea.student_profile_id IS NOT NULL
            UNION
            SELECT ea.exam_id, sgm.student_user_id AS student_id
            FROM exam_assignments ea
            JOIN teacher_exams te ON te.id = ea.exam_id
            JOIN student_group_members sgm ON sgm.group_id = ea.group_id
            WHERE NOT EXISTS (
                SELECT 1 FROM exam_assignment_exclusions ax
                WHERE ax.exam_id = ea.exam_id AND ax.student_profile_id = sgm.student_user_id
            )
        )"""


# ---------------------------------------------------------------- helpers

def _score_20(score, max_score):
    if score is None or not max_score or float(max_score) <= 0:
        return None
    return round(float(score) * 20 / float(max_score), 2)


def _num(value) -> str:
    """'18.5' / '17' for a score, '-' when empty."""
    if value is None:
        return '-'
    return f'{float(value):.2f}'.rstrip('0').rstrip('.')


def _time_label(value) -> str:
    value = erd_datetime(value)
    return timezone.localtime(value).strftime('%H:%M') if value else ''


def _date_param(value) -> date | None:
    """A 'YYYY-MM-DD' date from the Jalali picker's hidden input; anything else is ignored."""
    try:
        return date.fromisoformat(str(value or '')[:10])
    except ValueError:
        return None


def _safe_next(request, fallback: str) -> str:
    target = request.POST.get('next') or ''
    if url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return target
    return fallback


# ---------------------------------------------------------------- student list

def student_list_rows(teacher_id, group_id=None) -> list:
    """Every student of this teacher's groups (or one group) with their figures on this teacher's exams."""
    now = timezone.now()
    member_filter, member_params = ('AND sg.id = %s', [group_id]) if group_id else ('', [])
    rows = erd_rows(
        f"""
        WITH members AS (
            SELECT DISTINCT sgm.student_user_id AS student_id
            FROM student_group_members sgm JOIN student_groups sg ON sg.id = sgm.group_id
            WHERE {_own_groups_condition()} {member_filter}
        ),
        {_audience_cte()}
        SELECT p.id, COALESCE(NULLIF(p.full_name, ''), p.username, 'دانشجو') AS name,
               COALESCE(NULLIF(sp.student_number, ''), p.identifier, '') AS code,
               COALESCE(p.email, '') AS email, COALESCE(p.avatar_url, '') AS avatar_url,
               (SELECT COUNT(*) FROM audience au JOIN teacher_exams te ON te.id = au.exam_id
                 WHERE au.student_id = m.student_id) AS assigned_count,
               (SELECT COUNT(*) FROM audience au JOIN teacher_exams te ON te.id = au.exam_id
                 WHERE au.student_id = m.student_id AND te.start_at <= %s) AS held_count,
               (SELECT COUNT(DISTINCT a.exam_id) FROM exam_attempts a JOIN teacher_exams te ON te.id = a.exam_id
                 WHERE a.student_id = m.student_id AND a.status IN {DONE_STATUSES}) AS attended_count,
               (SELECT COUNT(*) FROM audience au JOIN teacher_exams te ON te.id = au.exam_id
                 WHERE au.student_id = m.student_id AND te.end_at < %s
                   AND NOT EXISTS (SELECT 1 FROM exam_attempts a WHERE a.exam_id = au.exam_id AND a.student_id = au.student_id)
               ) AS absent_count,
               (SELECT COUNT(*) FROM exam_attempts a JOIN teacher_exams te ON te.id = a.exam_id
                 WHERE a.student_id = m.student_id AND COALESCE(a.status, '') NOT IN {DONE_STATUSES} AND te.end_at < %s
               ) AS unfinished_count,
               (SELECT AVG(a.score * 20.0 / a.max_score) FROM exam_attempts a JOIN teacher_exams te ON te.id = a.exam_id
                 WHERE a.student_id = m.student_id AND a.status IN {DONE_STATUSES} AND COALESCE(a.is_graded, false) = true
                   AND a.score IS NOT NULL AND a.max_score > 0) AS average
        FROM members m
        JOIN profiles p ON p.id = m.student_id
        LEFT JOIN student_profiles sp ON sp.user_id = m.student_id
        ORDER BY name
        """,
        [teacher_id, teacher_id, *member_params, teacher_id, now, now, now],
    )
    if not rows:
        return []
    groups_by_student = _groups_by_student(teacher_id)
    last_exams = _last_exams(teacher_id, now)
    for row in rows:
        row['id'] = str(row['id'])
        row['initial'] = row['name'][:1]
        row['average'] = round(float(row['average']), 2) if row['average'] is not None else None
        row['groups'] = groups_by_student.get(row['id'], [])
        row['last_exam'] = last_exams.get(row['id'])
        row['status'] = _student_status(row)
        row['status_label'], row['status_tone'] = STUDENT_STATUSES[row['status']]
    return rows


def _groups_by_student(teacher_id) -> dict:
    result = {}
    for row in erd_rows(
        f"""
        SELECT sgm.student_user_id, sg.id, sg.course_name, sg.group_code
        FROM student_group_members sgm JOIN student_groups sg ON sg.id = sgm.group_id
        WHERE {_own_groups_condition()}
        ORDER BY sg.course_name, sg.group_code
        """,
        [teacher_id, teacher_id],
    ):
        result.setdefault(str(row['student_user_id']), []).append({'id': str(row['id']), 'label': _group_label(row)})
    return result


def _last_exams(teacher_id, now) -> dict:
    """Per student, the latest of this teacher's exams that has started, with that student's outcome."""
    result = {}
    rows = erd_rows(
        f"""
        WITH {_audience_cte()}
        SELECT au.student_id, te.id AS exam_id, te.title, te.start_at, te.end_at,
               a.status, a.score, a.max_score, a.is_graded, a.started_at
        FROM audience au
        JOIN teacher_exams te ON te.id = au.exam_id
        LEFT JOIN exam_attempts a ON a.exam_id = te.id AND a.student_id = au.student_id
        WHERE te.start_at <= %s
        ORDER BY te.start_at DESC, a.started_at DESC
        """,
        [teacher_id, now],
    )
    for row in rows:
        student_id = str(row['student_id'])
        if student_id in result:
            continue  # rows are newest first: the first one per student is their last exam and latest attempt
        state = _exam_state(row, now)
        score_20 = _score_20(row['score'], row['max_score']) if state == 'done' else None
        result[student_id] = {
            'title': row['title'],
            'date_label': _jalali_long_date(erd_datetime(row['start_at']), with_weekday=False),
            'state': state,
            'state_label': {'done': 'حاضر', 'grading': 'حاضر', 'absent': 'غایب', 'unfinished': 'ناتمام'}.get(state, 'در حال برگزاری'),
            'score_20': score_20,
            'percent': _sx_percent(row['score'], row['max_score']) if score_20 is not None else None,
        }
    return result


def _student_status(row) -> str:
    average = row['average']
    last_exam = row.get('last_exam') or {}
    if average is not None and average < 10:
        return 'warning'
    if last_exam.get('state') == 'absent':
        return 'absent'
    if average is not None and average < 14:
        return 'review'
    if not row['attended_count'] and not row['absent_count']:
        return 'new'
    return 'ok'


def _in_tab(row, tab) -> bool:
    if tab == 'review':
        return row['average'] is not None and row['average'] < 14
    if tab == 'absent':
        return row['absent_count'] > 0
    if tab == 'unfinished':
        return row['unfinished_count'] > 0
    return True


def _list_filters(request, groups) -> dict:
    group_ids = {group['id'] for group in groups}
    try:
        per_page = int(request.GET.get('per_page') or LIST_PAGE_SIZES[0])
    except ValueError:
        per_page = LIST_PAGE_SIZES[0]
    return {
        'q': (request.GET.get('q') or '').strip()[:100],
        'group': request.GET.get('group') if request.GET.get('group') in group_ids else '',
        'status': request.GET.get('status') if request.GET.get('status') in STUDENT_STATUSES else '',
        'tab': request.GET.get('tab') if request.GET.get('tab') in LIST_TABS else 'all',
        'per_page': per_page if per_page in LIST_PAGE_SIZES else LIST_PAGE_SIZES[0],
    }


def filtered_students(teacher_id, filters) -> tuple:
    """(rows matching search/group/status, rows matching those and the tab, count per tab)."""
    rows = student_list_rows(teacher_id, filters['group'] or None)
    query = filters['q'].lower()
    if query:
        rows = [row for row in rows if query in row['name'].lower() or query in row['code'].lower() or query in row['email'].lower()]
    if filters['status']:
        rows = [row for row in rows if row['status'] == filters['status']]
    tab_counts = {tab: sum(1 for row in rows if _in_tab(row, tab)) for tab in LIST_TABS}
    return rows, [row for row in rows if _in_tab(row, filters['tab'])], tab_counts


# ---------------------------------------------------------------- one student's exams

def _exam_state(row, now) -> str:
    status = (row.get('status') or '').lower()
    start_at, end_at = erd_datetime(row.get('start_at')), erd_datetime(row.get('end_at'))
    if status in ('submitted', 'graded', 'completed'):
        graded = row.get('is_graded') in (True, 1, '1') and row.get('score') is not None
        return 'done' if graded and not row.get('pending_count') else 'grading'
    if status:
        return 'unfinished' if end_at and end_at < now else 'in_progress'
    if start_at and start_at > now:
        return 'upcoming'
    if end_at and end_at < now:
        return 'absent'
    return 'open'


def student_exam_rows(teacher_id, student_id) -> list:
    """Every exam of this teacher open to the student, one row per attempt (or one row when not attempted)."""
    now = timezone.now()
    rows = erd_rows(
        f"""
        WITH {_audience_cte()}
        SELECT te.id AS exam_id, te.title, te.course_id, te.start_at, te.end_at, te.passing_score,
               COALESCE(c.title, '') AS course,
               a.id AS attempt_id, a.started_at, a.submitted_at, a.score, a.max_score, a.is_graded, a.status
        FROM teacher_exams te
        LEFT JOIN courses c ON c.id = te.course_id
        LEFT JOIN exam_attempts a ON a.exam_id = te.id AND a.student_id = %s
        WHERE a.id IS NOT NULL OR EXISTS (SELECT 1 FROM audience au WHERE au.exam_id = te.id AND au.student_id = %s)
        ORDER BY te.start_at DESC, a.started_at
        """,
        [teacher_id, student_id, student_id],
    )
    if not rows:
        return []
    exam_ids = list(dict.fromkeys(str(row['exam_id']) for row in rows))
    marks = ', '.join(['%s'] * len(exam_ids))
    exam_groups = {}
    for row in erd_rows(f'SELECT exam_id, group_id FROM exam_assignments WHERE exam_id IN ({marks}) AND group_id IS NOT NULL', exam_ids):
        exam_groups.setdefault(str(row['exam_id']), set()).add(str(row['group_id']))
    attempt_ids = [str(row['attempt_id']) for row in rows if row['attempt_id']]
    pending = {}
    if attempt_ids:
        attempt_marks = ', '.join(['%s'] * len(attempt_ids))
        for row in erd_rows(
            f"""
            SELECT attempt_id, COUNT(*) AS count, MIN(CAST(id AS TEXT)) AS first_id FROM attempt_answers
            WHERE attempt_id IN ({attempt_marks}) AND COALESCE(needs_manual_grading, false) = true
            GROUP BY attempt_id
            """,
            attempt_ids,
        ):
            pending[str(row['attempt_id'])] = row

    attempt_numbers = {}
    for row in rows:
        row['exam_id'] = str(row['exam_id'])
        row['course_id'] = str(row['course_id']) if row['course_id'] else ''
        row['group_ids'] = exam_groups.get(row['exam_id'], set())
        row['start_at'], row['end_at'] = erd_datetime(row['start_at']), erd_datetime(row['end_at'])
        row['started_at'], row['submitted_at'] = erd_datetime(row['started_at']), erd_datetime(row['submitted_at'])
        grading = pending.get(str(row['attempt_id'])) if row['attempt_id'] else None
        row['pending_count'] = grading['count'] if grading else 0
        row['first_pending_id'] = grading['first_id'] if grading else None
        if row['attempt_id']:
            row['attempt_id'] = str(row['attempt_id'])
            attempt_numbers[row['exam_id']] = attempt_numbers.get(row['exam_id'], 0) + 1
            row['attempt_no'] = attempt_numbers[row['exam_id']]
        else:
            row['attempt_no'] = 0
        row['state'] = _exam_state(row, now)
        row['state_label'], row['state_tone'] = EXAM_STATES[row['state']]
        row['score_20'] = _score_20(row['score'], row['max_score']) if row['state'] == 'done' else None
        row['raw_label'] = f"{_num(row['score'])} از {_num(row['max_score'])}" if row['score'] is not None and row['max_score'] else '-'
        when = row['started_at'] or row['start_at']
        row['date_label'] = _jalali_long_date(when, with_weekday=False) if when else '-'
        row['time_label'] = _time_label(when)
        row['minutes'] = (
            round((row['submitted_at'] - row['started_at']).total_seconds() / 60, 1)
            if row['started_at'] and row['submitted_at'] and row['submitted_at'] >= row['started_at'] else None
        )
    return rows


def _row_in_group(row, group) -> bool:
    return group['id'] in row['group_ids'] or (not row['group_ids'] and group['course_id'] and row['course_id'] == group['course_id'])


def _latest_attempt_per_exam(rows) -> list:
    """One row per exam: its latest attempt (rows come with attempts in start order)."""
    latest = {}
    for row in rows:
        latest[row['exam_id']] = row
    return list(latest.values())


def student_summary(rows) -> dict:
    per_exam = _latest_attempt_per_exam(rows)
    scores = [row['score_20'] for row in per_exam if row['score_20'] is not None]
    held = [row for row in per_exam if row['state'] not in ('upcoming',)]
    attended = [row for row in per_exam if row['state'] in ('done', 'grading')]
    average = round(sum(scores) / len(scores), 2) if scores else None
    return {
        'average': average,
        'average_percent': round(average * 5) if average is not None else None,
        'exams_total': len(per_exam),
        'completed': len(attended),
        'participation': round(len(attended) * 100 / len(held)) if held else None,
        'unfinished': sum(1 for row in rows if row['state'] == 'unfinished'),
        'absent': sum(1 for row in per_exam if row['state'] == 'absent'),
        'grading': sum(1 for row in rows if row['state'] == 'grading'),
    }


def _upcoming(rows) -> list:
    items = sorted((row for row in _latest_attempt_per_exam(rows) if row['state'] in ('upcoming', 'open')),
                   key=lambda row: row['start_at'] or timezone.now())
    for row in items:
        if row['start_at']:
            local = timezone.localtime(row['start_at'])
            _jy, jm, jd = _gregorian_to_jalali(local.year, local.month, local.day)
            row['day_label'], row['month_label'] = fa_digits(f'{jd:02d}'), JALALI_MONTH_NAMES[jm - 1]
    return items[:3]


def _timeline(rows) -> list:
    events = []
    for row in rows:
        if row['submitted_at']:
            label = 'تصحیح‌شده' if row['state'] == 'done' else 'ارسال شد'
            events.append({'at': row['submitted_at'], 'title': f"آزمون «{row['title']}»", 'label': label, 'tone': 'is-ok'})
        elif row['started_at']:
            label = 'ناتمام' if row['state'] == 'unfinished' else 'در حال انجام'
            events.append({'at': row['started_at'], 'title': f"شروع آزمون «{row['title']}»", 'label': label, 'tone': 'is-danger' if row['state'] == 'unfinished' else 'is-blue'})
        elif row['state'] == 'absent':
            events.append({'at': row['end_at'], 'title': f"آزمون «{row['title']}»", 'label': 'غیبت', 'tone': 'is-danger'})
    events.sort(key=lambda event: event['at'], reverse=True)
    for event in events:
        event['date_label'] = _jalali_long_date(event['at'], with_weekday=False)
        event['time_label'] = _time_label(event['at'])
    return events[:5]


def _exam_filters(request, groups) -> dict:
    group_ids = {group['id'] for group in groups}
    start, end = _date_param(request.GET.get('from')), _date_param(request.GET.get('to'))
    return {
        'group': request.GET.get('group') if request.GET.get('group') in group_ids else '',
        'state': request.GET.get('state') if request.GET.get('state') in EXAM_STATES else '',
        'from': start.isoformat() if start else '',
        'to': end.isoformat() if end else '',
    }


def _filter_exam_rows(rows, filters, groups) -> list:
    if filters['group']:
        group = next(group for group in groups if group['id'] == filters['group'])
        rows = [row for row in rows if _row_in_group(row, group)]
    if filters['state']:
        rows = [row for row in rows if row['state'] == filters['state']]
    tz = timezone.get_current_timezone()
    if filters['from']:
        start = timezone.make_aware(datetime.combine(_date_param(filters['from']), time.min), tz)
        rows = [row for row in rows if row['start_at'] and row['start_at'] >= start]
    if filters['to']:
        end = timezone.make_aware(datetime.combine(_date_param(filters['to']), time.max), tz)
        rows = [row for row in rows if row['start_at'] and row['start_at'] <= end]
    return rows


def student_groups(teacher_id, student_id, exam_rows) -> list:
    """This teacher's groups the student is a member of, with the exams of each still open to them."""
    groups = erd_rows(
        f"""
        SELECT sg.id, sg.course_id, sg.course_name, sg.group_code, sg.academic_year, sg.semester, sg.is_active,
               COALESCE(c.code, '') AS course_code,
               COALESCE(NULLIF(owner.full_name, ''), owner.username, '') AS owner_name
        FROM student_group_members sgm
        JOIN student_groups sg ON sg.id = sgm.group_id
        LEFT JOIN courses c ON c.id = sg.course_id
        LEFT JOIN profiles owner ON owner.id = sg.teacher_id
        WHERE sgm.student_user_id = %s AND {_own_groups_condition()}
        ORDER BY sg.course_name, sg.group_code
        """,
        [student_id, teacher_id, teacher_id],
    )
    per_exam = _latest_attempt_per_exam(exam_rows)
    for group in groups:
        group['id'] = str(group['id'])
        group['course_id'] = str(group['course_id']) if group['course_id'] else ''
        group['label'] = _group_label(group)
        group['term_label'] = _teacher_semester_label(group['semester'], group['academic_year'])
        group['is_active'] = group['is_active'] in (True, 1, '1', None)
        mine = [row for row in per_exam if _row_in_group(row, group)]
        group['active_exams'] = sum(1 for row in mine if row['state'] in ('upcoming', 'open', 'in_progress'))
        group['exams_count'] = len(mine)
    return groups


# ---------------------------------------------------------------- analytics

def student_analytics(student_rows, filters, groups) -> dict:
    """Score trend and answer time against the class, hard questions and short insights, for the latest exams."""
    rows = _filter_exam_rows(student_rows, {**filters, 'state': ''}, groups)
    exams = [row for row in _latest_attempt_per_exam(rows) if row['state'] in ('done', 'grading') and row['attempt_id']]
    exams.sort(key=lambda row: row['start_at'] or row['started_at'])
    exams = exams[-TREND_EXAMS:]
    if not exams:
        return {'has_data': False}
    exam_ids = [row['exam_id'] for row in exams]
    marks = ', '.join(['%s'] * len(exam_ids))
    class_rows = erd_rows(
        f"""
        SELECT exam_id, score, max_score, is_graded, started_at, submitted_at FROM exam_attempts
        WHERE exam_id IN ({marks}) AND status IN {DONE_STATUSES}
        """,
        exam_ids,
    )
    # answer time is a difference of two timestamps; done here because SQLite and PostgreSQL disagree on date math
    class_scores, class_minutes = {}, {}
    for row in class_rows:
        exam_id = str(row['exam_id'])
        score = _score_20(row['score'], row['max_score']) if row['is_graded'] in (True, 1, '1') else None
        if score is not None:
            class_scores.setdefault(exam_id, []).append(score)
        started, submitted = erd_datetime(row['started_at']), erd_datetime(row['submitted_at'])
        if started and submitted and submitted >= started:
            class_minutes.setdefault(exam_id, []).append((submitted - started).total_seconds() / 60)

    mean = lambda values: round(sum(values) / len(values), 1) if values else None  # noqa: E731
    points = []
    for index, row in enumerate(exams):
        points.append({
            'title': row['title'],
            'short': fa_digits(f'آزمون {index + 1}'),
            'date_label': row['date_label'],
            'student': row['score_20'],
            'class_avg': mean(class_scores.get(row['exam_id'], [])),
            'minutes': row['minutes'],
            'class_minutes': mean(class_minutes.get(row['exam_id'], [])),
        })
    trend = _trend_chart(points)
    time_chart = _time_chart(points)
    hard = _hard_questions([row['attempt_id'] for row in exams], exam_ids)
    return {
        'has_data': True,
        'points': points,
        'trend': trend,
        'time_chart': time_chart,
        'hard': hard,
        'insights': _insights(points, hard),
    }


def _trend_chart(points) -> dict:
    """SVG coordinates (viewBox 400x200, 0-20 axis) for the student's and the class's score lines."""
    width, height, pad = 400, 200, 24
    step = (width - 2 * pad) / max(1, len(points) - 1)

    def coords(key):
        line = []
        for index, point in enumerate(points):
            if point[key] is None:
                continue
            x = pad + index * step if len(points) > 1 else width / 2
            y = height - pad - (point[key] / 20) * (height - 2 * pad)
            line.append({'x': round(x, 1), 'y': round(y, 1), 'below': round(y + 16, 1), 'value': _num(point[key])})
        return line

    student, class_line = coords('student'), coords('class_avg')
    return {
        'student': student,
        'student_points': ' '.join(f"{p['x']},{p['y']}" for p in student),
        'class': class_line,
        'class_points': ' '.join(f"{p['x']},{p['y']}" for p in class_line),
        'grid': [{'y': round(height - pad - value / 20 * (height - 2 * pad), 1), 'label': fa_digits(value)} for value in (0, 5, 10, 15, 20)],
        'labels': [{'x': round(pad + index * step if len(points) > 1 else width / 2, 1), 'text': point['short']} for index, point in enumerate(points)],
    }


def _time_chart(points) -> dict:
    values = [value for point in points for value in (point['minutes'], point['class_minutes']) if value is not None]
    peak = max(values) if values else 0
    bars = []
    for point in points:
        bars.append({
            'short': point['short'],
            'student': _num(point['minutes']),
            'student_height': round(point['minutes'] * 100 / peak) if peak and point['minutes'] is not None else 0,
            'class_avg': _num(point['class_minutes']),
            'class_height': round(point['class_minutes'] * 100 / peak) if peak and point['class_minutes'] is not None else 0,
        })
    return {'bars': bars, 'has_data': bool(values)}


def _hard_questions(attempt_ids, exam_ids) -> dict:
    """Questions of these exams fewer than 40% of the class answered correctly, and how this student did on them."""
    exam_marks = ', '.join(['%s'] * len(exam_ids))
    correct = 'CASE WHEN aa.is_correct = true THEN 1.0 ELSE 0.0 END'
    hard_rows = erd_rows(
        f"""
        SELECT aa.question_id, AVG({correct}) AS rate, COUNT(*) AS answers
        FROM attempt_answers aa JOIN exam_attempts a ON a.id = aa.attempt_id
        WHERE a.exam_id IN ({exam_marks}) AND a.status IN {DONE_STATUSES} AND aa.is_correct IS NOT NULL
        GROUP BY aa.question_id
        HAVING AVG({correct}) < %s
        ORDER BY AVG({correct})
        """,
        [*exam_ids, HARD_QUESTION_RATE],
    )
    if not hard_rows:
        return {'total': 0}
    question_ids = [str(row['question_id']) for row in hard_rows]
    question_marks = ', '.join(['%s'] * len(question_ids))
    attempt_marks = ', '.join(['%s'] * len(attempt_ids))
    mine = {
        str(row['question_id']): row for row in erd_rows(
            f'SELECT question_id, is_correct, needs_manual_grading FROM attempt_answers '
            f'WHERE attempt_id IN ({attempt_marks}) AND question_id IN ({question_marks})',
            [*attempt_ids, *question_ids],
        )
    }
    texts = {str(row['id']): row['text'] for row in erd_rows(f'SELECT id, text FROM questions WHERE id IN ({question_marks})', question_ids)}
    counts = {'correct': 0, 'wrong': 0, 'missing': 0}
    items = []
    for row in hard_rows:
        question_id = str(row['question_id'])
        answer = mine.get(question_id)
        if not answer or answer['is_correct'] is None:
            outcome = 'missing'
        else:
            outcome = 'correct' if answer['is_correct'] in (True, 1, '1') else 'wrong'
        counts[outcome] += 1
        text = strip_tags(texts.get(question_id) or '').strip()
        items.append({
            'text': (text[:90] + '…') if len(text) > 90 else (text or 'سؤال'),
            'rate': round(float(row['rate']) * 100),
            'outcome': outcome,
        })
    total = len(hard_rows)
    correct_end = counts['correct'] * 100 / total
    wrong_end = correct_end + counts['wrong'] * 100 / total
    return {
        'total': total,
        'counts': counts,
        'percents': {key: round(value * 100 / total) for key, value in counts.items()},
        'donut': f'conic-gradient(#10b981 0 {correct_end:.1f}%, #f43f5e {correct_end:.1f}% {wrong_end:.1f}%, #cbd5e1 {wrong_end:.1f}% 100%)',
        'items': items[:5],
    }


def _insights(points, hard) -> list:
    insights = []
    last = next((point for point in reversed(points) if point['student'] is not None and point['class_avg'] is not None), None)
    if last:
        diff = round(last['student'] - last['class_avg'], 1)
        if diff >= 0:
            insights.append({'tone': 'is-ok', 'text': f"در «{last['title']}» نمره‌ی دانشجو {_num(diff)} نمره بالاتر از میانگین کلاس بود."})
        else:
            insights.append({'tone': 'is-warn', 'text': f"در «{last['title']}» نمره‌ی دانشجو {_num(-diff)} نمره پایین‌تر از میانگین کلاس بود."})
    slow = [point for point in points if point['minutes'] is not None and point['class_minutes']]
    slowest = max(slow, key=lambda point: point['minutes'] - point['class_minutes'], default=None)
    if slowest and slowest['minutes'] > slowest['class_minutes'] * 1.2:
        insights.append({'tone': 'is-warn', 'text': f"زمان پاسخ‌دهی در «{slowest['title']}» ({_num(slowest['minutes'])} دقیقه) بیشتر از میانگین کلاس ({_num(slowest['class_minutes'])} دقیقه) بود."})
    scored = [point['student'] for point in points if point['student'] is not None]
    if len(scored) >= 2:
        change = round(scored[-1] - scored[0], 1)
        if change > 0:
            insights.append({'tone': 'is-info', 'text': f'روند نمره‌ها از اولین تا آخرین آزمون {_num(change)} نمره بهبود داشته است.'})
        elif change < 0:
            insights.append({'tone': 'is-warn', 'text': f'روند نمره‌ها از اولین تا آخرین آزمون {_num(-change)} نمره افت داشته است.'})
    if hard.get('total'):
        insights.append({'tone': 'is-info', 'text': f"از {hard['total']} سؤال دشوار این آزمون‌ها، دانشجو به {hard['counts']['correct']} سؤال درست پاسخ داده است."})
    return [{**item, 'text': fa_digits(item['text'])} for item in insights]


# ---------------------------------------------------------------- notes

def student_notes(teacher_id, student_id, limit=None) -> list:
    rows = erd_rows(
        f"""
        SELECT id, body, is_shared, created_at FROM teacher_student_notes
        WHERE teacher_id = %s AND student_id = %s
        ORDER BY created_at DESC
        {f'LIMIT {int(limit)}' if limit else ''}
        """,
        [teacher_id, student_id],
    )
    for row in rows:
        row['id'] = str(row['id'])
        row['is_shared'] = row['is_shared'] in (True, 1, '1')
        created_at = erd_datetime(row['created_at'])
        row['date_label'] = _jalali_long_date(created_at, with_weekday=False) if created_at else ''
        row['time_label'] = _time_label(created_at)
    return rows


# ---------------------------------------------------------------- views

@erd_role_required('teacher')
def teacher_students(request):
    teacher_id = request.erd_profile_id
    groups = own_groups(teacher_id)
    filters = _list_filters(request, groups)
    rows, tab_rows, tab_counts = filtered_students(teacher_id, filters)
    page = Paginator(tab_rows, filters['per_page']).get_page(request.GET.get('page'))
    return render(request, 'teacher/modern.html', _teacher_modern_context(
        request, 'students',
        sl={
            'page': page, 'rows': list(page.object_list), 'total': len(tab_rows), 'groups': groups,
            'page_range': list(page.paginator.get_elided_page_range(page.number, on_each_side=1, on_ends=1)),
            'ellipsis': Paginator.ELLIPSIS,
            'filters': filters, 'tabs': LIST_TABS, 'tab_counts': tab_counts, 'statuses': STUDENT_STATUSES,
            'page_sizes': LIST_PAGE_SIZES, 'is_filtered': bool(filters['q'] or filters['group'] or filters['status']),
        },
    ))


@erd_role_required('teacher')
def teacher_group_students(request, group_id):
    own_group_or_404(request.erd_profile_id, group_id)
    return redirect(f"{reverse('core:teacher_students')}?group={group_id}")


@erd_role_required('teacher')
def teacher_student_profile(request, student_id):
    teacher_id = request.erd_profile_id
    student = scoped_student_or_404(teacher_id, student_id)
    tab = request.GET.get('tab') if request.GET.get('tab') in PROFILE_TABS else 'overview'
    exam_rows = student_exam_rows(teacher_id, student['id'])
    groups = student_groups(teacher_id, student['id'], exam_rows)
    profile = {
        'student': student, 'tab': tab, 'tabs': PROFILE_TABS, 'groups': groups,
        'summary': student_summary(exam_rows), 'note_max_length': NOTE_MAX_LENGTH,
    }
    if tab == 'overview':
        profile.update(upcoming=_upcoming(exam_rows), timeline=_timeline(exam_rows), notes=student_notes(teacher_id, student['id'], 3))
    elif tab == 'exams':
        filters = _exam_filters(request, groups)
        filtered = _filter_exam_rows(exam_rows, filters, groups)
        page = Paginator(filtered, EXAMS_PAGE_SIZE).get_page(request.GET.get('page'))
        first_pending = next((row['first_pending_id'] for row in exam_rows if row['first_pending_id']), None)
        profile.update(exam_page=page, exam_rows=list(page.object_list), exam_total=len(filtered), filters=filters,
                       states=EXAM_STATES, first_pending=first_pending,
                       is_filtered=any(filters.values()))
    elif tab == 'analytics':
        filters = _exam_filters(request, groups)
        profile.update(filters=filters, analytics=student_analytics(exam_rows, filters, groups),
                       notes=student_notes(teacher_id, student['id'], 3))
    elif tab == 'notes':
        profile.update(notes=student_notes(teacher_id, student['id']))
    return render(request, 'teacher/modern.html', _teacher_modern_context(request, 'student_profile', profile=profile))


@erd_role_required('teacher')
def teacher_student_report(request, student_id):
    """Printable report card (the browser's «Save as PDF» keeps Persian text and RTL layout intact)."""
    teacher_id = request.erd_profile_id
    student = scoped_student_or_404(teacher_id, student_id)
    exam_rows = student_exam_rows(teacher_id, student['id'])
    groups = student_groups(teacher_id, student['id'], exam_rows)
    group = next((item for item in groups if item['id'] == request.GET.get('group')), None)
    if group:
        exam_rows = [row for row in exam_rows if _row_in_group(row, group)]
    return render(request, 'teacher/students/report.html', {
        'student': student,
        'groups': [group] if group else groups,
        'rows': exam_rows,
        'summary': student_summary(exam_rows),
        'today_label': _jalali_long_date(timezone.localdate(), with_weekday=False),
        'auto_print': request.GET.get('print') == '1',
    })


@erd_role_required('teacher')
@require_POST
def teacher_student_note_create(request, student_id):
    teacher_id = request.erd_profile_id
    student = scoped_student_or_404(teacher_id, student_id)
    body = (request.POST.get('body') or '').strip()
    share = request.POST.get('action') == 'share'
    fallback = f"{reverse('core:teacher_student_profile', args=[student['id']])}?tab=notes"
    if not body or len(body) > NOTE_MAX_LENGTH:
        messages.error(request, f'متن یادداشت باید بین ۱ تا {fa_digits(NOTE_MAX_LENGTH)} نویسه باشد.')
        return redirect(_safe_next(request, fallback))
    with transaction.atomic():
        erd_execute(
            'INSERT INTO teacher_student_notes (id, teacher_id, student_id, body, is_shared, created_at) VALUES (%s, %s, %s, %s, %s, %s)',
            [str(uuid.uuid4()), teacher_id, student['id'], body, share, timezone.now()],
        )
        if share:
            create_notification(student['id'], 'بازخورد استاد', body, notification_type='teacher_feedback')
    log_activity(request.user, 'teacher_student_note', 'یادداشت استاد برای دانشجو ثبت شد.' + (' (ارسال به دانشجو)' if share else ''),
                 request, {'student_id': student['id'], 'shared': share})
    messages.success(request, 'بازخورد برای دانشجو ارسال و در یادداشت‌ها ثبت شد.' if share else 'یادداشت ثبت شد.')
    return redirect(_safe_next(request, fallback))


@erd_role_required('teacher')
@require_POST
def teacher_student_note_delete(request, student_id, note_id):
    teacher_id = request.erd_profile_id
    student = scoped_student_or_404(teacher_id, student_id)
    if not _valid_id(note_id) or not erd_row(
        'SELECT 1 AS ok FROM teacher_student_notes WHERE id = %s AND teacher_id = %s AND student_id = %s',
        [note_id, teacher_id, student['id']],
    ):
        raise Http404('یادداشت پیدا نشد.')
    erd_execute('DELETE FROM teacher_student_notes WHERE id = %s AND teacher_id = %s', [note_id, teacher_id])
    messages.success(request, 'یادداشت حذف شد.')
    return redirect(f"{reverse('core:teacher_student_profile', args=[student['id']])}?tab=notes")


@erd_role_required('teacher')
@require_POST
def teacher_students_message(request):
    """In-app notification from the teacher to one or more of their own students."""
    teacher_id = request.erd_profile_id
    student_ids = _scoped_student_ids(teacher_id, request.POST.getlist('student_ids'))
    title = (request.POST.get('title') or '').strip()
    body = (request.POST.get('body') or '').strip()
    fallback = reverse('core:teacher_students')
    if not title or len(title) > MESSAGE_TITLE_MAX_LENGTH or not body or len(body) > NOTE_MAX_LENGTH:
        messages.error(request, f'موضوع (حداکثر {fa_digits(MESSAGE_TITLE_MAX_LENGTH)} نویسه) و متن پیام (حداکثر {fa_digits(NOTE_MAX_LENGTH)} نویسه) را وارد کنید.')
        return redirect(_safe_next(request, fallback))
    with transaction.atomic():
        for student_id in student_ids:
            create_notification(student_id, title, body, notification_type='teacher_message')
    log_activity(request.user, 'teacher_students_message', f'پیام «{title}» برای {len(student_ids)} دانشجو ارسال شد.',
                 request, {'student_count': len(student_ids)})
    messages.success(request, fa_digits(f'پیام برای {len(student_ids)} دانشجو ارسال شد.'))
    return redirect(_safe_next(request, fallback))


def _cell(value):
    """Spreadsheet-safe text: a leading = + - @ would otherwise run as a formula in Excel."""
    text = '' if value is None else str(value)
    return f"'{text}" if text[:1] in ('=', '+', '-', '@') else text


EXPORT_HEADERS = ['نام و نام خانوادگی', 'شماره دانشجویی', 'ایمیل', 'کلاس‌ها', 'آزمون‌های اختصاص‌یافته', 'شرکت‌کرده',
                  'غیبت', 'ناتمام', 'میانگین (از ۲۰)', 'آخرین آزمون', 'وضعیت']
EXPORT_WIDTHS = (26, 16, 28, 34, 12, 12, 10, 10, 14, 28, 16)


def _export_xlsx(table) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = 'دانشجویان'
    sheet.sheet_view.rightToLeft = True
    for row in table:
        sheet.append(row)
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    for index, width in enumerate(EXPORT_WIDTHS):
        sheet.column_dimensions[chr(ord('A') + index)].width = width
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _export_csv(table) -> bytes:
    import csv
    from io import StringIO

    buffer = StringIO()
    csv.writer(buffer).writerows(table)
    return ('﻿' + buffer.getvalue()).encode('utf-8')  # the BOM makes Excel read the Persian text as UTF-8


@erd_role_required('teacher')
def teacher_students_export(request):
    """Excel file of the filtered (or the ticked) students; CSV when openpyxl is not installed."""
    teacher_id = request.erd_profile_id
    filters = _list_filters(request, own_groups(teacher_id))
    _rows, rows, _counts = filtered_students(teacher_id, filters)
    selected = set(request.GET.getlist('ids'))
    if selected:
        rows = [row for row in rows if row['id'] in selected]
    table = [EXPORT_HEADERS] + [
        [
            _cell(row['name']), _cell(row['code']), _cell(row['email']),
            _cell('، '.join(group['label'] for group in row['groups'])),
            row['assigned_count'], row['attended_count'], row['absent_count'], row['unfinished_count'],
            row['average'], _cell((row['last_exam'] or {}).get('title', '')), row['status_label'],
        ]
        for row in rows
    ]
    filename = f'students-{timezone.localdate().isoformat()}'
    try:
        content = _export_xlsx(table)
        content_type, filename = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', f'{filename}.xlsx'
    except ImportError:
        logger.warning('openpyxl is not installed; exporting the student list as CSV instead of XLSX.')
        content, content_type, filename = _export_csv(table), 'text/csv; charset=utf-8', f'{filename}.csv'
    log_activity(request.user, 'teacher_students_export', f'خروجی اکسل {len(rows)} دانشجو گرفته شد.', request, {'count': len(rows)})
    response = HttpResponse(content, content_type=content_type)
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response
