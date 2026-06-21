from django.db import migrations


ROLES = [
    {
        'code': 'exam_proctor',
        'name': 'ناظر آزمون',
        'description': 'مسئول نظارت بر جلسه آزمون، احراز هویت داوطلبان و ثبت تخلف‌ها.',
        'access_level': 50,
        'permissions': [
            'view_assigned_exam_sessions',
            'verify_candidate_identity',
            'monitor_exam_session',
            'report_violations',
            'pause_exam_when_allowed',
            'view_attendance',
        ],
        'duties': [
            'مشاهده آزمون‌های تخصیص‌یافته',
            'احراز هویت داوطلبان',
            'نظارت آنلاین یا حضوری بر جلسه آزمون',
            'ثبت تخلف و رخدادهای جلسه',
            'هماهنگی با پشتیبانی فنی در زمان بروز مشکل',
        ],
    },
    {
        'code': 'tech_support',
        'name': 'پشتیبان فنی',
        'description': 'مسئول پشتیبانی فنی سامانه، بررسی خطاها، نشست‌ها و مشکلات کاربران.',
        'access_level': 45,
        'permissions': [
            'view_technical_logs',
            'resolve_support_tickets',
            'reset_exam_sessions_when_allowed',
            'manage_user_devices',
            'support_live_exams',
        ],
        'duties': [
            'رسیدگی به درخواست‌های پشتیبانی',
            'بررسی لاگ‌ها و خطاهای فنی',
            'کمک به کاربران در ورود و شرکت در آزمون',
            'پشتیبانی آزمون‌های زنده',
            'مدیریت دستگاه‌ها و نشست‌ها در چارچوب مجوزها',
        ],
    },
]


def seed_roles(apps, schema_editor):
    SystemRole = apps.get_model('core', 'SystemRole')
    for role in ROLES:
        SystemRole.objects.update_or_create(
            code=role['code'],
            defaults={
                'name': role['name'],
                'description': role['description'],
                'access_level': role['access_level'],
                'permissions': role['permissions'],
                'duties': role['duties'],
                'is_active': True,
            },
        )


def remove_roles(apps, schema_editor):
    SystemRole = apps.get_model('core', 'SystemRole')
    SystemRole.objects.filter(code__in=[role['code'] for role in ROLES]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0004_academicinstitution_exam_allow_file_upload_and_more'),
    ]

    operations = [
        migrations.RunPython(seed_roles, remove_roles),
    ]
