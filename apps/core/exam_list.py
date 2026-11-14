"""Shared exam listing: teacher «آزمون‌های من» and manager/admin «آزمون‌ها» look and work the same.

Page = header («+ آزمون جدید»), status tabs with counts, filter bar (search title/code, course, group, and for
managers/admin «مدیر بخش» / «استاد» / «دانشجو» (apps/core/people_filters.py), date range, sort, table/card switch), the list as a table or as cards, server pager (10 per page).
* Data: views.py `_teacher_exam_list` (SQL) and `super_admin_exams` (Python filtering) build `rows` with the
  fields `present()` fills in, then `listing()` adds tabs and filter options.
* Template: templates/partials/exam_list/list.html (include with `xl=...`); styles static/css/exam-list.css;
  behaviour (view switch, «…» menu, copy code) static/js/exam-list.js.
No database access here (views.py imports this module)."""
from datetime import timedelta

from django.utils import timezone

# tab key → (label, tone); «همه» first. «لغو شده» only shows when there is one (or it is selected).
STATE_TABS = (
    ('all', 'همه', ''),
    ('draft', 'پیش‌نویس', 'violet'),
    ('pending_approval', 'در انتظار تأیید', 'amber'),
    ('scheduled', 'برنامه‌ریزی‌شده', 'blue'),
    ('running', 'در حال برگزاری', 'green'),
    ('finished', 'پایان‌یافته', 'grey'),
    ('cancelled', 'لغو شده', 'red'),
)
STATE_KEYS = {key for key, _label, _tone in STATE_TABS}

DATE_RANGES = {
    '': 'همه',
    'today': 'امروز',
    'week': '۷ روز آینده',
    'month': '۳۰ روز آینده',
    'past': 'برگزارشده',
    'unset': 'بدون زمان',
}
SORTS = {
    'newest': 'جدیدترین',
    'upcoming': 'نزدیک‌ترین',
    'oldest': 'قدیمی‌ترین',
    'title': 'عنوان',
}
VIEWS = ('cards', 'table')
PAGE_SIZE = 10


def read_filters(get, status_keys=STATE_KEYS) -> dict:
    """The list's GET parameters, unknown values dropped."""
    status = get.get('status') or 'all'
    date = get.get('date') or ''
    sort = get.get('sort') or 'newest'
    view = get.get('view') or 'table'
    return {
        'query': (get.get('q') or '').strip()[:100],
        'status': status if status in status_keys else 'all',
        'course': (get.get('course') or '').strip()[:64],
        'group': (get.get('group') or '').strip()[:64],
        'teacher': (get.get('teacher') or '').strip()[:64],  # profile id (people_filters)
        'manager': (get.get('manager') or '').strip()[:64],
        'student': (get.get('student') or '').strip()[:100],
        'date': date if date in DATE_RANGES else '',
        'sort': sort if sort in SORTS else 'newest',
        'view': view if view in VIEWS else 'table',
    }


def date_bounds(key, now=None):
    """(from, to) aware datetimes of a date range; ('unset', None) / ('past', now) for the special ones."""
    now = now or timezone.now()
    start_of_today = timezone.localtime(now).replace(hour=0, minute=0, second=0, microsecond=0)
    if key == 'today':
        return start_of_today, start_of_today + timedelta(days=1)
    if key == 'week':
        return now, start_of_today + timedelta(days=8)
    if key == 'month':
        return now, start_of_today + timedelta(days=31)
    if key == 'past':
        return 'past', now
    if key == 'unset':
        return 'unset', None
    return None, None


def in_date_range(start_at, key, now=None) -> bool:
    """Python twin of the SQL date filter (manager/admin list)."""
    low, high = date_bounds(key, now)
    if low is None:
        return True
    if low == 'unset':
        return start_at is None
    if not start_at:
        return False
    if low == 'past':
        return start_at < high
    return low <= start_at < high


def tabs(counts: dict, current: str) -> list:
    total = sum(counts.get(key, 0) for key, _label, _tone in STATE_TABS[1:])
    items = []
    for key, label, tone in STATE_TABS:
        count = total if key == 'all' else counts.get(key, 0)
        if key == 'cancelled' and not count and current != 'cancelled':
            continue
        items.append({'key': key, 'param': '' if key == 'all' else key, 'label': label, 'tone': tone, 'count': count, 'active': key == current})
    return items


def pill(state: str, label: str = '', pending_reviews=0, submitted=0) -> tuple:
    """(label, tone) of the status pill; an ended exam says whether answers still wait for grading."""
    if state == 'finished':
        if pending_reviews:
            return 'پایان‌یافته (در انتظار تصحیح)', 'grey'
        if submitted:
            return 'پایان‌یافته، تصحیح شده', 'green'
        return 'پایان‌یافته', 'grey'
    tab = {key: (tab_label, tone) for key, tab_label, tone in STATE_TABS}.get(state, ('', 'grey'))
    if state == 'scheduled' and label and label not in ('برنامه‌ریزی شده', 'برنامه‌ریزی‌شده'):
        return label, tab[1]  # «تأیید شده» / «زمان‌بندی انتشار»: approved, not visible to students yet
    return tab[0] or label, tab[1]


def present(row, *, state, primary, preview_url, report_url, menu, code):
    """Fill in what the list template shows for one exam (row keeps its other keys)."""
    row['state'] = state
    row['pill_label'], row['pill_tone'] = pill(state, row.get('base_label', ''), row.get('pending_reviews') or 0,
                                               row.get('submitted') or 0)
    row['primary'] = primary  # {'label', 'url' | 'approve': {...data}, 'tone': blue|amber|solid|grey}
    row['preview_url'] = preview_url
    row['report_url'] = report_url
    row['menu'] = [item for item in menu if item]  # {'label', 'icon', 'url' | 'post', 'danger', 'confirm'}
    row['code'] = code
    assigned, started = row.get('assigned') or 0, row.get('started') or 0
    row['progress'] = min(100, round(started * 100 / assigned)) if state == 'running' and assigned else None
    return row


def listing(*, rows, page, counts, filters, courses, groups, teachers=None, managers=None, student_filter=False,
            **extra) -> dict:
    """Everything templates/partials/exam_list/list.html needs. teachers / managers: [{'value', 'label'}] (the
    «استاد» / «مدیر بخش» selects, hidden when empty); student_filter: show the «دانشجو» search box (people_filters)."""
    return {
        'rows': rows, 'page': page, 'total': page.paginator.count if page else len(rows),
        'tabs': tabs(counts, filters['status']), **filters,
        'courses': courses, 'groups': groups, 'teachers': teachers or [], 'managers': managers or [],
        'student_filter': student_filter,
        'date_ranges': DATE_RANGES, 'sorts': SORTS,
        'filtered': bool(filters['query'] or filters['course'] or filters['group'] or filters['date']
                         or filters['teacher'] or filters.get('manager') or filters.get('student')
                         or filters['status'] != 'all'),
        **extra,
    }
