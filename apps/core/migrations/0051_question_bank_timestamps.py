from django.db import migrations


# Question bank lifecycle columns, all empty for existing rows (their real times are unknown):
#   updated_at  - last save from the question editor or a bank action
#   archived_at - archived: hidden from the list and from new exams, restorable
#   shared_at   - shared with the other teachers of the question's course
COLUMNS = ('updated_at', 'archived_at', 'shared_at')


def existing_columns(cursor):
    cursor.execute('SELECT * FROM questions LIMIT 0')
    return {item[0] for item in cursor.description or []}


def add_columns(apps, schema_editor):
    column_type = 'timestamptz' if schema_editor.connection.vendor == 'postgresql' else 'TIMESTAMP'
    with schema_editor.connection.cursor() as cursor:
        present = existing_columns(cursor)
        for column in COLUMNS:
            if column not in present:
                cursor.execute(f'ALTER TABLE questions ADD COLUMN {column} {column_type} NULL')
        cursor.execute('CREATE INDEX IF NOT EXISTS questions_teacher_archived_idx ON questions (teacher_id, archived_at)')
        cursor.execute('CREATE INDEX IF NOT EXISTS questions_shared_course_idx ON questions (course_id, shared_at)')


def drop_columns(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute('DROP INDEX IF EXISTS questions_teacher_archived_idx')
        cursor.execute('DROP INDEX IF EXISTS questions_shared_course_idx')
        present = existing_columns(cursor)
        for column in COLUMNS:
            if column in present:
                cursor.execute(f'ALTER TABLE questions DROP COLUMN {column}')


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0050_exam_results_published_at'),
    ]

    operations = [
        migrations.RunPython(add_columns, drop_columns),
    ]
