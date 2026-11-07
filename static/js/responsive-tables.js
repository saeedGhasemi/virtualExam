// Responsive tables: a listing table that is wider than the space it has becomes a stack of cards
// (each cell labelled with its column header) instead of scrolling sideways. Tables that fit stay tables.
// Card styles live in static/css/responsive.css (table.rt-cards).
(() => {
  // editors, answer matrices and print-only tables keep their table layout
  const SKIP = '.qx-matrix, .qb2-matrix, .qb-rubric, .gd-rubric, .ob-crit-table, .manager-bulk-map-table, .score-alloc-table, .sr-only, .srd-print-info, .grading-aid-table, .map-table, .rt-off';

  const label = (table) => {
    if (table.dataset.rtState) return table.dataset.rtState === 'ok';
    const head = table.tHead && table.tHead.rows.length === 1 ? [...table.tHead.rows[0].cells] : null;
    if (!head || !head.length || head.some((cell) => cell.colSpan > 1)) {
      table.dataset.rtState = 'skip';
      return false;
    }
    const names = head.map((cell) => cell.textContent.trim().replace(/\s+/g, ' '));
    for (const body of table.tBodies) {
      for (const row of body.rows) {
        if ([...row.cells].some((cell) => cell.colSpan > 1 || cell.rowSpan > 1)) continue; // e.g. "no data" rows
        [...row.cells].forEach((cell, i) => {
          if (!cell.hasAttribute('data-label')) cell.setAttribute('data-label', names[i] || '');
        });
      }
    }
    table.dataset.rtState = 'ok';
    return true;
  };

  const fit = () => {
    document.querySelectorAll('table').forEach((table) => {
      if (table.matches(SKIP) || table.closest('.qx, [contenteditable], .ql-editor')) return;
      if (!label(table)) return;
      table.classList.remove('rt-cards');
      const box = table.parentElement;
      if (!box || !box.clientWidth) return;
      if (table.offsetWidth > box.clientWidth + 2) table.classList.add('rt-cards');
    });
  };

  let timer = null;
  const later = () => { clearTimeout(timer); timer = setTimeout(fit, 120); };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', fit); else fit();
  window.addEventListener('load', fit);
  window.addEventListener('resize', later);
})();
