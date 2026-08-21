from django import template
from django.utils import timezone

register = template.Library()

PERSIAN_DIGITS = str.maketrans('0123456789', '۰۱۲۳۴۵۶۷۸۹')


@register.filter
def fa_digits(value):
    if value is None:
        return ''
    return str(value).translate(PERSIAN_DIGITS)


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


@register.simple_tag
def jalali_today():
    today = timezone.localdate()
    jy, jm, jd = _gregorian_to_jalali(today.year, today.month, today.day)
    return fa_digits(f'{jy:04d}/{jm:02d}/{jd:02d}')
