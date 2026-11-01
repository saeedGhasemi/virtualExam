import os
import sqlite3
import subprocess
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.utils import timezone


class Command(BaseCommand):
    help = (
        'Writes a backup of the database into BACKUP_DIR (the folder the system dashboard monitors): '
        'SQLite through its online backup API, PostgreSQL with pg_dump -Fc. '
        'With --keep N, only the newest N backups made by this command are kept.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--keep', type=int, default=0, help='Keep only the newest N backups made by this command (0 keeps all).')

    def handle(self, *args, **options):
        folder = Path(settings.BACKUP_DIR) if settings.BACKUP_DIR else None
        if not folder:
            raise CommandError('BACKUP_DIR is not set; set it in .env to the folder backups go to.')
        folder.mkdir(parents=True, exist_ok=True)
        stamp = timezone.localtime().strftime('%Y%m%d-%H%M%S')
        database = settings.DATABASES['default']
        if connection.vendor == 'sqlite':
            target = folder / f'db-{stamp}.sqlite3'
            name = str(database['NAME'])
            source = sqlite3.connect(name, uri=name.startswith('file:'))  # the test database is an in-memory URI
            copy = sqlite3.connect(str(target))
            try:
                source.backup(copy)  # consistent even while the app is writing
            finally:
                copy.close()
                source.close()
            pattern = 'db-*.sqlite3'
        elif connection.vendor == 'postgresql':
            target = folder / f'db-{stamp}.dump'
            environment = {**os.environ, 'PGPASSWORD': str(database.get('PASSWORD') or '')}
            command = ['pg_dump', '-Fc', '-f', str(target), '-h', str(database.get('HOST') or 'localhost'),
                       '-p', str(database.get('PORT') or '5432'), '-U', str(database.get('USER') or ''), str(database['NAME'])]
            try:
                result = subprocess.run(command, env=environment, capture_output=True, text=True)
            except FileNotFoundError as error:
                raise CommandError('pg_dump was not found; add the PostgreSQL bin folder to PATH.') from error
            if result.returncode != 0:
                target.unlink(missing_ok=True)
                raise CommandError(f'pg_dump failed: {result.stderr.strip()}')
            pattern = 'db-*.dump'
        else:
            raise CommandError(f'Backups are not supported for the {connection.vendor} database.')
        self.stdout.write(self.style.SUCCESS(f'Backup written: {target} ({target.stat().st_size} bytes)'))
        if options['keep'] > 0:
            older = sorted(folder.glob(pattern), key=lambda path: path.stat().st_mtime, reverse=True)[options['keep']:]
            for path in older:
                path.unlink()
            if older:
                self.stdout.write(f'Removed {len(older)} older backup(s).')
