from django.db import migrations


ROLES = [
    {
        'code': 'super_admin',
        'name': 'مدیر کل سیستم',
        'description': 'بالاترین سطح دسترسی و مسئول مدیریت کل سامانه.',
        'access_level': 100,
        'permissions': [
            'manage_users',
            'manage_roles',
            'manage_institutions',
            'view_all_exams',
            'system_settings',
            'view_reports',
            'view_logs',
            'backup_restore',
            'handle_violations',
            'handle_objections',
        ],
        'duties': [
            'مدیریت کاربران',
            'تعریف نقش‌ها و مجوزها',
            'مدیریت دانشگاه، مدرسه یا مؤسسه',
            'مشاهده همه آزمون‌ها',
            'تنظیمات عمومی سیستم',
            'مشاهده گزارش‌ها و لاگ‌ها',
            'پشتیبان‌گیری و بازیابی اطلاعات',
            'رسیدگی به تخلفات و اعتراض‌ها',
        ],
    },
    {
        'code': 'institution_admin',
        'name': 'مدیر مؤسسه، دانشگاه یا مدرسه',
        'description': 'مدیر مستقل یک مرکز آموزشی.',
        'access_level': 80,
        'permissions': [
            'manage_institution_teachers',
            'manage_institution_students',
            'manage_departments',
            'view_institution_exams',
            'view_performance_reports',
            'approve_users',
            'assign_exam_managers',
        ],
        'duties': [
            'مدیریت استادان و دانشجویان مرکز',
            'تعریف دانشکده، رشته، پایه یا گروه آموزشی',
            'مشاهده آزمون‌های مؤسسه',
            'مشاهده گزارش عملکرد',
            'تأیید یا غیرفعال‌کردن کاربران',
            'تعیین مدیر گروه یا مسئول آزمون',
        ],
    },
    {
        'code': 'exam_manager',
        'name': 'مدیر آموزش یا مسئول امتحانات',
        'description': 'مسئول برنامه‌ریزی و نظارت اجرایی آزمون‌ها.',
        'access_level': 70,
        'permissions': [
            'manage_exam_calendar',
            'assign_courses',
            'assign_students',
            'schedule_exams',
            'coordinate_proctors',
            'view_attendance',
            'view_exam_status',
            'prepare_official_reports',
            'manage_cancelled_or_extended_exams',
        ],
        'duties': [
            'تنظیم تقویم امتحانات',
            'اختصاص درس، استاد و دانشجویان',
            'تعیین زمان و محل مجازی آزمون',
            'هماهنگی ناظران',
            'مشاهده حضور و غیاب',
            'بررسی وضعیت برگزاری',
            'تهیه گزارش رسمی آزمون‌ها',
            'مدیریت آزمون‌های لغوشده یا تمدیدشده',
        ],
    },
    {
        'code': 'teacher',
        'name': 'استاد یا طراح سؤال',
        'description': 'طراح و مدیر آزمون و بانک سؤال.',
        'access_level': 60,
        'permissions': [
            'manage_question_bank',
            'design_exam',
            'define_questions',
            'set_scores',
            'set_negative_marking',
            'set_exam_duration',
            'grade_descriptive_answers',
            'view_student_results',
            'publish_grades',
            'answer_objections',
            'analyze_question_quality',
        ],
        'duties': [
            'ایجاد بانک سؤال',
            'طراحی آزمون',
            'تعریف سؤالات تستی، تشریحی، صحیح و غلط، جای‌خالی و تطبیقی',
            'تعیین بارم و نمره منفی',
            'تعیین مدت آزمون',
            'تصحیح پاسخ‌های تشریحی',
            'مشاهده نتایج دانشجویان',
            'انتشار نمره',
            'پاسخ به اعتراض‌ها',
            'تحلیل کیفیت سؤالات',
        ],
    },
    {
        'code': 'teaching_assistant',
        'name': 'کمک‌استاد یا دستیار آموزشی',
        'description': 'دستیار آموزشی با دسترسی محدود و وابسته به استاد مسئول.',
        'access_level': 40,
        'permissions': [
            'enter_questions',
            'initial_review_answers',
            'assist_grading',
            'view_limited_reports',
            'answer_students',
            'manage_course_content_with_permission',
        ],
        'duties': [
            'ورود سؤال به بانک سؤال',
            'بررسی اولیه پاسخ‌ها',
            'کمک در تصحیح آزمون',
            'مشاهده گزارش‌های محدود',
            'پاسخ‌گویی به دانشجویان',
            'مدیریت محتوای یک درس با اجازه استاد',
        ],
    },
    {
        'code': 'student',
        'name': 'دانشجو یا داوطلب',
        'description': 'کاربر اصلی سامانه که در آزمون شرکت می‌کند.',
        'access_level': 10,
        'permissions': [
            'view_assigned_exams',
            'participate_in_exam',
            'submit_answers',
            'upload_descriptive_files',
            'view_own_results',
            'submit_objection',
            'view_own_attendance',
        ],
        'duties': [
            'مشاهده آزمون‌های تخصیص‌یافته',
            'شرکت در آزمون',
            'ثبت پاسخ‌ها',
            'ارسال فایل در آزمون تشریحی',
            'مشاهده نمره و وضعیت قبولی',
            'ثبت اعتراض',
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
        ('core', '0002_systemrole_useractivitylog_userloginrecord_and_more'),
    ]

    operations = [
        migrations.RunPython(seed_roles, remove_roles),
    ]
