from django.db import migrations


def _table_has_column(schema_editor, table_name, column_name):
    with schema_editor.connection.cursor() as cursor:
        columns = schema_editor.connection.introspection.get_table_description(cursor, table_name)
    return any(column.name == column_name for column in columns)


ACTIVITY_COLUMNS = 'id, actor_id, action, entity_type, entity_id, reason, metadata'


def rebuild_sqlite_activity_table(schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """
            CREATE TABLE activity_audit_log_rebuild (
                id TEXT PRIMARY KEY,
                actor_id TEXT REFERENCES profiles(id),
                action TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                entity_id TEXT,
                reason TEXT,
                metadata JSON,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cursor.execute(
            f"INSERT INTO activity_audit_log_rebuild ({ACTIVITY_COLUMNS}) "
            f"SELECT {ACTIVITY_COLUMNS} FROM activity_audit_log"
        )
        cursor.execute("DROP TABLE activity_audit_log")
        cursor.execute("ALTER TABLE activity_audit_log_rebuild RENAME TO activity_audit_log")


def add_created_at(apps, schema_editor):
    vendor = schema_editor.connection.vendor
    if vendor == 'sqlite':
        if not _table_has_column(schema_editor, 'activity_audit_log', 'created_at'):
            rebuild_sqlite_activity_table(schema_editor)
        with schema_editor.connection.cursor() as cursor:
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_activity_audit_log_actor_created ON activity_audit_log (actor_id, created_at)")
        return
    if vendor != 'postgresql':
        return
    with schema_editor.connection.cursor() as cursor:
        if not _table_has_column(schema_editor, 'activity_audit_log', 'created_at'):
            cursor.execute("ALTER TABLE activity_audit_log ADD COLUMN created_at timestamptz DEFAULT now()")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_activity_audit_log_actor_created ON activity_audit_log (actor_id, created_at)")


def remove_created_at(apps, schema_editor):
    vendor = schema_editor.connection.vendor
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("DROP INDEX IF EXISTS idx_activity_audit_log_actor_created")
        if vendor == 'postgresql':
            cursor.execute("ALTER TABLE activity_audit_log DROP COLUMN IF EXISTS created_at")
        # SQLite: left in place on rollback since it is additive and harmless to keep.


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0026_profiles_pending_rejected_status'),
    ]

    operations = [
        migrations.RunPython(add_created_at, remove_created_at),
    ]
