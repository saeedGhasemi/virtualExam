/* Input rules for personal-data fields (user's requirement: a field only accepts what fits it, with an example
   placeholder). Found by name or type, so every page gets them without per-page code:
     national  کد ملی       name national_id / national_code …   10 digits + the Iranian check digit
     mobile    موبایل        name phone / mobile / phone_number …  09[0-4 or 9]xxxxxxxx (11 digits; +98 / 0098 pasted → 09…)
     landline  تلفن ثابت     name landline / telephone             0 + province code 1–8 + 9 digits (11 digits)
     birth     تاریخ تولد    name birth_date / birthdate …         Jalali yyyy/mm/dd (slashes added while typing), a real
                                                                  day, age 15 … 100; calendar button (date-field-picker.js)
     email     ایمیل         type=email or a name ending in "email" name@domain.tld, ≤ 100, part before @ ≤ 64, no ..
     date      تاریخ شمسی    name cooperation_started_at / start_date / end_date   like birth, any year 1300 … 1500
     year      سال           name entry_year / entrance_year              4 digits, 1300 … next year
     name      نام           name first_name / last_name / full_name …      Persian or English letters (not both), space,
                             ZWNJ; ≥ 2 letters, each word ≤ 20, no letter 3× in a row; caps NAME_MAX (first 30, last 40)
     studentno ش. دانشجویی   name student_number / student_code            4–15 digits
     code      کد پرسنلی     name personnel_code / identifier              3–20 English letters / digits, «-» between
     username  نام کاربری    name username                                 3–30: English letter first, then letters,
                                                                         digits, . _ - (not doubled / last); or an e-mail
     totp      کد ۶ رقمی     name totp_code with maxlength 6 (else otp: a 6-digit or recovery code)  digits
     identity  کد ورود آزمون name identity_code (national ID or student number)  digits
     acyear    سال تحصیلی    name academic_year (data-mq-rule="acyear" elsewhere)  1405-1406 («-» added while typing)
     latin     کد لاتین      name code / course_code / station_code / group_code (course, unit, group, exam join, OSCE codes)  A-Z 0-9 - _, ≤ 20
     color     کد رنگ        name settings_primary_color / mqa_color                #RRGGBB
     ip        محدوده IP     name ip_restriction_range, settings_ip_allow_list/_block_list  IPv4/IPv6 or CIDR, comma separated
     decimal   عدد           name numeric_answer / numeric_tolerance (text boxes)   digits, one «.», leading «-»
     clock     ساعت          data-mq-rule="clock" (text boxes such as the OSCE start time)  HH:MM
     number    عدد           every other <input type=number>: digits only (+ «.» when step allows decimals, «-» when
                             min < 0), Persian digits typed become 0-9 and the Persian decimal «٫» or «/» becomes «.»,
                             a Persian message for min / max / step; an example placeholder from NUM_PH by name, else
                             the allowed range. A box without its own min / max gets NUM_RANGE[name]
                             (= field_rules.NUMBER_RANGE), else min 0 / max 1000000. No more digits than the max has
                             (and no more decimals than the step has) can be typed or pasted: the box keeps its last
                             value and says why. Pasted / dropped text goes in only when it is one number
                             («۱۲٫۵», «1,250», « 20 »); other text («abc 12») is refused with a hint (user's report
                             2026-11-19: text could be pasted into «نمره کل آزمون»).
     text      متن کوتاه     name in TEXT_RULES (title, name, description, class_location, specialty …): any text, at
                             most N characters and no unbroken «word» longer than W (keyboard junk; = field_rules.TEXT_RULES).
     pwnew     رمز جدید      <input type=password autocomplete="new-password">     English letters, digits, symbols; no space /
                             Persian letters (wrong keyboard layout); the password standard PW_RULES (≥ 8 with upper +
                             lower English letter, digit, symbol = field_rules.PASSWORD_RULES); what is missing is named in
                             the message under the box (no checklist / chips: user's choice);
                             a repeat box (name …2 / confirm…) must equal the form's first new-password box
     pwcur     رمز فعلی      every other <input type=password> (sign-in, current password)   same keys, no length rule
   Kinds after «username» keep a page's own placeholder (it is already an example) and only add one when missing.
   Every kind caps the length (maxlength; a longer value already saved shows an error until shortened); text boxes of
   a form with personal fields get maxlength 150, every other text box 500 and every <textarea> 5000 unless they set
   their own (user's report 2026-11-15: nothing may take endless text). Server-side length guard for every POST: middleware.PersonFieldLengthMiddleware (field_rules.FIELD_MAX).
   Or set data-mq-rule="<kind>" yourself; data-mq-rule="off" opts an input out. Search boxes (name q) are left alone.
   name / studentno / code / username keep the value the page was rendered with (only what is typed is filtered).
   A value left exactly as the page rendered it gets only the length check, not the format check: the server lets an
   unchanged saved value through too (field_rules._STORED_IN), so old data never blocks saving other fields.
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
    latin: /^(code|course_code|station_code|join_code|group_code)$/i,
    color: /^(settings_primary_color|mqa_color)$/i,
    ip: /^(ip_restriction_range|settings_ip_allow_list|settings_ip_block_list)$/i,
    decimal: /^(numeric_answer|numeric_tolerance)$/i
  };
  var TEXT_TYPES = { '': 1, text: 1, tel: 1, email: 1, search: 1 };

  // allow: one typed character; max: length; mode: keyboard; ph: example placeholder.
  var RULES = {
    national: { allow: /\d/, max: 10, mode: 'numeric', ph: '۰۰۱۲۳۴۵۶۷۸ (۱۰ رقم)', hint: 'فقط رقم وارد کنید.' },
    mobile: { allow: /\d/, max: 11, mode: 'tel', ph: '۰۹۱۲۳۴۵۶۷۸۹', hint: 'فقط رقم وارد کنید.', auto: 'tel' },
    landline: { allow: /\d/, max: 11, mode: 'tel', ph: '۰۲۱۸۸۷۷۶۶۵۵ (با کد شهر)', hint: 'فقط رقم وارد کنید.' },
    birth: { allow: /[\d\/]/, max: 10, mode: 'numeric', ph: '۱۳۷۸/۰۶/۲۱ (سال/ماه/روز)', hint: 'فقط رقم وارد کنید؛ «/» خودکار گذاشته می‌شود.' },
    email: { allow: /[A-Za-z0-9.@_%+\-]/, max: 100, mode: 'email', ph: 'name@example.com', hint: 'ایمیل فقط با حروف انگلیسی، رقم و . _ - @ نوشته می‌شود.', auto: 'email' },
    date: { allow: /[\d\/]/, max: 10, mode: 'numeric', ph: '۱۴۰۵/۰۱/۱۵ (سال/ماه/روز)', hint: 'فقط رقم وارد کنید؛ «/» خودکار گذاشته می‌شود.' },
    year: { allow: /\d/, max: 4, mode: 'numeric', ph: '۱۴۰۳', hint: 'فقط رقم وارد کنید (سال شمسی).' },
    name: { allow: /[A-Za-z\u0621-\u063A\u0641-\u0655\u067E\u0686\u0698\u06A9\u06AF\u06CC\u0622\u200C .'\-]/, max: 80, mode: 'text', rtl: true, raw: true,
      ph: { first_name: 'علی', last_name: 'محمدی', full_name: 'علی محمدی', father_name: 'حسن', display_name: 'دکتر محمدی', '': 'علی محمدی' },
      hint: 'فقط حروف وارد کنید؛ رقم و نماد مجاز نیست.' },
    studentno: { allow: /\d/, max: 15, mode: 'numeric', raw: true, ph: '۴۰۳۱۲۳۴۵۶', hint: 'فقط رقم وارد کنید.' },
    code: { allow: /[A-Za-z0-9\-]/, max: 20, mode: 'text', raw: true, ph: '۱۴۰۵۱۱۲',
      hint: 'فقط رقم، حروف انگلیسی و «-» مجاز است.' },
    username: { allow: /[A-Za-z0-9._@+\-]/, max: 100, mode: 'text', raw: true, ph: 'ali.mohammadi', hint: 'نام کاربری فقط با حروف انگلیسی، رقم و . _ - نوشته می‌شود.', auto: 'username' },
    totp: { allow: /\d/, max: 6, mode: 'numeric', ph: '۱۲۳۴۵۶', hint: 'فقط رقم وارد کنید (کد ۶ رقمی برنامه).', keepPh: true, auto: 'one-time-code' },
    otp: { allow: /[A-Za-z0-9\-]/, max: 12, mode: 'text', raw: true, ph: '۱۲۳۴۵۶', hint: 'کد ۶ رقمی برنامه یا کد بازیابی (حروف انگلیسی و رقم).', keepPh: true, auto: 'one-time-code' },
    identity: { allow: /\d/, max: 20, mode: 'numeric', ph: '۰۰۱۲۳۴۵۶۷۸', hint: 'فقط رقم وارد کنید (کد ملی یا شماره دانشجویی).', keepPh: true },
    acyear: { allow: /[\d\-]/, max: 9, mode: 'numeric', ph: '۱۴۰۵-۱۴۰۶', hint: 'فقط رقم وارد کنید؛ «-» خودکار گذاشته می‌شود.', keepPh: true },
    latin: { allow: /[A-Za-z0-9_\-]/, max: 20, mode: 'text', raw: true, ph: 'PED-101', hint: 'فقط حروف انگلیسی، رقم و «-» مجاز است.', keepPh: true },
    color: { allow: /[#0-9A-Fa-f]/, max: 7, mode: 'text', raw: true, ph: '#2563EB', hint: 'کد رنگ فقط # و رقم و حروف A تا F است.', keepPh: true },
    ip: { allow: /[0-9A-Fa-f.:\/,، ]/, max: 500, mode: 'text', raw: true, ph: '192.168.1.0/24', hint: 'فقط رقم، «.»، «/»، «,» و برای IPv6 «:» و حروف a تا f مجاز است.', keepPh: true },
    decimal: { allow: /[\d.\-]/, max: 20, mode: 'decimal', raw: true, ph: '۲.۵', hint: 'فقط عدد وارد کنید.', keepPh: true },
    clock: { allow: /[\d:]/, max: 5, mode: 'numeric', ph: '۰۹:۰۰', hint: 'فقط رقم وارد کنید؛ «:» خودکار گذاشته می‌شود.', keepPh: true },
    number: { allow: /\d/, max: 20, mode: 'numeric', raw: true, ph: '', hint: 'فقط عدد وارد کنید.', keepPh: true },
    text: { allow: /[\s\S]/, max: 200, mode: 'text', raw: true, rtl: true, ph: '', hint: '', keepPh: true },
    pwnew: { allow: /[!-~]/, max: 128, mode: 'text', raw: true, ph: 'Sara#1403', keepPh: true, auto: 'new-password',
      hint: 'رمز عبور فقط با حروف انگلیسی، رقم و نمادها نوشته می‌شود (بدون فاصله)؛ زبان صفحه‌کلید را انگلیسی کنید.' },
    pwcur: { allow: /[!-~]/, max: 128, mode: 'text', raw: true, ph: '••••••••', keepPh: true, auto: 'current-password',
      hint: 'رمز عبور فقط با حروف انگلیسی، رقم و نمادها نوشته می‌شود (بدون فاصله)؛ زبان صفحه‌کلید را انگلیسی کنید.' }
  };
  // Name caps by field (field_rules.FIELD_MAX); other kinds use RULES[kind].max.
  var NAME_MAX = { first_name: 30, last_name: 40, father_name: 30, full_name: 80, display_name: 60 };
  function maxOf(kind, el) {
    if (kind === 'name') return NAME_MAX[((el && el.name) || '').toLowerCase()] || 80;
    if (kind === 'username' && signInForm(el && el.form)) return 254;
    if (kind === 'text') return (textRule(el) || [200])[0];
    return RULES[kind].max;
  }
  // A sign-in form (a current-password box, no new-password box): its username box also takes an e-mail or a student
  // number and old usernames, so it gets no username format rule.
  function signInForm(f) {
    if (!f) return false;
    var current = false;
    for (var i = 0; i < f.elements.length; i++) {
      var o = f.elements[i];
      if ((o.type || '').toLowerCase() !== 'password') continue;
      if ((o.getAttribute('autocomplete') || '') === 'new-password') return false;
      current = true;
    }
    return current;
  }
  // Same patterns as apps/core/field_rules.py.
  var EMAIL_RE = /^(?=.{6,100}$)(?=[^@]{1,64}@)[A-Za-z0-9_%+\-](?:\.?[A-Za-z0-9_%+\-])*@(?:[A-Za-z0-9](?:[A-Za-z0-9\-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,24}$/;
  var USERNAME_RE = /^[A-Za-z](?:[A-Za-z0-9]|[._\-](?=[A-Za-z0-9])){2,29}$/;
  var CODE_RE = /^[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){2,19}$/;
  var FA_LETTER = /[ء-ی]/, LATIN_LETTER = /[A-Za-z]/;
  var MSG = {
    email: 'ایمیل معتبر نیست؛ مثلاً name@example.com (بخش قبل از @ حداکثر ۶۴ نویسه).',
    username: 'نام کاربری ۳ تا ۳۰ نویسه است: با حرف انگلیسی شروع شود و فقط حروف انگلیسی، رقم و . _ - (نه پشت سر هم یا در آخر) داشته باشد، مثلاً ali.mohammadi.',
    code: 'کد پرسنلی ۳ تا ۲۰ نویسه است: رقم و حروف انگلیسی، «-» فقط میان آن‌ها، مثلاً ۱۴۰۵۱۱۲ یا TCH-1024.',
    studentno: 'شماره دانشجویی ۴ تا ۱۵ رقم است، مثلاً ۴۰۳۱۲۳۴۵۶.',
    mobile: 'شماره موبایل باید ۱۱ رقم و با ۰۹ شروع شود (پیش‌شماره ۰۹۰ تا ۰۹۴ یا ۰۹۹)، مثلاً ۰۹۱۲۳۴۵۶۷۸۹.',
    landline: 'تلفن ثابت ۱۱ رقم است و با کد استان شروع می‌شود، مثلاً ۰۲۱۸۸۷۷۶۶۵۵.'
  };
  function nameError(v) {
    v = v.replace(/\s+/g, ' ');
    if ((v.match(/[A-Za-zء-غف-يپچژکگیآ]/g) || []).length < 2) return 'نام دست‌کم ۲ حرف دارد، مثلاً علی.';
    var bare = v.replace(/\[آزمایشی\]/g, '');
    if (FA_LETTER.test(bare) && LATIN_LETTER.test(bare)) return 'نام را یا فقط با حروف فارسی بنویسید یا فقط با حروف انگلیسی.';
    var words = bare.split(/[\s‌\-.']+/);
    for (var i = 0; i < words.length; i++) if (words[i].length > 20) return 'هر بخش نام حداکثر ۲۰ حرف است؛ نام را درست و با فاصله بنویسید.';
    if (/([A-Za-zء-ی])\1\1/.test(bare)) return 'یک حرف بیش از دو بار پشت سر هم آمده است؛ نام را درست بنویسید.';
    return '';
  }
  // The password standard, same order as field_rules.PASSWORD_RULES (server twin).
  var PW_RULES = [
    ['۸ نویسه یا بیشتر', function (v) { return v.length >= 8; }],
    ['حرف بزرگ انگلیسی (A-Z)', function (v) { return /[A-Z]/.test(v); }],
    ['حرف کوچک انگلیسی (a-z)', function (v) { return /[a-z]/.test(v); }],
    ['رقم', function (v) { return /[0-9]/.test(v); }],
    ['نماد مثل ! @ # $', function (v) { return /[!-\/:-@\[-`{-~]/.test(v); }]
  ];
  // «سیاست گذرواژه» chosen by the admin (field_rules.PASSWORD_POLICY_RULES); <html data-mq-pw-policy> from appearance_head.html.
  var PW_POLICIES = {
    strong: PW_RULES,
    medium: [PW_RULES[0], ['حرف انگلیسی', function (v) { return /[A-Za-z]/.test(v); }], PW_RULES[3]],
    weak: [['۶ نویسه یا بیشتر', function (v) { return v.length >= 6; }]]
  };
  function pwMissing(v) {
    var rules = PW_POLICIES[document.documentElement.getAttribute('data-mq-pw-policy')] || PW_RULES;
    var out = [];
    for (var i = 0; i < rules.length; i++) if (!rules[i][1](v)) out.push(rules[i][0]);
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
    credit_units: '۳', negative_factor: '۰٫۲۵', negative_mark: '۰٫۲۵', groups_count: '۴', students_per_group: '۸',
    default_points: '۱', keep: '۷', hotspot_max_clicks: '۱', media_max_record_seconds: '۱۲۰', min_correct: '۱',
    max_correct: '۳', short_answer_max_chars: '۲۰۰', correct_threshold: '۸۰', passing_score_total: '۱۰۰',
    min_passing_percent: '۶۰', media_rubric_points: '۲'
  };
  // Ranges for number boxes without their own min / max (same as field_rules.NUMBER_RANGE).
  var NUM_RANGE = {
    credit_units: [0, 30], capacity: [1, 1000], min_students: [0, 1000], waitlist_capacity: [0, 1000],
    duration_minutes: [1, 1440], max_attempts: [0, 100], passing_score: [0, 1000], pass_score: [0, 1000],
    exam_pass_score: [0, 1000], passing_score_total: [0, 1000], study_minutes: [0, 600], transition_minutes: [0, 600],
    students_per_group: [1, 1000], groups_count: [1, 1000], default_points: [0, 1000], min_passing_percent: [0, 100],
    correct_threshold: [0, 100], short_answer_max_chars: [1, 10000], media_max_record_seconds: [1, 3600],
    hotspot_max_clicks: [1, 100], negative_factor: [0, 1], negative_mark: [0, 1000], min_correct: [0, 100], max_correct: [0, 100]
  };
  // Short free text of records: [most characters, longest unbroken word (0 = any)] (same as field_rules.TEXT_RULES).
  var TEXT_RULES = {
    title: [200, 40], exam_title: [200, 40], course_title: [200, 40], name: [100, 40], description: [2000, 0],
    class_schedule: [100, 30], class_location: [100, 30], domain: [120, 40], objectives: [200, 40], new_objective: [200, 40],
    patient_age: [40, 20], patient_chief_complaint: [200, 40], field_of_study: [150, 30], specialty: [150, 30],
    academic_rank: [150, 30], degree: [150, 30], semester: [150, 30], class_group: [150, 30], responsibility_area: [150, 30],
    department: [150, 30], office: [150, 30], job_title: [150, 30]
  };
  function textRule(el) { return TEXT_RULES[((el && el.name) || '').toLowerCase()] || null; }
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
  // Most digits before / after the point a number box takes: those of its largest allowed value / its step.
  function numDigits(el) {
    var sp = numSpec(el), big = Math.max(Math.abs(isNaN(sp.max) ? 1000000 : sp.max), Math.abs(isNaN(sp.min) ? 0 : sp.min));
    var dec = !sp.dec ? 0 : sp.step === 'any' ? 6 : Math.max(1, (sp.step.split('.')[1] || '').length);
    return { int: String(Math.floor(big)).length, dec: dec };
  }
  // The number in pasted / dropped text, or null when the text is not one number (for this box).
  function numberFromText(el, text) {
    var t = latinDigits(text).replace(/[\u200c\u200e\u200f\s]/g, '').replace(/[٫\/]/g, '.').replace(/[−–]/g, '-').replace(/^\+/, '');
    if (/[,٬]/.test(t)) {  // thousands separators only in their places: 1,250 / 12,500.5
      if (!/^-?\d{1,3}([,٬]\d{3})+(\.\d*)?$/.test(t)) return null;
      t = t.replace(/[,٬]/g, '');
    }
    if (!/^-?(\d+\.?\d*|\.\d+)$/.test(t)) return null;
    var sp = numSpec(el);
    if (t[0] === '-' && !sp.neg) return null;
    if (t.indexOf('.') >= 0 && !sp.dec) {
      if (!/\.0*$/.test(t)) return null;
      t = t.replace(/\.0*$/, '');
    }
    return t;
  }
  function fmtNum(n) { return faDigits(String(n)).replace('.', '٫'); }
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
    if (type !== 'search' && textRule(el)) return 'text';
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
    // Same as field_rules.birth_date_error: not after today, age 15 … 100 (BIRTH_AGE).
    function cmp(a, b) { return a[0] - b[0] || a[1] - b[1] || a[2] - b[2]; }
    var day = [y, mo, d];
    if (cmp(day, today) > 0) return 'تاریخ تولد نمی‌تواند بعد از امروز باشد.';
    if (cmp(day, [today[0] - 15, today[1], today[2]]) > 0) return 'سن باید دست‌کم ۱۵ سال باشد؛ سال تولد را درست وارد کنید.';
    if (cmp(day, [today[0] - 100, today[1], today[2]]) <= 0) return 'سن نمی‌تواند بیش از ۱۰۰ سال باشد؛ سال تولد را درست وارد کنید.';
    return '';
  }
  function numberError(el, v) {
    var sp = numSpec(el), n = parseFloat(v), base = isNaN(sp.min) ? 0 : sp.min;
    if (el.validity && el.validity.badInput) return 'فقط عدد وارد کنید.';
    if (v === '' && el.required) return 'این خانه را پر کنید.';
    if (v === '' || isNaN(n)) return '';
    if (!isNaN(sp.min) && n < sp.min) return 'کمترین مقدار ' + fmtNum(sp.min) + ' است.';
    if (!isNaN(sp.max) && n > sp.max) return 'بیشترین مقدار ' + fmtNum(sp.max) + ' است.';
    if (!sp.dec && Math.floor(n) !== n) return 'عدد باید صحیح باشد (بدون اعشار).';
    if (el.validity && el.validity.stepMismatch) {  // the two allowed values around the one typed
      var st = parseFloat(sp.step), lo = +(base + Math.floor((n - base) / st + 1e-9) * st).toFixed(6), hi = +(lo + st).toFixed(6);
      return 'باید مضربی از ' + fmtNum(st) + ' باشد؛ مثلاً ' + fmtNum(lo) + ' یا ' + fmtNum(hi) + '.';
    }
    return '';
  }
  // «محدوده IP» (same as field_rules.ip_range_error): IPv4 / IPv6 addresses or CIDR ranges, separated by «,» «،» or
  // spaces; ≤ 20 parts; no leading zeros in IPv4; prefix at least /8 (IPv4) or /16 (IPv6); no repeats.
  function ipv4Ok(a) {
    var g = a.split('.');
    if (g.length !== 4) return false;
    for (var i = 0; i < 4; i++) if (!/^(0|[1-9]\d{0,2})$/.test(g[i]) || +g[i] > 255) return false;
    return true;
  }
  function ipv6Ok(a) {
    if (!/^[0-9A-Fa-f:]+$/.test(a) || /:::/.test(a)) return false;
    var halves = a.split('::');
    if (halves.length > 2) return false;
    var groups = function (h) { return h ? h.split(':') : []; };
    var all = groups(halves[0]).concat(halves.length === 2 ? groups(halves[1]) : []);
    for (var i = 0; i < all.length; i++) if (!/^[0-9A-Fa-f]{1,4}$/.test(all[i])) return false;
    return halves.length === 2 ? all.length < 8 : all.length === 8;
  }
  function ipError(v) {
    var iso = function (t) { return '\u2068' + t + '\u2069'; };  // a Latin address inside Persian text
    var parts = v.split(/[\s,،]+/).filter(Boolean), seen = {};
    if (parts.length > 20) return 'حداکثر ۲۰ نشانی یا محدوده مجاز است.';
    for (var i = 0; i < parts.length; i++) {
      var p = parts[i], cut = p.split('/'), addr = cut[0], v6 = addr.indexOf(':') >= 0;
      var prefix = cut.length === 2 && /^\d{1,3}$/.test(cut[1]) ? +cut[1] : cut.length === 1 ? (v6 ? 128 : 32) : -1;
      if (cut.length > 2 || prefix < 0 || prefix > (v6 ? 128 : 32) || !(v6 ? ipv6Ok(addr) : ipv4Ok(addr)))
        return '«' + iso(p) + '» نشانی یا محدوده‌ی IP معتبر نیست؛ مثلاً ' + iso('192.168.1.0/24') + ' یا ' + iso('10.0.0.5') + '.';
      if (prefix < (v6 ? 16 : 8))
        return '«' + iso(p) + '» محدوده‌ی بسیار بزرگی است و عملاً همه را راه می‌دهد؛ پیشوند دست‌کم ' + iso(v6 ? '/16' : '/8') + ' باشد.';
      // the range itself, as the server compares them (192.168.1.5/24 = 192.168.1.0/24, 10.0.0.5 = 10.0.0.5/32)
      var key = (v6 ? addr.toLowerCase() : String(addr.split('.').reduce(function (n, g) { return n * 256 + +g; }, 0)
        - addr.split('.').reduce(function (n, g) { return n * 256 + +g; }, 0) % Math.pow(2, 32 - prefix))) + '/' + prefix;
      if (seen[key]) return '«' + iso(p) + '» تکراری است.';
      seen[key] = true;
    }
    return '';
  }
  function errorOf(kind, v, el) {
    if (kind === 'number') return numberError(el, v);
    if (!v) return el && el.required && !el.disabled ? 'این خانه را پر کنید.' : '';
    // A value already saved longer than the field allows (typing stops at maxlength; this catches old data).
    var max = maxOf(kind, el);
    if (kind !== 'mobile' && v.length > max) return 'حداکثر ' + faDigits(max) + ' نویسه مجاز است؛ مقدار را کوتاه کنید.';
    if (kind === 'text') {  // keyboard junk is refused even when already saved (the server refuses it too)
      var word = (textRule(el) || [0, 0])[1], words = v.split(/[\s‌\-\/،,;:.()]+/);
      for (var w = 0; w < words.length; w++)
        if (word && words[w].length > word) return 'کلمه‌ای بیش از ' + faDigits(word) + ' نویسه‌ی پشت سر هم دارد؛ متن درست و با فاصله بنویسید.';
      return '';
    }
    // The value the page was rendered with, unchanged: length only (the server lets a stored value through too).
    if (el && el._mqInitial && v === el._mqInitial && kind !== 'pwnew' && kind !== 'pwcur') return '';
    if (kind === 'national') return nationalOk(v) ? '' : (v.length !== 10 ? 'کد ملی باید ۱۰ رقم باشد.' : 'این کد ملی معتبر نیست؛ رقم‌ها را دوباره بررسی کنید.');
    if (kind === 'mobile') return /^09[0-49]\d{8}$/.test(v) ? '' : MSG.mobile;
    if (kind === 'landline') return /^0[1-8]\d{9}$/.test(v) ? '' : MSG.landline;
    if (kind === 'birth') return birthError(v);
    if (kind === 'date') return birthError(v, true);
    if (kind === 'year') return /^\d{4}$/.test(v) && +v >= 1300 && +v <= today[0] + 1 ? '' : 'سال را ۴ رقمی و شمسی بنویسید، مثلاً ۱۴۰۳.';
    if (kind === 'name') return nameError(v);
    if (kind === 'studentno') return /^\d{4,15}$/.test(v) ? '' : MSG.studentno;
    if (kind === 'code') return CODE_RE.test(v) ? '' : MSG.code;
    if (kind === 'username' && signInForm(el && el.form)) return '';
    if (kind === 'username') return v.indexOf('@') >= 0 ? (EMAIL_RE.test(v) ? '' : MSG.email) : (USERNAME_RE.test(v) ? '' : MSG.username);
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
    if (kind === 'email') return EMAIL_RE.test(v) ? '' : MSG.email;
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
  function clean(kind, raw, el) {
    if (kind === 'text') return raw;  // free text: Persian digits and every character stay
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
    return out.slice(0, maxOf(kind, el));
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
    if (el.hasAttribute('maxlength') || el.readOnly) return;
    if (el.tagName === 'TEXTAREA') { el.setAttribute('maxlength', String((textRule(el) || [5000])[0])); return; }
    var type = (el.getAttribute('type') || '').toLowerCase();
    if (!TEXT_TYPES[type] || type === 'search' || el.name === 'q') return;
    el.setAttribute('maxlength', TEXT_MAX.test(el.name || '') || personForm(el.form) ? '150' : '500');
  }

  function setup(el) {
    if (el._mqRule !== undefined) return;
    var kind = ruleOf(el);
    el._mqRule = kind;
    if (!kind) { capText(el); return; }
    var rule = RULES[kind];
    el.classList.add('mq-rule');
    if (kind === 'number') {
      el.classList.add('mq-rule-num');  // keeps the page's own alignment (scores, points …)
      var range = NUM_RANGE[(el.name || '').toLowerCase()];  // no negative / endless numbers where a page set no limit
      if (!el.hasAttribute('min')) el.setAttribute('min', String(range ? range[0] : 0));
      if (!el.hasAttribute('max')) el.setAttribute('max', String(range ? range[1] : 1000000));
    }
    else if (rule.rtl) el.classList.add('mq-rule-rtl'); else el.setAttribute('dir', 'ltr');
    el.setAttribute('inputmode', kind === 'number' && numSpec(el).dec ? 'decimal' : rule.mode);
    var ownMax = +el.getAttribute('maxlength') || 0;  // a page's own, tighter cap stays (e.g. a 6-digit code)
    if (el.type !== 'number' && !(rule.keepPh && ownMax && ownMax < maxOf(kind, el)))
      el.setAttribute('maxlength', String(kind === 'mobile' ? 14 : maxOf(kind, el))); // room for a pasted +98 / spaces, cleaned at once
    el.setAttribute('autocapitalize', 'off');
    el.setAttribute('spellcheck', 'false');
    if (rule.auto && !el.hasAttribute('autocomplete')) el.setAttribute('autocomplete', rule.auto);
    var ph = placeholderOf(kind, el);
    var own = el.getAttribute('placeholder');
    if (!el.hasAttribute('data-keep-placeholder') && !(rule.keepPh && own && own.trim()) && ph) el.setAttribute('placeholder', ph);
    ph = el.getAttribute('placeholder') || ph;
    if (!el.hasAttribute('title') && ph) el.setAttribute('title', 'نمونه: ' + ph);
    if (!rule.raw) {
      var v = clean(kind, el.value, el);
      if (v !== el.value) el.value = v;
    }
    el._mqInitial = (el.value || '').trim();  // unchanged = format not re-checked (see header)
    if (isDate(kind) && window.mqDatePicker) window.mqDatePicker.attach(el, kind);
    if (el.value) check(el, false);
  }
  function scan(root) {
    if (!root || !root.querySelectorAll) return;
    if (root.tagName === 'INPUT' || root.tagName === 'TEXTAREA') { setup(root); return; }
    var list = root.querySelectorAll('input, textarea');
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
      s = s.replace(/[٫\/]/g, '.');  // the Persian keyboard's decimal separator (or «/») is the point
      for (k = 0; k < s.length; k++) if (numAllows(el, s[k])) only += s[k];
      if (only.indexOf('.') >= 0 && (String(el.value).indexOf('.') >= 0 || only.indexOf('.') !== only.lastIndexOf('.'))) {
        e.preventDefault();
        hint(el, 'فقط یک ممیز (نقطه‌ی اعشار) مجاز است.');
        return;
      }
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
    if (el._mqRule === 'number' && s.indexOf('.') >= 0 && !numSpec(el).dec) { hint(el, 'این عدد باید صحیح باشد (بدون اعشار).'); return; }
    hint(el, rule.hint);
  }, true);
  // A short note under the field while typing (not over an error already shown there).
  function hint(el, text) {
    if (el._mqTouched && el.validationMessage) return;
    show(el, text, true);
    clearTimeout(el._mqHintTimer);  // one timer per field, so a hint never outlives its field's next one
    el._mqHintTimer = setTimeout(function () { if (!(el._mqTouched && el.validationMessage)) show(el, '', false); }, 2200);
  }
  // Pasted / dropped text into a number box: only one number goes in (the browser would keep the digits of any text,
  // or nothing of «۱۲٫۵»).
  function putNumber(e, text) {
    var el = target(e);
    if (!el || el._mqRule !== 'number' || text == null) return;
    e.preventDefault();
    var num = numberFromText(el, text);
    if (num === null) { hint(el, 'متن چسبانده‌شده عدد نیست؛ فقط عدد وارد کنید.'); return; }
    if (e.type === 'drop') el.focus();
    if (!(document.execCommand && document.execCommand('insertText', false, num))) {
      el.value = num;
      el.dispatchEvent(new Event('input', { bubbles: true }));
    }
  }
  document.addEventListener('paste', function (e) {
    putNumber(e, (e.clipboardData || window.clipboardData || { getData: function () { return null; } }).getData('text'));
  }, true);
  document.addEventListener('drop', function (e) { if (e.dataTransfer) putNumber(e, e.dataTransfer.getData('text')); }, true);
  // A number box keeps its last good value when a key or paste would give it more digits than it takes.
  function limitNumber(el) {
    var v = String(el.value), m = /^-?(\d*)(?:\.(\d*))?$/.exec(v);
    if (!m) return;
    var d = numDigits(el), intLen = m[1].replace(/^0+(?=\d)/, '').length, decLen = (m[2] || '').length;
    var max = numSpec(el).max, over = !isNaN(max) && v !== '' && parseFloat(v) > max;
    if (intLen <= d.int && decLen <= d.dec && !over) {
      var tidy = v.replace(/^(-?)0+(?=\d)/, '$1').replace(/^(-?)\./, '$10.');  // «025» → «25», «.5» → «0.5»
      if (tidy !== v) el.value = tidy;
      el._mqLast = el.value;
      return;
    }
    el.value = el._mqLast != null ? el._mqLast : '';
    hint(el, over ? 'بیشترین مقدار ' + fmtNum(max) + ' است.'
      : intLen > d.int ? 'حداکثر ' + faDigits(d.int) + ' رقم پیش از ممیز مجاز است.' : 'حداکثر ' + faDigits(d.dec) + ' رقم اعشار مجاز است.');
  }
  document.addEventListener('focusin', function (e) {
    var el = target(e);
    if (el && el._mqRule === 'number') el._mqLast = el.value;  // the value at hand (pages also set it by script)
  }, true);

  document.addEventListener('input', function (e) {
    var el = target(e);
    if (!el) return;
    var kind = el._mqRule;
    if (kind === 'number') {  // the browser keeps a number box's value numeric …
      // … except Firefox, which shows typed text it can't read (value '' + badInput) and lets keys that come as
      // composition (Persian layout, IME) past beforeinput uncancelled: put the last good value back.
      if (e.isComposing) return;
      if (el.validity && el.validity.badInput && e.data && /^insert/.test(e.inputType || '')) {
        var s = latinDigits(e.data).replace(/[٫\/]/g, '.'), only = '';
        for (var k = 0; k < s.length; k++) if (numAllows(el, s[k])) only += s[k];
        if (only !== s || /[^\x00-\x7f]/.test(e.data)) {
          el.value = el._mqLast != null ? el._mqLast : '';
          if (only && only.indexOf('.') < 0) { el.value = el.value + only; limitNumber(el); }  // Persian digits → 0-9
          else hint(el, s.indexOf('.') >= 0 && !numSpec(el).dec ? 'این عدد باید صحیح باشد (بدون اعشار).' : RULES.number.hint);
          check(el, false);
          return;
        }
      }
      limitNumber(el); check(el, false); return;
    }
    var before = el.value, caret = el.selectionStart;
    var cleaned = clean(kind, before, el);
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
    el._mqInitial = '';  // what was typed under the other kind gets the full check
    el.value = clean(kind, el.value, el);
    check(el, !!el.value);
  }
  window.mqFieldRules = { scan: scan, check: check, nationalOk: nationalOk, setRule: setRule };
})();
