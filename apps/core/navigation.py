from django.urls import NoReverseMatch, reverse
from django.db import connection


ROLE_NAV = {
    'super_admin': [
        ('اصلی', [
            ('داشبورد', 'core:dashboard', 'layout'),
            ('کاربران', 'core:super_admin_users', 'users'),
            ('نقش ها', 'core:super_admin_roles', 'shield'),
            ('گزارش ها', 'core:super_admin_reports', 'chart'),
            ('آزمون های فعال', 'core:super_admin_active_exams', 'clipboard'),
        ]),
    ],
    'institution_admin': [
        ('اصلی', [
            ('داشبورد', 'core:institution_admin_dashboard', 'layout'),
            ('تنظیمات موسسه', 'core:institution_settings', 'settings'),
            ('کاربران', 'core:institution_users', 'users'),
            ('ساختار آموزشی', 'core:institution_structure', 'database'),
            ('آزمون ها', 'core:institution_exams', 'clipboard'),
            ('تخلف ها', 'core:institution_violations', 'alert'),
        ]),
    ],
    'exam_manager': [
        ('اصلی', [
            ('داشبورد', 'core:exam_manager_dashboard', 'layout'),
            ('تقویم', 'core:exam_manager_calendar', 'clock'),
            ('تایید آزمون ها', 'core:exam_manager_approvals', 'check'),
            ('ناظران', 'core:exam_manager_proctors', 'users'),
            ('آزمون های فعال', 'core:exam_manager_active_exams', 'clipboard'),
            ('گزارش ها', 'core:exam_manager_reports', 'chart'),
        ]),
    ],
    'teacher': [
        ('اصلی', [
            ('داشبورد', 'core:teacher_panel', 'layout'),
            ('درس ها و گروه ها', 'core:teacher_courses', 'book'),
            ('بانک سوال', 'core:teacher_questions', 'question'),
            ('آزمون ها', 'core:teacher_exams', 'clipboard'),
            ('نظارت', 'core:teacher_monitoring', 'eye'),
            ('تصحیح', 'core:teacher_reviews', 'check'),
            ('نتایج', 'core:teacher_results', 'chart'),
            ('اعتراض ها', 'core:teacher_objections', 'alert'),
            ('تقویم', 'core:teacher_calendar', 'clock'),
            ('اعلان ها', 'core:teacher_announcements', 'spark'),
        ]),
        ('حساب', [
            ('پروفایل استاد', 'core:teacher_profile_page', 'users'),
            ('امنیت حساب', 'core:teacher_security', 'shield'),
        ]),
    ],
    'teaching_assistant': [
        ('اصلی', [
            ('داشبورد', 'core:assistant_panel', 'layout'),
            ('سوال ها', 'core:assistant_questions', 'question'),
            ('پیش نویس آزمون', 'core:assistant_exam_drafts', 'clipboard'),
            ('پیشنهاد اصلاح', 'core:assistant_question_suggestions', 'spark'),
            ('تصحیح پاسخ ها', 'core:assistant_reviews', 'check'),
            ('پرسش آموزشی', 'core:assistant_educational_questions', 'help'),
        ]),
    ],
    'student': [
        ('اصلی', [
            ('داشبورد', 'core:dashboard', 'layout'),
            ('آزمون ها', 'core:student_exam_schedule', 'clipboard'),
            ('آزمون آزمایشی', 'core:student_practice_exam', 'spark'),
            ('نتایج', 'core:student_results', 'chart'),
            ('اعتراض ها', 'core:student_objections', 'alert'),
            ('پرسش آموزشی', 'core:student_educational_questions', 'help'),
        ]),
    ],
}


ICON_MAP = {
    'alert': '!',
    'chart': '↗',
    'check': '✓',
    'clipboard': '□',
    'clock': '◷',
    'database': '▦',
    'eye': '◉',
    'help': '?',
    'layout': '▣',
    'question': '؟',
    'settings': '⚙',
    'shield': '◇',
    'spark': '✦',
    'users': '●',
}


def _safe_reverse(name):
    try:
        return reverse(name)
    except NoReverseMatch:
        return '#'


def _admin_sidebar_groups():
    return [
        ('اصلی', [
            ('داشبورد', _safe_reverse('core:dashboard'), 'dashboard'),
            ('درس‌ها', _safe_reverse('core:super_admin_courses'), 'book'),
            ('اساتید', _safe_reverse('core:super_admin_teachers'), 'teacher'),
            ('دانشجویان', _safe_reverse('core:super_admin_students'), 'students'),
            ('گروه‌بندی', _safe_reverse('core:super_admin_groups'), 'groups'),
            ('آزمون', _safe_reverse('core:super_admin_exams'), 'exam'),
            ('تقویم آموزشی', _safe_reverse('core:super_admin_calendar'), 'calendar'),
        ]),
        ('سیستم', [
            ('ساختار سازمانی', _safe_reverse('core:super_admin_org_units'), 'database'),
            ('مدیران آموزشی', _safe_reverse('core:super_admin_academic_managers'), 'manager'),
            ('سال تحصیلی و ترم', _safe_reverse('core:super_admin_academic_terms'), 'term'),
            ('تنظیمات سامانه', _safe_reverse('core:super_admin_settings'), 'settings'),
            ('پروفایل', _safe_reverse('core:profile'), 'profile'),
        ]),
    ]

def _profile_sidebar_groups(role_code):
    if role_code == 'super_admin':
        return _admin_sidebar_groups()
    groups = []
    for label, items in ROLE_NAV.get(role_code, ROLE_NAV['student']):
        groups.append((
            label,
            [(item_label, _safe_reverse(url_name), ICON_MAP.get(icon, '•')) for item_label, url_name, icon in items],
        ))
    groups.append(('سیستم', [('پروفایل', _safe_reverse('core:profile'), '♙')]))
    return groups


def app_shell(request):
    profile = None
    role_code = 'student'
    if request.user.is_authenticated:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT p.full_name, ur.role
                FROM profiles p
                LEFT JOIN user_roles ur ON ur.user_id = p.id
                WHERE p.username = %s OR p.email = %s
                ORDER BY CASE ur.role
                    WHEN 'admin' THEN 1
                    WHEN 'academic_manager' THEN 2
                    WHEN 'teacher' THEN 3
                    WHEN 'student' THEN 4
                    ELSE 5
                END
                LIMIT 1
                """,
                [request.user.username, request.user.email or ''],
            )
            row = cursor.fetchone()
        if row:
            profile = {'full_name': row[0], 'role': row[1]}
            role_code = {
                'admin': 'super_admin',
                'academic_manager': 'exam_manager',
                'teacher': 'teacher',
                'student': 'student',
            }.get(row[1], 'student')
    groups = []
    for label, items in ROLE_NAV.get(role_code, ROLE_NAV['student']):
        groups.append({
            'label': label,
            'items': [
                {
                    'label': item_label,
                    'url': _safe_reverse(url_name),
                    'icon': ICON_MAP.get(icon, '•'),
                    'active': request.path.startswith(_safe_reverse(url_name)),
                }
                for item_label, url_name, icon in items
            ],
        })
    display_name = (
        profile['full_name']
        if profile
        else request.user.get_full_name() or request.user.username
        if request.user.is_authenticated
        else ''
    )
    return {
        'app_nav_groups': groups,
        'app_display_name': display_name,
        'app_role_name': {
            'admin': 'مدیر سامانه',
            'academic_manager': 'مدیر آموزشی',
            'teacher': 'استاد',
            'student': 'دانشجو',
        }.get(profile['role'], '') if profile else '',
        'app_is_shell_page': request.user.is_authenticated and request.resolver_match and request.resolver_match.url_name not in {'home', 'login', 'login_2fa'},
    }


def app_shell(request):
    profile = None
    role_code = 'student'
    if request.user.is_authenticated:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT p.id, p.full_name, p.username, p.email, p.avatar_url, ur.role
                FROM profiles p
                LEFT JOIN user_roles ur ON ur.user_id = p.id
                WHERE p.username = %s OR p.email = %s
                ORDER BY CASE ur.role
                    WHEN 'admin' THEN 1
                    WHEN 'academic_manager' THEN 2
                    WHEN 'teacher' THEN 3
                    WHEN 'student' THEN 4
                    ELSE 5
                END
                LIMIT 1
                """,
                [request.user.username, request.user.email or ''],
            )
            row = cursor.fetchone()
        if row:
            profile = {
                'id': row[0],
                'full_name': row[1],
                'username': row[2],
                'email': row[3],
                'avatar_url': row[4],
                'role': row[5],
            }
            request._panel_profile_info = profile
            role_code = {
                'admin': 'super_admin',
                'academic_manager': 'exam_manager',
                'teacher': 'teacher',
                'student': 'student',
            }.get(row[5], 'student')

    profile_nav_groups = _profile_sidebar_groups(role_code)
    app_nav_groups = [
        {
            'label': group_label,
            'items': [
                {
                    'label': item_label,
                    'url': url,
                    'icon': icon,
                    'active': request.path.startswith(url),
                }
                for item_label, url, icon in items
            ],
        }
        for group_label, items in profile_nav_groups
    ]
    display_name = (
        profile['full_name']
        if profile
        else request.user.get_full_name() or request.user.username
        if request.user.is_authenticated
        else ''
    )
    role_label = {
        'admin': 'مدیر سامانه',
        'academic_manager': 'مدیر آموزشی',
        'teacher': 'استاد',
        'student': 'دانشجو',
    }.get(profile['role'], '') if profile else ''
    return {
        'app_nav_groups': app_nav_groups,
        'app_display_name': display_name,
        'app_role_name': role_label,
        'profile_nav_groups': profile_nav_groups,
        'display_name': display_name,
        'profile': profile,
        'role_label': role_label,
        'role_code': role_code,
        'is_super_admin_shell': role_code == 'super_admin',
        'app_is_shell_page': (
            request.user.is_authenticated
            and request.resolver_match
            and request.resolver_match.url_name not in {'home', 'login', 'login_2fa'}
        ),
    }
