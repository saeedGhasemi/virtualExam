# -----------------------------------------------------------------------------
# بخش DATABASES در config/settings.py
# جایگزین کامل بخش قبلی که به SQLite در dev سقوط می‌کرد.
# فقط PostgreSQL — اگر متغیرهای محیطی موجود نباشند، برنامه باید با خطای صریح
# متوقف شود، نه اینکه بی‌صدا به SQLite برگردد.
# -----------------------------------------------------------------------------

import os
import sys

REQUIRED_DB_ENV_VARS = [
    "DB_NAME",
    "DB_USER",
    "DB_PASSWORD",
    "DB_HOST",
    "DB_PORT",
]

_missing = [name for name in REQUIRED_DB_ENV_VARS if not os.getenv(name)]
if _missing:
    sys.stderr.write(
        "خطای پیکربندی: متغیرهای محیطی دیتابیس ناقصاند: "
        + ", ".join(_missing)
        + "\nاین پروژه دیگر به SQLite سقوط نمی‌کند، لطفاً یک فایل .env معتبر "
        "با اتصال PostgreSQL فراهم کنید.\n"
    )
    raise RuntimeError("پیکربندی دیتابیس PostgreSQL ناقص است.")

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("DB_NAME"),
        "USER": os.getenv("DB_USER"),
        "PASSWORD": os.getenv("DB_PASSWORD"),
        "HOST": os.getenv("DB_HOST", "localhost"),
        "PORT": os.getenv("DB_PORT", "5432"),
        # اتصال پایدار برای گونیکورن با چند worker
        "CONN_MAX_AGE": int(os.getenv("DB_CONN_MAX_AGE", "60")),
        # sslmode برای اتصال به دیتابیس مدیریت‌شده (مثل RDS/DigitalOcean) در production
        # در dev می‌توان "disable" گذاشت.
        "OPTIONS": {
            "sslmode": os.getenv("DB_SSLMODE", "prefer"),
            "connect_timeout": 10,
        },
    }
}

# اگر بخش JSONField بومی پستگرس استفاده می‌شود (که در models استفاده شده)،
# نیازی به تنظیم اضافه نیست — django.db.models.JSONField روی پستگرس خودکار
# از نوع ستون jsonb استفاده می‌کند.
