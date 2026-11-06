# Progress

_Last updated: 2026-11-05. Every chat updates this file before it ends (see `CLAUDE.md` → Session workflow)._

## Deployment status
- **Production runs commit `1f9e4ea`** (applied 2026-11-04, verified: files identical, migrations 0058–0059 applied, service active).
- Everything after `1f9e4ea` is **not deployed**: commit `6c81667` (editor digits) + the uncommitted responsive/scroll work below.
- `~/metaquizy-backup-20261105-0025/` on the server holds an old package for `6c81667` only — **superseded, don't use it**. The next deploy is one package built from `1f9e4ea..HEAD` (README → «ارسال آخرین نسخه به سرور»).
- That next package adds a new static file (`static/css/responsive.css`), so `collectstatic` is required (it's in the standard `apply-update.sh`). No new migrations since 0059.
- **Don't ask the teacher to run anything until the user says so.**
- Local `main` is 85 commits ahead of `origin/main` (not pushed, by choice).

## Responsive + scroll work (2026-11-05 → 07), committed in `22a5ccf` and the commit after it
- `static/css/responsive.css` (new, linked after `dist/styles.css` in `base.html`, `base_standalone.html`, `login.html`, `register.html`) holds all phone/tablet fixes; page-local fixes in `super_admin/profile.html`, `teacher/students/report.html`; panel chrome in `partials/super_admin_chrome.html`.
- Chrome: burger dropdown with «پروفایل»/«خروج» on phones; the dropdown no longer wraps «خروج» into a side column (no sideways scroll). ≤760px the page scrolls (shell unlocked); tablet/desktop `.app-shell` is a flex column so `.app-main` fills the rest.
- 55 templates had a UTF-8 BOM that rendered as a 25px line in `<body>`; stripped — **keep templates BOM-less**.
- Tablet layouts fixed: settings family (system settings, org units, academic terms) stacks the summary card, 2/1 card columns; user profile hero (avatar no longer over the tabs); exam-manager dashboard grid; avatars were stretched into ovals (now square). Phones: home exam-code form stacks, filter bars (teacher classes/students) no longer squeeze selects to 0px, calendar weekdays, OSCE tabs, report print button.
- Checked with Playwright crawls (Edge, 4 roles + public pages, ~170 pages, 320–1440px): no horizontal overflow, nothing clipped/unreachable vertically, and a text/overlap/squeezed-control check whose remaining hits were reviewed as intended (decorative overlaps, input unit suffixes). Not crawled: live attempt pages (phone tweaks for `.qx-*` added, untested in a real attempt).
- Tests: full suite 377 OK (2026-11-07). Needs a local `collectstatic` first (manifest storage fails with "Missing staticfiles manifest entry" otherwise).
- `static/dist/styles.css` is **gitignored**, so `git archive` packages don't contain it; the deploy package must add the locally built file. Build locally with `node node_modules/tailwindcss/lib/cli.js -i ./static/src/input.css -o ./static/dist/styles.css --minify` (`npx tailwindcss` isn't on PATH here). `input.css` was also reformatted by an editor (whitespace only) in `22a5ccf`.
- Local env note: `.venv` here is a Linux-style venv (no `Scripts\`); Python runs from `..\venv\Scripts\python.exe`.

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
