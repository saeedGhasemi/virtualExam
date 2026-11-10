"""Removes data whose retention period is over (Data.md → «سیاست نگهداری»).

    manage.py purge_expired_data            # delete
    manage.py purge_expired_data --dry-run  # only count

- expired Django sessions (same as `clearsessions`) and `user_sessions` rows whose session is gone;
- `auth_events` (sign-in log) older than AUTH_EVENTS_RETENTION_DAYS (default 365).
Exam records, answers, grades and the activity audit log are academic records and are never removed here.
"""
from datetime import timedelta

from django.conf import settings
from django.contrib.sessions.models import Session
from django.core.management.base import BaseCommand
from django.db import connection, transaction
from django.utils import timezone


class Command(BaseCommand):
    help = 'Delete expired sessions and sign-in log rows past their retention period (see Data.md).'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Only report what would be deleted.')

    def handle(self, *args, dry_run=False, **options):
        now = timezone.now()
        auth_cutoff = now - timedelta(days=settings.AUTH_EVENTS_RETENTION_DAYS)
        with transaction.atomic(), connection.cursor() as cursor:
            expired_sessions = Session.objects.filter(expire_date__lte=now)
            counts = {'sessions': expired_sessions.count()}
            cursor.execute('SELECT COUNT(*) FROM auth_events WHERE created_at < %s', [auth_cutoff])
            counts['auth_events'] = cursor.fetchone()[0]
            orphan_sql = ('FROM user_sessions us WHERE NOT EXISTS (SELECT 1 FROM django_session ds '
                          'WHERE ds.session_key = us.session_key AND ds.expire_date > %s)')
            cursor.execute(f'SELECT COUNT(*) {orphan_sql}', [now])
            counts['user_sessions'] = cursor.fetchone()[0]
            if not dry_run:
                expired_sessions.delete()
                cursor.execute('DELETE FROM auth_events WHERE created_at < %s', [auth_cutoff])
                cursor.execute(f'DELETE {orphan_sql}', [now])
        verb = 'would delete' if dry_run else 'deleted'
        self.stdout.write(', '.join(f'{verb} {count} {name}' for name, count in counts.items()))
