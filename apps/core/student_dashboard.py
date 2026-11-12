"""Student dashboard data: next exam, my exams, my classes, recent results and notifications.

Every figure comes from the student's own rows: exams through the same access rule as the
student exams page (``_sx_accessible_exams``), results through ``_sx_result_rows``.
"""
from datetime import timedelta

from django.core.paginator import Paginator
from django.urls import reverse
from django.utils import timezone

from .views import (
    _exam_result_columns, _exam_result_visibility, _jalali_long_date, _sx_accessible_exams, _sx_dt, _sx_result_rows,
    erd_rows,
)

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


# The exams page splits the dashboard states further: page state -> (badge label, badge tone, tab)
EXAM_PAGE_STATES = {
    'ready': ('آماده ورود', 'green', 'upcoming'),
    'upcoming': ('برگزار نشده', 'orange', 'upcoming'),
    'in_progress': ('در حال انجام', 'blue', 'in_progress'),
    'pending': ('در انتظار تصحیح', 'violet', 'finished'),
    'awaiting_release': ('در انتظار انتشار نتیجه', 'orange', 'finished'),
    'graded': ('نتیجه منتشر شده', 'green', 'finished'),
    'absent': ('غایب', 'red', 'finished'),
}
EXAM_PAGE_TABS = (('all', 'همه'), ('upcoming', 'پیش رو'), ('in_progress', 'در حال انجام'), ('finished', 'پایان‌یافته'))
EXAM_PAGE_SIZE = 10
CLASS_PAGE_SIZE = 10
# icon names from teacher/_qb_icon.html; courses have no icon of their own, so one is picked per course title
COURSE_ICONS = ('book', 'calculator', 'globe', 'chart', 'database', 'monitor')


def _latest_attempts(student_id) -> dict:
    """exam_id -> the student's latest attempt (ordered so the newest overwrites older ones).

    result_visible: the attempt is graded and its score may be shown (released, or shown immediately),
    the same rule as the result page."""
    release_select, _ = _exam_result_columns()
    attempts = {}
    for row in erd_rows(
        f"""
        SELECT ea.id, ea.exam_id, ea.status, ea.score, ea.is_graded, ea.submitted_at, {release_select}
        FROM exam_attempts ea
        JOIN exams e ON e.id = ea.exam_id
        WHERE ea.student_id = %s
        ORDER BY ea.started_at ASC NULLS FIRST
        """,
        [student_id],
    ):
        graded = bool(row.get('is_graded')) and row.get('score') is not None
        row['result_graded'] = graded
        row['result_visible'] = graded and _exam_result_visibility(row)['score']
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
        return {
            'label': 'مشاهده کارنامه' if attempt.get('result_visible') else 'در انتظار نتیجه',
            'url': reverse('core:student_result_detail', args=[attempt['id']]),
            'primary': False,
            'icon': 'chart',
        }
    return {'label': 'مشاهده جزئیات', 'url': detail_url, 'primary': False, 'icon': ''}


def _exam_page_state(exam: dict, attempt: dict, now) -> str:
    if attempt.get('submitted_at'):
        if attempt.get('result_visible'):
            return 'graded'
        return 'awaiting_release' if attempt.get('result_graded') else 'pending'
    if exam['starts_at'] > now:
        return 'upcoming'
    if exam['ends_at'] >= now:
        return 'in_progress' if attempt.get('status') == 'in_progress' else 'ready'
    return 'absent'


def _exam_page_action(exam: dict, attempt: dict, state: str) -> dict:
    if state == 'ready':
        return {'label': 'جزئیات و ورود', 'url': reverse('core:student_exam_detail', args=[exam['id']]), 'primary': True, 'icon': 'play'}
    if state == 'in_progress':
        return {'label': 'ادامه آزمون', 'url': reverse('core:student_attempt', args=[attempt['id']]), 'primary': True, 'icon': 'arrow'}
    if state == 'graded':
        return {'label': 'مشاهده کارنامه', 'url': reverse('core:student_result_detail', args=[attempt['id']]), 'primary': False, 'icon': 'idcard'}
    if state in ('pending', 'awaiting_release'):
        return {'label': 'رسید تحویل', 'url': reverse('core:student_attempt_receipt', args=[attempt['id']]), 'primary': False, 'icon': 'check'}
    return {'label': 'مشاهده جزئیات', 'url': reverse('core:student_exam_detail', args=[exam['id']]), 'primary': False, 'icon': 'eye'}


def _term_label(academic_year, semester) -> str:
    year = (academic_year or '').strip()
    term = (semester or '').strip()
    if not year and not term:
        return ''
    return f'نیمسال {term} {year}'.strip() if term else year


def _course_icon(course_title) -> str:
    return COURSE_ICONS[sum(map(ord, course_title or '')) % len(COURSE_ICONS)]


def student_exam_rows(student_id) -> list:
    """The student's accessible exams with a state, a Jalali date and the action that fits the state."""
    now = timezone.now()
    attempts = _latest_attempts(student_id)
    rows = []
    for exam in _sx_accessible_exams(student_id):
        attempt = attempts.get(str(exam['id'])) or {}
        state = _exam_state(exam, attempt, now)
        label, tone = EXAM_STATES[state]
        page_state = _exam_page_state(exam, attempt, now)
        page_label, page_tone, page_tab = EXAM_PAGE_STATES[page_state]
        rows.append({
            'id': exam['id'],
            'title': exam['title'],
            'course': exam['course_title'],
            'course_id': str(exam['course_id']) if exam.get('course_id') else '',
            'course_icon': _course_icon(exam['course_title']),
            'term': _term_label(exam.get('academic_year'), exam.get('semester')),
            'ends_at': exam['ends_at'],
            'page_state': page_state,
            'page_label': page_label,
            'page_tone': page_tone,
            'page_tab': page_tab,
            'page_action': _exam_page_action(exam, attempt, page_state),
            'result_url': reverse('core:student_result_detail', args=[attempt['id']]) if attempt.get('submitted_at') else '',
            # «پیش‌نمایش» with sample questions (exam_preview.py): the exam page, rules and structure, never its questions.
            'preview_url': f"{reverse('core:exam_preview', args=[exam['id']])}?new=1",
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


def _ordered_rows(rows: list) -> list:
    """Open and upcoming exams soonest first, then past ones newest first."""
    open_rows = [row for row in rows if row['state'] in ('ready', 'upcoming')]
    past_rows = sorted((row for row in rows if row['state'] in ('done', 'missed')), key=lambda row: row['starts_at'], reverse=True)
    return open_rows + past_rows


def _table_rows(rows: list) -> list:
    return _ordered_rows(rows)[:EXAM_TABLE_SIZE]


def student_classes(student_id, include_archived=False) -> list:
    archived_filter = '' if include_archived else 'AND COALESCE(sg.is_archived, false) = false'
    return erd_rows(
        f"""
        SELECT sg.id, COALESCE(c.title, sg.course_name, 'درس') AS course_title, sg.group_code,
               p.full_name AS teacher_name, sg.teacher_id, sg.academic_year, sg.semester,
               COALESCE(sg.is_archived, false) AS is_archived, COALESCE(sg.is_active, true) AS is_active
        FROM student_group_members sgm
        JOIN student_groups sg ON sg.id = sgm.group_id
        LEFT JOIN courses c ON c.id = sg.course_id
        LEFT JOIN profiles p ON p.id = sg.teacher_id
        WHERE sgm.student_user_id = %s {archived_filter}
        ORDER BY course_title
        """,
        [student_id],
    )


def _group_exam_ids(group_ids) -> dict:
    """group_id -> ids of the class's exams (callers intersect with the student's accessible exams).

    An exam belongs to a class when it is assigned to the group and is an exam of the group's course; an exam of
    another course assigned to the group still reaches the student (on «آزمون‌های من»), just not under this class."""
    if not group_ids:
        return {}
    placeholders = ', '.join(['%s'] * len(group_ids))
    by_group = {}
    for row in erd_rows(
        f"""
        SELECT ea.exam_id, ea.group_id
        FROM exam_assignments ea
        JOIN student_groups sg ON sg.id = ea.group_id
        JOIN exams e ON e.id = ea.exam_id
        WHERE ea.group_id IN ({placeholders})
          AND (e.course_id IS NULL OR sg.course_id IS NULL OR e.course_id = sg.course_id)
        """,
        list(group_ids),
    ):
        by_group.setdefault(str(row['group_id']), set()).add(str(row['exam_id']))
    return by_group


def _page(items: list, page_number, size: int):
    return Paginator(items, size).get_page(page_number)


CALENDAR_WEEKDAYS = ('شنبه', 'یکشنبه', 'دوشنبه', 'سه‌شنبه', 'چهارشنبه', 'پنجشنبه', 'جمعه')


def student_calendar_context(request, student_id) -> dict:
    """«تقویم من»: the student's exams on a Jalali month (Tehran time), each in its state's colour and linked to the
    page that fits it, plus the month's exams as a list (readable on phones). An exam open for several days is shown
    on every day of its window that falls in the month."""
    from .templatetags.core_extras import _gregorian_to_jalali
    from .views import _calendar_event_day, _jalali_calendar_month

    shown = _jalali_calendar_month(request)
    by_day, month_rows = {}, []
    for row in (student_exam_rows(student_id) if student_id else []):
        starts, ends = row['starts_at'], row['ends_at']
        start_day = _calendar_event_day(starts)
        end_day = _calendar_event_day(ends)
        event = {
            'id': row['id'], 'title': row['title'], 'course': row['course'], 'time': start_day[3],
            'tone': row['page_tone'], 'label': row['page_label'], 'url': row['page_action']['url'],
            'date_label': row['date_label'],
            'until_label': (f"{_jalali_long_date(ends, with_weekday=False)} ساعت {end_day[3]}"
                            if end_day[:3] != start_day[:3] else end_day[3]),
        }
        in_month = False
        day = timezone.localtime(starts).date()
        last = timezone.localtime(ends).date()
        while day <= last and (last - day).days < 62:  # long windows (training exams): every day they are open
            jy, jm, jd = _gregorian_to_jalali(day.year, day.month, day.day)  # a Tehran calendar day
            if (jy, jm) == (shown['year'], shown['month']):
                by_day.setdefault(jd, []).append({**event, 'continues': day != timezone.localtime(starts).date()})
                in_month = True
            day += timedelta(days=1)
        if in_month:
            month_rows.append({**event, 'starts_at': starts})
    month_rows.sort(key=lambda item: item['starts_at'])
    days = [{'day': None, 'events': []} for _ in range(shown['leading_blanks'])]
    days += [{'day': day, 'events': sorted(by_day.get(day, []), key=lambda item: (item['continues'], item['time'])),
              'is_today': (shown['year'], shown['month'], day) == shown['today']}
             for day in range(1, shown['length'] + 1)]
    days += [{'day': None, 'events': []} for _ in range(-len(days) % 7)]
    return {
        'calendar_month': shown,
        'calendar_days': days,
        'calendar_weekdays': CALENDAR_WEEKDAYS,
        'calendar_rows': month_rows,
        'calendar_legend': [(label, tone) for _key, (label, tone, _tab) in EXAM_PAGE_STATES.items()],
    }


def student_exams_page_context(request, student_id) -> dict:
    """Context for the "my exams" page: tabs, the exam open for entry, filters and one page of the table."""
    rows = _ordered_rows(student_exam_rows(student_id)) if student_id else []
    classes = {str(group['id']): group for group in student_classes(student_id, include_archived=True)} if student_id else {}
    tab = request.GET.get('tab', 'all')
    tab = tab if tab in dict(EXAM_PAGE_TABS) else 'all'
    query = request.GET.get('q', '').strip()
    course = request.GET.get('course', '').strip()
    term = request.GET.get('term', '').strip()
    class_id = request.GET.get('class', '').strip()
    selected_class = classes.get(class_id)

    courses = sorted({(row['course_id'], row['course']) for row in rows if row['course_id']}, key=lambda item: item[1])
    terms = sorted({row['term'] for row in rows if row['term']}, reverse=True)
    filtered = rows
    if selected_class:
        class_exam_ids = _group_exam_ids([class_id]).get(class_id, set())
        filtered = [row for row in filtered if str(row['id']) in class_exam_ids]
    if query:
        needle = query.casefold()
        filtered = [row for row in filtered if needle in row['title'].casefold() or needle in row['course'].casefold()]
    if course:
        filtered = [row for row in filtered if row['course_id'] == course]
    if term:
        filtered = [row for row in filtered if row['term'] == term]
    counts = {key: sum(1 for row in filtered if key == 'all' or row['page_tab'] == key) for key, _label in EXAM_PAGE_TABS}
    if tab != 'all':
        filtered = [row for row in filtered if row['page_tab'] == tab]

    featured = next((row for row in rows if row['page_state'] == 'in_progress'), None) or next(
        (row for row in rows if row['page_state'] == 'ready'), None)
    if featured:
        starts, ends = timezone.localtime(featured['starts_at']), timezone.localtime(featured['ends_at'])
        ends_label = ends.strftime('%H:%M')
        if ends.date() != starts.date():
            ends_label = f"{_jalali_long_date(featured['ends_at'], with_weekday=False)} ساعت {ends_label}"
        featured = {**featured, 'ends_label': ends_label}
    return {
        'tabs': [{'key': key, 'label': label, 'count': counts[key]} for key, label in EXAM_PAGE_TABS],
        'tab': tab,
        'featured': featured,
        'page_obj': _page(filtered, request.GET.get('page'), EXAM_PAGE_SIZE),
        'total': len(filtered),
        'has_exams': bool(rows),
        'query': query,
        'course': course,
        'term': term,
        'courses': courses,
        'terms': terms,
        'selected_class': selected_class,
    }


def _class_card(group: dict, exam_ids: set, rows_by_id: dict, practice_ids: set) -> dict:
    """A class card: only the class's own exams (see ``_group_exam_ids``) that the student can actually see."""
    class_rows = [rows_by_id[exam_id] for exam_id in exam_ids if exam_id in rows_by_id]
    open_now = sorted((row for row in class_rows if row['state'] == 'ready'), key=lambda row: row['ends_at'])
    upcoming = sorted((row for row in class_rows if row['state'] == 'upcoming'), key=lambda row: row['starts_at'])
    # an exam that is already open is shown with its closing date (its start date is in the past)
    current = open_now[0] if open_now else (upcoming[0] if upcoming else None)
    if current:
        is_open = current['state'] == 'ready'
        current = {**current, 'is_open': is_open,
                   'when_label': (f"تا {_jalali_long_date(current['ends_at'], with_weekday=False)}" if is_open
                                  else current['date_label'])}
    return {
        **group,
        'id': str(group['id']),
        'term': _term_label(group.get('academic_year'), group.get('semester')),
        'icon': _course_icon(group['course_title']),
        'is_current': bool(group['is_active']) and not group['is_archived'],
        'exam_count': len(class_rows),
        'result_count': sum(1 for row in class_rows if row['page_state'] == 'graded'),
        'practice_count': len(exam_ids & practice_ids),
        'next_exam': current,
    }


def student_classes_page_context(request, student_id) -> dict:
    """Context for the "my classes" page: the student's own groups, current or past, with their exams."""
    groups = student_classes(student_id, include_archived=True) if student_id else []
    rows_by_id = {str(row['id']): row for row in student_exam_rows(student_id)} if groups else {}
    # practice exams («آزمون آزمایشی») have no menu item of their own: each class card links to its class's ones
    practice_ids = {str(exam['id']) for exam in _sx_accessible_exams(student_id, practice=True)} if student_id else set()
    exams_by_group = _group_exam_ids([str(group['id']) for group in groups])
    cards = [_class_card(group, exams_by_group.get(str(group['id']), set()), rows_by_id, practice_ids) for group in groups]
    from .teacher_preferences import public_teacher_cards

    # the teacher as they chose to be shown: display name, and bio / e-mail only when their privacy settings allow
    teachers = public_teacher_cards(group.get('teacher_id') for group in groups)
    for card, group in zip(cards, groups):
        teacher = teachers.get(str(group.get('teacher_id') or ''))
        if teacher:
            card.update(teacher_name=teacher['name'] or card.get('teacher_name'), teacher_bio=teacher['bio'], teacher_email=teacher['email'])

    tab = 'past' if request.GET.get('tab') == 'past' else 'current'
    view = 'list' if request.GET.get('view') == 'list' else 'grid'
    query = request.GET.get('q', '').strip()
    term = request.GET.get('term', '').strip()
    terms = sorted({card['term'] for card in cards if card['term']}, reverse=True)
    filtered = cards
    if query:
        needle = query.casefold()
        filtered = [card for card in filtered
                    if needle in card['course_title'].casefold() or needle in (card['teacher_name'] or '').casefold()]
    if term:
        filtered = [card for card in filtered if card['term'] == term]
    counts = {
        'current': sum(1 for card in filtered if card['is_current']),
        'past': sum(1 for card in filtered if not card['is_current']),
    }
    filtered = [card for card in filtered if card['is_current'] == (tab == 'current')]
    return {
        'tab': tab,
        'view': view,
        'counts': counts,
        'page_obj': _page(filtered, request.GET.get('page'), CLASS_PAGE_SIZE),
        'total': len(filtered),
        'has_classes': bool(cards),
        'query': query,
        'term': term,
        'terms': terms,
        'has_practice': bool(practice_ids),
    }


def _recent_results(student_id) -> tuple:
    """(the latest graded results for the list, how many were submitted in the last NEW_RESULT_DAYS days)."""
    graded = [row for row in _sx_result_rows(student_id, practice=False) if not row['is_pending']]
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
                'stats': {'upcoming': 0, 'classes': 0, 'new_results': 0},
                **_dashboard_boxes({'upcoming': 0, 'classes': 0, 'new_results': 0})}
    rows = student_exam_rows(student_id)
    classes = student_classes(student_id)
    results, new_results = _recent_results(student_id)
    next_exam = next((row for row in rows if row['state'] == 'ready'), None) or next(
        (row for row in rows if row['state'] == 'upcoming'), None)
    full_name = profile.get('full_name') or request.user.get_full_name() or request.user.username
    stats = {
        'upcoming': sum(1 for row in rows if row['state'] in ('ready', 'upcoming')),
        'classes': len(classes),
        'new_results': new_results,
    }
    return {
        'first_name': profile.get('first_name') or full_name.split(' ')[0],
        'next_exam': next_exam,
        'exam_rows': _table_rows(rows),
        'classes': classes[:CLASS_LIST_SIZE],
        'results': results,
        'notifications': _notifications(student_id),
        'stats': stats,
        **_dashboard_boxes(stats),
    }


def _dashboard_boxes(stats) -> dict:
    """The «آزمون بعدی» tip and the three KPI boxes, drawn by partials/dashboard/kpis.html (the look shared with the teacher dashboard)."""
    exams_url = reverse('core:student_exam_schedule')
    return {'tip': {'title': 'نکات مهم قبل از آزمون',
                    'text': 'لطفاً با اتصال پایدار اینترنت، مرورگر به‌روز و کارت دانشجویی در زمان آزمون حاضر باشید.'},
            'kpis': [
        {'label': 'آزمون پیش‌رو', 'value': stats['upcoming'], 'hint': 'آزمون در انتظار برگزاری', 'icon': 'exams', 'url': exams_url},
        {'label': 'کلاس‌های من', 'value': stats['classes'], 'hint': 'کلاس فعال', 'icon': 'classes'},
        {'label': 'نتایج جدید', 'value': stats['new_results'], 'hint': 'کارنامه منتشر شده در ۱۴ روز اخیر', 'icon': 'results', 'url': f'{exams_url}?tab=finished'},
    ]}
