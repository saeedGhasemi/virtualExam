from django.db import migrations


def column_exists(cursor, table, column):
    cursor.execute(f'SELECT * FROM {table} LIMIT 0')
    return column in {item[0] for item in cursor.description or []}


def add_tables(apps, schema_editor):
    is_pg = schema_editor.connection.vendor == 'postgresql'
    pk_uuid = 'uuid PRIMARY KEY' if is_pg else 'TEXT PRIMARY KEY'
    uuid_type = 'uuid' if is_pg else 'TEXT'
    timestamp_type = 'timestamptz' if is_pg else 'TEXT'
    default_now = 'DEFAULT now()' if is_pg else 'DEFAULT CURRENT_TIMESTAMP'
    with schema_editor.connection.cursor() as cursor:
        # One row per signed-in browser, so a user can see and end their own sessions (user_id = auth_user.id).
        cursor.execute(
            f"""
            CREATE TABLE IF NOT EXISTS user_sessions (
                session_key VARCHAR(40) PRIMARY KEY,
                user_id INTEGER NOT NULL,
                ip_address TEXT,
                user_agent TEXT,
                created_at {timestamp_type} {default_now}
            )
            """
        )
        cursor.execute('CREATE INDEX IF NOT EXISTS user_sessions_user ON user_sessions (user_id, created_at)')

        # A user's request to close their account; the system admin approves it. Approval only deactivates the
        # account (profiles.deleted_at), nothing is removed, so the admin can still see the data.
        cursor.execute(
            f"""
            CREATE TABLE IF NOT EXISTS account_deletion_requests (
                id {pk_uuid},
                profile_id {uuid_type} NOT NULL REFERENCES profiles(id),
                reason TEXT CHECK (reason IS NULL OR length(reason) <= 500),
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'approved', 'rejected', 'cancelled')),
                reviewer_id {uuid_type},
                review_note TEXT CHECK (review_note IS NULL OR length(review_note) <= 300),
                created_at {timestamp_type} {default_now},
                reviewed_at {timestamp_type}
            )
            """
        )
        cursor.execute(
            'CREATE UNIQUE INDEX IF NOT EXISTS account_deletion_requests_one_pending '
            "ON account_deletion_requests (profile_id) WHERE status = 'pending'"
        )
        cursor.execute('CREATE INDEX IF NOT EXISTS account_deletion_requests_status ON account_deletion_requests (status, created_at)')

        # Logical deletion markers; existing rows stay NULL (= not deleted).
        for column, column_type in (('deleted_at', timestamp_type), ('deleted_by', uuid_type)):
            if not column_exists(cursor, 'profiles', column):
                cursor.execute(f'ALTER TABLE profiles ADD COLUMN {column} {column_type}')


def remove_tables(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute('DROP TABLE IF EXISTS account_deletion_requests')
        cursor.execute('DROP TABLE IF EXISTS user_sessions')
        if schema_editor.connection.vendor == 'postgresql':  # SQLite: additive columns are left in place on rollback
            cursor.execute('ALTER TABLE profiles DROP COLUMN IF EXISTS deleted_at')
            cursor.execute('ALTER TABLE profiles DROP COLUMN IF EXISTS deleted_by')


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0044_teacher_profile_change_requests'),
    ]

    operations = [
        migrations.RunPython(add_tables, remove_tables),
    ]
