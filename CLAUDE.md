# MetaQuizy — notes for Claude

Online exam system (Persian UI, RTL). Roles: student, teacher, academic_manager, admin.
**Reply to the user in Persian.** Session progress lives in `PROGRESS.md`; how to run and deploy is in `README.md`.

## Session workflow (the user opens a new chat per task)
- Start: read `PROGRESS.md` (short). Read only the code the task needs.
- Several chats may work in the same tree: run `git status` first, never revert or overwrite changes you didn't make, and re-read `PROGRESS.md` right before editing it.
- End of every chat that changed something: update `PROGRESS.md` (what changed, tested or not, committed or not, deploy impact such as migrations or new static files). Add to `CLAUDE.md` only lasting rules/conventions; to `README.md` only run/deploy procedure changes. Keep all three short, no duplication, no secrets.

## Stack
- Django 5.1.9, PostgreSQL (psycopg 3), WhiteNoise, gunicorn; openpyxl, Pillow, pyotp, qrcode (`requirements.txt`).
- One app: `apps/core`. Settings: `config/settings.py` (reads `.env`; `DB_ENGINE=postgres` locally).
- Frontend: Django templates in `templates/<role>/`, Bootstrap 5 + jQuery, Tailwind build (`npm run build:css`), custom CSS in `static/css/`.
- `TIME_ZONE='Asia/Tehran'`, `USE_TZ=True`, `LANGUAGE_CODE='fa-ir'`.

## Code conventions
- Most data access is raw SQL through `erd_rows` / `erd_row` / `erd_execute` / `erd_has_column` (`apps/core/views.py` ~line 625), not the ORM. Tables are ERD tables (`profiles`, `exams`, `exam_attempts`, `questions`, …); Django models are mostly legacy.
- `apps/core/views.py` is ~18.5k lines and **some functions are defined more than once — only the last definition is live.** Grep for `^def name` and edit the last one. Never read the whole file.
- Other modules: `teacher_preferences.py`, `grading_views.py`, `exam_schedule.py`, `student_dashboard.py`, `student_settings.py`, `teacher_question_bank.py`, `teacher_students.py`, `osce_views.py`.
- «پیش‌نمایش» of any exam/question is `exam_preview.py` on the real `student/attempt.html` (students get sample questions, nothing is saved). Link new exam/question pages to `core:exam_preview` / `core:question_preview` with `?new=1`; a change to the attempt page must keep its `preview` branches working.
- Timestamp columns without time zone store UTC (see `_db_naive_datetime`). Display dates in Jalali via `templatetags/core_extras.py`.
- Exam settings columns carry defaults for every exam; what applies is `_sx_exam_rules(exam_id)` (wizard values only when `settings_enforced`). Read effective settings from it, not from the raw columns.
- A global JS converter in `base.html` / `base_standalone.html` turns digits Persian; mark codes/IDs with `data-latin-digits` (editors are excluded).
- System appearance (admin «تنظیمات ظاهری», `apps/core/appearance.py`): `static/js/appearance.js` recolours brand blues at runtime, so hardcoded blues are fine; inline colours that must stay as written go inside `data-mq-keep`. Any new page with its own `<html>` needs the `data-mq-*` attributes + `{% include "partials/appearance_head.html" %}` before `</head>`. That partial also holds the anti-flash load gate (font preload, `font-display:block`, body hidden until parsed) — don't re-add `@font-face`/`swap` elsewhere.
- Filters, search, paging, calendar navigation **and same-page tabs** must not reload the page: wrap filter form + results (for tabs: tabs + tab content, nested regions allowed; `data-live-region="contents"` = no layout box) in `id="…" data-live-region` (`static/js/live-region.js`; header comment has the details). Auto-submit with `this.form.requestSubmit()`, never `form.submit()`. JS bound to elements inside a region must use delegation, rebind on `mq:live-load`, or sit inside a `data-live-scripts` region (inline scripts re-run; no document listeners there); mark download/reset links `data-live-skip`.
- Listing tables are handled by `static/js/responsive-tables.js` (header comment): every column, header and cells alike, centred (user's choice); wrap-to-fit, else a card grid; a table/card switch is `{% include "partials/rt_view_switch.html" with key="…" %}` (opens on cards; `default="table"` to change). Don't add per-page centring or horizontal scrolling for tables; opt out with `rt-off` / `data-rt-align="keep"`. Action-column buttons with a known label become icon buttons automatically (`ICONS` in that file; keep a button as text with `data-rt-text`).
- Font weights (user's choice, not too bold): body 400, labels/buttons/nav/badges 600, titles and key numbers 700, only big hero numbers 800; never 850/900/950.
- Wrapping strips (tabs, steps, type pickers) are flex-wrap rows with growing items, balanced by `static/js/balanced-rows.js` (add `data-balance-rows`); never `repeat(auto-fill,…)` for them (leaves empty columns). Card grids use `repeat(auto-fit,…)` so a few cards stretch to fill the row (no empty columns, user's choice); `auto-fill` only where fixed-size tiles are intended (e.g. question map).
- Every page must work down to **240px** wide (user's requirement; audit with Playwright at 240/320/390/768/1024/1440). Single-column grids use `grid-template-columns:minmax(0,1fr)` (a bare grid or `1fr` grows to its widest child and cuts the page). Page `<style>` blocks load after `responsive.css`, so overrides there need a doubled class (`.a.a`) or `!important`.
- Keep the existing structure and templates; don't create new templates/patterns where an existing one fits.
- When you change a static JS/CSS file, bump the `?v=` on its `{% static %}` include (locally `DEBUG=True` serves unhashed URLs without Cache-Control, so browsers keep the old file).
- Schema changes go in a new migration in `apps/core/migrations/` (latest: `0063`).
- Deleting a course or a student/teacher account goes through `apps/core/deletion.py` (dialog: item only / with all records); don't hand-write `DELETE FROM courses|profiles` elsewhere.
- Messages and confirmations: Django `messages` show as the shared top toast (`partials/flash_messages.html`); ask with `window.mqConfirm()` / `data-confirm` (`partials/confirm_dialog.html`), never the browser's `confirm()`.
- Passwords are never displayable (hashes only): show `••••••••` + last change, offer a change/reset form. Any code that sets a password calls `account_security.mark_password_set(user, change_required=…)`.
- Security docs: `Security.md` (secrets/.env, hashing), `Auth.md` (login, `auth_events`, throttle), `Data.md` (personal data, retention, `purge_expired_data`), `Hack.md` (attacks/defences). Every new view needs a role decorator (`student_required` / `teacher_required` / `exam_manager_required` / `super_admin_required` / `erd_role_required`): `apps/core/tests_security.py` sweeps all routes anonymously and as student/teacher. All sign-ins go through `SecureLoginView` (throttle in `auth_guard.py`); client IP only via `client_ip()`. No secret in code; demo passwords only behind `DEBUG`.

## Commands (PowerShell, from repo root)
- Run: `.venv\Scripts\python manage.py runserver 8001` (port 8000 is used by another local project).
- Tests, targeted: `.venv\Scripts\python manage.py test apps.core.tests.<ClassName>`
- Tests, all (slow, run once at the end): `.venv\Scripts\python manage.py test apps.core`
- Manual-test data (local DB; also on production since 2026-11-08 at the user's request — remove there with `--purge` when asked): `manage.py seed_test_data` (re)creates 15 teachers / students / questions and 17 exams (2 practice) in every state, all marked `mqtest_` / «[آزمایشی]» / `MQTEST-` (password `Test@12345`); `seed_test_data --purge` removes them and everything made with those accounts. Re-run it to refresh time-relative states.
- Checks: `.venv\Scripts\python manage.py check` · `makemigrations --check --dry-run`

## Git
- Commit locally only when asked; **never push** unless asked. Branch `main`.

## Production (https://metaquizy.ir) — precautions
- Ubuntu server, systemd `metaquizy.service` (gunicorn on 127.0.0.1:8020), app at `/srv/sites/metaquizy/app`. No sudo for us.
- **Install nothing and move nothing on the server; ship code only.** Don't delete pre-existing data.
- **"Deploy the latest version" / «آخرین نسخه رو ببر روی سرور»** means: follow `README.md` → «ارسال آخرین نسخه به سرور» steps 0–6 yourself, then stop and hand the user the one `sudo bash …/apply-update.sh` line for the teacher. Summary:
  1. Tests green; ask the user before committing uncommitted work; server's current commit (`OLD`) is in `PROGRESS.md`.
  2. Package `git diff OLD..HEAD` files with `git archive` (+ `deleted.txt`), `scp` to a new `~/metaquizy-backup-<timestamp>/`.
  3. On the server: `files-before.tar` + `pg_dump` backup; verify in `~/mq-verify` with the server venv (`check`, `migrate --plan`); write `apply-update.sh` + `rollback.sh` (templates in README; set the rollback migration target if the package has migrations).
  4. After the teacher runs it: verify (service active, `127.0.0.1:8020` 200, deployed files match), then update `PROGRESS.md` with the new server commit.
- **Full deploy by us («ببر روی سرور و دامنه»):** if the user also gives the **root** SSH login, do steps 0–5 with the normal user, then run `bash ~amirhossein/metaquizy-backup-<ts>/apply-update.sh` over `ssh root@…` yourself (root needs no `sudo`) and do step 4's verification — including public `https://metaquizy.ir/login/` 200 and that it serves `css/responsive…`. Before applying, confirm `files-before.tar` still matches the live files. If root isn't given, stop and hand over the one-line command. The script's `site check: 301` is the http→https redirect, not an error (add `-H 'X-Forwarded-Proto: https'` to get 200).
- **What the user gives for a deploy:** normal SSH `user@host` + password, DB name + DB user + DB password (for `pg_dump`), and optionally root `user@host` + password (to apply it ourselves). Server path is fixed (`/srv/sites/metaquizy/app`). Uncommitted work is not shipped — ask before committing it, never include another chat's unfinished work without asking.
- **Credentials:** the user types SSH/DB credentials into the chat each time. Use them only for that run (e.g. a temporary `SSH_ASKPASS` script in the scratchpad, `PGPASSWORD` inline), delete helper files afterwards, and never write them into any repo file, commit or memory.
- The server can't reach its own domain (curl returns 000); health-check `127.0.0.1:8020` instead.
- `DEPLOY.md`, `RAILWAY.md`, `render.yaml`, `railway.json` and `deploy/` describe other hosting targets, not the current server.
- Never write passwords or keys into repo files.
