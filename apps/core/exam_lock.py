"""Exam lock: while a student's (non-practice) exam attempt is open, the browser stays on that attempt.

The exam page traps «Back» / «Forward» and asks before leaving (templates/student/attempt.html), but a browser can
always be made to leave a page (history menu, a typed address, a second «Back» Chrome lets skip the trap, scripts).
So the server enforces it: any page opened by this session while the attempt still accepts answers — another
student page, the dashboard, the home page (which would sign out), «خروج», a typed address — is redirected back to
the attempt, and the try is logged for the teacher («تلاش برای خروج از آزمون»).

- The lock lives in the session (``mq_exam_lock`` = attempt id), set when the attempt page opens and on sign-in
  when the student has an open attempt, cleared on submit / when the attempt no longer accepts answers.
- Only top-level page loads are redirected (``Sec-Fetch-Dest: document``, or an HTML GET from an old browser):
  the attempt's own fetches, media, files and static are untouched.
- A readable ``mq_exam_lock=1`` cookie mirrors it so a page restored from the browser's back/forward cache (no
  request reaches the server) reloads itself (partials/appearance_head.html) and so lands on the attempt.
"""
import logging

from django.conf import settings
from django.contrib.auth.signals import user_logged_in
from django.db import DatabaseError
from django.dispatch import receiver
from django.shortcuts import redirect
from django.urls import reverse

logger = logging.getLogger(__name__)

SESSION_KEY = 'mq_exam_lock'
COOKIE_NAME = 'mq_exam_lock'


def lock(request, attempt_id) -> None:
    if getattr(request, 'session', None) is not None and request.session.get(SESSION_KEY) != str(attempt_id):
        request.session[SESSION_KEY] = str(attempt_id)


def unlock(request, attempt_id=None) -> None:
    session = getattr(request, 'session', None)
    if session is None or SESSION_KEY not in session:
        return
    if attempt_id is None or session.get(SESSION_KEY) == str(attempt_id):
        del session[SESSION_KEY]


def lockable_attempt(attempt_id, student_id) -> bool:
    """The attempt is the student's own, a course exam (not practice), not submitted and still within its time."""
    from . import student_practice as practice
    from .views import _sx_attempt_accepts_answers, erd_row

    if not attempt_id or not student_id:
        return False
    row = erd_row(
        "SELECT id FROM exam_attempts WHERE id = %s AND student_id = %s AND submitted_at IS NULL "
        "AND COALESCE(status, 'in_progress') IN ('in_progress', '')",
        [attempt_id, student_id],
    )
    if not row or practice.attempt_practice_mode(attempt_id, student_id):
        return False
    return _sx_attempt_accepts_answers(attempt_id)


def _student_id(user):
    from .views import erd_primary_role, erd_profile_for_user

    if erd_primary_role(user) != 'student':
        return None
    profile = erd_profile_for_user(user)
    return profile['id'] if profile else None


@receiver(user_logged_in)
def _lock_on_login(sender, request, user, **kwargs):
    """Signing in (again, or on another browser) during an open exam goes straight back to it."""
    if request is None or getattr(request, 'session', None) is None:
        return
    try:
        from .views import erd_rows

        student_id = _student_id(user)
        if not student_id:
            return
        for row in erd_rows(
            "SELECT id FROM exam_attempts WHERE student_id = %s AND submitted_at IS NULL "
            "AND COALESCE(status, 'in_progress') IN ('in_progress', '') ORDER BY started_at DESC NULLS LAST LIMIT 5",
            [student_id],
        ):
            if lockable_attempt(row['id'], student_id):
                lock(request, row['id'])
                return
    except DatabaseError:  # never block a sign-in on this
        logger.exception('exam lock: could not check open attempts on sign-in')


def is_page_load(request) -> bool:
    dest = request.headers.get('Sec-Fetch-Dest')
    mode = request.headers.get('Sec-Fetch-Mode')
    if dest or mode:
        return mode == 'navigate' and dest in ('document', None, '')
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return False
    return request.method in ('GET', 'HEAD', 'POST') and 'text/html' in request.headers.get('Accept', '')


class ExamLockMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        session = getattr(request, 'session', None)
        user = getattr(request, 'user', None)
        attempt_id = session.get(SESSION_KEY) if session is not None else None
        if attempt_id and user is not None and user.is_authenticated and is_page_load(request) and not self._allowed(request.path, attempt_id):
            response = self._redirect_back(request, user, attempt_id)
            if response is not None:
                return self._sync_cookie(request, response)
        return self._sync_cookie(request, self.get_response(request))

    @staticmethod
    def _allowed(path, attempt_id) -> bool:
        prefixes = (
            settings.STATIC_URL or '/static/', settings.MEDIA_URL or '/media/', '/favicon',
            f'/student/attempts/{attempt_id}/',  # the attempt, its events, «پایان آزمون» and the receipt
            f'/attempts/{attempt_id}/files/',     # the student's own uploaded answer files
        )
        return path.startswith(prefixes) or path == reverse('core:password_change_required')

    @staticmethod
    def _redirect_back(request, user, attempt_id):
        try:
            student_id = _student_id(user)
            if not lockable_attempt(attempt_id, student_id):
                unlock(request)
                return None
            from .views import ATTEMPT_EVENT_LIMIT, ATTEMPT_EVENTS, _log_attempt_event, erd_count

            if erd_count('activity_audit_log', "entity_type = 'exam_attempt' AND entity_id = %s", [str(attempt_id)]) < ATTEMPT_EVENT_LIMIT:
                action, description = ATTEMPT_EVENTS['navigation']
                _log_attempt_event(request, attempt_id, action, f'{description} (نشانی: {request.path[:200]})')
        except DatabaseError:
            logger.exception('exam lock: could not check attempt %s', attempt_id)
            return None
        return redirect('core:student_attempt', attempt_id=attempt_id)

    @staticmethod
    def _sync_cookie(request, response):
        session = getattr(request, 'session', None)
        locked = bool(session is not None and session.get(SESSION_KEY))
        has_cookie = request.COOKIES.get(COOKIE_NAME) == '1'
        if locked and not has_cookie:
            response.set_cookie(COOKIE_NAME, '1', samesite='Lax', secure=request.is_secure(), httponly=False)
        elif not locked and COOKIE_NAME in request.COOKIES:
            response.delete_cookie(COOKIE_NAME, samesite='Lax')
        return response
