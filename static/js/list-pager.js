/*
 * Listing pager (user's choice, 2026-11-11): every listing shows at most PAGE_SIZE items; the rest is reached with a
 * pager under it (prev / page numbers / next + «۱۱–۲۰ از ۴۳»), all in the page, no reload.
 * Styles: static/css/responsive.css → "Listing pager".
 *
 * What gets one:
 * - every table responsive-tables.js handles (data-rt-state="ok"), in table and card view alike (card view is the
 *   same rows). Skipped: tables with rowspan cells, and any table inside / marked data-pager="off" (a server pager
 *   whose page size the user picks). Server-paged lists use 10 per page too, so they never get a second pager.
 * - any other container marked data-pager (e.g. a grid of person cards): its element children are the items.
 * data-pager="5" sets another page size.
 * Lists a page pages itself (e.g. the wizards' JS-filtered tables) render the same pager with
 * window.mqPager.markup(page, pages, total, size) into an element with class mq-pager (buttons carry data-pg), hidden
 * when there is only one page. Server-paged lists use the {% mq_pager %} tag (core_extras), which renders nothing then.
 *
 * Items hidden by the page itself (hidden attribute / inline display:none, e.g. a client-side search) are left out of
 * the count; when that set changes the pager re-counts and goes back to page 1. A table row with a colspan cell right
 * after a normal row (a detail / expand row) moves with that row. Our own hiding is the class mq-pg-out (print shows
 * everything). The pager hides while its list is hidden (other view, inactive tab). Re-runs after live-region swaps
 * (mq:live-load). Whenever other items come on screen it fires a bubbling "mq:pager" at once (responsive-tables.js
 * re-measures before the next paint).
 */
(() => {
  if (window.__mqListPager) return;
  window.__mqListPager = true;

  const PAGE_SIZE = 10;
  const OUT = 'mq-pg-out';
  const fa = (n) => String(n).replace(/[0-9]/g, (d) => '۰۱۲۳۴۵۶۷۸۹'[d]);
  const lists = new Map(); // list element → state
  const ICON_PREV = '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="m9 18 6-6-6-6"/></svg>';
  const ICON_NEXT = '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="m15 18-6-6 6-6"/></svg>';

  const sizeOf = (list) => {
    const n = parseInt(list.getAttribute('data-pager'), 10);
    return n > 0 ? n : PAGE_SIZE;
  };
  const filteredOut = (el) => el.hidden || el.style.display === 'none';

  // items the page shows (not filtered out by its own scripts); table rows grouped with their detail rows
  const groupsOf = (list) => {
    if (list.tagName !== 'TABLE') {
      return [...list.children].filter((el) => !el.classList.contains('mq-pager') && !/^(SCRIPT|STYLE|TEMPLATE)$/.test(el.tagName) && !filteredOut(el)).map((el) => [el]);
    }
    const groups = [];
    for (const body of list.tBodies) {
      for (const row of body.rows) {
        if (filteredOut(row)) continue;
        const detail = [...row.cells].some((c) => c.colSpan > 1);
        if (detail && groups.length && groups[groups.length - 1][0].parentElement === body) groups[groups.length - 1].push(row);
        else groups.push([row]);
      }
    }
    return groups;
  };

  // the box that scrolls the page: panel layouts scroll an inner box (.app-main), others the window (null)
  const scrollerOf = (el) => {
    for (let n = el.parentElement; n && n !== document.body && n !== document.documentElement; n = n.parentElement) {
      const oy = getComputedStyle(n).overflowY;
      if ((oy === 'auto' || oy === 'scroll' || oy === 'overlay')
        && n.scrollHeight > n.clientHeight + 1 && n.clientHeight > window.innerHeight / 2) return n; // not a table's sideways box
    }
    return null;
  };
  // the pager goes after the list, or after a table's scroll box (so it doesn't scroll sideways with the table)
  const anchorOf = (list) => {
    let el = list;
    if (list.tagName !== 'TABLE') return el;
    for (let i = 0; i < 3; i += 1) {
      const parent = el.parentElement;
      if (!parent || parent.matches('body, main, section, article, form, td, [data-live-region]')) break;
      const kids = [...parent.children].filter((n) => !n.classList.contains('mq-pager') && !/^(SCRIPT|STYLE)$/.test(n.tagName));
      if (kids.length !== 1) break;
      const cs = getComputedStyle(parent);
      if (cs.overflowX === 'visible' && cs.overflowY === 'visible') break;
      el = parent;
    }
    return el;
  };

  // page numbers to show: first, last, current ±1 (more near the ends), with gaps (null) between
  const numbers = (page, pages) => {
    const want = new Set([1, pages, page - 1, page, page + 1]);
    if (page <= 3) [2, 3, 4].forEach((n) => want.add(n));
    if (page >= pages - 2) [pages - 1, pages - 2, pages - 3].forEach((n) => want.add(n));
    const list = [...want].filter((n) => n >= 1 && n <= pages).sort((a, b) => a - b);
    const out = [];
    list.forEach((n, i) => {
      if (i && n - list[i - 1] > 1) out.push(n - list[i - 1] === 2 ? n - 1 : null);
      out.push(n);
    });
    return out;
  };

  // the pager's inner markup (also used by pages that page their own lists: window.mqPager.markup)
  const markup = (page, pages, total, size) => {
    const from = (page - 1) * size + 1;
    const to = Math.min(total, page * size);
    const btn = (n) => `<button type="button" class="mq-pg-num${n === page ? ' is-active' : ''}" data-pg="${n}"${n === page ? ' aria-current="page"' : ''} aria-label="صفحه ${fa(n)}">${fa(n)}</button>`;
    return `<span class="mq-pg-info" aria-live="polite">${from === to ? fa(to) : `${fa(from)}–${fa(to)}`} از ${fa(total)}</span>`
      + '<span class="mq-pg-btns">'
      + `<button type="button" class="mq-pg-step" data-pg="${page - 1}"${page === 1 ? ' disabled' : ''} aria-label="صفحه قبل">${ICON_PREV}<span>قبلی</span></button>`
      + numbers(page, pages).map((n) => (n === null ? '<span class="mq-pg-gap" aria-hidden="true">…</span>' : btn(n))).join('')
      + `<span class="mq-pg-now" aria-hidden="true">${fa(page)} از ${fa(pages)}</span>`
      + `<button type="button" class="mq-pg-step" data-pg="${page + 1}"${page === pages ? ' disabled' : ''} aria-label="صفحه بعد"><span>بعدی</span>${ICON_NEXT}</button>`
      + '</span>';
  };
  const render = (st, total, size) => { st.nav.innerHTML = markup(st.page, Math.ceil(total / size), total, size); };

  // the pager follows its list's visibility (card/table view switches, tabs)
  const syncShown = (st) => {
    if (!st.nav.isConnected) return;
    const shown = st.list.getClientRects().length > 0 && !st.list.closest('[hidden]');
    if (st.nav.hidden === shown) st.nav.hidden = !shown;
  };

  const apply = (st) => {
    const {list} = st;
    const size = sizeOf(list);
    const groups = groupsOf(list);
    const sig = `${groups.length}|${groups.map((g) => g.length).join(',')}`;
    if (sig !== st.sig) { st.sig = sig; st.page = 1; }
    const pages = Math.max(1, Math.ceil(groups.length / size));
    st.page = Math.min(Math.max(1, st.page), pages);
    const first = (st.page - 1) * size;
    let changed = false;
    groups.forEach((g, i) => {
      const out = groups.length > size && (i < first || i >= first + size);
      g.forEach((el) => { if (el.classList.contains(OUT) !== out) { el.classList.toggle(OUT, out); changed = true; } });
    });
    // items the page hid itself don't keep our class (they come back on the page's own terms)
    list.querySelectorAll(`.${OUT}`).forEach((el) => { if (filteredOut(el)) el.classList.remove(OUT); });
    if (groups.length > size) {
      if (!st.nav.isConnected) {
        const anchor = anchorOf(list);
        anchor.after(st.nav);
        // line up with the list's content (a card grid's own side padding)
        const cs = getComputedStyle(anchor);
        st.nav.style.paddingInline = `${Math.max(parseFloat(cs.paddingRight) || 0, 2)}px ${Math.max(parseFloat(cs.paddingLeft) || 0, 2)}px`;
        if ((parseFloat(cs.paddingBottom) || 0) > 4) st.nav.style.marginTop = '0';
        if (list.tagName !== 'TABLE' && (parseFloat(cs.paddingBottom) || 0) > 4) st.nav.style.marginBottom = `${parseFloat(cs.paddingBottom)}px`;
      }
      render(st, groups.length, size);
      syncShown(st);
    } else st.nav.remove();
    return changed;
  };
  // other rows on screen: responsive-tables.js re-measures (column widths, lead rows) at once, before the next paint,
  // so a page never shows with the previous rows' widths first
  const refit = (target) => target.dispatchEvent(new CustomEvent('mq:pager', {bubbles: true}));

  const attach = (list) => {
    if (lists.has(list)) return apply(lists.get(list));
    if (list.closest('[data-pager="off"]')) return;
    if (list.tagName === 'TABLE' && (list.dataset.rtState !== 'ok' || list.querySelector('td[rowspan]:not([rowspan="1"]), th[rowspan]:not([rowspan="1"])'))) return;
    const nav = document.createElement('nav');
    nav.className = 'mq-pager';
    nav.setAttribute('aria-label', 'صفحه‌بندی فهرست');
    nav.setAttribute('data-no-loader', '');
    const st = {list, nav, page: 1, sig: null};
    lists.set(list, st);
    nav.addEventListener('click', (e) => {
      const b = e.target.closest('button[data-pg]');
      if (!b || b.disabled) return;
      st.page = parseInt(b.getAttribute('data-pg'), 10) || 1;
      apply(st);
      // back to the list's top: a short glide, or an instant jump when it is far (a long glide looks like the page flying).
      // Panel layouts scroll an inner box (.app-main), not the window.
      const box = scrollerOf(list);
      const viewTop = box ? box.getBoundingClientRect().top : 0;
      const top = anchorOf(list).getBoundingClientRect().top - viewTop;
      const viewH = box ? box.clientHeight : window.innerHeight;
      if (top < 0) (box || window).scrollBy({top: top - (box ? 12 : 90), behavior: top > -viewH ? 'smooth' : 'instant'});
      const again = nav.querySelector('button.is-active') || nav.querySelector('.mq-pg-step:not([disabled])');
      if (again) again.focus({preventScroll: true});
      refit(list);
    });
    // the page's own filters (hidden / style) and added or removed items re-count the pager
    const relevant = (m) => (m.type === 'childList'
      ? m.target === list || m.target.tagName === 'TBODY'
      : m.target.parentElement === list || m.target.tagName === 'TR');
    // (observer callbacks run before the next paint; our own class changes aren't observed, so no loop)
    st.observer = new MutationObserver((records) => {
      if (list.isConnected && records.some(relevant) && apply(st)) refit(list);
    });
    st.observer.observe(list, {subtree: true, childList: true, attributes: true, attributeFilter: ['hidden', 'style']});
    return apply(st);
  };

  const scan = () => {
    lists.forEach((st, list) => { if (!list.isConnected) { st.observer.disconnect(); st.nav.remove(); lists.delete(list); } });
    let changed = false;
    document.querySelectorAll('table[data-rt-state="ok"], [data-pager]:not(table):not([data-pager="off"])').forEach((list) => { if (attach(list)) changed = true; });
    if (changed) refit(document);
  };
  const syncAll = () => lists.forEach(syncShown);

  // responsive-tables.js labels tables on DOMContentLoaded / load / mq:live-load; this file loads after it
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', scan); else scan();
  window.addEventListener('load', scan);
  // after a live swap: in the same task as responsive-tables.js's pass (queued before this one), so the swapped-in
  // list is never painted with all its rows first
  let queued = false;
  document.addEventListener('mq:live-load', () => { if (queued) return; queued = true; queueMicrotask(() => { queued = false; scan(); }); });
  // view switches and tabs are clicks: re-check which pagers are on screen once the page has reacted
  document.addEventListener('click', () => { syncAll(); setTimeout(syncAll, 60); });
  window.addEventListener('resize', () => setTimeout(syncAll, 150));
  window.mqPager = {scan, markup};
})();
