// Whole-row links (user's choice): in a listing a click anywhere on a row / card opens that item, not only on its name.
// * Explicit: any element with data-row-href="url" (table row or card) — works everywhere.
// * Automatic for listing table rows (tbody tr, also in card view of responsive-tables.js): the target is the plain link
//   in the row's title cell (rt-head / .is-title / first cell that isn't «ردیف»), else the row's only link destination
//   (all its plain links point to one URL, e.g. a lone «مشاهده عملکرد» button). Rows with several different links and
//   no title link get nothing. "Plain" = a normal GET link: not #anchors, mailto:/tel:/javascript:, target=_blank,
//   download, data-confirm, data-live-skip (downloads/resets) or inside a menu. A row with a checkbox/radio (selection
//   lists, where a row click may tick the box) only opens a link in its title cell; the box itself still ticks.
// * Clicks on links, buttons, form controls, labels, menus and [data-no-row-link] keep their own action; a text
//   selection doesn't navigate. Ctrl/⌘/middle click opens a new tab. The row's link itself is clicked, so live regions
//   (static/js/live-region.js) and the page loader handle it as usual.
// * Opt out: data-row-link="off" on the row or any ancestor (table/section).
(() => {
  'use strict';
  if (window.mqRowLink) return;
  const INTERACTIVE = 'a, button, input, select, textarea, label, summary, details, [role="button"], [role="menuitem"], [contenteditable], [data-no-row-link], .dropdown-menu';
  const BAD_HREF = /^(#|mailto:|tel:|javascript:)/i;
  const NO_TITLE_HEAD = /^(ردیف|#|انتخاب|شماره ردیف)$/;

  const plain = (a) => {
    const href = a.getAttribute('href');
    return href && !BAD_HREF.test(href.trim()) && a.target !== '_blank' && !a.hasAttribute('download')
      && !a.hasAttribute('data-confirm') && !a.hasAttribute('data-live-skip')
      && !a.closest('details, [role="menu"], .dropdown-menu, [data-no-row-link]');
  };

  const titleCell = (row) => {
    const cells = Array.from(row.cells || []);
    const marked = cells.find((c) => c.classList.contains('rt-head') || c.classList.contains('is-title'));
    if (marked) return marked;
    const head = row.closest('table')?.tHead?.rows[0];
    return cells.find((c, i) => {
      if (c.querySelector('input[type="checkbox"], input[type="radio"]') && !c.querySelector('a')) return false;
      const th = head?.cells[i];
      return !(th && NO_TITLE_HEAD.test(th.textContent.trim()));
    });
  };

  // the link a row opens, or null; cached per row (rows are replaced when a live region reloads)
  const target = (row) => {
    if (row._mqRowLink !== undefined) return row._mqRowLink;
    let link = null;
    if (row.closest('[data-row-link="off"]')) link = null;
    else if (row.dataset.rowHref) link = row;
    else if (row.tagName === 'TR' && row.parentElement?.tagName === 'TBODY') {
      const links = Array.from(row.querySelectorAll('a[href]')).filter((a) => a.closest('tr') === row && plain(a));
      const cell = titleCell(row);
      link = links.find((a) => cell && cell.contains(a)) || null;
      const picking = row.querySelector('input[type="checkbox"], input[type="radio"]');
      if (!link && !picking && links.length && links.every((a) => a.href === links[0].href)) link = links[0];
    }
    row._mqRowLink = link;
    if (link) row.classList.add('mq-row-link');
    return link;
  };

  const rowOf = (el) => el.closest?.('[data-row-href], tbody > tr');

  const go = (event, newTab) => {
    const row = rowOf(event.target);
    if (!row || event.target.closest(INTERACTIVE)) return;
    const link = target(row);
    if (!link) return;
    if (String(window.getSelection?.() || '').trim()) return;  // selecting text, not opening
    const href = link === row ? row.dataset.rowHref : link.href;
    event.preventDefault();
    if (newTab) { window.open(href, '_blank', 'noopener'); return; }
    if (link === row) { const a = document.createElement('a'); a.href = href; a.hidden = true; row.appendChild(a); a.click(); a.remove(); }
    else link.click();
  };

  document.addEventListener('click', (e) => { if (e.button === 0) go(e, e.ctrlKey || e.metaKey || e.shiftKey); });
  document.addEventListener('auxclick', (e) => { if (e.button === 1) go(e, true); });
  // mark rows lazily so the pointer cursor / hover shows only where a click does something
  document.addEventListener('pointerover', (e) => { const row = rowOf(e.target); if (row) target(row); }, { passive: true });

  window.mqRowLink = { target };
})();
