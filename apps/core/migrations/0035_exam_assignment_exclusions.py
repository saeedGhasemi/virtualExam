from django.db import migrations


def add_table(apps, schema_editor):
    vendor = schema_editor.connection.vendor
    with schema_editor.connection.cursor() as cursor:
        pk_uuid = 'uuid PRIMARY KEY' if vendor == 'postgresql' else 'TEXT PRIMARY KEY'
        uuid_type = 'uuid' if vendor == 'postgresql' else 'TEXT'
        timestamp_type = 'timestamptz' if vendor == 'postgresql' else 'TEXT'
        default_now = 'DEFAULT now()' if vendor == 'postgresql' else 'DEFAULT CURRENT_TIMESTAMP'
        cursor.execute(
            f"""
            CREATE TABLE IF NOT EXISTS exam_assignment_exclusions (
                id {pk_uuid},
                exam_id {uuid_type} REFERENCES exams(id),
                student_profile_id {uuid_type} REFERENCES student_profiles(user_id),
                created_at {timestamp_type} {default_now},
                UNIQUE (exam_id, student_profile_id)
            )
            """
        )


def remove_table(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute('DROP TABLE IF EXISTS exam_assignment_exclusions')


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0034_group_archive_fields'),
    ]

    operations = [
        migrations.RunPython(add_table, remove_table),
    ]
