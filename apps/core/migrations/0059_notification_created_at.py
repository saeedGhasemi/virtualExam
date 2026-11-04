from django.db import migrations

# notifications.created_at: when a notification was made. The teacher's browser and e-mail channels
# («اعلان مرورگر» / «ایمیل») send only the ones made since they last looked. Existing rows get the migration time.


def _table_has_column(connection, table_name, column_name):
    with connection.cursor() as cursor:
        columns = connection.introspection.get_table_description(cursor, table_name)
    return any(column.name == column_name for column in columns)


def add_created_at(apps, schema_editor):
    connection = schema_editor.connection
    if _table_has_column(connection, 'notifications', 'created_at'):
        return
    column = 'TIMESTAMP WITH TIME ZONE DEFAULT now()' if connection.vendor == 'postgresql' else 'TIMESTAMP DEFAULT CURRENT_TIMESTAMP'
    with connection.cursor() as cursor:
        cursor.execute(f'ALTER TABLE notifications ADD COLUMN created_at {column}')


def remove_created_at(apps, schema_editor):
    if schema_editor.connection.vendor == 'postgresql':
        with schema_editor.connection.cursor() as cursor:
            cursor.execute('ALTER TABLE notifications DROP COLUMN IF EXISTS created_at')


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0058_attempt_receipt_code'),
    ]

    operations = [
        migrations.RunPython(add_created_at, remove_created_at),
    ]
