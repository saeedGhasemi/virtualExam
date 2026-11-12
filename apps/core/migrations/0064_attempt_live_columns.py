"""Live exam management (`apps/core/exam_hub.py`), kept on `exam_attempts`.

extra_minutes: «افزودن زمان» — minutes the teacher / academic manager gave this one attempt on top of the exam's
duration (and past the exam's end); `_sx_attempt_ends_at` adds them.
last_seen_at: the last time the open exam page checked in (`student_attempt_live`, every ~20 s); «متصل» on the live
monitor means it checked in recently.
"""
from django.db import migrations


def _has_column(schema_editor, table, column):
    with schema_editor.connection.cursor() as cursor:
        return any(item.name == column for item in schema_editor.connection.introspection.get_table_description(cursor, table))


def add_columns(apps, schema_editor):
    postgres = schema_editor.connection.vendor == 'postgresql'
    columns = {
        'extra_minutes': 'integer NOT NULL DEFAULT 0' if postgres else 'INTEGER NOT NULL DEFAULT 0',
        'last_seen_at': 'timestamptz' if postgres else 'TEXT',
    }
    with schema_editor.connection.cursor() as cursor:
        for column, definition in columns.items():
            if not _has_column(schema_editor, 'exam_attempts', column):
                cursor.execute(f'ALTER TABLE exam_attempts ADD COLUMN {column} {definition}')


def remove_columns(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return  # SQLite: additive columns are left in place on rollback (project convention).
    with schema_editor.connection.cursor() as cursor:
        cursor.execute('ALTER TABLE exam_attempts DROP COLUMN IF EXISTS extra_minutes')
        cursor.execute('ALTER TABLE exam_attempts DROP COLUMN IF EXISTS last_seen_at')


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0063_auth_events'),
    ]

    operations = [
        migrations.RunPython(add_columns, remove_columns),
    ]
