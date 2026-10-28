"""Student dashboard data: next exam, my exams, my classes, recent results and notifications.

Every figure comes from the student's own rows: exams through the same access rule as the
student exams page (``_sx_accessible_exams``), results through ``_sx_result_rows``.
"""
from datetime import timedelta

from django.urls import reverse
from django.utils import timezone

from .views import _jalali_long_date, _sx_accessible_exams, _sx_dt, _sx_result_rows, erd_rows

NEW_RESULT_DAYS = 14
EXAM_TABLE_SIZE = 5
CLASS_LIST_SIZE = 3
RESULT_LIST_SIZE = 2
NOTIFICATION_LIST_SIZE = 2

# state -> (badge label, badge tone)
EXAM_STATES = {
    'ready': ('آماده ورود', 'green'),
    'upcoming': ('در انتظار برگزاری', 'blue'),
    'done': ('برگزار شده', 'muted'),
    'missed': ('پایان یافته', 'muted'),
}


def _latest_attempts(student_id) -> dict:
    """exam_id -> the student's latest attempt (ordered so the newest overwrites older ones)."""
    attempts = {}
    for row in erd_rows(
        """
        SELECT id, exam_id, status, score, is_graded, submitted_at
        FROM exam_attempts
        WHERE student_id = %s
        ORDER BY started_at ASC NULLS FIRST
        """,
        [student_id],
    ):
        attempts[str(row['exam_id'])] = row
    return attempts


def _exam_state(exam: dict, attempt: dict, now) -> str:
    if attempt.get('submitted_at'):
        return 'done'
    if exam['starts_at'] > now:
        return 'upcoming'
    if exam['ends_at'] >= now:
        return 'ready'
    return 'missed'


def _exam_action(exam: dict, attempt: dict, state: str) -> dict:
    detail_url = reverse('core:student_exam_detail', args=[exam['id']])
    if state == 'ready':
        return {'label': 'مشاهده جزئیات و ورود', 'url': detail_url, 'primary': True, 'icon': 'arrow'}
    if state == 'done':
        graded = bool(attempt.get('is_graded')) and attempt.get('score') is not None
        return {
            'label': 'مشاهده کارنامه' if graded else 'در انتظار نتیجه',
            'url': reverse('core:student_result_detail', args=[attempt['id']]),
            'primary': False,
            'icon': 'chart',
        }
    return {'label': 'مشاهده جزئیات', 'url': detail_url, 'primary': False, 'icon': ''}


def student_exam_rows(student_id) -> list:
    """The student's accessible exams with a state, a Jalali date and the action that fits the state."""
    now = timezone.now()
    attempts = _latest_attempts(student_id)
    rows = []
    for exam in _sx_accessible_exams(student_id):
        attempt = attempts.get(str(exam['id'])) or {}
        state = _exam_state(exam, attempt, now)
        label, tone = EXAM_STATES[state]
        rows.append({
            'id': exam['id'],
            'title': exam['title'],
            'course': exam['course_title'],
            'starts_at': exam['starts_at'],
            'date_label': _jalali_long_date(exam['starts_at'], with_weekday=False),
            'time_label': timezone.localtime(exam['starts_at']).strftime('%H:%M'),
            'duration': exam['duration_minutes'],
            'question_count': exam['question_count'],
            'state': state,
            'state_label': label,
            'state_tone': tone,
            'action': _exam_action(exam, attempt, state),
        })
    return rows


def _table_rows(rows: list) -> list:
    """Open and upcoming exams soonest first, then past ones newest first."""
    open_rows = [row for row in rows if row['state'] in ('ready', 'upcoming')]
    past_rows = sorted((row for row in rows if row['state'] in ('done', 'missed')), key=lambda row: row['starts_at'], reverse=True)
    return (open_rows + past_rows)[:EXAM_TABLE_SIZE]


def student_classes(student_id) -> list:
    return erd_rows(
        """
        SELECT sg.id, COALESCE(c.title, sg.course_name, 'درس') AS course_title, sg.group_code,
               p.full_name AS teacher_name
        FROM student_group_members sgm
        JOIN student_groups sg ON sg.id = sgm.group_id
        LEFT JOIN courses c ON c.id = sg.course_id
        LEFT JOIN profiles p ON p.id = sg.teacher_id
        WHERE sgm.student_user_id = %s AND COALESCE(sg.is_archived, false) = false
        ORDER BY course_title
        """,
        [student_id],
    )


def _recent_results(student_id) -> tuple:
    """(the latest graded results for the list, how many were submitted in the last NEW_RESULT_DAYS days)."""
    graded = [row for row in _sx_result_rows(student_id) if not row['is_pending']]
    since = timezone.now() - timedelta(days=NEW_RESULT_DAYS)
    new_count = sum(1 for row in graded if row['submitted_at'] and (_sx_dt(row['submitted_at']) or since) >= since)
    items = [{
        'title': row['title'],
        'date_label': _jalali_long_date(row['submitted_at'], with_weekday=False),
        'score_20': round(row['percent'] / 5, 1),
        'url': reverse('core:student_result_detail', args=[row['id']]),
    } for row in graded[:RESULT_LIST_SIZE]]
    return items, new_count


def _notifications(student_id) -> list:
    # notifications has no created_at column, so unread ones come first instead of the newest.
    return erd_rows(
        """
        SELECT id, title, message, type, link, is_read
        FROM notifications
        WHERE user_id = %s
        ORDER BY is_read ASC
        LIMIT %s
        """,
        [student_id, NOTIFICATION_LIST_SIZE],
    )


def student_dashboard_context(request, profile) -> dict:
    student_id = profile['id'] if profile else None
    if not student_id:
        return {'first_name': request.user.first_name or request.user.username, 'exam_rows': [], 'classes': [],
                'results': [], 'notifications': [], 'next_exam': None,
                'stats': {'upcoming': 0, 'classes': 0, 'new_results': 0}}
    rows = student_exam_rows(student_id)
    classes = student_classes(student_id)
    results, new_results = _recent_results(student_id)
    next_exam = next((row for row in rows if row['state'] == 'ready'), None) or next(
        (row for row in rows if row['state'] == 'upcoming'), None)
    full_name = profile.get('full_name') or request.user.get_full_name() or request.user.username
    return {
        'first_name': profile.get('first_name') or full_name.split(' ')[0],
        'next_exam': next_exam,
        'exam_rows': _table_rows(rows),
        'classes': classes[:CLASS_LIST_SIZE],
        'results': results,
        'notifications': _notifications(student_id),
        'stats': {
            'upcoming': sum(1 for row in rows if row['state'] in ('ready', 'upcoming')),
            'classes': len(classes),
            'new_results': new_results,
        },
    }
