import re

from django.db import migrations


OLD_TYPES = ('single', 'multi', 'true_false', 'short_answer', 'essay', 'fill_blank', 'matching', 'ordering')
NEW_TYPES = OLD_TYPES + ('numeric', 'matrix', 'image_label', 'media_response')


def _check_sql(types):
    return 'type IN (' + ','.join(f"'{value}'" for value in types) + ')'


def _rebuild_sqlite_questions(schema_editor, old_types, new_types):
    """SQLite cannot alter a CHECK constraint: rebuild `questions` from its own DDL with the new type list."""
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'questions'")
        row = cursor.fetchone()
        if not row:
            return
        ddl = row[0]
        old_check, new_check = _check_sql(old_types), _check_sql(new_types)
        if old_check not in ddl:
            if new_check in ddl:
                return
            raise RuntimeError('questions.type CHECK constraint has an unexpected definition; rebuild aborted.')
        cursor.execute("SELECT sql FROM sqlite_master WHERE type = 'index' AND tbl_name = 'questions' AND sql IS NOT NULL")
        index_sql = [item[0] for item in cursor.fetchall()]
        cursor.execute('PRAGMA table_info(questions)')
        columns = ', '.join(f'"{item[1]}"' for item in cursor.fetchall())
        rebuilt = re.sub(r'^CREATE TABLE\s+["`]?questions["`]?', 'CREATE TABLE questions_types_rebuild', ddl.replace(old_check, new_check), count=1)
        cursor.execute(rebuilt)
        cursor.execute(f'INSERT INTO questions_types_rebuild ({columns}) SELECT {columns} FROM questions')
        cursor.execute('DROP TABLE questions')
        cursor.execute('ALTER TABLE questions_types_rebuild RENAME TO questions')
        for statement in index_sql:
            cursor.execute(statement)


def _replace_postgres_check(schema_editor, types):
    with schema_editor.connection.cursor() as cursor:
        # The original constraint is auto-named; drop every CHECK on questions that guards the `type` column.
        cursor.execute(
            """
            SELECT conname FROM pg_constraint
            WHERE conrelid = 'questions'::regclass AND contype = 'c'
              AND pg_get_constraintdef(oid) ILIKE '%%type%%single%%'
            """
        )
        for (name,) in cursor.fetchall():
            cursor.execute(f'ALTER TABLE questions DROP CONSTRAINT "{name}"')
        cursor.execute(f'ALTER TABLE questions ADD CONSTRAINT questions_type_check CHECK ({_check_sql(types)})')


def add_question_types(apps, schema_editor):
    vendor = schema_editor.connection.vendor
    if vendor == 'sqlite':
        _rebuild_sqlite_questions(schema_editor, OLD_TYPES, NEW_TYPES)
    elif vendor == 'postgresql':
        _replace_postgres_check(schema_editor, NEW_TYPES)


def remove_question_types(apps, schema_editor):
    vendor = schema_editor.connection.vendor
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            'SELECT COUNT(*) FROM questions WHERE type IN (' + ','.join(['%s'] * 4) + ')',
            list(NEW_TYPES[len(OLD_TYPES):]),
        )
        if cursor.fetchone()[0]:
            raise RuntimeError('Questions of the new types exist; delete them before reversing this migration.')
    if vendor == 'sqlite':
        _rebuild_sqlite_questions(schema_editor, NEW_TYPES, OLD_TYPES)
    elif vendor == 'postgresql':
        _replace_postgres_check(schema_editor, OLD_TYPES)


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0040_attempt_answer_files_and_grading'),
    ]

    operations = [
        migrations.RunPython(add_question_types, remove_question_types),
    ]
