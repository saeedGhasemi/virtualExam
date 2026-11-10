"""«حذف» of a course or a student/teacher account, with two choices in one dialog:

- «فقط خودِ …» (mode=only): the item and its pure link rows (enrolments, group memberships, roles, notifications…)
  are deleted; records that only point at it stay and lose the link (exams/groups of a course keep running without
  a course, a student's exam attempts stay without a name).
- «همراه با همه‌ی سوابق» (mode=all): everything that belongs to it is deleted too (a course's exams with their
  attempts/answers/objections, its groups and question sets; a student's attempts; a teacher's exams/questions/groups).

The effect follows the database's foreign keys (read live) plus a few references without a constraint, in one
transaction (all or nothing). GET on the delete URL returns the dialog body with the counts of a dry run.
A course's questions always stay in the question bank (they may be used by other courses' exams).
"""
from collections import Counter, namedtuple

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.db import connection, transaction
from django.http import Http404, HttpResponseForbidden
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme

from . import account_security
from .views import (
    _erd_is_admin_request,
    _erd_managed_unit_ids,
    _erd_profile_in_manager_scope,
    erd_role_required,
    erd_row,
    erd_rows,
    log_activity,
)

Reference = namedtuple('Reference', 'child child_column parent parent_column not_null')
IGNORED_PREFIXES = ('core_', 'auth_', 'django_')  # legacy ORM tables / Django internals
CHUNK = 500

VIRTUAL_REFERENCES = (  # references without a database constraint: (child, column, parent, parent column)
    ('academic_calendar_events', 'course_id', 'courses', 'id'),
    ('academic_calendar_events', 'group_id', 'student_groups', 'id'),
    ('academic_calendar_events', 'created_by', 'profiles', 'id'),
    ('account_deletion_requests', 'reviewer_id', 'profiles', 'id'),
    ('teacher_profile_change_requests', 'reviewer_id', 'profiles', 'id'),
    ('profiles', 'deleted_by', 'profiles', 'id'),
)

# Pure link rows: meaningless without the item, deleted in both modes.
LINKS = {
    ('student_course_enrollments', 'course_id'), ('student_course_enrollments', 'student_user_id'),
    ('student_group_members', 'group_id'), ('student_group_members', 'student_user_id'),
    ('exam_assignments', 'exam_id'), ('exam_assignments', 'group_id'), ('exam_assignments', 'student_profile_id'),
    ('exam_assignment_exclusions', 'exam_id'), ('exam_assignment_exclusions', 'student_profile_id'),
    ('exam_staff', 'exam_id'), ('exam_staff', 'teacher_id'), ('exam_questions', 'exam_id'), ('exam_questions', 'question_id'),
    ('question_set_items', 'set_id'), ('question_set_items', 'question_id'), ('group_teachers', 'group_id'),
    ('course_audit_log', 'course_id'), ('user_roles', 'user_id'), ('notifications', 'user_id'),
    ('account_deletion_requests', 'profile_id'),
}
# Records that belong to the item: deleted only with «همراه با همه‌ی سوابق».
RECORDS = {
    ('exams', 'course_id'), ('osce_exams', 'course_id'), ('question_sets', 'course_id'), ('student_groups', 'course_id'),
    ('exam_attempts', 'exam_id'), ('exam_attempts', 'student_id'), ('attempt_answers', 'attempt_id'),
    ('objections', 'exam_id'), ('objections', 'attempt_id'), ('objections', 'student_id'),
    ('exams', 'teacher_id'), ('questions', 'teacher_id'), ('osce_exams', 'teacher_id'), ('student_groups', 'teacher_id'),
}
ALWAYS_DETACH = {('questions', 'course_id')}

LABELS = {  # shown in the dialog, in this order
    'exams': 'آزمون', 'exam_attempts': 'شرکت در آزمون (برگه و نمره)', 'attempt_answers': 'پاسخ دانشجو',
    'objections': 'اعتراض', 'osce_exams': 'آزمون آسکی', 'student_groups': 'گروه / کلاس',
    'questions': 'سؤال بانک سؤال', 'question_sets': 'مجموعه سؤال',
    'student_group_members': 'عضویت در گروه', 'student_course_enrollments': 'ثبت‌نام در درس',
}
KIND_LABELS = {'student': 'دانشجو', 'teacher': 'استاد'}


def _graph(cursor):
    cursor.execute(
        """
        SELECT cl.relname, a.attname, pcl.relname, pa.attname, a.attnotnull
        FROM pg_constraint co
        JOIN pg_class cl ON cl.oid = co.conrelid
        JOIN pg_namespace ns ON ns.oid = cl.relnamespace
        JOIN pg_class pcl ON pcl.oid = co.confrelid
        JOIN pg_attribute a ON a.attrelid = co.conrelid AND a.attnum = co.conkey[1]
        JOIN pg_attribute pa ON pa.attrelid = co.confrelid AND pa.attnum = co.confkey[1]
        WHERE co.contype = 'f' AND array_length(co.conkey, 1) = 1 AND ns.nspname = current_schema()
        """
    )
    references = [Reference(*row) for row in cursor.fetchall()]
    known = {(ref.child, ref.child_column) for ref in references}
    introspection = connection.introspection
    tables = set(introspection.table_names(cursor))
    for child, column, parent, parent_column in VIRTUAL_REFERENCES:
        if (child, column) in known or child not in tables or parent not in tables:
            continue
        if column in {col.name for col in introspection.get_table_description(cursor, child)}:
            references.append(Reference(child, column, parent, parent_column, False))
    graph = {}
    for ref in references:
        if not ref.child.startswith(IGNORED_PREFIXES) and not ref.parent.startswith(IGNORED_PREFIXES):
            graph.setdefault(ref.parent, []).append(ref)
    return graph


class Plan:
    def __init__(self, cursor, mode):
        self.cursor, self.mode = cursor, mode
        self.graph = _graph(cursor)
        self.deleted, self.detached = Counter(), Counter()
        self.q = connection.ops.quote_name

    def _action(self, ref):
        key = (ref.child, ref.child_column)
        if key in ALWAYS_DETACH:
            return 'detach'
        if key in LINKS or (key in RECORDS and self.mode == 'all'):
            return 'delete'
        return 'delete' if ref.not_null else 'detach'

    def _in(self, column, values):
        return f'CAST({self.q(column)} AS TEXT) IN ({", ".join(["%s"] * len(values))})'

    def remove(self, table, column, values, depth=0):
        values = sorted({str(v) for v in values if v not in (None, '')})
        if not values:
            return
        if depth > 25:
            raise RuntimeError('reference chain too deep')
        for ref in self.graph.get(table, ()):
            keys = values
            if ref.parent_column != column:
                keys = set()
                for start in range(0, len(values), CHUNK):
                    part = values[start:start + CHUNK]
                    self.cursor.execute(f'SELECT CAST({self.q(ref.parent_column)} AS TEXT) FROM {self.q(table)} WHERE {self._in(column, part)}', part)
                    keys.update(row[0] for row in self.cursor.fetchall() if row[0] is not None)
                keys = sorted(keys)
            if not keys:
                continue
            if self._action(ref) == 'delete':
                self.remove(ref.child, ref.child_column, keys, depth + 1)
                continue
            for start in range(0, len(keys), CHUNK):
                part = keys[start:start + CHUNK]
                self.cursor.execute(f'UPDATE {self.q(ref.child)} SET {self.q(ref.child_column)} = NULL WHERE {self._in(ref.child_column, part)}', part)
                self.detached[ref.child] += max(self.cursor.rowcount or 0, 0)
        for start in range(0, len(values), CHUNK):
            part = values[start:start + CHUNK]
            self.cursor.execute(f'DELETE FROM {self.q(table)} WHERE {self._in(column, part)}', part)
            self.deleted[table] += max(self.cursor.rowcount or 0, 0)


class _DryRun(Exception):
    pass


def run(table, item_id, mode, *, commit=True, after=None):
    """Deletes in one transaction; commit=False rolls back (the dialog's counts)."""
    plan = None
    try:
        with transaction.atomic():
            with connection.cursor() as cursor:
                plan = Plan(cursor, mode)
                plan.remove(table, 'id', [item_id])
            if not commit:
                raise _DryRun
            if after:
                after()
    except _DryRun:
        pass
    return plan


def _summary(plan):
    return [{'label': label, 'count': plan.deleted[table]} for table, label in LABELS.items() if plan.deleted.get(table)]


def _back(request, fallback):
    target = request.POST.get('next') or request.GET.get('next') or ''
    if url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return target
    return fallback


def _choices(request, *, name, kind_label, table, item_id, action_url, back, reason=''):
    context = {'name': name, 'kind_label': kind_label, 'action_url': action_url, 'next': back, 'reason': reason}
    if not reason:
        context['all_items'] = _summary(run(table, item_id, 'all', commit=False))
    return render(request, 'partials/delete_choices.html', context)


def _mode(request):
    return 'all' if request.POST.get('mode') == 'all' else 'only'


# --- courses ----------------------------------------------------------------------------------------------------

@erd_role_required('academic_manager', 'admin')
def super_admin_course_delete(request, course_id):
    course = erd_row('SELECT id, title, org_unit_id FROM courses WHERE CAST(id AS TEXT) = %s', [str(course_id)])
    if not course:
        raise Http404('درس پیدا نشد.')
    managed = _erd_managed_unit_ids(request)
    if managed is not None and str(course.get('org_unit_id') or '') not in managed:
        return HttpResponseForbidden('این درس خارج از محدوده‌ی دسترسی شماست.')
    back = _back(request, reverse('core:super_admin_courses'))
    if request.method != 'POST':
        return _choices(request, name=course['title'], kind_label='درس', table='courses', item_id=course_id,
                        action_url=reverse('core:super_admin_course_delete', args=[course_id]), back=back)
    mode = _mode(request)
    plan = run('courses', course_id, mode)
    log_activity(request.user, 'course_deleted', f"درس {course['title']} حذف شد ({'با همه‌ی سوابق' if mode == 'all' else 'فقط درس'}).",
                 request, {'course_id': str(course_id), 'mode': mode, 'deleted': dict(plan.deleted)})
    messages.success(request, f"درس «{course['title']}» همراه با همه‌ی سوابقش حذف شد." if mode == 'all'
                     else f"درس «{course['title']}» حذف شد؛ آزمون‌ها، گروه‌ها و سؤال‌هایش باقی ماندند.")
    return redirect(back)


def delete_course_only(course_id):
    """For the old JSON «حذف» on the courses page."""
    run('courses', course_id, 'only')


# --- accounts ---------------------------------------------------------------------------------------------------

def account_delete_view(request, kind, user_id):
    """«حذف» on a student / teacher (called by views.super_admin_delete_account, which checks the role)."""
    if kind not in KIND_LABELS:
        raise Http404
    profile = erd_row('SELECT id, full_name, username FROM profiles WHERE CAST(id AS TEXT) = %s', [str(user_id)])
    if not profile:
        raise Http404('کاربر پیدا نشد.')
    if not _erd_is_admin_request(request) and not _erd_profile_in_manager_scope(request, user_id, kind):
        return HttpResponseForbidden('این کاربر خارج از محدوده‌ی دسترسی شماست.')
    label = KIND_LABELS[kind]
    back = _back(request, f"{reverse('core:super_admin_users')}?tab={'teachers' if kind == 'teacher' else 'students'}")
    reason = ''
    if str(profile['id']) == str(getattr(request, 'erd_profile_id', '')):
        reason = 'نمی‌توانید حساب خودتان را حذف کنید.'
    else:
        roles = {row['role'] for row in erd_rows('SELECT role FROM user_roles WHERE CAST(user_id AS TEXT) = %s', [str(user_id)])}
        others = roles - {kind, None}
        if others:
            reason = 'این حساب نقش دیگری هم دارد (مثلاً مدیر یا استاد)؛ ابتدا آن نقش را از حساب بردارید.'
    if request.method != 'POST':
        return _choices(request, name=profile['full_name'], kind_label=label, table='profiles', item_id=user_id, reason=reason,
                        action_url=reverse('core:super_admin_delete_account', args=[kind, user_id]), back=back)
    if reason:
        messages.error(request, reason)
        return redirect(back)
    mode = _mode(request)
    user = get_user_model().objects.filter(username=profile['username']).first() if profile.get('username') else None

    def remove_login():
        if not user:
            return
        account_security.end_all_sessions(user)
        with connection.cursor() as cursor:
            tables = set(connection.introspection.table_names(cursor))
            for table in ('user_sessions', 'user_two_factor', 'user_recovery_codes'):
                if table in tables:
                    cursor.execute(f'DELETE FROM {connection.ops.quote_name(table)} WHERE user_id = %s', [user.pk])
        user.delete()

    plan = run('profiles', user_id, mode, after=remove_login)
    log_activity(request.user, 'account_deleted', f"حساب {profile['full_name']} حذف شد ({'با همه‌ی سوابق' if mode == 'all' else 'فقط حساب'}).",
                 request, {'profile_id': str(user_id), 'kind': kind, 'mode': mode, 'deleted': dict(plan.deleted)})
    messages.success(request, f"{label} «{profile['full_name']}» همراه با همه‌ی سوابقش حذف شد." if mode == 'all'
                     else f"{label} «{profile['full_name']}» حذف شد؛ سوابقش بدون نام باقی ماند.")
    return redirect(back)
