from django.db import migrations

# Columns the exam wizard's settings need so that they take effect (the views read each one only when it exists):
#   exams.total_score         «مجموع نمرات کل آزمون»: the scale scores are reported on (NULL: out of 20, as before)
#   exams.passing_percent     «نمره قبولی (حداقل درصد)» (NULL: the legacy passing_score rule)
#   exam_attempts.furthest_question  furthest question reached; «امکان بازگشت به سوال قبلی» off keeps the student there
#   attempt_answers.locked_at        «امکان تغییر پاسخ» off: the answer stopped accepting changes at this time
#   exams.settings_enforced          the wizard saved this exam's settings, so they apply. The settings columns have
#                                    defaults (camera on, …) that every other exam also carries; those exams keep the
#                                    behaviour they always had until they are saved through the wizard.
COLUMNS = (
    ('exams', 'settings_enforced', 'boolean', 'BOOLEAN'),
    ('exams', 'total_score', 'numeric', 'NUMERIC'),
    ('exams', 'passing_percent', 'numeric', 'NUMERIC'),
    ('exam_attempts', 'furthest_question', 'integer DEFAULT 1', 'INTEGER DEFAULT 1'),
    ('attempt_answers', 'locked_at', 'timestamp with time zone', 'TIMESTAMP'),
)


def _table_has_column(schema_editor, table_name, column_name):
    with schema_editor.connection.cursor() as cursor:
        columns = schema_editor.connection.introspection.get_table_description(cursor, table_name)
    return any(column.name == column_name for column in columns)


def add_columns(apps, schema_editor):
    postgres = schema_editor.connection.vendor == 'postgresql'
    for table, column, pg_type, sqlite_type in COLUMNS:
        if _table_has_column(schema_editor, table, column):
            continue
        with schema_editor.connection.cursor() as cursor:
            cursor.execute(f'ALTER TABLE {table} ADD COLUMN {column} {pg_type if postgres else sqlite_type}')


def remove_columns(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return  # SQLite: additive columns left in place on rollback (matches migration 0032's convention)
    with schema_editor.connection.cursor() as cursor:
        for table, column, _pg_type, _sqlite_type in COLUMNS:
            cursor.execute(f'ALTER TABLE {table} DROP COLUMN IF EXISTS {column}')


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0056_questions_owner_any_profile'),
    ]

    operations = [
        migrations.RunPython(add_columns, remove_columns),
    ]
