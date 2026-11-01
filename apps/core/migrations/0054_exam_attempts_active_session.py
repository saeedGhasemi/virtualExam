from django.db import migrations


def _table_has_column(schema_editor, table_name, column_name):
    with schema_editor.connection.cursor() as cursor:
        columns = schema_editor.connection.introspection.get_table_description(cursor, table_name)
    return any(column.name == column_name for column in columns)


def add_column(apps, schema_editor):
    # The session (device) an attempt is bound to; answers from any other session are refused until it takes over.
    if _table_has_column(schema_editor, 'exam_attempts', 'active_session_key'):
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute('ALTER TABLE exam_attempts ADD COLUMN active_session_key varchar(64)')


def remove_column(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return  # SQLite: additive column left in place on rollback (matches migration 0032's convention)
    with schema_editor.connection.cursor() as cursor:
        cursor.execute('ALTER TABLE exam_attempts DROP COLUMN IF EXISTS active_session_key')


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0053_attempt_answers_marked_for_review'),
    ]

    operations = [
        migrations.RunPython(add_column, remove_column),
    ]
