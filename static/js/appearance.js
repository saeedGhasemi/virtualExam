/* «رنگ اصلی سامانه» and «اندازه فونت» from the admin's appearance settings (apps/core/appearance.py).

   The panels hard-code their brand blues (#2563eb, #1d4ed8, #4f46e5, rgba(37,99,235,.2), Tailwind rgb(37 99 235 / …), …)
   in hundreds of places, so the colour is applied here: every colour of the blue/indigo brand family (hue 205–250°,
   saturated, not the dark navy text colours) in same-origin stylesheets, <style> blocks, style="" and SVG paint
   attributes is moved to the chosen colour, keeping each shade's relative hue, saturation and lightness. Status colours
   (green/red/amber/violet) and greys are untouched; pale cyan/sky tints and light translucent glows around the blues
   (header gradient, page washes) take the chosen hue too. px font sizes become calc(Npx * var(--mq-fs)) so the text-size
   setting reaches them too (rem sizes follow the root size set in appearance.css).

   Loaded synchronously in <head> right after the stylesheets: it runs only when <html data-mq-accent> is set or the
   font isn't "medium" (otherwise it does nothing until MQAppearance.preview() is called by the settings page). Content
   added later (live-region swaps, scripts) is handled by a MutationObserver. Inline colours inside [data-mq-keep] are
   left alone. */
(() => {
  'use strict';
  const root = document.documentElement;
  const REF = rgbToHsl(37, 99, 235); // #2563EB, the colour the panels were designed with
  const TOKEN = /url\([^)]*\)|#(?:[0-9a-fA-F]{3,8})\b|rgba?\(\s*\d+(?:\.\d+)?[\s,]+\d+(?:\.\d+)?[\s,]+\d+(?:\.\d+)?(?:\s*[,/]\s*\d*\.?\d+%?)?/g;
  const PX_FONT = /^-?\d*\.?\d+px$/;
  const ATTRS = ['style', 'fill', 'stroke', 'stop-color'];
  const SHORTHANDS = ['background', 'border', 'border-color', 'border-top', 'border-right', 'border-bottom', 'border-left',
    'border-block', 'border-inline', 'border-block-start', 'border-block-end', 'border-inline-start', 'border-inline-end',
    'outline', 'text-decoration', 'column-rule'];

  let target = null; // HSL of the chosen colour, null = designed colours
  let active = false;
  const entries = []; // stylesheet declarations holding brand colours: {style, prop, orig, prio}
  const seenSheets = new WeakSet();
  const elements = new Set(); // elements whose attributes hold brand colours / px fonts
  const original = new WeakMap(); // element → {attr: authored value}
  const written = new WeakMap(); // element → {attr: value we wrote} (to ignore our own mutations)

  function clamp(v, lo, hi) { return Math.min(hi, Math.max(lo, v)); }

  function rgbToHsl(r, g, b) {
    r /= 255; g /= 255; b /= 255;
    const max = Math.max(r, g, b), min = Math.min(r, g, b), l = (max + min) / 2;
    if (max === min) return { h: 0, s: 0, l };
    const d = max - min;
    const s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
    let h;
    if (max === r) h = (g - b) / d + (g < b ? 6 : 0);
    else if (max === g) h = (b - r) / d + 2;
    else h = (r - g) / d + 4;
    return { h: h * 60, s, l };
  }

  function hslToRgb(h, s, l) {
    h = ((h % 360) + 360) % 360 / 360;
    if (s === 0) { const v = Math.round(l * 255); return [v, v, v]; }
    const q = l < 0.5 ? l * (1 + s) : l + s - l * s, p = 2 * l - q;
    const f = (t) => {
      if (t < 0) t += 1; if (t > 1) t -= 1;
      if (t < 1 / 6) return p + (q - p) * 6 * t;
      if (t < 1 / 2) return q;
      if (t < 2 / 3) return p + (q - p) * (2 / 3 - t) * 6;
      return p;
    };
    return [f(h + 1 / 3), f(h), f(h - 1 / 3)].map((v) => Math.round(v * 255));
  }

  function hexToRgb(hex) {
    let d = hex.replace('#', '');
    if (d.length === 3 || d.length === 4) d = d.split('').map((c) => c + c).join('');
    if (d.length !== 6 && d.length !== 8) return null;
    return [0, 2, 4].map((i) => parseInt(d.slice(i, i + 2), 16));
  }

  function inFamily(hsl) {
    return hsl.h >= 205 && hsl.h <= 250 && hsl.s >= 0.45 && hsl.l >= 0.27 && hsl.l <= 0.985;
  }

  // the panels' background washes next to the blues: pale cyan/sky/blue tints (header gradient #e8f7f8 → #eaf2ff,
  // page tints) and light translucent glows (rgba(91,255,216,.2) …). Solid/darker teal and green status colours aren't.
  function isWash(hsl, alpha) {
    if (hsl.s < 0.3 || hsl.h > 250) return false;
    if (hsl.l >= 0.88 && hsl.h >= 175) return true;
    return alpha <= 0.35 && hsl.l >= 0.55 && hsl.h >= 165;
  }

  function isBrand(rgb, alpha) {
    const hsl = rgbToHsl(rgb[0], rgb[1], rgb[2]);
    return inFamily(hsl) || isWash(hsl, alpha);
  }

  function mapRgb(rgb, alpha) {
    const hsl = rgbToHsl(rgb[0], rgb[1], rgb[2]);
    if (!inFamily(hsl)) {
      if (!isWash(hsl, alpha)) return null;
      return target ? hslToRgb(target.h, Math.min(hsl.s, target.s), hsl.l) : rgb; // a wash takes the colour's hue as is
    }
    if (!target) return rgb;
    const weight = Math.max(0, 1 - Math.abs(hsl.l - REF.l) / 0.45); // mid tones follow the target's lightness, tints stay light
    return hslToRgb(
      target.h + (hsl.h - REF.h),
      clamp(hsl.s * (REF.s ? target.s / REF.s : 1), 0, 1),
      clamp(hsl.l + (target.l - REF.l) * weight, 0, 1),
    );
  }

  function tokenRgb(token) {
    if (token[0] === '#') return hexToRgb(token);
    const nums = token.match(/\d+(?:\.\d+)?/g);
    return nums && nums.length >= 3 ? nums.slice(0, 3).map(Number) : null;
  }

  function tokenAlpha(token) {
    if (token[0] === '#') {
      const d = token.slice(1);
      if (d.length === 8) return parseInt(d.slice(6), 16) / 255;
      if (d.length === 4) return parseInt(d[3] + d[3], 16) / 255;
      return 1;
    }
    const m = token.match(/[,/]\s*(\d*\.?\d+)(%?)\s*$/);
    const parts = token.match(/\d+(?:\.\d+)?/g) || [];
    if (!m || parts.length < 4) return 1;
    return m[2] ? Number(m[1]) / 100 : Number(m[1]);
  }

  function hasBrand(value) {
    TOKEN.lastIndex = 0;
    let m;
    while ((m = TOKEN.exec(value))) {
      if (m[0][0] === 'u' || m[0][0] === 'U') continue;
      const rgb = tokenRgb(m[0]);
      if (rgb && isBrand(rgb, tokenAlpha(m[0]))) return true;
    }
    return false;
  }

  function recolor(value) {
    if (!target) return value;
    return value.replace(TOKEN, (token) => {
      if (token[0] === 'u' || token[0] === 'U') return token;
      const rgb = tokenRgb(token);
      const mapped = rgb && mapRgb(rgb, tokenAlpha(token));
      if (!mapped) return token;
      if (token[0] === '#') {
        const digits = token.slice(1);
        const alpha = digits.length === 8 ? digits.slice(6) : digits.length === 4 ? digits[3].repeat(2) : '';
        return '#' + mapped.map((v) => v.toString(16).padStart(2, '0')).join('') + alpha;
      }
      // rgb(37, 99, 235 … / rgba(37 99 235 … : swap only the three channels, keep separators and alpha
      let i = 0;
      return token.replace(/\d+(?:\.\d+)?/g, (n) => (i < 3 ? String(mapped[i++]) : n));
    });
  }

  function scaleFonts(styleText) {
    return styleText.replace(/(font-size\s*:\s*)(-?\d*\.?\d+px)/gi, '$1calc($2 * var(--mq-fs, 1))');
  }

  // ---------- stylesheets ----------
  function scanStyle(style) {
    for (let i = 0; i < style.length; i += 1) {
      const prop = style[i];
      const value = style.getPropertyValue(prop);
      if (!value) continue;
      const prio = style.getPropertyPriority(prop);
      if (prop === 'font-size' && PX_FONT.test(value.trim())) {
        style.setProperty(prop, `calc(${value.trim()} * var(--mq-fs, 1))`, prio);
        continue;
      }
      if ((value.indexOf('#') !== -1 || value.indexOf('rgb') !== -1) && hasBrand(value)) {
        const entry = { style, prop, orig: value, prio };
        entries.push(entry);
        applyEntry(entry);
      }
    }
    // a shorthand holding var() (Tailwind: border-color: rgb(37 99 235/var(--tw-border-opacity))) exposes its value
    // only on the shorthand; its longhands read as ''
    for (const prop of SHORTHANDS) {
      const value = style.getPropertyValue(prop);
      if (!value || value.indexOf('var(') === -1 || !hasBrand(value)) continue;
      const entry = { style, prop, orig: value, prio: style.getPropertyPriority(prop) };
      entries.push(entry);
      applyEntry(entry);
    }
  }

  function scanRules(rules) {
    for (let i = 0; i < rules.length; i += 1) {
      const rule = rules[i];
      if (rule.style) scanStyle(rule.style);
      if (rule.cssRules) scanRules(rule.cssRules);
    }
  }

  function scanSheets() {
    for (const sheet of Array.from(document.styleSheets)) {
      if (seenSheets.has(sheet)) continue;
      let rules;
      try { rules = sheet.cssRules; } catch (e) { seenSheets.add(sheet); continue; } // cross-origin
      if (!rules) continue;
      seenSheets.add(sheet);
      scanRules(rules);
    }
  }

  function applyEntry(entry) {
    const next = recolor(entry.orig);
    if (entry.style.getPropertyValue(entry.prop) !== next) entry.style.setProperty(entry.prop, next, entry.prio);
  }

  // ---------- elements (style="" and SVG paint attributes) ----------
  function transformAttr(attr, value) {
    const colored = recolor(value);
    return attr === 'style' ? scaleFonts(colored) : colored;
  }

  function writeAttrs(el) {
    const orig = original.get(el);
    if (!orig) return;
    const mine = written.get(el) || {};
    Object.keys(orig).forEach((attr) => {
      const next = transformAttr(attr, orig[attr]);
      mine[attr] = next;
      if (el.getAttribute(attr) !== next) el.setAttribute(attr, next);
    });
    written.set(el, mine);
  }

  function handleElement(el) {
    if (el.closest('[data-mq-keep]')) return; // e.g. the colour swatches of the settings page show their own colours
    let changed = false;
    for (const attr of ATTRS) {
      const value = el.getAttribute(attr);
      if (value === null) continue;
      const mine = written.get(el);
      if (mine && mine[attr] === value) continue; // our own write
      const relevant = hasBrand(value) || (attr === 'style' && /font-size\s*:\s*-?\d*\.?\d+px/i.test(value));
      const orig = original.get(el) || {};
      if (relevant) { orig[attr] = value; changed = true; } else if (attr in orig) { delete orig[attr]; }
      original.set(el, orig);
    }
    if (changed) { elements.add(el); writeAttrs(el); }
  }

  function handleTree(node) {
    if (node.nodeType !== 1) return;
    if (node.hasAttribute('style') || node.hasAttribute('fill') || node.hasAttribute('stroke') || node.hasAttribute('stop-color')) handleElement(node);
    node.querySelectorAll('[style],[fill],[stroke],[stop-color]').forEach(handleElement);
  }

  // ---------- lifecycle ----------
  const observer = new MutationObserver((records) => {
    let sheets = false;
    for (const record of records) {
      if (record.type === 'attributes') { handleElement(record.target); continue; }
      if (record.target.nodeName === 'STYLE') sheets = true;
      record.addedNodes.forEach((node) => {
        if (node.nodeName === 'STYLE' || node.nodeName === 'LINK') sheets = true;
        else handleTree(node);
        if (node.nodeType === 1 && node.querySelector && node.querySelector('style')) sheets = true;
      });
    }
    if (sheets) scanSheets();
  });

  function activate() {
    if (active) return;
    active = true;
    scanSheets();
    handleTree(root);
    observer.observe(root, { childList: true, subtree: true, attributes: true, attributeFilter: ATTRS });
    document.addEventListener('load', (event) => { if (event.target && event.target.nodeName === 'LINK') scanSheets(); }, true);
    document.addEventListener('DOMContentLoaded', () => { scanSheets(); handleTree(root); });
  }

  function setColor(hex) {
    const rgb = /^#[0-9a-fA-F]{6}$/.test(hex || '') ? hexToRgb(hex) : null;
    const hsl = rgb && rgbToHsl(rgb[0], rgb[1], rgb[2]);
    const isDefault = !hsl || (Math.abs(hsl.h - REF.h) < 0.5 && Math.abs(hsl.s - REF.s) < 0.005 && Math.abs(hsl.l - REF.l) < 0.005);
    target = isDefault ? null : hsl;
    entries.forEach(applyEntry);
    elements.forEach((el) => { if (el.isConnected) writeAttrs(el); else elements.delete(el); });
  }

  const font = root.dataset.mqFont;
  if (root.dataset.mqAccent || (font && font !== 'medium')) {
    activate();
    setColor(root.dataset.mqAccent);
  }

  // used by the settings page to preview unsaved values on the page itself
  window.MQAppearance = {
    preview(values) {
      const v = values || {};
      if (v.theme) root.dataset.mqTheme = v.theme;
      if (v.font) root.dataset.mqFont = v.font;
      if (v.color !== undefined) {
        activate();
        setColor(v.color);
      } else if (v.font && v.font !== 'medium') {
        activate();
      }
    },
  };
})();
