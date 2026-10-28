from django.db import migrations


def add_table(apps, schema_editor):
    is_pg = schema_editor.connection.vendor == 'postgresql'
    pk_uuid = 'uuid PRIMARY KEY' if is_pg else 'TEXT PRIMARY KEY'
    uuid_type = 'uuid' if is_pg else 'TEXT'
    bool_false = 'boolean NOT NULL DEFAULT false' if is_pg else 'INTEGER NOT NULL DEFAULT 0'
    timestamp_type = 'timestamptz' if is_pg else 'TEXT'
    default_now = 'DEFAULT now()' if is_pg else 'DEFAULT CURRENT_TIMESTAMP'
    with schema_editor.connection.cursor() as cursor:
        # A teacher's private notes on one student; is_shared marks a note also sent to the student as feedback.
        cursor.execute(
            f"""
            CREATE TABLE IF NOT EXISTS teacher_student_notes (
                id {pk_uuid},
                teacher_id {uuid_type} NOT NULL REFERENCES teacher_profiles(user_id),
                student_id {uuid_type} NOT NULL REFERENCES student_profiles(user_id),
                body TEXT NOT NULL CHECK (length(body) BETWEEN 1 AND 1000),
                is_shared {bool_false},
                created_at {timestamp_type} {default_now}
            )
            """
        )
        cursor.execute(
            'CREATE INDEX IF NOT EXISTS teacher_student_notes_lookup '
            'ON teacher_student_notes (teacher_id, student_id, created_at)'
        )


def remove_table(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute('DROP TABLE IF EXISTS teacher_student_notes')


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0041_question_types_v2'),
    ]

    operations = [
        migrations.RunPython(add_table, remove_table),
    ]
