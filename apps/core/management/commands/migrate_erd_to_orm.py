"""
مهاجرت داده از لایه‌ی خام ERD (profiles, org_units, exams, ...) به مدل‌های
ORM جنگو (apps.core.models) — فاز ۴ نقشه‌راه مهاجرت.

این دستور فقط از جدول‌های خام می‌خواند و در مدل‌های ORM می‌نویسد؛ جدول‌های
خام هرگز تغییر یا حذف نمی‌شوند (طبق قانون سخت‌گیرانه‌ی نقشه‌راه). اجرای
مکرر بی‌خطر است (idempotent): رکوردهایی که قبلاً مهاجرت شده‌اند دوباره
به‌روزرسانی می‌شوند نه تکرار.

استفاده:
    python manage.py migrate_erd_to_orm --dry-run   # فقط گزارش، هیچ نوشتنی در دیتابیس
    python manage.py migrate_erd_to_orm              # اجرای واقعی

طبق قانون سخت‌گیرانه‌ی دستورکار، اجرای واقعی (بدون --dry-run) باید فقط پس
از بررسی گزارش --dry-run و تأیید صریح کارفرما انجام شود.
"""

import json
from collections import defaultdict
from datetime import datetime

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import connection, transaction
from django.utils import timezone

from apps.core.models import (
    AcademicInstitution,
    AcademicTerm,
    AcademicUnit,
    Course,
    CourseClass,
    Exam,
    ExamManagerProfile,
    ExamQuestion,
    Question,
    StudentExamAttempt,
    StudentProfile,
    StudentQuestionAnswer,
    SystemRole,
    TeacherProfile,
    UserProfile,
    UserRoleAssignment,
)

User = get_user_model()


class DryRunRollback(Exception):
    """برای برگرداندن تراکنش در حالت --dry-run، بدون اینکه خطای واقعی باشد."""


QUESTION_TYPE_MAP = {
    'single': Question.QuestionType.MULTIPLE_CHOICE,
    'multi': Question.QuestionType.MULTI_SELECT,
    'true_false': Question.QuestionType.TRUE_FALSE,
    'short_answer': Question.QuestionType.SHORT_ANSWER,
    'essay': Question.QuestionType.DESCRIPTIVE,
    'fill_blank': Question.QuestionType.FILL_BLANK,
    'matching': Question.QuestionType.MATCHING,
    'ordering': Question.QuestionType.ORDERING,
}

UNIT_TYPE_MAP = {
    'faculty': AcademicUnit.UnitType.FACULTY,
    'department': AcademicUnit.UnitType.DEPARTMENT,
    'group': AcademicUnit.UnitType.CLASS_GROUP,
}

STUDENT_STATUS_MAP = {
    'active': StudentProfile.EnrollmentStatus.ACTIVE,
    'graduated': StudentProfile.EnrollmentStatus.GRADUATED,
    'leave': StudentProfile.EnrollmentStatus.SUSPENDED,
    'inactive': StudentProfile.EnrollmentStatus.WITHDRAWN,
}

ATTEMPT_STATUS_MAP = {
    'in_progress': StudentExamAttempt.Status.IN_PROGRESS,
    'submitted': StudentExamAttempt.Status.SUBMITTED,
    'graded': StudentExamAttempt.Status.SUBMITTED,
    'expired': StudentExamAttempt.Status.AUTO_SUBMITTED,
}


def parse_json_column(value, fallback=None):
    """ستون‌های jsonb/JSON روی SQLite به‌صورت رشته‌ی خام برمی‌گردند (نه dict/list
    پارس‌شده)، برخلاف psycopg روی Postgres. همان الگوی _sx_json موجود در
    views.py اینجا هم به کار می‌رود تا رفتار روی هر دو دیتابیس یکسان باشد."""
    if value in (None, ''):
        return fallback
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return fallback


def parse_datetime_column(value):
    """رشته‌ی خام تاریخ/زمان از ستون timestamptz خام را به datetime آگاه از
    time zone تبدیل می‌کند — همان منطق erd_datetime در views.py، چون خواندن
    مستقیم از cursor (نه از طریق فیلد جنگو) هیچ تبدیل خودکاری انجام نمی‌دهد."""
    if not value or hasattr(value, 'date'):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace('Z', '+00:00').replace(' ', 'T', 1) if 'T' not in text else text.replace('Z', '+00:00'))
    except ValueError:
        return None
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed


def parse_date_column(value):
    parsed = parse_datetime_column(value)
    return parsed.date() if parsed else None


def fetch_rows(sql, params=()):
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        columns = [col[0] for col in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]


class Report:
    """جمع‌آوری شمارش‌ها و موارد نیازمند بررسی دستی برای گزارش پایانی."""

    def __init__(self):
        self.created = defaultdict(int)
        self.updated = defaultdict(int)
        self.manual_review = defaultdict(list)
        self.skipped_orphan = defaultdict(list)

    def note_created(self, entity):
        self.created[entity] += 1

    def note_updated(self, entity):
        self.updated[entity] += 1

    def note_manual_review(self, entity, erd_id, reason):
        self.manual_review[entity].append((erd_id, reason))

    def note_orphan(self, entity, erd_id, reason):
        self.skipped_orphan[entity].append((erd_id, reason))

    def print_summary(self, stdout, style):
        stdout.write('')
        stdout.write(style.MIGRATE_HEADING('=== خلاصه‌ی مهاجرت ==='))
        entities = sorted(set(self.created) | set(self.updated))
        for entity in entities:
            stdout.write(f'{entity}: {self.created[entity]} ایجاد شد، {self.updated[entity]} به‌روزرسانی شد')

        total_manual = sum(len(v) for v in self.manual_review.values())
        if total_manual:
            stdout.write('')
            stdout.write(style.WARNING(f'=== نیاز به بررسی دستی ({total_manual} مورد) — مهاجرت نشدند ==='))
            for entity, items in self.manual_review.items():
                for erd_id, reason in items:
                    stdout.write(f'  [{entity}] id={erd_id}: {reason}')

        total_orphan = sum(len(v) for v in self.skipped_orphan.values())
        if total_orphan:
            stdout.write('')
            stdout.write(style.WARNING(f'=== رکورد یتیم / وابستگی گم‌شده ({total_orphan} مورد) — رد شدند ==='))
            for entity, items in self.skipped_orphan.items():
                for erd_id, reason in items:
                    stdout.write(f'  [{entity}] id={erd_id}: {reason}')


class Command(BaseCommand):
    help = 'مهاجرت داده از جدول‌های خام ERD به مدل‌های ORM (فاز ۴ نقشه‌راه مهاجرت). idempotent است.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='فقط گزارش بده — هیچ چیزی در دیتابیس نوشته نمی‌شود.',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        report = Report()

        try:
            with transaction.atomic():
                user_by_profile, userprofile_by_profile = self.migrate_profiles_and_roles(report)
                inst_by_unit, unit_by_unit = self.migrate_org_units(report)
                self.migrate_teacher_profiles(report, user_by_profile, userprofile_by_profile, inst_by_unit, unit_by_unit)
                student_profile_by_erd_user = self.migrate_student_profiles(report, user_by_profile, userprofile_by_profile, inst_by_unit, unit_by_unit)
                self.migrate_exam_manager_profiles(report, userprofile_by_profile, inst_by_unit, unit_by_unit)
                term_by_erd = self.migrate_academic_terms(report, inst_by_unit)
                course_by_erd = self.migrate_courses(report, inst_by_unit, unit_by_unit)
                teacher_by_erd_user = self.build_teacher_lookup()
                group_by_erd = self.migrate_student_groups(report, course_by_erd, teacher_by_erd_user, student_profile_by_erd_user)
                question_by_erd = self.migrate_questions(report, teacher_by_erd_user, course_by_erd)
                exam_by_erd = self.migrate_exams(report, course_by_erd, teacher_by_erd_user)
                exam_question_by_erd = self.migrate_exam_questions(report, exam_by_erd, question_by_erd)
                self.migrate_exam_attempts(report, exam_by_erd, student_profile_by_erd_user, exam_question_by_erd)

                if dry_run:
                    raise DryRunRollback()
        except DryRunRollback:
            pass

        report.print_summary(self.stdout, self.style)
        if dry_run:
            self.stdout.write('')
            self.stdout.write(self.style.NOTICE('این یک dry-run بود؛ هیچ داده‌ای در دیتابیس نوشته نشد (تراکنش rollback شد).'))
        else:
            self.stdout.write('')
            self.stdout.write(self.style.SUCCESS('مهاجرت واقعی انجام شد.'))

    # ------------------------------------------------------------------
    # کاربران و نقش‌ها
    # ------------------------------------------------------------------
    def match_django_user(self, erd_profile):
        username = erd_profile.get('username')
        email = erd_profile.get('email')
        candidates = User.objects.none()
        if username:
            candidates = User.objects.filter(username=username)
        if not candidates.exists() and email:
            candidates = User.objects.filter(email=email)
        count = candidates.count()
        if count == 1:
            return candidates.first(), None
        if count == 0:
            return None, 'هیچ کاربر جنگویی با این username/email پیدا نشد'
        return None, f'تطبیق مبهم — {count} کاربر جنگو با این username/email پیدا شد'

    def migrate_profiles_and_roles(self, report):
        """profiles + user_roles -> User(match-only) + UserProfile + UserRoleAssignment.

        طبق قانون سخت‌گیرانه‌ی دستورکار: username/email فقط برای *پیدا کردن*
        کاندید استفاده می‌شود؛ در صورت نبود یا ابهام تطبیق، آن رکورد مهاجرت
        نمی‌شود و در فهرست «نیاز به بررسی دستی» قرار می‌گیرد.
        """
        role_rows = fetch_rows('SELECT id, user_id, role, created_at FROM user_roles ORDER BY user_id, created_at')
        roles_by_profile = defaultdict(list)
        for row in role_rows:
            roles_by_profile[row['user_id']].append(row['role'])

        role_priority = ('admin', 'academic_manager', 'teacher', 'student')
        # نگاشت نقش خام -> کد نقش ORM. 'academic_manager' ذاتاً مبهم است
        # (هم می‌تواند institution_admin باشد هم exam_manager — این تمایز در
        # لایه‌ی ERD اصلاً ذخیره نشده). پیش‌فرض این مهاجرت exam_manager است
        # چون مدل هدف همین ExamManagerProfile چند-واحدی است؛ اما هر مورد در
        # گزارش «نیاز به بررسی دستی» هم علامت می‌خورد تا صریحاً تأیید/اصلاح شود.
        erd_role_to_orm_code = {
            'admin': SystemRole.RoleCode.SUPER_ADMIN,
            'academic_manager': SystemRole.RoleCode.EXAM_MANAGER,
            'teacher': SystemRole.RoleCode.TEACHER,
            'student': SystemRole.RoleCode.STUDENT,
        }
        role_objects = {code: SystemRole.objects.filter(code=code).first() for code in erd_role_to_orm_code.values()}

        user_by_profile = {}
        userprofile_by_profile = {}

        for erd_profile in fetch_rows('SELECT * FROM profiles'):
            erd_id = erd_profile['id']
            user, match_reason = self.match_django_user(erd_profile)
            if user is None:
                report.note_manual_review('profiles', erd_id, match_reason)
                continue
            user_by_profile[erd_id] = user

            roles = roles_by_profile.get(erd_id, [])
            primary_role = next((r for r in role_priority if r in roles), None)
            if primary_role is None:
                report.note_manual_review('profiles', erd_id, 'هیچ نقشی در user_roles برای این پروفایل ثبت نشده')
                continue
            primary_role_obj = role_objects.get(erd_role_to_orm_code[primary_role])
            if primary_role_obj is None:
                report.note_manual_review('profiles', erd_id, f'نقش ORM معادل «{primary_role}» در SystemRole پیدا نشد')
                continue

            defaults = {
                'full_name': erd_profile.get('full_name') or user.get_full_name() or user.username,
                'role': primary_role_obj,
                'mobile': erd_profile.get('phone') or '',
                'organizational_email': erd_profile.get('email') or '',
                'national_code': erd_profile.get('national_id') or '',
                'account_status': erd_profile.get('status') or UserProfile.AccountStatus.ACTIVE,
            }
            profile_obj, created = UserProfile.objects.update_or_create(user=user, defaults=defaults)
            userprofile_by_profile[erd_id] = profile_obj
            report.note_created('UserProfile') if created else report.note_updated('UserProfile')

            for role_code_raw in set(roles):
                orm_code = erd_role_to_orm_code.get(role_code_raw)
                role_obj = role_objects.get(orm_code) if orm_code else None
                if role_obj is None:
                    report.note_manual_review('user_roles', f'{erd_id}:{role_code_raw}', 'نقش ORM معادل پیدا نشد')
                    continue
                _, assignment_created = UserRoleAssignment.objects.update_or_create(
                    profile=profile_obj,
                    role=role_obj,
                    defaults={'is_primary': role_code_raw == primary_role},
                )
                report.note_created('UserRoleAssignment') if assignment_created else report.note_updated('UserRoleAssignment')
                if role_code_raw == 'academic_manager':
                    report.note_manual_review(
                        'user_roles',
                        f'{erd_id}:academic_manager',
                        'نقش «academic_manager» در ERD مبهم است (می‌تواند institution_admin یا exam_manager باشد)؛ '
                        'به‌صورت پیش‌فرض exam_manager در نظر گرفته شد — لطفاً تأیید یا اصلاح کنید.',
                    )

        return user_by_profile, userprofile_by_profile

    # ------------------------------------------------------------------
    # ساختار سازمانی
    # ------------------------------------------------------------------
    def migrate_org_units(self, report):
        """org_units -> AcademicInstitution (ریشه‌ها) + AcademicUnit (باقی).

        بازگشت: دو دیکشنری erd_unit_id -> شیء ORM: یکی برای واحدهایی که به
        AcademicInstitution تبدیل شدند (ریشه‌ها)، دیگری برای AcademicUnit.
        """
        units = fetch_rows('SELECT * FROM org_units')
        by_id = {u['id']: u for u in units}

        inst_by_unit = {}
        unit_by_unit = {}

        roots = [u for u in units if not u.get('parent_id')]
        for root in roots:
            defaults = {
                'name': root['name'],
                'status': AcademicInstitution.InstitutionStatus.ACTIVE if root.get('is_active') else AcademicInstitution.InstitutionStatus.INACTIVE,
            }
            obj, created = AcademicInstitution.objects.update_or_create(legacy_erd_id=root['id'], defaults=defaults)
            inst_by_unit[root['id']] = obj
            report.note_created('AcademicInstitution') if created else report.note_updated('AcademicInstitution')

        remaining = [u for u in units if u.get('parent_id')]
        changed = True
        while remaining and changed:
            changed = False
            still_remaining = []
            for unit in remaining:
                parent_id = unit['parent_id']
                if parent_id in inst_by_unit:
                    institution = inst_by_unit[parent_id]
                    parent_unit = None
                elif parent_id in unit_by_unit:
                    parent_unit = unit_by_unit[parent_id]
                    institution = parent_unit.institution
                else:
                    still_remaining.append(unit)
                    continue
                unit_type = UNIT_TYPE_MAP.get(unit.get('type'), AcademicUnit.UnitType.DEPARTMENT)
                # code در org_units اختیاری است؛ چند واحد می‌توانند code خالی
                # داشته باشند که با unique_together('institution','code') در
                # ORM تصادم می‌کند — برای واحدهای بدون کد، از id خام یک کد
                # یکتای پایدار می‌سازیم.
                code = (unit.get('code') or f"unit-{unit['id'][:8]}")[:40]
                defaults = {
                    'institution': institution,
                    'parent': parent_unit,
                    'name': unit['name'],
                    'code': code,
                    'unit_type': unit_type,
                    'is_active': bool(unit.get('is_active', True)),
                }
                obj, created = AcademicUnit.objects.update_or_create(legacy_erd_id=unit['id'], defaults=defaults)
                unit_by_unit[unit['id']] = obj
                report.note_created('AcademicUnit') if created else report.note_updated('AcademicUnit')
                changed = True
            remaining = still_remaining

        for unit in remaining:
            report.note_orphan('org_units', unit['id'], 'زنجیره‌ی parent_id به هیچ ریشه‌ای نمی‌رسد (احتمال حلقه یا parent گم‌شده)')

        return inst_by_unit, unit_by_unit

    def resolve_org_unit(self, org_unit_id, inst_by_unit, unit_by_unit):
        """org_unit_id خام -> (institution, academic_unit_or_None)."""
        if not org_unit_id:
            return None, None
        if org_unit_id in inst_by_unit:
            return inst_by_unit[org_unit_id], None
        if org_unit_id in unit_by_unit:
            unit = unit_by_unit[org_unit_id]
            return unit.institution, unit
        return None, None

    # ------------------------------------------------------------------
    # پروفایل‌های نقش
    # ------------------------------------------------------------------
    def migrate_teacher_profiles(self, report, user_by_profile, userprofile_by_profile, inst_by_unit, unit_by_unit):
        for row in fetch_rows('SELECT * FROM teacher_profiles'):
            erd_user_id = row['user_id']
            profile_obj = userprofile_by_profile.get(erd_user_id)
            if profile_obj is None:
                report.note_orphan('teacher_profiles', erd_user_id, 'پروفایل کاربری متناظر مهاجرت نشده (به بخش profiles نگاه کنید)')
                continue
            institution, unit = self.resolve_org_unit(row.get('org_unit_id'), inst_by_unit, unit_by_unit)
            if institution is None:
                report.note_manual_review('teacher_profiles', erd_user_id, 'واحد سازمانی/مؤسسه قابل تشخیص نیست')
                continue
            defaults = {
                'institution': institution,
                'academic_unit': unit,
                'personnel_code': row.get('personnel_code') or '',
                'specialization': row.get('specialty') or '',
            }
            _, created = TeacherProfile.objects.update_or_create(profile=profile_obj, defaults=defaults)
            report.note_created('TeacherProfile') if created else report.note_updated('TeacherProfile')

    def migrate_student_profiles(self, report, user_by_profile, userprofile_by_profile, inst_by_unit, unit_by_unit):
        student_profile_by_erd_user = {}
        for row in fetch_rows('SELECT * FROM student_profiles'):
            erd_user_id = row['user_id']
            profile_obj = userprofile_by_profile.get(erd_user_id)
            if profile_obj is None:
                report.note_orphan('student_profiles', erd_user_id, 'پروفایل کاربری متناظر مهاجرت نشده (به بخش profiles نگاه کنید)')
                continue
            institution, unit = self.resolve_org_unit(row.get('org_unit_id'), inst_by_unit, unit_by_unit)
            if institution is None:
                report.note_manual_review('student_profiles', erd_user_id, 'واحد سازمانی/مؤسسه قابل تشخیص نیست')
                continue
            defaults = {
                'institution': institution,
                'academic_unit': unit,
                'student_number': row.get('student_number') or '',
                'field_of_study': row.get('field_of_study') or '',
                'education_level': row.get('degree') or '',
                'semester': row.get('semester') or '',
                'class_group': row.get('class_group') or '',
                'enrollment_status': STUDENT_STATUS_MAP.get(row.get('academic_status'), StudentProfile.EnrollmentStatus.ACTIVE),
            }
            obj, created = StudentProfile.objects.update_or_create(profile=profile_obj, defaults=defaults)
            student_profile_by_erd_user[erd_user_id] = obj
            report.note_created('StudentProfile') if created else report.note_updated('StudentProfile')
        return student_profile_by_erd_user

    def migrate_exam_manager_profiles(self, report, userprofile_by_profile, inst_by_unit, unit_by_unit):
        scopes_by_manager = defaultdict(list)
        for row in fetch_rows('SELECT * FROM academic_manager_scopes'):
            scopes_by_manager[row['manager_id']].append(row['org_unit_id'])

        for row in fetch_rows('SELECT * FROM academic_manager_profiles'):
            erd_user_id = row['user_id']
            profile_obj = userprofile_by_profile.get(erd_user_id)
            if profile_obj is None:
                report.note_orphan('academic_manager_profiles', erd_user_id, 'پروفایل کاربری متناظر مهاجرت نشده (به بخش profiles نگاه کنید)')
                continue

            scope_unit_ids = scopes_by_manager.get(erd_user_id, [])
            managed_units = []
            institution = None
            for org_unit_id in scope_unit_ids:
                unit_institution, unit = self.resolve_org_unit(org_unit_id, inst_by_unit, unit_by_unit)
                if unit is None and unit_institution is not None:
                    report.note_manual_review(
                        'academic_manager_scopes',
                        f'{erd_user_id}:{org_unit_id}',
                        'این scope به کل یک مؤسسه (ریشه‌ی درخت) اشاره دارد، نه یک واحد سازمانی مشخص — '
                        'در طراحی فعلی ORM، managed_units فقط AcademicUnit می‌پذیرد، نه کل مؤسسه. این مورد اضافه نشد.',
                    )
                    if institution is None:
                        institution = unit_institution
                    continue
                if unit is not None:
                    managed_units.append(unit)
                    if institution is None:
                        institution = unit_institution

            if institution is None:
                report.note_manual_review(erd_user_id, erd_user_id, 'academic_manager_scopes خالی است یا هیچ واحد/مؤسسه‌ای قابل تشخیص نیست؛ ExamManagerProfile ساخته نشد')
                continue

            defaults = {
                'institution': institution,
                'employee_code': row.get('personnel_code') or '',
                'position_title': row.get('title') or '',
            }
            obj, created = ExamManagerProfile.objects.update_or_create(profile=profile_obj, defaults=defaults)
            if managed_units:
                obj.managed_units.set(managed_units)
            report.note_created('ExamManagerProfile') if created else report.note_updated('ExamManagerProfile')

    # ------------------------------------------------------------------
    # درس‌ها، ترم‌ها، گروه‌ها
    # ------------------------------------------------------------------
    def migrate_academic_terms(self, report, inst_by_unit):
        term_by_erd = {}
        institutions = list(AcademicInstitution.objects.all())
        default_institution = institutions[0] if len(institutions) == 1 else None
        for row in fetch_rows('SELECT * FROM academic_terms'):
            if default_institution is None:
                report.note_manual_review(
                    'academic_terms', row['id'],
                    'academic_terms در ERD به هیچ مؤسسه‌ای مستقیماً وصل نیست و بیش از یک مؤسسه در سیستم وجود دارد؛ '
                    'مشخص نیست این ترم به کدام مؤسسه تعلق دارد.',
                )
                continue
            title = row.get('label') or f"{row.get('year') or ''}-{row.get('semester') or ''}".strip('-') or f"term-{row['id'][:8]}"
            defaults = {
                'title': title[:120],
                'year': int(row['year']) if str(row.get('year') or '').isdigit() else None,
                'starts_at': parse_date_column(row.get('start_date')),
                'ends_at': parse_date_column(row.get('end_date')),
                'is_active': bool(row.get('is_active', True)),
            }
            obj, created = AcademicTerm.objects.update_or_create(institution=default_institution, legacy_erd_id=row['id'], defaults=defaults)
            term_by_erd[row['id']] = obj
            report.note_created('AcademicTerm') if created else report.note_updated('AcademicTerm')
        return term_by_erd

    def migrate_courses(self, report, inst_by_unit, unit_by_unit):
        course_by_erd = {}
        for row in fetch_rows('SELECT * FROM courses'):
            institution, unit = self.resolve_org_unit(row.get('org_unit_id'), inst_by_unit, unit_by_unit)
            if institution is None:
                report.note_orphan('courses', row['id'], 'واحد سازمانی/مؤسسه قابل تشخیص نیست')
                continue
            code = (row.get('code') or f"erd-{row['id'][:8]}")[:50]
            credit = row.get('credit_units') if row.get('credit_units') and 1 <= row.get('credit_units') <= 6 else None
            defaults = {
                'academic_unit': unit,
                'title': row['title'],
                'code': code,
                'credit_count': credit,
                'description': row.get('description') or '',
            }
            obj, created = Course.objects.update_or_create(institution=institution, legacy_erd_id=row['id'], defaults=defaults)
            course_by_erd[row['id']] = obj
            report.note_created('Course') if created else report.note_updated('Course')
        return course_by_erd

    def build_teacher_lookup(self):
        """erd profiles.id (=teacher_profiles.user_id) -> شیء ORM TeacherProfile."""
        lookup = {}
        for tp in TeacherProfile.objects.select_related('profile', 'profile__user').all():
            username = tp.profile.user.username
            email = tp.profile.user.email
            for row in fetch_rows('SELECT id FROM profiles WHERE username = %s OR email = %s', [username, email or '']):
                lookup[row['id']] = tp
        return lookup

    def build_student_lookup(self):
        lookup = {}
        for sp in StudentProfile.objects.select_related('profile', 'profile__user').all():
            username = sp.profile.user.username
            email = sp.profile.user.email
            for row in fetch_rows('SELECT id FROM profiles WHERE username = %s OR email = %s', [username, email or '']):
                lookup[row['id']] = sp
        return lookup

    def migrate_student_groups(self, report, course_by_erd, teacher_by_erd_user, student_profile_by_erd_user):
        group_by_erd = {}
        group_teacher_counts = defaultdict(int)
        for row in fetch_rows('SELECT group_id, COUNT(*) AS cnt FROM group_teachers GROUP BY group_id'):
            group_teacher_counts[row['group_id']] = row['cnt']

        for row in fetch_rows('SELECT * FROM student_groups'):
            course = course_by_erd.get(row.get('course_id'))
            if course is None:
                report.note_orphan('student_groups', row['id'], 'درس متناظر مهاجرت نشده')
                continue
            teacher = teacher_by_erd_user.get(row.get('teacher_id'))
            code = (row.get('group_code') or f"grp-{row['id'][:8]}")[:50]
            defaults = {
                'course': course,
                'title': row.get('course_name') or code,
                'code': code,
                'teacher': teacher,
                'capacity': row.get('capacity'),
                'is_active': bool(row.get('is_active', True)),
            }
            obj, created = CourseClass.objects.update_or_create(institution=course.institution, legacy_erd_id=row['id'], defaults=defaults)
            group_by_erd[row['id']] = obj
            report.note_created('CourseClass') if created else report.note_updated('CourseClass')

            if group_teacher_counts.get(row['id'], 0) > 1:
                report.note_manual_review(
                    'group_teachers', row['id'],
                    'این گروه در ERD بیش از یک استاد دارد؛ CourseClass.teacher فقط یک استاد را می‌پذیرد — فقط استاد اصلی گروه ثبت شد.',
                )

            member_students = []
            for member in fetch_rows('SELECT student_user_id FROM student_group_members WHERE group_id = %s', [row['id']]):
                student_obj = student_profile_by_erd_user.get(member['student_user_id'])
                if student_obj is not None:
                    member_students.append(student_obj)
                else:
                    report.note_orphan('student_group_members', member['student_user_id'], 'پروفایل دانشجویی متناظر مهاجرت نشده')
            if member_students:
                obj.students.set(member_students)

        return group_by_erd

    # ------------------------------------------------------------------
    # بانک سؤال، آزمون‌ها
    # ------------------------------------------------------------------
    def migrate_questions(self, report, teacher_by_erd_user, course_by_erd):
        question_by_erd = {}
        for row in fetch_rows('SELECT * FROM questions'):
            teacher = teacher_by_erd_user.get(row.get('teacher_id'))
            if teacher is None:
                report.note_orphan('questions', row['id'], 'استاد سازنده‌ی سؤال مهاجرت نشده — این سؤال بدون استاد ثبت نمی‌شود چون teacher در ORM اجباری است')
                continue
            course = course_by_erd.get(row.get('course_id'))
            question_type = QUESTION_TYPE_MAP.get(row.get('type'), Question.QuestionType.DESCRIPTIVE)
            options = parse_json_column(row.get('options'), [])
            correct_answer = parse_json_column(row.get('correct_answer'), row.get('correct_answer'))
            if isinstance(correct_answer, (list, dict)):
                correct_answer = json.dumps(correct_answer, ensure_ascii=False)
            defaults = {
                'course': course,
                'question_type': question_type,
                'text': row.get('text') or '',
                'options': options if isinstance(options, list) else [],
                'correct_answer': correct_answer or '',
                'suggested_score': row.get('default_points') or 1,
                'chapter': (row.get('subject') or '')[:120] if row.get('subject') else '',
            }
            obj, created = Question.objects.update_or_create(teacher=teacher, legacy_erd_id=row['id'], defaults=defaults)
            question_by_erd[row['id']] = obj
            report.note_created('Question') if created else report.note_updated('Question')
        return question_by_erd

    def resolve_exam_status(self, row):
        if row.get('is_cancelled'):
            return Exam.ExamStatus.CANCELLED
        if row.get('approval_status') == 'pending':
            return Exam.ExamStatus.PENDING_APPROVAL
        if not row.get('is_published'):
            return Exam.ExamStatus.DRAFT
        now = timezone.now()
        starts_at, ends_at = parse_datetime_column(row.get('start_at')), parse_datetime_column(row.get('end_at'))
        if starts_at and now < starts_at:
            return Exam.ExamStatus.SCHEDULED
        if ends_at and now > ends_at:
            return Exam.ExamStatus.FINISHED
        return Exam.ExamStatus.ACTIVE

    def migrate_exams(self, report, course_by_erd, teacher_by_erd_user):
        exam_by_erd = {}
        for row in fetch_rows('SELECT * FROM exams'):
            starts_at = parse_datetime_column(row.get('start_at'))
            ends_at = parse_datetime_column(row.get('end_at'))
            if not starts_at or not ends_at:
                report.note_manual_review('exams', row['id'], 'زمان شروع یا پایان آزمون خالی/نامعتبر است؛ در ORM این دو فیلد اجباری‌اند')
                continue
            course = course_by_erd.get(row.get('course_id'))
            designer = teacher_by_erd_user.get(row.get('teacher_id'))
            defaults = {
                'institution': course.institution if course else None,
                'course': course,
                'designer': designer,
                'title': row['title'],
                'description': row.get('description') or '',
                'starts_at': starts_at,
                'ends_at': ends_at,
                'duration_minutes': row.get('duration_minutes'),
                'status': self.resolve_exam_status(row),
                'passing_score': row.get('passing_score'),
                'negative_marking_enabled': bool(row.get('negative_marking')),
                'randomize_questions': bool(row.get('shuffle_questions')),
                'randomize_options': bool(row.get('shuffle_options')),
                'show_result_after_submit': bool(row.get('show_results_immediately')),
                'is_active': not bool(row.get('is_cancelled')),
            }
            obj, created = Exam.objects.update_or_create(legacy_erd_id=row['id'], defaults=defaults)
            exam_by_erd[row['id']] = obj
            report.note_created('Exam') if created else report.note_updated('Exam')
        return exam_by_erd

    def migrate_exam_questions(self, report, exam_by_erd, question_by_erd):
        exam_question_by_erd = {}
        for row in fetch_rows('SELECT * FROM exam_questions'):
            exam = exam_by_erd.get(row.get('exam_id'))
            question = question_by_erd.get(row.get('question_id'))
            if exam is None or question is None:
                report.note_orphan('exam_questions', row['id'], 'آزمون یا سؤال متناظر مهاجرت نشده')
                continue
            defaults = {'score': row.get('points') or 1, 'order': row.get('order_index') or 0}
            obj, created = ExamQuestion.objects.update_or_create(exam=exam, question=question, defaults=defaults)
            exam_question_by_erd[row['id']] = obj
            report.note_created('ExamQuestion') if created else report.note_updated('ExamQuestion')
        return exam_question_by_erd

    def migrate_exam_attempts(self, report, exam_by_erd, student_profile_by_erd_user, exam_question_by_erd):
        question_by_exam_question = {}
        for row in fetch_rows('SELECT id, exam_id, question_id FROM exam_questions'):
            question_by_exam_question[(row['exam_id'], row['question_id'])] = row['id']

        for row in fetch_rows('SELECT * FROM exam_attempts'):
            exam = exam_by_erd.get(row.get('exam_id'))
            student = student_profile_by_erd_user.get(row.get('student_id'))
            if exam is None or student is None:
                report.note_orphan('exam_attempts', row['id'], 'آزمون یا دانشجوی متناظر مهاجرت نشده')
                continue
            defaults = {
                'status': ATTEMPT_STATUS_MAP.get(row.get('status'), StudentExamAttempt.Status.NOT_STARTED),
                'started_at': parse_datetime_column(row.get('started_at')),
                'submitted_at': parse_datetime_column(row.get('submitted_at')),
            }
            attempt_obj, created = StudentExamAttempt.objects.update_or_create(exam=exam, student=student, defaults=defaults)
            report.note_created('StudentExamAttempt') if created else report.note_updated('StudentExamAttempt')

            for answer_row in fetch_rows('SELECT * FROM attempt_answers WHERE attempt_id = %s', [row['id']]):
                exam_question_erd_id = question_by_exam_question.get((row.get('exam_id'), answer_row.get('question_id')))
                exam_question_obj = exam_question_by_erd.get(exam_question_erd_id) if exam_question_erd_id else None
                if exam_question_obj is None:
                    report.note_orphan('attempt_answers', answer_row['id'], 'exam_question متناظر (آن سؤال در آن آزمون) پیدا نشد')
                    continue
                answer_value = parse_json_column(answer_row.get('answer'), answer_row.get('answer'))
                answer_defaults = {}
                if isinstance(answer_value, list):
                    answer_defaults['selected_options'] = answer_value
                elif answer_value is not None:
                    answer_defaults['answer_text'] = str(answer_value)
                _, answer_created = StudentQuestionAnswer.objects.update_or_create(
                    attempt=attempt_obj, exam_question=exam_question_obj, defaults=answer_defaults,
                )
                report.note_created('StudentQuestionAnswer') if answer_created else report.note_updated('StudentQuestionAnswer')
