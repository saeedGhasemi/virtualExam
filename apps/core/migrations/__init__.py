from django.db import migrations


def add_column_if_missing(schema_editor, table, column, definition):
    with schema_editor.connection.cursor() as cursor:
        if schema_editor.connection.vendor == 'sqlite':
            cursor.execute(f"PRAGMA table_info({table})")
            exists = any(row[1] == column for row in cursor.fetchall())
            if not exists:
                cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
            return
        cursor.execute(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_name = %s AND column_name = %s
            """,
            [table, column],
        )
        if cursor.fetchone() is None:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def add_academic_term_columns(apps, schema_editor):
    add_column_if_missing(schema_editor, 'academic_terms', 'start_date', 'text')
    add_column_if_missing(schema_editor, 'academic_terms', 'end_date', 'text')
    add_column_if_missing(schema_editor, 'academic_terms', 'description', 'text')
    add_column_if_missing(schema_editor, 'academic_terms', 'is_active', 'boolean DEFAULT true')


def remove_academic_term_columns(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("ALTER TABLE academic_terms DROP COLUMN IF EXISTS start_date")
        cursor.execute("ALTER TABLE academic_terms DROP COLUMN IF EXISTS end_date")
        cursor.execute("ALTER TABLE academic_terms DROP COLUMN IF EXISTS description")
        cursor.execute("ALTER TABLE academic_terms DROP COLUMN IF EXISTS is_active")


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0016_scale_scope_indexes'),
    ]

    operations = [
        migrations.RunPython(add_academic_term_columns, remove_academic_term_columns),
    ]
