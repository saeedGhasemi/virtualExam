import re

from django.db import migrations

# OSCE exams and their checklist templates are built by the same people who keep a question bank (teachers, academic
# managers, system admins — see migration 0056 for `questions`). Admins and managers have no teacher_profiles row, so
# the owner column now references profiles(id). Every teacher_profiles.user_id is a profiles.id, so existing rows
# satisfy the new key.
TEACHER_REF = 'REFERENCES teacher_profiles(user_id)'
PROFILE_REF = 'REFERENCES profiles(id)'
TABLES = ('osce_exams', 'osce_criteria_templates')


def _rebuild_sqlite(schema_editor, table, old_ref, new_ref):
    """SQLite cannot alter a foreign key: rebuild the table from its own DDL (as 0056 does for questions)."""
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = %s", [table])
        row = cursor.fetchone()
        if not row:
            return
        ddl = row[0]
        pattern = re.compile(r'(teacher_id\s+\w+\s+NOT\s+NULL\s+)' + re.escape(old_ref))
        if not pattern.search(ddl):
            if re.search(r'teacher_id\s+\w+\s+NOT\s+NULL\s+' + re.escape(new_ref), ddl):
                return
            raise RuntimeError(f'{table}.teacher_id has an unexpected definition; rebuild aborted.')
        cursor.execute("SELECT sql FROM sqlite_master WHERE type = 'index' AND tbl_name = %s AND sql IS NOT NULL", [table])
        index_sql = [item[0] for item in cursor.fetchall()]
        cursor.execute(f'PRAGMA table_info({table})')
        columns = ', '.join(f'"{item[1]}"' for item in cursor.fetchall())
        temp = f'{table}_owner_rebuild'
        rebuilt = re.sub(r'^CREATE TABLE\s+["`]?' + table + r'["`]?', f'CREATE TABLE {temp}',
                         pattern.sub(r'\g<1>' + new_ref, ddl, count=1), count=1)
        cursor.execute(rebuilt)
        cursor.execute(f'INSERT INTO {temp} ({columns}) SELECT {columns} FROM {table}')
        cursor.execute(f'DROP TABLE {table}')
        cursor.execute(f'ALTER TABLE {temp} RENAME TO {table}')
        for statement in index_sql:
            cursor.execute(statement)


def _replace_postgres_key(schema_editor, table, target):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT conname FROM pg_constraint
            WHERE conrelid = %s::regclass AND contype = 'f' AND pg_get_constraintdef(oid) ILIKE 'FOREIGN KEY (teacher_id)%%'
            """,
            [table],
        )
        for (name,) in cursor.fetchall():
            cursor.execute(f'ALTER TABLE {table} DROP CONSTRAINT "{name}"')
        cursor.execute(f'ALTER TABLE {table} ADD CONSTRAINT {table}_teacher_id_fkey FOREIGN KEY (teacher_id) {target}')


def _apply(schema_editor, old_ref, new_ref):
    vendor = schema_editor.connection.vendor
    for table in TABLES:
        if vendor == 'sqlite':
            _rebuild_sqlite(schema_editor, table, old_ref, new_ref)
        elif vendor == 'postgresql':
            _replace_postgres_key(schema_editor, table, new_ref)


def owner_any_profile(apps, schema_editor):
    _apply(schema_editor, TEACHER_REF, PROFILE_REF)


def owner_teacher_only(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        for table in TABLES:
            cursor.execute(f'SELECT COUNT(*) FROM {table} o WHERE NOT EXISTS '
                           '(SELECT 1 FROM teacher_profiles tp WHERE tp.user_id = o.teacher_id)')
            if cursor.fetchone()[0]:
                raise RuntimeError(f'{table} rows owned by admins or managers exist; move or delete them before reversing this migration.')
    _apply(schema_editor, PROFILE_REF, TEACHER_REF)


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0065_remove_org_level_settings'),
    ]

    operations = [
        migrations.RunPython(owner_any_profile, owner_teacher_only),
    ]
