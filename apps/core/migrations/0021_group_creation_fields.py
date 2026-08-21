from django.db import migrations


GROUP_COLUMNS = [
    ('capacity', 'integer DEFAULT 30'),
    ('min_students', 'integer DEFAULT 10'),
    ('waitlist_enabled', 'boolean DEFAULT false'),
    ('waitlist_capacity', 'integer DEFAULT 0'),
    ('requires_teacher_approval', 'boolean DEFAULT false'),
    ('offering_type', "text DEFAULT 'theory'"),
    ('class_schedule', 'text'),
    ('class_location', 'text'),
    ('registration_start_at', 'timestamp'),
    ('registration_end_at', 'timestamp'),
    ('status', "text DEFAULT 'draft'"),
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
        ('core', '0020_exam_creation_settings'),
    ]

    operations = [
        migrations.RunPython(add_group_columns, remove_group_columns),
    ]
