/* The account's own «تنظیمات ظاهری» card (templates/partials/my_appearance.html) — the admin panel's behaviour:
   every choice previews on the page at once through MQAppearance.preview() (static/js/appearance.js); nothing is
   stored until «ذخیره تغییرات» (the host page's form, or the card's own form). A bad colour code blocks that submit.
   Delegated, so it also works after a live-region tab swap. */
(() => {
  'use strict';
  if (window.__mqMyAppearance) return;
  window.__mqMyAppearance = true;

  const CARD = '[data-my-appearance]';

  const normHex = (value) => {
    const digits = String(value || '').trim().replace(/^#/, '').replace(/[۰-۹]/g, (d) => '۰۱۲۳۴۵۶۷۸۹'.indexOf(d));
    if (/^[0-9a-f]{3}$/i.test(digits)) return '#' + digits.split('').map((c) => c + c).join('').toUpperCase();
    return /^[0-9a-f]{6}$/i.test(digits) ? '#' + digits.toUpperCase() : null;
  };

  function markColor(card, hex) {
    let preset = false;
    card.querySelectorAll('[data-color]').forEach((swatch) => {
      const on = swatch.dataset.color.toUpperCase() === hex;
      preset = preset || on;
      swatch.classList.toggle('is-selected', on);
      swatch.setAttribute('aria-pressed', on ? 'true' : 'false');
    });
    const custom = card.querySelector('.ap-custom');
    custom?.classList.toggle('is-selected', !preset);
    if (custom && !preset) custom.style.setProperty('--sw', hex);
    const picker = card.querySelector('[data-ap-picker]');
    if (picker) picker.value = hex.toLowerCase();
  }

  function preview(card) {
    if (!window.MQAppearance) return;
    const code = (name) => card.querySelector(`[data-ap="${name}"]:checked`)?.value;
    const hex = normHex(card.querySelector('[data-ap-hex]')?.value);
    window.MQAppearance.preview({ theme: code('theme'), font: code('font'), ...(hex ? { color: hex } : {}) });
  }

  function setColor(card, hex) {
    const field = card.querySelector('[data-ap-hex]');
    if (!field) return;
    field.value = hex;
    markColor(card, hex);
    preview(card);
  }

  document.addEventListener('click', (event) => {
    const swatch = event.target.closest?.(`${CARD} [data-color]`);
    if (swatch) setColor(swatch.closest(CARD), swatch.dataset.color.toUpperCase());
  });

  document.addEventListener('input', (event) => {
    const card = event.target.closest?.(CARD);
    if (!card) return;
    if (event.target.matches('[data-ap-picker]')) setColor(card, event.target.value.toUpperCase());
    else if (event.target.matches('[data-ap-hex]')) {
      const hex = normHex(event.target.value);
      if (hex) { markColor(card, hex); preview(card); }
    }
  });

  document.addEventListener('change', (event) => {
    const card = event.target.closest?.(CARD);
    if (!card) return;
    if (event.target.matches('[data-ap]')) preview(card);
    if (event.target.matches('[data-ap-hex]')) {
      const hex = normHex(event.target.value);
      if (hex) event.target.value = hex;
    }
  });

  document.addEventListener('submit', (event) => {
    const form = event.target;
    const field = form.querySelector?.(`${CARD} [data-ap-hex]`) || (form.matches?.(CARD) ? form.querySelector('[data-ap-hex]') : null);
    if (!field) return;
    const hex = normHex(field.value);
    if (!hex) {
      event.preventDefault();
      event.stopImmediatePropagation();
      field.setCustomValidity('کد رنگ باید به شکل #RRGGBB باشد.');
      field.reportValidity();
      field.addEventListener('input', () => field.setCustomValidity(''), { once: true });
      return;
    }
    field.value = hex;
  }, true);
})();
