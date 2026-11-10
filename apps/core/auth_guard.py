"""Sign-in audit trail and brute-force protection (see Auth.md).

Every sign-in, failed attempt, blocked attempt and sign-out is a row in `auth_events` (migration 0063): time, username,
auth_user id, client IP and browser. The same rows drive the login throttle, so the limit is shared by every gunicorn
worker (the old per-process cache counter was not) and survives a restart:

- one account: LOGIN_MAX_FAILED_PER_USER failed passwords within LOGIN_LOCK_MINUTES lock it until the oldest of them
  leaves the window; a correct password (event `password_ok`) or a sign-in starts the count again;
- second step: 2 × LOGIN_MAX_FAILED_PER_USER wrong authenticator codes within the window (a correct password does not
  reset these, only a completed sign-in) lock the account the same way;
- one IP: LOGIN_MAX_FAILED_PER_IP failed attempts (any usernames) within the same window block that IP's attempts.
  Kept high because a whole campus can share one NAT address.
Attempts refused because of a lock are logged as `login_blocked` and do not extend the lock.
"""
import logging
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.db import DatabaseError, connection
from django.dispatch import receiver
from django.utils import timezone

logger = logging.getLogger(__name__)

EVENTS = ('login_success', 'login_failed', 'login_blocked', 'password_ok', 'two_factor_failed', 'logout')


def max_failed_per_user() -> int:
    return int(getattr(settings, 'LOGIN_MAX_FAILED_PER_USER', 5))


def max_failed_per_ip() -> int:
    return int(getattr(settings, 'LOGIN_MAX_FAILED_PER_IP', 100))


def lock_minutes() -> int:
    return int(getattr(settings, 'LOGIN_LOCK_MINUTES', 15))


def normalize_username(username) -> str:
    return (username or '').strip().lower()[:150]


def _client_ip(request) -> str:
    if request is None:
        return ''
    from .views import client_ip  # views imports this module; import late to avoid a cycle

    return (client_ip(request) or '')[:64]


def record(event: str, request=None, username: str = '', user=None) -> None:
    """Append one row to the sign-in log. Never raises: signing in must not fail because logging did."""
    if user is not None and not username:
        username = user.get_username()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                'INSERT INTO auth_events (event, username, user_id, ip_address, user_agent, created_at) '
                'VALUES (%s, %s, %s, %s, %s, %s)',
                [
                    event,
                    normalize_username(username),
                    getattr(user, 'pk', None),
                    _client_ip(request),
                    (request.META.get('HTTP_USER_AGENT', '') if request is not None else '')[:300],
                    timezone.now(),
                ],
            )
    except DatabaseError:
        logger.exception('could not record auth event %s for %s', event, username)


def _window_start():
    return timezone.now() - timedelta(minutes=lock_minutes())


def failed_for_user(username: str) -> int:
    """Failed passwords for this account inside the window and after its last correct password."""
    username = normalize_username(username)
    if not username:
        return 0
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT COUNT(*) FROM auth_events
            WHERE username = %s AND event = 'login_failed' AND created_at > %s
              AND created_at > COALESCE((SELECT MAX(created_at) FROM auth_events
                                         WHERE username = %s AND event IN ('login_success', 'password_ok')), %s)
            """,
            [username, _window_start(), username, _window_start()],
        )
        return cursor.fetchone()[0]


def failed_two_factor_for_user(username: str) -> int:
    """Wrong authenticator codes for this account inside the window and after its last completed sign-in."""
    username = normalize_username(username)
    if not username:
        return 0
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT COUNT(*) FROM auth_events
            WHERE username = %s AND event = 'two_factor_failed' AND created_at > %s
              AND created_at > COALESCE((SELECT MAX(created_at) FROM auth_events
                                         WHERE username = %s AND event = 'login_success'), %s)
            """,
            [username, _window_start(), username, _window_start()],
        )
        return cursor.fetchone()[0]


def failed_for_ip(ip: str) -> int:
    if not ip:
        return 0
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT COUNT(*) FROM auth_events WHERE ip_address = %s AND event = 'login_failed' AND created_at > %s",
            [ip, _window_start()],
        )
        return cursor.fetchone()[0]


def lock_reason(username: str, request=None) -> str:
    """'' when a sign-in may be tried; otherwise 'user' (account locked) or 'ip' (this address is throttled)."""
    try:
        if failed_for_user(username) >= max_failed_per_user():
            return 'user'
        if failed_two_factor_for_user(username) >= 2 * max_failed_per_user():
            return 'user'
        if failed_for_ip(_client_ip(request)) >= max_failed_per_ip():
            return 'ip'
    except DatabaseError:  # fail open: an unreadable log must not lock everybody out
        logger.exception('could not read auth events for %s', username)
    return ''


@receiver(user_logged_in)
def _on_login(sender, request, user, **kwargs):
    record('login_success', request, user=user)


@receiver(user_logged_out)
def _on_logout(sender, request, user, **kwargs):
    if user is not None:
        record('logout', request, user=user)
