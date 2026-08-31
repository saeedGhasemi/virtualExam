from django.db import migrations


def _table_has_column(schema_editor, table_name, column_name):
    with schema_editor.connection.cursor() as cursor:
        columns = schema_editor.connection.introspection.get_table_description(cursor, table_name)
    return any(column.name == column_name for column in columns)


EXAM_COLUMNS = [
    ('exam_mode', "text DEFAULT 'standard'"),
    ('cover_image_url', 'text'),
    ('tags', 'text'),
    ('grading_template', "text DEFAULT 'total_score'"),
    ('registration_start_at', 'timestamp'),
    ('registration_end_at', 'timestamp'),
    ('last_entry_at', 'timestamp'),
    ('allow_flagging_questions', 'boolean DEFAULT true'),
    ('show_question_list', 'boolean DEFAULT true'),
    ('one_question_per_page', 'boolean DEFAULT false'),
    ('auto_submit_on_time_end', 'boolean DEFAULT true'),
    ('correct_answer_display_mode', "text DEFAULT 'after_publish'"),
    ('score_display_mode', "text DEFAULT 'after_publish'"),
    ('explanation_display_mode', "text DEFAULT 'after_publish'"),
    ('grading_method', "text DEFAULT 'weighted_by_type'"),
    ('manual_review_required', 'boolean DEFAULT false'),
    ('results_deadline', "text DEFAULT '3_days_after_end'"),
    ('correction_instructions', 'text'),
    ('rubric_template', 'text'),
    ('correction_mode', "text DEFAULT 'manual'"),
    ('security_level', "text DEFAULT 'medium'"),
    ('execution_mode', "text DEFAULT 'web'"),
    ('identity_verification_required', 'boolean DEFAULT true'),
    ('device_limit_enabled', 'boolean DEFAULT true'),
    ('ip_restriction_enabled', 'boolean DEFAULT false'),
    ('ip_restriction_range', 'text'),
    ('webcam_monitoring', 'boolean DEFAULT true'),
    ('mic_monitoring', 'boolean DEFAULT false'),
    ('copy_paste_prevention', 'boolean DEFAULT true'),
    ('screenshot_prevention', 'boolean DEFAULT true'),
    ('autosave_interval_seconds', 'integer DEFAULT 30'),
    ('internet_disconnect_policy', "text DEFAULT 'resume_from_last_save'"),
    ('guidance_file_url', 'text'),
    ('scheduled_publish_at', 'timestamp'),
]


def add_columns(apps, schema_editor):
    vendor = schema_editor.connection.vendor
    with schema_editor.connection.cursor() as cursor:
        for column, definition in EXAM_COLUMNS:
            if not _table_has_column(schema_editor, 'exams', column):
                col_def = definition
                if vendor != 'postgresql':
                    col_def = col_def.replace('timestamp', 'TEXT').replace('boolean', 'BOOLEAN').replace('integer', 'INTEGER').replace('text', 'TEXT')
                cursor.execute(f'ALTER TABLE exams ADD COLUMN {column} {col_def}')

        pk_uuid = 'uuid PRIMARY KEY' if vendor == 'postgresql' else 'TEXT PRIMARY KEY'
        uuid_type = 'uuid' if vendor == 'postgresql' else 'TEXT'
        text_type = 'text' if vendor == 'postgresql' else 'TEXT'
        timestamp_type = 'timestamptz' if vendor == 'postgresql' else 'TEXT'
        default_now = 'DEFAULT now()' if vendor == 'postgresql' else 'DEFAULT CURRENT_TIMESTAMP'
        cursor.execute(
            f"""
            CREATE TABLE IF NOT EXISTS exam_staff (
                id {pk_uuid},
                exam_id {uuid_type} REFERENCES exams(id),
                teacher_id {uuid_type} REFERENCES teacher_profiles(user_id),
                role {text_type} CHECK (role IN ('designer', 'observer', 'co_grader')),
                created_at {timestamp_type} {default_now},
                UNIQUE (exam_id, teacher_id, role)
            )
            """
        )


def remove_columns(apps, schema_editor):
    vendor = schema_editor.connection.vendor
    with schema_editor.connection.cursor() as cursor:
        cursor.execute('DROP TABLE IF EXISTS exam_staff')
        if vendor != 'postgresql':
            # SQLite: additive columns left in place on rollback (harmless, matches migration 0031's convention).
            return
        for column, _definition in EXAM_COLUMNS:
            cursor.execute(f'ALTER TABLE exams DROP COLUMN IF EXISTS {column}')


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0031_profiles_account_security_fields'),
    ]

    operations = [
        migrations.RunPython(add_columns, remove_columns),
    ]
