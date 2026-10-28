from django.db import migrations


# Personal details a teacher edits on the «اطلاعات فردی» settings tab. All nullable: existing rows are untouched.
NEW_COLUMNS = [
    ('display_name', 'text'),
    ('degree', 'text'),
    ('landline', 'text'),
    ('bio', 'text'),
    ('show_bio', 'boolean'),
]


def column_exists(cursor, table, column):
    cursor.execute(f'SELECT * FROM {table} LIMIT 0')
    return column in {item[0] for item in cursor.description or []}


def add_columns(apps, schema_editor):
    is_pg = schema_editor.connection.vendor == 'postgresql'
    with schema_editor.connection.cursor() as cursor:
        for column, column_type in NEW_COLUMNS:
            if not column_exists(cursor, 'teacher_profiles', column):
                sql_type = column_type if is_pg else column_type.upper()
                default = ' DEFAULT true' if column_type == 'boolean' else ''
                cursor.execute(f'ALTER TABLE teacher_profiles ADD COLUMN {column} {sql_type}{default}')


def remove_columns(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return  # SQLite: additive columns are left in place on rollback
    with schema_editor.connection.cursor() as cursor:
        for column, _column_type in NEW_COLUMNS:
            cursor.execute(f'ALTER TABLE teacher_profiles DROP COLUMN IF EXISTS {column}')


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0042_teacher_student_notes'),
    ]

    operations = [
        migrations.RunPython(add_columns, remove_columns),
    ]
