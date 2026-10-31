from django.db import migrations


def _table_has_column(schema_editor, table_name, column_name):
    with schema_editor.connection.cursor() as cursor:
        columns = schema_editor.connection.introspection.get_table_description(cursor, table_name)
    return any(column.name == column_name for column in columns)


def add_column(apps, schema_editor):
    # «علامت‌گذاری برای مرور» on the exam page; the views already write it whenever this column exists.
    if _table_has_column(schema_editor, 'attempt_answers', 'marked_for_review'):
        return
    definition = 'boolean DEFAULT false' if schema_editor.connection.vendor == 'postgresql' else 'BOOLEAN DEFAULT 0'
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(f'ALTER TABLE attempt_answers ADD COLUMN marked_for_review {definition}')


def remove_column(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return  # SQLite: additive column left in place on rollback (matches migration 0032's convention)
    with schema_editor.connection.cursor() as cursor:
        cursor.execute('ALTER TABLE attempt_answers DROP COLUMN IF EXISTS marked_for_review')


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0052_practice_attempt_fields'),
    ]

    operations = [
        migrations.RunPython(add_column, remove_column),
    ]
