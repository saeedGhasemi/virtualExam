"""Test data for trying every part of the site by hand: 15 teachers, 15 students, 15 questions, 15 exams.

Everything it makes is marked so it can be found and removed:
  * usernames start with `mqtest_` (password of every account: Test@12345), e-mails end with @mqtest.local
  * names, exam titles, question texts, course / group / unit names carry «[آزمایشی]»
  * codes (course, group, org unit, personnel / student numbers) start with `MQTEST-`; question tags hold `mqtest`
  * question media files are `media/question-media/mqtest-*`

    python manage.py seed_test_data           # (re)create: removes the earlier test data first
    python manage.py seed_test_data --purge   # remove all test data, and whatever was made with these accounts
"""
import io
import json
import math
import random
import struct
import uuid
import wave
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand
from django.db import IntegrityError, connection, transaction
from django.http import QueryDict
from django.utils import timezone

MARK = '[آزمایشی]'
PREFIX = 'mqtest_'
CODE = 'MQTEST'
TAG = 'mqtest'
PASSWORD = 'Test@12345'
EMAIL_DOMAIN = 'mqtest.local'
MEDIA_PREFIX = 'question-media/mqtest-'
NS = uuid.UUID('5b7f3a52-6a3e-4f43-9d1c-6d7e51e2a001')


def sid(name):
    return str(uuid.uuid5(NS, name))


# ---------------------------------------------------------------- people
# (username suffix, first, last, gender, profile status, approval/academic status, extras, note shown in the summary)
TEACHERS = [
    ('t01', 'مریم', 'احمدی', 'female', 'active', 'approved', {'rank': 'دانشیار', 'bio': 'استاد اصلی داده‌های آزمایشی؛ بیشتر سؤال‌ها و آزمون‌ها مال اوست.'}, 'فعال، تأییدشده؛ صاحب سؤال‌ها و بیشتر آزمون‌ها'),
    ('t02', 'رضا', 'کریمی', 'male', 'active', 'approved', {'rank': 'استادیار'}, 'فعال؛ «همکار تصحیح» آزمون‌های تشریحی، مدرس گروه ۳'),
    ('t03', 'زهرا', 'حسینی', 'female', 'active', 'approved', {'rank': 'استاد'}, 'فعال؛ مدرس درس دوم و صاحب آزمون بایگانی‌شده'),
    ('t04', 'علی', 'موسوی', 'male', 'active', 'approved', {'rank': 'مربی'}, 'فعال ولی بدون درس/گروه/سؤال (حالت‌های خالی)'),
    ('t05', 'نرگس', 'رضایی', 'female', 'pending', 'pending', {}, 'ثبت‌نام‌شده، در انتظار تأیید'),
    ('t06', 'حمید', 'جعفری', 'male', 'rejected', 'rejected', {}, 'درخواست همکاری رد شده'),
    ('t07', 'لیلا', 'صادقی', 'female', 'inactive', 'approved', {}, 'غیرفعال'),
    ('t08', 'مهدی', 'نوری', 'male', 'blocked', 'approved', {}, 'مسدود'),
    ('t09', 'سمیرا', 'قاسمی', 'female', 'active', 'approved', {'must_change': True}, 'باید در اولین ورود رمز را عوض کند'),
    ('t10', 'امیر', 'یوسفی', 'male', 'active', 'approved', {'can_design': False}, 'فعال ولی اجازه‌ی طراحی آزمون ندارد'),
    ('t11', 'فاطمه', 'باقری', 'female', 'active', 'approved', {'change_request': True}, 'درخواست تغییر مشخصات در انتظار بررسی'),
    ('t12', 'سعید', 'مرادی', 'male', 'active', 'approved', {'deletion_request': True}, 'درخواست حذف حساب در انتظار بررسی'),
    ('t13', 'الهام', 'کاظمی', 'female', 'inactive', 'approved', {'deleted': True}, 'حذف‌شده (حذف نرم)'),
    ('t14', 'بهرام', 'شریفی', 'male', 'active', 'approved', {'rank': 'حق‌التدریس', 'cooperation': 'حق‌التدریس', 'bio': 'ناظر آزمون پایان‌ترم.'}, 'فعال، حق‌التدریس؛ «ناظر» یک آزمون'),
    ('t15', 'شیما', 'اکبری', 'female', 'active', 'approved', {'never_logged_in': True}, 'فعال ولی هرگز وارد نشده'),
]

STUDENTS = [
    ('s01', 'آرش', 'محمدی', 'male', 'active', 'active', {'skill': 0.9}, 'فعال، عضو دو گروه، چند نتیجه‌ی منتشرشده + اعلان'),
    ('s02', 'نیلوفر', 'عباسی', 'female', 'active', 'active', {'skill': 0.7}, 'فعال، پاسخ تشریحی در انتظار تصحیح'),
    ('s03', 'کیان', 'رحیمی', 'male', 'active', 'active', {'skill': 0.6}, 'فعال، الان وسط آزمون در حال برگزاری است'),
    ('s04', 'یاسمن', 'نجفی', 'female', 'active', 'active', {'skill': 1.0}, 'فعال، نمره‌ی کامل + اعتراض باز'),
    ('s05', 'پویا', 'زارعی', 'male', 'active', 'active', {'skill': 0.25}, 'فعال، نمره‌ی مردودی + اعتراض ردشده'),
    ('s06', 'ترانه', 'سلیمانی', 'female', 'active', 'leave', {'skill': 0.5}, 'مرخصی تحصیلی؛ یک تلاش منقضی‌شده'),
    ('s07', 'بردیا', 'حیدری', 'male', 'active', 'graduated', {'skill': 0.8}, 'فارغ‌التحصیل'),
    ('s08', 'مهسا', 'ملکی', 'female', 'active', 'inactive', {'skill': 0.5}, 'وضعیت تحصیلی غیرفعال'),
    ('s09', 'سینا', 'طاهری', 'male', 'pending', 'active', {'skill': 0.5}, 'حساب در انتظار تأیید'),
    ('s10', 'رویا', 'فرهادی', 'female', 'blocked', 'active', {'skill': 0.5}, 'حساب مسدود'),
    ('s11', 'امید', 'قربانی', 'male', 'active', 'active', {'skill': 0.55, 'must_change': True}, 'باید در اولین ورود رمز را عوض کند'),
    ('s12', 'هستی', 'جمالی', 'female', 'active', 'active', {'skill': 0.5}, 'عضو هیچ گروهی نیست (بدون آزمون)'),
    ('s13', 'دانیال', 'نصیری', 'male', 'active', 'active', {'skill': 0.65}, 'از یک آزمون گروهش مستثنا شده'),
    ('s14', 'سارا', 'پاکزاد', 'female', 'active', 'active', {'skill': 0.75, 'deletion_request': True}, 'آزمون انفرادی (بدون گروه) + درخواست حذف حساب'),
    ('s15', 'محسن', 'وکیلی', 'male', 'inactive', 'inactive', {'skill': 0.5, 'deleted': True}, 'حذف‌شده (حذف نرم)'),
]


# ---------------------------------------------------------------- media (generated, no external files)
def _wav_tone(seconds=3, rate=8000):
    buffer = io.BytesIO()
    with wave.open(buffer, 'wb') as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        frames = b''.join(
            struct.pack('<h', int(9000 * math.sin(2 * math.pi * (440 if i < rate * seconds / 2 else 660) * i / rate)))
            for i in range(rate * seconds)
        )
        out.writeframes(frames)
    return buffer.getvalue()


def _store_media(name, data):
    path = f'{MEDIA_PREFIX}{name}'
    if default_storage.exists(path):
        default_storage.delete(path)
    saved = default_storage.save(path, ContentFile(data))
    return f'{settings.MEDIA_URL}{saved}'


# ---------------------------------------------------------------- questions (builder POST fields)
def _post(fields):
    post = QueryDict(mutable=True)
    for name, value in fields.items():
        post.setlist(name, value if isinstance(value, list) else [value])
    return post


def question_posts(course1, course2, image_url, audio_url):
    """(key, builder POST fields, state) for the 15 questions; state: published / draft / archived / shared."""
    base = {'structure': 'independent', 'is_published': '1', 'tags': f'{TAG}, نمونه', 'suggested_time_seconds': '120'}

    def q(text, kind, course=course1, difficulty='medium', points='1', **extra):
        fields = dict(base, type=kind, text=f'{MARK} {text}', course_id=course, difficulty=difficulty, default_points=points)
        fields.update(extra)
        return fields

    return [
        ('q01', q('پایتخت ایران کدام شهر است؟', 'single', difficulty='easy', subject='جغرافیا',
                  option_text=['تبریز', 'تهران', 'شیراز', 'مشهد'], correct_options=['2'],
                  feedback_text='تهران از سال ۱۱۶۵ خورشیدی پایتخت ایران است.'), 'published'),
        ('q02', q('کدام اعداد اول هستند؟ (نمره‌ی جزئی دارد)', 'multi', points='2',
                  option_text=['2', '4', '5', '9', '11'], correct_options=['1', '3', '5'],
                  scoring_mode='partial', partial_credit='1', min_correct='1', max_correct='0'), 'published'),
        ('q03', q('آب در فشار یک اتمسفر در ۱۰۰ درجه‌ی سانتی‌گراد می‌جوشد. (سؤال اشتراکی)', 'true_false', difficulty='easy',
                  option_text=['درست', 'نادرست'], correct_options=['1']), 'shared'),
        ('q04', q('فرمول شیمیایی آب چیست؟ (چند پاسخ قابل قبول)', 'short_answer',
                  accepted_answer=['H2O', 'اچ‌تواو'], accepted_points_1='100', accepted_mode_1='exact', accepted_normalize_1='1',
                  accepted_points_2='100', accepted_mode_2='exact', accepted_normalize_2='1', max_chars='20'), 'published'),
        ('q05', q('شتاب جاذبه‌ی زمین چند متر بر مجذور ثانیه است؟ (تلرانس ۰٫۱)', 'numeric', difficulty='hard', points='2',
                  numeric_answer='9.8', numeric_unit='m/s²', numeric_decimals='1', numeric_tolerance_mode='absolute',
                  numeric_tolerance='0.1', numeric_accept_persian='1'), 'published'),
        ('q06', q('چرخه‌ی آب در طبیعت را توضیح دهید. (تشریحی با روبریک)', 'essay', difficulty='hard', points='4',
                  answer_formats=['text'], student_instructions='حداقل در سه جمله پاسخ دهید.',
                  sample_answer_text='تبخیر، میعان، بارش و جاری شدن آب در زمین.',
                  rubric_criterion=['مراحل', 'نگارش'], rubric_weak=['ناقص', 'نامرتب'], rubric_average=['دو مرحله', 'قابل فهم'],
                  rubric_excellent=['هر چهار مرحله', 'روان'], rubric_points=['3', '1']), 'published'),
        ('q07', q('پایتخت ایران [1] و پایتخت ترکیه [2] است.', 'fill_blank', points='2',
                  blank_count='2', normalize_answers='1', blank_answers_1='تهران', blank_points_1='1',
                  blank_answers_2='آنکارا، انکارا', blank_points_2='1'), 'published'),
        ('q08', q('هر کشور را به پایتخت آن وصل کنید.', 'matching', points='3',
                  matching_left=['ایران', 'فرانسه', 'ژاپن'], matching_right=['تهران', 'پاریس', 'توکیو'],
                  matching_points_1='1', matching_points_2='1', matching_points_3='1',
                  matching_distractors='رم، برلین', matching_mode='one_to_one'), 'published'),
        ('q09', q('مراحل رشد گیاه را به ترتیب مرتب کنید.', 'ordering', course=course2, points='2',
                  ordering_item=['کاشت بذر', 'جوانه زدن', 'رشد ساقه و برگ', 'گل دادن'], ordering_mode='exact'), 'published'),
        ('q10', q('هر جانور در کدام محیط زندگی می‌کند؟', 'matrix', points='3',
                  matrix_json=json.dumps({'columns': [{'id': 'c1', 'text': 'خشکی'}, {'id': 'c2', 'text': 'آب'}],
                                          'rows': [{'id': 'r1', 'text': 'شیر', 'points': 1, 'correct': ['c1']},
                                                   {'id': 'r2', 'text': 'نهنگ', 'points': 1, 'correct': ['c2']},
                                                   {'id': 'r3', 'text': 'شتر', 'points': 1, 'correct': ['c1']}]}, ensure_ascii=False),
                  matrix_selection='single', matrix_show_column_titles='1', matrix_show_row_titles='1'), 'published'),
        ('q11', q('نام شکل‌های مشخص‌شده روی تصویر را بنویسید.', 'image_label', points='2',
                  existing_question_image=image_url, question_image_alt='دایره و مربع',
                  label_markers_json=json.dumps([{'x': 30.0, 'y': 50.0, 'answer': 'دایره', 'synonyms': '', 'points': 1},
                                                 {'x': 70.0, 'y': 50.0, 'answer': 'مربع', 'synonyms': 'چهارگوش', 'points': 1}],
                                                ensure_ascii=False),
                  label_answer_mode='type', label_accept_synonyms='1'), 'published'),
        ('q12', q('روی دایره‌ی تصویر کلیک کنید.', 'hotspot', points='1',
                  existing_question_image=image_url, question_image_alt='دایره و مربع',
                  hotspot_regions_json=json.dumps([{'name': 'دایره', 'shape': 'circle', 'coords': [[30, 50], [18, 30]], 'points': 1}],
                                                  ensure_ascii=False),
                  hotspot_max_clicks='1'), 'published'),
        ('q13', q('به فایل صوتی گوش دهید و بگویید چند صدای متفاوت شنیدید. (پاسخ صوتی یا متنی)', 'media_response', points='3',
                  existing_question_audio=audio_url, answer_formats=['text', 'audio'], media_allow_replay='1',
                  media_max_plays='3', media_max_record_seconds='60', media_transcript='دو بوق با زیر و بمی متفاوت.'), 'published'),
        ('q14', q('کدام سیاره به خورشید نزدیک‌تر است؟ (پیش‌نویس منتشرنشده)', 'single', is_published='',
                  option_text=['زهره', 'عطارد', 'مریخ'], correct_options=['2']), 'draft'),
        ('q15', q('بزرگ‌ترین اقیانوس جهان کدام است؟ (آرشیوشده)', 'single', difficulty='easy',
                  option_text=['اطلس', 'هند', 'آرام'], correct_options=['3']), 'archived'),
    ]


# ---------------------------------------------------------------- answers
def answer_for(row, right):
    """A student's answer (the attempt_answers 'value') to a stored question: right or wrong."""
    def load(value):
        return json.loads(value) if isinstance(value, str) and value[:1] in '[{"' else value

    kind = row['type']
    correct = load(row['correct_answer'])
    accepted = load(row['accepted_answers']) or []
    if kind in ('single', 'true_false'):
        options = load(row['options']) or []
        ids = [str(option.get('id') if isinstance(option, dict) else index) for index, option in enumerate(options, 1)]
        wrong = next((value for value in ids if value != str(correct)), 'x')
        return str(correct) if right else wrong
    if kind == 'multi':
        values = [str(value) for value in correct]
        return values if right else values[:1]
    if kind == 'short_answer':
        return accepted[0]['answer'] if right else 'CO2'
    if kind == 'numeric':
        return [str(correct)] if right else ['12']
    if kind == 'fill_blank':
        return [blank['answers'][0] for blank in accepted] if right else [accepted[0]['answers'][0], 'بغداد']
    if kind == 'matching':
        count = len(load(row['matching_pairs']) or [])
        return ','.join(f'{n}:{n}' for n in range(1, count + 1)) if right else '1:1,2:3,3:2'
    if kind == 'ordering':
        count = len([item for item in load(row['ordering_items']) or [] if item])
        return ','.join(str(n) for n in range(1, count + 1)) if right else ','.join(str(n) for n in range(count, 0, -1))
    if kind == 'matrix':
        return ','.join(correct) if right else 'r1:c2,r2:c2,r3:c1'
    if kind == 'image_label':
        return [marker['answer'] for marker in accepted] if right else ['دایره', 'مثلث']
    if kind == 'hotspot':
        return '30,50' if right else '75,40'
    if kind == 'essay':
        return ('چرخه‌ی آب با تبخیر آب دریاها شروع می‌شود، بخار در هوا سرد و به ابر تبدیل می‌شود (میعان)، '
                'سپس به شکل باران و برف می‌بارد و در رودها و زمین جاری می‌شود.') if right else 'آب بخار می‌شود و می‌بارد.'
    if kind == 'media_response':
        return 'دو صدای متفاوت شنیدم؛ اولی بم‌تر و دومی زیرتر بود.' if right else 'یک صدا.'
    return ''


class Command(BaseCommand):
    help = 'Create (or with --purge remove) marked test data: 15 teachers, students, questions and exams.'

    def add_arguments(self, parser):
        parser.add_argument('--purge', action='store_true', help='Only remove the test data.')

    # ------------------------------------------------------------ helpers
    def sql(self, statement, params=None):
        with connection.cursor() as cursor:
            cursor.execute(statement, params or [])

    def insert(self, table, values):
        columns = list(values)
        self.sql(
            f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({', '.join(['%s'] * len(columns))})",
            [json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value for value in values.values()],
        )

    # ------------------------------------------------------------ purge
    def purge(self):
        from apps.core.views import erd_rows

        def ids(statement, params=None):
            return [str(row['id']) for row in erd_rows(statement, params or [])]

        like = f'{PREFIX}%'
        profiles = ids("SELECT id FROM profiles WHERE username LIKE %s OR email LIKE %s",
                       [like, f'%@{EMAIL_DOMAIN}'])
        courses = ids('SELECT id FROM courses WHERE code LIKE %s', [f'{CODE}-%'])
        units = ids('SELECT id FROM org_units WHERE code LIKE %s', [f'{CODE}-%'])
        groups = ids(
            'SELECT id FROM student_groups WHERE group_code LIKE %s OR teacher_id::text = ANY(%s) '
            'OR course_id::text = ANY(%s) OR created_by::text = ANY(%s)',
            [f'{CODE}-%', profiles, courses, profiles])
        questions = ids(
            "SELECT id FROM questions WHERE tags LIKE %s OR text LIKE %s OR teacher_id::text = ANY(%s) OR course_id::text = ANY(%s)",
            [f'%{TAG}%', f'{MARK}%', profiles, courses])
        exams = ids(
            'SELECT id FROM exams WHERE title LIKE %s OR teacher_id::text = ANY(%s) OR course_id::text = ANY(%s)',
            [f'{MARK}%', profiles, courses])
        attempts = ids('SELECT id FROM exam_attempts WHERE exam_id::text = ANY(%s) OR student_id::text = ANY(%s)', [exams, profiles])
        sets = ids('SELECT id FROM question_sets WHERE course_id::text = ANY(%s) OR created_by::text = ANY(%s)', [courses, profiles])

        owner = {
            'exam_id': exams, 'question_id': questions, 'attempt_id': attempts, 'group_id': groups, 'course_id': courses,
            'org_unit_id': units, 'set_id': sets, 'parent_id': units,
            **{name: profiles for name in ('user_id', 'student_id', 'teacher_id', 'profile_id', 'student_user_id',
                                           'student_profile_id', 'manager_id', 'actor_id', 'created_by', 'target_teacher_id')},
        }
        roots = {'profiles': profiles, 'courses': courses, 'org_units': units, 'student_groups': groups, 'questions': questions,
                 'exams': exams, 'exam_attempts': attempts, 'question_sets': sets}
        columns = erd_rows(
            """
            SELECT c.table_name, c.column_name FROM information_schema.columns c
            JOIN information_schema.tables t ON t.table_name = c.table_name AND t.table_schema = c.table_schema
            WHERE c.table_schema = 'public' AND t.table_type = 'BASE TABLE' AND c.data_type IN ('uuid', 'text', 'character varying')
            """
        )
        nullable = [(row['table_name'], row['column_name']) for row in columns
                    if (row['column_name'].endswith('_by') and row['column_name'] != 'created_by') or row['column_name'] in ('reviewer_id', 'previous_org_unit_id')]
        deletes = [(row['table_name'], row['column_name'], owner[row['column_name']]) for row in columns
                   if row['column_name'] in owner and owner[row['column_name']]]
        deletes += [(table, 'id', values) for table, values in roots.items() if values]
        removed = {}
        with transaction.atomic():
            for table, column in nullable:
                if profiles:
                    try:
                        with transaction.atomic():
                            self.sql(f'UPDATE {table} SET {column} = NULL WHERE {column}::text = ANY(%s)', [profiles])
                    except IntegrityError:
                        pass  # NOT NULL column: the row goes with its owner below
            pending = list(deletes)
            for _round in range(12):
                failed = []
                for table, column, values in pending:
                    try:
                        with transaction.atomic(), connection.cursor() as cursor:
                            cursor.execute(f'DELETE FROM {table} WHERE {column}::text = ANY(%s)', [values])
                            if cursor.rowcount:
                                removed[table] = removed.get(table, 0) + cursor.rowcount
                    except IntegrityError:
                        failed.append((table, column, values))
                if not failed or len(failed) == len(pending):
                    pending = failed
                    break
                pending = failed
            if pending:
                raise IntegrityError('Could not remove: ' + ', '.join(f'{t}.{c}' for t, c, _v in pending))
            for profile_id in profiles:
                self.sql('DELETE FROM system_settings WHERE key LIKE %s', [f'%{profile_id}%'])
        users = get_user_model().objects.filter(username__startswith=PREFIX)
        removed['auth_user'] = users.count()
        users.delete()
        media_dir = MEDIA_PREFIX.rsplit('/', 1)[0]
        if default_storage.exists(media_dir):
            for name in default_storage.listdir(media_dir)[1]:
                if name.startswith('mqtest-'):
                    default_storage.delete(f'{media_dir}/{name}')
        return removed

    # ------------------------------------------------------------ people
    def make_profile(self, key, first, last, gender, status, role, index, extras, last_login):
        profile_id = sid(f'profile:{key}')
        username = f'{PREFIX}{key}'
        now = timezone.now()
        self.insert('profiles', {
            'id': profile_id, 'full_name': f'{first} {last} {MARK}', 'first_name': first, 'last_name': f'{last} {MARK}',
            'username': username, 'email': f'{username}@{EMAIL_DOMAIN}', 'phone': f'0990{(9000000 + index * 7919) % 10000000:07d}',
            'national_id': f'{"8" if role == "teacher" else "7"}99{index:07d}', 'identifier': f'{CODE}-{key.upper()}',
            'avatar_url': None, 'status': status, 'gender': gender, 'birth_date': f'13{70 + index % 15}/0{1 + index % 9}/1{index % 9}',
            'password_method': 'manual', 'must_change_password': bool(extras.get('must_change')),
            'email_verified_required': False, 'created_at': now - timedelta(days=40 - index),
            'updated_at': now, 'last_login_at': last_login,
            'deleted_at': now - timedelta(days=2) if extras.get('deleted') else None,
        })
        self.insert('user_roles', {'id': sid(f'role:{key}'), 'user_id': profile_id, 'role': role})
        user, _ = get_user_model().objects.update_or_create(
            username=username,
            defaults={'email': f'{username}@{EMAIL_DOMAIN}', 'first_name': first, 'last_name': last,
                      'is_active': status == 'active' and not extras.get('deleted')},
        )
        user.set_password(PASSWORD)
        user.save()
        return profile_id

    # ------------------------------------------------------------ main
    def handle(self, *args, **options):
        removed = self.purge()
        if removed:
            self.stdout.write('Removed: ' + ', '.join(f'{table} {count}' for table, count in sorted(removed.items())))
        if options['purge']:
            self.stdout.write(self.style.SUCCESS('Test data removed.'))
            return
        with transaction.atomic():
            self.seed()

    def seed(self):
        from apps.core.grading_views import _refresh_attempt_score
        from apps.core.views import _question_import_check, _save_question_payload, erd_rows, grade_attempt

        now = timezone.now()
        rng = random.Random(1405)

        # ---- org unit, courses
        unit = sid('unit')
        self.insert('org_units', {'id': unit, 'parent_id': None, 'type': 'university', 'name': f'{MARK} دانشکده‌ی تست', 'code': f'{CODE}-OU', 'is_active': True})
        courses = []
        for number, title in enumerate(['علوم پایه', 'زیست‌شناسی', 'ریاضی عمومی'], start=1):
            course = sid(f'course:{number}')
            courses.append(course)
            self.insert('courses', {'id': course, 'title': f'{MARK} {title}', 'code': f'{CODE}-C{number}',
                                    'description': 'درس آزمایشی برای تست سایت', 'org_unit_id': unit, 'credit_units': number + 1})

        # ---- teachers
        teacher = {}
        for index, (key, first, last, gender, status, approval, extras, _note) in enumerate(TEACHERS, start=1):
            last_login = None if extras.get('never_logged_in') or status != 'active' else now - timedelta(hours=index * 5)
            profile_id = self.make_profile(key, first, last, gender, status, 'teacher', index, extras, last_login)
            teacher[key] = profile_id
            self.insert('teacher_profiles', {
                'user_id': profile_id, 'personnel_code': f'{CODE}-{key.upper()}', 'department': f'{MARK} گروه علوم',
                'specialty': 'آموزش علوم', 'approval_status': approval, 'org_unit_id': unit,
                'academic_rank': extras.get('rank', 'استادیار'), 'degree': 'دکتری', 'position_title': 'عضو هیئت علمی',
                'cooperation_type': extras.get('cooperation', 'تمام‌وقت'), 'employment_type': 'رسمی', 'weekly_hours': '12',
                'max_units': '20', 'password_method': 'manual', 'apply_children': False,
                'can_design_exam': extras.get('can_design', True), 'force_password_change': bool(extras.get('must_change')),
                'two_factor_enabled': False, 'display_name': f'دکتر {first} {last}', 'bio': extras.get('bio', ''), 'show_bio': True,
            })
            if extras.get('change_request'):
                self.insert('teacher_profile_change_requests', {
                    'id': sid(f'change:{key}'), 'teacher_id': profile_id, 'org_unit_id': unit, 'academic_rank': 'دانشیار',
                    'degree': 'دکتری', 'previous_org_unit_id': unit, 'previous_academic_rank': 'استادیار', 'previous_degree': 'دکتری',
                    'teacher_note': f'{MARK} ارتقای مرتبه', 'status': 'pending', 'created_at': now - timedelta(days=1)})
            if extras.get('deletion_request'):
                self.insert('account_deletion_requests', {
                    'id': sid(f'deletion:{key}'), 'profile_id': profile_id, 'reason': f'{MARK} دیگر از سامانه استفاده نمی‌کنم.',
                    'status': 'pending', 'created_at': now - timedelta(hours=6)})

        # ---- students
        student, skill = {}, {}
        for index, (key, first, last, gender, status, academic, extras, _note) in enumerate(STUDENTS, start=1):
            last_login = now - timedelta(hours=index * 3) if status == 'active' and not extras.get('deleted') else None
            profile_id = self.make_profile(key, first, last, gender, status, 'student', index, extras, last_login)
            student[key], skill[key] = profile_id, extras.get('skill', 0.5)
            self.insert('student_profiles', {
                'user_id': profile_id, 'student_number': f'{CODE}-{key.upper()}', 'field_of_study': 'علوم تجربی',
                'degree': 'کارشناسی', 'class_group': f'گروه {1 + index % 3}', 'semester': str(1 + index % 8),
                'academic_status': academic, 'department': f'{MARK} گروه علوم', 'org_unit_id': unit, 'entry_year': '1403',
                'admission_type': 'روزانه', 'password_method': 'manual', 'must_change_password': bool(extras.get('must_change')),
                'send_welcome_message': False, 'show_avatar_to_teacher': True,
            })
            if extras.get('deletion_request'):
                self.insert('account_deletion_requests', {
                    'id': sid(f'deletion:{key}'), 'profile_id': profile_id, 'reason': f'{MARK} انصراف از تحصیل',
                    'status': 'pending', 'created_at': now - timedelta(hours=3)})

        # ---- groups (class = course + teacher + members)
        group_specs = [
            ('G1', courses[0], 't01', ['s01', 's02', 's03', 's04', 's05', 's06', 's11', 's13', 's15'], 'active', False),
            ('G2', courses[1], 't03', ['s01', 's02', 's04', 's07', 's08'], 'active', False),
            ('G3', courses[0], 't02', ['s09', 's10', 's11'], 'active', False),
            ('G4', courses[2], 't01', ['s05', 's07'], 'archived', True),
        ]
        group = {}
        for code, course, owner, members, status, archived in group_specs:
            group_id = sid(f'group:{code}')
            group[code] = group_id
            self.insert('student_groups', {
                'id': group_id, 'teacher_id': teacher[owner], 'course_id': course,
                'course_name': erd_rows('SELECT title FROM courses WHERE id = %s', [course])[0]['title'],
                'academic_year': '1405-1406', 'semester': 'نیمسال اول', 'group_code': f'{CODE}-{code}',
                'description': f'{MARK} گروه آزمایشی', 'is_active': not archived, 'created_by': teacher[owner], 'capacity': 30,
                'min_students': 2, 'offering_type': 'theory', 'class_schedule': 'شنبه‌ها ۱۰ تا ۱۲', 'class_location': 'کلاس ۲۰۴',
                'registration_start_at': now - timedelta(days=30), 'registration_end_at': now + timedelta(days=30),
                'status': status, 'is_archived': archived, 'archived_at': now - timedelta(days=5) if archived else None,
            })
            for member in members:
                key_index = int(member[1:])
                self.insert('student_group_members', {
                    'id': sid(f'member:{code}:{member}'), 'group_id': group_id, 'student_user_id': student[member],
                    'full_name': f'{STUDENTS[key_index - 1][1]} {STUDENTS[key_index - 1][2]} {MARK}',
                    'national_id': f'799{key_index:07d}', 'student_number': f'{CODE}-{member.upper()}'})
                self.sql('INSERT INTO student_course_enrollments (id, student_user_id, course_id) VALUES (%s, %s, %s) '
                         'ON CONFLICT (student_user_id, course_id) DO NOTHING', [sid(f'enroll:{member}:{course}'), student[member], course])
        self.insert('group_teachers', {'group_id': group['G1'], 'teacher_id': teacher['t02']})

        # ---- questions
        image_url = _store_media('shapes.png', __import__('apps.core.question_import_word', fromlist=['x']).sample_shapes_png())
        audio_url = _store_media('tone.wav', _wav_tone())
        question = {}
        for key, fields, state in question_posts(courses[0], courses[1], image_url, audio_url):
            payload, errors = _question_import_check(_post(fields), set(courses))
            if errors:
                raise ValueError(f'{key}: {errors}')
            question_id = _save_question_payload(payload, teacher['t01'])
            question[key] = question_id
            if state == 'archived':
                self.sql('UPDATE questions SET archived_at = %s WHERE id = %s', [now - timedelta(days=3), question_id])
            elif state == 'shared':
                self.sql('UPDATE questions SET shared_at = %s WHERE id = %s', [now - timedelta(days=1), question_id])
        # t03 teaches G2 (course 2) and t02 co-teaches G1: q03 is shared with them; the ordering question is t03's own
        self.sql('UPDATE questions SET teacher_id = %s WHERE id = %s', [teacher['t03'], question['q09']])

        # ---- exams
        def exam(key, title, owner='t01', course=None, start=None, minutes=60, end=None, **fields):
            exam_id = sid(f'exam:{key}')
            values = {
                'id': exam_id, 'teacher_id': teacher[owner], 'course_id': course or courses[0], 'title': f'{MARK} {title}',
                'description': f'آزمون آزمایشی — {title}', 'duration_minutes': minutes, 'start_at': start,
                'end_at': end or (start + timedelta(minutes=minutes) if start else None),
                'shuffle_questions': False, 'shuffle_options': False, 'negative_marking': False, 'negative_factor': 0,
                'max_attempts': 1, 'is_published': False, 'show_results_immediately': False, 'passing_score': 10,
                'allow_partial': True, 'is_cancelled': False, 'approval_status': None, 'exam_type': 'آنلاین',
                'academic_year': '1405-1406', 'semester': 'نیمسال اول', 'lifecycle_status': 'draft', 'publish_mode': 'draft',
                'exam_mode': 'standard', 'settings_enforced': False, 'results_deadline': 'manual',
                'correction_mode': 'manual', 'tags': TAG, 'total_score': 20, 'passing_percent': 50,
                'webcam_monitoring': False, 'identity_verification_required': False, 'device_limit_enabled': False,
            }
            values.update(fields)
            if values.get('is_published') and values['approval_status'] is None:
                values.update(approval_status='approved', approved_at=(start or now) - timedelta(days=2))
            self.insert('exams', values)
            return exam_id

        def add_questions(exam_id, keys_points):
            for order, (key, points) in enumerate(keys_points, start=1):
                self.insert('exam_questions', {'id': sid(f'eq:{exam_id}:{key}'), 'exam_id': exam_id, 'question_id': question[key],
                                               'points': points, 'order_index': order})

        def assign(exam_id, groups=(), students=()):
            for code in groups:
                self.insert('exam_assignments', {'id': sid(f'assign:{exam_id}:{code}'), 'exam_id': exam_id, 'group_id': group[code]})
            for key in students:
                self.insert('exam_assignments', {'id': sid(f'assign:{exam_id}:{key}'), 'exam_id': exam_id, 'student_profile_id': student[key]})

        auto = [('q01', 2), ('q02', 2), ('q03', 1), ('q04', 2), ('q05', 2), ('q07', 2), ('q08', 3), ('q10', 3), ('q11', 2), ('q12', 1)]
        mixed = [('q01', 2), ('q03', 2), ('q05', 2), ('q07', 2), ('q08', 3), ('q06', 5), ('q13', 4)]
        days = timedelta(days=1)

        e01 = exam('e01', 'پیش‌نویس با سؤال', start=now + 10 * days)
        add_questions(e01, auto[:4])
        assign(e01, ['G1'])
        exam('e02', 'پیش‌نویس بدون سؤال (قابل تأیید نیست)', start=now + 12 * days)
        e03 = exam('e03', 'ارسال‌شده — در انتظار تأیید مدیر', start=now + 3 * days, lifecycle_status='pending_approval',
                   approval_status='pending', publish_mode='submit')
        add_questions(e03, auto)
        assign(e03, ['G1'])
        e04 = exam('e04', 'ردشده توسط مدیر آموزشی', start=now + 4 * days, approval_status='rejected', lifecycle_status='draft',
                   publish_mode='submit', cancel_reason=None)
        add_questions(e04, auto[:3])
        assign(e04, ['G1'])
        e05 = exam('e05', 'تأییدشده — انتشار زمان‌بندی‌شده (فردا)', start=now + 2 * days, lifecycle_status='approved',
                   approval_status='approved', approved_at=now - days,
                   publish_mode='scheduled', scheduled_publish_at=now + days)
        add_questions(e05, auto[:5])
        assign(e05, ['G1'])
        e06 = exam('e06', 'شروع تا ۳۰ دقیقه‌ی دیگر', start=now + timedelta(minutes=30), minutes=45, is_published=True,
                   lifecycle_status='published', publish_mode='immediate', show_results_immediately=True,
                   score_display_mode='immediate', correct_answer_display_mode='immediate')
        add_questions(e06, auto)
        assign(e06, ['G1'])
        e07 = exam('e07', 'برنامه‌ریزی‌شده با تنظیمات امنیتی (دو روز دیگر)', start=now + 2 * days + timedelta(hours=3), minutes=90,
                   is_published=True, lifecycle_status='published', publish_mode='immediate', settings_enforced=True,
                   shuffle_questions=True, shuffle_options=True, one_question_per_page=True, fullscreen_required=True,
                   copy_paste_prevention=True, track_tab_exit=True, security_level='high', review_answers_enabled=True,
                   registration_end_at=now + 2 * days + timedelta(hours=3, minutes=15), results_deadline='manual')
        add_questions(e07, mixed)
        assign(e07, ['G1', 'G2'])
        e08 = exam('e08', 'در حال برگزاری (الان)', start=now - timedelta(minutes=20), minutes=90, is_published=True,
                   lifecycle_status='published', publish_mode='immediate', score_display_mode='after_publish')
        add_questions(e08, auto)
        assign(e08, ['G1'])
        e09 = exam('e09', 'آزمون تمرینی باز (۳ بار شرکت)', start=now - 2 * days, end=now + 5 * days, minutes=30,
                   is_published=True, lifecycle_status='published', publish_mode='immediate', exam_mode='training',
                   max_attempts=3, show_results_immediately=True)
        add_questions(e09, auto[:5])
        assign(e09, ['G1', 'G2'])
        e10 = exam('e10', 'پایان‌یافته — نمرات منتشرشده', start=now - 6 * days, minutes=60, is_published=True,
                   lifecycle_status='closed', publish_mode='immediate', results_published_at=now - 4 * days,
                   review_answers_enabled=True)
        add_questions(e10, mixed)
        assign(e10, ['G1'])
        self.insert('exam_assignment_exclusions', {'id': sid('exclude:e10:s13'), 'exam_id': e10, 'student_profile_id': student['s13']})
        e11 = exam('e11', 'پایان‌یافته — تشریحی در انتظار تصحیح', start=now - 2 * days, minutes=60, is_published=True,
                   lifecycle_status='closed', publish_mode='immediate', manual_review_required=True)
        add_questions(e11, mixed)
        assign(e11, ['G1'])
        e12 = exam('e12', 'پایان‌یافته — تصحیح‌شده، در انتظار انتشار نمره', start=now - 3 * days, minutes=60, is_published=True,
                   lifecycle_status='closed', publish_mode='immediate')
        add_questions(e12, mixed)
        assign(e12, ['G1'], ['s14'])
        e13 = exam('e13', 'پایان‌یافته — نمره‌ی منفی، نتیجه‌ی فوری', start=now - 1 * days, minutes=40, is_published=True,
                   lifecycle_status='closed', publish_mode='immediate', settings_enforced=True, negative_marking=True,
                   negative_factor=0.25, allow_partial=False, show_results_immediately=True, score_display_mode='immediate',
                   correct_answer_display_mode='immediate', explanation_display_mode='immediate', results_deadline='manual')
        add_questions(e13, auto)
        assign(e13, ['G1'])
        e14 = exam('e14', 'لغوشده', start=now + 5 * days, is_published=True, lifecycle_status='published', publish_mode='immediate',
                   is_cancelled=True, cancel_reason='تداخل با برنامه‌ی کلاس جبرانی')
        add_questions(e14, auto[:4])
        assign(e14, ['G1'])
        e15 = exam('e15', 'بایگانی‌شده (ترم قبل)', owner='t03', course=courses[1], start=now - 60 * days, minutes=60,
                   is_published=True, lifecycle_status='archived', publish_mode='immediate', results_published_at=now - 55 * days,
                   semester='نیمسال دوم', academic_year='1404-1405')
        add_questions(e15, [('q03', 5), ('q09', 5), ('q01', 10)])
        assign(e15, ['G2'])

        self.insert('exam_staff', {'id': sid('staff:e11:t02'), 'exam_id': e11, 'teacher_id': teacher['t02'], 'role': 'co_grader'})
        self.insert('exam_staff', {'id': sid('staff:e12:t02'), 'exam_id': e12, 'teacher_id': teacher['t02'], 'role': 'co_grader'})
        self.insert('exam_staff', {'id': sid('staff:e10:t14'), 'exam_id': e10, 'teacher_id': teacher['t14'], 'role': 'observer'})
        self.insert('exam_staff', {'id': sid('staff:e07:t02'), 'exam_id': e07, 'teacher_id': teacher['t02'], 'role': 'designer'})

        # ---- attempts
        question_rows = {}

        def rows_of(exam_id):
            if exam_id not in question_rows:
                question_rows[exam_id] = erd_rows(
                    """
                    SELECT q.id, q.type, q.options, q.correct_answer, q.accepted_answers, q.matching_pairs, q.ordering_items
                    FROM exam_questions eq JOIN questions q ON q.id = eq.question_id WHERE eq.exam_id = %s ORDER BY eq.order_index
                    """, [exam_id])
            return question_rows[exam_id]

        def attempt(exam_id, key, started, minutes=35, status='submit', answered=None, number=1):
            attempt_id = sid(f'attempt:{exam_id}:{key}:{number}')
            submitted = None if status in ('in_progress', 'expired') else started + timedelta(minutes=minutes)
            self.insert('exam_attempts', {
                'id': attempt_id, 'exam_id': exam_id, 'student_id': student[key], 'started_at': started, 'submitted_at': submitted,
                'score': None, 'max_score': None, 'is_graded': False,
                'status': 'in_progress' if status == 'in_progress' else 'expired' if status == 'expired' else 'submitted',
                'furthest_question': 1})
            for position, row in enumerate(rows_of(exam_id)):
                if answered is not None and position >= answered:
                    break
                right = rng.random() < skill[key]
                self.insert('attempt_answers', {
                    'id': sid(f'answer:{attempt_id}:{row["id"]}'), 'attempt_id': attempt_id, 'question_id': row['id'],
                    'answer': {'value': answer_for(row, right)}, 'answer_files': [],
                    'needs_manual_grading': False, 'marked_for_review': position == 1 and status == 'in_progress'})
            if status not in ('in_progress', 'expired'):
                grade_attempt(attempt_id)
                self.sql('UPDATE exam_attempts SET submitted_at = %s WHERE id = %s', [submitted, attempt_id])
            return attempt_id

        def grade_manual(attempt_id, key, grader='t01'):
            for row in erd_rows(
                    """
                    SELECT aa.id, COALESCE(eq.points, 1) AS points, q.type FROM attempt_answers aa
                    JOIN exam_attempts ea ON ea.id = aa.attempt_id
                    JOIN exam_questions eq ON eq.exam_id = ea.exam_id AND eq.question_id = aa.question_id
                    JOIN questions q ON q.id = aa.question_id
                    WHERE aa.attempt_id = %s AND aa.needs_manual_grading = true
                    """, [attempt_id]):
                # a short answer only reaches manual grading when it matched no accepted answer: the teacher rejects it
                ratio = 0 if row['type'] == 'short_answer' else min(1.0, skill[key] + 0.1)
                points = round(float(row['points']) * ratio * 2) / 2
                self.sql(
                    'UPDATE attempt_answers SET points_awarded = %s, needs_manual_grading = false, graded_by = %s, graded_at = %s, '
                    'grader_feedback = %s, is_correct = %s WHERE id = %s',
                    [points, teacher[grader], now - timedelta(days=1), 'پاسخ خوب بود؛ به جزئیات بیشتری نیاز دارد.' if points else 'پاسخ ناکافی.',
                     points >= float(row['points']), row['id']])
            _refresh_attempt_score(attempt_id)

        # running exam: s01 already submitted, s03 and s04 still answering
        attempt(e08, 's01', now - timedelta(minutes=19), minutes=15)
        attempt(e08, 's03', now - timedelta(minutes=15), status='in_progress', answered=4)
        attempt(e08, 's04', now - timedelta(minutes=8), status='in_progress', answered=1)
        # training exam: s01 twice, s02 once
        attempt(e09, 's01', now - 2 * days + timedelta(hours=2), minutes=12)
        attempt(e09, 's01', now - days, minutes=10, number=2)
        attempt(e09, 's02', now - days, minutes=20)
        # published results
        for key in ('s01', 's02', 's04', 's05', 's11'):
            grade_manual(attempt(e10, key, now - 6 * days + timedelta(minutes=2)), key)
        attempt(e10, 's06', now - 6 * days + timedelta(minutes=5), status='expired', answered=2)
        # waiting for manual grading (s01's essay already graded, the rest pending)
        for key in ('s01', 's02', 's03', 's05'):
            attempt_id = attempt(e11, key, now - 2 * days + timedelta(minutes=3))
            if key == 's01':
                grade_manual(attempt_id, key, grader='t02')
        # graded, results not published yet
        for key in ('s01', 's02', 's04', 's14'):
            grade_manual(attempt(e12, key, now - 3 * days + timedelta(minutes=1)), key)
        # negative marking, immediate results
        for key in ('s01', 's02', 's03', 's04', 's05', 's13'):
            grade_manual(attempt(e13, key, now - days + timedelta(minutes=1), minutes=25), key)
        # archived exam of last term
        for key in ('s01', 's04', 's07'):
            attempt(e15, key, now - 60 * days + timedelta(minutes=1), minutes=40)
        self.sql("UPDATE exam_attempts SET status = 'disputed' WHERE id = %s", [sid(f'attempt:{e10}:s04:1')])

        # ---- objections
        objections = [
            ('s04', e10, 'q06', 'open', '', None, 'نمره‌ی سؤال تشریحی', 'به نظرم پاسخم کامل بود؛ لطفاً دوباره بررسی کنید.'),
            ('s05', e10, 'q08', 'resolved_rejected', 'پاسخ شما با کلید تطابق نداشت.', 't01', 'سؤال وصل‌کردنی', 'کلید این سؤال اشتباه است.'),
            ('s02', e10, 'q05', 'resolved_accepted', 'حق با شماست؛ نمره اصلاح شد.', 't01', 'تلرانس سؤال عددی', 'پاسخم در بازه‌ی مجاز بود.'),
            ('s01', e13, 'q02', 'under_review', '', None, 'نمره‌ی منفی', 'چرا برای این سؤال نمره‌ی منفی گرفتم؟'),
            ('s01', e15, 'q09', 'escalated', 'به مدیر آموزشی ارجاع شد.', 't03', 'ترتیب مراحل', 'دو ترتیب درست وجود دارد.'),
        ]
        for index, (key, exam_id, qkey, status, response, resolver, subject, message) in enumerate(objections, start=1):
            self.insert('objections', {
                'id': sid(f'objection:{index}'), 'student_id': student[key], 'exam_id': exam_id,
                'attempt_id': sid(f'attempt:{exam_id}:{key}:1'), 'question_id': question[qkey],
                'subject': f'{MARK} {subject}', 'message': message, 'status': status, 'teacher_response': response or None,
                'resolved_by': teacher[resolver] if resolver else None,
                'resolved_at': now - timedelta(hours=10) if status.startswith('resolved') else None})

        # ---- notifications
        for index, (key, title, message, read) in enumerate([
            ('s01', 'نتیجه آزمون منتشر شد', 'نتیجه‌ی «پایان‌یافته — نمرات منتشرشده» منتشر شد.', False),
            ('s01', 'آزمون جدید', 'آزمون «شروع تا ۳۰ دقیقه‌ی دیگر» برای شما منتشر شد.', False),
            ('s02', 'یادآوری آزمون', 'آزمون فردا شروع می‌شود.', True),
            ('t01', 'آزمون در انتظار تصحیح', 'پاسخ‌های تشریحی آزمون منتظر تصحیح هستند.', False),
            ('t01', 'اعتراض جدید', 'یک دانشجو به نمره اعتراض کرده است.', False),
        ], start=1):
            owner = student.get(key) or teacher.get(key)
            self.insert('notifications', {'id': sid(f'notification:{index}'), 'user_id': owner, 'type': 'system',
                                          'title': f'{MARK} {title}', 'message': message, 'link': '', 'is_read': read,
                                          'created_at': now - timedelta(hours=index)})

        self.report(teacher, student)

    def report(self, teacher, student):
        from apps.core.views import erd_rows, exam_access_code

        out = self.stdout.write
        out(self.style.SUCCESS(f'Test data created. Every account: password {PASSWORD}'))
        out('Teachers:')
        for key, *_rest, note in TEACHERS:
            out(f'  {PREFIX}{key}  {note}')
        out('Students:')
        for key, *_rest, note in STUDENTS:
            out(f'  {PREFIX}{key}  {note}')
        out('Exams:')
        for row in erd_rows('SELECT id, title FROM exams WHERE title LIKE %s ORDER BY title', [f'{MARK}%']):
            out(f"  {exam_access_code(row['id'])}  {row['title']}")
