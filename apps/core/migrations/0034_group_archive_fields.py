from django.db import migrations


GROUP_COLUMNS = [
    ('is_archived', 'boolean DEFAULT false'),
    ('archived_at', 'timestamp'),
]


def column_exists(cursor, table, column):
    cursor.execute(f"SELECT * FROM {table} LIMIT 0")
    return column in {item[0] for item in cursor.description or []}


def add_group_columns(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        for column, definition in GROUP_COLUMNS:
            if not column_exists(cursor, 'student_groups', column):
                cursor.execute(f'ALTER TABLE student_groups ADD COLUMN {column} {definition}')


def remove_group_columns(apps, schema_editor):
    if schema_editor.connection.vendor == 'sqlite':
        return
    with schema_editor.connection.cursor() as cursor:
        for column, _definition in GROUP_COLUMNS:
            cursor.execute(f'ALTER TABLE student_groups DROP COLUMN IF EXISTS {column}')


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0033_exam_answer_change_toggle'),
    ]

    operations = [
        migrations.RunPython(add_group_columns, remove_group_columns),
    ]
