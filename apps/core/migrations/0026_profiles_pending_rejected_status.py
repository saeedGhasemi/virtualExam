from django.db import migrations


PROFILES_COLUMNS = (
    'id, full_name, first_name, last_name, username, email, phone, '
    'national_id, identifier, avatar_url, status, last_login_at, created_at, updated_at'
)


def rebuild_sqlite_profiles_table(schema_editor, allowed_statuses):
    check_sql = ','.join(f"'{value}'" for value in allowed_statuses)
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            f"""
            CREATE TABLE profiles_status_rebuild (
                id TEXT PRIMARY KEY,
                full_name TEXT NOT NULL,
                first_name TEXT,
                last_name TEXT,
                username TEXT UNIQUE,
                email TEXT,
                phone TEXT,
                national_id TEXT UNIQUE,
                identifier TEXT,
                avatar_url TEXT,
                status TEXT CHECK (status IN ({check_sql})) DEFAULT 'active',
                last_login_at TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT
            )
            """
        )
        cursor.execute(
            f"INSERT INTO profiles_status_rebuild ({PROFILES_COLUMNS}) "
            f"SELECT {PROFILES_COLUMNS} FROM profiles"
        )
        cursor.execute("DROP TABLE profiles")
        cursor.execute("ALTER TABLE profiles_status_rebuild RENAME TO profiles")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_erd_profiles_username_email ON profiles (username, email)")


def add_pending_rejected_status(apps, schema_editor):
    vendor = schema_editor.connection.vendor
    if vendor == 'sqlite':
        rebuild_sqlite_profiles_table(schema_editor, ('active', 'inactive', 'blocked', 'pending', 'rejected'))
        return
    if vendor != 'postgresql':
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("ALTER TABLE profiles DROP CONSTRAINT IF EXISTS profiles_status_check")
        cursor.execute(
            """
            ALTER TABLE profiles
            ADD CONSTRAINT profiles_status_check
            CHECK (status IN ('active','inactive','blocked','pending','rejected'))
            """
        )


def rollback_pending_rejected_status(apps, schema_editor):
    vendor = schema_editor.connection.vendor
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("UPDATE profiles SET status = 'inactive' WHERE status IN ('pending', 'rejected')")
    if vendor == 'sqlite':
        rebuild_sqlite_profiles_table(schema_editor, ('active', 'inactive', 'blocked'))
        return
    if vendor != 'postgresql':
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("ALTER TABLE profiles DROP CONSTRAINT IF EXISTS profiles_status_check")
        cursor.execute(
            """
            ALTER TABLE profiles
            ADD CONSTRAINT profiles_status_check
            CHECK (status IN ('active','inactive','blocked'))
            """
        )


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0025_phase4_legacy_erd_id_tracking'),
    ]

    operations = [
        migrations.RunPython(add_pending_rejected_status, rollback_pending_rejected_status),
    ]
