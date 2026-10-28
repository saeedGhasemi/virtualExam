"""A user's own sign-in sessions: recorded on login, listed on the settings page and ended on request.

Rows live in user_sessions (migration 0045); the session itself stays in Django's session store, so a row only
counts while its session is still there and unexpired.
"""
import hashlib
import logging
import secrets
from importlib import import_module
from importlib.util import find_spec

from django.conf import settings
from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.contrib.sessions.models import Session
from django.db import DatabaseError, connection
from django.dispatch import receiver
from django.utils import timezone

logger = logging.getLogger(__name__)


def _session_store():
    return import_module(settings.SESSION_ENGINE).SessionStore


def _client_ip(request) -> str:
    from .views import client_ip  # views imports this module; import late to avoid a cycle

    return client_ip(request) or ''


@receiver(user_logged_in)
def record_session(sender, request, user, **kwargs):
    if request is None or not getattr(request, 'session', None):
        return
    if not request.session.session_key:
        request.session.save()
    try:
        with connection.cursor() as cursor:
            cursor.execute('DELETE FROM user_sessions WHERE session_key = %s', [request.session.session_key])
            cursor.execute(
                'INSERT INTO user_sessions (session_key, user_id, ip_address, user_agent) VALUES (%s, %s, %s, %s)',
                [request.session.session_key, user.pk, _client_ip(request)[:64], request.META.get('HTTP_USER_AGENT', '')[:300]],
            )
    except DatabaseError:  # login must not fail because the list of sessions could not be updated
        logger.exception('could not record the session of user %s', user.pk)


@receiver(user_logged_out)
def forget_session(sender, request, user, **kwargs):
    key = getattr(getattr(request, 'session', None), 'session_key', None)
    if key:
        with connection.cursor() as cursor:
            cursor.execute('DELETE FROM user_sessions WHERE session_key = %s', [key])


def active_sessions(user, current_key: str | None) -> list:
    """The user's sessions that are still valid, newest first, with the current one marked."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT us.session_key, us.ip_address, us.user_agent, us.created_at
            FROM user_sessions us
            JOIN django_session ds ON ds.session_key = us.session_key
            WHERE us.user_id = %s AND ds.expire_date > %s
            ORDER BY us.created_at DESC
            LIMIT 20
            """,
            [user.pk, timezone.now()],
        )
        rows = cursor.fetchall()
    from .views import describe_user_agent

    return [
        {'key': key, 'ip': ip or '-', 'device': describe_user_agent(agent), 'created_at': created, 'is_current': key == current_key}
        for key, ip, agent, created in rows
    ]


def end_session(user, session_key: str, current_key: str | None) -> bool:
    """End one of the user's own sessions (never someone else's, never the current one)."""
    if not session_key or session_key == current_key:
        return False
    with connection.cursor() as cursor:
        cursor.execute('SELECT 1 FROM user_sessions WHERE session_key = %s AND user_id = %s', [session_key, user.pk])
        if not cursor.fetchone():
            return False
        cursor.execute('DELETE FROM user_sessions WHERE session_key = %s', [session_key])
    _session_store()(session_key=session_key).delete()
    return True


def end_other_sessions(user, current_key: str | None) -> int:
    """End every session of the user except the current one, including ones signed in before tracking existed."""
    store, ended = _session_store(), 0
    for stored in Session.objects.filter(expire_date__gt=timezone.now()).iterator():
        if stored.session_key == current_key:
            continue
        if str(stored.get_decoded().get('_auth_user_id')) == str(user.pk):
            store(session_key=stored.session_key).delete()
            ended += 1
    with connection.cursor() as cursor:
        cursor.execute('DELETE FROM user_sessions WHERE user_id = %s AND session_key <> %s', [user.pk, current_key or ''])
    return ended


def end_all_sessions(user) -> int:
    return end_other_sessions(user, None)


# --- Two-step sign-in with an authenticator app (TOTP, RFC 6238 via pyotp) -----------------------------------

TOTP_ISSUER = 'MetaQuiz'
# pyotp and qrcode are pinned in requirements.txt; without them the setup button is replaced by a notice.
TWO_FACTOR_AVAILABLE = all(find_spec(name) for name in ('pyotp', 'qrcode'))
RECOVERY_CODE_COUNT = 10
RECOVERY_ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'  # no 0/O/1/I, easy to copy by hand


def _fetch(sql, params):
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        return cursor.fetchone()


def two_factor_enabled(user) -> bool:
    row = _fetch('SELECT enabled FROM user_two_factor WHERE user_id = %s', [user.pk])
    return bool(row and row[0])


def two_factor_status(user) -> dict:
    left = _fetch('SELECT COUNT(*) FROM user_recovery_codes WHERE user_id = %s AND used_at IS NULL', [user.pk])[0]
    return {'enabled': two_factor_enabled(user), 'recovery_left': left, 'available': TWO_FACTOR_AVAILABLE}


def start_enrollment(user) -> str:
    """A fresh secret for setting up the app; it only takes effect after confirm_enrollment."""
    import pyotp

    if two_factor_enabled(user):
        raise ValueError('two-factor sign-in is already on')
    secret = pyotp.random_base32()
    with connection.cursor() as cursor:
        cursor.execute('DELETE FROM user_two_factor WHERE user_id = %s', [user.pk])
        cursor.execute('INSERT INTO user_two_factor (user_id, secret, enabled) VALUES (%s, %s, %s)', [user.pk, secret, False])
    return secret


def pending_secret(user) -> str | None:
    row = _fetch('SELECT secret FROM user_two_factor WHERE user_id = %s AND enabled = %s', [user.pk, False])
    return row[0] if row else None


def provisioning_qr_svg(user, secret: str) -> str:
    """Inline SVG of the otpauth:// link that authenticator apps scan."""
    import pyotp
    import qrcode
    import qrcode.image.svg

    uri = pyotp.TOTP(secret).provisioning_uri(name=user.get_username(), issuer_name=TOTP_ISSUER)
    image = qrcode.make(uri, image_factory=qrcode.image.svg.SvgPathImage, box_size=8, border=2)
    return image.to_string(encoding='unicode')


def _matching_step(secret: str, code: str) -> int | None:
    """The 30-second step the code belongs to (now, or one step either side for clock drift), or None."""
    import pyotp

    totp, now = pyotp.TOTP(secret), timezone.now()
    current = totp.timecode(now)
    for step in (current, current - 1, current + 1):
        if secrets.compare_digest(totp.generate_otp(step), code):
            return step
    return None


def _accept_totp(user, code: str, secret: str, last_step) -> bool:
    step = _matching_step(secret, code)
    if step is None or (last_step is not None and step <= last_step):
        return False
    with connection.cursor() as cursor:
        cursor.execute('UPDATE user_two_factor SET last_used_step = %s WHERE user_id = %s', [step, user.pk])
    return True


def _hash_code(code: str) -> str:
    # Recovery codes are ~50 random bits, not user-chosen passwords, so a plain SHA-256 is enough here
    # (and keeps checking ten of them fast); the codes themselves are never stored.
    return hashlib.sha256(code.encode()).hexdigest()


def _normalize_recovery(code: str) -> str:
    return ''.join(code.split()).replace('-', '').upper()


def new_recovery_codes(user) -> list:
    """Replace the user's recovery codes; the plain codes are returned once, to show the user."""
    codes = [''.join(secrets.choice(RECOVERY_ALPHABET) for _ in range(10)) for _ in range(RECOVERY_CODE_COUNT)]
    with connection.cursor() as cursor:
        cursor.execute('DELETE FROM user_recovery_codes WHERE user_id = %s', [user.pk])
        for code in codes:
            cursor.execute('INSERT INTO user_recovery_codes (user_id, code_hash) VALUES (%s, %s)', [user.pk, _hash_code(code)])
    return [f'{code[:5]}-{code[5:]}' for code in codes]


def confirm_enrollment(user, code: str) -> list | None:
    """Turn two-step sign-in on if the code from the app matches; returns the new recovery codes."""
    row = _fetch('SELECT secret, last_used_step FROM user_two_factor WHERE user_id = %s AND enabled = %s', [user.pk, False])
    if not row or not _accept_totp(user, (code or '').strip(), row[0], row[1]):
        return None
    with connection.cursor() as cursor:
        cursor.execute('UPDATE user_two_factor SET enabled = %s, confirmed_at = %s WHERE user_id = %s', [True, timezone.now(), user.pk])
    return new_recovery_codes(user)


def verify_code(user, code: str) -> str | None:
    """Check a sign-in code: 'totp' or 'recovery' when accepted (a recovery code is used up), else None."""
    code = (code or '').strip()
    row = _fetch('SELECT secret, last_used_step FROM user_two_factor WHERE user_id = %s AND enabled = %s', [user.pk, True])
    if not row:
        return None
    if code.isdigit() and len(code) == 6:
        return 'totp' if _accept_totp(user, code, row[0], row[1]) else None
    with connection.cursor() as cursor:
        cursor.execute(
            'UPDATE user_recovery_codes SET used_at = %s WHERE user_id = %s AND code_hash = %s AND used_at IS NULL',
            [timezone.now(), user.pk, _hash_code(_normalize_recovery(code))],
        )
        return 'recovery' if cursor.rowcount == 1 else None


def disable_two_factor(user) -> None:
    with connection.cursor() as cursor:
        cursor.execute('DELETE FROM user_two_factor WHERE user_id = %s', [user.pk])
        cursor.execute('DELETE FROM user_recovery_codes WHERE user_id = %s', [user.pk])
