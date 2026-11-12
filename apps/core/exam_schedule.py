"""Exam work that is due at a time rather than on a request:

- publish_due_exams(): «زمان‌بندی انتشار», an approved exam becomes visible to students once its publish time comes.
- finalize_expired_attempts(): an attempt whose time ran out without «پایان آزمون» (e.g. the browser was closed) is
  submitted with its saved answers when the exam's «ارسال خودکار در پایان زمان» is on, else closed as expired.
- release_due_results(): results are published when «خودکار پس از تصحیح کامل» finds every attempt graded, or when
  «مهلت نهایی انتشار نمرات» passes.

run_due_tasks() runs all three. It runs from ScheduledPublishMiddleware (at most once a minute per process, so no
extra service is needed) and from `manage.py publish_scheduled_exams` for a cron/systemd timer.
"""
import logging
import time

from django.utils import timezone

logger = logging.getLogger(__name__)
PUBLISH_CHECK_SECONDS = 60


def publish_due_exams(now=None) -> list:
    """Publish every approved, unpublished, uncancelled exam whose scheduled_publish_at has passed; returns them."""
    from .views import erd_datetime, erd_execute, erd_has_column, erd_rows

    if not erd_has_column('exams', 'scheduled_publish_at'):
        return []
    now = now or timezone.now()
    waiting = erd_rows(
        """
        SELECT id, title, scheduled_publish_at FROM exams
        WHERE lifecycle_status = 'approved' AND COALESCE(is_published, false) = false AND COALESCE(is_cancelled, false) = false
          AND scheduled_publish_at IS NOT NULL
        """
    )
    # Compared here, not in SQL: SQLite keeps these datetimes as text with differing UTC offsets.
    due = [exam for exam in waiting if (erd_datetime(exam['scheduled_publish_at']) or now) <= now]
    for exam in due:
        erd_execute(
            "UPDATE exams SET is_published = true, lifecycle_status = 'published' WHERE id = %s AND lifecycle_status = 'approved'",
            [exam['id']],
        )
        logger.info('Scheduled exam %s published', exam['id'])
    from .views import announce_exam_published

    for exam in due:
        announce_exam_published(exam['id'])
    return [{'id': exam['id'], 'title': exam['title']} for exam in due]


def finalize_expired_attempts(now=None) -> list:
    """Close every in-progress attempt whose time (plus the grace period) has run out; returns their ids."""
    from datetime import timedelta

    from .views import (
        ATTEMPT_GRACE_SECONDS, _notify_if_result_released, _sx_attempt_ends_at, _sx_attempt_extra_sql, _sx_dt, _sx_exam_cutoff, _sx_exam_rules,
        erd_execute, erd_rows, grade_attempt, log_activity,
    )

    now = now or timezone.now()
    open_attempts = erd_rows(
        f"""
        SELECT ea.id, ea.exam_id, ea.started_at, COALESCE(e.duration_minutes, 90) AS duration_minutes, e.end_at,
               {_sx_attempt_extra_sql()} AS extra_minutes
        FROM exam_attempts ea JOIN exams e ON e.id = ea.exam_id
        WHERE ea.submitted_at IS NULL AND ea.status = 'in_progress' AND ea.started_at IS NOT NULL
        """
    )
    rules_by_exam, closed = {}, []
    for attempt in open_attempts:
        exam_id = str(attempt['exam_id'])
        rules = rules_by_exam.setdefault(exam_id, _sx_exam_rules(exam_id))
        if not rules['settings_enforced']:
            continue  # exams without wizard settings keep such attempts as «نیمه‌کاره» for the teacher, as always
        cutoff = _sx_exam_cutoff(attempt['end_at'], rules['registration_end_at'])
        deadline = _sx_attempt_ends_at(_sx_dt(attempt['started_at']), attempt['duration_minutes'], cutoff, attempt['extra_minutes'])
        if now <= deadline + timedelta(seconds=ATTEMPT_GRACE_SECONDS):
            continue
        attempt_id = str(attempt['id'])
        if rules['auto_submit_on_time_end']:
            try:
                result = grade_attempt(attempt_id)
            except Exception:  # keep the answers as submitted (ungraded) so the teacher can still grade them
                logger.exception('Grading expired attempt %s failed; saved as submitted without a score.', attempt_id)
                erd_execute("UPDATE exam_attempts SET submitted_at = %s, status = 'submitted' WHERE id = %s AND submitted_at IS NULL",
                            [now, attempt_id])
                result = {'grading_failed': True}
            log_activity(None, 'exam_auto_submitted', 'زمان آزمون تمام شد و پاسخ‌های ذخیره‌شده خودکار ارسال شد.', None,
                         {'attempt_id': attempt_id, **result})
            _notify_if_result_released(attempt_id)
        else:
            erd_execute("UPDATE exam_attempts SET status = 'expired' WHERE id = %s AND submitted_at IS NULL", [attempt_id])
            log_activity(None, 'exam_attempt_expired', 'زمان آزمون تمام شد و دانشجو آزمون را ارسال نکرد.', None,
                         {'attempt_id': attempt_id})
        closed.append(attempt_id)
    return closed


RESULT_DEADLINE_DAYS = {'3_days_after_end': 3, '7_days_after_end': 7}


def release_due_results(now=None) -> list:
    """Publish the results of every ended exam whose «زمان اعلام نمره» says they are due; returns the exam ids."""
    from datetime import timedelta

    from .views import _set_exam_results_published, _sx_dt, erd_count, erd_has_column, erd_rows

    if not all(erd_has_column('exams', column) for column in ('results_published_at', 'settings_enforced', 'correction_mode')):
        return []
    now = now or timezone.now()
    exams = erd_rows(
        """
        SELECT id, start_at, end_at, COALESCE(duration_minutes, 90) AS duration_minutes, correction_mode, results_deadline
        FROM exams
        WHERE results_published_at IS NULL AND settings_enforced = true
          AND COALESCE(is_published, false) = true AND COALESCE(is_cancelled, false) = false
        """
    )
    released = []
    for exam in exams:
        start = _sx_dt(exam['start_at'])
        end = _sx_dt(exam['end_at']) or (start + timedelta(minutes=int(exam['duration_minutes'])) if start else None)
        if not end or now < end:
            continue
        days = RESULT_DEADLINE_DAYS.get(exam.get('results_deadline') or '')
        due = bool(days) and now >= end + timedelta(days=days)
        if not due and exam.get('correction_mode') == 'auto_then_manual':
            submitted = erd_count('exam_attempts', 'exam_id = %s AND submitted_at IS NOT NULL', [exam['id']])
            waiting = erd_count(
                'exam_attempts',
                "exam_id = %s AND (status = 'in_progress' OR (submitted_at IS NOT NULL AND COALESCE(is_graded, false) = false))",
                [exam['id']],
            )
            due = submitted > 0 and waiting == 0
        if due:
            _set_exam_results_published(None, exam['id'], True)
            logger.info('Results of exam %s released automatically', exam['id'])
            released.append(str(exam['id']))
    return released


def run_due_tasks(now=None) -> dict:
    """Every timed exam task; one failing does not stop the others (the next run retries it)."""
    done = {}
    from .teacher_preferences import archive_stale_drafts, send_due_emails

    for name, task in (('published', publish_due_exams), ('finalized', finalize_expired_attempts),
                       ('released', release_due_results), ('teacher_emails', send_due_emails),
                       ('archived_drafts', archive_stale_drafts)):
        try:
            done[name] = task(now)
        except Exception:
            logger.exception('Timed exam task %s failed', name)
            done[name] = []
    return done


class ScheduledPublishMiddleware:
    """Runs run_due_tasks() before a request, at most once every PUBLISH_CHECK_SECONDS in this process."""

    def __init__(self, get_response):
        self.get_response = get_response
        self.last_check = 0.0

    def __call__(self, request):
        if time.monotonic() - self.last_check >= PUBLISH_CHECK_SECONDS:
            self.last_check = time.monotonic()
            try:
                run_due_tasks()
            except Exception:  # a failed check must not break the page; the next check retries
                logger.exception('Timed exam tasks failed')
        return self.get_response(request)
