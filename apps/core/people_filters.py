"""«مدیر بخش» / «استاد» / «دانشجو» filters of the manager/admin exam list and question bank (teacher's request).

Who gets which filter (each level filters by the levels below it):
- system admin (level 1): مدیر بخش + استاد + دانشجو;
- university manager (level 2): مدیر بخش (the department managers of its university) + استاد + دانشجو;
- department manager (level 3): استاد + دانشجو;
- teachers: none (their lists hold only their own exams / questions).
What a filter keeps:
- مدیر بخش M: exams / questions inside M's scope (its units and their subunits, the same rule M's own lists use)
  plus those M made; options = department managers below the viewer;
- استاد T: exams / questions T made (the «استاد» / «طراح» shown in the row); options = makers in the list;
- دانشجو: a search box (name, username, student number or national ID; Persian digits accepted, sent on Enter):
  exams the matching students are or were in (assigned directly, through a group minus exclusions, or attempted)
  and the questions of those exams; only students inside the viewer's scope are matched.
Results are always inside the viewer's own scope (the filters only narrow the list).
GET params: manager, teacher (profile ids), student (text).
"""
from .field_rules import latin_digits
from . import org_levels

STUDENT_MATCH_LIMIT = 500


def read(get) -> dict:
    return {
        'manager': (get.get('manager') or '').strip()[:64],
        'teacher': (get.get('teacher') or '').strip()[:64],
        'student': (get.get('student') or '').strip()[:100],
    }


def visible(request) -> dict:
    """Which of the three filters the signed-in account gets."""
    level = org_levels.request_level(request)
    return {
        'manager': level in (org_levels.SYSTEM, org_levels.UNIVERSITY),
        'teacher': level is not None,
        'student': level is not None,
    }


def manager_options(request) -> list:
    """Department managers (level 3) below the signed-in account: every one for the admin, those of its
    university for a level-2 manager, none otherwise. [{'value', 'label'}] sorted by name."""
    from .views import _erd_is_admin_request, _erd_managed_unit_ids, erd_rows

    if not visible(request)['manager']:
        return []
    units = None if _erd_is_admin_request(request) else sorted(_erd_managed_unit_ids(request) or ())
    if units is not None and not units:
        return []
    unit_sql = f"AND s.org_unit_id::text IN ({', '.join(['%s'] * len(units))})" if units else ''
    rows = erd_rows(
        f"""
        SELECT p.id, COALESCE(NULLIF(TRIM(p.full_name), ''), p.username, '-') AS name,
               STRING_AGG(DISTINCT ou.name, '، ') AS units,
               BOOL_OR(ou.type = 'university') AS has_university
        FROM academic_manager_scopes s
        JOIN profiles p ON p.id = s.manager_id
        JOIN org_units ou ON ou.id = s.org_unit_id
        WHERE p.deleted_at IS NULL
          AND EXISTS (SELECT 1 FROM user_roles ur WHERE ur.user_id = p.id AND ur.role = 'academic_manager')
          AND p.id::text != %s
          {unit_sql}
        GROUP BY p.id, p.full_name, p.username
        ORDER BY 2
        """,
        [str(getattr(request, 'erd_profile_id', '') or ''), *(units or [])],
    )
    return [
        {'value': str(row['id']), 'label': f"{row['name']} — {row['units']}" if row['units'] else row['name']}
        for row in rows if not row['has_university']
    ]


def valid_manager(request, value, options=None) -> str:
    """The manager filter's value when it is one of the account's options, else ''."""
    if not value:
        return ''
    options = manager_options(request) if options is None else options
    return value if any(item['value'] == value for item in options) else ''


def manager_unit_ids(manager_id) -> list:
    from .views import _erd_manager_scope_cte, erd_rows

    return sorted(str(row['id']) for row in erd_rows(_erd_manager_scope_cte() + 'SELECT id FROM managed_units', [manager_id]))


def manager_exam_ids(manager_id) -> set:
    """Exams inside a manager's scope (views._erd_exam_scope_condition with its units) or made by the manager."""
    from .views import _erd_exam_scope_condition, _erd_manager_scope_cte, erd_rows

    rows = erd_rows(
        _erd_manager_scope_cte() + f'SELECT e.id FROM exams e WHERE e.teacher_id = %s OR {_erd_exam_scope_condition()}',
        [manager_id, manager_id],
    )
    return {str(row['id']) for row in rows}


def _like(text: str) -> str:
    escaped = text.lower().replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
    return f'%{escaped}%'


def _search_text(text: str) -> str:
    """Latin digits and Persian ی / ک (Arabic forms typed on some keyboards)."""
    return latin_digits(text).replace('ي', 'ی').replace('ك', 'ک').strip()


def student_ids(request, text) -> list:
    """Profile ids of the students inside the account's scope whose name, username, student number or national ID
    contains the text."""
    from .views import _erd_is_admin_request, _erd_manager_scope_cte, _erd_student_scope_condition, erd_rows

    text = _search_text(text or '')
    if not text:
        return []
    is_admin = _erd_is_admin_request(request)
    like = _like(text)
    name_sql = "TRANSLATE(LOWER(COALESCE({col}, '')), 'يك', 'یک') LIKE %s ESCAPE '\\'"
    rows = erd_rows(
        ('' if is_admin else _erd_manager_scope_cte()) + f"""
        SELECT DISTINCT sp.user_id AS id
        FROM student_profiles sp
        JOIN profiles p ON p.id = sp.user_id
        WHERE p.deleted_at IS NULL
          AND ({'1=1' if is_admin else _erd_student_scope_condition()})
          AND ({name_sql.format(col='p.full_name')} OR {name_sql.format(col='p.username')}
               OR COALESCE(sp.student_number, '') LIKE %s ESCAPE '\\' OR COALESCE(p.national_id, '') LIKE %s ESCAPE '\\')
        LIMIT {STUDENT_MATCH_LIMIT}
        """,
        ([] if is_admin else [request.erd_profile_id]) + [like] * 4,
    )
    return [str(row['id']) for row in rows]


def student_exam_ids(ids) -> set:
    """Exams the students are or were in: direct assignment, group assignment minus exclusions, or an attempt."""
    from .views import erd_rows

    if not ids:
        return set()
    marks = ', '.join(['%s'] * len(ids))
    rows = erd_rows(
        f"""
        SELECT ea.exam_id FROM exam_assignments ea WHERE ea.student_profile_id::text IN ({marks})
        UNION
        SELECT ea.exam_id FROM exam_assignments ea
        JOIN student_group_members sgm ON sgm.group_id = ea.group_id
        WHERE sgm.student_user_id::text IN ({marks})
          AND NOT EXISTS (SELECT 1 FROM exam_assignment_exclusions ax
                          WHERE ax.exam_id = ea.exam_id AND ax.student_profile_id = sgm.student_user_id)
        UNION
        SELECT at.exam_id FROM exam_attempts at WHERE at.student_id::text IN ({marks})
        """,
        [*ids, *ids, *ids],
    )
    return {str(row['exam_id']) for row in rows}
