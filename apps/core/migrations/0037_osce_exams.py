from django.db import migrations


def add_tables(apps, schema_editor):
    vendor = schema_editor.connection.vendor
    is_pg = vendor == 'postgresql'
    pk_uuid = 'uuid PRIMARY KEY' if is_pg else 'TEXT PRIMARY KEY'
    uuid_type = 'uuid' if is_pg else 'TEXT'
    json_type = 'jsonb' if is_pg else 'TEXT'
    timestamp_type = 'timestamptz' if is_pg else 'TEXT'
    default_now = 'DEFAULT now()' if is_pg else 'DEFAULT CURRENT_TIMESTAMP'
    with schema_editor.connection.cursor() as cursor:
        # An OSCE exam is a set of stations owned by one teacher; it stays a draft until published.
        cursor.execute(
            f"""
            CREATE TABLE IF NOT EXISTS osce_exams (
                id {pk_uuid},
                teacher_id {uuid_type} NOT NULL REFERENCES teacher_profiles(user_id),
                course_id {uuid_type} REFERENCES courses(id),
                title TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'published')),
                settings {json_type} NOT NULL DEFAULT '{{}}',
                created_at {timestamp_type} {default_now},
                updated_at {timestamp_type} {default_now}
            )
            """
        )
        cursor.execute('CREATE INDEX IF NOT EXISTS osce_exams_teacher_idx ON osce_exams (teacher_id)')
        cursor.execute(
            f"""
            CREATE TABLE IF NOT EXISTS osce_stations (
                id {pk_uuid},
                osce_exam_id {uuid_type} NOT NULL REFERENCES osce_exams(id) ON DELETE CASCADE,
                position INTEGER NOT NULL CHECK (position > 0),
                title TEXT NOT NULL,
                code TEXT NOT NULL,
                station_type TEXT NOT NULL DEFAULT 'clinical'
                    CHECK (station_type IN ('clinical', 'skill', 'communication', 'knowledge')),
                domain TEXT NOT NULL DEFAULT '',
                difficulty TEXT NOT NULL DEFAULT 'medium' CHECK (difficulty IN ('easy', 'medium', 'hard')),
                duration_minutes INTEGER NOT NULL DEFAULT 10 CHECK (duration_minutes > 0),
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                description TEXT NOT NULL DEFAULT '',
                objectives {json_type} NOT NULL DEFAULT '[]',
                details {json_type} NOT NULL DEFAULT '{{}}',
                created_at {timestamp_type} {default_now},
                updated_at {timestamp_type} {default_now},
                UNIQUE (osce_exam_id, code)
            )
            """
        )
        cursor.execute('CREATE INDEX IF NOT EXISTS osce_stations_exam_position_idx ON osce_stations (osce_exam_id, position)')


def remove_tables(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute('DROP TABLE IF EXISTS osce_stations')
        cursor.execute('DROP TABLE IF EXISTS osce_exams')


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0036_exam_post_publish_notification_prefs'),
    ]

    operations = [
        migrations.RunPython(add_tables, remove_tables),
    ]
