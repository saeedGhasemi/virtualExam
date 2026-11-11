import contextvars
import json
import re
from datetime import datetime

from django import template
from django.http import QueryDict
from django.utils import timezone

register = template.Library()

PERSIAN_DIGITS = str.maketrans('0123456789', '۰۱۲۳۴۵۶۷۸۹')


@register.filter
def fa_digits(value):
    if value is None:
        return ''
    return str(value).translate(PERSIAN_DIGITS)


_RTL_CHARS = re.compile(r'[\u0590-\u065f\u066a-\u06ef\u06fa-\u08ff\ufb1d-\ufdff\ufe70-\ufeff]')  # letters only: Arabic-Indic / Persian digits are neutral like 0-9
_LTR_CHARS = re.compile(r'[A-Za-z\u00c0-\u024f\u0370-\u03ff\u0400-\u04ff]')


@register.filter
def text_dir(value, default='rtl'):
    """'rtl' or 'ltr' from the first letter of the text (like dir="auto"), the default when it has no letters.
    Used so an English question / option lays out left-to-right inside the Persian page."""
    text = str(value or '')
    rtl, ltr = _RTL_CHARS.search(text), _LTR_CHARS.search(text)
    if rtl and ltr:
        return 'rtl' if rtl.start() < ltr.start() else 'ltr'
    if ltr:
        return 'ltr'
    if rtl:
        return 'rtl'
    return default


@register.filter
def exam_type_label(kind):
    """Question-type label exactly as the student exam page shows it (one source: _sx_type_label)."""
    from apps.core.views import _sx_type_label  # imported on use: keeps loading this tag library independent of the views module

    return _sx_type_label(kind)


@register.filter
def json_dumps(value):
    """JSON for an HTML attribute value; Django's autoescape handles the quoting."""
    return json.dumps(value, ensure_ascii=False)


@register.filter
def get_item(mapping, key):
    if not mapping:
        return ''
    return mapping.get(key, '')


def _gregorian_to_jalali(year, month, day):
    gregorian_days = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    if year > 1600:
        jy = 979
        year -= 1600
    else:
        jy = 0
        year -= 621
    gy2 = year + 1 if month > 2 else year
    days = (
        365 * year
        + ((gy2 + 3) // 4)
        - ((gy2 + 99) // 100)
        + ((gy2 + 399) // 400)
        - 80
        + day
        + gregorian_days[month - 1]
    )
    jy += 33 * (days // 12053)
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        jm = 1 + (days // 31)
        jd = 1 + (days % 31)
    else:
        jm = 7 + ((days - 186) // 30)
        jd = 1 + ((days - 186) % 30)
    return jy, jm, jd


def _jalali_to_gregorian(jy, jm, jd):
    """The Gregorian date of a Jalali date: Farvardin 1st found with _gregorian_to_jalali, plus the day offset."""
    from datetime import date, timedelta

    nowruz = next(day for day in (date(jy + 621, 3, d) for d in range(19, 23)) if _gregorian_to_jalali(day.year, day.month, day.day) == (jy, 1, 1))
    offset = (jm - 1) * 31 if jm <= 7 else 186 + (jm - 7) * 30
    return nowruz + timedelta(days=offset + jd - 1)


def _jalali_month_length(jy, jm):
    if jm <= 6:
        return 31
    if jm <= 11:
        return 30
    return (_jalali_to_gregorian(jy + 1, 1, 1) - _jalali_to_gregorian(jy, 12, 1)).days  # Esfand: 29, or 30 in a leap year


@register.filter
def exam_code(exam_id):
    """«کد آزمون» of an exam id, as students type it on the home page (MQ-1A2B3C)."""
    from apps.core.views import exam_access_code

    return exam_access_code(exam_id) if exam_id else ''


# «تقویم تاریخ» of a teacher who chose «میلادی»: set for the request by erd_role_required, read by every date filter.
CALENDAR = contextvars.ContextVar('calendar', default='jalali')
GREGORIAN_MONTHS = ('ژانویه', 'فوریه', 'مارس', 'آوریل', 'مه', 'ژوئن', 'ژوئیه', 'اوت', 'سپتامبر', 'اکتبر', 'نوامبر', 'دسامبر')


def display_date_parts(year, month, day):
    """(year, month, day, month names) of a Gregorian day in the calendar dates are shown in for this request."""
    if CALENDAR.get() == 'gregorian':
        return year, month, day, GREGORIAN_MONTHS
    jy, jm, jd = _gregorian_to_jalali(year, month, day)
    return jy, jm, jd, JALALI_MONTHS


@register.filter
def to_jalali(value):
    """Format a date/datetime (or ISO string from a raw SQLite cursor) as a Jalali string."""
    if not value:
        return ''
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return value
    if getattr(value, 'tzinfo', None) is not None and value.utcoffset() is not None:
        value = timezone.localtime(value)  # an aware moment is shown in the site's time zone (Tehran), not UTC
    jy, jm, jd, _months = display_date_parts(value.year, value.month, value.day)
    date_part = f'{jy:04d}/{jm:02d}/{jd:02d}'
    if hasattr(value, 'hour'):
        return fa_digits(f'{date_part} - {value.hour:02d}:{value.minute:02d}')
    return fa_digits(date_part)


JALALI_MONTHS = ('فروردین', 'اردیبهشت', 'خرداد', 'تیر', 'مرداد', 'شهریور', 'مهر', 'آبان', 'آذر', 'دی', 'بهمن', 'اسفند')
JALALI_WEEKDAYS = ('دوشنبه', 'سه‌شنبه', 'چهارشنبه', 'پنجشنبه', 'جمعه', 'شنبه', 'یکشنبه')  # by date.weekday()


def _jalali_moment(value):
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return None
    if getattr(value, 'tzinfo', None) is not None and value.utcoffset() is not None:
        value = timezone.localtime(value)
    return value if hasattr(value, 'year') else None


@register.filter
def jalali_date(value):
    """«۱۴۰۵/۰۸/۱۲»: the Jalali day only (Tehran time for an aware moment)."""
    moment = _jalali_moment(value) if value else None
    if not moment:
        return value or ''
    jy, jm, jd, _months = display_date_parts(moment.year, moment.month, moment.day)
    return fa_digits(f'{jy:04d}/{jm:02d}/{jd:02d}')


@register.filter
def jalali_long(value):
    """«سه‌شنبه، ۱۲ آبان ۱۴۰۵»."""
    moment = _jalali_moment(value) if value else None
    if not moment:
        return value or ''
    jy, jm, jd, months = display_date_parts(moment.year, moment.month, moment.day)
    return fa_digits(f'{JALALI_WEEKDAYS[moment.weekday()]}، {jd} {months[jm - 1]} {jy}')


@register.simple_tag(takes_context=True)
def query_url(context, **overrides):
    request = context.get('request')
    params = request.GET.copy() if request else QueryDict(mutable=True)
    for key, value in overrides.items():
        if value in (None, ''):
            params.pop(key, None)
        else:
            params[key] = value
    query_string = params.urlencode()
    return f'?{query_string}' if query_string else '?'


@register.simple_tag
def jalali_year():
    """The current Jalali year at Tehran time («۱۴۰۵»)."""
    today = timezone.localdate()
    return fa_digits(_gregorian_to_jalali(today.year, today.month, today.day)[0])


@register.simple_tag
def jalali_today():
    today = timezone.localdate()
    jy, jm, jd = _gregorian_to_jalali(today.year, today.month, today.day)
    return fa_digits(f'{jy:04d}/{jm:02d}/{jd:02d}')
