"""The panel top bar's «اعلان‌ها» (bell) and «جستجو» (magnifier) buttons (partials/super_admin_chrome.html +
static/js/panel-header.js; they used to be decorative).

- notifications: GET → the signed-in account's latest notifications (the `notifications` table that
  views.create_notification fills) + the unread count; POST id=<uuid> marks one read, POST all=1 marks all read.
  Only the account's own rows are ever read or changed.
- search: GET ?q= → pages of the account's own menu whose title matches, plus records the role may open:
  admin → users, courses, exams, groups; academic manager → users / exams in their units (same scope checks as the
  user and exam pages); teacher → their own exams. Students get pages only.
Both answer JSON and are fetched by panel-header.js; text search runs only on Enter / the search button (CLAUDE.md)."""
from django.http import JsonResponse
from django.urls import NoReverseMatch, reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from .views import erd_execute, erd_role_required, erd_rows

PANEL_ROLES = ('admin', 'academic_manager', 'teacher', 'student')
NOTIFICATION_LIMIT = 15
SEARCH_LIMIT = 6

# Pages per role: (title, url name, extra words that should find it).
PAGES = {
    'admin': [
        ('داشبورد', 'core:dashboard', 'خانه'),
        ('درس‌ها', 'core:super_admin_courses', 'دروس'),
        ('کاربران — اساتید', 'core:super_admin_users', 'استاد معلم'),
        ('مدیران آموزشی', 'core:super_admin_academic_managers', 'مدیر'),
        ('فهرست اطلاعات کاربران', 'core:super_admin_user_directory', 'دانشجو چاپ'),
        ('گروه‌بندی', 'core:super_admin_groups', 'گروه کلاس'),
        ('آزمون‌ها', 'core:super_admin_exams', 'امتحان'),
        ('تقویم آموزشی', 'core:super_admin_calendar', 'رویداد'),
        ('بانک سؤال', 'core:teacher_questions', 'سوال سؤالات'),
        ('تنظیمات سامانه', 'core:super_admin_settings', 'پشتیبان بازیابی امنیت ظاهر'),
        ('سال تحصیلی و ترم', 'core:super_admin_academic_terms', 'ترم نیمسال'),
        ('ساختار سازمانی', 'core:super_admin_org_units', 'دانشگاه بخش'),
        ('پروفایل', 'core:profile', 'حساب گذرواژه رمز'),
    ],
    'academic_manager': [
        ('داشبورد', 'core:exam_manager_dashboard', 'خانه'),
        ('گروه‌ها', 'core:exam_manager_groups', 'گروه کلاس'),
        ('تقویم آموزشی', 'core:exam_manager_calendar', 'رویداد'),
        ('بانک سؤال', 'core:teacher_questions', 'سوال سؤالات'),
        ('پروفایل', 'core:profile', 'حساب گذرواژه رمز'),
    ],
    'teacher': [
        ('داشبورد', 'core:teacher_panel', 'خانه'),
        ('بانک سؤال', 'core:teacher_questions', 'سوال سؤالات'),
        ('تقویم', 'core:teacher_calendar', 'رویداد'),
        ('تنظیمات', 'core:teacher_settings', 'امنیت گذرواژه'),
        ('پروفایل', 'core:profile', 'حساب'),
    ],
    'student': [
        ('داشبورد', 'core:dashboard', 'خانه'),
        ('تقویم', 'core:student_calendar', 'رویداد'),
        ('تنظیمات', 'core:student_settings', 'امنیت گذرواژه'),
        ('پروفایل', 'core:profile', 'حساب'),
    ],
}


def _norm(text) -> str:
    return (str(text or '').replace('ي', 'ی').replace('ك', 'ک').replace('‌', ' ').strip().lower())


def _url(name, *args):
    try:
        return reverse(name, args=args)
    except NoReverseMatch:
        return ''


def _iso(value):
    if not value:
        return ''
    if timezone.is_naive(value):  # timestamp columns without time zone store UTC (views._db_naive_datetime)
        value = timezone.make_aware(value, timezone.utc)
    return timezone.localtime(value).isoformat()


@erd_role_required(*PANEL_ROLES)
@require_http_methods(['GET', 'POST'])
def notifications(request):
    profile_id = request.erd_profile_id
    if not profile_id:
        return JsonResponse({'unread': 0, 'items': []})
    if request.method == 'POST':
        if request.POST.get('all') == '1':
            erd_execute('UPDATE notifications SET is_read = TRUE WHERE user_id = %s AND is_read = FALSE', [profile_id])
        elif request.POST.get('id'):
            erd_execute('UPDATE notifications SET is_read = TRUE WHERE id::text = %s AND user_id = %s',
                        [request.POST['id'], profile_id])
    rows = erd_rows(
        'SELECT id, title, message, link, is_read, created_at FROM notifications WHERE user_id = %s '
        'ORDER BY is_read, created_at DESC NULLS LAST LIMIT %s', [profile_id, NOTIFICATION_LIMIT])
    unread = erd_rows('SELECT COUNT(*) AS n FROM notifications WHERE user_id = %s AND is_read = FALSE', [profile_id])
    items = [{
        'id': str(row['id']),
        'title': row.get('title') or 'اعلان',
        'message': row.get('message') or '',
        # only links inside this site («/…», never «//host»): the link column is written by the app, but stay safe
        'link': row['link'] if str(row.get('link') or '').startswith('/') and not str(row['link']).startswith('//') else '',
        'is_read': bool(row.get('is_read')),
        'at': _iso(row.get('created_at')),
    } for row in rows]
    return JsonResponse({'unread': unread[0]['n'] if unread else 0, 'items': items})


def _like(q):
    return '%' + q.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'


def _records(request, q):
    role, profile_id = request.erd_role, request.erd_profile_id
    like = _like(q)
    groups = []
    if role == 'admin':
        users = erd_rows(
            """
            SELECT p.id, p.full_name, p.username, ur.role FROM profiles p
            JOIN user_roles ur ON ur.user_id = p.id
            WHERE ur.role IN ('student', 'teacher', 'academic_manager') AND p.deleted_at IS NULL
              AND (p.full_name ILIKE %s OR p.username ILIKE %s OR p.email ILIKE %s)
            ORDER BY p.full_name LIMIT %s
            """, [like, like, like, SEARCH_LIMIT])
        kinds = {'student': ('student', 'دانشجو'), 'teacher': ('teacher', 'استاد'), 'academic_manager': ('manager', 'مدیر آموزشی')}
        groups.append(('کاربران', [
            {'title': row['full_name'] or row['username'], 'hint': kinds[row['role']][1],
             'url': _url('core:super_admin_user_profile', kinds[row['role']][0], row['id'])} for row in users]))
        courses = erd_rows('SELECT id, title, code FROM courses WHERE title ILIKE %s OR code ILIKE %s ORDER BY title LIMIT %s',
                           [like, like, SEARCH_LIMIT])
        groups.append(('درس‌ها', [{'title': row['title'], 'hint': row.get('code') or 'درس',
                                    'url': _url('core:super_admin_course_edit', row['id'])} for row in courses]))
        exams = erd_rows('SELECT id, title FROM exams WHERE title ILIKE %s ORDER BY start_at DESC NULLS LAST LIMIT %s',
                         [like, SEARCH_LIMIT])
        groups.append(('آزمون‌ها', [{'title': row['title'], 'hint': 'آزمون',
                                      'url': _url('core:super_admin_exam_hub', row['id'])} for row in exams]))
        rows = erd_rows(
            "SELECT id, course_name, group_code FROM student_groups WHERE course_name ILIKE %s OR group_code ILIKE %s "
            "ORDER BY course_name LIMIT %s", [like, like, SEARCH_LIMIT])
        groups.append(('گروه‌های درسی', [{'title': row['course_name'] or 'گروه', 'hint': row.get('group_code') or 'گروه',
                                          'url': _url('core:super_admin_group_detail', row['id'])} for row in rows]))
    elif role == 'academic_manager':
        from .views import _erd_profile_in_manager_scope

        users = erd_rows(
            """
            SELECT p.id, p.full_name, p.username, ur.role FROM profiles p
            JOIN user_roles ur ON ur.user_id = p.id
            WHERE ur.role IN ('student', 'teacher') AND p.deleted_at IS NULL
              AND (p.full_name ILIKE %s OR p.username ILIKE %s OR p.email ILIKE %s)
            ORDER BY p.full_name LIMIT 40
            """, [like, like, like])
        found = []
        for row in users:
            kind = 'student' if row['role'] == 'student' else 'teacher'
            if _erd_profile_in_manager_scope(request, row['id'], kind):
                found.append({'title': row['full_name'] or row['username'], 'hint': 'دانشجو' if kind == 'student' else 'استاد',
                              'url': _url('core:super_admin_user_profile', kind, row['id'])})
            if len(found) >= SEARCH_LIMIT:
                break
        groups.append(('کاربران', found))
    elif role == 'teacher' and profile_id:
        exams = erd_rows('SELECT id, title FROM exams WHERE teacher_id = %s AND title ILIKE %s '
                         'ORDER BY start_at DESC NULLS LAST LIMIT %s', [profile_id, like, SEARCH_LIMIT])
        groups.append(('آزمون‌های من', [{'title': row['title'], 'hint': 'آزمون',
                                          'url': _url('core:teacher_exam_hub', row['id'])} for row in exams]))
    return [{'label': label, 'items': [item for item in items if item['url']]} for label, items in groups]


@erd_role_required(*PANEL_ROLES)
@require_http_methods(['GET'])
def search(request):
    q = ' '.join(str(request.GET.get('q') or '').split())[:80]
    if len(q) < 2:
        return JsonResponse({'q': q, 'groups': [], 'message': 'دست‌کم ۲ حرف بنویسید.'})
    needle = _norm(q)
    pages = []
    for title, name, words in PAGES.get(request.erd_role, []):
        url = _url(name)
        if url and (needle in _norm(title) or needle in _norm(words)):
            pages.append({'title': title, 'hint': 'صفحه', 'url': url})
    groups = [{'label': 'صفحه‌ها', 'items': pages[:SEARCH_LIMIT]}] + _records(request, q)
    groups = [group for group in groups if group['items']]
    return JsonResponse({'q': q, 'groups': groups, 'message': '' if groups else 'نتیجه‌ای پیدا نشد.'})
