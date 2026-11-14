import logging
import time
from urllib.parse import urlencode

from django.conf import settings
from django.db import DataError, DatabaseError, connection
from django.http import Http404, HttpResponseNotFound, JsonResponse
from django.shortcuts import redirect
from django.urls import reverse

logger = logging.getLogger(__name__)


class ReplacedSessionNoticeMiddleware:
    """A device signed out because the account signed in elsewhere (account_security: one device per account) gets
    a toast saying so on the page it lands on (the sign-in page)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from django.contrib import messages

        from . import account_security

        try:
            if account_security.replaced_session_notice(request):
                messages.warning(request, account_security.REPLACED_SESSION_MESSAGE)
        except DatabaseError:
            logger.exception('could not check for a replaced session')
        return self.get_response(request)


class MalformedIdNotFoundMiddleware:
    """A URL id that is not a UUID makes PostgreSQL reject the query on the ERD uuid columns.

    Such a URL points at nothing, so it is answered with 404 instead of a 500. Other database errors pass through."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        if not (isinstance(exception, DataError) and 'invalid input syntax for type uuid' in str(exception)):
            return None
        logger.info('Malformed id in %s answered with 404', request.path)
        if connection.in_atomic_block:  # the failed statement aborted the transaction; render nothing that queries
            return HttpResponseNotFound('پیدا نشد.')
        from .views import error_404  # the site's own 404 page

        return error_404(request, Http404())


class PasswordChangeRequiredMiddleware:
    """A super admin gave this account a temporary password (profiles.password_change_required): until its owner
    picks a new one, every page except the change page and «خروج» redirects there."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, 'user', None)
        if user is not None and user.is_authenticated and self._must_change(request, user):
            target = reverse('core:password_change_required')
            if request.path not in {target, reverse('core:logout')}:
                if request.headers.get('x-requested-with') == 'XMLHttpRequest' or 'application/json' in request.headers.get('accept', ''):
                    return JsonResponse({'error': 'password_change_required', 'redirect': target}, status=403)
                return redirect(f'{target}?{urlencode({"next": request.get_full_path()})}' if request.method == 'GET' else target)
        return self.get_response(request)

    @staticmethod
    def _must_change(request, user) -> bool:
        if request.path.startswith((settings.STATIC_URL or '/static/', settings.MEDIA_URL or '/media/', '/favicon')):
            return False
        from .views import erd_profile_for_user

        try:
            profile = erd_profile_for_user(user)
        except DatabaseError:
            return False
        return bool(profile and profile.get('password_change_required'))


class PersonFieldLengthMiddleware:
    """No POST may store a personal / basic-info field longer than field_rules.FIELD_MAX (student number, national ID,
    phone, names, codes, field of study …), whichever page or dialog sends it. The browser already stops typing at that
    length and refuses keys that don't fit (static/js/field-rules.js); this is the server-side guard. A too-long value, or
    a personal field in the wrong format (field_rules.format_error: national ID, mobile, birth date, names, codes,
    e-mail …), is refused before the view runs:
    JSON 400 for scripts, else the message as a toast and back to the form."""

    # Pages that check these formats themselves and show the error on the form with the typed values kept (nicer than
    # a toast + redirect); the length caps still apply to them.
    SELF_VALIDATING = {'profile', 'teacher_settings', 'student_settings', 'super_admin_teacher_create',
                       'super_admin_student_create', 'super_admin_manager_create'}

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        if request.method != 'POST' or getattr(view_func, 'csrf_exempt', False):
            return None
        user = getattr(request, 'user', None)
        if user is None or not user.is_authenticated:  # sign-up / sign-in: their Django forms check lengths themselves
            return None
        from .field_rules import format_error, too_long_error

        try:
            error = too_long_error(request.POST)
            match = getattr(request, 'resolver_match', None)
            if not error and getattr(match, 'url_name', None) not in self.SELF_VALIDATING:
                error = format_error(request.POST)
        except Exception:  # unreadable body: the view / CSRF check reports it
            return None
        if not error:
            return None
        logger.info('Too-long / malformed field refused on %s', request.path)
        if request.headers.get('x-requested-with') == 'XMLHttpRequest' or 'application/json' in request.headers.get('accept', ''):
            return JsonResponse({'ok': False, 'error': error, 'message': error}, status=400)
        from django.contrib import messages
        from django.utils.http import url_has_allowed_host_and_scheme

        messages.error(request, error)
        back = request.headers.get('referer', '')
        if not url_has_allowed_host_and_scheme(back, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
            back = request.get_full_path()
        return redirect(back)


class ForbiddenPageMiddleware:
    """A refused request (403) that a person opened in the browser gets the site's styled 403 page (`403.html`, with
    the refusal text) instead of the bare text the role decorators / scope checks answer with
    (`HttpResponseForbidden('…')`). Script requests (fetch/XHR, JSON) keep the original short answer."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if response.status_code != 403 or getattr(response, 'streaming', False):
            return response
        if not response.get('Content-Type', '').startswith('text/html'):
            return response
        if request.headers.get('X-Requested-With') or request.headers.get('Sec-Fetch-Mode', 'navigate') != 'navigate':
            return response
        body = response.content.decode(response.charset or 'utf-8', 'replace').strip()
        if '<' in body or len(body) > 300:  # already a page (e.g. the CSRF failure view)
            return response
        from django.shortcuts import render

        try:
            return render(request, '403.html', {'forbidden_message': body}, status=403)
        except DatabaseError:  # the page's chrome queries; a broken transaction keeps the plain answer
            logger.exception('could not render the 403 page')
            return response


class SecurityHeadersMiddleware:
    """Response headers Django's SecurityMiddleware does not set (Hack.md → «هدرها»):

    - Content-Security-Policy limited to what cannot break the inline scripts the templates use: no <base> hijack, no
      plugins, no framing by other sites, forms post only back to this site;
    - Permissions-Policy: camera/microphone/fullscreen only for this site (exam proctoring), the rest off;
    - pages for a signed-in user are not stored by the browser or a shared cache (`no-store`), so after «خروج» the
      Back button or another person on the same computer cannot bring a private page (answers, grades) back.
    """

    CSP = "base-uri 'self'; object-src 'none'; frame-ancestors 'none'; form-action 'self'"
    PERMISSIONS = 'camera=(self), microphone=(self), fullscreen=(self), display-capture=(), geolocation=(), payment=(), usb=()'

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        # Over HTTPS the browser also upgrades any leftover http:// sub-resource instead of loading it in clear text.
        csp = self.CSP + ('; upgrade-insecure-requests' if request.is_secure() else '')
        response.headers.setdefault('Content-Security-Policy', csp)
        response.headers.setdefault('Permissions-Policy', self.PERMISSIONS)
        user = getattr(request, 'user', None)
        static_prefix = settings.STATIC_URL or '/static/'
        if (user is not None and user.is_authenticated and 'Cache-Control' not in response.headers
                and not request.path.startswith(static_prefix)):
            response.headers['Cache-Control'] = 'private, no-store'
        # A file download keeps the page where it is: tell the site-wide loader (static/js/page-loader.js) that the file
        # has started, so it hides instead of waiting for a page that never comes.
        if response.headers.get('Content-Disposition', '').lower().startswith('attachment'):
            response.set_cookie('mq_dl', str(time.time_ns()), max_age=120, path='/', samesite='Lax',
                                secure=request.is_secure(), httponly=False)
        return response
