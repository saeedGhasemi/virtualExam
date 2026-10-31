"""The teacher's question bank page: the question list with its filters, the counts and the other tabs.

Filtering, counting and paging happen in the database, and nothing here runs for the other teacher pages.
"""
import json
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
    _teacher_question_rows,
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


def _like(text: str) -> str:
    escaped = text.lower().replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
    return f'%{escaped}%'


def _where(teacher_id, filters, archived=False) -> tuple:
    clauses = ['q.teacher_id = %s', f"q.archived_at IS {'NOT ' if archived else ''}NULL"]
    params = [teacher_id]
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
    joins = 'FROM questions q LEFT JOIN courses c ON c.id = q.course_id'
    total = int((erd_row(f'SELECT COUNT(*) AS n {joins} WHERE {where}', params) or {}).get('n') or 0)
    page = Paginator(range(total), PAGE_SIZE).get_page(request.GET.get('page'))
    structure = 'q.structure' if 'structure' in erd_table_columns('questions') else "'independent' AS structure"
    rows = erd_rows(
        f"""
        SELECT q.id, q.text, q.type, q.difficulty, {structure}, COALESCE(c.title, '-') AS course, {STATUS_SQL} AS status_key,
               q.updated_at, q.archived_at
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
               COUNT(DISTINCT CASE WHEN q.archived_at IS NULL THEN q.course_id END) AS banks
        FROM questions q
        WHERE q.teacher_id = %s
        """,
        [teacher_id],
    ) or {}
    return {key: int(row.get(key) or 0) for key in ('total', 'active', 'draft', 'needs_review', 'archived', 'banks')}


def autosaved_drafts(teacher_id) -> list:
    """Builder forms autosaved but never saved as a question (new questions and unsaved edits), newest first."""
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
        question = erd_row('SELECT id, text, type FROM questions WHERE id = %s AND teacher_id = %s', [target, teacher_id])
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
        WHERE q.teacher_id = %s AND q.archived_at IS NULL AND {STATUS_SQL} != 'active' AND q.updated_at < %s
        """,
        [teacher_id, timezone.now() - timedelta(days=days)],
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
        WHERE q.teacher_id = %s
        GROUP BY q.course_id, c.title
        ORDER BY COUNT(*) DESC, c.title
        """,
        [teacher_id],
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
    subjects = erd_rows(
        """
        SELECT TRIM(q.subject) AS title, COUNT(*) AS count
        FROM questions q
        WHERE q.teacher_id = %s AND q.archived_at IS NULL AND COALESCE(TRIM(q.subject), '') != ''
        GROUP BY TRIM(q.subject)
        ORDER BY COUNT(*) DESC, TRIM(q.subject)
        """,
        [teacher_id],
    )
    tag_counts = {}
    for row in erd_rows("SELECT q.tags FROM questions q WHERE q.teacher_id = %s AND q.archived_at IS NULL AND COALESCE(q.tags, '') != ''", [teacher_id]):
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
               {STATUS_SQL} AS status_key, q.updated_at, q.archived_at
        FROM questions q LEFT JOIN courses c ON c.id = q.course_id
        WHERE q.teacher_id = %s AND q.updated_at IS NOT NULL
        ORDER BY q.updated_at DESC
        LIMIT {int(limit)}
        """,
        [teacher_id],
    )
    return [_row(row) for row in rows]


def question_bank_context(request, teacher_id) -> dict:
    view = request.GET.get('view') if request.GET.get('view') in VIEWS else 'all'
    questions, page = question_page(
        request, teacher_id, archived=view == 'archive', status='unpublished' if view == 'drafts' else None,
    )
    all_questions = _teacher_question_rows(teacher_id) if view == 'shared' else []
    filters = _filters(request)
    banks = course_banks(teacher_id) if view in ('all', 'banks') else []
    return {
        'questions': questions,
        'question_page': page,
        'question_page_query': _query_without_page(request),
        'question_stats': question_stats(teacher_id),
        'question_view': view,
        'question_filters': filters,
        'question_type_base': '?' + urlencode({key: value for key, value in filters.items() if key != 'type' and value}) + '&type=',
        'question_filter_course': _course_title(filters['course']),
        'question_banks': banks,
        'question_categories': categories(teacher_id) if view == 'tags' else {},
        'recent_questions': recent_questions(teacher_id) if view == 'all' else [],
        'autosaved_drafts': autosaved_drafts(teacher_id) if view == 'drafts' else [],
        'stale_drafts': stale_draft_count(teacher_id) if view == 'drafts' else 0,
        'shared_questions': [q for q in all_questions if q['status_key'] == 'active'][:10],
    }


@erd_role_required('teacher')
def teacher_question_archive(request, question_id):
    """«آرشیو» / «بازیابی» one of the teacher's questions (POST only; another teacher's question is a 404)."""
    if request.method != 'POST':
        return redirect('core:teacher_questions')
    archive = request.POST.get('action') != 'restore'
    with transaction.atomic():
        row = erd_row(
            'SELECT id, text FROM questions WHERE id = %s AND teacher_id = %s', [str(question_id), request.erd_profile_id]
        )
        if not row:
            raise Http404('سؤال پیدا نشد.')
        now = timezone.now()
        erd_execute(
            'UPDATE questions SET archived_at = %s, updated_at = %s WHERE id = %s AND teacher_id = %s',
            [now if archive else None, now, row['id'], request.erd_profile_id],
        )
    log_activity(request.user, 'question_archived' if archive else 'question_restored',
                 'سؤال آرشیو شد.' if archive else 'سؤال از آرشیو بازیابی شد.', request, {'question_id': str(row['id'])})
    messages.success(request, 'سؤال آرشیو شد و در آزمون‌های جدید قابل انتخاب نیست.' if archive else 'سؤال از آرشیو بازیابی شد.')
    return redirect(f"{reverse('core:teacher_questions')}{'?view=archive' if not archive else ''}")
