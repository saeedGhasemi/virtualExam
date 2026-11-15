/* Jalali calendar for typed date boxes (user's requirement: «تاریخ تولد» gets a real date picker like professional sites).
   static/js/field-rules.js calls window.mqDatePicker.attach(input, kind) for every `birth` / `date` kind box (by name:
   birth_date, cooperation_started_at, start_date … or data-mq-rule), so pages need no code of their own. The box stays
   typeable (yyyy/mm/dd, checked by field-rules.js); a calendar button inside it (left end) opens a popup with month and
   year selects, ‹ › month arrows and a day grid (Saturday first). `birth`: years from 100 to 15 years ago only
   (field_rules.BIRTH_AGE), days outside that range disabled, opens on the typed date or 20 years ago; `date`: 1300–1500
   with «امروز». A pick writes yyyy/mm/dd (0-9 digits, what the server stores), fires input + change (dirty-form.js,
   validation) and closes; Escape / a click outside close it. The popup lives on <body> (position: fixed, flipped
   above the box when there is no room below, kept inside the screen down to 240px). Leap years: 33-year cycle, the
   same rule as field-rules.js / field_rules.py (exact for 1210–1634). Loaded before field-rules.js by base.html and
   base_standalone.html; disabled / read-only boxes get no button. */
(function () {
  var FA = '۰۱۲۳۴۵۶۷۸۹';
  var MONTHS = ['فروردین', 'اردیبهشت', 'خرداد', 'تیر', 'مرداد', 'شهریور', 'مهر', 'آبان', 'آذر', 'دی', 'بهمن', 'اسفند'];
  var WEEK = ['ش', 'ی', 'د', 'س', 'چ', 'پ', 'ج'];
  var BIRTH_AGE = [15, 100];  // field_rules.BIRTH_AGE
  function fa(n) { return String(n).replace(/\d/g, function (d) { return FA[d]; }); }
  function latin(s) {
    return String(s || '').replace(/[۰-۹]/g, function (c) { return String(FA.indexOf(c)); })
      .replace(/[٠-٩]/g, function (c) { return String(c.charCodeAt(0) - 0x660); });
  }
  function pad(n) { return (n < 10 ? '0' : '') + n; }
  function leap(y) { return [1, 5, 9, 13, 17, 22, 26, 30].indexOf(((y % 33) + 33) % 33) >= 0; }
  function monthDays(y, m) { return m <= 6 ? 31 : m <= 11 ? 30 : (leap(y) ? 30 : 29); }
  // Weekday, Saturday = 0. 1400/01/01 was a Sunday (index 1).
  function weekday(y, m, d) {
    var days = (m <= 6 ? (m - 1) * 31 : 186 + (m - 7) * 30) + d - 1, yy;
    if (y >= 1400) for (yy = 1400; yy < y; yy++) days += leap(yy) ? 366 : 365;
    else for (yy = y; yy < 1400; yy++) days -= leap(yy) ? 366 : 365;
    return (((1 + days) % 7) + 7) % 7;
  }
  var TODAY = (function () {
    try {
      var o = {};
      new Intl.DateTimeFormat('en-US-u-ca-persian', { timeZone: 'Asia/Tehran', year: 'numeric', month: 'numeric', day: 'numeric' })
        .formatToParts(new Date()).forEach(function (p) { o[p.type] = parseInt(latin(p.value), 10); });
      if (o.year > 1300) return [o.year, o.month, o.day];
    } catch (e) {}
    var g = new Date();
    return [g.getFullYear() - 621, 1, 1];
  })();
  function cmp(a, b) { return a[0] - b[0] || a[1] - b[1] || a[2] - b[2]; }
  function parse(v) {
    var m = /^(\d{4})\/(\d{1,2})\/(\d{1,2})$/.exec(latin(v).trim());
    if (!m) return null;
    var y = +m[1], mo = +m[2], d = +m[3];
    if (mo < 1 || mo > 12 || d < 1 || d > monthDays(y, mo)) return null;
    return [y, mo, d];
  }
  // Allowed range per kind: [first, last] dates (inclusive).
  function range(kind) {
    if (kind === 'birth') {
      var last = [TODAY[0] - BIRTH_AGE[0], TODAY[1], Math.min(TODAY[2], monthDays(TODAY[0] - BIRTH_AGE[0], TODAY[1]))];
      var first = [TODAY[0] - BIRTH_AGE[1], TODAY[1], Math.min(TODAY[2], monthDays(TODAY[0] - BIRTH_AGE[1], TODAY[1]))];
      // «more than 100 years» is refused, so the first allowed day is the day after exactly 100 years ago
      first = first[2] < monthDays(first[0], first[1]) ? [first[0], first[1], first[2] + 1]
        : first[1] < 12 ? [first[0], first[1] + 1, 1] : [first[0] + 1, 1, 1];
      return [first, last];
    }
    return [[1300, 1, 1], [1500, 12, monthDays(1500, 12)]];
  }

  var CAL = '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="5" width="18" height="16" rx="2"/><path d="M16 3v4M8 3v4M3 10h18"/></svg>';
  function addStyle() {
    if (document.getElementById('mq-dp-style')) return;
    var st = document.createElement('style');
    st.id = 'mq-dp-style';
    st.textContent = ''
      + '.mq-date-wrap{position:relative;display:block;width:100%;min-width:0}'
      + '.mq-date-wrap>input.mq-date-input{width:100%;padding-left:2.6rem!important}'
      + '.mq-date-wrap>.teacher-wizard-date-icon{display:none}'
      + '.mq-date-btn{position:absolute;left:.3rem;top:50%;transform:translateY(-50%);display:inline-grid;place-items:center;width:2rem;height:2rem;margin:0;padding:0;border:0;border-radius:.5rem;background:transparent;color:#64748b;cursor:pointer}'
      + '.mq-date-btn:hover,.mq-date-btn[aria-expanded="true"]{background:#eef2ff;color:#4b46ff}'
      + '.mq-date-btn:focus-visible{outline:2px solid #4b46ff;outline-offset:1px}'
      + '.mq-date-btn svg,.mq-dp-nav svg{width:1.15rem;height:1.15rem;fill:none;stroke:currentColor;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}'
      + '.mq-dp{position:fixed;z-index:1300;box-sizing:border-box;width:18.5rem;max-width:calc(100vw - 16px);padding:.7rem;border:1px solid #dbe3f0;border-radius:.9rem;background:#fff;color:#0f172a;box-shadow:0 18px 40px rgba(15,23,42,.18);direction:rtl;font-size:.85rem;line-height:1.4}'
      + '.mq-dp *{box-sizing:border-box}'
      + '.mq-dp-head{display:grid;grid-template-columns:2rem minmax(0,1fr) minmax(0,1fr) 2rem;gap:.35rem;align-items:center;margin-bottom:.5rem}'
      + '.mq-dp-head select{width:100%;min-width:0;height:2.1rem;padding:0 .4rem;border:1px solid #dbe3f0;border-radius:.55rem;background:#f8fafc;color:#0f172a;font:inherit;font-weight:600;cursor:pointer}'
      + '.mq-dp-nav{display:inline-grid;place-items:center;width:2rem;height:2rem;border:0;border-radius:.5rem;background:#f1f5f9;color:#334155;cursor:pointer}'
      + '.mq-dp-nav:hover:not(:disabled){background:#e0e7ff;color:#4b46ff}.mq-dp-nav:disabled{opacity:.35;cursor:default}'
      + '.mq-dp-week,.mq-dp-grid{display:grid;grid-template-columns:repeat(7,minmax(0,1fr));gap:.15rem;text-align:center}'
      + '.mq-dp-week span{padding:.2rem 0;color:#64748b;font-size:.75rem;font-weight:600}'
      + '.mq-dp-grid button{height:2.1rem;min-width:0;padding:0;border:0;border-radius:.5rem;background:transparent;color:#0f172a;font:inherit;cursor:pointer}'
      + '.mq-dp-grid button:hover:not(:disabled){background:#eef2ff;color:#4b46ff}'
      + '.mq-dp-grid button.is-today{box-shadow:inset 0 0 0 1px #c7d2fe}'
      + '.mq-dp-grid button.is-selected{background:#4b46ff;color:#fff;font-weight:700}'
      + '.mq-dp-grid button:disabled{color:#cbd5e1;cursor:default}'
      + '.mq-dp-grid button:focus-visible,.mq-dp-foot button:focus-visible,.mq-dp-nav:focus-visible{outline:2px solid #4b46ff;outline-offset:1px}'
      + '.mq-dp-foot{display:flex;flex-wrap:wrap;gap:.4rem;justify-content:space-between;margin-top:.55rem;padding-top:.55rem;border-top:1px solid #eef2f7}'
      + '.mq-dp-foot button{flex:1 1 auto;height:2rem;padding:0 .7rem;border:1px solid #dbe3f0;border-radius:.55rem;background:#fff;color:#334155;font:inherit;font-weight:600;cursor:pointer}'
      + '.mq-dp-foot button:hover{border-color:#4b46ff;color:#4b46ff}'
      + '@media (max-width:360px){.mq-dp{padding:.5rem}.mq-dp-grid button{height:1.9rem}.mq-dp-head{grid-template-columns:1.8rem minmax(0,1fr) minmax(0,1fr) 1.8rem;gap:.25rem}.mq-dp-nav{width:1.8rem}}';
    (document.head || document.documentElement).appendChild(st);
  }

  var open = null;  // {el, kind, btn, pop, y, m}

  function close(refocus) {
    if (!open) return;
    var o = open;
    open = null;
    o.pop.remove();
    o.btn.setAttribute('aria-expanded', 'false');
    if (refocus) o.btn.focus();
  }

  function place() {
    if (!open) return;
    var r = open.el.getBoundingClientRect(), p = open.pop, vw = document.documentElement.clientWidth, vh = window.innerHeight;
    var w = p.offsetWidth, h = p.offsetHeight;
    var left = Math.min(Math.max(8, r.left), Math.max(8, vw - w - 8));
    var top = r.bottom + 6;
    if (top + h > vh - 8 && r.top - h - 6 >= 8) top = r.top - h - 6;  // no room below: above the box
    else if (top + h > vh - 8) top = Math.max(8, vh - h - 8);
    p.style.left = left + 'px';
    p.style.top = top + 'px';
  }

  function render() {
    var o = open, lim = range(o.kind), sel = parse(o.el.value), y = o.y, m = o.m, i;
    var years = '', months = '';
    for (i = lim[1][0]; i >= lim[0][0]; i--) years += '<option value="' + i + '"' + (i === y ? ' selected' : '') + '>' + fa(i) + '</option>';
    for (i = 1; i <= 12; i++) {
      var off = cmp([y, i, monthDays(y, i)], lim[0]) < 0 || cmp([y, i, 1], lim[1]) > 0;
      months += '<option value="' + i + '"' + (i === m ? ' selected' : '') + (off ? ' disabled' : '') + '>' + MONTHS[i - 1] + '</option>';
    }
    var cells = '', first = weekday(y, m, 1), n = monthDays(y, m);
    for (i = 0; i < first; i++) cells += '<span></span>';
    for (i = 1; i <= n; i++) {
      var day = [y, m, i], out = cmp(day, lim[0]) < 0 || cmp(day, lim[1]) > 0;
      var cls = (sel && !cmp(sel, day) ? 'is-selected' : '') + (!cmp(TODAY, day) ? ' is-today' : '');
      cells += '<button type="button" data-day="' + i + '"' + (cls.trim() ? ' class="' + cls.trim() + '"' : '')
        + (out ? ' disabled' : '') + (sel && !cmp(sel, day) ? ' aria-pressed="true"' : '')
        + ' aria-label="' + fa(i) + ' ' + MONTHS[m - 1] + ' ' + fa(y) + '">' + fa(i) + '</button>';
    }
    var prevOff = cmp([y, m, 1], lim[0]) <= 0, nextOff = cmp([y, m, monthDays(y, m)], lim[1]) >= 0;
    o.pop.innerHTML = '<div class="mq-dp-head">'
      + '<button type="button" class="mq-dp-nav" data-nav="-1" aria-label="ماه قبل"' + (prevOff ? ' disabled' : '') + '><svg viewBox="0 0 24 24"><path d="m9 18 6-6-6-6"/></svg></button>'
      + '<select data-month aria-label="ماه">' + months + '</select>'
      + '<select data-year aria-label="سال">' + years + '</select>'
      + '<button type="button" class="mq-dp-nav" data-nav="1" aria-label="ماه بعد"' + (nextOff ? ' disabled' : '') + '><svg viewBox="0 0 24 24"><path d="m15 18-6-6 6-6"/></svg></button>'
      + '</div><div class="mq-dp-week">' + WEEK.map(function (w) { return '<span>' + w + '</span>'; }).join('') + '</div>'
      + '<div class="mq-dp-grid">' + cells + '</div>'
      + '<div class="mq-dp-foot">'
      + (o.kind === 'birth' ? '' : '<button type="button" data-today>امروز</button>')
      + (o.el.value ? '<button type="button" data-clear>پاک کردن</button>' : '')
      + '<button type="button" data-close>بستن</button></div>';
  }

  // Keep the shown month inside the allowed range.
  function show(y, m) {
    var lim = range(open.kind);
    if (cmp([y, m, 31], lim[0]) < 0) { y = lim[0][0]; m = lim[0][1]; }
    if (cmp([y, m, 1], lim[1]) > 0) { y = lim[1][0]; m = lim[1][1]; }
    open.y = y;
    open.m = m;
    // Re-rendering replaces the buttons: keep the keyboard focus inside the calendar (same arrow / select).
    var had = open.pop.contains(document.activeElement) ? document.activeElement : null;
    var again = had && (had.getAttribute('data-nav') ? '[data-nav="' + had.getAttribute('data-nav') + '"]'
      : had.hasAttribute('data-month') ? '[data-month]' : '[data-year]');
    render();
    place();
    if (again) {
      var f = open.pop.querySelector(again);
      if (f && f.disabled) f = open.pop.querySelector('[data-year]');
      if (f) f.focus({ preventScroll: true });
    }
  }

  function write(el, value) {
    el.value = value;
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
    if (window.mqFieldRules) window.mqFieldRules.check(el, !!value);
  }

  function openFor(el, kind, btn) {
    if (open && open.el === el) { close(true); return; }
    close(false);
    var pop = document.createElement('div');
    pop.className = 'mq-dp';
    pop.setAttribute('role', 'dialog');
    pop.setAttribute('aria-label', kind === 'birth' ? 'انتخاب تاریخ تولد' : 'انتخاب تاریخ');
    pop.setAttribute('data-no-loader', '');
    open = { el: el, kind: kind, btn: btn, pop: pop, y: 0, m: 0 };
    pop.addEventListener('mousedown', function (e) {  // keep focus where it is, except for the selects
      if (e.target.tagName !== 'SELECT' && e.target.tagName !== 'OPTION') e.preventDefault();
    });
    pop.addEventListener('click', function (e) {
      var t = e.target.closest('button');
      if (!t || !open) return;
      if (t.hasAttribute('data-nav')) {
        var mm = open.m + (+t.getAttribute('data-nav')), yy = open.y;
        if (mm < 1) { mm = 12; yy--; } else if (mm > 12) { mm = 1; yy++; }
        show(yy, mm);
      } else if (t.hasAttribute('data-day')) {
        var target = open.el;
        write(target, open.y + '/' + pad(open.m) + '/' + pad(+t.getAttribute('data-day')));
        close(true);
      } else if (t.hasAttribute('data-today')) {
        var el2 = open.el;
        write(el2, TODAY[0] + '/' + pad(TODAY[1]) + '/' + pad(TODAY[2]));
        close(true);
      } else if (t.hasAttribute('data-clear')) {
        var el3 = open.el;
        write(el3, '');
        close(true);
      } else if (t.hasAttribute('data-close')) close(true);
    });
    pop.addEventListener('change', function (e) {
      if (!open) return;
      if (e.target.hasAttribute('data-year')) show(+e.target.value, open.m);
      else if (e.target.hasAttribute('data-month')) show(open.y, +e.target.value);
    });
    pop.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); close(true); }
    });
    document.body.appendChild(pop);
    btn.setAttribute('aria-expanded', 'true');
    var sel = parse(el.value), lim = range(kind);
    var start = sel || (kind === 'birth' ? [TODAY[0] - 20, 1, 1] : TODAY);
    show(start[0], start[1]);
    var focus = pop.querySelector('.mq-dp-grid .is-selected') || pop.querySelector('[data-year]');
    if (focus && lim) focus.focus({ preventScroll: true });
  }

  function attach(el, kind) {
    if (!el || el._mqDatePicker || el.disabled || el.readOnly || el.type === 'hidden') return;
    el._mqDatePicker = true;
    addStyle();
    var wrap = el.parentElement;
    if (!wrap) return;
    if (!wrap.classList.contains('teacher-wizard-date-field')) {
      wrap = document.createElement('div');
      el.parentElement.insertBefore(wrap, el);
      wrap.appendChild(el);
    }
    wrap.classList.add('mq-date-wrap');
    el.classList.add('mq-date-input');
    var btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'mq-date-btn';
    btn.setAttribute('aria-label', kind === 'birth' ? 'انتخاب تاریخ تولد از تقویم' : 'انتخاب تاریخ از تقویم');
    btn.setAttribute('aria-haspopup', 'dialog');
    btn.setAttribute('aria-expanded', 'false');
    btn.setAttribute('data-no-loader', '');
    btn.innerHTML = CAL;
    btn.addEventListener('click', function (e) { e.preventDefault(); openFor(el, kind, btn); });
    wrap.appendChild(btn);
    el.addEventListener('keydown', function (e) {
      if (e.altKey && e.key === 'ArrowDown') { e.preventDefault(); openFor(el, kind, btn); }
      else if (e.key === 'Escape' && open && open.el === el) close(false);
    });
    el.addEventListener('input', function () {  // a typed full date moves the open calendar to it
      if (!open || open.el !== el) return;
      var d = parse(el.value);
      if (d) show(d[0], d[1]);
    });
  }

  document.addEventListener('mousedown', function (e) {
    if (open && !open.pop.contains(e.target) && !open.btn.contains(e.target)) close(false);
  }, true);
  document.addEventListener('focusin', function (e) {
    if (open && !open.pop.contains(e.target) && e.target !== open.el && e.target !== open.btn) close(false);
  });
  document.addEventListener('keydown', function (e) {  // wherever the focus is (e.g. lost to <body>)
    if (open && e.key === 'Escape') { e.preventDefault(); close(open.pop.contains(document.activeElement) || document.activeElement === document.body); }
  });
  window.addEventListener('resize', function () { place(); });
  document.addEventListener('scroll', function () { place(); }, true);
  // A live region / dialog swap that removes the box closes its calendar.
  document.addEventListener('mq:live-load', function () { if (open && !open.el.isConnected) close(false); });

  window.mqDatePicker = { attach: attach, close: function () { close(false); } };
})();
