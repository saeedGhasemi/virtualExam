// Shared exam list (templates/partials/exam_list/list.html): table/card switch, «…» menu, copy exam code.
// Everything is delegated, so it keeps working after live-region.js swaps the list.
(() => {
  if (window.__mqExamList) return;
  window.__mqExamList = true;

  // table / cards: switched at once; the choice goes into the filter form and every tab/pager link (?view=)
  // so the next live load renders the same view, and into the address bar (refresh keeps it).
  const setParam = (href, value) => {
    const url = new URL(href, location.href);
    url.searchParams.set('view', value);
    return url;
  };
  document.addEventListener('click', (event) => {
    const button = event.target.closest('[data-xl-view]');
    if (!button) return;
    const root = button.closest('[data-xl]');
    if (!root) return;
    const view = button.dataset.xlView;
    root.querySelectorAll('[data-xl-body]').forEach((body) => { body.dataset.view = view; });
    root.querySelectorAll('[data-xl-view]').forEach((item) => {
      const on = item.dataset.xlView === view;
      item.classList.toggle('is-active', on);
      item.setAttribute('aria-pressed', on ? 'true' : 'false');
    });
    root.querySelectorAll('[data-xl-view-input]').forEach((input) => { input.value = view; });
    root.querySelectorAll('.xl-tabs a[href], .xl-foot a[href]').forEach((link) => {
      const url = setParam(link.getAttribute('href'), view);
      link.setAttribute('href', url.search || '?');
    });
    try { history.replaceState(history.state, '', setParam(location.href, view)); } catch (error) { /* ignore */ }
  });

  // «…» menu: one open at a time. It floats (position:fixed) beside its button so a table
  // wrapper or card with overflow never clips it or grows a scrollbar; below the button,
  // or above it when there is no room below; kept on screen; follows scrolling/resizing.
  const place = (button, menu) => {
    menu.classList.add('is-float');
    menu.style.left = '0px'; menu.style.top = '0px';
    const origin = menu.getBoundingClientRect();  // containing block's origin (viewport unless an ancestor is transformed)
    const box = button.getBoundingClientRect();
    const width = document.documentElement.clientWidth;
    const height = window.innerHeight;
    if (box.bottom < 0 || box.top > height) { closeAll(); return; }
    const w = origin.width, h = origin.height, gap = 6, edge = 8;
    let top = box.bottom + gap;
    if (top + h + edge > height) top = box.top - h - gap >= edge ? box.top - h - gap : Math.max(edge, height - h - edge);
    const rtl = getComputedStyle(menu).direction === 'rtl';
    let left = rtl ? box.left : box.right - w;  // the menu's inline end lines up with the button's
    left = Math.min(Math.max(left, edge), Math.max(edge, width - w - edge));
    menu.style.left = `${Math.round(left - origin.left)}px`;
    menu.style.top = `${Math.round(top - origin.top)}px`;
  };
  const closeAll = (except) => {
    document.querySelectorAll('[data-xl-menu][aria-expanded="true"]').forEach((button) => {
      if (button === except) return;
      button.setAttribute('aria-expanded', 'false');
      const menu = button.nextElementSibling;
      if (menu) menu.hidden = true;
    });
  };
  document.addEventListener('click', (event) => {
    const button = event.target.closest('[data-xl-menu]');
    if (!button) {
      if (!event.target.closest('.xl-menu') || event.target.closest('.xl-menu [data-approve-url]')) closeAll();
      return;
    }
    const menu = button.nextElementSibling;
    const open = button.getAttribute('aria-expanded') !== 'true';
    closeAll(button);
    button.setAttribute('aria-expanded', open ? 'true' : 'false');
    menu.hidden = !open;
    if (!open) return;
    place(button, menu);
    menu.querySelector('a, button')?.focus({preventScroll: true});
  });
  const follow = () => {
    const button = document.querySelector('[data-xl-menu][aria-expanded="true"]');
    if (button && button.nextElementSibling) place(button, button.nextElementSibling);
  };
  window.addEventListener('scroll', follow, {capture: true, passive: true});
  window.addEventListener('resize', follow, {passive: true});
  document.addEventListener('keydown', (event) => {
    if (event.key !== 'Escape') return;
    const open = document.querySelector('[data-xl-menu][aria-expanded="true"]');
    if (!open) return;
    closeAll();
    open.focus();
  });
  document.addEventListener('mq:live-load', () => closeAll());

  // copy exam code (http pages have no clipboard API: fall back to a hidden textarea)
  document.addEventListener('click', (event) => {
    const button = event.target.closest('[data-xl-copy]');
    if (!button) return;
    const code = button.dataset.xlCopy;
    const done = () => {
      const label = button.title;
      button.title = 'کپی شد';
      button.classList.add('is-done');
      setTimeout(() => { button.title = label; button.classList.remove('is-done'); }, 1800);
    };
    if (navigator.clipboard && window.isSecureContext) { navigator.clipboard.writeText(code).then(done).catch(() => {}); return; }
    const area = document.createElement('textarea');
    area.value = code; area.style.position = 'fixed'; area.style.opacity = '0';
    document.body.appendChild(area); area.select();
    try { document.execCommand('copy'); done(); } catch (error) { /* the code stays selectable */ }
    area.remove();
  });
})();
