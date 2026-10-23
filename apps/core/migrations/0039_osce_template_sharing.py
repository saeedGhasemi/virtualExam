from django.db import migrations


def _table_has_column(schema_editor, table_name, column_name):
    with schema_editor.connection.cursor() as cursor:
        columns = schema_editor.connection.introspection.get_table_description(cursor, table_name)
    return any(column.name == column_name for column in columns)


def add_column(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        if not _table_has_column(schema_editor, 'osce_criteria_templates', 'is_shared'):
            # Shared templates form the org-unit library («بارگذاری از کتابخانه»).
            cursor.execute('ALTER TABLE osce_criteria_templates ADD COLUMN is_shared BOOLEAN NOT NULL DEFAULT FALSE')
        cursor.execute(
            'CREATE INDEX IF NOT EXISTS osce_criteria_templates_shared_idx '
            'ON osce_criteria_templates (teacher_id) WHERE is_shared'
        )


def remove_column(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute('DROP INDEX IF EXISTS osce_criteria_templates_shared_idx')
        if schema_editor.connection.vendor == 'postgresql':
            cursor.execute('ALTER TABLE osce_criteria_templates DROP COLUMN IF EXISTS is_shared')


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0038_osce_criteria_templates'),
    ]

    operations = [
        migrations.RunPython(add_column, remove_column),
    ]
