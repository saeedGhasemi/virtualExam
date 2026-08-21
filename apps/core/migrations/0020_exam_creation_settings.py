from django.db import migrations


EXAM_COLUMNS = [
    ('result_release_mode', "text DEFAULT 'after_exam'"),
    ('review_answers_enabled', 'boolean DEFAULT false'),
    ('show_instructions_before_start', 'boolean DEFAULT true'),
    ('autosave_enabled', 'boolean DEFAULT true'),
    ('fullscreen_required', 'boolean DEFAULT false'),
    ('track_tab_exit', 'boolean DEFAULT true'),
    ('show_correct_answers', 'boolean DEFAULT false'),
    ('show_score', 'boolean DEFAULT true'),
    ('show_feedback', 'boolean DEFAULT true'),
    ('publish_mode', "text DEFAULT 'draft'"),
]


def column_exists(cursor, table, column):
    cursor.execute(f"SELECT * FROM {table} LIMIT 0")
    return column in {item[0] for item in cursor.description or []}


def add_exam_columns(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        for column, definition in EXAM_COLUMNS:
            if not column_exists(cursor, 'exams', column):
                cursor.execute(f'ALTER TABLE exams ADD COLUMN {column} {definition}')


def remove_exam_columns(apps, schema_editor):
    if schema_editor.connection.vendor == 'sqlite':
        return
    with schema_editor.connection.cursor() as cursor:
        for column, _definition in EXAM_COLUMNS:
            cursor.execute(f'ALTER TABLE exams DROP COLUMN IF EXISTS {column}')


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0019_manager_wizard_fields'),
    ]

    operations = [
        migrations.RunPython(add_exam_columns, remove_exam_columns),
    ]
