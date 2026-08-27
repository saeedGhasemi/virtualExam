from django.db import migrations


def _table_has_column(schema_editor, table_name, column_name):
    with schema_editor.connection.cursor() as cursor:
        columns = schema_editor.connection.introspection.get_table_description(cursor, table_name)
    return any(column.name == column_name for column in columns)


def add_academic_rank(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        if not _table_has_column(schema_editor, 'teacher_profiles', 'academic_rank'):
            cursor.execute("ALTER TABLE teacher_profiles ADD COLUMN academic_rank TEXT")


def remove_academic_rank(apps, schema_editor):
    vendor = schema_editor.connection.vendor
    if vendor != 'postgresql':
        # SQLite: left in place on rollback since it is additive and harmless to keep.
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("ALTER TABLE teacher_profiles DROP COLUMN IF EXISTS academic_rank")


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0028_profiles_gender_birth_date'),
    ]

    operations = [
        migrations.RunPython(add_academic_rank, remove_academic_rank),
    ]
