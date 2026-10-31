"""Student practice exams («آزمون آزمایشی»): exams the wizard marks exam_mode='practice'.

They reach students through the same access rule as course exams (``_sx_accessible_exams``), but have their
own section: a student may take one again (up to the exam's «تعداد تلاش مجاز»), picks a tutorial or simulation
mode for each attempt, and the result never reaches their course results.
"""
import uuid

from django.db import connection, transaction
from django.utils import timezone

from .views import PRACTICE_EXAM_MODE, _sx_exam_row, erd_execute, erd_has_column, erd_row

# mode -> (title, description), in the order the preparation page offers them
PRACTICE_MODES = {
    'tutorial': ('حالت آموزشی (بازخورد فوری)',
                 'پس از پاسخ به هر سؤال، پاسخ صحیح و توضیح آموزشی نمایش داده می‌شود.'),
    'simulation': ('حالت شبیه‌ساز (بازخورد پس از پایان)',
                   'تمام سؤالات به صورت یکجا نمایش داده می‌شود و بازخورد و تحلیل نتایج پس از اتمام آزمون ارائه می‌شود.'),
}
DEFAULT_PRACTICE_MODE = 'tutorial'


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

