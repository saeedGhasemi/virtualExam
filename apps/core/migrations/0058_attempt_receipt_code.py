import secrets

from django.db import migrations

# «شناسه رسید»: every submitted attempt gets its own receipt id, «کد آزمون» and six random characters
# (MQ-1A2B3C-7KQ4RZ). The unique index makes two attempts never share one; attempts already submitted get theirs here.
RECEIPT_ALPHABET = '23456789ABCDEFGHJKLMNPQRSTUVWXYZ'  # no 0/O or 1/I to mix up when read out


def _receipt(exam_id):
    exam_code = str(exam_id).replace('-', '')[:6].upper()
    return f"MQ-{exam_code}-{''.join(secrets.choice(RECEIPT_ALPHABET) for _ in range(6))}"


def _table_has_column(connection, table_name, column_name):
    with connection.cursor() as cursor:
        columns = connection.introspection.get_table_description(cursor, table_name)
    return any(column.name == column_name for column in columns)


def add_receipt_code(apps, schema_editor):
    connection = schema_editor.connection
    with connection.cursor() as cursor:
        if not _table_has_column(connection, 'exam_attempts', 'receipt_code'):
            cursor.execute('ALTER TABLE exam_attempts ADD COLUMN receipt_code VARCHAR(24)')
        cursor.execute('CREATE UNIQUE INDEX IF NOT EXISTS exam_attempts_receipt_code_uniq '
                       'ON exam_attempts (receipt_code) WHERE receipt_code IS NOT NULL')
        cursor.execute('SELECT id, exam_id FROM exam_attempts WHERE submitted_at IS NOT NULL AND receipt_code IS NULL')
        attempts = cursor.fetchall()
        cursor.execute('SELECT receipt_code FROM exam_attempts WHERE receipt_code IS NOT NULL')
        taken = {row[0] for row in cursor.fetchall()}
        for attempt_id, exam_id in attempts:
            code = _receipt(exam_id)
            while code in taken:
                code = _receipt(exam_id)
            taken.add(code)
            cursor.execute('UPDATE exam_attempts SET receipt_code = %s WHERE id = %s', [code, attempt_id])


def remove_receipt_code(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute('DROP INDEX IF EXISTS exam_attempts_receipt_code_uniq')
        if schema_editor.connection.vendor == 'postgresql':
            cursor.execute('ALTER TABLE exam_attempts DROP COLUMN IF EXISTS receipt_code')


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0057_exam_settings_columns'),
    ]

    operations = [
        migrations.RunPython(add_receipt_code, remove_receipt_code),
    ]
