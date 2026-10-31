"""The teacher's question bank page: the question list with its filters, the counts and the other tabs.

Filtering, counting and paging happen in the database, and nothing here runs for the other teacher pages.
"""
from django.core.paginator import Paginator

from .views import (
    QUESTION_DIFFICULTY_LABELS,
    QUESTION_STRUCTURE_LABELS,
    QUESTION_TYPE_LABELS,
    _query_without_page,
    _teacher_question_rows,
    _teacher_question_sets,
    _teacher_question_tags,
    erd_row,
    erd_rows,
    erd_table_columns,
)

PAGE_SIZE = 20
VIEWS = ('all', 'banks', 'drafts', 'shared', 'archive', 'tags')
TYPE_ALIASES = {'single': ('single', 'multiple_choice'), 'essay': ('essay', 'descriptive')}
STATUS_SQL = (
    "CASE WHEN COALESCE(TRIM(q.text), '') = '' THEN 'needs_review' "
    "WHEN COALESCE(q.is_published, false) = true THEN 'active' ELSE 'draft' END"
)
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
    }


def _like(text: str) -> str:
    escaped = text.lower().replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
    return f'%{escaped}%'


def _where(teacher_id, filters) -> tuple:
    clauses, params = ['q.teacher_id = %s'], [teacher_id]
    if filters['q']:
        clauses.append("(LOWER(COALESCE(q.text, '')) LIKE %s ESCAPE '\\' OR LOWER(COALESCE(c.title, '')) LIKE %s ESCAPE '\\')")
        params += [_like(filters['q'])] * 2
    if filters['status'] != 'all':
        clauses.append(f'{STATUS_SQL} = %s')
        params.append(filters['status'])
    if filters['type'] != 'all':
        types = TYPE_ALIASES.get(filters['type'], (filters['type'],))
        clauses.append(f"q.type IN ({', '.join(['%s'] * len(types))})")
        params += list(types)
    if filters['difficulty'] != 'all':
        clauses.append('q.difficulty = %s')
        params.append(filters['difficulty'])
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


def question_page(request, teacher_id):
    """(page of question rows, Paginator page) for the filtered list, fetched with LIMIT/OFFSET."""
    where, params = _where(teacher_id, _filters(request))
    joins = 'FROM questions q LEFT JOIN courses c ON c.id = q.course_id'
    total = int((erd_row(f'SELECT COUNT(*) AS n {joins} WHERE {where}', params) or {}).get('n') or 0)
    page = Paginator(range(total), PAGE_SIZE).get_page(request.GET.get('page'))
    structure = 'q.structure' if 'structure' in erd_table_columns('questions') else "'independent' AS structure"
    rows = erd_rows(
        f"""
        SELECT q.id, q.text, q.type, q.difficulty, {structure}, COALESCE(c.title, '-') AS course, {STATUS_SQL} AS status_key
        {joins}
        WHERE {where}
        ORDER BY q.text, q.id
        LIMIT {PAGE_SIZE} OFFSET {(page.number - 1) * PAGE_SIZE}
        """,
        params,
    ) if total else []
    return [_row(row) for row in rows], page


def question_stats(teacher_id) -> dict:
    row = erd_row(
        f"""
        SELECT COUNT(*) AS total,
               SUM(CASE WHEN {STATUS_SQL} = 'active' THEN 1 ELSE 0 END) AS active,
               SUM(CASE WHEN {STATUS_SQL} = 'draft' THEN 1 ELSE 0 END) AS draft,
               SUM(CASE WHEN {STATUS_SQL} = 'needs_review' THEN 1 ELSE 0 END) AS needs_review,
               COUNT(DISTINCT q.course_id) AS banks
        FROM questions q
        WHERE q.teacher_id = %s
        """,
        [teacher_id],
    ) or {}
    return {key: int(row.get(key) or 0) for key in ('total', 'active', 'draft', 'needs_review', 'banks')}


def question_bank_context(request, teacher_id) -> dict:
    view = request.GET.get('view') if request.GET.get('view') in VIEWS else 'all'
    questions, page = question_page(request, teacher_id)
    all_questions = _teacher_question_rows(teacher_id)
    return {
        'questions': questions,
        'question_page': page,
        'question_page_query': _query_without_page(request),
        'question_stats': question_stats(teacher_id),
        'question_view': view,
        'question_filters': _filters(request),
        'question_banks': _teacher_question_sets(teacher_id, all_questions),
        'question_tags': _teacher_question_tags(all_questions),
        'question_drafts': [q for q in all_questions if q['status_key'] == 'draft'][:10],
        'shared_questions': [q for q in all_questions if q['status_key'] == 'active'][:10],
        'archived_questions': all_questions[-8:],
    }
