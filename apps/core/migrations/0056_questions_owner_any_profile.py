import re

from django.db import migrations

# questions.teacher_id is the question's owner. System admins and academic managers keep a question bank too, and they
# have no teacher_profiles row, so the owner now references profiles(id). Every existing owner is a teacher, and every
# teacher_profiles.user_id is a profiles.id, so existing rows satisfy the new key.
TEACHER_REF = 'REFERENCES teacher_profiles(user_id)'
PROFILE_REF = 'REFERENCES profiles(id)'


def _rebuild_sqlite_questions(schema_editor, old_ref, new_ref):
    """SQLite cannot alter a foreign key: rebuild `questions` from its own DDL (as migration 0041 does)."""
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'questions'")
        row = cursor.fetchone()
        if not row:
            return
        ddl = row[0]
        pattern = re.compile(r'(teacher_id\s+\w+\s+)' + re.escape(old_ref))
        if not pattern.search(ddl):
            if re.search(r'teacher_id\s+\w+\s+' + re.escape(new_ref), ddl):
                return
            raise RuntimeError('questions.teacher_id has an unexpected definition; rebuild aborted.')
        cursor.execute("SELECT sql FROM sqlite_master WHERE type = 'index' AND tbl_name = 'questions' AND sql IS NOT NULL")
        index_sql = [item[0] for item in cursor.fetchall()]
        cursor.execute('PRAGMA table_info(questions)')
        columns = ', '.join(f'"{item[1]}"' for item in cursor.fetchall())
        rebuilt = re.sub(r'^CREATE TABLE\s+["`]?questions["`]?', 'CREATE TABLE questions_owner_rebuild', pattern.sub(r'\g<1>' + new_ref, ddl, count=1), count=1)
        cursor.execute(rebuilt)
        cursor.execute(f'INSERT INTO questions_owner_rebuild ({columns}) SELECT {columns} FROM questions')
        cursor.execute('DROP TABLE questions')
        cursor.execute('ALTER TABLE questions_owner_rebuild RENAME TO questions')
        for statement in index_sql:
            cursor.execute(statement)


def _replace_postgres_key(schema_editor, target):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT conname FROM pg_constraint
            WHERE conrelid = 'questions'::regclass AND contype = 'f' AND pg_get_constraintdef(oid) ILIKE 'FOREIGN KEY (teacher_id)%%'
            """
        )
        for (name,) in cursor.fetchall():
            cursor.execute(f'ALTER TABLE questions DROP CONSTRAINT "{name}"')
        cursor.execute(f'ALTER TABLE questions ADD CONSTRAINT questions_teacher_id_fkey FOREIGN KEY (teacher_id) {target}')


def owner_any_profile(apps, schema_editor):
    vendor = schema_editor.connection.vendor
    if vendor == 'sqlite':
        _rebuild_sqlite_questions(schema_editor, TEACHER_REF, PROFILE_REF)
    elif vendor == 'postgresql':
        _replace_postgres_key(schema_editor, PROFILE_REF)


def owner_teacher_only(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute('SELECT COUNT(*) FROM questions q WHERE q.teacher_id IS NOT NULL AND NOT EXISTS '
                       '(SELECT 1 FROM teacher_profiles tp WHERE tp.user_id = q.teacher_id)')
        if cursor.fetchone()[0]:
            raise RuntimeError('Questions owned by admins or managers exist; move or delete them before reversing this migration.')
    vendor = schema_editor.connection.vendor
    if vendor == 'sqlite':
        _rebuild_sqlite_questions(schema_editor, PROFILE_REF, TEACHER_REF)
    elif vendor == 'postgresql':
        _replace_postgres_key(schema_editor, TEACHER_REF)


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0055_activity_log_entity_index'),
    ]

    operations = [
        migrations.RunPython(owner_any_profile, owner_teacher_only),
    ]
