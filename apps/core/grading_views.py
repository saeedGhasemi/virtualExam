"""Manual grading of essay answers and access-checked streaming of student answer files.

A teacher may grade an answer when they designed the exam or own the question. Every query carries that
condition, so a changed id in the URL answers 404 instead of exposing another teacher's students.
"""
import json
import logging
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.http import FileResponse, Http404
from django.shortcuts import redirect, render
from django.urls import reverse

from .uploads import CONTENT_TYPES, private_path
from .views import (
    _essay_view,
    _sx_answer_files,
    _sx_answer_value,
    _sx_float,
    _sx_json,
    _teacher_modern_context,
    erd_execute,
    erd_profile_for_user,
    erd_role_required,
    erd_row,
    erd_rows,
)

logger = logging.getLogger(__name__)

PAGE_SIZE = 20
FEEDBACK_MAX = 2000
ESSAY_TYPES = ('essay', 'descriptive', 'media_response')
GRADING_FILTERS = {'pending': 'در انتظار تصحیح', 'graded': 'تصحیح‌شده', 'all': 'همه'}

# Base of every grading query: essay answers of submitted attempts that this teacher may grade.
_SCOPED_FROM = """
    FROM attempt_answers aa
    JOIN exam_attempts ea ON ea.id = aa.attempt_id
    JOIN exams e ON e.id = ea.exam_id
    JOIN questions q ON q.id = aa.question_id
    JOIN profiles p ON p.id = ea.student_id
    LEFT JOIN exam_questions eq ON eq.exam_id = e.id AND eq.question_id = q.id
    WHERE q.type IN ('essay', 'descriptive', 'media_response')
      AND ea.submitted_at IS NOT NULL
      AND (e.teacher_id = %s OR q.teacher_id = %s)
"""


def _filter_sql(status):
    if status == 'pending':
        return ' AND COALESCE(aa.needs_manual_grading, false) = true'
    if status == 'graded':
        return ' AND aa.graded_at IS NOT NULL'
    return ''


@erd_role_required('teacher')
def teacher_reviews(request):
    """List of essay answers to grade (replaces the former static sample page)."""
    teacher_id = request.erd_profile_id
    status = request.GET.get('status') if request.GET.get('status') in GRADING_FILTERS else 'pending'
    params = [teacher_id, teacher_id]
    counts = erd_row(
        f"""
        SELECT COUNT(*) AS total,
               SUM(CASE WHEN COALESCE(aa.needs_manual_grading, false) THEN 1 ELSE 0 END) AS pending,
               SUM(CASE WHEN aa.graded_at IS NOT NULL THEN 1 ELSE 0 END) AS graded
        {_SCOPED_FROM}
        """,
        params,
    ) or {}
    total = int(counts.get({'pending': 'pending', 'graded': 'graded'}.get(status, 'total')) or 0)
    paginator = Paginator(range(total), PAGE_SIZE)
    page = paginator.get_page(request.GET.get('page'))
    rows = erd_rows(
        f"""
        SELECT aa.id, aa.points_awarded, aa.needs_manual_grading, aa.graded_at, ea.submitted_at,
               e.title AS exam_title, p.full_name AS student_name, q.text AS question_text,
               COALESCE(eq.points, q.default_points) AS max_points
        {_SCOPED_FROM}{_filter_sql(status)}
        ORDER BY ea.submitted_at, aa.id
        LIMIT {PAGE_SIZE} OFFSET {(page.number - 1) * PAGE_SIZE}
        """,
        params,
    ) if total else []
    for row in rows:
        row['id'] = str(row['id'])
    return render(request, 'teacher/modern.html', _teacher_modern_context(
        request, 'reviews',
        grading_rows=rows, grading_page=page, grading_status=status, grading_filters=GRADING_FILTERS,
        grading_counts={key: int(counts.get(key) or 0) for key in ('total', 'pending', 'graded')},
    ))


def _grading_answer(teacher_id, answer_id):
    row = erd_row(
        f"""
        SELECT aa.id, aa.attempt_id, aa.answer, aa.answer_files, aa.points_awarded, aa.needs_manual_grading,
               aa.rubric_scores, aa.grader_feedback, aa.graded_at, ea.submitted_at, ea.status AS attempt_status,
               e.title AS exam_title, p.full_name AS student_name, q.id AS question_id, q.text AS question_text,
               q.rubric, q.scoring_settings, COALESCE(eq.points, q.default_points) AS max_points
        {_SCOPED_FROM} AND aa.id = %s
        """,
        [teacher_id, teacher_id, str(answer_id)],
    )
    if not row:
        raise Http404('پاسخ پیدا نشد.')
    return row


def _decimal(value):
    try:
        number = Decimal(str(value).strip().translate(str.maketrans('۰۱۲۳۴۵۶۷۸۹٫', '0123456789.')))
    except (InvalidOperation, AttributeError):
        return None
    return number if number.is_finite() else None


def _grade_from_post(post, rubric, max_points):
    """Returns (points awarded, per-criterion scores, feedback, errors)."""
    errors, scores = [], []
    if rubric:
        rubric_total = Decimal(0)
        for index, item in enumerate(rubric):
            limit = _decimal(item.get('points')) or Decimal(0)
            score = _decimal(post.get(f'score_{index}'))
            if score is None or score < 0 or score > limit:
                errors.append(f'نمره معیار «{item.get("criterion")}» باید بین ۰ و {limit.normalize()} باشد.')
                score = Decimal(0)
            scores.append({'criterion': item.get('criterion'), 'score': float(score), 'max': float(limit)})
            rubric_total += limit
        earned = sum((Decimal(str(item['score'])) for item in scores), Decimal(0))
        # The rubric total and the exam's points for this question may differ; scale to the exam points.
        awarded = (earned / rubric_total * max_points) if rubric_total else Decimal(0)
    else:
        awarded = _decimal(post.get('score'))
        if awarded is None or awarded < 0 or awarded > max_points:
            errors.append(f'نمره باید بین ۰ و {max_points.normalize()} باشد.')
            awarded = Decimal(0)
    feedback = (post.get('feedback') or '').strip()
    if len(feedback) > FEEDBACK_MAX:
        errors.append(f'بازخورد حداکثر {FEEDBACK_MAX} نویسه است.')
    return awarded.quantize(Decimal('0.01')), scores, feedback, errors


def _refresh_attempt_score(attempt_id):
    """Recompute the attempt total after a manual grade; finish grading when nothing is pending."""
    totals = erd_row(
        """
        SELECT COALESCE(SUM(aa.points_awarded), 0) AS score,
               SUM(CASE WHEN COALESCE(aa.needs_manual_grading, false) THEN 1 ELSE 0 END) AS pending
        FROM attempt_answers aa
        JOIN exam_attempts ea ON ea.id = aa.attempt_id
        JOIN exam_questions eq ON eq.exam_id = ea.exam_id AND eq.question_id = aa.question_id
        WHERE aa.attempt_id = %s
        """,
        [attempt_id],
    )
    done = not int(totals.get('pending') or 0)
    erd_execute(
        """
        UPDATE exam_attempts
        SET score = %s, is_graded = %s,
            status = CASE WHEN %s AND status = 'submitted' THEN 'graded' ELSE status END
        WHERE id = %s
        """,
        [max(_sx_float(totals.get('score'), 0), 0), done, done, attempt_id],
    )


@erd_role_required('teacher')
def teacher_grading_detail(request, answer_id):
    teacher_id = request.erd_profile_id
    row = _grading_answer(teacher_id, answer_id)
    rubric = [item for item in (_sx_json(row.get('rubric'), []) or []) if isinstance(item, dict) and item.get('criterion')]
    max_points = _decimal(row.get('max_points')) or Decimal(0)
    if request.method == 'POST':
        awarded, scores, feedback, errors = _grade_from_post(request.POST, rubric, max_points)
        if errors:
            for error in errors:
                messages.error(request, error)
        else:
            with transaction.atomic():
                erd_execute(
                    """
                    UPDATE attempt_answers
                    SET points_awarded = %s, needs_manual_grading = false, rubric_scores = %s,
                        grader_feedback = %s, graded_by = %s, graded_at = now()
                    WHERE id = %s
                    """,
                    [awarded, json.dumps(scores, ensure_ascii=False), feedback, teacher_id, row['id']],
                )
                _refresh_attempt_score(row['attempt_id'])
            messages.success(request, f'نمره {awarded.normalize()} از {max_points.normalize()} ثبت شد.')
            following = erd_row(
                f"SELECT aa.id {_SCOPED_FROM} AND COALESCE(aa.needs_manual_grading, false) = true ORDER BY ea.submitted_at, aa.id LIMIT 1",
                [teacher_id, teacher_id],
            )
            if request.POST.get('next') and following:
                return redirect('core:teacher_grading_detail', answer_id=following['id'])
            return redirect('core:teacher_reviews')
    answer_id = str(row['id'])
    files = [{**item, 'url': reverse('core:attempt_answer_file', args=[str(row['attempt_id']), item['id']])}
             for item in _sx_answer_files(row.get('answer_files'))]
    previous = {item.get('criterion'): item.get('score') for item in (_sx_json(row.get('rubric_scores'), []) or []) if isinstance(item, dict)}
    essay = _essay_view(_sx_json(row.get('scoring_settings'), {}) or {})
    return render(request, 'teacher/modern.html', _teacher_modern_context(
        request, 'grading_detail',
        grading=row, grading_answer_id=answer_id, grading_answer_text=_sx_answer_value(row.get('answer')),
        grading_files=files, grading_essay=essay, grading_max_points=max_points.normalize(),
        grading_rubric=[{**item, 'index': index, 'previous': previous.get(item.get('criterion'), '')} for index, item in enumerate(rubric)],
        grading_rubric_total=sum((_decimal(item.get('points')) or Decimal(0) for item in rubric), Decimal(0)).normalize(),
    ))


@login_required
def attempt_answer_file(request, attempt_id, file_id):
    """Stream one answer file to the attempt's student or to a teacher who may grade it."""
    profile = erd_profile_for_user(request.user)
    if not profile:
        raise Http404
    rows = erd_rows(
        """
        SELECT aa.answer_files, ea.student_id, e.teacher_id AS exam_teacher, q.teacher_id AS question_teacher
        FROM attempt_answers aa
        JOIN exam_attempts ea ON ea.id = aa.attempt_id
        JOIN exams e ON e.id = ea.exam_id
        JOIN questions q ON q.id = aa.question_id
        WHERE aa.attempt_id = %s
        """,
        [str(attempt_id)],
    )
    viewer = str(profile['id'])
    for row in rows:
        allowed = viewer in {str(row['student_id']), str(row['exam_teacher']), str(row['question_teacher'])}
        for item in _sx_answer_files(row.get('answer_files')):
            if item['id'] != file_id:
                continue
            path = private_path(item['path'])
            if not allowed or not path:
                raise Http404
            response = FileResponse(
                open(path, 'rb'), content_type=CONTENT_TYPES.get(item.get('ext'), 'application/octet-stream'),
                as_attachment=item.get('kind') == 'file', filename=item.get('name') or path.name,
            )
            response['X-Content-Type-Options'] = 'nosniff'
            response['Cache-Control'] = 'private, no-store'
            return response
    raise Http404
