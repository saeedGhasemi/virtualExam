from django.db import migrations


def _table_has_column(schema_editor, table_name, column_name):
    with schema_editor.connection.cursor() as cursor:
        columns = schema_editor.connection.introspection.get_table_description(cursor, table_name)
    return any(column.name == column_name for column in columns)


def _columns(is_pg):
    json_type = 'jsonb' if is_pg else 'TEXT'
    return [
        # Student uploads for essay answers: [{id, name, kind, ext, size, path}] under PRIVATE_MEDIA_ROOT.
        ('answer_files', f"{json_type} NOT NULL DEFAULT '[]'"),
        # Manual grading of essay answers.
        ('rubric_scores', f"{json_type}"),
        ('grader_feedback', 'TEXT'),
        ('graded_by', 'uuid REFERENCES profiles(id)' if is_pg else 'TEXT'),
        ('graded_at', 'timestamptz' if is_pg else 'TEXT'),
    ]


def add_columns(apps, schema_editor):
    is_pg = schema_editor.connection.vendor == 'postgresql'
    with schema_editor.connection.cursor() as cursor:
        for column, definition in _columns(is_pg):
            if not _table_has_column(schema_editor, 'attempt_answers', column):
                cursor.execute(f'ALTER TABLE attempt_answers ADD COLUMN {column} {definition}')
        cursor.execute(
            'CREATE INDEX IF NOT EXISTS attempt_answers_manual_idx ON attempt_answers (question_id) WHERE needs_manual_grading'
        )


def remove_columns(apps, schema_editor):
    is_pg = schema_editor.connection.vendor == 'postgresql'
    with schema_editor.connection.cursor() as cursor:
        cursor.execute('DROP INDEX IF EXISTS attempt_answers_manual_idx')
        if not is_pg:
            return  # SQLite: additive columns are left in place on rollback (project convention).
        for column, _definition in _columns(is_pg):
            cursor.execute(f'ALTER TABLE attempt_answers DROP COLUMN IF EXISTS {column}')


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0039_osce_template_sharing'),
    ]

    operations = [
        migrations.RunPython(add_columns, remove_columns),
    ]
