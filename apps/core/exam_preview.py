"""«پیش‌نمایش» of an exam or a single question, on the real student exam page (student/attempt.html).

Who sees what:
- system admin / academic manager (exams and questions in their scope), teacher (their own exams, exams they are
  staff on, their own questions and questions shared with their courses): the real questions.
- student (an exam assigned to them, course or practice): **sample questions** with the exam's real structure
  (count, order, types, points, suggested time, option/blank/item counts, answer formats), duration and rules,
  so they learn the exam page without seeing a single real question, option or media file.

Nothing is written to the database: the preview's answers, marks, locks and timer live in the viewer's session
(SESSION_KEY), one entry per previewed exam/question, until «شروع دوباره» or the session ends. The page behaves like
the real attempt (navigation, «امکان بازگشت», «امکان تغییر پاسخ», list, flagging, autosave, timer, the end-of-exam
summary); camera/microphone/full-screen/tab tracking are only listed, never started, and no proctoring event or file
upload leaves the browser.
"""
import json
import random
import time
import uuid

from django.http import Http404, JsonResponse
from django.shortcuts import redirect, render
from django.templatetags.static import static
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache

from .rich_text import clean_delta, delta_text
from .views import (
    ANSWER_TEXT_MAX,
    EXAM_RULE_DEFAULTS,
    MANUAL_ANSWER_KINDS,
    PAGE_RULE_KEYS,
    PRACTICE_EXAM_MODE,
    _BLANK_MARKER_RE,
    _em_exam_rows,
    _em_int,
    _sx_answer_dashboard,
    _sx_attempt_items,
    _sx_decode_item_answer,
    _sx_exam_row,
    _sx_exam_rules,
    _sx_float,
    _sx_json,
    _sx_question_options,
    _sx_type_label,
    _teacher_owned_exam,
    erd_has_column,
    erd_role_name,
    erd_role_required,
    erd_row,
    erd_rows,
    question_for_editor,
)

SESSION_KEY = 'mq_previews'
MAX_STATES = 6  # previews kept per session; the oldest is dropped
PREVIEW_ROLES = ('student', 'teacher', 'academic_manager', 'admin')
SAMPLE_IMAGE = 'img/preview-sample.svg'

# Shown above the page: the exam's security rules that the preview lists but does not start.
RULE_LABELS = (
    ('fullscreen_required', 'حالت تمام‌صفحه'),
    ('webcam_monitoring', 'نظارت وبکم'),
    ('mic_monitoring', 'نظارت میکروفون'),
    ('track_tab_exit', 'ثبت خروج از صفحه'),
    ('copy_paste_prevention', 'جلوگیری از کپی و چسباندن'),
    ('screenshot_prevention', 'جلوگیری از اسکرین‌شات'),
    ('ip_restriction_enabled', 'محدودیت IP'),
    ('identity_verification_required', 'تأیید هویت پیش از شروع'),
)


IDLE_RULES = {'fullscreen_required', 'webcam_monitoring', 'mic_monitoring', 'track_tab_exit', 'ip_restriction_enabled',
               'identity_verification_required'}


def _valid_id(value) -> str:
    """ERD ids are UUIDs; anything else is a 404 (a malformed id must never reach a uuid column)."""
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError, AttributeError):
        raise Http404('پیدا نشد.')


# ---------------------------------------------------------------------------------------------------------------
# Access
# ---------------------------------------------------------------------------------------------------------------

def _exam_for_viewer(request, exam_id):
    """(exam row, sample_questions) when the viewer may preview the exam, else 404."""
    role = request.erd_role
    exam = None
    if role == 'student':
        exam = _sx_exam_row(exam_id, request.erd_profile_id)
    elif role == 'teacher':
        exam = _teacher_owned_exam(request.erd_profile_id, exam_id, staff=True)
    elif role in ('admin', 'academic_manager'):
        exam = (_em_exam_rows(request, exam_id) or [None])[0]
    if not exam:
        raise Http404('آزمون پیدا نشد.')
    mode = 'exam_mode, ' if erd_has_column('exams', 'exam_mode') else ''
    row = erd_row(f'SELECT id, title, {mode}COALESCE(duration_minutes, 90) AS duration_minutes FROM exams WHERE id = %s', [exam_id])
    if not row:
        raise Http404('آزمون پیدا نشد.')
    return row, role == 'student'


def _question_for_viewer(request, question_id):
    """The question row the viewer may preview (their bank, or shared with their courses), else 404."""
    row = question_for_editor(request, question_id)
    if not row and request.erd_role == 'teacher':
        from .teacher_question_bank import SHARED_WITH_SQL

        teacher_id = request.erd_profile_id
        row = erd_row(f'SELECT q.* FROM questions q WHERE q.id = %s AND {SHARED_WITH_SQL}',
                      [question_id, teacher_id, teacher_id, teacher_id])
    if not row:
        raise Http404('سؤال پیدا نشد.')
    return row


# ---------------------------------------------------------------------------------------------------------------
# Rows in the shape of views._sx_attempt_rows (answers come from the preview state)
# ---------------------------------------------------------------------------------------------------------------

OPTIONAL_QUESTION_COLUMNS = ('matching_pairs', 'ordering_items', 'question_media', 'scoring_settings',
                             'suggested_time_seconds', 'accepted_answers')


def _optional_sql():
    return ', '.join(f'q.{column}' if erd_has_column('questions', column) else f'NULL AS {column}'
                     for column in OPTIONAL_QUESTION_COLUMNS)


def _exam_rows(exam_id, token):
    shuffle_sql = ', '.join(
        f'COALESCE(e.{column}, false) AS exam_{column}' if erd_has_column('exams', column) else f'false AS exam_{column}'
        for column in ('shuffle_questions', 'shuffle_options')
    )
    rows = erd_rows(
        f"""
        SELECT q.id AS question_id, q.text, COALESCE(q.type, 'single') AS type, q.options,
               COALESCE(eq.points, q.default_points) AS question_points, {_optional_sql()}, {shuffle_sql}
        FROM exam_questions eq
        JOIN exams e ON e.id = eq.exam_id
        JOIN questions q ON q.id = eq.question_id
        WHERE eq.exam_id = %s
        ORDER BY eq.order_index NULLS LAST, q.id
        """,
        [exam_id],
    )
    if rows and rows[0].get('exam_shuffle_questions'):
        random.Random(f'{token}-questions').shuffle(rows)  # «ترتیب تصادفی سؤال‌ها», like a new attempt
    return rows


def _question_rows(question):
    row = {column: question.get(column) for column in OPTIONAL_QUESTION_COLUMNS}
    row.update({
        'question_id': str(question['id']), 'text': question.get('text'), 'type': question.get('type') or 'single',
        'options': question.get('options'), 'question_points': question.get('default_points'),
        'exam_shuffle_options': False,
    })
    return [row]


def _settings(row) -> dict:
    data = _sx_json(row.get('scoring_settings'), {}) or {}
    return data if isinstance(data, dict) else {}


def _count(value, low, high, default):
    return min(max(value, low), high) if value else default


SAMPLE_NOTE = 'این سؤال نمونه است؛ در آزمون واقعی سؤال استاد در همین قالب نمایش داده می‌شود.'


def _sample_row(row, index):
    """A stand-in for one real question: same type, points and answer structure; canned text, no real content."""
    kind = row.get('type') or 'single'
    real = _settings(row)
    sample = {
        'question_id': f'sample-{index}', 'type': kind, 'question_points': row.get('question_points'),
        'suggested_time_seconds': row.get('suggested_time_seconds'), 'exam_shuffle_options': False,
        'options': None, 'matching_pairs': None, 'ordering_items': None, 'question_media': None,
        'accepted_answers': None, 'scoring_settings': None,
    }
    media = _sx_json(row.get('question_media'), {}) or {}
    sample_image = kind in ('image_label', 'hotspot') or (isinstance(media, dict) and bool(media.get('image')))
    settings_data = {}
    if kind in ('single', 'single_choice', 'multiple_choice', 'multi'):
        count = _count(len(_sx_question_options(row.get('options'), kind)), 2, 10, 4)
        sample['text'] = f'سؤال نمونه {index}: {SAMPLE_NOTE} کدام گزینه را انتخاب می‌کنید؟'
        sample['options'] = json.dumps([f'گزینه نمونه {number}' for number in range(1, count + 1)], ensure_ascii=False)
        if kind == 'multi':
            settings_data = {key: real[key] for key in ('min_correct', 'max_correct') if key in real}
    elif kind == 'true_false':
        sample['text'] = f'سؤال نمونه {index}: {SAMPLE_NOTE} این جمله درست است یا نادرست؟'
    elif kind == 'short_answer':
        sample['text'] = f'سؤال نمونه {index}: {SAMPLE_NOTE} پاسخ کوتاه خود را بنویسید.'
        settings_data = {'max_chars': real['max_chars']} if real.get('max_chars') else {}
    elif kind in ('essay', 'descriptive', 'media_response'):
        essay = real.get('essay') or {}
        settings_data = {'essay': {
            'answer_formats': essay.get('answer_formats') or ['text'],
            'student_instructions': 'راهنمای پاسخ‌دهی استاد در آزمون واقعی در این قسمت نمایش داده می‌شود.' if essay.get('student_instructions') else '',
        }}
        if kind == 'media_response':
            stimulus = real.get('media_response') or {}
            settings_data['media_response'] = {'max_record_seconds': stimulus.get('max_record_seconds') or 120}
            sample['text'] = f'سؤال نمونه {index}: {SAMPLE_NOTE} در آزمون واقعی فایل صوتی یا ویدئویی سؤال در این قسمت پخش می‌شود؛ پاسخ خود را بنویسید یا ضبط کنید.'
        else:
            sample['text'] = f'سؤال نمونه {index}: {SAMPLE_NOTE} پاسخ تشریحی خود را بنویسید.'
    elif kind == 'fill_blank':
        blanks = _count(len(_BLANK_MARKER_RE.findall(str(row.get('text') or ''))), 1, 6, 2)
        parts = '، '.join(f'پاسخ {number} را در [{number}] بنویسید' for number in range(1, blanks + 1))
        sample['text'] = f'سؤال نمونه {index} (متن نمونه): {parts}.'
    elif kind == 'numeric':
        numeric = real.get('numeric') or {}
        settings_data = {'numeric': {'unit': 'واحد' if numeric.get('unit') else '', 'require_unit': bool(numeric.get('require_unit'))}}
        sample['text'] = f'سؤال نمونه {index}: {SAMPLE_NOTE} پاسخ عددی را وارد کنید.'
    elif kind == 'ordering':
        count = _count(len(_sx_json(row.get('ordering_items'), []) or []), 2, 8, 4)
        sample['text'] = f'سؤال نمونه {index}: {SAMPLE_NOTE} موارد زیر را به ترتیب درست مرتب کنید.'
        sample['ordering_items'] = json.dumps([{'text': f'مورد نمونه {number}', 'order': number} for number in range(1, count + 1)], ensure_ascii=False)
    elif kind == 'matching':
        count = _count(len(_sx_json(row.get('matching_pairs'), []) or []), 2, 8, 3)
        sample['text'] = f'سؤال نمونه {index}: {SAMPLE_NOTE} هر مورد ستون اول را به پاسخ مناسب در ستون دوم وصل کنید.'
        sample['matching_pairs'] = json.dumps([{'left': f'مورد نمونه {number}', 'right': f'پاسخ نمونه {number}'} for number in range(1, count + 1)], ensure_ascii=False)
        settings_data = {'matching_mode': real.get('matching_mode') or 'one_to_one'}
        if real.get('matching_distractors'):
            settings_data['matching_distractors'] = ['پاسخ اضافه نمونه']
    elif kind == 'matrix':
        matrix = real.get('matrix') or {}
        rows_count = _count(len(_sx_json(row.get('options'), []) or []), 1, 8, 3)
        columns_count = _count(len(matrix.get('columns') or []), 2, 6, 3)
        sample['text'] = f'سؤال نمونه {index}: {SAMPLE_NOTE} برای هر سطر، ستون درست را انتخاب کنید.'
        sample['options'] = json.dumps([{'id': f'r{number}', 'text': f'سطر نمونه {number}'} for number in range(1, rows_count + 1)], ensure_ascii=False)
        settings_data = {'matrix': {
            'columns': [{'id': f'c{number}', 'text': f'ستون {number}'} for number in range(1, columns_count + 1)],
            'selection': matrix.get('selection') or 'single', 'show_column_titles': True, 'show_row_titles': True,
        }}
    elif kind == 'image_label':
        label = real.get('image_label') or {}
        count = _count(len([item for item in _sx_json(row.get('accepted_answers'), []) or [] if isinstance(item, dict)]), 1, 6, 3)
        spots = [(22, 30), (70, 26), (48, 62), (20, 78), (78, 74), (50, 18)]
        sample['text'] = f'سؤال نمونه {index}: {SAMPLE_NOTE} نام هر بخش شماره‌دار تصویر را بنویسید.'
        sample['accepted_answers'] = json.dumps([{'marker': number, 'x': spots[number - 1][0], 'y': spots[number - 1][1], 'answer': f'برچسب نمونه {number}'}
                                                 for number in range(1, count + 1)], ensure_ascii=False)
        settings_data = {'image_label': {'answer_mode': label.get('answer_mode') or 'type'}}
    elif kind == 'hotspot':
        hotspot = real.get('hotspot') or {}
        sample['text'] = f'سؤال نمونه {index}: {SAMPLE_NOTE} روی ناحیه‌ی درست تصویر کلیک کنید.'
        settings_data = {'hotspot': {'max_clicks': hotspot.get('max_clicks') or 1}}
    else:
        sample['text'] = f'سؤال نمونه {index}: {SAMPLE_NOTE}'
    sample['scoring_settings'] = json.dumps(settings_data, ensure_ascii=False)
    sample['sample_image'] = sample_image
    return sample


# ---------------------------------------------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------------------------------------------

def _state_key(kind, target_id):
    return f'{kind}:{target_id}'


def _get_state(request, key):
    return (request.session.get(SESSION_KEY) or {}).get(key)


def _put_state(request, key, state):
    states = dict(request.session.get(SESSION_KEY) or {})
    states[key] = state
    if len(states) > MAX_STATES:
        for old in sorted(states, key=lambda name: states[name].get('started', 0))[:len(states) - MAX_STATES]:
            states.pop(old, None)
    request.session[SESSION_KEY] = states
    request.session.modified = True


def _back_url(request, default):
    """Where «خروج از پیش‌نمایش» goes: ?next=, else the page the preview was opened from, else the role's list."""
    for candidate in (request.GET.get('next'), request.META.get('HTTP_REFERER')):
        if candidate and url_has_allowed_host_and_scheme(candidate, allowed_hosts={request.get_host()},
                                                         require_https=request.is_secure()) and '/preview/' not in candidate:
            return candidate
    return default


def _default_back(request, kind):
    if kind == 'question':
        return reverse('core:teacher_questions')
    return {
        'student': reverse('core:student_exam_schedule'),
        'teacher': reverse('core:teacher_exams'),
        'academic_manager': reverse('core:exam_manager_exams'),
    }.get(request.erd_role, reverse('core:super_admin_exams'))


def _new_state(request, kind):
    return {
        'token': str(uuid.uuid4()), 'started': time.time(), 'answers': {}, 'marked': [], 'locked': [],
        'furthest': 1, 'back': _back_url(request, _default_back(request, kind)),
    }


def _state(request, kind, target_id):
    key = _state_key(kind, target_id)
    state = _get_state(request, key)
    if not state:
        state = _new_state(request, kind)
        _put_state(request, key, state)
    return key, state


# ---------------------------------------------------------------------------------------------------------------
# The page
# ---------------------------------------------------------------------------------------------------------------

def _rules(kind, exam):
    if kind == 'question':
        rules = dict(EXAM_RULE_DEFAULTS)
        rules['settings_enforced'] = False
    else:
        rules = _sx_exam_rules(exam['id'])
        if exam.get('exam_mode') == PRACTICE_EXAM_MODE:
            rules.update({key: EXAM_RULE_DEFAULTS[key] for key in PAGE_RULE_KEYS})  # as views._sx_attempt_page_rules
    if not rules['review_answers_enabled']:
        rules['one_question_per_page'] = True
    return rules


def _context(request, kind, target, rows, sample, state, rules):
    """Everything views.student_attempt hands to student/attempt.html, plus ``preview``."""
    token = state['token']
    answers, marked = state['answers'], set(state['marked'])
    for row in rows:
        question_id = str(row['question_id'])
        row['answer'] = answers.get(question_id)
        row['marked'] = question_id in marked
    items = _sx_attempt_items(rows, token, set(state['locked']) if not rules['allow_answer_changes'] else set())
    sample_media = {'image': static(SAMPLE_IMAGE), 'image_alt': 'تصویر نمونه', 'video_caption': '', 'video_subtitle': ''}
    for item, row in zip(items, rows):
        if row.get('sample_image'):
            item['media'] = dict(sample_media)
    current_index = min(max(1, _em_int(request.GET.get('q'), 1)), len(items))
    practice = None
    if kind == 'exam' and target.get('exam_mode') == PRACTICE_EXAM_MODE:
        from .student_practice import PRACTICE_MODES

        practice = {'mode': 'simulation', 'mode_title': PRACTICE_MODES['simulation'][0], 'tutorial': False, 'feedback': None}
    timed = kind == 'exam'
    remaining = None
    if timed:
        total = _em_int(target.get('duration_minutes'), 90) * 60
        remaining = max(0, int(total - (time.time() - state['started'])))
    preview_url = request.path
    role = request.erd_role
    return {
        'attempt': {'pk': token, 'id': token, 'exam': {'title': target.get('title') or ('پیش‌نمایش سؤال' if kind == 'question' else 'آزمون')}},
        'current_answer': items[current_index - 1],
        'current_index': current_index,
        'total_questions': len(items),
        'answered_count': sum(1 for item in items if item['answered']),
        'attempt_map': _sx_answer_dashboard(items, current_index),
        'remaining_seconds': remaining,
        'practice': practice,
        # Copy/paste and screenshot shields run as in the exam (nothing is reported); camera, microphone, full screen
        # and tab tracking are listed in the preview bar instead of being started.
        'proctoring': {'track': False, 'fullscreen': False, 'webcam': False, 'mic': False,
                       'copy_paste': rules['copy_paste_prevention'], 'screenshot': rules['screenshot_prevention']},
        'items': items,
        'page_rules': {
            'one_per_page': rules['one_question_per_page'],
            'show_list': rules['show_question_list'],
            'flagging': rules['allow_flagging_questions'],
            'back': rules['review_answers_enabled'],
            'lock_on_leave': not rules['allow_answer_changes'],
            'auto_submit': rules['auto_submit_on_time_end'],
            'autosave': rules['autosave_enabled'],
            'autosave_seconds': rules['autosave_interval_seconds'],
            'offline': rules['internet_disconnect_policy'],
        },
        'preview': {
            'kind': kind,
            'sample': sample,
            'timed': timed,
            'url': preview_url,
            'finish_url': f'{preview_url}finish/',
            'back_url': state.get('back') or _default_back(request, kind),
            'role_label': f'پیش‌نمایش {erd_role_name(role)}',
            'duration_minutes': _em_int(target.get('duration_minutes'), 90) if timed else None,
            'rules': [label for key, label in RULE_LABELS if rules.get(key)] if kind == 'exam' else [],
            # Listed but not started in a preview (camera, microphone, full screen, …).
            'idle_rules': '، '.join(label for key, label in RULE_LABELS if key in IDLE_RULES and rules.get(key)) if kind == 'exam' else '',
            'practice': bool(practice),
        },
    }


def _save_answers(request, state, rows, rules):
    """views._sx_save_attempt_answers, into the preview state instead of attempt_answers."""
    allowed = {str(row['question_id']): row for row in rows}
    locked = set(state['locked'])
    marked = set(state['marked'])
    answers = state['answers']
    posted = dict.fromkeys(key.split('_', 1)[1] for key in request.POST.keys() if key.startswith(('answer_', 'seen_')))
    for question_id in posted:
        if question_id not in allowed:
            continue
        key = f'answer_{question_id}'
        is_marked = bool(request.POST.get(f'mark_{question_id}')) and rules['allow_flagging_questions']
        if question_id in locked or key not in request.POST:
            if is_marked and question_id not in locked:
                marked.add(question_id)
            elif not is_marked:
                marked.discard(question_id)
            continue
        question = allowed[question_id]
        values = [value[:ANSWER_TEXT_MAX] for value in request.POST.getlist(key)]
        value = values if len(values) > 1 else (values[0] if values else '')
        if question.get('type') in ('ordering', 'matching'):
            value = _sx_decode_item_answer(question['type'], question, state['token'], values[0] if values else '')
        stored = {'value': value}
        if question.get('type') == 'short_answer' and isinstance(value, str):
            limit = int(_sx_float(_settings(question).get('max_chars'), 0))
            if limit:
                stored['value'] = value[:limit]
        if question.get('type') in MANUAL_ANSWER_KINDS and request.POST.get(f'answer_delta_{question_id}'):
            delta = clean_delta(request.POST.get(f'answer_delta_{question_id}'))
            if delta.get('ops'):
                stored['delta'] = delta
                stored['value'] = delta_text(delta).strip()[:ANSWER_TEXT_MAX]
        answers[question_id] = json.dumps(stored, ensure_ascii=False)
        (marked.add if is_marked else marked.discard)(question_id)
    if not rules['allow_answer_changes']:
        _lock(state, [key[len('lock_'):] for key in request.POST if key.startswith('lock_') and key[len('lock_'):] in allowed])
    state['marked'] = sorted(marked)


def _answered(state, question_id) -> bool:
    raw = _sx_json(state['answers'].get(question_id), {})
    value = raw.get('value') if isinstance(raw, dict) else raw
    if isinstance(value, list):
        return any(str(item).strip() for item in value)
    return bool(str(value or '').strip())


def _lock(state, question_ids):
    locked = set(state['locked'])
    locked.update(str(question_id) for question_id in question_ids if _answered(state, str(question_id)))
    state['locked'] = sorted(locked)


def _target(request, kind, target_id):
    if kind == 'exam':
        exam, sample = _exam_for_viewer(request, target_id)
        return exam, sample
    question = _question_for_viewer(request, target_id)
    return {'id': question['id'], 'title': 'پیش‌نمایش سؤال', 'question': question}, False


def _rows_for(kind, target, sample, state):
    rows = _exam_rows(target['id'], state['token']) if kind == 'exam' else _question_rows(target['question'])
    if sample:
        rows = [_sample_row(row, index) for index, row in enumerate(rows, start=1)]
    return rows


def _preview(request, kind, target_id):
    target_id = _valid_id(target_id)
    target, sample = _target(request, kind, target_id)
    if request.method == 'GET' and request.GET.get('new'):
        # Opened from a list / detail page: a fresh run that returns to that page.
        _put_state(request, _state_key(kind, target_id), _new_state(request, kind))
        return redirect(request.path)
    key, state = _state(request, kind, target_id)
    rows = _rows_for(kind, target, sample, state)
    if not rows:
        return render(request, 'student/preview_finish.html', _finish_context(request, kind, target, [], state, empty=True))
    rules = _rules(kind, target)
    is_xhr = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    current_index = min(max(1, _em_int(request.GET.get('q'), 1)), len(rows))
    if request.method == 'POST':
        if request.POST.get('action') == 'restart':
            _put_state(request, key, _new_state(request, kind) | {'back': state.get('back')})
            return redirect(request.path)
        _save_answers(request, state, rows, rules)
        _put_state(request, key, state)
        if is_xhr:
            return JsonResponse({'ok': True})
        action = request.POST.get('action') or ('goto' if request.POST.get('goto') else None)
        current_id = str(rows[current_index - 1]['question_id']) if rules['one_question_per_page'] else None
        if action == 'finish':
            if not rules['allow_answer_changes'] and current_id:
                _lock(state, [current_id])
                _put_state(request, key, state)
            return redirect(f'{request.path}finish/')
        target_index = current_index
        if action == 'previous':
            target_index = max(1, current_index - 1)
        elif action == 'next':
            target_index = min(len(rows), current_index + 1)
        elif action == 'goto':
            target_index = min(max(1, _em_int(request.POST.get('goto'), current_index)), len(rows))
        if target_index != current_index and not rules['allow_answer_changes'] and current_id:
            _lock(state, [current_id])
        if not rules['review_answers_enabled']:
            furthest = state['furthest']
            target_index = furthest + 1 if action == 'next' and current_index >= furthest else furthest
            target_index = min(max(target_index, 1), len(rows))
            state['furthest'] = max(state['furthest'], target_index)
        _put_state(request, key, state)
        return redirect(f'{request.path}?q={target_index}')
    if not rules['review_answers_enabled']:
        furthest = min(max(state['furthest'], 1), len(rows))
        if current_index != furthest:
            return redirect(f'{request.path}?q={furthest}')
    if not rules['allow_answer_changes'] and rules['one_question_per_page']:
        # As in the exam: answered questions other than the one on screen were left behind (e.g. via the list).
        _lock(state, [row['question_id'] for index, row in enumerate(rows, start=1) if index != current_index])
        _put_state(request, key, state)
    return render(request, 'student/attempt.html', _context(request, kind, target, rows, sample, state, rules))


def _finish_context(request, kind, target, rows, state, empty=False):
    marked = set(state['marked'])
    questions = []
    for index, row in enumerate(rows, start=1):
        question_id = str(row['question_id'])
        questions.append({
            'index': index, 'type_label': _sx_type_label(row.get('type')),
            'points': _sx_float(row.get('question_points'), 0),
            'answered': _answered(state, question_id), 'marked': question_id in marked,
        })
    answered = sum(1 for question in questions if question['answered'])
    preview_url = request.path[:-len('finish/')] if request.path.endswith('/finish/') else request.path
    return {
        'kind': kind,
        'title': target.get('title') or '',
        'empty': empty,
        'questions': questions,
        'answered_count': answered,
        'unanswered_count': len(questions) - answered,
        'marked_count': sum(1 for question in questions if question['marked']),
        'total_points': sum(question['points'] for question in questions),
        'time_up': bool(request.GET.get('timeup')),
        'preview_url': preview_url,
        'back_url': state.get('back') or _default_back(request, kind),
        'sample': request.erd_role == 'student',
    }


def _finish(request, kind, target_id):
    target_id = _valid_id(target_id)
    target, sample = _target(request, kind, target_id)
    key, state = _state(request, kind, target_id)
    rows = _rows_for(kind, target, sample, state)
    return render(request, 'student/preview_finish.html', _finish_context(request, kind, target, rows, state, empty=not rows))


@never_cache
@erd_role_required(*PREVIEW_ROLES)
def exam_preview(request, exam_id):
    return _preview(request, 'exam', exam_id)


@never_cache
@erd_role_required(*PREVIEW_ROLES)
def exam_preview_finish(request, exam_id):
    return _finish(request, 'exam', exam_id)


@never_cache
@erd_role_required('teacher', 'academic_manager', 'admin')
def question_preview(request, question_id):
    return _preview(request, 'question', question_id)


@never_cache
@erd_role_required('teacher', 'academic_manager', 'admin')
def question_preview_finish(request, question_id):
    return _finish(request, 'question', question_id)
