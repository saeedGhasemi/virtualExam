import json
import logging

from django.db import migrations

logger = logging.getLogger(__name__)

# Some single-choice questions saved by the old form flag two options as correct while correct_answer names
# one. Grading has always used correct_answer, but the editor ticks both and saving keeps an arbitrary one.
# The option flags are aligned with correct_answer (what students were graded on); the original options are
# kept under scoring_settings[LEGACY_KEY] so the migration can be reversed.

LEGACY_KEY = '_legacy_options'
KINDS = ('single', 'true_false')


def _load(value, default):
    if value is None or value == '':
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return value if isinstance(value, str) else default


def align_correct_flags(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "SELECT id, options, correct_answer, scoring_settings FROM questions WHERE type IN (%s, %s)", list(KINDS)
        )
        for question_id, raw_options, raw_correct, raw_settings in cursor.fetchall():
            options = _load(raw_options, [])
            if not isinstance(options, list) or not all(isinstance(option, dict) for option in options):
                continue
            correct = str(_load(raw_correct, '') or '').strip()
            ids = [str(option.get('id') or index) for index, option in enumerate(options, start=1)]
            flagged = [option_id for option_id, option in zip(ids, options) if option.get('is_correct')]
            if flagged == [correct]:
                continue
            if correct not in ids:
                logger.warning('Question %s: correct_answer %r names no option; flags left as they are.', question_id, correct)
                continue
            settings = _load(raw_settings, {})
            settings = dict(settings) if isinstance(settings, dict) else {}
            settings[LEGACY_KEY] = options
            aligned = [dict(option, is_correct=option_id == correct) for option_id, option in zip(ids, options)]
            cursor.execute(
                'UPDATE questions SET options = %s, scoring_settings = %s WHERE id = %s',
                [json.dumps(aligned, ensure_ascii=False), json.dumps(settings, ensure_ascii=False), question_id],
            )


def restore_correct_flags(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute('SELECT id, scoring_settings FROM questions WHERE type IN (%s, %s)', list(KINDS))
        for question_id, raw_settings in cursor.fetchall():
            settings = _load(raw_settings, {})
            if not isinstance(settings, dict) or LEGACY_KEY not in settings:
                continue
            options = settings.pop(LEGACY_KEY)
            cursor.execute(
                'UPDATE questions SET options = %s, scoring_settings = %s WHERE id = %s',
                [json.dumps(options, ensure_ascii=False), json.dumps(settings, ensure_ascii=False), question_id],
            )


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0048_legacy_question_formats'),
    ]

    operations = [
        migrations.RunPython(align_correct_flags, restore_correct_flags),
    ]
