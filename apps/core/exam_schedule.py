"""Exam work that is due at a time rather than on a request:

- publish_due_exams(): «زمان‌بندی انتشار», an approved exam becomes visible to students once its publish time comes.
- finalize_expired_attempts(): an attempt whose time ran out without «پایان آزمون» (e.g. the browser was closed) is
  submitted with its saved answers when the exam's «ارسال خودکار در پایان زمان» is on (the default, also for exams
  without wizard settings), else closed as expired.
- release_due_results(): results are published when «خودکار پس از تصحیح کامل» finds every attempt graded, or when
  «مهلت نهایی انتشار نمرات» passes.

run_due_tasks() runs all of them. Nothing to install on the server:
- ScheduledPublishMiddleware runs it before a request, at most once a minute per process.
- Each web process also starts a daemon thread on its first request (like auto_backup.py) that closes expired
  attempts every FINALIZE_TICK_SECONDS and runs everything once a minute, so an attempt whose browser was closed is
  closed within seconds of its grace time even when nobody is using the site. DUE_TASKS_SCHEDULER=0 in .env turns
  the thread off (tests: always off).
- `manage.py publish_scheduled_exams` does the same from a cron/systemd timer, if one is ever wanted.
All runners share one PostgreSQL advisory lock, so only one process in the deployment runs the tasks at a time; each
attempt is also taken atomically (views._sx_claim_attempt_close), so it is never graded, logged or announced twice.
"""
import logging
import random
import threading
import time
from contextlib import contextmanager

from django.conf import settings
from django.db import connection, connections
from django.utils import timezone

logger = logging.getLogger(__name__)
PUBLISH_CHECK_SECONDS = 60
FINALIZE_TICK_SECONDS = 10
TASKS_LOCK_KEY = 7_412_030_956  # pg advisory lock id of «timed exam tasks running» (auto_backup uses ...955)


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
        ATTEMPT_GRACE_SECONDS, _notify_if_result_released, _sx_attempt_ends_at, _sx_attempt_extra_sql, _sx_claim_attempt_close, _sx_dt,
        _sx_exam_cutoff, _sx_exam_rules, attempt_receipt_code, erd_execute, erd_rows, grade_attempt, log_activity,
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
        # Every exam, with or without wizard settings: time up means the attempt ends (older exams use the default
        # «ارسال خودکار در پایان زمان» = on, which their exam page already announces and counts down to).
        rules = rules_by_exam.setdefault(exam_id, _sx_exam_rules(exam_id))
        cutoff = _sx_exam_cutoff(attempt['end_at'], rules['registration_end_at'])
        deadline = _sx_attempt_ends_at(_sx_dt(attempt['started_at']), attempt['duration_minutes'], cutoff, attempt['extra_minutes'])
        if now <= deadline + timedelta(seconds=ATTEMPT_GRACE_SECONDS):
            continue
        attempt_id = str(attempt['id'])
        if rules['auto_submit_on_time_end']:
            # Taken atomically and stamped at the deadline, not at this run: the attempt lasted only as long as allowed.
            if not _sx_claim_attempt_close(attempt_id, submitted_at=deadline):
                continue  # submitted or closed meanwhile (the student's own submit, another process)
            try:
                result = grade_attempt(attempt_id)
            except Exception:  # keep the answers as submitted (ungraded) so the teacher can still grade them
                logger.exception('Grading expired attempt %s failed; saved as submitted without a score.', attempt_id)
                erd_execute("UPDATE exam_attempts SET status = 'submitted' WHERE id = %s", [attempt_id])
                attempt_receipt_code(attempt_id)
                result = {'grading_failed': True}
            log_activity(None, 'exam_auto_submitted', 'زمان آزمون تمام شد و پاسخ‌های ذخیره‌شده خودکار ارسال شد.', None,
                         {'attempt_id': attempt_id, **result})
            _notify_if_result_released(attempt_id)
        else:
            if not _sx_claim_attempt_close(attempt_id, status='expired'):
                continue
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


TASK_NAMES = ('published', 'finalized', 'released', 'teacher_emails', 'archived_drafts')


@contextmanager
def _only_runner():
    """Yields True when this process may run the tasks now: it holds the deployment-wide advisory lock (PostgreSQL;
    other databases have one process). Released right after, on this connection."""
    if connection.vendor != 'postgresql':
        yield True
        return
    with connection.cursor() as cursor:
        cursor.execute('SELECT pg_try_advisory_lock(%s)', [TASKS_LOCK_KEY])
        got = bool(cursor.fetchone()[0])
    try:
        yield got
    finally:
        if got:
            with connection.cursor() as cursor:
                cursor.execute('SELECT pg_advisory_unlock(%s)', [TASKS_LOCK_KEY])


def run_due_tasks(now=None, only=None) -> dict:
    """Every timed exam task (or those named in ``only``); one failing does not stop the others (the next run retries
    it). Skipped, with empty results, while another process runs them."""
    done = {name: [] for name in TASK_NAMES}
    from .teacher_preferences import archive_stale_drafts, send_due_emails

    tasks = (('published', publish_due_exams), ('finalized', finalize_expired_attempts),
             ('released', release_due_results), ('teacher_emails', send_due_emails),
             ('archived_drafts', archive_stale_drafts))
    with _only_runner() as mine:
        if not mine:
            return done
        for name, task in tasks:
            if only and name not in only:
                continue
            try:
                done[name] = task(now)
            except Exception:
                logger.exception('Timed exam task %s failed', name)
                done[name] = []
    return done


# ---------------------------------------------------------------- in-process scheduler thread

_thread = None
_thread_guard = threading.Lock()


def scheduler_enabled():
    return bool(getattr(settings, 'DUE_TASKS_SCHEDULER', False))


def ensure_scheduler():
    """Starts this process's scheduler thread once (called on every request; cheap after the first)."""
    global _thread
    if _thread is not None or not scheduler_enabled():
        return
    with _thread_guard:
        if _thread is None:
            _thread = threading.Thread(target=_loop, name='metaquizy-due-tasks', daemon=True)
            _thread.start()


def _loop():
    time.sleep(random.uniform(2, 8))  # let the process finish starting; spread the workers apart
    last_full = 0.0
    while True:
        try:
            if time.monotonic() - last_full >= PUBLISH_CHECK_SECONDS:
                last_full = time.monotonic()
                run_due_tasks()
            else:
                run_due_tasks(only=('finalized',))
        except Exception:  # noqa: BLE001 — the thread must survive anything
            logger.exception('Timed exam scheduler tick failed.')
        finally:
            connections.close_all()  # this thread's own connections only
        time.sleep(FINALIZE_TICK_SECONDS + random.uniform(0, 2))


class ScheduledPublishMiddleware:
    """Starts the scheduler thread, and runs run_due_tasks() before a request at most once every
    PUBLISH_CHECK_SECONDS in this process (a fallback when the thread is off)."""

    def __init__(self, get_response):
        self.get_response = get_response
        self.last_check = 0.0

    def __call__(self, request):
        ensure_scheduler()  # here, not in __init__: with a preloaded app __init__ runs in the master before fork
        if time.monotonic() - self.last_check >= PUBLISH_CHECK_SECONDS:
            self.last_check = time.monotonic()
            try:
                run_due_tasks()
            except Exception:  # a failed check must not break the page; the next check retries
                logger.exception('Timed exam tasks failed')
        return self.get_response(request)
