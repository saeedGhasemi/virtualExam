/* Input rules for personal-data fields (user's requirement: a field only accepts what fits it, with an example
   placeholder). Found by name or type, so every page gets them without per-page code:
     national  کد ملی       name national_id / national_code …   10 digits + the Iranian check digit
     mobile    موبایل        name phone / mobile / phone_number …  09xxxxxxxxx (11 digits; +98 / 0098 pasted → 09…)
     landline  تلفن ثابت     name landline / telephone             0 + city code + number (10–11 digits)
     birth     تاریخ تولد    name birth_date / birthdate …         Jalali yyyy/mm/dd (slashes added while typing),
                                                                  a real day, 1300 … today
     email     ایمیل         type=email or a name ending in "email" Latin address name@domain.tld
     date      تاریخ شمسی    name cooperation_started_at / start_date / end_date   like birth, any year 1300 … 1500
     year      سال           name entry_year / entrance_year              4 digits, 1300 … next year
     name      نام           name first_name / last_name / full_name …      Persian or English letters, space, ZWNJ
     studentno ش. دانشجویی   name student_number / student_code            digits only
     code      کد پرسنلی     name personnel_code / identifier              English letters, digits, «-» (data has ADM-1024 …)
     username  نام کاربری    name username                                 English letters, digits, . _ - @
     totp      کد ۶ رقمی     name totp_code with maxlength 6 (else otp: a 6-digit or recovery code)  digits
     identity  کد ورود آزمون name identity_code (national ID or student number)  digits
     acyear    سال تحصیلی    name academic_year (data-mq-rule="acyear" elsewhere)  1405-1406 («-» added while typing)
     latin     کد لاتین      name code / course_code / station_code (course, exam join, OSCE codes)  A-Z 0-9 - _
     color     کد رنگ        name settings_primary_color / mqa_color                #RRGGBB
     ip        محدوده IP     name ip_restriction_range                             IPv4/IPv6 or CIDR, comma separated
     decimal   عدد           name numeric_answer / numeric_tolerance (text boxes)   digits, one «.», leading «-»
     clock     ساعت          data-mq-rule="clock" (text boxes such as the OSCE start time)  HH:MM
     number    عدد           every other <input type=number>: digits only (+ «.» when step allows decimals, «-» when
                             min < 0), Persian digits typed become 0-9, a Persian message for min / max / step; an
                             example placeholder from NUM_PH by name, else the allowed range.
     pwnew     رمز جدید      <input type=password autocomplete="new-password">     English letters, digits, symbols; no space /
                             Persian letters (wrong keyboard layout); the password standard PW_RULES (≥ 8 with upper +
                             lower English letter, digit, symbol = field_rules.PASSWORD_RULES); what is missing is named in
                             the message under the box (no checklist / chips: user's choice);
                             a repeat box (name …2 / confirm…) must equal the form's first new-password box
     pwcur     رمز فعلی      every other <input type=password> (sign-in, current password)   same keys, no length rule
   Kinds after «username» keep a page's own placeholder (it is already an example) and only add one when missing.
   Every kind caps the length (maxlength; a longer value already saved shows an error until shortened); free-text
   basic-info boxes (field_of_study, specialty, department …) and other text boxes of a form with personal fields get
   maxlength 150. Server-side length guard for every POST: middleware.PersonFieldLengthMiddleware (field_rules.FIELD_MAX).
   Or set data-mq-rule="<kind>" yourself; data-mq-rule="off" opts an input out. Search boxes (name q) are left alone.
   name / studentno / code / username keep the value the page was rendered with (only what is typed is filtered).
   Keys that don't fit are refused as typed (with a short hint under the field), pasted text is cleaned, Persian /
   Arabic digits become 0-9 (that is what the server stores). The example placeholder replaces a page's own unless the
   input has data-keep-placeholder. A wrong value gets a Persian message under the field after leaving it or on submit
   (setCustomValidity, so the form is not sent). Inputs added later (live regions, dialogs) get the rules through a
   MutationObserver, before the next paint. Server-side twin: apps/core/field_rules.py. Loaded by base.html,
   base_standalone.html, login.html and register.html. */
(function () {
  var FA = '۰۱۲۳۴۵۶۷۸۹', AR = '٠١٢٣٤٥٦٧٨٩';
  function latinDigits(s) {
    return String(s || '').replace(/[۰-۹٠-٩]/g, function (c) {
      var i = FA.indexOf(c);
      return String(i >= 0 ? i : AR.indexOf(c));
    });
  }
  function faDigits(s) { return String(s).replace(/\d/g, function (d) { return FA[d]; }); }

  var NAMES = {
    national: /^(national_?id|national_?code|national_?number|melli_?code|code_?melli)$/i,
    mobile: /^(phone|mobile|phone_?number|mobile_?number|cell_?phone|cellphone)$/i,
    landline: /^(landline|telephone|tel|phone_?landline)$/i,
    birth: /^(birth_?date|date_?of_?birth|birthday)$/i,
    email: /(^|_)e?mail$/i,
    date: /^(cooperation_started_at|start_date|end_date|hire_date|employment_date)$/i,
    year: /^(entry_year|entrance_year|admission_year)$/i,
    name: /^(first_name|last_name|full_name|father_name|display_name)$/i,
    studentno: /^(student_number|student_code|student_id_number)$/i,
    code: /^(personnel_code|employee_code|identifier)$/i,
    username: /^username$/i,
    identity: /^identity_code$/i,
    acyear: /^academic_year$/i,
    latin: /^(code|course_code|station_code|join_code)$/i,
    color: /^(settings_primary_color|mqa_color)$/i,
    ip: /^ip_restriction_range$/i,
    decimal: /^(numeric_answer|numeric_tolerance)$/i
  };
  var TEXT_TYPES = { '': 1, text: 1, tel: 1, email: 1, search: 1 };

  // allow: one typed character; max: length; mode: keyboard; ph: example placeholder.
  var RULES = {
    national: { allow: /\d/, max: 10, mode: 'numeric', ph: '۰۰۱۲۳۴۵۶۷۸ (۱۰ رقم)', hint: 'فقط رقم وارد کنید.' },
    mobile: { allow: /\d/, max: 11, mode: 'tel', ph: '۰۹۱۲۳۴۵۶۷۸۹', hint: 'فقط رقم وارد کنید.', auto: 'tel' },
    landline: { allow: /\d/, max: 11, mode: 'tel', ph: '۰۲۱۸۸۷۷۶۶۵۵ (با کد شهر)', hint: 'فقط رقم وارد کنید.' },
    birth: { allow: /[\d\/]/, max: 10, mode: 'numeric', ph: '۱۳۷۸/۰۶/۲۱ (سال/ماه/روز)', hint: 'فقط رقم وارد کنید؛ «/» خودکار گذاشته می‌شود.' },
    email: { allow: /[A-Za-z0-9.@_%+\-]/, max: 254, mode: 'email', ph: 'name@example.com', hint: 'ایمیل فقط با حروف انگلیسی، رقم و . _ - @ نوشته می‌شود.', auto: 'email' },
    date: { allow: /[\d\/]/, max: 10, mode: 'numeric', ph: '۱۴۰۵/۰۱/۱۵ (سال/ماه/روز)', hint: 'فقط رقم وارد کنید؛ «/» خودکار گذاشته می‌شود.' },
    year: { allow: /\d/, max: 4, mode: 'numeric', ph: '۱۴۰۳', hint: 'فقط رقم وارد کنید (سال شمسی).' },
    name: { allow: /[A-Za-z\u0621-\u063A\u0641-\u0655\u067E\u0686\u0698\u06A9\u06AF\u06CC\u0622\u200C .'\-]/, max: 80, mode: 'text', rtl: true, raw: true,
      ph: { first_name: 'علی', last_name: 'محمدی', full_name: 'علی محمدی', father_name: 'حسن', display_name: 'دکتر محمدی', '': 'علی محمدی' },
      hint: 'فقط حروف وارد کنید؛ رقم و نماد مجاز نیست.' },
    studentno: { allow: /\d/, max: 20, mode: 'numeric', raw: true, ph: '۴۰۳۱۲۳۴۵۶', hint: 'فقط رقم وارد کنید.' },
    code: { allow: /[A-Za-z0-9\-]/, max: 30, mode: 'text', raw: true, ph: '۱۴۰۵۱۱۲',
      hint: 'فقط رقم، حروف انگلیسی و «-» مجاز است.' },
    username: { allow: /[A-Za-z0-9._@+\-]/, max: 150, mode: 'text', raw: true, ph: 'ali.mohammadi', hint: 'نام کاربری فقط با حروف انگلیسی، رقم و . _ - نوشته می‌شود.', auto: 'username' },
    totp: { allow: /\d/, max: 6, mode: 'numeric', ph: '۱۲۳۴۵۶', hint: 'فقط رقم وارد کنید (کد ۶ رقمی برنامه).', keepPh: true, auto: 'one-time-code' },
    otp: { allow: /[A-Za-z0-9\-]/, max: 12, mode: 'text', raw: true, ph: '۱۲۳۴۵۶', hint: 'کد ۶ رقمی برنامه یا کد بازیابی (حروف انگلیسی و رقم).', keepPh: true, auto: 'one-time-code' },
    identity: { allow: /\d/, max: 20, mode: 'numeric', ph: '۰۰۱۲۳۴۵۶۷۸', hint: 'فقط رقم وارد کنید (کد ملی یا شماره دانشجویی).', keepPh: true },
    acyear: { allow: /[\d\-]/, max: 9, mode: 'numeric', ph: '۱۴۰۵-۱۴۰۶', hint: 'فقط رقم وارد کنید؛ «-» خودکار گذاشته می‌شود.', keepPh: true },
    latin: { allow: /[A-Za-z0-9_\-]/, max: 30, mode: 'text', raw: true, ph: 'PED-101', hint: 'فقط حروف انگلیسی، رقم و «-» مجاز است.', keepPh: true },
    color: { allow: /[#0-9A-Fa-f]/, max: 7, mode: 'text', raw: true, ph: '#2563EB', hint: 'کد رنگ فقط # و رقم و حروف A تا F است.', keepPh: true },
    ip: { allow: /[0-9A-Fa-f.:\/, ]/, max: 500, mode: 'text', raw: true, ph: '192.168.1.0/24', hint: 'فقط رقم، «.»، «/» و «,» مجاز است.', keepPh: true },
    decimal: { allow: /[\d.\-]/, max: 20, mode: 'decimal', raw: true, ph: '۲.۵', hint: 'فقط عدد وارد کنید.', keepPh: true },
    clock: { allow: /[\d:]/, max: 5, mode: 'numeric', ph: '۰۹:۰۰', hint: 'فقط رقم وارد کنید؛ «:» خودکار گذاشته می‌شود.', keepPh: true },
    number: { allow: /\d/, max: 20, mode: 'numeric', raw: true, ph: '', hint: 'فقط عدد وارد کنید.', keepPh: true },
    pwnew: { allow: /[!-~]/, max: 128, mode: 'text', raw: true, ph: 'Sara#1403', keepPh: true, auto: 'new-password',
      hint: 'رمز عبور فقط با حروف انگلیسی، رقم و نمادها نوشته می‌شود (بدون فاصله)؛ زبان صفحه‌کلید را انگلیسی کنید.' },
    pwcur: { allow: /[!-~]/, max: 128, mode: 'text', raw: true, ph: '••••••••', keepPh: true, auto: 'current-password',
      hint: 'رمز عبور فقط با حروف انگلیسی، رقم و نمادها نوشته می‌شود (بدون فاصله)؛ زبان صفحه‌کلید را انگلیسی کنید.' }
  };
  // The password standard, same order as field_rules.PASSWORD_RULES (server twin).
  var PW_RULES = [
    ['۸ نویسه یا بیشتر', function (v) { return v.length >= 8; }],
    ['حرف بزرگ انگلیسی (A-Z)', function (v) { return /[A-Z]/.test(v); }],
    ['حرف کوچک انگلیسی (a-z)', function (v) { return /[a-z]/.test(v); }],
    ['رقم', function (v) { return /[0-9]/.test(v); }],
    ['نماد مثل ! @ # $', function (v) { return /[!-\/:-@\[-`{-~]/.test(v); }]
  ];
  function pwMissing(v) {
    var out = [];
    for (var i = 0; i < PW_RULES.length; i++) if (!PW_RULES[i][1](v)) out.push(PW_RULES[i][0]);
    return out;
  }
  // The first new-password box of a repeat box's form («تکرار رمز عبور» must equal it).
  function pwRepeat(el) { return /(2|_?confirm(ation)?|_?repeat|_?again)$/i.test(el.name || ''); }
  function pwPartner(el) {
    var f = el.form;
    if (!f) return null;
    for (var i = 0; i < f.elements.length; i++) {
      var o = f.elements[i];
      if (o !== el && o._mqRule === 'pwnew' && !pwRepeat(o)) return o;
    }
    return null;
  }
  // Example placeholders for number boxes, by name (else the allowed range «۰ تا ۲۰»).
  var NUM_PH = {
    duration_minutes: '۹۰', study_minutes: '۲', transition_minutes: '۱', max_attempts: '۱', passing_score: '۱۰',
    pass_score: '۱۲', exam_pass_score: '۱۰', capacity: '۳۰', min_students: '۱۰', waitlist_capacity: '۵',
    credit_units: '۳', negative_factor: '۰.۲۵', negative_mark: '۰.۲۵', groups_count: '۴', students_per_group: '۸',
    default_points: '۱', keep: '۷', hotspot_max_clicks: '۱', media_max_record_seconds: '۱۲۰', min_correct: '۱',
    max_correct: '۳', short_answer_max_chars: '۲۰۰', correct_threshold: '۸۰', passing_score_total: '۱۰۰',
    min_passing_percent: '۶۰', media_rubric_points: '۲'
  };
  // A number box: decimals allowed when its step is not a whole number, a minus when min < 0.
  function numSpec(el) {
    var step = (el.getAttribute('step') || '').trim(), min = parseFloat(el.getAttribute('min'));
    var dec = step === 'any' || (step !== '' && !/^\d+$/.test(step));
    return { dec: dec, neg: !(min >= 0), min: min, max: parseFloat(el.getAttribute('max')), step: step };
  }
  function numAllows(el, c) {
    if (/\d/.test(c)) return true;
    var sp = numSpec(el);
    return (c === '.' && sp.dec) || (c === '-' && sp.neg);
  }
  function fmtNum(n) { return faDigits(String(n)); }
  function isDate(kind) { return kind === 'birth' || kind === 'date'; }
  function placeholderOf(kind, el) {
    if (kind === 'number') {
      var sp = numSpec(el), named = NUM_PH[(el.name || '').toLowerCase()];
      if (named !== undefined) return named;
      if (!isNaN(sp.min) && !isNaN(sp.max)) return fmtNum(sp.min) + ' تا ' + fmtNum(sp.max);
      if (!isNaN(sp.min)) return fmtNum(Math.max(sp.min, 1));
      return '۱';
    }
    var ph = RULES[kind].ph;
    return typeof ph === 'string' ? ph : (ph[(el.name || '').toLowerCase()] || ph['']);
  }

  function ruleOf(el) {
    if (!el || el.tagName !== 'INPUT') return null;
    var set = el.getAttribute('data-mq-rule');
    if (set) return RULES[set] ? set : null;
    var type = (el.getAttribute('type') || '').toLowerCase(), name = el.name || '';
    if (type === 'password') return (el.getAttribute('autocomplete') || '') === 'new-password' ? 'pwnew' : 'pwcur';
    if (type === 'number') return NAMES.year.test(name) ? 'year' : NAMES.studentno.test(name) ? 'studentno' : 'number';
    if (!TEXT_TYPES[type]) return null;
    if (/^totp_code$/i.test(name)) return el.getAttribute('maxlength') === '6' ? 'totp' : 'otp';
    if (type === 'email' || NAMES.email.test(name)) return 'email';
    for (var k in NAMES) if (k !== 'email' && NAMES[k].test(name)) return k;
    if (type === 'tel') return 'mobile';
    return null;
  }

  // ----- validation ---------------------------------------------------------------------------------------------
  function nationalOk(v) {
    if (!/^\d{10}$/.test(v) || /^(\d)\1{9}$/.test(v)) return false;
    var sum = 0;
    for (var i = 0; i < 9; i++) sum += +v[i] * (10 - i);
    var r = sum % 11, c = +v[9];
    return r < 2 ? c === r : c === 11 - r;
  }
  function jalaliLeap(y) { return [1, 5, 9, 13, 17, 22, 26, 30].indexOf(y % 33) >= 0; }  // exact for 1210–1634
  var today = (function () {
    try {
      var parts = new Intl.DateTimeFormat('en-US-u-ca-persian', { year: 'numeric', month: 'numeric', day: 'numeric' }).formatToParts(new Date());
      var o = {};
      parts.forEach(function (p) { o[p.type] = parseInt(latinDigits(p.value), 10); });
      if (o.year > 1300) return [o.year, o.month, o.day];
    } catch (e) {}
    var d = new Date();
    return [d.getFullYear() - 621, 12, 29];
  })();
  function birthError(v, anyYear) {
    var m = /^(\d{4})\/(\d{1,2})\/(\d{1,2})$/.exec(v);
    if (!m) return 'تاریخ را به شکل سال/ماه/روز شمسی بنویسید، مثلاً ' + (anyYear ? '۱۴۰۵/۰۱/۱۵.' : '۱۳۷۸/۰۶/۲۱.');
    var y = +m[1], mo = +m[2], d = +m[3];
    if (mo < 1 || mo > 12) return 'ماه باید بین ۱ تا ۱۲ باشد.';
    var days = mo <= 6 ? 31 : mo <= 11 ? 30 : (jalaliLeap(y) ? 30 : 29);
    if (d < 1 || d > days) return 'این ماه ' + faDigits(days) + ' روز دارد.';
    if (anyYear) return y < 1300 || y > 1500 ? 'سال باید بین ۱۳۰۰ و ۱۵۰۰ باشد.' : '';
    if (y < 1300) return 'سال تولد باید از ۱۳۰۰ به بعد باشد.';
    var after = y > today[0] || (y === today[0] && (mo > today[1] || (mo === today[1] && d > today[2])));
    if (after) return 'تاریخ تولد نمی‌تواند بعد از امروز باشد.';
    return '';
  }
  function numberError(el, v) {
    var sp = numSpec(el), n = parseFloat(v), base = isNaN(sp.min) ? 0 : sp.min;
    if (el.validity && el.validity.badInput) return 'فقط عدد وارد کنید.';
    if (v === '' || isNaN(n)) return '';
    if (!isNaN(sp.min) && n < sp.min) return 'کمترین مقدار ' + fmtNum(sp.min) + ' است.';
    if (!isNaN(sp.max) && n > sp.max) return 'بیشترین مقدار ' + fmtNum(sp.max) + ' است.';
    if (!sp.dec && Math.floor(n) !== n) return 'عدد باید صحیح باشد (بدون اعشار).';
    if (el.validity && el.validity.stepMismatch) return 'این عدد با گام ' + fmtNum(sp.step) + ' جور نیست؛ مثلاً ' + fmtNum(base) + ' یا ' + fmtNum(base + parseFloat(sp.step)) + '.';
    return '';
  }
  function ipError(v) {
    var parts = v.split(/[\s,،]+/).filter(Boolean);
    for (var i = 0; i < parts.length; i++) {
      var p = parts[i];
      if (p.indexOf(':') >= 0) { if (!/^[0-9A-Fa-f:]+(\/\d{1,3})?$/.test(p)) return 'نشانی IPv6 «' + p + '» معتبر نیست.'; continue; }
      var m = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})(\/(\d{1,2}))?$/.exec(p);
      if (!m || +m[1] > 255 || +m[2] > 255 || +m[3] > 255 || +m[4] > 255 || (m[6] && +m[6] > 32)) return '«' + p + '» نشانی IP معتبر نیست؛ مثلاً 192.168.1.0/24.';
    }
    return '';
  }
  function errorOf(kind, v, el) {
    if (kind === 'number') return numberError(el, v);
    if (!v) return '';
    // A value already saved longer than the field allows (typing stops at maxlength; this catches old data).
    if (kind !== 'mobile' && v.length > RULES[kind].max) return 'حداکثر ' + faDigits(RULES[kind].max) + ' نویسه مجاز است؛ مقدار را کوتاه کنید.';
    if (kind === 'national') return nationalOk(v) ? '' : (v.length !== 10 ? 'کد ملی باید ۱۰ رقم باشد.' : 'این کد ملی معتبر نیست؛ رقم‌ها را دوباره بررسی کنید.');
    if (kind === 'mobile') return /^09\d{9}$/.test(v) ? '' : 'شماره موبایل باید ۱۱ رقم و با ۰۹ شروع شود، مثلاً ۰۹۱۲۳۴۵۶۷۸۹.';
    if (kind === 'landline') return /^0\d{9,10}$/.test(v) ? '' : 'تلفن ثابت را با کد شهر و با ۰ شروع کنید، مثلاً ۰۲۱۸۸۷۷۶۶۵۵.';
    if (kind === 'birth') return birthError(v);
    if (kind === 'date') return birthError(v, true);
    if (kind === 'year') return /^\d{4}$/.test(v) && +v >= 1300 && +v <= today[0] + 1 ? '' : 'سال را ۴ رقمی و شمسی بنویسید، مثلاً ۱۴۰۳.';
    if (kind === 'name') return /[A-Za-z\u0621-\u06CC]/.test(v) ? '' : 'نام باید حروف داشته باشد، مثلاً علی.';
    if (kind === 'username') return v.length >= 3 ? '' : 'نام کاربری دست‌کم ۳ نویسه است، مثلاً ali.mohammadi.';
    if (kind === 'pwnew') {
      if (/[^!-~]/.test(v)) return 'رمز عبور فقط حروف انگلیسی، رقم و نماد دارد؛ فاصله و حروف فارسی مجاز نیست.';
      if (el && pwRepeat(el)) {
        var first = pwPartner(el);
        return first && first.value !== el.value ? 'تکرار رمز عبور با رمز جدید یکی نیست.' : '';
      }
      var missing = pwMissing(v);
      return missing.length ? 'رمز عبور هنوز این موارد را کم دارد: ' + missing.join('، ') + '.' : '';
    }
    if (kind === 'pwcur') return /[^!-~]/.test(v) ? 'رمز عبور فقط حروف انگلیسی، رقم و نماد دارد؛ زبان صفحه‌کلید را انگلیسی کنید.' : '';
    if (kind === 'totp') return /^\d{6}$/.test(v) ? '' : 'کد ۶ رقم است، مثلاً ۱۲۳۴۵۶.';
    if (kind === 'otp') return /^\d{6}$/.test(v) || v.length >= 8 ? '' : 'کد ۶ رقمی برنامه یا کد بازیابی را کامل وارد کنید.';
    if (kind === 'identity') return v.length >= 5 ? '' : 'کد ملی (۱۰ رقم) یا شماره دانشجویی را کامل وارد کنید.';
    if (kind === 'acyear') {
      var ay = /^(\d{4})-(\d{4})$/.exec(v);
      return ay && +ay[2] === +ay[1] + 1 && +ay[1] >= 1300 && +ay[1] <= 1500 ? '' : 'سال تحصیلی را به شکل دو سال پشت سر هم بنویسید، مثلاً ۱۴۰۵-۱۴۰۶.';
    }
    if (kind === 'color') return /^#?[0-9A-Fa-f]{6}$/.test(v) ? '' : 'کد رنگ ۶ نویسه‌ای است، مثلاً #2563EB.';
    if (kind === 'ip') return ipError(v);
    if (kind === 'decimal') return /^-?\d+(\.\d+)?$/.test(v) ? '' : 'یک عدد بنویسید، مثلاً ۲.۵ یا ۱۲۰.';
    if (kind === 'clock') {
      var cm = /^(\d{1,2}):(\d{2})$/.exec(v);
      return cm && +cm[1] < 24 && +cm[2] < 60 ? '' : 'ساعت را به شکل ساعت:دقیقه بنویسید، مثلاً ۰۹:۰۰.';
    }
    if (kind === 'email') return /^[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}$/.test(v) && !/\.\./.test(v) ? '' : 'ایمیل معتبر نیست؛ مثلاً name@example.com.';
    return '';
  }

  // ----- cleaning -----------------------------------------------------------------------------------------------
  function formatBirth(s) {
    var seg = ['', '', ''], lim = [4, 2, 2], i = 0;
    for (var k = 0; k < s.length; k++) {
      var c = s[k];
      if (c === '/') { if (seg[i] && i < 2) i++; continue; }
      if (seg[i].length >= lim[i]) { if (i === 2) break; i++; }
      // A month can't start with 2-9 nor a day with 4-9: that digit is the whole part (6 → 06).
      if (!seg[i] && ((i === 1 && c > '1') || (i === 2 && c > '3'))) c = '0' + c;
      seg[i] += c;
    }
    return seg[0] + (i >= 1 ? '/' + seg[1] : '') + (i >= 2 ? '/' + seg[2] : '');
  }
  function clean(kind, raw) {
    var rule = RULES[kind], s = latinDigits(raw);
    if (kind === 'mobile') s = s.replace(/^\s*(\+|00)98/, '0');
    var out = '';
    for (var k = 0; k < s.length; k++) if (rule.allow.test(s[k])) out += s[k];
    if (isDate(kind)) return formatBirth(out);
    if (kind === 'acyear') { out = out.replace(/-/g, ''); return out.length > 4 ? out.slice(0, 4) + '-' + out.slice(4, 8) : out; }
    if (kind === 'clock') {  // like dates: 9 → 09, «:» typed after one digit ends the hour, minutes 6-9 → 06
      var hm = ['', ''], h = 0;
      for (var t = 0; t < out.length; t++) {
        var ch = out[t];
        if (ch === ':') { if (hm[0] && !h) { if (hm[0].length === 1) hm[0] = '0' + hm[0]; h = 1; } continue; }
        if (hm[h].length >= 2) { if (h) break; h = 1; }
        if (!hm[h] && ((!h && ch > '2') || (h && ch > '5'))) ch = '0' + ch;
        hm[h] += ch;
      }
      return hm[0] + (h ? ':' + hm[1] : '');
    }
    if (kind === 'decimal') {  // one leading «-», one «.»
      var neg = out[0] === '-', body = out.replace(/-/g, ''), dot = body.indexOf('.');
      if (dot >= 0) body = body.slice(0, dot + 1) + body.slice(dot + 1).replace(/\./g, '');
      out = (neg ? '-' : '') + body;
    }
    if (kind === 'color') out = (out.indexOf('#') >= 0 ? '#' : '') + out.replace(/#/g, '');
    if (kind === 'name') out = out.replace(/ {2,}/g, ' ');
    if (kind === 'mobile' && /^98\d/.test(out)) out = '0' + out.slice(2);  // country code typed (+ is refused)
    if (kind === 'mobile' && /^9\d{9}$/.test(out)) out = '0' + out;
    return out.slice(0, rule.max);
  }
  // Characters that count for the caret: what survives cleaning, minus the slashes birth dates get automatically.
  function weight(kind, s) {
    var rule = RULES[kind], n = 0;
    s = latinDigits(s);
    for (var k = 0; k < s.length; k++) if (rule.allow.test(s[k]) && !(isDate(kind) && s[k] === '/') && !(kind === 'acyear' && s[k] === '-') && !(kind === 'clock' && s[k] === ':')) n++;
    return n;
  }

  // ----- messages -----------------------------------------------------------------------------------------------
  function addStyle() {
    if (document.getElementById('mq-rule-style')) return;
    var st = document.createElement('style');
    st.id = 'mq-rule-style';
    // Typed values are LTR codes; the Persian example placeholder reads right to left.
    st.textContent = 'input.mq-rule:not(.mq-rule-rtl):not(.mq-rule-num){direction:ltr;text-align:left}'
      + 'input.mq-rule:not(.mq-rule-num):placeholder-shown{direction:rtl;text-align:right}'
      // Sign-in / sign-up fields keep their own right alignment (user's choice), typed text still LTR.
      + '.auth-field input.mq-rule.mq-rule{text-align:right}'
      + 'input.mq-rule.mq-rule-bad{border-color:#e11d48!important;box-shadow:0 0 0 3px rgba(225,29,72,.16)!important}'
      // A message is a small solid note, readable on light pages and on the dark sign-in card alike.
      + '.mq-rule-msg.mq-rule-msg{display:flex;align-items:flex-start;gap:.45rem;box-sizing:border-box;flex-basis:100%;width:100%;max-width:100%;margin:.4rem 0 0;padding:.4rem .65rem;border:1px solid #fecdd3;border-radius:.65rem;background:#fff1f2;color:#9f1239;font-size:.8rem;font-weight:600;line-height:1.65;text-align:right;direction:rtl;white-space:normal;overflow-wrap:anywhere;box-shadow:0 1px 2px rgba(15,23,42,.06)}'
      + '.mq-rule-msg.mq-rule-msg::before{content:"!";flex:none;display:inline-grid;place-items:center;width:1.15rem;height:1.15rem;margin-top:.12rem;border-radius:50%;background:#e11d48;color:#fff;font-size:.72rem;font-weight:700;line-height:1}'
      + '.mq-rule-msg.mq-rule-msg.is-hint{border-color:#fde68a;background:#fffbeb;color:#92400e}'
      + '.mq-rule-msg.mq-rule-msg.is-hint::before{content:"i";background:#d97706}'
      + '.mq-rule-msg.mq-rule-msg[hidden]{display:none!important}';
    (document.head || document.documentElement).appendChild(st);
  }
  // The message goes after the field's own box: the label holding it, else a small wrapper (icon + input) around it.
  function msgHost(el) {
    var label = el.closest('label');
    if (label) return { parent: label, before: null };
    var p = el.parentElement, box = p && p !== el.form && p.children.length <= 3 && !/^(FORM|FIELDSET|TD|BODY)$/.test(p.tagName) ? p : null;
    return box ? { parent: box.parentElement, before: box.nextSibling } : { parent: p, before: el.nextSibling };
  }
  function msgEl(el, create) {
    var m = el._mqRuleMsg;
    if (m && m.isConnected) return m;
    if (!create) return null;
    var host = msgHost(el);
    if (!host.parent) return null;
    m = document.createElement('small');
    m.className = 'mq-rule-msg';
    m.setAttribute('aria-live', 'polite');
    m.id = 'mq-rule-msg-' + Math.random().toString(36).slice(2, 9);
    host.parent.insertBefore(m, host.before);
    el._mqRuleMsg = m;
    el.setAttribute('aria-describedby', ((el.getAttribute('aria-describedby') || '') + ' ' + m.id).trim());
    return m;
  }
  function show(el, text, hint) {
    var m = msgEl(el, !!text);
    if (m) {
      m.textContent = text || '';
      m.hidden = !text;
      m.classList.toggle('is-hint', !!hint);
    }
  }
  function check(el, reveal) {
    var kind = el._mqRule;
    if (!kind) return true;
    var value = kind === 'pwnew' || kind === 'pwcur' ? el.value : el.value.trim();
    var err = errorOf(kind, value, el);
    el.setCustomValidity(err);
    if (reveal) el._mqTouched = true;
    var visible = !!(el._mqTouched && err);  // a real boolean: toggle(…, undefined) would flip the class
    el.classList.toggle('mq-rule-bad', visible);
    if (visible) el.setAttribute('aria-invalid', 'true'); else el.removeAttribute('aria-invalid');
    if (el._mqTouched) show(el, err, false);
    return !err;
  }

  // ----- set-up ---------------------------------------------------------------------------------------------------
  // Free-text basic-info fields (and any other text box of a form with personal fields) get a length cap only.
  // Same caps as the server's field_rules.FIELD_MAX, which refuses longer values whatever page sends them.
  var TEXT_MAX = /^(field_of_study|specialty|academic_rank|degree|semester|class_group|responsibility_area|department|office|job_title)$/i;
  function personForm(f) {
    if (!f) return false;
    if (f._mqPerson === undefined) {
      f._mqPerson = false;
      for (var i = 0; i < f.elements.length; i++) if (ruleOf(f.elements[i])) { f._mqPerson = true; break; }
    }
    return f._mqPerson;
  }
  function capText(el) {
    var type = (el.getAttribute('type') || '').toLowerCase();
    if (!TEXT_TYPES[type] || type === 'search' || el.name === 'q' || el.hasAttribute('maxlength')) return;
    if (TEXT_MAX.test(el.name || '') || personForm(el.form)) el.setAttribute('maxlength', '150');
  }

  function setup(el) {
    if (el._mqRule !== undefined) return;
    var kind = ruleOf(el);
    el._mqRule = kind;
    if (!kind) { if (el.tagName === 'INPUT') capText(el); return; }
    var rule = RULES[kind];
    el.classList.add('mq-rule');
    if (kind === 'number') el.classList.add('mq-rule-num');  // keeps the page's own alignment (scores, points …)
    else if (rule.rtl) el.classList.add('mq-rule-rtl'); else el.setAttribute('dir', 'ltr');
    el.setAttribute('inputmode', kind === 'number' && numSpec(el).dec ? 'decimal' : rule.mode);
    var ownMax = +el.getAttribute('maxlength') || 0;  // a page's own, tighter cap stays (e.g. a 6-digit code)
    if (el.type !== 'number' && !(rule.keepPh && ownMax && ownMax < rule.max))
      el.setAttribute('maxlength', String(kind === 'mobile' ? 14 : rule.max)); // room for a pasted +98 / spaces, cleaned at once
    el.setAttribute('autocapitalize', 'off');
    el.setAttribute('spellcheck', 'false');
    if (rule.auto && !el.hasAttribute('autocomplete')) el.setAttribute('autocomplete', rule.auto);
    var ph = placeholderOf(kind, el);
    var own = el.getAttribute('placeholder');
    if (!el.hasAttribute('data-keep-placeholder') && !(rule.keepPh && own && own.trim()) && ph) el.setAttribute('placeholder', ph);
    ph = el.getAttribute('placeholder') || ph;
    if (!el.hasAttribute('title') && ph) el.setAttribute('title', 'نمونه: ' + ph);
    if (!rule.raw) {
      var v = clean(kind, el.value);
      if (v !== el.value) el.value = v;
    }
    if (el.value) check(el, false);
  }
  function scan(root) {
    if (!root || !root.querySelectorAll) return;
    if (root.tagName === 'INPUT') { setup(root); return; }
    var list = root.querySelectorAll('input');
    for (var i = 0; i < list.length; i++) setup(list[i]);
  }
  function target(e) {
    var el = e.target;
    if (!el || el.tagName !== 'INPUT') return null;
    if (el._mqRule === undefined) setup(el);
    return el._mqRule ? el : null;
  }

  document.addEventListener('beforeinput', function (e) {
    var el = target(e);
    if (!el || !e.data || !/^insert(Text|CompositionText|FromPaste|FromDrop|ReplacementText)?$/.test(e.inputType)) return;
    if (e.inputType === 'insertFromPaste' || e.inputType === 'insertFromDrop') return; // cleaned on input
    var rule = RULES[el._mqRule], s = latinDigits(e.data), ok = false, k;
    if (el._mqRule === 'number') {
      var only = '';
      for (k = 0; k < s.length; k++) if (numAllows(el, s[k])) only += s[k];
      if (only && s === e.data) return;
      if (only) {  // a number box can't hold Persian digits: put in their 0-9 twins instead
        e.preventDefault();
        if (!(document.execCommand && document.execCommand('insertText', false, only))) el.value = (el.value || '') + only;
        return;
      }
    } else {
      for (k = 0; k < s.length; k++) if (rule.allow.test(s[k])) { ok = true; break; }
      if (ok) return;
    }
    e.preventDefault();
    if (el._mqTouched && el.validationMessage) return;  // an error is already shown there
    show(el, rule.hint, true);
    clearTimeout(el._mqHintTimer);  // one timer per field, so a hint never outlives its field's next one
    el._mqHintTimer = setTimeout(function () { if (!(el._mqTouched && el.validationMessage)) show(el, '', false); }, 2200);
  }, true);

  document.addEventListener('input', function (e) {
    var el = target(e);
    if (!el) return;
    var kind = el._mqRule;
    if (kind === 'number') { check(el, false); return; }  // the browser keeps a number box's value numeric
    var before = el.value, caret = el.selectionStart;
    var cleaned = clean(kind, before);
    if (cleaned !== before) {
      var pos = 0, n = 0, want = caret == null || caret >= before.length ? -1 : weight(kind, before.slice(0, caret));
      if (want < 0) pos = cleaned.length;  // typing at the end stays at the end (also after an added 0)
      else while (pos < cleaned.length && n < want) { if (!(isDate(kind) && cleaned[pos] === '/')) n++; pos++; }
      el.value = cleaned;
      try { if (document.activeElement === el) el.setSelectionRange(pos, pos); } catch (err) {}
    }
    check(el, false);
    if (kind === 'pwnew' && !pwRepeat(el) && el.form) {
      for (var r = 0; r < el.form.elements.length; r++) {
        var o = el.form.elements[r];
        if (o !== el && o._mqRule === 'pwnew' && pwRepeat(o) && o.value) check(o, false);
      }
    }
  }, true);

  document.addEventListener('focusout', function (e) {
    var el = target(e);
    if (!el) return;
    if (el._mqRule === 'pwnew' || el._mqRule === 'pwcur') {
      clearTimeout(el._mqHintTimer);
      if (check(el, !!el.value) || !el._mqTouched) show(el, '', false);
      return;
    }
    var v = el.value.trim();
    if (isDate(el._mqRule)) {  // 1378/6/2 → 1378/06/02
      var m = /^(\d{4})\/(\d{1,2})\/(\d{1,2})$/.exec(v);
      if (m) v = m[1] + '/' + ('0' + m[2]).slice(-2) + '/' + ('0' + m[3]).slice(-2);
    }
    if (el._mqRule === 'email') v = v.replace(/\.+$/, '');
    if (el._mqRule === 'name') v = v.replace(/\s+/g, ' ');
    if (el._mqRule === 'clock' && /^\d:\d\d$/.test(v)) v = '0' + v;
    if (el._mqRule === 'decimal') v = v.replace(/\.$/, '');
    if (v !== el.value) el.value = v;
    clearTimeout(el._mqHintTimer);
    if (check(el, !!v) || !el._mqTouched) show(el, '', false);  // a typing hint ends when the field is left
  }, true);

  // On submit the browser fires "invalid" for each failing field: show our message there.
  document.addEventListener('invalid', function (e) {
    var el = target(e);
    if (el) check(el, true);
  }, true);

  function init() {
    addStyle();
    scan(document.body);
    if (window.MutationObserver) {
      new MutationObserver(function (records) {
        for (var i = 0; i < records.length; i++) {
          var added = records[i].addedNodes;
          for (var j = 0; j < added.length; j++) if (added[j].nodeType === 1) scan(added[j]);
        }
      }).observe(document.body, { childList: true, subtree: true });
    }
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
  // Change a field's kind later (register: student number ↔ personnel code with the role picker).
  function setRule(el, kind) {
    if (!el || !RULES[kind]) return;
    el.setAttribute('data-mq-rule', kind);
    el.removeAttribute('maxlength');
    el._mqRule = undefined;
    setup(el);
    el.value = clean(kind, el.value);
    check(el, !!el.value);
  }
  window.mqFieldRules = { scan: scan, check: check, nationalOk: nationalOk, setRule: setRule };
})();
