import logging

from django.db import DataError, connection
from django.http import Http404, HttpResponseNotFound

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
