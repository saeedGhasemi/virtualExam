from django.db import migrations


# «نمایش تصویر پروفایل برای استاد» on the student's settings page. Defaults to true, so existing students keep
# showing their photo until they switch it off.
COLUMN = 'show_avatar_to_teacher'


def column_exists(cursor, table, column):
    cursor.execute(f'SELECT * FROM {table} LIMIT 0')
    return column in {item[0] for item in cursor.description or []}


def add_column(apps, schema_editor):
    is_pg = schema_editor.connection.vendor == 'postgresql'
    with schema_editor.connection.cursor() as cursor:
        if not column_exists(cursor, 'student_profiles', COLUMN):
            cursor.execute(f'ALTER TABLE student_profiles ADD COLUMN {COLUMN} {"boolean" if is_pg else "BOOLEAN"} DEFAULT true')


def remove_column(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return  # SQLite: additive columns are left in place on rollback
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(f'ALTER TABLE student_profiles DROP COLUMN IF EXISTS {COLUMN}')


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0046_two_factor'),
    ]

    operations = [
        migrations.RunPython(add_column, remove_column),
    ]
