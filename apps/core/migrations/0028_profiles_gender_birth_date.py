from django.db import migrations


def _table_has_column(schema_editor, table_name, column_name):
    with schema_editor.connection.cursor() as cursor:
        columns = schema_editor.connection.introspection.get_table_description(cursor, table_name)
    return any(column.name == column_name for column in columns)


def add_gender_birth_date(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        if not _table_has_column(schema_editor, 'profiles', 'gender'):
            cursor.execute("ALTER TABLE profiles ADD COLUMN gender TEXT")
        if not _table_has_column(schema_editor, 'profiles', 'birth_date'):
            cursor.execute("ALTER TABLE profiles ADD COLUMN birth_date TEXT")


def remove_gender_birth_date(apps, schema_editor):
    vendor = schema_editor.connection.vendor
    if vendor != 'postgresql':
        # SQLite: left in place on rollback since it is additive and harmless to keep.
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("ALTER TABLE profiles DROP COLUMN IF EXISTS gender")
        cursor.execute("ALTER TABLE profiles DROP COLUMN IF EXISTS birth_date")


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0027_activity_audit_log_created_at'),
    ]

    operations = [
        migrations.RunPython(add_gender_birth_date, remove_gender_birth_date),
    ]
