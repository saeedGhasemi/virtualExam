# Progress

_Last updated: 2026-11-05. Every chat updates this file before it ends (see `CLAUDE.md` → Session workflow)._

## Deployment status
- **Production runs commit `1f9e4ea`** (applied 2026-11-04, verified: files identical, migrations 0058–0059 applied, service active).
- Everything after `1f9e4ea` is **not deployed**: commit `6c81667` (editor digits) + the uncommitted responsive/scroll work below.
- `~/metaquizy-backup-20261105-0025/` on the server holds an old package for `6c81667` only — **superseded, don't use it**. The next deploy is one package built from `1f9e4ea..HEAD` (README → «ارسال آخرین نسخه به سرور»).
- That next package adds a new static file (`static/css/responsive.css`), so `collectstatic` is required (it's in the standard `apply-update.sh`). No new migrations since 0059.
- **Don't ask the teacher to run anything until the user says so.**
- Local `main` is 85 commits ahead of `origin/main` (not pushed, by choice).

## Uncommitted work in the tree (2026-11-05, from the responsive chat)
~60 templates modified + new `static/css/responsive.css`. Must be committed (user approval) before any deploy.
- **Responsive pass:** `responsive.css` (linked after `dist/styles.css` in `base.html`, `base_standalone.html`, `login.html`, `register.html`) holds phone/tablet fixes; page-local fixes in `super_admin/profile.html`; panel chrome (`partials/super_admin_chrome.html`) got a dropdown menu plus «پروفایل»/«خروج» on phones. Playwright crawl (Edge, 4 roles, ~170 pages, 320–1440px): no horizontal overflow. Home page featured plan card colours fixed. Not crawled: live attempt pages (phone tweaks for `.qx-*` added in `responsive.css`, untested in a real attempt).
- **Scroll fix:** (1) 55 templates had a UTF-8 BOM that rendered as a line in `<body>`; stripped — keep templates BOM-less. (2) ≤760px the `.app-shell` is unlocked; on tablet/desktop it's a flex column so `.app-main` fills the rest (`super_admin_chrome.html`). (3) Admin dashboard overview and settings summary card no longer clipped. (4) After the BOM strip, small-phone overflow on courses / teachers / students / managers lists and the exam-manager new-exam form was fixed. Vertical + horizontal audits: clean.
- Not mine, already in the tree before this chat: edits to `exam_manager/grouping.html`, `super_admin/org_units.html`, `super_admin/settings.html`, `teacher/_question_form.html`, `teacher/osce/_builder.html` (BOM strip touched some of them too), plus `README.md`/`CLAUDE.md`/`PROGRESS.md` from the docs chat.
- Tests: full suite 377 OK (2026-11-05, final run), `check` and `makemigrations --check` clean. Needs a local `collectstatic` first (manifest storage fails with "Missing staticfiles manifest entry" otherwise).
- Local env note: `.venv` here is a Linux-style venv (no `Scripts\`); this chat ran Python from `..\venv\Scripts\python.exe`.
- Tailwind isn't installed locally, so `input.css` can't be rebuilt; put CSS fixes in `static/css/responsive.css`.

## Completed and committed (tested locally)
- **Exam code:** `MQ-` + 6 hex; bold, copyable; joinable from home (`/join/`) by every role, with errors for wrong codes.
- **Receipts:** real unique code per attempt (migration 0058); searchable by teachers and managers.
- **Exam timing:** last-entry time, group audience and duration scenarios covered by tests.
- **Attempt page:** fullscreen overlay fix; camera gate with retry; browser Back blocked; pages not cached.
- **Profiles:** working profile/settings for every role (name, email, mobile, avatar, password, 2FA, sessions).
- **Teacher preferences** take effect (`teacher_preferences.py`); notification timestamps (migration 0059).
- **Exam list:** styling, results-release link, question usage count column.
- **Report card:** A4 print layout. **Home page:** opening `/` logs out.
- **Question import:** xlsx/csv, fully validated, xlsx template.
- **Admin user approval:** activate/deactivate/delete; accounts with history are kept with a message; activating a teacher approves their sign-up.
- **Question edit:** saves for every type; digits stay as typed (`6c81667`).

## Decisions / open items
- Server account «دانشجو داوطلب» (username `student`) stays pending on purpose.
- Login/registration flow, incl. demo quick-login buttons, stays as is (user decision).
