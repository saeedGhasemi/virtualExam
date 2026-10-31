from django.db import migrations


def _table_has_column(schema_editor, table_name, column_name):
    with schema_editor.connection.cursor() as cursor:
        columns = schema_editor.connection.introspection.get_table_description(cursor, table_name)
    return any(column.name == column_name for column in columns)


# (table, column, postgres type, sqlite type) — additive only; existing rows keep NULL.
COLUMNS = [
    # «حالت آموزشی» / «حالت شبیه‌ساز» chosen by the student when starting a practice attempt.
    ('exam_attempts', 'practice_mode', 'text', 'TEXT'),
    # When the tutorial mode showed this answer's feedback; the answer is locked from then on.
    ('attempt_answers', 'feedback_shown_at', 'timestamptz', 'TEXT'),
]


def add_columns(apps, schema_editor):
    postgres = schema_editor.connection.vendor == 'postgresql'
    with schema_editor.connection.cursor() as cursor:
        for table, column, pg_type, sqlite_type in COLUMNS:
            if not _table_has_column(schema_editor, table, column):
                cursor.execute(f'ALTER TABLE {table} ADD COLUMN {column} {pg_type if postgres else sqlite_type}')


def remove_columns(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        # SQLite: additive columns left in place on rollback (matches migration 0032's convention).
        return
    with schema_editor.connection.cursor() as cursor:
        for table, column, _pg_type, _sqlite_type in COLUMNS:
            cursor.execute(f'ALTER TABLE {table} DROP COLUMN IF EXISTS {column}')


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0051_question_bank_timestamps'),
    ]

    operations = [
        migrations.RunPython(add_columns, remove_columns),
    ]
