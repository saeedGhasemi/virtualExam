from django.db import migrations


def add_index(apps, schema_editor):
    # Proctoring events are counted per attempt (entity_type 'exam_attempt', entity_id) on the teacher's pages.
    with schema_editor.connection.cursor() as cursor:
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_activity_audit_log_entity ON activity_audit_log (entity_type, entity_id)')


def remove_index(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute('DROP INDEX IF EXISTS idx_activity_audit_log_entity')


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0054_exam_attempts_active_session'),
    ]

    operations = [
        migrations.RunPython(add_index, remove_index),
    ]
