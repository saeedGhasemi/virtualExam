import json
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
    jy, jm, jd = _gregorian_to_jalali(value.year, value.month, value.day)
    date_part = f'{jy:04d}/{jm:02d}/{jd:02d}'
    if hasattr(value, 'hour'):
        return fa_digits(f'{date_part} - {value.hour:02d}:{value.minute:02d}')
    return fa_digits(date_part)


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
def jalali_today():
    today = timezone.localdate()
    jy, jm, jd = _gregorian_to_jalali(today.year, today.month, today.day)
    return fa_digits(f'{jy:04d}/{jm:02d}/{jd:02d}')
