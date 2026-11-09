// Responsive listing tables (styles: static/css/responsive.css → "Listing tables").
// * Every listing table gets one alignment rule: every column, header and cells alike, centred horizontally and
//   vertically (rt-c; the cell's own flex rows / narrow blocks are centred too). Short values stay on one line
//   (classes rt-start / rt-c / rt-nw / rt-jc / rt-mc). Card view keeps its own label-start / value-end layout.
//   A cell holding one row of items (icon/avatar/code chip + text) is a "lead" row (rt-lead): every lead row of a
//   column gets the width of the widest one, centred, items start-aligned, so icons line up in a straight column
//   instead of zigzagging with the text length.
// * A table wider than its box first tries wrapping its text (rt-fit); if it still doesn't fit it becomes a grid of
//   cards (rt-cards; each cell labelled with its column header, the main cell as the card title, actions at the bottom)
//   instead of scrolling sideways.
// * A view switch (`[data-rt-switch="key"]` with `[data-rt-view="table|cards"]` buttons, optional
//   `data-rt-target="selector"`, default: the tables of the switch's closest section) lets the user pick table or
//   cards. Every page load opens on `data-rt-default` (cards unless set); the choice lasts while the page is open
//   (live-region filtering/paging keeps it), it is not stored.
// * Action buttons (the «عملیات» column) with a known label (ویرایش، مشاهده، حذف، گزارش، نتایج، تصحیح…) become icon
//   buttons (rt-ico): the label moves to title + a visually hidden span (screen readers, tests and textContent keep it),
//   a count like «تصحیح (۶)» becomes a badge, حذف is red, filled buttons stay filled. Unknown labels, menu items and
//   controls marked data-rt-text stay as text. Add a label to ICONS below to cover a new button.
// Opt out with class rt-off (or the SKIP list below).
(() => {
  // editors, answer matrices and print-only tables keep their table layout
  const SKIP = '.qx-matrix, .qb2-matrix, .qb-rubric, .gd-rubric, .ob-crit-table, .manager-bulk-map-table, .score-alloc-table, .sr-only, .srd-print-info, .grading-aid-table, .map-table, .rt-off';
  const ACTION_HEAD = /^(عملیات|اقدام|اقدامات|عملیات‌ها|actions?)$/i;
  const NO_TITLE_HEAD = /^(ردیف|#|انتخاب|شماره ردیف)$/;
  const chosen = {}; // switch key → view picked on this page

  // action-button icons (24×24 stroke paths)
  const P = {
    eye: '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/>',
    info: '<circle cx="12" cy="12" r="9"/><path d="M12 16v-5M12 8h.01"/>',
    edit: '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"/>',
    trash: '<path d="M3 6h18M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6M10 11v6M14 11v6"/>',
    report: '<path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9Z"/><path d="M14 3v6h6M8 17v-3M12 17v-6M16 17v-2"/>',
    card: '<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="9" cy="10" r="2"/><path d="M6 16c.6-1.5 1.7-2.2 3-2.2s2.4.7 3 2.2M14 9h4M14 13h4"/>',
    chart: '<path d="M3 3v18h18"/><path d="M7 15l4-4 3 3 5-6"/>',
    publish: '<path d="M3 3v18h18"/><path d="M7 16v-4M11 16V9M15 16v-6"/><path d="m17 7 2-2 2 2M19 5v6"/>',
    live: '<path d="M22 12h-4l-3 8L9 4l-3 8H2"/>',
    grade: '<path d="M9 11l3 3 8-8"/><path d="M20 12v6a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h9"/>',
    archive: '<rect x="3" y="4" width="18" height="4" rx="1"/><path d="M5 8v11a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8M10 12h4"/>',
    share: '<circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><path d="m8.6 13.5 6.8 4M15.4 6.5l-6.8 4"/>',
    unshare: '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M17 11h6"/>',
    manage: '<path d="M4 7h10M18 7h2M4 17h4M12 17h8"/><circle cx="16" cy="7" r="2"/><circle cx="10" cy="17" r="2"/>',
    resume: '<path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h5"/><path d="M14 3v6h6v3"/><path d="m15 22 6-6-2.5-2.5-6 6V22Z"/>',
    message: '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2Z"/>',
    download: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3"/>',
    print: '<path d="M6 9V2h12v7M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2"/><rect x="6" y="14" width="12" height="8"/>',
    copy: '<rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>',
    check: '<path d="M20 6 9 17l-5-5"/>',
    reject: '<path d="M18 6 6 18M6 6l12 12"/>',
    restore: '<path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/>',
    users: '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.9M16 3.1a4 4 0 0 1 0 7.8"/>',
  };
  // label → icon [, tone]; the first match wins
  const ICONS = [
    [/^(مشاهده|نمایش|مشاهده پروفایل|پروفایل|پیش‌?\s?نمایش)$/, 'eye'],
    [/^(جزئیات|مشاهده جزئیات)$/, 'info'],
    [/^(ویرایش|✎|✏️?|اصلاح)$/, 'edit'],
    [/^حذف$/, 'trash', 'danger'],
    [/^(گزارش|گزارش آزمون)$/, 'report'],
    [/^(کارنامه|مشاهده کارنامه)$/, 'card'],
    [/^(نتایج|نتیجه|مشاهده نتایج)$/, 'chart'],
    [/^(نتایج و انتشار|انتشار نتایج)$/, 'publish'],
    [/^(پایش زنده|پایش|مانیتورینگ)$/, 'live'],
    [/^(تصحیح|ادامه تصحیح)$/, 'grade'],
    [/^(آرشیو|بایگانی)$/, 'archive'],
    [/^(اشتراک|اشتراک‌?\s?گذاری|اشتراک با هم‌?\s?درس‌?\s?ها)$/, 'share'],
    [/^لغو اشتراک$/, 'unshare', 'danger'],
    [/^(مدیریت|مدیریت بانک|تنظیمات)$/, 'manage'],
    [/^(ادامه|ادامه ویرایش)$/, 'resume'],
    [/^(پیام|ارسال پیام)$/, 'message'],
    [/^(دانلود|دریافت فایل)$/, 'download'],
    [/^چاپ$/, 'print'],
    [/^(کپی|کپی کد|تکثیر)$/, 'copy'],
    [/^(تأیید|تایید)$/, 'check', 'success'],
    [/^(رد|رد کردن)$/, 'reject', 'danger'],
    [/^(بازگردانی|بازیابی)$/, 'restore'],
    [/^(اعضا|دانشجویان|شرکت‌?\s?کنندگان)$/, 'users'],
  ];
  const faDigits = (t) => t.replace(/[0-9]/g, (d) => '۰۱۲۳۴۵۶۷۸۹'[d]);
  const iconize = (cell) => {
    // an icon-only disabled placeholder (e.g. «کارنامه» before results exist) matches the icon buttons beside it
    cell.querySelectorAll('span[aria-disabled="true"]').forEach((el) => {
      if (el.querySelector('svg') && !el.textContent.trim()) el.classList.add('rt-ico');
    });
    cell.querySelectorAll('a, button').forEach((el) => {
      if (el.classList.contains('rt-ico') || el.closest('[role=menu], .dropdown-menu, details, [data-rt-text]') || el.querySelector('img')) return;
      const raw = el.textContent.trim().replace(/\s+/g, ' ');
      const m = raw.match(/^(.*?)\s*[(]\s*([0-9۰-۹]+)\s*[)]$/); // «تصحیح (۶)»
      const label = (m ? m[1] : raw).trim();
      const hit = ICONS.find(([re]) => re.test(label));
      if (!hit) return;
      const cs = getComputedStyle(el);
      const rgb = (cs.backgroundColor.match(/[\d.]+/g) || []).map(Number);
      // filled (saturated, opaque) buttons stay filled; white / tinted ones get the plain icon style
      const filled = cs.backgroundImage.includes('gradient') || (rgb.length >= 3 && (rgb[3] === undefined || rgb[3] > .8) && Math.max(rgb[0], rgb[1], rgb[2]) - Math.min(rgb[0], rgb[1], rgb[2]) > 90);
      const own = el.querySelector('svg');
      if (own) own.remove();
      el.textContent = '';
      if (own) { own.setAttribute('aria-hidden', 'true'); el.appendChild(own); } else el.insertAdjacentHTML('afterbegin', `<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">${P[hit[1]]}</svg>`);
      const sr = document.createElement('span');
      sr.className = 'rt-ico-label';
      sr.textContent = raw;
      el.appendChild(sr);
      if (m) { const badge = document.createElement('b'); badge.className = 'rt-ico-badge'; badge.setAttribute('aria-hidden', 'true'); badge.textContent = faDigits(m[2]); el.appendChild(badge); }
      if (!el.title) el.title = raw;
      el.classList.add('rt-ico');
      if (hit[2]) el.classList.add(`is-${hit[2]}`);
      if (filled) el.classList.add('is-filled');
    });
    // beside the page's own bare icon buttons (no border/background), converted ones go bare too
    const bare = [...cell.querySelectorAll('a, button')].some((el) => {
      if (el.classList.contains('rt-ico') || el.textContent.trim() || !el.querySelector('svg')) return false;
      const cs = getComputedStyle(el);
      return parseFloat(cs.borderTopWidth) === 0 && /rgba\(0, 0, 0, 0\)|transparent/.test(cs.backgroundColor) && cs.backgroundImage === 'none';
    });
    if (bare) cell.querySelectorAll('.rt-ico:not(.is-filled)').forEach((el) => el.classList.add('is-ghost'));
  };
  try { Object.keys(localStorage).filter((k) => k.startsWith('mq-rt-view:')).forEach((k) => localStorage.removeItem(k)); } catch (e) { /* old stored choices are no longer used */ }

  // short values (dates, durations, counts, badges), with or without an icon
  const shortValue = (cell, t) => t.length <= 28 && cell.querySelectorAll('*').length <= 6 && !cell.querySelector('a, button, input, select, textarea, img, p, ul, ol, table, br, form, label')
    && ![...cell.querySelectorAll('*')].some((n) => getComputedStyle(n).display === 'block' && n.previousSibling && (n.previousElementSibling || n.previousSibling.textContent.trim())); // a second line by design

  // centre a box's own wrappers: flex rows get justify-content:center, narrower blocks auto margins, full-width blocks
  // (e.g. a <details> menu) are looked into
  const centreIn = (box, depth) => {
    const own = getComputedStyle(box);
    if (own.display.includes('flex') || own.display.includes('grid') && box.tagName !== 'TD' && box.tagName !== 'TH') return; // its items follow justify-content / the grid
    const inner = box.getBoundingClientRect().width - parseFloat(own.paddingLeft) - parseFloat(own.paddingRight) - parseFloat(own.borderLeftWidth) - parseFloat(own.borderRightWidth);
    for (const child of box.children) {
      const cs = getComputedStyle(child);
      if (cs.position === 'absolute' || cs.position === 'fixed' || cs.display === 'none') continue;
      if (cs.display.includes('flex') && cs.flexDirection.startsWith('row')) { child.classList.add('rt-jc'); continue; }
      if (!/^(block|grid|table|list-item)$/.test(cs.display)) continue;
      if (child.getBoundingClientRect().width < inner - 2) child.classList.add('rt-mc');
      else if (depth < 2) centreIn(child, depth + 1);
    }
  };

  const alignCell = (cell) => {
    if (getComputedStyle(cell).display.includes('flex')) cell.classList.add('rt-jc');
    const lead = cell.tagName === 'TD' && leadRow(cell);
    if (lead) lead.classList.add('rt-lead'); else centreIn(cell, 0);
    if (cell.tagName !== 'TH') markShort(cell);
  };

  // one flex row of 2+ items and no loose text, e.g. icon + title, avatar + name, code chip + title
  const leadRow = (cell) => {
    if (cell.classList.contains('rt-act')) return null;
    const kids = [...cell.children].filter((n) => getComputedStyle(n).position !== 'absolute');
    if (kids.length !== 1 || [...cell.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim())) return null;
    const row = kids[0], cs = getComputedStyle(row);
    if (!cs.display.includes('flex') || !cs.flexDirection.startsWith('row') || row.children.length < 2) return null;
    if ([...row.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim())) return null;
    return row;
  };
  // equal widths per column (table view only; measured on every fit, since a hidden table measures 0)
  const leadWidths = (table) => {
    const cols = {};
    table.querySelectorAll(':scope > tbody > tr > td > .rt-lead').forEach((row) => {
      row.style.removeProperty('--rt-lead-w');
      const i = row.parentElement.cellIndex;
      row.style.width = 'max-content';
      cols[i] = Math.max(cols[i] || 0, Math.ceil(row.getBoundingClientRect().width));
      row.style.width = '';
    });
    table.querySelectorAll(':scope > tbody > tr > td > .rt-lead').forEach((row) => {
      const w = cols[row.parentElement.cellIndex];
      if (w) row.style.setProperty('--rt-lead-w', `${w}px`);
    });
  };

  const markShort = (cell) => {
    const t = cell.textContent.trim().replace(/\s+/g, ' ');
    // (fixed-layout tables don't grow, so one-line text there would spill over the next cell)
    if (t && shortValue(cell, t) && getComputedStyle(cell.closest('table')).tableLayout !== 'fixed') cell.classList.add('rt-nw');
    // loose text next to elements (e.g. a date + <small>time</small>) is one value: keep it together in card view
    const nodes = [...cell.childNodes];
    if (nodes.some((n) => n.nodeType === 3 && n.textContent.trim()) && cell.children.length) {
      const wrap = document.createElement('span');
      wrap.className = 'rt-val';
      nodes.forEach((n) => wrap.appendChild(n));
      cell.appendChild(wrap);
    }
  };

  // fixed column widths can be too small: content then spills over the next cell
  const spills = (table) => [...table.tBodies].some((body) => [...body.rows].slice(0, 8).some((row) => [...row.cells].some((cell) => cell.colSpan === 1 && cell.scrollWidth > cell.clientWidth + 3)));
  // a wrapped table is only kept when no long text got squeezed into a narrow column
  const squeezed = (table) => [...table.tBodies].some((body) => [...body.rows].slice(0, 8).some((row) => [...row.cells].some((cell) => cell.clientWidth < 200 && cell.textContent.trim().length > 45)));

  const label = (table) => {
    if (table.dataset.rtState) return table.dataset.rtState === 'ok';
    const head = table.tHead && table.tHead.rows.length === 1 ? [...table.tHead.rows[0].cells] : null;
    if (!head || !head.length || head.some((cell) => cell.colSpan > 1)) {
      table.dataset.rtState = 'skip';
      return false;
    }
    const names = head.map((cell) => cell.textContent.trim().replace(/\s+/g, ' '));
    const rows = [...table.tBodies].flatMap((body) => [...body.rows]).filter((row) => ![...row.cells].some((cell) => cell.colSpan > 1 || cell.rowSpan > 1)); // skip "no data" rows
    // card title = first named column whose cells hold text; actions = the «عملیات» column or one with only buttons/links
    const hasText = (i) => rows.some((row) => row.cells[i] && row.cells[i].textContent.trim().length > 1);
    const onlyControls = (i) => rows.length && rows.every((row) => { const c = row.cells[i]; if (!c) return false; const clone = c.cloneNode(true); clone.querySelectorAll('a, button, form, select, details, [role=menu], .dropdown-menu').forEach((n) => n.remove()); return !clone.textContent.trim() && c.querySelector('a, button, select'); });    let titleCol = names.findIndex((n, i) => n && !NO_TITLE_HEAD.test(n) && !ACTION_HEAD.test(n) && hasText(i));
    const actionCols = names.map((n, i) => (i !== titleCol && (ACTION_HEAD.test(n) || (i === names.length - 1 && onlyControls(i))) ? i : -1)).filter((i) => i >= 0);
    head.forEach((cell) => cell.classList.add('rt-th'));
    for (const row of rows) {
      [...row.cells].forEach((cell, i) => {
        if (!cell.hasAttribute('data-label')) cell.setAttribute('data-label', names[i] || '');
        if (i === titleCol) cell.classList.add('rt-head');
        if (actionCols.includes(i)) { cell.classList.add('rt-act'); iconize(cell); }
      });
    }
    if (!table.matches('[data-rt-align="keep"]')) {
      table.classList.add('rt-start');
      head.forEach((th, i) => { // every column centred, header and cells alike (the user's choice, 2026-11-09)
        th.classList.add('rt-c');
        rows.forEach((row) => row.cells[i] && row.cells[i].classList.add('rt-c'));
      });
      head.forEach(alignCell);
      for (const row of rows) [...row.cells].forEach(alignCell);
    }
    table.dataset.rtState = 'ok';
    return true;
  };

  const tablesFor = (sw) => {
    const sel = sw.getAttribute('data-rt-target');
    if (sel) return [...document.querySelectorAll(sel)];
    const scope = sw.closest('section, article, [data-live-region], main') || document;
    return [...scope.querySelectorAll('table')];
  };

  const applySwitches = () => {
    document.querySelectorAll('[data-rt-switch]').forEach((sw) => {
      const view = chosen[sw.getAttribute('data-rt-switch')] || sw.getAttribute('data-rt-default') || 'cards';
      tablesFor(sw).forEach((t) => { t.dataset.rtView = view; });
      sw.querySelectorAll('[data-rt-view]').forEach((b) => {
        const on = b.getAttribute('data-rt-view') === view;
        b.classList.toggle('is-active', on);
        b.setAttribute('aria-pressed', on ? 'true' : 'false');
      });
    });
  };

  const fit = () => {
    applySwitches();
    document.querySelectorAll('table').forEach((table) => {
      if (table.matches(SKIP) || table.closest('.qx, [contenteditable], .ql-editor')) return;
      table.classList.remove('rt-cards', 'rt-fit', 'rt-fit-act');
      if (!label(table)) return;
      const box = table.parentElement;
      if (!box || !box.clientWidth) return;
      if (table.dataset.rtView === 'cards') { table.classList.add('rt-cards'); return; }
      leadWidths(table);
      // room = the box's content width (clientWidth includes its padding, so a table could still stick out by the padding)
      const bs = getComputedStyle(box);
      const room = box.clientWidth - (parseFloat(bs.paddingLeft) || 0) - (parseFloat(bs.paddingRight) || 0);
      const natural = table.offsetWidth;
      if (natural <= room + 2 && !spills(table)) return;
      // a little too wide: let long text wrap before giving up the table (much too wide would squeeze every column)
      if (natural <= room * 1.35) {
        table.classList.add('rt-fit');
        if (table.offsetWidth <= room + 2 && !squeezed(table) && !spills(table)) return;
        table.classList.add('rt-fit-act'); // then let action buttons wrap onto a second line
        if (table.offsetWidth <= room + 2 && !squeezed(table) && !spills(table)) return;
        table.classList.remove('rt-fit', 'rt-fit-act');
      }
      table.classList.add('rt-cards');
    });
  };

  document.addEventListener('click', (e) => {
    const btn = e.target.closest('[data-rt-switch] [data-rt-view]');
    if (!btn) return;
    e.preventDefault();
    chosen[btn.closest('[data-rt-switch]').getAttribute('data-rt-switch')] = btn.getAttribute('data-rt-view');
    fit();
  });

  let timer = null;
  const later = () => { clearTimeout(timer); timer = setTimeout(fit, 120); };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', fit); else fit();
  window.addEventListener('load', fit);
  window.addEventListener('resize', later);
  document.addEventListener('mq:live-load', fit); // tables swapped in by live-region.js
})();
