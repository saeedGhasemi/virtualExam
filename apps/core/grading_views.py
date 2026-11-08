"""Manual grading of essay and unmatched short answers, and access-checked streaming of student answer files.

A teacher may grade an answer when they designed the exam or own the question. Every query carries that
condition, so a changed id in the URL answers 404 instead of exposing another teacher's students.
"""
import json
import logging
import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.http import FileResponse, Http404, HttpResponse, StreamingHttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone

from .rich_text import clean_delta, delta_to_html
from .uploads import CONTENT_TYPES, private_path
from .views import (
    _essay_view,
    _notify_if_result_released,
    _sx_answer_files,
    _sx_answer_value,
    _sx_float,
    _media_kind,
    _sx_json,
    _sx_question_media,
    _teacher_modern_context,
    erd_execute,
    erd_has_column,
    erd_profile_for_user,
    erd_role_required,
    erd_row,
    erd_rows,
)

logger = logging.getLogger(__name__)

PAGE_SIZE = 20
FEEDBACK_MAX = 2000
# Short answers matching none of the teacher's accepted answers are sent here by grade_attempt too;
# without them the attempt could never finish grading.
MANUAL_GRADING_TYPES = ('essay', 'descriptive', 'media_response', 'short_answer')
GRADING_FILTERS = {'pending': 'در انتظار تصحیح', 'graded': 'تصحیح‌شده', 'all': 'همه'}

# Base of every grading query: manually graded answers of submitted attempts that this teacher may grade: the exam's
# or the question's owner, or a teacher the wizard named «همکار تصحیح» of the exam. Takes the teacher id three times
# (grader_params).
_SCOPED_FROM = f"""
    FROM attempt_answers aa
    JOIN exam_attempts ea ON ea.id = aa.attempt_id
    JOIN exams e ON e.id = ea.exam_id
    JOIN questions q ON q.id = aa.question_id
    JOIN profiles p ON p.id = ea.student_id
    LEFT JOIN exam_questions eq ON eq.exam_id = e.id AND eq.question_id = q.id
    WHERE q.type IN ({', '.join(f"'{kind}'" for kind in MANUAL_GRADING_TYPES)})
      AND ea.submitted_at IS NOT NULL
      AND (e.teacher_id = %s OR q.teacher_id = %s
           OR e.id IN (SELECT es.exam_id FROM exam_staff es WHERE es.teacher_id = %s AND es.role = 'co_grader'))
"""


def _first_grade_sql():
    return 'aa.first_grade' if erd_has_column('attempt_answers', 'first_grade') else 'NULL AS first_grade'


def _blind_name(answer_id):
    """«تصحیح ناشناس»: a stable anonymous label instead of the student's name."""
    return f'دانشجوی ناشناس #{str(answer_id).replace("-", "")[:6].upper()}'


def grader_params(teacher_id) -> list:
    return [teacher_id, teacher_id, teacher_id]


def _filter_sql(status):
    if status == 'pending':
        return ' AND COALESCE(aa.needs_manual_grading, false) = true'
    if status == 'graded':
        return ' AND aa.graded_at IS NOT NULL'
    return ''


@erd_role_required('teacher')
def teacher_reviews(request):
    """List of essay and short answers to grade (replaces the former static sample page)."""
    teacher_id = request.erd_profile_id
    status = request.GET.get('status') if request.GET.get('status') in GRADING_FILTERS else 'pending'
    params = grader_params(teacher_id)
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
               e.title AS exam_title, p.full_name AS student_name, q.text AS question_text, q.scoring_settings,
               {_first_grade_sql()}, COALESCE(eq.points, q.default_points, 1) AS max_points
        {_SCOPED_FROM}{_filter_sql(status)}
        ORDER BY ea.submitted_at, aa.id
        LIMIT {PAGE_SIZE} OFFSET {(page.number - 1) * PAGE_SIZE}
        """,
        params,
    ) if total else []
    for row in rows:
        row['id'] = str(row['id'])
        essay = (_sx_json(row.get('scoring_settings'), {}) or {}).get('essay') or {}
        if essay.get('blind_grading'):
            row['student_name'] = _blind_name(row['id'])
        first = _sx_json(row.get('first_grade'), None)
        row['awaiting_second'] = bool(essay.get('second_grader') and isinstance(first, dict) and row.get('needs_manual_grading'))
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
               q.type AS question_type, q.accepted_answers, q.rubric, q.scoring_settings, q.question_media, COALESCE(eq.points, q.default_points, 1) AS max_points,
               e.correction_instructions AS exam_correction_instructions, e.rubric_template AS exam_rubric_template,
               e.settings_enforced AS exam_settings_enforced, {_first_grade_sql()}
        {_SCOPED_FROM} AND aa.id = %s
        """,
        [*grader_params(teacher_id), str(answer_id)],
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
    was_graded = bool((erd_row('SELECT is_graded FROM exam_attempts WHERE id = %s', [attempt_id]) or {}).get('is_graded'))
    erd_execute(
        """
        UPDATE exam_attempts
        SET score = %s, is_graded = %s,
            status = CASE WHEN %s AND status = 'submitted' THEN 'graded' ELSE status END
        WHERE id = %s
        """,
        [max(_sx_float(totals.get('score'), 0), 0), done, done, attempt_id],
    )
    if done and not was_graded:
        _notify_if_result_released(attempt_id)


@erd_role_required('teacher')
def teacher_grading_detail(request, answer_id):
    teacher_id = request.erd_profile_id
    row = _grading_answer(teacher_id, answer_id)
    from .teacher_preferences import grading_rules

    rules = grading_rules(teacher_id)  # the grading teacher's «تصحیح و بازخورد» settings
    # Criteria without a positive «نمره» cannot be scored (their limit would be 0, and a rubric of such criteria only
    # would make every grade 0); they are left out, and a rubric with none left falls back to a single score.
    rubric = [item for item in (_sx_json(row.get('rubric'), []) or [])
              if isinstance(item, dict) and item.get('criterion') and (_decimal(item.get('points')) or Decimal(0)) > 0]
    if not rules['use_rubric']:  # «نحوه تصحیح سؤالات تشریحی: دستی»: one score for the answer
        rubric = []
    max_points = _decimal(row.get('max_points')) or Decimal(0)
    published = erd_has_column('exams', 'results_published_at') and bool((erd_row(
        'SELECT e.results_published_at FROM exam_attempts ea JOIN exams e ON e.id = ea.exam_id WHERE ea.id = %s',
        [row['attempt_id']]) or {}).get('results_published_at'))
    locked = rules['lock_after_publish'] and published and bool(row.get('graded_at'))  # «قفل کردن نمرات پس از انتشار»
    if request.method == 'POST' and locked:
        messages.error(request, 'نتایج این آزمون منتشر شده و نمره‌ها طبق تنظیمات شما قفل است؛ برای تغییر، ابتدا «قفل کردن نمرات پس از انتشار» را خاموش کنید.')
        return redirect('core:teacher_grading_detail', answer_id=row['id'])
    if request.method == 'POST':
        post = request.POST
        if not rules['feedback']:  # «ارائه بازخورد کتبی» off: no box, and an earlier feedback is kept as it was
            post = request.POST.copy()
            post['feedback'] = row.get('grader_feedback') or ''
        awarded, scores, feedback, errors = _grade_from_post(post, rubric, max_points)
        if rules['integer_scores']:  # «دقت نمره‌دهی: عدد صحیح»
            awarded = awarded.quantize(Decimal('1'), rounding=ROUND_HALF_UP)
        essay_settings = (_sx_json(row.get('scoring_settings'), {}) or {}).get('essay') or {}
        first = _sx_json(row.get('first_grade'), None)
        first = first if isinstance(first, dict) else None
        double = bool(essay_settings.get('second_grader')) and erd_has_column('attempt_answers', 'first_grade') and not row.get('graded_at')
        if not errors and double and (first is None or str(first.get('by')) == str(teacher_id)):
            # «نمره‌دهنده دوم»: the first grade is kept apart and the answer stays in the queue for another grader.
            grade = {'by': str(teacher_id), 'by_name': (erd_profile_for_user(request.user) or {}).get('full_name') or '',
                     'points': float(awarded), 'scores': scores, 'feedback': feedback, 'at': timezone.now().isoformat()}
            erd_execute('UPDATE attempt_answers SET first_grade = %s, needs_manual_grading = true WHERE id = %s',
                        [json.dumps(grade, ensure_ascii=False), row['id']])
            messages.success(request, f'نمره‌ی اول ({awarded.normalize()} از {max_points.normalize()}) ثبت شد؛ پاسخ تا نمره‌دهی مستقلِ مصحح دوم در صف می‌ماند و نمره‌ی نهایی میانگین دو نمره خواهد بود.')
            return redirect('core:teacher_reviews')
        if not errors and double and first:
            # Second, independent grade: the final points are the mean of both.
            second = awarded
            awarded = ((Decimal(str(first.get('points') or 0)) + second) / 2).quantize(Decimal('0.01'))
            if rules['integer_scores']:
                awarded = awarded.quantize(Decimal('1'), rounding=ROUND_HALF_UP)
            scores = {'first': first.get('scores') or [], 'second': scores, 'first_points': first.get('points'), 'second_points': float(second)}
            feedback = '\n\n'.join(part for part in (first.get('feedback') or '', feedback) if part)
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
            messages.success(request, f'نمره {awarded.normalize()} از {max_points.normalize()} ثبت شد.'
                             + (' (میانگین نمره‌ی دو مصحح)' if double and first else ''))
            # Next pending answer, skipping those this teacher already graded first (they wait for someone else).
            following = next((item for item in erd_rows(
                f"SELECT aa.id, {_first_grade_sql()} {_SCOPED_FROM} AND COALESCE(aa.needs_manual_grading, false) = true ORDER BY ea.submitted_at, aa.id LIMIT 50",
                grader_params(teacher_id),
            ) if str((_sx_json(item.get('first_grade'), None) or {}).get('by', '')) != str(teacher_id)), None)
            if request.POST.get('next') and following:
                return redirect('core:teacher_grading_detail', answer_id=following['id'])
            return redirect('core:teacher_reviews')
    answer_id = str(row['id'])
    files = [{**item, 'url': reverse('core:attempt_answer_file', args=[str(row['attempt_id']), item['id']])}
             for item in _sx_answer_files(row.get('answer_files'))]
    first_grade = _sx_json(row.get('first_grade'), None)
    own_first = isinstance(first_grade, dict) and str(first_grade.get('by')) == str(teacher_id) and not row.get('graded_at')
    # The first grader reopening their (not yet final) grade sees their own scores; otherwise the final rubric scores.
    previous_scores = first_grade.get('scores') if own_first else _sx_json(row.get('rubric_scores'), [])
    previous = {item.get('criterion'): item.get('score') for item in (previous_scores if isinstance(previous_scores, list) else []) if isinstance(item, dict)}
    scoring_settings = _sx_json(row.get('scoring_settings'), {}) or {}
    essay = _essay_view(scoring_settings)
    first = _sx_json(row.get('first_grade'), None)
    first = first if isinstance(first, dict) else None
    blind = essay.get('blind_grading')
    if blind:
        row['student_name'] = _blind_name(row['id'])
    # Audio/video questions: the grader hears/sees the same stimulus (and transcript) the student answered.
    media_settings = (scoring_settings.get('media_response') or {}) if isinstance(scoring_settings, dict) else {}
    raw_answer = _sx_json(row.get('answer'), {})
    delta = raw_answer.get('delta') if isinstance(raw_answer, dict) else None
    # A rich essay answer (written with the exam page's editor): safe HTML built from its Quill Delta.
    answer_html = delta_to_html(clean_delta(delta)) if isinstance(delta, dict) else ''
    return render(request, 'teacher/modern.html', _teacher_modern_context(
        request, 'grading_detail',
        grading=row, grading_answer_id=answer_id, grading_answer_text=_sx_answer_value(row.get('answer')),
        grading_answer_html=answer_html,
        grading_blind=blind,
        # Double marking: the first grader sees and may change their own grade; the second grader only learns that a
        # first grade exists (independent marking). Once final, both grades are shown.
        grading_double=bool(essay.get('second_grader')),
        grading_first=first,
        grading_first_mine=bool(first and str(first.get('by')) == str(teacher_id)),
        grading_files=files, grading_essay=essay, grading_max_points=max_points.normalize(),
        grading_is_short_answer=row.get('question_type') == 'short_answer',
        grading_is_media=row.get('question_type') == 'media_response',
        grading_media=_sx_question_media(row.get('question_media')),
        grading_transcript=media_settings.get('transcript') or '',
        grading_attachment=media_settings.get('attachment') or None,
        grading_accepted_answers=[
            {'answer': item.get('answer'), 'media': item.get('media') or '', 'media_kind': _media_kind(item.get('media') or '')}
            for item in (_sx_json(row.get('accepted_answers'), []) or [])
            if isinstance(item, dict) and item.get('answer')
        ],
        grading_rubric=[{**item, 'index': index, 'previous': previous.get(item.get('criterion'), '')} for index, item in enumerate(rubric)],
        # The single score field: the final grade, or the first grader's own (not yet final) grade when they reopen it.
        grading_score_value=(f"{_sx_float(row.get('points_awarded'), 0):g}" if row.get('graded_at')
                             else f"{_sx_float(first.get('points'), 0):g}" if own_first and first else ''),
        grading_rules=rules, grading_locked=locked, grading_score_step='1' if rules['integer_scores'] else '0.25',
        grading_rubric_total=sum((_decimal(item.get('points')) or Decimal(0) for item in rubric), Decimal(0)).normalize(),
    ))


# Audio answers recorded in Chrome/Firefox are WebM/Ogg containers; serve them as audio so <audio> plays them.
AUDIO_CONTENT_TYPES = {'webm': 'audio/webm', 'ogg': 'audio/ogg', 'mp4': 'audio/mp4'}
# iPhone .mov (H.264 in QuickTime) plays in <video> in Chrome/Edge/Firefox when served as MP4; «video/quicktime» does not.
VIDEO_CONTENT_TYPES = {'mov': 'video/mp4'}
_RANGE_RE = re.compile(r'bytes=(\d*)-(\d*)$')
RANGE_CHUNK = 256 * 1024


def _ranged_file_response(request, path, content_type):
    """A single «Range: bytes=a-b» answer (206) so players can seek and Safari plays audio/video; else the file."""
    size = path.stat().st_size
    match = _RANGE_RE.match((request.headers.get('Range') or '').strip())
    if not match or not size or (not match.group(1) and not match.group(2)):
        return None
    if match.group(1):
        start = int(match.group(1))
        end = min(int(match.group(2)), size - 1) if match.group(2) else size - 1
    else:  # «bytes=-N»: the last N bytes
        start, end = max(size - int(match.group(2)), 0), size - 1
    if start >= size or end < start:
        response = HttpResponse(status=416)
        response['Content-Range'] = f'bytes */{size}'
        return response
    length = end - start + 1

    def chunks():
        # Streamed: players open videos with «bytes=0-», which must not read a 100MB answer into memory.
        with open(path, 'rb') as handle:
            handle.seek(start)
            left = length
            while left > 0:
                block = handle.read(min(RANGE_CHUNK, left))
                if not block:
                    break
                left -= len(block)
                yield block

    response = StreamingHttpResponse(chunks(), status=206, content_type=content_type)
    response['Content-Range'] = f'bytes {start}-{end}/{size}'
    response['Content-Length'] = str(length)
    return response


@login_required
def attempt_answer_file(request, attempt_id, file_id):
    """Stream one answer file to the attempt's student or to a teacher who may grade it (owner or co-grader)."""
    profile = erd_profile_for_user(request.user)
    if not profile:
        raise Http404
    rows = erd_rows(
        """
        SELECT aa.answer_files, ea.student_id, e.teacher_id AS exam_teacher, q.teacher_id AS question_teacher,
               EXISTS (SELECT 1 FROM exam_staff es WHERE es.exam_id = e.id AND es.teacher_id = %s AND es.role = 'co_grader') AS is_co_grader
        FROM attempt_answers aa
        JOIN exam_attempts ea ON ea.id = aa.attempt_id
        JOIN exams e ON e.id = ea.exam_id
        JOIN questions q ON q.id = aa.question_id
        WHERE aa.attempt_id = %s
        """,
        [str(profile['id']), str(attempt_id)],
    )
    viewer = str(profile['id'])
    for row in rows:
        allowed = viewer in {str(row['student_id']), str(row['exam_teacher']), str(row['question_teacher'])} or bool(row.get('is_co_grader'))
        for item in _sx_answer_files(row.get('answer_files')):
            if item['id'] != file_id:
                continue
            path = private_path(item['path'])
            if not allowed or not path:
                raise Http404
            extension = item.get('ext')
            content_type = ((AUDIO_CONTENT_TYPES.get(extension) if item.get('kind') == 'audio'
                             else VIDEO_CONTENT_TYPES.get(extension) if item.get('kind') == 'video' else None)
                            or CONTENT_TYPES.get(extension, 'application/octet-stream'))
            response = None if item.get('kind') == 'file' else _ranged_file_response(request, path, content_type)
            if response is None:
                response = FileResponse(
                    open(path, 'rb'), content_type=content_type,
                    as_attachment=item.get('kind') == 'file', filename=item.get('name') or path.name,
                )
            if item.get('kind') != 'file':
                response['Accept-Ranges'] = 'bytes'
            response['X-Content-Type-Options'] = 'nosniff'
            response['Cache-Control'] = 'private, no-store'
            return response
    raise Http404
