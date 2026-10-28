from django.db import migrations


def add_table(apps, schema_editor):
    is_pg = schema_editor.connection.vendor == 'postgresql'
    pk_uuid = 'uuid PRIMARY KEY' if is_pg else 'TEXT PRIMARY KEY'
    uuid_type = 'uuid' if is_pg else 'TEXT'
    timestamp_type = 'timestamptz' if is_pg else 'TEXT'
    default_now = 'DEFAULT now()' if is_pg else 'DEFAULT CURRENT_TIMESTAMP'
    with schema_editor.connection.cursor() as cursor:
        # A teacher's request to change their university details (unit, rank, degree); an academic manager reviews it.
        # previous_* keep what the profile held when the request was made, so the reviewer sees the change.
        cursor.execute(
            f"""
            CREATE TABLE IF NOT EXISTS teacher_profile_change_requests (
                id {pk_uuid},
                teacher_id {uuid_type} NOT NULL REFERENCES teacher_profiles(user_id),
                org_unit_id {uuid_type} REFERENCES org_units(id) ON DELETE SET NULL,
                academic_rank TEXT,
                degree TEXT,
                previous_org_unit_id {uuid_type},
                previous_academic_rank TEXT,
                previous_degree TEXT,
                teacher_note TEXT CHECK (teacher_note IS NULL OR length(teacher_note) <= 300),
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'approved', 'rejected', 'cancelled')),
                reviewer_id {uuid_type},
                review_note TEXT CHECK (review_note IS NULL OR length(review_note) <= 300),
                created_at {timestamp_type} {default_now},
                reviewed_at {timestamp_type}
            )
            """
        )
        # At most one open request per teacher, enforced by the database.
        cursor.execute(
            'CREATE UNIQUE INDEX IF NOT EXISTS teacher_profile_change_requests_one_pending '
            "ON teacher_profile_change_requests (teacher_id) WHERE status = 'pending'"
        )
        cursor.execute(
            'CREATE INDEX IF NOT EXISTS teacher_profile_change_requests_status '
            'ON teacher_profile_change_requests (status, created_at)'
        )
        cursor.execute(
            'CREATE INDEX IF NOT EXISTS teacher_profile_change_requests_teacher '
            'ON teacher_profile_change_requests (teacher_id, created_at)'
        )


def remove_table(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute('DROP TABLE IF EXISTS teacher_profile_change_requests')


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0043_teacher_profile_personal_fields'),
    ]

    operations = [
        migrations.RunPython(add_table, remove_table),
    ]
