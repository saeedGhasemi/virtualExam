from django.db import migrations


def create_erd_tables(apps, schema_editor):
    vendor = schema_editor.connection.vendor
    if vendor == 'postgresql':
        uuid = 'uuid'
        text = 'text'
        boolean = 'boolean'
        integer = 'integer'
        smallint = 'smallint'
        numeric = 'numeric'
        timestamp = 'timestamptz'
        json_type = 'jsonb'
        pk_uuid = 'uuid PRIMARY KEY'
        default_now = 'DEFAULT now()'
    else:
        uuid = 'TEXT'
        text = 'TEXT'
        boolean = 'BOOLEAN'
        integer = 'INTEGER'
        smallint = 'INTEGER'
        numeric = 'NUMERIC'
        timestamp = 'TEXT'
        json_type = 'JSON'
        pk_uuid = 'TEXT PRIMARY KEY'
        default_now = "DEFAULT CURRENT_TIMESTAMP"

    statements = [
        f"""
        CREATE TABLE IF NOT EXISTS profiles (
            id {pk_uuid},
            full_name {text} NOT NULL,
            first_name {text},
            last_name {text},
            username {text} UNIQUE,
            email {text},
            phone {text},
            national_id {text} UNIQUE,
            identifier {text},
            avatar_url {text},
            status {text} CHECK (status IN ('active','inactive','blocked')) DEFAULT 'active',
            last_login_at {timestamp},
            created_at {timestamp} {default_now},
            updated_at {timestamp}
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS admin_profiles (
            user_id {uuid} PRIMARY KEY REFERENCES profiles(id),
            title {text},
            access_level {text} DEFAULT 'standard'
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS org_units (
            id {pk_uuid},
            parent_id {uuid} REFERENCES org_units(id),
            type {text} CHECK (type IN ('university','faculty','department','group')),
            name {text} NOT NULL,
            code {text},
            is_active {boolean} DEFAULT true
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS teacher_profiles (
            user_id {uuid} PRIMARY KEY REFERENCES profiles(id),
            personnel_code {text},
            department {text},
            specialty {text},
            approval_status {text} CHECK (approval_status IN ('pending','approved','rejected')) DEFAULT 'pending',
            org_unit_id {uuid} REFERENCES org_units(id)
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS student_profiles (
            user_id {uuid} PRIMARY KEY REFERENCES profiles(id),
            student_number {text},
            field_of_study {text},
            degree {text},
            class_group {text},
            semester {text},
            academic_status {text} CHECK (academic_status IN ('active','leave','graduated','inactive')) DEFAULT 'active',
            department {text},
            org_unit_id {uuid} REFERENCES org_units(id)
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS academic_manager_profiles (
            user_id {uuid} PRIMARY KEY REFERENCES profiles(id),
            personnel_code {text},
            department {text},
            responsibility_area {text}
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS user_roles (
            id {pk_uuid},
            user_id {uuid} REFERENCES profiles(id),
            role {text} CHECK (role IN ('admin','academic_manager','teacher','student')),
            created_at {timestamp} {default_now}
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS notifications (
            id {pk_uuid},
            user_id {uuid} REFERENCES profiles(id),
            type {text},
            title {text} NOT NULL,
            message {text},
            link {text},
            is_read {boolean} DEFAULT false
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS activity_audit_log (
            id {pk_uuid},
            actor_id {uuid} REFERENCES profiles(id),
            action {text} NOT NULL,
            entity_type {text} NOT NULL,
            entity_id {uuid},
            reason {text},
            metadata {json_type}
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS courses (
            id {pk_uuid},
            title {text} NOT NULL,
            code {text} UNIQUE,
            description {text},
            org_unit_id {uuid} REFERENCES org_units(id),
            credit_units {smallint} CHECK (credit_units BETWEEN 1 AND 6)
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS academic_manager_scopes (
            id {pk_uuid},
            manager_id {uuid} REFERENCES academic_manager_profiles(user_id),
            org_unit_id {uuid} REFERENCES org_units(id),
            created_at {timestamp} {default_now},
            UNIQUE (manager_id, org_unit_id)
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS exams (
            id {pk_uuid},
            teacher_id {uuid} REFERENCES teacher_profiles(user_id),
            course_id {uuid} REFERENCES courses(id),
            title {text} NOT NULL,
            description {text},
            duration_minutes {integer} CHECK (duration_minutes > 0),
            start_at {timestamp},
            end_at {timestamp},
            shuffle_questions {boolean},
            shuffle_options {boolean},
            negative_marking {boolean},
            negative_factor {numeric} CHECK (negative_factor >= 0 AND negative_factor <= 1),
            max_attempts {integer} DEFAULT 1,
            is_published {boolean},
            show_results_immediately {boolean},
            passing_score {numeric},
            allow_partial {boolean},
            is_cancelled {boolean},
            cancel_reason {text},
            extend_reason {text},
            approval_status {text} CHECK (approval_status IN ('pending','approved','rejected')),
            approved_by {uuid} REFERENCES profiles(id),
            approved_at {timestamp},
            exam_type {text},
            academic_year {text},
            semester {text},
            CHECK (end_at IS NULL OR start_at IS NULL OR end_at > start_at)
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS questions (
            id {pk_uuid},
            teacher_id {uuid} REFERENCES teacher_profiles(user_id),
            course_id {uuid} REFERENCES courses(id),
            type {text} CHECK (type IN ('single','multi','true_false','short_answer','essay','fill_blank','matching','ordering')),
            difficulty {text} CHECK (difficulty IN ('easy','medium','hard')),
            text {text} NOT NULL,
            options {json_type},
            correct_answer {json_type},
            explanation {text},
            default_points {numeric} CHECK (default_points > 0),
            tags {text},
            media_url {text}
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS question_sets (
            id {pk_uuid},
            title {text} NOT NULL,
            description {text},
            course_id {uuid} REFERENCES courses(id),
            created_by {uuid} REFERENCES profiles(id),
            target_teacher_id {uuid} REFERENCES teacher_profiles(user_id),
            status {text} CHECK (status IN ('draft','shared','archived')),
            status_note {text}
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS student_groups (
            id {pk_uuid},
            teacher_id {uuid} REFERENCES teacher_profiles(user_id),
            course_id {uuid} REFERENCES courses(id),
            course_name {text} NOT NULL,
            academic_year {text} NOT NULL,
            semester {text},
            group_code {text},
            description {text},
            is_active {boolean},
            created_by {uuid} REFERENCES profiles(id)
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS course_audit_log (
            id {pk_uuid},
            course_id {uuid} REFERENCES courses(id),
            changed_by {uuid} REFERENCES profiles(id),
            action {text} CHECK (action IN ('create','update','delete')),
            summary {text},
            old_values {json_type},
            new_values {json_type}
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS student_group_members (
            id {pk_uuid},
            group_id {uuid} REFERENCES student_groups(id),
            student_user_id {uuid} REFERENCES profiles(id),
            full_name {text} NOT NULL,
            national_id {text} NOT NULL,
            student_number {text} NOT NULL
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS group_teachers (
            group_id {uuid} REFERENCES student_groups(id),
            teacher_id {uuid} REFERENCES teacher_profiles(user_id),
            created_at {timestamp} {default_now},
            PRIMARY KEY (group_id, teacher_id)
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS exam_assignments (
            id {pk_uuid},
            exam_id {uuid} REFERENCES exams(id),
            group_id {uuid} REFERENCES student_groups(id),
            student_profile_id {uuid} REFERENCES student_profiles(user_id),
            created_at {timestamp} {default_now},
            CHECK (group_id IS NOT NULL OR student_profile_id IS NOT NULL)
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS exam_questions (
            id {pk_uuid},
            exam_id {uuid} REFERENCES exams(id),
            question_id {uuid} REFERENCES questions(id),
            points {numeric} CHECK (points > 0),
            order_index {integer},
            UNIQUE (exam_id, order_index)
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS exam_attempts (
            id {pk_uuid},
            exam_id {uuid} REFERENCES exams(id),
            student_id {uuid} REFERENCES profiles(id),
            started_at {timestamp},
            submitted_at {timestamp},
            score {numeric},
            max_score {numeric},
            is_graded {boolean},
            status {text} CHECK (status IN ('in_progress','submitted','graded','expired'))
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS objections (
            id {pk_uuid},
            student_id {uuid} REFERENCES profiles(id),
            exam_id {uuid} REFERENCES exams(id),
            attempt_id {uuid} REFERENCES exam_attempts(id),
            question_id {uuid} REFERENCES questions(id),
            subject {text} NOT NULL,
            message {text} NOT NULL,
            status {text} CHECK (status IN ('pending','in_review','resolved','rejected')),
            teacher_response {text},
            resolved_by {uuid} REFERENCES profiles(id),
            resolved_at {timestamp}
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS question_set_items (
            id {pk_uuid},
            set_id {uuid} REFERENCES question_sets(id),
            question_id {uuid} REFERENCES questions(id),
            order_index {integer},
            points {numeric}
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS attempt_answers (
            id {pk_uuid},
            attempt_id {uuid} REFERENCES exam_attempts(id),
            question_id {uuid} REFERENCES questions(id),
            answer {json_type},
            is_correct {boolean},
            points_awarded {numeric},
            needs_manual_grading {boolean},
            UNIQUE (attempt_id, question_id)
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS academic_terms (
            id {pk_uuid},
            year {text} NOT NULL,
            semester {text},
            label {text},
            is_current {boolean}
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS system_settings (
            key {text} PRIMARY KEY,
            value {json_type} NOT NULL,
            description {text},
            updated_by {uuid} REFERENCES profiles(id)
        )
        """,
    ]

    with schema_editor.connection.cursor() as cursor:
        for statement in statements:
            cursor.execute(statement)


def drop_erd_tables(apps, schema_editor):
    tables = [
        'system_settings',
        'academic_terms',
        'attempt_answers',
        'question_set_items',
        'objections',
        'exam_attempts',
        'exam_questions',
        'exam_assignments',
        'group_teachers',
        'student_group_members',
        'course_audit_log',
        'student_groups',
        'question_sets',
        'questions',
        'exams',
        'academic_manager_scopes',
        'courses',
        'activity_audit_log',
        'notifications',
        'user_roles',
        'academic_manager_profiles',
        'student_profiles',
        'teacher_profiles',
        'org_units',
        'admin_profiles',
        'profiles',
    ]
    with schema_editor.connection.cursor() as cursor:
        for table in tables:
            cursor.execute(f'DROP TABLE IF EXISTS {table}')


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0013_systemsetting'),
    ]

    operations = [
        migrations.RunPython(create_erd_tables, drop_erd_tables),
    ]
