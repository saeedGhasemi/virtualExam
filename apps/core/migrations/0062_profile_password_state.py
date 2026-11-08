"""Password state of each account, kept on `profiles`.

password_changed_at: when the login password was last set (by the user or by a super admin); shown as «آخرین تغییر».
password_change_required: a super admin set a temporary password; the user must choose a new one before using the site
(enforced by `PasswordChangeRequiredMiddleware`). The older must_change_password columns on the role tables are wizard
leftovers that were never enforced, so they are not reused.
"""
from django.db import migrations


def _has_column(schema_editor, table, column):
    with schema_editor.connection.cursor() as cursor:
        return any(item.name == column for item in schema_editor.connection.introspection.get_table_description(cursor, table))


def add_columns(apps, schema_editor):
    postgres = schema_editor.connection.vendor == 'postgresql'
    columns = {
        'password_changed_at': 'timestamptz' if postgres else 'TEXT',
        'password_change_required': 'boolean NOT NULL DEFAULT false' if postgres else 'BOOLEAN NOT NULL DEFAULT 0',
    }
    with schema_editor.connection.cursor() as cursor:
        for column, definition in columns.items():
            if not _has_column(schema_editor, 'profiles', column):
                cursor.execute(f'ALTER TABLE profiles ADD COLUMN {column} {definition}')


def remove_columns(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return  # SQLite: additive columns are left in place on rollback (project convention).
    with schema_editor.connection.cursor() as cursor:
        cursor.execute('ALTER TABLE profiles DROP COLUMN IF EXISTS password_changed_at')
        cursor.execute('ALTER TABLE profiles DROP COLUMN IF EXISTS password_change_required')


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0061_attempt_answer_first_grade'),
    ]

    operations = [
        migrations.RunPython(add_columns, remove_columns),
    ]
