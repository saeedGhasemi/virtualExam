"""The three fixed access levels of the system (replaces the old editable «سطح‌ها» of «ساختار سازمانی»).

  سطح ۱ — مدیر سیستم (role `admin`): the whole system. Defines universities (level 2) and departments (level 3)
          and the managers of both, and sees everything.
  سطح ۲ — دانشگاه (org unit `university`, e.g. «دانشگاه علوم پزشکی»): an `academic_manager` whose scope is a
          university. Defines the departments of that university and their managers, and sees / manages every
          teacher, student, course, class and exam of its departments.
  سطح ۳ — بخش (org unit `department`, e.g. «بخش کودکان»; the academic manager of one ward/department): an
          `academic_manager` whose scope is a department. Creates its own teachers and students and manages the
          courses, classes and exams of the department. Cannot change the structure or create managers.
  Under level 3: teachers (their classes, students and exams) and students.

Scope itself is the existing `academic_manager_scopes` tree (`views._erd_manager_scope_cte`): a level-2 manager's
scope is its university, so every department below it is included automatically. A manager's level is the
highest unit in its scope (any university → 2, else 3). Old unit types `faculty` / `group` count as level 3.
"""
from django.db import connection

SYSTEM, UNIVERSITY, DEPARTMENT = 1, 2, 3

LEVELS = {
    SYSTEM: {
        'number': SYSTEM, 'title': 'مدیر سیستم', 'unit': 'کل سامانه', 'manager_title': 'مدیر سیستم', 'tone': 'blue',
        'hint': 'ریشه‌ی سامانه؛ دانشگاه‌ها، بخش‌ها و مدیران آن‌ها را تعریف می‌کند و به همه‌چیز دسترسی دارد.',
    },
    UNIVERSITY: {
        'number': UNIVERSITY, 'title': 'دانشگاه', 'unit': 'دانشگاه', 'manager_title': 'مدیر دانشگاه', 'tone': 'purple',
        'unit_type': 'university', 'name': 'دانشگاه علوم پزشکی',  # shown as the level's title (user's choice)
        'hint': 'بخش‌های خود و مدیرانشان را تعریف می‌کند و استادان، دانشجویان و آزمون‌های همه‌ی بخش‌هایش را می‌بیند.',
    },
    DEPARTMENT: {
        'number': DEPARTMENT, 'title': 'بخش', 'unit': 'بخش', 'manager_title': 'مدیر بخش', 'tone': 'green',
        'unit_type': 'department', 'name': 'بخش کودکان',  # shown as the level's title (user's choice)
        'hint': 'مدیر آموزشی بخش؛ استاد و دانشجوی خود را می‌سازد و درس، کلاس و آزمون‌های بخش را مدیریت می‌کند.',
    },
}

UNIT_TYPE_LEVEL = {'university': UNIVERSITY, 'faculty': DEPARTMENT, 'department': DEPARTMENT, 'group': DEPARTMENT}

# What each level may do: (capability, system, university, department, teacher)
PERMISSIONS = [
    ('تعریف دانشگاه (سطح ۲) و مدیر دانشگاه', True, False, False, False),
    ('تعریف بخش (سطح ۳) و مدیر بخش', True, True, False, False),
    ('ساخت استاد و دانشجو', True, True, True, False),
    ('تعریف درس و کلاس، عضوگیری دانشجو', True, True, True, 'کلاس‌های خودش'),
    ('ساخت، تأیید و برگزاری آزمون', True, True, True, 'آزمون‌های خودش'),
    ('تصحیح و انتشار نمره', True, True, True, 'آزمون‌های خودش'),
    ('دیدن گزارش‌ها و کاربران', 'کل سامانه', 'بخش‌های دانشگاه', 'همان بخش', 'دانشجویان خودش'),
    ('تنظیمات عمومی سامانه، ترم‌ها و پشتیبان‌گیری', True, False, False, False),
]


def unit_level(unit_type) -> int:
    return UNIT_TYPE_LEVEL.get(str(unit_type or ''), DEPARTMENT)


def manager_level(profile_id) -> int:
    """2 when the manager's scope holds a university, else 3 (no scope at all: 3, i.e. the narrowest)."""
    if not profile_id:
        return DEPARTMENT
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT ou.type FROM academic_manager_scopes s JOIN org_units ou ON ou.id = s.org_unit_id
            WHERE s.manager_id = %s
            """,
            [str(profile_id)],
        )
        types = [row[0] for row in cursor.fetchall()]
    return min((unit_level(kind) for kind in types), default=DEPARTMENT)


def account_level(role, profile_id=None):
    if role in ('admin', 'super_admin'):
        return SYSTEM
    if role in ('academic_manager', 'exam_manager'):
        return manager_level(profile_id)
    return None


def manager_title(role, profile_id=None, level=None) -> str:
    level = level or account_level(role, profile_id)
    return LEVELS[level]['manager_title'] if level in LEVELS else ''


def request_level(request):
    """The signed-in account's level (1 / 2 / 3, None for teachers and students), cached on the request."""
    if not hasattr(request, '_mq_access_level'):
        from .views import erd_primary_role, erd_profile_for_user

        role = getattr(request, 'erd_role', None) or erd_primary_role(request.user)
        profile_id = getattr(request, 'erd_profile_id', None)
        if role == 'academic_manager' and not profile_id:
            profile = erd_profile_for_user(request.user)
            profile_id = profile['id'] if profile else None
        request._mq_access_level = account_level(role, profile_id)
    return request._mq_access_level


def can_manage_structure(request) -> bool:
    """Levels 1 and 2 define units (level 2: departments of its own university) and the managers of them."""
    return request_level(request) in (SYSTEM, UNIVERSITY)
