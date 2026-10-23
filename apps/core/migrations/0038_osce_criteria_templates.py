from django.db import migrations


def add_table(apps, schema_editor):
    is_pg = schema_editor.connection.vendor == 'postgresql'
    pk_uuid = 'uuid PRIMARY KEY' if is_pg else 'TEXT PRIMARY KEY'
    uuid_type = 'uuid' if is_pg else 'TEXT'
    json_type = 'jsonb' if is_pg else 'TEXT'
    timestamp_type = 'timestamptz' if is_pg else 'TEXT'
    default_now = 'DEFAULT now()' if is_pg else 'DEFAULT CURRENT_TIMESTAMP'
    with schema_editor.connection.cursor() as cursor:
        # A teacher's own reusable OSCE checklists («قالب‌های من»); built-in templates live in code.
        cursor.execute(
            f"""
            CREATE TABLE IF NOT EXISTS osce_criteria_templates (
                id {pk_uuid},
                teacher_id {uuid_type} NOT NULL REFERENCES teacher_profiles(user_id),
                title TEXT NOT NULL,
                items {json_type} NOT NULL DEFAULT '[]',
                created_at {timestamp_type} {default_now},
                UNIQUE (teacher_id, title)
            )
            """
        )


def remove_table(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute('DROP TABLE IF EXISTS osce_criteria_templates')


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0037_osce_exams'),
    ]

    operations = [
        migrations.RunPython(add_table, remove_table),
    ]
