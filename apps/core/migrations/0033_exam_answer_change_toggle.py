from django.db import migrations


def _table_has_column(schema_editor, table_name, column_name):
    with schema_editor.connection.cursor() as cursor:
        columns = schema_editor.connection.introspection.get_table_description(cursor, table_name)
    return any(column.name == column_name for column in columns)


def add_columns(apps, schema_editor):
    vendor = schema_editor.connection.vendor
    boolean_type = 'boolean' if vendor == 'postgresql' else 'BOOLEAN'
    with schema_editor.connection.cursor() as cursor:
        if not _table_has_column(schema_editor, 'exams', 'allow_answer_changes'):
            cursor.execute(f"ALTER TABLE exams ADD COLUMN allow_answer_changes {boolean_type} DEFAULT true")


def remove_columns(apps, schema_editor):
    vendor = schema_editor.connection.vendor
    if vendor != 'postgresql':
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("ALTER TABLE exams DROP COLUMN IF EXISTS allow_answer_changes")


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0032_exam_wizard_fields'),
    ]

    operations = [
        migrations.RunPython(add_columns, remove_columns),
    ]
