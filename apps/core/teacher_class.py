"""«کلاس»: one page per group for its teacher (teacher/courses/<group_id>/), drawn after the user's five mock-ups.

Tabs (same URL, ?tab=…, swapped without reload by live-region.js; the tab strip is identical on every tab):
  overview  «نمای کلی»   info strip (کد درس / نیمسال / ظرفیت / عضویت / «دسترسی‌های استاد» that opens), four KPIs,
                         «آزمون در حال برگزاری», «در انتظار تصحیح», «آزمون‌های پیش‌رو», «فعالیت‌های اخیر»
  students  «دانشجویان» the members with «آزمون‌های شرکت‌کرده» (x of the class's ended exams), last exam's score,
                         learning status (LEARNING), search + status filter, Excel (?export=xlsx);
                         &student=<id> = «عملکرد دانشجو» beside a compact list, &pview=perf|chart|activity
  exams     «آزمون‌ها»   the class's exams: views._teacher_exam_list with the class filter (same actions and «…» menu
                         as «آزمون‌های من»), status chips + status dropdown + search, server pager (10)
A class's exams = this teacher's exams of the group's course or assigned to the group (same rule as before).
Membership and class details belong to the academic manager: nothing here changes them.
Template: templates/teacher/class/ (page.html + one partial per tab); static/css/class-hub.css on top of exam-hub.css.
"""
import re
from io import BytesIO
from urllib.parse import urlencode

from django.http import Http404, HttpResponse
from django.urls import reverse
from django.utils import timezone

from . import exam_list
from .templatetags.core_extras import fa_digits
from .views import (
    QUESTION_TYPE_LABELS,
    STUDENT_AVATAR_SQL,
    _TEACHER_EXAM_STATE_BY_LABEL,
    _teacher_courses_rows,
    _teacher_exam_list,
    _teacher_exam_status,
    _teacher_selected_course,
    erd_datetime,
    erd_rows,
    exam_access_code,
)

TABS = (
    ('overview', 'نمای کلی', 'chart'),
    ('students', 'دانشجویان', 'users'),
    ('exams', 'آزمون‌ها', 'doc'),
)
TAB_KEYS = {key for key, _label, _icon in TABS}

# learning status of a student in the class → (label, pill tone, icon)
LEARNING = {
    'excellent': ('پیشرفت عالی', 'green', 'chevrons'),
    'good': ('پیشرفت خوب', 'green', 'trendup'),
    'average': ('پیشرفت متوسط', 'blue', 'equal'),
    'weak': ('نیاز به تلاش بیشتر', 'red', 'trenddown'),
    'pending': ('در انتظار ارزیابی', 'grey', 'clock'),
    'late': ('با تأخیر در مشارکت', 'amber', 'alert'),
}
# average out of 20 → status (first threshold reached)
LEARNING_STEPS = ((19, 'excellent'), (16, 'good'), (12, 'average'), (0, 'weak'))

# one ended exam for one student → (label, tone)
RESULT_STATES = {
    'done': ('تأیید شده', 'green'),
    'grading': ('در انتظار تصحیح', 'amber'),
    'absent': ('غایب', 'red'),
    'unfinished': ('ناتمام', 'amber'),
}

# exams tab: chips (as drawn) and the dropdown with every state
EXAM_CHIPS = (
    ('all', 'همه', ''),
    ('finished', 'پایان‌یافته', 'check'),
    ('running', 'در حال برگزاری', 'play'),
    ('scheduled', 'زمان‌بندی‌شده', 'calendar'),
    ('pending_approval', 'در انتظار تأیید', 'clock'),
)
EXAM_STATE_OPTIONS = (
    ('all', 'همه وضعیت‌ها'), ('draft', 'پیش‌نویس'), ('pending_approval', 'در انتظار تأیید'),
    ('scheduled', 'زمان‌بندی‌شده'), ('running', 'در حال برگزاری'), ('finished', 'پایان‌یافته'), ('cancelled', 'لغو شده'),
)
# status pill of an exam row → (label, tone, icon)
EXAM_PILLS = {
    'draft': ('پیش‌نویس', 'grey', 'doc'),
    'pending_approval': ('در انتظار تأیید', 'amber', 'clock'),
    'scheduled': ('زمان‌بندی‌شده', 'blue', 'calendar'),
    'running': ('در حال برگزاری', 'green', 'play'),
    'finished': ('پایان‌یافته', 'green', 'check'),
    'finished_pending': ('پایان‌یافته (تصحیح نشده)', 'violet', 'info'),
    'cancelled': ('لغو شده', 'red', 'x'),
}
# main button of an exam row → icon
EXAM_MAIN_ICONS = {'draft': 'edit', 'pending_approval': 'clock', 'scheduled': 'calendar', 'running': 'live', 'finished': 'chart'}

PERMISSIONS = (
    'مشاهده دانشجویان و عملکرد آن‌ها',
    'ایجاد، ویرایش و مدیریت آزمون‌های کلاس',
    'تصحیح پاسخ‌ها و انتشار نتایج',
    'استفاده از بانک سؤال درس',
)
DONE = ('submitted', 'graded', 'completed')
UPCOMING_LIMIT = 5
ACTIVITY_LIMIT = 5


# ---------------------------------------------------------------- helpers

def _score_20(score, max_score):
    if score is None or not max_score or float(max_score) <= 0:
        return None
    return round(float(score) * 20 / float(max_score), 1)


def _when_label(value, now) -> str:
    """«امروز ۱۰:۱۵» / «دیروز ۱۸:۴۰» / «۱۴۰۵/۰۸/۱۸ ۱۶:۲۰»."""
    from .templatetags.core_extras import jalali_date

    moment = timezone.localtime(value)
    days = (timezone.localtime(now).date() - moment.date()).days
    day = 'امروز' if days == 0 else 'دیروز' if days == 1 else jalali_date(moment)
    return fa_digits(f"{day} {moment.strftime('%H:%M')}")


def _date_time(value) -> str:
    """«۱۴۰۵/۰۸/۲۵ – ۱۰:۰۰» ('' when empty)."""
    from .templatetags.core_extras import jalali_date

    value = erd_datetime(value)
    if not value:
        return ''
    return fa_digits(f"{jalali_date(value)} – {timezone.localtime(value).strftime('%H:%M')}")


def _group_title(group) -> str:
    return f"{group['course_name'] or ''} · گروه {group['group_code']}" if group.get('group_code') else (group['course_name'] or '')


def _term_label(group) -> str:
    year = str(group.get('academic_year') or '').strip()
    return fa_digits(year.replace('-', ' – ')) if year else ''


def _url(group_id, **params) -> str:
    query = urlencode({key: value for key, value in params.items() if value not in (None, '')})
    return f"{reverse('core:teacher_course_detail', args=[group_id])}{'?' + query if query else ''}"


def _hub(exam_id, tab='overview') -> str:
    from .exam_hub import hub_url

    return hub_url('teacher', exam_id, tab)


# ---------------------------------------------------------------- data

def class_exams(teacher_id, group) -> list:
    """This teacher's exams of the class, newest start first, each with its state key (exam_list.STATE_TABS)."""
    rows = erd_rows(
        """
        SELECT e.id, e.title, e.duration_minutes, e.start_at, e.end_at, COALESCE(e.lifecycle_status, '') AS lifecycle,
               COALESCE(e.is_cancelled, false) AS is_cancelled, COALESCE(e.is_published, false) AS is_published,
               COALESCE(e.approval_status, '') AS approval_status, COALESCE(e.exam_type, '') AS exam_type,
               e.results_published_at
        FROM exams e
        WHERE e.teacher_id = %s
          AND (e.course_id = %s OR e.id IN (SELECT exam_id FROM exam_assignments WHERE group_id = %s))
        ORDER BY e.start_at DESC NULLS LAST, e.title
        """,
        [teacher_id, group.get('course_id'), group['id']],
    )
    now = timezone.now()
    for row in rows:
        row['id'] = str(row['id'])
        row['start_at'], row['end_at'] = erd_datetime(row['start_at']), erd_datetime(row['end_at'])
        label, _tone = _teacher_exam_status(row, now)
        row['state'] = _TEACHER_EXAM_STATE_BY_LABEL.get(label, 'draft')
    return rows


def _members(group_id) -> list:
    return [dict(row, id=str(row['id'])) for row in erd_rows(
        f"""
        SELECT p.id, COALESCE(NULLIF(p.full_name, ''), NULLIF(sgm.full_name, ''), p.username, 'دانشجو') AS name,
               COALESCE(NULLIF(sp.student_number, ''), NULLIF(sgm.student_number, ''), p.identifier, '') AS code,
               {STUDENT_AVATAR_SQL} AS avatar_url
        FROM student_group_members sgm
        JOIN profiles p ON p.id = sgm.student_user_id
        LEFT JOIN student_profiles sp ON sp.user_id = p.id
        WHERE sgm.group_id = %s
        ORDER BY name
        """,
        [group_id],
    )]


def _attempts(group_id, exam_ids) -> dict:
    """{(exam id, student id): latest non-practice attempt of a member} with its pending manual answers."""
    if not exam_ids:
        return {}
    marks = ', '.join(['%s'] * len(exam_ids))
    latest = {}
    for row in erd_rows(
        f"""
        SELECT a.id, a.exam_id, a.student_id, COALESCE(a.status, '') AS status, a.score, a.max_score,
               COALESCE(a.is_graded, false) AS is_graded, a.started_at, a.submitted_at,
               (SELECT COUNT(*) FROM attempt_answers aa
                 WHERE aa.attempt_id = a.id AND COALESCE(aa.needs_manual_grading, false) = true) AS pending
        FROM exam_attempts a
        WHERE a.exam_id IN ({marks}) AND COALESCE(a.practice_mode, '') = ''
          AND a.student_id IN (SELECT student_user_id FROM student_group_members WHERE group_id = %s)
        ORDER BY a.started_at NULLS FIRST
        """,
        [*exam_ids, group_id],
    ):
        latest[(str(row['exam_id']), str(row['student_id']))] = row
    return latest


def _exclusions(exam_ids) -> set:
    if not exam_ids:
        return set()
    marks = ', '.join(['%s'] * len(exam_ids))
    return {(str(row['exam_id']), str(row['student_profile_id'])) for row in erd_rows(
        f'SELECT exam_id, student_profile_id FROM exam_assignment_exclusions WHERE exam_id IN ({marks})', exam_ids)}


def _result(attempt) -> dict:
    """One ended exam for one student: state key (RESULT_STATES), score out of 20, attempt id."""
    if not attempt:
        return {'state': 'absent', 'score': None, 'attempt_id': None}
    done = attempt['status'] in DONE
    score = _score_20(attempt['score'], attempt['max_score'])
    if done and attempt['is_graded'] and score is not None and not attempt['pending']:
        state = 'done'
    else:
        state = 'grading' if done else 'unfinished'
    return {'state': state, 'score': score if state == 'done' else None, 'attempt_id': str(attempt['id'])}


def _learning(results) -> str:
    """LEARNING key from a student's results on the class's ended exams (oldest first)."""
    if not results:
        return 'pending'
    last = results[-1]['state']
    if last in ('absent', 'unfinished'):
        return 'late'
    scores = [item['score'] for item in results if item['state'] == 'done']
    if last == 'grading' or not scores:
        return 'pending'
    average = sum(scores) / len(scores)
    return next(key for limit, key in LEARNING_STEPS if average >= limit)


def class_students(group, exams) -> list:
    """Every member with their results on the class's ended exams (oldest first) and the summary the list shows.
    Only exams at least one member took count: an ended exam nobody in the class sat makes no one «غایب»."""
    ended = sorted((exam for exam in exams if exam['state'] == 'finished'),
                   key=lambda exam: exam['end_at'] or exam['start_at'] or timezone.now())
    ids = [exam['id'] for exam in ended]
    attempts, excluded = _attempts(group['id'], ids), _exclusions(ids)
    held = {exam_id for exam_id, _student_id in attempts}
    ended = [exam for exam in ended if exam['id'] in held]  # an ended exam nobody in the class took was not held for it
    students = _members(group['id'])
    for student in students:
        results = []
        for exam in ended:
            if (exam['id'], student['id']) in excluded:
                continue
            result = _result(attempts.get((exam['id'], student['id'])))
            results.append({**result, 'exam': exam,
                            'state_label': RESULT_STATES[result['state']][0], 'state_tone': RESULT_STATES[result['state']][1]})
        scores = [item['score'] for item in results if item['state'] == 'done']
        student['results'] = results
        student['initial'] = student['name'][:1]
        student['taken'] = sum(1 for item in results if item['state'] in ('done', 'grading'))
        student['total'] = len(results)
        student['absent'] = sum(1 for item in results if item['state'] == 'absent')
        student['last'] = results[-1] if results else None
        student['last_done'] = next((item for item in reversed(results) if item['state'] == 'done'), None)
        student['average'] = round(sum(scores) / len(scores), 1) if scores else None
        student['best'] = max(scores) if scores else None
        student['worst'] = min(scores) if scores else None
        student['learning'] = _learning(results)
        student['learning_label'], student['learning_tone'], student['learning_icon'] = LEARNING[student['learning']]
        student['is_absent'] = bool(results) and results[-1]['state'] == 'absent'
    return students


def _class_averages(students) -> dict:
    """{exam id: the class's average out of 20 over graded results}."""
    sums = {}
    for student in students:
        for item in student['results']:
            if item['state'] == 'done':
                total, count = sums.get(item['exam']['id'], (0, 0))
                sums[item['exam']['id']] = (total + item['score'], count + 1)
    return {key: round(total / count, 1) for key, (total, count) in sums.items()}


# ---------------------------------------------------------------- tabs

def _overview(teacher_id, group, exams) -> dict:
    now = timezone.now()
    live = [dict(exam, code=exam_access_code(exam['id']), when=_date_time(exam['start_at']),
                 type_label=f"برگزاری {exam['exam_type']}" if exam['exam_type'] and not exam['exam_type'].isascii() else 'برگزاری آنلاین',
                 live_url=_hub(exam['id'], 'live'))
            for exam in exams if exam['state'] == 'running']
    upcoming = sorted((exam for exam in exams if exam['state'] == 'scheduled'),
                      key=lambda exam: exam['start_at'] or now)
    upcoming = [dict(exam, when=_date_time(exam['start_at']), manage_url=_hub(exam['id']),
                     preview_url=f"{reverse('core:exam_preview', args=[exam['id']])}?new=1") for exam in upcoming]

    by_id = {exam['id']: exam for exam in exams}
    pending, types = {}, {}
    if exams:
        marks = ', '.join(['%s'] * len(exams))
        for row in erd_rows(
            f"""
            SELECT ea.exam_id, COALESCE(q.type, '') AS type, COUNT(aa.id) AS count
            FROM attempt_answers aa
            JOIN exam_attempts ea ON ea.id = aa.attempt_id
            LEFT JOIN questions q ON q.id = aa.question_id
            WHERE ea.exam_id IN ({marks}) AND COALESCE(aa.needs_manual_grading, false) = true
              AND ea.student_id IN (SELECT student_user_id FROM student_group_members WHERE group_id = %s)
            GROUP BY ea.exam_id, q.type
            """,
            [*by_id, group['id']],
        ):
            exam_id = str(row['exam_id'])
            pending[exam_id] = pending.get(exam_id, 0) + row['count']
            types.setdefault(exam_id, []).append((row['count'], row['type']))
    grading = [{
        'id': exam_id, 'title': by_id[exam_id]['title'], 'count': count, 'url': _hub(exam_id, 'grading'),
        'type_label': QUESTION_TYPE_LABELS.get(max(types[exam_id])[1], 'تشریحی'),
    } for exam_id, count in sorted(pending.items(), key=lambda item: -item[1])]

    events = []
    submitted = {}
    if exams:
        marks = ', '.join(['%s'] * len(exams))
        for row in erd_rows(
            f"""
            SELECT a.exam_id, COUNT(*) AS count, MAX(a.submitted_at) AS last_at
            FROM exam_attempts a
            WHERE a.exam_id IN ({marks}) AND a.submitted_at IS NOT NULL AND COALESCE(a.practice_mode, '') = ''
              AND a.student_id IN (SELECT student_user_id FROM student_group_members WHERE group_id = %s)
            GROUP BY a.exam_id
            """,
            [*by_id, group['id']],
        ):
            submitted[str(row['exam_id'])] = row
    for exam in exams:
        title = exam['title']
        if exam['state'] in ('running', 'finished') and exam['start_at'] and exam['start_at'] <= now:
            events.append(('live', f'آزمون «{title}» آغاز شد.', exam['start_at']))
        if exam['state'] == 'finished' and exam['end_at'] and exam['end_at'] <= now:
            events.append(('checkcircle', f'آزمون «{title}» به پایان رسید.', exam['end_at']))
        published = erd_datetime(exam.get('results_published_at'))
        if published:
            events.append(('award', f'نتایج آزمون «{title}» منتشر شد.', published))
        sent = submitted.get(exam['id'])
        if sent and erd_datetime(sent['last_at']):
            text = (f"آزمون «{title}» برای تصحیح ارسال شد ({fa_digits(pending[exam['id']])} پاسخ)."
                    if pending.get(exam['id']) else f"{fa_digits(sent['count'])} دانشجو پاسخ آزمون «{title}» را ارسال کردند.")
            events.append(('doc', text, erd_datetime(sent['last_at'])))
    events.sort(key=lambda event: event[2], reverse=True)
    activity = [{'icon': icon, 'text': text, 'when': _when_label(at, now)} for icon, text, at in events[:ACTIVITY_LIMIT]]

    return {
        'kpis': {
            'students': int(group.get('students_count') or 0),
            'exams': sum(1 for exam in exams if exam['state'] != 'cancelled'),
            'running': len(live),
            'finished': sum(1 for exam in exams if exam['state'] == 'finished'),
        },
        'live': live,
        'grading': grading,
        'upcoming': upcoming[:UPCOMING_LIMIT],
        'upcoming_total': len(upcoming),
        'activity': activity,
    }


def _students_tab(request, group, exams) -> dict:
    query = (request.GET.get('q') or '').strip()[:100]
    status = request.GET.get('status') if request.GET.get('status') in LEARNING else ''
    everyone = class_students(group, exams)
    rows = everyone
    if query:
        needle = query.lower()
        rows = [row for row in rows if needle in row['name'].lower() or needle in str(row['code']).lower()]
    if status:
        rows = [row for row in rows if row['learning'] == status]
    data = {'rows': rows, 'total': len(everyone), 'query': query, 'status': status,
            'statuses': [(key, label) for key, (label, _tone, _icon) in LEARNING.items()],
            'filtered': bool(query or status)}
    params = {'tab': 'students', 'q': query, 'status': status}
    for index, row in enumerate(rows):
        row['row_no'] = index + 1
        row['url'] = _url(group['id'], **params, student=row['id'])
    selected_id = request.GET.get('student') or ''
    if selected_id:
        selected = next((row for row in everyone if row['id'] == selected_id), None)
        if not selected:
            raise Http404('دانشجو در این کلاس نیست.')
        data['panel'] = _student_panel(request, group, selected, rows, everyone, params)
    return data


def _student_panel(request, group, student, rows, everyone, params) -> dict:
    view = request.GET.get('pview') if request.GET.get('pview') in ('perf', 'chart', 'activity') else 'perf'
    order = [row['id'] for row in rows] if student['id'] in [row['id'] for row in rows] else [row['id'] for row in everyone]
    position = order.index(student['id'])
    neighbour = lambda step: (_url(group['id'], **params, student=order[position + step], pview=view)  # noqa: E731
                              if 0 <= position + step < len(order) else '')
    averages = _class_averages(everyone)
    results = list(reversed(student['results']))  # newest first in the table
    for index, item in enumerate(results):
        item['row_no'] = index + 1
        item['date'] = _date_time(item['exam']['start_at']).split(' – ')[0] if item['exam']['start_at'] else ''
        item['card_url'] = f"{_hub(item['exam']['id'], 'results')}&student={item['attempt_id']}" if item['attempt_id'] else ''
    panel = {
        'student': student, 'view': view, 'results': results,
        'prev_url': neighbour(-1), 'next_url': neighbour(1),
        'close_url': _url(group['id'], **params),
        'tab_urls': {key: _url(group['id'], **params, student=student['id'], pview=key) for key in ('perf', 'chart', 'activity')},
        'report_url': f"{reverse('core:teacher_student_report', args=[student['id']])}?group={group['id']}&print=1",
        'bars': [
            {'label': 'میانگین نمره', 'value': student['average']},
            {'label': 'بهترین نمره', 'value': student['best']},
            {'label': 'ضعیف‌ترین نمره', 'value': student['worst']},
        ],
    }
    for bar in panel['bars']:
        bar['percent'] = round(bar['value'] * 5) if bar['value'] is not None else 0
    if view == 'chart':
        from .teacher_students import _trend_chart

        points = [{'student': item['score'], 'class_avg': averages.get(item['exam']['id']),
                   'short': _date_time(item['exam']['start_at'])[5:10] or item['exam']['title'][:10]}
                  for item in student['results'] if item['state'] == 'done']
        panel['chart'] = _trend_chart(points) if points else None
    if view == 'activity':
        panel['activity'] = _student_activity(group, student)
    return panel


def _student_activity(group, student) -> list:
    """Every attempt of the student on the class's exams: entry, hand-in, minutes, state."""
    rows = erd_rows(
        """
        SELECT e.title, a.started_at, a.submitted_at, COALESCE(a.status, '') AS status
        FROM exam_attempts a JOIN exams e ON e.id = a.exam_id
        WHERE a.student_id = %s AND COALESCE(a.practice_mode, '') = ''
          AND e.id IN (SELECT id FROM exams WHERE course_id = %s
                       UNION SELECT exam_id FROM exam_assignments WHERE group_id = %s)
        ORDER BY a.started_at DESC NULLS LAST
        """,
        [student['id'], group.get('course_id'), group['id']],
    )
    items = []
    for row in rows:
        started, sent = erd_datetime(row['started_at']), erd_datetime(row['submitted_at'])
        minutes = round((sent - started).total_seconds() / 60) if started and sent and sent >= started else None
        items.append({
            'title': row['title'], 'started': _date_time(started), 'submitted': _date_time(sent),
            'minutes': minutes,
            'state_label': 'ارسال شده' if row['status'] in DONE else 'در حال انجام' if row['status'] == 'in_progress' else 'ناتمام',
            'state_tone': 'green' if row['status'] in DONE else 'blue' if row['status'] == 'in_progress' else 'amber',
        })
    return items


def _exams_tab(request, teacher_id, group) -> dict:
    filters = exam_list.read_filters(request.GET)
    filters.update(course='', group='', date='', sort='newest', view='table', class_group=(group.get('course_id'), group['id']))
    data = _teacher_exam_list(teacher_id, filters, request.GET.get('page'))
    counts = {tab['key']: tab['count'] for tab in data['tabs']}
    for row in data['rows']:
        state = row['state']
        pill = 'finished_pending' if state == 'finished' and row.get('pending_reviews') else state
        row['class_pill'] = EXAM_PILLS.get(pill, EXAM_PILLS['draft'])
        if row['primary'].get('label') == 'نظارت زنده':
            row['primary']['label'] = 'پایش زنده'
        row['primary_icon'] = 'edit' if state == 'finished' and row.get('pending_reviews') else EXAM_MAIN_ICONS.get(state, 'info')
        row['when'] = _date_time(row['start_at'])
        row['results_url'] = _hub(row['id'], 'results') if state == 'finished' else row['report_url']
    data['chips'] = [{'key': key, 'label': label, 'icon': icon, 'count': counts.get(key, 0), 'active': filters['status'] == key,
                      'url': _url(group['id'], tab='exams', status='' if key == 'all' else key, q=filters['query'])}
                     for key, label, icon in EXAM_CHIPS]
    data['state_options'] = EXAM_STATE_OPTIONS
    return data


# ---------------------------------------------------------------- page

def class_context(request, teacher_id, group_id) -> dict:
    """Context of the class page (merged into the teacher console's); 404 for a group that is not the teacher's."""
    group = _teacher_selected_course(_teacher_courses_rows(teacher_id), group_id)
    if not group:
        raise Http404('کلاس پیدا نشد.')
    group = dict(group, id=str(group['id']))
    tab = request.GET.get('tab') if request.GET.get('tab') in TAB_KEYS else 'overview'
    exams = class_exams(teacher_id, group)
    cls = {
        'group': group, 'id': group['id'], 'title': _group_title(group), 'term': _term_label(group),
        'tab': tab, 'tabs': [{'key': key, 'label': label, 'icon': icon, 'url': _url(group['id'], tab=key)} for key, label, icon in TABS],
        'urls': {'overview': _url(group['id']), 'students': _url(group['id'], tab='students'),
                 'exams': _url(group['id'], tab='exams'), 'list': reverse('core:teacher_courses'),
                 'new_exam': reverse('core:teacher_exam_create')},
        'permissions': PERMISSIONS,
    }
    if tab == 'overview':
        cls['overview'] = _overview(teacher_id, group, exams)
    elif tab == 'students':
        cls['students'] = _students_tab(request, group, exams)
    else:
        cls['exams'] = _exams_tab(request, teacher_id, group)
    return {'cls': cls, 'selected_course': group, 'selected_group_id': group['id']}


def export_students(teacher_id, group_id) -> HttpResponse:
    """Excel file of the class's students (the same figures as the «دانشجویان» tab)."""
    from openpyxl import Workbook
    from openpyxl.styles import Font

    group = _teacher_selected_course(_teacher_courses_rows(teacher_id), group_id)
    if not group:
        raise Http404('کلاس پیدا نشد.')
    group = dict(group, id=str(group['id']))
    students = class_students(group, class_exams(teacher_id, group))
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = 'دانشجویان'
    sheet.sheet_view.rightToLeft = True
    sheet.append(['نام و نام خانوادگی', 'شماره دانشجویی', 'آزمون‌های شرکت‌کرده', 'آزمون‌های برگزارشده', 'غیبت',
                  'نمره آخرین آزمون (از ۲۰)', 'میانگین (از ۲۰)', 'وضعیت یادگیری'])
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    for row in students:
        last = row['last']
        last_text = '' if not last else last['score'] if last['state'] == 'done' else last['state_label']
        name = str(row['name'])
        sheet.append([f"'{name}" if name[:1] in '=+-@' else name, str(row['code']), row['taken'], row['total'],
                      row['absent'], last_text, row['average'] if row['average'] is not None else '', row['learning_label']])
    for column, width in zip('ABCDEFGH', (26, 16, 14, 14, 8, 18, 14, 20)):
        sheet.column_dimensions[column].width = width
    buffer = BytesIO()
    workbook.save(buffer)
    response = HttpResponse(buffer.getvalue(),
                            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    name = re.sub(r'[^A-Za-z0-9_-]', '', str(group['group_code'] or '')) or 'students'
    response['Content-Disposition'] = f'attachment; filename="class-{name}.xlsx"'
    return response

