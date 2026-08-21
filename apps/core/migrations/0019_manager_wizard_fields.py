from django.db import migrations


def _has_column(schema_editor, table_name, column_name):
    with schema_editor.connection.cursor() as cursor:
        columns = schema_editor.connection.introspection.get_table_description(cursor, table_name)
    return any(column.name == column_name for column in columns)


def add_manager_wizard_fields(apps, schema_editor):
    vendor = schema_editor.connection.vendor
    text = "text" if vendor == "postgresql" else "TEXT"
    boolean = "boolean" if vendor == "postgresql" else "BOOLEAN"

    with schema_editor.connection.cursor() as cursor:
        for table_name in ("profiles",):
            if not _has_column(schema_editor, table_name, "gender"):
                cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN gender {text}")
            if not _has_column(schema_editor, table_name, "birth_date"):
                cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN birth_date {text}")
            if not _has_column(schema_editor, table_name, "password_method"):
                cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN password_method {text} DEFAULT 'activation_link'")
            if not _has_column(schema_editor, table_name, "must_change_password"):
                cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN must_change_password {boolean} DEFAULT true")
            if not _has_column(schema_editor, table_name, "email_verified_required"):
                cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN email_verified_required {boolean} DEFAULT true")

        if not _has_column(schema_editor, "academic_manager_profiles", "title"):
            cursor.execute(f"ALTER TABLE academic_manager_profiles ADD COLUMN title {text}")
        if not _has_column(schema_editor, "academic_manager_profiles", "access_type"):
            cursor.execute(f"ALTER TABLE academic_manager_profiles ADD COLUMN access_type {text}")
        if not _has_column(schema_editor, "academic_manager_profiles", "include_child_units"):
            cursor.execute(f"ALTER TABLE academic_manager_profiles ADD COLUMN include_child_units {boolean} DEFAULT true")


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0018_student_wizard_fields"),
    ]

    operations = [
        migrations.RunPython(add_manager_wizard_fields, migrations.RunPython.noop),
    ]
