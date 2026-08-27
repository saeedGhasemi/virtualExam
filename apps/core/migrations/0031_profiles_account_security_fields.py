from django.db import migrations


def _table_has_column(schema_editor, table_name, column_name):
    with schema_editor.connection.cursor() as cursor:
        columns = schema_editor.connection.introspection.get_table_description(cursor, table_name)
    return any(column.name == column_name for column in columns)


def add_columns(apps, schema_editor):
    vendor = schema_editor.connection.vendor
    boolean_type = 'boolean' if vendor == 'postgresql' else 'BOOLEAN'
    text_type = 'text' if vendor == 'postgresql' else 'TEXT'

    with schema_editor.connection.cursor() as cursor:
        if not _table_has_column(schema_editor, 'profiles', 'password_method'):
            cursor.execute(f"ALTER TABLE profiles ADD COLUMN password_method {text_type}")
        if not _table_has_column(schema_editor, 'profiles', 'must_change_password'):
            cursor.execute(f"ALTER TABLE profiles ADD COLUMN must_change_password {boolean_type}")
        if not _table_has_column(schema_editor, 'profiles', 'email_verified_required'):
            cursor.execute(f"ALTER TABLE profiles ADD COLUMN email_verified_required {boolean_type}")


def remove_columns(apps, schema_editor):
    vendor = schema_editor.connection.vendor
    if vendor != 'postgresql':
        # SQLite: left in place on rollback since it is additive and harmless to keep.
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("ALTER TABLE profiles DROP COLUMN IF EXISTS password_method")
        cursor.execute("ALTER TABLE profiles DROP COLUMN IF EXISTS must_change_password")
        cursor.execute("ALTER TABLE profiles DROP COLUMN IF EXISTS email_verified_required")


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0030_teacher_profiles_extended_fields'),
    ]

    operations = [
        migrations.RunPython(add_columns, remove_columns),
    ]
