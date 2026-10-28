from django.db import migrations


def add_tables(apps, schema_editor):
    is_pg = schema_editor.connection.vendor == 'postgresql'
    timestamp_type = 'timestamptz' if is_pg else 'TEXT'
    default_now = 'DEFAULT now()' if is_pg else 'DEFAULT CURRENT_TIMESTAMP'
    bool_false = 'boolean NOT NULL DEFAULT false' if is_pg else 'INTEGER NOT NULL DEFAULT 0'
    pk_serial = 'BIGSERIAL PRIMARY KEY' if is_pg else 'INTEGER PRIMARY KEY AUTOINCREMENT'
    with schema_editor.connection.cursor() as cursor:
        # Authenticator-app (TOTP) secret per sign-in account (user_id = auth_user.id). enabled stays false until
        # the user proves the app works; last_used_step blocks replaying a code inside its 30-second window.
        cursor.execute(
            f"""
            CREATE TABLE IF NOT EXISTS user_two_factor (
                user_id INTEGER PRIMARY KEY,
                secret TEXT NOT NULL,
                enabled {bool_false},
                last_used_step BIGINT,
                confirmed_at {timestamp_type},
                created_at {timestamp_type} {default_now}
            )
            """
        )
        # Single-use recovery codes; only a SHA-256 of each is stored.
        cursor.execute(
            f"""
            CREATE TABLE IF NOT EXISTS user_recovery_codes (
                id {pk_serial},
                user_id INTEGER NOT NULL,
                code_hash VARCHAR(64) NOT NULL,
                used_at {timestamp_type},
                created_at {timestamp_type} {default_now}
            )
            """
        )
        cursor.execute('CREATE INDEX IF NOT EXISTS user_recovery_codes_user ON user_recovery_codes (user_id)')


def remove_tables(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute('DROP TABLE IF EXISTS user_recovery_codes')
        cursor.execute('DROP TABLE IF EXISTS user_two_factor')


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0045_sessions_and_account_deletion'),
    ]

    operations = [
        migrations.RunPython(add_tables, remove_tables),
    ]
