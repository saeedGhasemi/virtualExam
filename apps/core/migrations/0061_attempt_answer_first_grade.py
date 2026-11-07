"""«تصحیح توسط نمره‌دهنده دوم»: the first of two independent grades of an answer, kept until the second grader grades it.

attempt_answers.first_grade = {by, by_name, points, scores, feedback, at}; the final points are the mean of both grades.
"""
from django.db import migrations


def _has_column(schema_editor, table, column):
    with schema_editor.connection.cursor() as cursor:
        return any(item.name == column for item in schema_editor.connection.introspection.get_table_description(cursor, table))


def add_column(apps, schema_editor):
    if _has_column(schema_editor, 'attempt_answers', 'first_grade'):
        return
    json_type = 'jsonb' if schema_editor.connection.vendor == 'postgresql' else 'TEXT'
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(f'ALTER TABLE attempt_answers ADD COLUMN first_grade {json_type}')


def remove_column(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return  # SQLite: additive columns are left in place on rollback (project convention).
    with schema_editor.connection.cursor() as cursor:
        cursor.execute('ALTER TABLE attempt_answers DROP COLUMN IF EXISTS first_grade')


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0060_question_type_hotspot'),
    ]

    operations = [
        migrations.RunPython(add_column, remove_column),
    ]
