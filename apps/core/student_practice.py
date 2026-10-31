"""Student practice exams («آزمون آزمایشی»): exams the wizard marks exam_mode='practice'.

They reach students through the same access rule as course exams (``_sx_accessible_exams``), but have their
own section: a student may take one again (up to the exam's «تعداد تلاش مجاز»), picks a tutorial or simulation
mode for each attempt, and the result never reaches their course results.
"""
import re
import uuid

from django.core.paginator import Paginator
from django.db import connection, transaction
from django.urls import reverse
from django.utils import timezone

from .student_dashboard import _course_icon
from .views import (
    PRACTICE_EXAM_MODE, _jalali_long_date, _sx_accessible_exams, _sx_dt, _sx_exam_mode_sql, _sx_exam_row,
    _sx_percent, erd_execute, erd_has_column, erd_row, erd_rows,
)

# mode -> (title, description), in the order the preparation page offers them
PRACTICE_MODES = {
    'tutorial': ('حالت آموزشی (بازخورد فوری)',
                 'پس از پاسخ به هر سؤال، پاسخ صحیح و توضیح آموزشی نمایش داده می‌شود.'),
    'simulation': ('حالت شبیه‌ساز (بازخورد پس از پایان)',
                   'مانند آزمون اصلی پاسخ می‌دهید؛ پاسخ صحیح، توضیح و تحلیل نتایج پس از پایان آزمون در کارنامه نمایش داده می‌شود.'),
}
DEFAULT_PRACTICE_MODE = 'tutorial'
CARD_PAGE_SIZE = 9
RECENT_ATTEMPTS_SIZE = 10

# attempt status -> (label, tone)
ATTEMPT_STATES = {
    'in_progress': ('در حال انجام', 'blue'),
    'pending': ('در انتظار تصحیح', 'orange'),
    'graded': ('پایان یافته', 'green'),
    'expired': ('منقضی شده', 'gray'),
}


def practice_exam(exam_id, student_id):
    """The practice exam when the student may see it, else None (callers turn None into a 404)."""
    exam = _sx_exam_row(exam_id, student_id)
    if not exam or exam.get('exam_mode') != PRACTICE_EXAM_MODE:
        return None
    return exam


def attempt_limit(exam) -> int | None:
    """The exam's «تعداد تلاش مجاز»; None means unlimited (no value or 0)."""
    try:
        limit = int(exam.get('max_attempts') or 0)
    except (TypeError, ValueError):
        return None
    return limit if limit > 0 else None


def attempts_used(exam_id, student_id) -> int:
    row = erd_row('SELECT COUNT(*) AS count FROM exam_attempts WHERE exam_id = %s AND student_id = %s', [exam_id, student_id])
    return int(row['count'] or 0) if row else 0


def open_attempt(exam_id, student_id):
    """The student's unfinished attempt on the exam, which is resumed instead of starting another one."""
    mode = 'practice_mode' if erd_has_column('exam_attempts', 'practice_mode') else 'NULL AS practice_mode'
    return erd_row(
        f"""
        SELECT id, started_at, {mode}
        FROM exam_attempts
        WHERE exam_id = %s AND student_id = %s AND submitted_at IS NULL AND status = 'in_progress'
        ORDER BY started_at DESC NULLS LAST
        LIMIT 1
        """,
        [exam_id, student_id],
    )


def start_refusal(exam, student_id) -> str:
    """Why a new attempt may not start now, or '' when it may. An unfinished attempt is resumed, never refused."""
    if exam['starts_at'] > timezone.now():
        return 'این آزمون آزمایشی هنوز شروع نشده است.'
    limit = attempt_limit(exam)
    if limit is not None and attempts_used(exam['id'], student_id) >= limit:
        return 'تعداد دفعات مجاز شرکت در این آزمون آزمایشی به پایان رسیده است.'
    if not exam['question_count']:
        return 'این آزمون آزمایشی هنوز سؤالی ندارد.'
    return ''


def start_practice_attempt(exam, student_id, mode) -> tuple:
    """(attempt_id, '') for the attempt to open, or (None, reason) when a new one may not start.

    Runs under a lock on the student's profile row so two quick clicks cannot both pass the attempt limit."""
    mode = mode if mode in PRACTICE_MODES else DEFAULT_PRACTICE_MODE
    with transaction.atomic():
        if connection.vendor == 'postgresql':
            erd_row('SELECT id FROM profiles WHERE id = %s FOR UPDATE', [student_id])
        resumed = open_attempt(exam['id'], student_id)
        if resumed:
            return resumed['id'], ''
        refusal = start_refusal(exam, student_id)
        if refusal:
            return None, refusal
        attempt_id = str(uuid.uuid4())
        columns = ['id', 'exam_id', 'student_id', 'started_at', 'status', 'is_graded']
        values = [attempt_id, exam['id'], student_id, timezone.now(), 'in_progress', False]
        if erd_has_column('exam_attempts', 'practice_mode'):
            columns.append('practice_mode')
            values.append(mode)
        erd_execute(
            f"INSERT INTO exam_attempts ({', '.join(columns)}) VALUES ({', '.join(['%s'] * len(values))})",
            values,
        )
    return attempt_id, ''


def exam_tags(exam) -> list:
    """The wizard's comma-separated «برچسب‌ها» of the exam."""
    return [tag.strip() for tag in re.split('[,،]', exam.get('tags') or '') if tag.strip()]


def _attempt_counts(student_id) -> dict:
    """exam_id -> how many attempts the student has on each practice exam."""
    return {
        str(row['exam_id']): int(row['used'] or 0)
        for row in erd_rows(
            f"""
            SELECT ea.exam_id, COUNT(*) AS used
            FROM exam_attempts ea JOIN exams e ON e.id = ea.exam_id
            WHERE ea.student_id = %s AND {_sx_exam_mode_sql()} = '{PRACTICE_EXAM_MODE}'
            GROUP BY ea.exam_id
            """,
            [student_id],
        )
    }


def _open_attempts(student_id) -> dict:
    """exam_id -> the student's unfinished practice attempt id."""
    return {
        str(row['exam_id']): row['id']
        for row in erd_rows(
            f"""
            SELECT ea.exam_id, ea.id
            FROM exam_attempts ea JOIN exams e ON e.id = ea.exam_id
            WHERE ea.student_id = %s AND ea.submitted_at IS NULL AND ea.status = 'in_progress'
              AND {_sx_exam_mode_sql()} = '{PRACTICE_EXAM_MODE}'
            ORDER BY ea.started_at ASC NULLS FIRST
            """,
            [student_id],
        )
    }


def _card_action(exam, used, open_attempt_id, now) -> dict:
    """The card's button: continue, start, or a disabled reason (never a link that would only be refused)."""
    if open_attempt_id:
        return {'label': 'ادامه تمرین', 'url': reverse('core:student_attempt', args=[open_attempt_id])}
    if exam['starts_at'] > now:
        return {'label': f"از {_jalali_long_date(exam['starts_at'], with_weekday=False)}", 'url': ''}
    if not exam['question_count']:
        return {'label': 'هنوز سؤالی ندارد', 'url': ''}
    limit = attempt_limit(exam)
    if limit is not None and used >= limit:
        return {'label': 'سقف تلاش تکمیل شد', 'url': ''}
    return {'label': 'تمرین دوباره' if used else 'شروع تمرین',
            'url': reverse('core:student_practice_detail', args=[exam['id']])}


def practice_cards(student_id) -> list:
    now = timezone.now()
    counts, open_ids = _attempt_counts(student_id), _open_attempts(student_id)
    cards = []
    for exam in _sx_accessible_exams(student_id, practice=True):
        exam_id = str(exam['id'])
        used = counts.get(exam_id, 0)
        cards.append({
            'id': exam_id,
            'title': exam['title'],
            'description': exam['description'],
            'course': exam['course_title'],
            'course_id': str(exam['course_id']) if exam.get('course_id') else '',
            'course_icon': _course_icon(exam['course_title']),
            'question_count': exam['question_count'],
            'duration': exam['duration_minutes'],
            'tags': exam_tags(exam),
            'used': used,
            'limit': attempt_limit(exam),
            'action': _card_action(exam, used, open_ids.get(exam_id), now),
        })
    return cards


def _percent_tone(percent) -> str:
    return 'green' if percent >= 70 else 'blue' if percent >= 50 else 'red'


def recent_attempts(student_id, limit=RECENT_ATTEMPTS_SIZE) -> list:
    """The student's latest practice attempts, newest first, with how long each took and its score."""
    rows = erd_rows(
        f"""
        SELECT ea.id, ea.started_at, ea.submitted_at, ea.status, ea.score, ea.max_score, ea.is_graded,
               e.title, COALESCE(c.title, 'درس') AS course_title,
               (SELECT COUNT(*) FROM exam_questions eq WHERE eq.exam_id = e.id) AS question_count
        FROM exam_attempts ea
        JOIN exams e ON e.id = ea.exam_id
        LEFT JOIN courses c ON c.id = e.course_id
        WHERE ea.student_id = %s AND {_sx_exam_mode_sql()} = '{PRACTICE_EXAM_MODE}'
        ORDER BY ea.started_at DESC NULLS LAST
        LIMIT %s
        """,
        [student_id, limit],
    )
    items = []
    for row in rows:
        started, submitted = _sx_dt(row.get('started_at')), _sx_dt(row.get('submitted_at'))
        graded = bool(row.get('is_graded')) and row.get('score') is not None
        if submitted:
            state = 'graded' if graded else 'pending'
        else:
            state = 'expired' if row.get('status') == 'expired' else 'in_progress'
        label, tone = ATTEMPT_STATES[state]
        percent = _sx_percent(row.get('score'), row.get('max_score')) if graded else None
        if state == 'in_progress':
            action = {'label': 'ادامه تمرین', 'url': reverse('core:student_attempt', args=[row['id']])}
        elif submitted:
            action = {'label': 'مشاهده نتیجه', 'url': reverse('core:student_result_detail', args=[row['id']])}
        else:
            action = None
        items.append({
            'id': row['id'],
            'date_label': _jalali_long_date(started, with_weekday=False) if started else '-',
            'time_label': timezone.localtime(started).strftime('%H:%M') if started else '',
            'title': row['title'],
            'course': row['course_title'],
            'question_count': int(row.get('question_count') or 0),
            'minutes': max(1, round((submitted - started).total_seconds() / 60)) if submitted and started else None,
            'percent': percent,
            'percent_tone': _percent_tone(percent) if percent is not None else '',
            'state_label': label,
            'state_tone': tone,
            'action': action,
        })
    return items


def _uses_microphone(exam_id) -> bool:
    if not erd_has_column('exams', 'mic_monitoring'):
        return False
    row = erd_row('SELECT mic_monitoring FROM exams WHERE id = %s', [exam_id])
    return bool(row and row.get('mic_monitoring'))


def practice_rules(exam, limit) -> list:
    """The rules that actually apply to this practice attempt, from the exam's own settings."""
    rules = [
        f"زمان پاسخ‌گویی {exam['duration_minutes']} دقیقه است و با شروع آزمون آغاز می‌شود؛ با پایان زمان، پاسخ‌های ذخیره‌شده ارسال می‌شوند.",
        'پاسخ هر سؤال هنگام رفتن به سؤال بعد یا قبل ذخیره می‌شود و می‌توانید پیش از تحویل نهایی آن را تغییر دهید.',
        'در حالت آموزشی، پس از دیدن بازخورد یک سؤال، پاسخ آن سؤال دیگر قابل تغییر نیست.',
        'نمره‌ی آزمون آزمایشی در کارنامه و معدل درسی شما محاسبه نمی‌شود.',
    ]
    if limit is None:
        rules.append('محدودیتی برای تعداد دفعات شرکت در این آزمون وجود ندارد.')
    else:
        rules.append(f'حداکثر {limit} بار می‌توانید در این آزمون شرکت کنید؛ هر شروع یک بار حساب می‌شود.')
    return rules


def practice_detail_context(exam, student_id) -> dict:
    """Context for the preparation page: exam facts, the modes, readiness checks and whether it may start."""
    limit = attempt_limit(exam)
    resumed = open_attempt(exam['id'], student_id)
    return {
        'exam': exam,
        'used': attempts_used(exam['id'], student_id),
        'limit': limit,
        'modes': [{'key': key, 'title': title, 'description': text} for key, (title, text) in PRACTICE_MODES.items()],
        'default_mode': DEFAULT_PRACTICE_MODE,
        'open_attempt': resumed,
        'open_mode_title': PRACTICE_MODES.get(resumed.get('practice_mode') or DEFAULT_PRACTICE_MODE, PRACTICE_MODES[DEFAULT_PRACTICE_MODE])[0] if resumed else '',
        'refusal': '' if resumed else start_refusal(exam, student_id),
        'uses_microphone': _uses_microphone(exam['id']),
        'rules': practice_rules(exam, limit),
    }


def practice_list_context(request, student_id) -> dict:
    """Context for the practice exams page: filtered, paginated exam cards and the latest attempts."""
    cards = practice_cards(student_id)
    query = request.GET.get('q', '').strip()
    course = request.GET.get('course', '').strip()
    tag = request.GET.get('tag', '').strip()
    filtered = cards
    if query:
        needle = query.casefold()
        filtered = [card for card in filtered if needle in card['title'].casefold() or needle in card['course'].casefold()]
    if course:
        filtered = [card for card in filtered if card['course_id'] == course]
    if tag:
        filtered = [card for card in filtered if tag in card['tags']]
    return {
        'page_obj': Paginator(filtered, CARD_PAGE_SIZE).get_page(request.GET.get('page')),
        'total': len(filtered),
        'has_exams': bool(cards),
        'query': query,
        'course': course,
        'tag': tag,
        'courses': sorted({(card['course_id'], card['course']) for card in cards if card['course_id']}, key=lambda item: item[1]),
        'tags': sorted({item for card in cards for item in card['tags']}),
        'recent_attempts': recent_attempts(student_id),
    }

