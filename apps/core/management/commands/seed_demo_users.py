from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from apps.core.models import (
    AcademicInstitution,
    StudentProfile,
    SystemAdminProfile,
    SystemRole,
    TeacherProfile,
    UserProfile,
)


DEMO_USERS = [
    {
        'username': 'system_admin',
        'password': 'Admin@12345',
        'full_name': 'مدیر سیستم',
        'email': 'system.admin@demo.ir',
        'role': SystemRole.RoleCode.SUPER_ADMIN,
        'position': 'مدیر کل سامانه',
        'is_staff': True,
        'is_superuser': True,
    },
    {
        'username': 'education_manager',
        'password': 'Edu@12345',
        'full_name': 'مدیر آموزشی',
        'email': 'education.manager@demo.ir',
        'role': SystemRole.RoleCode.EXAM_MANAGER,
        'position': 'مدیر آموزشی و مسئول امتحانات',
        'personnel_number': 'EDU-1001',
    },
    {
        'username': 'teacher_demo',
        'password': 'Teacher@12345',
        'full_name': 'استاد نمونه',
        'email': 'teacher@demo.ir',
        'role': SystemRole.RoleCode.TEACHER,
        'position': 'استاد',
        'personnel_number': 'TCH-1001',
    },
    {
        'username': 'student_demo',
        'password': 'Student@12345',
        'full_name': 'دانش‌آموز نمونه',
        'email': 'student@demo.ir',
        'role': SystemRole.RoleCode.STUDENT,
        'position': 'دانش‌آموز',
        'student_number': 'STU-1001',
    },
]


class Command(BaseCommand):
    help = 'Create or refresh demo users for quick login.'

    def handle(self, *args, **options):
        User = get_user_model()
        institution, _ = AcademicInstitution.objects.get_or_create(
            name='مدرسه / دانشگاه نمونه متا کوییز',
            defaults={
                'institution_type': AcademicInstitution.InstitutionType.SCHOOL,
                'registration_code': 'DEMO-AY',
                'email': 'info@demo.ir',
                'status': AcademicInstitution.InstitutionStatus.ACTIVE,
            },
        )

        role_labels = dict(SystemRole.RoleCode.choices)
        for index, item in enumerate(DEMO_USERS, start=1):
            role, _ = SystemRole.objects.get_or_create(
                code=item['role'],
                defaults={
                    'name': role_labels.get(item['role'], item['role']),
                    'access_level': max(1, 100 - index),
                    'is_active': True,
                },
            )
            if role.name != role_labels.get(item['role'], role.name):
                role.name = role_labels.get(item['role'], role.name)
                role.save(update_fields=['name'])

            user, _ = User.objects.get_or_create(
                username=item['username'],
                defaults={
                    'email': item['email'],
                    'first_name': item['full_name'],
                    'is_active': True,
                    'is_staff': item.get('is_staff', False),
                    'is_superuser': item.get('is_superuser', False),
                },
            )
            user.email = item['email']
            user.first_name = item['full_name']
            user.is_active = True
            user.is_staff = item.get('is_staff', False)
            user.is_superuser = item.get('is_superuser', False)
            user.set_password(item['password'])
            user.save()

            profile, _ = UserProfile.objects.update_or_create(
                user=user,
                defaults={
                    'role': role,
                    'full_name': item['full_name'],
                    'organizational_email': item['email'],
                    'personnel_number': item.get('personnel_number', ''),
                    'student_number': item.get('student_number', ''),
                    'institution_name': institution.name,
                    'organizational_position': item['position'],
                    'account_status': UserProfile.AccountStatus.ACTIVE,
                    'account_verified': True,
                },
            )

            if item['role'] == SystemRole.RoleCode.SUPER_ADMIN:
                SystemAdminProfile.objects.get_or_create(
                    profile=profile,
                    defaults={'admin_code': 'ADM-1001', 'access_scope': 'دسترسی کامل به سامانه'},
                )
            elif item['role'] == SystemRole.RoleCode.TEACHER:
                TeacherProfile.objects.get_or_create(
                    profile=profile,
                    defaults={
                        'institution': institution,
                        'personnel_code': item['personnel_number'],
                        'academic_rank': 'استاد',
                        'specialization': 'آموزش آنلاین',
                    },
                )
            elif item['role'] == SystemRole.RoleCode.STUDENT:
                StudentProfile.objects.get_or_create(
                    profile=profile,
                    defaults={
                        'institution': institution,
                        'student_number': item['student_number'],
                        'field_of_study': 'آموزش عمومی',
                        'education_level': 'دانش‌آموز',
                    },
                )

            self.stdout.write(self.style.SUCCESS(f"{item['username']} / {item['password']}"))
