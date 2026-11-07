"""Allow the image-hotspot question type («انتخاب ناحیه روی تصویر») in questions.type (CHECK constraint only)."""
import importlib

from django.db import migrations

_types_v2 = importlib.import_module('apps.core.migrations.0041_question_types_v2')

OLD_TYPES = _types_v2.NEW_TYPES
NEW_TYPES = OLD_TYPES + ('hotspot',)


def add_hotspot(apps, schema_editor):
    vendor = schema_editor.connection.vendor
    if vendor == 'sqlite':
        _types_v2._rebuild_sqlite_questions(schema_editor, OLD_TYPES, NEW_TYPES)
    elif vendor == 'postgresql':
        _types_v2._replace_postgres_check(schema_editor, NEW_TYPES)


def remove_hotspot(apps, schema_editor):
    vendor = schema_editor.connection.vendor
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM questions WHERE type = 'hotspot'")
        if cursor.fetchone()[0]:
            raise RuntimeError('Hotspot questions exist; delete them before reversing this migration.')
    if vendor == 'sqlite':
        _types_v2._rebuild_sqlite_questions(schema_editor, NEW_TYPES, OLD_TYPES)
    elif vendor == 'postgresql':
        _types_v2._replace_postgres_check(schema_editor, OLD_TYPES)


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0059_notification_created_at'),
    ]

    operations = [
        migrations.RunPython(add_hotspot, remove_hotspot),
    ]
