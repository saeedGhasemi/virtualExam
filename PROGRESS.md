# Progress

_Last updated: 2026-11-07. Every chat updates this file before it ends (see `CLAUDE.md` → Session workflow)._

## Deployment status
- **Production runs commit `1f9e4ea`** (applied 2026-11-04, verified: files identical, migrations 0058–0059 applied, service active).
- **Package for `1f9e4ea..3e84467` is staged on the server, waiting for the teacher** (2026-11-07): `~/metaquizy-backup-20261107-0446/` holds `deploy.tar` (67 git files + locally built `static/dist/styles.css`), `files-before.tar`, `existing.txt`, `db-before.dump` (pg_dump, 96 tables), `apply-update.sh`, `rollback.sh`. Verified in a temp copy with the server venv: `check` clean, no migrations, `collectstatic` OK. New static files: `static/css/responsive.css`, `static/js/responsive-tables.js`. Teacher command: `sudo bash /home/amirhossein/metaquizy-backup-20261107-0446/apply-update.sh`.
- After the teacher runs it: verify (service active, `127.0.0.1:8020/login/` 200, deployed files match `3e84467`), then set the production commit above to `3e84467`.
- Superseded packages: `~/metaquizy-backup-20261107-0353`, `-20261107-0248` (its script renamed to `apply-update.sh.SUPERSEDED-…`), `-20261104-*`, `-20261105-0025`.
- The SSH user has no sudo (checked). Local `main` is ahead of `origin/main` (not pushed, by choice).

## Responsive + scroll work (2026-11-05 → 07), committed in `22a5ccf` and the commit after it
- `static/css/responsive.css` (new, linked after `dist/styles.css` in `base.html`, `base_standalone.html`, `login.html`, `register.html`) holds all phone/tablet fixes; page-local fixes in `super_admin/profile.html`, `teacher/students/report.html`; panel chrome in `partials/super_admin_chrome.html`.
- Chrome: burger dropdown with «پروفایل»/«خروج» on phones; the dropdown no longer wraps «خروج» into a side column (no sideways scroll). ≤760px the page scrolls (shell unlocked); tablet/desktop `.app-shell` is a flex column so `.app-main` fills the rest.
- 55 templates had a UTF-8 BOM that rendered as a 25px line in `<body>`; stripped — **keep templates BOM-less**.
- Tablet layouts fixed: settings family (system settings, org units, academic terms) stacks the summary card, 2/1 card columns; user profile hero (avatar no longer over the tabs); exam-manager dashboard grid; avatars were stretched into ovals (now square). Phones: home exam-code form stacks, filter bars (teacher classes/students) no longer squeeze selects to 0px, calendar weekdays, OSCE tabs, report print button.
- **No sideways-scrolling strips** (user preference: a longer page is fine, horizontal scroll is not): question-type picker, option pills, teacher-students / student-settings tabs, create-exam steps, OSCE tabs and org-level cards now wrap into rows. Only the home image carousel still swipes (kept on purpose).
- **Tables → cards:** `static/js/responsive-tables.js` (new, loaded by `base.html` / `base_standalone.html`) labels each cell with its column header and adds `rt-cards` to any listing table wider than its box, so it shows as a card stack instead of scrolling; tables that fit stay tables. Editors/matrices are excluded (`SKIP` list in the file). List footers (page size / pager / count) stack on phones.
- Also fixed: home exam-code and search forms (input squeezed to ~0px at 481–760px), login quick-role labels truncated, matching-question column B and short-answer accepted answer inputs squeezed on phones.
- **Design pass from the user's mockups (2026-11-07, inspiration only — no new features/buttons, keep current nav + logo):** settings tab bars (active = blue fill + underline; phones: student 3 cols icon-over-label, teacher 2×2), student-settings phone overflow (form grid grew to 584px on the workspace tab) fixed, read-only values/theme cards wrap, teacher theme switcher no longer covered on tablets; question builder phone footer (primary row + 2×2), media tabs 4 columns, styled the study-link input; exam page: options keep letter/text/radio on one row, 2-column footer with «پایان آزمون» full width, side cards 2 columns on tablets; class pages: compact view switch; card tables override fixed column widths.
- Exam page was checked by rendering attempts inside the **test database** (temporary test file, deleted) and opening the HTML in the browser — no attempts created in the real DB.
- The crawler now also visits `?tab=` pages and flags whole-page overflow.
- Checked with Playwright crawls (Edge, 4 roles + public pages, ~170 pages, 320–1440px incl. 626/900/1180): no horizontal overflow, no sideways-scrolling boxes except the home carousel, nothing clipped/unreachable vertically, and a text/overlap/squeezed-control check whose remaining hits were reviewed as intended (decorative overlaps, input unit suffixes). Not crawled: live attempt pages (phone tweaks for `.qx-*` added, untested in a real attempt).
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
