"""Database backup / restore for the admin «تنظیمات سامانه» → «پشتیبان‌گیری و بازیابی» tab.

Only PostgreSQL, only the pg_dump custom format (-Fc): a backup is a single .dump file, and a restore runs
pg_restore --clean --if-exists --single-transaction, so a restore that fails half way changes nothing.
Connection settings come from settings.DATABASES['default']; the password goes through PGPASSWORD (never on the
command line). The pg_dump / pg_restore binaries are taken from PATH, or from PG_BIN_DIR in .env.
Before every restore a safety backup of the current database is written to disk (BACKUP_DIR, else
BASE_DIR/backups, else the temp folder); if that fails the restore does not run.
"""
import os
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.http import FileResponse, HttpResponseForbidden
from django.shortcuts import redirect
from django.urls import reverse
from django.db import connection
from django.utils import timezone

DUMP_MAGIC = b'PGDMP'
DUMP_TIMEOUT_SECONDS = 15 * 60
RESTORE_TIMEOUT_SECONDS = 30 * 60
RESTORE_MAX_BYTES = 2 * 1024 ** 3


class BackupError(Exception):
    """A user-facing (Persian) reason the backup / restore did not happen."""


def _database():
    return settings.DATABASES['default']


def is_postgres():
    return _database().get('ENGINE') == 'django.db.backends.postgresql'


def tool_path(name):
    folder = (os.getenv('PG_BIN_DIR') or '').strip()
    if folder:
        for candidate in (Path(folder) / name, Path(folder) / f'{name}.exe'):
            if candidate.is_file():
                return str(candidate)
    return shutil.which(name)


def tool_version(name):
    path = tool_path(name)
    if not path:
        return ''
    try:
        result = subprocess.run([path, '--version'], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return ''
    return (result.stdout or '').strip().replace(f'{name} (PostgreSQL) ', '')


def _environment():
    database = _database()
    environment = {**os.environ, 'PGPASSWORD': str(database.get('PASSWORD') or '')}
    sslmode = (database.get('OPTIONS') or {}).get('sslmode')
    if sslmode:
        environment['PGSSLMODE'] = str(sslmode)
    return environment


def _connection_args():
    database = _database()
    return ['-h', str(database.get('HOST') or 'localhost'), '-p', str(database.get('PORT') or '5432'),
            '-U', str(database.get('USER') or '')]


def database_name():
    return str(_database().get('NAME') or '')


def _error_text(stderr):
    text = (stderr or '').strip()
    return text[-600:] if text else 'بدون پیام خطا'


def _require_tool(name):
    path = tool_path(name)
    if not path:
        raise BackupError(f'ابزار {name} روی سرور پیدا نشد (مسیر PostgreSQL را در PATH یا PG_BIN_DIR تنظیم کنید).')
    return path


def dump_to(output):
    """Writes a pg_dump -Fc of the current database into `output` (a path or a binary file object)."""
    if not is_postgres():
        raise BackupError('پشتیبان‌گیری فقط برای پایگاه داده PostgreSQL فعال است.')
    command = [_require_tool('pg_dump'), '-Fc', '--no-password', *_connection_args()]
    target = None
    if isinstance(output, (str, Path)):
        target = Path(output)
        command += ['-f', str(target)]
    command.append(database_name())
    try:
        result = subprocess.run(command, env=_environment(), stdout=None if target else output,
                                stderr=subprocess.PIPE, text=False, timeout=DUMP_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired as error:
        if target:
            target.unlink(missing_ok=True)
        raise BackupError('زمان تهیه نسخه پشتیبان بیش از حد طول کشید.') from error
    except OSError as error:
        raise BackupError(f'اجرای pg_dump ممکن نشد: {error}') from error
    if result.returncode != 0:
        if target:
            target.unlink(missing_ok=True)
        raise BackupError('pg_dump خطا داد: ' + _error_text(result.stderr.decode('utf-8', 'replace')))


def download_name():
    stamp = timezone.localtime().strftime('%Y%m%d-%H%M%S')
    return f'metaquizy-{database_name()}-{stamp}.dump'


def safety_backup_folders():
    folders = []
    if getattr(settings, 'BACKUP_DIR', ''):
        folders.append(Path(settings.BACKUP_DIR))
    folders.append(Path(settings.BASE_DIR) / 'backups')
    folders.append(Path(tempfile.gettempdir()) / 'metaquizy-backups')
    return folders


def write_safety_backup():
    """Backs up the current database before a restore; returns the file path. Raises BackupError if no folder works."""
    stamp = timezone.localtime().strftime('%Y%m%d-%H%M%S')
    last_error = None
    for folder in safety_backup_folders():
        try:
            folder.mkdir(parents=True, exist_ok=True)
            probe = folder / f'.write-test-{stamp}'
            probe.write_bytes(b'')
            probe.unlink()
        except OSError as error:
            last_error = error
            continue
        target = folder / f'db-{stamp}-before-restore.dump'
        dump_to(target)
        return target
    raise BackupError(f'هیچ پوشه‌ای برای نسخه پشتیبان ایمنی قابل نوشتن نبود ({last_error}); بازیابی انجام نشد.')


def check_dump_file(path):
    """The file must be a pg_dump custom-format archive that pg_restore can read."""
    with open(path, 'rb') as handle:
        if handle.read(len(DUMP_MAGIC)) != DUMP_MAGIC:
            raise BackupError('این فایل، نسخه پشتیبان معتبر PostgreSQL (خروجی همین صفحه با قالب ‎.dump‎) نیست.')
    try:
        result = subprocess.run([_require_tool('pg_restore'), '--list', str(path)], capture_output=True, timeout=120)
    except (OSError, subprocess.SubprocessError) as error:
        raise BackupError(f'بررسی فایل پشتیبان ممکن نشد: {error}') from error
    if result.returncode != 0:
        raise BackupError('فایل پشتیبان خوانا نیست: ' + _error_text(result.stderr.decode('utf-8', 'replace')))


def restore_from(path):
    """Replaces the current database with the archive at `path` in one transaction (all or nothing)."""
    if not is_postgres():
        raise BackupError('بازیابی فقط برای پایگاه داده PostgreSQL فعال است.')
    command = [_require_tool('pg_restore'), '--clean', '--if-exists', '--no-owner', '--no-privileges',
               '--single-transaction', '--exit-on-error', '--no-password', *_connection_args(),
               '-d', database_name(), str(path)]
    environment = _environment()
    # Don't wait forever behind a lock held by another request; the whole restore then rolls back.
    environment['PGOPTIONS'] = (environment.get('PGOPTIONS', '') + ' -c lock_timeout=120000').strip()
    connection.close()  # this request's own connection must not hold locks on the tables being replaced
    try:
        result = subprocess.run(command, env=environment, capture_output=True, timeout=RESTORE_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired as error:
        raise BackupError('زمان بازیابی بیش از حد طول کشید؛ تراکنش لغو شد و پایگاه داده تغییری نکرد.') from error
    except OSError as error:
        raise BackupError(f'اجرای pg_restore ممکن نشد: {error}') from error
    if result.returncode != 0:
        raise BackupError('بازیابی انجام نشد و پایگاه داده بدون تغییر ماند. خطای pg_restore: '
                          + _error_text(result.stderr.decode('utf-8', 'replace')))


def overview():
    """Facts shown on the tab: database, size, server version, tool availability, newest backup on disk."""
    info = {
        'is_postgres': is_postgres(),
        'name': database_name(),
        'host': str(_database().get('HOST') or 'localhost'),
        'size': '',
        'server_version': '',
        'pg_dump': tool_version('pg_dump'),
        'pg_restore': tool_version('pg_restore'),
        'latest_backup': None,
        'max_upload': RESTORE_MAX_BYTES,
    }
    if info['is_postgres']:
        try:
            with connection.cursor() as cursor:
                cursor.execute('SELECT pg_size_pretty(pg_database_size(current_database())), current_setting(%s)',
                               ['server_version'])
                info['size'], info['server_version'] = cursor.fetchone()
        except Exception:  # the tab must still render if the size query is not allowed
            pass
    newest = None
    for folder in safety_backup_folders():
        try:
            for path in folder.glob('db-*.dump'):
                stat = path.stat()
                if newest is None or stat.st_mtime > newest[1]:
                    newest = (path.name, stat.st_mtime, stat.st_size)
        except OSError:
            continue
    if newest:
        info['latest_backup'] = {
            'name': newest[0],
            'at': datetime.fromtimestamp(newest[1], tz=timezone.get_current_timezone()),
            'size_mb': round(newest[2] / (1024 * 1024), 2),
        }
    return info


def can_manage(user):
    """Backup / restore: the system admin (the panel's admin role, checked by the view) who is also a Django superuser."""
    return bool(user.is_authenticated and user.is_superuser and user.is_active)


def _back():
    return redirect(f"{reverse('core:super_admin_settings')}?tab=backup")


def handle_post(request, action):
    """POST from the backup tab: settings_action = db_backup | db_restore."""
    from apps.core.views import log_activity  # views imports half the app; import here to avoid a cycle

    if not can_manage(request.user):
        return HttpResponseForbidden('پشتیبان‌گیری و بازیابی فقط برای مدیر کل (superuser) مجاز است.')

    if action == 'db_backup':
        handle = tempfile.TemporaryFile()
        try:
            dump_to(handle)
        except BackupError as error:
            handle.close()
            messages.error(request, str(error))
            return _back()
        size = handle.tell()
        handle.seek(0)
        log_activity(request.user, 'database_backup_downloaded', 'نسخه پشتیبان پایگاه داده دریافت شد.', request,
                     {'database': database_name(), 'bytes': size})
        response = FileResponse(handle, as_attachment=True, filename=download_name(),
                                content_type='application/octet-stream')
        response['Cache-Control'] = 'no-store'
        return response

    # db_restore: every check passes before anything touches the database.
    upload = request.FILES.get('backup_file')
    if not upload:
        messages.error(request, 'فایل پشتیبان انتخاب نشده است.')
        return _back()
    if not upload.name.lower().endswith(('.dump', '.backup')):
        messages.error(request, 'فقط فایل پشتیبان با پسوند ‎.dump‎ (خروجی همین صفحه) پذیرفته می‌شود.')
        return _back()
    if upload.size <= 0 or upload.size > RESTORE_MAX_BYTES:
        messages.error(request, 'حجم فایل پشتیبان مجاز نیست.')
        return _back()
    if request.POST.get('confirm_name', '').strip() != database_name():
        messages.error(request, 'نام پایگاه داده را دقیقاً همان‌طور که نمایش داده شده وارد کنید؛ بازیابی انجام نشد.')
        return _back()
    if request.POST.get('confirm_understand') != 'on':
        messages.error(request, 'تأیید «از جایگزینی کامل داده‌ها آگاهم» لازم است؛ بازیابی انجام نشد.')
        return _back()
    if not request.user.check_password(request.POST.get('current_password', '')):
        messages.error(request, 'گذرواژه فعلی درست نیست؛ بازیابی انجام نشد.')
        return _back()

    temporary = None
    try:
        if hasattr(upload, 'temporary_file_path'):
            source = upload.temporary_file_path()
        else:
            temporary = tempfile.NamedTemporaryFile(suffix='.dump', delete=False)
            for chunk in upload.chunks():
                temporary.write(chunk)
            temporary.close()
            source = temporary.name
        check_dump_file(source)
        from apps.core.auto_backup import exclusive  # same lock as the scheduled backups (auto_backup.py)
        with exclusive() as acquired:
            if not acquired:
                raise BackupError('یک پشتیبان‌گیری خودکار در حال انجام است؛ چند دقیقه دیگر دوباره تلاش کنید. '
                                  'بازیابی انجام نشد.')
            safety = write_safety_backup()
            actor = request.user.get_username()
            restore_from(source)
    except BackupError as error:
        messages.error(request, str(error))
        return _back()
    finally:
        if temporary is not None:
            Path(temporary.name).unlink(missing_ok=True)
    try:
        log_activity(request.user, 'database_restored', 'پایگاه داده از فایل پشتیبان بازیابی شد.', request,
                     {'database': database_name(), 'file': upload.name, 'safety_backup': str(safety), 'by': actor})
    except Exception:  # the restored data may not know this user; the restore itself already succeeded
        pass
    messages.success(request, f'پایگاه داده بازیابی شد. نسخه پشتیبان ایمنیِ پیش از بازیابی: {safety}. '
                              'اگر از حساب خارج شدید، با حساب موجود در فایل بازیابی‌شده وارد شوید.')
    return _back()
