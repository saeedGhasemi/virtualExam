"""Scheduled (automatic) database backups: «تنظیمات سامانه» → «پشتیبان‌گیری و بازیابی» → «پشتیبان‌گیری خودکار».

How it runs — nothing to install or schedule on the server:
- Every web process starts one daemon thread on its first request (AutoBackupSchedulerMiddleware). The thread wakes
  about once a minute and calls run(). Only when a backup is due does it take a PostgreSQL advisory lock on its own
  connection, so one process in the whole deployment backs up at a time (restores take the same lock), and the
  state in system_settings makes each scheduled slot run once. `manage.py backup_database --scheduled` does the
  same from cron, if one is ever wanted. AUTO_BACKUP_SCHEDULER=0 in .env turns the thread off (tests: always off).
- Schedule (Tehran time): every N hours / daily / weekly at HH:MM. A slot missed while the site was down is caught up
  once when it comes back (like anacron); a failed slot is retried up to MAX_TRIES times, RETRY_AFTER apart.
- Files: db-YYYYMMDD-HHMMSS-auto.dump (pg_dump -Fc via db_backup.dump_to, written as a hidden .partial, checked with
  pg_restore --list, then renamed, mode 600) in BACKUP_DIR, else BASE_DIR/backups. Only after a good backup are the
  *-auto.dump files beyond the newest `keep` removed; manual / before-restore files are never removed automatically.
- Config and state are two JSON rows in system_settings (CONFIG_KEY, STATE_KEY).
"""
import json
import logging
import os
import random
import re
import shutil
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone as dt_timezone
from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.db import DatabaseError, connection, connections, transaction
from django.http import FileResponse, HttpResponseForbidden
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone

from apps.core import db_backup
from apps.core.db_backup import BackupError

logger = logging.getLogger(__name__)

CONFIG_KEY = 'auto_backup.config'
STATE_KEY = 'auto_backup.state'
LOCK_KEY = 7_412_030_955  # pg advisory lock id of «backup / restore in progress»
TICK_SECONDS = 60
MAX_TRIES = 3
RETRY_AFTER = timedelta(minutes=30)
MIN_FREE_BYTES = 100 * 1024 ** 2
AUTO_SUFFIX = '-auto.dump'
FILE_NAME = re.compile(r'^db-[0-9]{8}-[0-9]{6}(?:-[a-z-]+)?\.dump$')

FREQUENCIES = (('hours', 'هر چند ساعت'), ('daily', 'روزانه'), ('weekly', 'هفتگی'))
HOUR_STEPS = (1, 2, 3, 4, 6, 8, 12)
WEEKDAYS = ((5, 'شنبه'), (6, 'یکشنبه'), (0, 'دوشنبه'), (1, 'سه‌شنبه'), (2, 'چهارشنبه'), (3, 'پنجشنبه'), (4, 'جمعه'))
KEEP_MIN, KEEP_MAX = 1, 365
DEFAULT_CONFIG = {'enabled': True, 'frequency': 'daily', 'every_hours': 6, 'time': '03:00', 'weekday': 4, 'keep': 14}


# ---------------------------------------------------------------- config / state (system_settings rows)

def _read(key):
    try:
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute('SELECT value FROM system_settings WHERE key = %s', [key])
            row = cursor.fetchone()
    except DatabaseError:
        return None
    if not row or row[0] in (None, ''):
        return None
    try:
        value = json.loads(row[0]) if isinstance(row[0], str) else row[0]
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _write(key, value, description, profile_id=None):
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO system_settings (key, value, description, updated_by)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_by = excluded.updated_by
            """,
            [key, json.dumps(value, ensure_ascii=False), description, profile_id],
        )


def clean_config(raw):
    """A complete, valid config from any dict (stored row or posted form); invalid values fall back to defaults."""
    raw = raw if isinstance(raw, dict) else {}
    config = dict(DEFAULT_CONFIG)
    enabled = raw.get('enabled', config['enabled'])
    config['enabled'] = enabled is True or str(enabled).lower() in ('1', 'true', 'on', 'yes')
    if raw.get('frequency') in dict(FREQUENCIES):
        config['frequency'] = raw['frequency']
    try:
        if int(raw.get('every_hours')) in HOUR_STEPS:
            config['every_hours'] = int(raw['every_hours'])
    except (TypeError, ValueError):
        pass
    match = re.fullmatch(r'([01]?[0-9]|2[0-3]):([0-5][0-9])', str(raw.get('time') or '').strip())
    if match:
        config['time'] = f'{int(match.group(1)):02d}:{match.group(2)}'
    try:
        if int(raw.get('weekday')) in dict(WEEKDAYS):
            config['weekday'] = int(raw['weekday'])
    except (TypeError, ValueError):
        pass
    try:
        config['keep'] = min(KEEP_MAX, max(KEEP_MIN, int(raw.get('keep'))))
    except (TypeError, ValueError):
        pass
    return config


def load_config():
    return clean_config(_read(CONFIG_KEY))


def save_config(values, profile_id=None):
    config = clean_config(values)
    _write(CONFIG_KEY, config, 'Automatic database backup schedule', profile_id)
    return config


def load_state():
    return _read(STATE_KEY) or {}


def _save_state(state):
    _write(STATE_KEY, state, 'Automatic database backup status (written by the scheduler)')


def _moment(value):
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return moment if timezone.is_aware(moment) else timezone.make_aware(moment, dt_timezone.utc)


# ---------------------------------------------------------------- schedule

def period(config):
    if config['frequency'] == 'hours':
        return timedelta(hours=config['every_hours'])
    return timedelta(days=7 if config['frequency'] == 'weekly' else 1)


def latest_slot(config, now=None):
    """The most recent scheduled moment at or before `now` (aware, Tehran time)."""
    now = timezone.localtime(now or timezone.now())
    hour, minute = (int(part) for part in config['time'].split(':'))
    anchor = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if config['frequency'] == 'weekly':
        anchor -= timedelta(days=(anchor.weekday() - config['weekday']) % 7)
    step = period(config)
    return timezone.localtime(anchor + ((now - anchor) // step) * step)


def next_slot(config, now=None):
    return timezone.localtime(latest_slot(config, now) + period(config))


def is_due(config, state, now=None):
    if not config['enabled']:
        return False
    now = now or timezone.now()
    slot = latest_slot(config, now)
    attempt = _moment(state.get('last_attempt_at'))
    if attempt is None or attempt < slot:
        return True
    return (state.get('last_status') == 'error' and state.get('failed_slot') == int(slot.timestamp())
            and int(state.get('failures') or 0) < MAX_TRIES and now - attempt >= RETRY_AFTER)


def schedule_text(config):
    at = config['time']
    if config['frequency'] == 'hours':
        return f'هر {config["every_hours"]} ساعت (از ساعت {at})'
    if config['frequency'] == 'weekly':
        return f'هر هفته، {dict(WEEKDAYS)[config["weekday"]]} ساعت {at}'
    return f'هر روز ساعت {at}'


# ---------------------------------------------------------------- lock

_local_lock = threading.Lock()


@contextmanager
def exclusive():
    """Yields True while this process holds the deployment-wide backup/restore lock, False if someone else has it.
    PostgreSQL: an advisory lock on a connection of its own, so closing Django's connection (a restore does) keeps it
    and a crashed process releases it automatically."""
    if not db_backup.is_postgres():
        acquired = _local_lock.acquire(blocking=False)
        try:
            yield acquired
        finally:
            if acquired:
                _local_lock.release()
        return
    import psycopg

    database = settings.DATABASES['default']
    params = {'dbname': database.get('NAME'), 'autocommit': True, 'connect_timeout': 10}
    for option, key in (('user', 'USER'), ('password', 'PASSWORD'), ('host', 'HOST'), ('port', 'PORT')):
        if database.get(key):
            params[option] = str(database[key])
    sslmode = (database.get('OPTIONS') or {}).get('sslmode')
    if sslmode:
        params['sslmode'] = sslmode
    try:
        lock_connection = psycopg.connect(**params)
    except psycopg.Error as error:
        raise BackupError(f'اتصال جداگانه به پایگاه داده برای قفل پشتیبان‌گیری ممکن نشد: {error}') from error
    try:
        acquired = bool(lock_connection.execute('SELECT pg_try_advisory_lock(%s)', [LOCK_KEY]).fetchone()[0])
        try:
            yield acquired
        finally:
            if acquired:
                try:
                    lock_connection.execute('SELECT pg_advisory_unlock(%s)', [LOCK_KEY])
                except psycopg.Error:
                    pass  # closing the connection below releases it anyway
    finally:
        lock_connection.close()


def is_running():
    try:
        with exclusive() as acquired:
            return not acquired
    except BackupError:
        return False


# ---------------------------------------------------------------- files

def backup_folder():
    return Path(settings.BACKUP_DIR) if getattr(settings, 'BACKUP_DIR', '') else Path(settings.BASE_DIR) / 'backups'


def _writable_folder():
    folder = backup_folder()
    try:
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        probe = folder / f'.write-test-{os.getpid()}-{threading.get_ident()}'
        probe.write_bytes(b'')
        probe.unlink()
    except OSError as error:
        raise BackupError(f'پوشه نسخه‌های پشتیبان قابل نوشتن نیست: {folder} ({error.strerror or error}). '
                          'مسیر BACKUP_DIR را در ‎.env‎ به پوشه‌ای قابل نوشتن برای سرویس سامانه تنظیم کنید.') from error
    return folder


def _auto_files(folder):
    try:
        return sorted((path for path in folder.glob(f'db-*{AUTO_SUFFIX}') if FILE_NAME.match(path.name)),
                      key=lambda path: path.name, reverse=True)
    except OSError:
        return []


def _check_free_space(folder):
    newest = _auto_files(folder)[:1]
    need = MIN_FREE_BYTES
    try:
        if newest:
            need = max(need, 2 * newest[0].stat().st_size)
        free = shutil.disk_usage(folder).free
    except OSError:
        return
    if free < need:
        raise BackupError(f'فضای خالی دیسک کافی نیست ({round(free / 1024 ** 2)} مگابایت آزاد، دست‌کم '
                          f'{round(need / 1024 ** 2)} مگابایت لازم است). نسخه‌های قدیمی را حذف یا فضای دیسک را بیشتر کنید.')


def _make_backup():
    folder = _writable_folder()
    _check_free_space(folder)
    stamp = timezone.localtime().strftime('%Y%m%d-%H%M%S')
    final = folder / f'db-{stamp}{AUTO_SUFFIX}'
    partial = folder / f'.{final.name}.partial'
    try:
        db_backup.dump_to(partial)
        db_backup.check_dump_file(partial)  # a backup that pg_restore cannot read is not kept
        try:
            os.chmod(partial, 0o600)  # personal data and password hashes: owner only
        except OSError:
            pass
        os.replace(partial, final)
    finally:
        partial.unlink(missing_ok=True)
    return final


def prune(keep, folder=None):
    """Removes *-auto.dump files beyond the newest `keep`, and stale .partial leftovers of killed runs."""
    folder = folder or backup_folder()
    removed = 0
    for path in _auto_files(folder)[keep:]:
        try:
            path.unlink()
            removed += 1
        except OSError:
            logger.warning('Could not remove old automatic backup %s', path)
    try:
        for path in folder.glob('.db-*.partial'):
            if time.time() - path.stat().st_mtime > 86400:
                path.unlink(missing_ok=True)
    except OSError:
        pass
    return removed


def stored_backups():
    """Every db-*.dump on this server (auto folder + the restore-safety folders), newest first."""
    seen, items = set(), []
    for folder in [backup_folder(), *db_backup.safety_backup_folders()]:
        try:
            paths = list(folder.glob('db-*.dump'))
        except OSError:
            continue
        for path in paths:
            if path.name in seen or not FILE_NAME.match(path.name):
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            seen.add(path.name)
            if path.name.endswith(AUTO_SUFFIX):
                kind = 'auto'
            elif path.name.endswith('-before-restore.dump'):
                kind = 'safety'
            else:
                kind = 'manual'
            items.append({
                'name': path.name, 'path': path, 'kind': kind,
                'kind_label': {'auto': 'خودکار', 'safety': 'پیش از بازیابی', 'manual': 'دستی (فرمان سرور)'}[kind],
                'size': stat.st_size, 'size_mb': round(stat.st_size / 1024 ** 2, 2),
                'at': datetime.fromtimestamp(stat.st_mtime, tz=timezone.get_current_timezone()),
            })
    items.sort(key=lambda item: item['at'], reverse=True)
    return items


def _find_stored(name):
    name = os.path.basename(str(name or ''))
    return next((item for item in stored_backups() if item['name'] == name), None) if FILE_NAME.match(name) else None


# ---------------------------------------------------------------- running a backup

def run(trigger='scheduler', force=False):
    """One scheduled backup if it is due (or now, with force). Returns {'status': ok|error|busy|not_due|disabled|
    unsupported, 'message', 'file'}; never raises for an expected failure, which is recorded in the state."""
    if not db_backup.is_postgres():
        return {'status': 'unsupported', 'message': 'پشتیبان‌گیری خودکار فقط برای PostgreSQL فعال است.'}
    config = load_config()
    if not force:
        if not config['enabled']:
            return {'status': 'disabled', 'message': 'پشتیبان‌گیری خودکار خاموش است.'}
        if not is_due(config, load_state()):
            return {'status': 'not_due', 'message': ''}
    try:
        with exclusive() as acquired:
            if not acquired:
                return {'status': 'busy', 'message': 'یک پشتیبان‌گیری یا بازیابی دیگر در حال انجام است؛ چند دقیقه دیگر دوباره تلاش کنید.'}
            return _run_locked(trigger, force)
    except BackupError as error:  # the lock connection itself failed
        return {'status': 'error', 'message': str(error)}


def _run_locked(trigger, force):
    config, state = load_config(), load_state()
    now = timezone.now()
    if not force and not (config['enabled'] and is_due(config, state, now)):  # another process just did it
        return {'status': 'not_due', 'message': ''}
    slot = int(latest_slot(config, now).timestamp())
    state.update({'last_attempt_at': now.isoformat(), 'last_trigger': trigger})
    _save_state(state)
    began = time.monotonic()
    try:
        path = _make_backup()
        removed = prune(config['keep'], path.parent)
    except BackupError as error:
        message = str(error)
    except Exception as error:  # noqa: BLE001 — record anything unexpected instead of killing the scheduler
        logger.exception('Automatic database backup failed.')
        message = f'خطای پیش‌بینی‌نشده: {error}'
    else:
        size = path.stat().st_size
        state.update({
            'last_status': 'ok', 'last_error': '', 'last_success_at': timezone.now().isoformat(),
            'last_file': path.name, 'last_size': size, 'last_duration': round(time.monotonic() - began, 1),
            'failures': 0, 'failed_slot': None,
        })
        _save_state(state)
        logger.info('Automatic database backup written: %s (%s bytes, %s removed)', path, size, removed)
        return {'status': 'ok', 'message': f'نسخه پشتیبان {path.name} ساخته شد.', 'file': path.name, 'removed': removed}
    failures = int(state.get('failures') or 0) + 1 if state.get('failed_slot') == slot else 1
    state.update({'last_status': 'error', 'last_error': message[:1000], 'failed_slot': slot, 'failures': failures,
                  'last_duration': round(time.monotonic() - began, 1)})
    _save_state(state)
    logger.error('Automatic database backup failed: %s', message)
    try:
        from apps.core.views import log_activity  # views imports half the app; import here to avoid a cycle
        log_activity(None, 'database_auto_backup_failed', 'پشتیبان‌گیری خودکار پایگاه داده ناموفق بود.',
                     None, {'error': message[:500], 'trigger': trigger})
    except Exception:  # noqa: BLE001 — the failure is already in the state row
        pass
    return {'status': 'error', 'message': message}


# ---------------------------------------------------------------- in-process scheduler

_thread = None
_thread_guard = threading.Lock()


def scheduler_enabled():
    return bool(getattr(settings, 'AUTO_BACKUP_SCHEDULER', False))


def ensure_scheduler():
    """Starts this process's scheduler thread once (called on every request; cheap after the first)."""
    global _thread
    if _thread is not None or not scheduler_enabled():
        return
    with _thread_guard:
        if _thread is None:
            _thread = threading.Thread(target=_loop, name='metaquizy-auto-backup', daemon=True)
            _thread.start()


def _loop():
    time.sleep(random.uniform(20, 60))  # let the process finish starting; spread the workers apart
    while True:
        try:
            run('scheduler')
        except Exception:  # noqa: BLE001 — the thread must survive anything
            logger.exception('Automatic backup scheduler tick failed.')
        finally:
            connections.close_all()  # this thread's own connections only
        time.sleep(TICK_SECONDS + random.uniform(0, 15))


class AutoBackupSchedulerMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        ensure_scheduler()  # here, not in __init__: with a preloaded app __init__ runs in the master before fork
        return self.get_response(request)


# ---------------------------------------------------------------- page data, dashboard health, POST actions

def overview():
    config, state = load_config(), load_state()
    now = timezone.now()
    files = stored_backups()
    auto_files = [item for item in files if item['kind'] == 'auto']
    last_success = _moment(state.get('last_success_at'))
    return {
        'config': config,
        'schedule_text': schedule_text(config),
        'next_run': next_slot(config, now) if config['enabled'] else None,
        'due_now': is_due(config, state, now),
        'last_attempt': _moment(state.get('last_attempt_at')),
        'last_success': last_success,
        'last_status': state.get('last_status') or '',
        'last_error': state.get('last_error') or '',
        'last_file': state.get('last_file') or '',
        'last_size_mb': round((state.get('last_size') or 0) / 1024 ** 2, 2),
        'last_duration': state.get('last_duration'),
        'failures': int(state.get('failures') or 0),
        'retries_left': state.get('last_status') == 'error' and int(state.get('failures') or 0) < MAX_TRIES,
        'running': is_running() if db_backup.is_postgres() else False,
        'folder': str(backup_folder()),
        'files': files,
        'auto_count': len(auto_files),
        'total_mb': round(sum(item['size'] for item in files) / 1024 ** 2, 2),
        'scheduler_on': scheduler_enabled(),
        'health': health(config, state),
        'frequencies': FREQUENCIES,
        'hour_steps': HOUR_STEPS,
        'weekdays': WEEKDAYS,
        'keep_min': KEEP_MIN,
        'keep_max': KEEP_MAX,
    }


def health(config=None, state=None):
    """The admin dashboard's «پشتیبان‌گیری» line while automatic backups are on; None when they are off."""
    config = config or load_config()
    if not config['enabled'] or not db_backup.is_postgres():
        return None
    state = state if state is not None else load_state()
    last_success = _moment(state.get('last_success_at'))
    if state.get('last_status') == 'error':
        return {'status': 'خطا در آخرین پشتیبان‌گیری خودکار', 'tone': 'bad'}
    if not last_success:
        return {'status': 'در انتظار اولین نسخه خودکار', 'tone': 'warn'}
    from apps.core.templatetags.core_extras import to_jalali
    late = timezone.now() - last_success > period(config) + timedelta(hours=2)
    return {'status': f'آخرین نسخه خودکار: {to_jalali(last_success)}', 'tone': 'bad' if late else 'ok'}


def _back():
    return redirect(f"{reverse('core:super_admin_settings')}?tab=backup")


POST_ACTIONS = ('auto_backup_save', 'auto_backup_run', 'auto_backup_download', 'auto_backup_delete')


def handle_post(request, action):
    from apps.core.views import erd_profile_for_user, log_activity  # avoid an import cycle with views

    if not db_backup.can_manage(request.user):
        return HttpResponseForbidden('پشتیبان‌گیری فقط برای مدیر کل (superuser) مجاز است.')

    if action == 'auto_backup_save':
        profile = erd_profile_for_user(request.user)
        config = save_config({
            'enabled': request.POST.get('enabled'), 'frequency': request.POST.get('frequency'),
            'every_hours': request.POST.get('every_hours'), 'time': request.POST.get('time'),
            'weekday': request.POST.get('weekday'), 'keep': request.POST.get('keep'),
        }, profile['id'] if profile else None)
        log_activity(request.user, 'database_auto_backup_settings', 'تنظیمات پشتیبان‌گیری خودکار ذخیره شد.', request, config)
        if config['enabled']:
            messages.success(request, f'پشتیبان‌گیری خودکار فعال شد: {schedule_text(config)}؛ '
                                      f'{config["keep"]} نسخه آخر نگه داشته می‌شود.')
        else:
            messages.success(request, 'پشتیبان‌گیری خودکار خاموش شد.')
        return _back()

    if action == 'auto_backup_run':
        result = run('manual', force=True)
        if result['status'] == 'ok':
            log_activity(request.user, 'database_auto_backup_run', 'پشتیبان‌گیری روی سرور به‌صورت دستی اجرا شد.',
                         request, {'file': result.get('file')})
            messages.success(request, result['message'])
        else:
            messages.error(request, result['message'] or 'پشتیبان‌گیری انجام نشد.')
        return _back()

    item = _find_stored(request.POST.get('file'))
    if not item:
        messages.error(request, 'این نسخه پشتیبان روی سرور پیدا نشد.')
        return _back()

    if action == 'auto_backup_download':
        try:
            handle = open(item['path'], 'rb')
        except OSError:
            messages.error(request, 'خواندن فایل پشتیبان ممکن نشد.')
            return _back()
        log_activity(request.user, 'database_backup_downloaded', 'نسخه پشتیبان ذخیره‌شده روی سرور دریافت شد.', request,
                     {'file': item['name'], 'bytes': item['size']})
        response = FileResponse(handle, as_attachment=True, filename=f'metaquizy-{db_backup.database_name()}-{item["name"]}',
                                content_type='application/octet-stream')
        response['Cache-Control'] = 'no-store'
        return response

    # auto_backup_delete
    try:
        item['path'].unlink()
    except OSError as error:
        messages.error(request, f'حذف فایل ممکن نشد: {error.strerror or error}')
        return _back()
    log_activity(request.user, 'database_backup_deleted', 'یک نسخه پشتیبان از سرور حذف شد.', request, {'file': item['name']})
    messages.success(request, f'نسخه {item["name"]} حذف شد.')
    return _back()
