import json
import logging
import re

from django.db import migrations

logger = logging.getLogger(__name__)

# Questions saved by the first question form keep their settings in a shape the grader no longer reads:
#   scoring_settings.partial_credit           -> grader reads scoring_mode
#   no negative_value                         -> grader takes the penalty from negative_value
#   short answers {answer, points=raw score}  -> grader needs match_mode, points as a credit percentage
#   fill blanks {answer, points} (no blanks)  -> grader needs one {answers: [...]} entry per blank
# The question editor already shows these rows to the teacher with the new meaning (partial credit on, the
# negative_points column as penalty, ...), so each row is converted to what saving it unchanged in the editor
# would store. The original values are kept under LEGACY_KEY so the migration can be reversed.

LEGACY_KEY = '_legacy_format'
BLANK_MARKER_RE = re.compile(r'\[[۰۱۲۳۴۵۶۷۸۹0-9]+\]')
DEFAULT_NEGATIVE_VALUE = 0.25  # the editor's default penalty when none is stored


def _load(value, default):
    if value is None or value == '':
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def _number(value, default):
    try:
        return float(str(value).strip()) if value not in (None, '') else default  # float() accepts Persian digits
    except ValueError:
        return default


def _short_answers(items, max_points):
    """Raw scores become a credit percentage of the question's points (2 of 2 -> 100, 1 of 2 -> 50)."""
    converted = []
    for item in items:
        raw = _number(item.get('points'), None)
        percent = 100.0 if raw is None or max_points <= 0 else min(max(raw / max_points * 100, 0), 100)
        converted.append({
            'answer': item.get('answer', ''), 'points': round(percent, 2), 'match_mode': 'exact',
            'case_sensitive': False, 'normalize': True, 'tolerance': 0, 'typo_tolerance': 0, 'ignore_word_order': False,
        })
    return converted


def _blanks(items, text):
    """The old form had one shared «accepted answers» list. With a single blank its rows are alternatives for that
    blank; with several blanks they map one row per blank only when the counts match. Otherwise None (left as is)."""
    answers = [str(item.get('answer', '')).strip() for item in items if str(item.get('answer', '')).strip()]
    marker_count = len(BLANK_MARKER_RE.findall(text or ''))
    if marker_count <= 1:
        groups = [answers]
    elif len(answers) == marker_count:
        groups = [[answer] for answer in answers]
    else:
        return None
    return [
        {'blank': index, 'answers': group, 'points': 1.0, 'case_sensitive': False, 'ignore_spaces': True}
        for index, group in enumerate(groups, start=1)
    ]


def convert_legacy_questions(apps, schema_editor):
    connection = schema_editor.connection
    with connection.cursor() as cursor:
        cursor.execute('SELECT * FROM questions LIMIT 0')
        columns = {column[0] for column in cursor.description or []}
        if not {'scoring_settings', 'accepted_answers'}.issubset(columns):
            return
        cursor.execute(
            'SELECT id, type, text, default_points, negative_points, scoring_settings, accepted_answers, correct_answer '
            'FROM questions'
        )
        rows = cursor.fetchall()
        for question_id, kind, text, default_points, negative_points, raw_settings, raw_accepted, correct_answer in rows:
            settings = _load(raw_settings, {})
            settings = dict(settings) if isinstance(settings, dict) else {}  # a copy: jsonb returns the stored dict
            if 'scoring_mode' in settings or LEGACY_KEY in settings:
                continue  # saved by the current editor, or already converted
            accepted = _load(raw_accepted, [])
            accepted = [item for item in accepted if isinstance(item, dict)] if isinstance(accepted, list) else []
            # Raw column values, kept as read so the reverse can write them back unchanged.
            legacy = {'scoring_settings': raw_settings, 'accepted_answers': raw_accepted, 'correct_answer': correct_answer}

            settings['scoring_mode'] = 'partial' if settings.get('partial_credit', True) else 'all_or_nothing'
            if 'negative_value' not in settings:
                stored = abs(_number(negative_points, 0))
                settings['negative_value'] = min(stored or DEFAULT_NEGATIVE_VALUE, 1)  # the form allows 0..1 of the points
            new_accepted, new_correct = None, None
            if kind == 'short_answer' and accepted and not any('match_mode' in item for item in accepted):
                new_accepted = _short_answers(accepted, _number(default_points, 1))
            elif kind == 'fill_blank' and accepted and not any('answers' in item for item in accepted):
                new_accepted = _blanks(accepted, text)
                if new_accepted is None:
                    logger.warning('Question %s: %s accepted answers for a multi-blank stem; left unconverted.', question_id, len(accepted))
                else:
                    new_correct = '|'.join(blank['answers'][0] if blank['answers'] else '' for blank in new_accepted)
            settings[LEGACY_KEY] = legacy

            assignments, params = ['scoring_settings = %s'], [json.dumps(settings, ensure_ascii=False)]
            if new_accepted is not None:
                assignments.append('accepted_answers = %s')
                params.append(json.dumps(new_accepted, ensure_ascii=False))
            if new_correct is not None:
                assignments.append('correct_answer = %s')
                params.append(json.dumps(new_correct, ensure_ascii=False))
            cursor.execute(f"UPDATE questions SET {', '.join(assignments)} WHERE id = %s", [*params, question_id])


def _stored(value):
    # Django's psycopg 3 cursor reads jsonb as JSON text (as SQLite does); only a Python value needs encoding again.
    return value if value is None or isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def restore_legacy_questions(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute('SELECT * FROM questions LIMIT 0')
        if 'scoring_settings' not in {column[0] for column in cursor.description or []}:
            return
        cursor.execute('SELECT id, scoring_settings FROM questions')
        for question_id, raw_settings in cursor.fetchall():
            settings = _load(raw_settings, {})
            legacy = settings.get(LEGACY_KEY) if isinstance(settings, dict) else None
            if not legacy:
                continue
            cursor.execute(
                'UPDATE questions SET scoring_settings = %s, accepted_answers = %s, correct_answer = %s WHERE id = %s',
                [
                    *(_stored(legacy[key]) for key in ('scoring_settings', 'accepted_answers', 'correct_answer')),
                    question_id,
                ],
            )


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0047_student_avatar_privacy'),
    ]

    operations = [
        migrations.RunPython(convert_legacy_questions, restore_legacy_questions),
    ]
