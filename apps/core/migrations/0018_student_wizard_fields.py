from django.db import migrations


def _table_has_column(schema_editor, table_name, column_name):
    with schema_editor.connection.cursor() as cursor:
        columns = schema_editor.connection.introspection.get_table_description(cursor, table_name)
    return any(column.name == column_name for column in columns)


def add_student_wizard_fields(apps, schema_editor):
    vendor = schema_editor.connection.vendor
    text = "text" if vendor == "postgresql" else "TEXT"
    boolean = "boolean" if vendor == "postgresql" else "BOOLEAN"
    timestamp = "timestamptz" if vendor == "postgresql" else "TEXT"
    uuid_type = "uuid" if vendor == "postgresql" else "TEXT"
    pk_uuid = "uuid PRIMARY KEY" if vendor == "postgresql" else "TEXT PRIMARY KEY"
    default_now = "DEFAULT now()" if vendor == "postgresql" else "DEFAULT CURRENT_TIMESTAMP"

    with schema_editor.connection.cursor() as cursor:
        if not _table_has_column(schema_editor, "student_profiles", "entry_year"):
            cursor.execute(f"ALTER TABLE student_profiles ADD COLUMN entry_year {text}")
        if not _table_has_column(schema_editor, "student_profiles", "admission_type"):
            cursor.execute(f"ALTER TABLE student_profiles ADD COLUMN admission_type {text}")
        if not _table_has_column(schema_editor, "student_profiles", "password_method"):
            cursor.execute(f"ALTER TABLE student_profiles ADD COLUMN password_method {text} DEFAULT 'activation_link'")
        if not _table_has_column(schema_editor, "student_profiles", "must_change_password"):
            cursor.execute(f"ALTER TABLE student_profiles ADD COLUMN must_change_password {boolean} DEFAULT true")
        if not _table_has_column(schema_editor, "student_profiles", "send_welcome_message"):
            cursor.execute(f"ALTER TABLE student_profiles ADD COLUMN send_welcome_message {boolean} DEFAULT true")

        cursor.execute(
            f"""
            CREATE TABLE IF NOT EXISTS student_course_enrollments (
                id {pk_uuid},
                student_user_id {uuid_type} REFERENCES profiles(id),
                course_id {uuid_type} REFERENCES courses(id),
                created_at {timestamp} {default_now},
                UNIQUE (student_user_id, course_id)
            )
            """
        )

        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_student_course_enrollments_student
            ON student_course_enrollments (student_user_id)
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_student_course_enrollments_course
            ON student_course_enrollments (course_id)
            """
        )


def remove_student_wizard_fields(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("DROP TABLE IF EXISTS student_course_enrollments")


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0017_academic_terms_settings_columns"),
    ]

    operations = [
        migrations.RunPython(add_student_wizard_fields, remove_student_wizard_fields),
    ]
