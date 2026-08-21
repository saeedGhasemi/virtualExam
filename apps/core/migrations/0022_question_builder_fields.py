from django.db import migrations


def _json_type(vendor):
    return 'jsonb' if vendor == 'postgresql' else 'JSON'


def add_question_builder_fields(apps, schema_editor):
    vendor = schema_editor.connection.vendor
    json_type = _json_type(vendor)
    text_type = 'text' if vendor == 'postgresql' else 'TEXT'
    numeric_type = 'numeric' if vendor == 'postgresql' else 'NUMERIC'
    boolean_type = 'boolean' if vendor == 'postgresql' else 'BOOLEAN'
    columns = {
        'structure': f'{text_type} DEFAULT \'independent\'',
        'subject': text_type,
        'question_media': json_type,
        'answer_media': json_type,
        'scoring_settings': json_type,
        'feedback': json_type,
        'rubric': json_type,
        'accepted_answers': json_type,
        'matching_pairs': json_type,
        'ordering_items': json_type,
        'scenario_data': json_type,
        'is_published': f'{boolean_type} DEFAULT false',
        'negative_points': numeric_type,
        'suggested_time_seconds': 'integer',
    }
    existing = set()
    with schema_editor.connection.cursor() as cursor:
        cursor.execute('SELECT * FROM questions LIMIT 0')
        existing = {column[0] for column in cursor.description or []}
        for column, definition in columns.items():
            if column not in existing:
                cursor.execute(f'ALTER TABLE questions ADD COLUMN {column} {definition}')


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0021_group_creation_fields'),
    ]

    operations = [
        migrations.RunPython(add_question_builder_fields, noop_reverse),
    ]
