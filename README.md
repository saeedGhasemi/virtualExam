# MetaQuizy — سامانه‌ی آزمون آنلاین

سامانه‌ی برگزاری آزمون آنلاین (Django + PostgreSQL)، با چهار نقش: دانشجو، استاد، مدیر آموزش و مدیر کل.
سایت اصلی: https://metaquizy.ir

| فایل | برای چیست |
|---|---|
| `CLAUDE.md` | قواعد پروژه برای Claude (در هر چت خودکار خوانده می‌شود) |
| `PROGRESS.md` | وضعیت فعلی: چه کارهایی انجام شده، چه چیزی روی سرور است، چه چیزی مانده |
| `README.md` | همین فایل: اجرای محلی و **راهنمای ارسال به سرور** |

## اجرای محلی (ویندوز، PowerShell، در پوشه‌ی پروژه)
1. فایل `.env` را از روی `.env.example` بسازید (`DB_ENGINE=postgres` و اطلاعات PostgreSQL محلی).
2. `.venv\Scripts\python manage.py migrate`
3. `.venv\Scripts\python manage.py runserver 8001` و باز کردن http://127.0.0.1:8001
4. تست: `.venv\Scripts\python manage.py test apps.core` (یا فقط یک کلاس: `apps.core.tests.<ClassName>`)

کلیدها و رمزها فقط در `.env` (که در `.gitignore` است) یا روی سرور؛ هرگز در فایل‌های پروژه.

---

## ارسال آخرین نسخه به سرور

**قواعد ثابت:** روی سرور چیزی نصب یا جابه‌جا نمی‌شود؛ فقط فایل‌های کدی که عوض شده‌اند می‌روند. داده‌ها حذف نمی‌شوند.
ما (کاربر SSH) sudo نداریم؛ مرحله‌ی آخر را **استاد** با یک دستور `sudo` اجرا می‌کند.

اطلاعات ورود (کاربر و آدرس SSH، رمزها) **هرگز در این فایل‌ها نوشته نمی‌شود**؛ هر بار خودتان در چت یا ترمینال وارد می‌کنید.
در دستورهای زیر به‌جای `USER@HOST` همان آدرس SSH را بگذارید. مسیر برنامه روی سرور: `/srv/sites/metaquizy/app`.

**اگر با Claude کار می‌کنید:** بنویسید «آخرین نسخه رو ببر روی سرور و دامنه» و این‌ها را در همان پیام بدهید:
1. SSH کاربر عادی: `user@host` و رمز
2. دیتابیس: نام، کاربر و رمز (برای بکاپ `pg_dump`)
3. اختیاری، SSH کاربر root: `root@host` و رمز. با این، Claude مرحله‌ی آخر را هم خودش اجرا و سایت را چک می‌کند. بدون آن، یک دستور برای استاد تحویل می‌دهد.

Claude رمزها را فقط برای همان بار استفاده می‌کند و بعد پاک می‌کند. ممکن است Claude Code برای اجرا روی سرور اصلی اجازه بخواهد؛ آن را تأیید کنید.

### مرحله ۰ — روی کامپیوتر خودتان
1. همه‌ی تست‌ها سبز باشند: `.venv\Scripts\python manage.py test apps.core`
2. همه‌ی تغییرات commit شده باشند (`git status` باید خالی باشد). بسته از روی commitها ساخته می‌شود؛ چیزی که commit نشده نمی‌رود.
3. شماره‌ی نسخه را در فایل `VERSION` بالا ببرید و commit کنید (زیر لوگو نمایش داده می‌شود و با آن معلوم است نسخه‌ی جدید روی سایت آمده یا نه). قالب `MAJOR.MINOR.PATCH`: فقط رفع اشکال ← عدد آخر (`1.1.0` → `1.1.1`)؛ امکان جدید ← عدد وسط و صفر کردن آخری (`1.1.1` → `1.2.0`)؛ تغییر بزرگ و ناسازگار ← عدد اول (`2.0.0`).
4. از `PROGRESS.md` بخش «Deployment status» شناسه‌ی commit فعلی سرور را بردارید (مثلاً `1f9e4ea`). به آن می‌گوییم `OLD`.

### مرحله ۱ — ساخت بسته (PowerShell، در پوشه‌ی پروژه)
```powershell
$OLD = "1f9e4ea"                                   # commit فعلی سرور
$TS  = Get-Date -Format "yyyyMMdd-HHmm"
git diff --name-only --diff-filter=d $OLD HEAD > files.txt      # فایل‌های جدید/تغییرکرده
git diff --name-only --diff-filter=D $OLD HEAD > deleted.txt    # فایل‌های حذف‌شده (معمولاً خالی)
git -c core.autocrlf=false archive -o deploy.tar HEAD (Get-Content files.txt)   # LF, like the server
git diff --name-only $OLD HEAD -- apps/core/migrations          # اگر چیزی نشان داد، یعنی تغییر دیتابیس دارد
```
فایل‌های `files.txt`، `deleted.txt` و `deploy.tar` را بعد از ارسال پاک کنید (جزو پروژه نیستند، commit نشوند).

### مرحله ۲ — فرستادن به سرور
```powershell
ssh USER@HOST "mkdir -p ~/metaquizy-backup-$TS"
scp deploy.tar deleted.txt USER@HOST:metaquizy-backup-$TS/
ssh USER@HOST
```
(هر بار رمز SSH را می‌پرسد.) از اینجا به بعد دستورها **روی سرور** اجرا می‌شوند:

### مرحله ۳ — بکاپ (روی سرور)
```bash
B=~/metaquizy-backup-XXXXXXXX-XXXX            # همان پوشه‌ی مرحله ۲
cd /srv/sites/metaquizy/app
# نسخه‌ی فعلی فایل‌هایی که قرار است عوض شوند
tar -tf $B/deploy.tar | while read f; do [ -f "$f" ] && echo "$f"; done > $B/existing.txt
cat $B/deleted.txt >> $B/existing.txt
tar -cf $B/files-before.tar -T $B/existing.txt
# بکاپ کامل دیتابیس (رمز دیتابیس را می‌پرسد)
pg_dump -h 127.0.0.1 -U <DB_USER> -Fc metaquizy_db -f $B/db-before.dump
ls -lh $B        # هر دو فایل باید حجم داشته باشند
```

### مرحله ۴ — آزمایش در یک کپی موقت (بدون دست زدن به سایت اصلی)
```bash
V=~/mq-verify; rm -rf $V; mkdir $V
cd /srv/sites/metaquizy/app
tar --exclude=./.venv --exclude=./staticfiles --exclude=./media --exclude=./private_media --exclude=./node_modules --exclude=./.git -cf - . | tar -xf - -C $V
cd $V && tar -xf $B/deploy.tar
/srv/sites/metaquizy/app/.venv/bin/python manage.py check           # باید: no issues
/srv/sites/metaquizy/app/.venv/bin/python manage.py migrate --plan  # فقط نشان می‌دهد چه migrationهایی اجرا می‌شود
cd ~ && rm -rf $V
```
اگر `check` خطا داد، **ادامه ندهید**.

### مرحله ۵ — اسکریپت‌های استاد (روی سرور)
فایل `$B/apply-update.sh`:
```bash
#!/usr/bin/env bash
# Run once with: sudo bash <this file>
set -euo pipefail
B="$(cd "$(dirname "$0")" && pwd)"
APP=/srv/sites/metaquizy/app
cd "$APP"
tar -xf "$B/deploy.tar" --no-same-owner
tar -tf "$B/deploy.tar" | xargs chown metaquizy:metaquizy
[ -s "$B/deleted.txt" ] && xargs rm -f < "$B/deleted.txt"
sudo -u metaquizy .venv/bin/python manage.py check
sudo -u metaquizy .venv/bin/python manage.py migrate --no-input
sudo -u metaquizy .venv/bin/python manage.py collectstatic --no-input
systemctl restart metaquizy
sleep 4
systemctl is-active metaquizy
curl -s -o /dev/null -m 10 -w 'site check: %{http_code}\n' -H 'Host: metaquizy.ir' http://127.0.0.1:8020/login/ || true
echo 'Update applied.'
```
فایل `$B/rollback.sh` (فقط اگر بعد از به‌روزرسانی مشکلی پیش آمد):
```bash
#!/usr/bin/env bash
# Run with: sudo bash <this file>
set -euo pipefail
B="$(cd "$(dirname "$0")" && pwd)"
APP=/srv/sites/metaquizy/app
cd "$APP"
# اگر این به‌روزرسانی migration جدید داشت، خط زیر را با آخرین migration قبلی فعال کنید (قبل از برگرداندن فایل‌ها):
# sudo -u metaquizy .venv/bin/python manage.py migrate core <LAST_OLD_MIGRATION> --no-input
tar -xf "$B/files-before.tar" --no-same-owner
tar -tf "$B/files-before.tar" | xargs chown metaquizy:metaquizy
# فایل‌هایی که این به‌روزرسانی تازه اضافه کرده بود حذف شوند
{ tar -tf "$B/deploy.tar" | grep -vxF -f "$B/existing.txt" || true; } | xargs -r rm -f
sudo -u metaquizy .venv/bin/python manage.py collectstatic --no-input
systemctl restart metaquizy
sleep 4
systemctl is-active metaquizy
echo 'Previous version restored.'
```
برای ساختن فایل روی سرور: `nano $B/apply-update.sh` ← متن را بچسبانید ← `Ctrl+O`، `Enter`، `Ctrl+X`.

### مرحله ۶ — پیام به استاد
> لطفاً روی سرور این دستور را اجرا کنید: `sudo bash /home/<USER>/metaquizy-backup-XXXXXXXX-XXXX/apply-update.sh`
> خروجی آخر باید `active`، `site check: 200` (یا 301/302) و `Update applied.` باشد.

### مرحله ۷ — بعد از اجرا
- سایت را در مرورگر باز کنید و با هر نقش وارد شوید.
- در `PROGRESS.md` بخش «Deployment status» commit جدید سرور و تاریخ را بنویسید و commit کنید.
- نکته: سرور به دامنه‌ی خودش (`https://metaquizy.ir`) دسترسی ندارد؛ برای بررسی از روی سرور همیشه `127.0.0.1:8020` را بزنید.
