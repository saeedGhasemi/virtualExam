// Balanced wrapping strips (styles: static/css/responsive.css → "No sideways-scrolling strips").
// A strip is a flex row whose items grow (flex: 1 1 <min width>), so every row is filled edge to edge. Left alone,
// wrapping makes uneven rows (13 items → 11 + 2 huge ones); this keeps the same number of rows but sizes items so the
// rows differ by at most one item (13 → 7 + 6, or 3 + 3 + 3 + 2 + 2 on a phone). Items keep their CSS min width.
// Strips: the selector below, or any element with data-balance-rows. Re-run on resize and live-region loads.
(() => {
  const STRIPS = '.question-type-strip, .exam-wizard .wizard-steps, .ob-tabs, .tstu-tabs, [data-balance-rows]';

  const balance = (strip) => {
    const items = [...strip.children].filter((n) => !n.hidden && getComputedStyle(n).display !== 'none' && getComputedStyle(n).position !== 'absolute');
    items.forEach((n) => n.style.removeProperty('flex-basis'));
    const cs = getComputedStyle(strip);
    if (!cs.display.includes('flex') || cs.flexWrap !== 'wrap' || items.length < 2) return; // e.g. wide wizard: its own layout
    const width = strip.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
    const gap = parseFloat(cs.columnGap) || 0;
    const min = Math.max(...items.map((n) => parseFloat(getComputedStyle(n).flexBasis) || n.getBoundingClientRect().width));
    if (!width || !min) return;
    const fit = Math.max(1, Math.floor((width + gap) / (min + gap)));
    if (fit >= items.length) return; // one row: the items already share it
    // same number of rows, row lengths differing by at most one: the first `extra` rows get one item more
    const rows = Math.ceil(items.length / fit);
    const base = Math.floor(items.length / rows);
    const extra = items.length % rows;
    // -0.5px: rounding must never push the k-th item onto the next row
    const basis = (k) => `calc((100% - ${(k - 1) * gap}px) / ${k} - .5px)`;
    items.forEach((n, i) => { n.style.flexBasis = basis(i < extra * (base + 1) ? base + 1 : base); });
  };

  const run = () => document.querySelectorAll(STRIPS).forEach(balance);
  let timer = null;
  const later = () => { clearTimeout(timer); timer = setTimeout(run, 100); };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', run); else run();
  window.addEventListener('load', run);
  window.addEventListener('resize', later);
  document.addEventListener('mq:live-load', run);
})();
