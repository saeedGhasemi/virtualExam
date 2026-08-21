import json
import uuid
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import connection, transaction
from django.utils import timezone


NS = uuid.UUID("f9cf531d-f77d-4c3e-bdd3-716d6af0a327")


def sid(name):
    return str(uuid.uuid5(NS, name))


ROLE_NATIONAL_PREFIX = {
    "admin": "9001",
    "academic_manager": "9101",
    "teacher": "9201",
    "student": "9301",
}


ROLE_AVATARS = {
    "admin": "/static/img/online-exam-3d.png",
    "academic_manager": "/static/img/hero-educators.png",
    "teacher": "/static/img/hero-teacher-laptop.png",
    "student": "/static/img/student-hero.png",
}

QUESTION_IMAGES = [
    "/static/img/exam-session.svg",
    "/static/img/exam-dashboard.svg",
    "/static/img/hero-exam.jpg",
    "/static/img/online-exam-3d.png",
    "/static/img/hero-student-1.png",
    "/static/img/hero-student-2.png",
    "/static/img/hero-student-3.png",
    "/static/img/register-illustration.png",
    "/static/img/login-illustration.png",
    "/static/img/auth-side.jpg",
]


class Command(BaseCommand):
    help = "Seed 10 production-safe demo records for the main ERD sections."

    def add_arguments(self, parser):
        parser.add_argument("--count", type=int, default=10)

    def execute_sql(self, cursor, sql, params):
        cursor.execute(sql, params)

    def upsert_profile(self, cursor, profile_id, role, index):
        first_name = {
            "academic_manager": "مدیر",
            "teacher": "استاد",
            "student": "دانشجو",
            "admin": "مدیر سامانه",
        }.get(role, "کاربر")
        role_label = {
            "academic_manager": "آموزشی",
            "teacher": "نمونه",
            "student": "نمونه",
            "admin": "نمونه",
        }.get(role, "نمونه")
        username = f"demo10_{role}_{index:02d}"
        email = f"{username}@metaquizy.ir"
        full_name = f"{first_name} {role_label} {index:02d}"
        national_id = f"{ROLE_NATIONAL_PREFIX.get(role, '9901')}{index:06d}"
        avatar_url = ROLE_AVATARS.get(role, "/static/img/metaquiz-logo.svg")
        self.execute_sql(
            cursor,
            """
            INSERT INTO profiles (
                id, full_name, first_name, last_name, username, email, phone,
                national_id, identifier, avatar_url, status, created_at, updated_at, gender,
                password_method, must_change_password, email_verified_required
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'active', CURRENT_TIMESTAMP,
                    CURRENT_TIMESTAMP, %s, 'activation_link', false, false)
            ON CONFLICT (id) DO UPDATE SET
                full_name = EXCLUDED.full_name,
                first_name = EXCLUDED.first_name,
                last_name = EXCLUDED.last_name,
                username = EXCLUDED.username,
                email = EXCLUDED.email,
                phone = EXCLUDED.phone,
                national_id = EXCLUDED.national_id,
                identifier = EXCLUDED.identifier,
                avatar_url = EXCLUDED.avatar_url,
                status = 'active',
                updated_at = CURRENT_TIMESTAMP
            """,
            [
                profile_id,
                full_name,
                first_name,
                f"{role_label} {index:02d}",
                username,
                email,
                f"0912{index:07d}"[-11:],
                national_id,
                f"DEMO10-{role.upper()}-{index:02d}",
                avatar_url,
                "female" if index % 2 == 0 else "male",
            ],
        )
        self.execute_sql(
            cursor,
            """
            INSERT INTO user_roles (id, user_id, role, created_at)
            VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
            ON CONFLICT (id) DO UPDATE SET role = EXCLUDED.role
            """,
            [sid(f"role:{role}:{index}"), profile_id, role],
        )

        User = get_user_model()
        user, _ = User.objects.update_or_create(
            username=username,
            defaults={
                "email": email,
                "first_name": full_name,
                "is_active": True,
                "is_staff": role == "admin",
                "is_superuser": role == "admin",
            },
        )
        user.set_password("Demo@12345")
        user.save()

    def handle(self, *args, **options):
        count = options["count"]
        now = timezone.now()

        with transaction.atomic(), connection.cursor() as cursor:
            admin_id = sid("admin:01")
            self.upsert_profile(cursor, admin_id, "admin", 1)
            self.execute_sql(
                cursor,
                """
                INSERT INTO admin_profiles (user_id, title, access_level)
                VALUES (%s, 'مدیر نمونه سامانه', 'full')
                ON CONFLICT (user_id) DO UPDATE SET title = EXCLUDED.title, access_level = EXCLUDED.access_level
                """,
                [admin_id],
            )

            org_ids = []
            for i in range(1, count + 1):
                org_id = sid(f"org:{i}")
                org_ids.append(org_id)
                parent_id = org_ids[0] if i > 1 else None
                unit_type = "university" if i == 1 else ("faculty" if i <= 4 else "department")
                self.execute_sql(
                    cursor,
                    """
                    INSERT INTO org_units (id, parent_id, type, name, code, is_active)
                    VALUES (%s, %s, %s, %s, %s, true)
                    ON CONFLICT (id) DO UPDATE SET
                        parent_id = EXCLUDED.parent_id,
                        type = EXCLUDED.type,
                        name = EXCLUDED.name,
                        code = EXCLUDED.code,
                        is_active = true
                    """,
                    [org_id, parent_id, unit_type, f"واحد نمونه {i:02d}", f"DEMO10-OU-{i:02d}"],
                )

            term_ids = []
            for i in range(1, count + 1):
                term_id = sid(f"term:{i}")
                term_ids.append(term_id)
                self.execute_sql(
                    cursor,
                    """
                    INSERT INTO academic_terms (id, year, semester, label, is_current, start_date, end_date, description, is_active)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, true)
                    ON CONFLICT (id) DO UPDATE SET
                        year = EXCLUDED.year,
                        semester = EXCLUDED.semester,
                        label = EXCLUDED.label,
                        is_current = EXCLUDED.is_current,
                        start_date = EXCLUDED.start_date,
                        end_date = EXCLUDED.end_date,
                        description = EXCLUDED.description,
                        is_active = true
                    """,
                    [
                        term_id,
                        str(1405 + ((i - 1) // 2)),
                        "نیمسال اول" if i % 2 else "نیمسال دوم",
                        f"ترم نمونه {i:02d}",
                        i == 1,
                        f"140{5 + ((i - 1) // 2)}/07/01",
                        f"140{5 + ((i - 1) // 2)}/11/30",
                        "داده نمونه برای بررسی صفحه نیمسال‌ها",
                    ],
                )

            manager_ids = []
            teacher_ids = []
            student_ids = []
            for i in range(1, count + 1):
                manager_id = sid(f"academic_manager:{i}")
                teacher_id = sid(f"teacher:{i}")
                student_id = sid(f"student:{i}")
                manager_ids.append(manager_id)
                teacher_ids.append(teacher_id)
                student_ids.append(student_id)

                self.upsert_profile(cursor, manager_id, "academic_manager", i)
                self.execute_sql(
                    cursor,
                    """
                    INSERT INTO academic_manager_profiles
                        (user_id, personnel_code, department, responsibility_area, title, access_type, include_child_units)
                    VALUES (%s, %s, %s, %s, %s, 'unit_manager', true)
                    ON CONFLICT (user_id) DO UPDATE SET
                        personnel_code = EXCLUDED.personnel_code,
                        department = EXCLUDED.department,
                        responsibility_area = EXCLUDED.responsibility_area,
                        title = EXCLUDED.title,
                        access_type = EXCLUDED.access_type,
                        include_child_units = true
                    """,
                    [manager_id, f"MGR-DEMO10-{i:02d}", f"واحد نمونه {i:02d}", "نظارت بر آزمون‌های نمونه", "مدیر آموزشی نمونه"],
                )
                self.execute_sql(
                    cursor,
                    """
                    INSERT INTO academic_manager_scopes (id, manager_id, org_unit_id, created_at)
                    VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
                    ON CONFLICT (id) DO UPDATE SET org_unit_id = EXCLUDED.org_unit_id
                    """,
                    [sid(f"manager-scope:{i}"), manager_id, org_ids[(i - 1) % count]],
                )

                self.upsert_profile(cursor, teacher_id, "teacher", i)
                self.execute_sql(
                    cursor,
                    """
                    INSERT INTO teacher_profiles (user_id, personnel_code, department, specialty, approval_status, org_unit_id)
                    VALUES (%s, %s, %s, %s, 'approved', %s)
                    ON CONFLICT (user_id) DO UPDATE SET
                        personnel_code = EXCLUDED.personnel_code,
                        department = EXCLUDED.department,
                        specialty = EXCLUDED.specialty,
                        approval_status = 'approved',
                        org_unit_id = EXCLUDED.org_unit_id
                    """,
                    [teacher_id, f"TCH-DEMO10-{i:02d}", f"گروه نمونه {i:02d}", "آزمون الکترونیکی", org_ids[(i - 1) % count]],
                )

                self.upsert_profile(cursor, student_id, "student", i)
                self.execute_sql(
                    cursor,
                    """
                    INSERT INTO student_profiles
                        (user_id, student_number, field_of_study, degree, class_group, semester,
                         academic_status, department, org_unit_id, entry_year, admission_type,
                         password_method, must_change_password, send_welcome_message)
                    VALUES (%s, %s, 'مهندسی نمونه', 'کارشناسی', %s, %s, 'active', %s, %s, '1405',
                            'روزانه', 'activation_link', false, false)
                    ON CONFLICT (user_id) DO UPDATE SET
                        student_number = EXCLUDED.student_number,
                        field_of_study = EXCLUDED.field_of_study,
                        degree = EXCLUDED.degree,
                        class_group = EXCLUDED.class_group,
                        semester = EXCLUDED.semester,
                        academic_status = 'active',
                        department = EXCLUDED.department,
                        org_unit_id = EXCLUDED.org_unit_id,
                        entry_year = EXCLUDED.entry_year
                    """,
                    [student_id, f"STU-DEMO10-{i:02d}", f"گروه {i:02d}", str((i % 8) + 1), f"گروه نمونه {i:02d}", org_ids[(i - 1) % count]],
                )

            course_ids = []
            for i in range(1, count + 1):
                course_id = sid(f"course:{i}")
                course_ids.append(course_id)
                self.execute_sql(
                    cursor,
                    """
                    INSERT INTO courses (id, title, code, description, org_unit_id, credit_units)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                        title = EXCLUDED.title,
                        code = EXCLUDED.code,
                        description = EXCLUDED.description,
                        org_unit_id = EXCLUDED.org_unit_id,
                        credit_units = EXCLUDED.credit_units
                    """,
                    [course_id, f"درس نمونه {i:02d}", f"CRS-DEMO10-{i:02d}", "درس نمونه برای تست صفحات درس و آزمون", org_ids[(i - 1) % count], (i % 4) + 1],
                )

            group_ids = []
            for i in range(1, count + 1):
                group_id = sid(f"group:{i}")
                group_ids.append(group_id)
                self.execute_sql(
                    cursor,
                    """
                    INSERT INTO student_groups (
                        id, teacher_id, course_id, course_name, academic_year, semester, group_code,
                        description, is_active, created_by, capacity, min_students, waitlist_enabled,
                        waitlist_capacity, requires_teacher_approval, offering_type, class_schedule,
                        class_location, registration_start_at, registration_end_at, status
                    )
                    VALUES (%s, %s, %s, %s, '1405-1406', %s, %s, %s, true, %s, 30, 5, true, 10, false,
                            'حضوری', %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP + interval '30 days', 'active')
                    ON CONFLICT (id) DO UPDATE SET
                        teacher_id = EXCLUDED.teacher_id,
                        course_id = EXCLUDED.course_id,
                        course_name = EXCLUDED.course_name,
                        semester = EXCLUDED.semester,
                        group_code = EXCLUDED.group_code,
                        description = EXCLUDED.description,
                        is_active = true,
                        status = 'active'
                    """,
                    [
                        group_id,
                        teacher_ids[(i - 1) % count],
                        course_ids[(i - 1) % count],
                        f"درس نمونه {i:02d}",
                        "نیمسال اول" if i % 2 else "نیمسال دوم",
                        f"GRP-DEMO10-{i:02d}",
                        "گروه نمونه برای بررسی لیست گروه‌ها",
                        admin_id,
                        f"شنبه و دوشنبه ساعت {8 + i}:00",
                        f"کلاس نمونه {i:02d}",
                    ],
                )
                self.execute_sql(
                    cursor,
                    """
                    INSERT INTO student_group_members (id, group_id, student_user_id, full_name, national_id, student_number)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                        group_id = EXCLUDED.group_id,
                        student_user_id = EXCLUDED.student_user_id,
                        full_name = EXCLUDED.full_name,
                        national_id = EXCLUDED.national_id,
                        student_number = EXCLUDED.student_number
                    """,
                    [sid(f"group-member:{i}"), group_id, student_ids[(i - 1) % count], f"دانشجو نمونه {i:02d}", f"100000{i:04d}", f"STU-DEMO10-{i:02d}"],
                )
                self.execute_sql(
                    cursor,
                    """
                    INSERT INTO student_course_enrollments (id, student_user_id, course_id, created_at)
                    VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
                    ON CONFLICT (id) DO UPDATE SET course_id = EXCLUDED.course_id
                    """,
                    [sid(f"course-enrollment:{i}"), student_ids[(i - 1) % count], course_ids[(i - 1) % count]],
                )

            question_ids = []
            for i in range(1, count + 1):
                question_id = sid(f"question:{i}")
                question_ids.append(question_id)
                options_json = json.dumps(["گزینه الف", "گزینه ب", "گزینه ج", "گزینه د"], ensure_ascii=False)
                answer_json = json.dumps({"value": "گزینه ب"}, ensure_ascii=False)
                self.execute_sql(
                    cursor,
                    """
                    INSERT INTO questions
                        (id, teacher_id, course_id, type, difficulty, text, options, correct_answer,
                         explanation, default_points, tags, media_url)
                    VALUES (%s, %s, %s, 'single', %s, %s, %s::jsonb, %s::jsonb, %s, 1, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                        teacher_id = EXCLUDED.teacher_id,
                        course_id = EXCLUDED.course_id,
                        difficulty = EXCLUDED.difficulty,
                        text = EXCLUDED.text,
                        options = EXCLUDED.options,
                        correct_answer = EXCLUDED.correct_answer,
                        explanation = EXCLUDED.explanation,
                        tags = EXCLUDED.tags,
                        media_url = EXCLUDED.media_url
                    """,
                    [
                        question_id,
                        teacher_ids[(i - 1) % count],
                        course_ids[(i - 1) % count],
                        ["easy", "medium", "hard"][i % 3],
                        f"سوال نمونه {i:02d}: پاسخ درست کدام گزینه است؟",
                        options_json,
                        answer_json,
                        "این سوال برای بررسی بانک سوال ساخته شده است.",
                        "نمونه,آزمون",
                        QUESTION_IMAGES[(i - 1) % len(QUESTION_IMAGES)],
                    ],
                )

            question_set_ids = []
            for i in range(1, count + 1):
                set_id = sid(f"question-set:{i}")
                question_set_ids.append(set_id)
                self.execute_sql(
                    cursor,
                    """
                    INSERT INTO question_sets (id, title, description, course_id, created_by, target_teacher_id, status, status_note)
                    VALUES (%s, %s, %s, %s, %s, %s, 'shared', 'نمونه منتشر شده')
                    ON CONFLICT (id) DO UPDATE SET
                        title = EXCLUDED.title,
                        description = EXCLUDED.description,
                        course_id = EXCLUDED.course_id,
                        created_by = EXCLUDED.created_by,
                        target_teacher_id = EXCLUDED.target_teacher_id,
                        status = 'shared'
                    """,
                    [set_id, f"مجموعه سوال نمونه {i:02d}", "مجموعه نمونه برای بررسی صفحه مجموعه سوال", course_ids[(i - 1) % count], admin_id, teacher_ids[(i - 1) % count]],
                )
                self.execute_sql(
                    cursor,
                    """
                    INSERT INTO question_set_items (id, set_id, question_id, order_index, points)
                    VALUES (%s, %s, %s, %s, 1)
                    ON CONFLICT (id) DO UPDATE SET question_id = EXCLUDED.question_id, order_index = EXCLUDED.order_index
                    """,
                    [sid(f"question-set-item:{i}"), set_id, question_ids[(i - 1) % count], i],
                )

            exam_ids = []
            for i in range(1, count + 1):
                exam_id = sid(f"exam:{i}")
                exam_ids.append(exam_id)
                start_at = now + timedelta(days=i)
                end_at = start_at + timedelta(minutes=90)
                self.execute_sql(
                    cursor,
                    """
                    INSERT INTO exams (
                        id, teacher_id, course_id, title, description, duration_minutes, start_at, end_at,
                        shuffle_questions, shuffle_options, negative_marking, negative_factor, max_attempts,
                        is_published, show_results_immediately, passing_score, allow_partial, is_cancelled,
                        approval_status, approved_by, approved_at, exam_type, academic_year, semester,
                        lifecycle_status, result_release_mode, review_answers_enabled, show_instructions_before_start,
                        autosave_enabled, fullscreen_required, track_tab_exit, show_correct_answers, show_score,
                        show_feedback, publish_mode
                    )
                    VALUES (%s, %s, %s, %s, %s, 90, %s, %s, true, true, false, 0, 1, true, true,
                            10, true, false, 'approved', %s, CURRENT_TIMESTAMP, 'final', '1405-1406',
                            %s, 'published', 'immediate', true, true, true, false, true, true, true, true, 'automatic')
                    ON CONFLICT (id) DO UPDATE SET
                        teacher_id = EXCLUDED.teacher_id,
                        course_id = EXCLUDED.course_id,
                        title = EXCLUDED.title,
                        description = EXCLUDED.description,
                        start_at = EXCLUDED.start_at,
                        end_at = EXCLUDED.end_at,
                        is_published = true,
                        approval_status = 'approved',
                        lifecycle_status = 'published'
                    """,
                    [
                        exam_id,
                        teacher_ids[(i - 1) % count],
                        course_ids[(i - 1) % count],
                        f"آزمون نمونه {i:02d}",
                        "آزمون نمونه برای بررسی تقویم، لیست آزمون‌ها و گزارش‌ها",
                        start_at,
                        end_at,
                        admin_id,
                        "نیمسال اول" if i % 2 else "نیمسال دوم",
                    ],
                )
                self.execute_sql(
                    cursor,
                    """
                    INSERT INTO exam_questions (id, exam_id, question_id, points, order_index)
                    VALUES (%s, %s, %s, 1, %s)
                    ON CONFLICT (id) DO UPDATE SET question_id = EXCLUDED.question_id, order_index = EXCLUDED.order_index
                    """,
                    [sid(f"exam-question:{i}"), exam_id, question_ids[(i - 1) % count], i],
                )
                self.execute_sql(
                    cursor,
                    """
                    INSERT INTO exam_assignments (id, exam_id, group_id, student_profile_id, created_at)
                    VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP)
                    ON CONFLICT (id) DO UPDATE SET
                        exam_id = EXCLUDED.exam_id,
                        group_id = EXCLUDED.group_id,
                        student_profile_id = EXCLUDED.student_profile_id
                    """,
                    [sid(f"exam-assignment:{i}"), exam_id, group_ids[(i - 1) % count], student_ids[(i - 1) % count]],
                )
                attempt_id = sid(f"exam-attempt:{i}")
                self.execute_sql(
                    cursor,
                    """
                    INSERT INTO exam_attempts (id, exam_id, student_id, started_at, submitted_at, score, max_score, is_graded, status)
                    VALUES (%s, %s, %s, %s, %s, %s, 20, true, 'submitted')
                    ON CONFLICT (id) DO UPDATE SET
                        exam_id = EXCLUDED.exam_id,
                        student_id = EXCLUDED.student_id,
                        score = EXCLUDED.score,
                        max_score = EXCLUDED.max_score,
                        is_graded = true,
                        status = 'submitted'
                    """,
                    [attempt_id, exam_id, student_ids[(i - 1) % count], start_at, start_at + timedelta(minutes=60), 12 + (i % 8)],
                )
                self.execute_sql(
                    cursor,
                    """
                    INSERT INTO attempt_answers
                        (id, attempt_id, question_id, answer, is_correct, points_awarded, needs_manual_grading)
                    VALUES (%s, %s, %s, %s::jsonb, %s, %s, false)
                    ON CONFLICT (id) DO UPDATE SET
                        answer = EXCLUDED.answer,
                        is_correct = EXCLUDED.is_correct,
                        points_awarded = EXCLUDED.points_awarded,
                        needs_manual_grading = false
                    """,
                    [
                        sid(f"attempt-answer:{i}"),
                        attempt_id,
                        question_ids[(i - 1) % count],
                        json.dumps({"selected": "گزینه ب"}, ensure_ascii=False),
                        i % 3 != 0,
                        1 if i % 3 != 0 else 0,
                    ],
                )
                self.execute_sql(
                    cursor,
                    """
                    INSERT INTO objections
                        (id, student_id, exam_id, attempt_id, question_id, subject, message, status, teacher_response, resolved_by, resolved_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                    ON CONFLICT (id) DO UPDATE SET
                        subject = EXCLUDED.subject,
                        message = EXCLUDED.message,
                        status = EXCLUDED.status,
                        teacher_response = EXCLUDED.teacher_response
                    """,
                    [
                        sid(f"objection:{i}"),
                        student_ids[(i - 1) % count],
                        exam_id,
                        attempt_id,
                        question_ids[(i - 1) % count],
                        f"اعتراض نمونه {i:02d}",
                        "درخواست بررسی دوباره پاسخ ثبت شده.",
                        "resolved_accepted" if i % 2 else "open",
                        "بررسی شد و نتیجه ثبت گردید." if i % 2 else "",
                        teacher_ids[(i - 1) % count],
                    ],
                )
                self.execute_sql(
                    cursor,
                    """
                    INSERT INTO notifications (id, user_id, type, title, message, link, is_read)
                    VALUES (%s, %s, 'system', %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                        title = EXCLUDED.title,
                        message = EXCLUDED.message,
                        link = EXCLUDED.link,
                        is_read = EXCLUDED.is_read
                    """,
                    [
                        sid(f"notification:{i}"),
                        student_ids[(i - 1) % count],
                        f"اعلان نمونه {i:02d}",
                        "برای بررسی بخش اعلان‌ها ایجاد شده است.",
                        "/dashboard/",
                        i % 2 == 0,
                    ],
                )

        self.stdout.write(self.style.SUCCESS(f"Seeded {count} demo records for each main section."))
        self.stdout.write("Demo login pattern: demo10_student_01 / Demo@12345")
