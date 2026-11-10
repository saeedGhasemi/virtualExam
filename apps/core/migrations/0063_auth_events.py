"""auth_events: one row per sign-in, failed sign-in, blocked attempt, correct password before 2FA, wrong 2FA code and
sign-out (time, username, auth_user id, IP, browser). It is the sign-in audit trail and the shared counter of the
login throttle (`apps/core/auth_guard.py`, Auth.md). Rows older than AUTH_EVENTS_RETENTION_DAYS are removed by
`manage.py purge_expired_data` (Data.md).
"""
from django.db import migrations


def add_table(apps, schema_editor):
    postgres = schema_editor.connection.vendor == 'postgresql'
    pk = 'BIGSERIAL PRIMARY KEY' if postgres else 'INTEGER PRIMARY KEY AUTOINCREMENT'
    timestamp = 'timestamptz NOT NULL DEFAULT now()' if postgres else 'TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP'
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            f"""
            CREATE TABLE IF NOT EXISTS auth_events (
                id {pk},
                event VARCHAR(30) NOT NULL,
                username VARCHAR(150) NOT NULL DEFAULT '',
                user_id INTEGER,
                ip_address VARCHAR(64) NOT NULL DEFAULT '',
                user_agent VARCHAR(300) NOT NULL DEFAULT '',
                created_at {timestamp}
            )
            """
        )
        cursor.execute('CREATE INDEX IF NOT EXISTS auth_events_username ON auth_events (username, created_at)')
        cursor.execute('CREATE INDEX IF NOT EXISTS auth_events_ip ON auth_events (ip_address, created_at)')
        cursor.execute('CREATE INDEX IF NOT EXISTS auth_events_user ON auth_events (user_id, created_at)')


def drop_table(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute('DROP TABLE IF EXISTS auth_events')


class Migration(migrations.Migration):
    dependencies = [('core', '0062_profile_password_state')]
    operations = [migrations.RunPython(add_table, drop_table)]
