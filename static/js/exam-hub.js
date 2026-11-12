/*
 * «مدیریت آزمون» page (templates/exam_hub/, apps/core/exam_hub.py). Everything is delegated or re-run on
 * mq:live-load, because tabs, filters and paging swap #xh-page without a reload (live-region.js).
 * - [data-xh-countdown="seconds"]: counts down to 00:00:00 (data-xh-days: «n روز و …» for long waits).
 * - [data-xh-poll="seconds"] (live monitor / participant): refreshes every [data-xh-part][id] inside it from the
 *   same URL in the background (no loader, {mqBackground:true}); paused while the tab is hidden.
 * - [data-xh-counter] textarea/input: fills the [data-xh-count] next to it.
 * - [data-xh-toggle="id"]: shows / hides a detail row.  [data-xh-print]: print.  [data-xh-full]: full screen.
 */
(() => {
  if (window.__mqExamHub) return;
  window.__mqExamHub = true;

  const pad = (n) => String(n).padStart(2, '0');
  const hms = (s) => `${pad(Math.floor(s / 3600))}:${pad(Math.floor((s % 3600) / 60))}:${pad(s % 60)}`;
  const clocks = new Map(); // element → end moment (performance.now based)

  const scanClocks = (root) => {
    (root || document).querySelectorAll('[data-xh-countdown]').forEach((el) => {
      if (clocks.has(el)) return;
      const seconds = Math.max(0, parseInt(el.dataset.xhCountdown, 10) || 0);
      clocks.set(el, performance.now() + seconds * 1000);
      paint(el, seconds);
    });
  };
  const paint = (el, s) => {
    if (el.hasAttribute('data-xh-days') && s >= 86400) {
      el.textContent = `${Math.floor(s / 86400)} روز و ${hms(s % 86400)}`;
    } else {
      el.textContent = hms(s);
    }
  };
  setInterval(() => {
    const now = performance.now();
    clocks.forEach((end, el) => {
      if (!el.isConnected) { clocks.delete(el); return; }
      paint(el, Math.max(0, Math.round((end - now) / 1000)));
    });
  }, 1000);

  const fillCounter = (field) => {
    const box = field.closest('label, .xh-field, form');
    const out = box && box.querySelector('[data-xh-count]');
    if (out) out.textContent = String(field.value.length);
  };
  const scanCounters = (root) => (root || document).querySelectorAll('[data-xh-counter]').forEach(fillCounter);
  document.addEventListener('input', (event) => {
    if (event.target.matches && event.target.matches('[data-xh-counter]')) fillCounter(event.target);
    if (event.target.matches && event.target.matches('[data-xh-rubric], [data-xh-grade] input[name="score"]')) grade(event.target.closest('[data-xh-grade]'));
  });
  document.addEventListener('change', (event) => {
    const box = event.target.matches && event.target.matches('[data-xh-switch-text]') ? event.target.closest('label').querySelector('small') : null;
    if (box) box.textContent = event.target.checked ? box.dataset.on : box.dataset.off;
  });

  // «تصحیح پاسخ»: rubric sum → the question's points (same rule as grading_views._grade_from_post).
  const num = (v) => Number(String(v || '').replace(/[۰-۹]/g, (d) => '۰۱۲۳۴۵۶۷۸۹'.indexOf(d)).replace('٫', '.')) || 0;
  const fmt = (n) => String(Math.round(n * 100) / 100);
  const grade = (form) => {
    if (!form) return;
    const max = num(form.dataset.max);
    const inputs = [...form.querySelectorAll('[data-xh-rubric]')];
    const out = form.querySelector('[data-xh-final]');
    if (!inputs.length) { const single = form.querySelector('input[name="score"]'); if (out && single) out.textContent = single.value ? fmt(num(single.value)) : '—'; return; }
    const total = num(form.dataset.rubricTotal);
    const earned = inputs.reduce((sum, el) => sum + num(el.value), 0);
    let awarded = total ? earned / total * max : 0;
    if (form.dataset.integer) awarded = Math.round(awarded);
    const calc = form.querySelector('[data-xh-calc]');
    if (calc) calc.textContent = `${inputs.map((el) => fmt(num(el.value))).join(' + ')} = ${fmt(earned)} از ${fmt(total)}`;
    if (out) out.textContent = fmt(awarded);
  };
  const scanGrades = (root) => (root || document).querySelectorAll('[data-xh-grade]').forEach(grade);

  document.addEventListener('click', (event) => {
    const toggle = event.target.closest('[data-xh-toggle]');
    if (toggle) {
      const row = document.getElementById(toggle.dataset.xhToggle);
      if (row) {
        row.hidden = !row.hidden;
        toggle.setAttribute('aria-expanded', String(!row.hidden));
        if (!row.hidden) scanCounters(row);
      }
      return;
    }
    if (event.target.closest('[data-xh-print]')) { window.print(); return; }
    const copy = event.target.closest('[data-xh-copy]');
    if (copy) {
      const text = copy.parentElement.querySelector('[data-xh-copy-text]');
      if (text && navigator.clipboard) navigator.clipboard.writeText(text.textContent.trim()).catch(() => {});
      return;
    }
    const full = event.target.closest('[data-xh-full]');
    if (full) {
      const root = document.querySelector('[data-xh-root]');
      if (!root) return;
      if (document.fullscreenElement) document.exitFullscreen();
      else if (root.requestFullscreen) root.requestFullscreen().catch(() => root.classList.toggle('xh-full'));
      else root.classList.toggle('xh-full');
    }
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') document.querySelectorAll('.xh-full').forEach((el) => el.classList.remove('xh-full'));
  });

  // Background refresh of the live parts.
  let pollTimer = null;
  let polling = false;
  const poll = async () => {
    const host = document.querySelector('[data-xh-poll]');
    if (!host || document.hidden || polling) return;
    polling = true;
    try {
      const response = await fetch(window.location.href, {credentials: 'same-origin', headers: {'X-Requested-With': 'fetch'}, mqBackground: true});
      if (!response.ok || response.redirected) return;
      const doc = new DOMParser().parseFromString(await response.text(), 'text/html');
      host.querySelectorAll('[data-xh-part][id]').forEach((part) => {
        const fresh = doc.getElementById(part.id);
        if (!fresh) return;
        // keep an open «…» or focused control untouched
        if (part.contains(document.activeElement) && document.activeElement !== document.body) return;
        const node = document.importNode(fresh, true);
        part.replaceWith(node);
        scanClocks(node);
        node.dispatchEvent(new CustomEvent('mq:live-load', {bubbles: true}));
      });
    } catch (error) {
      // offline for a moment: try again next round
    } finally {
      polling = false;
    }
  };
  const startPolling = () => {
    clearInterval(pollTimer);
    const host = document.querySelector('[data-xh-poll]');
    const seconds = host ? parseInt(host.dataset.xhPoll, 10) : 0;
    if (seconds > 0) pollTimer = setInterval(poll, Math.max(seconds, 10) * 1000);
  };

  const init = (root) => { scanClocks(root); scanCounters(root); scanGrades(root); startPolling(); };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', () => init());
  else init();
  document.addEventListener('mq:live-load', (event) => {
    if (event.target && event.target.id === 'xh-page') init(event.target);
  });
})();
