"""«ساختار سازمانی» no longer has editable levels: the three access levels are fixed in apps/core/org_levels.py.
Removes the two settings rows the old level editor kept (nothing reads them any more)."""
from django.db import migrations


def remove_settings(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("DELETE FROM system_settings WHERE key IN ('org_structure_levels_config', 'org_structure_levels')")


class Migration(migrations.Migration):
    dependencies = [('core', '0064_attempt_live_columns')]

    operations = [migrations.RunPython(remove_settings, migrations.RunPython.noop)]
