from django.db import migrations


def _table_has_column(schema_editor, table_name, column_name):
    with schema_editor.connection.cursor() as cursor:
        columns = schema_editor.connection.introspection.get_table_description(cursor, table_name)
    return any(column.name == column_name for column in columns)


NEW_TEXT_COLUMNS = [
    'position_title',
    'service_location',
    'cooperation_started_at',
    'cooperation_type',
    'employment_type',
    'weekly_hours',
    'max_units',
    'password_method',
]
NEW_BOOLEAN_COLUMNS = [
    'apply_children',
    'can_design_exam',
    'force_password_change',
    'two_factor_enabled',
]


def add_columns(apps, schema_editor):
    vendor = schema_editor.connection.vendor
    boolean_type = 'boolean' if vendor == 'postgresql' else 'BOOLEAN'
    text_type = 'text' if vendor == 'postgresql' else 'TEXT'
    uuid_type = 'uuid' if vendor == 'postgresql' else 'TEXT'
    timestamp_type = 'timestamptz' if vendor == 'postgresql' else 'TEXT'
    default_now = 'DEFAULT now()' if vendor == 'postgresql' else 'DEFAULT CURRENT_TIMESTAMP'

    with schema_editor.connection.cursor() as cursor:
        for name in NEW_TEXT_COLUMNS:
            if not _table_has_column(schema_editor, 'teacher_profiles', name):
                cursor.execute(f"ALTER TABLE teacher_profiles ADD COLUMN {name} {text_type}")
        for name in NEW_BOOLEAN_COLUMNS:
            if not _table_has_column(schema_editor, 'teacher_profiles', name):
                cursor.execute(f"ALTER TABLE teacher_profiles ADD COLUMN {name} {boolean_type}")

        cursor.execute(
            f"""
            CREATE TABLE IF NOT EXISTS teacher_sub_units (
                teacher_id {uuid_type} REFERENCES teacher_profiles(user_id),
                org_unit_id {uuid_type} REFERENCES org_units(id),
                created_at {timestamp_type} {default_now},
                PRIMARY KEY (teacher_id, org_unit_id)
            )
            """
        )


def remove_columns(apps, schema_editor):
    vendor = schema_editor.connection.vendor
    if vendor != 'postgresql':
        # SQLite: left in place on rollback since it is additive and harmless to keep.
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("DROP TABLE IF EXISTS teacher_sub_units")
        for name in NEW_TEXT_COLUMNS + NEW_BOOLEAN_COLUMNS:
            cursor.execute(f"ALTER TABLE teacher_profiles DROP COLUMN IF EXISTS {name}")


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0029_teacher_profiles_academic_rank'),
    ]

    operations = [
        migrations.RunPython(add_columns, remove_columns),
    ]
