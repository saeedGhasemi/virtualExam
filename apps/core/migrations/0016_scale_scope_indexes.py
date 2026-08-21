from django.db import migrations


def add_scale_scope_indexes(apps, schema_editor):
    if schema_editor.connection.vendor not in {'postgresql', 'sqlite'}:
        return
    statements = [
        "CREATE INDEX IF NOT EXISTS idx_erd_profiles_username_email ON profiles (username, email)",
        "CREATE INDEX IF NOT EXISTS idx_erd_roles_user_role ON user_roles (user_id, role)",
        "CREATE INDEX IF NOT EXISTS idx_erd_org_units_parent ON org_units (parent_id)",
        "CREATE INDEX IF NOT EXISTS idx_erd_manager_scopes_manager_unit ON academic_manager_scopes (manager_id, org_unit_id)",
        "CREATE INDEX IF NOT EXISTS idx_erd_teacher_profiles_org_user ON teacher_profiles (org_unit_id, user_id)",
        "CREATE INDEX IF NOT EXISTS idx_erd_student_profiles_org_user ON student_profiles (org_unit_id, user_id)",
        "CREATE INDEX IF NOT EXISTS idx_erd_courses_org_id ON courses (org_unit_id, id)",
        "CREATE INDEX IF NOT EXISTS idx_erd_student_groups_teacher_course ON student_groups (teacher_id, course_id)",
        "CREATE INDEX IF NOT EXISTS idx_erd_group_teachers_teacher_group ON group_teachers (teacher_id, group_id)",
        "CREATE INDEX IF NOT EXISTS idx_erd_sgm_group_student ON student_group_members (group_id, student_user_id)",
        "CREATE INDEX IF NOT EXISTS idx_erd_sgm_student_group ON student_group_members (student_user_id, group_id)",
        "CREATE INDEX IF NOT EXISTS idx_erd_exams_teacher_course_status ON exams (teacher_id, course_id, is_published, is_cancelled)",
        "CREATE INDEX IF NOT EXISTS idx_erd_exams_lifecycle_start ON exams (lifecycle_status, start_at)",
        "CREATE INDEX IF NOT EXISTS idx_erd_exam_assignments_exam_student ON exam_assignments (exam_id, student_profile_id)",
        "CREATE INDEX IF NOT EXISTS idx_erd_exam_assignments_exam_group ON exam_assignments (exam_id, group_id)",
        "CREATE INDEX IF NOT EXISTS idx_erd_exam_attempts_exam_student_status ON exam_attempts (exam_id, student_id, status)",
        "CREATE INDEX IF NOT EXISTS idx_erd_exam_attempts_student_started ON exam_attempts (student_id, started_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_erd_exam_questions_exam_order ON exam_questions (exam_id, order_index)",
        "CREATE INDEX IF NOT EXISTS idx_erd_questions_teacher_course ON questions (teacher_id, course_id)",
        "CREATE INDEX IF NOT EXISTS idx_erd_attempt_answers_attempt_question ON attempt_answers (attempt_id, question_id)",
        "CREATE UNIQUE INDEX IF NOT EXISTS uniq_erd_attempt_answers_attempt_question ON attempt_answers (attempt_id, question_id)",
        "CREATE INDEX IF NOT EXISTS idx_erd_objections_exam_student_status ON objections (exam_id, student_id, status)",
    ]
    with schema_editor.connection.cursor() as cursor:
        for statement in statements:
            cursor.execute(statement)


def remove_scale_scope_indexes(apps, schema_editor):
    if schema_editor.connection.vendor not in {'postgresql', 'sqlite'}:
        return
    names = [
        'idx_erd_profiles_username_email',
        'idx_erd_roles_user_role',
        'idx_erd_org_units_parent',
        'idx_erd_manager_scopes_manager_unit',
        'idx_erd_teacher_profiles_org_user',
        'idx_erd_student_profiles_org_user',
        'idx_erd_courses_org_id',
        'idx_erd_student_groups_teacher_course',
        'idx_erd_group_teachers_teacher_group',
        'idx_erd_sgm_group_student',
        'idx_erd_sgm_student_group',
        'idx_erd_exams_teacher_course_status',
        'idx_erd_exams_lifecycle_start',
        'idx_erd_exam_assignments_exam_student',
        'idx_erd_exam_assignments_exam_group',
        'idx_erd_exam_attempts_exam_student_status',
        'idx_erd_exam_attempts_student_started',
        'idx_erd_exam_questions_exam_order',
        'idx_erd_questions_teacher_course',
        'idx_erd_attempt_answers_attempt_question',
        'uniq_erd_attempt_answers_attempt_question',
        'idx_erd_objections_exam_student_status',
    ]
    with schema_editor.connection.cursor() as cursor:
        for name in names:
            cursor.execute(f'DROP INDEX IF EXISTS {name}')


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0015_erd_state_machine_statuses'),
    ]

    operations = [
        migrations.RunPython(add_scale_scope_indexes, remove_scale_scope_indexes),
    ]
