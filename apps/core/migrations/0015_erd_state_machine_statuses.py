from django.db import migrations


def table_has_column(schema_editor, table, column):
    with schema_editor.connection.cursor() as cursor:
        if schema_editor.connection.vendor == 'sqlite':
            cursor.execute(f"PRAGMA table_info({table})")
            return any(row[1] == column for row in cursor.fetchall())
        cursor.execute(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_name = %s AND column_name = %s
            """,
            [table, column],
        )
        return cursor.fetchone() is not None


def apply_state_machine_statuses(apps, schema_editor):
    if schema_editor.connection.vendor == 'sqlite':
        with schema_editor.connection.cursor() as cursor:
            if not table_has_column(schema_editor, 'exams', 'lifecycle_status'):
                cursor.execute("ALTER TABLE exams ADD COLUMN lifecycle_status text DEFAULT 'draft'")
            cursor.execute(
                """
                UPDATE exams
                SET lifecycle_status = CASE
                    WHEN COALESCE(is_cancelled, 0) THEN 'closed'
                    WHEN COALESCE(is_published, 0) THEN 'published'
                    WHEN approval_status = 'approved' THEN 'approved'
                    WHEN approval_status = 'rejected' THEN 'draft'
                    WHEN approval_status = 'pending' THEN 'pending_approval'
                    ELSE COALESCE(lifecycle_status, 'draft')
                END
                """
            )
        return
    if schema_editor.connection.vendor != 'postgresql':
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """
            ALTER TABLE exams
            ADD COLUMN IF NOT EXISTS lifecycle_status text DEFAULT 'draft'
            """
        )
        cursor.execute(
            """
            UPDATE exams
            SET lifecycle_status = CASE
                WHEN COALESCE(is_cancelled, false) THEN 'closed'
                WHEN COALESCE(is_published, false) THEN 'published'
                WHEN approval_status = 'approved' THEN 'approved'
                WHEN approval_status = 'rejected' THEN 'draft'
                WHEN approval_status = 'pending' THEN 'pending_approval'
                ELSE COALESCE(lifecycle_status, 'draft')
            END
            """
        )
        cursor.execute("ALTER TABLE exams DROP CONSTRAINT IF EXISTS exams_lifecycle_status_check")
        cursor.execute(
            """
            ALTER TABLE exams
            ADD CONSTRAINT exams_lifecycle_status_check
            CHECK (lifecycle_status IN ('draft','pending_approval','approved','published','in_progress','closed','archived'))
            """
        )
        cursor.execute("ALTER TABLE exam_attempts DROP CONSTRAINT IF EXISTS exam_attempts_status_check")
        cursor.execute(
            """
            ALTER TABLE exam_attempts
            ADD CONSTRAINT exam_attempts_status_check
            CHECK (status IN ('in_progress','submitted','graded','expired','disputed'))
            """
        )
        cursor.execute("ALTER TABLE objections DROP CONSTRAINT IF EXISTS objections_status_check")
        cursor.execute(
            """
            ALTER TABLE objections
            ADD CONSTRAINT objections_status_check
            CHECK (status IN ('open','under_review','resolved_accepted','resolved_rejected','escalated','resolved_final'))
            """
        )
        cursor.execute(
            """
            UPDATE objections
            SET status = CASE status
                WHEN 'pending' THEN 'open'
                WHEN 'in_review' THEN 'under_review'
                WHEN 'resolved' THEN 'resolved_accepted'
                WHEN 'rejected' THEN 'resolved_rejected'
                ELSE status
            END
            """
        )


def rollback_state_machine_statuses(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("ALTER TABLE objections DROP CONSTRAINT IF EXISTS objections_status_check")
        cursor.execute(
            """
            UPDATE objections
            SET status = CASE status
                WHEN 'open' THEN 'pending'
                WHEN 'under_review' THEN 'in_review'
                WHEN 'resolved_accepted' THEN 'resolved'
                WHEN 'resolved_rejected' THEN 'rejected'
                WHEN 'escalated' THEN 'in_review'
                WHEN 'resolved_final' THEN 'resolved'
                ELSE status
            END
            """
        )
        cursor.execute(
            """
            ALTER TABLE objections
            ADD CONSTRAINT objections_status_check
            CHECK (status IN ('pending','in_review','resolved','rejected'))
            """
        )
        cursor.execute("ALTER TABLE exam_attempts DROP CONSTRAINT IF EXISTS exam_attempts_status_check")
        cursor.execute(
            """
            ALTER TABLE exam_attempts
            ADD CONSTRAINT exam_attempts_status_check
            CHECK (status IN ('in_progress','submitted','graded','expired'))
            """
        )
        cursor.execute("ALTER TABLE exams DROP CONSTRAINT IF EXISTS exams_lifecycle_status_check")
        cursor.execute("ALTER TABLE exams DROP COLUMN IF EXISTS lifecycle_status")


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0014_create_erd_tables'),
    ]

    operations = [
        migrations.RunPython(apply_state_machine_statuses, rollback_state_machine_statuses),
    ]
