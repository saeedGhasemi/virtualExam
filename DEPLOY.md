# انتشار سایت روی اینترنت

این پروژه برای deploy روی Render آماده شده است. Render به پروژه یک آدرس عمومی مثل `https://virtual-exam.onrender.com` می‌دهد و دیتابیس PostgreSQL آنلاین را هم می‌سازد.

## مراحل پیشنهادی

1. پروژه را روی GitHub push کنید.
2. وارد Render شوید و گزینه `New` سپس `Blueprint` را انتخاب کنید.
3. همین repository را وصل کنید. Render فایل `render.yaml` را می‌خواند و سرویس وب + دیتابیس را می‌سازد.
4. مقدار `OPENAI_API_KEY` را در بخش Environment وارد کنید.
5. Deploy را اجرا کنید.

## نکات مهم

- برای production مقدار `DEBUG` باید `False` باشد.
- فایل `.env` و `db.sqlite3` نباید روی GitHub بروند.
- دیتای فعلی داخل `db.sqlite3` محلی است. اگر لازم است همین داده‌ها آنلاین شوند، باید جداگانه به PostgreSQL منتقل شوند.
- فایل‌های آپلودی کاربرها روی هاست‌های رایگان پایدار نیستند مگر storage جداگانه مثل S3 یا یک persistent disk تنظیم شود.

## اجرای محلی قبل از deploy

```bash
python manage.py check
python manage.py migrate
npm run build:css
python manage.py collectstatic --no-input
```
