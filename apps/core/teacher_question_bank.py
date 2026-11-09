"""The teacher's question bank page: the question list with its filters, the counts and the other tabs.

Filtering, counting and paging happen in the database, and nothing here runs for the other teacher pages.
Who sees what (bank_owner):
- teacher: the questions they own (+ the «اشتراکی» tab: co-teachers' shared questions of their courses);
- academic manager: their own questions and those of their managed units (subunits included): a question whose course
  belongs to one, or whose author is a teacher of one (ManagerScope), with a «طراح» column;
- system admin («مدیر کل»): every question in the system (owner None).
Managers and the admin may open, edit (saved under the original author) and archive what they see
(views.question_for_editor), as a department head / site manager can in common LMSs.
"""
import json
import uuid
from datetime import timedelta

from urllib.parse import urlencode

from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.http import Http404
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone

from .views import (
    QUESTION_DIFFICULTY_LABELS,
    QUESTION_STRUCTURE_LABELS,
    QUESTION_TYPE_LABELS,
    _query_without_page,
    erd_execute,
    erd_role_required,
    erd_row,
    erd_rows,
    erd_table_columns,
    log_activity,
)

PAGE_SIZE = 20
VIEWS = ('all', 'banks', 'drafts', 'shared', 'archive', 'tags')
TYPE_ALIASES = {'single': ('single', 'multiple_choice'), 'essay': ('essay', 'descriptive')}
STATUS_SQL = (
    "CASE WHEN COALESCE(TRIM(q.text), '') = '' THEN 'needs_review' "
    "WHEN COALESCE(q.is_published, false) = true THEN 'active' ELSE 'draft' END"
)
NO_COURSE = 'none'
# The tags column holds «a, b، c»; this wraps it as ",a,b,c," so one tag matches exactly.
TAGS_SQL = "(',' || LOWER(REPLACE(REPLACE(REPLACE(COALESCE(q.tags, ''), '،', ','), ', ', ','), ' ,', ',')) || ',')"
STATUS_LABELS = {
    'active': ('فعال', 'is-ok'),
    'draft': ('پیش‌نویس', 'is-muted'),
    'needs_review': ('نیازمند بازبینی', 'is-warn'),
}


def _filters(request) -> dict:
    return {
        'q': (request.GET.get('q') or '').strip()[:200],
        'status': request.GET.get('status') if request.GET.get('status') in STATUS_LABELS else 'all',
        'type': (request.GET.get('type') or 'all')[:40],
        'difficulty': request.GET.get('difficulty') if request.GET.get('difficulty') in QUESTION_DIFFICULTY_LABELS else 'all',
        'course': (request.GET.get('course') or '').strip()[:64],
        'subject': (request.GET.get('subject') or '').strip()[:160],
        'tag': (request.GET.get('tag') or '').strip()[:80],
    }


class ManagerScope:
    """An academic manager's bank: their own questions + those of their managed units (unit ids include subunits)."""

    def __init__(self, profile_id, unit_ids):
        self.profile_id = profile_id
        self.unit_ids = sorted(str(unit_id) for unit_id in unit_ids or ())

    def __str__(self):  # drafts and other per-user keys stay the manager's own
        return str(self.profile_id)

    def sql(self) -> tuple:
        if not self.unit_ids:
            return 'q.teacher_id = %s', [self.profile_id]
        units = ', '.join(['%s'] * len(self.unit_ids))
        return (
            f'(q.teacher_id = %s OR (q.teacher_id IS NOT NULL AND ('
            f'q.course_id IN (SELECT id FROM courses WHERE org_unit_id IN ({units})) '
            f'OR q.teacher_id IN (SELECT user_id FROM teacher_profiles WHERE org_unit_id IN ({units})))))',
            [self.profile_id, *self.unit_ids, *self.unit_ids],
        )


def _owner(owner_id) -> tuple:
    """SQL condition + params limiting questions to one owner (or a ManagerScope); None (system admin) = every question."""
    if isinstance(owner_id, ManagerScope):
        return owner_id.sql()
    return ('q.teacher_id = %s', [owner_id]) if owner_id else ('q.teacher_id IS NOT NULL', [])


def bank_owner(request):
    """Whose questions the bank lists: None (all) for the system admin, a ManagerScope for an academic manager,
    otherwise the signed-in profile."""
    role = getattr(request, 'erd_role', None)
    if role == 'admin':
        return None
    if role == 'academic_manager':
        from .views import _erd_managed_unit_ids
        return ManagerScope(request.erd_profile_id, _erd_managed_unit_ids(request))
    return request.erd_profile_id


def _like(text: str) -> str:
    escaped = text.lower().replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
    return f'%{escaped}%'


def _where(teacher_id, filters, archived=False) -> tuple:
    owner_sql, params = _owner(teacher_id)
    clauses = [owner_sql, f"q.archived_at IS {'NOT ' if archived else ''}NULL"]
    if filters['q']:
        clauses.append(
            "(LOWER(COALESCE(q.text, '')) LIKE %s ESCAPE '\\' OR LOWER(COALESCE(c.title, '')) LIKE %s ESCAPE '\\'"
            " OR LOWER(CAST(q.id AS TEXT)) LIKE %s ESCAPE '\\')"
        )
        params += [_like(filters['q'])] * 2 + [_like(filters['q'])[1:]]  # the code shown in the list is the id's start
    if filters['status'] == 'unpublished':
        clauses.append(f"{STATUS_SQL} != 'active'")
    elif filters['status'] != 'all':
        clauses.append(f'{STATUS_SQL} = %s')
        params.append(filters['status'])
    if filters['type'] != 'all':
        types = TYPE_ALIASES.get(filters['type'], (filters['type'],))
        clauses.append(f"q.type IN ({', '.join(['%s'] * len(types))})")
        params += list(types)
    if filters['difficulty'] != 'all':
        clauses.append('q.difficulty = %s')
        params.append(filters['difficulty'])
    if filters['course'] == NO_COURSE:
        clauses.append('q.course_id IS NULL')
    elif filters['course']:
        clauses.append('q.course_id = %s')
        params.append(filters['course'])
    if filters['subject']:
        clauses.append("TRIM(COALESCE(q.subject, '')) = %s")
        params.append(filters['subject'])
    if filters['tag']:
        clauses.append(f"{TAGS_SQL} LIKE %s ESCAPE '\\'")
        params.append(f"%,{_like(filters['tag'])[1:-1]},%")
    return ' AND '.join(clauses), params


def _row(row) -> dict:
    """A list row with its display labels, from stored values only."""
    kind = row.get('type') or 'single'
    difficulty = row.get('difficulty') or 'medium'
    structure = row.get('structure') or 'independent'
    status_label, status_class = STATUS_LABELS[row['status_key']]
    return {
        **row,
        'code': str(row['id'])[:8],
        'type_label': QUESTION_TYPE_LABELS.get(kind, kind),
        'difficulty_label': QUESTION_DIFFICULTY_LABELS.get(difficulty, difficulty),
        'difficulty_class': 'is-ok' if difficulty == 'easy' else 'is-danger' if difficulty == 'hard' else 'is-muted',
        'structure_label': QUESTION_STRUCTURE_LABELS.get(structure, structure),
        'status_label': status_label,
        'status_class': status_class,
    }


def question_page(request, teacher_id, archived=False, status=None):
    """(page of question rows, Paginator page) for the filtered list, fetched with LIMIT/OFFSET."""
    filters = _filters(request)
    if status:
        filters['status'] = status
    where, params = _where(teacher_id, filters, archived)
    joins = 'FROM questions q LEFT JOIN courses c ON c.id = q.course_id LEFT JOIN profiles p ON p.id = q.teacher_id'
    total = int((erd_row(f'SELECT COUNT(*) AS n {joins} WHERE {where}', params) or {}).get('n') or 0)
    page = Paginator(range(total), PAGE_SIZE).get_page(request.GET.get('page'))
    structure = 'q.structure' if 'structure' in erd_table_columns('questions') else "'independent' AS structure"
    rows = erd_rows(
        f"""
        SELECT q.id, q.text, q.type, q.difficulty, {structure}, COALESCE(c.title, '-') AS course, {STATUS_SQL} AS status_key,
               q.updated_at, q.archived_at, q.shared_at, COALESCE(p.full_name, '-') AS author,
               (SELECT COUNT(*) FROM exam_questions eq JOIN exams e ON e.id = eq.exam_id
                WHERE eq.question_id = q.id AND COALESCE(e.is_cancelled, false) = false) AS usage_count,
               (SELECT e.title FROM exam_questions eq JOIN exams e ON e.id = eq.exam_id
                WHERE eq.question_id = q.id AND COALESCE(e.is_cancelled, false) = false
                ORDER BY e.start_at DESC NULLS LAST LIMIT 1) AS last_exam_title,
               (SELECT MAX(e.start_at) FROM exam_questions eq JOIN exams e ON e.id = eq.exam_id
                WHERE eq.question_id = q.id AND COALESCE(e.is_cancelled, false) = false) AS last_exam_at
        {joins}
        WHERE {where}
        ORDER BY {'q.archived_at DESC, ' if archived else ''}q.text, q.id
        LIMIT {PAGE_SIZE} OFFSET {(page.number - 1) * PAGE_SIZE}
        """,
        params,
    ) if total else []
    return [_row(row) for row in rows], page


def question_stats(teacher_id) -> dict:
    row = erd_row(
        f"""
        SELECT SUM(CASE WHEN q.archived_at IS NULL THEN 1 ELSE 0 END) AS total,
               SUM(CASE WHEN q.archived_at IS NULL AND {STATUS_SQL} = 'active' THEN 1 ELSE 0 END) AS active,
               SUM(CASE WHEN q.archived_at IS NULL AND {STATUS_SQL} = 'draft' THEN 1 ELSE 0 END) AS draft,
               SUM(CASE WHEN q.archived_at IS NULL AND {STATUS_SQL} = 'needs_review' THEN 1 ELSE 0 END) AS needs_review,
               SUM(CASE WHEN q.archived_at IS NOT NULL THEN 1 ELSE 0 END) AS archived,
               COUNT(DISTINCT CASE WHEN q.archived_at IS NULL THEN q.course_id END)
                 + MAX(CASE WHEN q.archived_at IS NULL AND q.course_id IS NULL THEN 1 ELSE 0 END) AS banks
        FROM questions q
        WHERE {_owner(teacher_id)[0]}
        """,
        _owner(teacher_id)[1],
    ) or {}
    return {key: int(row.get(key) or 0) for key in ('total', 'active', 'draft', 'needs_review', 'archived', 'banks')}


def autosaved_drafts(teacher_id, owner_id=False) -> list:
    """Builder forms autosaved but never saved as a question (new questions and unsaved edits), newest first.

    Drafts are always the signed-in user's own; owner_id None (system admin) lets an edit draft be of anyone's question."""
    owner_sql, owner_params = _owner(teacher_id if owner_id is False else owner_id)
    prefix = f'question_draft.{teacher_id}.'
    rows = erd_rows('SELECT key, value FROM system_settings WHERE key LIKE %s', [f'{prefix}%'])
    drafts = []
    for row in rows:
        target = row['key'][len(prefix):]
        try:
            data = row['value'] if isinstance(row['value'], dict) else json.loads(row['value'] or '{}')
        except (TypeError, ValueError):
            continue
        text = ((data.get('fields') or {}).get('text') or [''])[0].strip()
        if target.startswith('new-'):
            kind = target[4:]
            create = reverse('core:teacher_question_create')
            drafts.append({
                'title': text, 'type_label': QUESTION_TYPE_LABELS.get(kind, kind), 'kind': 'جدید', 'saved_at': data.get('saved_at') or '',
                'resume_url': f'{create}?type={kind}&draft=restore', 'discard_url': f'{create}?type={kind}&draft=discard',
            })
            continue
        question = erd_row(f'SELECT q.id, q.text, q.type FROM questions q WHERE q.id = %s AND {owner_sql}', [target, *owner_params])
        if question:
            edit = reverse('core:teacher_question_edit', args=[question['id']])
            drafts.append({
                'title': text or question['text'], 'type_label': QUESTION_TYPE_LABELS.get(question['type'], question['type']),
                'kind': 'ویرایش ذخیره‌نشده', 'saved_at': data.get('saved_at') or '',
                'resume_url': f'{edit}?draft=restore', 'discard_url': f'{edit}?draft=discard',
            })
    return sorted(drafts, key=lambda item: item['saved_at'], reverse=True)


def stale_draft_count(teacher_id, days=14) -> int:
    """Unpublished questions not saved for `days` days (only rows saved since times were recorded)."""
    row = erd_row(
        f"""
        SELECT COUNT(*) AS n FROM questions q
        WHERE {_owner(teacher_id)[0]} AND q.archived_at IS NULL AND {STATUS_SQL} != 'active' AND q.updated_at < %s
        """,
        [*_owner(teacher_id)[1], timezone.now() - timedelta(days=days)],
    ) or {}
    return int(row.get('n') or 0)


def _course_title(course_id) -> str:
    if not course_id:
        return ''
    if course_id == NO_COURSE:
        return 'بدون درس'
    return (erd_row('SELECT title FROM courses WHERE id = %s', [course_id]) or {}).get('title') or ''


def course_banks(teacher_id) -> list:
    """One bank per course of the teacher's questions (questions without a course form their own bank)."""
    rows = erd_rows(
        f"""
        SELECT q.course_id, COALESCE(c.title, 'بدون درس') AS title,
               SUM(CASE WHEN q.archived_at IS NULL AND {STATUS_SQL} = 'active' THEN 1 ELSE 0 END) AS active,
               SUM(CASE WHEN q.archived_at IS NULL AND {STATUS_SQL} != 'active' THEN 1 ELSE 0 END) AS draft,
               SUM(CASE WHEN q.archived_at IS NOT NULL THEN 1 ELSE 0 END) AS archived,
               SUM(CASE WHEN q.shared_at IS NOT NULL AND q.archived_at IS NULL THEN 1 ELSE 0 END) AS shared,
               MAX(q.updated_at) AS last_update
        FROM questions q LEFT JOIN courses c ON c.id = q.course_id
        WHERE {_owner(teacher_id)[0]}
        GROUP BY q.course_id, c.title
        ORDER BY COUNT(*) DESC, c.title
        """,
        _owner(teacher_id)[1],
    )
    url = reverse('core:teacher_questions')
    return [
        {
            **row,
            'count': int(row['active'] or 0) + int(row['draft'] or 0),
            'url': f"{url}?{urlencode({'course': row['course_id'] or NO_COURSE})}",
        }
        for row in rows
    ]


def categories(teacher_id) -> dict:
    """Subjects («مبحث») and tags of the teacher's questions, with how many questions carry each."""
    url = reverse('core:teacher_questions')
    owner_sql, owner_params = _owner(teacher_id)
    subjects = erd_rows(
        f"""
        SELECT TRIM(q.subject) AS title, COUNT(*) AS count
        FROM questions q
        WHERE {owner_sql} AND q.archived_at IS NULL AND COALESCE(TRIM(q.subject), '') != ''
        GROUP BY TRIM(q.subject)
        ORDER BY COUNT(*) DESC, TRIM(q.subject)
        """,
        owner_params,
    )
    tag_counts = {}
    for row in erd_rows(f"SELECT q.tags FROM questions q WHERE {owner_sql} AND q.archived_at IS NULL AND COALESCE(q.tags, '') != ''", owner_params):
        for tag in {part.strip() for part in str(row['tags']).replace('،', ',').split(',') if part.strip()}:
            tag_counts[tag] = tag_counts.get(tag, 0) + 1
    palette = ['is-red', 'is-orange', 'is-blue', 'is-purple', 'is-green', 'is-yellow']
    tags = sorted(tag_counts.items(), key=lambda item: (-item[1], item[0]))
    return {
        'subjects': [{**row, 'url': f"{url}?{urlencode({'subject': row['title']})}"} for row in subjects],
        'tags': [
            {'title': tag, 'count': count, 'class': palette[index % len(palette)], 'url': f"{url}?{urlencode({'tag': tag})}"}
            for index, (tag, count) in enumerate(tags)
        ],
    }


def recent_questions(teacher_id, limit=5) -> list:
    """The teacher's most recently saved questions (only rows saved since save times were recorded)."""
    rows = erd_rows(
        f"""
        SELECT q.id, q.text, q.type, q.difficulty, q.structure, COALESCE(c.title, '-') AS course,
               {STATUS_SQL} AS status_key, q.updated_at, q.archived_at, COALESCE(p.full_name, '-') AS author
        FROM questions q LEFT JOIN courses c ON c.id = q.course_id LEFT JOIN profiles p ON p.id = q.teacher_id
        WHERE {_owner(teacher_id)[0]} AND q.updated_at IS NOT NULL
        ORDER BY q.updated_at DESC
        LIMIT {int(limit)}
        """,
        _owner(teacher_id)[1],
    )
    return [_row(row) for row in rows]


# Courses the teacher teaches (own groups or co-taught ones): sharing never reaches beyond them.
TEACHER_COURSES_SQL = """
    SELECT sg.course_id FROM student_groups sg
    LEFT JOIN group_teachers gt ON gt.group_id = sg.id
    WHERE (sg.teacher_id = %s OR gt.teacher_id = %s) AND sg.course_id IS NOT NULL
"""
SHARED_WITH_SQL = f"""
    q.shared_at IS NOT NULL AND q.archived_at IS NULL AND q.teacher_id != %s
    AND q.course_id IN ({TEACHER_COURSES_SQL})
"""


def shared_page(request, teacher_id):
    """Other teachers' shared questions of the courses this teacher teaches, newest share first, paged.
    teacher_id None (system admin): every shared question; a ManagerScope: the shared questions within it."""
    if isinstance(teacher_id, ManagerScope):
        scope_sql, params = teacher_id.sql()
        shared_sql = f'q.shared_at IS NOT NULL AND q.archived_at IS NULL AND {scope_sql}'
    elif teacher_id:
        shared_sql, params = SHARED_WITH_SQL, [teacher_id, teacher_id, teacher_id]
    else:
        shared_sql, params = 'q.shared_at IS NOT NULL AND q.archived_at IS NULL', []
    total = int((erd_row(f'SELECT COUNT(*) AS n FROM questions q WHERE {shared_sql}', params) or {}).get('n') or 0)
    page = Paginator(range(total), PAGE_SIZE).get_page(request.GET.get('page'))
    rows = erd_rows(
        f"""
        SELECT q.id, q.text, q.type, q.difficulty, q.structure, COALESCE(c.title, '-') AS course,
               {STATUS_SQL} AS status_key, q.shared_at, COALESCE(p.full_name, '-') AS author
        FROM questions q
        LEFT JOIN courses c ON c.id = q.course_id
        LEFT JOIN profiles p ON p.id = q.teacher_id
        WHERE {shared_sql}
        ORDER BY q.shared_at DESC, q.id
        LIMIT {PAGE_SIZE} OFFSET {(page.number - 1) * PAGE_SIZE}
        """,
        params,
    ) if total else []
    return [_row(row) for row in rows], page


def question_bank_context(request, teacher_id) -> dict:
    owner = bank_owner(request)
    view = request.GET.get('view') if request.GET.get('view') in VIEWS else 'all'
    if view == 'shared':
        questions, page = shared_page(request, owner)
    else:
        questions, page = question_page(
            request, owner, archived=view == 'archive', status='unpublished' if view == 'drafts' else None,
        )
    filters = _filters(request)
    banks = course_banks(owner) if view in ('all', 'banks') else []
    return {
        'questions': questions,
        'question_page': page,
        'question_page_query': _query_without_page(request),
        'question_stats': question_stats(owner),
        # admin / manager banks hold other teachers' questions too: «طراح» column + their own heading
        'question_scope_all': owner is None or isinstance(owner, ManagerScope),
        'question_scope_title': (
            'بانک سؤال سامانه (سؤال‌های همه اساتید)' if owner is None
            else 'بانک سؤال واحدهای زیرمجموعه (سؤال‌های من و اساتید واحدها)' if isinstance(owner, ManagerScope)
            else 'بانک سؤال من'
        ),
        'question_can_share': getattr(request, 'erd_role', None) == 'teacher',  # share/copy views are teacher-only
        'question_view': view,
        'question_filters': filters,
        'question_type_base': '?' + urlencode({key: value for key, value in filters.items() if key != 'type' and value}) + '&type=',
        'question_filter_course': _course_title(filters['course']),
        'question_banks': banks,
        'question_categories': categories(owner) if view == 'tags' else {},
        'recent_questions': recent_questions(owner) if view == 'all' else [],
        'autosaved_drafts': autosaved_drafts(teacher_id, owner) if view == 'drafts' else [],
        'stale_drafts': stale_draft_count(owner) if view == 'drafts' else 0,
    }


@erd_role_required('teacher', 'academic_manager', 'admin')
def teacher_question_archive(request, question_id):
    """«آرشیو» / «بازیابی» one of the teacher's questions (POST only; another teacher's question is a 404)."""
    if request.method != 'POST':
        return redirect('core:teacher_questions')
    archive = request.POST.get('action') != 'restore'
    owner_sql, owner_params = _owner(bank_owner(request))
    with transaction.atomic():
        row = erd_row(f'SELECT q.id, q.text FROM questions q WHERE q.id = %s AND {owner_sql}', [str(question_id), *owner_params])
        if not row:
            raise Http404('سؤال پیدا نشد.')
        now = timezone.now()
        erd_execute(
            'UPDATE questions SET archived_at = %s, updated_at = %s WHERE id = %s',
            [now if archive else None, now, row['id']],
        )
    log_activity(request.user, 'question_archived' if archive else 'question_restored',
                 'سؤال آرشیو شد.' if archive else 'سؤال از آرشیو بازیابی شد.', request, {'question_id': str(row['id'])})
    messages.success(request, 'سؤال آرشیو شد و در آزمون‌های جدید قابل انتخاب نیست.' if archive else 'سؤال از آرشیو بازیابی شد.')
    return redirect(f"{reverse('core:teacher_questions')}{'?view=archive' if not archive else ''}")


@erd_role_required('teacher')
def teacher_question_share(request, question_id):
    """Share one's published question with the other teachers of its course, or stop sharing it (POST only)."""
    if request.method != 'POST':
        return redirect('core:teacher_questions')
    share = request.POST.get('action') != 'unshare'
    row = erd_row(
        f'SELECT q.id, q.course_id, {STATUS_SQL} AS status_key FROM questions q WHERE q.id = %s AND q.teacher_id = %s',
        [str(question_id), request.erd_profile_id],
    )
    if not row:
        raise Http404('سؤال پیدا نشد.')
    if share and (not row['course_id'] or row['status_key'] != 'active'):
        messages.error(request, 'فقط سؤال منتشرشده‌ای که درس دارد قابل اشتراک با اساتید همان درس است.')
        return redirect('core:teacher_questions')
    now = timezone.now()
    erd_execute(
        'UPDATE questions SET shared_at = %s, updated_at = %s WHERE id = %s AND teacher_id = %s',
        [now if share else None, now, row['id'], request.erd_profile_id],
    )
    log_activity(request.user, 'question_shared' if share else 'question_unshared',
                 'سؤال با اساتید هم‌درس به اشتراک گذاشته شد.' if share else 'اشتراک سؤال لغو شد.', request, {'question_id': str(row['id'])})
    messages.success(request, 'سؤال برای اساتید هم‌درس به اشتراک گذاشته شد.' if share else 'اشتراک سؤال لغو شد.')
    return redirect('core:teacher_questions')


# Copied as the new owner's unpublished, unshared draft; everything else is the shared question's content.
COPY_RESET = {'id', 'teacher_id', 'is_published', 'shared_at', 'archived_at', 'updated_at', 'legacy_erd_id'}


@erd_role_required('teacher')
def teacher_shared_question_copy(request, question_id):
    """«افزودن به بانک من»: copy a question shared with this teacher's courses into their bank as a draft."""
    if request.method != 'POST':
        return redirect(f"{reverse('core:teacher_questions')}?view=shared")
    teacher_id = request.erd_profile_id
    source = erd_row(f'SELECT q.id FROM questions q WHERE q.id = %s AND {SHARED_WITH_SQL}', [str(question_id), teacher_id, teacher_id, teacher_id])
    if not source:
        raise Http404('سؤال پیدا نشد.')
    columns = [column for column in erd_table_columns('questions') if column not in COPY_RESET]
    new_id = str(uuid.uuid4())
    erd_execute(
        f"""
        INSERT INTO questions (id, teacher_id, is_published, updated_at, {', '.join(columns)})
        SELECT %s, %s, false, %s, {', '.join(columns)} FROM questions WHERE id = %s
        """,
        [new_id, teacher_id, timezone.now(), source['id']],
    )
    log_activity(request.user, 'shared_question_copied', 'سؤال اشتراکی به بانک استاد افزوده شد.', request,
                 {'question_id': new_id, 'source_question_id': str(source['id'])})
    messages.success(request, 'یک نسخه از سؤال به‌صورت پیش‌نویس به بانک شما افزوده شد.')
    return redirect('core:teacher_question_edit', question_id=new_id)
