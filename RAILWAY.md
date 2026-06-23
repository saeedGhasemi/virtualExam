# انتشار سایت روی Railway

Railway برای پروژه Django مناسب است و بعد از deploy می‌تواند یک آدرس عمومی مثل `https://your-app.up.railway.app` بسازد.

## مراحل

1. وارد Railway شوید: https://railway.com
2. `New Project` را بزنید.
3. `Deploy from GitHub repo` را انتخاب کنید.
4. repository را انتخاب کنید: `saeedGhasemi/virtualExam`
5. یک سرویس PostgreSQL اضافه کنید:
   - داخل همان پروژه روی `Create` بزنید.
   - `Database` سپس `Add PostgreSQL` را انتخاب کنید.
6. در سرویس Django، بخش `Variables` این‌ها را بگذارید:

```text
DEBUG=False
ALLOWED_HOSTS=.railway.app,localhost,127.0.0.1
SECRET_KEY=یک مقدار طولانی و تصادفی
OPENAI_API_KEY=کلید OpenAI
PGDATABASE=${{Postgres.PGDATABASE}}
PGUSER=${{Postgres.PGUSER}}
PGPASSWORD=${{Postgres.PGPASSWORD}}
PGHOST=${{Postgres.PGHOST}}
PGPORT=${{Postgres.PGPORT}}
```

7. Deploy را اجرا کنید.
8. برای گرفتن آدرس عمومی:
   - وارد سرویس Django شوید.
   - `Settings` را باز کنید.
   - در بخش `Networking` روی `Generate Domain` بزنید.

## نکته

اگر اسم سرویس دیتابیس در Railway چیزی غیر از `Postgres` بود، در variableها همان اسم را جایگزین کنید.
