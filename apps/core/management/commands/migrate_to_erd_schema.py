import json
import uuid

from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction


NS = uuid.UUID('12345678-1234-5678-1234-567812345678')


def stable_uuid(name):
    return str(uuid.uuid5(NS, str(name)))


def as_json(value, default=None):
    if value in (None, ''):
        return json.dumps(default)
    if isinstance(value, (dict, list, bool, int, float)):
        return json.dumps(value, ensure_ascii=False)
    try:
        json.loads(value)
        return value
    except Exception:
        return json.dumps(value, ensure_ascii=False)


def table_exists(cursor, table):
    return table in connection.introspection.table_names(cursor)


def rows(cursor, sql, params=()):
    cursor.execute(sql, params)
    columns = [col[0] for col in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def execmany(cursor, sql, data):
    if data:
        cursor.executemany(sql, data)


class Command(BaseCommand):
    help = 'Copy legacy core_* data into the ERD tables, then optionally drop old core_* tables.'

    ERD_TABLES = [
        'profiles', 'admin_profiles', 'teacher_profiles', 'student_profiles',
        'academic_manager_profiles', 'user_roles', 'notifications',
        'activity_audit_log', 'org_units', 'courses', 'academic_manager_scopes',
        'exams', 'questions', 'question_sets', 'student_groups',
        'course_audit_log', 'student_group_members', 'group_teachers',
        'exam_assignments', 'exam_questions', 'exam_attempts', 'objections',
        'question_set_items', 'attempt_answers', 'academic_terms',
        'system_settings',
    ]

    DROP_ORDER = [
        'core_assistantreviewassignment',
        'core_assistantquestionsuggestion',
        'core_assistantquestionsubmission',
        'core_assistantexamdraft',
        'core_educationalquestion',
        'core_studentpracticecheck',
        'core_studentexamevent',
        'core_studentquestionanswer',
        'core_studentobjection',
        'core_descriptiveanswerreview',
        'core_examstartauthorization',
        'core_examreschedulerequest',
        'core_examproctorassignment',
        'core_examexecutionreport',
        'core_examapproval',
        'core_examresultpublication',
        'core_examviolationreport',
        'core_studentexamattempt',
        'core_examquestion',
        'core_exam_proctors',
        'core_exam_technical_supports',
        'core_exam',
        'core_question',
        'core_courseclass_students',
        'core_courseclass',
        'core_studentprofile_courses',
        'core_teacherprofile_courses',
        'core_studentprofile',
        'core_teacherprofile',
        'core_institutionadminprofile_managed_units',
        'core_institutionadminprofile',
        'core_systemadminprofile',
        'core_examproctorprofile',
        'core_technicalsupportprofile',
        'core_course',
        'core_academicterm',
        'core_academicunit',
        'core_academicinstitution',
        'core_userloginrecord',
        'core_useractivitylog',
        'core_systemsetting',
        'core_userprofile',
        'core_systemrole',
    ]

    def add_arguments(self, parser):
        parser.add_argument('--drop-old', action='store_true', help='Drop legacy core_* tables after copying.')
        parser.add_argument('--clear-erd', action='store_true', help='Clear ERD tables before copying.')

    def handle(self, *args, **options):
        with connection.cursor() as cursor:
            missing = [table for table in self.ERD_TABLES if not table_exists(cursor, table)]
            if missing:
                raise CommandError(f'ERD tables are missing: {", ".join(missing)}')

        with transaction.atomic():
            with connection.cursor() as cursor:
                if options['clear_erd']:
                    self.clear_erd(cursor)
                counts = self.copy_data(cursor)
                if options['drop_old']:
                    self.drop_old(cursor)

        for key, value in counts.items():
            self.stdout.write(f'{key}: {value}')
        if options['drop_old']:
            self.stdout.write(self.style.WARNING('Legacy core_* tables were dropped.'))
        self.stdout.write(self.style.SUCCESS('ERD data migration finished.'))

    def clear_erd(self, cursor):
        for table in reversed(self.ERD_TABLES):
            cursor.execute(f'DELETE FROM {table}')

    def copy_data(self, cursor):
        counts = {}
        profiles = rows(cursor, '''
            SELECT p.*, u.username, u.email AS auth_email, u.first_name, u.last_name, u.last_login
            FROM core_userprofile p
            JOIN auth_user u ON u.id = p.user_id
        ''')
        profile_by_old = {r['id']: stable_uuid(f"profile:{r['id']}") for r in profiles}
        profile_by_user = {r['user_id']: profile_by_old[r['id']] for r in profiles}

        data = []
        for r in profiles:
            identifier = r.get('personnel_number') or r.get('student_number') or r.get('applicant_code')
            data.append((
                profile_by_old[r['id']], r['full_name'] or r['username'], r.get('first_name'), r.get('last_name'),
                r.get('username'), r.get('auth_email') or r.get('organizational_email'), r.get('mobile'),
                r.get('national_code') or None, identifier or None, None,
                r.get('account_status') or 'active', r.get('last_login'), r.get('created_at'), r.get('updated_at'),
            ))
        execmany(cursor, '''
            INSERT OR REPLACE INTO profiles
            (id, full_name, first_name, last_name, username, email, phone, national_id, identifier, avatar_url, status, last_login_at, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', data)
        counts['profiles'] = len(data)

        institutions = rows(cursor, 'SELECT * FROM core_academicinstitution')
        inst_unit = {r['id']: stable_uuid(f"institution:{r['id']}") for r in institutions}
        unit_rows = [(inst_unit[r['id']], None, 'university', r['name'], r.get('registration_code'), 1 if r.get('status') == 'active' else 0) for r in institutions]

        units = rows(cursor, 'SELECT * FROM core_academicunit')
        unit_by_old = {r['id']: stable_uuid(f"unit:{r['id']}") for r in units}
        for r in units:
            parent = unit_by_old.get(r.get('parent_id')) or inst_unit.get(r.get('institution_id'))
            unit_type = {'faculty': 'faculty', 'department': 'department', 'grade': 'group', 'class_group': 'group'}.get(r.get('unit_type'), 'department')
            unit_rows.append((unit_by_old[r['id']], parent, unit_type, r['name'], r.get('code'), r.get('is_active')))
        execmany(cursor, 'INSERT OR REPLACE INTO org_units (id, parent_id, type, name, code, is_active) VALUES (?, ?, ?, ?, ?, ?)', unit_rows)
        counts['org_units'] = len(unit_rows)

        role_rows = []
        role_map = {
            'super_admin': 'admin',
            'institution_admin': 'academic_manager',
            'exam_manager': 'academic_manager',
            'teacher': 'teacher',
            'student': 'student',
        }
        for r in rows(cursor, 'SELECT p.id, p.created_at, sr.code FROM core_userprofile p JOIN core_systemrole sr ON sr.id = p.role_id'):
            role = role_map.get(r['code'])
            if role:
                role_rows.append((stable_uuid(f"role:{r['id']}:{role}"), profile_by_old[r['id']], role, r.get('created_at')))
        execmany(cursor, 'INSERT OR REPLACE INTO user_roles (id, user_id, role, created_at) VALUES (?, ?, ?, ?)', role_rows)
        counts['user_roles'] = len(role_rows)

        admin_rows = []
        for r in rows(cursor, 'SELECT sap.*, p.organizational_position FROM core_systemadminprofile sap JOIN core_userprofile p ON p.id = sap.profile_id'):
            admin_rows.append((profile_by_old[r['profile_id']], r.get('organizational_position') or 'مدیر سیستم', r.get('access_scope') or 'standard'))
        execmany(cursor, 'INSERT OR REPLACE INTO admin_profiles (user_id, title, access_level) VALUES (?, ?, ?)', admin_rows)
        counts['admin_profiles'] = len(admin_rows)

        teacher_rows = []
        teacher_profile_to_user = {}
        for r in rows(cursor, 'SELECT tp.*, p.department AS profile_department FROM core_teacherprofile tp JOIN core_userprofile p ON p.id = tp.profile_id'):
            user_id = profile_by_old[r['profile_id']]
            teacher_profile_to_user[r['id']] = user_id
            teacher_rows.append((user_id, r.get('personnel_code'), r.get('profile_department'), r.get('specialization'), 'approved', unit_by_old.get(r.get('academic_unit_id'))))
        execmany(cursor, 'INSERT OR REPLACE INTO teacher_profiles (user_id, personnel_code, department, specialty, approval_status, org_unit_id) VALUES (?, ?, ?, ?, ?, ?)', teacher_rows)
        counts['teacher_profiles'] = len(teacher_rows)

        student_rows = []
        student_profile_to_user = {}
        for r in rows(cursor, 'SELECT sp.*, p.department AS profile_department FROM core_studentprofile sp JOIN core_userprofile p ON p.id = sp.profile_id'):
            user_id = profile_by_old[r['profile_id']]
            student_profile_to_user[r['id']] = user_id
            status = {'active': 'active', 'graduated': 'graduated', 'suspended': 'inactive', 'withdrawn': 'inactive'}.get(r.get('enrollment_status'), 'active')
            student_rows.append((user_id, r.get('student_number'), r.get('field_of_study'), r.get('education_level'), r.get('class_group'), r.get('semester'), status, r.get('profile_department'), unit_by_old.get(r.get('academic_unit_id'))))
        execmany(cursor, '''
            INSERT OR REPLACE INTO student_profiles
            (user_id, student_number, field_of_study, degree, class_group, semester, academic_status, department, org_unit_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', student_rows)
        counts['student_profiles'] = len(student_rows)

        manager_rows = []
        for r in rows(cursor, '''
            SELECT p.* FROM core_userprofile p JOIN core_systemrole sr ON sr.id = p.role_id
            WHERE sr.code IN ('institution_admin', 'exam_manager')
        '''):
            manager_rows.append((profile_by_old[r['id']], r.get('personnel_number'), r.get('department'), r.get('responsibility_scope') or r.get('access_scope')))
        execmany(cursor, 'INSERT OR REPLACE INTO academic_manager_profiles (user_id, personnel_code, department, responsibility_area) VALUES (?, ?, ?, ?)', manager_rows)
        counts['academic_manager_profiles'] = len(manager_rows)

        courses = rows(cursor, 'SELECT * FROM core_course')
        course_by_old = {r['id']: stable_uuid(f"course:{r['id']}") for r in courses}
        course_rows = []
        for r in courses:
            credit = r.get('credit_count') if r.get('credit_count') and 1 <= r.get('credit_count') <= 6 else None
            course_rows.append((course_by_old[r['id']], r['title'], r.get('code'), r.get('description'), unit_by_old.get(r.get('academic_unit_id')) or inst_unit.get(r.get('institution_id')), credit))
        execmany(cursor, 'INSERT OR REPLACE INTO courses (id, title, code, description, org_unit_id, credit_units) VALUES (?, ?, ?, ?, ?, ?)', course_rows)
        counts['courses'] = len(course_rows)

        terms = rows(cursor, 'SELECT * FROM core_academicterm')
        term_by_old = {r['id']: stable_uuid(f"term:{r['id']}") for r in terms}
        term_rows = [(term_by_old[r['id']], str(r.get('year') or ''), r.get('title'), r.get('title'), r.get('is_active')) for r in terms]
        execmany(cursor, 'INSERT OR REPLACE INTO academic_terms (id, year, semester, label, is_current) VALUES (?, ?, ?, ?, ?)', term_rows)
        counts['academic_terms'] = len(term_rows)

        questions = rows(cursor, 'SELECT * FROM core_question')
        question_by_old = {r['id']: stable_uuid(f"question:{r['id']}") for r in questions}
        qtype = {'multiple_choice': 'single', 'true_false': 'true_false', 'short_answer': 'short_answer', 'descriptive': 'essay', 'fill_blank': 'fill_blank', 'matching': 'matching'}
        question_rows = []
        for r in questions:
            question_rows.append((
                question_by_old[r['id']], teacher_profile_to_user.get(r.get('teacher_id')), course_by_old.get(r.get('course_id')),
                qtype.get(r.get('question_type'), 'essay'), r.get('difficulty'), r.get('text'), as_json(r.get('options'), []),
                as_json(r.get('correct_answer'), None), None, r.get('suggested_score'), json.dumps([x for x in (r.get('chapter'), r.get('topic')) if x], ensure_ascii=False), None,
            ))
        execmany(cursor, '''
            INSERT OR REPLACE INTO questions
            (id, teacher_id, course_id, type, difficulty, text, options, correct_answer, explanation, default_points, tags, media_url)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', question_rows)
        counts['questions'] = len(question_rows)

        classes = rows(cursor, 'SELECT * FROM core_courseclass')
        group_by_old = {r['id']: stable_uuid(f"group:{r['id']}") for r in classes}
        group_rows = []
        for r in classes:
            group_rows.append((
                group_by_old[r['id']], teacher_profile_to_user.get(r.get('teacher_id')), course_by_old.get(r.get('course_id')),
                rows(cursor, 'SELECT title FROM core_course WHERE id=?', (r.get('course_id'),))[0]['title'] if r.get('course_id') else r['title'],
                None, None, r.get('code'), None, r.get('is_active'), teacher_profile_to_user.get(r.get('teacher_id')),
            ))
        execmany(cursor, '''
            INSERT OR REPLACE INTO student_groups
            (id, teacher_id, course_id, course_name, academic_year, semester, group_code, description, is_active, created_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', group_rows)
        counts['student_groups'] = len(group_rows)

        member_rows = []
        for r in rows(cursor, 'SELECT * FROM core_courseclass_students'):
            student_user_id = student_profile_to_user.get(r.get('studentprofile_id'))
            if not student_user_id:
                continue
            p = rows(cursor, 'SELECT p.full_name, p.national_code, sp.student_number FROM core_studentprofile sp JOIN core_userprofile p ON p.id = sp.profile_id WHERE sp.id=?', (r.get('studentprofile_id'),))[0]
            member_rows.append((stable_uuid(f"groupmember:{r['id']}"), group_by_old.get(r.get('courseclass_id')), student_user_id, p['full_name'], p.get('national_code') or '', p.get('student_number') or ''))
        execmany(cursor, 'INSERT OR REPLACE INTO student_group_members (id, group_id, student_user_id, full_name, national_id, student_number) VALUES (?, ?, ?, ?, ?, ?)', member_rows)
        counts['student_group_members'] = len(member_rows)

        group_teacher_rows = [(group_by_old[r['id']], teacher_profile_to_user.get(r.get('teacher_id')), r.get('created_at')) for r in classes if r.get('teacher_id') in teacher_profile_to_user]
        execmany(cursor, 'INSERT OR REPLACE INTO group_teachers (group_id, teacher_id, created_at) VALUES (?, ?, ?)', group_teacher_rows)
        counts['group_teachers'] = len(group_teacher_rows)

        exams = rows(cursor, 'SELECT * FROM core_exam')
        exam_by_old = {r['id']: stable_uuid(f"exam:{r['id']}") for r in exams}
        exam_rows = []
        for r in exams:
            approval = {'pending_approval': 'pending', 'cancelled': 'rejected'}.get(r.get('status'), 'approved')
            exam_rows.append((
                exam_by_old[r['id']], teacher_profile_to_user.get(r.get('designer_id')), course_by_old.get(r.get('course_id')),
                r['title'], r.get('description'), r.get('duration_minutes'), r.get('starts_at'), r.get('ends_at'),
                r.get('randomize_questions'), r.get('randomize_options'), r.get('negative_marking_enabled'), 0,
                1, r.get('status') not in ('draft', 'pending_approval'), r.get('show_result_after_submit'),
                r.get('passing_score'), r.get('allow_backtracking'), r.get('status') == 'cancelled',
                r.get('emergency_stop_reason') if r.get('status') == 'cancelled' else None, r.get('emergency_resolution_note'),
                approval, None, None, None, None, None,
            ))
        execmany(cursor, '''
            INSERT OR REPLACE INTO exams
            (id, teacher_id, course_id, title, description, duration_minutes, start_at, end_at, shuffle_questions, shuffle_options,
             negative_marking, negative_factor, max_attempts, is_published, show_results_immediately, passing_score, allow_partial,
             is_cancelled, cancel_reason, extend_reason, approval_status, approved_by, approved_at, exam_type, academic_year, semester)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', exam_rows)
        counts['exams'] = len(exam_rows)

        exam_questions = rows(cursor, 'SELECT * FROM core_examquestion')
        exam_question_by_old = {r['id']: stable_uuid(f"examquestion:{r['id']}") for r in exam_questions}
        eq_rows = [(exam_question_by_old[r['id']], exam_by_old.get(r.get('exam_id')), question_by_old.get(r.get('question_id')), r.get('score'), r.get('order')) for r in exam_questions]
        execmany(cursor, 'INSERT OR REPLACE INTO exam_questions (id, exam_id, question_id, points, order_index) VALUES (?, ?, ?, ?, ?)', eq_rows)
        counts['exam_questions'] = len(eq_rows)

        assignment_rows = []
        for r in rows(cursor, 'SELECT e.id exam_id, cc.id group_id FROM core_exam e JOIN core_courseclass cc ON cc.course_id = e.course_id'):
            assignment_rows.append((stable_uuid(f"assignment:{r['exam_id']}:{r['group_id']}"), exam_by_old.get(r['exam_id']), group_by_old.get(r['group_id']), None, None))
        execmany(cursor, 'INSERT OR REPLACE INTO exam_assignments (id, exam_id, group_id, student_profile_id, created_at) VALUES (?, ?, ?, ?, ?)', assignment_rows)
        counts['exam_assignments'] = len(assignment_rows)

        attempts = rows(cursor, 'SELECT * FROM core_studentexamattempt')
        attempt_by_old = {r['id']: stable_uuid(f"attempt:{r['id']}") for r in attempts}
        status_map = {'in_progress': 'in_progress', 'submitted': 'submitted', 'auto_submitted': 'submitted', 'not_started': 'expired', 'blocked': 'expired', 'waiting_proctor': 'in_progress'}
        attempt_rows = [(attempt_by_old[r['id']], exam_by_old.get(r.get('exam_id')), student_profile_to_user.get(r.get('student_id')), r.get('started_at'), r.get('submitted_at'), None, None, 0, status_map.get(r.get('status'), 'in_progress')) for r in attempts]
        execmany(cursor, 'INSERT OR REPLACE INTO exam_attempts (id, exam_id, student_id, started_at, submitted_at, score, max_score, is_graded, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)', attempt_rows)
        counts['exam_attempts'] = len(attempt_rows)

        answer_rows = []
        for r in rows(cursor, 'SELECT a.*, eq.question_id FROM core_studentquestionanswer a JOIN core_examquestion eq ON eq.id = a.exam_question_id'):
            answer_rows.append((stable_uuid(f"answer:{r['id']}"), attempt_by_old.get(r.get('attempt_id')), question_by_old.get(r.get('question_id')), as_json(r.get('selected_options') or r.get('answer_text'), None), None, None, None))
        execmany(cursor, 'INSERT OR REPLACE INTO attempt_answers (id, attempt_id, question_id, answer, is_correct, points_awarded, needs_manual_grading) VALUES (?, ?, ?, ?, ?, ?, ?)', answer_rows)
        counts['attempt_answers'] = len(answer_rows)

        objection_rows = []
        for r in rows(cursor, 'SELECT * FROM core_studentobjection'):
            objection_rows.append((
                stable_uuid(f"objection:{r['id']}"), student_profile_to_user.get(r.get('student_id')), exam_by_old.get(r.get('exam_id')),
                None, question_by_old.get(r.get('question_id')), r.get('objection_type') or 'اعتراض', r.get('objection_text') or '',
                {'pending': 'pending', 'approved': 'resolved', 'rejected': 'rejected'}.get(r.get('decision'), 'pending'),
                r.get('decision_reason'), profile_by_user.get(r.get('reviewed_by_id')), r.get('reviewed_at'),
            ))
        execmany(cursor, '''
            INSERT OR REPLACE INTO objections
            (id, student_id, exam_id, attempt_id, question_id, subject, message, status, teacher_response, resolved_by, resolved_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', objection_rows)
        counts['objections'] = len(objection_rows)

        audit_rows = []
        for r in rows(cursor, 'SELECT * FROM core_useractivitylog'):
            audit_rows.append((stable_uuid(f"audit:{r['id']}"), profile_by_user.get(r.get('user_id')), r.get('action'), r.get('action') or 'system', None, r.get('description'), as_json(r.get('metadata'), {})))
        execmany(cursor, 'INSERT OR REPLACE INTO activity_audit_log (id, actor_id, action, entity_type, entity_id, reason, metadata) VALUES (?, ?, ?, ?, ?, ?, ?)', audit_rows)
        counts['activity_audit_log'] = len(audit_rows)

        settings_rows = []
        if table_exists(cursor, 'core_systemsetting'):
            for r in rows(cursor, 'SELECT * FROM core_systemsetting'):
                settings_rows.append((r['key'], as_json(r['value'], {}), r.get('description'), None))
        execmany(cursor, 'INSERT OR REPLACE INTO system_settings (key, value, description, updated_by) VALUES (?, ?, ?, ?)', settings_rows)
        counts['system_settings'] = len(settings_rows)

        return counts

    def drop_old(self, cursor):
        if connection.vendor == 'postgresql':
            cursor.execute('SET session_replication_role = replica')
        else:
            cursor.execute('PRAGMA foreign_keys=OFF')
        for table in self.DROP_ORDER:
            if table_exists(cursor, table):
                if connection.vendor == 'postgresql':
                    cursor.execute(f'DROP TABLE {table} CASCADE')
                else:
                    cursor.execute(f'DROP TABLE {table}')
        if connection.vendor == 'postgresql':
            cursor.execute('SET session_replication_role = DEFAULT')
        else:
            cursor.execute('PRAGMA foreign_keys=ON')
