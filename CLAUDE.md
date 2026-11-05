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
- Timestamp columns without time zone store UTC (see `_db_naive_datetime`). Display dates in Jalali via `templatetags/core_extras.py`.
- A global JS converter in `base.html` / `base_standalone.html` turns digits Persian; mark codes/IDs with `data-latin-digits` (editors are excluded).
- Keep the existing structure and templates; don't create new templates/patterns where an existing one fits.
- Schema changes go in a new migration in `apps/core/migrations/` (latest: `0059`).

## Commands (PowerShell, from repo root)
- Run: `.venv\Scripts\python manage.py runserver 8001` (port 8000 is used by another local project).
- Tests, targeted: `.venv\Scripts\python manage.py test apps.core.tests.<ClassName>`
- Tests, all (slow, run once at the end): `.venv\Scripts\python manage.py test apps.core`
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
- **Credentials:** the user types SSH/DB credentials into the chat each time. Use them only for that run (e.g. a temporary `SSH_ASKPASS` script in the scratchpad, `PGPASSWORD` inline), delete helper files afterwards, and never write them into any repo file, commit or memory.
- The server can't reach its own domain (curl returns 000); health-check `127.0.0.1:8020` instead.
- `DEPLOY.md`, `RAILWAY.md`, `render.yaml`, `railway.json` and `deploy/` describe other hosting targets, not the current server.
- Never write passwords or keys into repo files.
