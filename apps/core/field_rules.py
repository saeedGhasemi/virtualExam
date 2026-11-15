"""Server-side twin of static/js/field-rules.js: format rules for personal-data fields (user's requirement).

`clean_person_fields(data)` normalises national_id / phone / landline / birth_date / email / names / codes in place (Persian and
Arabic digits → 0-9, spaces and dashes out, +98 → 0, 1378/6/2 → 1378/06/02) and returns Persian error messages for
values that don't fit. Empty values are not errors (required-ness is the caller's business).
"""
import re

_FA = str.maketrans('0123456789', '۰۱۲۳۴۵۶۷۸۹')
_DIGITS = str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩', '01234567890123456789')
# Persian / English letters, space, ZWNJ, . ' - ; at least one letter. Kept loose for names seeded with «[آزمایشی]».
_NAME = re.compile(r"(?=.*[A-Za-zء-ی])[A-Za-zء-غف-ٕپچژکگیآ‌ .'\-\[\]]+")
# E-mail like RFC 5321 in practice: local part ≤ 64 (no leading / trailing / double dot), domain labels 1–63 that
# don't start or end with «-», a 2–24-letter top-level domain; whole address ≤ FIELD_MAX['email'].
_EMAIL = re.compile(r'^(?=.{6,100}$)(?=[^@]{1,64}@)[A-Za-z0-9_%+\-](?:\.?[A-Za-z0-9_%+\-])*@'
                    r'(?:[A-Za-z0-9](?:[A-Za-z0-9\-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,24}$')
# Username: 3–30 English letters / digits starting with a letter; «.», «_», «-» only between them. (An account may
# also sign in with its e-mail as username: an e-mail is accepted too.)
_USERNAME = re.compile(r'^[A-Za-z](?:[A-Za-z0-9]|[._\-](?=[A-Za-z0-9])){2,29}$')
# Personnel / staff code: 3–20 English letters and digits, «-» only between them (data has ADM-1024, MQTEST-T01 …).
_CODE = re.compile(r'^[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){2,19}$')
_STUDENT_NO = re.compile(r'^\d{4,15}$')
# Iranian mobile: 09 + operator digit (090–094 Irancell / Rightel / …, 099 MCI / MVNOs) + 8 digits.
_MOBILE = re.compile(r'^09[0-49]\d{8}$')
# Landline: 0 + two-digit province code (01x–08x) + 8-digit number = 11 digits.
_LANDLINE = re.compile(r'^0[1-8]\d{9}$')
_PERSIAN_LETTER = re.compile(r'[ء-ی]')
_LATIN_LETTER = re.compile(r'[A-Za-z]')
NAME_WORD_MAX = 20     # longest single word of a name (عبدالرسول = 9, Venkataraghavan = 15)
BIRTH_AGE = (15, 100)  # a birth date makes the person 15 … 100 years old


def name_error(value: str) -> str:
    """'' when `value` looks like a real person's name, else a Persian reason (length caps are FIELD_MAX's)."""
    value = re.sub(r'\s+', ' ', str(value or '')).strip()
    if not _NAME.fullmatch(value):
        return 'نام فقط حروف فارسی یا انگلیسی است (بدون رقم و نماد)، مثلاً علی محمدی.'
    letters = [c for c in value if c.isalpha()]
    if len(letters) < 2:
        return 'نام دست‌کم ۲ حرف دارد.'
    bare = re.sub(r'\[آزمایشی\]', '', value)  # seed marker
    if _PERSIAN_LETTER.search(bare) and _LATIN_LETTER.search(bare):
        return 'نام را یا فقط با حروف فارسی بنویسید یا فقط با حروف انگلیسی.'
    if any(len(word) > NAME_WORD_MAX for word in re.split(r"[\s‌\-.']+", bare)):
        return f'هر بخش نام حداکثر {str(NAME_WORD_MAX).translate(_FA)} حرف است؛ نام را درست و با فاصله بنویسید.'
    if re.search(r'(\w)\1\1', bare):
        return 'یک حرف بیش از دو بار پشت سر هم آمده است؛ نام را درست بنویسید.'
    return ''


def email_error(value: str) -> str:
    value = latin_digits(value)
    return '' if _EMAIL.fullmatch(value) else 'ایمیل معتبر نیست؛ مثلاً name@example.com (بخش قبل از @ حداکثر ۶۴ نویسه).'


def username_error(value: str) -> str:
    value = latin_digits(value)
    if '@' in value:
        return email_error(value)
    return '' if _USERNAME.fullmatch(value) else (
        'نام کاربری ۳ تا ۳۰ نویسه است: با حرف انگلیسی شروع شود و فقط حروف انگلیسی، رقم و . _ - (نه پشت سر هم یا در آخر) داشته باشد، مثلاً ali.mohammadi.')


# Longest value a personal / basic-info field may hold, by POST name (teacher's report: a 300-character student
# number was saved and ran across the profile pages). Checked on every POST by middleware.PersonFieldLengthMiddleware;
# the same caps are the inputs' maxlength in static/js/field-rules.js. Raw lengths, so a few spaces / dashes still fit.
FIELD_MAX = {
    'national_id': 20, 'national_code': 20,
    'phone': 20, 'mobile': 20, 'phone_number': 20, 'mobile_number': 20, 'landline': 20,
    'birth_date': 20, 'entry_year': 10,
    # Realistic caps like professional sign-up forms (teacher's report 2026-11-15: an 80 + 80-letter junk name, a
    # 254-character e-mail and a 30-digit code were accepted and broke the users page). Same caps in field-rules.js.
    'first_name': 30, 'last_name': 40, 'father_name': 30, 'full_name': 80, 'display_name': 60,
    'student_number': 15, 'student_code': 15, 'personnel_code': 20, 'employee_code': 20, 'identifier': 20,
    'username': 100, 'email': 100, 'login_email': 100, 'notification_email': 100,
    'field_of_study': 150, 'specialty': 150, 'academic_rank': 150, 'degree': 150, 'semester': 150,
    'class_group': 150, 'responsibility_area': 150, 'department': 150, 'office': 150, 'job_title': 150,
}
FIELD_LABELS = {
    'national_id': 'کد ملی', 'national_code': 'کد ملی', 'phone': 'شماره تماس', 'mobile': 'شماره موبایل',
    'phone_number': 'شماره تماس', 'mobile_number': 'شماره موبایل', 'landline': 'تلفن ثابت', 'birth_date': 'تاریخ تولد',
    'entry_year': 'سال ورود', 'first_name': 'نام', 'last_name': 'نام خانوادگی', 'father_name': 'نام پدر',
    'full_name': 'نام و نام خانوادگی', 'display_name': 'نام نمایشی', 'student_number': 'شماره دانشجویی',
    'student_code': 'شماره دانشجویی', 'personnel_code': 'کد پرسنلی', 'employee_code': 'کد پرسنلی',
    'identifier': 'کد پرسنلی', 'username': 'نام کاربری', 'email': 'ایمیل', 'login_email': 'ایمیل',
    'field_of_study': 'رشته تحصیلی', 'specialty': 'تخصص', 'academic_rank': 'مرتبه علمی', 'degree': 'مقطع',
    'semester': 'نیمسال', 'class_group': 'گروه', 'responsibility_area': 'حوزه مسئولیت', 'department': 'بخش / سمت',
    'office': 'اتاق / دفتر', 'job_title': 'سمت', 'notification_email': 'ایمیل اعلان‌ها', 'entrance_year': 'سال ورود',
}


# Titles, names, codes and short free text of records (course, group, org unit, exam, OSCE station …), by POST name:
# (most characters, longest unbroken word; 0 = no word limit). User's report 2026-11-15: 100-letter unbroken junk in
# course / unit / group / OSCE / wizard fields was accepted and ran over the pages. Real titles have words ≤ ~20
# letters; a «word» longer than the limit is keyboard junk. Same table in static/js/field-rules.js (TEXT_RULES).
TEXT_RULES = {
    'title': (200, 40), 'exam_title': (200, 40), 'course_title': (200, 40), 'name': (100, 40),
    'code': (20, 0), 'course_code': (20, 0), 'group_code': (20, 0), 'station_code': (20, 0),
    'description': (2000, 0), 'class_schedule': (100, 30), 'class_location': (100, 30),
    'domain': (120, 40), 'objectives': (200, 40), 'new_objective': (200, 40),
    'patient_age': (40, 20), 'patient_chief_complaint': (200, 40),
    'field_of_study': (150, 30), 'specialty': (150, 30), 'academic_rank': (150, 30), 'degree': (150, 30),
    'semester': (150, 30), 'class_group': (150, 30), 'responsibility_area': (150, 30), 'department': (150, 30),
    'office': (150, 30), 'job_title': (150, 30),
}
TEXT_LABELS = {
    'title': 'عنوان', 'exam_title': 'عنوان آزمون', 'course_title': 'عنوان درس', 'name': 'نام', 'code': 'کد',
    'course_code': 'کد درس', 'group_code': 'شماره گروه', 'station_code': 'کد ایستگاه', 'description': 'توضیحات',
    'class_schedule': 'برنامه کلاس', 'class_location': 'مکان کلاس', 'domain': 'حوزه', 'objectives': 'هدف',
    'new_objective': 'هدف', 'patient_age': 'سن بیمار', 'patient_chief_complaint': 'شکایت اصلی',
}
for _name, (_limit, _word) in TEXT_RULES.items():
    FIELD_MAX[_name] = min(FIELD_MAX.get(_name, _limit), _limit)
    FIELD_LABELS.setdefault(_name, TEXT_LABELS.get(_name, _name))

# Number boxes, by POST name: (least, most). Wide enough for every page that uses the name (each page sets its own,
# tighter min / max on the box); they stop negative durations / scores and 20-digit capacities (same report).
# field-rules.js (NUM_RANGE) has the same names plus max_attempts / min_passing_percent / negative_factor / passing_score_total, which the exam wizard checks
# itself (it clamps attempts, reports the percent / negative factor on its form); duration 0 is left to the views (OSCE says why).
NUMBER_RANGE = {
    'credit_units': (0, 30), 'capacity': (1, 1000), 'min_students': (0, 1000), 'waitlist_capacity': (0, 1000),
    'duration_minutes': (0, 1440), 'passing_score': (0, 1000), 'pass_score': (0, 1000),
    'exam_pass_score': (0, 1000), 'study_minutes': (0, 600),
    'transition_minutes': (0, 600), 'students_per_group': (1, 1000), 'groups_count': (1, 1000),
    'default_points': (0, 1000), 'correct_threshold': (0, 100),
    'short_answer_max_chars': (1, 10000), 'media_max_record_seconds': (1, 3600), 'hotspot_max_clicks': (1, 100),
    'negative_mark': (0, 1000), 'min_correct': (0, 100), 'max_correct': (0, 100),
}
NUMBER_LABELS = {
    'credit_units': 'تعداد واحد', 'capacity': 'ظرفیت', 'min_students': 'حداقل دانشجو',
    'waitlist_capacity': 'ظرفیت فهرست انتظار', 'duration_minutes': 'مدت زمان (دقیقه)', 'max_attempts': 'تعداد دفعات شرکت',
    'passing_score': 'نمره قبولی', 'pass_score': 'نمره قبولی', 'exam_pass_score': 'نمره قبولی',
    'passing_score_total': 'نمره کل', 'study_minutes': 'زمان مطالعه', 'transition_minutes': 'زمان جابه‌جایی',
    'students_per_group': 'دانشجو در هر گروه', 'groups_count': 'تعداد گروه', 'default_points': 'نمره پیش‌فرض',
    'min_passing_percent': 'درصد قبولی', 'correct_threshold': 'آستانه درستی', 'short_answer_max_chars': 'حداکثر نویسه',
    'media_max_record_seconds': 'حداکثر زمان ضبط', 'hotspot_max_clicks': 'حداکثر کلیک', 'negative_factor': 'ضریب نمره منفی',
    'negative_mark': 'نمره منفی', 'min_correct': 'حداقل پاسخ درست', 'max_correct': 'حداکثر پاسخ درست',
}


def _fa_num(value) -> str:
    text = f'{value:g}' if isinstance(value, float) else str(value)
    return text.translate(_FA)


def long_word(value: str, limit: int) -> bool:
    """True when `value` has an unbroken run (no space / ZWNJ / dash / slash) longer than `limit` characters."""
    return bool(limit) and any(len(word) > limit for word in re.split(r'[\s‌\-/،,;:.()]+', value or ''))


def too_long_error(post) -> str:
    """Persian message for the first POST field longer than FIELD_MAX allows (or, for TEXT_RULES fields, with an
    unbroken word longer than its limit), else ''."""
    for name, limit in FIELD_MAX.items():
        for value in post.getlist(name) if hasattr(post, 'getlist') else [post.get(name)]:
            if value and len(str(value).strip()) > limit:
                label = FIELD_LABELS.get(name, name)
                return f'«{label}» حداکثر {_fa_num(limit)} نویسه است؛ مقدار طولانی‌تر ذخیره نشد. آن را کوتاه کنید و دوباره ذخیره کنید.'
    for name, (limit, word) in TEXT_RULES.items():
        for value in post.getlist(name) if hasattr(post, 'getlist') else [post.get(name)]:
            if value and long_word(str(value), word):
                label = FIELD_LABELS.get(name, name)
                return f'«{label}» کلمه‌ای بیش از {_fa_num(word)} نویسه‌ی پشت سر هم دارد؛ متن درست و با فاصله بنویسید.'
    for name in LATIN_CODES:  # course / unit / station codes: English letters, digits, - and _ (field-rules.js «latin»)
        for value in post.getlist(name) if hasattr(post, 'getlist') else [post.get(name)]:
            text = latin_digits(value)
            if text and not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9_\-]*[A-Za-z0-9])?', text):
                return f'«{FIELD_LABELS.get(name, name)}» فقط حروف انگلیسی، رقم و «-» دارد، مثلاً PED-101.'
    return number_error(post)


LATIN_CODES = ('code', 'course_code', 'station_code')


def number_error(post) -> str:
    """Persian message for the first NUMBER_RANGE POST field that isn't a number in its range, else ''."""
    for name, (low, high) in NUMBER_RANGE.items():
        for value in post.getlist(name) if hasattr(post, 'getlist') else [post.get(name)]:
            text = latin_digits(value)
            if not text:
                continue
            label = NUMBER_LABELS.get(name, name)
            try:
                number = float(text)
            except ValueError:
                return f'«{label}» باید عدد باشد.'
            if number != number or number < low or number > high:
                return f'«{label}» باید بین {_fa_num(low)} و {_fa_num(high)} باشد.'
    return ''


def latin_digits(value) -> str:
    return str(value or '').translate(_DIGITS).strip()


def national_id_ok(code: str) -> bool:
    if not re.fullmatch(r'\d{10}', code or '') or len(set(code)) == 1:
        return False
    rest = sum(int(code[i]) * (10 - i) for i in range(9)) % 11
    check = int(code[9])
    return check == rest if rest < 2 else check == 11 - rest


def _jalali_leap(year: int) -> bool:
    return year % 33 in (1, 5, 9, 13, 17, 22, 26, 30)  # 33-year cycle, exact for 1210–1634


def _gregorian_to_jalali(gy, gm, gd):
    g_d_m = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    gy2 = gy + 1 if gm > 2 else gy
    days = 355666 + 365 * gy + (gy2 + 3) // 4 - (gy2 + 99) // 100 + (gy2 + 399) // 400 + gd + g_d_m[gm - 1]
    jy = -1595 + 33 * (days // 12053)
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        return jy, 1 + days // 31, 1 + days % 31
    return jy, 7 + (days - 186) // 30, 1 + (days - 186) % 30


def today_jalali():
    from django.utils import timezone
    d = timezone.localdate()
    return _gregorian_to_jalali(d.year, d.month, d.day)


def birth_date_error(value: str) -> str:
    match = re.fullmatch(r'(\d{4})/(\d{1,2})/(\d{1,2})', value or '')
    if not match:
        return 'تاریخ تولد را به شکل سال/ماه/روز شمسی بنویسید، مثلاً ۱۳۷۸/۰۶/۲۱.'
    year, month, day = (int(part) for part in match.groups())
    if not 1 <= month <= 12:
        return 'ماه تاریخ تولد باید بین ۱ تا ۱۲ باشد.'
    days = 31 if month <= 6 else 30 if month <= 11 else (30 if _jalali_leap(year) else 29)
    if not 1 <= day <= days:
        return 'روز تاریخ تولد در آن ماه وجود ندارد.'
    ty, tm, td = today_jalali()
    if (year, month, day) > today_jalali():
        return 'تاریخ تولد نمی‌تواند بعد از امروز باشد.'
    youngest, oldest = BIRTH_AGE
    if (year, month, day) > (ty - youngest, tm, td):
        return f'سن باید دست‌کم {str(youngest).translate(_FA)} سال باشد؛ سال تولد را درست وارد کنید.'
    if (year, month, day) <= (ty - oldest, tm, td):
        return f'سن نمی‌تواند بیش از {str(oldest).translate(_FA)} سال باشد؛ سال تولد را درست وارد کنید.'
    return ''


def jalali_date_error(value: str, label: str = 'تاریخ') -> str:
    """'' when `value` is a real Jalali date yyyy/mm/dd between 1300 and 1500 (the `date` kind of field-rules.js)."""
    match = re.fullmatch(r'(\d{4})[/-](\d{1,2})[/-](\d{1,2})', latin_digits(value or '').strip())
    if not match:
        return f'{label} را فقط با رقم و به شکل سال/ماه/روز شمسی بنویسید، مثلاً ۱۴۰۵/۰۷/۰۱.'
    year, month, day = (int(part) for part in match.groups())
    if not 1300 <= year <= 1500:
        return f'سال {label} باید بین ۱۳۰۰ و ۱۵۰۰ باشد.'
    if not 1 <= month <= 12:
        return f'ماه {label} باید بین ۱ تا ۱۲ باشد.'
    days = 31 if month <= 6 else 30 if month <= 11 else (30 if _jalali_leap(year) else 29)
    if not 1 <= day <= days:
        return f'روز {label} در آن ماه وجود ندارد.'
    return ''


def normal_jalali_date(value: str) -> str:
    """yyyy/mm/dd with two-digit month and day (call only after jalali_date_error returned '')."""
    year, month, day = re.split(r'[/-]', latin_digits(value).strip())
    return f'{int(year):04d}/{int(month):02d}/{int(day):02d}'


def clean_person_fields(data: dict) -> list:
    errors = []
    if data.get('national_id'):
        data['national_id'] = re.sub(r'[\s\-]', '', latin_digits(data['national_id']))
        if not national_id_ok(data['national_id']):
            errors.append('کد ملی باید ۱۰ رقم و معتبر باشد.')
    for key, label in (('phone', 'mobile'), ('mobile', 'mobile'), ('landline', 'landline')):
        if data.get(key):
            value = re.sub(r'[\s\-()]', '', latin_digits(data[key]))
            value = re.sub(r'^(\+|00)98', '0', value)
            if re.fullmatch(r'9\d{9}', value):
                value = '0' + value
            data[key] = value
            if label == 'mobile' and not _MOBILE.fullmatch(value):
                errors.append(MOBILE_MESSAGE)
            if label == 'landline' and not _LANDLINE.fullmatch(value):
                errors.append(LANDLINE_MESSAGE)
    if data.get('birth_date'):
        value = latin_digits(data['birth_date']).replace('-', '/')
        match = re.fullmatch(r'(\d{4})/(\d{1,2})/(\d{1,2})', value)
        if match:
            value = f'{match[1]}/{int(match[2]):02d}/{int(match[3]):02d}'
        data['birth_date'] = value
        error = birth_date_error(value)
        if error:
            errors.append(error)
    for key in ('first_name', 'last_name', 'full_name', 'father_name'):
        if data.get(key):
            data[key] = re.sub(r'\s+', ' ', str(data[key])).strip()
            message = name_error(data[key])
            if message:
                errors.append(f'«{FIELD_LABELS[key]}»: {message}')
                break
    if data.get('student_number'):
        data['student_number'] = latin_digits(data['student_number'])
        if not _STUDENT_NO.fullmatch(data['student_number']):
            errors.append(STUDENT_NO_MESSAGE)
    for key in ('personnel_code', 'identifier'):
        if data.get(key):
            data[key] = latin_digits(data[key])
            if not _CODE.fullmatch(data[key]):
                errors.append(CODE_MESSAGE)
    for key in ('email', 'login_email'):
        if data.get(key):
            data[key] = latin_digits(data[key])
            message = email_error(data[key])
            if message:
                errors.append(message)
    if data.get('username'):
        data['username'] = latin_digits(data['username'])
        message = username_error(data['username'])
        if message:
            errors.append(message)
    return errors


# Format of personal fields, by POST name (user's requirement: a field only holds what fits it). Checked on every
# signed-in POST by middleware.PersonFieldLengthMiddleware, after the length caps; the browser twin is
# static/js/field-rules.js, which already refuses wrong keys as typed. Empty values pass (required-ness is the view's).
_FORMAT_FIELDS = {
    'national_id': 'national', 'national_code': 'national',
    'phone': 'mobile', 'mobile': 'mobile', 'phone_number': 'mobile', 'mobile_number': 'mobile', 'landline': 'landline',
    'birth_date': 'birth', 'entry_year': 'year', 'entrance_year': 'year',
    'first_name': 'name', 'last_name': 'name', 'full_name': 'name', 'father_name': 'name',
    'student_number': 'studentno', 'student_code': 'studentno',
    'personnel_code': 'code', 'employee_code': 'code', 'identifier': 'code',
    'email': 'email', 'login_email': 'email', 'notification_email': 'email',
    'username': 'username',
}

MOBILE_MESSAGE = 'شماره موبایل باید ۱۱ رقم و با ۰۹ شروع شود (پیش‌شماره ۰۹۰ تا ۰۹۴ یا ۰۹۹)، مثلاً ۰۹۱۲۳۴۵۶۷۸۹.'
LANDLINE_MESSAGE = 'تلفن ثابت ۱۱ رقم است و با کد استان شروع می‌شود، مثلاً ۰۲۱۸۸۷۷۶۶۵۵.'
STUDENT_NO_MESSAGE = 'شماره دانشجویی ۴ تا ۱۵ رقم است، مثلاً ۴۰۳۱۲۳۴۵۶.'
CODE_MESSAGE = 'کد پرسنلی ۳ تا ۲۰ نویسه است: رقم و حروف انگلیسی، «-» فقط میان آن‌ها، مثلاً ۱۴۰۵۱۱۲ یا TCH-1024.'


def _format_message(kind: str, raw: str) -> str:
    value = latin_digits(raw)
    if kind == 'national':
        return '' if national_id_ok(re.sub(r'[\s\-]', '', value)) else 'کد ملی باید ۱۰ رقم و معتبر باشد، مثلاً ۰۰۱۲۳۴۵۶۷۸.'
    if kind in ('mobile', 'landline'):
        value = re.sub(r'^(\+|00)98', '0', re.sub(r'[\s\-()]', '', value))
        if kind == 'mobile':
            if re.fullmatch(r'9\d{9}', value):
                value = '0' + value
            return '' if _MOBILE.fullmatch(value) else MOBILE_MESSAGE
        return '' if _LANDLINE.fullmatch(value) else LANDLINE_MESSAGE
    if kind == 'birth':
        return birth_date_error(value.replace('-', '/'))
    if kind == 'year':
        return '' if re.fullmatch(r'1[34]\d\d', value) else 'سال را ۴ رقمی و شمسی بنویسید، مثلاً ۱۴۰۳.'
    if kind == 'name':
        return name_error(value)
    if kind == 'studentno':
        return '' if _STUDENT_NO.fullmatch(value) else STUDENT_NO_MESSAGE
    if kind == 'code':
        return '' if _CODE.fullmatch(value) else CODE_MESSAGE
    if kind == 'email':
        return email_error(value)
    if kind == 'username':
        return username_error(value)
    return ''


# Where a value of each kind is stored: a wrong-format value that is already saved there is an old, unchanged value
# (seed codes «MQTEST-S01», data from before these rules) and is let through, so editing anything else on that account
# (photo, status …) still works. New or changed values must fit. Length caps (FIELD_MAX) have no such exception.
_STORED_IN = {
    'national': ("SELECT 1 FROM profiles WHERE national_id = %s LIMIT 1",),
    'mobile': ("SELECT 1 FROM profiles WHERE phone = %s LIMIT 1",),
    'name': ("SELECT 1 FROM profiles WHERE first_name = %s OR last_name = %s OR full_name = %s LIMIT 1",),
    'studentno': ("SELECT 1 FROM student_profiles WHERE student_number = %s LIMIT 1",
                  "SELECT 1 FROM profiles WHERE identifier = %s LIMIT 1"),
    'code': ("SELECT 1 FROM teacher_profiles WHERE personnel_code = %s LIMIT 1",
             "SELECT 1 FROM profiles WHERE identifier = %s LIMIT 1"),
    'email': ("SELECT 1 FROM profiles WHERE lower(email) = lower(%s) LIMIT 1",),
    'username': ("SELECT 1 FROM profiles WHERE username = %s LIMIT 1",),
    'landline': ("SELECT 1 FROM teacher_profiles WHERE landline = %s LIMIT 1",),
    'birth': ("SELECT 1 FROM profiles WHERE birth_date = %s LIMIT 1",),
}


def _already_stored(kind: str, value: str) -> bool:
    from django.db import connection

    for sql in _STORED_IN.get(kind, ()):
        try:
            with connection.cursor() as cursor:
                cursor.execute(sql, [value] * sql.count('%s'))
                if cursor.fetchone():
                    return True
        except Exception:  # no database (SimpleTestCase) or a failed query: check the format
            return False
    return False


def format_errors(post, skip=()) -> list:
    """Persian messages for every personal POST field whose value doesn't fit its format (an unchanged stored value
    passes). Pages that validate on their own form (middleware SELF_VALIDATING) call it with the fields they already
    check themselves in `skip`."""
    messages = []
    for name, kind in _FORMAT_FIELDS.items():
        if name in skip:
            continue
        for value in post.getlist(name) if hasattr(post, 'getlist') else [post.get(name)]:
            if value and str(value).strip():
                message = _format_message(kind, str(value).strip())
                if message and not _already_stored(kind, str(value).strip()):
                    messages.append(f'«{FIELD_LABELS.get(name, name)}»: {message}')
                    break
    return messages


def format_error(post) -> str:
    """Persian message for the first personal POST field whose value doesn't fit its format, else ''."""
    messages = format_errors(post)
    return messages[0] if messages else ''


def record_issues(record: dict) -> list:
    """(key, Persian message) for each value of an imported row (Excel bulk import) that is too long or in the wrong
    format: the same rules as the forms and PersonFieldLengthMiddleware. Numeric cells are tidied in place first (Excel
    stores 0012345678 as 12345678 and may add «.0»), so the stored value is the corrected one."""
    issues = []
    for key, value in record.items():
        if value in (None, '') or not isinstance(value, (str, int, float)):
            continue
        kind = _FORMAT_FIELDS.get(key)
        if kind in ('national', 'mobile', 'landline', 'studentno', 'year', 'code'):
            value = latin_digits(value)
            if re.fullmatch(r'\d+\.0+', value):
                value = value.split('.')[0]
            if kind == 'national' and re.fullmatch(r'\d{8,9}', value):
                value = value.zfill(10)
            if kind == 'mobile' and re.fullmatch(r'9\d{9}', value):
                value = '0' + value
            record[key] = value
        message = too_long_error({key: str(value)}) or format_error({key: str(value)})
        if message:
            issues.append((key, message))
    return issues


class LatinPasswordValidator:
    """New passwords hold only English letters, digits and ASCII symbols — no spaces, no Persian letters (user's
    requirement: a box only takes what fits it; a password typed with the Persian keyboard layout can't be typed the
    same way on the sign-in page). Listed in settings.AUTH_PASSWORD_VALIDATORS; the browser twin is the `pwnew` kind
    of static/js/field-rules.js, which refuses those keys as typed. Sign-in itself is not limited here."""

    message = 'رمز عبور فقط حروف انگلیسی، رقم و نماد دارد؛ فاصله و حروف فارسی مجاز نیست. زبان صفحه‌کلید را انگلیسی کنید.'

    def validate(self, password, user=None):
        from django.core.exceptions import ValidationError

        if password and not re.fullmatch(r'[!-~]+', password):
            raise ValidationError(self.message, code='password_not_latin')

    def get_help_text(self):
        return 'فقط حروف انگلیسی، رقم و نماد (بدون فاصله).'


# The password standard (user's requirement: «........» or «////////» must not pass): at least 8 characters with an
# uppercase and a lowercase English letter, a digit and a symbol. Same list, same order, in static/js/field-rules.js
# (PW_RULES), which shows it as a live checklist under every new-password box.
PASSWORD_MIN_LENGTH = 8
PASSWORD_RULES = (
    ('length', '۸ نویسه یا بیشتر', lambda p: len(p) >= PASSWORD_MIN_LENGTH),
    ('upper', 'حرف بزرگ انگلیسی (A-Z)', lambda p: re.search(r'[A-Z]', p) is not None),
    ('lower', 'حرف کوچک انگلیسی (a-z)', lambda p: re.search(r'[a-z]', p) is not None),
    ('digit', 'رقم', lambda p: re.search(r'[0-9]', p) is not None),
    ('symbol', 'نماد مثل ! @ # $', lambda p: re.search(r'[!-/:-@\[-`{-~]', p) is not None),
)


# «سیاست گذرواژه» (admin › تنظیمات امنیتی, system_settings.password_policy): which rules a new password must meet.
# قوی = the full standard above (default); متوسط = 8+ with an English letter and a digit; ضعیف = 6+ characters.
# Browser twin: PW_POLICIES in static/js/field-rules.js (the policy reaches it as <html data-mq-pw-policy>).
PASSWORD_POLICY_RULES = {
    'strong': PASSWORD_RULES,
    'medium': (
        PASSWORD_RULES[0],
        ('letter', 'حرف انگلیسی', lambda p: re.search(r'[A-Za-z]', p) is not None),
        PASSWORD_RULES[3],
    ),
    'weak': (('length6', '۶ نویسه یا بیشتر', lambda p: len(p) >= 6),),
}


def current_password_policy() -> str:
    try:
        from .system_settings import password_policy
        policy = password_policy()
    except Exception:  # no settings table yet: the full standard
        policy = 'strong'
    return policy if policy in PASSWORD_POLICY_RULES else 'strong'


def password_missing(password: str, policy: str | None = None) -> list:
    """Labels of the rules of the password policy this password doesn't meet yet (empty = it meets it)."""
    password = password or ''
    rules = PASSWORD_POLICY_RULES.get(policy or current_password_policy(), PASSWORD_RULES)
    return [label for _key, label, ok in rules if not ok(password)]


class PasswordStrengthValidator:
    """Enforces PASSWORD_RULES for every new password (sign-up, change, reset, admin-set). Listed in
    settings.AUTH_PASSWORD_VALIDATORS in place of Django's length / all-digits validators."""

    def validate(self, password, user=None):
        from django.core.exceptions import ValidationError

        missing = password_missing(password)
        if missing:
            raise ValidationError('رمز عبور به اندازه کافی محکم نیست؛ این موارد را کم دارد: ' + '، '.join(missing) + '.',
                                  code='password_too_weak')

    def get_help_text(self):
        return {'medium': 'حداقل ۸ نویسه، با حرف انگلیسی و رقم.', 'weak': 'حداقل ۶ نویسه.'}.get(
            current_password_policy(), 'حداقل ۸ نویسه، با حرف بزرگ و کوچک انگلیسی، رقم و نماد.')
