"""«زیرمجموعه من»: how many people sit under the signed-in account, by its access level.

- teacher: the students of the groups they teach (owner or co-teacher, not archived), per group;
- academic_manager: teachers / students / courses / groups / units of their managed units (scope tree), per unit;
- admin: the whole system, academic managers included, per unit.

Counts use the same scope rules as the pages they link to, so a number always matches the list behind it.
"""
from django.urls import reverse

from .views import (
    _erd_group_scope_condition,
    _erd_manager_scope_cte,
    _erd_student_scope_condition,
    _erd_teacher_scope_condition,
    erd_has_column,
    erd_row,
    erd_rows,
)

BREAKDOWN_LIMIT = 6
UNIT_TYPES = {'university': 'دانشگاه', 'faculty': 'دانشکده', 'department': 'گروه آموزشی', 'group': 'گروه'}
ACTIVE = "COALESCE(p.status, 'active') = 'active'"


def _n(value) -> int:
    return int(value or 0)


def _tile(label, value, icon, tone, hint='', url=''):
    return {'label': label, 'value': _n(value), 'icon': icon, 'tone': tone, 'hint': hint, 'url': url}


def _with_share(rows, key):
    """Each row's bar width: its count against the largest one in the list."""
    top = max((row[key] for row in rows), default=0)
    for row in rows:
        row['share'] = round(row[key] * 100 / top) if top else 0
    return rows


def _not_archived(alias='sg') -> str:
    return f' AND COALESCE({alias}.is_archived, false) = false' if erd_has_column('student_groups', 'is_archived') else ''


# ---------------------------------------------------------------- teacher

def _teacher_overview(teacher_id) -> dict:
    own = f'(sg.teacher_id = %s OR sg.id IN (SELECT group_id FROM group_teachers WHERE teacher_id = %s)){_not_archived()}'
    own_params = [teacher_id, teacher_id]
    totals = erd_row(
        f"""
        SELECT COUNT(DISTINCT sgm.student_user_id) AS students,
               COUNT(DISTINCT CASE WHEN {ACTIVE} THEN sgm.student_user_id END) AS students_active
        FROM student_group_members sgm
        JOIN student_groups sg ON sg.id = sgm.group_id
        JOIN profiles p ON p.id = sgm.student_user_id
        WHERE {own}
        """,
        own_params,
    ) or {}
    groups = erd_rows(
        f"""
        SELECT sg.id, sg.course_id, COALESCE(NULLIF(sg.course_name, ''), c.title, '-') AS course_name,
               COALESCE(sg.group_code, '') AS group_code, COALESCE(sg.is_active, true) AS is_active,
               (SELECT COUNT(DISTINCT m.student_user_id) FROM student_group_members m WHERE m.group_id = sg.id) AS students
        FROM student_groups sg
        LEFT JOIN courses c ON c.id = sg.course_id
        WHERE {own}
        """,
        own_params,
    )
    students_url = reverse('core:teacher_students')
    courses = {str(row['course_id']) for row in groups if row['course_id']}
    active_groups = sum(1 for row in groups if row['is_active'])
    rows = [
        {
            'label': row['course_name'],
            'meta': f"گروه {row['group_code']}" if row['group_code'] else 'کلاس',
            'total': _n(row['students']),
            'counts': [{'label': 'دانشجو', 'value': _n(row['students']), 'url': f"{students_url}?group={row['id']}"}],
        }
        for row in sorted(groups, key=lambda item: (-_n(item['students']), str(item['course_name'])))
    ]
    students = _n(totals.get('students'))
    return {
        'subtitle': 'دانشجویان کلاس‌هایی که تدریس می‌کنید (مالک یا مدرس همکار)',
        'more_url': students_url,
        'more_label': 'فهرست دانشجویان',
        'tiles': [
            _tile('دانشجویان', students, 'students', 'blue', f"{_n(totals.get('students_active'))} حساب فعال", students_url),
            _tile('کلاس‌ها', len(groups), 'groups', 'violet', f'{active_groups} کلاس فعال', reverse('core:teacher_courses')),
            _tile('درس‌ها', len(courses), 'courses', 'orange', 'درس‌های کلاس‌های شما', reverse('core:teacher_courses')),
        ],
        'breakdown_title': 'دانشجویان به تفکیک کلاس',
        'rows': _with_share(rows[:BREAKDOWN_LIMIT], 'total'),
        'rows_more': max(len(rows) - BREAKDOWN_LIMIT, 0),
        'empty': 'هنوز کلاسی به شما اختصاص داده نشده است.',
    }


# ---------------------------------------------------------------- manager / admin

def _unit_rows(users_url, unit_where='', params=None) -> list:
    """Units with the teachers and students registered directly in them (what the users page's «واحد» filter shows)."""
    rows = erd_rows(
        f"""
        {_erd_manager_scope_cte() if unit_where else ''}
        SELECT ou.id, ou.name, ou.type, COALESCE(parent.name, '') AS parent_name,
               (SELECT COUNT(*) FROM teacher_profiles tp WHERE tp.org_unit_id = ou.id) AS teachers,
               (SELECT COUNT(*) FROM student_profiles sp WHERE sp.org_unit_id = ou.id) AS students
        FROM org_units ou
        LEFT JOIN org_units parent ON parent.id = ou.parent_id
        {('WHERE ' + unit_where) if unit_where else ''}
        """,
        params or [],
    )
    result = []
    for row in rows:
        teachers, students = _n(row['teachers']), _n(row['students'])
        if not teachers and not students:
            continue
        meta = UNIT_TYPES.get(row['type'] or '', 'واحد')
        if row['parent_name']:
            meta = f"{meta} · {row['parent_name']}"
        result.append({
            'label': row['name'],
            'meta': meta,
            'total': teachers + students,
            'counts': [
                {'label': 'استاد', 'value': teachers, 'url': f"{users_url}?tab=teachers&unit={row['id']}"},
                {'label': 'دانشجو', 'value': students, 'url': f"{users_url}?tab=students&unit={row['id']}"},
            ],
        })
    result.sort(key=lambda item: (-item['total'], str(item['label'])))
    return result


def manager_scope_counts(manager_id) -> dict:
    """Teachers, students, courses, groups and units in this academic manager's scope tree (same rules as access checks)."""
    return erd_row(
        _erd_manager_scope_cte() + f"""
        SELECT
            (SELECT COUNT(*) FROM teacher_profiles tp WHERE {_erd_teacher_scope_condition()}) AS teachers,
            (SELECT COUNT(*) FROM teacher_profiles tp JOIN profiles p ON p.id = tp.user_id
             WHERE {ACTIVE} AND {_erd_teacher_scope_condition()}) AS teachers_active,
            (SELECT COUNT(*) FROM student_profiles sp WHERE {_erd_student_scope_condition()}) AS students,
            (SELECT COUNT(*) FROM student_profiles sp JOIN profiles p ON p.id = sp.user_id
             WHERE {ACTIVE} AND {_erd_student_scope_condition()}) AS students_active,
            (SELECT COUNT(*) FROM courses c WHERE c.org_unit_id IN (SELECT id FROM managed_units)) AS courses,
            (SELECT COUNT(*) FROM student_groups sg LEFT JOIN courses c ON c.id = sg.course_id
             WHERE {_erd_group_scope_condition()}{_not_archived()}) AS groups,
            (SELECT COUNT(*) FROM managed_units) AS units
        """,
        [manager_id],
    ) or {}


def _manager_overview(manager_id) -> dict:
    counts = manager_scope_counts(manager_id)
    users_url = reverse('core:exam_manager_users')
    rows = _unit_rows(users_url, 'ou.id IN (SELECT id FROM managed_units)', [manager_id])
    return {
        'subtitle': 'اساتید و دانشجویان واحدهای سازمانی تحت مدیریت شما و زیرواحدهایشان',
        'more_url': users_url,
        'more_label': 'مدیریت کاربران',
        'tiles': [
            _tile('اساتید', counts.get('teachers'), 'teachers', 'blue', f"{_n(counts.get('teachers_active'))} حساب فعال", f'{users_url}?tab=teachers'),
            _tile('دانشجویان', counts.get('students'), 'students', 'emerald', f"{_n(counts.get('students_active'))} حساب فعال", f'{users_url}?tab=students'),
            _tile('درس‌ها', counts.get('courses'), 'courses', 'orange', 'در واحدهای شما', reverse('core:exam_manager_courses')),
            _tile('گروه‌های درسی', counts.get('groups'), 'groups', 'violet', f"{_n(counts.get('units'))} واحد سازمانی"),
        ],
        'breakdown_title': 'به تفکیک واحد سازمانی محل ثبت',
        'rows': _with_share(rows[:BREAKDOWN_LIMIT], 'total'),
        'rows_more': max(len(rows) - BREAKDOWN_LIMIT, 0),
        'empty': 'هنوز استاد یا دانشجویی در واحدهای شما ثبت نشده است.',
    }


def _admin_overview() -> dict:
    counts = erd_row(
        f"""
        SELECT
            (SELECT COUNT(DISTINCT ur.user_id) FROM user_roles ur WHERE ur.role = 'academic_manager') AS managers,
            (SELECT COUNT(*) FROM teacher_profiles) AS teachers,
            (SELECT COUNT(*) FROM teacher_profiles tp JOIN profiles p ON p.id = tp.user_id WHERE {ACTIVE}) AS teachers_active,
            (SELECT COUNT(*) FROM student_profiles) AS students,
            (SELECT COUNT(*) FROM student_profiles sp JOIN profiles p ON p.id = sp.user_id WHERE {ACTIVE}) AS students_active,
            (SELECT COUNT(*) FROM courses) AS courses,
            (SELECT COUNT(*) FROM org_units) AS units
        """
    ) or {}
    users_url = reverse('core:super_admin_users')
    rows = _unit_rows(users_url)
    return {
        'subtitle': 'همه کاربران سامانه بر اساس نقش و واحد سازمانی',
        'more_url': users_url,
        'more_label': 'مدیریت کاربران',
        'tiles': [
            _tile('مدیران آموزشی', counts.get('managers'), 'managers', 'indigo', f"{_n(counts.get('units'))} واحد سازمانی", reverse('core:super_admin_academic_managers')),
            _tile('اساتید', counts.get('teachers'), 'teachers', 'blue', f"{_n(counts.get('teachers_active'))} حساب فعال", f'{users_url}?tab=teachers'),
            _tile('دانشجویان', counts.get('students'), 'students', 'emerald', f"{_n(counts.get('students_active'))} حساب فعال", f'{users_url}?tab=students'),
            _tile('درس‌ها', counts.get('courses'), 'courses', 'orange', 'در کل سامانه', reverse('core:super_admin_courses')),
        ],
        'breakdown_title': 'به تفکیک واحد سازمانی محل ثبت',
        'rows': _with_share(rows[:BREAKDOWN_LIMIT], 'total'),
        'rows_more': max(len(rows) - BREAKDOWN_LIMIT, 0),
        'empty': 'هنوز استاد یا دانشجویی به واحد سازمانی وصل نشده است.',
    }


def subordinate_overview(role, profile_id) -> dict | None:
    """The «زیرمجموعه من» panel for one account; None for roles with nobody under them (students)."""
    if role == 'admin':
        data = _admin_overview()
    elif role == 'academic_manager' and profile_id:
        data = _manager_overview(profile_id)
    elif role == 'teacher' and profile_id:
        data = _teacher_overview(profile_id)
    else:
        return None
    data['title'] = 'زیرمجموعه من'
    return data
