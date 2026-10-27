"""Numeric, matrix, image-labelling and audio/video-response questions.

Builder parsing, validation, edit-form values, grading and the student exam view of the four question types
added after the original eight. The question builder (views._apply_independent_settings / _question_form_data),
grade_attempt (views._grade_question) and the student exam page (views.student_attempt) call into this module.

Storage (all in existing `questions` columns, no new columns):
- numeric:        correct_answer = value; scoring_settings.numeric = unit / decimals / tolerance / switches
- matrix:         options = rows [{id, text, points, correct: [column ids]}]; scoring_settings.matrix = columns
                  and display switches; correct_answer = ["r1:c2", ...]
- image_label:    question_media.image = the image; accepted_answers = markers [{marker, x, y, answer, synonyms,
                  points}] (x/y in % of the image); scoring_settings.image_label = answer mode / synonyms switch
- media_response: question_media.audio|video = the stimulus; scoring_settings.media_response = playback rules,
                  transcript, record limit; scoring_settings.essay = answer formats / instructions (shared with the
                  essay upload and grading code); rubric = manual-grading criteria. Always graded manually.
"""
import json
import random
import re

V2_TYPES = ('numeric', 'matrix', 'image_label', 'media_response')

TYPE_LABELS = {
    'numeric': 'پاسخ عددی',
    'matrix': 'ماتریسی / جدول',
    'image_label': 'تصویری / نشانه‌گذاری',
    'media_response': 'صوتی / ویدئویی',
}

MATRIX_MAX_ROWS = 30
MATRIX_MAX_COLUMNS = 10
LABEL_MAX_MARKERS = 30
CELL_TEXT_MAX = 300
TRANSCRIPT_MAX = 3000
MEDIA_ANSWER_FORMATS = ('text', 'audio', 'video')
RECORD_SECONDS_RANGE = (10, 600)
ATTACHMENT_EXTENSIONS = {'pdf', 'docx', 'jpg', 'jpeg', 'png'}
ATTACHMENT_MAX = 10 * 1024 * 1024

_DIGITS = str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩٫', '01234567890123456789.')
_NON_LATIN_DIGIT_RE = re.compile(r'[۰-۹٠-٩٫]')


def _number(value, fallback=None):
    try:
        return float(str(value if value is not None else '').translate(_DIGITS).replace(',', '').replace('٬', '').strip())
    except ValueError:
        return fallback


def _clock_seconds(value):
    """«mm:ss» (or plain seconds) → seconds; '' / invalid → None."""
    text = str(value or '').translate(_DIGITS).strip()
    if not text:
        return None
    minutes, _, seconds = text.rpartition(':')
    try:
        return max(int(minutes or 0) * 60 + int(seconds), 0)
    except ValueError:
        return None


def _clock(seconds):
    return '' if seconds is None else f'{int(seconds) // 60:02d}:{int(seconds) % 60:02d}'


def _json_list(raw):
    try:
        value = json.loads(raw or '[]')
    except (TypeError, ValueError):
        return []
    return value if isinstance(value, list) else []


def _json(value, fallback):
    if isinstance(value, (dict, list)):
        return value
    try:
        parsed = json.loads(value) if value not in (None, '') else fallback
    except (TypeError, ValueError):
        return fallback
    return parsed if isinstance(parsed, type(fallback)) else fallback


def _text(value, limit=CELL_TEXT_MAX):
    return str(value or '').strip()[:limit]


def _split(value):
    return [part.strip() for part in re.split(r'[,،\n]', str(value or '')) if part.strip()]


def _answer_list(answer):
    if isinstance(answer, list):
        return [str(item) for item in answer]
    return [str(answer)] if answer not in (None, '') else []


def _normalize(value):
    from .views import _normalize_answer_text  # imported on use: views imports this module

    return _normalize_answer_text(value)


# ----- builder: POST → payload -----

def apply_settings(payload, post, settings_data):
    """Fill payload/scoring settings of a v2 question from the builder form (uploads are resolved later)."""
    kind = payload['stored_type']
    if kind == 'numeric':
        value = _number(post.get('numeric_answer'))
        mode = post.get('numeric_tolerance_mode')
        settings_data['numeric'] = {
            'value': value,
            'unit': _text(post.get('numeric_unit'), 30),
            'decimals': min(max(int(_number(post.get('numeric_decimals'), 0) or 0), 0), 6),
            'tolerance_mode': mode if mode in {'absolute', 'percent'} else 'absolute',
            'tolerance': abs(_number(post.get('numeric_tolerance'), 0) or 0),
            'accept_persian_digits': bool(post.get('numeric_accept_persian')),
            'require_unit': bool(post.get('numeric_require_unit')),
        }
        payload['correct_answer'] = '' if value is None else f'{value:g}'
        payload['options'] = []
    elif kind == 'matrix':
        columns, rows = _parse_matrix(post.get('matrix_json'))
        settings_data['matrix'] = {
            'columns': columns,
            'selection': 'multi' if post.get('matrix_selection') == 'multi' else 'single',
            'show_column_titles': bool(post.get('matrix_show_column_titles')),
            'show_row_titles': bool(post.get('matrix_show_row_titles')),
            'shuffle_rows': bool(post.get('matrix_shuffle_rows')),
            'shuffle_columns': bool(post.get('matrix_shuffle_columns')),
        }
        payload['options'] = rows
        payload['correct_answer'] = [f"{row['id']}:{column}" for row in rows for column in row['correct']]
    elif kind == 'image_label':
        markers = _parse_markers(post.get('label_markers_json'))
        settings_data['image_label'] = {
            'answer_mode': 'drag' if post.get('label_answer_mode') == 'drag' else 'type',
            'accept_synonyms': bool(post.get('label_accept_synonyms')),
        }
        payload['accepted_answers'] = markers
        payload['correct_answer'] = '|'.join(marker['answer'] for marker in markers)
        payload['options'] = []
    elif kind == 'media_response':
        record = int(_number(post.get('media_max_record_seconds'), 120) or 120)
        settings_data['media_response'] = {
            'allow_replay': bool(post.get('media_allow_replay')),
            'range_start': _clock_seconds(post.get('media_range_start')),
            'range_end': _clock_seconds(post.get('media_range_end')),
            'max_plays': min(max(int(_number(post.get('media_max_plays'), 0) or 0), 0), 20),
            'transcript': _text(post.get('media_transcript'), TRANSCRIPT_MAX),
            'show_transcript': bool(post.get('media_show_transcript')),
            'max_record_seconds': min(max(record, RECORD_SECONDS_RANGE[0]), RECORD_SECONDS_RANGE[1]),
            'attachment': None,  # resolved with the other uploads
        }
        settings_data['essay'] = {
            'student_instructions': '',
            'answer_formats': [key for key in MEDIA_ANSWER_FORMATS if key in post.getlist('answer_formats')],
            'sample_answer_text': '',
            'sample_answer_file': None,
        }
        payload['rubric'] = [
            {'criterion': _text(criterion, 120), 'description': _text(description), 'points': _text(points, 10), 'grading': 'manual'}
            for criterion, description, points in zip(post.getlist('media_rubric_criterion'), post.getlist('media_rubric_description'), post.getlist('media_rubric_points'))
            if criterion.strip()
        ]
        payload['options'] = []
    return payload


def _parse_matrix(raw):
    data = _json(raw, {})
    raw_columns = [item for item in (data.get('columns') or []) if isinstance(item, dict)][:MATRIX_MAX_COLUMNS]
    raw_rows = [item for item in (data.get('rows') or []) if isinstance(item, dict)][:MATRIX_MAX_ROWS]
    # IDs are re-issued in display order so stored answers never depend on client-made IDs.
    column_ids = {}
    columns = []
    for index, column in enumerate(raw_columns, start=1):
        column_ids[str(column.get('id'))] = f'c{index}'
        columns.append({'id': f'c{index}', 'text': _text(column.get('text'))})
    rows = []
    for index, row in enumerate(raw_rows, start=1):
        correct = []
        for column in row.get('correct') or []:
            mapped = column_ids.get(str(column))
            if mapped and mapped not in correct:
                correct.append(mapped)
        rows.append({
            'id': f'r{index}',
            'text': _text(row.get('text')),
            'points': max(_number(row.get('points'), 1) or 0, 0),
            'correct': correct,
        })
    return columns, rows


def _parse_markers(raw):
    markers = []
    for index, item in enumerate([item for item in _json_list(raw) if isinstance(item, dict)][:LABEL_MAX_MARKERS], start=1):
        markers.append({
            'marker': index,
            'x': min(max(_number(item.get('x'), 50) or 0, 0), 100),
            'y': min(max(_number(item.get('y'), 50) or 0, 0), 100),
            'answer': _text(item.get('answer'), 120),
            'synonyms': [_text(part, 120) for part in _split(item.get('synonyms'))][:20],
            'points': max(_number(item.get('points'), 1) or 0, 0),
        })
    return markers


def resolve_uploads(payload, files, post, store, errors):
    """Supplementary file of an audio/video question. `store(uploaded, extensions, limit)` → (url, error)."""
    media_settings = (payload.get('scoring_settings') or {}).get('media_response')
    if media_settings is None:
        return
    from django.conf import settings

    uploaded = files.get('media_attachment_file')
    if uploaded:
        url, error = store(uploaded, ATTACHMENT_EXTENSIONS, ATTACHMENT_MAX)
        if error:
            errors.append(error)
        else:
            media_settings['attachment'] = {'url': url, 'name': uploaded.name[:150]}
        return
    existing = (post.get('existing_media_attachment') or '').strip()
    if existing and not post.get('remove_media_attachment') and existing.startswith(f'{settings.MEDIA_URL}question-media/') and '..' not in existing:
        media_settings['attachment'] = {'url': existing, 'name': (post.get('existing_media_attachment_name') or 'فایل مکمل')[:150]}


def errors_for(payload):
    kind = payload['stored_type']
    settings_data = payload.get('scoring_settings') or {}
    errors = []
    if kind == 'numeric':
        numeric = settings_data.get('numeric') or {}
        if numeric.get('value') is None:
            errors.append('پاسخ صحیح عددی را به‌صورت عدد وارد کنید.')
        if numeric.get('tolerance_mode') == 'percent' and numeric.get('tolerance', 0) > 100:
            errors.append('تلرانس درصدی حداکثر ۱۰۰ است.')
        if numeric.get('require_unit') and not numeric.get('unit'):
            errors.append('برای الزامی کردن واحد، واحد پاسخ را وارد کنید.')
    elif kind == 'matrix':
        matrix = settings_data.get('matrix') or {}
        columns, rows = matrix.get('columns') or [], payload.get('options') or []
        if len(columns) < 2 or any(not column['text'] for column in columns):
            errors.append('حداقل دو ستون با عنوان وارد کنید.')
        if len(rows) < 2 or any(not row['text'] for row in rows):
            errors.append('حداقل دو سطر با متن وارد کنید.')
        if any(not row['correct'] for row in rows):
            errors.append('برای هر سطر پاسخ صحیح را در جدول مشخص کنید.')
        if matrix.get('selection') == 'single' and any(len(row['correct']) > 1 for row in rows):
            errors.append('در حالت تک‌گزینه‌ای هر سطر فقط یک پاسخ صحیح دارد.')
    elif kind == 'image_label':
        markers = payload.get('accepted_answers') or []
        if not (payload.get('question_media') or {}).get('image'):
            errors.append('تصویر سؤال را برای نشانه‌گذاری بارگذاری کنید.')
        if not markers:
            errors.append('حداقل یک نشانه روی تصویر قرار دهید.')
        elif any(not marker['answer'] for marker in markers):
            errors.append('برای هر نشانه پاسخ صحیح وارد کنید.')
    elif kind == 'media_response':
        media = payload.get('question_media') or {}
        media_settings = settings_data.get('media_response') or {}
        if not (media.get('audio') or media.get('video')):
            errors.append('فایل صوتی یا ویدئویی سؤال را بارگذاری کنید.')
        start, end = media_settings.get('range_start'), media_settings.get('range_end')
        if start is not None and end is not None and end <= start:
            errors.append('پایان بازه‌ی مجاز پخش باید بعد از شروع آن باشد.')
        if not (settings_data.get('essay') or {}).get('answer_formats'):
            errors.append('حداقل یک قالب پاسخ برای دانشجو انتخاب کنید.')
    return errors


# ----- builder: stored row → edit-form values -----

def form_values(kind, source, settings_data):
    if kind == 'numeric':
        numeric = settings_data.get('numeric') or {}
        value = numeric.get('value')
        return {'numeric': {
            'value': '' if value is None else f'{value:g}',
            'unit': numeric.get('unit') or '',
            'decimals': numeric.get('decimals', 1),
            'tolerance_mode': numeric.get('tolerance_mode') or 'absolute',
            'tolerance': f"{numeric.get('tolerance', 0):g}",
            'accept_persian_digits': numeric.get('accept_persian_digits', True),
            'require_unit': bool(numeric.get('require_unit')),
        }}
    if kind == 'matrix':
        matrix = settings_data.get('matrix') or {}
        rows = [row for row in _json(source.get('options'), []) if isinstance(row, dict)]
        columns = matrix.get('columns') or []
        if not rows and not columns:
            columns = [{'id': 'c1', 'text': ''}, {'id': 'c2', 'text': ''}]
            rows = [{'id': f'r{index}', 'text': '', 'points': 1, 'correct': []} for index in (1, 2, 3)]
        return {'matrix': {
            'data': {'columns': columns, 'rows': rows},
            'selection': matrix.get('selection') or 'single',
            'show_column_titles': matrix.get('show_column_titles', True),
            'show_row_titles': matrix.get('show_row_titles', True),
            'shuffle_rows': bool(matrix.get('shuffle_rows')),
            'shuffle_columns': bool(matrix.get('shuffle_columns')),
        }}
    if kind == 'image_label':
        label = settings_data.get('image_label') or {}
        markers = [
            {**marker, 'synonyms': '، '.join(marker.get('synonyms') or [])}
            for marker in _json(source.get('accepted_answers'), []) if isinstance(marker, dict) and 'marker' in marker
        ]
        return {'image_label': {
            'markers': markers,
            'answer_mode': label.get('answer_mode') or 'type',
            'accept_synonyms': label.get('accept_synonyms', True),
        }}
    if kind == 'media_response':
        media_settings = settings_data.get('media_response') or {}
        essay = settings_data.get('essay') or {}
        rubric = [row for row in _json(source.get('rubric'), []) if isinstance(row, dict)]
        return {'media_response': {
            'allow_replay': media_settings.get('allow_replay', True),
            'range_start': _clock(media_settings.get('range_start')),
            'range_end': _clock(media_settings.get('range_end')),
            'max_plays': media_settings.get('max_plays', 3),
            'transcript': media_settings.get('transcript') or '',
            'show_transcript': bool(media_settings.get('show_transcript')),
            'max_record_seconds': media_settings.get('max_record_seconds') or 120,
            'attachment': media_settings.get('attachment') or None,
            'answer_formats': essay.get('answer_formats') or ['audio'],
            'rubric': rubric or [{'criterion': '', 'description': '', 'points': '', 'grading': 'manual'}],
        }}
    return {}


# ----- grading -----

def grade(kind, row, answer, max_points, settings_data, partial, wrong):
    """(points, needs_manual, is_fully_correct) — same contract as views._grade_question."""
    full = (max_points, False, True)
    if kind == 'media_response':
        return 0, True, False
    if kind == 'numeric':
        return full if numeric_correct(settings_data.get('numeric') or {}, answer) else wrong()
    if kind == 'matrix':
        rows = [item for item in _json(row.get('options'), []) if isinstance(item, dict) and item.get('correct')]
        if not rows:
            return 0, True, False
        chosen = {}
        for part in ','.join(_answer_list(answer)).split(','):
            row_id, _, column = part.strip().partition(':')
            if row_id and column:
                chosen.setdefault(row_id, set()).add(column)
        weights = [(max(float(item.get('points') or 0), 0) or 1, chosen.get(item['id'], set()) == set(item['correct'])) for item in rows]
        return _weighted(weights, max_points, partial, full, wrong)
    if kind == 'image_label':
        markers = [item for item in _json(row.get('accepted_answers'), []) if isinstance(item, dict) and item.get('answer')]
        if not markers:
            return 0, True, False
        given = _answer_list(answer)
        synonyms = (settings_data.get('image_label') or {}).get('accept_synonyms', True)
        weights = []
        for index, marker in enumerate(markers):
            accepted = [marker['answer']] + (list(marker.get('synonyms') or []) if synonyms else [])
            text = given[index] if index < len(given) else ''
            hit = bool(text.strip()) and any(_normalize(text) == _normalize(item) for item in accepted)
            weights.append((max(float(marker.get('points') or 0), 0) or 1, hit))
        return _weighted(weights, max_points, partial, full, wrong)
    return 0, True, False


def _weighted(weights, max_points, partial, full, wrong):
    total = sum(weight for weight, _hit in weights)
    earned = sum(weight for weight, hit in weights if hit)
    if total and earned == total:
        return full
    if partial and total:
        return round(max_points * earned / total, 4), False, False
    return wrong()


def numeric_range(numeric):
    value = numeric.get('value')
    if value is None:
        return None
    tolerance = numeric.get('tolerance') or 0
    delta = abs(value) * tolerance / 100 if numeric.get('tolerance_mode') == 'percent' else tolerance
    return value - delta, value + delta


def numeric_correct(numeric, answer):
    bounds = numeric_range(numeric)
    parts = _answer_list(answer)
    text = (parts[0] if parts else '').strip()
    if not bounds or not text:
        return False
    if not numeric.get('accept_persian_digits', True) and _NON_LATIN_DIGIT_RE.search(text):
        return False
    number = _number(text)
    if number is None:
        return False
    if numeric.get('require_unit'):
        unit = parts[1] if len(parts) > 1 else ''
        if re.sub(r'\s+', '', unit).lower() != re.sub(r'\s+', '', numeric.get('unit') or '').lower():
            return False
    low, high = bounds
    return low - 1e-9 <= number <= high + 1e-9


# ----- student exam page -----

def student_view(kind, row, settings_data, answer, attempt_id):
    """Extra keys of the exam-page item; never includes correct answers."""
    seed = f"{attempt_id}-{row['question_id']}"
    given = _answer_list(answer)
    if kind == 'numeric':
        numeric = settings_data.get('numeric') or {}
        return {
            'numeric_unit': numeric.get('unit') or '',
            'numeric_require_unit': bool(numeric.get('require_unit')),
            'numeric_value': given[0] if given else '',
            'numeric_unit_value': given[1] if len(given) > 1 else '',
        }
    if kind == 'matrix':
        matrix = settings_data.get('matrix') or {}
        columns = [dict(column) for column in matrix.get('columns') or []]
        rows = [{'id': item['id'], 'text': item.get('text', '')} for item in _json(row.get('options'), []) if isinstance(item, dict) and item.get('id')]
        if matrix.get('shuffle_rows'):
            random.Random(f'{seed}-rows').shuffle(rows)
        if matrix.get('shuffle_columns'):
            random.Random(f'{seed}-columns').shuffle(columns)
        chosen = {part.strip() for part in ','.join(given).split(',') if part.strip()}
        for item in rows:
            item['cells'] = [
                {'id': column['id'], 'label': column['text'], 'value': f"{item['id']}:{column['id']}", 'checked': f"{item['id']}:{column['id']}" in chosen}
                for column in columns
            ]
        return {
            'matrix_columns': columns,
            'matrix_rows': rows,
            'matrix_multi': matrix.get('selection') == 'multi',
            'matrix_show_column_titles': matrix.get('show_column_titles', True),
            'matrix_show_row_titles': matrix.get('show_row_titles', True),
            'matrix_answer': ','.join(sorted(chosen)),
        }
    if kind == 'image_label':
        label = settings_data.get('image_label') or {}
        markers = [item for item in _json(row.get('accepted_answers'), []) if isinstance(item, dict) and 'marker' in item]
        bank = [item.get('answer') or '' for item in markers]
        random.Random(f'{seed}-bank').shuffle(bank)
        return {
            'label_markers': [
                {
                    'number': item['marker'],
                    # Pre-formatted so a localized number format can never break the inline style.
                    'left': f"{float(item.get('x', 50)):.2f}", 'top': f"{float(item.get('y', 50)):.2f}",
                    'value': given[index] if index < len(given) else '',
                }
                for index, item in enumerate(markers)
            ],
            'label_drag': label.get('answer_mode') == 'drag',
            'label_bank': [text for text in bank if text],
        }
    if kind == 'media_response':
        media_settings = settings_data.get('media_response') or {}
        max_plays = media_settings.get('max_plays') or 0
        return {
            'playback': {
                'max_plays': max_plays if media_settings.get('allow_replay', True) else 1,
                'start': media_settings.get('range_start'),
                'end': media_settings.get('range_end'),
            },
            'transcript': media_settings.get('transcript') if media_settings.get('show_transcript') else '',
            'attachment': media_settings.get('attachment') or None,
            'max_record_seconds': media_settings.get('max_record_seconds') or 120,
        }
    return {}
