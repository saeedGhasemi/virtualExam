import logging
import time
from urllib.parse import urlencode

from django.conf import settings
from django.db import DataError, DatabaseError, connection
from django.http import Http404, HttpResponseNotFound, JsonResponse
from django.shortcuts import redirect
from django.urls import reverse

logger = logging.getLogger(__name__)


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
