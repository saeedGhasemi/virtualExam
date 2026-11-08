"""«گزارش آزمون»: a read-only, printable report of one exam for its teacher and for academic managers / admins.

Tab «مشخصات آزمون» lists everything the 7-step exam wizard saved, grouped by step, as one A4 sheet, with every
question in full (stem, image, options / items, answer space) and its answer key, which can be hidden before
printing (e.g. for a teacher who holds the exam on paper). Tab «شرکت‌کنندگان و نتایج» lists every student's
attempts (score, start / end, grader) and final score with pass / fail, plus absentees. Tab «تحلیل سوالات» shows, per
question, how often each option was chosen (or how many answers were right / partial / wrong). Tab «حضور و غیاب» marks every
student who should have sat the exam as present / entered without sending / absent. Every tab prints on its own.
"""
import re
from datetime import timedelta

from django.http import Http404
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.utils.html import strip_tags

from . import question_kinds
from .views import (
    EXAM_STAFF_ROLE_LABELS,
    RESULT_OPTION_LETTERS,
    PRACTICE_EXAM_MODE,
    TRAINING_EXAM_MODE,
    _essay_view,
    _exam_score_scale,
    _question_stem_html,
    _sx_fill_blank_segments,
    _sx_float,
    _sx_json,
    _sx_matching_display_columns,
    _sx_ordering_display_items,
    _sx_question_media,
    _sx_question_options,
    _sx_attempt_ends_at,
    _sx_exam_rules,
    _sx_percent,
    _with_exam_grading_rules,
    _sx_result_status,
    _sx_result_values,
    _erd_exam_in_manager_scope,
    _exam_audience_student_ids,
    _sx_type_label,
    erd_datetime,
    erd_has_column,
    erd_role_required,
    erd_row,
    erd_rows,
    exam_access_code,
)

EXAM_MODE_LABELS = {'standard': 'آزمون عادی', 'practice': 'آزمون آزمایشی', 'training': 'آزمون تمرینی'}
DISPLAY_MODE_LABELS = {'after_publish': 'پس از انتشار نتایج', 'immediate': 'بلافاصله', 'manual': 'نمایش داده نشود'}
SCORE_DISPLAY_LABELS = {**DISPLAY_MODE_LABELS, 'manual': 'دستی (با انتشار نتایج توسط استاد)'}
GRADING_TEMPLATE_LABELS = {'detailed_score': 'کارنامه‌ی تفصیلی (نمره‌ی هر سؤال)', 'total_score': 'فقط نمره‌ی کل'}
GRADING_METHOD_LABELS = {'weighted_by_type': 'نمره‌دهی وزنی بر اساس نوع سوال', 'uniform': 'یکسان برای همه سوالات'}
RUBRIC_LABELS = {'': 'بدون روبریک', 'analytic_multilevel': 'روبریک تحلیلی چندسطحی', 'holistic': 'روبریک کل‌نگر'}
RESULTS_DEADLINE_LABELS = {
    '3_days_after_end': '۳ روز پس از تاریخ پایان آزمون', '7_days_after_end': '۷ روز پس از تاریخ پایان آزمون',
    'manual': 'دستی توسط استاد',
}
CORRECTION_MODE_LABELS = {'manual': 'دستی (توسط مدرس)', 'auto_then_manual': 'خودکار پس از تصحیح کامل'}
SECURITY_LEVEL_LABELS = {'low': 'کم', 'medium': 'متوسط', 'high': 'زیاد'}
EXECUTION_MODE_LABELS = {'web': 'وب (هر دستگاه)', 'in_app': 'در دسکتاپ', 'lockdown_browser': 'مرورگر متمرکز'}
INTERNET_POLICY_LABELS = {'resume_from_last_save': 'ادامه از آخرین ذخیره', 'pause': 'توقف آزمون', 'none': 'بدون واکنش خاص'}
PUBLISH_MODE_LABELS = {
    'draft': 'پیش‌نویس', 'submit': 'ارسال برای تأیید', 'immediate': 'انتشار فوری', 'scheduled': 'زمان‌بندی انتشار',
}
APPROVAL_LABELS = {'approved': 'تأیید شده', 'pending': 'در انتظار تأیید', 'rejected': 'رد شده'}
DIFFICULTY_LABELS = {'easy': 'آسان', 'medium': 'متوسط', 'hard': 'سخت'}
OBJECTIVE_TYPES = {'single', 'single_choice', 'multiple_choice', 'multi', 'true_false', 'matching', 'ordering', 'numeric'}


def _report_status(exam, now) -> tuple:
    """(key, label) of the exam's state, as the exam lists show it."""
    start_at, end_at = exam.get('start_at'), exam.get('end_at')
    if exam.get('is_cancelled'):
        return 'cancelled', 'لغو شده'
    if not exam.get('is_published'):
        return {
            'pending_approval': ('pending', 'در انتظار تأیید'), 'approved': ('scheduled', 'زمان‌بندی انتشار'),
        }.get(exam.get('lifecycle_status'), ('draft', 'پیش‌نویس'))
    if start_at and start_at <= now and (not end_at or now <= end_at):
        return 'running', 'در حال برگزاری'
    if end_at and end_at < now:
        return 'finished', 'پایان یافته'
    return 'scheduled', 'برنامه‌ریزی شده'


def _number(value):
    """2.0 → «2», 2.5 → «2.5», None → None."""
    if value is None or value == '':
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return value
    return int(number) if number.is_integer() else round(number, 2)


def _flag(exam, column, label, hint=''):
    return {'label': label, 'on': exam.get(column) in (True, 1, '1', 't', 'true'), 'hint': hint, 'known': column in exam}


def _passing(exam, scale):
    """(label, score on the exam's scale) of «نمره قبولی», read as _sx_result_status reads it."""
    if exam.get('passing_percent') is not None:
        percent = _sx_float(exam['passing_percent'], 0)
        return f'{_number(percent)}٪', _number(round(percent * scale / 100, 2))
    raw = _sx_float(exam.get('passing_score'), 60)
    if raw <= 20:  # a score out of 20
        return f'{_number(raw)} از ۲۰', _number(round(raw * scale / 20, 2))
    return f'{_number(raw)}٪', _number(round(raw * scale / 100, 2))


def _letter(number):
    return RESULT_OPTION_LETTERS[number] if number < len(RESULT_OPTION_LETTERS) else str(number + 1)


_PERSIAN_LETTERS = re.compile('[؀-ۿ]')


def _is_ltr(text):
    """A text with Latin letters and no Persian / Arabic ones (an English question) is shown left to right, Latin digits."""
    return bool(re.search('[A-Za-z]', text or '')) and not _PERSIAN_LETTERS.search(text or '')


def _plain(text):
    return re.sub(r'\s+', ' ', strip_tags(str(text or ''))).strip()


def _report_rubric(row):
    return [
        {'criterion': r.get('criterion'), 'description': r.get('description') or '', 'points': _number(r.get('points'))}
        for r in (_sx_json(row.get('rubric'), []) or []) if isinstance(r, dict) and r.get('criterion')
    ]


def _report_question(index, row):
    """One question as the report sheet prints it: stem, media, what the student sees, and the answer key."""
    kind = row.get('type') or 'single'
    settings_data = _sx_json(row.get('scoring_settings'), {}) or {}
    settings_data = settings_data if isinstance(settings_data, dict) else {}
    media = _sx_question_media(row.get('question_media'))
    points = float(row.get('points') or 0)
    item = {
        'index': index, 'type': kind, 'type_label': _sx_type_label(kind),
        'difficulty_label': DIFFICULTY_LABELS.get(row.get('difficulty') or 'medium', 'متوسط'),
        'points': _number(points), 'points_value': points,
        'text': _plain(row.get('text')) or '-', 'stem_html': _question_stem_html(settings_data),
        'image': media.get('image'), 'image_alt': media.get('image_alt') or '',
        'has_audio': bool(media.get('audio')), 'has_video': bool(media.get('video')),
        'options': [], 'left': [], 'right': [], 'items': [], 'segments': [], 'key_lines': [], 'rubric': [],
        'answer_lines': 0, 'matrix': None, 'markers': [], 'unit': '', 'instructions': '',
        'explanation': _plain(row.get('explanation')),
    }
    item['ltr'] = _is_ltr(item['text'])
    if kind in ('single', 'single_choice', 'multiple_choice', 'multi', 'true_false'):
        key = set(_sx_result_values(row.get('correct_answer')))
        item['options'] = [
            {**option, 'letter': _letter(number), 'correct': option['value'] in key, 'ltr': _is_ltr(option['label'])}
            for number, option in enumerate(_sx_question_options(row.get('options'), kind))
        ]
        item['multi'] = kind == 'multi'
    elif kind == 'fill_blank':
        item['stem_html'] = ''  # the plain stem with numbered blanks prints better than the rich one with [n] markers
        item['segments'] = _sx_fill_blank_segments(row.get('text') or '')
        blanks = [b for b in (_sx_json(row.get('accepted_answers'), []) or []) if isinstance(b, dict) and b.get('answers')]
        if not blanks:
            legacy = _sx_json(row.get('correct_answer'), row.get('correct_answer'))
            blanks = [{'answers': [part]} for part in str(legacy or '').split('|') if part]
        item['key_lines'] = [f"جای خالی {n}: {' / '.join(str(a) for a in b['answers'])}" for n, b in enumerate(blanks, start=1)]
    elif kind == 'short_answer':
        item['answer_lines'] = 2
        accepted = [a for a in (_sx_json(row.get('accepted_answers'), []) or []) if isinstance(a, dict) and a.get('answer')]
        item['key_lines'] = [
            str(a['answer']) + (f" ({_number(a.get('points'))}٪ نمره)" if _sx_float(a.get('points'), 100) < 100 else '')
            for a in accepted
        ]
    elif kind in ('essay', 'descriptive'):
        essay = _essay_view(settings_data)
        item['answer_lines'] = 8
        item['instructions'] = essay['student_instructions']
        if essay['sample_answer_text']:
            item['key_lines'] = [f"پاسخ نمونه: {essay['sample_answer_text']}"]
        item['rubric'] = _report_rubric(row)
    elif kind == 'matching':
        left, right = _sx_matching_display_columns(row.get('matching_pairs'), row.get('id'), row.get('scoring_settings'))
        item['left'] = [{**entry, 'number': number} for number, entry in enumerate(left, start=1)]
        item['right'] = [{**entry, 'letter': _letter(number)} for number, entry in enumerate(right)]
        letters = {_plain(entry['label']): entry['letter'] for entry in item['right']}
        pairs = [p for p in (_sx_json(row.get('matching_pairs'), []) or []) if isinstance(p, dict) and p.get('left') and p.get('right')]
        item['key_lines'] = [
            f"{n}. {_plain(p['left'])} ← {letters.get(_plain(p['right']), '')}) {_plain(p['right'])}"
            for n, p in enumerate(pairs, start=1)
        ]
    elif kind == 'ordering':
        entries = _sx_ordering_display_items(row.get('ordering_items'), row.get('id'))
        item['items'] = [{**entry, 'letter': _letter(number)} for number, entry in enumerate(entries)]
        ordered = sorted(item['items'], key=lambda e: int(e['value']) if str(e['value']).isdigit() else 0)
        if ordered:
            item['key_lines'] = ['ترتیب صحیح: ' + ' ← '.join(f"{e['letter']}) {_plain(e['label'])}" for e in ordered)]
    elif kind == 'numeric':
        numeric = settings_data.get('numeric') or {}
        item['unit'] = numeric.get('unit') or ''
        item['answer_lines'] = 1
        value = numeric.get('value')
        if value in (None, ''):
            value = _sx_json(row.get('correct_answer'), row.get('correct_answer'))
        if value not in (None, ''):
            tolerance = _sx_float(numeric.get('tolerance'), 0)
            suffix = '٪' if numeric.get('tolerance_mode') == 'percent' else ''
            item['key_lines'] = [f"{_number(value)} {item['unit']}".strip() + (f' (± {_number(tolerance)}{suffix})' if tolerance else '')]
    elif kind == 'matrix':
        matrix = settings_data.get('matrix') or {}
        columns = [c for c in matrix.get('columns') or [] if isinstance(c, dict)]
        rows = [r for r in (_sx_json(row.get('options'), []) or []) if isinstance(r, dict)]
        item['matrix'] = {
            'columns': columns,
            'rows': [
                {'text': r.get('text') or '', 'cells': [str(c.get('id')) in {str(x) for x in r.get('correct') or []} for c in columns]}
                for r in rows
            ],
        }
    elif kind == 'image_label':
        markers = [m for m in (_sx_json(row.get('accepted_answers'), []) or []) if isinstance(m, dict) and 'marker' in m]
        item['markers'] = [
            {'marker': m.get('marker'), 'x': _sx_float(m.get('lx', m.get('x')), 0), 'y': _sx_float(m.get('ly', m.get('y')), 0)}
            for m in markers
        ]
        item['key_lines'] = [
            f"{m.get('marker')}: {m.get('answer') or '-'}" + (f" (یا: {'، '.join(m['synonyms'])})" if m.get('synonyms') else '')
            for m in markers
        ]
    elif kind == 'hotspot':
        regions = [r for r in (_sx_json(row.get('accepted_answers'), []) or []) if isinstance(r, dict) and r.get('shape')]
        item['max_clicks'] = (settings_data.get('hotspot') or {}).get('max_clicks') or 1
        if regions:
            item['key_lines'] = ['نواحی صحیح: ' + '، '.join(str(r.get('name') or question_kinds.region_label(r)) for r in regions)]
    elif kind == 'media_response':
        item['rubric'] = _report_rubric(row)
        item['answer_lines'] = 4
        transcript = (settings_data.get('media_response') or {}).get('transcript')
        if transcript:
            item['key_lines'] = [f'متن فایل: {transcript}']
    return item


def _report_questions(exam_id, grading_rules=None):
    optional = ', '.join(
        f'q.{column}' if erd_has_column('questions', column) else f'NULL AS {column}'
        for column in ('ordering_items', 'matching_pairs', 'question_media', 'accepted_answers', 'scoring_settings', 'rubric', 'explanation', 'tags', 'subject')
    )
    rows = erd_rows(
        f"""
        SELECT q.id, q.text, COALESCE(q.type, 'single') AS type, q.difficulty, q.options, q.correct_answer, {optional},
               COALESCE(eq.points, q.default_points, 1) AS points
        FROM exam_questions eq JOIN questions q ON q.id = eq.question_id
        WHERE eq.exam_id = %s ORDER BY eq.order_index NULLS LAST, eq.id
        """,
        [exam_id],
    )
    items = []
    for index, row in enumerate(rows, start=1):
        item = _report_question(index, row)
        item['id'] = str(row['id'])
        item['tags'] = [t.strip() for t in re.split('[,،]', str(row.get('tags') or '')) if t.strip()]
        if row.get('subject') and str(row['subject']).strip() not in item['tags']:
            item['tags'].insert(0, str(row['subject']).strip())
        graded_as = _with_exam_grading_rules(row, grading_rules or {})  # the exam's «نمره منفی» as grading applies it
        settings_data = _sx_json(graded_as.get('scoring_settings'), {}) or {}
        settings_data = settings_data if isinstance(settings_data, dict) else {}
        negative = abs(_sx_float(settings_data.get('negative_value'), 0)) if settings_data.get('negative_marking') else 0
        item['negative'] = _number(round(item['points_value'] * negative, 2))
        items.append(item)
    _attach_answer_stats(exam_id, items)
    return items


# Each student's last submitted attempt, so the counts match «شرکت کننده» (students, not attempts).
_LATEST_ATTEMPTS = '''
    WITH latest AS (
        SELECT DISTINCT ON (student_id) id FROM exam_attempts
        WHERE exam_id = %s AND submitted_at IS NOT NULL
        ORDER BY student_id, submitted_at DESC
    )
'''
CHOICE_KINDS = {'single', 'single_choice', 'multiple_choice', 'multi', 'true_false'}


def _attach_answer_stats(exam_id, items):
    """«تحلیل سوالات»: each student's answer (last submitted attempt) to each question, counted.

    Choice questions get the share of answers that picked each option (single choice adds up to 100%; a
    multi-answer question is out of its respondents, so it can exceed 100%). Other types get right / partial /
    wrong / waiting-for-the-teacher counts from the grading."""
    rows = erd_rows(
        _LATEST_ATTEMPTS + """
        SELECT aa.question_id, aa.answer, aa.is_correct, aa.points_awarded, aa.needs_manual_grading, aa.graded_by,
               COALESCE(eq.points, q.default_points, 1) AS max_points
        FROM attempt_answers aa
        JOIN exam_attempts ea ON ea.id = aa.attempt_id
        JOIN exam_questions eq ON eq.exam_id = ea.exam_id AND eq.question_id = aa.question_id
        JOIN questions q ON q.id = aa.question_id
        WHERE ea.id IN (SELECT id FROM latest)
        """,
        [exam_id],
    )
    submitted = len(erd_rows(_LATEST_ATTEMPTS + 'SELECT 1 FROM latest', [exam_id]))
    by_question = {}
    for row in rows:
        by_question.setdefault(str(row['question_id']), []).append(row)
    for item in items:
        answers = by_question.get(item['id'], [])
        given = [(row, _sx_result_values(row.get('answer'))) for row in answers]
        given = [(row, values) for row, values in given if values]
        item['stats'] = {'submitted': submitted, 'answered': len(given), 'unanswered': max(submitted - len(given), 0), 'bars': []}
        if item['type'] in CHOICE_KINDS and item['options']:
            for option in item['options']:
                keys = {option['value'], option['label']}
                count = sum(1 for _row, values in given if keys & set(values))
                option['count'] = count
                option['percent'] = round(count * 100 / len(given), 2) if given else 0
            correct = sum(1 for row, _values in given if row.get('is_correct') in (True, 1, '1', 't', 'true'))
        else:
            full = partial = wrong = waiting = 0
            for row, _values in given:
                points, max_points = _sx_float(row.get('points_awarded'), 0), _sx_float(row.get('max_points'), 0)
                if row.get('needs_manual_grading') and not row.get('graded_by') and not points:
                    waiting += 1
                elif row.get('is_correct') in (True, 1, '1', 't', 'true') or (max_points and points >= max_points):
                    full += 1
                elif points > 0:
                    partial += 1
                else:
                    wrong += 1
            total = len(given) or 1
            item['stats']['bars'] = [
                {'label': label, 'count': count, 'percent': round(count * 100 / total, 2) if given else 0, 'tone': tone}
                for label, count, tone in (('پاسخ کامل (تمام نمره)', full, 'correct'), ('پاسخ ناقص (نمره‌ی جزئی)', partial, 'partial'),
                                           ('پاسخ نادرست', wrong, 'wrong'), ('در انتظار تصحیح استاد', waiting, 'waiting'))
                if count or tone != 'waiting'
            ]
            correct = full
        item['stats']['correct_percent'] = round(correct * 100 / len(given), 2) if given else 0


def _report_participants(exam, audience_ids, exam_end_at=None):
    """«شرکت‌کنندگان و نتایج»: one row per student with their attempts and final (best graded) score."""
    exam_id = exam['id']
    scale = _exam_score_scale(exam)
    attempts = erd_rows(
        """
        SELECT ea.id, ea.student_id, ea.started_at, ea.submitted_at, ea.score, ea.max_score, ea.is_graded, ea.status,
               COALESCE(p.full_name, '-') AS name, COALESCE(p.avatar_url, '') AS avatar_url,
               COALESCE(sp.student_number, '') AS student_number
        FROM exam_attempts ea
        LEFT JOIN profiles p ON p.id = ea.student_id
        LEFT JOIN student_profiles sp ON sp.user_id = ea.student_id
        WHERE ea.exam_id = %s
        ORDER BY ea.started_at NULLS LAST, ea.id
        """,
        [exam_id],
    )
    graders = {}
    for row in erd_rows(
        """
        SELECT DISTINCT aa.attempt_id, COALESCE(p.full_name, '-') AS name
        FROM attempt_answers aa JOIN exam_attempts ea ON ea.id = aa.attempt_id
        LEFT JOIN profiles p ON p.id = aa.graded_by
        WHERE ea.exam_id = %s AND aa.graded_by IS NOT NULL
        """,
        [exam_id],
    ):
        graders.setdefault(str(row['attempt_id']), []).append(row['name'])
    pending_manual = {str(row['attempt_id']) for row in erd_rows(
        """
        SELECT DISTINCT aa.attempt_id FROM attempt_answers aa JOIN exam_attempts ea ON ea.id = aa.attempt_id
        WHERE ea.exam_id = %s AND COALESCE(aa.needs_manual_grading, false) AND aa.graded_by IS NULL
        """,
        [exam_id],
    )}

    now = timezone.now()
    students = {}
    for attempt in attempts:
        student_id = str(attempt['student_id'])
        student = students.setdefault(student_id, {
            'id': student_id, 'name': attempt['name'], 'avatar_url': attempt['avatar_url'],
            'student_number': attempt['student_number'], 'attempts': [], 'absent': False,
        })
        graded = bool(attempt.get('is_graded')) and attempt.get('score') is not None and bool(attempt.get('submitted_at'))
        max_score = _sx_float(attempt.get('max_score'), 0)
        scaled = round(_sx_float(attempt.get('score'), 0) * scale / max_score, 2) if graded and max_score else (0 if graded else None)
        if not attempt.get('submitted_at'):
            started_at = erd_datetime(attempt.get('started_at'))
            running = started_at and attempt.get('status') == 'in_progress' and \
                _sx_attempt_ends_at(started_at, exam.get('duration_minutes'), exam_end_at) > now
            state = 'در حال پاسخ‌گویی' if running else 'ناتمام (بدون ارسال پاسخ)'
        elif not graded:
            state = 'در انتظار تصحیح'
        else:
            state = ''
        names = graders.get(str(attempt['id'])) or []
        if names:
            grader = 'مصحح: ' + '، '.join(names)
        elif str(attempt['id']) in pending_manual:
            grader = 'در انتظار تصحیح دستی'
        else:
            grader = 'مصحح سیستمی' if graded else ''
        student['attempts'].append({
            'started_at': erd_datetime(attempt.get('started_at')), 'submitted_at': erd_datetime(attempt.get('submitted_at')),
            'graded': graded, 'score': _number(scaled), 'score_value': scaled, 'state': state,
            'grader': grader if attempt.get('submitted_at') else '',
            'percent': _sx_percent(attempt.get('score'), max_score) if graded and max_score else 0,
            'raw': attempt,
        })

    for student in students.values():
        graded = [a for a in student['attempts'] if a['graded']]
        best = max(graded, key=lambda a: a['score_value']) if graded else None
        if best:
            label, tone, _ = _sx_result_status({**best['raw'], 'percent': best['percent'],
                                                'passing_percent': exam.get('passing_percent'),
                                                'passing_score': exam.get('passing_score') if exam.get('passing_score') is not None else 60})
            student.update(final=best['score'], final_value=best['score_value'], result=label,
                           status='passed' if tone == 'green' else 'failed')
        else:
            pending = any(a['submitted_at'] for a in student['attempts'])
            student.update(final=None, final_value=None, result='در انتظار تصحیح' if pending else 'ناتمام', status='pending')
        for attempt in student['attempts']:
            attempt.pop('raw', None)

    absent_ids = [sid for sid in audience_ids if sid not in students]
    if absent_ids:
        placeholders = ','.join(['%s'] * len(absent_ids))
        for row in erd_rows(
            f"""
            SELECT p.id, COALESCE(p.full_name, '-') AS name, COALESCE(p.avatar_url, '') AS avatar_url,
                   COALESCE(sp.student_number, '') AS student_number
            FROM profiles p LEFT JOIN student_profiles sp ON sp.user_id = p.id
            WHERE p.id IN ({placeholders})
            """,
            absent_ids,
        ):
            students[str(row['id'])] = {
                'id': str(row['id']), 'name': row['name'], 'avatar_url': row['avatar_url'],
                'student_number': row['student_number'], 'attempts': [], 'absent': True,
                'final': None, 'final_value': None, 'result': 'غایب', 'status': 'absent',
            }

    rows = sorted(students.values(), key=lambda s: (s['absent'], s['name']))
    audience = set(audience_ids)
    for student in rows:  # «حضور و غیاب»: present = sent their answers, incomplete = entered but never sent them
        started = [a['started_at'] for a in student['attempts'] if a['started_at']]
        student['entered_at'] = min(started) if started else None
        student['in_audience'] = student['id'] in audience
        student['attendance'] = ('absent' if student['absent']
                                 else 'present' if any(a['submitted_at'] for a in student['attempts']) else 'incomplete')
    session_count = max([len(s['attempts']) for s in rows] + [1])
    for student in rows:
        student['cells'] = student['attempts'] + [None] * (session_count - len(student['attempts']))
    finals = [s['final_value'] for s in rows if s['final_value'] is not None]
    participants = [s for s in rows if not s['absent']]
    passing_score = _passing(exam, scale)[1]
    return {
        'rows': rows,
        'sessions': list(range(1, session_count + 1)),
        'wide': session_count > 3,  # more attempts than fit as columns: one wrapping «نشست‌ها» cell instead
        'scale': _number(scale),
        'average': _number(round(sum(finals) / len(finals), 2)) if finals else None,
        'passing_score': passing_score,
        'connected': len(participants),
        'submitted': sum(1 for s in participants if any(a['submitted_at'] for a in s['attempts'])),
        'absent': sum(1 for s in rows if s['absent']),
        'passed': sum(1 for s in rows if s['status'] == 'passed'),
        'failed': sum(1 for s in rows if s['status'] == 'failed'),
        'pending': sum(1 for s in rows if s['status'] == 'pending'),
        'highest': _number(max(finals)) if finals else None,
        'attendance': _attendance_summary(rows),
        'lowest': _number(min(finals)) if finals else None,
    }


def _attendance_summary(rows):
    counts = {key: sum(1 for s in rows if s['attendance'] == key) for key in ('present', 'incomplete', 'absent')}
    total = len(rows)
    share = {key: round(count * 100 / total, 1) if total else 0 for key, count in counts.items()}
    return {
        'total': total, **counts,
        'present_percent': _number(share['present']),
        'outside': sum(1 for s in rows if not s['in_audience']),
        # the ring: present (green) → incomplete (amber) → absent (red), as cumulative percentages
        'ring_present': share['present'], 'ring_incomplete': round(share['present'] + share['incomplete'], 1),
    }

def _exam_report_context(exam, back_url, role):
    exam_id = exam['id']
    for column in ('start_at', 'end_at', 'registration_start_at', 'registration_end_at', 'last_entry_at',
                   'scheduled_publish_at', 'approved_at', 'created_at', 'updated_at', 'results_published_at'):
        exam[column] = erd_datetime(exam.get(column))
    if exam['start_at'] and not exam['end_at'] and exam.get('duration_minutes'):
        exam['end_at'] = exam['start_at'] + timedelta(minutes=int(exam['duration_minutes']))
    status_key, status_label = _report_status(exam, timezone.now())

    term = erd_row('SELECT label FROM academic_terms WHERE year = %s AND semester = %s LIMIT 1',
                   [exam.get('academic_year') or '', exam.get('semester') or '']) if exam.get('academic_year') else None
    term_label = (term or {}).get('label') or ' / '.join(str(v) for v in (exam.get('academic_year'), exam.get('semester')) if v)

    # What the system really applies: the wizard's settings only when it saved them (settings_enforced), else defaults.
    rules = _sx_exam_rules(exam_id)
    enforced = rules['settings_enforced']
    grading_rules = {key: exam.get(key) for key in ('negative_marking', 'negative_factor', 'allow_partial')} if enforced else {}
    for column in ('registration_start_at', 'registration_end_at'):
        exam[column] = erd_datetime(rules.get(column))
    questions = _report_questions(exam_id, grading_rules)
    type_rows, total_points = {}, 0
    for question in questions:
        total_points += question['points_value']
        row = type_rows.setdefault(question['type_label'], {'label': question['type_label'], 'count': 0, 'points': 0})
        row['count'] += 1
        row['points'] += question['points_value']
    for row in type_rows.values():
        row['points'] = _number(row['points'])
    objective_count = sum(1 for q in questions if q.get('type') in OBJECTIVE_TYPES)

    groups = erd_rows(
        """
        SELECT COALESCE(c.title, sg.course_name, '-') AS course, sg.group_code, COALESCE(tp.full_name, '-') AS teacher,
               (SELECT COUNT(*) FROM student_group_members m WHERE m.group_id = sg.id) AS members
        FROM exam_assignments ea
        JOIN student_groups sg ON sg.id = ea.group_id
        LEFT JOIN courses c ON c.id = sg.course_id
        LEFT JOIN profiles tp ON tp.id = sg.teacher_id
        WHERE ea.exam_id = %s
        ORDER BY course, sg.group_code
        """,
        [exam_id],
    )
    individual_count = len(erd_rows(
        'SELECT 1 FROM exam_assignments WHERE exam_id = %s AND student_profile_id IS NOT NULL', [exam_id]))
    excluded_count = len(erd_rows('SELECT 1 FROM exam_assignment_exclusions WHERE exam_id = %s', [exam_id]))
    staff = erd_rows(
        """
        SELECT COALESCE(p.full_name, '-') AS name, es.role
        FROM exam_staff es LEFT JOIN profiles p ON p.id = es.teacher_id
        WHERE es.exam_id = %s ORDER BY es.role, name
        """,
        [exam_id],
    )
    for person in staff:
        person['role_label'] = EXAM_STAFF_ROLE_LABELS.get(person['role'], person['role'] or '-')

    audience_ids = _exam_audience_student_ids(exam_id)
    scale = _exam_score_scale(exam)
    tags = [tag.strip() for tag in re.split('[,،]', exam.get('tags') or '') if tag.strip()]
    max_attempts = rules['max_attempts']
    # Results: practice / training exams release score, key and explanations on grading (see _exam_result_visibility).
    instant = exam.get('exam_mode') in (PRACTICE_EXAM_MODE, TRAINING_EXAM_MODE)
    score_mode = 'immediate' if instant else (exam.get('score_display_mode') or ('immediate' if exam.get('show_results_immediately') else 'after_publish'))
    answer_mode = 'immediate' if instant else (exam.get('correct_answer_display_mode') or 'after_publish')
    explain_mode = 'immediate' if instant else (exam.get('explanation_display_mode') or 'after_publish')
    autosave_interval = rules['autosave_interval_seconds']
    penalty = _number(exam.get('negative_factor')) if grading_rules.get('negative_marking') in (True, 1) and _sx_float(exam.get('negative_factor'), 0) else 0

    return {
        'title': f"گزارش آزمون {exam['title']}",
        'exam': exam,
        'exam_code': exam_access_code(exam_id),
        'role': role,
        'back_url': back_url,
        'status_key': status_key,
        'status_label': status_label,
        'printed_at': timezone.now(),
        'term_label': term_label,
        'tags': tags,
        'settings_enforced': enforced,
        'exam_mode_label': EXAM_MODE_LABELS.get(exam.get('exam_mode') or 'standard', exam.get('exam_mode')),
        'grading_template_label': GRADING_TEMPLATE_LABELS.get(exam.get('grading_template') or 'detailed_score') if enforced else None,
        'max_attempts_label': 'نامحدود' if max_attempts == 0 else (max_attempts or 1),
        'score_mode': score_mode,
        'display_modes': [
            ('نمایش نمره', SCORE_DISPLAY_LABELS.get(score_mode, SCORE_DISPLAY_LABELS['after_publish'])),
            ('نمایش پاسخ صحیح', DISPLAY_MODE_LABELS.get(answer_mode, DISPLAY_MODE_LABELS['after_publish'])),
            ('نمایش توضیح پاسخ', DISPLAY_MODE_LABELS.get(explain_mode, DISPLAY_MODE_LABELS['after_publish'])),
        ],
        'rules': [
            _flag(rules, 'review_answers_enabled', 'امکان بازگشت به سوال قبلی'),
            _flag(rules, 'allow_answer_changes', 'امکان تغییر پاسخ'),
            _flag(rules, 'one_question_per_page', 'نمایش یک سوال در هر صفحه'),
            _flag(rules, 'show_question_list', 'نمایش فهرست سوالات'),
            _flag(rules, 'allow_flagging_questions', 'امکان علامت‌گذاری سوال'),
            _flag(rules, 'auto_submit_on_time_end', 'ارسال خودکار در پایان زمان'),
            _flag(rules, 'show_instructions_before_start', 'نمایش دستورالعمل پیش از شروع'),
        ],
        'questions': questions,
        'type_rows': list(type_rows.values()),
        'question_total_points': _number(total_points),
        'objective_count': objective_count,
        'subjective_count': len(questions) - objective_count,
        'groups': groups,
        'individual_count': individual_count,
        'excluded_count': excluded_count,
        'audience_count': len(audience_ids),
        'participants': _report_participants(exam, audience_ids, rules.get('end_at') or exam.get('end_at')),
        'results_published_at': erd_datetime(exam.get('results_published_at')),
        'penalty': penalty,
        'staff': staff,
        'total_score': _number(exam.get('total_score')) if _sx_float(exam.get('total_score'), 0) > 0 else None,
        'score_scale': _number(scale),
        'passing_label': _passing(exam, scale)[0],
        'grading_method_label': GRADING_METHOD_LABELS.get(exam.get('grading_method') or 'weighted_by_type') if enforced else None,
        'rubric_label': RUBRIC_LABELS.get(exam.get('rubric_template') or '', exam.get('rubric_template')) if enforced else None,
        'results_deadline_label': RESULTS_DEADLINE_LABELS.get(exam.get('results_deadline') or '3_days_after_end') if enforced else None,
        'correction_mode_label': CORRECTION_MODE_LABELS.get(exam.get('correction_mode') or 'manual') if enforced else None,
        'grading_flags': [
            {'label': 'نمره منفی (جریمه)', 'on': bool(penalty)},
            # «نمره جزئی» off makes partial-credit questions all-or-nothing; when the exam does not set it, each question decides
            {'label': 'اعطای نمره جزئی' if enforced else 'اعطای نمره جزئی (طبق تنظیم هر سؤال)',
             'on': grading_rules.get('allow_partial') not in (False, 0)},
            {'label': 'بازبینی دستی پاسخ‌ها', 'on': enforced and exam.get('manual_review_required') in (True, 1)},
        ],
        'security_level_label': SECURITY_LEVEL_LABELS.get(exam.get('security_level') or 'medium') if enforced else None,
        'execution_mode_label': EXECUTION_MODE_LABELS.get(exam.get('execution_mode') or 'web') if enforced else None,
        'internet_policy_label': INTERNET_POLICY_LABELS.get(rules['internet_disconnect_policy'], INTERNET_POLICY_LABELS['none']),
        'autosave_label': ('پس از هر تغییر پاسخ' if not autosave_interval else f'هر {autosave_interval} ثانیه') if rules['autosave_enabled'] else None,
        'ip_range': rules['ip_restriction_range'] if rules['ip_restriction_enabled'] else '',
        'security_flags': [
            _flag(rules, 'identity_verification_required', 'احراز هویت داوطلب'),
            _flag(rules, 'device_limit_enabled', 'محدودیت دستگاه'),
            _flag(rules, 'ip_restriction_enabled', 'محدودیت IP'),
            _flag(rules, 'fullscreen_required', 'اجبار تمام‌صفحه'),
            _flag(rules, 'webcam_monitoring', 'نظارت وبکم'),
            _flag(rules, 'mic_monitoring', 'نظارت میکروفون'),
            _flag(rules, 'track_tab_exit', 'هشدار تعویض تب'),
            _flag(rules, 'copy_paste_prevention', 'جلوگیری از کپی و چسباندن'),
            _flag(rules, 'screenshot_prevention', 'جلوگیری از اسکرین‌شات'),
            _flag(rules, 'autosave_enabled', 'ذخیره خودکار پاسخ‌ها'),
            _flag(exam, 'shuffle_questions', 'مخلوط‌سازی سوالات'),
            _flag(exam, 'shuffle_options', 'مخلوط‌سازی گزینه‌ها'),
        ],
        'publish_mode_label': PUBLISH_MODE_LABELS.get(exam.get('publish_mode') or 'draft', exam.get('publish_mode')),
        'approval_label': APPROVAL_LABELS.get(exam.get('approval_status') or 'pending', exam.get('approval_status') or '-'),
        'notify_flags': [
            _flag(exam, 'notify_students_system_message', 'اعلان از طریق پیام سامانه'),
            _flag(exam, 'notify_students_email', 'ارسال ایمیل اطلاع‌رسانی'),
            _flag(exam, 'show_in_academic_calendar', 'نمایش در تقویم آموزشی'),
        ],
    }


_EXAM_REPORT_SQL = """
    SELECT e.*, COALESCE(c.title, '-') AS course_title, c.code AS course_code,
           COALESCE(p.full_name, '-') AS teacher_name, ap.full_name AS approved_by_name
    FROM exams e
    LEFT JOIN courses c ON c.id = e.course_id
    LEFT JOIN profiles p ON p.id = e.teacher_id
    LEFT JOIN profiles ap ON ap.id = e.approved_by
    WHERE e.id = %s
"""


@erd_role_required('teacher')
def teacher_exam_report(request, exam_id):
    """The exam's owner and its «عوامل آزمون» (designer / observer / co-grader) may read the report."""
    exam = erd_row(
        _EXAM_REPORT_SQL + ' AND (e.teacher_id = %s OR e.id IN (SELECT es.exam_id FROM exam_staff es WHERE es.teacher_id = %s))',
        [exam_id, request.erd_profile_id, request.erd_profile_id],
    )
    if not exam:
        raise Http404('آزمون پیدا نشد.')
    return render(request, 'super_admin/exam_report.html',
                  _exam_report_context(exam, reverse('core:teacher_exams'), 'teacher'))


@erd_role_required('academic_manager', 'admin')
def super_admin_exam_report(request, exam_id):
    exam = erd_row(_EXAM_REPORT_SQL, [exam_id])
    if not exam or not _erd_exam_in_manager_scope(request, exam_id):
        raise Http404('آزمون پیدا نشد.')
    return render(request, 'super_admin/exam_report.html',
                  _exam_report_context(exam, reverse('core:super_admin_exams'), 'manager'))
