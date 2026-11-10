"""Deployment security checks, run by `manage.py check` (and so by the deploy verification step, see README).

With DEBUG off, a missing or placeholder SECRET_KEY is an error, so a broken .env is caught before an update is
applied rather than after. Cookies without Secure are a warning under `check --deploy` (Django's own deploy checks
also warn about a short key).
"""
from django.conf import settings
from django.core.checks import Error, Tags, Warning, register

INSECURE_KEY_PREFIX = 'django-insecure'


@register(Tags.security, deploy=False)
def production_secrets_check(app_configs, **kwargs):
    if settings.DEBUG:
        return []
    problems = []
    key = settings.SECRET_KEY or ''
    if not key.strip() or key.startswith(INSECURE_KEY_PREFIX):
        problems.append(Error(
            'SECRET_KEY is missing or the built-in placeholder while DEBUG is off.',
            hint='Set a long random SECRET_KEY in the server .env (never in the code). See Security.md.',
            id='core.S001',
        ))
    return problems


@register(Tags.security, deploy=True)
def production_cookie_check(app_configs, **kwargs):
    """Only under `check --deploy` (the test runner switches DEBUG off, so a plain check would warn in every run)."""
    problems = []
    if not settings.DEBUG and (not settings.SESSION_COOKIE_SECURE or not settings.CSRF_COOKIE_SECURE):
        problems.append(Warning(
            'Session/CSRF cookies are not marked Secure while DEBUG is off.',
            hint='Leave SESSION_COOKIE_SECURE / CSRF_COOKIE_SECURE unset (they follow DEBUG) when the site is served over HTTPS.',
            id='core.S002',
        ))
    return problems
