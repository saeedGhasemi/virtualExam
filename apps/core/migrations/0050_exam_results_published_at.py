from django.db import migrations


# «انتشار نتایج»: when the teacher or the academic manager published an exam's results. Results whose
# «نمایش نمره» is not «بلافاصله» stay hidden from students until it is set; empty means not published.
COLUMN = 'results_published_at'


def column_exists(cursor, table, column):
    cursor.execute(f'SELECT * FROM {table} LIMIT 0')
    return column in {item[0] for item in cursor.description or []}


def add_column(apps, schema_editor):
    is_pg = schema_editor.connection.vendor == 'postgresql'
    with schema_editor.connection.cursor() as cursor:
        if not column_exists(cursor, 'exams', COLUMN):
            cursor.execute(f'ALTER TABLE exams ADD COLUMN {COLUMN} {"timestamptz" if is_pg else "TIMESTAMP"} NULL')


def drop_column(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        if column_exists(cursor, 'exams', COLUMN):
            cursor.execute(f'ALTER TABLE exams DROP COLUMN {COLUMN}')


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0049_single_choice_correct_flags'),
    ]

    operations = [
        migrations.RunPython(add_column, drop_column),
    ]
