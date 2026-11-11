from pathlib import Path
import os
import sys
import importlib.util
from urllib.parse import parse_qsl, unquote, urlparse
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / '.env', override=True)

# Every secret (SECRET_KEY, database/e-mail passwords) comes only from the environment / .env, never from the code
# (Security.md). With DEBUG off, `manage.py check` fails on a missing or placeholder SECRET_KEY (apps/core/checks.py).
SECRET_KEY = os.getenv('SECRET_KEY', 'django-insecure-local-development-only')
# Off unless .env says DEBUG=True (local development), so a missing or partial .env never runs production in debug mode.
DEBUG = os.getenv('DEBUG', 'False').lower() == 'true'
ALLOWED_HOSTS = [host.strip() for host in os.getenv(
    'ALLOWED_HOSTS', 'metaquizy.ir,www.metaquizy.ir,127.0.0.1,localhost,37.32.4.207').split(',') if host.strip()]
RENDER_EXTERNAL_HOSTNAME = os.getenv('RENDER_EXTERNAL_HOSTNAME', '').strip()
if RENDER_EXTERNAL_HOSTNAME:
    ALLOWED_HOSTS.append(RENDER_EXTERNAL_HOSTNAME)

RAILWAY_PUBLIC_DOMAIN = os.getenv('RAILWAY_PUBLIC_DOMAIN', '').strip()
if RAILWAY_PUBLIC_DOMAIN:
    ALLOWED_HOSTS.append(RAILWAY_PUBLIC_DOMAIN)

CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.getenv('CSRF_TRUSTED_ORIGINS', 'https://metaquizy.ir,https://www.metaquizy.ir,https://37.32.4.207').split(',')
    if origin.strip()
]
if RENDER_EXTERNAL_HOSTNAME:
    CSRF_TRUSTED_ORIGINS.append(f'https://{RENDER_EXTERNAL_HOSTNAME}')
if RAILWAY_PUBLIC_DOMAIN:
    CSRF_TRUSTED_ORIGINS.append(f'https://{RAILWAY_PUBLIC_DOMAIN}')

HAS_WHITENOISE = importlib.util.find_spec('whitenoise') is not None

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'apps.core',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'apps.core.middleware.MalformedIdNotFoundMiddleware',
    'apps.core.exam_schedule.ScheduledPublishMiddleware',
    'apps.core.middleware.PasswordChangeRequiredMiddleware',
    'apps.core.exam_lock.ExamLockMiddleware',
    'apps.core.middleware.SecurityHeadersMiddleware',
    'apps.core.auto_backup.AutoBackupSchedulerMiddleware',
]

if HAS_WHITENOISE:
    MIDDLEWARE.insert(1, 'whitenoise.middleware.WhiteNoiseMiddleware')

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'apps.core.navigation.app_shell',
                'apps.core.context_processors.panel_user',
                'apps.core.appearance.appearance_context',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'
ASGI_APPLICATION = 'config.asgi.application'

DATABASE_URL = os.getenv('DATABASE_URL', '').strip()
DB_ENGINE = os.getenv('DB_ENGINE', 'sqlite').strip().lower()

if DATABASE_URL:
    db_url = urlparse(DATABASE_URL)
    db_options = dict(parse_qsl(db_url.query))

    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': unquote(db_url.path.lstrip('/')),
            'USER': unquote(db_url.username or ''),
            'PASSWORD': unquote(db_url.password or ''),
            'HOST': db_url.hostname or '',
            'PORT': str(db_url.port or ''),
        }
    }

    if db_options:
        DATABASES['default']['OPTIONS'] = db_options
elif DB_ENGINE == 'postgres':
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': os.getenv('POSTGRES_DB', 'virtual_exam'),
            'USER': os.getenv('POSTGRES_USER', 'postgres'),
            'PASSWORD': os.getenv('POSTGRES_PASSWORD', 'postgres'),
            'HOST': os.getenv('POSTGRES_HOST', '127.0.0.1'),
            'PORT': os.getenv('POSTGRES_PORT', '5432'),
        }
    }
elif os.getenv('PGHOST', '').strip():
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': os.getenv('PGDATABASE', 'railway'),
            'USER': os.getenv('PGUSER', 'postgres'),
            'PASSWORD': os.getenv('PGPASSWORD', ''),
            'HOST': os.getenv('PGHOST', ''),
            'PORT': os.getenv('PGPORT', '5432'),
        }
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }

if DATABASES['default']['ENGINE'] == 'django.db.backends.postgresql':
    DATABASES['default']['CONN_MAX_AGE'] = int(os.getenv('DB_CONN_MAX_AGE', '60'))
    DATABASES['default']['CONN_HEALTH_CHECKS'] = True
    DATABASES['default'].setdefault('OPTIONS', {})
    DATABASES['default']['OPTIONS'].setdefault('connect_timeout', int(os.getenv('DB_CONNECT_TIMEOUT', '5')))
    DATABASES['default']['OPTIONS'].setdefault('application_name', os.getenv('DB_APPLICATION_NAME', 'virtual_exam_panel'))

CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': os.getenv('DJANGO_CACHE_LOCATION', 'virtual-exam-default'),
        'TIMEOUT': int(os.getenv('DJANGO_CACHE_TIMEOUT', '300')),
        'OPTIONS': {
            'MAX_ENTRIES': int(os.getenv('DJANGO_CACHE_MAX_ENTRIES', '50000')),
        },
    }
}

SESSION_ENGINE = os.getenv('SESSION_ENGINE', 'django.contrib.sessions.backends.cached_db')
SESSION_COOKIE_AGE = int(os.getenv('SESSION_COOKIE_AGE', str(60 * 60 * 8)))

# Brute-force protection of the sign-in page (apps/core/auth_guard.py, Auth.md). Counted in auth_events, so the limit
# is shared by all gunicorn workers.
LOGIN_MAX_FAILED_PER_USER = int(os.getenv('LOGIN_MAX_FAILED_PER_USER', '5'))
LOGIN_MAX_FAILED_PER_IP = int(os.getenv('LOGIN_MAX_FAILED_PER_IP', '100'))
LOGIN_LOCK_MINUTES = int(os.getenv('LOGIN_LOCK_MINUTES', '15'))
# How long sign-in audit rows are kept before `manage.py purge_expired_data` removes them (Data.md).
AUTH_EVENTS_RETENTION_DAYS = int(os.getenv('AUTH_EVENTS_RETENTION_DAYS', '365'))
# Proxies in front of gunicorn that append to X-Forwarded-For (nginx = 1). Only those hops are trusted for the
# client IP; 0 ignores the header (gunicorn reached directly).
TRUSTED_PROXY_COUNT = int(os.getenv('TRUSTED_PROXY_COUNT', '1'))

EXAM_MAX_CONCURRENT_STUDENTS = int(os.getenv('EXAM_MAX_CONCURRENT_STUDENTS', '1500'))
EXAM_MAX_CONCURRENT_TEACHERS = int(os.getenv('EXAM_MAX_CONCURRENT_TEACHERS', '300'))

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator', 'OPTIONS': {'min_length': 8}},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# Passwords are stored only as salted, slow hashes (Security.md). PBKDF2-SHA256 (Django's default, 870k+ iterations)
# signs new passwords; Argon2id becomes the primary hasher when PASSWORD_HASHER=argon2 and argon2-cffi is installed.
# The later entries only verify older hashes, which are upgraded to the primary one at the next sign-in.
_ARGON2 = 'django.contrib.auth.hashers.Argon2PasswordHasher'
PASSWORD_HASHERS = [
    'django.contrib.auth.hashers.PBKDF2PasswordHasher',
    'django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher',
    'django.contrib.auth.hashers.ScryptPasswordHasher',
]
if importlib.util.find_spec('argon2') is not None:
    if os.getenv('PASSWORD_HASHER', '').strip().lower() == 'argon2':
        PASSWORD_HASHERS.insert(0, _ARGON2)
    else:
        PASSWORD_HASHERS.append(_ARGON2)

LANGUAGE_CODE = 'fa-ir'
TIME_ZONE = 'Asia/Tehran'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'
# Folder of database backups (automatic ones go here; empty: BASE_DIR/backups). See apps/core/auto_backup.py.
BACKUP_DIR = os.getenv('BACKUP_DIR', '').strip()
# Each web process runs the automatic-backup scheduler thread (schedule set in the admin's backup tab); 0 turns it
# off, e.g. when `manage.py backup_database --scheduled` runs from cron instead. Never on during tests.
AUTO_BACKUP_SCHEDULER = (os.getenv('AUTO_BACKUP_SCHEDULER', '1').strip().lower() not in ('0', 'false', 'no', 'off')
                         and 'test' not in sys.argv[1:2])
# Never mapped to a URL: student answer files are streamed by views after an access check.
PRIVATE_MEDIA_ROOT = Path(os.getenv('PRIVATE_MEDIA_ROOT', str(BASE_DIR / 'private_media')))

STORAGES = {
    'default': {
        'BACKEND': 'django.core.files.storage.FileSystemStorage',
    },
    'staticfiles': {
        'BACKEND': (
            'whitenoise.storage.CompressedManifestStaticFilesStorage'
            if HAS_WHITENOISE
            else 'django.contrib.staticfiles.storage.StaticFilesStorage'
        ),
    },
}

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

LOGIN_URL = '/login/'
LOGIN_REDIRECT_URL = '/dashboard/'
LOGOUT_REDIRECT_URL = '/'

# اجازه می‌دهد authenticate() برای کاربران is_active=False هم شیء کاربر را برگرداند
# تا StyledAuthenticationForm.confirm_login_allowed بتواند پیام اختصاصی (در انتظار
# تأیید مدیر سیستم / رد شده / مسدود) نشان دهد، نه پیام عمومی «ورود نامعتبر» جنگو.
AUTHENTICATION_BACKENDS = ['django.contrib.auth.backends.AllowAllUsersModelBackend']

# --- Transport, cookies and headers (Security.md, Hack.md) ---------------------------------------------------
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
# Cookies: never readable by page scripts (HttpOnly), only sent over HTTPS when DEBUG is off (Secure), and not sent on
# cross-site sub-requests or POSTs (SameSite=Lax), so a stolen-session XSS or a cross-site form cannot use them.
SESSION_COOKIE_SECURE = os.getenv('SESSION_COOKIE_SECURE', str(not DEBUG)).lower() == 'true'
CSRF_COOKIE_SECURE = os.getenv('CSRF_COOKIE_SECURE', str(not DEBUG)).lower() == 'true'
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = True  # the pages send the token from the form field ({% csrf_token %}), never from the cookie
SESSION_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_SAMESITE = 'Lax'
# http -> https: on by default with DEBUG off (nginx forwards X-Forwarded-Proto, see SECURE_PROXY_SSL_HEADER).
SECURE_SSL_REDIRECT = os.getenv('SECURE_SSL_REDIRECT', str(not DEBUG)).lower() == 'true'
# HSTS: production sets SECURE_HSTS_SECONDS in .env; with DEBUG off and nothing set, one day. Subdomains / preload only
# when .env opts in (preload is hard to undo).
SECURE_HSTS_SECONDS = int(os.getenv('SECURE_HSTS_SECONDS', '0' if DEBUG else '86400'))
SECURE_HSTS_INCLUDE_SUBDOMAINS = os.getenv('SECURE_HSTS_INCLUDE_SUBDOMAINS', 'false').lower() == 'true'
SECURE_HSTS_PRELOAD = os.getenv('SECURE_HSTS_PRELOAD', 'false').lower() == 'true'
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = 'same-origin'
X_FRAME_OPTIONS = 'DENY'
# مرورگر هدر COOP را فقط روی HTTPS/localhost می‌پذیرد؛ روی استقرار HTTP (مثلاً با IP)
# مقدار خالی بدهید تا هدر ارسال نشود و خطای کنسول ایجاد نکند.
SECURE_CROSS_ORIGIN_OPENER_POLICY = os.getenv('SECURE_CROSS_ORIGIN_OPENER_POLICY', 'same-origin').strip() or None

# ایمیل اطلاع‌رسانی آزمون («ارسال ایمیل اطلاع‌رسانی» در ویزارد آزمون). بدون EMAIL_HOST ایمیلی ارسال نمی‌شود
# و فقط اعلان داخل سامانه می‌رود.
EMAIL_HOST = os.getenv('EMAIL_HOST', '').strip()
EMAIL_PORT = int(os.getenv('EMAIL_PORT', '587'))
EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER', '').strip()
EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD', '')
EMAIL_USE_TLS = os.getenv('EMAIL_USE_TLS', 'true').lower() == 'true'
EMAIL_TIMEOUT = int(os.getenv('EMAIL_TIMEOUT', '10'))
DEFAULT_FROM_EMAIL = os.getenv('DEFAULT_FROM_EMAIL', EMAIL_HOST_USER or 'no-reply@localhost').strip()
