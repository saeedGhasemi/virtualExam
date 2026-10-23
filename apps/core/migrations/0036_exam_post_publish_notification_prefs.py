from django.db import migrations


def _table_has_column(schema_editor, table_name, column_name):
    with schema_editor.connection.cursor() as cursor:
        columns = schema_editor.connection.introspection.get_table_description(cursor, table_name)
    return any(column.name == column_name for column in columns)


EXAM_COLUMNS = [
    ('notify_students_system_message', 'boolean DEFAULT true'),
    ('notify_students_email', 'boolean DEFAULT true'),
    ('show_in_academic_calendar', 'boolean DEFAULT false'),
]


def add_columns(apps, schema_editor):
    vendor = schema_editor.connection.vendor
    with schema_editor.connection.cursor() as cursor:
        for column, definition in EXAM_COLUMNS:
            if not _table_has_column(schema_editor, 'exams', column):
                col_def = definition
                if vendor != 'postgresql':
                    col_def = col_def.replace('boolean', 'BOOLEAN')
                cursor.execute(f'ALTER TABLE exams ADD COLUMN {column} {col_def}')


def remove_columns(apps, schema_editor):
    vendor = schema_editor.connection.vendor
    if vendor != 'postgresql':
        # SQLite: additive columns left in place on rollback (matches migration 0032's convention).
        return
    with schema_editor.connection.cursor() as cursor:
        for column, _definition in EXAM_COLUMNS:
            cursor.execute(f'ALTER TABLE exams DROP COLUMN IF EXISTS {column}')


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0035_exam_assignment_exclusions'),
    ]

    operations = [
        migrations.RunPython(add_columns, remove_columns),
    ]
