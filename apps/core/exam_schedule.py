"""«زمان‌بندی انتشار»: an exam approved with a publish time becomes visible to students once that time comes.

publish_due_exams() does the work. It runs from ScheduledPublishMiddleware (at most once a minute per process,
so no extra service is needed) and from `manage.py publish_scheduled_exams` for a cron/systemd timer.
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
    return [{'id': exam['id'], 'title': exam['title']} for exam in due]


class ScheduledPublishMiddleware:
    """Runs publish_due_exams() before a request, at most once every PUBLISH_CHECK_SECONDS in this process."""

    def __init__(self, get_response):
        self.get_response = get_response
        self.last_check = 0.0

    def __call__(self, request):
        if time.monotonic() - self.last_check >= PUBLISH_CHECK_SECONDS:
            self.last_check = time.monotonic()
            try:
                publish_due_exams()
            except Exception:  # a failed check must not break the page; the next check retries
                logger.exception('Publishing scheduled exams failed')
        return self.get_response(request)
