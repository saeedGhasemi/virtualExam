"""«فهرست اطلاعات کاربران»: a printable directory (like the institution's Excel sheets) of students, teachers and managers.

Academic managers see the teachers and students of their own org units (same scope rules as «کاربران»); the
system admin sees everyone and also the «مدیران» tab (system admins + academic managers). Every tab can be
filtered, its columns chosen, printed (A4 landscape) or downloaded as an Excel file with the same rows/columns.
"""
from io import BytesIO

from django.http import HttpResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone

from .views import (
    _erd_is_admin_request,
    _erd_manager_scope_cte,
    _erd_manager_visible_org_units,
    _erd_student_scope_condition,
    _erd_teacher_scope_condition,
    _matches_query,
    erd_role_required,
    erd_rows,
)

ROW_LIMIT = 3000

TAB_LABELS = {'students': 'دانشجویان', 'teachers': 'اساتید', 'managers': 'مدیران'}
STATUS_LABELS = {'active': 'فعال', 'inactive': 'غیرفعال', 'blocked': 'مسدود', 'pending': 'در انتظار تأیید', 'rejected': 'رد شده'}
STATUS_TONES = {'active': 'ok', 'pending': 'wait', 'inactive': 'off', 'blocked': 'bad', 'rejected': 'bad'}
ACADEMIC_LABELS = {'active': 'مشغول به تحصیل', 'leave': 'مرخصی', 'graduated': 'فارغ‌التحصیل', 'inactive': 'غیرفعال'}
ACADEMIC_TONES = {'active': 'ok', 'leave': 'wait', 'graduated': 'info', 'inactive': 'off'}
GENDER_LABELS = {'male': 'مرد', 'female': 'زن'}

# key, header, shown by default, cell style (ltr = codes / emails / phones)
COLUMNS = {
    'teachers': [
        ('first_name', 'نام', True, 'name'),
        ('last_name', 'نام خانوادگی', True, 'name'),
        ('academic_rank', 'مرتبه علمی', True, ''),
        ('department', 'گروه آموزشی', True, ''),
        ('faculty', 'دانشکده', False, ''),
        ('specialty', 'تخصص', False, ''),
        ('degree', 'مدرک تحصیلی', False, ''),
        ('email', 'ایمیل', True, 'ltr latin'),
        ('phone', 'تلفن همراه', True, 'ltr'),
        ('landline', 'تلفن ثابت', True, 'ltr'),
        ('national_id', 'کد ملی', True, 'ltr'),
        ('personnel_code', 'کد پرسنلی', True, 'ltr'),
        ('cooperation', 'نوع همکاری', True, ''),
        ('gender', 'جنسیت', False, ''),
        ('username', 'نام کاربری', False, 'ltr latin'),
        ('status', 'وضعیت حساب', True, 'status'),
    ],
    'managers': [
        ('first_name', 'نام', True, 'name'),
        ('last_name', 'نام خانوادگی', True, 'name'),
        ('role', 'نوع مدیر', True, ''),
        ('title', 'سمت', True, ''),
        ('unit', 'واحد / حوزه مسئولیت', True, ''),
        ('email', 'ایمیل', True, 'ltr latin'),
        ('phone', 'تلفن همراه', True, 'ltr'),
        ('national_id', 'کد ملی', True, 'ltr'),
        ('personnel_code', 'کد پرسنلی', True, 'ltr'),
        ('gender', 'جنسیت', False, ''),
        ('username', 'نام کاربری', False, 'ltr latin'),
        ('status', 'وضعیت حساب', True, 'status'),
    ],
    'students': [
        ('first_name', 'نام', True, 'name'),
        ('last_name', 'نام خانوادگی', True, 'name'),
        ('student_number', 'شماره دانشجویی', True, 'ltr'),
        ('field_of_study', 'رشته', True, ''),
        ('degree', 'مقطع', True, ''),
        ('entry_year', 'ورودی', True, ''),
        ('department', 'گروه آموزشی', True, ''),
        ('faculty', 'دانشکده', False, ''),
        ('admission_type', 'نوع پذیرش', False, ''),
        ('email', 'ایمیل', True, 'ltr latin'),
        ('phone', 'تلفن همراه', True, 'ltr'),
        ('national_id', 'کد ملی', True, 'ltr'),
        ('academic_status', 'وضعیت تحصیلی', True, 'status'),
        ('gender', 'جنسیت', False, ''),
        ('username', 'نام کاربری', False, 'ltr latin'),
        ('status', 'وضعیت حساب', False, 'status'),
    ],
}


def _split_name(row):
    first = (row.get('first_name') or '').strip()
    last = (row.get('last_name') or '').strip()
    if not first and not last:
        parts = (row.get('full_name') or '').split(maxsplit=1)
        first = parts[0] if parts else ''
        last = parts[1] if len(parts) > 1 else ''
    return first, last


class _Units:
    """Org-unit lookups for the units the viewer may see (path labels, subtree filter)."""

    def __init__(self, request):
        self.units = _erd_manager_visible_org_units(request)
        self.by_id = {str(unit['id']): unit for unit in self.units}

    def path(self, unit_id):
        chain, seen = {}, set()
        current = self.by_id.get(str(unit_id or ''))
        while current and str(current['id']) not in seen:
            seen.add(str(current['id']))
            chain.setdefault(current['type'], current['name'])
            current = self.by_id.get(str(current.get('parent_id') or ''))
        return {
            'faculty': chain.get('faculty') or '',
            'department': chain.get('department') or chain.get('educational_group') or chain.get('group') or '',
            'label': ' ← '.join(p for p in [chain.get('faculty'), chain.get('department') or chain.get('educational_group') or chain.get('group')] if p)
            or chain.get('university') or '',
        }

    def subtree(self, unit_id):
        if not unit_id or unit_id not in self.by_id:
            return None
        ids, frontier = {unit_id}, [unit_id]
        while frontier:
            parent = frontier.pop()
            for unit in self.units:
                uid = str(unit['id'])
                if str(unit.get('parent_id') or '') == parent and uid not in ids:
                    ids.add(uid)
                    frontier.append(uid)
        return ids


def _scoped_rows(request, sql_select, scope_condition):
    is_admin = _erd_is_admin_request(request)
    sql = ('' if is_admin else _erd_manager_scope_cte()) + sql_select.format(
        scope='1=1' if is_admin else scope_condition,
    ) + f' LIMIT {ROW_LIMIT + 1}'
    return erd_rows(sql, [] if is_admin else [request.erd_profile_id])


def _teachers(request, units):
    rows = _scoped_rows(request, """
        SELECT p.id, p.full_name, p.first_name, p.last_name, p.username, p.email, p.phone, p.national_id,
               p.gender, p.status, p.identifier, tp.personnel_code, tp.department AS tp_department, tp.specialty,
               tp.academic_rank, tp.org_unit_id, tp.cooperation_type, tp.employment_type, tp.degree, tp.landline,
               tp.approval_status
        FROM teacher_profiles tp
        JOIN profiles p ON p.id = tp.user_id
        WHERE p.deleted_at IS NULL AND {scope}
        ORDER BY COALESCE(NULLIF(p.last_name, ''), p.full_name), p.first_name
    """, _erd_teacher_scope_condition())
    out = []
    for row in rows:
        first, last = _split_name(row)
        path = units.path(row.get('org_unit_id'))
        status = row.get('status') or 'active'
        if status == 'active' and (row.get('approval_status') or 'approved') == 'pending':
            status = 'pending'
        cooperation = ' · '.join(dict.fromkeys(v for v in [row.get('cooperation_type'), row.get('employment_type')] if v))
        out.append({
            'id': row['id'], 'kind': 'teacher', 'unit_id': str(row.get('org_unit_id') or ''), 'status_key': status,
            'first_name': first, 'last_name': last, 'academic_rank': row.get('academic_rank') or '',
            'department': path['department'] or row.get('tp_department') or '', 'faculty': path['faculty'],
            'specialty': row.get('specialty') or '', 'degree': row.get('degree') or '',
            'email': row.get('email') or '', 'phone': row.get('phone') or '', 'landline': row.get('landline') or '',
            'national_id': row.get('national_id') or '', 'personnel_code': row.get('personnel_code') or row.get('identifier') or '',
            'cooperation': cooperation, 'gender': GENDER_LABELS.get(row.get('gender') or '', ''),
            'username': row.get('username') or '',
            'status': (STATUS_LABELS.get(status, status), STATUS_TONES.get(status, 'off')),
        })
    return out


def _students(request, units):
    rows = _scoped_rows(request, """
        SELECT p.id, p.full_name, p.first_name, p.last_name, p.username, p.email, p.phone, p.national_id,
               p.gender, p.status, p.identifier, sp.student_number, sp.field_of_study, sp.degree, sp.semester, sp.entry_year,
               sp.academic_status, sp.department AS sp_department, sp.org_unit_id, sp.admission_type
        FROM student_profiles sp
        JOIN profiles p ON p.id = sp.user_id
        WHERE p.deleted_at IS NULL AND {scope}
        ORDER BY COALESCE(NULLIF(p.last_name, ''), p.full_name), p.first_name
    """, _erd_student_scope_condition())
    out = []
    for row in rows:
        first, last = _split_name(row)
        path = units.path(row.get('org_unit_id'))
        status = row.get('status') or 'active'
        academic = row.get('academic_status') or 'active'
        entry_year = str(row.get('entry_year') or '').strip()
        if not entry_year:
            for token in str(row.get('semester') or '').replace('/', '-').split('-'):
                if token.isdigit() and len(token) == 4:
                    entry_year = token
                    break
        out.append({
            'id': row['id'], 'kind': 'student', 'unit_id': str(row.get('org_unit_id') or ''), 'status_key': status,
            'first_name': first, 'last_name': last, 'student_number': row.get('student_number') or row.get('identifier') or '',
            'field_of_study': row.get('field_of_study') or '', 'degree': row.get('degree') or '',
            'entry_year': entry_year, 'department': path['department'] or row.get('sp_department') or '',
            'faculty': path['faculty'], 'admission_type': row.get('admission_type') or '',
            'email': row.get('email') or '', 'phone': row.get('phone') or '',
            'national_id': row.get('national_id') or '',
            'academic_status': (ACADEMIC_LABELS.get(academic, academic), ACADEMIC_TONES.get(academic, 'off')),
            'gender': GENDER_LABELS.get(row.get('gender') or '', ''), 'username': row.get('username') or '',
            'status': (STATUS_LABELS.get(status, status), STATUS_TONES.get(status, 'off')),
        })
    return out


def _managers(request, units):
    rows = erd_rows(f"""
        SELECT p.id, p.full_name, p.first_name, p.last_name, p.username, p.email, p.phone, p.national_id,
               p.gender, p.status, ur.role, amp.personnel_code, amp.department, amp.responsibility_area,
               amp.title AS manager_title, ap.title AS admin_title, p.identifier
        FROM user_roles ur
        JOIN profiles p ON p.id = ur.user_id
        LEFT JOIN academic_manager_profiles amp ON amp.user_id = p.id
        LEFT JOIN admin_profiles ap ON ap.user_id = p.id
        WHERE ur.role IN ('admin', 'academic_manager') AND p.deleted_at IS NULL
        ORDER BY CASE ur.role WHEN 'admin' THEN 0 ELSE 1 END, COALESCE(NULLIF(p.last_name, ''), p.full_name), p.first_name
        LIMIT {ROW_LIMIT + 1}
    """)
    scopes = {}
    for scope in erd_rows('SELECT manager_id, org_unit_id FROM academic_manager_scopes'):
        scopes.setdefault(str(scope['manager_id']), []).append(str(scope['org_unit_id']))
    out, seen = [], set()
    for row in rows:
        is_admin = row.get('role') == 'admin'
        key = (str(row['id']), row.get('role'))
        if key in seen:
            continue
        seen.add(key)
        first, last = _split_name(row)
        status = row.get('status') or 'active'
        scope_ids = scopes.get(str(row['id']), [])
        if is_admin:
            unit = 'سراسر سیستم'
        else:
            unit = '، '.join(filter(None, (units.path(uid)['label'] for uid in scope_ids))) \
                or row.get('responsibility_area') or row.get('department') or ''
        out.append({
            'id': row['id'], 'kind': 'manager', 'unit_ids': scope_ids, 'is_admin': is_admin, 'status_key': status,
            'first_name': first, 'last_name': last, 'role': 'مدیر سیستم' if is_admin else 'مدیر آموزشی',
            'title': (row.get('admin_title') if is_admin else row.get('manager_title')) or '',
            'unit': unit, 'email': row.get('email') or '', 'phone': row.get('phone') or '',
            'national_id': row.get('national_id') or '',
            'personnel_code': row.get('personnel_code') or ('' if is_admin else row.get('identifier') or ''),
            'gender': GENDER_LABELS.get(row.get('gender') or '', ''), 'username': row.get('username') or '',
            'status': (STATUS_LABELS.get(status, status), STATUS_TONES.get(status, 'off')),
        })
    return out


def _cell_text(value):
    return value[0] if isinstance(value, tuple) else str(value or '')


def _filter(rows, *, query, status, unit_ids, role):
    keep = []
    for row in rows:
        if status and row['status_key'] != status:
            continue
        if role and row.get('is_admin') != (role == 'admin'):
            continue
        if unit_ids is not None:
            row_units = row.get('unit_ids') if 'unit_ids' in row else [row.get('unit_id')]
            if not any(uid in unit_ids for uid in row_units or []):
                continue
        if query and not _matches_query(query, *(_cell_text(v) for k, v in row.items() if k not in {'id', 'kind'})):
            continue
        keep.append(row)
    return keep


def _export_xlsx(title, columns, rows):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = title[:31]
    sheet.sheet_view.rightToLeft = True
    thin = Side(style='thin', color='9AA8BF')
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    headers = ['ردیف'] + [label for _, label, _, _ in columns]
    sheet.append(headers)
    for cell in sheet[1]:
        cell.font = Font(bold=True, color='FFFFFF')
        cell.fill = PatternFill('solid', fgColor='315CFF')
        cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
        cell.border = border
    for index, row in enumerate(rows, start=1):
        values = [index]
        for key, _, _, _ in columns:
            text = _cell_text(row.get(key))
            values.append(f"'{text}" if text[:1] in ('=', '+', '-', '@') else text)
        sheet.append(values)
        for cell in sheet[sheet.max_row]:
            cell.border = border
            cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
            cell.number_format = '@'  # national ids / phones keep their leading zeros
    for position, header in enumerate(headers, start=1):
        width = max([len(header)] + [len(str(sheet.cell(r, position).value or '')) for r in range(2, sheet.max_row + 1)])
        sheet.column_dimensions[get_column_letter(position)].width = min(max(width + 4, 8), 42)
    sheet.row_dimensions[1].height = 26
    sheet.freeze_panes = 'A2'
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


@erd_role_required('academic_manager', 'admin')
def super_admin_user_directory(request):
    is_admin = _erd_is_admin_request(request)
    tabs = ['students', 'teachers', 'managers'] if is_admin else ['students', 'teachers']
    tab = request.GET.get('tab', 'students').strip()
    if tab not in tabs:
        tab = 'students'
    query = request.GET.get('q', '').strip()
    status = request.GET.get('status', '').strip()
    status = status if status in STATUS_LABELS else ''
    role = request.GET.get('role', '').strip() if tab == 'managers' else ''
    role = role if role in {'admin', 'academic_manager'} else ''
    unit = request.GET.get('unit', '').strip()

    units = _Units(request)
    unit_ids = units.subtree(unit)
    if unit_ids is None:
        unit = ''
    loaders = {'teachers': _teachers, 'managers': _managers, 'students': _students}
    all_rows = loaders[tab](request, units)
    truncated = len(all_rows) > ROW_LIMIT
    all_rows = all_rows[:ROW_LIMIT]
    rows = _filter(all_rows, query=query, status=status, unit_ids=unit_ids, role=role)
    columns = COLUMNS[tab]

    if request.GET.get('export') == 'xlsx':
        hidden = set(filter(None, request.GET.get('hide', '').split(',')))
        shown = [col for col in columns if col[0] not in hidden] or columns
        stamp = timezone.localtime().strftime('%Y%m%d-%H%M')
        response = HttpResponse(
            _export_xlsx(TAB_LABELS[tab], shown, rows),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
        response['Content-Disposition'] = f'attachment; filename="metaquizy-{tab}-{stamp}.xlsx"'
        return response

    table_rows = [{
        'id': row['id'], 'kind': row['kind'],
        'url': '' if row['kind'] == 'manager' and (row.get('is_admin') or not is_admin)
        else reverse('core:super_admin_user_profile', args=[row['kind'], row['id']]),
        'cells': [{
            'key': key, 'label': label, 'default': default, 'style': style,
            'text': _cell_text(row.get(key)),
            'tone': row[key][1] if isinstance(row.get(key), tuple) else '',
            # digits stay 0-9 in codes and in anything with Latin letters
            'latin': 'ltr' in style and (key in ('national_id', 'personnel_code', 'student_number')
                                         or any('a' <= ch.lower() <= 'z' for ch in _cell_text(row.get(key)))),
        } for key, label, default, style in columns],
    } for row in rows]

    unit_name = units.by_id.get(unit, {}).get('name', '') if unit else ''
    filter_notes = [note for note in [
        f'واحد: {unit_name}' if unit_name else '',
        f'نوع مدیر: {"مدیر سیستم" if role == "admin" else "مدیر آموزشی"}' if role else '',
        f'وضعیت: {STATUS_LABELS[status]}' if status else '',
        f'جست‌وجو: «{query}»' if query else '',
    ] if note]

    return render(request, 'super_admin/user_directory.html', {
        'tab': tab,
        'tab_label': TAB_LABELS[tab],
        'dir_key': tab,  # column choices are remembered per tab (localStorage mq-user-dir-cols-<tab>)
        'sheet_title': f'فهرست اطلاعات {TAB_LABELS[tab]}',
        'is_filtered': bool(query or unit or status or role),
        'tabs': [{'key': key, 'label': TAB_LABELS[key]} for key in tabs],
        'columns': [{'key': key, 'label': label, 'default': default, 'style': style} for key, label, default, style in columns],
        'rows': table_rows,
        'total_count': len(all_rows),
        'shown_count': len(table_rows),
        'active_count': sum(1 for row in rows if row['status_key'] == 'active'),
        'truncated': truncated,
        'row_limit': ROW_LIMIT,
        'query': query,
        'status_filter': status,
        'role_filter': role,
        'unit_filter': unit,
        'org_units': units.units,
        'status_options': list(STATUS_LABELS.items()),
        'filter_notes': filter_notes,
        'scope_label': 'همه‌ی واحدهای سامانه' if is_admin else 'واحدهای تحت مدیریت شما',
        'is_admin_viewer': is_admin,
        'printed_at': timezone.now(),
    })
