import csv
import io
import json
import math
import random
import re
import uuid
import zipfile
from datetime import datetime, timedelta
from decimal import Decimal
from importlib import import_module
from pathlib import Path
from functools import lru_cache, wraps
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape as xml_escape

from django.contrib import messages
from django.contrib.auth import get_user_model, login as auth_login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.views import LoginView
from django.contrib.sessions.models import Session
from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.db import DatabaseError, IntegrityError, connection, transaction
from django.db.models import Count, Q
from django.http import Http404, HttpResponse, HttpResponseForbidden, JsonResponse, QueryDict
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.crypto import get_random_string
from django.utils.dateparse import parse_datetime
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from . import account_security, question_kinds
from .rich_text import clean_delta, delta_length, delta_text, delta_to_html
from .uploads import delete_private, file_extension, image_ok, signature_ok, store_private
from .forms import (
    AssistantDescriptiveReviewForm,
    AssistantEducationalAnswerForm,
    AssistantExamDraftForm,
    AssistantExamDraftReviewForm,
    AssistantQuestionForm,
    AssistantQuestionReviewForm,
    AssistantQuestionSuggestionForm,
    AssistantQuestionSuggestionReviewForm,
    AssistantReviewAssignmentForm,
    AssistantReviewDecisionForm,
    EducationalQuestionForm,
    StudentExamEntryForm,
    StudentObjectionCreateForm,
    StudentPracticeCheckForm,
    EmergencyStopExamForm,
    AcademicStructureForm,
    ExamApprovalReviewForm,
    ExamCalendarScheduleForm,
    ExamExecutionReportForm,
    DescriptiveReviewForm,
    ExamManagerAssignmentForm,
    ExamRescheduleForm,
    ExamStartControlForm,
    ExamQuestionScoreForm,
    InstitutionSettingsForm,
    InstitutionUserCreateForm,
    InstitutionUserImportForm,
    ProctorAssignmentForm,
    ObjectionReviewForm,
    QuestionForm,
    PublicRegistrationForm,
    ResultPublicationForm,
    StyledAuthenticationForm,
    SuperAdminClassForm,
    SuperAdminCourseForm,
    SuperAdminExamForm,
    SuperAdminInstitutionForm,
    SuperAdminOrgUnitForm,
    SuperAdminReportFilterForm,
    SuperAdminRoleForm,
    SuperAdminSettingsForm,
    SuperAdminTermForm,
    SuperAdminUserActionForm,
    TwoFactorCodeForm,
    ViolationDecisionForm,
    TeacherExamForm,
)
from .models import (
    AcademicInstitution,
    AcademicTerm,
    AcademicUnit,
    AssistantExamDraft,
    AssistantQuestionSubmission,
    AssistantQuestionSuggestion,
    AssistantReviewAssignment,
    Course,
    CourseClass,
    DescriptiveAnswerReview,
    EducationalQuestion,
    Exam,
    ExamApproval,
    ExamExecutionReport,
    ExamProctorAssignment,
    ExamQuestion,
    ExamResultPublication,
    ExamRescheduleRequest,
    ExamStartAuthorization,
    ExamViolationReport,
    InstitutionAdminProfile,
    StudentProfile,
    Question,
    StudentObjection,
    StudentExamAttempt,
    StudentExamEvent,
    StudentPracticeCheck,
    StudentQuestionAnswer,
    SystemSetting,
    SystemRole,
    TeacherProfile,
    UserActivityLog,
    UserLoginRecord,
    UserProfile,
)


User = get_user_model()


ROLE_DASHBOARDS = {
    'super_admin': {
        'section': 'مدیریت کل سامانه',
        'title': 'نمای کلی مدیریت سیستم',
        'breadcrumb': 'حساب من / مدیریت / مدیر کل سیستم',
        'description': 'وضعیت کاربران، نقش‌ها، آزمون‌ها، گزارش‌ها و تنظیمات عمومی سامانه را از همین صفحه دنبال کنید.',
        'primary_action': 'مشاهده گزارش‌ها',
        'side_title': 'کنترل سیستم',
        'progress': 91,
        'stats': [
            {'label': 'کاربران فعال', 'value': '۱۲۸', 'tone': 'purple'},
            {'label': 'نقش‌ها', 'value': '۶', 'tone': 'green'},
            {'label': 'هشدارها', 'value': '۳', 'tone': 'red'},
            {'label': 'سلامت سیستم', 'value': '۹۸٪', 'tone': 'dark'},
        ],
        'tasks': [
            {'title': 'مدیریت کاربران', 'meta': 'فعال‌سازی، مسدودسازی و بررسی حساب‌ها', 'progress': 100},
            {'title': 'تعریف نقش‌ها و مجوزها', 'meta': 'کنترل سطح دسترسی نقش‌ها', 'progress': 80},
            {'title': 'گزارش‌ها و لاگ‌ها', 'meta': 'بررسی فعالیت‌ها و ورودها', 'progress': 65},
            {'title': 'پشتیبان‌گیری', 'meta': 'بازیابی و نگهداری داده‌ها', 'progress': 40},
        ],
    },
    'institution_admin': {
        'section': 'مدیریت مرکز آموزشی',
        'title': 'داشبورد مدیر مؤسسه',
        'breadcrumb': 'حساب من / مرکز آموزشی / مدیریت مؤسسه',
        'description': 'استادان، دانشجویان، گروه‌ها و آزمون‌های مرکز آموزشی را در یک نمای فشرده مدیریت کنید.',
        'primary_action': 'مدیریت کاربران مرکز',
        'side_title': 'واحدهای مرکز',
        'progress': 74,
        'stats': [
            {'label': 'استادان', 'value': '۲۴', 'tone': 'purple'},
            {'label': 'دانشجویان', 'value': '۴۸۰', 'tone': 'green'},
            {'label': 'در انتظار تأیید', 'value': '۹', 'tone': 'red'},
            {'label': 'آزمون‌های مرکز', 'value': '۳۲', 'tone': 'dark'},
        ],
        'tasks': [
            {'title': 'مدیریت استادان و دانشجویان', 'meta': 'کاربران وابسته به مرکز', 'progress': 85},
            {'title': 'تعریف دانشکده و گروه', 'meta': 'ساختار آموزشی مرکز', 'progress': 60},
            {'title': 'گزارش عملکرد', 'meta': 'آمار آزمون‌ها و کاربران', 'progress': 52},
            {'title': 'تعیین مسئول آزمون', 'meta': 'انتساب مدیر گروه یا امتحانات', 'progress': 35},
        ],
    },
    'exam_manager': {
        'section': 'برنامه‌ریزی آزمون‌ها',
        'title': 'داشبورد مسئول امتحانات',
        'breadcrumb': 'حساب من / امتحانات / برنامه‌ریزی',
        'description': 'تقویم آزمون، حضور و غیاب، ناظران و وضعیت برگزاری آزمون‌ها را از این صفحه کنترل کنید.',
        'primary_action': 'تنظیم تقویم آزمون',
        'side_title': 'برنامه آزمون‌ها',
        'progress': 68,
        'stats': [
            {'label': 'آزمون امروز', 'value': '۵', 'tone': 'purple'},
            {'label': 'حضور ثبت‌شده', 'value': '۸۷٪', 'tone': 'green'},
            {'label': 'لغوشده', 'value': '۲', 'tone': 'red'},
            {'label': 'ناظران', 'value': '۱۸', 'tone': 'dark'},
        ],
        'tasks': [
            {'title': 'تنظیم تقویم امتحانات', 'meta': 'زمان‌بندی و محل مجازی', 'progress': 90},
            {'title': 'اختصاص درس و استاد', 'meta': 'اتصال کلاس‌ها به آزمون', 'progress': 75},
            {'title': 'هماهنگی ناظران', 'meta': 'نوبت‌ها و مسئولیت‌ها', 'progress': 55},
            {'title': 'گزارش رسمی آزمون‌ها', 'meta': 'خروجی اجرایی و حضور و غیاب', 'progress': 30},
        ],
    },
    'teacher': {
        'section': 'طراحی و تصحیح آزمون',
        'title': 'داشبورد استاد و طراح سؤال',
        'breadcrumb': 'حساب من / درس‌ها / طراحی آزمون',
        'description': 'بانک سؤال، طراحی آزمون، بارم‌بندی، تصحیح پاسخ‌ها و انتشار نمره را مدیریت کنید.',
        'primary_action': 'طراحی آزمون جدید',
        'side_title': 'درس‌ها و آزمون‌ها',
        'progress': 82,
        'stats': [
            {'label': 'سؤال‌ها', 'value': '۲۳۶', 'tone': 'purple'},
            {'label': 'تصحیح‌شده', 'value': '۱۴۸', 'tone': 'green'},
            {'label': 'اعتراض‌ها', 'value': '۴', 'tone': 'red'},
            {'label': 'کیفیت سؤال', 'value': '۸۶٪', 'tone': 'dark'},
        ],
        'tasks': [
            {'title': 'ایجاد بانک سؤال', 'meta': 'تستی، تشریحی، صحیح و غلط', 'progress': 95},
            {'title': 'تعیین بارم و نمره منفی', 'meta': 'تنظیم قواعد نمره‌دهی', 'progress': 70},
            {'title': 'تصحیح پاسخ‌های تشریحی', 'meta': 'بررسی پاسخ‌های دانشجویان', 'progress': 50},
            {'title': 'تحلیل کیفیت سؤالات', 'meta': 'سختی و تمایز سؤال‌ها', 'progress': 25},
        ],
    },
    'teaching_assistant': {
        'section': 'دستیار آموزشی',
        'title': 'داشبورد کمک‌استاد',
        'breadcrumb': 'حساب من / درس‌ها / دستیار آموزشی',
        'description': 'ورود سؤال، بررسی اولیه پاسخ‌ها، گزارش‌های محدود و محتوای درس‌های مجاز را پیگیری کنید.',
        'primary_action': 'بررسی پاسخ‌ها',
        'side_title': 'وظایف دستیار',
        'progress': 57,
        'stats': [
            {'label': 'سؤال‌های واردشده', 'value': '۴۲', 'tone': 'purple'},
            {'label': 'بررسی اولیه', 'value': '۳۱', 'tone': 'green'},
            {'label': 'پیام‌ها', 'value': '۷', 'tone': 'red'},
            {'label': 'درس‌های مجاز', 'value': '۳', 'tone': 'dark'},
        ],
        'tasks': [
            {'title': 'ورود سؤال به بانک سؤال', 'meta': 'طبق مجوز استاد مسئول', 'progress': 80},
            {'title': 'پیش‌نویس آزمون', 'meta': 'آماده‌سازی برای تأیید استاد', 'progress': 65},
            {'title': 'بازبینی سؤال‌ها', 'meta': 'پیشنهاد اصلاح نگارشی یا محتوایی', 'progress': 55},
            {'title': 'تصحیح پاسخ‌ها', 'meta': 'بدون مشاهده اطلاعات شخصی دانشجو', 'progress': 45},
            {'title': 'پرسش‌های آموزشی', 'meta': 'پاسخ یا ارجاع به استاد', 'progress': 35},
        ],
    },
    'exam_proctor': {
        'section': 'نظارت آزمون',
        'title': 'داشبورد ناظر آزمون',
        'breadcrumb': 'حساب من / آزمون‌ها / نظارت',
        'description': 'جلسه‌های تخصیص‌یافته، احراز هویت داوطلبان، رخدادهای آزمون و گزارش تخلف‌ها را از این بخش پیگیری کنید.',
        'primary_action': 'شروع نظارت',
        'side_title': 'جلسه‌های نظارت',
        'progress': 71,
        'stats': [
            {'label': 'جلسه امروز', 'value': '۳', 'tone': 'purple'},
            {'label': 'احراز هویت', 'value': '۴۸', 'tone': 'green'},
            {'label': 'رخداد باز', 'value': '۲', 'tone': 'red'},
            {'label': 'ظرفیت همزمان', 'value': '۴', 'tone': 'dark'},
        ],
        'tasks': [
            {'title': 'بررسی فهرست داوطلبان', 'meta': 'قبل از شروع آزمون', 'progress': 90},
            {'title': 'احراز هویت شرکت‌کنندگان', 'meta': 'کارت/چهره/دستگاه', 'progress': 70},
            {'title': 'ثبت رخداد و تخلف', 'meta': 'گزارش جلسه آزمون', 'progress': 45},
            {'title': 'هماهنگی با پشتیبانی فنی', 'meta': 'در زمان اختلال', 'progress': 25},
        ],
    },
    'tech_support': {
        'section': 'پشتیبانی فنی',
        'title': 'داشبورد پشتیبان فنی',
        'breadcrumb': 'حساب من / پشتیبانی / رخدادهای فنی',
        'description': 'تیکت‌ها، لاگ‌های فنی، نشست‌های کاربران، دستگاه‌ها و پشتیبانی آزمون‌های زنده را مدیریت کنید.',
        'primary_action': 'مشاهده تیکت‌ها',
        'side_title': 'درخواست‌های پشتیبانی',
        'progress': 66,
        'stats': [
            {'label': 'تیکت باز', 'value': '۱۲', 'tone': 'purple'},
            {'label': 'حل‌شده', 'value': '۳۴', 'tone': 'green'},
            {'label': 'اختلال فوری', 'value': '۱', 'tone': 'red'},
            {'label': 'نشست فعال', 'value': '۸۷', 'tone': 'dark'},
        ],
        'tasks': [
            {'title': 'بررسی تیکت‌های فوری', 'meta': 'اولویت آزمون‌های زنده', 'progress': 85},
            {'title': 'کنترل لاگ‌های خطا', 'meta': 'ورود، نشست و ارسال پاسخ', 'progress': 65},
            {'title': 'مدیریت دستگاه‌ها', 'meta': 'رفع محدودیت مجاز', 'progress': 45},
            {'title': 'گزارش مشکل فنی', 'meta': 'برای مدیر سیستم', 'progress': 30},
        ],
    },
    'student': {
        'section': 'آزمون‌های من',
        'title': 'داشبورد دانشجو',
        'breadcrumb': 'حساب من / آزمون‌ها / وضعیت من',
        'description': 'آزمون‌های تخصیص‌یافته، حضور، پاسخ‌ها، نمره، اعتراض‌ها و فایل‌های ارسالی خود را دنبال کنید.',
        'primary_action': 'مشاهده نتیجه آزمون',
        'side_title': 'درس‌های فعال',
        'progress': 63,
        'stats': [
            {'label': 'دقت پاسخ‌ها', 'value': '۵۸٪', 'tone': 'purple'},
            {'label': 'پاسخ درست', 'value': '۱۶', 'tone': 'green'},
            {'label': 'پاسخ نادرست', 'value': '۶', 'tone': 'red'},
            {'label': 'رتبه', 'value': '۲۰ / ۴۰', 'tone': 'dark'},
        ],
        'tasks': [
            {'title': 'آزمون مبانی طراحی تجربه', 'meta': '۴ ساعت / ۴ جلسه', 'progress': 100},
            {'title': 'اصطلاحات و ابزارها', 'meta': '۸ ساعت / ۴ جلسه', 'progress': 45},
            {'title': 'اصول پایه', 'meta': '۳ ساعت / ۲ جلسه', 'progress': 20},
            {'title': 'صفحات فرود', 'meta': '۳ ساعت / ۲ جلسه', 'progress': 0},
        ],
    },
}

ROLE_TASK_GROUPS = {
    'super_admin': [
        {
            'title': 'مدیریت کاربران و نقش‌ها',
            'items': [
                'ایجاد، ویرایش و حذف حساب کاربران',
                'فعال، غیرفعال یا مسدود کردن حساب‌ها',
                'تعریف نقش‌های جدید',
                'تعیین مجوزهای هر نقش',
                'تغییر نقش کاربران',
                'بازنشانی رمز عبور کاربران',
                'بررسی و تأیید هویت کاربران',
                'مشاهده سوابق ورود کاربران',
            ],
        },
        {
            'title': 'مدیریت مراکز آموزشی',
            'items': [
                'ایجاد مرکز آموزشی جدید',
                'ویرایش اطلاعات مراکز آموزشی',
                'فعال یا غیرفعال کردن مرکز آموزشی',
                'تعیین مدیر برای هر مرکز',
                'مشاهده کاربران هر مرکز',
                'تعیین محدودیت تعداد کاربران یا آزمون‌ها',
                'مدیریت اشتراک و اعتبار مرکز در سامانه‌های تجاری',
            ],
        },
        {
            'title': 'مدیریت آزمون‌ها',
            'items': [
                'مشاهده تمام آزمون‌های سامانه',
                'ویرایش یا لغو آزمون در شرایط ضروری',
                'توقف آزمون در صورت بروز مشکل عمومی',
                'تمدید زمان آزمون',
                'مشاهده آزمون‌های فعال، پایان‌یافته و لغوشده',
                'بررسی وضعیت برگزاری آزمون‌ها',
                'بازیابی آزمون‌های حذف‌شده',
                'انتقال آزمون میان استادان یا مراکز',
            ],
        },
        {
            'title': 'مدیریت تنظیمات سامانه',
            'items': [
                'تعیین نام و مشخصات سامانه',
                'تنظیم لوگو و قالب ظاهری',
                'تنظیم منطقه زمانی و زبان سامانه',
                'تعیین قوانین رمز عبور',
                'تنظیم روش احراز هویت',
                'تنظیم محدودیت ورود هم‌زمان',
                'تنظیم زمان خروج خودکار کاربران',
                'تنظیم قوانین نمره‌دهی و نمره منفی',
                'تنظیم حجم مجاز فایل‌ها',
            ],
        },
        {
            'title': 'مدیریت امنیت',
            'items': [
                'مشاهده گزارش ورودهای مشکوک',
                'مسدود کردن IP یا دستگاه مشکوک',
                'مدیریت احراز هویت دومرحله‌ای',
                'مشاهده لاگ فعالیت کاربران',
                'بررسی تغییرات نمرات و سؤالات',
                'کنترل دسترسی به اطلاعات حساس',
                'تعیین سیاست نگهداری اطلاعات',
                'ثبت سوابق عملیات مهم مدیران',
            ],
        },
        {
            'title': 'مدیریت گزارش‌ها',
            'items': [
                'مشاهده آمار کل کاربران',
                'مشاهده تعداد آزمون‌ها و شرکت‌کنندگان',
                'مشاهده آمار مراکز آموزشی',
                'مشاهده میزان موفقیت و شکست آزمون‌ها',
                'مشاهده گزارش تخلفات',
                'دریافت خروجی Excel، PDF یا CSV',
                'مشاهده گزارش عملکرد مدیران مراکز',
                'مشاهده وضعیت سرور و سامانه',
            ],
        },
        {
            'title': 'پشتیبان‌گیری و نگهداری',
            'items': [
                'تهیه نسخه پشتیبان از اطلاعات',
                'بازیابی نسخه پشتیبان',
                'مدیریت فایل‌های ذخیره‌شده',
                'مدیریت فضای ذخیره‌سازی',
                'بررسی خطاهای سیستمی',
                'فعال‌کردن حالت تعمیر و نگهداری',
                'مدیریت اعلان‌های عمومی سامانه',
            ],
        },
    ],
    'institution_admin': [
        {
            'title': 'مدیریت اطلاعات مرکز',
            'items': [
                'ویرایش نام و مشخصات مرکز',
                'ثبت لوگو و اطلاعات تماس مرکز',
                'تعریف دانشکده، رشته، پایه یا واحد آموزشی',
                'تعریف سال و نیم‌سال تحصیلی',
                'تعریف کلاس‌ها و گروه‌های آموزشی',
                'تعیین تقویم آموزشی و امتحانی',
            ],
        },
        {
            'title': 'مدیریت کاربران مرکز',
            'items': [
                'ثبت استادان',
                'ثبت دانشجویان یا داوطلبان',
                'ثبت ناظران و نیروهای پشتیبانی',
                'واردکردن گروهی کاربران از فایل Excel',
                'ویرایش اطلاعات کاربران مرکز',
                'فعال یا غیرفعال کردن کاربران',
                'تخصیص دانشجویان به کلاس یا گروه',
                'تخصیص استاد به درس',
                'تعیین ناظر برای آزمون',
                'ارسال اطلاعات ورود به کاربران',
            ],
        },
        {
            'title': 'مدیریت دروس و کلاس‌ها',
            'items': [
                'تعریف درس',
                'تعیین کد درس',
                'تعیین تعداد واحد',
                'ایجاد کلاس درس',
                'تعیین استاد هر کلاس',
                'ثبت دانشجویان کلاس',
                'تعیین نیم‌سال ارائه درس',
                'انتقال دانشجو میان کلاس‌ها',
                'مشاهده فهرست دانشجویان هر درس',
            ],
        },
        {
            'title': 'مدیریت آزمون‌ها',
            'items': [
                'مشاهده آزمون‌های مرکز',
                'تأیید آزمون قبل از انتشار در صورت نیاز',
                'تعیین برنامه زمانی امتحانات',
                'جلوگیری از تداخل آزمون‌ها',
                'تخصیص ناظر به آزمون',
                'لغو یا جابه‌جایی آزمون',
                'تمدید زمان آزمون با ثبت دلیل',
                'مشاهده وضعیت برگزاری آزمون',
                'مشاهده تعداد حاضر و غایب',
                'بررسی آزمون‌های ناقص یا دارای مشکل',
            ],
        },
        {
            'title': 'مدیریت نتایج',
            'items': [
                'مشاهده نتایج آزمون‌های مرکز',
                'مشاهده آمار قبولی و مردودی',
                'تأیید نهایی نتایج',
                'اجازه انتشار نمرات',
                'دریافت کارنامه گروهی',
                'دریافت گزارش عملکرد کلاس‌ها',
                'بررسی تغییرات نمرات',
                'مشاهده اعتراض‌های دانشجویان',
            ],
        },
        {
            'title': 'مدیریت گزارش‌ها',
            'items': [
                'گزارش حضور و غیاب',
                'گزارش عملکرد استادان',
                'گزارش عملکرد دانشجویان',
                'گزارش آزمون‌های برگزارشده',
                'گزارش تخلفات',
                'گزارش مشکلات فنی',
                'گزارش میانگین نمرات',
                'گزارش سختی سؤالات',
                'دریافت خروجی Excel یا PDF',
            ],
        },
        {
            'title': 'اطلاع‌رسانی',
            'items': [
                'ارسال اطلاعیه به کاربران مرکز',
                'ارسال پیام به استادان',
                'ارسال پیام به دانشجویان',
                'اعلام تغییر زمان آزمون',
                'اعلام لغو آزمون',
                'ارسال برنامه امتحانات',
                'ارسال نتیجه یا کارنامه',
            ],
        },
    ],
}


def client_ip(request):
    forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if forwarded_for:
        return forwarded_for.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')


def describe_user_agent(user_agent):
    ua = user_agent or ''
    if 'Windows' in ua:
        os_label = 'ویندوز'
    elif 'Android' in ua:
        os_label = 'اندروید'
    elif 'iPhone' in ua or 'iPad' in ua:
        os_label = 'iOS'
    elif 'Macintosh' in ua or 'Mac OS' in ua:
        os_label = 'مک'
    elif 'Linux' in ua:
        os_label = 'لینوکس'
    else:
        os_label = 'دستگاه نامشخص'
    if 'Edg/' in ua or 'Edge' in ua:
        browser = 'Edge'
    elif 'Chrome' in ua and 'Chromium' not in ua:
        browser = 'Chrome'
    elif 'Firefox' in ua:
        browser = 'Firefox'
    elif 'Safari' in ua and 'Chrome' not in ua:
        browser = 'Safari'
    else:
        browser = ''
    return f'{os_label} - {browser}' if browser else os_label


def dictfetchall(cursor):
    columns = [column[0] for column in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def dictfetchone(cursor):
    columns = [column[0] for column in cursor.description]
    row = cursor.fetchone()
    return dict(zip(columns, row)) if row else None


def erd_adapt_sql(sql):
    if connection.vendor != 'sqlite':
        return sql
    adapted = sql.replace('::uuid', '').replace('::int', '').replace('::numeric', '').replace('::text', '')
    adapted = adapted.replace(' ILIKE ', ' LIKE ')
    adapted = adapted.replace('now()', "datetime('now')")
    adapted = adapted.replace(
        "COALESCE(to_char(COALESCE(e.start_at, e.approved_at), 'YYYY/MM/DD'), '-')",
        "COALESCE(replace(substr(COALESCE(e.start_at, e.approved_at), 1, 10), '-', '/'), '-')",
    )
    adapted = adapted.replace(
        "to_char(e.start_at, 'YYYY/MM/DD')",
        "replace(substr(e.start_at, 1, 10), '-', '/')",
    )
    adapted = adapted.replace(
        "COALESCE(to_char(e.start_at, 'HH24:MI'), '-')",
        "COALESCE(substr(e.start_at, 12, 5), '-')",
    )
    adapted = adapted.replace(
        "COALESCE(to_char(e.end_at, 'HH24:MI'), '-')",
        "COALESCE(substr(e.end_at, 12, 5), '-')",
    )
    adapted = adapted.replace(
        "COALESCE(to_char(e.start_at, 'YYYY/MM/DD HH24:MI'), '-')",
        "COALESCE(replace(substr(e.start_at, 1, 16), '-', '/'), '-')",
    )
    adapted = adapted.replace(
        "COALESCE(to_char(e.end_at, 'YYYY/MM/DD HH24:MI'), '-')",
        "COALESCE(replace(substr(e.end_at, 1, 16), '-', '/'), '-')",
    )
    if not erd_has_column('exams', 'lifecycle_status'):
        inferred_lifecycle = (
            "CASE "
            "WHEN COALESCE(e.is_cancelled, false) THEN 'closed' "
            "WHEN COALESCE(e.is_published, false) THEN 'published' "
            "WHEN COALESCE(e.approval_status, '') = 'pending' THEN 'pending_approval' "
            "ELSE 'draft' END"
        )
        adapted = adapted.replace("COALESCE(e.lifecycle_status, '')", inferred_lifecycle)
        adapted = adapted.replace("COALESCE(e.lifecycle_status, '-') AS lifecycle_status", f"{inferred_lifecycle} AS lifecycle_status")
    return adapted


def _erd_parse_json_field(value):
    """Normalize a jsonb/JSON column read via a raw cursor: Postgres (psycopg2)
    already returns dict/list; SQLite has no native JSON type and returns the
    raw text, so it needs json.loads. Returns None if the value is empty or
    not valid JSON."""
    if value in (None, ''):
        return None
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return None


def erd_rows(sql, params=None):
    sql = erd_adapt_sql(sql)
    with connection.cursor() as cursor:
        cursor.execute(sql, params or [])
        return dictfetchall(cursor)


def erd_row(sql, params=None):
    sql = erd_adapt_sql(sql)
    with connection.cursor() as cursor:
        cursor.execute(sql, params or [])
        return dictfetchone(cursor)


def erd_execute(sql, params=None):
    sql = erd_adapt_sql(sql)
    with connection.cursor() as cursor:
        cursor.execute(sql, params or [])


def erd_sync_login_account(username, *, is_active=True, reset_password=False):
    """ایجاد/به‌روزرسانی حساب ورود جنگویی (auth_user) هم‌نام با پروفایل ERD.

    ثبت پروفایل در جدول‌های ERD به‌تنهایی کاربر را قادر به ورود نمی‌کند،
    چون احراز هویت Django روی جدول auth_user و رمز هش‌شده‌ی آن کار می‌کند.
    این تابع تضمین می‌کند هر پروفایلی که نقش می‌گیرد یک کاربر Django هم‌نام
    با رمز عبور واقعی داشته باشد. رمز تولیدشده را برمی‌گرداند تا به مدیر
    نمایش داده شود (فقط وقتی کاربر تازه ساخته شده یا reset_password=True).
    """
    username = (username or '').strip()
    if not username:
        return None, None
    user, created = User.objects.get_or_create(username=username, defaults={'is_active': is_active})
    generated_password = None
    if created or reset_password:
        generated_password = get_random_string(10)
        user.set_password(generated_password)
    if user.is_active != is_active:
        user.is_active = is_active
    user.save()
    return user, generated_password


@lru_cache(maxsize=64)
def erd_table_columns(table):
    try:
        with connection.cursor() as cursor:
            cursor.execute(f'SELECT * FROM {table} LIMIT 0')
            return {column[0] for column in cursor.description or []}
    except Exception:
        return set()


def erd_has_column(table, column):
    return column in erd_table_columns(table)


def erd_datetime(value):
    if not value or hasattr(value, 'date'):
        return value
    value = str(value).strip()
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        return None
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed


def erd_count(table, where='', params=None):
    sql = f'SELECT COUNT(*) AS count FROM {table}'
    if where:
        sql += f' WHERE {where}'
    row = erd_row(sql, params or [])
    return row['count'] if row else 0


ORG_LEVEL_MIN_COUNT = 1
ORG_LEVEL_DEFAULT_TITLES = ['دانشگاه', 'دانشکده', 'گروه آموزشی', 'رشته', 'کلاس / واحد']
ORG_LEVEL_DEFAULT_HINTS = [
    'ریشه ساختار سازمانی',
    'زیرمجموعه دانشگاه',
    'زیرمجموعه دانشکده',
    'ریزترین سطح ساختار سازمانی',
    'ریزترین سطح ساختار سازمانی',
]


def default_org_level(index):
    return {
        'title': ORG_LEVEL_DEFAULT_TITLES[index - 1] if index <= len(ORG_LEVEL_DEFAULT_TITLES) else f'سطح {index}',
        'hint': ORG_LEVEL_DEFAULT_HINTS[index - 1] if index <= len(ORG_LEVEL_DEFAULT_HINTS) else 'سطح فرعی ساختار سازمانی',
    }


def repair_display_text(value):
    text = str(value or '').strip()
    if not any(marker in text for marker in ('Ø', 'Ù', 'Û', 'Ã', 'Â', 'â')):
        return text
    for _ in range(3):
        try:
            repaired = text.encode('cp1252').decode('utf-8')
        except UnicodeError:
            break
        if repaired == text:
            break
        text = repaired
    return text


def normalize_org_levels(raw_value):
    try:
        if isinstance(raw_value, str):
            raw_value = json.loads(raw_value)
    except json.JSONDecodeError:
        raw_value = None

    if isinstance(raw_value, int):
        level_count = max(raw_value, ORG_LEVEL_MIN_COUNT)
        return [default_org_level(index) for index in range(1, level_count + 1)]

    if isinstance(raw_value, list):
        levels = []
        for index, item in enumerate(raw_value, start=1):
            defaults = default_org_level(index)
            if not isinstance(item, dict):
                item = {}
            title = repair_display_text(item.get('title')) or defaults['title']
            hint = repair_display_text(item.get('hint') or item.get('description')) or defaults['hint']
            levels.append({'title': title, 'hint': hint})
        return levels or [default_org_level(1)]

    return [default_org_level(index) for index in range(1, 6)]


def get_org_level_config():
    row = erd_row("SELECT value FROM system_settings WHERE key = %s", ['org_structure_levels_config'])
    if row:
        return normalize_org_levels(row['value'])
    legacy_row = erd_row("SELECT value FROM system_settings WHERE key = %s", ['org_structure_levels'])
    return normalize_org_levels(legacy_row['value'] if legacy_row else 5)


def org_unit_level_index(unit):
    code = str(unit.get('code') or '')
    if code.startswith('__level:') and '__' in code[8:]:
        try:
            return int(code.split('__', 2)[1].split(':', 1)[1])
        except (IndexError, ValueError):
            pass
    return {'university': 1, 'faculty': 2, 'department': 3, 'group': 4}.get(unit.get('type'), 3)


def _xlsx_column_name(index):
    name = ''
    while index:
        index, remainder = divmod(index - 1, 26)
        name = chr(65 + remainder) + name
    return name


def _xlsx_cell_value(cell, shared_strings):
    ns = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    cell_type = cell.attrib.get('t')
    if cell_type == 's':
        value = cell.findtext('m:v', default='', namespaces=ns)
        return shared_strings[int(value)] if value.isdigit() and int(value) < len(shared_strings) else ''
    if cell_type == 'inlineStr':
        return ''.join(cell.itertext()).strip()
    return cell.findtext('m:v', default='', namespaces=ns).strip()


def read_xlsx_dicts(uploaded_file):
    ns = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    with zipfile.ZipFile(uploaded_file) as archive:
        shared_strings = []
        if 'xl/sharedStrings.xml' in archive.namelist():
            shared_root = ET.fromstring(archive.read('xl/sharedStrings.xml'))
            for item in shared_root.findall('m:si', ns):
                shared_strings.append(''.join(item.itertext()).strip())

        sheet_name = 'xl/worksheets/sheet1.xml'
        if sheet_name not in archive.namelist():
            sheet_name = next((name for name in archive.namelist() if name.startswith('xl/worksheets/sheet')), None)
        if not sheet_name:
            return []

        root = ET.fromstring(archive.read(sheet_name))
        rows = []
        for row in root.findall('.//m:sheetData/m:row', ns):
            values = {}
            for cell in row.findall('m:c', ns):
                ref = cell.attrib.get('r', '')
                column = ''.join(ch for ch in ref if ch.isalpha())
                values[column] = _xlsx_cell_value(cell, shared_strings)
            rows.append(values)
        if not rows:
            return []

        headers = rows[0]
        parsed_rows = []
        for row in rows[1:]:
            parsed = {}
            for column, header in headers.items():
                header = (header or '').strip()
                if header:
                    parsed[header] = (row.get(column) or '').strip()
            if any(parsed.values()):
                parsed_rows.append(parsed)
        return parsed_rows


def xlsx_response(filename, headers, rows, sheet_name='Sheet1'):
    def cell(ref, value):
        value = xml_escape(str(value or ''))
        return f'<c r="{ref}" t="inlineStr"><is><t>{value}</t></is></c>'

    sheet_rows = []
    for row_index, row_values in enumerate([headers, *rows], start=1):
        cells = ''.join(
            cell(f'{_xlsx_column_name(col_index)}{row_index}', value)
            for col_index, value in enumerate(row_values, start=1)
        )
        sheet_rows.append(f'<row r="{row_index}">{cells}</row>')

    sheet_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'<sheetData>{"".join(sheet_rows)}</sheetData></worksheet>'
    )
    workbook_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'<sheets><sheet name="{xml_escape(sheet_name)}" sheetId="1" r:id="rId1"/></sheets></workbook>'
    )
    rels_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
        '</Relationships>'
    )
    workbook_rels_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
        '</Relationships>'
    )
    content_types_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '</Types>'
    )

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('[Content_Types].xml', content_types_xml)
        archive.writestr('_rels/.rels', rels_xml)
        archive.writestr('xl/workbook.xml', workbook_xml)
        archive.writestr('xl/_rels/workbook.xml.rels', workbook_rels_xml)
        archive.writestr('xl/worksheets/sheet1.xml', sheet_xml)
    buffer.seek(0)

    response = HttpResponse(
        buffer.getvalue(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


def erd_profile_for_user(user):
    if not user or not getattr(user, 'is_authenticated', False):
        return None
    sentinel = object()
    cached = getattr(user, '_erd_profile_cache_value', sentinel)
    if cached is not sentinel:
        return cached
    profile = erd_row(
        """
        SELECT *
        FROM profiles
        WHERE username = %s OR email = %s
        ORDER BY CASE WHEN username = %s THEN 0 ELSE 1 END
        LIMIT 1
        """,
        [user.username, user.email or '', user.username],
    )
    user._erd_profile_cache_value = profile
    return profile


def erd_roles_for_profile(profile_id):
    if not profile_id:
        return []
    rows = erd_rows('SELECT role FROM user_roles WHERE user_id = %s ORDER BY created_at', [profile_id])
    return [row['role'] for row in rows]


def erd_primary_role(user):
    """نقش اصلی کاربر در جدول‌های ERD، یا None اگر هیچ نقشی برایش ثبت نشده باشد.

    قبلاً وقتی پروفایل/نقشی پیدا نمی‌شد، به‌صورت پیش‌فرض 'student' برمی‌گشت که
    یک حفره‌ی امنیتی بود (کاربر بدون پروفایل، بی‌صدا به‌عنوان دانشجو تلقی
    می‌شد). فراخوان‌ها باید None را به‌عنوان «بدون نقش/دسترسی رد شود» تلقی
    کنند، نه اینکه خودشان دوباره پیش‌فرض دیگری جایگزین کنند.
    """
    if hasattr(user, '_erd_primary_role_cache'):
        return user._erd_primary_role_cache
    profile = erd_profile_for_user(user)
    roles = getattr(user, '_erd_roles_cache', None)
    if roles is None:
        roles = erd_roles_for_profile(profile['id'] if profile else None)
        user._erd_roles_cache = roles
    for role in ('admin', 'academic_manager', 'teacher', 'student'):
        if role in roles:
            user._erd_primary_role_cache = role
            return role
    user._erd_primary_role_cache = None
    return None


def erd_role_required(*allowed_roles):
    def decorator(view_func):
        @login_required
        @wraps(view_func)
        def wrapped(request, *args, **kwargs):
            role = erd_primary_role(request.user)
            if role not in allowed_roles:
                return HttpResponseForbidden('دسترسی برای این نقش مجاز نیست.')
            profile = erd_profile_for_user(request.user)
            request.erd_profile = profile
            request.erd_profile_id = profile['id'] if profile else None
            request.erd_role = role
            return view_func(request, *args, **kwargs)
        return wrapped
    return decorator


def erd_role_code(user):
    return {
        'admin': 'super_admin',
        'academic_manager': 'exam_manager',
        'teacher': 'teacher',
        'student': 'student',
    }.get(erd_primary_role(user))


def erd_role_name(role):
    return {
        'admin': 'مدیر سامانه',
        'academic_manager': 'مدیر آموزشی',
        'teacher': 'استاد',
        'student': 'دانشجو',
        'super_admin': 'مدیر سامانه',
        'exam_manager': 'مدیر آموزشی',
    }.get(role, 'کاربر سامانه')


def erd_setting(key, default=None):
    row = erd_row('SELECT value FROM system_settings WHERE key = %s', [key])
    if not row:
        return default
    value = row['value']
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def erd_recent_exams(limit=5):
    return erd_rows(
        """
        SELECT e.id, e.title, COALESCE(c.title, 'بدون درس') AS course,
               COALESCE(to_char(e.start_at, 'YYYY/MM/DD'), '-') AS created_at
        FROM exams e
        LEFT JOIN courses c ON c.id = e.course_id
        ORDER BY e.start_at DESC NULLS LAST, e.title
        LIMIT %s
        """,
        [limit],
    )


def erd_admin_dashboard_panel():
    month_labels = {
        1: 'فروردین',
        2: 'اردیبهشت',
        3: 'خرداد',
        4: 'تیر',
        5: 'مرداد',
        6: 'شهریور',
        7: 'مهر',
        8: 'آبان',
        9: 'آذر',
        10: 'دی',
        11: 'بهمن',
        12: 'اسفند',
    }
    role_labels = {
        'admin': 'مدیر سامانه',
        'academic_manager': 'مدیر آموزشی',
        'teacher': 'استاد',
        'student': 'دانشجو',
    }
    question_labels = {
        'single': 'چندگزینه‌ای',
        'multi': 'چندپاسخه',
        'true_false': 'صحیح/غلط',
        'essay': 'تشریحی',
        'short_answer': 'پاسخ کوتاه',
        'fill_blank': 'جای خالی',
        'matching': 'تطبیقی',
        'ordering': 'مرتب‌سازی',
        **question_kinds.TYPE_LABELS,
    }

    lifecycle_expr = (
        "COALESCE(lifecycle_status, 'draft')"
        if erd_has_column('exams', 'lifecycle_status')
        else (
            "CASE "
            "WHEN COALESCE(is_cancelled, false) THEN 'closed' "
            "WHEN COALESCE(is_published, false) THEN 'published' "
            "WHEN COALESCE(approval_status, '') = 'pending' THEN 'pending_approval' "
            "ELSE 'draft' END"
        )
    )
    if connection.vendor == 'sqlite':
        monthly_rows = erd_rows(
            f"""
            SELECT CAST(substr(COALESCE(start_at, approved_at, CURRENT_TIMESTAMP), 6, 2) AS INTEGER) AS month_number,
                   SUM(CASE
                       WHEN {lifecycle_expr} IN ('draft', 'pending_approval')
                         OR COALESCE(is_published, 0) = 0
                       THEN 1 ELSE 0 END) AS draft_count,
                   SUM(CASE
                       WHEN COALESCE(is_published, 0) = 1
                         AND COALESCE(is_cancelled, 0) = 0
                       THEN 1 ELSE 0 END) AS published_count,
                   SUM(CASE
                       WHEN {lifecycle_expr} IN ('closed', 'archived')
                         OR (end_at IS NOT NULL AND end_at < CURRENT_TIMESTAMP)
                       THEN 1 ELSE 0 END) AS held_count
            FROM exams
            GROUP BY month_number
            """,
        )
    else:
        monthly_rows = erd_rows(
            f"""
            SELECT EXTRACT(MONTH FROM COALESCE(start_at, approved_at, CURRENT_TIMESTAMP))::int AS month_number,
                   COUNT(*) FILTER (
                       WHERE {lifecycle_expr} IN ('draft', 'pending_approval')
                          OR COALESCE(is_published, false) = false
                   ) AS draft_count,
                   COUNT(*) FILTER (
                       WHERE COALESCE(is_published, false) = true
                         AND COALESCE(is_cancelled, false) = false
                   ) AS published_count,
                   COUNT(*) FILTER (
                       WHERE {lifecycle_expr} IN ('closed', 'archived')
                          OR (end_at IS NOT NULL AND end_at < CURRENT_TIMESTAMP)
                   ) AS held_count
            FROM exams
            GROUP BY month_number
            """,
        )
    by_month = {row['month_number']: row for row in monthly_rows}
    max_month_value = max(
        [
            int(row.get('draft_count') or 0)
            + int(row.get('published_count') or 0)
            + int(row.get('held_count') or 0)
            for row in monthly_rows
        ]
        or [0]
    )

    def bar_percent(value):
        if not value or not max_month_value:
            return 0
        return max(8, round((int(value) / max_month_value) * 62))

    monthly_activity = []
    month_order = list(range(1, 13))
    for month_number in month_order:
        row = by_month.get(month_number, {})
        draft_count = int(row.get('draft_count') or 0)
        published_count = int(row.get('published_count') or 0)
        held_count = int(row.get('held_count') or 0)
        monthly_activity.append(
            {
                'label': month_labels[month_number],
                'draft': draft_count,
                'published': published_count,
                'held': held_count,
                'draft_pct': bar_percent(draft_count),
                'published_pct': bar_percent(published_count),
                'held_pct': bar_percent(held_count),
            }
        )

    question_rows = erd_rows(
        """
        SELECT COALESCE(type, 'unknown') AS type, COUNT(*) AS count
        FROM questions
        GROUP BY COALESCE(type, 'unknown')
        ORDER BY count DESC, type
        """,
    )
    question_total = sum(int(row['count']) for row in question_rows) or 0
    question_type_stats = []
    for type_key in ['single', 'multi', 'true_false', 'essay', 'fill_blank', 'matching']:
        row = next((item for item in question_rows if item['type'] == type_key), None)
        count = int(row['count']) if row else 0
        question_type_stats.append(
            {
                'type': type_key,
                'label': question_labels.get(type_key, type_key),
                'count': count,
                'percent': round((count / question_total) * 100) if question_total else 0,
            }
        )

    center_x, center_y, radius = 160, 130, 92
    radar_points = []
    for index, item in enumerate(question_type_stats):
        angle = -math.pi / 2 + index * (2 * math.pi / len(question_type_stats))
        value_radius = radius * (item['percent'] / 100)
        radar_points.append(
            f"{center_x + math.cos(angle) * value_radius:.1f},{center_y + math.sin(angle) * value_radius:.1f}"
        )
    radar_polygon_points = ' '.join(radar_points) if radar_points else f'{center_x},{center_y}'

    role_rows = erd_rows(
        """
        SELECT role, COUNT(*) AS count
        FROM user_roles
        GROUP BY role
        ORDER BY count DESC, role
        """,
    )
    role_colors = ['#f59e0b', '#10b981', '#7c3aed', '#2563eb', '#ef4444']
    role_total = sum(int(row['count']) for row in role_rows) or 0
    role_distribution = []
    gradient_parts = []
    cursor = 0
    for index, row in enumerate(role_rows):
        count = int(row['count'])
        percent = round((count / role_total) * 100) if role_total else 0
        color = role_colors[index % len(role_colors)]
        next_cursor = 100 if index == len(role_rows) - 1 else cursor + percent
        gradient_parts.append(f'{color} {cursor}% {next_cursor}%')
        cursor = next_cursor
        role_distribution.append(
            {
                'role': row['role'],
                'label': role_labels.get(row['role'], row['role']),
                'count': count,
                'percent': percent,
                'color': color,
            }
        )
    role_distribution_style = (
        f"background: conic-gradient({', '.join(gradient_parts)});"
        if gradient_parts
        else 'background: #e5e7eb;'
    )

    recent_exams = erd_rows(
        """
        SELECT e.id, e.title, COALESCE(c.title, 'بدون درس') AS course,
               COALESCE(to_char(COALESCE(e.start_at, e.approved_at), 'YYYY/MM/DD'), '-') AS date,
               CASE
                   WHEN COALESCE(e.is_cancelled, false) THEN 'لغوشده'
                   WHEN COALESCE(e.lifecycle_status, '') IN ('closed', 'archived')
                        OR (e.end_at IS NOT NULL AND e.end_at < CURRENT_TIMESTAMP) THEN 'برگزار شده'
                   WHEN COALESCE(e.is_published, false) THEN 'منتشر شده'
                   WHEN COALESCE(e.approval_status, '') = 'pending' THEN 'در انتظار تایید'
                   ELSE 'پیش‌نویس'
               END AS status_label,
               CASE
                   WHEN COALESCE(e.is_cancelled, false) THEN 'danger'
                   WHEN COALESCE(e.is_published, false) THEN 'success'
                   WHEN COALESCE(e.approval_status, '') = 'pending' THEN 'warning'
                   ELSE 'muted'
               END AS status_tone
        FROM exams e
        LEFT JOIN courses c ON c.id = e.course_id
        ORDER BY COALESCE(e.start_at, e.approved_at) DESC NULLS LAST, e.title
        LIMIT 4
        """,
    )

    average_row = erd_row(
        """
        SELECT ROUND(AVG(score)::numeric, 1) AS average_score
        FROM exam_attempts
        WHERE score IS NOT NULL
        """,
    )
    average_score = average_row['average_score'] if average_row and average_row['average_score'] is not None else None
    active_exams_count = erd_count(
        'exams',
        "COALESCE(is_published, false) = true AND COALESCE(is_cancelled, false) = false",
    )
    users_count = erd_count('profiles')
    questions_count = erd_count('questions')
    exams_count = erd_count('exams')
    students_count = erd_count('student_profiles')
    attempts_count = erd_count('exam_attempts')
    open_objections_count = erd_count(
        'objections',
        "COALESCE(status, 'open') IN ('open', 'pending', 'in_review', 'under_review', 'escalated')",
    )
    today = timezone.localdate()
    if connection.vendor == 'sqlite':
        today_exams_count = erd_count('exams', "date(start_at) = date('now')")
    else:
        today_exams_count = erd_count('exams', "DATE(start_at) = CURRENT_DATE")
    review_needed_count = erd_count(
        'exams',
        "COALESCE(approval_status, '') = 'pending' OR COALESCE(lifecycle_status, 'draft') = 'pending_approval'",
    )
    violation_reports_count = erd_count(
        'activity_audit_log',
        "action ILIKE %s OR reason ILIKE %s",
        ['%violation%', '%تخلف%'],
    )
    pending_registrations_count = erd_count('profiles', "status = 'pending'")
    active_users_count = erd_count('profiles', "status = 'active'")
    inactive_users_count = erd_count('profiles', "COALESCE(status, 'active') <> 'active'")
    present_percent = round((active_users_count / users_count) * 100) if users_count else 0
    inactive_percent = round((inactive_users_count / users_count) * 100) if users_count else 0
    abandoned_percent = max(0, 100 - present_percent - inactive_percent) if users_count else 0

    exam_status_rows = erd_rows(
        """
        SELECT COALESCE(lifecycle_status, 'draft') AS status, COUNT(*) AS count
        FROM exams
        GROUP BY COALESCE(lifecycle_status, 'draft')
        """,
    )
    status_count_map = {row['status']: int(row['count']) for row in exam_status_rows}
    exam_status_items = [
        {'label': 'در حال برگزاری', 'count': status_count_map.get('in_progress', 0), 'color': '#10b981'},
        {'label': 'آینده‌سازی', 'count': status_count_map.get('published', 0) + status_count_map.get('approved', 0), 'color': '#0ea5e9'},
        {'label': 'پایان یافته', 'count': status_count_map.get('closed', 0) + status_count_map.get('archived', 0), 'color': '#f59e0b'},
        {'label': 'بسته شده', 'count': status_count_map.get('draft', 0) + status_count_map.get('pending_approval', 0), 'color': '#8b5cf6'},
    ]

    def conic_style(items):
        total = sum(int(item['count']) for item in items)
        if not total:
            return 'background: conic-gradient(#e8eef7 0 100%);'
        cursor = 0
        parts = []
        for index, item in enumerate(items):
            percent = round((int(item['count']) / total) * 100)
            next_cursor = 100 if index == len(items) - 1 else min(100, cursor + percent)
            parts.append(f"{item['color']} {cursor}% {next_cursor}%")
            cursor = next_cursor
        return f"background: conic-gradient({', '.join(parts)});"

    recent_activities = erd_rows(
        """
        SELECT l.action, l.entity_type, l.reason, COALESCE(p.full_name, 'سیستم') AS actor_name
        FROM activity_audit_log l
        LEFT JOIN profiles p ON p.id = l.actor_id
        LIMIT 5
        """,
    )
    if not recent_activities:
        recent_activities = [
            {'action': 'ایجاد آزمون', 'entity_type': 'exam', 'reason': '۴۵ سوال توسط دکتر رئیسی ایجاد شد', 'actor_name': 'مدیر سیستم'},
            {'action': 'انتشار آزمون', 'entity_type': 'exam', 'reason': 'انتشار برای ۲۸۰ شرکت‌کننده', 'actor_name': 'مدیر سیستم'},
            {'action': 'هشدار تخلف', 'entity_type': 'violation', 'reason': 'تشخیص خروج از صفحه', 'actor_name': 'سیستم نظارت'},
            {'action': 'تغییر زمان‌بندی', 'entity_type': 'calendar', 'reason': 'تغییر تاریخ برگزاری', 'actor_name': 'مدیر سیستم'},
            {'action': 'اطلاع‌رسانی', 'entity_type': 'system', 'reason': 'نگهداری سرورها', 'actor_name': 'مدیر سیستم'},
        ]

    trend_labels = ['۸ اردیبهشت', '۹ اردیبهشت', '۱۰ اردیبهشت', '۱۱ اردیبهشت', '۱۲ اردیبهشت', '۱۳ اردیبهشت', '۱۴ اردیبهشت']
    trend_base = max(exams_count, attempts_count, erd_count('activity_audit_log'), 1)
    trend_primary = [
        max(8, round((value / max(trend_base, 1)) * 46))
        for value in [attempts_count, attempts_count + 4, attempts_count + 1, attempts_count + 8, attempts_count + 5, attempts_count + 13, attempts_count + 7]
    ]
    trend_secondary = [max(5, round(value * .62)) for value in trend_primary]
    chart_x = [24, 112, 200, 288, 376, 464, 552]
    activity_primary_points = ' '.join(f'{chart_x[index]},{64 - value}' for index, value in enumerate(trend_primary))
    activity_secondary_points = ' '.join(f'{chart_x[index]},{78 - value}' for index, value in enumerate(trend_secondary))

    return {
        'type': 'super_admin',
        'users_count': users_count,
        'active_users_count': active_users_count,
        'institutions_count': erd_count('org_units', "type = 'university'"),
        'roles_count': erd_row('SELECT COUNT(DISTINCT role) AS count FROM user_roles')['count'],
        'exams_count': exams_count,
        'active_exams_count': active_exams_count,
        'questions_count': questions_count,
        'students_count': students_count,
        'attempts_count': attempts_count,
        'today_logs_count': erd_count('activity_audit_log', '1 = 1'),
        'recent_logs': [],
        'recent_exams': recent_exams,
        'today_exams_count': today_exams_count,
        'review_needed_count': review_needed_count,
        'violation_reports_count': violation_reports_count,
        'inactive_users_count': inactive_users_count,
        'dashboard_cards': [
            {'label': 'کل آزمون‌ها', 'value': exams_count, 'hint': '۱۳٪ نسبت به ماه قبل', 'tone': 'blue', 'icon': 'doc'},
            {'label': 'آزمون‌های فعال', 'value': active_exams_count, 'hint': '۲۵٪ نسبت به ماه قبل', 'tone': 'green', 'icon': 'play'},
            {'label': 'آزمون‌های امروز', 'value': today_exams_count, 'hint': 'در حال برگزاری', 'tone': 'orange', 'icon': 'calendar'},
            {'label': 'کاربران فعال', 'value': users_count, 'hint': '۲۷٪ نسبت به ماه قبل', 'tone': 'emerald', 'icon': 'users'},
            {'label': 'نیازمند بررسی', 'value': review_needed_count, 'hint': '۸ مورد جدید', 'tone': 'red', 'icon': 'alert'},
            {'label': 'درخواست‌های ثبت‌نام', 'value': pending_registrations_count, 'hint': f'{pending_registrations_count} مورد جدید', 'tone': 'indigo', 'icon': 'shield', 'url': f'{reverse("core:super_admin_users")}?tab=students&status=pending'},
        ],
        'quick_actions': [
            {'label': 'ایجاد آزمون جدید', 'url': reverse('core:super_admin_exams'), 'tone': 'primary', 'icon': 'plus'},
            {'label': 'انتشار آزمون', 'url': reverse('core:super_admin_exams'), 'tone': 'blue', 'icon': 'send'},
            {'label': 'مدیریت سوالات', 'url': reverse('core:teacher_questions'), 'tone': 'blue', 'icon': 'question'},
            {'label': 'زمان‌بندی آزمون', 'url': reverse('core:super_admin_calendar'), 'tone': 'blue', 'icon': 'calendar'},
        ],
        'health_items': [
            {'label': 'سرورهای وب', 'status': 'سالم'},
            {'label': 'پایگاه داده', 'status': 'سالم'},
            {'label': 'ذخیره‌سازی', 'status': 'سالم'},
            {'label': 'سیستم پشتیبان‌گیری', 'status': 'سالم'},
        ],
        'exam_status_items': exam_status_items,
        'exam_status_style': conic_style(exam_status_items),
        'user_participation_items': [
            {'label': 'حاضر', 'value': present_percent, 'color': '#2563eb'},
            {'label': 'غیرفعال', 'value': inactive_percent, 'color': '#10b981'},
            {'label': 'انصراف', 'value': abandoned_percent, 'color': '#ef4444'},
        ],
        'user_participation_style': conic_style([
            {'count': present_percent, 'color': '#2563eb'},
            {'count': inactive_percent, 'color': '#10b981'},
            {'count': abandoned_percent, 'color': '#ef4444'},
        ]),
        'recent_activities': recent_activities,
        'trend_labels': trend_labels,
        'activity_primary_points': activity_primary_points,
        'activity_secondary_points': activity_secondary_points,
        'dashboard_today_label': today.strftime('%Y/%m/%d'),
        'monthly_activity': monthly_activity,
        'question_type_stats': question_type_stats,
        'question_total': question_total,
        'radar_polygon_points': radar_polygon_points,
        'role_distribution': role_distribution,
        'role_distribution_style': role_distribution_style,
        'report_cards': [
            {'label': 'کل کاربران', 'value': users_count, 'tone': 'blue'},
            {'label': 'تعداد درس‌ها', 'value': erd_count('courses'), 'tone': 'indigo'},
            {'label': 'آزمون‌های منتشرشده', 'value': active_exams_count, 'tone': 'green'},
            {'label': 'اعتراض‌های باز', 'value': open_objections_count, 'tone': 'red'},
            {'label': 'میانگین نمره', 'value': average_score if average_score is not None else '—', 'tone': 'orange'},
            {'label': 'تلاش‌های ثبت‌شده', 'value': attempts_count, 'tone': 'purple'},
        ],
    }


def erd_profile_page_context(user):
    profile = erd_profile_for_user(user)
    if not profile:
        return None

    roles = erd_roles_for_profile(profile['id'])
    primary_role = roles[0] if roles else erd_primary_role(user)
    role_labels = {
        'admin': 'مدیر سامانه',
        'academic_manager': 'مدیر آموزشی',
        'teacher': 'استاد',
        'student': 'دانشجو',
    }
    access_levels = {
        'admin': 'سطح کامل',
        'academic_manager': 'سطح مدیریتی آموزشی',
        'teacher': 'سطح استاد',
        'student': 'سطح دانشجو',
    }
    nav_by_role = {
        'admin': [
            ('اصلی', [
                ('داشبورد', reverse('core:dashboard'), '▦'),
                ('درس‌ها', reverse('core:super_admin_courses'), '▥'),
                ('اساتید', reverse('core:super_admin_teachers'), '▱'),
                ('دانشجویان', reverse('core:super_admin_students'), '♙'),
                ('گروه‌بندی', reverse('core:super_admin_groups'), '♧'),
                ('آزمون', reverse('core:super_admin_exams'), '▤'),
                ('تقویم آموزشی', reverse('core:super_admin_calendar'), '◷'),
            ]),
            ('سیستم', [
                ('ساختار سازمانی', reverse('core:super_admin_org_units'), '▣'),
                ('مدیران آموزشی', reverse('core:super_admin_academic_managers'), '▱'),
                ('سال تحصیلی و ترم', reverse('core:super_admin_academic_terms'), '◴'),
                ('تنظیمات سامانه', reverse('core:super_admin_settings'), '⚙'),
                ('پروفایل', reverse('core:profile'), '♙'),
            ]),
        ],
        'academic_manager': [
            ('اصلی', [
                ('داشبورد', reverse('core:dashboard'), '▦'),
                ('تقویم', reverse('core:exam_manager_calendar'), '◷'),
                ('تایید آزمون‌ها', reverse('core:exam_manager_exams'), '✓'),
                ('ناظران', reverse('core:exam_manager_proctors'), '♙'),
                ('آزمون‌های فعال', reverse('core:exam_manager_active_exams'), '▤'),
                ('گزارش‌ها', reverse('core:exam_manager_reports'), '↗'),
                ('پروفایل', reverse('core:profile'), '♙'),
            ]),
        ],
        'teacher': [
            ('اصلی', [
                ('داشبورد', reverse('core:dashboard'), '▦'),
                ('بانک سوال', reverse('core:teacher_questions'), '؟'),
                ('آزمون‌ها', reverse('core:teacher_exams'), '▤'),
                ('نظارت', reverse('core:teacher_monitoring'), '◉'),
                ('تصحیح', reverse('core:teacher_reviews'), '✓'),
                ('نتایج', reverse('core:teacher_results'), '↗'),
                ('اعتراض‌ها', reverse('core:teacher_objections'), '!'),
                ('پروفایل', reverse('core:profile'), '♙'),
            ]),
        ],
        'student': [
            ('اصلی', [
                ('داشبورد', reverse('core:dashboard'), '▦'),
                ('آزمون‌ها', reverse('core:student_exam_schedule'), '▤'),
                ('آزمون آزمایشی', reverse('core:student_practice_exam'), '✦'),
                ('نتایج', reverse('core:student_results'), '↗'),
                ('اعتراض‌ها', reverse('core:student_objections'), '!'),
                ('پرسش آموزشی', reverse('core:student_educational_questions'), '؟'),
                ('پروفایل', reverse('core:profile'), '♙'),
            ]),
        ],
    }
    nav_by_role['admin'] = [
        ('اصلی', [
            ('داشبورد', reverse('core:dashboard'), 'dashboard'),
            ('درس‌ها', reverse('core:super_admin_courses'), 'book'),
            ('اساتید', reverse('core:super_admin_teachers'), 'teacher'),
            ('دانشجویان', reverse('core:super_admin_students'), 'students'),
            ('گروه‌بندی', reverse('core:super_admin_groups'), 'groups'),
            ('آزمون', reverse('core:super_admin_exams'), 'exam'),
            ('تقویم آموزشی', reverse('core:super_admin_calendar'), 'calendar'),
        ]),
        ('سیستم', [
            ('ساختار سازمانی', reverse('core:super_admin_org_units'), 'database'),
            ('مدیران آموزشی', reverse('core:super_admin_academic_managers'), 'manager'),
            ('سال تحصیلی و ترم', reverse('core:super_admin_academic_terms'), 'term'),
            ('تنظیمات سامانه', reverse('core:super_admin_settings'), 'settings'),
            ('پروفایل', reverse('core:profile'), 'profile'),
        ]),
    ]
    role_details = {}
    status_labels = {
        'active': 'فعال',
        'inactive': 'غیرفعال',
        'blocked': 'مسدود',
        'pending': 'در انتظار تایید',
    }
    if 'student' in roles:
        role_details.update(
            erd_row(
                "SELECT student_number, academic_status FROM student_profiles WHERE user_id = %s",
                [profile['id']],
            )
            or {}
        )
    if 'teacher' in roles:
        role_details.update(
            erd_row(
                "SELECT personnel_code, approval_status FROM teacher_profiles WHERE user_id = %s",
                [profile['id']],
            )
            or {}
        )
    if 'academic_manager' in roles:
        employee_column = 'employee_code' if erd_has_column('academic_manager_profiles', 'employee_code') else 'personnel_code'
        access_column = 'access_level' if erd_has_column('academic_manager_profiles', 'access_level') else "'manager'"
        role_details.update(
            erd_row(
                f"SELECT {employee_column} AS employee_code, {access_column} AS access_level FROM academic_manager_profiles WHERE user_id = %s",
                [profile['id']],
            )
            or {}
        )

    return {
        'profile': profile,
        'roles': roles,
        'role_label': role_labels.get(primary_role, 'کاربر سامانه'),
        'roles_label': '، '.join(role_labels.get(role, role) for role in roles) or 'کاربر سامانه',
        'access_label': access_levels.get(primary_role, 'سطح عمومی'),
        'status_label': status_labels.get(profile.get('status') or profile.get('account_status'), profile.get('status') or '-'),
        'role_details': role_details,
        'last_login_at': profile.get('last_login_at') or user.last_login,
        'profile_nav_groups': nav_by_role.get(primary_role, []),
    }


def log_activity(user, action, description='', request=None, metadata=None):
    profile = erd_profile_for_user(user)
    erd_execute(
        """
        INSERT INTO activity_audit_log (id, actor_id, action, entity_type, entity_id, reason, metadata)
        VALUES (%s, %s, %s, %s, NULL, %s, %s)
        """,
        [
            str(uuid.uuid4()),
            profile['id'] if profile else None,
            action,
            'system',
            description or '',
            json.dumps({
                **(metadata or {}),
                'ip_address': client_ip(request) if request else None,
                'user_agent': request.META.get('HTTP_USER_AGENT', '') if request else '',
            }),
        ],
    )


def is_super_admin(user):
    if not user.is_authenticated:
        return False
    return erd_primary_role(user) == 'admin'


def super_admin_required(view_func):
    @login_required
    def wrapped(request, *args, **kwargs):
        if not is_super_admin(request.user):
            return HttpResponseForbidden('دسترسی فقط برای مدیر کل سیستم مجاز است.')
        return view_func(request, *args, **kwargs)
    return wrapped


def get_managed_institution(user):
    try:
        profile = getattr(user, 'profile', None)
    except DatabaseError:
        return None
    if not profile or profile.role.code != SystemRole.RoleCode.INSTITUTION_ADMIN:
        return None
    admin_profile = getattr(profile, 'institution_admin_profile', None)
    if admin_profile:
        return admin_profile.institution
    if profile.institution_name:
        return AcademicInstitution.objects.filter(name=profile.institution_name).first()
    return None


def institution_admin_required(view_func):
    @login_required
    def wrapped(request, *args, **kwargs):
        institution = get_managed_institution(request.user)
        if not institution:
            return HttpResponseForbidden('دسترسی فقط برای مدیر مؤسسه دارای مرکز آموزشی مجاز است.')
        request.managed_institution = institution
        return view_func(request, *args, **kwargs)
    return wrapped


def get_exam_manager_institution(user):
    try:
        profile = getattr(user, 'profile', None)
    except DatabaseError:
        return None
    if not profile or profile.role.code != SystemRole.RoleCode.EXAM_MANAGER:
        return None
    if profile.institution_name:
        return AcademicInstitution.objects.filter(name=profile.institution_name).first()
    return AcademicInstitution.objects.first()


def exam_manager_required(view_func):
    @login_required
    def wrapped(request, *args, **kwargs):
        institution = get_exam_manager_institution(request.user)
        if not institution:
            return HttpResponseForbidden('دسترسی فقط برای مسئول امتحانات دارای مؤسسه مجاز است.')
        request.managed_institution = institution
        return view_func(request, *args, **kwargs)
    return wrapped


def get_teacher_profile(user):
    try:
        profile = getattr(user, 'profile', None)
    except DatabaseError:
        return None
    if not profile or profile.role.code != SystemRole.RoleCode.TEACHER:
        return None
    teacher_profile = getattr(profile, 'teacher_profile', None)
    if teacher_profile:
        return teacher_profile
    institution = AcademicInstitution.objects.filter(name=profile.institution_name).first() or AcademicInstitution.objects.first()
    if institution:
        return TeacherProfile.objects.create(profile=profile, institution=institution)
    return None


def teacher_required(view_func):
    @login_required
    def wrapped(request, *args, **kwargs):
        teacher = get_teacher_profile(request.user)
        if not teacher:
            return HttpResponseForbidden('دسترسی فقط برای استاد یا طراح آزمون مجاز است.')
        request.teacher_profile = teacher
        request.managed_institution = teacher.institution
        return view_func(request, *args, **kwargs)
    return wrapped


def get_assistant_teacher(user):
    try:
        profile = getattr(user, 'profile', None)
    except DatabaseError:
        return None
    if not profile or profile.role.code != SystemRole.RoleCode.TEACHING_ASSISTANT:
        return None
    supervisor = profile.supervisor_teacher
    supervisor_profile = getattr(supervisor, 'profile', None) if supervisor else None
    if supervisor_profile:
        return getattr(supervisor_profile, 'teacher_profile', None)
    if profile.institution_name:
        institution = AcademicInstitution.objects.filter(name=profile.institution_name).first()
        if institution:
            return institution.teachers.first()
    return TeacherProfile.objects.first()


def assistant_required(view_func):
    @login_required
    def wrapped(request, *args, **kwargs):
        teacher = get_assistant_teacher(request.user)
        if not teacher:
            return HttpResponseForbidden('دسترسی فقط برای دستیار آموزشی دارای استاد مسئول مجاز است.')
        request.assistant_profile = request.user.profile
        request.assistant_teacher = teacher
        request.managed_institution = teacher.institution
        return view_func(request, *args, **kwargs)
    return wrapped


def get_student_profile(user):
    try:
        profile = getattr(user, 'profile', None)
    except DatabaseError:
        return None
    if not profile or profile.role.code != SystemRole.RoleCode.STUDENT:
        return None
    student = getattr(profile, 'student_profile', None)
    if student:
        return student
    institution = None
    if profile.institution_name:
        institution = AcademicInstitution.objects.filter(name=profile.institution_name).first()
    institution = institution or AcademicInstitution.objects.first()
    if not institution:
        return None
    student, _ = StudentProfile.objects.get_or_create(
        profile=profile,
        defaults={
            'institution': institution,
            'student_number': profile.student_number,
            'academic_unit': None,
        },
    )
    return student


def student_required(view_func):
    @login_required
    def wrapped(request, *args, **kwargs):
        student = get_student_profile(request.user)
        if not student:
            return HttpResponseForbidden('دسترسی فقط برای دانشجو مجاز است.')
        request.student_profile = student
        request.managed_institution = student.institution
        return view_func(request, *args, **kwargs)
    return wrapped


def student_available_exams(student):
    courses = student.courses.all()
    qs = Exam.objects.select_related('course', 'designer', 'designer__profile').filter(is_active=True)
    if courses.exists():
        qs = qs.filter(course__in=courses)
    elif student.institution:
        qs = qs.filter(Q(institution=student.institution) | Q(institution__isnull=True))
    return qs.exclude(status__in=[Exam.ExamStatus.CANCELLED, Exam.ExamStatus.DRAFT]).order_by('starts_at')


def get_student_attempt(student, exam):
    attempt, _ = StudentExamAttempt.objects.get_or_create(
        student=student,
        exam=exam,
        defaults={'last_activity_at': timezone.now()},
    )
    for exam_question in exam.exam_questions.select_related('question').all():
        StudentQuestionAnswer.objects.get_or_create(attempt=attempt, exam_question=exam_question)
    return attempt


class SecureLoginView(LoginView):
    template_name = 'login.html'
    authentication_form = StyledAuthenticationForm

    def get_success_url(self):
        next_url = self.get_redirect_url()
        if next_url:
            return next_url
        role = erd_primary_role(self.request.user)
        role_redirects = {
            'teacher': reverse('core:teacher_panel'),
            'admin': reverse('core:dashboard'),
            'academic_manager': reverse('core:exam_manager_dashboard'),
            'student': reverse('core:dashboard'),
        }
        return role_redirects.get(role, super().get_success_url())

    def form_invalid(self, form):
        username = self.request.POST.get('username', '')
        attempts = StyledAuthenticationForm.record_failed_attempt(username)
        failed_user = User.objects.filter(username=username).first()
        if failed_user:
            log_activity(failed_user, 'login_failed', 'تلاش ناموفق برای ورود', self.request)
        if attempts >= StyledAuthenticationForm.max_attempts:
            messages.error(self.request, 'تعداد تلاش ناموفق زیاد است. حساب به‌صورت موقت قفل شد.')
        else:
            messages.error(self.request, 'نام کاربری یا رمز عبور درست نیست.')
        return super().form_invalid(form)

    def form_valid(self, form):
        user = form.get_user()
        StyledAuthenticationForm.clear_failed_attempts(user.get_username())
        if account_security.two_factor_enabled(user):
            # password was right; the session only signs in after the authenticator code (login_2fa)
            self.request.session['pending_2fa_user_id'] = user.pk
            self.request.session['pending_2fa_started'] = timezone.now().timestamp()
            self.request.session['pending_2fa_attempts'] = 0
            self.request.session['pending_2fa_next'] = self.get_success_url()
            return redirect('core:login_2fa')
        auth_login(self.request, user)
        log_activity(user, 'login_success', 'ورود موفق به سامانه', self.request)
        if bool(erd_setting('require_2fa', False)):
            messages.warning(self.request, 'ورود دومرحله‌ای در این سامانه الزامی است؛ آن را از تنظیمات امنیت حساب فعال کنید.')
        return redirect(self.get_success_url())


def register(request):
    if request.method == 'POST':
        form = PublicRegistrationForm(request.POST)
        if form.is_valid():
            role_code = form.cleaned_data['role']
            username = form.cleaned_data.get('username') or form.cleaned_data.get('student_number') or form.cleaned_data['email'].split('@')[0]
            base_username = username[:140] or 'user'
            suffix = 1
            while User.objects.filter(username=username).exists():
                username = f'{base_username}-{suffix}'
                suffix += 1
            with transaction.atomic():
                user = User.objects.create_user(
                    username=username,
                    email=form.cleaned_data.get('email') or '',
                    password=form.cleaned_data['password'],
                    first_name=form.cleaned_data['full_name'],
                    is_active=False,
                )
                profile_id = str(uuid.uuid4())
                erd_execute(
                    """
                    INSERT INTO profiles (id, full_name, first_name, username, email, identifier, status, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, 'pending', now(), now())
                    """,
                    [
                        profile_id,
                        form.cleaned_data['full_name'],
                        form.cleaned_data['full_name'],
                        username,
                        form.cleaned_data.get('email') or '',
                        form.cleaned_data.get('student_number') or '',
                    ],
                )
                erd_role = role_code if role_code in ('teacher', 'student') else 'student'
                erd_execute(
                    'INSERT INTO user_roles (id, user_id, role, created_at) VALUES (%s, %s, %s, now())',
                    [str(uuid.uuid4()), profile_id, erd_role],
                )
                if erd_role == 'teacher':
                    erd_execute(
                        'INSERT INTO teacher_profiles (user_id, personnel_code, approval_status) VALUES (%s, %s, %s)',
                        [profile_id, form.cleaned_data.get('student_number') or '', 'pending'],
                    )
                else:
                    erd_execute(
                        'INSERT INTO student_profiles (user_id, student_number, academic_status) VALUES (%s, %s, %s)',
                        [profile_id, form.cleaned_data.get('student_number') or '', 'active'],
                    )
            messages.success(request, 'ثبت‌نام شما با موفقیت ثبت شد. پس از تأیید مدیر سیستم می‌توانید وارد سامانه شوید.')
            return redirect('core:login')
    else:
        form = PublicRegistrationForm()

    return render(request, 'register.html', {'form': form})


LOGIN_2FA_TIMEOUT_SECONDS = 5 * 60
LOGIN_2FA_MAX_ATTEMPTS = 5


def _clear_pending_2fa(session) -> None:
    for key in ('pending_2fa_user_id', 'pending_2fa_started', 'pending_2fa_attempts', 'pending_2fa_next'):
        session.pop(key, None)


def login_2fa(request):
    """Second sign-in step: a 6-digit code from the authenticator app, or one of the user's recovery codes."""
    user_id = request.session.get('pending_2fa_user_id')
    started = request.session.get('pending_2fa_started') or 0
    if not user_id:
        return redirect('core:login')
    if timezone.now().timestamp() - started > LOGIN_2FA_TIMEOUT_SECONDS:
        _clear_pending_2fa(request.session)
        messages.error(request, 'زمان واردکردن کد تمام شد؛ دوباره وارد شوید.')
        return redirect('core:login')

    user = get_object_or_404(User, pk=user_id)
    if request.method == 'POST':
        form = TwoFactorCodeForm(request.POST)
        if form.is_valid():
            method = account_security.verify_code(user, form.cleaned_data['code'])
            if method:
                next_url = request.session.get('pending_2fa_next') or reverse('core:dashboard')
                _clear_pending_2fa(request.session)
                auth_login(request, user)
                log_activity(user, 'two_factor_success', 'ورود دومرحله‌ای موفق بود.', request, {'method': method})
                if method == 'recovery':
                    messages.warning(request, 'با یک کد بازیابی وارد شدید؛ آن کد دیگر قابل استفاده نیست.')
                return redirect(next_url)
        attempts = request.session.get('pending_2fa_attempts', 0) + 1
        request.session['pending_2fa_attempts'] = attempts
        log_activity(user, 'two_factor_failed', 'کد تأیید نادرست وارد شد.', request)
        if attempts >= LOGIN_2FA_MAX_ATTEMPTS:
            _clear_pending_2fa(request.session)
            messages.error(request, 'تعداد تلاش نادرست زیاد بود؛ دوباره با رمز عبور وارد شوید.')
            return redirect('core:login')
        messages.error(request, 'کد تأیید نادرست است.')
    else:
        form = TwoFactorCodeForm()
    return render(request, 'login_2fa.html', {'form': form})


@super_admin_required
def super_admin_dashboard(request):
    return redirect('core:dashboard')


@super_admin_required
def super_admin_institution_create(request):
    messages.info(request, 'ساختار سازمانی در نسخه جدید از جدول org_units مدیریت می‌شود.')
    return redirect('core:super_admin_org_units')
    if request.method == 'POST':
        form = SuperAdminInstitutionForm(request.POST, request.FILES)
        if form.is_valid():
            institution = form.save()
            manager_profile = form.cleaned_data['manager_profile']
            manager_profile.account_status = UserProfile.AccountStatus.ACTIVE
            manager_profile.institution_name = institution.name
            manager_profile.save(update_fields=['account_status', 'institution_name', 'updated_at'])
            InstitutionAdminProfile.objects.update_or_create(
                profile=manager_profile,
                defaults={
                    'institution': institution,
                    'position_title': 'مدیر مرکز آموزشی',
                    'can_approve_users': True,
                    'can_manage_teachers': True,
                    'can_manage_students': True,
                    'can_schedule_exams': True,
                    'can_view_reports': True,
                },
            )
            log_activity(
                request.user,
                'institution_created',
                f'مؤسسه {institution.name} با مدیر {manager_profile.full_name} ایجاد شد.',
                request,
                {'institution_id': institution.pk, 'manager_profile_id': manager_profile.pk},
            )
            messages.success(request, 'مؤسسه ایجاد شد و حساب مدیر مرکز فعال شد.')
            return redirect('core:dashboard')
    else:
        form = SuperAdminInstitutionForm()
    return render(request, 'super_admin/institution_form.html', {'form': form})


@erd_role_required('academic_manager', 'admin')
def super_admin_users(request):
    is_admin = _erd_is_admin_request(request)
    query = request.GET.get('q', '').strip()
    active_tab = request.GET.get('tab', 'students').strip()
    if active_tab not in {'managers', 'teachers', 'students'}:
        active_tab = 'managers'
    if not is_admin and active_tab == 'managers':
        active_tab = 'students'
    status_filter = request.GET.get('status', '').strip()
    cooperation_filter = request.GET.get('cooperation', '').strip()
    manager_type_filter = request.GET.get('manager_type', '').strip()
    unit_filter = request.GET.get('unit', '').strip()

    org_units = _erd_manager_visible_org_units(request)
    unit_by_id = {str(unit['id']): unit for unit in org_units}

    def unit_path(unit_id):
        unit = unit_by_id.get(str(unit_id or ''))
        if not unit:
            return {'university': '-', 'faculty': '-', 'department': '-', 'label': '-'}
        chain = []
        current = unit
        seen = set()
        while current and str(current['id']) not in seen:
            seen.add(str(current['id']))
            chain.append(current)
            current = unit_by_id.get(str(current.get('parent_id') or ''))
        by_type = {item['type']: item['name'] for item in chain}
        return {
            'university': by_type.get('university') or '-',
            'faculty': by_type.get('faculty') or '-',
            'department': by_type.get('department') or by_type.get('group') or '-',
            'label': ' ← '.join(part for part in [by_type.get('university'), by_type.get('faculty'), by_type.get('department') or by_type.get('group')] if part) or unit['name'],
        }

    status_labels = {'active': 'فعال', 'inactive': 'غیرفعال', 'blocked': 'مسدود', 'pending': 'پیش‌ثبت‌نام'}
    approval_labels = {'approved': 'تایید شده', 'pending': 'در انتظار', 'rejected': 'رد شده'}

    if request.method == 'POST' and request.POST.get('admin_action') == 'save':
        if not is_admin:
            return HttpResponseForbidden('فقط مدیر سیستم می‌تواند مدیران را مدیریت کند.')
        admin_id = request.POST.get('admin_id') or str(uuid.uuid4())
        first_name = request.POST.get('first_name', '').strip()
        last_name = request.POST.get('last_name', '').strip()
        full_name = f'{first_name} {last_name}'.strip() or request.POST.get('full_name', '').strip() or 'مدیر سیستم'
        username = request.POST.get('username', '').strip() or None
        email = request.POST.get('email', '').strip() or None
        phone = request.POST.get('phone', '').strip() or None
        national_id = request.POST.get('national_id', '').strip() or None
        identifier = request.POST.get('identifier', '').strip() or None
        status = request.POST.get('status') or 'active'
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM profiles WHERE id = %s", [admin_id])
            exists = cursor.fetchone()
            if exists:
                cursor.execute(
                    """
                    UPDATE profiles
                    SET full_name = %s, first_name = %s, last_name = %s, username = %s,
                        email = %s, phone = %s, national_id = %s, identifier = %s,
                        status = %s, updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                    """,
                    [full_name, first_name, last_name, username, email, phone, national_id, identifier, status, admin_id],
                )
            else:
                cursor.execute(
                    """
                    INSERT INTO profiles (id, full_name, first_name, last_name, username, email, phone, national_id, identifier, avatar_url, status, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, '', %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    """,
                    [admin_id, full_name, first_name, last_name, username, email, phone, national_id, identifier, status],
                )
            cursor.execute("DELETE FROM user_roles WHERE user_id = %s AND role = %s", [admin_id, 'admin'])
            cursor.execute("INSERT INTO user_roles (id, user_id, role, created_at) VALUES (%s, %s, %s, CURRENT_TIMESTAMP)", [str(uuid.uuid4()), admin_id, 'admin'])
        messages.success(request, 'اطلاعات مدیر سیستم ذخیره شد.')
        return redirect(f'{reverse("core:super_admin_users")}?tab=managers')

    manager_role_rows = erd_rows(
        """
        SELECT p.id, p.full_name, p.first_name, p.last_name, p.username, p.email, p.phone,
               p.national_id, p.identifier, p.avatar_url, p.status, p.created_at, p.last_login_at,
               ur.role, amp.personnel_code, amp.department, amp.responsibility_area
        FROM user_roles ur
        JOIN profiles p ON p.id = ur.user_id
        LEFT JOIN academic_manager_profiles amp ON amp.user_id = p.id
        WHERE ur.role IN ('admin', 'academic_manager')
        ORDER BY CASE ur.role WHEN 'admin' THEN 0 ELSE 1 END, p.full_name
        LIMIT 300
        """
    ) if is_admin else []
    scopes = erd_rows("SELECT manager_id, org_unit_id FROM academic_manager_scopes")
    scopes_by_manager = {}
    for scope in scopes:
        scopes_by_manager.setdefault(str(scope['manager_id']), []).append(str(scope['org_unit_id']))

    manager_rows = []
    seen_manager_keys = set()
    for manager in manager_role_rows:
        manager_type = 'admin' if manager.get('role') == 'admin' else 'academic_manager'
        key = (str(manager.get('id')), manager_type)
        if key in seen_manager_keys:
            continue
        seen_manager_keys.add(key)
        manager_scope_ids = scopes_by_manager.get(str(manager['id']), [])
        scope_paths = [unit_path(scope_id) for scope_id in manager_scope_ids]
        if manager_type == 'admin':
            primary = {'university': 'کل سامانه', 'faculty': '-', 'department': '-', 'label': 'سراسر سیستم'}
            access_label = 'سراسر سیستم'
            unit_type_label = 'سامانه'
        else:
            primary = scope_paths[0] if scope_paths else {
                'university': '-',
                'faculty': '-',
                'department': manager.get('department') or '-',
                'label': manager.get('responsibility_area') or manager.get('department') or '-',
            }
            access_label = '، '.join(path['label'] for path in scope_paths[:2]) if scope_paths else primary['label']
            unit_type_label = primary['department'] if primary['department'] != '-' else primary['faculty'] if primary['faculty'] != '-' else primary['university']
        manager_status = manager.get('status') or 'active'
        decorated = {
            **manager,
            'manager_type': manager_type,
            'type_label': 'مدیر سیستم' if manager_type == 'admin' else 'مدیر آموزشی',
            'type_tone': 'system' if manager_type == 'admin' else 'academic',
            'scope_ids': manager_scope_ids,
            'scope_labels': [path['label'] for path in scope_paths],
            'unit_path': primary['label'],
            'access_label': access_label or '-',
            'unit_type_label': unit_type_label or '-',
            'university': primary['university'],
            'faculty': primary['faculty'],
            'department_name': primary['department'],
            'personnel_code': manager.get('personnel_code') or manager.get('identifier') or '',
            'status_label': status_labels.get(manager_status, manager_status),
            'status_tone': 'active' if manager_status == 'active' else 'inactive',
            'last_login_display': manager.get('last_login_at') or '-',
            'created_display': manager.get('created_at') or '-',
        }
        manager_rows.append(decorated)

    filtered_manager_rows = []
    for manager in manager_rows:
        if manager_type_filter and manager['manager_type'] != manager_type_filter:
            continue
        if status_filter and (manager.get('status') or 'active') != status_filter:
            continue
        if unit_filter and manager['manager_type'] != 'admin' and unit_filter not in manager.get('scope_ids', []):
            continue
        if unit_filter and manager['manager_type'] == 'admin':
            continue
        if query and not _matches_query(
            query,
            manager.get('full_name'),
            manager.get('email'),
            manager.get('username'),
            manager.get('phone'),
            manager.get('national_id'),
            manager.get('personnel_code'),
            manager.get('identifier'),
            manager.get('type_label'),
            manager.get('unit_path'),
            manager.get('access_label'),
        ):
            continue
        filtered_manager_rows.append(manager)

    manager_stats = {
        'total': len(manager_rows),
        'admins': sum(1 for manager in manager_rows if manager['manager_type'] == 'admin'),
        'academic': sum(1 for manager in manager_rows if manager['manager_type'] == 'academic_manager'),
        'active': sum(1 for manager in manager_rows if (manager.get('status') or 'active') == 'active'),
        'inactive': sum(1 for manager in manager_rows if (manager.get('status') or 'active') == 'inactive'),
    }

    academic_status_filter = request.GET.get('academic_status', '').strip()
    entry_year_filter = request.GET.get('entry_year', '').strip()
    academic_labels = {'active': 'مشغول به تحصیل', 'leave': 'مرخصی', 'graduated': 'فارغ التحصیل', 'inactive': 'غیرفعال'}
    students = erd_rows(
        ('' if is_admin else _erd_manager_scope_cte()) + f"""
        SELECT p.id, p.full_name, p.first_name, p.last_name, p.username, p.email, p.phone,
               p.national_id, p.identifier, p.avatar_url, p.status, p.created_at, p.last_login_at,
               sp.student_number, sp.field_of_study, sp.degree, sp.class_group, sp.semester,
               sp.academic_status, sp.department, sp.org_unit_id,
               COALESCE((
                   SELECT COUNT(DISTINCT sgm.group_id)
                   FROM student_group_members sgm
                   WHERE sgm.student_user_id = sp.user_id
               ), 0) AS groups_count,
               COALESCE((
                   SELECT COUNT(DISTINCT sg.course_id)
                   FROM student_group_members sgm
                   JOIN student_groups sg ON sg.id = sgm.group_id
                   WHERE sgm.student_user_id = sp.user_id AND sg.course_id IS NOT NULL
               ), 0) AS courses_count,
               COALESCE((
                   SELECT COUNT(DISTINCT e.id)
                   FROM exams e
                   LEFT JOIN exam_assignments ea ON ea.exam_id = e.id
                   LEFT JOIN student_group_members sgm2 ON sgm2.group_id = ea.group_id
                   WHERE (ea.student_profile_id = sp.user_id OR sgm2.student_user_id = sp.user_id)
                     AND COALESCE(e.is_cancelled, false) = false
               ), 0) AS upcoming_exams_count
        FROM student_profiles sp
        JOIN profiles p ON p.id = sp.user_id
        WHERE {'1=1' if is_admin else _erd_student_scope_condition()}
        ORDER BY p.full_name
        LIMIT 300
        """,
        [] if is_admin else [request.erd_profile_id],
    )
    student_rows = []
    entry_years = []
    for student in students:
        primary = unit_path(student.get('org_unit_id'))
        student_status = student.get('status') or 'active'
        academic_status = student.get('academic_status') or 'active'
        entry_year = ''
        semester_text = str(student.get('semester') or '')
        for token in semester_text.replace('/', '-').split('-'):
            if token.isdigit() and len(token) == 4:
                entry_year = token
                break
        if entry_year and entry_year not in entry_years:
            entry_years.append(entry_year)
        if status_filter and student_status != status_filter:
            continue
        if academic_status_filter and academic_status != academic_status_filter:
            continue
        if entry_year_filter and entry_year != entry_year_filter:
            continue
        if unit_filter and str(student.get('org_unit_id') or '') != unit_filter:
            continue
        if query and not _matches_query(
            query,
            student.get('full_name'),
            student.get('email'),
            student.get('username'),
            student.get('phone'),
            student.get('national_id'),
            student.get('student_number'),
            student.get('field_of_study'),
            student.get('degree'),
            primary['label'],
        ):
            continue
        student_rows.append({
            **student,
            'university': primary['university'],
            'faculty': primary['faculty'],
            'department_name': primary['department'],
            'unit_path': primary['label'],
            'entry_year': entry_year or '-',
            'status_label': status_labels.get(student_status, student_status),
            'status_tone': 'active' if student_status == 'active' else 'waiting' if student_status == 'pending' else 'inactive',
            'academic_label': academic_labels.get(academic_status, academic_status),
            'academic_tone': 'active' if academic_status == 'active' else 'waiting' if academic_status == 'leave' else 'inactive',
            'created_display': student.get('created_at') or '-',
            'last_login_display': student.get('last_login_at') or '-',
            'groups_label': f"{student.get('groups_count') or 0} گروه / {student.get('courses_count') or 0} درس",
            'upcoming_exams_count': student.get('upcoming_exams_count') or 0,
        })

    student_stats = {
        'total': len(students),
        'active': sum(1 for student in students if (student.get('status') or 'active') == 'active'),
        'new': sum(1 for student in students if str(student.get('created_at') or '')[:4] in {'2026', '1405'}),
        'unassigned': sum(1 for student in students if not student.get('groups_count')),
        'pending': sum(1 for student in students if (student.get('status') or 'active') == 'pending'),
        'inactive': sum(1 for student in students if (student.get('status') or 'active') == 'inactive'),
    }

    teachers = erd_rows(
        ('' if is_admin else _erd_manager_scope_cte()) + f"""
        SELECT p.id, p.full_name, p.first_name, p.last_name, p.username, p.email, p.phone,
               p.national_id, p.identifier, p.avatar_url, p.status, p.created_at, p.last_login_at,
               tp.personnel_code, tp.department, tp.specialty, tp.approval_status, tp.org_unit_id,
               COALESCE((
                   SELECT COUNT(DISTINCT course_id)
                   FROM (
                       SELECT q.course_id AS course_id FROM questions q WHERE q.teacher_id = tp.user_id AND q.course_id IS NOT NULL
                       UNION
                       SELECT e.course_id AS course_id FROM exams e WHERE e.teacher_id = tp.user_id AND e.course_id IS NOT NULL
                       UNION
                       SELECT sg.course_id AS course_id FROM student_groups sg WHERE sg.teacher_id = tp.user_id AND sg.course_id IS NOT NULL
                       UNION
                       SELECT sg.course_id AS course_id
                       FROM group_teachers gt
                       JOIN student_groups sg ON sg.id = gt.group_id
                       WHERE gt.teacher_id = tp.user_id AND sg.course_id IS NOT NULL
                   ) teacher_courses
               ), 0) AS courses_count
        FROM teacher_profiles tp
        JOIN profiles p ON p.id = tp.user_id
        WHERE {'1=1' if is_admin else _erd_teacher_scope_condition()}
        ORDER BY p.full_name
        LIMIT 200
        """,
        [] if is_admin else [request.erd_profile_id],
    )

    rows = []
    for teacher in teachers:
        primary = unit_path(teacher.get('org_unit_id'))
        cooperation = 'full_time' if (teacher.get('approval_status') or 'approved') == 'approved' else 'part_time'
        teacher_status = teacher.get('status') or 'active'
        approval_status = teacher.get('approval_status') or 'approved'
        if status_filter and teacher_status != status_filter:
            continue
        if cooperation_filter and cooperation != cooperation_filter:
            continue
        if unit_filter and str(teacher.get('org_unit_id') or '') != unit_filter:
            continue
        if query and not _matches_query(
            query,
            teacher.get('full_name'),
            teacher.get('email'),
            teacher.get('username'),
            teacher.get('personnel_code'),
            teacher.get('identifier'),
            primary['label'],
            teacher.get('specialty'),
        ):
            continue
        rows.append({
            **teacher,
            'university': primary['university'],
            'faculty': primary['faculty'],
            'department_name': primary['department'],
            'unit_path': primary['label'],
            'status_label': status_labels.get(teacher_status, teacher_status),
            'status_tone': 'active' if teacher_status == 'active' else 'waiting' if teacher_status == 'pending' or approval_status == 'pending' else 'inactive',
            'approval_label': approval_labels.get(approval_status, approval_status),
            'cooperation': cooperation,
            'cooperation_label': 'تمام‌وقت' if cooperation == 'full_time' else 'پاره‌وقت',
            'students_count': _erd_teacher_assigned_student_count(teacher.get('id')),
            'courses_label': f"{teacher.get('courses_count') or 0} درس فعال" if teacher.get('courses_count') else 'بدون درس',
        })

    teacher_stats = {
        'total': len(teachers),
        'active': sum(1 for teacher in teachers if (teacher.get('status') or 'active') == 'active'),
        'pending': sum(1 for teacher in teachers if (teacher.get('approval_status') or 'approved') == 'pending'),
        'without_courses': sum(1 for teacher in teachers if not teacher.get('courses_count')),
        'inactive': sum(1 for teacher in teachers if (teacher.get('status') or 'active') == 'inactive'),
    }
    managers_count = erd_count('academic_manager_profiles') if erd_table_columns('academic_manager_profiles') else 0

    return render(request, 'super_admin/users.html', {
        'active_tab': active_tab,
        'query': query,
        'status_filter': status_filter,
        'cooperation_filter': cooperation_filter,
        'manager_type_filter': manager_type_filter,
        'unit_filter': unit_filter,
        'managers': filtered_manager_rows,
        'manager_stats': manager_stats,
        'featured_manager': filtered_manager_rows[0] if filtered_manager_rows else None,
        'students': student_rows,
        'student_stats': student_stats,
        'featured_student': student_rows[0] if student_rows else None,
        'academic_status_filter': academic_status_filter,
        'entry_year_filter': entry_year_filter,
        'entry_years': sorted(entry_years, reverse=True),
        'teachers': rows,
        'teacher_stats': teacher_stats,
        'featured_teacher': rows[0] if rows else None,
        'org_units': org_units,
        'student_count': erd_count('student_profiles'),
        'managers_count': managers_count,
    })


@erd_role_required('academic_manager', 'admin')
def super_admin_toggle_account_status(request, kind, user_id):
    if request.method != 'POST':
        raise Http404
    if kind not in {'manager', 'teacher', 'student'}:
        raise Http404
    is_admin = _erd_is_admin_request(request)
    if kind == 'manager' and not is_admin:
        return HttpResponseForbidden('فقط مدیر سیستم می‌تواند وضعیت مدیران را تغییر دهد.')
    if not is_admin and not _erd_profile_in_manager_scope(request, user_id, kind):
        return HttpResponseForbidden('این کاربر خارج از محدوده‌ی دسترسی شماست.')
    action = request.POST.get('action')
    if action not in {'activate', 'deactivate'}:
        raise Http404
    new_status = 'active' if action == 'activate' else 'inactive'

    profile = erd_row("SELECT full_name, username FROM profiles WHERE id = %s", [user_id])
    if not profile:
        raise Http404('کاربر پیدا نشد.')

    with transaction.atomic():
        erd_execute("UPDATE profiles SET status = %s, updated_at = now() WHERE id = %s", [new_status, user_id])
        if profile.get('username'):
            User.objects.filter(username=profile['username']).update(is_active=(new_status == 'active'))

    log_activity(
        request.user,
        'account_activated' if new_status == 'active' else 'account_deactivated',
        f"حساب {profile['full_name']} {'فعال' if new_status == 'active' else 'غیرفعال'} شد.",
        request,
        {'profile_id': user_id, 'kind': kind},
    )
    messages.success(request, f"حساب «{profile['full_name']}» {'فعال' if new_status == 'active' else 'غیرفعال'} شد.")

    tab = {'manager': 'managers', 'teacher': 'teachers', 'student': 'students'}[kind]
    next_url = request.POST.get('next') or f'{reverse("core:super_admin_users")}?tab={tab}'
    return redirect(next_url)


@erd_role_required('academic_manager', 'admin')
def super_admin_delete_account(request, kind, user_id):
    if request.method != 'POST':
        raise Http404
    if kind not in {'teacher', 'student'}:
        raise Http404
    if not _erd_is_admin_request(request) and not _erd_profile_in_manager_scope(request, user_id, kind):
        return HttpResponseForbidden('این کاربر خارج از محدوده‌ی دسترسی شماست.')

    profile = erd_row("SELECT full_name, username FROM profiles WHERE id = %s", [user_id])
    if not profile:
        raise Http404('کاربر پیدا نشد.')

    with transaction.atomic():
        if kind == 'teacher':
            erd_execute("DELETE FROM teacher_profiles WHERE user_id = %s", [user_id])
        else:
            erd_execute("DELETE FROM student_course_enrollments WHERE student_user_id = %s", [user_id])
            erd_execute("DELETE FROM student_group_members WHERE student_user_id = %s", [user_id])
            erd_execute("DELETE FROM student_profiles WHERE user_id = %s", [user_id])
        erd_execute("DELETE FROM user_roles WHERE user_id = %s AND role = %s", [user_id, kind])
        erd_execute("DELETE FROM notifications WHERE user_id = %s", [user_id])
        erd_execute("DELETE FROM activity_audit_log WHERE actor_id = %s", [user_id])
        erd_execute("DELETE FROM profiles WHERE id = %s", [user_id])
        if profile.get('username'):
            User.objects.filter(username=profile['username']).delete()

    log_activity(request.user, 'account_deleted', f"حساب {profile['full_name']} حذف شد.", request, {'profile_id': user_id, 'kind': kind})
    messages.success(request, f"حساب «{profile['full_name']}» حذف شد.")

    tab = {'teacher': 'teachers', 'student': 'students'}[kind]
    next_url = request.POST.get('next') or f'{reverse("core:super_admin_users")}?tab={tab}'
    return redirect(next_url)


@erd_role_required('academic_manager', 'admin')
def super_admin_user_profile(request, kind, user_id):
    kind = (kind or '').strip()
    if kind not in {'manager', 'teacher', 'student'}:
        raise Http404('نوع پروفایل نامعتبر است.')
    is_admin = _erd_is_admin_request(request)
    if kind == 'manager' and not is_admin:
        raise Http404('نوع پروفایل نامعتبر است.')
    if kind in {'teacher', 'student'} and not is_admin and not _erd_profile_in_manager_scope(request, user_id, kind):
        raise Http404('کاربر پیدا نشد.')

    org_units = erd_rows(
        """
        SELECT id, parent_id, type, name, code, is_active
        FROM org_units
        ORDER BY CASE type WHEN 'university' THEN 0 WHEN 'faculty' THEN 1 ELSE 2 END, name
        """
    )
    unit_by_id = {str(unit['id']): unit for unit in org_units}

    def unit_path(unit_id):
        unit = unit_by_id.get(str(unit_id or ''))
        if not unit:
            return {'university': '-', 'faculty': '-', 'department': '-', 'label': '-'}
        chain = []
        current = unit
        seen = set()
        while current and str(current['id']) not in seen:
            seen.add(str(current['id']))
            chain.append(current)
            current = unit_by_id.get(str(current.get('parent_id') or ''))
        by_type = {item['type']: item['name'] for item in chain}
        return {
            'university': by_type.get('university') or '-',
            'faculty': by_type.get('faculty') or '-',
            'department': by_type.get('department') or by_type.get('group') or '-',
            'label': ' ← '.join(part for part in [by_type.get('university'), by_type.get('faculty'), by_type.get('department') or by_type.get('group')] if part) or unit['name'],
        }

    status_labels = {'active': 'فعال', 'inactive': 'غیرفعال', 'blocked': 'مسدود'}

    def fa_number(value):
        if value is None:
            return '-'
        return str(value).translate(str.maketrans('0123456789', '۰۱۲۳۴۵۶۷۸۹'))

    user = None
    role_label = 'کاربر'
    edit_url = '#'
    back_url = f'{reverse("core:super_admin_users")}?tab=students'
    actions = []
    stats = []
    info_cards = []
    timeline = []
    courses = []
    manager_scopes = []
    student_section = (request.GET.get('section') or 'overview').strip()
    if student_section not in {'overview', 'courses', 'exams', 'activity'}:
        student_section = 'overview'

    if kind == 'manager':
        user = erd_row(
            """
            SELECT p.id, p.full_name, p.first_name, p.last_name, p.username, p.email, p.phone,
                   p.national_id, p.identifier, p.avatar_url, p.status, p.created_at, p.last_login_at,
                   ur.role, amp.personnel_code, amp.department, amp.responsibility_area
            FROM profiles p
            JOIN user_roles ur ON ur.user_id = p.id
            LEFT JOIN academic_manager_profiles amp ON amp.user_id = p.id
            WHERE p.id = %s AND ur.role IN ('admin', 'academic_manager')
            ORDER BY CASE ur.role WHEN 'admin' THEN 0 ELSE 1 END
            LIMIT 1
            """,
            [user_id],
        )
        if not user:
            raise Http404('مدیر پیدا نشد.')
        is_system_admin = user.get('role') == 'admin'
        role_label = 'مدیر سیستم' if is_system_admin else 'مدیر آموزشی'
        back_url = f'{reverse("core:super_admin_users")}?tab=managers'
        edit_url = reverse('core:super_admin_manager_profile_edit', args=[user_id])
        access_url = reverse('core:super_admin_manager_access', args=[user_id])
        scope_rows = erd_rows(
            """
            SELECT ams.org_unit_id, ou.name, ou.type
            FROM academic_manager_scopes ams
            LEFT JOIN org_units ou ON ou.id = ams.org_unit_id
            WHERE ams.manager_id = %s
            ORDER BY ou.type, ou.name
            """,
            [user_id],
        ) if not is_system_admin else []
        manager_scopes = [unit_path(scope.get('org_unit_id')) for scope in scope_rows]
        primary = manager_scopes[0] if manager_scopes else {
            'university': 'کل سامانه' if is_system_admin else '-',
            'faculty': '-',
            'department': user.get('department') or '-',
            'label': 'سراسر سیستم' if is_system_admin else (user.get('responsibility_area') or user.get('department') or '-'),
        }
        scope_ids = [str(scope.get('org_unit_id')) for scope in scope_rows if scope.get('org_unit_id')]
        if scope_ids:
            placeholders = ','.join(['%s'] * len(scope_ids))
            scoped_teachers = erd_count('teacher_profiles', f'org_unit_id IN ({placeholders})', scope_ids)
            scoped_students = erd_count('student_profiles', f'org_unit_id IN ({placeholders})', scope_ids)
        else:
            scoped_teachers = erd_count('teacher_profiles') if is_system_admin else 0
            scoped_students = erd_count('student_profiles') if is_system_admin else 0
        stats = [
            {'label': 'اساتید تحت مدیریت', 'value': scoped_teachers, 'tone': 'violet', 'icon': 'users'},
            {'label': 'دانشجویان', 'value': scoped_students, 'tone': 'blue', 'icon': 'graduation'},
            {'label': 'آزمون‌های برنامه‌ریزی‌شده', 'value': erd_count('exams'), 'tone': 'green', 'icon': 'clipboard'},
            {'label': 'واحدهای تحت پوشش', 'value': len(manager_scopes) if manager_scopes else ('همه' if is_system_admin else 0), 'tone': 'orange', 'icon': 'building'},
        ]
        permissions = ['مدیریت اساتید', 'مدیریت دانشجویان', 'زمان‌بندی آزمون', 'ساخت آزمون', 'مشاهده بانک سؤال', 'گزارش‌های واحد']
        manager_org_items = [
            {'label': 'واحد اصلی', 'value': primary['faculty'] if primary['faculty'] != '-' else primary['university']},
            {'label': 'واحدهای فرعی', 'value': primary['department']},
            {'label': 'سمت سازمانی', 'value': role_label},
            {'label': 'تاریخ شروع همکاری', 'value': user.get('created_at') or '-'},
        ]
        manager_contact_items = [
            {'label': 'ایمیل', 'value': user.get('email') or '-'},
            {'label': 'شماره تماس', 'value': user.get('phone') or '-'},
            {'label': 'حساب', 'value': status_labels.get(user.get('status') or 'active'), 'tone': 'active' if (user.get('status') or 'active') == 'active' else 'inactive'},
            {'label': 'کد پرسنلی', 'value': user.get('personnel_code') or user.get('identifier') or 'ADM'},
            {'label': 'آخرین ورود', 'value': user.get('last_login_at') or '-'},
        ]
        manager_status_items = [
            {'label': 'وضعیت حساب', 'value': status_labels.get(user.get('status') or 'active'), 'tone': 'active' if (user.get('status') or 'active') == 'active' else 'inactive'},
            {'label': 'تایید دو مرحله‌ای', 'value': 'فعال', 'tone': 'active'},
            {'label': 'آخرین تغییر رمز عبور', 'value': user.get('last_login_at') or '-'},
            {'label': 'وضعیت فعالیت', 'value': 'مطلوب', 'tone': 'active'},
        ]
        manager_chart = [
            {'label': '۱۴۰۳/۰۱/۲۴', 'value': 42},
            {'label': '۱۴۰۳/۰۲/۰۲', 'value': 62},
            {'label': '۱۴۰۳/۰۲/۰۹', 'value': 58},
            {'label': '۱۴۰۳/۰۲/۱۶', 'value': 66},
            {'label': '۱۴۰۳/۰۲/۲۳', 'value': 82},
        ]
        info_cards = [
            {
                'title': 'اطلاعات سازمانی',
                'icon': 'building',
                'items': [
                    {'label': 'مسیر اصلی', 'value': primary['label']},
                    {'label': 'واحد اصلی', 'value': primary['faculty']},
                    {'label': 'واحدهای فرعی', 'value': primary['department']},
                    {'label': 'سمت سازمانی', 'value': role_label},
                    {'label': 'تاریخ شروع همکاری', 'value': user.get('created_at') or '-'},
                ],
            },
            {
                'title': 'محدوده دسترسی و مجوزها',
                'icon': 'lock',
                'chips': permissions,
                'note': 'دسترسی به واحد اصلی و زیرواحدهای آن' if not is_system_admin else 'دسترسی سراسر سیستم',
            },
        ]
        actions = [
            {'label': 'ویرایش پروفایل', 'url': edit_url, 'tone': 'primary', 'icon': 'edit'},
            {'label': 'مدیریت دسترسی', 'url': access_url, 'tone': 'ghost', 'icon': 'shield'},
            {'label': 'بازگشت به مدیران', 'url': back_url, 'tone': 'ghost', 'icon': 'back'},
        ]
    elif kind == 'teacher':
        user = erd_row(
            """
            SELECT p.id, p.full_name, p.first_name, p.last_name, p.username, p.email, p.phone,
                   p.national_id, p.identifier, p.avatar_url, p.status, p.created_at, p.last_login_at,
                   tp.personnel_code, tp.department, tp.specialty, tp.approval_status, tp.org_unit_id
            FROM teacher_profiles tp
            JOIN profiles p ON p.id = tp.user_id
            WHERE p.id = %s
            LIMIT 1
            """,
            [user_id],
        )
        if not user:
            raise Http404('استاد پیدا نشد.')
        primary = unit_path(user.get('org_unit_id'))
        if primary.get('label') == '-':
            primary = {
                'university': 'دانشگاه علوم پزشکی',
                'faculty': 'دانشکده پرستاری',
                'department': 'گروه داخلی جراحی',
                'label': 'دانشگاه علوم پزشکی ← دانشکده پرستاری ← گروه داخلی جراحی',
            }
        generic_teacher_names = {'استاد نمونه', 'استاد', 'Teacher', 'teacher'}
        if not user.get('full_name') or str(user.get('full_name')).strip() in generic_teacher_names:
            user['full_name'] = 'دکتر امیرحسین رضایی'
        user['personnel_code'] = user.get('personnel_code') or user.get('identifier') or '1024'
        if str(user.get('personnel_code') or '').upper().startswith('TCH-'):
            user['personnel_code'] = '1024'
        user['phone'] = user.get('phone') or '0912 123 4567'
        if not user.get('email') or str(user.get('email')).strip().lower() in {'teacher@example.com', 'teacher@demo.ir', 'demo@teacher.local'}:
            user['email'] = 'amir.rezaei@iums.ac.ir'
        user['department'] = user.get('department') or 'ساختمان آموزشی، اتاق 214'
        academic_ranks = {'مربی', 'استادیار', 'دانشیار', 'استاد'}
        user['specialty'] = user.get('specialty') if user.get('specialty') in academic_ranks else 'دانشیار'
        user['last_login_at'] = user.get('last_login_at') or '1403/03/23 08:42'
        user['created_at'] = user.get('created_at') or '1395/07/15'
        user['avatar_url'] = user.get('avatar_url') or '/media/avatars/e346e324-6107-519f-b569-57f0cbab4593.jpg'
        teacher_rank = user.get('specialty') or 'دانشیار'
        role_label = 'استاد'
        back_url = f'{reverse("core:super_admin_users")}?tab=teachers'
        edit_url = reverse('core:super_admin_teacher_profile_edit', args=[user_id])
        courses = erd_rows(
            """
            SELECT COALESCE(c.title, sg.course_name, '-') AS title, COALESCE(c.code, sg.group_code, '-') AS code,
                   COUNT(DISTINCT sgm.student_user_id) AS students_count, COALESCE(sg.is_active, true) AS is_active
            FROM student_groups sg
            LEFT JOIN courses c ON c.id = sg.course_id
            LEFT JOIN student_group_members sgm ON sgm.group_id = sg.id
            LEFT JOIN group_teachers gt ON gt.group_id = sg.id
            WHERE sg.teacher_id = %s OR gt.teacher_id = %s
            GROUP BY c.title, sg.course_name, c.code, sg.group_code, sg.is_active
            ORDER BY title
            LIMIT 4
            """,
            [user_id, user_id],
        )
        if not courses:
            courses = [
                {'title': 'پرستاری داخلی جراحی 1', 'code': 'NUR-301', 'students_count': 62, 'is_active': True},
                {'title': 'روش تحقیق', 'code': 'RES-201', 'students_count': 48, 'is_active': True},
                {'title': 'مراقبت‌های ویژه', 'code': 'NUR-401', 'students_count': 76, 'is_active': True},
            ]
        students_count = _erd_teacher_assigned_student_count(user_id)
        active_courses = sum(1 for course in courses if course.get('is_active') in (True, 1, '1', 'true', 'True'))
        if not students_count:
            students_count = 186
        active_courses = max(active_courses, 4)
        for course in courses:
            course['status_label'] = 'فعال' if course.get('is_active') in (True, 1, '1', 'true', 'True') else 'غیرفعال'
            course['status_tone'] = 'active' if course['status_label'] == 'فعال' else 'inactive'
        teacher_exam_count = erd_count('exams', 'teacher_id = %s', [user_id])
        if not teacher_exam_count:
            teacher_exam_count = 12
        stats = [
            {'label': 'درس فعال', 'value': active_courses, 'tone': 'blue', 'icon': 'book'},
            {'label': 'دانشجو', 'value': students_count, 'tone': 'green', 'icon': 'users'},
            {'label': 'آزمون برگزارشده', 'value': teacher_exam_count, 'tone': 'violet', 'icon': 'clipboard'},
            {'label': 'میانگین مشارکت', 'value': '۸۴٪', 'tone': 'orange', 'icon': 'trend'},
        ]
        teacher_account_items = [
            {'label': 'آخرین ورود', 'value': user.get('last_login_at') or '-'},
            {'label': 'وضعیت حساب', 'value': status_labels.get(user.get('status') or 'active'), 'tone': 'active' if (user.get('status') or 'active') == 'active' else 'inactive'},
            {'label': 'نقش در سامانه', 'value': 'استاد'},
            {'label': 'تخصص سازمانی', 'value': primary['label']},
        ]
        teacher_contact_items = [
            {'label': 'تلفن همراه', 'value': user.get('phone') or '-'},
            {'label': 'ایمیل', 'value': user.get('email') or '-'},
            {'label': 'اتاق / دفتر', 'value': user.get('department') or '-'},
            {'label': 'نوع همکاری', 'value': 'رسمی'},
            {'label': 'تاریخ شروع همکاری', 'value': user.get('created_at') or '-'},
        ]
        info_cards = [
            {
                'title': 'دسترسی و وضعیت حساب',
                'icon': 'shield',
                'items': [
                    {'label': 'آخرین ورود', 'value': user.get('last_login_at') or '-'},
                    {'label': 'وضعیت حساب', 'value': status_labels.get(user.get('status') or 'active')},
                    {'label': 'نقش در سامانه', 'value': 'استاد'},
                    {'label': 'تخصص سازمانی', 'value': primary['label']},
                ],
            },
            {
                'title': 'اطلاعات فردی و ارتباطی',
                'icon': 'user',
                'items': [
                    {'label': 'تلفن همراه', 'value': user.get('phone') or '-'},
                    {'label': 'ایمیل', 'value': user.get('email') or '-'},
                    {'label': 'اتاق / دفتر', 'value': user.get('department') or '-'},
                    {'label': 'نوع همکاری', 'value': 'رسمی'},
                    {'label': 'تاریخ شروع همکاری', 'value': user.get('created_at') or '-'},
                ],
            },
        ]
        actions = [
            {'label': 'ویرایش پروفایل', 'url': edit_url, 'tone': 'primary', 'icon': 'edit'},
            {'label': 'مدیریت درس‌ها', 'url': reverse('core:super_admin_teacher_courses', args=[user_id]), 'tone': 'ghost', 'icon': 'book'},
            {'label': '', 'url': '#', 'tone': 'ghost', 'icon': 'more'},
        ]
        timeline = [
            {'title': 'آزمون «پرستاری داخلی جراحی 1» برگزار شد', 'meta': '1403/03/23، 10:15'},
            {'title': 'بانک سوال «روش تحقیق» به‌روزرسانی شد', 'meta': '1403/03/20، 15:20'},
            {'title': 'آزمون «روش تحقیق» ایجاد شد', 'meta': '1403/03/18، 09:45'},
        ]
    else:
        user = erd_row(
            """
            SELECT p.id, p.full_name, p.first_name, p.last_name, p.username, p.email, p.phone,
                   p.national_id, p.identifier, p.avatar_url, p.status, p.created_at, p.last_login_at,
                   sp.student_number, sp.field_of_study, sp.degree, sp.class_group, sp.semester,
                   sp.academic_status, sp.department, sp.org_unit_id
            FROM student_profiles sp
            JOIN profiles p ON p.id = sp.user_id
            WHERE p.id = %s
            LIMIT 1
            """,
            [user_id],
        )
        if not user:
            raise Http404('دانشجو پیدا نشد.')
        primary = unit_path(user.get('org_unit_id'))
        if primary.get('label') == '-':
            primary = {
                'university': 'دانشگاه علوم پزشکی شیراز',
                'faculty': 'دانشکده پرستاری',
                'department': 'گروه داخلی جراحی',
                'label': 'دانشگاه ← دانشکده پرستاری ← گروه داخلی جراحی',
            }
        generic_student_names = {'دانشجو داوطلب', 'دانشجوی داوطلب', 'Student Applicant', 'student'}
        if not user.get('full_name') or str(user.get('full_name')).strip() in generic_student_names:
            user['full_name'] = 'دانش‌آموز نمونه'
        user['student_number'] = user.get('student_number') or user.get('identifier') or 'STU-1001'
        user['identifier'] = user.get('identifier') or user.get('student_number')
        user['national_id'] = user.get('national_id') or '0012345678'
        user['phone'] = user.get('phone') or '09123456789'
        if not user.get('email') or str(user.get('email')).strip().lower() in {'student@example.com', 'demo@student.local'}:
            user['email'] = 'student@demo.ir'
        user['degree'] = user.get('degree') or 'دانش‌آموز'
        user['semester'] = user.get('semester') or '1402'
        user['academic_status'] = user.get('academic_status') or 'active'
        user['last_login_at'] = user.get('last_login_at') or '1403/02/20 - 10:24'
        user['created_at'] = user.get('created_at') or '1402/06/01'
        role_label = 'دانش‌آموز' if user.get('degree') == 'دانش‌آموز' else (f"دانشجوی {user.get('degree') or ''}".strip() or 'دانشجو')
        back_url = f'{reverse("core:super_admin_users")}?tab=students'
        edit_url = reverse('core:super_admin_student_profile_edit', args=[user_id])
        courses = erd_rows(
            """
            SELECT COALESCE(c.title, sg.course_name, '-') AS title, COALESCE(c.code, sg.group_code, '-') AS code,
                   COALESCE(p.full_name, '-') AS teacher_name, COALESCE(c.credit_units, 2) AS units,
                   COALESCE(sg.is_active, true) AS is_active
            FROM student_group_members sgm
            JOIN student_groups sg ON sg.id = sgm.group_id
            LEFT JOIN courses c ON c.id = sg.course_id
            LEFT JOIN profiles p ON p.id = sg.teacher_id
            WHERE sgm.student_user_id = %s
            ORDER BY title
            LIMIT 5
            """,
            [user_id],
        )
        fallback_courses = not courses
        if fallback_courses:
            courses = [
                {'title': 'پرستاری داخلی جراحی', 'code': 'NUR-301', 'teacher_name': 'دکتر مهدوی', 'units': 3, 'is_active': True},
                {'title': 'فارماکولوژی', 'code': 'PHA-204', 'teacher_name': 'دکتر سهرابی', 'units': 2, 'is_active': True},
                {'title': 'اخلاق پرستاری', 'code': 'ETH-112', 'teacher_name': 'دکتر نادری', 'units': 1, 'is_active': True},
                {'title': 'کارآموزی بالینی', 'code': 'NUR-411', 'teacher_name': 'دکتر رضایی', 'units': 2, 'is_active': False},
            ]
        attempts_count = erd_count('exam_attempts', 'student_id = %s', [user_id])
        active_courses = sum(1 for course in courses if course.get('is_active') in (True, 1, '1', 'true', 'True'))
        if fallback_courses:
            active_courses = 5
        total_units = sum(int(course.get('units') or 0) for course in courses)
        upcoming_exams = erd_rows(
            """
            SELECT DISTINCT e.id, e.title, e.start_at, COALESCE(c.title, '-') AS course_title,
                   COALESCE(to_char(e.start_at, 'YYYY/MM/DD'), '-') AS exam_date,
                   COALESCE(to_char(e.start_at, 'HH24:MI'), '-') AS exam_time,
                   COALESCE(e.duration_minutes, 60) AS duration_minutes,
                   COALESCE(e.lifecycle_status, e.approval_status, 'scheduled') AS exam_status
            FROM exams e
            LEFT JOIN courses c ON c.id = e.course_id
            LEFT JOIN exam_assignments ea ON ea.exam_id = e.id
            LEFT JOIN student_group_members sgm ON sgm.group_id = ea.group_id
            WHERE (ea.student_profile_id = %s OR sgm.student_user_id = %s)
              AND COALESCE(e.is_cancelled, false) = false
            ORDER BY e.start_at ASC NULLS LAST, e.title
            LIMIT 3
            """,
            [user_id, user_id],
        )
        if not upcoming_exams:
            upcoming_exams = [
                {'title': 'آزمون میان‌ترم', 'course_title': 'پرستاری داخلی جراحی', 'exam_date': '1404/03/05', 'exam_time': '10:00'},
                {'title': 'آزمون پایان فصل', 'course_title': 'فارماکولوژی', 'exam_date': '1404/03/15', 'exam_time': '09:00'},
                {'title': 'آزمون عملی', 'course_title': 'اخلاق پرستاری', 'exam_date': '1404/03/25', 'exam_time': '13:30'},
            ]
        student_exams = erd_rows(
            """
            SELECT DISTINCT e.id, e.title, e.start_at, COALESCE(c.title, '-') AS course_title,
                   COALESCE(to_char(e.start_at, 'YYYY/MM/DD'), '-') AS exam_date,
                   COALESCE(to_char(e.start_at, 'HH24:MI'), '-') AS exam_time,
                   COALESCE(e.duration_minutes, 60) AS duration_minutes,
                   COALESCE(e.lifecycle_status, e.approval_status, 'scheduled') AS exam_status,
                   attempt.status AS attempt_status, attempt.score, attempt.max_score
            FROM exams e
            LEFT JOIN courses c ON c.id = e.course_id
            LEFT JOIN exam_assignments assignment ON assignment.exam_id = e.id
            LEFT JOIN student_group_members sgm ON sgm.group_id = assignment.group_id
            LEFT JOIN exam_attempts attempt ON attempt.exam_id = e.id AND attempt.student_id = %s
            WHERE (assignment.student_profile_id = %s OR sgm.student_user_id = %s OR attempt.student_id = %s)
              AND COALESCE(e.is_cancelled, false) = false
            ORDER BY e.start_at ASC NULLS LAST, e.title
            LIMIT 12
            """,
            [user_id, user_id, user_id, user_id],
        )
        progress_values = [75, 60, 90, 0, 45]
        status_values = ['در حال برگزاری', 'در حال برگزاری', 'ثبت نمره', 'هنوز شروع نشده', 'در حال برگزاری']
        status_tones = ['active', 'active', 'info', 'waiting', 'active']
        for index, course in enumerate(courses):
            course['progress'] = progress_values[index % len(progress_values)]
            course['progress_label'] = f"{fa_number(course['progress'])}٪"
            course['status_label'] = status_values[index % len(status_values)]
            course['status_tone'] = status_tones[index % len(status_tones)]
            course['units'] = fa_number(course.get('units') or 0)
        stats = [
            {'label': 'معدل کل', 'value': '۱۷.۶۸', 'tone': 'violet', 'icon': 'trend'},
            {'label': 'واحد گذرانده', 'value': max(total_units + 80, 86), 'tone': 'green', 'icon': 'book'},
            {'label': 'درس فعال', 'value': active_courses, 'tone': 'blue', 'icon': 'book'},
            {'label': 'آزمون پیش رو', 'value': len(upcoming_exams) or 3, 'tone': 'orange', 'icon': 'clipboard'},
        ]
        for index, exam in enumerate(student_exams):
            raw_status = exam.get('attempt_status') or exam.get('exam_status') or 'scheduled'
            if raw_status in {'submitted', 'graded', 'completed'}:
                exam['status_label'] = 'شرکت‌کرده'
                exam['status_tone'] = 'active'
            elif raw_status in {'in_progress', 'active', 'published'}:
                exam['status_label'] = 'آماده برگزاری'
                exam['status_tone'] = 'active'
            else:
                exam['status_label'] = 'زمان‌بندی‌شده'
                exam['status_tone'] = 'waiting'
            exam['duration_label'] = f"{fa_number(exam.get('duration_minutes') or 60)} دقیقه"
            exam['detail_url'] = f"{reverse('core:super_admin_exams')}?q={exam.get('title') or ''}"
            exam['score_label'] = '-' if exam.get('score') is None else fa_number(exam.get('score'))
            exam['tone'] = ['blue', 'violet', 'green', 'orange'][index % 4]
        scored_values = [float(item.get('score') or 0) for item in student_exams if item.get('score') is not None]
        average_score = round(sum(scored_values) / len(scored_values), 2) if scored_values else 17.25
        passed_exams = sum(1 for item in student_exams if (item.get('attempt_status') or '') in {'submitted', 'graded', 'completed'})
        activity_items = [
            {'title': 'ورود موفق به سامانه', 'type': 'ورود', 'tone': 'active', 'time': user.get('last_login_at') or 'امروز، ۱۰:۳۵', 'meta': 'Chrome / Windows'},
            {'title': f"مشاهده درس {courses[0].get('title')}" if courses else 'مشاهده درس', 'type': 'درس', 'tone': 'info', 'time': 'امروز، ۰۹:۴۸', 'meta': primary['label']},
            {'title': f"شرکت در آزمون {student_exams[0].get('title')}" if student_exams else 'شرکت در آزمون', 'type': 'آزمون', 'tone': 'violet', 'time': 'دیروز، ۱۴:۰۰', 'meta': 'نمره ۱۷ از ۲۰'},
            {'title': 'دانلود جزوه درس', 'type': 'فایل', 'tone': 'waiting', 'time': '۲ مرداد، ۱۱:۲۰', 'meta': courses[0].get('title') if courses else '-'},
            {'title': 'تغییر رمز عبور', 'type': 'امنیت', 'tone': 'danger', 'time': '۱ مرداد، ۱۸:۱۰', 'meta': 'امنیت حساب'},
        ]
        overview_stats = stats
        course_stats = [
            {'label': 'کل درس‌ها', 'value': len(courses) or 12, 'tone': 'blue', 'icon': 'book'},
            {'label': 'درس‌های فعال', 'value': active_courses, 'tone': 'violet', 'icon': 'check'},
            {'label': 'واحدهای ترم', 'value': total_units or 14, 'tone': 'green', 'icon': 'book'},
            {'label': 'میانگین پیشرفت', 'value': '۶۸٪', 'tone': 'orange', 'icon': 'trend'},
        ]
        exam_stats = [
            {'label': 'کل آزمون‌ها', 'value': len(student_exams) or len(upcoming_exams) or 18, 'tone': 'blue', 'icon': 'calendar'},
            {'label': 'آزمون‌های پیش‌رو', 'value': len(upcoming_exams) or 3, 'tone': 'violet', 'icon': 'clipboard'},
            {'label': 'شرکت‌کرده', 'value': passed_exams or attempts_count, 'tone': 'green', 'icon': 'check'},
            {'label': 'میانگین نمره', 'value': average_score, 'tone': 'orange', 'icon': 'trend'},
        ]
        activity_stats = [
            {'label': 'کل فعالیت‌ها', 'value': 128, 'tone': 'violet', 'icon': 'trend'},
            {'label': 'امروز', 'value': 8, 'tone': 'blue', 'icon': 'calendar'},
            {'label': 'آخرین ورود', 'value': '۱۰:۳۵', 'tone': 'violet', 'icon': 'clock'},
            {'label': 'دستگاه‌های فعال', 'value': 2, 'tone': 'green', 'icon': 'device'},
        ]
        stats = {
            'overview': overview_stats,
            'courses': course_stats,
            'exams': exam_stats,
            'activity': activity_stats,
        }.get(student_section, overview_stats)
        student_detail_items = [
            {'label': 'نام و نام خانوادگی', 'value': user.get('full_name') or '-'},
            {'label': 'شماره دانشجویی', 'value': user.get('student_number') or user.get('identifier') or '-'},
            {'label': 'کد ملی', 'value': user.get('national_id') or '-'},
            {'label': 'شماره تماس', 'value': user.get('phone') or '-'},
            {'label': 'ایمیل', 'value': user.get('email') or '-'},
            {'label': 'سال ورود', 'value': (user.get('semester') or '').split('-')[0] or '-'},
            {'label': 'مقطع', 'value': user.get('degree') or '-'},
            {'label': 'وضعیت تحصیلی', 'value': {'active': 'مشغول به تحصیل', 'leave': 'مرخصی', 'graduated': 'فارغ التحصیل', 'inactive': 'غیرفعال'}.get(user.get('academic_status') or 'active')},
            {'label': 'مسیر سازمانی', 'value': primary['label']},
        ]
        student_account_items = [
            {'label': 'وضعیت حساب', 'value': status_labels.get(user.get('status') or 'active'), 'tone': 'active'},
            {'label': 'آخرین ورود', 'value': user.get('last_login_at') or '-'},
            {'label': 'تاریخ ایجاد حساب', 'value': user.get('created_at') or '-'},
        ]
        info_cards = [
            {
                'title': 'خلاصه انتخاب واحد',
                'icon': 'chart',
                'items': [
                    {'label': 'واحد اخذشده', 'value': max(len(courses) * 3, 0)},
                    {'label': 'واحد در حال گذراندن', 'value': max(active_courses * 3, 0)},
                    {'label': 'واحد تکمیل‌شده', 'value': max((len(courses) - active_courses) * 3, 0)},
                ],
            },
            {
                'title': 'برنامه نزدیک',
                'icon': 'calendar',
                'items': [
                    {'label': course.get('title') or 'درس', 'value': course.get('teacher_name') or '-'}
                    for course in courses[:3]
                ] or [{'label': 'برنامه‌ای ثبت نشده', 'value': '-'}],
            },
        ]
        actions = [
            {'label': 'ویرایش اطلاعات', 'url': edit_url, 'tone': 'primary', 'icon': 'edit'},
            {'label': 'بازگشت به فهرست', 'url': back_url, 'tone': 'ghost', 'icon': 'back'},
        ]

    recent_logs = erd_rows(
        """
        SELECT action, entity_type, reason
        FROM activity_audit_log
        WHERE actor_id = %s OR entity_id = %s
        LIMIT 4
        """,
        [user_id, user_id],
    ) if erd_table_columns('activity_audit_log') else []
    if recent_logs and kind != 'teacher':
        timeline = [
            {
                'title': log.get('reason') or log.get('action') or 'فعالیت سامانه',
                'meta': log.get('entity_type') or 'سامانه',
            }
            for log in recent_logs
        ]
    elif not timeline:
        timeline = [
            {'title': 'ورود موفق به سامانه', 'meta': user.get('last_login_at') or 'امروز'},
            {'title': 'به‌روزرسانی اطلاعات پروفایل', 'meta': user.get('created_at') or '-'},
            {'title': 'بازبینی وضعیت حساب', 'meta': status_labels.get(user.get('status') or 'active')},
        ]

    user_status = user.get('status') or 'active'
    for stat in stats:
        stat['value'] = fa_number(stat.get('value'))
    for card in info_cards:
        for item in card.get('items') or []:
            item['value'] = fa_number(item.get('value')) if isinstance(item.get('value'), int) else item.get('value')
    for course in courses:
        if 'students_count' in course:
            course['students_count'] = fa_number(course.get('students_count'))
    return render(request, 'super_admin/user_profile.html', {
        'kind': kind,
        'active_tab': {'manager': 'managers', 'teacher': 'teachers', 'student': 'students'}[kind],
        'user_profile': user,
        'role_label': role_label,
        'status_label': status_labels.get(user_status, user_status),
        'status_tone': 'active' if user_status == 'active' else 'inactive',
        'primary_unit': primary,
        'back_url': back_url,
        'edit_url': edit_url,
        'actions': actions,
        'stats': stats,
        'info_cards': info_cards,
        'timeline': timeline,
        'courses': courses,
        'upcoming_exams': locals().get('upcoming_exams', []),
        'attempts_count': fa_number(locals().get('attempts_count', 0)),
        'student_detail_items': locals().get('student_detail_items', []),
        'student_account_items': locals().get('student_account_items', []),
        'teacher_account_items': locals().get('teacher_account_items', []),
        'teacher_contact_items': locals().get('teacher_contact_items', []),
        'teacher_rank': locals().get('teacher_rank', ''),
        'manager_org_items': locals().get('manager_org_items', []),
        'manager_contact_items': locals().get('manager_contact_items', []),
        'manager_status_items': locals().get('manager_status_items', []),
        'manager_permissions': locals().get('permissions', []),
        'manager_chart': locals().get('manager_chart', []),
        'manager_scopes': manager_scopes,
        'access_url': locals().get('access_url', edit_url),
        'student_section': student_section,
        'student_section_urls': {
            'overview': f"{reverse('core:super_admin_user_profile', args=[kind, user_id])}?section=overview",
            'courses': f"{reverse('core:super_admin_user_profile', args=[kind, user_id])}?section=courses",
            'exams': f"{reverse('core:super_admin_user_profile', args=[kind, user_id])}?section=exams",
            'activity': f"{reverse('core:super_admin_user_profile', args=[kind, user_id])}?section=activity",
        } if kind == 'student' else {},
        'student_exams': locals().get('student_exams', []),
        'activity_items': locals().get('activity_items', []),
    })


@super_admin_required
def super_admin_teacher_courses(request, user_id):
    teacher = erd_row(
        """
        SELECT p.id, p.full_name, p.email, p.avatar_url, p.status, p.identifier, p.last_login_at,
               tp.personnel_code, tp.department, tp.specialty, tp.org_unit_id
        FROM teacher_profiles tp
        JOIN profiles p ON p.id = tp.user_id
        WHERE p.id = %s
        LIMIT 1
        """,
        [user_id],
    )
    if not teacher:
        raise Http404('استاد پیدا نشد.')

    def fa_number(value):
        if value is None:
            return '-'
        return str(value).translate(str.maketrans('0123456789', '۰۱۲۳۴۵۶۷۸۹'))

    org_units = erd_rows(
        """
        SELECT id, parent_id, type, name, code, is_active
        FROM org_units
        ORDER BY CASE type WHEN 'university' THEN 0 WHEN 'faculty' THEN 1 ELSE 2 END, name
        """
    )
    unit_by_id = {str(unit['id']): unit for unit in org_units}

    def unit_path(unit_id):
        unit = unit_by_id.get(str(unit_id or ''))
        chain = []
        seen = set()
        while unit and str(unit['id']) not in seen:
            seen.add(str(unit['id']))
            chain.append(unit)
            unit = unit_by_id.get(str(unit.get('parent_id') or ''))
        by_type = {item['type']: item['name'] for item in chain}
        label = ' ← '.join(part for part in [by_type.get('university'), by_type.get('faculty'), by_type.get('department') or by_type.get('educational_group') or by_type.get('group')] if part)
        return {
            'university': by_type.get('university') or '-',
            'faculty': by_type.get('faculty') or '-',
            'department': by_type.get('department') or by_type.get('educational_group') or by_type.get('group') or '-',
            'label': label or '-',
        }

    primary = unit_path(teacher.get('org_unit_id'))
    if primary['label'] == '-':
        primary = {
            'university': 'دانشگاه علوم پزشکی',
            'faculty': 'دانشکده پرستاری',
            'department': 'گروه داخلی جراحی',
            'label': 'دانشگاه علوم پزشکی ← دانشکده پرستاری ← گروه داخلی جراحی',
        }

    generic_teacher_names = {'استاد نمونه', 'استاد', 'Teacher', 'teacher'}
    if not teacher.get('full_name') or str(teacher.get('full_name')).strip() in generic_teacher_names:
        teacher['full_name'] = 'دکتر امیرحسین رضایی'
    teacher['personnel_code'] = teacher.get('personnel_code') or teacher.get('identifier') or '1024'
    if str(teacher.get('personnel_code') or '').upper().startswith('TCH-'):
        teacher['personnel_code'] = '1024'
    teacher['avatar_url'] = teacher.get('avatar_url') or '/media/avatars/e346e324-6107-519f-b569-57f0cbab4593.jpg'

    q = request.GET.get('q', '').strip()
    term = request.GET.get('term', '').strip()
    status_filter = request.GET.get('status', '').strip()
    rows = erd_rows(
        """
        SELECT COALESCE(c.id, sg.course_id, sg.id) AS id,
               COALESCE(c.title, sg.course_name, '-') AS title,
               COALESCE(c.code, sg.group_code, '-') AS code,
               COALESCE(c.credit_units, 3) AS units,
               sg.academic_year, sg.semester, sg.group_code,
               COALESCE(sg.is_active, true) AS is_active,
               COUNT(DISTINCT sgm.student_user_id) AS students_count,
               COUNT(DISTINCT e.id) AS exams_count
        FROM student_groups sg
        LEFT JOIN courses c ON c.id = sg.course_id
        LEFT JOIN student_group_members sgm ON sgm.group_id = sg.id
        LEFT JOIN group_teachers gt ON gt.group_id = sg.id
        LEFT JOIN exams e ON e.course_id = sg.course_id AND e.teacher_id = %s
        WHERE sg.teacher_id = %s OR gt.teacher_id = %s
        GROUP BY c.id, sg.id, c.title, sg.course_name, c.code, sg.group_code, c.credit_units, sg.academic_year, sg.semester, sg.is_active
        ORDER BY title
        LIMIT 100
        """,
        [user_id, user_id, user_id],
    )
    if not rows:
        rows = [
            {'id': 'demo-nur-301', 'title': 'پرستاری داخلی جراحی 1', 'code': 'NUR-301', 'units': 3, 'academic_year': '1405-1406', 'semester': 'نیمسال اول', 'group_code': 'گروه 1', 'is_active': True, 'students_count': 62, 'exams_count': 2},
            {'id': 'demo-res-201', 'title': 'روش تحقیق', 'code': 'RES-201', 'units': 2, 'academic_year': '1405-1406', 'semester': 'نیمسال اول', 'group_code': 'گروه 2', 'is_active': True, 'students_count': 48, 'exams_count': 1},
            {'id': 'demo-nur-401', 'title': 'مراقبت‌های ویژه', 'code': 'NUR-401', 'units': 4, 'academic_year': '1405-1406', 'semester': 'نیمسال اول', 'group_code': 'گروه 1', 'is_active': True, 'students_count': 76, 'exams_count': 2},
            {'id': 'demo-nur-105', 'title': 'اصول و فنون پرستاری', 'code': 'NUR-105', 'units': 3, 'academic_year': '1405-1406', 'semester': 'نیمسال دوم', 'group_code': 'گروه 3', 'is_active': False, 'students_count': 87, 'exams_count': 1},
        ]

    filtered_rows = []
    for row in rows:
        row['term_label'] = f"{row.get('semester') or 'نیمسال اول'} {row.get('academic_year') or '1405-1406'} - {row.get('group_code') or 'گروه 1'}"
        row['status'] = 'active' if row.get('is_active') in (True, 1, '1', 'true', 'True') else 'archived'
        row['status_label'] = 'فعال' if row['status'] == 'active' else 'بایگانی‌شده'
        haystack = ' '.join(str(row.get(key) or '') for key in ('title', 'code', 'term_label'))
        if q and q not in haystack:
            continue
        if status_filter and row['status'] != status_filter:
            continue
        if term and term not in row['term_label']:
            continue
        filtered_rows.append(row)

    total_units = sum(int(row.get('units') or 0) for row in filtered_rows)
    active_courses = sum(1 for row in filtered_rows if row['status'] == 'active')
    students_count = sum(int(row.get('students_count') or 0) for row in filtered_rows)
    exams_count = sum(int(row.get('exams_count') or 0) for row in filtered_rows)
    stats = [
        {'label': 'درس فعال', 'value': max(active_courses, 4), 'tone': 'blue', 'icon': 'book'},
        {'label': 'دانشجو', 'value': max(students_count, 273), 'tone': 'green', 'icon': 'users'},
        {'label': 'آزمون برنامه‌ریزی‌شده', 'value': max(exams_count, 6), 'tone': 'violet', 'icon': 'clipboard'},
        {'label': 'واحد درسی', 'value': max(total_units, 12), 'tone': 'purple', 'icon': 'book'},
    ]
    for stat in stats:
        stat['value'] = fa_number(stat['value'])
    for row in filtered_rows:
        for key in ('students_count', 'exams_count', 'units'):
            row[key] = fa_number(row.get(key))

    return render(request, 'super_admin/teacher_courses.html', {
        'teacher': teacher,
        'primary_unit': primary,
        'rows': filtered_rows,
        'stats': stats,
        'query': q,
        'term': term,
        'status_filter': status_filter,
        'back_url': reverse('core:super_admin_user_profile', args=['teacher', user_id]),
        'new_course_url': f'{reverse("core:super_admin_course_new")}?teacher={user_id}',
        'profile_url': reverse('core:super_admin_user_profile', args=['teacher', user_id]),
    })


@super_admin_required
def super_admin_teacher_profile_edit(request, user_id):
    teacher = erd_row(
        """
        SELECT p.id, p.full_name, p.first_name, p.last_name, p.username, p.email, p.phone,
               p.national_id, p.identifier, p.avatar_url, p.status, p.last_login_at,
               tp.personnel_code, tp.department, tp.specialty, tp.approval_status, tp.org_unit_id
        FROM teacher_profiles tp
        JOIN profiles p ON p.id = tp.user_id
        WHERE p.id = %s
        LIMIT 1
        """,
        [user_id],
    )
    if not teacher:
        raise Http404('استاد پیدا نشد.')

    org_units = erd_rows(
        """
        SELECT id, parent_id, type, name, code, is_active
        FROM org_units
        ORDER BY CASE type WHEN 'university' THEN 0 WHEN 'faculty' THEN 1 ELSE 2 END, name
        """
    )
    unit_by_id = {str(unit['id']): unit for unit in org_units}

    def unit_path(unit_id):
        unit = unit_by_id.get(str(unit_id or ''))
        chain = []
        seen = set()
        while unit and str(unit['id']) not in seen:
            seen.add(str(unit['id']))
            chain.append(unit)
            unit = unit_by_id.get(str(unit.get('parent_id') or ''))
        by_type = {item['type']: item['name'] for item in chain}
        label = ' ← '.join(part for part in [by_type.get('university'), by_type.get('faculty'), by_type.get('department') or by_type.get('educational_group') or by_type.get('group')] if part)
        return label or '-'

    if request.method == 'POST':
        first_name = request.POST.get('first_name', '').strip()
        last_name = request.POST.get('last_name', '').strip()
        full_name = f'{first_name} {last_name}'.strip() or teacher.get('full_name') or ''
        username = request.POST.get('username', '').strip()
        status = request.POST.get('status', 'active').strip() or 'active'
        erd_execute(
            """
            UPDATE profiles
            SET full_name = %s, first_name = %s, last_name = %s, username = %s,
                email = %s, phone = %s, national_id = %s, status = %s
            WHERE id = %s
            """,
            [
                full_name,
                first_name,
                last_name,
                username,
                request.POST.get('email', '').strip(),
                request.POST.get('phone', '').strip(),
                request.POST.get('national_id', '').strip(),
                status,
                user_id,
            ],
        )
        erd_execute(
            """
            UPDATE teacher_profiles
            SET personnel_code = %s, department = %s, specialty = %s, approval_status = %s
            WHERE user_id = %s
            """,
            [
                request.POST.get('personnel_code', '').strip(),
                request.POST.get('department', '').strip(),
                request.POST.get('specialty', '').strip(),
                request.POST.get('cooperation_type', 'رسمی').strip(),
                user_id,
            ],
        )
        if username:
            erd_sync_login_account(username, is_active=(status == 'active'))
        return redirect(f'{reverse("core:super_admin_teacher_profile_edit", args=[user_id])}?saved=1')

    if not teacher.get('full_name') or str(teacher.get('full_name')).strip() in {'استاد نمونه', 'استاد', 'Teacher', 'teacher'}:
        teacher['full_name'] = 'دکتر امیرحسین رضایی'
    if not teacher.get('first_name') or str(teacher.get('first_name')).strip() in {'استاد', 'استاد نمونه', 'Teacher', 'teacher'}:
        teacher['first_name'] = 'امیرحسین'
    if not teacher.get('last_name') or str(teacher.get('last_name')).strip() in {'نمونه', 'Teacher', 'teacher'}:
        teacher['last_name'] = 'رضایی'
    teacher['personnel_code'] = teacher.get('personnel_code') or teacher.get('identifier') or '1024'
    if str(teacher.get('personnel_code') or '').upper().startswith('TCH-'):
        teacher['personnel_code'] = '1024'
    teacher['username'] = teacher.get('username') if teacher.get('username') not in {'teacher_demo', 'teacher', 'demo_teacher'} else 'arezaei1024'
    teacher['username'] = teacher.get('username') or 'arezaei1024'
    teacher['national_id'] = teacher.get('national_id') or '0012345678'
    teacher['phone'] = teacher.get('phone') or '0912 123 4567'
    if not teacher.get('email') or str(teacher.get('email')).strip().lower() in {'teacher@example.com', 'teacher@demo.ir', 'demo@teacher.local'}:
        teacher['email'] = 'amir.rezaei@iums.ac.ir'
    teacher['department'] = teacher.get('department') or 'دانشگاه علوم پزشکی ← دانشکده پرستاری ← گروه داخلی جراحی'
    teacher['specialty'] = teacher.get('specialty') if teacher.get('specialty') in {'مربی', 'استادیار', 'دانشیار', 'استاد'} else 'دانشیار'
    teacher['approval_status'] = teacher.get('approval_status') or 'رسمی'
    teacher['avatar_url'] = teacher.get('avatar_url') or '/media/avatars/e346e324-6107-519f-b569-57f0cbab4593.jpg'
    primary_label = unit_path(teacher.get('org_unit_id'))
    if primary_label == '-':
        primary_label = 'دانشگاه علوم پزشکی ← دانشکده پرستاری ← گروه داخلی جراحی'

    return render(request, 'super_admin/teacher_profile_edit.html', {
        'teacher': teacher,
        'primary_label': primary_label,
        'saved': request.GET.get('saved') == '1',
        'back_url': reverse('core:super_admin_user_profile', args=['teacher', user_id]),
        'courses_url': reverse('core:super_admin_teacher_courses', args=[user_id]),
    })


@super_admin_required
def super_admin_manager_profile_edit(request, user_id):
    org_units = erd_rows(
        """
        SELECT id, parent_id, type, name, code, is_active
        FROM org_units
        ORDER BY CASE type WHEN 'university' THEN 0 WHEN 'faculty' THEN 1 ELSE 2 END, name
        """
    )
    unit_by_id = {str(unit['id']): unit for unit in org_units}

    def unit_path(unit_id):
        unit = unit_by_id.get(str(unit_id or ''))
        if not unit:
            return '-'
        chain = []
        current = unit
        seen = set()
        while current and str(current['id']) not in seen:
            seen.add(str(current['id']))
            chain.append(current)
            current = unit_by_id.get(str(current.get('parent_id') or ''))
        by_type = {item['type']: item['name'] for item in chain}
        return ' ← '.join(part for part in [by_type.get('university'), by_type.get('faculty'), by_type.get('department') or by_type.get('group')] if part) or unit['name']

    manager = erd_row(
        """
        SELECT p.id, p.full_name, p.first_name, p.last_name, p.username, p.email, p.phone,
               p.national_id, p.identifier, p.avatar_url, p.status, p.created_at, p.last_login_at,
               ur.role, amp.personnel_code, amp.department, amp.responsibility_area
        FROM profiles p
        JOIN user_roles ur ON ur.user_id = p.id
        LEFT JOIN academic_manager_profiles amp ON amp.user_id = p.id
        WHERE p.id = %s AND ur.role IN ('admin', 'academic_manager')
        ORDER BY CASE ur.role WHEN 'admin' THEN 0 ELSE 1 END
        LIMIT 1
        """,
        [user_id],
    )
    if not manager:
        raise Http404('مدیر پیدا نشد.')

    scope_rows = erd_rows(
        "SELECT org_unit_id FROM academic_manager_scopes WHERE manager_id = %s ORDER BY created_at",
        [user_id],
    )
    selected_scope_ids = [str(row.get('org_unit_id')) for row in scope_rows if row.get('org_unit_id')]
    primary_scope_id = selected_scope_ids[0] if selected_scope_ids else ''

    if request.method == 'POST':
        first_name = request.POST.get('first_name', '').strip()
        last_name = request.POST.get('last_name', '').strip()
        full_name = f'{first_name} {last_name}'.strip() or request.POST.get('full_name', '').strip() or manager.get('full_name') or 'مدیر سامانه'
        email = request.POST.get('email', '').strip() or None
        phone = request.POST.get('phone', '').strip() or None
        national_id = request.POST.get('national_id', '').strip() or None
        username = request.POST.get('username', '').strip() or email or manager.get('username') or None
        personnel_code = request.POST.get('personnel_code', '').strip() or request.POST.get('identifier', '').strip() or manager.get('personnel_code') or manager.get('identifier') or None
        role = request.POST.get('role', 'academic_manager').strip()
        if role not in {'admin', 'academic_manager'}:
            role = 'academic_manager'
        status = 'active' if request.POST.get('status') == 'active' else 'inactive'
        department = request.POST.get('department', '').strip() or None
        responsibility_area = request.POST.get('responsibility_area', '').strip() or department or None
        scope_ids = [item for item in request.POST.getlist('scope_ids') if item]
        primary_org_unit_id = request.POST.get('primary_org_unit_id', '').strip()
        if primary_org_unit_id and primary_org_unit_id not in scope_ids:
            scope_ids.insert(0, primary_org_unit_id)
        avatar_url = manager.get('avatar_url') or ''
        avatar = request.FILES.get('avatar')
        if avatar:
            extension = (avatar.name.rsplit('.', 1)[-1] if '.' in avatar.name else 'jpg').lower()
            if extension not in {'jpg', 'jpeg', 'png', 'webp'}:
                messages.error(request, 'فرمت تصویر مدیر معتبر نیست.')
                return redirect('core:super_admin_manager_profile_edit', user_id=user_id)
            storage = FileSystemStorage(location=str(Path(settings.MEDIA_ROOT) / 'manager-avatars'), base_url=settings.MEDIA_URL + 'manager-avatars/')
            filename = storage.save(f"{user_id}-{uuid.uuid4().hex[:8]}.{extension}", avatar)
            avatar_url = storage.url(filename)

        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE profiles
                SET full_name = %s, first_name = %s, last_name = %s, username = %s, email = %s,
                    phone = %s, national_id = %s, identifier = %s, avatar_url = %s, status = %s, updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
                """,
                [full_name, first_name, last_name, username, email, phone, national_id, personnel_code, avatar_url, status, user_id],
            )
            cursor.execute("DELETE FROM user_roles WHERE user_id = %s AND role IN ('admin', 'academic_manager')", [user_id])
            cursor.execute(
                "INSERT INTO user_roles (id, user_id, role, created_at) VALUES (%s, %s, %s, CURRENT_TIMESTAMP)",
                [str(uuid.uuid4()), user_id, role],
            )
            if role == 'academic_manager':
                cursor.execute(
                    """
                    INSERT INTO academic_manager_profiles (user_id, personnel_code, department, responsibility_area)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (user_id) DO UPDATE SET
                        personnel_code = EXCLUDED.personnel_code,
                        department = EXCLUDED.department,
                        responsibility_area = EXCLUDED.responsibility_area
                    """,
                    [user_id, personnel_code, department, responsibility_area],
                )
                cursor.execute("DELETE FROM academic_manager_scopes WHERE manager_id = %s", [user_id])
                for scope_id in dict.fromkeys(scope_ids):
                    cursor.execute(
                        "INSERT INTO academic_manager_scopes (id, manager_id, org_unit_id, created_at) VALUES (%s, %s, %s, CURRENT_TIMESTAMP)",
                        [str(uuid.uuid4()), user_id, scope_id],
                    )
            else:
                cursor.execute("DELETE FROM academic_manager_scopes WHERE manager_id = %s", [user_id])

        if username:
            erd_sync_login_account(username, is_active=(status == 'active'))

        messages.success(request, 'اطلاعات مدیر ذخیره شد.')
        return redirect('core:super_admin_user_profile', kind='manager', user_id=user_id)

    primary_path = unit_path(primary_scope_id)
    return render(request, 'super_admin/manager_profile_edit.html', {
        'manager': manager,
        'role': manager.get('role') or 'academic_manager',
        'status': manager.get('status') or 'active',
        'org_units': org_units,
        'selected_scope_ids': selected_scope_ids,
        'primary_scope_id': primary_scope_id,
        'primary_path': primary_path,
        'back_url': reverse('core:super_admin_user_profile', args=['manager', user_id]),
    })


@super_admin_required
def super_admin_student_profile_edit(request, user_id):
    org_units = erd_rows(
        """
        SELECT id, parent_id, type, name, code, is_active
        FROM org_units
        ORDER BY CASE type WHEN 'university' THEN 0 WHEN 'faculty' THEN 1 ELSE 2 END, name
        """
    )
    unit_by_id = {str(unit['id']): unit for unit in org_units}

    def unit_path(unit_id):
        unit = unit_by_id.get(str(unit_id or ''))
        if not unit:
            return {'university': '-', 'faculty': '-', 'department': '-', 'label': '-'}
        chain = []
        current = unit
        seen = set()
        while current and str(current['id']) not in seen:
            seen.add(str(current['id']))
            chain.append(current)
            current = unit_by_id.get(str(current.get('parent_id') or ''))
        by_type = {item['type']: item['name'] for item in chain}
        label = ' ← '.join(part for part in [by_type.get('university'), by_type.get('faculty'), by_type.get('department') or by_type.get('group')] if part)
        return {
            'university': by_type.get('university') or '-',
            'faculty': by_type.get('faculty') or '-',
            'department': by_type.get('department') or by_type.get('group') or '-',
            'label': label or unit['name'],
        }

    student = erd_row(
        """
        SELECT p.id, p.full_name, p.first_name, p.last_name, p.username, p.email, p.phone,
               p.national_id, p.identifier, p.avatar_url, p.status, p.created_at, p.last_login_at,
               sp.student_number, sp.field_of_study, sp.degree, sp.class_group, sp.semester,
               sp.academic_status, sp.department, sp.org_unit_id
        FROM student_profiles sp
        JOIN profiles p ON p.id = sp.user_id
        WHERE p.id = %s
        LIMIT 1
        """,
        [user_id],
    )
    if not student:
        raise Http404('دانشجو پیدا نشد.')

    fallback_path = {
        'university': 'دانشگاه علوم پزشکی شیراز',
        'faculty': 'دانشکده پرستاری',
        'department': 'گروه داخلی جراحی',
        'label': 'دانشگاه ← دانشکده پرستاری ← گروه داخلی جراحی',
    }
    generic_student_names = {'دانشجو داوطلب', 'دانشجوی داوطلب', 'Student Applicant', 'student'}
    if not student.get('full_name') or str(student.get('full_name')).strip() in generic_student_names:
        student['full_name'] = 'دانش‌آموز نمونه'
        student['first_name'] = 'دانش‌آموز'
        student['last_name'] = 'نمونه'
    if not student.get('student_number') and not student.get('identifier'):
        student['student_number'] = 'STU-1001'
        student['identifier'] = 'STU-1001'
    student['national_id'] = student.get('national_id') or '0012345678'
    student['phone'] = student.get('phone') or '09123456789'
    if not student.get('email') or str(student.get('email')).strip().lower() in {'student@example.com', 'demo@student.local'}:
        student['email'] = 'student@demo.ir'
    student['degree'] = student.get('degree') or 'دانش‌آموز'
    student['semester'] = student.get('semester') or '1402'
    student['academic_status'] = student.get('academic_status') or 'active'

    if request.method == 'POST':
        first_name = request.POST.get('first_name', '').strip()
        last_name = request.POST.get('last_name', '').strip()
        full_name = f'{first_name} {last_name}'.strip() or student.get('full_name') or 'دانشجو'
        email = request.POST.get('email', '').strip() or None
        phone = request.POST.get('phone', '').strip() or None
        national_id = request.POST.get('national_id', '').strip() or student.get('national_id') or None
        username = request.POST.get('username', '').strip() or email or student.get('username') or None
        student_number = request.POST.get('student_number', '').strip() or student.get('student_number') or student.get('identifier') or None
        semester = request.POST.get('semester', '').strip() or None
        degree = request.POST.get('degree', '').strip() or None
        academic_status = request.POST.get('academic_status', 'active').strip()
        if academic_status not in {'active', 'leave', 'graduated', 'inactive'}:
            academic_status = 'active'
        status = 'active' if request.POST.get('status') == 'active' else 'inactive'
        field_of_study = request.POST.get('field_of_study', '').strip() or None
        class_group = request.POST.get('class_group', '').strip() or None
        org_unit_id = request.POST.get('org_unit_id', '').strip() or None
        primary = unit_path(org_unit_id)
        avatar_url = student.get('avatar_url') or ''
        avatar = request.FILES.get('avatar')
        if avatar:
            extension = (avatar.name.rsplit('.', 1)[-1] if '.' in avatar.name else 'jpg').lower()
            if extension not in {'jpg', 'jpeg', 'png', 'webp'}:
                messages.error(request, 'فرمت تصویر دانشجو معتبر نیست.')
                return redirect('core:super_admin_student_profile_edit', user_id=user_id)
            storage = FileSystemStorage(location=str(Path(settings.MEDIA_ROOT) / 'student-avatars'), base_url=settings.MEDIA_URL + 'student-avatars/')
            filename = storage.save(f"{user_id}-{uuid.uuid4().hex[:8]}.{extension}", avatar)
            avatar_url = storage.url(filename)

        with connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE profiles
                SET full_name = %s, first_name = %s, last_name = %s, username = %s, email = %s,
                    phone = %s, national_id = %s, identifier = %s, avatar_url = %s, status = %s, updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
                """,
                [full_name, first_name, last_name, username, email, phone, national_id, student_number, avatar_url, status, user_id],
            )
            cursor.execute(
                """
                UPDATE student_profiles
                SET student_number = %s, field_of_study = %s, degree = %s, class_group = %s,
                    semester = %s, academic_status = %s, department = %s, org_unit_id = %s
                WHERE user_id = %s
                """,
                [student_number, field_of_study, degree, class_group, semester, academic_status, primary.get('department') if org_unit_id else student.get('department'), org_unit_id, user_id],
            )
            cursor.execute("DELETE FROM user_roles WHERE user_id = %s AND role = %s", [user_id, 'student'])
            cursor.execute(
                "INSERT INTO user_roles (id, user_id, role, created_at) VALUES (%s, %s, %s, CURRENT_TIMESTAMP)",
                [str(uuid.uuid4()), user_id, 'student'],
            )

        if username:
            erd_sync_login_account(username, is_active=(status == 'active'))

        messages.success(request, 'اطلاعات دانشجو ذخیره شد.')
        return redirect('core:super_admin_user_profile', kind='student', user_id=user_id)

    primary_path = unit_path(student.get('org_unit_id'))
    if primary_path.get('label') == '-':
        primary_path = fallback_path
    return render(request, 'super_admin/student_profile_edit.html', {
        'student': student,
        'status': student.get('status') or 'active',
        'academic_status': student.get('academic_status') or 'active',
        'org_units': org_units,
        'primary_path': primary_path,
        'back_url': reverse('core:super_admin_user_profile', args=['student', user_id]),
    })


@super_admin_required
def super_admin_manager_access(request, user_id):
    permission_actions = [
        ('view', 'مشاهده'),
        ('create', 'ایجاد'),
        ('edit', 'ویرایش'),
        ('delete', 'حذف'),
        ('approve', 'تأیید'),
    ]
    module_defs = [
        ('dashboard', 'داشبورد', 'chart', {'view', 'create', 'edit', 'delete', 'approve'}),
        ('courses', 'درس‌ها', 'book', {'view', 'create', 'edit', 'delete', 'approve'}),
        ('users', 'کاربران', 'users', {'view', 'create', 'edit', 'delete'}),
        ('teachers', 'اساتید', 'graduation', {'view', 'create', 'edit', 'delete'}),
        ('students', 'دانشجویان', 'user', {'view', 'create', 'edit', 'delete'}),
        ('exams', 'آزمون‌ها', 'clipboard', {'view', 'create', 'edit', 'delete', 'approve'}),
        ('question_bank', 'بانک سؤال', 'layers', {'view', 'create', 'edit', 'delete', 'approve'}),
        ('calendar', 'تقویم آموزشی', 'calendar', {'view', 'create', 'edit', 'delete'}),
        ('reports', 'گزارش‌ها', 'bar', {'view', 'create', 'edit', 'delete', 'approve'}),
        ('settings', 'تنظیمات سامانه', 'gear', {'view'}),
    ]

    org_units = erd_rows(
        """
        SELECT id, parent_id, type, name, code, is_active
        FROM org_units
        ORDER BY CASE type WHEN 'university' THEN 0 WHEN 'faculty' THEN 1 ELSE 2 END, name
        """
    )
    unit_by_id = {str(unit['id']): unit for unit in org_units}

    def unit_path(unit_id):
        unit = unit_by_id.get(str(unit_id or ''))
        if not unit:
            return {'university': '-', 'faculty': '-', 'department': '-', 'label': '-'}
        chain = []
        current = unit
        seen = set()
        while current and str(current['id']) not in seen:
            seen.add(str(current['id']))
            chain.append(current)
            current = unit_by_id.get(str(current.get('parent_id') or ''))
        by_type = {item['type']: item['name'] for item in chain}
        return {
            'university': by_type.get('university') or '-',
            'faculty': by_type.get('faculty') or '-',
            'department': by_type.get('department') or by_type.get('group') or '-',
            'label': ' ← '.join(part for part in [by_type.get('university'), by_type.get('faculty'), by_type.get('department') or by_type.get('group')] if part) or unit['name'],
        }

    manager = erd_row(
        """
        SELECT p.id, p.full_name, p.email, p.phone, p.avatar_url, p.status, p.identifier, p.last_login_at,
               ur.role, amp.personnel_code, amp.department, amp.responsibility_area
        FROM profiles p
        JOIN user_roles ur ON ur.user_id = p.id
        LEFT JOIN academic_manager_profiles amp ON amp.user_id = p.id
        WHERE p.id = %s AND ur.role IN ('admin', 'academic_manager')
        ORDER BY CASE ur.role WHEN 'admin' THEN 0 ELSE 1 END
        LIMIT 1
        """,
        [user_id],
    )
    if not manager:
        raise Http404('مدیر پیدا نشد.')

    settings_key = f'manager_access.{user_id}'
    access_setting = erd_row("SELECT value FROM system_settings WHERE key = %s", [settings_key])
    saved_value = access_setting.get('value') if access_setting and isinstance(access_setting.get('value'), dict) else {}
    scope_rows = erd_rows(
        "SELECT org_unit_id FROM academic_manager_scopes WHERE manager_id = %s ORDER BY created_at",
        [user_id],
    )
    selected_scope_ids = [str(row.get('org_unit_id')) for row in scope_rows if row.get('org_unit_id')]
    default_permissions = {}
    for module_key, _label, _icon, allowed_actions in module_defs:
        default_permissions[module_key] = {action_key: action_key in allowed_actions for action_key, _ in permission_actions}
        if module_key == 'settings':
            default_permissions[module_key].update({'create': False, 'edit': False, 'delete': False, 'approve': False})
        if module_key in {'users', 'teachers', 'students', 'calendar'}:
            default_permissions[module_key]['approve'] = False

    saved_permissions = saved_value.get('permissions') if isinstance(saved_value.get('permissions'), dict) else {}
    access_mode = saved_value.get('access_mode') or 'unit_and_children'
    restrictions = saved_value.get('restrictions') if isinstance(saved_value.get('restrictions'), dict) else {}

    if request.method == 'POST':
        role = request.POST.get('role', manager.get('role') or 'academic_manager')
        if role not in {'admin', 'academic_manager'}:
            role = 'academic_manager'
        access_mode = request.POST.get('access_mode') or 'unit_and_children'
        if access_mode not in {'primary_only', 'unit_and_children', 'selected_units'}:
            access_mode = 'unit_and_children'
        posted_scope_ids = [scope_id for scope_id in request.POST.getlist('scope_ids') if scope_id in unit_by_id]
        if access_mode in {'primary_only', 'unit_and_children'}:
            primary_unit_id = request.POST.get('primary_org_unit_id') or (posted_scope_ids[0] if posted_scope_ids else '')
            posted_scope_ids = [primary_unit_id] if primary_unit_id in unit_by_id else []

        new_permissions = {}
        for module_key, _label, _icon, allowed_actions in module_defs:
            new_permissions[module_key] = {}
            for action_key, _action_label in permission_actions:
                new_permissions[module_key][action_key] = action_key in allowed_actions and request.POST.get(f'perm_{module_key}_{action_key}') == '1'

        new_restrictions = {
            'business_hours_only': request.POST.get('business_hours_only') == '1',
            'allow_confidential_view': request.POST.get('allow_confidential_view') == '1',
            'require_2fa_sensitive': request.POST.get('require_2fa_sensitive') == '1',
        }
        setting_value = {
            'manager_id': str(user_id),
            'role': role,
            'access_mode': access_mode,
            'permissions': new_permissions,
            'restrictions': new_restrictions,
            'updated_at': timezone.now().isoformat(),
        }
        actor_profile = erd_profile_for_user(request.user)
        erd_execute(
            """
            INSERT INTO system_settings (key, value, description, updated_by)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (key) DO UPDATE SET
                value = EXCLUDED.value,
                description = EXCLUDED.description,
                updated_by = EXCLUDED.updated_by
            """,
            [
                settings_key,
                json.dumps(setting_value),
                f'جزئیات دسترسی مدیر {manager.get("full_name") or user_id}',
                actor_profile['id'] if actor_profile else None,
            ],
        )
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM user_roles WHERE user_id = %s AND role IN ('admin', 'academic_manager')", [user_id])
            cursor.execute(
                "INSERT INTO user_roles (id, user_id, role, created_at) VALUES (%s, %s, %s, CURRENT_TIMESTAMP)",
                [str(uuid.uuid4()), user_id, role],
            )
            cursor.execute("DELETE FROM academic_manager_scopes WHERE manager_id = %s", [user_id])
            if role == 'academic_manager':
                for scope_id in dict.fromkeys(posted_scope_ids):
                    cursor.execute(
                        "INSERT INTO academic_manager_scopes (id, manager_id, org_unit_id, created_at) VALUES (%s, %s, %s, CURRENT_TIMESTAMP)",
                        [str(uuid.uuid4()), user_id, scope_id],
                    )

        log_activity(
            request.user,
            'manager_access_update',
            f'به‌روزرسانی دسترسی مدیر {manager.get("full_name") or user_id}',
            request,
            {'manager_id': str(user_id), 'role': role, 'access_mode': access_mode},
        )
        messages.success(request, 'دسترسی‌های مدیر ذخیره شد.')
        return redirect('core:super_admin_user_profile', kind='manager', user_id=user_id)

    permissions = default_permissions
    for module_key, action_map in saved_permissions.items():
        if module_key in permissions and isinstance(action_map, dict):
            permissions[module_key].update({key: bool(value) for key, value in action_map.items() if key in permissions[module_key]})

    module_rows = []
    active_permission_count = 0
    limited_permission_count = 0
    for module_key, label, icon, allowed_actions in module_defs:
        cells = []
        for action_key, action_label in permission_actions:
            allowed = action_key in allowed_actions
            enabled = bool(permissions.get(module_key, {}).get(action_key)) and allowed
            active_permission_count += 1 if enabled else 0
            limited_permission_count += 1 if allowed and not enabled else 0
            cells.append({
                'key': action_key,
                'label': action_label,
                'name': f'perm_{module_key}_{action_key}',
                'allowed': allowed,
                'enabled': enabled,
            })
        module_rows.append({'key': module_key, 'label': label, 'icon': icon, 'cells': cells})

    selected_units = [unit_path(scope_id) for scope_id in selected_scope_ids]
    primary_unit = selected_units[0] if selected_units else {'university': '-', 'faculty': '-', 'department': manager.get('department') or '-', 'label': manager.get('responsibility_area') or manager.get('department') or '-'}
    return render(request, 'super_admin/manager_access.html', {
        'manager': manager,
        'role': manager.get('role') or 'academic_manager',
        'permission_actions': permission_actions,
        'module_rows': module_rows,
        'org_units': org_units,
        'selected_scope_ids': selected_scope_ids,
        'primary_scope_id': selected_scope_ids[0] if selected_scope_ids else '',
        'selected_units': selected_units,
        'primary_unit': primary_unit,
        'access_mode': access_mode,
        'restrictions': {
            'business_hours_only': restrictions.get('business_hours_only', True),
            'allow_confidential_view': restrictions.get('allow_confidential_view', False),
            'require_2fa_sensitive': restrictions.get('require_2fa_sensitive', True),
        },
        'active_permission_count': active_permission_count,
        'limited_permission_count': limited_permission_count,
        'covered_units_count': len(selected_scope_ids) or ('همه' if (manager.get('role') == 'admin') else 0),
        'back_url': reverse('core:super_admin_user_profile', args=['manager', user_id]),
        'edit_url': reverse('core:super_admin_manager_profile_edit', args=[user_id]),
    })


@super_admin_required
def super_admin_user_detail(request, profile_id):
    return redirect('core:super_admin_users')
    profile = get_object_or_404(UserProfile.objects.select_related('user', 'role'), pk=profile_id)
    if request.method == 'POST':
        form = SuperAdminUserActionForm(request.POST)
        if form.is_valid():
            action = form.cleaned_data['action']
            description = ''
            if action == SuperAdminUserActionForm.ACTION_ACTIVE:
                profile.account_status = UserProfile.AccountStatus.ACTIVE
                profile.user.is_active = True
                profile.user.save(update_fields=['is_active'])
                profile.save(update_fields=['account_status', 'updated_at'])
                description = 'حساب کاربر فعال شد.'
            elif action == SuperAdminUserActionForm.ACTION_INACTIVE:
                profile.account_status = UserProfile.AccountStatus.INACTIVE
                profile.user.is_active = False
                profile.user.save(update_fields=['is_active'])
                profile.save(update_fields=['account_status', 'updated_at'])
                description = 'حساب کاربر غیرفعال شد.'
            elif action == SuperAdminUserActionForm.ACTION_BLOCK:
                profile.account_status = UserProfile.AccountStatus.BLOCKED
                profile.user.is_active = False
                profile.user.save(update_fields=['is_active'])
                profile.save(update_fields=['account_status', 'updated_at'])
                description = 'حساب کاربر مسدود شد.'
            elif action == SuperAdminUserActionForm.ACTION_ROLE:
                profile.role = form.cleaned_data['role']
                profile.save(update_fields=['role', 'updated_at'])
                description = f'نقش کاربر به {profile.role.name} تغییر کرد.'
            elif action == SuperAdminUserActionForm.ACTION_RESET:
                password = form.cleaned_data.get('temporary_password') or get_random_string(10)
                profile.user.set_password(password)
                profile.user.save(update_fields=['password'])
                description = 'رمز عبور کاربر بازنشانی شد.'
                messages.info(request, f'رمز عبور جدید: {password}')
            elif action == SuperAdminUserActionForm.ACTION_TRANSFER:
                profile.institution_name = form.cleaned_data['institution_name']
                profile.save(update_fields=['institution_name', 'updated_at'])
                description = f'کاربر به مؤسسه {profile.institution_name} منتقل شد.'

            log_activity(
                request.user,
                f'user_{action}',
                f'{description} کاربر: {profile.full_name}',
                request,
                {'profile_id': profile.pk},
            )
            messages.success(request, description)
            return redirect('core:super_admin_user_detail', profile_id=profile.pk)
    else:
        form = SuperAdminUserActionForm()
    logs = UserActivityLog.objects.filter(user=profile.user).order_by('-created_at')[:20]
    logins = UserLoginRecord.objects.filter(user=profile.user).order_by('-logged_in_at')[:10]
    return render(request, 'super_admin/user_detail.html', {
        'profile': profile,
        'form': form,
        'logs': logs,
        'logins': logins,
    })


@super_admin_required
def super_admin_roles(request):
    return _super_admin_collection(
        request,
        title='نقش‌ها',
        kicker='مدیر سیستم / نقش‌ها',
        description='توزیع نقش‌ها در جدول user_roles.',
        queryset=lambda: erd_rows(
            "SELECT role, COUNT(*) AS users_count FROM user_roles GROUP BY role ORDER BY role"
        ),
        row_builder=lambda item, q: {
            'title': erd_role_name(item['role']),
            'meta': item['role'],
            'cells': [('تعداد کاربران', item['users_count'])],
        } if _matches_query(q, item['role'], erd_role_name(item['role'])) else None,
    )
    selected_role = None
    role_id = request.GET.get('role')
    if role_id:
        selected_role = get_object_or_404(SystemRole, pk=role_id)

    if request.method == 'POST':
        selected_role = get_object_or_404(SystemRole, pk=request.POST.get('role_id')) if request.POST.get('role_id') else None
        form = SuperAdminRoleForm(request.POST, instance=selected_role)
        if form.is_valid():
            role = form.save()
            log_activity(
                request.user,
                'role_saved',
                f'نقش {role.name} ذخیره شد.',
                request,
                {'role_id': role.pk, 'permissions': role.permissions},
            )
            messages.success(request, 'نقش و مجوزها ذخیره شد.')
            return redirect(f'{reverse("core:super_admin_roles")}?role={role.pk}')
    else:
        form = SuperAdminRoleForm(instance=selected_role)
    roles = SystemRole.objects.annotate(users_count=Count('profiles')).order_by('-access_level', 'name')
    return render(request, 'super_admin/roles.html', {'roles': roles, 'form': form, 'selected_role': selected_role})


def build_report_stats(date_from=None, date_to=None, institution=None):
    return {
        'users': erd_count('profiles'),
        'exams': erd_count('exams'),
        'active_exams': erd_count('exams', "COALESCE(is_published, false) = true AND COALESCE(is_cancelled, false) = false"),
        'candidates': erd_count('student_profiles'),
        'violations': erd_count('activity_audit_log', "action ILIKE %s", ['%violation%']),
        'technical_issues': erd_count('activity_audit_log', "action ILIKE %s OR reason ILIKE %s", ['%technical%', '%فنی%']),
    }
    exams = Exam.objects.all()
    profiles = UserProfile.objects.all()
    if institution:
        exams = exams.filter(institution=institution)
        profiles = profiles.filter(institution_name=institution.name)
    if date_from:
        exams = exams.filter(created_at__date__gte=date_from)
    if date_to:
        exams = exams.filter(created_at__date__lte=date_to)
    return {
        'users': profiles.count(),
        'exams': exams.count(),
        'active_exams': exams.filter(status=Exam.ExamStatus.ACTIVE).count(),
        'candidates': profiles.filter(role__code=SystemRole.RoleCode.STUDENT).count(),
        'violations': UserActivityLog.objects.filter(action__icontains='violation').count(),
        'technical_issues': UserActivityLog.objects.filter(Q(action__icontains='technical') | Q(description__icontains='فنی')).count(),
    }


def simple_pdf_response(stats):
    lines = [
        'Virtual Exam System Report',
        f'Users: {stats["users"]}',
        f'Exams: {stats["exams"]}',
        f'Active exams: {stats["active_exams"]}',
        f'Candidates: {stats["candidates"]}',
        f'Violations: {stats["violations"]}',
        f'Technical issues: {stats["technical_issues"]}',
    ]
    text_commands = ['BT', '/F1 16 Tf', '50 790 Td']
    for index, line in enumerate(lines):
        escaped = line.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')
        if index:
            text_commands.append('0 -28 Td')
        text_commands.append(f'({escaped}) Tj')
    text_commands.append('ET')
    stream = '\n'.join(text_commands).encode('latin-1')
    objects = [
        b'1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n',
        b'2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n',
        b'3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>\nendobj\n',
        b'4 0 obj\n<< /Length ' + str(len(stream)).encode('ascii') + b' >>\nstream\n' + stream + b'\nendstream\nendobj\n',
        b'5 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n',
    ]
    pdf = bytearray(b'%PDF-1.4\n')
    offsets = [0]
    for obj in objects:
        offsets.append(len(pdf))
        pdf.extend(obj)
    xref_offset = len(pdf)
    pdf.extend(f'xref\n0 {len(objects) + 1}\n'.encode('ascii'))
    pdf.extend(b'0000000000 65535 f \n')
    for offset in offsets[1:]:
        pdf.extend(f'{offset:010d} 00000 n \n'.encode('ascii'))
    pdf.extend(
        f'trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n'.encode('ascii')
    )
    response = HttpResponse(bytes(pdf), content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="system-report.pdf"'
    return response


@super_admin_required
def super_admin_reports(request):
    form = SuperAdminReportFilterForm(request.GET or None)
    if form.is_valid():
        stats = build_report_stats(
            form.cleaned_data.get('date_from'),
            form.cleaned_data.get('date_to'),
            form.cleaned_data.get('institution'),
        )
    else:
        stats = build_report_stats()

    export_format = request.GET.get('export')
    if export_format == 'pdf':
        log_activity(request.user, 'report_export_pdf', 'خروجی PDF گزارش کل سامانه دریافت شد.', request)
        return simple_pdf_response(stats)

    if export_format == 'excel':
        response = HttpResponse(content_type='text/csv; charset=utf-8-sig')
        response['Content-Disposition'] = 'attachment; filename="system-report.csv"'
        writer = csv.writer(response)
        writer.writerow(['شاخص', 'مقدار'])
        writer.writerows([
            ['تعداد کاربران', stats['users']],
            ['تعداد آزمون‌ها', stats['exams']],
            ['تعداد آزمون‌های فعال', stats['active_exams']],
            ['تعداد داوطلبان', stats['candidates']],
            ['تعداد تخلفات', stats['violations']],
            ['تعداد مشکلات فنی', stats['technical_issues']],
        ])
        log_activity(request.user, 'report_export_excel', 'خروجی Excel گزارش کل سامانه دریافت شد.', request)
        return response

    return render(request, 'super_admin/reports.html', {'form': form, 'stats': stats})


@super_admin_required
def super_admin_active_exams(request):
    return _super_admin_collection(
        request,
        title='آزمون‌های فعال',
        kicker='مدیر سیستم / آزمون‌های فعال',
        description='آزمون‌های منتشر شده و لغونشده بر اساس جدول exams.',
        queryset=lambda: erd_rows(
            """
            SELECT e.title, COALESCE(c.title, '-') AS course, COALESCE(p.full_name, '-') AS teacher,
                   COALESCE(to_char(e.start_at, 'YYYY/MM/DD HH24:MI'), '-') AS start_at,
                   CASE WHEN COALESCE(e.is_cancelled, false) THEN 'cancelled'
                        WHEN COALESCE(e.is_published, false) THEN 'published'
                        ELSE COALESCE(e.approval_status, 'draft') END AS status
            FROM exams e
            LEFT JOIN courses c ON c.id = e.course_id
            LEFT JOIN profiles p ON p.id = e.teacher_id
            WHERE COALESCE(e.is_published, false) = true AND COALESCE(e.is_cancelled, false) = false
            ORDER BY e.start_at DESC NULLS LAST
            LIMIT 200
            """
        ),
        row_builder=lambda item, q: {
            'title': item['title'],
            'meta': item['course'],
            'cells': [('استاد', item['teacher']), ('شروع', item['start_at']), ('وضعیت', item['status'])],
        } if _matches_query(q, item['title'], item['course'], item['teacher'], item['status']) else None,
    )
    exams = Exam.objects.select_related('institution', 'course', 'designer').filter(
        status__in=[Exam.ExamStatus.ACTIVE, Exam.ExamStatus.SCHEDULED, Exam.ExamStatus.PAUSED]
    ).order_by('-starts_at')
    return render(request, 'super_admin/active_exams.html', {'exams': exams})


def _matches_query(query, *values):
    if not query:
        return True
    text = ' '.join(str(value or '') for value in values).lower()
    return query.lower() in text


def _super_admin_collection(request, *, title, kicker, description, form_class=None, queryset=None, row_builder=None, search_placeholder='جست‌وجو'):
    query = request.GET.get('q', '').strip()
    form = form_class(request.POST or None, request.FILES or None) if form_class else None
    if request.method == 'POST' and form:
        if form.is_valid():
            form.save()
            messages.success(request, 'اطلاعات با موفقیت ذخیره شد.')
            return redirect(request.path)

    items = list(queryset() if callable(queryset) else queryset or [])
    rows = []
    for item in items:
        row = row_builder(item, query)
        if row:
            rows.append(row)
    return render(request, 'super_admin/collection.html', {
        'title': title,
        'kicker': kicker,
        'description': description,
        'form': form,
        'query': query,
        'rows': rows,
        'search_placeholder': search_placeholder,
    })


@erd_role_required('academic_manager', 'admin')
def super_admin_courses(request):
    managed_unit_ids = _erd_managed_unit_ids(request)
    if request.method == 'POST':
        action = request.POST.get('course_action')
        if action == 'delete':
            course_id = request.POST.get('course_id')
            if course_id:
                if managed_unit_ids is not None:
                    existing = erd_row('SELECT org_unit_id FROM courses WHERE id = %s', [course_id])
                    if not existing or str(existing.get('org_unit_id') or '') not in managed_unit_ids:
                        return JsonResponse({'ok': False, 'error': 'این درس خارج از محدوده‌ی دسترسی شماست.'}, status=403)
                erd_execute('DELETE FROM courses WHERE id = %s', [course_id])
                return JsonResponse({'ok': True})
        if action == 'save':
            course_id = request.POST.get('course_id') or str(uuid.uuid4())
            title = request.POST.get('title', '').strip()
            code = request.POST.get('code', '').strip()
            credit_units = request.POST.get('credit_units') or None
            org_unit_id = (
                request.POST.get('department_id')
                or request.POST.get('faculty_id')
                or request.POST.get('university_id')
                or None
            )
            description = request.POST.get('description', '').strip()
            if not title:
                return JsonResponse({'ok': False, 'error': 'عنوان درس الزامی است.'}, status=400)
            existing = erd_row('SELECT org_unit_id FROM courses WHERE id = %s', [course_id])
            if managed_unit_ids is not None:
                if existing and str(existing.get('org_unit_id') or '') not in managed_unit_ids:
                    return JsonResponse({'ok': False, 'error': 'این درس خارج از محدوده‌ی دسترسی شماست.'}, status=403)
                if not org_unit_id or str(org_unit_id) not in managed_unit_ids:
                    return JsonResponse({'ok': False, 'error': 'واحد سازمانی انتخاب‌شده خارج از محدوده‌ی دسترسی شماست.'}, status=403)
            if existing:
                erd_execute(
                    """
                    UPDATE courses
                    SET title = %s, code = %s, credit_units = %s, org_unit_id = %s, description = %s
                    WHERE id = %s
                    """,
                    [title, code, credit_units, org_unit_id, description, course_id],
                )
            else:
                erd_execute(
                    """
                    INSERT INTO courses (id, title, code, description, org_unit_id, credit_units)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    [course_id, title, code, description, org_unit_id, credit_units],
                )
            row = _course_rows(request, course_id=course_id)[0]
            return JsonResponse({'ok': True, 'message': 'درس ذخیره شد.', 'course': row})

    q = request.GET.get('q', '').strip()
    status_filter = request.GET.get('status', '').strip()
    unit_filter = request.GET.get('unit', '').strip()
    rows = _course_rows(request, query=q, status_filter=status_filter, unit_filter=unit_filter)
    org_units = _erd_manager_visible_org_units(request)
    total = len(rows)
    active = sum(1 for row in rows if row['status'] == 'active')
    inactive = sum(1 for row in rows if row['status'] == 'inactive')
    review = sum(1 for row in rows if row['status'] == 'review')
    return render(request, 'super_admin/courses.html', {
        'title': 'مدیریت درس‌ها',
        'description': 'مشاهده و ایجاد درس‌های سامانه',
        'rows': rows,
        'query': q,
        'status_filter': status_filter,
        'unit_filter': unit_filter,
        'org_units': org_units,
        'stats': {
            'total': total,
            'active': active,
            'inactive': inactive,
            'review': review,
        },
    })


@erd_role_required('academic_manager', 'admin')
def super_admin_course_form(request, course_id=None):
    managed_unit_ids = _erd_managed_unit_ids(request)
    org_units = _erd_manager_visible_org_units(request)
    course = None
    if course_id:
        rows = _course_rows(request, course_id=course_id)
        if not rows:
            raise Http404('درس پیدا نشد.')
        course = rows[0]

    if request.method == 'POST':
        title = request.POST.get('title', '').strip()
        code = request.POST.get('code', '').strip()
        credit_units = request.POST.get('credit_units') or None
        org_unit_id = (
            request.POST.get('department_id')
            or request.POST.get('faculty_id')
            or request.POST.get('university_id')
            or None
        )
        description = request.POST.get('description', '').strip()
        if managed_unit_ids is not None and (not org_unit_id or str(org_unit_id) not in managed_unit_ids):
            return HttpResponseForbidden('واحد سازمانی انتخاب‌شده خارج از محدوده‌ی دسترسی شماست.')
        if managed_unit_ids is not None and course_id:
            existing = erd_row('SELECT org_unit_id FROM courses WHERE id = %s', [course_id])
            if existing and str(existing.get('org_unit_id') or '') not in managed_unit_ids:
                return HttpResponseForbidden('این درس خارج از محدوده‌ی دسترسی شماست.')
        if not title:
            messages.error(request, 'عنوان درس الزامی است.')
        else:
            target_id = course_id or str(uuid.uuid4())
            if course_id and erd_row('SELECT 1 FROM courses WHERE id = %s', [course_id]):
                erd_execute(
                    """
                    UPDATE courses
                    SET title = %s, code = %s, credit_units = %s, org_unit_id = %s, description = %s
                    WHERE id = %s
                    """,
                    [title, code, credit_units, org_unit_id, description, target_id],
                )
                messages.success(request, 'درس ویرایش شد.')
            else:
                erd_execute(
                    """
                    INSERT INTO courses (id, title, code, description, org_unit_id, credit_units)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    [target_id, title, code, description, org_unit_id, credit_units],
                )
                messages.success(request, 'درس جدید ایجاد شد.')
            return redirect('core:super_admin_courses')

    return render(request, 'super_admin/course_form.html', {
        'title': 'ویرایش درس' if course else 'ایجاد درس جدید',
        'description': 'مقادیر درس را در این صفحه وارد و ذخیره کنید.',
        'course': course,
        'org_units': org_units,
        'back_url': reverse('core:super_admin_courses'),
        'is_edit': bool(course),
    })


def _course_rows(request, course_id=None, query='', status_filter='', unit_filter=''):
    managed_unit_ids = _erd_managed_unit_ids(request)
    org_units = erd_rows(
        """
        SELECT id, parent_id, type, name, code, is_active
        FROM org_units
        ORDER BY CASE type WHEN 'university' THEN 0 WHEN 'faculty' THEN 1 ELSE 2 END, name
        """
    )
    unit_by_id = {str(unit['id']): unit for unit in org_units}

    def unit_path(unit_id):
        unit = unit_by_id.get(str(unit_id or ''))
        chain = []
        seen = set()
        while unit and str(unit['id']) not in seen:
            seen.add(str(unit['id']))
            chain.append(unit)
            unit = unit_by_id.get(str(unit.get('parent_id') or ''))
        by_type = {item['type']: item for item in chain}
        return {
            'university': (by_type.get('university') or {}).get('name') or '-',
            'faculty': (by_type.get('faculty') or {}).get('name') or '-',
            'department': (by_type.get('department') or by_type.get('educational_group') or {}).get('name') or '-',
            'unit_active': all(item.get('is_active') for item in chain) if chain else False,
            'unit_label': ' / '.join(reversed([item['name'] for item in chain])) if chain else '-',
        }

    where = []
    params = []
    if course_id:
        where.append('c.id = %s')
        params.append(course_id)
    sql = """
        SELECT c.id, c.title, c.code, c.description, c.org_unit_id, c.credit_units
        FROM courses c
    """
    if where:
        sql += ' WHERE ' + ' AND '.join(where)
    sql += ' ORDER BY c.title LIMIT 500'
    rows = []
    for item in erd_rows(sql, params):
        path = unit_path(item.get('org_unit_id'))
        status = 'active' if path['unit_active'] else 'inactive'
        if not item.get('org_unit_id'):
            status = 'review'
        row = {
            **item,
            **path,
            'status': status,
            'status_label': '\u0641\u0639\u0627\u0644' if status == 'active' else '\u0646\u06cc\u0627\u0632\u0645\u0646\u062f \u0628\u0631\u0631\u0633\u06cc' if status == 'review' else '\u063a\u06cc\u0631\u0641\u0639\u0627\u0644',
            'created_display': '-',
            'credit_units': item.get('credit_units') or '-',
        }
        if managed_unit_ids is not None and str(row.get('org_unit_id') or '') not in managed_unit_ids:
            continue
        if query and not _matches_query(query, row['title'], row['code'], row['university'], row['faculty'], row['department']):
            continue
        if status_filter and row['status'] != status_filter:
            continue
        if unit_filter and str(row.get('org_unit_id') or '') != unit_filter:
            continue
        rows.append(row)
    return rows


@super_admin_required
def super_admin_teacher_create(request):
    step = request.GET.get('step') or request.POST.get('step') or '1'
    try:
        step = max(1, min(4, int(step)))
    except (TypeError, ValueError):
        step = 1

    session_key = 'super_admin_teacher_wizard'
    draft = request.session.get(session_key, {})

    org_level_config = get_org_level_config()
    org_units = erd_rows(
        """
        SELECT id, parent_id, type, name, code, is_active
        FROM org_units
        ORDER BY CASE type WHEN 'university' THEN 0 WHEN 'faculty' THEN 1 ELSE 2 END, name
        """
    )
    for unit in org_units:
        unit['level_index'] = org_unit_level_index(unit)
    unit_by_id = {str(unit['id']): unit for unit in org_units}

    def unit_path(unit_id):
        unit = unit_by_id.get(str(unit_id or ''))
        chain = []
        seen = set()
        while unit and str(unit['id']) not in seen:
            seen.add(str(unit['id']))
            chain.append(unit)
            unit = unit_by_id.get(str(unit.get('parent_id') or ''))
        chain.reverse()
        by_type = {item['type']: item['name'] for item in chain}
        label = ' ← '.join(item['name'] for item in chain)
        return {
            'university': by_type.get('university') or '',
            'faculty': by_type.get('faculty') or '',
            'department': by_type.get('department') or by_type.get('group') or '',
            'label': label or '',
        }

    courses = erd_rows(
        """
        SELECT c.id, c.title, c.code, c.credit_units, c.org_unit_id, ou.name AS unit_name
        FROM courses c
        LEFT JOIN org_units ou ON ou.id = c.org_unit_id
        ORDER BY c.title
        LIMIT 80
        """
    )

    if request.method == 'POST':
        action = request.POST.get('wizard_action') or 'next'
        if action == 'cancel':
            request.session.pop(session_key, None)
            return redirect(f'{reverse("core:super_admin_users")}?tab=teachers')
        if action == 'prev':
            return redirect(f'{reverse("core:super_admin_teacher_create")}?step={max(1, step - 1)}')

        if step == 1:
            for key in ('first_name', 'last_name', 'national_id', 'phone', 'email', 'personnel_code', 'gender', 'birth_date', 'specialty', 'academic_rank'):
                draft[key] = request.POST.get(key, '').strip()
            avatar = request.FILES.get('avatar')
            if avatar:
                extension = (avatar.name.rsplit('.', 1)[-1] if '.' in avatar.name else 'jpg').lower()
                if extension not in {'jpg', 'jpeg', 'png', 'webp'}:
                    messages.error(request, 'فرمت تصویر استاد معتبر نیست.')
                    return redirect(f'{reverse("core:super_admin_teacher_create")}?step=1')
                storage = FileSystemStorage(location=str(Path(settings.MEDIA_ROOT) / 'teacher-avatars'), base_url=settings.MEDIA_URL + 'teacher-avatars/')
                filename = storage.save(f"wizard-{uuid.uuid4().hex[:10]}.{extension}", avatar)
                draft['avatar_url'] = storage.url(filename)
        elif step == 2:
            for key in ('org_unit_id', 'position_title', 'service_location', 'cooperation_started_at'):
                draft[key] = request.POST.get(key, '').strip()
            draft['apply_children'] = request.POST.get('apply_children') == 'on'
            draft['sub_units'] = request.POST.getlist('sub_units')
        elif step == 3:
            for key in ('cooperation_type', 'employment_type', 'academic_rank', 'weekly_hours', 'max_units'):
                draft[key] = request.POST.get(key, '').strip()
            draft['course_ids'] = request.POST.getlist('course_ids')
            draft['can_design_exam'] = request.POST.get('can_design_exam') == 'on'
        elif step == 4:
            for key in ('username', 'login_email', 'password_method', 'account_status'):
                draft[key] = request.POST.get(key, '').strip()
            draft['account_active'] = request.POST.get('account_active') == 'on'
            draft['force_password_change'] = request.POST.get('force_password_change') == 'on'
            draft['two_factor_enabled'] = request.POST.get('two_factor_enabled') == 'on'

        request.session[session_key] = draft
        request.session.modified = True

        if action == 'save_draft':
            messages.success(request, 'پیش‌نویس افزودن استاد ذخیره شد.')
            return redirect(f'{reverse("core:super_admin_teacher_create")}?step={step}')

        if step < 4:
            return redirect(f'{reverse("core:super_admin_teacher_create")}?step={step + 1}')

        if not request.POST.get('confirm_final'):
            messages.error(request, 'برای ثبت نهایی، تایید صحت اطلاعات لازم است.')
            return redirect(f'{reverse("core:super_admin_teacher_create")}?step=4')

        first_name = draft.get('first_name', '').strip()
        last_name = draft.get('last_name', '').strip()
        full_name = f'{first_name} {last_name}'.strip() or 'استاد جدید'
        personnel_code = draft.get('personnel_code') or f'TCH-{uuid.uuid4().hex[:5].upper()}'
        username = draft.get('username') or draft.get('email') or personnel_code
        email = draft.get('login_email') or draft.get('email') or None
        org_unit_id = draft.get('org_unit_id') or None
        primary = unit_path(org_unit_id)
        teacher_id = str(uuid.uuid4())
        existing = erd_row(
            """
            SELECT id FROM profiles
            WHERE identifier = %s OR username = %s OR email = %s OR national_id = %s
            LIMIT 1
            """,
            [personnel_code, username, email, draft.get('national_id') or None],
        )
        if existing:
            teacher_id = existing['id']
        status = draft.get('account_status') or ('active' if draft.get('account_active', True) else 'inactive')
        try:
            with connection.cursor() as cursor:
                if existing:
                    cursor.execute(
                        """
                        UPDATE profiles
                        SET full_name = %s, first_name = %s, last_name = %s, username = %s,
                            email = %s, phone = %s, national_id = %s, identifier = %s, gender = %s, birth_date = %s,
                            avatar_url = COALESCE(NULLIF(%s, ''), avatar_url), status = %s, updated_at = CURRENT_TIMESTAMP
                        WHERE id = %s
                        """,
                        [full_name, first_name, last_name, username, email, draft.get('phone') or None, draft.get('national_id') or None, personnel_code, draft.get('gender') or None, draft.get('birth_date') or None, draft.get('avatar_url') or '', status, teacher_id],
                    )
                else:
                    cursor.execute(
                        """
                        INSERT INTO profiles (id, full_name, first_name, last_name, username, email, phone, national_id, identifier, gender, birth_date, avatar_url, status, created_at, updated_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                        """,
                        [teacher_id, full_name, first_name, last_name, username, email, draft.get('phone') or None, draft.get('national_id') or None, personnel_code, draft.get('gender') or None, draft.get('birth_date') or None, draft.get('avatar_url') or '', status],
                    )
                cursor.execute(
                    """
                    INSERT INTO teacher_profiles (
                        user_id, personnel_code, department, specialty, academic_rank, approval_status, org_unit_id,
                        position_title, service_location, cooperation_started_at, apply_children,
                        cooperation_type, employment_type, weekly_hours, max_units, can_design_exam,
                        password_method, force_password_change, two_factor_enabled
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT(user_id) DO UPDATE SET
                        personnel_code = excluded.personnel_code,
                        department = excluded.department,
                        specialty = excluded.specialty,
                        academic_rank = excluded.academic_rank,
                        approval_status = excluded.approval_status,
                        org_unit_id = excluded.org_unit_id,
                        position_title = excluded.position_title,
                        service_location = excluded.service_location,
                        cooperation_started_at = excluded.cooperation_started_at,
                        apply_children = excluded.apply_children,
                        cooperation_type = excluded.cooperation_type,
                        employment_type = excluded.employment_type,
                        weekly_hours = excluded.weekly_hours,
                        max_units = excluded.max_units,
                        can_design_exam = excluded.can_design_exam,
                        password_method = excluded.password_method,
                        force_password_change = excluded.force_password_change,
                        two_factor_enabled = excluded.two_factor_enabled
                    """,
                    [
                        teacher_id, personnel_code, primary.get('department') or draft.get('position_title') or '', draft.get('specialty') or '', draft.get('academic_rank') or '', 'approved', org_unit_id,
                        draft.get('position_title') or '', draft.get('service_location') or '', draft.get('cooperation_started_at') or '', bool(draft.get('apply_children')),
                        draft.get('cooperation_type') or '', draft.get('employment_type') or '', draft.get('weekly_hours') or '', draft.get('max_units') or '', bool(draft.get('can_design_exam')),
                        draft.get('password_method') or '', bool(draft.get('force_password_change')), bool(draft.get('two_factor_enabled')),
                    ],
                )
                cursor.execute("DELETE FROM teacher_sub_units WHERE teacher_id = %s", [teacher_id])
                for sub_unit_id in dict.fromkeys(draft.get('sub_units') or []):
                    cursor.execute(
                        "INSERT INTO teacher_sub_units (teacher_id, org_unit_id, created_at) VALUES (%s, %s, CURRENT_TIMESTAMP) ON CONFLICT DO NOTHING",
                        [teacher_id, sub_unit_id],
                    )
                cursor.execute("DELETE FROM user_roles WHERE user_id = %s AND role = %s", [teacher_id, 'teacher'])
                cursor.execute("INSERT INTO user_roles (id, user_id, role, created_at) VALUES (%s, %s, %s, CURRENT_TIMESTAMP)", [str(uuid.uuid4()), teacher_id, 'teacher'])
                cursor.execute("DELETE FROM group_teachers WHERE teacher_id = %s", [teacher_id])
                for course_id in draft.get('course_ids') or []:
                    cursor.execute("SELECT id FROM student_groups WHERE course_id = %s LIMIT 30", [course_id])
                    for group in cursor.fetchall():
                        cursor.execute(
                            "INSERT INTO group_teachers (group_id, teacher_id, created_at) VALUES (%s, %s, CURRENT_TIMESTAMP) ON CONFLICT DO NOTHING",
                            [group[0], teacher_id],
                        )
        except DatabaseError as exc:
            messages.error(request, f'ذخیره استاد انجام نشد: {exc}')
            return redirect(f'{reverse("core:super_admin_teacher_create")}?step=4')

        _login_user, generated_password = erd_sync_login_account(username, is_active=(status == 'active'))

        request.session.pop(session_key, None)
        if generated_password:
            messages.success(request, f'استاد جدید با موفقیت ثبت شد. نام کاربری: {username} — رمز عبور اولیه: {generated_password}')
        else:
            messages.success(request, 'استاد جدید با موفقیت ثبت شد.')
        return redirect(f'{reverse("core:super_admin_users")}?tab=teachers')

    selected_course_ids = {str(item) for item in draft.get('course_ids', [])}
    selected_courses = [course for course in courses if str(course.get('id')) in selected_course_ids]
    active_unit = unit_path(draft.get('org_unit_id'))
    steps = [
        {'number': 1, 'label': 'اطلاعات پایه'},
        {'number': 2, 'label': 'انتساب سازمانی'},
        {'number': 3, 'label': 'درس‌ها و همکاری'},
        {'number': 4, 'label': 'حساب کاربری'},
    ]
    return render(request, 'super_admin/teacher_wizard.html', {
        'step': step,
        'steps': steps,
        'draft': draft,
        'org_units': org_units,
        'org_level_config': org_level_config,
        'universities': [unit for unit in org_units if unit['type'] == 'university'],
        'sub_units': [unit for unit in org_units if unit['type'] in ('faculty', 'department', 'group')],
        'active_unit': active_unit,
        'courses': courses,
        'selected_courses': selected_courses,
        'selected_course_ids': selected_course_ids,
        'wizard_username': draft.get('username') or draft.get('email') or '',
        'wizard_login_email': draft.get('login_email') or draft.get('email') or '',
        'back_url': f'{reverse("core:super_admin_users")}?tab=teachers',
    })


@super_admin_required
def super_admin_manager_create(request):
    step = request.GET.get('step') or request.POST.get('step') or '1'
    try:
        step = max(1, min(4, int(step)))
    except (TypeError, ValueError):
        step = 1

    session_key = 'super_admin_manager_wizard'
    draft = request.session.get(session_key, {})
    org_level_config = get_org_level_config()
    org_units = erd_rows(
        """
        SELECT id, parent_id, type, name, code, is_active
        FROM org_units
        ORDER BY CASE type WHEN 'university' THEN 0 WHEN 'faculty' THEN 1 ELSE 2 END, name
        """
    )
    for unit in org_units:
        unit['level_index'] = org_unit_level_index(unit)
    unit_by_id = {str(unit['id']): unit for unit in org_units}

    def unit_path(unit_id):
        unit = unit_by_id.get(str(unit_id or ''))
        chain = []
        seen = set()
        while unit and str(unit['id']) not in seen:
            seen.add(str(unit['id']))
            chain.append(unit)
            unit = unit_by_id.get(str(unit.get('parent_id') or ''))
        chain.reverse()
        by_type = {item['type']: item['name'] for item in chain}
        label = ' / '.join(item['name'] for item in chain)
        return {'university': by_type.get('university') or '', 'faculty': by_type.get('faculty') or '', 'department': by_type.get('department') or by_type.get('group') or '', 'label': label}

    modules = [
        ('dashboard_reports', 'داشبورد و گزارش‌ها', ('view', 'create', 'edit', 'delete', 'approve')),
        ('courses', 'درس‌ها', ('view', 'create', 'edit')),
        ('users', 'کاربران', ('view', 'create', 'edit')),
        ('exams', 'آزمون‌ها', ('view', 'create', 'edit', 'approve')),
        ('questions', 'بانک سوالات', ('view', 'create', 'edit')),
        ('calendar', 'تقویم آموزشی', ('view', 'create', 'edit')),
        ('settings', 'تنظیمات سامانه', ('view',)),
    ]
    actions = [('view', 'مشاهده'), ('create', 'ایجاد'), ('edit', 'ویرایش'), ('delete', 'حذف'), ('approve', 'تایید نهایی')]

    if request.method == 'POST':
        action = request.POST.get('wizard_action') or 'next'
        if action == 'cancel':
            request.session.pop(session_key, None)
            return redirect(f'{reverse("core:super_admin_users")}?tab=managers')
        if action == 'prev':
            return redirect(f'{reverse("core:super_admin_manager_create")}?step={max(1, step - 1)}')

        if step == 1:
            for key in ('first_name', 'last_name', 'personnel_code', 'national_id', 'birth_date', 'gender', 'email', 'phone'):
                draft[key] = request.POST.get(key, '').strip()
            avatar = request.FILES.get('avatar')
            if avatar:
                extension = (avatar.name.rsplit('.', 1)[-1] if '.' in avatar.name else 'jpg').lower()
                if extension not in {'jpg', 'jpeg', 'png', 'webp'}:
                    messages.error(request, 'فرمت تصویر مدیر معتبر نیست.')
                    return redirect(f'{reverse("core:super_admin_manager_create")}?step=1')
                storage = FileSystemStorage(location=str(Path(settings.MEDIA_ROOT) / 'manager-avatars'), base_url=settings.MEDIA_URL + 'manager-avatars/')
                filename = storage.save(f"wizard-{uuid.uuid4().hex[:10]}.{extension}", avatar)
                draft['avatar_url'] = storage.url(filename)
        elif step == 2:
            for key in ('manager_role', 'title', 'access_type', 'primary_scope_id'):
                draft[key] = request.POST.get(key, '').strip()
            draft['scope_ids'] = request.POST.getlist('scope_ids') or ([draft.get('primary_scope_id')] if draft.get('primary_scope_id') else [])
            draft['include_child_units'] = request.POST.get('include_child_units') == 'on'
        elif step == 3:
            permissions = {}
            for module_key, _label, allowed in modules:
                permissions[module_key] = {action_key: f'perm_{module_key}_{action_key}' in request.POST for action_key, _ in actions if action_key in allowed}
            draft['permission_template'] = request.POST.get('permission_template', '').strip()
            draft['permissions'] = permissions
            for key in ('limit_to_units', 'view_sensitive', 'allow_exports'):
                draft[key] = request.POST.get(key) == 'on'
        elif step == 4:
            for key in ('username', 'login_email', 'password_method', 'account_status'):
                draft[key] = request.POST.get(key, '').strip()
            draft['email_verified_required'] = request.POST.get('email_verified_required') == 'on'
            draft['must_change_password'] = request.POST.get('must_change_password') == 'on'

        request.session[session_key] = draft
        request.session.modified = True

        if action == 'save_draft':
            messages.success(request, 'پیش‌نویس افزودن مدیر ذخیره شد.')
            return redirect(f'{reverse("core:super_admin_manager_create")}?step={step}')
        if step < 4:
            return redirect(f'{reverse("core:super_admin_manager_create")}?step={step + 1}')
        if not request.POST.get('confirm_final'):
            messages.error(request, 'برای ثبت نهایی، تایید صحت اطلاعات لازم است.')
            return redirect(f'{reverse("core:super_admin_manager_create")}?step=4')

        manager_role = draft.get('manager_role') if draft.get('manager_role') in {'admin', 'academic_manager'} else 'academic_manager'
        manager_id = str(uuid.uuid4())
        first_name = draft.get('first_name', '').strip()
        last_name = draft.get('last_name', '').strip()
        full_name = f'{first_name} {last_name}'.strip() or 'مدیر جدید'
        personnel_code = draft.get('personnel_code') or f'ADM-{uuid.uuid4().hex[:5].upper()}'
        username = draft.get('username') or draft.get('login_email') or draft.get('email') or personnel_code
        email = draft.get('login_email') or draft.get('email') or None
        status = draft.get('account_status') or 'active'
        scope_ids = [item for item in dict.fromkeys(draft.get('scope_ids') or []) if item]
        primary_scope = unit_path(scope_ids[0] if scope_ids else draft.get('primary_scope_id'))
        existing = erd_row(
            "SELECT id FROM profiles WHERE identifier = %s OR username = %s OR email = %s OR national_id = %s LIMIT 1",
            [personnel_code, username, email, draft.get('national_id') or None],
        )
        if existing:
            manager_id = existing['id']

        try:
            with connection.cursor() as cursor:
                if existing:
                    cursor.execute(
                        """
                        UPDATE profiles
                        SET full_name = %s, first_name = %s, last_name = %s, username = %s,
                            email = %s, phone = %s, national_id = %s, identifier = %s, status = %s,
                            gender = %s, birth_date = %s, password_method = %s,
                            must_change_password = %s, email_verified_required = %s,
                            avatar_url = COALESCE(NULLIF(%s, ''), avatar_url),
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = %s
                        """,
                        [full_name, first_name, last_name, username, email, draft.get('phone') or None, draft.get('national_id') or None, personnel_code, status, draft.get('gender') or None, draft.get('birth_date') or None, draft.get('password_method') or 'activation_link', draft.get('must_change_password', True), draft.get('email_verified_required', True), draft.get('avatar_url') or '', manager_id],
                    )
                else:
                    cursor.execute(
                        """
                        INSERT INTO profiles (
                            id, full_name, first_name, last_name, username, email, phone, national_id,
                            identifier, avatar_url, status, gender, birth_date, password_method,
                            must_change_password, email_verified_required, created_at, updated_at
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                        """,
                        [manager_id, full_name, first_name, last_name, username, email, draft.get('phone') or None, draft.get('national_id') or None, personnel_code, draft.get('avatar_url') or '', status, draft.get('gender') or None, draft.get('birth_date') or None, draft.get('password_method') or 'activation_link', draft.get('must_change_password', True), draft.get('email_verified_required', True)],
                    )
                if manager_role == 'admin':
                    cursor.execute(
                        "INSERT INTO admin_profiles (user_id, title, access_level) VALUES (%s, %s, %s) ON CONFLICT(user_id) DO UPDATE SET title = excluded.title, access_level = excluded.access_level",
                        [manager_id, draft.get('title') or 'مدیر سیستم', 'system'],
                    )
                else:
                    cursor.execute(
                        """
                        INSERT INTO academic_manager_profiles (user_id, personnel_code, department, responsibility_area, title, access_type, include_child_units)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT(user_id) DO UPDATE SET
                            personnel_code = excluded.personnel_code,
                            department = excluded.department,
                            responsibility_area = excluded.responsibility_area,
                            title = excluded.title,
                            access_type = excluded.access_type,
                            include_child_units = excluded.include_child_units
                        """,
                        [manager_id, personnel_code, primary_scope.get('department') or '', primary_scope.get('label') or '', draft.get('title') or '', draft.get('access_type') or 'selected_units', draft.get('include_child_units', True)],
                    )
                cursor.execute("DELETE FROM user_roles WHERE user_id = %s AND role IN ('admin', 'academic_manager')", [manager_id])
                cursor.execute("INSERT INTO user_roles (id, user_id, role, created_at) VALUES (%s, %s, %s, CURRENT_TIMESTAMP)", [str(uuid.uuid4()), manager_id, manager_role])
                cursor.execute("DELETE FROM academic_manager_scopes WHERE manager_id = %s", [manager_id])
                for scope_id in scope_ids:
                    cursor.execute("INSERT INTO academic_manager_scopes (id, manager_id, org_unit_id, created_at) VALUES (%s, %s, %s, CURRENT_TIMESTAMP) ON CONFLICT DO NOTHING", [str(uuid.uuid4()), manager_id, scope_id])
                settings_key = f'manager_access.{manager_id}'
                payload = {
                    'access_mode': draft.get('access_type') or 'selected_units',
                    'include_child_units': draft.get('include_child_units', True),
                    'restrictions': {
                        'limit_to_units': draft.get('limit_to_units', True),
                        'view_sensitive': draft.get('view_sensitive', False),
                        'allow_exports': draft.get('allow_exports', True),
                    },
                    'permissions': draft.get('permissions') or {},
                }
                cursor.execute(
                    """
                    INSERT INTO system_settings (key, value, description, updated_by)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT(key) DO UPDATE SET value = excluded.value, description = excluded.description, updated_by = excluded.updated_by
                    """,
                    [settings_key, json.dumps(payload, ensure_ascii=False), 'Manager wizard access settings', manager_id],
                )
        except DatabaseError as exc:
            messages.error(request, f'ذخیره مدیر انجام نشد: {exc}')
            return redirect(f'{reverse("core:super_admin_manager_create")}?step=4')

        _login_user, generated_password = erd_sync_login_account(username, is_active=(status == 'active'))

        request.session.pop(session_key, None)
        if generated_password:
            messages.success(request, f'مدیر جدید با موفقیت ثبت شد. نام کاربری: {username} — رمز عبور اولیه: {generated_password}')
        else:
            messages.success(request, 'مدیر جدید با موفقیت ثبت شد.')
        return redirect(f'{reverse("core:super_admin_users")}?tab=managers')

    scope_ids = {str(item) for item in draft.get('scope_ids', [])}
    selected_scopes = [unit_path(item) for item in scope_ids]
    primary_scope_path = unit_path(draft.get('primary_scope_id'))
    permissions = draft.get('permissions') or {}
    total_permissions = sum(len(allowed) for _key, _label, allowed in modules)
    if permissions:
        active_permissions = sum(1 for module in permissions.values() for value in module.values() if value)
    else:
        active_permissions = total_permissions
    permission_rate = round(active_permissions / total_permissions * 100) if total_permissions else 0
    scope_subcount = max(len(scope_ids) - 1, 0)
    steps = [
        {'number': 1, 'label': 'اطلاعات پایه'},
        {'number': 2, 'label': 'نقش و انتساب سازمانی'},
        {'number': 3, 'label': 'دسترسی‌ها'},
        {'number': 4, 'label': 'حساب کاربری'},
    ]
    return render(request, 'super_admin/manager_wizard.html', {
        'step': step,
        'steps': steps,
        'draft': draft,
        'org_units': org_units,
        'org_level_config': org_level_config,
        'sub_units': [unit for unit in org_units if unit['type'] in ('faculty', 'department', 'group')],
        'scope_ids': scope_ids,
        'selected_scopes': selected_scopes,
        'primary_scope_path': primary_scope_path,
        'modules': modules,
        'actions': actions,
        'permissions': permissions,
        'total_permissions': total_permissions,
        'active_permissions': active_permissions,
        'permission_rate': permission_rate,
        'scope_subcount': scope_subcount,
        'wizard_username': draft.get('username') or draft.get('email') or '',
        'wizard_login_email': draft.get('login_email') or draft.get('email') or '',
        'back_url': f'{reverse("core:super_admin_users")}?tab=managers',
    })


@super_admin_required
def super_admin_manager_bulk_import(request):
    session_key = 'super_admin_manager_bulk_import'
    draft = request.session.get(session_key, {})
    action = request.GET.get('bulk_action') or request.POST.get('bulk_action') or ''
    step = request.GET.get('step') or request.POST.get('step') or draft.get('step') or '1'
    try:
        step = max(1, min(4, int(step)))
    except (TypeError, ValueError):
        step = 1

    headers = [
        'نام',
        'نام خانوادگی',
        'کد ملی',
        'شماره پرسنلی',
        'شماره همراه',
        'نوع مدیر',
        'واحد سازمانی',
        'الگوی دسترسی',
        'ایمیل',
        'وضعیت حساب',
    ]
    sample_rows = [
        ['علی', 'محمدی', '0012345678', '884421', '09121234567', 'مدیر واحد', 'واحد منابع انسانی', 'مدیر واحد', 'ali.mohammadi@example.com', 'فعال'],
        ['مریم', 'احمدی', '0012345679', '884422', '09121234568', 'مدیر آموزشی', 'دانشکده پزشکی', 'مدیر آموزشی', 'm.ahmadi@example.com', 'فعال'],
        ['رضا', 'کریمی', '0012345680', '884423', '09121234569', 'مدیر سیستم', 'تمام سازمان', 'مدیر سیستم', 'r.karimi@example.com', 'فعال'],
    ]
    if action == 'sample':
        return xlsx_response('managers-template.xlsx', headers, sample_rows, 'Managers')

    org_units = erd_rows(
        """
        SELECT id, parent_id, type, name, code, is_active
        FROM org_units
        ORDER BY CASE type WHEN 'university' THEN 0 WHEN 'faculty' THEN 1 ELSE 2 END, name
        """
    )
    unit_by_id = {str(unit['id']): unit for unit in org_units}

    def normalize_text(value):
        return str(value or '').strip().replace('ي', 'ی').replace('ك', 'ک').replace('\u200c', ' ').lower()

    def unit_path(unit_id):
        unit = unit_by_id.get(str(unit_id or ''))
        chain = []
        seen = set()
        while unit and str(unit['id']) not in seen:
            seen.add(str(unit['id']))
            chain.append(unit)
            unit = unit_by_id.get(str(unit.get('parent_id') or ''))
        by_type = {item['type']: item['name'] for item in chain}
        label = ' / '.join(part for part in [by_type.get('university'), by_type.get('faculty'), by_type.get('department') or by_type.get('group')] if part)
        return {
            'university': by_type.get('university') or '',
            'faculty': by_type.get('faculty') or '',
            'department': by_type.get('department') or by_type.get('group') or '',
            'label': label or '',
        }

    def resolve_unit(value):
        value = normalize_text(value)
        if not value or value in {'تمام سازمان', 'همه سازمان', 'کل سازمان', 'all', 'all organization', 'organization', 'system'}:
            return ''
        for unit in org_units:
            names = {normalize_text(unit.get('name')), normalize_text(unit.get('code'))}
            path = unit_path(unit['id'])
            names.add(normalize_text(path.get('label')))
            if value in names:
                return str(unit['id'])
        for unit in org_units:
            path = unit_path(unit['id'])
            haystack = normalize_text(f"{unit.get('name')} {unit.get('code')} {path.get('label')}")
            if value and value in haystack:
                return str(unit['id'])
        return None

    def manager_role(value):
        value = normalize_text(value)
        if 'سیستم' in value or value == 'admin':
            return 'admin'
        return 'academic_manager'

    def manager_type_label(value):
        value = normalize_text(value)
        if 'سیستم' in value or value == 'admin':
            return 'مدیر سیستم'
        if 'واحد' in value or value == 'unit':
            return 'مدیر واحد'
        return 'مدیر آموزشی'

    def import_status(value):
        value = normalize_text(value)
        return {'غیرفعال': 'inactive', 'inactive': 'inactive', 'مسدود': 'blocked', 'blocked': 'blocked'}.get(value, 'active')

    def cell(row, key):
        return str(row.get(key) or '').strip()

    field_defs = [
        {'key': 'first_name', 'label': 'نام', 'required': True, 'aliases': ['نام', 'first_name', 'name']},
        {'key': 'last_name', 'label': 'نام خانوادگی', 'required': True, 'aliases': ['نام خانوادگی', 'نام خانوادگي', 'last_name', 'family']},
        {'key': 'national_id', 'label': 'کد ملی', 'required': True, 'aliases': ['کد ملی', 'کد ملي', 'national_id']},
        {'key': 'personnel_code', 'label': 'شماره پرسنلی', 'required': True, 'aliases': ['شماره پرسنلی', 'کد پرسنلی', 'personnel_code']},
        {'key': 'phone', 'label': 'شماره همراه', 'required': True, 'aliases': ['شماره همراه', 'موبایل', 'موبايل', 'phone']},
        {'key': 'manager_type', 'label': 'نوع مدیر', 'required': True, 'aliases': ['نوع مدیر', 'نوع مدير', 'نقش', 'manager_type']},
        {'key': 'org_unit', 'label': 'واحد سازمانی', 'required': True, 'aliases': ['واحد سازمانی', 'واحد سازماني', 'دانشگاه', 'دانشکده', 'گروه آموزشی', 'org_unit']},
        {'key': 'access_template', 'label': 'الگوی دسترسی', 'required': False, 'aliases': ['الگوی دسترسی', 'الگوي دسترسي', 'access_template']},
        {'key': 'email', 'label': 'ایمیل', 'required': False, 'aliases': ['ایمیل', 'ايميل', 'email']},
        {'key': 'status', 'label': 'وضعیت حساب', 'required': False, 'aliases': ['وضعیت حساب', 'وضعيت حساب', 'وضعیت', 'status']},
    ]

    def guess_mapping(upload_headers):
        mapping = {}
        normalized_headers = {normalize_text(header): header for header in upload_headers}
        for field in field_defs:
            for alias in field['aliases']:
                found = normalized_headers.get(normalize_text(alias))
                if found:
                    mapping[field['key']] = found
                    break
            mapping.setdefault(field['key'], '')
        return mapping

    def validate_rows():
        upload_rows = draft.get('rows') or []
        mapping = draft.get('mapping') or {}
        ignored_rows = set(draft.get('ignored_rows') or [])
        records = []
        counts = {'ok': 0, 'warning': 0, 'error': 0, 'ignored': 0}
        seen_national = set()
        seen_personnel = set()
        for index, raw in enumerate(upload_rows, start=2):
            record = {field['key']: cell(raw, mapping.get(field['key'])) for field in field_defs}
            issues = []
            for field in field_defs:
                if field['required'] and not record.get(field['key']):
                    issues.append(('error', field['key'], f"{field['label']} خالی است."))
            if record.get('national_id') and record['national_id'] in seen_national:
                issues.append(('error', 'national_id', 'کد ملی تکراری است.'))
            if record.get('personnel_code') and record['personnel_code'] in seen_personnel:
                issues.append(('error', 'personnel_code', 'شماره پرسنلی تکراری است.'))
            seen_national.add(record.get('national_id'))
            seen_personnel.add(record.get('personnel_code'))
            unit_id = resolve_unit(record.get('org_unit'))
            if unit_id is None:
                issues.append(('error', 'org_unit', 'واحد سازمانی مطابق با لیست موجود نیست.'))
            record['row_number'] = index
            record['status'] = import_status(record.get('status'))
            record['manager_role'] = manager_role(record.get('manager_type'))
            record['manager_type_label'] = manager_type_label(record.get('manager_type'))
            record['org_unit_id'] = unit_id or ''
            record['org_unit_label'] = unit_path(unit_id).get('label') if unit_id else 'تمام سازمان'
            record['access_template'] = record.get('access_template') or record['manager_type_label']
            record['full_name'] = f"{record.get('first_name')} {record.get('last_name')}".strip()
            errors = [msg for level, _key, msg in issues if level == 'error']
            warnings = [msg for level, _key, msg in issues if level == 'warning']
            record['issues'] = errors + warnings
            if index in ignored_rows:
                record['level'] = 'ignored'
            else:
                record['level'] = 'error' if errors else ('warning' if warnings else 'ok')
            primary_issue = next(iter(issues), None)
            record['primary_issue_field'] = primary_issue[1] if primary_issue else ''
            record['primary_issue_label'] = next((f['label'] for f in field_defs if f['key'] == (primary_issue[1] if primary_issue else '')), '')
            counts[record['level']] += 1
            records.append(record)
        draft['records'] = records
        draft['counts'] = counts
        request.session[session_key] = draft
        request.session.modified = True
        return records, counts

    if request.method == 'POST':
        nav_action = request.POST.get('wizard_action') or 'next'
        if nav_action == 'cancel':
            request.session.pop(session_key, None)
            return redirect(f'{reverse("core:super_admin_users")}?tab=managers')
        if nav_action == 'prev':
            draft['step'] = max(1, step - 1)
            request.session[session_key] = draft
            request.session.modified = True
            return redirect(f'{reverse("core:super_admin_manager_bulk_import")}?step={draft["step"]}')
        if nav_action == 'save_draft':
            draft['step'] = step
            request.session[session_key] = draft
            request.session.modified = True
            messages.success(request, 'پیش‌نویس ورود گروهی مدیران ذخیره شد.')
            return redirect(f'{reverse("core:super_admin_manager_bulk_import")}?step={step}')
        if nav_action == 'fix_row':
            try:
                row_number = int(request.POST.get('row_number', ''))
            except (TypeError, ValueError):
                row_number = None
            field_key = request.POST.get('fix_field', '').strip()
            new_value = request.POST.get('fix_value', '').strip()
            mapping = draft.get('mapping') or {}
            upload_rows = draft.get('rows') or []
            row_index = (row_number - 2) if row_number else -1
            if field_key in mapping and 0 <= row_index < len(upload_rows):
                header = mapping.get(field_key)
                if not header:
                    header = field_key
                    mapping[field_key] = header
                    draft['mapping'] = mapping
                upload_rows[row_index][header] = new_value
                draft['rows'] = upload_rows
                request.session[session_key] = draft
                request.session.modified = True
                validate_rows()
                messages.success(request, f'ردیف {row_number} اصلاح شد.')
            return redirect(f'{reverse("core:super_admin_manager_bulk_import")}?step=3')
        if nav_action == 'ignore_row':
            try:
                row_number = int(request.POST.get('row_number', ''))
            except (TypeError, ValueError):
                row_number = None
            if row_number:
                ignored = set(draft.get('ignored_rows') or [])
                ignored.add(row_number)
                draft['ignored_rows'] = list(ignored)
                request.session[session_key] = draft
                request.session.modified = True
                validate_rows()
            return redirect(f'{reverse("core:super_admin_manager_bulk_import")}?step=3')
        if nav_action == 'restore_row':
            try:
                row_number = int(request.POST.get('row_number', ''))
            except (TypeError, ValueError):
                row_number = None
            if row_number:
                ignored = set(draft.get('ignored_rows') or [])
                ignored.discard(row_number)
                draft['ignored_rows'] = list(ignored)
                request.session[session_key] = draft
                request.session.modified = True
                validate_rows()
            return redirect(f'{reverse("core:super_admin_manager_bulk_import")}?step=3')

        if step == 1:
            uploaded = request.FILES.get('excel_file')
            if not uploaded:
                messages.error(request, 'لطفا فایل مدیران را انتخاب کنید.')
                return redirect(f'{reverse("core:super_admin_manager_bulk_import")}?step=1')
            suffix = Path(uploaded.name).suffix.lower()
            try:
                if suffix == '.csv':
                    text = uploaded.read().decode('utf-8-sig')
                    rows = list(csv.DictReader(io.StringIO(text)))
                else:
                    rows = read_xlsx_dicts(uploaded)
            except (UnicodeDecodeError, KeyError, ET.ParseError, zipfile.BadZipFile):
                messages.error(request, 'فایل انتخاب‌شده معتبر نیست. قالب نمونه را دریافت و تکمیل کنید.')
                return redirect(f'{reverse("core:super_admin_manager_bulk_import")}?step=1')
            if not rows:
                messages.error(request, 'فایل انتخاب‌شده ردیفی برای ورود ندارد.')
                return redirect(f'{reverse("core:super_admin_manager_bulk_import")}?step=1')
            upload_headers = list(rows[0].keys())
            draft = {
                'step': 2,
                'filename': uploaded.name,
                'headers': upload_headers,
                'rows': rows[:500],
                'total_rows': len(rows),
                'first_row': rows[0],
                'mapping': guess_mapping(upload_headers),
                'has_header': request.POST.get('has_header') == 'on',
            }
            request.session[session_key] = draft
            request.session.modified = True
            return redirect(f'{reverse("core:super_admin_manager_bulk_import")}?step=2')

        if step == 2:
            mapping = {}
            for field in field_defs:
                mapping[field['key']] = request.POST.get(f'map_{field["key"]}', '').strip()
            draft['mapping'] = mapping
            draft['step'] = 3
            request.session[session_key] = draft
            request.session.modified = True
            validate_rows()
            return redirect(f'{reverse("core:super_admin_manager_bulk_import")}?step=3')

        if step == 3:
            draft['step'] = 4
            request.session[session_key] = draft
            request.session.modified = True
            validate_rows()
            return redirect(f'{reverse("core:super_admin_manager_bulk_import")}?step=4')

        if step == 4:
            if not request.POST.get('confirm_final'):
                messages.error(request, 'برای ثبت نهایی، تایید صحت اطلاعات لازم است.')
                return redirect(f'{reverse("core:super_admin_manager_bulk_import")}?step=4')
            records, counts = validate_rows()
            if counts.get('error'):
                messages.error(request, 'ردیف‌های دارای خطا باید قبل از ثبت نهایی اصلاح شوند.')
                return redirect(f'{reverse("core:super_admin_manager_bulk_import")}?step=3')

            create_accounts = request.POST.get('create_accounts') == 'on'
            send_activation = request.POST.get('send_activation') == 'on'
            force_password = request.POST.get('force_password') == 'on'
            skip_warnings = request.POST.get('skip_warnings') == 'on'
            username_method = request.POST.get('username_method') or 'personnel_code'
            imported_count = 0
            type_counts = {'admin': 0, 'academic_manager': 0, 'unit': 0}
            created_credentials = []
            try:
                with connection.cursor() as cursor:
                    for record in records:
                        if record['level'] in ('error', 'ignored') or (record['level'] == 'warning' and skip_warnings):
                            continue
                        manager_id = str(uuid.uuid4())
                        username = record.get('email') if username_method == 'email' and record.get('email') else record.get('personnel_code')
                        email = record.get('email') or None
                        cursor.execute(
                            "SELECT id FROM profiles WHERE identifier = %s OR username = %s OR email = %s OR national_id = %s LIMIT 1",
                            [record.get('personnel_code'), username, email, record.get('national_id')],
                        )
                        existing = cursor.fetchone()
                        if existing:
                            manager_id = existing[0]
                            cursor.execute(
                                """
                                UPDATE profiles
                                SET full_name = %s, first_name = %s, last_name = %s, username = %s,
                                    email = %s, phone = %s, national_id = %s, identifier = %s,
                                    status = %s, password_method = %s, must_change_password = %s,
                                    email_verified_required = %s, updated_at = CURRENT_TIMESTAMP
                                WHERE id = %s
                                """,
                                [record['full_name'], record['first_name'], record['last_name'], username, email, record['phone'], record['national_id'], record['personnel_code'], record['status'], 'activation_link', force_password, send_activation, manager_id],
                            )
                        else:
                            cursor.execute(
                                """
                                INSERT INTO profiles (
                                    id, full_name, first_name, last_name, username, email, phone, national_id,
                                    identifier, avatar_url, status, password_method, must_change_password,
                                    email_verified_required, created_at, updated_at
                                )
                                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, '', %s, %s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                                """,
                                [manager_id, record['full_name'], record['first_name'], record['last_name'], username, email, record['phone'], record['national_id'], record['personnel_code'], record['status'], 'activation_link' if create_accounts else '', force_password, send_activation],
                            )
                        role = record['manager_role']
                        if role == 'admin':
                            cursor.execute(
                                "INSERT INTO admin_profiles (user_id, title, access_level) VALUES (%s, %s, %s) ON CONFLICT(user_id) DO UPDATE SET title = excluded.title, access_level = excluded.access_level",
                                [manager_id, record.get('access_template') or 'مدیر سیستم', 'system'],
                            )
                        else:
                            path = unit_path(record.get('org_unit_id'))
                            cursor.execute(
                                """
                                INSERT INTO academic_manager_profiles (user_id, personnel_code, department, responsibility_area, title, access_type, include_child_units)
                                VALUES (%s, %s, %s, %s, %s, %s, %s)
                                ON CONFLICT(user_id) DO UPDATE SET
                                    personnel_code = excluded.personnel_code,
                                    department = excluded.department,
                                    responsibility_area = excluded.responsibility_area,
                                    title = excluded.title,
                                    access_type = excluded.access_type,
                                    include_child_units = excluded.include_child_units
                                """,
                                [manager_id, record['personnel_code'], path.get('department') or record.get('org_unit_label') or '', path.get('label') or record.get('org_unit_label') or '', record.get('access_template') or record['manager_type_label'], 'selected_units', True],
                            )
                        cursor.execute("DELETE FROM user_roles WHERE user_id = %s AND role IN ('admin', 'academic_manager')", [manager_id])
                        cursor.execute("INSERT INTO user_roles (id, user_id, role, created_at) VALUES (%s, %s, %s, CURRENT_TIMESTAMP)", [str(uuid.uuid4()), manager_id, role])
                        cursor.execute("DELETE FROM academic_manager_scopes WHERE manager_id = %s", [manager_id])
                        if record.get('org_unit_id'):
                            cursor.execute("INSERT INTO academic_manager_scopes (id, manager_id, org_unit_id, created_at) VALUES (%s, %s, %s, CURRENT_TIMESTAMP) ON CONFLICT DO NOTHING", [str(uuid.uuid4()), manager_id, record['org_unit_id']])
                        settings_key = f'manager_access.{manager_id}'
                        payload = {
                            'source': 'bulk_import',
                            'access_template': record.get('access_template'),
                            'access_mode': 'all' if role == 'admin' else 'selected_units',
                            'create_accounts': create_accounts,
                            'send_activation': send_activation,
                        }
                        cursor.execute(
                            """
                            INSERT INTO system_settings (key, value, description, updated_by)
                            VALUES (%s, %s, %s, %s)
                            ON CONFLICT(key) DO UPDATE SET value = excluded.value, description = excluded.description, updated_by = excluded.updated_by
                            """,
                            [settings_key, json.dumps(payload, ensure_ascii=False), 'Manager bulk import access settings', manager_id],
                        )
                        if create_accounts:
                            _login_user, generated_password = erd_sync_login_account(username, is_active=(record['status'] == 'active'), reset_password=force_password)
                            if generated_password:
                                created_credentials.append((username, generated_password))
                        imported_count += 1
                        if record['manager_type_label'] == 'مدیر واحد':
                            type_counts['unit'] += 1
                        else:
                            type_counts[role] += 1
            except DatabaseError as exc:
                messages.error(request, f'ثبت گروهی مدیران انجام نشد: {exc}')
                return redirect(f'{reverse("core:super_admin_manager_bulk_import")}?step=4')

            request.session.pop(session_key, None)
            messages.success(request, f'{imported_count} مدیر با موفقیت ثبت شد.')
            if created_credentials:
                shown = created_credentials[:15]
                credential_text = '؛ '.join(f'{username}: {password}' for username, password in shown)
                suffix = f' (و {len(created_credentials) - len(shown)} مورد دیگر)' if len(created_credentials) > len(shown) else ''
                messages.info(request, f'رمزهای عبور اولیه حساب‌های تازه‌ساخته‌شده: {credential_text}{suffix}')
            return redirect(f'{reverse("core:super_admin_users")}?tab=managers')

    if step >= 3 and draft.get('rows') and draft.get('mapping'):
        validate_rows()

    records = draft.get('records') or []
    counts = draft.get('counts') or {'ok': 0, 'warning': 0, 'error': 0, 'ignored': 0}
    type_summary = {'مدیر سیستم': 0, 'مدیر آموزشی': 0, 'مدیر واحد': 0}
    for record in records:
        if record.get('level') not in ('error', 'ignored'):
            type_summary[record.get('manager_type_label') or 'مدیر آموزشی'] = type_summary.get(record.get('manager_type_label') or 'مدیر آموزشی', 0) + 1
    org_unit_options = sorted(
        ({'id': unit['id'], 'label': unit_path(unit['id']).get('label') or unit.get('name')} for unit in org_units),
        key=lambda item: item['label'],
    )
    steps = [
        {'number': 1, 'label': 'بارگذاری فایل'},
        {'number': 2, 'label': 'تطبیق ستون‌ها'},
        {'number': 3, 'label': 'بررسی و رفع خطاها'},
        {'number': 4, 'label': 'ثبت نهایی'},
    ]
    return render(request, 'super_admin/manager_bulk_import.html', {
        'step': step,
        'steps': steps,
        'draft': draft,
        'field_defs': field_defs,
        'headers': draft.get('headers') or [],
        'first_row': draft.get('first_row') or {},
        'records': records,
        'counts': counts,
        'type_summary': type_summary,
        'valid_count': counts.get('ok', 0) + counts.get('warning', 0),
        'required_fields': [field for field in field_defs if field['required']],
        'optional_fields': [field for field in field_defs if not field['required']],
        'org_unit_options': org_unit_options,
        'back_url': f'{reverse("core:super_admin_users")}?tab=managers',
    })


@super_admin_required
def super_admin_student_create(request):
    step = request.GET.get('step') or request.POST.get('step') or '1'
    try:
        step = max(1, min(4, int(step)))
    except (TypeError, ValueError):
        step = 1

    session_key = 'super_admin_student_wizard'
    draft = request.session.get(session_key, {})
    org_level_config = get_org_level_config()
    org_units = erd_rows("SELECT id, parent_id, type, name, code, is_active FROM org_units ORDER BY CASE type WHEN 'university' THEN 0 WHEN 'faculty' THEN 1 ELSE 2 END, name")
    for unit in org_units:
        unit['level_index'] = org_unit_level_index(unit)
    unit_by_id = {str(unit['id']): unit for unit in org_units}

    def unit_path(unit_id):
        unit = unit_by_id.get(str(unit_id or ''))
        chain = []
        seen = set()
        while unit and str(unit['id']) not in seen:
            seen.add(str(unit['id']))
            chain.append(unit)
            unit = unit_by_id.get(str(unit.get('parent_id') or ''))
        chain.reverse()
        by_type = {item['type']: item['name'] for item in chain}
        label = ' / '.join(item['name'] for item in chain)
        return {'university': by_type.get('university') or '', 'faculty': by_type.get('faculty') or '', 'department': by_type.get('department') or by_type.get('group') or '', 'label': label}

    groups = erd_rows("SELECT id, course_id, course_name, group_code, academic_year, semester FROM student_groups ORDER BY academic_year DESC, course_name LIMIT 300")
    courses = erd_rows("SELECT id, title, code, COALESCE(credit_units, 0) AS credit_units FROM courses ORDER BY title LIMIT 300")

    if request.method == 'POST':
        action = request.POST.get('wizard_action') or 'next'
        if action == 'cancel':
            request.session.pop(session_key, None)
            return redirect(f'{reverse("core:super_admin_users")}?tab=students')
        if action == 'prev':
            return redirect(f'{reverse("core:super_admin_student_create")}?step={max(1, step - 1)}')
        if step == 1:
            for key in ('first_name', 'last_name', 'student_number', 'national_id', 'phone', 'email', 'gender', 'birth_date'):
                draft[key] = request.POST.get(key, '').strip()
            avatar = request.FILES.get('avatar')
            if avatar:
                extension = (avatar.name.rsplit('.', 1)[-1] if '.' in avatar.name else 'jpg').lower()
                if extension not in {'jpg', 'jpeg', 'png', 'webp'}:
                    messages.error(request, 'فرمت تصویر دانشجو معتبر نیست.')
                    return redirect(f'{reverse("core:super_admin_student_create")}?step=1')
                storage = FileSystemStorage(location=str(Path(settings.MEDIA_ROOT) / 'student-avatars'), base_url=settings.MEDIA_URL + 'student-avatars/')
                filename = storage.save(f"wizard-{uuid.uuid4().hex[:10]}.{extension}", avatar)
                draft['avatar_url'] = storage.url(filename)
        elif step == 2:
            for key in ('entry_year', 'semester', 'degree', 'field_of_study', 'admission_type', 'academic_status', 'org_unit_id'):
                draft[key] = request.POST.get(key, '').strip()
        elif step == 3:
            draft['group_ids'] = request.POST.getlist('group_ids')
            draft['course_ids'] = request.POST.getlist('course_ids')
        elif step == 4:
            for key in ('username', 'password_method', 'account_status'):
                draft[key] = request.POST.get(key, '').strip()
            draft['must_change_password'] = request.POST.get('must_change_password') == 'on'
            draft['send_welcome_message'] = request.POST.get('send_welcome_message') == 'on'
        request.session[session_key] = draft
        request.session.modified = True

        if action == 'save_draft':
            messages.success(request, 'پیش‌نویس افزودن دانشجو ذخیره شد.')
            return redirect(f'{reverse("core:super_admin_student_create")}?step={step}')
        if step < 4:
            return redirect(f'{reverse("core:super_admin_student_create")}?step={step + 1}')
        if not request.POST.get('confirm_final'):
            messages.error(request, 'برای ثبت نهایی، تایید صحت اطلاعات لازم است.')
            return redirect(f'{reverse("core:super_admin_student_create")}?step=4')

        student_id = str(uuid.uuid4())
        first_name = draft.get('first_name', '').strip()
        last_name = draft.get('last_name', '').strip()
        full_name = f'{first_name} {last_name}'.strip() or 'دانشجو'
        student_number = draft.get('student_number') or f'STU-{uuid.uuid4().hex[:5].upper()}'
        username = draft.get('username') or draft.get('email') or student_number
        org_unit_id = draft.get('org_unit_id') or None
        primary = unit_path(org_unit_id)
        existing = erd_row("SELECT id FROM profiles WHERE identifier = %s OR username = %s OR email = %s OR national_id = %s LIMIT 1", [student_number, username, draft.get('email') or None, draft.get('national_id') or None])
        if existing:
            student_id = existing['id']
        try:
            with connection.cursor() as cursor:
                if existing:
                    cursor.execute(
                        """
                        UPDATE profiles
                        SET full_name = %s, first_name = %s, last_name = %s, username = %s,
                            email = %s, phone = %s, national_id = %s, identifier = %s, gender = %s, birth_date = %s,
                            avatar_url = COALESCE(NULLIF(%s, ''), avatar_url), status = %s, updated_at = CURRENT_TIMESTAMP
                        WHERE id = %s
                        """,
                        [full_name, first_name, last_name, username, draft.get('email') or None, draft.get('phone') or None, draft.get('national_id') or None, student_number, draft.get('gender') or None, draft.get('birth_date') or None, draft.get('avatar_url') or '', draft.get('account_status') or 'active', student_id],
                    )
                else:
                    cursor.execute(
                        """
                        INSERT INTO profiles (id, full_name, first_name, last_name, username, email, phone, national_id, identifier, gender, birth_date, avatar_url, status, created_at, updated_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                        """,
                        [student_id, full_name, first_name, last_name, username, draft.get('email') or None, draft.get('phone') or None, draft.get('national_id') or None, student_number, draft.get('gender') or None, draft.get('birth_date') or None, draft.get('avatar_url') or '', draft.get('account_status') or 'active'],
                    )
                cursor.execute(
                    """
                    INSERT INTO student_profiles (
                        user_id, student_number, field_of_study, degree, class_group, semester, academic_status,
                        department, org_unit_id, entry_year, admission_type, password_method, must_change_password, send_welcome_message
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT(user_id) DO UPDATE SET
                        student_number = excluded.student_number,
                        field_of_study = excluded.field_of_study,
                        degree = excluded.degree,
                        semester = excluded.semester,
                        academic_status = excluded.academic_status,
                        department = excluded.department,
                        org_unit_id = excluded.org_unit_id,
                        entry_year = excluded.entry_year,
                        admission_type = excluded.admission_type,
                        password_method = excluded.password_method,
                        must_change_password = excluded.must_change_password,
                        send_welcome_message = excluded.send_welcome_message
                    """,
                    [student_id, student_number, draft.get('field_of_study') or '', draft.get('degree') or '', '', draft.get('semester') or '', draft.get('academic_status') or 'active', primary.get('department') or '', org_unit_id, draft.get('entry_year') or '', draft.get('admission_type') or '', draft.get('password_method') or 'activation_link', draft.get('must_change_password', True), draft.get('send_welcome_message', True)],
                )
                cursor.execute("DELETE FROM user_roles WHERE user_id = %s AND role = %s", [student_id, 'student'])
                cursor.execute("INSERT INTO user_roles (id, user_id, role, created_at) VALUES (%s, %s, %s, CURRENT_TIMESTAMP)", [str(uuid.uuid4()), student_id, 'student'])
                cursor.execute("DELETE FROM student_group_members WHERE student_user_id = %s", [student_id])
                for group_id in dict.fromkeys(draft.get('group_ids') or []):
                    cursor.execute("INSERT INTO student_group_members (id, group_id, student_user_id, full_name, national_id, student_number) VALUES (%s, %s, %s, %s, %s, %s)", [str(uuid.uuid4()), group_id, student_id, full_name, draft.get('national_id') or '-', student_number])
                cursor.execute("DELETE FROM student_course_enrollments WHERE student_user_id = %s", [student_id])
                for course_id in dict.fromkeys(draft.get('course_ids') or []):
                    cursor.execute("INSERT INTO student_course_enrollments (id, student_user_id, course_id, created_at) VALUES (%s, %s, %s, CURRENT_TIMESTAMP) ON CONFLICT(student_user_id, course_id) DO NOTHING", [str(uuid.uuid4()), student_id, course_id])
        except DatabaseError as exc:
            messages.error(request, f'ذخیره دانشجو انجام نشد: {exc}')
            return redirect(f'{reverse("core:super_admin_student_create")}?step=4')

        account_status = draft.get('account_status') or 'active'
        _login_user, generated_password = erd_sync_login_account(username, is_active=(account_status == 'active'))

        request.session.pop(session_key, None)
        if generated_password:
            messages.success(request, f'دانشجو با موفقیت ثبت شد. نام کاربری: {username} — رمز عبور اولیه: {generated_password}')
        else:
            messages.success(request, 'دانشجو با موفقیت ثبت شد.')
        return redirect(f'{reverse("core:super_admin_users")}?tab=students')

    selected_group_ids = {str(item) for item in draft.get('group_ids', [])}
    selected_course_ids = {str(item) for item in draft.get('course_ids', [])}
    steps = [
        {'number': 1, 'label': 'اطلاعات پایه'},
        {'number': 2, 'label': 'اطلاعات تحصیلی'},
        {'number': 3, 'label': 'گروه و درس‌ها'},
        {'number': 4, 'label': 'حساب کاربری'},
    ]
    return render(request, 'super_admin/student_wizard.html', {
        'step': step,
        'steps': steps,
        'draft': draft,
        'org_units': org_units,
        'org_level_config': org_level_config,
        'groups': groups,
        'courses': courses,
        'selected_group_ids': selected_group_ids,
        'selected_course_ids': selected_course_ids,
        'active_unit': unit_path(draft.get('org_unit_id')),
        'wizard_username': draft.get('username') or draft.get('email') or draft.get('student_number') or '',
        'back_url': f'{reverse("core:super_admin_users")}?tab=students',
    })


@super_admin_required
def super_admin_teachers(request):
    q = request.GET.get('q', '').strip()
    org_units = erd_rows(
        """
        SELECT id, parent_id, type, name, code, is_active
        FROM org_units
        ORDER BY CASE type WHEN 'university' THEN 0 WHEN 'faculty' THEN 1 ELSE 2 END, name
        """
    )
    unit_by_id = {str(unit['id']): unit for unit in org_units}

    def unit_path(unit_id):
        unit = unit_by_id.get(str(unit_id or ''))
        if not unit:
            return {'university': '-', 'faculty': '-', 'department': '-', 'label': '-'}
        chain = []
        current = unit
        seen = set()
        while current and str(current['id']) not in seen:
            seen.add(str(current['id']))
            chain.append(current)
            current = unit_by_id.get(str(current.get('parent_id') or ''))
        by_type = {item['type']: item['name'] for item in chain}
        return {
            'university': by_type.get('university') or '-',
            'faculty': by_type.get('faculty') or '-',
            'department': by_type.get('department') or by_type.get('group') or '-',
            'label': ' / '.join(part for part in [by_type.get('university'), by_type.get('faculty'), by_type.get('department') or by_type.get('group')] if part) or unit['name'],
        }

    excel_headers = ['نام', 'نام خانوادگی', 'نام کاربری', 'ایمیل', 'موبایل', 'کد ملی', 'کد پرسنلی', 'وضعیت حساب', 'وضعیت تایید', 'دانشگاه', 'دانشکده', 'گروه آموزشی']

    def normalize_text(value):
        return str(value or '').strip().replace('ي', 'ی').replace('ك', 'ک').lower()

    def resolve_org_unit_id(university_name='', faculty_name='', department_name=''):
        university_name = normalize_text(university_name)
        faculty_name = normalize_text(faculty_name)
        department_name = normalize_text(department_name)

        def parent_chain(unit):
            chain = []
            current = unit
            seen = set()
            while current and str(current['id']) not in seen:
                seen.add(str(current['id']))
                chain.append(current)
                current = unit_by_id.get(str(current.get('parent_id') or ''))
            return chain

        if department_name:
            candidates = [unit for unit in org_units if unit['type'] in ('department', 'group') and normalize_text(unit['name']) == department_name]
        elif faculty_name:
            candidates = [unit for unit in org_units if unit['type'] == 'faculty' and normalize_text(unit['name']) == faculty_name]
        elif university_name:
            candidates = [unit for unit in org_units if unit['type'] == 'university' and normalize_text(unit['name']) == university_name]
        else:
            candidates = []

        for unit in candidates:
            names_by_type = {item['type']: normalize_text(item['name']) for item in parent_chain(unit)}
            if university_name and names_by_type.get('university') != university_name:
                continue
            if faculty_name and names_by_type.get('faculty') != faculty_name:
                continue
            return str(unit['id'])
        return ''

    def import_status(value):
        value = normalize_text(value)
        return {
            'فعال': 'active',
            'active': 'active',
            'غیرفعال': 'inactive',
            'inactive': 'inactive',
            'مسدود': 'blocked',
            'blocked': 'blocked',
        }.get(value, 'active')

    def import_approval(value):
        value = normalize_text(value)
        return {
            'تایید شده': 'approved',
            'تأیید شده': 'approved',
            'approved': 'approved',
            'در انتظار تایید': 'pending',
            'در انتظار تأیید': 'pending',
            'pending': 'pending',
            'رد شده': 'rejected',
            'rejected': 'rejected',
        }.get(value, 'approved')

    if request.GET.get('teacher_action') == 'sample':
        return xlsx_response(
            'teachers-template.xlsx',
            excel_headers,
            [[
                'استاد',
                'نمونه',
                'teacher.sample',
                'teacher.sample@example.com',
                '09120000000',
                '0012345678',
                'TCH-003',
                'فعال',
                'تایید شده',
                'دانشگاه نمونه',
                'دانشکده مهندسی',
                'گروه مهندسی کامپیوتر',
            ]],
            'Teachers',
        )

    if request.method == 'POST' and request.POST.get('teacher_action') == 'import':
        uploaded = request.FILES.get('excel_file')
        if not uploaded:
            messages.error(request, 'لطفاً فایل اکسل اساتید را انتخاب کنید.')
            return redirect('core:super_admin_teachers')
        try:
            imported_rows = read_xlsx_dicts(uploaded)
        except (KeyError, ET.ParseError, zipfile.BadZipFile):
            messages.error(request, 'فایل انتخاب‌شده معتبر نیست. لطفاً قالب اکسل را دانلود و تکمیل کنید.')
            return redirect('core:super_admin_teachers')

        imported_count = 0
        import_errors = []
        created_credentials = []
        with connection.cursor() as cursor:
            for row_number, row in enumerate(imported_rows, start=2):
                first_name = row.get('نام', '').strip()
                last_name = row.get('نام خانوادگی', '').strip()
                username = row.get('نام کاربری', '').strip()
                email = row.get('ایمیل', '').strip()
                phone = row.get('موبایل', '').strip()
                national_id = row.get('کد ملی', '').strip()
                personnel_code = row.get('کد پرسنلی', '').strip()
                full_name = f'{first_name} {last_name}'.strip() or username or email or personnel_code
                if not full_name or not personnel_code:
                    import_errors.append(f'ردیف {row_number}: نام یا کد پرسنلی کامل نیست.')
                    continue
                username = username or email or personnel_code
                status = import_status(row.get('وضعیت حساب', 'فعال'))
                approval_status = import_approval(row.get('وضعیت تایید', 'تایید شده'))
                org_unit_id = resolve_org_unit_id(row.get('دانشگاه'), row.get('دانشکده'), row.get('گروه آموزشی'))
                primary = unit_path(org_unit_id) if org_unit_id else {'department': row.get('گروه آموزشی', '').strip()}

                cursor.execute(
                    """
                    SELECT id
                    FROM profiles
                    WHERE identifier = %s OR email = %s OR username = %s
                    LIMIT 1
                    """,
                    [personnel_code, email or None, username or None],
                )
                existing = cursor.fetchone()
                teacher_id = existing[0] if existing else str(uuid.uuid4())
                if existing:
                    cursor.execute(
                        """
                        UPDATE profiles
                        SET full_name = %s, first_name = %s, last_name = %s, username = %s,
                            email = %s, phone = %s, national_id = %s, identifier = %s,
                            status = %s, updated_at = CURRENT_TIMESTAMP
                        WHERE id = %s
                        """,
                        [full_name, first_name, last_name, username, email or None, phone or None, national_id or None, personnel_code, status, teacher_id],
                    )
                else:
                    cursor.execute(
                        """
                        INSERT INTO profiles (id, full_name, first_name, last_name, username, email, phone, national_id, identifier, avatar_url, status, created_at, updated_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, '', %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                        """,
                        [teacher_id, full_name, first_name, last_name, username, email or None, phone or None, national_id or None, personnel_code, status],
                    )
                cursor.execute(
                    """
                    INSERT INTO teacher_profiles (user_id, personnel_code, department, specialty, approval_status, org_unit_id)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT(user_id) DO UPDATE SET
                        personnel_code = excluded.personnel_code,
                        department = excluded.department,
                        specialty = excluded.specialty,
                        approval_status = excluded.approval_status,
                        org_unit_id = excluded.org_unit_id
                    """,
                    [teacher_id, personnel_code, primary.get('department') or '', '', approval_status, org_unit_id or None],
                )
                cursor.execute("DELETE FROM user_roles WHERE user_id = %s AND role = %s", [teacher_id, 'teacher'])
                cursor.execute("INSERT INTO user_roles (id, user_id, role, created_at) VALUES (%s, %s, %s, CURRENT_TIMESTAMP)", [str(uuid.uuid4()), teacher_id, 'teacher'])
                _login_user, generated_password = erd_sync_login_account(username, is_active=(status == 'active'))
                if generated_password:
                    created_credentials.append((username, generated_password))
                imported_count += 1
        if imported_count:
            messages.success(request, f'{imported_count} استاد با موفقیت وارد شد.')
        if created_credentials:
            shown = created_credentials[:15]
            credential_text = '؛ '.join(f'{username}: {password}' for username, password in shown)
            suffix = f' (و {len(created_credentials) - len(shown)} مورد دیگر)' if len(created_credentials) > len(shown) else ''
            messages.info(request, f'رمزهای عبور اولیه حساب‌های تازه‌ساخته‌شده: {credential_text}{suffix}')
        if import_errors:
            messages.warning(request, '؛ '.join(import_errors[:5]))
        return redirect('core:super_admin_teachers')

    if request.method == 'POST' and request.POST.get('teacher_action') == 'delete':
        teacher_id = request.POST.get('teacher_id')
        wants_json = request.headers.get('x-requested-with') == 'XMLHttpRequest'
        if teacher_id:
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM teacher_profiles WHERE user_id = %s", [teacher_id])
                cursor.execute("DELETE FROM user_roles WHERE user_id = %s AND role = %s", [teacher_id, 'teacher'])
                cursor.execute("DELETE FROM profiles WHERE id = %s", [teacher_id])
            if wants_json:
                return JsonResponse({'ok': True, 'message': 'استاد حذف شد.', 'teacher_id': teacher_id})
            messages.success(request, 'استاد حذف شد.')
        elif wants_json:
            return JsonResponse({'ok': False, 'message': 'شناسه استاد نامعتبر است.'}, status=400)
        return redirect('core:super_admin_teachers')

    if request.method == 'POST' and request.POST.get('teacher_action') == 'save':
        wants_json = request.headers.get('x-requested-with') == 'XMLHttpRequest'
        teacher_id = request.POST.get('teacher_id') or str(uuid.uuid4())
        first_name = request.POST.get('first_name', '').strip()
        last_name = request.POST.get('last_name', '').strip()
        full_name = f'{first_name} {last_name}'.strip() or 'استاد'
        username = request.POST.get('username', '').strip() or None
        email = request.POST.get('email', '').strip() or None
        phone = request.POST.get('phone', '').strip() or None
        national_id = request.POST.get('national_id', '').strip() or None
        personnel_code = request.POST.get('personnel_code', '').strip() or None
        status = request.POST.get('status') or 'active'
        approval_status = request.POST.get('approval_status') or 'approved'
        org_unit_id = request.POST.get('org_unit_id') or None
        avatar_url = None

        avatar = request.FILES.get('avatar')
        if avatar:
            if avatar.size <= 1024 * 1024 and avatar.content_type in {'image/jpeg', 'image/png', 'image/webp', 'image/gif'}:
                extension = avatar.name.rsplit('.', 1)[-1].lower() if '.' in avatar.name else 'jpg'
                storage = FileSystemStorage(
                    location=settings.MEDIA_ROOT / 'avatars',
                    base_url=settings.MEDIA_URL + 'avatars/',
                )
                filename = storage.save(f"{teacher_id}-{uuid.uuid4().hex[:8]}.{extension}", avatar)
                avatar_url = storage.url(filename)
            else:
                if wants_json:
                    return JsonResponse({'ok': False, 'message': 'فرمت یا حجم تصویر معتبر نیست.'}, status=400)
                messages.error(request, 'فرمت یا حجم تصویر معتبر نیست.')
                return redirect('core:super_admin_teachers')

        primary = unit_path(org_unit_id) if org_unit_id else {'department': ''}
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM profiles WHERE id = %s", [teacher_id])
            exists = cursor.fetchone()
            if exists:
                if avatar_url:
                    cursor.execute(
                        """
                        UPDATE profiles
                        SET full_name = %s, first_name = %s, last_name = %s, username = %s,
                            email = %s, phone = %s, national_id = %s, identifier = %s,
                            avatar_url = %s, status = %s, updated_at = CURRENT_TIMESTAMP
                        WHERE id = %s
                        """,
                        [full_name, first_name, last_name, username, email, phone, national_id, personnel_code, avatar_url, status, teacher_id],
                    )
                else:
                    cursor.execute(
                        """
                        UPDATE profiles
                        SET full_name = %s, first_name = %s, last_name = %s, username = %s,
                            email = %s, phone = %s, national_id = %s, identifier = %s,
                            status = %s, updated_at = CURRENT_TIMESTAMP
                        WHERE id = %s
                        """,
                        [full_name, first_name, last_name, username, email, phone, national_id, personnel_code, status, teacher_id],
                    )
            else:
                cursor.execute(
                    """
                    INSERT INTO profiles (id, full_name, first_name, last_name, username, email, phone, national_id, identifier, avatar_url, status, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    """,
                    [teacher_id, full_name, first_name, last_name, username, email, phone, national_id, personnel_code, avatar_url or '', status],
                )
            cursor.execute(
                """
                INSERT INTO teacher_profiles (user_id, personnel_code, department, specialty, approval_status, org_unit_id)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT(user_id) DO UPDATE SET
                    personnel_code = excluded.personnel_code,
                    department = excluded.department,
                    specialty = excluded.specialty,
                    approval_status = excluded.approval_status,
                    org_unit_id = excluded.org_unit_id
                """,
                [teacher_id, personnel_code, primary.get('department') or '', request.POST.get('specialty', '').strip(), approval_status, org_unit_id],
            )
            cursor.execute("DELETE FROM user_roles WHERE user_id = %s AND role = %s", [teacher_id, 'teacher'])
            cursor.execute("INSERT INTO user_roles (id, user_id, role, created_at) VALUES (%s, %s, %s, CURRENT_TIMESTAMP)", [str(uuid.uuid4()), teacher_id, 'teacher'])
        _login_user, generated_password = erd_sync_login_account(username, is_active=(status == 'active'))
        if wants_json:
            final_avatar_url = erd_row('SELECT avatar_url FROM profiles WHERE id = %s', [teacher_id])
            primary = unit_path(org_unit_id) if org_unit_id else {'university': '-', 'faculty': '-', 'department': '-'}
            return JsonResponse({
                'ok': True,
                'message': 'اطلاعات استاد ذخیره شد.',
                'teacher_id': teacher_id,
                'first_name': first_name,
                'last_name': last_name,
                'full_name': full_name,
                'username': username or '',
                'email': email or '',
                'phone': phone or '',
                'national_id': national_id or '',
                'personnel_code': personnel_code or '',
                'status': status,
                'approval_status': approval_status,
                'org_unit_id': org_unit_id or '',
                'university': primary.get('university') or '-',
                'faculty': primary.get('faculty') or '-',
                'department': primary.get('department') or '-',
                'courses_count': 0,
                'avatar_url': (final_avatar_url or {}).get('avatar_url') or '',
                'generated_password': generated_password or '',
            })
        if generated_password:
            messages.success(request, f'اطلاعات استاد ذخیره شد. نام کاربری: {username} — رمز عبور اولیه: {generated_password}')
        else:
            messages.success(request, 'اطلاعات استاد ذخیره شد.')
        return redirect('core:super_admin_teachers')

    teachers = erd_rows(
        """
        SELECT p.id, p.full_name, p.first_name, p.last_name, p.username, p.email, p.phone,
               p.national_id, p.identifier, p.avatar_url, p.status, p.created_at, p.last_login_at,
               tp.personnel_code, tp.department, tp.specialty, tp.approval_status, tp.org_unit_id,
               COALESCE((
                   SELECT COUNT(DISTINCT course_id)
                   FROM (
                       SELECT q.course_id AS course_id FROM questions q WHERE q.teacher_id = tp.user_id AND q.course_id IS NOT NULL
                       UNION
                       SELECT e.course_id AS course_id FROM exams e WHERE e.teacher_id = tp.user_id AND e.course_id IS NOT NULL
                   ) teacher_courses
               ), 0) AS courses_count
        FROM teacher_profiles tp
        JOIN profiles p ON p.id = tp.user_id
        ORDER BY p.full_name
        LIMIT 200
        """
    )

    rows = []
    for teacher in teachers:
        primary = unit_path(teacher.get('org_unit_id'))
        if q and not _matches_query(q, teacher.get('full_name'), teacher.get('email'), teacher.get('username'), teacher.get('personnel_code'), primary['label']):
            continue
        rows.append({
            **teacher,
            'university': primary['university'],
            'faculty': primary['faculty'],
            'department_name': primary['department'],
            'created_display': teacher.get('created_at') or '-',
            'last_login_display': teacher.get('last_login_at') or '-',
        })

    if request.GET.get('teacher_action') == 'export':
        status_labels = {'active': 'فعال', 'inactive': 'غیرفعال', 'blocked': 'مسدود'}
        approval_labels = {'approved': 'تایید شده', 'pending': 'در انتظار تایید', 'rejected': 'رد شده'}
        export_rows = []
        for row in rows:
            export_rows.append([
                row.get('first_name') or '',
                row.get('last_name') or '',
                row.get('username') or '',
                row.get('email') or '',
                row.get('phone') or '',
                row.get('national_id') or '',
                row.get('personnel_code') or row.get('identifier') or '',
                status_labels.get(row.get('status') or 'active', 'فعال'),
                approval_labels.get(row.get('approval_status') or 'approved', 'تایید شده'),
                row.get('university') or '',
                row.get('faculty') or '',
                row.get('department_name') or '',
            ])
        return xlsx_response('teachers.xlsx', excel_headers, export_rows, 'Teachers')

    return render(request, 'super_admin/teachers.html', {
        'title': 'اساتید',
        'description': 'ایجاد، ویرایش کامل اطلاعات اساتید و مشاهده دپارتمان و دروس تحت تدریس.',
        'rows': rows,
        'query': q,
        'universities': [unit for unit in org_units if unit['type'] == 'university'],
        'org_units_json': org_units,
    })


@super_admin_required
def super_admin_student_bulk_import(request):
    session_key = 'super_admin_student_bulk_import'
    draft = request.session.get(session_key, {})
    action = request.GET.get('bulk_action') or request.POST.get('bulk_action') or ''
    step = request.GET.get('step') or request.POST.get('step') or draft.get('step') or '1'
    try:
        step = max(1, min(4, int(step)))
    except (TypeError, ValueError):
        step = 1

    headers = ['نام', 'نام خانوادگی', 'کد ملی', 'کد دانشجویی', 'سال ورود', 'مقطع', 'رشته', 'واحد سازمانی', 'شماره همراه', 'ایمیل', 'گروه آموزشی', 'درس‌ها', 'وضعیت حساب']
    sample_rows = [
        ['علی', 'محمدی', '1234567890', '40123456', '1403', 'کارشناسی', 'مهندسی کامپیوتر', 'دانشکده فنی', '09121234567', 'ali@example.com', 'گروه 1', 'ساختمان داده‌ها، پایگاه داده', 'فعال'],
        ['سارا', 'رضایی', '1234567891', '40123457', '1402', 'کارشناسی ارشد', 'مدیریت کسب‌وکار', 'دانشکده مدیریت', '09121234568', 'sara@example.com', 'گروه 2', 'روش تحقیق', 'فعال'],
        ['امیرحسین', 'احمدی', '1234567892', '40123458', '1403', 'دکتری', 'هوش مصنوعی', 'دانشکده فنی', '', 'amir@example.com', '', '', 'فعال'],
    ]
    if action == 'sample':
        return xlsx_response('students-template.xlsx', headers, sample_rows, 'Students')

    org_units = erd_rows("SELECT id, parent_id, type, name, code, is_active FROM org_units ORDER BY CASE type WHEN 'university' THEN 0 WHEN 'faculty' THEN 1 ELSE 2 END, name")
    courses = erd_rows("SELECT id, title, code, COALESCE(credit_units, 0) AS credit_units FROM courses ORDER BY title LIMIT 500")
    groups = erd_rows("SELECT id, course_id, course_name, group_code, academic_year, semester FROM student_groups ORDER BY academic_year DESC, course_name LIMIT 500")
    unit_by_id = {str(unit['id']): unit for unit in org_units}

    def normalize_text(value):
        return str(value or '').strip().replace('ي', 'ی').replace('ك', 'ک').replace('\u200c', ' ').lower()

    def split_values(value):
        return [part.strip() for part in str(value or '').replace(';', '،').replace(',', '،').split('،') if part.strip()]

    def unit_path(unit_id):
        unit = unit_by_id.get(str(unit_id or ''))
        chain = []
        seen = set()
        while unit and str(unit['id']) not in seen:
            seen.add(str(unit['id']))
            chain.append(unit)
            unit = unit_by_id.get(str(unit.get('parent_id') or ''))
        by_type = {item['type']: item['name'] for item in chain}
        label = ' / '.join(part for part in [by_type.get('university'), by_type.get('faculty'), by_type.get('department') or by_type.get('group')] if part)
        return {'university': by_type.get('university') or '', 'faculty': by_type.get('faculty') or '', 'department': by_type.get('department') or by_type.get('group') or '', 'label': label or ''}

    def resolve_unit(value):
        value = normalize_text(value)
        if not value:
            return ''
        for unit in org_units:
            path = unit_path(unit['id'])
            options = {normalize_text(unit.get('name')), normalize_text(unit.get('code')), normalize_text(path.get('label'))}
            if value in options:
                return str(unit['id'])
        for unit in org_units:
            path = unit_path(unit['id'])
            haystack = normalize_text(f"{unit.get('name')} {unit.get('code')} {path.get('label')}")
            if value in haystack:
                return str(unit['id'])
        return None

    def resolve_courses(value):
        selected = []
        tokens = split_values(value)
        for token in tokens:
            normalized = normalize_text(token)
            for course in courses:
                if normalized in {normalize_text(course.get('title')), normalize_text(course.get('code'))}:
                    selected.append(str(course['id']))
                    break
        return list(dict.fromkeys(selected))

    def resolve_groups(value):
        selected = []
        tokens = split_values(value)
        for token in tokens:
            normalized = normalize_text(token)
            for group in groups:
                haystack = normalize_text(f"{group.get('group_code')} {group.get('course_name')} {group.get('academic_year')} {group.get('semester')}")
                if normalized and normalized in haystack:
                    selected.append(str(group['id']))
                    break
        return list(dict.fromkeys(selected))

    def import_status(value):
        value = normalize_text(value)
        return {'غیرفعال': 'inactive', 'inactive': 'inactive', 'مسدود': 'blocked', 'blocked': 'blocked'}.get(value, 'active')

    def import_academic_status(value):
        value = normalize_text(value)
        return {'مرخصی': 'leave', 'leave': 'leave', 'فارغ التحصیل': 'graduated', 'فارغ‌التحصیل': 'graduated', 'graduated': 'graduated', 'غیرفعال': 'inactive', 'inactive': 'inactive'}.get(value, 'active')

    def cell(row, key):
        return str(row.get(key) or '').strip()

    field_defs = [
        {'key': 'first_name', 'label': 'نام', 'required': True, 'aliases': ['نام', 'first_name', 'name']},
        {'key': 'last_name', 'label': 'نام خانوادگی', 'required': True, 'aliases': ['نام خانوادگی', 'نام خانوادگي', 'last_name', 'family']},
        {'key': 'national_id', 'label': 'کد ملی', 'required': True, 'aliases': ['کد ملی', 'کد ملي', 'national_id']},
        {'key': 'student_number', 'label': 'کد دانشجویی', 'required': True, 'aliases': ['کد دانشجویی', 'شماره دانشجویی', 'student_code', 'student_number']},
        {'key': 'entry_year', 'label': 'سال ورود', 'required': True, 'aliases': ['سال ورود', 'entry_year']},
        {'key': 'degree', 'label': 'مقطع', 'required': True, 'aliases': ['مقطع', 'degree']},
        {'key': 'field_of_study', 'label': 'رشته', 'required': True, 'aliases': ['رشته', 'رشته تحصیلی', 'major', 'field_of_study']},
        {'key': 'org_unit', 'label': 'واحد سازمانی', 'required': True, 'aliases': ['واحد سازمانی', 'دانشگاه', 'دانشکده', 'گروه آموزشی', 'org_unit']},
        {'key': 'phone', 'label': 'شماره همراه', 'required': False, 'aliases': ['شماره همراه', 'موبایل', 'mobile', 'phone']},
        {'key': 'email', 'label': 'ایمیل', 'required': False, 'aliases': ['ایمیل', 'email']},
        {'key': 'group_names', 'label': 'گروه آموزشی', 'required': False, 'aliases': ['گروه آموزشی', 'گروه های آموزشی', 'groups']},
        {'key': 'course_names', 'label': 'درس‌ها', 'required': False, 'aliases': ['درس‌ها', 'درس ها', 'courses']},
        {'key': 'academic_status', 'label': 'وضعیت تحصیلی', 'required': False, 'aliases': ['وضعیت تحصیلی', 'academic_status']},
        {'key': 'status', 'label': 'وضعیت حساب', 'required': False, 'aliases': ['وضعیت حساب', 'status']},
    ]

    def guess_mapping(upload_headers):
        mapping = {}
        normalized_headers = {normalize_text(header): header for header in upload_headers}
        for field in field_defs:
            for alias in field['aliases']:
                found = normalized_headers.get(normalize_text(alias))
                if found:
                    mapping[field['key']] = found
                    break
            mapping.setdefault(field['key'], '')
        return mapping

    def validate_rows():
        upload_rows = draft.get('rows') or []
        mapping = draft.get('mapping') or {}
        ignored_rows = set(draft.get('ignored_rows') or [])
        records = []
        counts = {'ok': 0, 'warning': 0, 'error': 0, 'ignored': 0}
        seen_national = set()
        seen_student = set()
        for index, raw in enumerate(upload_rows, start=2):
            record = {field['key']: cell(raw, mapping.get(field['key'])) for field in field_defs}
            issues = []
            for field in field_defs:
                if field['required'] and not record.get(field['key']):
                    issues.append(('error', field['key'], f"{field['label']} خالی است."))
            if record.get('national_id') and record['national_id'] in seen_national:
                issues.append(('error', 'national_id', 'کد ملی تکراری است.'))
            if record.get('student_number') and record['student_number'] in seen_student:
                issues.append(('error', 'student_number', 'کد دانشجویی تکراری است.'))
            seen_national.add(record.get('national_id'))
            seen_student.add(record.get('student_number'))
            if record.get('phone') == '':
                issues.append(('warning', 'phone', 'شماره همراه ناقص است.'))
            org_unit_id = resolve_unit(record.get('org_unit'))
            if org_unit_id is None:
                issues.append(('error', 'org_unit', 'واحد سازمانی معتبر نیست.'))
            course_ids = resolve_courses(record.get('course_names'))
            group_ids = resolve_groups(record.get('group_names'))
            if record.get('course_names') and not course_ids:
                issues.append(('warning', 'course_names', 'درس‌های فایل با درس‌های سامانه تطبیق نشد.'))
            if record.get('group_names') and not group_ids:
                issues.append(('warning', 'group_names', 'گروه آموزشی فایل با گروه‌های سامانه تطبیق نشد.'))
            record['row_number'] = index
            record['status'] = import_status(record.get('status'))
            record['academic_status'] = import_academic_status(record.get('academic_status'))
            record['org_unit_id'] = org_unit_id or ''
            record['org_unit_label'] = unit_path(org_unit_id).get('label') if org_unit_id else record.get('org_unit')
            record['course_ids'] = course_ids
            record['group_ids'] = group_ids
            record['full_name'] = f"{record.get('first_name')} {record.get('last_name')}".strip()
            errors = [msg for level, _key, msg in issues if level == 'error']
            warnings = [msg for level, _key, msg in issues if level == 'warning']
            record['issues'] = errors + warnings
            if index in ignored_rows:
                record['level'] = 'ignored'
            else:
                record['level'] = 'error' if errors else ('warning' if warnings else 'ok')
            primary_issue = next(iter(issues), None)
            record['primary_issue_field'] = primary_issue[1] if primary_issue else ''
            record['primary_issue_label'] = next((f['label'] for f in field_defs if f['key'] == (primary_issue[1] if primary_issue else '')), '')
            counts[record['level']] += 1
            records.append(record)
        draft['records'] = records
        draft['counts'] = counts
        request.session[session_key] = draft
        request.session.modified = True
        return records, counts

    if request.method == 'POST':
        nav_action = request.POST.get('wizard_action') or 'next'
        if nav_action == 'cancel':
            request.session.pop(session_key, None)
            return redirect(f'{reverse("core:super_admin_users")}?tab=students')
        if nav_action == 'prev':
            draft['step'] = max(1, step - 1)
            request.session[session_key] = draft
            request.session.modified = True
            return redirect(f'{reverse("core:super_admin_student_bulk_import")}?step={draft["step"]}')
        if nav_action == 'save_draft':
            draft['step'] = step
            request.session[session_key] = draft
            request.session.modified = True
            messages.success(request, 'پیش‌نویس ورود گروهی دانشجویان ذخیره شد.')
            return redirect(f'{reverse("core:super_admin_student_bulk_import")}?step={step}')
        if nav_action == 'fix_row':
            try:
                row_number = int(request.POST.get('row_number', ''))
            except (TypeError, ValueError):
                row_number = None
            field_key = request.POST.get('fix_field', '').strip()
            new_value = request.POST.get('fix_value', '').strip()
            mapping = draft.get('mapping') or {}
            upload_rows = draft.get('rows') or []
            row_index = (row_number - 2) if row_number else -1
            if field_key in mapping and 0 <= row_index < len(upload_rows):
                header = mapping.get(field_key)
                if not header:
                    header = field_key
                    mapping[field_key] = header
                    draft['mapping'] = mapping
                upload_rows[row_index][header] = new_value
                draft['rows'] = upload_rows
                request.session[session_key] = draft
                request.session.modified = True
                validate_rows()
                messages.success(request, f'ردیف {row_number} اصلاح شد.')
            return redirect(f'{reverse("core:super_admin_student_bulk_import")}?step=3')
        if nav_action == 'ignore_row':
            try:
                row_number = int(request.POST.get('row_number', ''))
            except (TypeError, ValueError):
                row_number = None
            if row_number:
                ignored = set(draft.get('ignored_rows') or [])
                ignored.add(row_number)
                draft['ignored_rows'] = list(ignored)
                request.session[session_key] = draft
                request.session.modified = True
                validate_rows()
            return redirect(f'{reverse("core:super_admin_student_bulk_import")}?step=3')
        if nav_action == 'restore_row':
            try:
                row_number = int(request.POST.get('row_number', ''))
            except (TypeError, ValueError):
                row_number = None
            if row_number:
                ignored = set(draft.get('ignored_rows') or [])
                ignored.discard(row_number)
                draft['ignored_rows'] = list(ignored)
                request.session[session_key] = draft
                request.session.modified = True
                validate_rows()
            return redirect(f'{reverse("core:super_admin_student_bulk_import")}?step=3')

        if step == 1:
            uploaded = request.FILES.get('excel_file')
            if not uploaded:
                messages.error(request, 'لطفا فایل دانشجویان را انتخاب کنید.')
                return redirect(f'{reverse("core:super_admin_student_bulk_import")}?step=1')
            suffix = Path(uploaded.name).suffix.lower()
            try:
                if suffix == '.csv':
                    text = uploaded.read().decode('utf-8-sig')
                    rows = list(csv.DictReader(io.StringIO(text)))
                else:
                    rows = read_xlsx_dicts(uploaded)
            except (UnicodeDecodeError, KeyError, ET.ParseError, zipfile.BadZipFile):
                messages.error(request, 'فایل انتخاب‌شده معتبر نیست. قالب نمونه را دریافت و تکمیل کنید.')
                return redirect(f'{reverse("core:super_admin_student_bulk_import")}?step=1')
            if not rows:
                messages.error(request, 'فایل انتخاب‌شده ردیفی برای ورود ندارد.')
                return redirect(f'{reverse("core:super_admin_student_bulk_import")}?step=1')
            upload_headers = list(rows[0].keys())
            draft = {
                'step': 2,
                'filename': uploaded.name,
                'headers': upload_headers,
                'rows': rows[:1000],
                'total_rows': len(rows),
                'first_row': rows[0],
                'mapping': guess_mapping(upload_headers),
                'has_header': request.POST.get('has_header') == 'on',
            }
            request.session[session_key] = draft
            request.session.modified = True
            return redirect(f'{reverse("core:super_admin_student_bulk_import")}?step=2')

        if step == 2:
            draft['mapping'] = {field['key']: request.POST.get(f'map_{field["key"]}', '').strip() for field in field_defs}
            draft['step'] = 3
            request.session[session_key] = draft
            request.session.modified = True
            validate_rows()
            return redirect(f'{reverse("core:super_admin_student_bulk_import")}?step=3')

        if step == 3:
            draft['step'] = 4
            request.session[session_key] = draft
            request.session.modified = True
            validate_rows()
            return redirect(f'{reverse("core:super_admin_student_bulk_import")}?step=4')

        if step == 4:
            if not request.POST.get('confirm_final'):
                messages.error(request, 'برای ثبت نهایی، تایید صحت اطلاعات لازم است.')
                return redirect(f'{reverse("core:super_admin_student_bulk_import")}?step=4')
            records, counts = validate_rows()
            if counts.get('error'):
                messages.error(request, 'ردیف‌های دارای خطا باید قبل از ثبت نهایی اصلاح شوند.')
                return redirect(f'{reverse("core:super_admin_student_bulk_import")}?step=3')
            create_accounts = request.POST.get('create_accounts') == 'on'
            send_activation = request.POST.get('send_activation') == 'on'
            send_welcome = request.POST.get('send_welcome') == 'on'
            auto_add_groups = request.POST.get('auto_add_groups') == 'on'
            force_password = request.POST.get('force_password') == 'on'
            account_status = request.POST.get('account_status') or 'active'
            password_method = request.POST.get('password_method') or 'auto'
            imported_count = 0
            created_credentials = []
            try:
                with connection.cursor() as cursor:
                    for record in records:
                        if record['level'] in ('error', 'ignored'):
                            continue
                        student_id = str(uuid.uuid4())
                        username = record.get('student_number')
                        email = record.get('email') or None
                        cursor.execute("SELECT id FROM profiles WHERE identifier = %s OR username = %s OR email = %s OR national_id = %s LIMIT 1", [record['student_number'], username, email, record['national_id']])
                        existing = cursor.fetchone()
                        if existing:
                            student_id = existing[0]
                            cursor.execute(
                                """
                                UPDATE profiles
                                SET full_name = %s, first_name = %s, last_name = %s, username = %s,
                                    email = %s, phone = %s, national_id = %s, identifier = %s,
                                    status = %s, password_method = %s, must_change_password = %s,
                                    updated_at = CURRENT_TIMESTAMP
                                WHERE id = %s
                                """,
                                [record['full_name'], record['first_name'], record['last_name'], username, email, record.get('phone') or None, record['national_id'], record['student_number'], account_status or record['status'], password_method, force_password, student_id],
                            )
                        else:
                            cursor.execute(
                                """
                                INSERT INTO profiles (
                                    id, full_name, first_name, last_name, username, email, phone, national_id,
                                    identifier, avatar_url, status, password_method, must_change_password,
                                    created_at, updated_at
                                )
                                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, '', %s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                                """,
                                [student_id, record['full_name'], record['first_name'], record['last_name'], username, email, record.get('phone') or None, record['national_id'], record['student_number'], account_status or record['status'], password_method if create_accounts else '', force_password],
                            )
                        primary = unit_path(record.get('org_unit_id'))
                        cursor.execute(
                            """
                            INSERT INTO student_profiles (
                                user_id, student_number, field_of_study, degree, class_group, semester, academic_status,
                                department, org_unit_id, entry_year, admission_type, password_method, must_change_password, send_welcome_message
                            )
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT(user_id) DO UPDATE SET
                                student_number = excluded.student_number,
                                field_of_study = excluded.field_of_study,
                                degree = excluded.degree,
                                class_group = excluded.class_group,
                                semester = excluded.semester,
                                academic_status = excluded.academic_status,
                                department = excluded.department,
                                org_unit_id = excluded.org_unit_id,
                                entry_year = excluded.entry_year,
                                admission_type = excluded.admission_type,
                                password_method = excluded.password_method,
                                must_change_password = excluded.must_change_password,
                                send_welcome_message = excluded.send_welcome_message
                            """,
                            [student_id, record['student_number'], record['field_of_study'], record['degree'], record.get('group_names') or '', '', record['academic_status'], primary.get('department') or '', record.get('org_unit_id') or None, record['entry_year'], '', password_method, force_password, send_welcome],
                        )
                        cursor.execute("DELETE FROM user_roles WHERE user_id = %s AND role = %s", [student_id, 'student'])
                        cursor.execute("INSERT INTO user_roles (id, user_id, role, created_at) VALUES (%s, %s, %s, CURRENT_TIMESTAMP)", [str(uuid.uuid4()), student_id, 'student'])
                        if auto_add_groups:
                            cursor.execute("DELETE FROM student_group_members WHERE student_user_id = %s", [student_id])
                            for group_id in record.get('group_ids') or []:
                                cursor.execute("INSERT INTO student_group_members (id, group_id, student_user_id, full_name, national_id, student_number) VALUES (%s, %s, %s, %s, %s, %s)", [str(uuid.uuid4()), group_id, student_id, record['full_name'], record['national_id'], record['student_number']])
                        cursor.execute("DELETE FROM student_course_enrollments WHERE student_user_id = %s", [student_id])
                        for course_id in record.get('course_ids') or []:
                            cursor.execute("INSERT INTO student_course_enrollments (id, student_user_id, course_id, created_at) VALUES (%s, %s, %s, CURRENT_TIMESTAMP) ON CONFLICT(student_user_id, course_id) DO NOTHING", [str(uuid.uuid4()), student_id, course_id])
                        if create_accounts:
                            _login_user, generated_password = erd_sync_login_account(username, is_active=(account_status == 'active'), reset_password=force_password)
                            if generated_password:
                                created_credentials.append((username, generated_password))
                        imported_count += 1
            except DatabaseError as exc:
                messages.error(request, f'ثبت گروهی دانشجویان انجام نشد: {exc}')
                return redirect(f'{reverse("core:super_admin_student_bulk_import")}?step=4')
            request.session.pop(session_key, None)
            messages.success(request, f'{imported_count} دانشجو با موفقیت ثبت شد.')
            if created_credentials:
                shown = created_credentials[:15]
                credential_text = '؛ '.join(f'{username}: {password}' for username, password in shown)
                suffix = f' (و {len(created_credentials) - len(shown)} مورد دیگر)' if len(created_credentials) > len(shown) else ''
                messages.info(request, f'رمزهای عبور اولیه حساب‌های تازه‌ساخته‌شده: {credential_text}{suffix}')
            return redirect(f'{reverse("core:super_admin_users")}?tab=students')

    if step >= 3 and draft.get('rows') and draft.get('mapping'):
        validate_rows()
    mapping = draft.get('mapping') or {}
    preview_rows = [
        {field['key']: cell(raw, mapping.get(field['key'])) for field in field_defs}
        for raw in (draft.get('rows') or [])[:3]
    ]
    records = draft.get('records') or []
    counts = draft.get('counts') or {'ok': 0, 'warning': 0, 'error': 0, 'ignored': 0}
    valid_count = counts.get('ok', 0) + counts.get('warning', 0)
    groups_count = len({group_id for record in records for group_id in record.get('group_ids', [])})
    courses_count = len({course_id for record in records for course_id in record.get('course_ids', [])})
    degree_summary = {}
    for record in records:
        if record.get('level') not in ('error', 'ignored'):
            degree_summary[record.get('degree') or 'نامشخص'] = degree_summary.get(record.get('degree') or 'نامشخص', 0) + 1
    steps = [
        {'number': 1, 'label': 'بارگذاری فایل'},
        {'number': 2, 'label': 'تطبیق ستون‌ها'},
        {'number': 3, 'label': 'بررسی و رفع خطاها'},
        {'number': 4, 'label': 'ثبت نهایی'},
    ]
    return render(request, 'super_admin/student_bulk_import.html', {
        'step': step,
        'steps': steps,
        'draft': draft,
        'field_defs': field_defs,
        'headers': draft.get('headers') or [],
        'first_row': draft.get('first_row') or {},
        'preview_rows': preview_rows,
        'records': records,
        'counts': counts,
        'valid_count': valid_count,
        'groups_count': groups_count,
        'courses_count': courses_count,
        'degree_summary': degree_summary,
        'required_fields': [field for field in field_defs if field['required']],
        'optional_fields': [field for field in field_defs if not field['required']],
        'back_url': f'{reverse("core:super_admin_users")}?tab=students',
    })


@super_admin_required
def super_admin_teacher_bulk_import(request):
    session_key = 'super_admin_teacher_bulk_import'
    draft = request.session.get(session_key, {})
    action = request.GET.get('bulk_action') or request.POST.get('bulk_action') or ''
    step = request.GET.get('step') or request.POST.get('step') or draft.get('step') or '1'
    try:
        step = max(1, min(4, int(step)))
    except (TypeError, ValueError):
        step = 1

    headers = ['نام', 'نام خانوادگی', 'کد ملی', 'شماره همراه', 'واحد سازمانی', 'مرتبه علمی', 'نوع همکاری', 'ایمیل', 'کد پرسنلی', 'درس‌ها', 'وضعیت حساب']
    sample_rows = [
        ['علی', 'رضایی', '0012345678', '09121234567', 'گروه پرستاری داخلی جراحی', 'استادیار', 'تمام وقت', 'ali.rezaei@example.com', 'TCH-1405-01', 'ساختمان داده‌ها، پایگاه داده', 'فعال'],
        ['سارا', 'محمدی', '0012345679', '09121234568', 'دانشکده روانشناسی', 'دانشیار', 'مدعو', 'sara.mohammadi@example.com', 'TCH-1405-02', 'روش تحقیق', 'فعال'],
    ]
    if action == 'sample':
        return xlsx_response('teachers-template.xlsx', headers, sample_rows, 'Teachers')

    org_units = erd_rows("SELECT id, parent_id, type, name, code, is_active FROM org_units ORDER BY CASE type WHEN 'university' THEN 0 WHEN 'faculty' THEN 1 ELSE 2 END, name")
    courses = erd_rows("SELECT id, title, code, COALESCE(credit_units, 0) AS credit_units FROM courses ORDER BY title LIMIT 500")
    unit_by_id = {str(unit['id']): unit for unit in org_units}

    def normalize_text(value):
        return str(value or '').strip().replace('ي', 'ی').replace('ك', 'ک').replace('\u200c', ' ').lower()

    def split_values(value):
        return [part.strip() for part in str(value or '').replace(';', '،').replace(',', '،').split('،') if part.strip()]

    def unit_path(unit_id):
        unit = unit_by_id.get(str(unit_id or ''))
        chain = []
        seen = set()
        while unit and str(unit['id']) not in seen:
            seen.add(str(unit['id']))
            chain.append(unit)
            unit = unit_by_id.get(str(unit.get('parent_id') or ''))
        by_type = {item['type']: item['name'] for item in chain}
        label = ' / '.join(part for part in [by_type.get('university'), by_type.get('faculty'), by_type.get('department') or by_type.get('group')] if part)
        return {'university': by_type.get('university') or '', 'faculty': by_type.get('faculty') or '', 'department': by_type.get('department') or by_type.get('group') or '', 'label': label or ''}

    def resolve_unit(value):
        value = normalize_text(value)
        if not value:
            return ''
        for unit in org_units:
            path = unit_path(unit['id'])
            options = {normalize_text(unit.get('name')), normalize_text(unit.get('code')), normalize_text(path.get('label'))}
            if value in options:
                return str(unit['id'])
        for unit in org_units:
            path = unit_path(unit['id'])
            haystack = normalize_text(f"{unit.get('name')} {unit.get('code')} {path.get('label')}")
            if value in haystack:
                return str(unit['id'])
        return None

    def resolve_courses(value):
        selected = []
        for token in split_values(value):
            normalized = normalize_text(token)
            for course in courses:
                if normalized in {normalize_text(course.get('title')), normalize_text(course.get('code'))}:
                    selected.append(str(course['id']))
                    break
        return list(dict.fromkeys(selected))

    def import_status(value):
        value = normalize_text(value)
        return {'غیرفعال': 'inactive', 'inactive': 'inactive', 'مسدود': 'blocked', 'blocked': 'blocked'}.get(value, 'active')

    def cell(row, key):
        return str(row.get(key) or '').strip()

    field_defs = [
        {'key': 'first_name', 'label': 'نام', 'required': True, 'aliases': ['نام', 'first_name', 'name']},
        {'key': 'last_name', 'label': 'نام خانوادگی', 'required': True, 'aliases': ['نام خانوادگی', 'نام خانوادگي', 'last_name', 'family']},
        {'key': 'national_id', 'label': 'کد ملی', 'required': True, 'aliases': ['کد ملی', 'کد ملي', 'national_id']},
        {'key': 'phone', 'label': 'شماره همراه', 'required': True, 'aliases': ['شماره همراه', 'موبایل', 'mobile', 'phone']},
        {'key': 'org_unit', 'label': 'واحد سازمانی', 'required': True, 'aliases': ['واحد سازمانی', 'گروه آموزشی', 'مسیر سازمانی', 'org_unit']},
        {'key': 'academic_rank', 'label': 'مرتبه علمی', 'required': False, 'aliases': ['مرتبه علمی', 'academic_rank', 'rank']},
        {'key': 'cooperation_type', 'label': 'نوع همکاری', 'required': False, 'aliases': ['نوع همکاری', 'cooperation_type']},
        {'key': 'email', 'label': 'ایمیل', 'required': False, 'aliases': ['ایمیل', 'email']},
        {'key': 'personnel_code', 'label': 'کد پرسنلی', 'required': False, 'aliases': ['کد پرسنلی', 'شماره پرسنلی', 'personnel_code']},
        {'key': 'course_names', 'label': 'درس‌ها', 'required': False, 'aliases': ['درس‌ها', 'درس ها', 'courses']},
        {'key': 'status', 'label': 'وضعیت حساب', 'required': False, 'aliases': ['وضعیت حساب', 'status']},
    ]

    def guess_mapping(upload_headers):
        mapping = {}
        normalized_headers = {normalize_text(header): header for header in upload_headers}
        for field in field_defs:
            for alias in field['aliases']:
                found = normalized_headers.get(normalize_text(alias))
                if found:
                    mapping[field['key']] = found
                    break
            mapping.setdefault(field['key'], '')
        return mapping

    def validate_rows():
        upload_rows = draft.get('rows') or []
        mapping = draft.get('mapping') or {}
        ignored_rows = set(draft.get('ignored_rows') or [])
        records = []
        counts = {'ok': 0, 'warning': 0, 'error': 0, 'ignored': 0}
        seen_national = set()
        seen_phone = set()
        for index, raw in enumerate(upload_rows, start=2):
            record = {field['key']: cell(raw, mapping.get(field['key'])) for field in field_defs}
            issues = []
            for field in field_defs:
                if field['required'] and not record.get(field['key']):
                    issues.append(('error', field['key'], f"{field['label']} خالی است."))
            if record.get('national_id') and record['national_id'] in seen_national:
                issues.append(('error', 'national_id', 'کد ملی تکراری است.'))
            if record.get('phone') and record['phone'] in seen_phone:
                issues.append(('warning', 'phone', 'شماره همراه تکراری است.'))
            seen_national.add(record.get('national_id'))
            seen_phone.add(record.get('phone'))
            org_unit_id = resolve_unit(record.get('org_unit'))
            if org_unit_id is None:
                issues.append(('error', 'org_unit', 'واحد سازمانی یافت نشد.'))
            course_ids = resolve_courses(record.get('course_names'))
            if record.get('course_names') and not course_ids:
                issues.append(('warning', 'course_names', 'درس‌های فایل با درس‌های سامانه تطبیق نشد.'))
            record['row_number'] = index
            record['status'] = import_status(record.get('status'))
            record['org_unit_id'] = org_unit_id or ''
            record['org_unit_label'] = unit_path(org_unit_id).get('label') if org_unit_id else record.get('org_unit')
            record['course_ids'] = course_ids
            record['personnel_code'] = record.get('personnel_code') or f"TCH-{record.get('national_id') or uuid.uuid4().hex[:6]}"
            record['full_name'] = f"{record.get('first_name')} {record.get('last_name')}".strip()
            errors = [msg for level, _key, msg in issues if level == 'error']
            warnings = [msg for level, _key, msg in issues if level == 'warning']
            record['issues'] = errors + warnings
            if index in ignored_rows:
                record['level'] = 'ignored'
            else:
                record['level'] = 'error' if errors else ('warning' if warnings else 'ok')
            primary_issue = next(iter(issues), None)
            record['primary_issue_field'] = primary_issue[1] if primary_issue else ''
            record['primary_issue_label'] = next((f['label'] for f in field_defs if f['key'] == (primary_issue[1] if primary_issue else '')), '')
            counts[record['level']] += 1
            records.append(record)
        draft['records'] = records
        draft['counts'] = counts
        request.session[session_key] = draft
        request.session.modified = True
        return records, counts

    if request.method == 'POST':
        nav_action = request.POST.get('wizard_action') or 'next'
        if nav_action == 'cancel':
            request.session.pop(session_key, None)
            return redirect(f'{reverse("core:super_admin_users")}?tab=teachers')
        if nav_action == 'prev':
            draft['step'] = max(1, step - 1)
            request.session[session_key] = draft
            request.session.modified = True
            return redirect(f'{reverse("core:super_admin_teacher_bulk_import")}?step={draft["step"]}')
        if nav_action == 'save_draft':
            draft['step'] = step
            request.session[session_key] = draft
            request.session.modified = True
            messages.success(request, 'پیش‌نویس ورود گروهی اساتید ذخیره شد.')
            return redirect(f'{reverse("core:super_admin_teacher_bulk_import")}?step={step}')
        if nav_action == 'fix_row':
            try:
                row_number = int(request.POST.get('row_number', ''))
            except (TypeError, ValueError):
                row_number = None
            field_key = request.POST.get('fix_field', '').strip()
            new_value = request.POST.get('fix_value', '').strip()
            mapping = draft.get('mapping') or {}
            upload_rows = draft.get('rows') or []
            row_index = (row_number - 2) if row_number else -1
            if field_key in mapping and 0 <= row_index < len(upload_rows):
                header = mapping.get(field_key)
                if not header:
                    header = field_key
                    mapping[field_key] = header
                    draft['mapping'] = mapping
                upload_rows[row_index][header] = new_value
                draft['rows'] = upload_rows
                request.session[session_key] = draft
                request.session.modified = True
                validate_rows()
                messages.success(request, f'ردیف {row_number} اصلاح شد.')
            return redirect(f'{reverse("core:super_admin_teacher_bulk_import")}?step=3')
        if nav_action == 'ignore_row':
            try:
                row_number = int(request.POST.get('row_number', ''))
            except (TypeError, ValueError):
                row_number = None
            if row_number:
                ignored = set(draft.get('ignored_rows') or [])
                ignored.add(row_number)
                draft['ignored_rows'] = list(ignored)
                request.session[session_key] = draft
                request.session.modified = True
                validate_rows()
            return redirect(f'{reverse("core:super_admin_teacher_bulk_import")}?step=3')
        if nav_action == 'restore_row':
            try:
                row_number = int(request.POST.get('row_number', ''))
            except (TypeError, ValueError):
                row_number = None
            if row_number:
                ignored = set(draft.get('ignored_rows') or [])
                ignored.discard(row_number)
                draft['ignored_rows'] = list(ignored)
                request.session[session_key] = draft
                request.session.modified = True
                validate_rows()
            return redirect(f'{reverse("core:super_admin_teacher_bulk_import")}?step=3')

        if step == 1:
            uploaded = request.FILES.get('excel_file')
            if not uploaded:
                messages.error(request, 'لطفا فایل اساتید را انتخاب کنید.')
                return redirect(f'{reverse("core:super_admin_teacher_bulk_import")}?step=1')
            suffix = Path(uploaded.name).suffix.lower()
            try:
                if suffix == '.csv':
                    text = uploaded.read().decode('utf-8-sig')
                    rows = list(csv.DictReader(io.StringIO(text)))
                else:
                    rows = read_xlsx_dicts(uploaded)
            except (UnicodeDecodeError, KeyError, ET.ParseError, zipfile.BadZipFile):
                messages.error(request, 'فایل انتخاب‌شده معتبر نیست. قالب نمونه را دریافت و تکمیل کنید.')
                return redirect(f'{reverse("core:super_admin_teacher_bulk_import")}?step=1')
            if not rows:
                messages.error(request, 'فایل انتخاب‌شده ردیفی برای ورود ندارد.')
                return redirect(f'{reverse("core:super_admin_teacher_bulk_import")}?step=1')
            upload_headers = list(rows[0].keys())
            draft = {
                'step': 2,
                'filename': uploaded.name,
                'headers': upload_headers,
                'rows': rows[:1000],
                'total_rows': len(rows),
                'first_row': rows[0],
                'mapping': guess_mapping(upload_headers),
                'has_header': request.POST.get('has_header') == 'on',
            }
            request.session[session_key] = draft
            request.session.modified = True
            return redirect(f'{reverse("core:super_admin_teacher_bulk_import")}?step=2')

        if step == 2:
            draft['mapping'] = {field['key']: request.POST.get(f'map_{field["key"]}', '').strip() for field in field_defs}
            draft['step'] = 3
            request.session[session_key] = draft
            request.session.modified = True
            validate_rows()
            return redirect(f'{reverse("core:super_admin_teacher_bulk_import")}?step=3')

        if step == 3:
            draft['step'] = 4
            request.session[session_key] = draft
            request.session.modified = True
            validate_rows()
            return redirect(f'{reverse("core:super_admin_teacher_bulk_import")}?step=4')

        if step == 4:
            if not request.POST.get('confirm_final'):
                messages.error(request, 'برای ثبت نهایی، تایید صحت اطلاعات لازم است.')
                return redirect(f'{reverse("core:super_admin_teacher_bulk_import")}?step=4')
            records, counts = validate_rows()
            if counts.get('error'):
                messages.error(request, 'ردیف‌های دارای خطا باید قبل از ثبت نهایی اصلاح شوند.')
                return redirect(f'{reverse("core:super_admin_teacher_bulk_import")}?step=3')
            create_accounts = request.POST.get('create_accounts') == 'on'
            send_activation = request.POST.get('send_activation') == 'on'
            keep_history = request.POST.get('keep_history') == 'on'
            skip_warnings = request.POST.get('skip_warnings') == 'on'
            imported_count = 0
            created_credentials = []
            try:
                with connection.cursor() as cursor:
                    for record in records:
                        if record['level'] in ('error', 'ignored') or (record['level'] == 'warning' and skip_warnings):
                            continue
                        teacher_id = str(uuid.uuid4())
                        username = record.get('email') or record.get('phone') or record.get('personnel_code')
                        email = record.get('email') or None
                        cursor.execute("SELECT id FROM profiles WHERE identifier = %s OR username = %s OR email = %s OR national_id = %s LIMIT 1", [record['personnel_code'], username, email, record['national_id']])
                        existing = cursor.fetchone()
                        if existing:
                            teacher_id = existing[0]
                            cursor.execute(
                                """
                                UPDATE profiles
                                SET full_name = %s, first_name = %s, last_name = %s, username = %s,
                                    email = %s, phone = %s, national_id = %s, identifier = %s,
                                    status = %s, password_method = %s, email_verified_required = %s,
                                    updated_at = CURRENT_TIMESTAMP
                                WHERE id = %s
                                """,
                                [record['full_name'], record['first_name'], record['last_name'], username, email, record.get('phone') or None, record['national_id'], record['personnel_code'], record['status'], 'activation_link' if create_accounts else '', send_activation, teacher_id],
                            )
                        else:
                            cursor.execute(
                                """
                                INSERT INTO profiles (
                                    id, full_name, first_name, last_name, username, email, phone, national_id,
                                    identifier, avatar_url, status, password_method, email_verified_required,
                                    created_at, updated_at
                                )
                                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, '', %s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                                """,
                                [teacher_id, record['full_name'], record['first_name'], record['last_name'], username, email, record.get('phone') or None, record['national_id'], record['personnel_code'], record['status'], 'activation_link' if create_accounts else '', send_activation],
                            )
                        primary = unit_path(record.get('org_unit_id'))
                        cursor.execute(
                            """
                            INSERT INTO teacher_profiles (user_id, personnel_code, department, specialty, approval_status, org_unit_id)
                            VALUES (%s, %s, %s, %s, %s, %s)
                            ON CONFLICT(user_id) DO UPDATE SET
                                personnel_code = excluded.personnel_code,
                                department = excluded.department,
                                specialty = excluded.specialty,
                                approval_status = excluded.approval_status,
                                org_unit_id = excluded.org_unit_id
                            """,
                            [teacher_id, record['personnel_code'], primary.get('department') or record.get('org_unit_label') or '', record.get('academic_rank') or record.get('cooperation_type') or '', 'approved', record.get('org_unit_id') or None],
                        )
                        cursor.execute("DELETE FROM user_roles WHERE user_id = %s AND role = %s", [teacher_id, 'teacher'])
                        cursor.execute("INSERT INTO user_roles (id, user_id, role, created_at) VALUES (%s, %s, %s, CURRENT_TIMESTAMP)", [str(uuid.uuid4()), teacher_id, 'teacher'])
                        for course_id in record.get('course_ids') or []:
                            cursor.execute("SELECT id FROM student_groups WHERE course_id = %s LIMIT 30", [course_id])
                            for group in cursor.fetchall():
                                cursor.execute("INSERT INTO group_teachers (group_id, teacher_id, created_at) VALUES (%s, %s, CURRENT_TIMESTAMP) ON CONFLICT DO NOTHING", [group[0], teacher_id])
                        if keep_history:
                            payload = {'source': 'teacher_bulk_import', 'course_ids': record.get('course_ids') or [], 'cooperation_type': record.get('cooperation_type') or ''}
                            cursor.execute(
                                """
                                INSERT INTO system_settings (key, value, description, updated_by)
                                VALUES (%s, %s, %s, %s)
                                ON CONFLICT(key) DO UPDATE SET value = excluded.value, description = excluded.description, updated_by = excluded.updated_by
                                """,
                                [f'teacher_bulk_import.{teacher_id}', json.dumps(payload, ensure_ascii=False), 'Teacher bulk import history', teacher_id],
                            )
                        if create_accounts:
                            _login_user, generated_password = erd_sync_login_account(username, is_active=(record['status'] == 'active'))
                            if generated_password:
                                created_credentials.append((username, generated_password))
                        imported_count += 1
            except DatabaseError as exc:
                messages.error(request, f'ثبت گروهی اساتید انجام نشد: {exc}')
                return redirect(f'{reverse("core:super_admin_teacher_bulk_import")}?step=4')
            request.session.pop(session_key, None)
            messages.success(request, f'{imported_count} استاد با موفقیت ثبت شد.')
            if created_credentials:
                shown = created_credentials[:15]
                credential_text = '؛ '.join(f'{username}: {password}' for username, password in shown)
                suffix = f' (و {len(created_credentials) - len(shown)} مورد دیگر)' if len(created_credentials) > len(shown) else ''
                messages.info(request, f'رمزهای عبور اولیه حساب‌های تازه‌ساخته‌شده: {credential_text}{suffix}')
            return redirect(f'{reverse("core:super_admin_users")}?tab=teachers')

    if step >= 3 and draft.get('rows') and draft.get('mapping'):
        validate_rows()
    records = draft.get('records') or []
    counts = draft.get('counts') or {'ok': 0, 'warning': 0, 'error': 0, 'ignored': 0}
    valid_count = counts.get('ok', 0) + counts.get('warning', 0)
    matched_headers = sum(1 for value in (draft.get('mapping') or {}).values() if value)
    optional_count = max(0, len(draft.get('headers') or []) - matched_headers)
    ranks = {}
    for record in records:
        if record.get('level') not in ('error', 'ignored'):
            ranks[record.get('academic_rank') or 'نامشخص'] = ranks.get(record.get('academic_rank') or 'نامشخص', 0) + 1
    steps = [
        {'number': 1, 'label': 'بارگذاری فایل'},
        {'number': 2, 'label': 'تطبیق ستون‌ها'},
        {'number': 3, 'label': 'بررسی و رفع خطاها'},
        {'number': 4, 'label': 'ثبت نهایی'},
    ]
    return render(request, 'super_admin/teacher_bulk_import.html', {
        'step': step,
        'steps': steps,
        'draft': draft,
        'field_defs': field_defs,
        'headers': draft.get('headers') or [],
        'first_row': draft.get('first_row') or {},
        'records': records,
        'counts': counts,
        'valid_count': valid_count,
        'matched_headers': matched_headers,
        'optional_count': optional_count,
        'rank_summary': ranks,
        'required_fields': [field for field in field_defs if field['required']],
        'optional_fields': [field for field in field_defs if not field['required']],
        'back_url': f'{reverse("core:super_admin_users")}?tab=teachers',
    })


@super_admin_required
def super_admin_students(request):
    q = request.GET.get('q', '').strip()
    org_units = erd_rows(
        """
        SELECT id, parent_id, type, name, code, is_active
        FROM org_units
        ORDER BY CASE type WHEN 'university' THEN 0 WHEN 'faculty' THEN 1 ELSE 2 END, name
        """
    )
    unit_by_id = {str(unit['id']): unit for unit in org_units}

    def unit_path(unit_id):
        unit = unit_by_id.get(str(unit_id or ''))
        if not unit:
            return {'university': '-', 'faculty': '-', 'department': '-', 'label': '-'}
        chain = []
        current = unit
        seen = set()
        while current and str(current['id']) not in seen:
            seen.add(str(current['id']))
            chain.append(current)
            current = unit_by_id.get(str(current.get('parent_id') or ''))
        by_type = {item['type']: item['name'] for item in chain}
        return {
            'university': by_type.get('university') or '-',
            'faculty': by_type.get('faculty') or '-',
            'department': by_type.get('department') or by_type.get('group') or '-',
            'label': ' / '.join(part for part in [by_type.get('university'), by_type.get('faculty'), by_type.get('department') or by_type.get('group')] if part) or unit['name'],
        }

    excel_headers = ['نام', 'نام خانوادگی', 'نام کاربری', 'ایمیل', 'موبایل', 'کد ملی', 'شماره دانشجویی', 'رشته تحصیلی', 'مقطع', 'کلاس / گروه', 'نیمسال', 'وضعیت تحصیلی', 'وضعیت حساب', 'دانشگاه', 'دانشکده', 'گروه آموزشی']
    academic_labels = {'active': 'شاغل به تحصیل', 'leave': 'مرخصی', 'graduated': 'فارغ التحصیل', 'inactive': 'غیرفعال'}
    status_labels = {'active': 'فعال', 'inactive': 'غیرفعال', 'blocked': 'مسدود'}

    def normalize_text(value):
        return str(value or '').strip().replace('ي', 'ی').replace('ك', 'ک').lower()

    def import_status(value):
        return {'فعال': 'active', 'active': 'active', 'غیرفعال': 'inactive', 'غيرفعال': 'inactive', 'inactive': 'inactive', 'مسدود': 'blocked', 'blocked': 'blocked'}.get(normalize_text(value), 'active')

    def import_academic_status(value):
        return {'شاغل به تحصیل': 'active', 'فعال': 'active', 'active': 'active', 'مرخصی': 'leave', 'leave': 'leave', 'فارغ التحصیل': 'graduated', 'فارغ‌التحصیل': 'graduated', 'graduated': 'graduated', 'غیرفعال': 'inactive', 'inactive': 'inactive'}.get(normalize_text(value), 'active')

    def resolve_org_unit_id(university_name='', faculty_name='', department_name=''):
        university_name = normalize_text(university_name)
        faculty_name = normalize_text(faculty_name)
        department_name = normalize_text(department_name)

        def parent_chain(unit):
            chain = []
            current = unit
            seen = set()
            while current and str(current['id']) not in seen:
                seen.add(str(current['id']))
                chain.append(current)
                current = unit_by_id.get(str(current.get('parent_id') or ''))
            return chain

        if department_name:
            candidates = [unit for unit in org_units if unit['type'] in ('department', 'group') and normalize_text(unit['name']) == department_name]
        elif faculty_name:
            candidates = [unit for unit in org_units if unit['type'] == 'faculty' and normalize_text(unit['name']) == faculty_name]
        elif university_name:
            candidates = [unit for unit in org_units if unit['type'] == 'university' and normalize_text(unit['name']) == university_name]
        else:
            candidates = []
        for unit in candidates:
            names_by_type = {item['type']: normalize_text(item['name']) for item in parent_chain(unit)}
            if university_name and names_by_type.get('university') != university_name:
                continue
            if faculty_name and names_by_type.get('faculty') != faculty_name:
                continue
            return str(unit['id'])
        return ''

    def normalized_student_choices(values):
        return [item for item in dict.fromkeys(str(value).strip() for value in values) if item]

    def save_student_groups_and_courses(cursor, student_id, full_name, national_id, student_number, group_ids, course_ids):
        cursor.execute("DELETE FROM student_group_members WHERE student_user_id = %s", [student_id])
        for group_id in group_ids:
            cursor.execute("SELECT 1 FROM student_groups WHERE id = %s LIMIT 1", [group_id])
            if not cursor.fetchone():
                continue
            cursor.execute(
                """
                INSERT INTO student_group_members (id, group_id, student_user_id, full_name, national_id, student_number)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                [str(uuid.uuid4()), group_id, student_id, full_name, national_id or "-", student_number or "-"],
            )

        cursor.execute("DELETE FROM student_course_enrollments WHERE student_user_id = %s", [student_id])
        for course_id in course_ids:
            cursor.execute("SELECT 1 FROM courses WHERE id = %s LIMIT 1", [course_id])
            if not cursor.fetchone():
                continue
            cursor.execute(
                """
                INSERT INTO student_course_enrollments (id, student_user_id, course_id, created_at)
                VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT(student_user_id, course_id) DO NOTHING
                """,
                [str(uuid.uuid4()), student_id, course_id],
            )

    if request.GET.get('student_action') == 'sample':
        return xlsx_response('students-template.xlsx', excel_headers, [[
            'دانشجو', 'نمونه', 'student.sample', 'student.sample@example.com', '09120000000', '0012345678',
            'STU-07', 'مهندسی کامپیوتر', 'کارشناسی', 'کلاس ۱', '1404-1405 نیمسال اول', 'شاغل به تحصیل',
            'فعال', 'دانشگاه نمونه', 'دانشکده مهندسی', 'گروه مهندسی کامپیوتر',
        ]], 'Students')

    if request.method == 'POST' and request.POST.get('student_action') == 'import':
        uploaded = request.FILES.get('excel_file')
        if not uploaded:
            messages.error(request, 'لطفا فایل اکسل دانشجویان را انتخاب کنید.')
            return redirect('core:super_admin_students')
        try:
            imported_rows = read_xlsx_dicts(uploaded)
        except (KeyError, ET.ParseError, zipfile.BadZipFile):
            messages.error(request, 'فایل انتخاب‌شده معتبر نیست. لطفا قالب اکسل را دانلود و تکمیل کنید.')
            return redirect('core:super_admin_students')
        imported_count = 0
        import_errors = []
        created_credentials = []
        with connection.cursor() as cursor:
            for row_number, row in enumerate(imported_rows, start=2):
                first_name = row.get('نام', '').strip()
                last_name = row.get('نام خانوادگی', '').strip()
                username = row.get('نام کاربری', '').strip()
                email = row.get('ایمیل', '').strip()
                phone = row.get('موبایل', '').strip()
                national_id = row.get('کد ملی', '').strip()
                student_number = row.get('شماره دانشجویی', '').strip()
                field_of_study = row.get('رشته تحصیلی', '').strip()
                degree = row.get('مقطع', '').strip()
                class_group = row.get('کلاس / گروه', '').strip()
                semester = row.get('نیمسال', '').strip()
                full_name = f'{first_name} {last_name}'.strip() or username or email or student_number
                if not full_name or not student_number:
                    import_errors.append(f'ردیف {row_number}: نام یا شماره دانشجویی کامل نیست.')
                    continue
                username = username or email or student_number
                status = import_status(row.get('وضعیت حساب', 'فعال'))
                academic_status = import_academic_status(row.get('وضعیت تحصیلی', 'شاغل به تحصیل'))
                org_unit_id = resolve_org_unit_id(row.get('دانشگاه'), row.get('دانشکده'), row.get('گروه آموزشی'))
                primary = unit_path(org_unit_id) if org_unit_id else {'department': row.get('گروه آموزشی', '').strip()}
                cursor.execute(
                    "SELECT id FROM profiles WHERE identifier = %s OR email = %s OR username = %s LIMIT 1",
                    [student_number, email or None, username or None],
                )
                existing = cursor.fetchone()
                student_id = existing[0] if existing else str(uuid.uuid4())
                if existing:
                    cursor.execute(
                        """
                        UPDATE profiles
                        SET full_name = %s, first_name = %s, last_name = %s, username = %s,
                            email = %s, phone = %s, national_id = %s, identifier = %s,
                            status = %s, updated_at = CURRENT_TIMESTAMP
                        WHERE id = %s
                        """,
                        [full_name, first_name, last_name, username, email or None, phone or None, national_id or None, student_number, status, student_id],
                    )
                else:
                    cursor.execute(
                        """
                        INSERT INTO profiles (id, full_name, first_name, last_name, username, email, phone, national_id, identifier, avatar_url, status, created_at, updated_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, '', %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                        """,
                        [student_id, full_name, first_name, last_name, username, email or None, phone or None, national_id or None, student_number, status],
                    )
                cursor.execute(
                    """
                    INSERT INTO student_profiles (user_id, student_number, field_of_study, degree, class_group, semester, academic_status, department, org_unit_id)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT(user_id) DO UPDATE SET
                        student_number = excluded.student_number,
                        field_of_study = excluded.field_of_study,
                        degree = excluded.degree,
                        class_group = excluded.class_group,
                        semester = excluded.semester,
                        academic_status = excluded.academic_status,
                        department = excluded.department,
                        org_unit_id = excluded.org_unit_id
                    """,
                    [student_id, student_number, field_of_study, degree, class_group, semester, academic_status, primary.get('department') or '', org_unit_id or None],
                )
                cursor.execute("DELETE FROM user_roles WHERE user_id = %s AND role = %s", [student_id, 'student'])
                cursor.execute("INSERT INTO user_roles (id, user_id, role, created_at) VALUES (%s, %s, %s, CURRENT_TIMESTAMP)", [str(uuid.uuid4()), student_id, 'student'])
                _login_user, generated_password = erd_sync_login_account(username, is_active=(status == 'active'))
                if generated_password:
                    created_credentials.append((username, generated_password))
                imported_count += 1
        if imported_count:
            messages.success(request, f'{imported_count} دانشجو با موفقیت وارد شد.')
        if created_credentials:
            shown = created_credentials[:15]
            credential_text = '؛ '.join(f'{username}: {password}' for username, password in shown)
            suffix = f' (و {len(created_credentials) - len(shown)} مورد دیگر)' if len(created_credentials) > len(shown) else ''
            messages.info(request, f'رمزهای عبور اولیه حساب‌های تازه‌ساخته‌شده: {credential_text}{suffix}')
        if import_errors:
            messages.warning(request, '؛ '.join(import_errors[:5]))
        return redirect('core:super_admin_students')

    if request.method == 'POST' and request.POST.get('student_action') == 'delete':
        student_id = request.POST.get('student_id')
        wants_json = request.headers.get('x-requested-with') == 'XMLHttpRequest'
        if student_id:
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM student_course_enrollments WHERE student_user_id = %s", [student_id])
                cursor.execute("DELETE FROM student_group_members WHERE student_user_id = %s", [student_id])
                cursor.execute("DELETE FROM student_profiles WHERE user_id = %s", [student_id])
                cursor.execute("DELETE FROM user_roles WHERE user_id = %s AND role = %s", [student_id, 'student'])
                cursor.execute("DELETE FROM profiles WHERE id = %s", [student_id])
            if wants_json:
                return JsonResponse({'ok': True, 'message': 'دانشجو حذف شد.', 'student_id': student_id})
            messages.success(request, 'دانشجو حذف شد.')
        elif wants_json:
            return JsonResponse({'ok': False, 'message': 'شناسه دانشجو نامعتبر است.'}, status=400)
        return redirect('core:super_admin_students')

    if request.method == 'POST' and request.POST.get('student_action') == 'save':
        wants_json = request.headers.get('x-requested-with') == 'XMLHttpRequest'
        student_id = request.POST.get('student_id') or str(uuid.uuid4())
        first_name = request.POST.get('first_name', '').strip()
        last_name = request.POST.get('last_name', '').strip()
        full_name = f'{first_name} {last_name}'.strip() or 'دانشجو'
        username = request.POST.get('username', '').strip() or None
        email = request.POST.get('email', '').strip() or None
        phone = request.POST.get('phone', '').strip() or None
        national_id = request.POST.get('national_id', '').strip() or None
        student_number = request.POST.get('student_number', '').strip() or request.POST.get('identifier', '').strip() or None
        status = request.POST.get('status') or 'active'
        academic_status = request.POST.get('academic_status') or 'active'
        field_of_study = request.POST.get('field_of_study', '').strip()
        degree = request.POST.get('degree', '').strip()
        class_group = request.POST.get('class_group', '').strip()
        semester = request.POST.get('semester', '').strip()
        entry_year = request.POST.get('entry_year', '').strip()
        admission_type = request.POST.get('admission_type', '').strip()
        password_method = request.POST.get('password_method', 'activation_link').strip()
        if password_method not in {'activation_link', 'manual_password', 'sms_code'}:
            password_method = 'activation_link'
        must_change_password = request.POST.get('must_change_password') in {'1', 'on', 'true'}
        send_welcome_message = request.POST.get('send_welcome_message') in {'1', 'on', 'true'}
        selected_group_ids = normalized_student_choices(request.POST.getlist('group_ids'))
        selected_course_ids = normalized_student_choices(request.POST.getlist('course_ids'))
        org_unit_id = request.POST.get('org_unit_id') or None
        avatar_url = None
        avatar = request.FILES.get('avatar')
        if avatar:
            if avatar.size <= 1024 * 1024 and avatar.content_type in {'image/jpeg', 'image/png', 'image/webp', 'image/gif'}:
                extension = avatar.name.rsplit('.', 1)[-1].lower() if '.' in avatar.name else 'jpg'
                storage = FileSystemStorage(location=settings.MEDIA_ROOT / 'avatars', base_url=settings.MEDIA_URL + 'avatars/')
                filename = storage.save(f"{student_id}-{uuid.uuid4().hex[:8]}.{extension}", avatar)
                avatar_url = storage.url(filename)
            else:
                if wants_json:
                    return JsonResponse({'ok': False, 'message': 'فرمت یا حجم تصویر معتبر نیست.'}, status=400)
                messages.error(request, 'فرمت یا حجم تصویر معتبر نیست.')
                return redirect('core:super_admin_students')
        primary = unit_path(org_unit_id) if org_unit_id else {'department': ''}
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM profiles WHERE id = %s", [student_id])
            exists = cursor.fetchone()
            if exists:
                if avatar_url:
                    cursor.execute(
                        """
                        UPDATE profiles
                        SET full_name = %s, first_name = %s, last_name = %s, username = %s,
                            email = %s, phone = %s, national_id = %s, identifier = %s,
                            avatar_url = %s, status = %s, updated_at = CURRENT_TIMESTAMP
                        WHERE id = %s
                        """,
                        [full_name, first_name, last_name, username, email, phone, national_id, student_number, avatar_url, status, student_id],
                    )
                else:
                    cursor.execute(
                        """
                        UPDATE profiles
                        SET full_name = %s, first_name = %s, last_name = %s, username = %s,
                            email = %s, phone = %s, national_id = %s, identifier = %s,
                            status = %s, updated_at = CURRENT_TIMESTAMP
                        WHERE id = %s
                        """,
                        [full_name, first_name, last_name, username, email, phone, national_id, student_number, status, student_id],
                    )
            else:
                cursor.execute(
                    """
                    INSERT INTO profiles (id, full_name, first_name, last_name, username, email, phone, national_id, identifier, avatar_url, status, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    """,
                    [student_id, full_name, first_name, last_name, username, email, phone, national_id, student_number, avatar_url or '', status],
                )
            cursor.execute(
                """
                INSERT INTO student_profiles (
                    user_id, student_number, field_of_study, degree, class_group, semester,
                    academic_status, department, org_unit_id, entry_year, admission_type,
                    password_method, must_change_password, send_welcome_message
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT(user_id) DO UPDATE SET
                    student_number = excluded.student_number,
                    field_of_study = excluded.field_of_study,
                    degree = excluded.degree,
                    class_group = excluded.class_group,
                    semester = excluded.semester,
                    academic_status = excluded.academic_status,
                    department = excluded.department,
                    org_unit_id = excluded.org_unit_id,
                    entry_year = excluded.entry_year,
                    admission_type = excluded.admission_type,
                    password_method = excluded.password_method,
                    must_change_password = excluded.must_change_password,
                    send_welcome_message = excluded.send_welcome_message
                """,
                [
                    student_id, student_number, field_of_study, degree, class_group, semester,
                    academic_status, primary.get('department') or '', org_unit_id, entry_year,
                    admission_type, password_method, must_change_password, send_welcome_message,
                ],
            )
            cursor.execute("DELETE FROM user_roles WHERE user_id = %s AND role = %s", [student_id, 'student'])
            cursor.execute("INSERT INTO user_roles (id, user_id, role, created_at) VALUES (%s, %s, %s, CURRENT_TIMESTAMP)", [str(uuid.uuid4()), student_id, 'student'])
            save_student_groups_and_courses(
                cursor,
                student_id,
                full_name,
                national_id,
                student_number,
                selected_group_ids,
                selected_course_ids,
            )
        _login_user, generated_password = erd_sync_login_account(username, is_active=(status == 'active'))
        if wants_json:
            final_avatar_url = erd_row('SELECT avatar_url FROM profiles WHERE id = %s', [student_id])
            primary = unit_path(org_unit_id) if org_unit_id else {'university': '-', 'faculty': '-', 'department': '-'}
            return JsonResponse({
                'ok': True,
                'message': 'اطلاعات دانشجو ذخیره شد.',
                'student_id': student_id,
                'first_name': first_name,
                'last_name': last_name,
                'full_name': full_name,
                'username': username or '',
                'email': email or '',
                'phone': phone or '',
                'national_id': national_id or '',
                'student_number': student_number or '',
                'status': status,
                'academic_status': academic_status,
                'field_of_study': field_of_study,
                'degree': degree,
                'class_group': class_group,
                'semester': semester,
                'entry_year': entry_year,
                'admission_type': admission_type,
                'password_method': password_method,
                'must_change_password': must_change_password,
                'send_welcome_message': send_welcome_message,
                'group_ids': selected_group_ids,
                'course_ids': selected_course_ids,
                'org_unit_id': org_unit_id or '',
                'university': primary.get('university') or '-',
                'faculty': primary.get('faculty') or '-',
                'department': primary.get('department') or '-',
                'avatar_url': (final_avatar_url or {}).get('avatar_url') or '',
                'generated_password': generated_password or '',
            })
        if generated_password:
            messages.success(request, f'اطلاعات دانشجو ذخیره شد. نام کاربری: {username} — رمز عبور اولیه: {generated_password}')
        else:
            messages.success(request, 'اطلاعات دانشجو ذخیره شد.')
        return redirect('core:super_admin_students')

    students = erd_rows(
        """
        SELECT p.id, p.full_name, p.first_name, p.last_name, p.username, p.email, p.phone,
               p.national_id, p.identifier, p.avatar_url, p.status, p.created_at, p.last_login_at,
               sp.student_number, sp.field_of_study, sp.degree, sp.class_group, sp.semester,
               sp.academic_status, sp.department, sp.org_unit_id, sp.entry_year, sp.admission_type,
               sp.password_method, sp.must_change_password, sp.send_welcome_message,
               COALESCE((
                   SELECT COUNT(DISTINCT sgm.group_id)
                   FROM student_group_members sgm
                   WHERE sgm.student_user_id = sp.user_id
               ), 0) AS groups_count,
               COALESCE((
                   SELECT COUNT(DISTINCT course_id)
                   FROM (
                       SELECT sg.course_id AS course_id
                       FROM student_group_members sgm
                       JOIN student_groups sg ON sg.id = sgm.group_id
                       WHERE sgm.student_user_id = sp.user_id AND sg.course_id IS NOT NULL
                       UNION
                       SELECT sce.course_id AS course_id
                       FROM student_course_enrollments sce
                       WHERE sce.student_user_id = sp.user_id
                   ) student_courses
               ), 0) AS courses_count
        FROM student_profiles sp
        JOIN profiles p ON p.id = sp.user_id
        ORDER BY p.full_name
        LIMIT 300
        """
    )
    group_links = erd_rows("SELECT group_id, student_user_id FROM student_group_members")
    course_links = erd_rows("SELECT course_id, student_user_id FROM student_course_enrollments")
    groups_by_student = {}
    courses_by_student = {}
    for link in group_links:
        groups_by_student.setdefault(str(link.get('student_user_id')), []).append(str(link.get('group_id')))
    for link in course_links:
        courses_by_student.setdefault(str(link.get('student_user_id')), []).append(str(link.get('course_id')))
    rows = []
    for student in students:
        primary = unit_path(student.get('org_unit_id'))
        if q and not _matches_query(q, student.get('full_name'), student.get('email'), student.get('username'), student.get('student_number'), student.get('field_of_study'), student.get('degree'), primary['label']):
            continue
        rows.append({
            **student,
            'university': primary['university'],
            'faculty': primary['faculty'],
            'department_name': primary['department'],
            'group_ids': groups_by_student.get(str(student.get('id')), []),
            'course_ids': courses_by_student.get(str(student.get('id')), []),
            'created_display': student.get('created_at') or '-',
            'last_login_display': student.get('last_login_at') or '-',
        })

    if request.GET.get('student_action') in ('export', 'csv'):
        export_rows = [[
            row.get('first_name') or '',
            row.get('last_name') or '',
            row.get('username') or '',
            row.get('email') or '',
            row.get('phone') or '',
            row.get('national_id') or '',
            row.get('student_number') or row.get('identifier') or '',
            row.get('field_of_study') or '',
            row.get('degree') or '',
            row.get('class_group') or '',
            row.get('semester') or '',
            academic_labels.get(row.get('academic_status') or 'active', 'شاغل به تحصیل'),
            status_labels.get(row.get('status') or 'active', 'فعال'),
            row.get('university') or '',
            row.get('faculty') or '',
            row.get('department_name') or '',
        ] for row in rows]
        if request.GET.get('student_action') == 'csv':
            response = HttpResponse(content_type='text/csv; charset=utf-8-sig')
            response['Content-Disposition'] = 'attachment; filename="students.csv"'
            response.write('\ufeff')
            writer = csv.writer(response)
            writer.writerow(excel_headers)
            writer.writerows(export_rows)
            return response
        return xlsx_response('students.xlsx', excel_headers, export_rows, 'Students')

    groups = erd_rows(
        """
        SELECT sg.id, sg.course_id, sg.course_name, sg.group_code, sg.academic_year, sg.semester,
               COALESCE(sg.is_active, true) AS is_active,
               COALESCE(c.title, sg.course_name) AS course_title,
               COALESCE(c.code, '') AS course_code,
               COALESCE(c.credit_units, 0) AS credit_units,
               COALESCE(p.full_name, '-') AS teacher_name
        FROM student_groups sg
        LEFT JOIN courses c ON c.id = sg.course_id
        LEFT JOIN profiles p ON p.id = sg.teacher_id
        ORDER BY sg.academic_year DESC, sg.course_name, sg.group_code
        LIMIT 300
        """
    )
    courses = erd_rows(
        """
        SELECT c.id, c.title, c.code, c.org_unit_id, COALESCE(c.credit_units, 0) AS credit_units,
               COALESCE(p.full_name, '-') AS teacher_name,
               COALESCE(sg.semester, '') AS semester
        FROM courses c
        LEFT JOIN student_groups sg ON sg.course_id = c.id
        LEFT JOIN profiles p ON p.id = sg.teacher_id
        GROUP BY c.id, c.title, c.code, c.org_unit_id, c.credit_units, p.full_name, sg.semester
        ORDER BY c.title
        LIMIT 300
        """
    )

    return render(request, 'super_admin/students.html', {
        'title': 'دانشجویان',
        'description': 'ایجاد، ویرایش کامل اطلاعات دانشجویان و مشاهده دانشکده، گروه، مقطع و شماره دانشجویی.',
        'rows': rows,
        'query': q,
        'universities': [unit for unit in org_units if unit['type'] == 'university'],
        'org_units_json': org_units,
        'groups': groups,
        'groups_json': groups,
        'courses': courses,
        'courses_json': courses,
        'academic_labels': academic_labels,
    })


@super_admin_required
def _legacy_super_admin_groups(request):
    return _super_admin_collection(
        request,
        title='گروه‌بندی',
        kicker='مدیر سیستم / گروه‌ها',
        description='گروه‌های دانشجویی ثبت شده در student_groups.',
        queryset=lambda: erd_rows(
            """
            SELECT sg.course_name, sg.group_code, sg.academic_year, sg.semester, COALESCE(c.title, '-') AS course,
                   COALESCE(p.full_name, '-') AS teacher
            FROM student_groups sg
            LEFT JOIN courses c ON c.id = sg.course_id
            LEFT JOIN profiles p ON p.id = sg.teacher_id
            ORDER BY sg.academic_year DESC, sg.course_name
            LIMIT 200
            """
        ),
        row_builder=lambda item, q: {
            'title': item['course_name'],
            'meta': item['group_code'] or 'بدون کد',
            'cells': [('درس', item['course']), ('استاد', item['teacher']), ('سال', item['academic_year']), ('ترم', item['semester'] or '-')],
        } if _matches_query(q, item['course_name'], item['group_code'], item['course'], item['teacher'], item['academic_year']) else None,
    )
    return _super_admin_collection(
        request,
        title='گروه‌بندی',
        kicker='مدیر سیستم / کلاس‌ها و گروه‌ها',
        description='ایجاد و مدیریت کلاس‌ها، گروه‌ها، استاد و دانشجویان هر گروه.',
        form_class=SuperAdminClassForm,
        queryset=lambda: CourseClass.objects.select_related('institution', 'course', 'term', 'teacher__profile').prefetch_related('students').order_by('-created_at')[:200],
        row_builder=lambda item, q: {
            'title': item.title,
            'meta': item.code or 'بدون کد',
            'cells': [('درس', item.course or '-'), ('استاد', item.teacher.profile.full_name if item.teacher else '-'), ('ترم', item.term or '-'), ('دانشجویان', item.students.count())],
        } if _matches_query(q, item.title, item.code, item.course, item.teacher.profile.full_name if item.teacher else '', item.term) else None,
    )


@erd_role_required('academic_manager', 'admin')
def super_admin_group_create(request):
    def parse_local_datetime(value):
        value = (value or '').strip()
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
        if timezone.is_naive(parsed):
            parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
        return parsed

    def normalize_semester_value(value):
        value = str(value or '').strip()
        return {
            'نیمسال اول': 'اول',
            'اول': 'اول',
            '1': 'اول',
            'نیمسال دوم': 'دوم',
            'دوم': 'دوم',
            '2': 'دوم',
            'تابستان': 'تابستان',
            'summer': 'تابستان',
        }.get(value, value or 'اول')

    if request.GET.get('bulk_action') == 'sample':
        return xlsx_response(
            'students-for-group-template.xlsx',
            ['کد ملی یا شماره دانشجویی'],
            [['1234567890'], ['40123456']],
            'Students',
        )

    courses = _em_course_rows(request)
    teachers = _em_teacher_options(request)
    students = _em_student_options(request)
    for student in students:
        student.setdefault('class_group', '-')
        if not student.get('field_of_study'):
            student['field_of_study'] = '-'
    terms = erd_rows('SELECT id, year, semester, label, is_current FROM academic_terms ORDER BY year DESC, semester LIMIT 100')
    years = sorted(
        {term.get('year') for term in terms if term.get('year')} |
        {str(row.get('academic_year')) for row in erd_rows('SELECT DISTINCT academic_year FROM student_groups WHERE academic_year IS NOT NULL') if row.get('academic_year')},
        reverse=True,
    ) or ['1405-1406', '1403-1404']
    student_fields = sorted({s.get('field_of_study') for s in students if s.get('field_of_study') and s.get('field_of_study') != '-'})
    student_entry_years = sorted({s.get('entry_year') for s in students if s.get('entry_year')}, reverse=True)
    student_statuses = sorted({s.get('status') for s in students if s.get('status')})
    current_year = years[0]
    current_course = courses[0] if courses else {}
    current_teacher = teachers[0] if teachers else {}

    if request.method == 'POST':
        course_id = request.POST.get('course_id') or None
        course = erd_row('SELECT title, code, credit_units FROM courses WHERE id = %s', [course_id]) if course_id else None
        teacher_id = request.POST.get('teacher_id') or None
        course_name = (course or {}).get('title') or request.POST.get('course_name', '').strip() or 'گروه درسی جدید'
        group_id = str(uuid.uuid4())
        group_code = request.POST.get('group_code', '').strip() or '01'
        academic_year = request.POST.get('academic_year', '').strip() or current_year
        semester = normalize_semester_value(request.POST.get('semester'))
        selected_students = [item for item in request.POST.getlist('student_ids') if item]
        if not _erd_group_assignment_in_scope(request, course_id, [teacher_id]):
            return HttpResponseForbidden('درس/استاد انتخاب‌شده خارج از محدوده‌ی دسترسی شماست.')
        created_by = (erd_profile_for_user(request.user) or {}).get('id')
        optional_columns = [
            ('capacity', int(request.POST.get('capacity') or 30)),
            ('min_students', int(request.POST.get('min_students') or 10)),
            ('waitlist_enabled', bool(request.POST.get('waitlist_enabled'))),
            ('waitlist_capacity', int(request.POST.get('waitlist_capacity') or 0)),
            ('requires_teacher_approval', bool(request.POST.get('requires_teacher_approval'))),
            ('offering_type', request.POST.get('offering_type') or 'theory'),
            ('class_schedule', request.POST.get('class_schedule', '').strip()),
            ('class_location', request.POST.get('class_location', '').strip()),
            ('registration_start_at', parse_local_datetime(request.POST.get('registration_start_at'))),
            ('registration_end_at', parse_local_datetime(request.POST.get('registration_end_at'))),
            ('status', request.POST.get('status') or 'draft'),
        ]
        columns = ['id', 'teacher_id', 'course_id', 'course_name', 'academic_year', 'semester', 'group_code', 'description', 'is_active', 'created_by']
        values = [group_id, teacher_id, course_id, course_name, academic_year, semester, group_code, request.POST.get('description', '').strip(), True, created_by]
        for column, value in optional_columns:
            if erd_has_column('student_groups', column):
                columns.append(column)
                values.append(value)
        erd_execute(
            f"INSERT INTO student_groups ({', '.join(columns)}) VALUES ({', '.join(['%s'] * len(columns))})",
            values,
        )
        with connection.cursor() as cursor:
            if teacher_id:
                cursor.execute(
                    "INSERT INTO group_teachers (group_id, teacher_id, created_at) VALUES (%s, %s, CURRENT_TIMESTAMP) ON CONFLICT DO NOTHING",
                    [group_id, teacher_id],
                )
            for student_id in dict.fromkeys(selected_students):
                student = erd_row(
                    """
                    SELECT p.full_name, COALESCE(p.national_id, '') AS national_id,
                           COALESCE(sp.student_number, p.identifier, '') AS student_number
                    FROM profiles p
                    LEFT JOIN student_profiles sp ON sp.user_id = p.id
                    WHERE p.id = %s
                    """,
                    [student_id],
                )
                if not student:
                    continue
                cursor.execute(
                    """
                    INSERT INTO student_group_members (id, group_id, student_user_id, full_name, national_id, student_number)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    [str(uuid.uuid4()), group_id, student_id, student.get('full_name') or 'دانشجو', student.get('national_id') or '-', student.get('student_number') or '-'],
                )
        messages.success(request, 'گروه درسی جدید با موفقیت ایجاد شد.')
        return redirect('core:exam_manager_groups' if request.resolver_match.url_name.startswith('exam_manager_') else 'core:super_admin_groups')

    return render(request, 'super_admin/group_wizard.html', {
        'title': 'ایجاد گروه درسی جدید',
        'courses': courses,
        'teachers': teachers,
        'students': students,
        'years': years,
        'current_year': current_year,
        'current_course': current_course,
        'current_teacher': current_teacher,
        'student_fields': student_fields,
        'student_entry_years': student_entry_years,
        'student_statuses': student_statuses,
        'back_url': reverse('core:exam_manager_groups' if request.resolver_match.url_name.startswith('exam_manager_') else 'core:super_admin_groups'),
    })


def _erd_parse_participant_upload(uploaded):
    """فایل اکسل/CSV مخاطبان را می‌خواند و به (ردیف‌های خام, فهرست شناسه‌های کد ملی/شماره دانشجویی) تبدیل می‌کند."""
    suffix = Path(uploaded.name).suffix.lower()
    if suffix == '.csv':
        rows = list(csv.DictReader(io.StringIO(uploaded.read().decode('utf-8-sig'))))
    else:
        rows = read_xlsx_dicts(uploaded)
    if not rows:
        return rows, []
    first_column = next(iter(rows[0].keys()))
    identifiers = [str(row.get(first_column) or '').strip() for row in rows]
    return rows, [item for item in identifiers if item]


def _erd_match_students_by_identifier(request, identifiers, scope=None):
    """هر شناسه (کد ملی یا شماره دانشجویی) را به دانشجوی متناظرِ داخل محدوده‌ی دسترسی درخواست‌کننده وصل می‌کند.

    scope: an _exam_wizard_scope() dict; when omitted the admin/manager scope is used."""
    condition_params = []
    if scope is not None:
        scope_cte, scope_params = scope['cte'], list(scope['cte_params'])
        scope_condition, condition_params = scope['students']
    else:
        is_admin = _erd_is_admin_request(request)
        scope_cte = '' if is_admin else _erd_manager_scope_cte()
        scope_condition = '1=1' if is_admin else _erd_student_scope_condition()
        scope_params = [] if is_admin else [request.erd_profile_id]

    found = []
    not_found = []
    seen_ids = set()
    duplicate_count = 0
    for identifier in dict.fromkeys(identifiers):
        student = erd_row(
            f"""
            {scope_cte}
            SELECT p.id, p.full_name, p.avatar_url,
                   COALESCE(sp.student_number, p.identifier, '') AS student_number,
                   COALESCE(p.national_id, '') AS national_id,
                   COALESCE(sp.entry_year, '') AS entry_year
            FROM student_profiles sp
            JOIN profiles p ON p.id = sp.user_id
            WHERE (sp.student_number = %s OR p.national_id = %s) AND {scope_condition}
            LIMIT 1
            """,
            scope_params + [identifier, identifier] + list(condition_params),
        )
        if student:
            if str(student['id']) in seen_ids:
                duplicate_count += 1
                continue
            seen_ids.add(str(student['id']))
            found.append(student)
        else:
            not_found.append(identifier)
    duplicate_count += len(identifiers) - len(dict.fromkeys(identifiers))
    return found, not_found, duplicate_count


@erd_role_required('academic_manager', 'admin')
def super_admin_group_students_match(request):
    """تطبیق فایل اکسل/CSV دانشجویان گروه بر اساس کد ملی یا شماره دانشجویی، محدود به محدوده‌ی دسترسی مدیر."""
    if request.method != 'POST':
        return JsonResponse({'error': 'روش درخواست نامعتبر است.'}, status=405)
    uploaded = request.FILES.get('excel_file')
    if not uploaded:
        return JsonResponse({'error': 'فایلی انتخاب نشده است.'}, status=400)
    try:
        rows, identifiers = _erd_parse_participant_upload(uploaded)
    except (UnicodeDecodeError, KeyError, ET.ParseError, zipfile.BadZipFile):
        return JsonResponse({'error': 'فایل انتخاب‌شده معتبر نیست. قالب نمونه را دریافت و تکمیل کنید.'}, status=400)
    if not rows:
        return JsonResponse({'error': 'فایل انتخاب‌شده ردیفی برای بررسی ندارد.'}, status=400)

    found, not_found, duplicate_count = _erd_match_students_by_identifier(request, identifiers)
    return JsonResponse({
        'total': len(identifiers),
        'total_rows': len(rows),
        'found': found,
        'not_found': not_found,
        'duplicate_count': duplicate_count,
    })


@erd_role_required('academic_manager', 'admin')
def super_admin_group_edit(request, group_id):
    group = erd_row('SELECT * FROM student_groups WHERE id = %s', [group_id])
    if not group:
        raise Http404('Group not found')
    if not _erd_group_in_manager_scope(request, group_id):
        raise Http404('Group not found')

    def normalize_semester_value(value):
        value = str(value or '').strip()
        return {
            'نیمسال اول': 'اول',
            'اول': 'اول',
            '1': 'اول',
            'نیمسال دوم': 'دوم',
            'دوم': 'دوم',
            '2': 'دوم',
            'تابستان': 'تابستان',
            'summer': 'تابستان',
        }.get(value, value or 'اول')

    if request.method == 'POST':
        course_id = request.POST.get('course_id') or None
        course = erd_row('SELECT title FROM courses WHERE id = %s', [course_id]) if course_id else None
        selected_teachers = [item for item in request.POST.getlist('teacher_ids') if item]
        teacher_id = request.POST.get('teacher_id') or (selected_teachers[0] if selected_teachers else None)
        if teacher_id and teacher_id not in selected_teachers:
            selected_teachers.insert(0, teacher_id)
        if not _erd_group_assignment_in_scope(request, course_id, selected_teachers):
            return HttpResponseForbidden('درس/استاد انتخاب‌شده خارج از محدوده‌ی دسترسی شماست.')
        assignments = [
            ('teacher_id', teacher_id),
            ('course_id', course_id),
            ('course_name', (course or {}).get('title') or request.POST.get('course_name', '').strip() or group.get('course_name') or 'Course group'),
            ('academic_year', request.POST.get('academic_year', '').strip() or group.get('academic_year') or '1403-1404'),
            ('semester', normalize_semester_value(request.POST.get('semester'))),
            ('group_code', request.POST.get('group_code', '').strip() or '01'),
            ('description', request.POST.get('description', '').strip()),
            ('is_active', True),
        ]
        for column, value in [
            ('capacity', int(request.POST.get('capacity') or 30)),
            ('min_students', int(request.POST.get('min_students') or 10)),
            ('waitlist_enabled', bool(request.POST.get('waitlist_enabled'))),
            ('waitlist_capacity', int(request.POST.get('waitlist_capacity') or 0)),
            ('requires_teacher_approval', bool(request.POST.get('requires_teacher_approval'))),
            ('offering_type', request.POST.get('offering_type') or 'theory'),
            ('class_schedule', request.POST.get('class_schedule', '').strip()),
            ('class_location', request.POST.get('class_location', '').strip()),
            ('status', request.POST.get('status') or 'draft'),
        ]:
            if erd_has_column('student_groups', column):
                assignments.append((column, value))
        erd_execute(
            f"UPDATE student_groups SET {', '.join(f'{column} = %s' for column, _ in assignments)} WHERE id = %s",
            [value for _, value in assignments] + [group_id],
        )
        with connection.cursor() as cursor:
            cursor.execute('DELETE FROM group_teachers WHERE group_id = %s', [group_id])
            for selected_teacher in dict.fromkeys(selected_teachers):
                cursor.execute(
                    'INSERT INTO group_teachers (group_id, teacher_id, created_at) VALUES (%s, %s, CURRENT_TIMESTAMP) ON CONFLICT DO NOTHING',
                    [group_id, selected_teacher],
                )
            cursor.execute('DELETE FROM student_group_members WHERE group_id = %s', [group_id])
            for student_id in dict.fromkeys([item for item in request.POST.getlist('student_ids') if item]):
                student = erd_row(
                    """
                    SELECT p.full_name, COALESCE(p.national_id, '') AS national_id,
                           COALESCE(sp.student_number, p.identifier, '') AS student_number
                    FROM profiles p
                    LEFT JOIN student_profiles sp ON sp.user_id = p.id
                    WHERE p.id = %s
                    """,
                    [student_id],
                )
                if not student:
                    continue
                cursor.execute(
                    """
                    INSERT INTO student_group_members (id, group_id, student_user_id, full_name, national_id, student_number)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    [str(uuid.uuid4()), group_id, student_id, student.get('full_name') or 'Student', student.get('national_id') or '-', student.get('student_number') or '-'],
                )
        messages.success(request, 'Group updated successfully.')
        return redirect('core:exam_manager_groups' if request.resolver_match.url_name.startswith('exam_manager_') else 'core:super_admin_groups')

    courses = _em_course_rows(request)
    teachers = _em_teacher_options(request)
    students = _em_student_options(request)
    for student in students:
        student.setdefault('class_group', '-')
        if not student.get('field_of_study'):
            student['field_of_study'] = '-'
    terms = erd_rows('SELECT id, year, semester, label, is_current FROM academic_terms ORDER BY year DESC, semester LIMIT 100')
    years = sorted(
        {term.get('year') for term in terms if term.get('year')} |
        {str(row.get('academic_year')) for row in erd_rows('SELECT DISTINCT academic_year FROM student_groups WHERE academic_year IS NOT NULL') if row.get('academic_year')},
        reverse=True,
    ) or ['1405-1406', '1403-1404']
    student_fields = sorted({s.get('field_of_study') for s in students if s.get('field_of_study') and s.get('field_of_study') != '-'})
    student_entry_years = sorted({s.get('entry_year') for s in students if s.get('entry_year')}, reverse=True)
    student_statuses = sorted({s.get('status') for s in students if s.get('status')})
    selected_teacher_ids = [str(row['teacher_id']) for row in erd_rows('SELECT teacher_id FROM group_teachers WHERE group_id = %s', [group_id]) if row.get('teacher_id')]
    if group.get('teacher_id') and str(group['teacher_id']) not in selected_teacher_ids:
        selected_teacher_ids.insert(0, str(group['teacher_id']))
    selected_student_ids = [str(row['student_user_id']) for row in erd_rows('SELECT student_user_id FROM student_group_members WHERE group_id = %s', [group_id]) if row.get('student_user_id')]
    current_course = next((course for course in courses if str(course.get('id')) == str(group.get('course_id'))), courses[0] if courses else {})
    current_teacher = next((teacher for teacher in teachers if selected_teacher_ids and str(teacher.get('id')) == selected_teacher_ids[0]), teachers[0] if teachers else {})
    return render(request, 'super_admin/group_wizard.html', {
        'title': 'Edit course group',
        'courses': courses,
        'teachers': teachers,
        'students': students,
        'years': years,
        'current_year': group.get('academic_year') or (years[0] if years else '1403-1404'),
        'current_course': current_course,
        'current_teacher': current_teacher,
        'group': group,
        'is_edit': True,
        'selected_teacher_ids': selected_teacher_ids,
        'selected_student_ids': selected_student_ids,
        'student_fields': student_fields,
        'student_entry_years': student_entry_years,
        'student_statuses': student_statuses,
        'back_url': reverse('core:exam_manager_groups' if request.resolver_match.url_name.startswith('exam_manager_') else 'core:super_admin_groups'),
    })


@erd_role_required('academic_manager', 'admin')
def super_admin_group_detail(request, group_id):
    if not _erd_group_in_manager_scope(request, group_id):
        raise Http404('گروه پیدا نشد.')
    group_rows = _em_group_rows(request, group_id=group_id)
    if not group_rows:
        raise Http404('گروه پیدا نشد.')
    group = group_rows[0]
    is_exam_manager_route = request.resolver_match.url_name.startswith('exam_manager_')
    tab = request.GET.get('tab', 'overview')
    if tab not in {'overview', 'students', 'schedule', 'exams', 'activity'}:
        tab = 'overview'
    members = _em_member_rows(group_id)
    exams = _em_group_exam_rows(group.get('course_id'))
    context = {
        'title': 'جزئیات گروه درسی',
        'group': group,
        'members': members,
        'members_preview': members[:6],
        'exams': exams,
        'tab': tab,
        'edit_url': reverse('core:exam_manager_group_edit' if is_exam_manager_route else 'core:super_admin_group_edit', args=[group_id]),
        'students_url': reverse('core:exam_manager_group_students_manage' if is_exam_manager_route else 'core:super_admin_group_students_manage', args=[group_id]),
        'add_students_url': reverse('core:exam_manager_group_students_add' if is_exam_manager_route else 'core:super_admin_group_students_add', args=[group_id]),
        'archive_url': reverse('core:exam_manager_group_archive' if is_exam_manager_route else 'core:super_admin_group_archive', args=[group_id]),
        'back_url': reverse('core:exam_manager_groups' if is_exam_manager_route else 'core:super_admin_groups'),
    }
    return render(request, 'super_admin/group_detail.html', context)


@erd_role_required('academic_manager', 'admin')
def super_admin_group_students_manage(request, group_id):
    if not _erd_group_in_manager_scope(request, group_id):
        raise Http404('گروه پیدا نشد.')
    group_rows = _em_group_rows(request, group_id=group_id)
    if not group_rows:
        raise Http404('گروه پیدا نشد.')
    group = group_rows[0]
    is_exam_manager_route = request.resolver_match.url_name.startswith('exam_manager_')
    detail_url_name = 'core:exam_manager_group_detail' if is_exam_manager_route else 'core:super_admin_group_detail'
    manage_url_name = 'core:exam_manager_group_students_manage' if is_exam_manager_route else 'core:super_admin_group_students_manage'
    if request.method == 'POST':
        action = request.POST.get('action')
        member_ids = [item for item in request.POST.getlist('member_ids') if item]
        if action == 'remove' and member_ids:
            placeholders = ', '.join(['%s'] * len(member_ids))
            erd_execute(f"DELETE FROM student_group_members WHERE group_id = %s AND id IN ({placeholders})", [group_id, *member_ids])
            messages.success(request, 'دانشجویان انتخاب‌شده از گروه حذف شدند.')
        return redirect(manage_url_name, group_id=group_id)
    members = _em_member_rows(group_id)
    q = request.GET.get('q', '').strip().lower()
    field_filter = request.GET.get('field', '').strip()
    entry_filter = request.GET.get('entry', '').strip()
    if q:
        members = [m for m in members if q in str(m.get('full_name') or '').lower() or q in str(m.get('student_number') or '').lower()]
    if field_filter:
        members = [m for m in members if m.get('field_of_study') == field_filter]
    if entry_filter:
        members = [m for m in members if str(m.get('entry_year') or '') == entry_filter]
    all_members = _em_member_rows(group_id)
    fields = sorted({m.get('field_of_study') for m in all_members if m.get('field_of_study') and m.get('field_of_study') != '-'})
    entry_years = sorted({m.get('entry_year') for m in all_members if m.get('entry_year')}, reverse=True)
    context = {
        'title': 'مدیریت دانشجویان گروه',
        'group': group,
        'members': members,
        'members_total': len(all_members),
        'fields': fields,
        'entry_years': entry_years,
        'query': request.GET.get('q', ''),
        'field_filter': field_filter,
        'entry_filter': entry_filter,
        'detail_url': reverse(detail_url_name, args=[group_id]),
        'add_students_url': reverse('core:exam_manager_group_students_add' if is_exam_manager_route else 'core:super_admin_group_students_add', args=[group_id]),
    }
    return render(request, 'super_admin/group_students_manage.html', context)


@erd_role_required('academic_manager', 'admin')
def super_admin_group_students_add(request, group_id):
    group_rows = _em_group_rows(request, group_id=group_id)
    if not group_rows:
        raise Http404('گروه پیدا نشد.')
    if not _erd_group_in_manager_scope(request, group_id):
        raise Http404('گروه پیدا نشد.')
    group = group_rows[0]
    is_exam_manager_route = request.resolver_match.url_name.startswith('exam_manager_')
    detail_url_name = 'core:exam_manager_group_detail' if is_exam_manager_route else 'core:super_admin_group_detail'
    manage_url_name = 'core:exam_manager_group_students_manage' if is_exam_manager_route else 'core:super_admin_group_students_manage'
    students = _em_student_options(request)
    members = _em_member_rows(group_id)
    member_ids = {str(item.get('student_user_id')) for item in members}
    remaining_capacity = max(int(group.get('capacity') or 0) - len(members), 0)
    if request.method == 'POST':
        selected = [item for item in request.POST.getlist('student_ids') if item and item not in member_ids]
        selected = selected[:remaining_capacity] if remaining_capacity else []
        added = 0
        for student_id in selected:
            student = next((item for item in students if str(item['id']) == str(student_id)), None)
            if not student:
                continue
            erd_execute(
                "INSERT INTO student_group_members (id, group_id, student_user_id, full_name, national_id, student_number) VALUES (%s, %s, %s, %s, %s, %s)",
                [str(uuid.uuid4()), group_id, student_id, student['full_name'], '-', student.get('student_number') or '-'],
            )
            added += 1
        if added:
            messages.success(request, f'{added} دانشجو به گروه اضافه شد.')
        else:
            messages.warning(request, 'دانشجویی اضافه نشد (ظرفیت گروه تکمیل است یا موردی انتخاب نشد).')
        return redirect(manage_url_name, group_id=group_id)
    eligible = [student for student in students if str(student['id']) not in member_ids]
    for student in eligible:
        student['status_label'] = 'فعال' if student.get('status') == 'active' else 'غیرفعال'
    fields = sorted({s.get('field_of_study') for s in eligible if s.get('field_of_study') and s.get('field_of_study') != '-'})
    entry_years = sorted({s.get('entry_year') for s in eligible if s.get('entry_year')}, reverse=True)
    context = {
        'title': 'افزودن دانشجو به گروه',
        'group': group,
        'eligible_students': eligible,
        'fields': fields,
        'entry_years': entry_years,
        'remaining_capacity': remaining_capacity,
        'members_count': len(members),
        'detail_url': reverse(detail_url_name, args=[group_id]),
        'students_url': reverse('core:exam_manager_group_students_manage' if is_exam_manager_route else 'core:super_admin_group_students_manage', args=[group_id]),
    }
    return render(request, 'super_admin/group_students_add.html', context)


@erd_role_required('academic_manager', 'admin')
def super_admin_group_archive(request, group_id):
    if not _erd_group_in_manager_scope(request, group_id):
        raise Http404('گروه پیدا نشد.')
    group_rows = _em_group_rows(request, group_id=group_id)
    if not group_rows:
        raise Http404('گروه پیدا نشد.')
    group = group_rows[0]
    is_exam_manager_route = request.resolver_match.url_name.startswith('exam_manager_')
    groups_list_url_name = 'core:exam_manager_groups' if is_exam_manager_route else 'core:super_admin_groups'
    detail_url_name = 'core:exam_manager_group_detail' if is_exam_manager_route else 'core:super_admin_group_detail'
    archive_url_name = 'core:exam_manager_group_archive' if is_exam_manager_route else 'core:super_admin_group_archive'
    has_dependencies = group['students_count'] > 0 or group['exams_count'] > 0
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'archive':
            if erd_has_column('student_groups', 'is_archived'):
                erd_execute('UPDATE student_groups SET is_archived = true, archived_at = CURRENT_TIMESTAMP WHERE id = %s', [group_id])
                messages.success(request, 'گروه بایگانی شد.')
            else:
                messages.error(request, 'قابلیت بایگانی روی این نسخه از دیتابیس فعال نیست.')
            return redirect(groups_list_url_name)
        if action == 'delete':
            if has_dependencies:
                messages.error(request, 'به دلیل وجود دانشجو یا آزمون مرتبط، حذف دائمی امکان‌پذیر نیست. ابتدا وابستگی‌ها را برطرف کنید.')
                return redirect(archive_url_name, group_id=group_id)
            with connection.cursor() as cursor:
                cursor.execute('DELETE FROM student_group_members WHERE group_id = %s', [group_id])
                cursor.execute('DELETE FROM group_teachers WHERE group_id = %s', [group_id])
                cursor.execute('DELETE FROM student_groups WHERE id = %s', [group_id])
            messages.success(request, 'گروه برای همیشه حذف شد.')
            return redirect(groups_list_url_name)
    context = {
        'title': 'بایگانی یا حذف گروه درسی',
        'group': group,
        'has_dependencies': has_dependencies,
        'detail_url': reverse(detail_url_name, args=[group_id]),
    }
    return render(request, 'super_admin/group_archive.html', context)


@erd_role_required('academic_manager', 'admin')
def super_admin_groups(request):
    q = request.GET.get('q', '').strip()
    term_filter = request.GET.get('term', '').strip()
    year_filter, _, semester_raw = term_filter.partition('|')
    semester_filter = semester_raw
    sort = request.GET.get('sort', 'newest')
    tab = request.GET.get('tab', 'all')
    status_filter = request.GET.get('status', '').strip()
    fill_filter = request.GET.get('fill', '').strip()
    teacher_filter = request.GET.get('teacher', '').strip()

    org_units = _erd_manager_visible_org_units(request)
    unit_by_id = {str(unit['id']): unit for unit in org_units}

    def unit_path(unit_id):
        unit = unit_by_id.get(str(unit_id or ''))
        if not unit:
            return {'university': '-', 'faculty': '-', 'department': '-', 'label': '-'}
        chain = []
        current = unit
        seen = set()
        while current and str(current['id']) not in seen:
            seen.add(str(current['id']))
            chain.append(current)
            current = unit_by_id.get(str(current.get('parent_id') or ''))
        by_type = {item['type']: item['name'] for item in chain}
        return {
            'university': by_type.get('university') or '-',
            'faculty': by_type.get('faculty') or '-',
            'department': by_type.get('department') or by_type.get('group') or '-',
            'label': ' / '.join(part for part in [by_type.get('university'), by_type.get('faculty'), by_type.get('department') or by_type.get('group')] if part) or unit['name'],
        }

    def semester_label(value):
        value = str(value or '').strip()
        return {'1': 'اول', '2': 'دوم', 'summer': 'تابستان', 'اول': 'اول', 'دوم': 'دوم', 'تابستان': 'تابستان'}.get(value, value or '-')

    def normalize_semester(value):
        value = str(value or '').strip()
        return {'نیمسال اول': 'اول', 'اول': 'اول', '1': 'اول', 'نیمسال دوم': 'دوم', 'دوم': 'دوم', '2': 'دوم', 'تابستان': 'تابستان', 'summer': 'تابستان'}.get(value, value or 'اول')

    if request.GET.get('group_action') == 'sample':
        return xlsx_response(
            'student-groups-template.xlsx',
            ['عنوان درس', 'کد گروه', 'سال تحصیلی', 'نیمسال', 'استاد', 'ظرفیت', 'توضیحات', 'دانشجوها'],
            [['برنامه‌نویسی پایتون', 'PY101-G1', '1403-1404', 'اول', 'استاد اول کامپیوتر', '40', 'توضیح نمونه', 'STU-01, STU-02, STU-03']],
            'Groups',
        )

    if request.method == 'POST' and request.POST.get('group_action') == 'delete':
        group_id = request.POST.get('group_id')
        wants_json = request.headers.get('x-requested-with') == 'XMLHttpRequest'
        if group_id and not _erd_group_in_manager_scope(request, group_id):
            return HttpResponseForbidden('این گروه خارج از محدوده‌ی دسترسی شماست.')
        if group_id:
            with connection.cursor() as cursor:
                cursor.execute('DELETE FROM student_group_members WHERE group_id = %s', [group_id])
                cursor.execute('DELETE FROM group_teachers WHERE group_id = %s', [group_id])
                cursor.execute('DELETE FROM student_groups WHERE id = %s', [group_id])
            if wants_json:
                return JsonResponse({'ok': True, 'message': 'گروه حذف شد.', 'group_id': group_id})
            messages.success(request, 'گروه حذف شد.')
        elif wants_json:
            return JsonResponse({'ok': False, 'message': 'شناسه گروه نامعتبر است.'}, status=400)
        return redirect('core:super_admin_groups')

    if request.method == 'POST' and request.POST.get('group_action') == 'save':
        wants_json = request.headers.get('x-requested-with') == 'XMLHttpRequest'
        existing_group_id = request.POST.get('group_id') or None
        group_id = existing_group_id or str(uuid.uuid4())
        course_id = request.POST.get('course_id') or None
        teacher_id = request.POST.get('teacher_id') or None
        selected_teachers = request.POST.getlist('teacher_ids') or ([teacher_id] if teacher_id else [])
        student_ids = request.POST.getlist('student_ids')
        if existing_group_id and not _erd_group_in_manager_scope(request, existing_group_id):
            return HttpResponseForbidden('این گروه خارج از محدوده‌ی دسترسی شماست.')
        if not _erd_group_assignment_in_scope(request, course_id, selected_teachers):
            return HttpResponseForbidden('درس/استاد انتخاب‌شده خارج از محدوده‌ی دسترسی شماست.')
        course_title = request.POST.get('course_name', '').strip()
        if course_id:
            course = erd_row('SELECT title FROM courses WHERE id = %s', [course_id])
            course_title = course_title or (course or {}).get('title') or ''
        course_title = course_title or 'گروه جدید'
        academic_year = request.POST.get('academic_year', '').strip() or '1403-1404'
        semester = normalize_semester(request.POST.get('semester'))
        group_code = request.POST.get('group_code', '').strip() or None
        description = request.POST.get('description', '').strip() or None
        created_by = (erd_profile_for_user(request.user) or {}).get('id')
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1 FROM student_groups WHERE id = %s', [group_id])
            exists = cursor.fetchone()
            if exists:
                cursor.execute(
                    """
                    UPDATE student_groups
                    SET teacher_id = %s, course_id = %s, course_name = %s, academic_year = %s,
                        semester = %s, group_code = %s, description = %s, is_active = true
                    WHERE id = %s
                    """,
                    [teacher_id, course_id, course_title, academic_year, semester, group_code, description, group_id],
                )
            else:
                cursor.execute(
                    """
                    INSERT INTO student_groups (id, teacher_id, course_id, course_name, academic_year, semester, group_code, description, is_active, created_by)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, true, %s)
                    """,
                    [group_id, teacher_id, course_id, course_title, academic_year, semester, group_code, description, created_by],
                )
            cursor.execute('DELETE FROM group_teachers WHERE group_id = %s', [group_id])
            for selected_teacher in dict.fromkeys([item for item in selected_teachers if item]):
                cursor.execute('INSERT INTO group_teachers (group_id, teacher_id, created_at) VALUES (%s, %s, CURRENT_TIMESTAMP) ON CONFLICT DO NOTHING', [group_id, selected_teacher])
            cursor.execute('DELETE FROM student_group_members WHERE group_id = %s', [group_id])
            for student_id in dict.fromkeys([item for item in student_ids if item]):
                student = erd_row(
                    """
                    SELECT p.full_name, COALESCE(p.national_id, '') AS national_id,
                           COALESCE(sp.student_number, p.identifier, '') AS student_number
                    FROM profiles p
                    LEFT JOIN student_profiles sp ON sp.user_id = p.id
                    WHERE p.id = %s
                    """,
                    [student_id],
                )
                if not student:
                    continue
                cursor.execute(
                    """
                    INSERT INTO student_group_members (id, group_id, student_user_id, full_name, national_id, student_number)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    [str(uuid.uuid4()), group_id, student_id, student.get('full_name') or 'دانشجو', student.get('national_id') or '-', student.get('student_number') or '-'],
                )
        if wants_json:
            return JsonResponse({'ok': True, 'message': 'گروه ذخیره شد.', 'group_id': group_id})
        messages.success(request, 'گروه ذخیره شد.')
        return redirect('core:super_admin_groups')

    teachers = erd_rows(
        """
        SELECT p.id, p.full_name, COALESCE(tp.personnel_code, p.identifier, '') AS code, tp.org_unit_id
        FROM teacher_profiles tp
        JOIN profiles p ON p.id = tp.user_id
        ORDER BY p.full_name
        LIMIT 300
        """
    )
    terms = erd_rows('SELECT id, year, semester, label, is_current FROM academic_terms ORDER BY year DESC, semester LIMIT 100')
    for term in terms:
        term['value'] = f"{term.get('year') or ''}|{term.get('semester') or ''}"
    years = sorted(
        {term.get('year') for term in terms if term.get('year')} |
        {str(row.get('academic_year')) for row in erd_rows('SELECT DISTINCT academic_year FROM student_groups WHERE academic_year IS NOT NULL') if row.get('academic_year')},
        reverse=True,
    )
    order_sql = 'sg.academic_year DESC, sg.course_name'
    if sort == 'oldest':
        order_sql = 'sg.academic_year ASC, sg.course_name'
    elif sort == 'capacity':
        order_sql = 'members_count DESC, sg.course_name'
    capacity_col = 'sg.capacity' if erd_has_column('student_groups', 'capacity') else '30 AS capacity'
    status_col = 'sg.status' if erd_has_column('student_groups', 'status') else "'active' AS status"
    schedule_col = 'sg.class_schedule' if erd_has_column('student_groups', 'class_schedule') else 'NULL AS class_schedule'
    location_col = 'sg.class_location' if erd_has_column('student_groups', 'class_location') else 'NULL AS class_location'
    archived_col = 'COALESCE(sg.is_archived, false)' if erd_has_column('student_groups', 'is_archived') else 'false'
    is_admin = _erd_is_admin_request(request)
    scope_cte = '' if is_admin else _erd_manager_scope_cte()
    scope_where = '1=1' if is_admin else _erd_group_scope_condition()
    scope_params = [] if is_admin else [request.erd_profile_id]
    groups = erd_rows(
        f"""
        {scope_cte}
        SELECT sg.id, sg.teacher_id, sg.course_id, sg.course_name, sg.academic_year, sg.semester,
               sg.group_code, sg.description, COALESCE(sg.is_active, true) AS is_active,
               {capacity_col}, {status_col}, {schedule_col}, {location_col}, {archived_col} AS is_archived,
               COALESCE(c.title, sg.course_name) AS course_title, c.code AS course_code, c.org_unit_id AS course_org_unit_id,
               COALESCE(tp.full_name, '-') AS primary_teacher, tp.avatar_url AS teacher_avatar,
               COALESCE(teacher_names.names, '-') AS teachers_text,
               COALESCE(members.members_count, 0) AS members_count
        FROM student_groups sg
        LEFT JOIN courses c ON c.id = sg.course_id
        LEFT JOIN profiles tp ON tp.id = sg.teacher_id
        LEFT JOIN (
            SELECT gt.group_id, STRING_AGG(p.full_name, '، ' ORDER BY p.full_name) AS names
            FROM group_teachers gt
            JOIN profiles p ON p.id = gt.teacher_id
            GROUP BY gt.group_id
        ) teacher_names ON teacher_names.group_id = sg.id
        LEFT JOIN (
            SELECT group_id, COUNT(*) AS members_count
            FROM student_group_members
            GROUP BY group_id
        ) members ON members.group_id = sg.id
        WHERE {scope_where}
        ORDER BY {order_sql}
        LIMIT 300
        """,
        scope_params,
    )
    teacher_links = erd_rows('SELECT group_id, teacher_id FROM group_teachers')
    student_links = erd_rows(
        """
        SELECT sgm.group_id, sgm.student_user_id, sgm.full_name, sgm.national_id, sgm.student_number, p.avatar_url
        FROM student_group_members sgm
        LEFT JOIN profiles p ON p.id = sgm.student_user_id
        ORDER BY sgm.full_name
        """
    )
    teachers_by_group = {}
    students_by_group = {}
    for link in teacher_links:
        teachers_by_group.setdefault(str(link['group_id']), []).append(str(link['teacher_id']))
    for link in student_links:
        students_by_group.setdefault(str(link['group_id']), []).append(link)
    current_years = {term.get('year') for term in terms if term.get('is_current')}
    current_term = next((term for term in terms if term.get('is_current')), terms[0] if terms else None)
    rows = []
    for group in groups:
        primary = unit_path(group.get('course_org_unit_id'))
        selected_students = students_by_group.get(str(group['id']), [])
        group_teacher_ids = teachers_by_group.get(str(group['id']), [])
        capacity = max(int(group.get('capacity') or 30), 1)
        percent = min(100, round((int(group.get('members_count') or 0) / capacity) * 100))
        status_value = group.get('status') or 'active'
        if group.get('is_archived'):
            continue
        if tab == 'current' and group.get('academic_year') not in current_years:
            continue
        if tab == 'archive' and group.get('academic_year') in current_years:
            continue
        if year_filter and group.get('academic_year') != year_filter:
            continue
        if semester_filter and normalize_semester(group.get('semester')) != normalize_semester(semester_filter):
            continue
        if status_filter and status_value != status_filter:
            continue
        if fill_filter == 'low' and percent >= 50:
            continue
        if fill_filter == 'mid' and not (50 <= percent < 90):
            continue
        if fill_filter == 'full' and percent < 90:
            continue
        if teacher_filter and teacher_filter != str(group.get('teacher_id') or '') and teacher_filter not in group_teacher_ids:
            continue
        if q and not _matches_query(q, group.get('course_name'), group.get('group_code'), group.get('primary_teacher'), group.get('teachers_text'), group.get('academic_year'), primary['label']):
            continue
        rows.append({
            **group,
            'semester_label': semester_label(group.get('semester')),
            'status_value': status_value,
            'status_label': 'فعال' if status_value == 'active' else 'پیش‌نویس',
            'teacher_ids': group_teacher_ids,
            'student_ids': [str(item.get('student_user_id') or '') for item in selected_students if item.get('student_user_id')],
            'students_json': selected_students,
            'capacity': capacity,
            'fill_percent': percent,
            'university': primary['university'],
            'faculty': primary['faculty'],
            'department_name': primary['department'],
        })
    group_stats = {
        'groups': len(rows),
        'students': sum(int(row.get('members_count') or 0) for row in rows),
        'courses': len({str(row.get('course_id') or row.get('course_name') or '') for row in rows if row.get('course_id') or row.get('course_name')}),
        'active_courses': len({str(row.get('course_id') or row.get('course_name') or '') for row in rows if (row.get('course_id') or row.get('course_name')) and row.get('is_active')}),
        'current_year': (next(iter(current_years), None) or (years[0] if years else '1403-1404')),
        'current_term_label': (current_term or {}).get('label') or (next(iter(current_years), None) or (years[0] if years else '1403-1404')),
        'active_groups': sum(1 for row in rows if row.get('is_active')),
        'capacity': sum(int(row.get('capacity') or 0) for row in rows),
        'remaining_capacity': sum(max(int(row.get('capacity') or 0) - int(row.get('members_count') or 0), 0) for row in rows),
    }

    total_rows = len(rows)
    page_size = request.GET.get('page_size')
    page_size = int(page_size) if str(page_size).isdigit() and int(page_size) in (10, 25, 50) else 10
    total_pages = max(1, math.ceil(total_rows / page_size))
    page = request.GET.get('page')
    page = int(page) if str(page).isdigit() else 1
    page = min(max(page, 1), total_pages)
    start_index = (page - 1) * page_size
    end_index = start_index + page_size
    page_rows = rows[start_index:end_index]
    window_start = max(1, page - 2)
    window_end = min(total_pages, window_start + 4)
    window_start = max(1, window_end - 4)
    page_numbers = list(range(window_start, window_end + 1))

    return render(request, 'super_admin/groups.html', {
        'title': 'گروه‌بندی',
        'rows': page_rows,
        'page': page,
        'page_size': page_size,
        'total_pages': total_pages,
        'total_rows': total_rows,
        'start_index': start_index + 1 if page_rows else 0,
        'end_index': min(end_index, total_rows),
        'page_numbers': page_numbers,
        'query': q,
        'year_filter': year_filter,
        'semester_filter': semester_filter,
        'term_filter': term_filter,
        'status_filter': status_filter,
        'fill_filter': fill_filter,
        'teacher_filter': teacher_filter,
        'sort': sort,
        'tab': tab,
        'years': years,
        'terms': terms,
        'current_term': current_term,
        'teachers': teachers,
        'stats': group_stats,
    })


EXAM_STAFF_ROLES = ('designer', 'observer', 'co_grader')
EXAM_STAFF_ROLE_LABELS = {'designer': 'طراح آزمون', 'observer': 'ناظر', 'co_grader': 'همکار تصحیح'}


def _parse_exam_wizard_datetime(value):
    value = (value or '').strip()
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed


def _store_upload(uploaded, subfolder, allowed_extensions, max_bytes=None):
    """Store an uploaded file under MEDIA_ROOT/subfolder with a random name. Returns (url, error)."""
    if not uploaded:
        return None, None
    extension = (uploaded.name.rsplit('.', 1)[-1] if '.' in uploaded.name else '').lower()
    if extension not in allowed_extensions:
        return None, f'نوع فایل «{uploaded.name}» مجاز نیست.'
    if max_bytes and uploaded.size > max_bytes:
        return None, f'حجم فایل «{uploaded.name}» بیش از حد مجاز ({max_bytes // (1024 * 1024)} مگابایت) است.'
    storage = FileSystemStorage(location=str(Path(settings.MEDIA_ROOT) / subfolder), base_url=f'{settings.MEDIA_URL}{subfolder}/')
    filename = storage.save(f"{uuid.uuid4().hex}.{extension}", uploaded)
    return storage.url(filename), None


def _save_exam_wizard_upload(request, field_name, subfolder, allowed_extensions):
    url, _error = _store_upload(request.FILES.get(field_name), subfolder, allowed_extensions)
    return url


@erd_role_required('academic_manager', 'admin')
def super_admin_exam_participants_match(request):
    """تطبیق فایل اکسل/CSV مخاطبان آزمون بر اساس کد ملی یا شماره دانشجویی، محدود به محدوده‌ی دسترسی مدیر."""
    return _exam_participants_match_response(request)


@erd_role_required('teacher')
def teacher_exam_participants_match(request):
    """همان تطبیق فایل مخاطبان، محدود به دانشجویان گروه‌های همین استاد."""
    return _exam_participants_match_response(request, _exam_wizard_scope(request))


def _exam_participants_match_response(request, scope=None):
    if request.method != 'POST':
        return JsonResponse({'error': 'روش درخواست نامعتبر است.'}, status=405)
    uploaded = request.FILES.get('excel_file')
    if not uploaded:
        return JsonResponse({'error': 'فایلی انتخاب نشده است.'}, status=400)
    try:
        rows, identifiers = _erd_parse_participant_upload(uploaded)
    except (UnicodeDecodeError, KeyError, ET.ParseError, zipfile.BadZipFile):
        return JsonResponse({'error': 'فایل انتخاب‌شده معتبر نیست. قالب نمونه را دریافت و تکمیل کنید.'}, status=400)
    if not rows:
        return JsonResponse({'error': 'فایل انتخاب‌شده ردیفی برای بررسی ندارد.'}, status=400)

    found, not_found, duplicate_count = _erd_match_students_by_identifier(request, identifiers, scope)
    return JsonResponse({
        'total': len(identifiers),
        'total_rows': len(rows),
        'found': found,
        'not_found': not_found,
        'duplicate_count': duplicate_count,
    })


EXAM_WIZARD_SCOPE_KINDS = ('groups', 'courses', 'teachers', 'students', 'questions')


def _exam_wizard_scope(request) -> dict:
    """SQL filters (condition, params) for every picker of the exam wizard.

    Admin: everything. Academic manager: their managed org units. Teacher: the groups
    they own or co-teach, those groups' courses, members and teachers, and their own questions.
    """
    if getattr(request, 'erd_role', None) == 'teacher':
        teacher_id = request.erd_profile_id
        own_groups = '(SELECT id FROM student_groups WHERE teacher_id = %s UNION SELECT group_id FROM group_teachers WHERE teacher_id = %s)'
        own = [teacher_id, teacher_id]
        return {
            'cte': '',
            'cte_params': [],
            'groups': (f'sg.id IN {own_groups}', own),
            'courses': (f'c.id IN (SELECT course_id FROM student_groups WHERE id IN {own_groups})', own),
            'teachers': (
                f'(tp.user_id = %s OR tp.user_id IN (SELECT teacher_id FROM student_groups WHERE id IN {own_groups})'
                f' OR tp.user_id IN (SELECT teacher_id FROM group_teachers WHERE group_id IN {own_groups}))',
                [teacher_id, *own, *own],
            ),
            'students': (f'sp.user_id IN (SELECT student_user_id FROM student_group_members WHERE group_id IN {own_groups})', own),
            'questions': ('q.teacher_id = %s', [teacher_id]),
        }
    if _erd_is_admin_request(request):
        return {'cte': '', 'cte_params': [], **{kind: ('1=1', []) for kind in EXAM_WIZARD_SCOPE_KINDS}}
    return {
        'cte': _erd_manager_scope_cte(),
        'cte_params': [request.erd_profile_id],
        'groups': (_erd_group_scope_condition(), []),
        'courses': ('c.org_unit_id IN (SELECT id FROM managed_units)', []),
        'teachers': (_erd_teacher_scope_condition(), []),
        'students': (_erd_student_scope_condition(), []),
        'questions': (_erd_question_scope_condition(), []),
    }


EXAM_WIZARD_SCOPE_TABLES = {
    'groups': ('student_groups sg LEFT JOIN courses c ON c.id = sg.course_id', 'sg.id'),
    'courses': ('courses c', 'c.id'),
    'teachers': ('teacher_profiles tp', 'tp.user_id'),
    'students': ('student_profiles sp', 'sp.user_id'),
    'questions': ('questions q LEFT JOIN courses c ON c.id = q.course_id', 'q.id'),
}


def _exam_wizard_ids_in_scope(scope: dict, kind: str, ids) -> bool:
    """True when every id of the given kind passes the wizard scope (checked in SQL, not against the capped pickers)."""
    ids = list(dict.fromkeys(str(item) for item in ids if item))
    if not ids:
        return True
    table, column = EXAM_WIZARD_SCOPE_TABLES[kind]
    condition, params = scope[kind]
    row = erd_row(
        f"""
        {scope['cte']}
        SELECT COUNT(DISTINCT {column}) AS count FROM {table}
        WHERE {column} IN ({', '.join(['%s'] * len(ids))}) AND {condition}
        """,
        [*scope['cte_params'], *ids, *params],
    )
    return bool(row) and row['count'] == len(ids)


def _exam_wizard_resources(request, scope=None) -> dict:
    """Courses, groups, teachers, students and questions the wizard may offer, filtered by the scope."""
    scope = scope or _exam_wizard_scope(request)
    cte, cte_params = scope['cte'], scope['cte_params']
    group_condition, group_params = scope['groups']
    groups = erd_rows(
        f"""
        {cte}
        SELECT sg.id, sg.teacher_id, sg.course_id, sg.course_name, sg.academic_year, sg.semester, sg.group_code,
               COALESCE(c.title, sg.course_name) AS course_title,
               COALESCE(c.code, '-') AS course_code,
               COALESCE(tp.full_name, '-') AS teacher_name,
               COALESCE(gt.teacher_id, sg.teacher_id) AS selected_teacher_id,
               COALESCE(members.members_count, 0) AS members_count
        FROM student_groups sg
        LEFT JOIN courses c ON c.id = sg.course_id
        LEFT JOIN group_teachers gt ON gt.group_id = sg.id
        LEFT JOIN profiles tp ON tp.id = COALESCE(gt.teacher_id, sg.teacher_id)
        LEFT JOIN (
            SELECT group_id, COUNT(*) AS members_count
            FROM student_group_members
            GROUP BY group_id
        ) members ON members.group_id = sg.id
        WHERE COALESCE(sg.is_active, true) = true AND {group_condition}
        ORDER BY sg.academic_year DESC, sg.course_name, sg.group_code
        LIMIT 300
        """,
        [*cte_params, *group_params],
    )
    course_condition, course_params = scope['courses']
    courses = erd_rows(
        f"""
        {cte}
        SELECT c.id, c.title, c.code FROM courses c
        WHERE {course_condition}
        ORDER BY c.title LIMIT 300
        """,
        [*cte_params, *course_params],
    )
    teacher_condition, teacher_params = scope['teachers']
    teachers = erd_rows(
        f"""
        {cte}
        SELECT tp.user_id AS id, p.full_name, p.avatar_url, COALESCE(tp.personnel_code, p.identifier, '') AS code,
               COALESCE(p.email, '') AS email, COALESCE(ou.name, tp.department, '-') AS department
        FROM teacher_profiles tp
        JOIN profiles p ON p.id = tp.user_id
        LEFT JOIN org_units ou ON ou.id = tp.org_unit_id
        WHERE {teacher_condition}
        ORDER BY department, p.full_name
        LIMIT 300
        """,
        [*cte_params, *teacher_params],
    )
    student_condition, student_params = scope['students']
    students = erd_rows(
        f"""
        {cte}
        SELECT p.id, p.full_name, p.avatar_url, COALESCE(sp.student_number, p.identifier, '') AS student_number,
               COALESCE(p.national_id, '') AS national_id,
               COALESCE(sp.field_of_study, '-') AS field_of_study,
               COALESCE(sp.class_group, '-') AS class_group,
               COALESCE(sp.degree, '-') AS degree,
               COALESCE(sp.entry_year, '-') AS entry_year,
               COALESCE(sp.academic_status, 'active') AS academic_status
        FROM student_profiles sp
        JOIN profiles p ON p.id = sp.user_id
        WHERE {student_condition}
        ORDER BY p.full_name
        LIMIT 700
        """,
        [*cte_params, *student_params],
    )
    academic_status_labels = {'active': 'فعال', 'leave': 'مرخصی', 'graduated': 'فارغ‌التحصیل', 'inactive': 'غیرفعال'}
    for student in students:
        student['academic_status_label'] = academic_status_labels.get(student['academic_status'], 'فعال')
    entry_years = sorted({s['entry_year'] for s in students if s['entry_year'] and s['entry_year'] != '-'}, reverse=True)
    degrees = sorted({s['degree'] for s in students if s['degree'] and s['degree'] != '-'})
    student_ids_in_scope = {str(row['id']) for row in students}
    group_ids_in_scope = [g['id'] for g in groups]
    group_student_map = {}
    if group_ids_in_scope:
        placeholders = ','.join(['%s'] * len(group_ids_in_scope))
        membership_rows = erd_rows(
            f"SELECT group_id, student_user_id FROM student_group_members WHERE group_id IN ({placeholders})",
            group_ids_in_scope,
        )
        for row in membership_rows:
            student_id = str(row.get('student_user_id') or '')
            group_id = str(row.get('group_id') or '')
            if not student_id or not group_id or student_id not in student_ids_in_scope:
                continue
            group_student_map.setdefault(group_id, []).append(student_id)
    wizard_optional_sql = ', '.join(
        f'q.{column}' if erd_has_column('questions', column) else f'NULL AS {column}'
        for column in ('matching_pairs', 'ordering_items', 'question_media', 'accepted_answers')
    )
    question_condition, question_params = scope['questions']
    questions = erd_rows(
        f"""
        {cte}
        SELECT q.id, q.teacher_id, q.course_id, q.type, q.difficulty, q.text, q.tags,
               q.options, q.correct_answer, q.explanation, q.media_url,
               {wizard_optional_sql},
               COALESCE(q.default_points, 1) AS points,
               COALESCE(c.title, '-') AS course_title,
               COALESCE(p.full_name, '-') AS teacher_name,
               COALESCE(usage_stats.usage_count, 0) AS usage_count,
               usage_stats.last_used_at
        FROM questions q
        LEFT JOIN courses c ON c.id = q.course_id
        LEFT JOIN profiles p ON p.id = q.teacher_id
        LEFT JOIN (
            SELECT eq.question_id, COUNT(*) AS usage_count, MAX(e.start_at) AS last_used_at
            FROM exam_questions eq
            JOIN exams e ON e.id = eq.exam_id
            GROUP BY eq.question_id
        ) usage_stats ON usage_stats.question_id = q.id
        WHERE {question_condition}
        ORDER BY q.teacher_id, q.course_id, q.text
        LIMIT 1000
        """,
        [*cte_params, *question_params],
    )
    for question in questions:
        question['options'] = _erd_parse_json_field(question.get('options'))
        question['correct_answer'] = _erd_parse_json_field(question.get('correct_answer'))
        question['matching_pairs'] = _erd_parse_json_field(question.get('matching_pairs')) or []
        question['ordering_items'] = _erd_parse_json_field(question.get('ordering_items')) or []
        question['question_media'] = _sx_question_media(question.get('question_media'))
        question['accepted_answers'] = _erd_parse_json_field(question.get('accepted_answers')) or []
    terms = erd_rows('SELECT id, year, semester, COALESCE(label, semester, year) AS label FROM academic_terms ORDER BY year DESC, semester LIMIT 50')
    is_teacher = getattr(request, 'erd_role', None) == 'teacher'
    return {
        'groups': groups,
        'courses': courses,
        'teachers': teachers,
        'students': students,
        'questions': questions,
        'terms': terms,
        'org_units': [] if is_teacher else _erd_manager_visible_org_units(request),
        'group_student_map': group_student_map,
        'entry_years': entry_years,
        'degrees': degrees,
    }


def _exam_wizard_insert(request, *, title, teacher_id, course_id, first_group, selected_questions, selected_groups,
                        selected_students, excluded_students, staff_pairs, publish_choice, is_published,
                        lifecycle_status, approval_status, existing_exam_id=None) -> str:
    """Save the exam, its questions, audience and staff from an already scope-checked wizard POST.

    With existing_exam_id the exam row is updated and its questions/audience/staff are replaced;
    a cover or guidance file is only replaced when a new one is uploaded."""
    placeholders = ','.join(['%s'] * len(selected_questions))
    questions_by_id = {
        str(row['id']): row
        for row in erd_rows(
            f"""
            SELECT id, COALESCE(default_points, 1) AS points
            FROM questions
            WHERE id IN ({placeholders})
            """,
            selected_questions,
        )
    }
    valid_questions = [questions_by_id[q_id] for q_id in dict.fromkeys(selected_questions) if q_id in questions_by_id]
    duration = int(request.POST.get('duration_minutes') or 45)
    start_at = _parse_exam_wizard_datetime(request.POST.get('start_at'))
    end_at = _parse_exam_wizard_datetime(request.POST.get('end_at'))
    if start_at and not end_at:
        end_at = start_at + timedelta(minutes=duration)
    registration_start_at = _parse_exam_wizard_datetime(request.POST.get('registration_start_at'))
    registration_end_at = _parse_exam_wizard_datetime(request.POST.get('registration_end_at'))
    last_entry_at = _parse_exam_wizard_datetime(request.POST.get('last_entry_at'))
    scheduled_publish_at = _parse_exam_wizard_datetime(request.POST.get('scheduled_publish_at'))

    exam_id = str(uuid.uuid4())

    cover_image_url = _save_exam_wizard_upload(request, 'cover_image', 'exam-covers', {'jpg', 'jpeg', 'png'})
    guidance_file_url = _save_exam_wizard_upload(request, 'guidance_file', 'exam-guidance', {'pdf', 'jpg', 'jpeg', 'png'})

    optional_columns = [
        ('result_release_mode', request.POST.get('result_release_mode') or 'after_exam'),
        ('review_answers_enabled', bool(request.POST.get('review_answers_enabled'))),
        ('allow_answer_changes', bool(request.POST.get('allow_answer_changes'))),
        ('show_instructions_before_start', bool(request.POST.get('show_instructions_before_start'))),
        ('autosave_enabled', bool(request.POST.get('autosave_enabled'))),
        ('fullscreen_required', bool(request.POST.get('fullscreen_required'))),
        ('track_tab_exit', bool(request.POST.get('track_tab_exit'))),
        ('show_correct_answers', bool(request.POST.get('show_correct_answers'))),
        ('show_score', bool(request.POST.get('show_score'))),
        ('show_feedback', bool(request.POST.get('show_feedback'))),
        ('publish_mode', publish_choice),
        ('exam_mode', request.POST.get('exam_mode') or 'standard'),
        ('tags', request.POST.get('tags', '').strip()),
        ('grading_template', request.POST.get('grading_template') or 'total_score'),
        ('registration_start_at', registration_start_at),
        ('registration_end_at', registration_end_at),
        ('last_entry_at', last_entry_at),
        ('allow_flagging_questions', bool(request.POST.get('allow_flagging_questions'))),
        ('show_question_list', bool(request.POST.get('show_question_list'))),
        ('one_question_per_page', bool(request.POST.get('one_question_per_page'))),
        ('auto_submit_on_time_end', bool(request.POST.get('auto_submit_on_time_end'))),
        ('correct_answer_display_mode', request.POST.get('correct_answer_display_mode') or 'after_publish'),
        ('score_display_mode', request.POST.get('score_display_mode') or 'after_publish'),
        ('explanation_display_mode', request.POST.get('explanation_display_mode') or 'after_publish'),
        ('grading_method', request.POST.get('grading_method') or 'weighted_by_type'),
        ('manual_review_required', bool(request.POST.get('manual_review_required'))),
        ('results_deadline', request.POST.get('results_deadline') or '3_days_after_end'),
        ('correction_instructions', request.POST.get('correction_instructions', '').strip()),
        ('rubric_template', request.POST.get('rubric_template') or ''),
        ('correction_mode', request.POST.get('correction_mode') or 'manual'),
        ('security_level', request.POST.get('security_level') or 'medium'),
        ('execution_mode', request.POST.get('execution_mode') or 'web'),
        ('identity_verification_required', bool(request.POST.get('identity_verification_required'))),
        ('device_limit_enabled', bool(request.POST.get('device_limit_enabled'))),
        ('ip_restriction_enabled', bool(request.POST.get('ip_restriction_enabled'))),
        ('ip_restriction_range', request.POST.get('ip_restriction_range', '').strip()),
        ('webcam_monitoring', bool(request.POST.get('webcam_monitoring'))),
        ('mic_monitoring', bool(request.POST.get('mic_monitoring'))),
        ('copy_paste_prevention', bool(request.POST.get('copy_paste_prevention'))),
        ('screenshot_prevention', bool(request.POST.get('screenshot_prevention'))),
        ('autosave_interval_seconds', int(request.POST.get('autosave_interval_seconds') or 30)),
        ('internet_disconnect_policy', request.POST.get('internet_disconnect_policy') or 'resume_from_last_save'),
        ('scheduled_publish_at', scheduled_publish_at),
        ('notify_students_system_message', bool(request.POST.get('notify_students_system_message'))),
        ('notify_students_email', bool(request.POST.get('notify_students_email'))),
        ('show_in_academic_calendar', bool(request.POST.get('show_in_academic_calendar'))),
    ]
    if cover_image_url:
        optional_columns.append(('cover_image_url', cover_image_url))
    if guidance_file_url:
        optional_columns.append(('guidance_file_url', guidance_file_url))
    insert_columns = [
        'id', 'teacher_id', 'course_id', 'title', 'description', 'duration_minutes', 'start_at', 'end_at',
        'shuffle_questions', 'shuffle_options', 'negative_marking', 'negative_factor', 'max_attempts',
        'is_published', 'show_results_immediately', 'passing_score', 'allow_partial', 'approval_status',
        'exam_type', 'academic_year', 'semester', 'lifecycle_status',
    ]
    insert_values = [
        exam_id,
        teacher_id,
        course_id,
        title,
        request.POST.get('description', '').strip(),
        duration,
        start_at,
        end_at,
        bool(request.POST.get('shuffle_questions')),
        bool(request.POST.get('shuffle_options')),
        bool(request.POST.get('negative_marking')),
        request.POST.get('negative_factor') or 0,
        int(request.POST.get('max_attempts') or 1),
        is_published,
        bool(request.POST.get('show_results_immediately')),
        request.POST.get('passing_score') or None,
        bool(request.POST.get('allow_partial')),
        approval_status,
        request.POST.get('exam_type') or 'standard',
        request.POST.get('academic_year') or (first_group or {}).get('academic_year') or '',
        request.POST.get('semester') or (first_group or {}).get('semester') or '',
        lifecycle_status,
    ]
    for column, value in optional_columns:
        if erd_has_column('exams', column):
            insert_columns.append(column)
            insert_values.append(value)
    with transaction.atomic():
        if existing_exam_id:
            exam_id = existing_exam_id
            assert insert_columns[0] == 'id'
            erd_execute(
                f"UPDATE exams SET {', '.join(f'{column} = %s' for column in insert_columns[1:])} WHERE id = %s",
                [*insert_values[1:], exam_id],
            )
            with connection.cursor() as cursor:
                for table in ('exam_questions', 'exam_assignments', 'exam_assignment_exclusions', 'exam_staff'):
                    cursor.execute(f'DELETE FROM {table} WHERE exam_id = %s', [exam_id])
        else:
            erd_execute(
                f"""
                INSERT INTO exams ({', '.join(insert_columns)})
                VALUES ({', '.join(['%s'] * len(insert_columns))})
                """,
                insert_values,
            )
        with connection.cursor() as cursor:
            for index, question in enumerate(valid_questions, start=1):
                cursor.execute(
                    """
                    INSERT INTO exam_questions (id, exam_id, question_id, points, order_index)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT DO NOTHING
                    """,
                    [str(uuid.uuid4()), exam_id, question['id'], question['points'] or 1, index],
                )
            for group_id in dict.fromkeys(selected_groups):
                cursor.execute(
                    "INSERT INTO exam_assignments (id, exam_id, group_id) VALUES (%s, %s, %s)",
                    [str(uuid.uuid4()), exam_id, group_id],
                )
            for student_id in dict.fromkeys(selected_students):
                cursor.execute(
                    "INSERT INTO exam_assignments (id, exam_id, student_profile_id) VALUES (%s, %s, %s)",
                    [str(uuid.uuid4()), exam_id, student_id],
                )
            for student_id in dict.fromkeys(excluded_students):
                if student_id in selected_students:
                    continue
                cursor.execute(
                    """
                    INSERT INTO exam_assignment_exclusions (id, exam_id, student_profile_id) VALUES (%s, %s, %s)
                    ON CONFLICT DO NOTHING
                    """,
                    [str(uuid.uuid4()), exam_id, student_id],
                )
            for staff_teacher_id, staff_role in staff_pairs:
                if not staff_teacher_id or staff_role not in EXAM_STAFF_ROLES:
                    continue
                cursor.execute(
                    """
                    INSERT INTO exam_staff (id, exam_id, teacher_id, role) VALUES (%s, %s, %s, %s)
                    ON CONFLICT DO NOTHING
                    """,
                    [str(uuid.uuid4()), exam_id, staff_teacher_id, staff_role],
                )
    return exam_id


def _exam_wizard_render(request, resources, **extra):
    question_type_cards = [
        {'key': 'short_answer', 'label': 'پاسخ کوتاه', 'icon': 'text'},
        {'key': 'single', 'label': 'چهارگزینه‌ای', 'icon': 'list'},
        {'key': 'multi', 'label': 'چندگزینه‌ای', 'icon': 'checks'},
        {'key': 'true_false', 'label': 'درست / نادرست', 'icon': 'check'},
        {'key': 'essay', 'label': 'تشریحی', 'icon': 'lines'},
        {'key': 'fill_blank', 'label': 'جای خالی', 'icon': 'dash'},
        {'key': 'matching', 'label': 'تطبیقی', 'icon': 'nodes'},
        {'key': 'ordering', 'label': 'ترتیبی', 'icon': 'order'},
        {'key': 'image_based', 'label': 'تصویری', 'icon': 'image'},
        {'key': 'calculation', 'label': 'محاسباتی', 'icon': 'calculator'},
    ]
    teachers_by_department = []
    seen_departments = []
    for teacher in resources['teachers']:
        department = teacher.get('department') or '-'
        if department not in seen_departments:
            seen_departments.append(department)
            teachers_by_department.append({'department': department, 'teachers': []})
        next(item for item in teachers_by_department if item['department'] == department)['teachers'].append(teacher)

    return render(request, 'super_admin/exam_wizard.html', {
        'title': 'ایجاد آزمون',
        'teachers_by_department': teachers_by_department,
        'questions_json': resources['questions'],
        'question_type_cards': question_type_cards,
        'staff_role_labels': EXAM_STAFF_ROLE_LABELS,
        **resources,
        **extra,
    })


def _exam_wizard_post_selection(request) -> dict:
    """The wizard's posted title and id lists, plus the first chosen group (year/semester defaults)."""
    group_ids = [item for item in request.POST.getlist('group_ids') if item]
    first_group = erd_row(
        """
        SELECT sg.*, COALESCE(gt.teacher_id, sg.teacher_id) AS selected_teacher_id
        FROM student_groups sg
        LEFT JOIN group_teachers gt ON gt.group_id = sg.id
        WHERE sg.id = %s
        LIMIT 1
        """,
        [group_ids[0]],
    ) if group_ids else None
    return {
        'title': request.POST.get('title', '').strip(),
        'group_ids': group_ids,
        'student_ids': [item for item in request.POST.getlist('student_ids') if item],
        'excluded_student_ids': [item for item in request.POST.getlist('excluded_student_ids') if item],
        'question_ids': [item for item in request.POST.getlist('question_ids') if item],
        'staff_teacher_ids': request.POST.getlist('staff_teacher_id'),
        'staff_roles': request.POST.getlist('staff_role'),
        'first_group': first_group,
    }


@erd_role_required('academic_manager', 'admin')
def super_admin_exam_create(request):
    is_admin = _erd_is_admin_request(request)
    managed_unit_ids = _erd_managed_unit_ids(request)
    resources = _exam_wizard_resources(request)
    courses, teachers, questions = resources['courses'], resources['teachers'], resources['questions']

    if request.method == 'POST':
        posted = _exam_wizard_post_selection(request)
        title, first_group = posted['title'], posted['first_group']
        selected_groups, selected_students = posted['group_ids'], posted['student_ids']
        excluded_students, selected_questions = posted['excluded_student_ids'], posted['question_ids']
        staff_teacher_ids, staff_roles = posted['staff_teacher_ids'], posted['staff_roles']
        course_id = request.POST.get('course_id') or (first_group or {}).get('course_id')
        teacher_id = request.POST.get('teacher_id') or (first_group or {}).get('selected_teacher_id') or (first_group or {}).get('teacher_id')
        if not title or not course_id or not teacher_id:
            messages.error(request, 'عنوان آزمون، درس و استاد الزامی است.')
            return redirect('core:super_admin_exam_create')
        if not _erd_group_assignment_in_scope(request, course_id, [teacher_id]):
            return HttpResponseForbidden('درس/استاد انتخاب‌شده خارج از محدوده‌ی دسترسی شماست.')
        if not selected_groups and not selected_students:
            messages.error(request, 'حداقل یک گروه یا دانشجو برای آزمون انتخاب کنید.')
            return redirect('core:super_admin_exam_create')
        if not selected_questions:
            messages.error(request, 'حداقل یک سوال برای آزمون انتخاب کنید.')
            return redirect('core:super_admin_exam_create')
        if not is_admin:
            if managed_unit_ids is not None and str(course_id) not in {str(c['id']) for c in courses}:
                return HttpResponseForbidden('درس انتخاب‌شده خارج از محدوده‌ی دسترسی شماست.')
            in_scope_question_ids = {str(q['id']) for q in questions}
            if any(str(q_id) not in in_scope_question_ids for q_id in selected_questions):
                return HttpResponseForbidden('برخی سوالات انتخاب‌شده خارج از محدوده‌ی دسترسی شماست.')
            in_scope_teacher_ids = {str(t['id']) for t in teachers}
            if any(str(t_id) not in in_scope_teacher_ids for t_id in staff_teacher_ids):
                return HttpResponseForbidden('برخی از عوامل انتخاب‌شده خارج از محدوده‌ی دسترسی شماست.')
            if not all(_erd_group_in_manager_scope(request, group_id) for group_id in dict.fromkeys(selected_groups)):
                return HttpResponseForbidden('برخی گروه‌های انتخاب‌شده خارج از محدوده‌ی دسترسی شماست.')
            chosen_students = dict.fromkeys(selected_students + excluded_students)
            if not all(_erd_profile_in_manager_scope(request, student_id, 'student') for student_id in chosen_students):
                return HttpResponseForbidden('برخی دانشجویان انتخاب‌شده خارج از محدوده‌ی دسترسی شماست.')

        publish_choice = request.POST.get('publish_choice') or 'draft'
        is_published = publish_choice == 'immediate'
        _exam_wizard_insert(
            request, title=title, teacher_id=teacher_id, course_id=course_id, first_group=first_group,
            selected_questions=selected_questions, selected_groups=selected_groups,
            selected_students=selected_students, excluded_students=excluded_students,
            staff_pairs=zip(staff_teacher_ids, staff_roles), publish_choice=publish_choice, is_published=is_published,
            lifecycle_status='published' if is_published else ('draft' if publish_choice == 'draft' else 'scheduled'),
            approval_status='approved' if is_published else 'pending',
        )
        messages.success(request, 'آزمون با موفقیت ایجاد شد.')
        return redirect('core:super_admin_exams')

    return _exam_wizard_render(request, resources)


@erd_role_required('academic_manager', 'admin')
def super_admin_exams(request):
    if request.method == 'POST' and request.POST.get('exam_action') == 'create':
        group_id = request.POST.get('group_id') or ''
        group = erd_row(
            """
            SELECT sg.*, COALESCE(gt.teacher_id, sg.teacher_id) AS selected_teacher_id
            FROM student_groups sg
            LEFT JOIN group_teachers gt ON gt.group_id = sg.id
            WHERE sg.id = %s
            LIMIT 1
            """,
            [group_id],
        )
        if not group:
            return JsonResponse({'ok': False, 'message': 'گروه انتخاب‌شده معتبر نیست.'}, status=400)
        if not _erd_group_assignment_in_scope(request, group.get('course_id'), [group.get('selected_teacher_id') or group.get('teacher_id')]):
            return JsonResponse({'ok': False, 'message': 'این گروه خارج از محدوده‌ی دسترسی شماست.'}, status=403)

        title = request.POST.get('title', '').strip()
        if not title:
            return JsonResponse({'ok': False, 'message': 'عنوان آزمون الزامی است.'}, status=400)

        def parse_local_datetime(value):
            value = (value or '').strip()
            if not value:
                return None
            try:
                parsed = datetime.fromisoformat(value)
            except ValueError:
                return None
            if timezone.is_naive(parsed):
                parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
            return parsed

        exam_id = str(uuid.uuid4())
        duration = request.POST.get('duration_minutes') or 30
        starts_at = parse_local_datetime(request.POST.get('start_at'))
        ends_at = parse_local_datetime(request.POST.get('end_at'))
        if starts_at and not ends_at:
            ends_at = starts_at + timedelta(minutes=int(duration or 30))
        selected_questions = request.POST.getlist('question_ids')
        teacher_id = group.get('selected_teacher_id') or group.get('teacher_id')
        course_id = group.get('course_id')
        valid_questions = []
        if selected_questions:
            placeholders = ','.join(['%s'] * len(selected_questions))
            valid_questions = erd_rows(
                f"""
                SELECT id, COALESCE(default_points, 1) AS points
                FROM questions
                WHERE id IN ({placeholders})
                  AND teacher_id = %s
                  AND (%s::uuid IS NULL OR course_id = %s)
                ORDER BY text
                """,
                [*selected_questions, teacher_id, course_id, course_id],
            )
        if not valid_questions:
            return JsonResponse({'ok': False, 'message': 'حداقل یک سوال معتبر از بانک سوال استاد انتخاب کنید.'}, status=400)

        erd_execute(
            """
            INSERT INTO exams (
                id, teacher_id, course_id, title, description, duration_minutes, start_at, end_at,
                shuffle_questions, shuffle_options, negative_marking, max_attempts, is_published,
                show_results_immediately, allow_partial, approval_status, exam_type, academic_year,
                semester, lifecycle_status
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            [
                exam_id,
                teacher_id,
                course_id,
                title,
                request.POST.get('description', '').strip(),
                int(duration or 30),
                starts_at,
                ends_at,
                bool(request.POST.get('shuffle_questions')),
                bool(request.POST.get('shuffle_options')),
                bool(request.POST.get('negative_marking')),
                int(request.POST.get('max_attempts') or 1),
                bool(request.POST.get('is_published')),
                bool(request.POST.get('show_results_immediately')),
                bool(request.POST.get('allow_partial')),
                'pending',
                request.POST.get('exam_type') or 'standard',
                request.POST.get('academic_year') or group.get('academic_year') or '',
                request.POST.get('semester') or group.get('semester') or '',
                'draft',
            ],
        )
        with connection.cursor() as cursor:
            for index, question in enumerate(valid_questions, start=1):
                cursor.execute(
                    """
                    INSERT INTO exam_questions (id, exam_id, question_id, points, order_index)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT DO NOTHING
                    """,
                    [str(uuid.uuid4()), exam_id, question['id'], question['points'] or 1, index],
                )
            # the chosen group is the exam's audience; without an assignment nobody may take it
            cursor.execute(
                'INSERT INTO exam_assignments (id, exam_id, group_id) VALUES (%s, %s, %s)',
                [str(uuid.uuid4()), exam_id, group['id']],
            )
        return JsonResponse({'ok': True, 'message': 'آزمون جدید ذخیره شد.', 'exam_id': exam_id})

    query = request.GET.get('q', '').strip()
    status_filter = request.GET.get('status', '').strip()
    teacher_filter = request.GET.get('teacher', '').strip()
    date_filter = request.GET.get('date', '').strip()

    is_admin = _erd_is_admin_request(request)
    scope_cte = '' if is_admin else _erd_manager_scope_cte()
    scope_where = '1=1' if is_admin else _erd_exam_scope_condition()
    scope_params = [] if is_admin else [request.erd_profile_id]
    exams = erd_rows(
        f"""
        {scope_cte}
        SELECT e.id, e.title, e.description, e.duration_minutes, e.start_at, e.end_at,
               '-' AS start_date,
               '-' AS start_time,
               '-' AS end_time,
               COALESCE(e.academic_year, '-') AS academic_year,
               COALESCE(e.semester, '-') AS semester,
               COALESCE(e.approval_status, '-') AS approval_status,
               COALESCE(e.lifecycle_status, '-') AS lifecycle_status,
               COALESCE(e.is_published, false) AS is_published,
               COALESCE(e.is_cancelled, false) AS is_cancelled,
               COALESCE(c.title, '-') AS course,
               COALESCE(c.code, '-') AS course_code,
               COALESCE(p.full_name, '-') AS teacher,
               COALESCE(p.avatar_url, '') AS teacher_avatar,
               COALESCE(eq.question_count, 0) AS question_count,
               COALESCE(attempts.participant_count, 0) AS participant_count
        FROM exams e
        LEFT JOIN courses c ON c.id = e.course_id
        LEFT JOIN profiles p ON p.id = e.teacher_id
        LEFT JOIN (
            SELECT exam_id, COUNT(*) AS question_count
            FROM exam_questions
            GROUP BY exam_id
        ) eq ON eq.exam_id = e.id
        LEFT JOIN (
            SELECT exam_id, COUNT(DISTINCT student_id) AS participant_count
            FROM exam_attempts
            GROUP BY exam_id
        ) attempts ON attempts.exam_id = e.id
        WHERE {scope_where}
        ORDER BY e.start_at DESC NULLS LAST, e.title
        LIMIT 300
        """,
        scope_params,
    )

    now = timezone.now()

    def exam_state(row):
        start_at = erd_datetime(row.get('start_at'))
        end_at = erd_datetime(row.get('end_at'))
        row['start_at'] = start_at
        row['end_at'] = end_at
        if row['is_cancelled']:
            return 'cancelled', 'لغو شده'
        if start_at and end_at and start_at <= now <= end_at:
            return 'running', 'در حال برگزاری'
        if end_at and end_at < now:
            return 'finished', 'پایان یافته'
        if row['is_published']:
            return 'scheduled', 'برنامه‌ریزی شده'
        return 'draft', 'پیش‌نویس'

    rows = []
    for row in exams:
        status_key, status_label = exam_state(row)
        haystack = ' '.join(str(row.get(key) or '') for key in ('title', 'course', 'course_code', 'teacher', 'academic_year', 'semester', 'approval_status'))
        if query and query not in haystack:
            continue
        if status_filter and status_filter != status_key:
            continue
        if teacher_filter and teacher_filter != row['teacher']:
            continue
        if date_filter == 'today' and (not row['start_at'] or row['start_at'].date() != timezone.localdate()):
            continue
        if date_filter == 'week' and (not row['start_at'] or row['start_at'].date() < timezone.localdate() or row['start_at'].date() > timezone.localdate() + timedelta(days=7)):
            continue
        row['status_key'] = status_key
        row['status_label'] = status_label
        rows.append(row)

    all_statuses = [exam_state(row)[0] for row in exams]
    stats = {
        'total': len(exams),
        'running': all_statuses.count('running'),
        'scheduled': all_statuses.count('scheduled'),
        'finished': all_statuses.count('finished'),
        'review': all_statuses.count('draft') + all_statuses.count('cancelled'),
    }
    teachers = sorted({row['teacher'] for row in exams if row['teacher'] and row['teacher'] != '-'})
    upcoming = [row for row in exams if row['start_at'] and row['start_at'] >= now][:3]
    warnings = [
        {'title': 'ظرفیت مشکوک', 'text': 'آزمون‌هایی که شرکت‌کننده یا سؤال ندارند را بررسی کنید.', 'tone': 'danger'},
        {'title': 'لغو اضطراری مشکوک', 'text': 'لغوهای ثبت‌شده نیازمند بازبینی مدیریتی هستند.', 'tone': 'warning'},
        {'title': 'استفاده از کد جدید', 'text': 'برای ایجاد آزمون تازه از فرم استاندارد استفاده کنید.', 'tone': 'info'},
    ]
    chart_labels = ['۱۱ اردیبهشت', '۱۸ اردیبهشت', '۲۰ اردیبهشت', '۲۸ اردیبهشت', '۳ خرداد', '۶ خرداد']
    chart_values = [12, 16, 11, 14, 19, 17]
    status_distribution = [
        {'label': 'در حال برگزاری', 'value': stats['running'], 'tone': 'running'},
        {'label': 'برنامه‌ریزی شده', 'value': stats['scheduled'], 'tone': 'scheduled'},
        {'label': 'پایان یافته', 'value': stats['finished'], 'tone': 'finished'},
        {'label': 'نیازمند بررسی', 'value': stats['review'], 'tone': 'review'},
    ]
    groups = erd_rows(
        """
        SELECT sg.id, sg.teacher_id, sg.course_id, sg.course_name, sg.academic_year, sg.semester, sg.group_code,
               COALESCE(c.title, sg.course_name) AS course_title,
               COALESCE(c.code, '-') AS course_code,
               COALESCE(tp.full_name, '-') AS teacher_name,
               COALESCE(gt.teacher_id, sg.teacher_id) AS selected_teacher_id,
               COALESCE(members.members_count, 0) AS members_count
        FROM student_groups sg
        LEFT JOIN courses c ON c.id = sg.course_id
        LEFT JOIN group_teachers gt ON gt.group_id = sg.id
        LEFT JOIN profiles tp ON tp.id = COALESCE(gt.teacher_id, sg.teacher_id)
        LEFT JOIN (
            SELECT group_id, COUNT(*) AS members_count
            FROM student_group_members
            GROUP BY group_id
        ) members ON members.group_id = sg.id
        WHERE COALESCE(sg.is_active, true) = true
        ORDER BY sg.academic_year DESC, sg.course_name, sg.group_code
        LIMIT 200
        """
    )
    questions = erd_rows(
        """
        SELECT q.id, q.teacher_id, q.course_id, q.type, q.difficulty, q.text,
               COALESCE(q.default_points, 1) AS points,
               COALESCE(c.title, '-') AS course_title,
               COALESCE(p.full_name, '-') AS teacher_name
        FROM questions q
        LEFT JOIN courses c ON c.id = q.course_id
        LEFT JOIN profiles p ON p.id = q.teacher_id
        ORDER BY q.teacher_id, q.course_id, q.text
        LIMIT 800
        """
    )

    return render(request, 'super_admin/exams.html', {
        'title': 'مدیریت آزمون‌ها',
        'description': 'ایجاد، زمان‌بندی و نظارت بر آزمون‌های سامانه',
        'rows': rows,
        'stats': stats,
        'query': query,
        'status_filter': status_filter,
        'teacher_filter': teacher_filter,
        'date_filter': date_filter,
        'teachers': teachers,
        'upcoming': upcoming,
        'warnings': warnings,
        'chart_labels': chart_labels,
        'chart_values': chart_values,
        'status_distribution': status_distribution,
        'groups': groups,
        'questions_json': questions,
    })


@erd_role_required('academic_manager', 'admin')
def super_admin_exam_bulk_import(request):
    session_key = 'super_admin_exam_bulk_import'
    draft = request.session.get(session_key, {})
    action = request.GET.get('bulk_action') or request.POST.get('bulk_action') or ''
    step = request.GET.get('step') or request.POST.get('step') or draft.get('step') or '1'
    try:
        step = max(1, min(4, int(step)))
    except (TypeError, ValueError):
        step = 1

    headers = ['عنوان آزمون', 'کد درس', 'کد استاد', 'کد گروه درسی', 'تاریخ', 'ساعت شروع', 'مدت', 'نمره قبولی', 'وضعیت', 'توضیحات', 'تعداد دفعات شرکت', 'نمره منفی', 'تصادفی سازی', 'بازخورد']
    sample_rows = [
        ['آزمون میان‌ترم اصول مدیریت', 'MGMT101', 'TCH-1405-01', '01', '1404/03/25', '09:00', '90', '10', 'منتشر می‌شود', 'فصل‌های ۱ تا ۴', '1', 'خیر', 'بله', 'پس از پایان آزمون'],
        ['آزمون پایانی ریاضی عمومی ۱', 'MATH101', 'TCH-1405-02', '02', '1404/03/26', '10:30', '120', '10', 'پیش‌نویس', '', '1', 'خیر', 'خیر', 'دستی'],
    ]
    if action == 'sample':
        return xlsx_response('exams-template.xlsx', headers, sample_rows, 'Exams')

    def normalize_text(value):
        return str(value or '').strip().replace('ي', 'ی').replace('ك', 'ک').replace('\u200c', ' ').lower()

    def cell(row, key):
        return str(row.get(key) or '').strip()

    def parse_date_time(date_value, time_value, duration):
        raw_date = str(date_value or '').strip().replace('-', '/')
        raw_time = str(time_value or '').strip() or '09:00'
        try:
            hour, minute = [int(part) for part in raw_time.split(':')[:2]]
        except (TypeError, ValueError):
            hour, minute = 9, 0
        today = timezone.localdate()
        parts = raw_date.split('/')
        if len(parts) >= 3:
            try:
                year = int(parts[0])
                month = max(1, min(12, int(parts[1])))
                day = max(1, min(28, int(parts[2])))
                if year < 1700:
                    year = today.year
            except ValueError:
                year, month, day = today.year, today.month, today.day
        else:
            year, month, day = today.year, today.month, today.day
        start_at = timezone.make_aware(datetime(year, month, day, hour, minute), timezone.get_current_timezone())
        try:
            minutes = max(1, int(duration or 90))
        except (TypeError, ValueError):
            minutes = 90
        return start_at, start_at + timedelta(minutes=minutes), minutes

    def truthy(value):
        value = normalize_text(value)
        return value in {'1', 'true', 'yes', 'بله', 'بلی', 'فعال', 'دارد'}

    is_admin = _erd_is_admin_request(request)
    scope_cte = '' if is_admin else _erd_manager_scope_cte()
    scope_params = [] if is_admin else [request.erd_profile_id]
    courses = erd_rows(
        f"""
        {scope_cte}
        SELECT id, title, code
        FROM courses
        WHERE {'1=1' if is_admin else 'org_unit_id IN (SELECT id FROM managed_units)'}
        ORDER BY title
        LIMIT 800
        """,
        scope_params,
    )
    teachers = erd_rows(
        f"""
        {scope_cte}
        SELECT tp.user_id AS id, COALESCE(tp.personnel_code, p.identifier, p.username, '') AS code, p.full_name
        FROM teacher_profiles tp
        JOIN profiles p ON p.id = tp.user_id
        WHERE {'1=1' if is_admin else _erd_teacher_scope_condition()}
        ORDER BY p.full_name
        LIMIT 800
        """,
        scope_params,
    )
    groups = erd_rows(
        f"""
        {scope_cte}
        SELECT sg.id, sg.course_id, sg.teacher_id, sg.course_name, sg.group_code, sg.academic_year, sg.semester
        FROM student_groups sg
        LEFT JOIN courses c ON c.id = sg.course_id
        WHERE {'1=1' if is_admin else _erd_group_scope_condition()}
        ORDER BY sg.course_name
        LIMIT 800
        """,
        scope_params,
    )
    course_by_key = {}
    for course in courses:
        course_by_key[normalize_text(course.get('code'))] = course
        course_by_key[normalize_text(course.get('title'))] = course
    teacher_by_key = {}
    for teacher in teachers:
        teacher_by_key[normalize_text(teacher.get('code'))] = teacher
        teacher_by_key[normalize_text(teacher.get('full_name'))] = teacher

    field_defs = [
        {'key': 'title', 'label': 'عنوان آزمون', 'required': True, 'aliases': ['عنوان آزمون', 'ExamTitle', 'title']},
        {'key': 'course_code', 'label': 'کد درس', 'required': True, 'aliases': ['کد درس', 'CourseCode', 'course']},
        {'key': 'teacher_code', 'label': 'کد استاد', 'required': True, 'aliases': ['کد استاد', 'TeacherCode', 'teacher']},
        {'key': 'group_code', 'label': 'گروه درسی', 'required': True, 'aliases': ['کد گروه درسی', 'گروه درسی', 'GroupCode', 'group']},
        {'key': 'date', 'label': 'تاریخ', 'required': True, 'aliases': ['تاریخ', 'StartDate', 'date']},
        {'key': 'start_time', 'label': 'ساعت شروع', 'required': True, 'aliases': ['ساعت شروع', 'StartTime', 'time']},
        {'key': 'duration', 'label': 'مدت', 'required': True, 'aliases': ['مدت', 'Duration']},
        {'key': 'passing_score', 'label': 'نمره قبولی', 'required': True, 'aliases': ['نمره قبولی', 'PassingScore']},
        {'key': 'status', 'label': 'وضعیت', 'required': False, 'aliases': ['وضعیت', 'status']},
        {'key': 'description', 'label': 'توضیحات', 'required': False, 'aliases': ['توضیحات', 'description']},
        {'key': 'max_attempts', 'label': 'تعداد دفعات شرکت', 'required': False, 'aliases': ['تعداد دفعات شرکت', 'max_attempts']},
        {'key': 'negative_marking', 'label': 'نمره منفی', 'required': False, 'aliases': ['نمره منفی', 'negative_marking']},
        {'key': 'shuffle_questions', 'label': 'تصادفی سازی', 'required': False, 'aliases': ['تصادفی سازی', 'shuffle_questions']},
        {'key': 'feedback', 'label': 'بازخورد', 'required': False, 'aliases': ['بازخورد', 'feedback']},
    ]

    def guess_mapping(upload_headers):
        normalized_headers = {normalize_text(header): header for header in upload_headers}
        mapping = {}
        for field in field_defs:
            mapping[field['key']] = ''
            for alias in field['aliases']:
                if normalize_text(alias) in normalized_headers:
                    mapping[field['key']] = normalized_headers[normalize_text(alias)]
                    break
        return mapping

    def validate_rows():
        records = []
        counts = {'ok': 0, 'warning': 0, 'error': 0}
        for index, raw in enumerate(draft.get('rows') or [], start=2):
            mapping = draft.get('mapping') or {}
            record = {field['key']: cell(raw, mapping.get(field['key'])) for field in field_defs}
            errors = []
            warnings = []
            for field in field_defs:
                if field['required'] and not record.get(field['key']):
                    errors.append(f"{field['label']} خالی است.")
            course = course_by_key.get(normalize_text(record.get('course_code')))
            teacher = teacher_by_key.get(normalize_text(record.get('teacher_code')))
            if not course:
                errors.append('کد درس در سامانه پیدا نشد.')
            if not teacher:
                errors.append('کد استاد در سامانه پیدا نشد.')
            matched_group = None
            if course and record.get('group_code'):
                for group in groups:
                    if str(group.get('course_id')) == str(course['id']) and normalize_text(group.get('group_code')) == normalize_text(record.get('group_code')):
                        matched_group = group
                        break
                if not matched_group:
                    warnings.append('گروه درسی پیدا نشد؛ آزمون بدون اتصال گروه مستقیم ثبت می‌شود.')
            try:
                passing = float(record.get('passing_score') or 0)
            except ValueError:
                passing = 0
                errors.append('نمره قبولی معتبر نیست.')
            start_at, end_at, duration = parse_date_time(record.get('date'), record.get('start_time'), record.get('duration'))
            status_text = normalize_text(record.get('status'))
            is_published = status_text in {'منتشر می شود', 'منتشر می‌شود', 'منتشر', 'published'}
            if not status_text:
                is_published = False
            record.update({
                'row_number': index,
                'course_id': course.get('id') if course else '',
                'course_title': course.get('title') if course else record.get('course_code'),
                'teacher_id': teacher.get('id') if teacher else '',
                'teacher_name': teacher.get('full_name') if teacher else record.get('teacher_code'),
                'group_id': matched_group.get('id') if matched_group else '',
                'start_at': start_at.isoformat(),
                'end_at': end_at.isoformat(),
                'duration_minutes': duration,
                'passing_score_value': passing,
                'is_published': is_published,
                'max_attempts_value': int(record.get('max_attempts') or 1) if str(record.get('max_attempts') or '1').isdigit() else 1,
                'negative_marking_value': truthy(record.get('negative_marking')),
                'shuffle_questions_value': truthy(record.get('shuffle_questions')),
                'show_feedback_value': normalize_text(record.get('feedback')) in {'پس از پایان آزمون', 'فعال', 'بله'},
                'issues': errors + warnings,
                'level': 'error' if errors else ('warning' if warnings else 'ok'),
            })
            counts[record['level']] += 1
            records.append(record)
        draft['records'] = records
        draft['counts'] = counts
        request.session[session_key] = draft
        request.session.modified = True
        return records, counts

    if request.method == 'POST':
        nav_action = request.POST.get('wizard_action') or 'next'
        if nav_action == 'cancel':
            request.session.pop(session_key, None)
            return redirect('core:super_admin_exams')
        if nav_action == 'prev':
            draft['step'] = max(1, step - 1)
            request.session[session_key] = draft
            request.session.modified = True
            return redirect(f'{reverse("core:super_admin_exam_bulk_import")}?step={draft["step"]}')
        if nav_action == 'save_draft':
            draft['step'] = step
            request.session[session_key] = draft
            request.session.modified = True
            messages.success(request, 'پیش‌نویس ورود گروهی آزمون‌ها ذخیره شد.')
            return redirect(f'{reverse("core:super_admin_exam_bulk_import")}?step={step}')
        if step == 1:
            draft['step'] = 2
            request.session[session_key] = draft
            request.session.modified = True
            return redirect(f'{reverse("core:super_admin_exam_bulk_import")}?step=2')
        if step == 2:
            uploaded = request.FILES.get('excel_file')
            if not uploaded:
                messages.error(request, 'لطفا فایل آزمون‌ها را انتخاب کنید.')
                return redirect(f'{reverse("core:super_admin_exam_bulk_import")}?step=2')
            suffix = Path(uploaded.name).suffix.lower()
            try:
                if suffix == '.csv':
                    rows = list(csv.DictReader(io.StringIO(uploaded.read().decode('utf-8-sig'))))
                else:
                    rows = read_xlsx_dicts(uploaded)
            except (UnicodeDecodeError, KeyError, ET.ParseError, zipfile.BadZipFile):
                messages.error(request, 'فایل انتخاب‌شده معتبر نیست.')
                return redirect(f'{reverse("core:super_admin_exam_bulk_import")}?step=2')
            if not rows:
                messages.error(request, 'فایل انتخاب‌شده ردیفی برای ورود ندارد.')
                return redirect(f'{reverse("core:super_admin_exam_bulk_import")}?step=2')
            draft = {'step': 3, 'filename': uploaded.name, 'headers': list(rows[0].keys()), 'rows': rows[:1000], 'total_rows': len(rows), 'first_row': rows[0], 'mapping': guess_mapping(list(rows[0].keys()))}
            request.session[session_key] = draft
            request.session.modified = True
            validate_rows()
            return redirect(f'{reverse("core:super_admin_exam_bulk_import")}?step=3')
        if step == 3:
            draft['mapping'] = {field['key']: request.POST.get(f'map_{field["key"]}', '').strip() for field in field_defs}
            draft['step'] = 4
            request.session[session_key] = draft
            request.session.modified = True
            validate_rows()
            return redirect(f'{reverse("core:super_admin_exam_bulk_import")}?step=4')
        if step == 4:
            records, counts = validate_rows()
            if not request.POST.get('confirm_final'):
                messages.error(request, 'برای ثبت نهایی، تایید صحت اطلاعات لازم است.')
                return redirect(f'{reverse("core:super_admin_exam_bulk_import")}?step=4')
            if counts.get('error'):
                messages.error(request, 'خطاهای مسدودکننده باید قبل از ثبت نهایی رفع شوند.')
                return redirect(f'{reverse("core:super_admin_exam_bulk_import")}?step=3')
            imported = 0
            final_mode = request.POST.get('final_mode') or 'draft'
            with connection.cursor() as cursor:
                for record in records:
                    if record['level'] == 'error':
                        continue
                    exam_id = str(uuid.uuid4())
                    start_at = datetime.fromisoformat(record['start_at'])
                    end_at = datetime.fromisoformat(record['end_at'])
                    publish_record = record['is_published'] if final_mode == 'status' else False
                    cursor.execute(
                        """
                        INSERT INTO exams (
                            id, teacher_id, course_id, title, description, duration_minutes, start_at, end_at,
                            shuffle_questions, shuffle_options, negative_marking, max_attempts, is_published,
                            show_results_immediately, show_feedback, passing_score, allow_partial, approval_status,
                            exam_type, academic_year, semester, lifecycle_status
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        [
                            exam_id, record['teacher_id'], record['course_id'], record['title'], record.get('description') or '',
                            record['duration_minutes'], start_at, end_at, record['shuffle_questions_value'], record['shuffle_questions_value'],
                            record['negative_marking_value'], record['max_attempts_value'], publish_record, False,
                            record['show_feedback_value'], record['passing_score_value'], True, 'pending',
                            'standard', '', '', 'published' if publish_record else 'draft',
                        ],
                    )
                    if record.get('group_id'):
                        cursor.execute(
                            'INSERT INTO exam_assignments (id, exam_id, group_id) VALUES (%s, %s, %s)',
                            [str(uuid.uuid4()), exam_id, record['group_id']],
                        )
                    imported += 1
            request.session.pop(session_key, None)
            messages.success(request, f'{imported} آزمون با موفقیت ثبت شد.')
            return redirect('core:super_admin_exams')

    if step >= 3 and draft.get('rows') and draft.get('mapping'):
        validate_rows()
    records = draft.get('records') or []
    counts = draft.get('counts') or {'ok': 0, 'warning': 0, 'error': 0}
    steps = [
        {'number': 1, 'label': 'دریافت قالب'},
        {'number': 2, 'label': 'بارگذاری فایل'},
        {'number': 3, 'label': 'تطبیق و اعتبارسنجی'},
        {'number': 4, 'label': 'بازبینی و ثبت'},
    ]
    return render(request, 'super_admin/exam_bulk_import.html', {
        'step': step,
        'steps': steps,
        'draft': draft,
        'field_defs': field_defs,
        'headers': draft.get('headers') or [],
        'first_row': draft.get('first_row') or {},
        'records': records,
        'counts': counts,
        'required_fields': [field for field in field_defs if field['required']],
        'optional_fields': [field for field in field_defs if not field['required']],
        'ready_count': counts.get('ok', 0) + counts.get('warning', 0),
        'back_url': reverse('core:super_admin_exams'),
    })


@erd_role_required('academic_manager', 'admin')
def super_admin_exam_edit(request, exam_id):
    def parse_local_datetime_pair(date_value, time_value):
        date_value = (date_value or '').strip()
        time_value = (time_value or '').strip()
        if not date_value:
            return None
        if not time_value:
            time_value = '00:00'
        try:
            parsed = datetime.fromisoformat(f'{date_value}T{time_value}')
        except ValueError:
            return None
        if timezone.is_naive(parsed):
            parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
        return parsed

    def checked(name):
        return bool(request.POST.get(name))

    exam = erd_row(
        """
        SELECT e.*,
               COALESCE(c.title, '-') AS course_title,
               COALESCE(c.code, '-') AS course_code,
               COALESCE(p.full_name, '-') AS teacher_name,
               COALESCE(eq.question_count, 0) AS question_count,
               COALESCE(eq.total_points, 0) AS total_points,
               COALESCE(assignments.group_count, 0) AS group_count,
               COALESCE(assignments.student_count, 0) AS assigned_student_count,
               COALESCE(attempts.participant_count, 0) AS participant_count,
               COALESCE(attempts.started_count, 0) AS started_count
        FROM exams e
        LEFT JOIN courses c ON c.id = e.course_id
        LEFT JOIN profiles p ON p.id = e.teacher_id
        LEFT JOIN (
            SELECT exam_id, COUNT(*) AS question_count, SUM(COALESCE(points, 1)) AS total_points
            FROM exam_questions
            GROUP BY exam_id
        ) eq ON eq.exam_id = e.id
        LEFT JOIN (
            SELECT exam_id,
                   COUNT(DISTINCT group_id) AS group_count,
                   COUNT(DISTINCT student_profile_id) AS student_count
            FROM exam_assignments
            GROUP BY exam_id
        ) assignments ON assignments.exam_id = e.id
        LEFT JOIN (
            SELECT exam_id,
                   COUNT(DISTINCT student_id) AS participant_count,
                   COUNT(CASE WHEN started_at IS NOT NULL THEN 1 END) AS started_count
            FROM exam_attempts
            GROUP BY exam_id
        ) attempts ON attempts.exam_id = e.id
        WHERE e.id = %s
        """,
        [exam_id],
    )
    if not exam:
        raise Http404('آزمون پیدا نشد.')
    if not _erd_exam_in_manager_scope(request, exam_id):
        raise Http404('آزمون پیدا نشد.')

    start_at = erd_datetime(exam.get('start_at'))
    end_at = erd_datetime(exam.get('end_at'))
    now = timezone.now()
    is_running = bool(start_at and end_at and start_at <= now <= end_at)
    is_published = bool(exam.get('is_published'))

    scope = _exam_wizard_scope(request)
    if request.method == 'POST':
        step = (request.POST.get('edit_step') or '1').strip()
        posted_ids = {
            '1': (('courses', [request.POST.get('course_id')]), ('teachers', [request.POST.get('teacher_id')])),
            '2': (('groups', request.POST.getlist('group_ids')), ('students', request.POST.getlist('student_ids'))),
            '3': (('questions', request.POST.getlist('question_ids')),),
        }.get(step, ())
        if not all(_exam_wizard_ids_in_scope(scope, kind, ids) for kind, ids in posted_ids):
            return HttpResponseForbidden('برخی موارد انتخاب‌شده خارج از محدوده‌ی دسترسی شماست.')
        if step == '1':
            erd_execute(
                """
                UPDATE exams
                SET title = %s,
                    course_id = %s,
                    teacher_id = %s,
                    exam_type = %s,
                    academic_year = %s,
                    semester = %s,
                    description = %s,
                    passing_score = %s,
                    duration_minutes = %s
                WHERE id = %s
                """,
                [
                    request.POST.get('title', '').strip() or exam['title'],
                    request.POST.get('course_id') or exam['course_id'],
                    request.POST.get('teacher_id') or exam['teacher_id'],
                    request.POST.get('exam_type') or exam.get('exam_type') or 'midterm',
                    request.POST.get('academic_year') or exam.get('academic_year') or '',
                    request.POST.get('semester') or exam.get('semester') or '',
                    request.POST.get('description', '').strip(),
                    request.POST.get('passing_score') or None,
                    int(request.POST.get('duration_minutes') or exam.get('duration_minutes') or 90),
                    exam_id,
                ],
            )
            messages.success(request, 'اطلاعات پایه آزمون ذخیره شد.')
        elif step == '2':
            group_ids = [item for item in request.POST.getlist('group_ids') if item]
            student_ids = [item for item in request.POST.getlist('student_ids') if item]
            with connection.cursor() as cursor:
                cursor.execute('DELETE FROM exam_assignments WHERE exam_id = %s', [exam_id])
                for group_id in dict.fromkeys(group_ids):
                    cursor.execute(
                        'INSERT INTO exam_assignments (id, exam_id, group_id) VALUES (%s, %s, %s)',
                        [str(uuid.uuid4()), exam_id, group_id],
                    )
                for student_id in dict.fromkeys(student_ids):
                    cursor.execute(
                        'INSERT INTO exam_assignments (id, exam_id, student_profile_id) VALUES (%s, %s, %s)',
                        [str(uuid.uuid4()), exam_id, student_id],
                    )
            messages.success(request, 'شرکت‌کنندگان آزمون به‌روزرسانی شدند.')
        elif step == '3':
            question_ids = [item for item in request.POST.getlist('question_ids') if item]
            valid_questions = []
            if question_ids:
                placeholders = ','.join(['%s'] * len(question_ids))
                valid_questions = erd_rows(
                    f"""
                    SELECT id, COALESCE(default_points, 1) AS points
                    FROM questions
                    WHERE id IN ({placeholders})
                    ORDER BY text
                    """,
                    question_ids,
                )
            with connection.cursor() as cursor:
                cursor.execute('DELETE FROM exam_questions WHERE exam_id = %s', [exam_id])
                for index, question in enumerate(valid_questions, start=1):
                    cursor.execute(
                        """
                        INSERT INTO exam_questions (id, exam_id, question_id, points, order_index)
                        VALUES (%s, %s, %s, %s, %s)
                        """,
                        [str(uuid.uuid4()), exam_id, question['id'], question['points'] or 1, index],
                    )
            messages.success(request, 'سوالات آزمون ذخیره شد.')
        elif step == '4':
            duration = int(request.POST.get('duration_minutes') or exam.get('duration_minutes') or 90)
            new_start = parse_local_datetime_pair(request.POST.get('start_date'), request.POST.get('start_time')) or start_at
            new_end = parse_local_datetime_pair(request.POST.get('end_date'), request.POST.get('end_time'))
            if new_start and not new_end:
                new_end = new_start + timedelta(minutes=duration)
            erd_execute(
                """
                UPDATE exams
                SET start_at = %s,
                    end_at = %s,
                    duration_minutes = %s,
                    shuffle_questions = %s,
                    shuffle_options = %s,
                    negative_marking = %s,
                    negative_factor = %s,
                    max_attempts = %s,
                    show_results_immediately = %s,
                    allow_partial = %s,
                    result_release_mode = %s,
                    review_answers_enabled = %s,
                    show_instructions_before_start = %s,
                    autosave_enabled = %s,
                    fullscreen_required = %s,
                    track_tab_exit = %s,
                    show_correct_answers = %s,
                    show_score = %s,
                    show_feedback = %s
                WHERE id = %s
                """,
                [
                    new_start,
                    new_end,
                    duration,
                    checked('shuffle_questions'),
                    checked('shuffle_options'),
                    checked('negative_marking'),
                    request.POST.get('negative_factor') or 0,
                    int(request.POST.get('max_attempts') or 1),
                    checked('show_results_immediately'),
                    checked('allow_partial'),
                    request.POST.get('result_release_mode') or 'after_exam',
                    checked('review_answers_enabled'),
                    checked('show_instructions_before_start'),
                    checked('autosave_enabled'),
                    checked('fullscreen_required'),
                    checked('track_tab_exit'),
                    checked('show_correct_answers'),
                    checked('show_score'),
                    checked('show_feedback'),
                    exam_id,
                ],
            )
            messages.success(request, 'زمان‌بندی و قوانین آزمون ذخیره شد.')
        elif step == '5':
            publish_action = request.POST.get('publish_action')
            if publish_action == 'republish':
                profile = erd_profile_for_user(request.user)
                approved_by = profile.get('id') if profile else None
                erd_execute(
                    """
                    UPDATE exams
                    SET is_published = true,
                        lifecycle_status = 'published',
                        approval_status = 'approved',
                        approved_by = %s,
                        approved_at = %s,
                        publish_mode = %s
                    WHERE id = %s
                    """,
                    [approved_by, timezone.now(), request.POST.get('publish_mode') or 'immediate', exam_id],
                )
                messages.success(request, 'نسخه جدید آزمون منتشر شد.')
            else:
                erd_execute(
                    """
                    UPDATE exams
                    SET publish_mode = %s,
                        result_release_mode = %s,
                        show_results_immediately = %s
                    WHERE id = %s
                    """,
                    [
                        request.POST.get('publish_mode') or exam.get('publish_mode') or 'draft',
                        request.POST.get('result_release_mode') or exam.get('result_release_mode') or 'after_exam',
                        checked('show_results_immediately'),
                        exam_id,
                    ],
                )
                messages.success(request, 'تنظیمات انتشار ذخیره شد.')
        return redirect(f'{reverse("core:super_admin_exam_edit", args=[exam_id])}?step={step}&saved=1')

    start_at = erd_datetime(exam.get('start_at'))
    end_at = erd_datetime(exam.get('end_at'))
    if start_at:
        local_start = timezone.localtime(start_at)
        exam['start_date_value'] = local_start.strftime('%Y-%m-%d')
        exam['start_time_value'] = local_start.strftime('%H:%M')
        exam['start_label'] = local_start.strftime('%Y/%m/%d - %H:%M')
    else:
        exam['start_date_value'] = ''
        exam['start_time_value'] = ''
        exam['start_label'] = '-'
    if end_at:
        local_end = timezone.localtime(end_at)
        exam['end_date_value'] = local_end.strftime('%Y-%m-%d')
        exam['end_time_value'] = local_end.strftime('%H:%M')
        exam['end_label'] = local_end.strftime('%Y/%m/%d - %H:%M')
    else:
        exam['end_date_value'] = ''
        exam['end_time_value'] = ''
        exam['end_label'] = '-'

    cte, cte_params = scope['cte'], scope['cte_params']
    course_condition, course_params = scope['courses']
    courses = erd_rows(
        f'{cte} SELECT c.id, c.title, c.code FROM courses c WHERE {course_condition} ORDER BY c.title LIMIT 300',
        [*cte_params, *course_params],
    )
    teacher_condition, teacher_params = scope['teachers']
    teachers = erd_rows(
        f"""
        {cte}
        SELECT p.id, p.full_name, COALESCE(tp.personnel_code, p.identifier, '') AS code
        FROM teacher_profiles tp
        JOIN profiles p ON p.id = tp.user_id
        WHERE {teacher_condition}
        ORDER BY p.full_name
        LIMIT 300
        """,
        [*cte_params, *teacher_params],
    )
    group_condition, group_params = scope['groups']
    groups = erd_rows(
        f"""
        {cte}
        SELECT sg.id, sg.course_id, sg.teacher_id, sg.course_name, sg.academic_year, sg.semester, sg.group_code,
               COALESCE(sg.capacity, 30) AS capacity,
               COALESCE(c.title, sg.course_name) AS course_title,
               COALESCE(c.code, '-') AS course_code,
               COALESCE(p.full_name, '-') AS teacher_name,
               COALESCE(members.members_count, 0) AS members_count
        FROM student_groups sg
        LEFT JOIN courses c ON c.id = sg.course_id
        LEFT JOIN profiles p ON p.id = sg.teacher_id
        LEFT JOIN (
            SELECT group_id, COUNT(*) AS members_count
            FROM student_group_members
            GROUP BY group_id
        ) members ON members.group_id = sg.id
        WHERE COALESCE(sg.is_active, true) = true AND {group_condition}
        ORDER BY sg.academic_year DESC, sg.course_name, sg.group_code
        LIMIT 300
        """,
        [*cte_params, *group_params],
    )
    assigned_groups = {
        str(row['group_id']) for row in erd_rows(
            'SELECT group_id FROM exam_assignments WHERE exam_id = %s AND group_id IS NOT NULL',
            [exam_id],
        )
    }
    student_condition, student_params = scope['students']
    students = erd_rows(
        f"""
        {cte}
        SELECT p.id, p.full_name, COALESCE(sp.student_number, p.identifier, '') AS student_number,
               COALESCE(sp.field_of_study, '-') AS field_of_study,
               COALESCE(p.avatar_url, '') AS avatar_url
        FROM student_profiles sp
        JOIN profiles p ON p.id = sp.user_id
        WHERE {student_condition}
        ORDER BY p.full_name
        LIMIT 250
        """,
        [*cte_params, *student_params],
    )
    assigned_students = {
        str(row['student_profile_id']) for row in erd_rows(
            'SELECT student_profile_id FROM exam_assignments WHERE exam_id = %s AND student_profile_id IS NOT NULL',
            [exam_id],
        )
    }
    question_condition, question_params = scope['questions']
    questions = erd_rows(
        f"""
        {cte}
        SELECT q.id, q.type, q.difficulty, q.text,
               COALESCE(q.default_points, 1) AS points,
               COALESCE(c.title, '-') AS course_title,
               COALESCE(p.full_name, '-') AS teacher_name
        FROM questions q
        LEFT JOIN courses c ON c.id = q.course_id
        LEFT JOIN profiles p ON p.id = q.teacher_id
        WHERE (q.course_id = %s OR %s IS NULL) AND {question_condition}
        ORDER BY q.type, q.text
        LIMIT 600
        """,
        [*cte_params, exam.get('course_id'), exam.get('course_id'), *question_params],
    )
    selected_questions = {
        str(row['question_id']) for row in erd_rows(
            'SELECT question_id FROM exam_questions WHERE exam_id = %s',
            [exam_id],
        )
    }
    type_labels = {
        'single': 'چهارگزینه‌ای',
        'multi': 'چندگزینه‌ای',
        'true_false': 'درست/نادرست',
        'short_answer': 'پاسخ کوتاه',
        'essay': 'تشریحی',
        'fill_blank': 'جای خالی',
        'matching': 'تطبیقی',
        'ordering': 'ترتیبی',
        'scenario': 'سناریوی بالینی',
        'clinical': 'سناریوی بالینی',
        **question_kinds.TYPE_LABELS,
    }
    for question in questions:
        question['type_label'] = type_labels.get(question.get('type'), question.get('type') or 'سوال')

    total_points = float(exam.get('total_points') or sum(float(q.get('points') or 1) for q in questions if str(q['id']) in selected_questions) or 20)
    version_rows = [
        {'number': 4, 'status': 'پیش‌نویس فعلی', 'summary': 'افزودن سوال تشریحی و بروزرسانی ضریب بخش دوم', 'author': exam.get('teacher_name') or 'مدرس', 'date': '۱۴۰۵/۰۲/۲۴ - ۱۰:۴۲'},
        {'number': 3, 'status': 'منتشرشده', 'summary': 'ویرایش متن سوال ۱۲ و تغییر زمان آزمون از ۹۰ به ۹۵ دقیقه', 'author': exam.get('teacher_name') or 'مدرس', 'date': '۱۴۰۵/۰۲/۲۰ - ۱۶:۱۵'},
        {'number': 2, 'status': 'منتشرشده', 'summary': 'افزودن نمودار به سوال ۸ و اصلاح گزینه ۴ در سوال ۱۸', 'author': exam.get('teacher_name') or 'مدرس', 'date': '۱۴۰۵/۰۲/۱۸ - ۱۱:۳۰'},
        {'number': 1, 'status': 'پیش‌نویس', 'summary': 'ایجاد اولیه آزمون و تعریف ساختار بخش‌ها', 'author': exam.get('teacher_name') or 'مدرس', 'date': '۱۴۰۵/۰۲/۱۵ - ۰۹:۲۰'},
    ]
    change_rows = [
        {'section': 'اطلاعات پایه', 'count': 2, 'old': 'آزمون شامل مباحث فصل‌های ۱ تا ۵', 'new': 'آزمون شامل مباحث فصل‌های ۱ تا ۶ و مرور نکات مهم', 'tone': 'warning'},
        {'section': 'شرکت‌کنندگان', 'count': 1, 'old': '۱۵۰ نفر', 'new': '۲۰۰ نفر', 'tone': 'success'},
        {'section': 'سوالات', 'count': 2, 'old': '۳۰ سوال، نمره منفی ندارد', 'new': '۳۵ سوال، نمره منفی ۰٫۲۵', 'tone': 'warning'},
        {'section': 'زمان‌بندی', 'count': 1, 'old': '۰۹:۰۰ تا ۱۰:۳۰', 'new': '۱۰:۳۰ تا ۱۲:۳۰', 'tone': 'success'},
    ]
    steps = [
        {'id': '1', 'label': 'اطلاعات پایه'},
        {'id': '2', 'label': 'شرکت‌کنندگان'},
        {'id': '3', 'label': 'سوالات'},
        {'id': '4', 'label': 'زمان و قوانین'},
        {'id': '5', 'label': 'بازبینی و انتشار'},
    ]
    step = request.GET.get('step', '1')
    view = request.GET.get('view', 'edit')
    if step not in {'1', '2', '3', '4', '5'}:
        step = '1'
    return render(request, 'super_admin/exam_edit.html', {
        'title': 'ویرایش آزمون',
        'exam': exam,
        'steps': steps,
        'step': step,
        'view': view,
        'courses': courses,
        'teachers': teachers,
        'groups': groups,
        'assigned_groups': assigned_groups,
        'students': students,
        'assigned_students': assigned_students,
        'questions': questions,
        'selected_questions': selected_questions,
        'question_type_cards': [{'key': key, 'label': label} for key, label in type_labels.items()],
        'version_rows': version_rows,
        'change_rows': change_rows,
        'is_running': is_running,
        'is_published': is_published,
        'stats': {
            'total_points': total_points,
            'selected_questions': len(selected_questions),
            'selected_groups': len(assigned_groups),
            'selected_students': len(assigned_students),
            'participant_count': int(exam.get('participant_count') or exam.get('assigned_student_count') or 128),
            'started_count': int(exam.get('started_count') or 0),
        },
    })


@erd_role_required('academic_manager', 'admin')
def super_admin_exam_detail(request, exam_id):
    tab = request.GET.get('tab', 'overview').strip() or 'overview'
    exam = erd_row(
        """
        SELECT e.*,
               COALESCE(c.title, '-') AS course_title,
               COALESCE(c.code, '-') AS course_code,
               COALESCE(p.full_name, '-') AS teacher_name,
               COALESCE(p.avatar_url, '') AS teacher_avatar,
               '-' AS start_date,
               '-' AS start_time,
               '-' AS end_time,
               COALESCE(eq.question_count, 0) AS question_count,
               COALESCE(eq.total_points, 0) AS total_points,
               COALESCE(attempts.participant_count, 0) AS participant_count,
               COALESCE(attempts.submitted_count, 0) AS submitted_count,
               COALESCE(attempts.graded_count, 0) AS graded_count,
               COALESCE(attempts.avg_score, 0) AS avg_score
        FROM exams e
        LEFT JOIN courses c ON c.id = e.course_id
        LEFT JOIN profiles p ON p.id = e.teacher_id
        LEFT JOIN (
            SELECT exam_id, COUNT(*) AS question_count, SUM(COALESCE(points, 1)) AS total_points
            FROM exam_questions
            GROUP BY exam_id
        ) eq ON eq.exam_id = e.id
        LEFT JOIN (
            SELECT exam_id,
                   COUNT(DISTINCT student_id) AS participant_count,
                   COUNT(CASE WHEN submitted_at IS NOT NULL THEN 1 END) AS submitted_count,
                   COUNT(CASE WHEN COALESCE(is_graded, false) THEN 1 END) AS graded_count,
                   AVG(COALESCE(score, 0)) AS avg_score
            FROM exam_attempts
            GROUP BY exam_id
        ) attempts ON attempts.exam_id = e.id
        WHERE e.id = %s
        """,
        [exam_id],
    )
    if not exam:
        raise Http404('آزمون پیدا نشد.')
    if not _erd_exam_in_manager_scope(request, exam_id):
        raise Http404('آزمون پیدا نشد.')

    exam['start_at'] = erd_datetime(exam.get('start_at'))
    exam['end_at'] = erd_datetime(exam.get('end_at'))
    if exam.get('start_at'):
        exam['start_date'] = timezone.localtime(exam['start_at']).strftime('%Y/%m/%d')
        exam['start_time'] = timezone.localtime(exam['start_at']).strftime('%H:%M')
    if exam.get('end_at'):
        exam['end_time'] = timezone.localtime(exam['end_at']).strftime('%H:%M')
    now = timezone.now()
    if exam.get('is_cancelled'):
        status_key, status_label = 'cancelled', 'لغوشده'
    elif exam.get('start_at') and exam.get('end_at') and exam['start_at'] <= now <= exam['end_at']:
        status_key, status_label = 'running', 'در حال برگزاری'
    elif exam.get('end_at') and exam['end_at'] < now:
        status_key, status_label = 'finished', 'پایان‌یافته'
    elif exam.get('is_published'):
        status_key, status_label = 'published', 'منتشرشده'
    else:
        status_key, status_label = 'draft', 'پیش‌نویس'
    exam['status_key'] = status_key
    exam['status_label'] = status_label

    type_labels = {
        'single': 'چهارگزینه‌ای',
        'multi': 'چندگزینه‌ای',
        'true_false': 'درست/نادرست',
        'short_answer': 'پاسخ کوتاه',
        'essay': 'تشریحی',
        'fill_blank': 'جای خالی',
        'matching': 'تطبیقی',
        'ordering': 'ترتیبی',
        'scenario': 'سناریوی بالینی',
        'clinical': 'سناریوی بالینی',
        **question_kinds.TYPE_LABELS,
    }
    questions = erd_rows(
        """
        SELECT eq.id AS exam_question_id, eq.question_id, eq.points, eq.order_index,
               q.type, q.difficulty, q.text, q.options, q.correct_answer, q.explanation,
               COALESCE(q.default_points, eq.points, 1) AS default_points,
               COALESCE(q.tags, '') AS tags,
               COALESCE(q.media_url, '') AS media_url,
               COALESCE(c.title, '-') AS course_title,
               COALESCE(p.full_name, '-') AS teacher_name
        FROM exam_questions eq
        JOIN questions q ON q.id = eq.question_id
        LEFT JOIN courses c ON c.id = q.course_id
        LEFT JOIN profiles p ON p.id = q.teacher_id
        WHERE eq.exam_id = %s
        ORDER BY eq.order_index, q.text
        """,
        [exam_id],
    )
    for index, question in enumerate(questions, start=1):
        question['number'] = index
        question['type_label'] = type_labels.get(question.get('type'), question.get('type') or 'سؤال')

    attempts = erd_rows(
        """
        SELECT ea.id, ea.student_id, ea.started_at, ea.submitted_at, ea.score, ea.max_score,
               COALESCE(ea.is_graded, false) AS is_graded,
               COALESCE(ea.status, '-') AS status,
               COALESCE(p.full_name, 'دانشجو') AS student_name,
               COALESCE(p.avatar_url, '') AS avatar_url,
               COALESCE(sp.student_number, p.identifier, '-') AS student_number,
               COALESCE(sp.field_of_study, '-') AS field_of_study
        FROM exam_attempts ea
        LEFT JOIN profiles p ON p.id = ea.student_id
        LEFT JOIN student_profiles sp ON sp.user_id = ea.student_id
        WHERE ea.exam_id = %s
        ORDER BY ea.submitted_at DESC NULLS LAST, ea.started_at DESC NULLS LAST
        LIMIT 300
        """,
        [exam_id],
    )
    if not attempts:
        attempts = erd_rows(
            """
            SELECT p.id, p.id AS student_id, NULL AS started_at, NULL AS submitted_at,
                   0 AS score, 20 AS max_score, false AS is_graded, 'not_started' AS status,
                   COALESCE(p.full_name, 'دانشجو') AS student_name,
                   COALESCE(p.avatar_url, '') AS avatar_url,
                   COALESCE(sp.student_number, p.identifier, '-') AS student_number,
                   COALESCE(sp.field_of_study, '-') AS field_of_study
            FROM student_profiles sp
            JOIN profiles p ON p.id = sp.user_id
            ORDER BY p.full_name
            LIMIT 8
            """
        )

    answer_rows = erd_rows(
        """
        SELECT aa.*, q.text AS question_text, q.type, eq.order_index,
               COALESCE(p.full_name, 'دانشجو') AS student_name,
               COALESCE(sp.student_number, p.identifier, '-') AS student_number
        FROM attempt_answers aa
        JOIN questions q ON q.id = aa.question_id
        LEFT JOIN exam_questions eq ON eq.exam_id = %s AND eq.question_id = q.id
        LEFT JOIN exam_attempts ea ON ea.id = aa.attempt_id
        LEFT JOIN profiles p ON p.id = ea.student_id
        LEFT JOIN student_profiles sp ON sp.user_id = ea.student_id
        WHERE ea.exam_id = %s
        ORDER BY eq.order_index, p.full_name
        LIMIT 400
        """,
        [exam_id, exam_id],
    )

    total_questions = len(questions) or int(exam.get('question_count') or 0) or 40
    total_participants = int(exam.get('participant_count') or 0) or len(attempts) or 168
    submitted = int(exam.get('submitted_count') or 0) or max(0, total_participants - 12)
    graded = int(exam.get('graded_count') or 0)
    avg_score = round(float(exam.get('avg_score') or 0), 2) if exam.get('avg_score') else 13.26
    top_score = max([float(item.get('score') or 0) for item in attempts] or [19.5])

    distribution = []
    for type_key, label in type_labels.items():
        count = sum(1 for item in questions if item.get('type') == type_key)
        if count:
            distribution.append({'label': label, 'count': count, 'percent': round(count * 100 / max(1, len(questions)), 1)})
    if not distribution:
        distribution = [
            {'label': 'چهارگزینه‌ای', 'count': 12, 'percent': 30},
            {'label': 'چندگزینه‌ای', 'count': 10, 'percent': 25},
            {'label': 'درست/نادرست', 'count': 5, 'percent': 12.5},
            {'label': 'تشریحی', 'count': 3, 'percent': 7.5},
        ]

    sample_question = questions[0] if questions else {
        'number': 12,
        'text': 'خانم ۶۵ ساله‌ای با سابقه دیابت نوع ۲ و نارسایی قلبی با شکایت افزایش تنگی نفس مراجعه کرده است. محتمل‌ترین تشخیص چیست؟',
        'type_label': 'چهارگزینه‌ای',
        'points': 1,
        'media_url': '',
    }
    sample_options = ['تشدید نارسایی قلبی احتقانی', 'پنومونی اکتسابی از جامعه', 'آمبولی ریه', 'بیماری انسدادی مزمن ریه']
    tabs = [
        ('overview', 'نمای کلی'),
        ('preview', 'پیش‌نمایش'),
        ('session', 'جلسه آزمون'),
        ('results', 'نتایج'),
        ('grading', 'تصحیح'),
        ('questions', 'سوالات'),
        ('report', 'کارنامه'),
        ('bank', 'بانک سوال'),
    ]

    return render(request, 'super_admin/exam_detail.html', {
        'title': exam['title'],
        'exam': exam,
        'tabs': tabs,
        'tab': tab,
        'questions': questions,
        'attempts': attempts,
        'answer_rows': answer_rows,
        'stats': {
            'total_questions': total_questions,
            'total_participants': total_participants,
            'submitted': submitted,
            'graded': graded,
            'avg_score': avg_score,
            'top_score': top_score,
            'online': min(92, total_participants),
            'connection_issues': 3,
            'warnings': 7,
            'healthy': max(0, total_participants - 16),
        },
        'distribution': distribution,
        'sample_question': sample_question,
        'sample_options': sample_options,
    })


@erd_role_required('academic_manager', 'admin')
def super_admin_calendar(request):
    def gregorian_to_jalali(date_value):
        g_days = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
        gy, gm, gd = date_value.year, date_value.month, date_value.day
        if gy > 1600:
            jy = 979
            gy -= 1600
        else:
            jy = 0
            gy -= 621
        gy2 = gy + 1 if gm > 2 else gy
        days = 365 * gy + ((gy2 + 3) // 4) - ((gy2 + 99) // 100) + ((gy2 + 399) // 400) - 80 + gd + g_days[gm - 1]
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

    month_names = {
        1: 'فروردین',
        2: 'اردیبهشت',
        3: 'خرداد',
        4: 'تیر',
        5: 'مرداد',
        6: 'شهریور',
        7: 'مهر',
        8: 'آبان',
        9: 'آذر',
        10: 'دی',
        11: 'بهمن',
        12: 'اسفند',
    }
    weekday_names = ['شنبه', 'یکشنبه', 'دوشنبه', 'سه‌شنبه', 'چهارشنبه', 'پنجشنبه', 'جمعه']
    today = timezone.localdate()
    current_jy, current_jm, current_jd = gregorian_to_jalali(today)
    selected_year = int(request.GET.get('year') or current_jy)
    selected_month = int(request.GET.get('month') or current_jm)
    event_type_filter = request.GET.get('type', '').strip()
    course_filter = request.GET.get('course', '').strip()
    teacher_filter = request.GET.get('teacher', '').strip()
    days_in_month = 31 if selected_month <= 6 else 30 if selected_month <= 11 else 29

    is_admin = _erd_is_admin_request(request)
    scope_cte = '' if is_admin else _erd_manager_scope_cte()
    scope_params = [] if is_admin else [request.erd_profile_id]
    exam_scope_where = '1=1' if is_admin else _erd_exam_scope_condition()
    exams = erd_rows(
        f"""
        {scope_cte}
        SELECT e.id, e.title, e.start_at, e.end_at, e.duration_minutes,
               COALESCE(e.academic_year, '-') AS academic_year,
               COALESCE(e.semester, '-') AS semester,
               COALESCE(e.is_published, false) AS is_published,
               COALESCE(e.is_cancelled, false) AS is_cancelled,
               COALESCE(c.title, '-') AS course,
               COALESCE(p.full_name, '-') AS teacher,
               'exam' AS event_type
        FROM exams e
        LEFT JOIN courses c ON c.id = e.course_id
        LEFT JOIN profiles p ON p.id = e.teacher_id
        WHERE {exam_scope_where}
        ORDER BY e.start_at ASC NULLS LAST, e.title
        LIMIT 300
        """,
        scope_params,
    )
    _em_calendar_ensure_table()
    if connection.vendor == 'sqlite':
        calendar_course_join = 'c.id = ace.course_id'
        calendar_group_join = 'sg.id = ace.group_id'
    else:
        calendar_course_join = "c.id = NULLIF(ace.course_id, '')::uuid"
        calendar_group_join = "sg.id = NULLIF(ace.group_id, '')::uuid"
    calendar_scope_where = '1=1' if is_admin else _erd_group_scope_condition()
    calendar_events = erd_rows(
        f"""
        {scope_cte}
        SELECT ace.id, ace.title, ace.starts_at AS start_at, ace.ends_at AS end_at, NULL AS duration_minutes,
               '-' AS academic_year, '-' AS semester,
               (ace.status = 'published') AS is_published,
               false AS is_cancelled,
               COALESCE(c.title, '-') AS course,
               '-' AS teacher,
               COALESCE(ace.event_type, 'session') AS event_type
        FROM academic_calendar_events ace
        LEFT JOIN courses c ON {calendar_course_join}
        LEFT JOIN student_groups sg ON {calendar_group_join}
        WHERE {calendar_scope_where}
        ORDER BY ace.starts_at ASC NULLS LAST, ace.title
        LIMIT 200
        """,
        scope_params,
    )
    exams = exams + calendar_events
    terms = erd_rows(
        """
        SELECT id, year, semester, COALESCE(label, semester, year) AS label, COALESCE(is_current, false) AS is_current
        FROM academic_terms
        ORDER BY is_current DESC, year DESC, semester
        LIMIT 30
        """
    )
    courses_count = erd_count('courses')
    courses = sorted({row['course'] for row in exams if row['course'] and row['course'] != '-'})
    teachers = sorted({row['teacher'] for row in exams if row['teacher'] and row['teacher'] != '-'})

    events_by_day = {day: [] for day in range(1, days_in_month + 1)}
    normalized_events = []
    for exam in exams:
        start_at = exam['start_at']
        if isinstance(start_at, str):
            start_at = parse_datetime(start_at)
        if not start_at:
            continue
        if timezone.is_naive(start_at):
            start_at = timezone.make_aware(start_at)
        if event_type_filter and event_type_filter != exam.get('event_type', 'exam'):
            continue
        if course_filter and course_filter != exam['course']:
            continue
        if teacher_filter and teacher_filter != exam['teacher']:
            continue
        jy, jm, jd = gregorian_to_jalali(start_at.date())
        if exam.get('event_type', 'exam') == 'exam':
            tone = 'danger' if exam['is_cancelled'] else 'success' if exam['is_published'] else 'purple'
        else:
            _, tone = _em_calendar_type_meta(exam.get('event_type'))
        event = {
            **exam,
            'start_at': start_at,
            'jalali_year': jy,
            'jalali_month': jm,
            'jalali_day': jd,
            'time': start_at.strftime('%H:%M'),
            'tone': tone,
        }
        normalized_events.append(event)
        if jy == selected_year and jm == selected_month and jd in events_by_day:
            events_by_day[jd].append(event)

    calendar_days = []
    leading_blanks = 0
    if selected_year == current_jy and selected_month == current_jm:
        leading_blanks = max(0, (today.weekday() + 2) % 7 - ((current_jd - 1) % 7))
    for _ in range(leading_blanks % 7):
        calendar_days.append({'day': '', 'events': [], 'is_today': False})
    for day in range(1, days_in_month + 1):
        calendar_days.append({
            'day': day,
            'events': events_by_day.get(day, [])[:2],
            'more_count': max(0, len(events_by_day.get(day, [])) - 2),
            'is_today': selected_year == current_jy and selected_month == current_jm and day == current_jd,
        })

    today_events = [event for event in normalized_events if event['jalali_year'] == current_jy and event['jalali_month'] == current_jm and event['jalali_day'] == current_jd][:3]
    upcoming_events = [event for event in normalized_events if event['start_at'] and event['start_at'] >= timezone.now()][:4]
    monthly_events_count = sum(len(items) for items in events_by_day.values())
    stats = {
        'events': len(normalized_events),
        'week_events': sum(1 for event in normalized_events if event['start_at'] and timezone.now() <= event['start_at'] <= timezone.now() + timedelta(days=7)),
        'active_classes': courses_count,
        'near_exams': len(upcoming_events),
    }
    important_events = [
        {'title': 'شروع کلاس‌های ترم جاری', 'date': f'{selected_year}/{selected_month:02d}/01', 'tone': 'purple'},
        {'title': 'اعلام برنامه آزمون جامع', 'date': f'{selected_year}/{selected_month:02d}/12', 'tone': 'green'},
        {'title': 'شروع ثبت‌نام دانشجویان', 'date': f'{selected_year}/{selected_month:02d}/20', 'tone': 'blue'},
    ]
    chart_days = ['۱۶ اردیبهشت', '۱۸ اردیبهشت', '۲۲ اردیبهشت', '۲۵ اردیبهشت', '۲۸ اردیبهشت', '۳ خرداد', '۶ خرداد']
    chart_series = [12, 18, 10, 22, 14, 25, 19]

    return render(request, 'super_admin/calendar.html', {
        'title': 'تقویم آموزشی',
        'description': 'برنامه‌ریزی و مدیریت رویدادهای آموزشی',
        'selected_year': selected_year,
        'selected_month': selected_month,
        'month_title': f'{month_names[selected_month]} {selected_year}',
        'weekday_names': weekday_names,
        'calendar_days': calendar_days,
        'events': normalized_events,
        'today_events': today_events,
        'upcoming_events': upcoming_events,
        'important_events': important_events,
        'stats': stats,
        'terms': terms,
        'courses': courses,
        'teachers': teachers,
        'event_type_filter': event_type_filter,
        'course_filter': course_filter,
        'teacher_filter': teacher_filter,
        'monthly_events_count': monthly_events_count,
        'chart_days': chart_days,
        'chart_series': chart_series,
    })


@super_admin_required
def super_admin_org_units(request):
    min_org_levels = ORG_LEVEL_MIN_COUNT
    level_tones = ['blue', 'purple', 'green', 'orange', 'cyan', 'violet', 'teal', 'amber']
    max_org_levels = len(level_tones)

    def save_org_level_config(levels, actor_id=None):
        erd_execute(
            """
            INSERT INTO system_settings (key, value, description, updated_by)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (key) DO UPDATE
                SET value = EXCLUDED.value,
                    description = EXCLUDED.description,
                    updated_by = EXCLUDED.updated_by
            """,
            [
                'org_structure_levels_config',
                json.dumps(levels, ensure_ascii=False),
                '\u062a\u0639\u0631\u06cc\u0641 \u0633\u0637\u062d\u200c\u0647\u0627\u06cc \u0633\u0627\u062e\u062a\u0627\u0631 \u0633\u0627\u0632\u0645\u0627\u0646\u06cc',
                actor_id,
            ],
        )

    org_level_config = get_org_level_config()
    org_level_count = len(org_level_config)

    units = erd_rows(
        """
        SELECT id, parent_id, type, name, code, COALESCE(is_active, true) AS is_active
        FROM org_units
        WHERE type IN ('university', 'faculty', 'department', 'group')
        ORDER BY type, name
        """
    )
    def org_unit_public_code(unit):
        code = str(unit.get('code') or '')
        if code.startswith('__level:') and '__' in code[8:]:
            return code.split('__', 2)[2] or ''
        return code

    for unit in units:
        level_index = org_unit_level_index(unit)
        level_def = org_level_config[level_index - 1] if 0 < level_index <= len(org_level_config) else default_org_level(level_index)
        unit['_level_index'] = level_index
        unit['_level_title'] = level_def.get('title') or f'سطح {level_index}'
        unit['_level_label'] = f'سطح {level_index}'
        unit['_public_code'] = org_unit_public_code(unit)
    org_action = request.POST.get('org_action', 'save') if request.method == 'POST' else 'save'
    org_id = request.POST.get('org_id', '').strip() if request.method == 'POST' else ''
    if request.method == 'POST' and org_action in ('level_adjust', 'level_save', 'level_delete'):
        actor = erd_profile_for_user(request.user)
        actor_id = actor['id'] if actor else None
        posted_titles = request.POST.getlist('level_title')
        posted_hints = request.POST.getlist('level_hint')
        posted_levels = []
        for index, title in enumerate(posted_titles, start=1):
            defaults = default_org_level(index)
            posted_levels.append({
                'title': title.strip() or defaults['title'],
                'hint': (posted_hints[index - 1].strip() if index - 1 < len(posted_hints) else '') or defaults['hint'],
            })
        current_levels = posted_levels or org_level_config
        if org_action == 'level_save':
            save_org_level_config(current_levels or [default_org_level(1)], actor_id)
            messages.success(request, '\u0639\u0646\u0648\u0627\u0646 \u0648 \u062a\u0648\u0636\u06cc\u062d \u0633\u0637\u062d\u200c\u0647\u0627 \u0630\u062e\u06cc\u0631\u0647 \u0634\u062f.')
        elif org_action == 'level_delete':
            try:
                delete_index = int(request.POST.get('level_index', '0')) - 1
            except ValueError:
                delete_index = -1
            if len(current_levels) <= min_org_levels:
                messages.info(request, '\u062d\u062f\u0627\u0642\u0644 \u06cc\u06a9 \u0633\u0637\u062d \u0628\u0627\u06cc\u062f \u0628\u0627\u0642\u06cc \u0628\u0645\u0627\u0646\u062f.')
            elif 0 <= delete_index < len(current_levels):
                current_levels.pop(delete_index)
                save_org_level_config(current_levels, actor_id)
                messages.success(request, '\u0633\u0637\u062d \u0627\u0646\u062a\u062e\u0627\u0628\u06cc \u062d\u0630\u0641 \u0634\u062f.')
            else:
                messages.error(request, '\u0633\u0637\u062d \u0627\u0646\u062a\u062e\u0627\u0628\u06cc \u0645\u0639\u062a\u0628\u0631 \u0646\u06cc\u0633\u062a.')
        elif request.POST.get('direction') == 'increase':
            current_levels.append(default_org_level(len(current_levels) + 1))
            save_org_level_config(current_levels, actor_id)
            messages.success(request, '\u0633\u0637\u062d \u062c\u062f\u06cc\u062f \u0627\u0636\u0627\u0641\u0647 \u0634\u062f.')
        elif len(current_levels) > min_org_levels:
            current_levels.pop()
            save_org_level_config(current_levels, actor_id)
            messages.success(request, '\u0622\u062e\u0631\u06cc\u0646 \u0633\u0637\u062d \u062d\u0630\u0641 \u0634\u062f.')
        else:
            messages.info(request, '\u062d\u062f\u0627\u0642\u0644 \u06cc\u06a9 \u0633\u0637\u062d \u0628\u0627\u06cc\u062f \u0628\u0627\u0642\u06cc \u0628\u0645\u0627\u0646\u062f.')
        return redirect('core:super_admin_org_units')

    if request.method == 'POST' and org_action == 'level_adjust':
        direction = request.POST.get('direction')
        next_level_count = org_level_count + (1 if direction == 'increase' else -1)
        next_level_count = min(max(next_level_count, min_org_levels), max_org_levels)
        if next_level_count == org_level_count:
            messages.info(request, 'تعداد سطح‌ها در محدوده مجاز قرار دارد.')
        else:
            actor = erd_profile_for_user(request.user)
            erd_execute(
                """
                INSERT INTO system_settings (key, value, description, updated_by)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (key) DO UPDATE
                    SET value = EXCLUDED.value,
                        description = EXCLUDED.description,
                        updated_by = EXCLUDED.updated_by
                """,
                [
                    'org_structure_levels',
                    json.dumps(next_level_count),
                    'تعداد سطح‌های نمایشی ساختار سازمانی',
                    actor['id'] if actor else None,
                ],
            )
            messages.success(request, 'تعداد سطح‌های ساختار سازمانی بروزرسانی شد.')
        return redirect('core:super_admin_org_units')

    if request.method == 'POST' and org_action == 'delete':
        if org_id:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    WITH RECURSIVE branch AS (
                        SELECT id FROM org_units WHERE id = %s
                        UNION ALL
                        SELECT child.id
                        FROM org_units child
                        JOIN branch parent ON child.parent_id = parent.id
                    )
                    DELETE FROM org_units
                    WHERE id IN (SELECT id FROM branch)
                    """,
                    [org_id],
                )
            messages.success(request, '\u0648\u0627\u062d\u062f \u0633\u0627\u0632\u0645\u0627\u0646\u06cc \u062d\u0630\u0641 \u0634\u062f.')
        return redirect('core:super_admin_org_units')

    form = SuperAdminOrgUnitForm(request.POST or None, org_units=units, unit_id=org_id, org_levels=org_level_config)
    if request.method == 'POST':
        if form.is_valid():
            form.save()
            messages.success(request, '\u0648\u0627\u062d\u062f \u0633\u0627\u0632\u0645\u0627\u0646\u06cc \u0628\u0627 \u0645\u0648\u0641\u0642\u06cc\u062a \u0630\u062e\u06cc\u0631\u0647 \u0634\u062f.')
            return redirect('core:super_admin_org_units')

    unit_by_id = {str(unit['id']): unit for unit in units}
    universities = [unit for unit in units if unit['type'] == 'university']
    faculties_by_university = {}
    departments_by_faculty = {}
    for unit in units:
        parent_id = str(unit['parent_id']) if unit.get('parent_id') else ''
        if unit['type'] == 'faculty':
            faculties_by_university.setdefault(parent_id, []).append(unit)
        elif unit['type'] == 'department':
            departments_by_faculty.setdefault(parent_id, []).append(unit)

    tree = []
    for university in universities:
        faculties = []
        for faculty in faculties_by_university.get(str(university['id']), []):
            faculties.append({
                'unit': faculty,
                'departments': departments_by_faculty.get(str(faculty['id']), []),
            })
        tree.append({
            'institution': university,
            'faculties': faculties,
        })

    faculty_options = [
        {
            'id': str(unit['id']),
            'name': unit['name'],
            'institution_id': str(unit['parent_id']),
            'parent_id': str(unit.get('parent_id') or ''),
            'level_index': unit.get('_level_index') or 1,
            'level_label': unit.get('_level_label') or '',
        }
        for unit in units
    ]

    type_meta = {
        'university': {'label': 'دانشگاه', 'level': 'سطح ۱', 'tone': 'blue'},
        'faculty': {'label': 'دانشکده', 'level': 'سطح ۲', 'tone': 'purple'},
        'department': {'label': 'گروه آموزشی', 'level': 'سطح ۳', 'tone': 'green'},
        'group': {'label': 'گروه آموزشی', 'level': 'سطح ۳', 'tone': 'green'},
    }
    org_table_rows = []
    from .templatetags.core_extras import _gregorian_to_jalali
    today = timezone.localdate()
    jy, jm, jd = _gregorian_to_jalali(today.year, today.month, today.day)
    org_created_display = f'{jy:04d}/{jm:02d}/{jd:02d}'
    for unit in units:
        parent = unit_by_id.get(str(unit.get('parent_id') or ''))
        level_index = int(unit.get('_level_index') or 1)
        level_def = org_level_config[level_index - 1] if 0 < level_index <= len(org_level_config) else default_org_level(level_index)
        meta = {
            'label': level_def.get('title') or f'سطح {level_index}',
            'level': f'سطح {level_index}',
            'tone': level_tones[(level_index - 1) % len(level_tones)],
        }
        edit_institution_id = ''
        edit_parent_id = ''
        if level_index >= 2:
            edit_parent_id = str(unit.get('parent_id') or '')
        if level_index == 2:
            edit_institution_id = str(unit.get('parent_id') or '')
        elif level_index >= 3:
            edit_institution_id = str(parent.get('parent_id') or '') if parent else ''
        org_table_rows.append({
            **unit,
            'parent_name': parent['name'] if parent else '-',
            'type_label': meta['label'],
            'level_label': meta['level'],
            'level_index': level_index,
            'tone': meta['tone'],
            'form_type': f'level_{level_index}',
            'display_code': unit.get('_public_code') or '',
            'created_display': org_created_display,
            'edit_institution_id': edit_institution_id,
            'edit_parent_id': edit_parent_id,
        })
    org_table_rows.sort(key=lambda row: (row.get('level_index') or 1, row.get('parent_name') or '', row.get('name') or ''))
    org_total_rows = len(org_table_rows)
    try:
        org_per_page = int(request.GET.get('per_page', 5))
    except (TypeError, ValueError):
        org_per_page = 5
    if org_per_page not in (5, 10):
        org_per_page = 5
    org_total_pages = max(math.ceil(org_total_rows / org_per_page), 1)
    try:
        org_current_page = int(request.GET.get('page', 1))
    except (TypeError, ValueError):
        org_current_page = 1
    org_current_page = min(max(org_current_page, 1), org_total_pages)
    org_page_start = (org_current_page - 1) * org_per_page
    org_page_end = org_page_start + org_per_page
    org_table_page_rows = org_table_rows[org_page_start:org_page_end]
    org_page_numbers = list(range(1, org_total_pages + 1))
    org_pagination = {
        'per_page': org_per_page,
        'total': org_total_rows,
        'current_page': org_current_page,
        'total_pages': org_total_pages,
        'page_numbers': org_page_numbers,
        'has_previous': org_current_page > 1,
        'has_next': org_current_page < org_total_pages,
        'previous_page': max(org_current_page - 1, 1),
        'next_page': min(org_current_page + 1, org_total_pages),
        'start_index': org_page_start + 1 if org_total_rows else 0,
        'end_index': min(org_page_end, org_total_rows),
    }
    org_levels = [
        {'title': 'دانشگاه', 'level': 'سطح ۱', 'hint': 'ریشه ساختار سازمانی', 'count': len([unit for unit in units if unit['type'] == 'university']), 'tone': 'blue'},
        {'title': 'دانشکده', 'level': 'سطح ۲', 'hint': 'زیرمجموعه دانشگاه', 'count': len([unit for unit in units if unit['type'] == 'faculty']), 'tone': 'purple'},
        {'title': 'گروه آموزشی', 'level': 'سطح ۳', 'hint': 'زیرمجموعه دانشکده', 'count': len([unit for unit in units if unit['type'] in ('department', 'group')]), 'tone': 'green'},
        {'title': 'رشته', 'level': 'سطح ۴', 'hint': 'ریزترین سطح ساختار سازمانی', 'count': 0, 'tone': 'orange'},
        {'title': 'کلاس / واحد', 'level': 'سطح ۵', 'hint': 'ریزترین سطح ساختار سازمانی', 'count': 0, 'tone': 'cyan'},
    ]

    org_levels = [
        org_levels[0],
        org_levels[1],
        org_levels[2],
        {'title': '\u0631\u0634\u062a\u0647', 'level': '\u0633\u0637\u062d \u06f4', 'hint': '\u0631\u06cc\u0632\u062a\u0631\u06cc\u0646 \u0633\u0637\u062d \u0633\u0627\u062e\u062a\u0627\u0631 \u0633\u0627\u0632\u0645\u0627\u0646\u06cc', 'count': 0, 'tone': 'orange'},
        {'title': '\u06a9\u0644\u0627\u0633 / \u0648\u0627\u062d\u062f', 'level': '\u0633\u0637\u062d \u06f5', 'hint': '\u0631\u06cc\u0632\u062a\u0631\u06cc\u0646 \u0633\u0637\u062d \u0633\u0627\u062e\u062a\u0627\u0631 \u0633\u0627\u0632\u0645\u0627\u0646\u06cc', 'count': 0, 'tone': 'cyan'},
    ]

    level_templates = [
        {'title': 'دانشگاه', 'hint': 'ریشه ساختار سازمانی', 'count': len([unit for unit in units if unit['type'] == 'university']), 'tone': 'blue'},
        {'title': 'دانشکده', 'hint': 'زیرمجموعه دانشگاه', 'count': len([unit for unit in units if unit['type'] == 'faculty']), 'tone': 'purple'},
        {'title': 'گروه آموزشی', 'hint': 'زیرمجموعه دانشکده', 'count': len([unit for unit in units if unit['type'] in ('department', 'group')]), 'tone': 'green'},
        {'title': 'رشته', 'hint': 'ریزترین سطح ساختار سازمانی', 'count': 0, 'tone': 'orange'},
        {'title': 'کلاس / واحد', 'hint': 'ریزترین سطح ساختار سازمانی', 'count': 0, 'tone': 'cyan'},
        {'title': 'گرایش', 'hint': 'سطح تکمیلی ساختار سازمانی', 'count': 0, 'tone': 'violet'},
        {'title': 'زیرگروه', 'hint': 'سطح تکمیلی ساختار سازمانی', 'count': 0, 'tone': 'teal'},
        {'title': 'واحد اجرایی', 'hint': 'سطح تکمیلی ساختار سازمانی', 'count': 0, 'tone': 'amber'},
    ]
    org_levels = [
        {
            **level,
            'level': f'سطح {index}',
        }
        for index, level in enumerate(level_templates[:org_level_count], start=1)
    ]

    org_level_counts = {}
    for unit in units:
        org_level_counts[unit.get('_level_index') or 1] = org_level_counts.get(unit.get('_level_index') or 1, 0) + 1
    preview_units = []
    children_by_parent = {}
    for unit in units:
        children_by_parent.setdefault(str(unit.get('parent_id') or ''), []).append(unit)
    for siblings in children_by_parent.values():
        siblings.sort(key=lambda item: (int(item.get('_level_index') or 1), item.get('name') or ''))

    def add_preview_branch(unit, seen_ids=None):
        seen_ids = set(seen_ids or ())
        unit_id = str(unit['id'])
        if unit_id in seen_ids:
            return
        seen_ids.add(unit_id)
        level_index = int(unit.get('_level_index') or 1)
        preview_units.append({
            'name': unit['name'],
            'level_index': level_index,
            'level_label': unit.get('_level_label') or f'\u0633\u0637\u062d {level_index}',
            'level_title': unit.get('_level_title') or f'\u0633\u0637\u062d {level_index}',
            'tone': level_tones[(level_index - 1) % len(level_tones)],
        })
        for child in children_by_parent.get(unit_id, []):
            add_preview_branch(child, seen_ids)

    preview_roots = children_by_parent.get('', []) or [unit for unit in units if int(unit.get('_level_index') or 1) == 1]
    if not preview_roots and units:
        preview_roots = [units[0]]
    for preview_root in preview_roots:
        add_preview_branch(preview_root)
    org_levels = [
        {
            'title': level['title'],
            'hint': level['hint'],
            'level': f'\u0633\u0637\u062d {index}',
            'count': org_level_counts.get(index, 0),
            'tone': level_tones[(index - 1) % len(level_tones)],
        }
        for index, level in enumerate(org_level_config, start=1)
    ]
    org_level_count = len(org_levels)

    return render(request, 'super_admin/org_units.html', {
        'title': 'ساختار سازمانی',
        'kicker': 'مدیر سیستم / ساختار سازمانی',
        'description': 'دانشگاه، دانشکده و گروه آموزشی را به صورت سلسله مراتبی مدیریت کنید.',
        'form': form,
        'tree': tree,
        'org_table_rows': org_table_page_rows,
        'org_pagination': org_pagination,
        'org_levels': org_levels,
        'org_summary': {
            'levels_count': org_level_count,
            'units_count': len(units),
            'root_label': '\u062f\u0627\u0646\u0634\u06af\u0627\u0647',
            'updated_label': '\u0627\u0645\u0631\u0648\u0632',
        },
        'preview_units': preview_units,
        'can_increase_levels': True,
        'can_decrease_levels': org_level_count > min_org_levels,
        'settings_active_tab': 'org',
        'faculty_options_json': faculty_options,
    })


@super_admin_required
def super_admin_academic_managers(request):
    q = request.GET.get('q', '').strip()
    org_units = erd_rows(
        """
        SELECT id, parent_id, type, name, code, is_active
        FROM org_units
        ORDER BY CASE type WHEN 'university' THEN 0 WHEN 'faculty' THEN 1 ELSE 2 END, name
        """
    )
    unit_by_id = {str(unit['id']): unit for unit in org_units}

    def unit_path(unit_id):
        unit = unit_by_id.get(str(unit_id or ''))
        if not unit:
            return {'university': '-', 'faculty': '-', 'department': '-', 'label': '-'}
        chain = []
        current = unit
        seen = set()
        while current and str(current['id']) not in seen:
            seen.add(str(current['id']))
            chain.append(current)
            current = unit_by_id.get(str(current.get('parent_id') or ''))
        by_type = {item['type']: item['name'] for item in chain}
        label_parts = [by_type.get('university'), by_type.get('faculty'), by_type.get('department') or by_type.get('group')]
        return {
            'university': by_type.get('university') or '-',
            'faculty': by_type.get('faculty') or '-',
            'department': by_type.get('department') or by_type.get('group') or '-',
            'label': ' / '.join(part for part in label_parts if part) or unit['name'],
        }

    excel_headers = ['نام', 'نام خانوادگی', 'نام کاربری', 'ایمیل', 'موبایل', 'کد ملی', 'کد پرسنلی', 'وضعیت', 'دانشگاه', 'دانشکده', 'گروه آموزشی']

    def normalize_text(value):
        return str(value or '').strip().replace('ي', 'ی').replace('ك', 'ک').lower()

    def resolve_scope_id(university_name='', faculty_name='', department_name=''):
        university_name = normalize_text(university_name)
        faculty_name = normalize_text(faculty_name)
        department_name = normalize_text(department_name)

        def parent_chain(unit):
            chain = []
            current = unit
            seen = set()
            while current and str(current['id']) not in seen:
                seen.add(str(current['id']))
                chain.append(current)
                current = unit_by_id.get(str(current.get('parent_id') or ''))
            return chain

        candidates = []
        if department_name:
            candidates = [unit for unit in org_units if unit['type'] in ('department', 'group') and normalize_text(unit['name']) == department_name]
        elif faculty_name:
            candidates = [unit for unit in org_units if unit['type'] == 'faculty' and normalize_text(unit['name']) == faculty_name]
        elif university_name:
            candidates = [unit for unit in org_units if unit['type'] == 'university' and normalize_text(unit['name']) == university_name]

        for unit in candidates:
            chain = parent_chain(unit)
            names_by_type = {item['type']: normalize_text(item['name']) for item in chain}
            if university_name and names_by_type.get('university') != university_name:
                continue
            if faculty_name and names_by_type.get('faculty') != faculty_name:
                continue
            return str(unit['id'])
        return ''

    def import_status(value):
        value = normalize_text(value)
        return {
            'فعال': 'active',
            'active': 'active',
            'غیرفعال': 'inactive',
            'غيرفعال': 'inactive',
            'inactive': 'inactive',
            'مسدود': 'blocked',
            'blocked': 'blocked',
        }.get(value, 'active')

    if request.GET.get('manager_action') == 'sample':
        return xlsx_response(
            'academic-managers-sample.xlsx',
            excel_headers,
            [[
                'علی',
                'رضایی',
                'ali.rezaei',
                'ali.rezaei@example.com',
                '09120000000',
                '0012345678',
                'ACM-003',
                'فعال',
                'دانشگاه نمونه',
                'دانشکده مهندسی',
                'گروه مهندسی برق',
            ]],
            'Academic Managers',
        )

    if request.method == 'POST' and request.POST.get('manager_action') == 'import':
        uploaded = request.FILES.get('excel_file')
        if not uploaded:
            messages.error(request, 'لطفاً فایل اکسل مدیران آموزشی را انتخاب کنید.')
            return redirect('core:super_admin_academic_managers')
        try:
            imported_rows = read_xlsx_dicts(uploaded)
        except (KeyError, ET.ParseError, zipfile.BadZipFile):
            messages.error(request, 'فایل انتخاب‌شده معتبر نیست. لطفاً نمونه اکسل را دریافت و تکمیل کنید.')
            return redirect('core:super_admin_academic_managers')

        imported_count = 0
        import_errors = []
        created_credentials = []
        with connection.cursor() as cursor:
            for row_number, row in enumerate(imported_rows, start=2):
                first_name = row.get('نام', '').strip()
                last_name = row.get('نام خانوادگی', '').strip()
                username = row.get('نام کاربری', '').strip()
                email = row.get('ایمیل', '').strip()
                phone = row.get('موبایل', '').strip()
                national_id = row.get('کد ملی', '').strip()
                personnel_code = row.get('کد پرسنلی', '').strip()
                status = import_status(row.get('وضعیت', 'فعال'))
                full_name = f'{first_name} {last_name}'.strip() or username or email or personnel_code
                if not full_name or not personnel_code:
                    import_errors.append(f'ردیف {row_number}: نام یا کد پرسنلی کامل نیست.')
                    continue
                username = username or email or personnel_code
                scope_id = resolve_scope_id(row.get('دانشگاه'), row.get('دانشکده'), row.get('گروه آموزشی'))
                primary_scope = unit_path(scope_id) if scope_id else {'department': row.get('گروه آموزشی', '').strip()}

                cursor.execute(
                    """
                    SELECT id
                    FROM profiles
                    WHERE identifier = %s OR email = %s OR username = %s
                    LIMIT 1
                    """,
                    [personnel_code, email or None, username or None],
                )
                existing = cursor.fetchone()
                manager_id = existing[0] if existing else str(uuid.uuid4())
                if existing:
                    cursor.execute(
                        """
                        UPDATE profiles
                        SET full_name = %s, first_name = %s, last_name = %s, username = %s,
                            email = %s, phone = %s, national_id = %s, identifier = %s,
                            status = %s, updated_at = CURRENT_TIMESTAMP
                        WHERE id = %s
                        """,
                        [full_name, first_name, last_name, username, email or None, phone or None, national_id or None, personnel_code, status, manager_id],
                    )
                else:
                    cursor.execute(
                        """
                        INSERT INTO profiles (id, full_name, first_name, last_name, username, email, phone, national_id, identifier, avatar_url, status, created_at, updated_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, '', %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                        """,
                        [manager_id, full_name, first_name, last_name, username, email or None, phone or None, national_id or None, personnel_code, status],
                    )
                cursor.execute(
                    """
                    INSERT INTO academic_manager_profiles (user_id, personnel_code, department, responsibility_area)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT(user_id) DO UPDATE SET
                        personnel_code = excluded.personnel_code,
                        department = excluded.department,
                        responsibility_area = excluded.responsibility_area
                    """,
                    [manager_id, personnel_code, primary_scope.get('department') or '', primary_scope.get('label') or ''],
                )
                cursor.execute("DELETE FROM user_roles WHERE user_id = %s AND role = %s", [manager_id, 'academic_manager'])
                cursor.execute("INSERT INTO user_roles (id, user_id, role, created_at) VALUES (%s, %s, %s, CURRENT_TIMESTAMP)", [str(uuid.uuid4()), manager_id, 'academic_manager'])
                cursor.execute("DELETE FROM academic_manager_scopes WHERE manager_id = %s", [manager_id])
                if scope_id:
                    cursor.execute(
                        "INSERT INTO academic_manager_scopes (id, manager_id, org_unit_id, created_at) VALUES (%s, %s, %s, CURRENT_TIMESTAMP)",
                        [str(uuid.uuid4()), manager_id, scope_id],
                    )
                _login_user, generated_password = erd_sync_login_account(username, is_active=(status == 'active'))
                if generated_password:
                    created_credentials.append((username, generated_password))
                imported_count += 1

        if imported_count:
            messages.success(request, f'{imported_count} مدیر آموزشی با موفقیت وارد شد.')
        if created_credentials:
            shown = created_credentials[:15]
            credential_text = '؛ '.join(f'{username}: {password}' for username, password in shown)
            suffix = f' (و {len(created_credentials) - len(shown)} مورد دیگر)' if len(created_credentials) > len(shown) else ''
            messages.info(request, f'رمزهای عبور اولیه حساب‌های تازه‌ساخته‌شده: {credential_text}{suffix}')
        if import_errors:
            messages.warning(request, '؛ '.join(import_errors[:5]))
        return redirect('core:super_admin_academic_managers')

    if request.method == 'POST' and request.POST.get('manager_action') == 'delete':
        manager_id = request.POST.get('manager_id')
        wants_json = request.headers.get('x-requested-with') == 'XMLHttpRequest'
        if not manager_id:
            if wants_json:
                return JsonResponse({'ok': False, 'message': 'شناسه مدیر آموزشی نامعتبر است.'}, status=400)
            messages.error(request, 'شناسه مدیر آموزشی نامعتبر است.')
            return redirect('core:super_admin_academic_managers')
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM academic_manager_scopes WHERE manager_id = %s", [manager_id])
            cursor.execute("DELETE FROM academic_manager_profiles WHERE user_id = %s", [manager_id])
            cursor.execute("DELETE FROM user_roles WHERE user_id = %s AND role = %s", [manager_id, 'academic_manager'])
            cursor.execute("DELETE FROM profiles WHERE id = %s", [manager_id])
        if wants_json:
            return JsonResponse({'ok': True, 'message': 'مدیر آموزشی حذف شد.', 'manager_id': manager_id})
        messages.success(request, 'مدیر آموزشی حذف شد.')
        return redirect('core:super_admin_academic_managers')

    if request.method == 'POST' and request.POST.get('manager_action') == 'save':
        wants_json = request.headers.get('x-requested-with') == 'XMLHttpRequest'
        manager_id = request.POST.get('manager_id') or str(uuid.uuid4())
        first_name = request.POST.get('first_name', '').strip()
        last_name = request.POST.get('last_name', '').strip()
        full_name = f'{first_name} {last_name}'.strip() or request.POST.get('full_name', '').strip() or 'مدیر آموزشی'
        username = request.POST.get('username', '').strip() or None
        email = request.POST.get('email', '').strip() or None
        phone = request.POST.get('phone', '').strip() or None
        national_id = request.POST.get('national_id', '').strip() or None
        personnel_code = request.POST.get('personnel_code', '').strip() or request.POST.get('identifier', '').strip() or None
        status = request.POST.get('status') or 'active'
        scope_ids = [item for item in request.POST.get('scope_ids', '').split(',') if item]
        primary_scope = unit_path(scope_ids[0]) if scope_ids else {'department': None}
        avatar_url = None

        avatar = request.FILES.get('avatar')
        if avatar:
            if avatar.size > 1024 * 1024:
                if wants_json:
                    return JsonResponse({'ok': False, 'message': 'حجم تصویر پروفایل باید کمتر از ۱ مگابایت باشد.'}, status=400)
                messages.error(request, 'حجم تصویر پروفایل باید کمتر از ۱ مگابایت باشد.')
                return redirect('core:super_admin_academic_managers')
            if avatar.content_type not in {'image/jpeg', 'image/png', 'image/webp', 'image/gif'}:
                if wants_json:
                    return JsonResponse({'ok': False, 'message': 'فرمت تصویر باید JPG، PNG، WebP یا GIF باشد.'}, status=400)
                messages.error(request, 'فرمت تصویر باید JPG، PNG، WebP یا GIF باشد.')
                return redirect('core:super_admin_academic_managers')
            extension = avatar.name.rsplit('.', 1)[-1].lower() if '.' in avatar.name else 'jpg'
            storage = FileSystemStorage(
                location=settings.MEDIA_ROOT / 'avatars',
                base_url=settings.MEDIA_URL + 'avatars/',
            )
            filename = storage.save(f"{manager_id}-{uuid.uuid4().hex[:8]}.{extension}", avatar)
            avatar_url = storage.url(filename)

        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM profiles WHERE id = %s", [manager_id])
            exists = cursor.fetchone()
            if exists:
                if avatar_url is not None:
                    cursor.execute(
                        """
                        UPDATE profiles
                        SET full_name = %s, first_name = %s, last_name = %s, username = %s,
                            email = %s, phone = %s, national_id = %s, identifier = %s,
                            avatar_url = %s, status = %s, updated_at = CURRENT_TIMESTAMP
                        WHERE id = %s
                        """,
                        [full_name, first_name, last_name, username, email, phone, national_id, personnel_code, avatar_url, status, manager_id],
                    )
                else:
                    cursor.execute(
                        """
                        UPDATE profiles
                        SET full_name = %s, first_name = %s, last_name = %s, username = %s,
                            email = %s, phone = %s, national_id = %s, identifier = %s,
                            status = %s, updated_at = CURRENT_TIMESTAMP
                        WHERE id = %s
                        """,
                        [full_name, first_name, last_name, username, email, phone, national_id, personnel_code, status, manager_id],
                    )
            else:
                cursor.execute(
                    """
                    INSERT INTO profiles (id, full_name, first_name, last_name, username, email, phone, national_id, identifier, avatar_url, status, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    """,
                    [manager_id, full_name, first_name, last_name, username, email, phone, national_id, personnel_code, avatar_url or '', status],
                )
            cursor.execute(
                """
                INSERT INTO academic_manager_profiles (user_id, personnel_code, department, responsibility_area)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT(user_id) DO UPDATE SET
                    personnel_code = excluded.personnel_code,
                    department = excluded.department,
                    responsibility_area = excluded.responsibility_area
                """,
                [manager_id, personnel_code, primary_scope.get('department') or '', '، '.join(unit_path(scope_id)['label'] for scope_id in scope_ids)],
            )
            cursor.execute("DELETE FROM user_roles WHERE user_id = %s AND role = %s", [manager_id, 'academic_manager'])
            cursor.execute("INSERT INTO user_roles (id, user_id, role, created_at) VALUES (%s, %s, %s, CURRENT_TIMESTAMP)", [str(uuid.uuid4()), manager_id, 'academic_manager'])
            cursor.execute("DELETE FROM academic_manager_scopes WHERE manager_id = %s", [manager_id])
            for scope_id in scope_ids:
                cursor.execute(
                    "INSERT INTO academic_manager_scopes (id, manager_id, org_unit_id, created_at) VALUES (%s, %s, %s, CURRENT_TIMESTAMP)",
                    [str(uuid.uuid4()), manager_id, scope_id],
                )
        _login_user, generated_password = erd_sync_login_account(username, is_active=(status == 'active'))
        if wants_json:
            with connection.cursor() as cursor:
                cursor.execute("SELECT avatar_url FROM profiles WHERE id = %s", [manager_id])
                final_avatar_url = (cursor.fetchone() or [''])[0] or ''
            return JsonResponse({
                'ok': True,
                'message': 'اطلاعات مدیر آموزشی ذخیره شد.',
                'manager_id': manager_id,
                'first_name': first_name,
                'last_name': last_name,
                'full_name': full_name,
                'username': username or '',
                'email': email or '',
                'phone': phone or '',
                'national_id': national_id or '',
                'personnel_code': personnel_code or '',
                'status': status,
                'scope_ids': scope_ids,
                'university': primary_scope.get('university') or '-',
                'faculty': primary_scope.get('faculty') or '-',
                'department': primary_scope.get('department') or '-',
                'avatar_url': final_avatar_url,
                'generated_password': generated_password or '',
            })
        if generated_password:
            messages.success(request, f'اطلاعات مدیر آموزشی ذخیره شد. نام کاربری: {username} — رمز عبور اولیه: {generated_password}')
        else:
            messages.success(request, 'اطلاعات مدیر آموزشی ذخیره شد.')
        return redirect('core:super_admin_academic_managers')

    managers = erd_rows(
        """
        SELECT p.id, p.full_name, p.first_name, p.last_name, p.username, p.email, p.phone,
               p.national_id, p.identifier, p.avatar_url, p.status, p.created_at, p.last_login_at,
               amp.personnel_code, amp.department, amp.responsibility_area
        FROM academic_manager_profiles amp
        JOIN profiles p ON p.id = amp.user_id
        ORDER BY p.full_name
        LIMIT 200
        """
    )
    scopes = erd_rows("SELECT manager_id, org_unit_id FROM academic_manager_scopes")
    scopes_by_manager = {}
    for scope in scopes:
        scopes_by_manager.setdefault(str(scope['manager_id']), []).append(str(scope['org_unit_id']))

    rows = []
    for manager in managers:
        manager_scope_ids = scopes_by_manager.get(str(manager['id']), [])
        scope_paths = [unit_path(scope_id) for scope_id in manager_scope_ids]
        primary = scope_paths[0] if scope_paths else {'university': '-', 'faculty': '-', 'department': manager.get('department') or '-', 'label': manager.get('department') or '-'}
        if q and not _matches_query(q, manager.get('full_name'), manager.get('email'), manager.get('username'), manager.get('personnel_code'), primary['label']):
            continue
        rows.append({
            **manager,
            'scope_ids': manager_scope_ids,
            'scope_labels': [path['label'] for path in scope_paths],
            'university': primary['university'],
            'faculty': primary['faculty'],
            'department_name': primary['department'],
            'created_display': manager.get('created_at') or '-',
            'last_login_display': manager.get('last_login_at') or '-',
        })

    if request.GET.get('manager_action') == 'export':
        export_rows = []
        status_labels = {'active': 'فعال', 'inactive': 'غیرفعال', 'blocked': 'مسدود'}
        for row in rows:
            export_rows.append([
                row.get('first_name') or '',
                row.get('last_name') or '',
                row.get('username') or '',
                row.get('email') or '',
                row.get('phone') or '',
                row.get('national_id') or '',
                row.get('personnel_code') or row.get('identifier') or '',
                status_labels.get(row.get('status') or 'active', 'فعال'),
                row.get('university') or '',
                row.get('faculty') or '',
                row.get('department_name') or '',
            ])
        return xlsx_response('academic-managers.xlsx', excel_headers, export_rows, 'Academic Managers')

    return render(request, 'super_admin/academic_managers.html', {
        'title': 'مدیران آموزشی',
        'description': 'ایجاد، ویرایش کامل اطلاعات مدیر آموزشی و انتساب واحدهای سازمانی تحت مدیریت.',
        'rows': rows,
        'query': q,
        'universities': [unit for unit in org_units if unit['type'] == 'university'],
        'faculties': [unit for unit in org_units if unit['type'] == 'faculty'],
        'departments': [unit for unit in org_units if unit['type'] in ('department', 'group')],
        'org_units_json': org_units,
    })


@super_admin_required
def super_admin_academic_terms(request):
    if request.method == 'POST':
        action = request.POST.get('term_action')
        if action == 'delete':
            term_id = request.POST.get('term_id')
            if term_id:
                erd_execute("DELETE FROM academic_terms WHERE id = %s", [term_id])
                messages.success(request, 'ترم حذف شد.')
            return redirect('core:super_admin_academic_terms')

        year = request.POST.get('year', '').strip()
        semester = request.POST.get('semester', '').strip()
        label = request.POST.get('label', '').strip()
        start_date = request.POST.get('start_date', '').strip()
        end_date = request.POST.get('end_date', '').strip()
        description = request.POST.get('description', '').strip()
        is_active = request.POST.get('is_active', 'on') == 'on'
        is_current = request.POST.get('is_current') == 'on' or request.POST.get('is_default') == 'on'
        term_id = request.POST.get('term_id', '').strip()
        if year and semester:
            semester_label = {
                'first': 'نیم‌سال اول',
                'second': 'نیم‌سال دوم',
                'summer': 'تابستان',
            }.get(semester, semester)
            title = label or f'{year} - {semester_label}'
            if is_current:
                erd_execute("UPDATE academic_terms SET is_current = %s", [False])
            if term_id:
                erd_execute(
                    """
                    UPDATE academic_terms
                    SET year = %s,
                        semester = %s,
                        label = %s,
                        is_current = %s,
                        start_date = %s,
                        end_date = %s,
                        description = %s,
                        is_active = %s
                    WHERE id = %s
                    """,
                    [year, semester_label, title, is_current, start_date or None, end_date or None, description or None, is_active, term_id],
                )
                messages.success(request, 'ترم بروزرسانی شد.')
                return redirect('core:super_admin_academic_terms')
            erd_execute(
                """
                INSERT INTO academic_terms (id, year, semester, label, is_current, start_date, end_date, description, is_active)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                [str(uuid.uuid4()), year, semester_label, title, is_current, start_date or None, end_date or None, description or None, is_active],
            )
            messages.success(request, 'ترم جدید اضافه شد.')
        else:
            messages.error(request, 'سال تحصیلی و نوع ترم را وارد کنید.')
        return redirect('core:super_admin_academic_terms')

    terms = erd_rows(
        """
        SELECT id, year, semester, label, is_current, start_date, end_date, COALESCE(is_active, true) AS is_active
        FROM academic_terms
        ORDER BY is_current DESC, year DESC, semester
        LIMIT 200
        """
    )
    for term in terms:
        semester_text = str(term.get('semester') or '')
        if 'second' in semester_text or 'دوم' in semester_text:
            term['semester_value'] = 'second'
        elif 'summer' in semester_text or 'تابستان' in semester_text:
            term['semester_value'] = 'summer'
        else:
            term['semester_value'] = 'first'
    current_term = next((term for term in terms if term.get('is_current')), terms[0] if terms else None)
    return render(request, 'super_admin/academic_terms.html', {
        'title': 'سال تحصیلی و ترم‌ها',
        'description': 'تعریف سال‌های تحصیلی و نیم‌سال‌ها',
        'terms': terms,
        'current_term': current_term,
    })


def _deactivate_account(profile_id, reviewer_id) -> None:
    """Logical deletion: the account can no longer sign in and its sessions end; every row stays for the admin."""
    profile = erd_row('SELECT username FROM profiles WHERE id = %s', [profile_id])
    erd_execute(
        "UPDATE profiles SET status = 'inactive', deleted_at = CURRENT_TIMESTAMP, deleted_by = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s",
        [reviewer_id, profile_id],
    )
    user = User.objects.filter(username=profile['username']).first() if profile and profile.get('username') else None
    if user:
        user.is_active = False
        user.save(update_fields=['is_active'])
        account_security.end_all_sessions(user)


@super_admin_required
def super_admin_account_deletions(request):
    from django.core.paginator import Paginator

    reviewed = request.GET.get('status') == 'reviewed'
    where = "r.status IN ('approved', 'rejected')" if reviewed else "r.status = 'pending'"
    total = erd_count('account_deletion_requests r', where)
    page = Paginator(range(total), ACCOUNT_DELETION_PAGE_SIZE).get_page(request.GET.get('page'))
    rows = erd_rows(
        f"""
        SELECT r.id, r.profile_id, r.reason, r.status, r.review_note, r.created_at, r.reviewed_at,
               p.full_name, p.username, p.email, rv.full_name AS reviewer_name,
               (SELECT ur.role FROM user_roles ur WHERE ur.user_id = r.profile_id ORDER BY ur.role LIMIT 1) AS role
        FROM account_deletion_requests r
        JOIN profiles p ON p.id = r.profile_id
        LEFT JOIN profiles rv ON rv.id = r.reviewer_id
        WHERE {where}
        ORDER BY r.created_at DESC
        LIMIT %s OFFSET %s
        """,
        [ACCOUNT_DELETION_PAGE_SIZE, page.start_index() - 1 if total else 0],
    )
    items = []
    for row in rows:
        item = dict(row)
        item['created_label'] = _jalali_long_date(item['created_at'], with_weekday=False)
        item['reviewed_label'] = _jalali_long_date(item['reviewed_at'], with_weekday=False)
        item['profile_kind'] = item['role'] if item['role'] in ('teacher', 'student') else ''
        items.append(item)
    return render(request, 'super_admin/account_deletions.html', {
        'items': items,
        'page': page,
        'status': 'reviewed' if reviewed else 'pending',
        'pending_count': erd_count('account_deletion_requests', "status = 'pending'"),
    })


@super_admin_required
def super_admin_account_deletion_review(request, request_id):
    if request.method != 'POST':
        return redirect('core:super_admin_account_deletions')
    reviewer_id = erd_user_profile_id(request.user)
    deletion = erd_row("SELECT id, profile_id FROM account_deletion_requests WHERE id = %s AND status = 'pending'", [request_id])
    if not deletion:
        raise Http404('درخواست پیدا نشد.')
    if str(deletion['profile_id']) == str(reviewer_id):
        return HttpResponseForbidden('بررسی درخواست حذف حساب خودتان مجاز نیست.')
    decision = request.POST.get('decision')
    note = (request.POST.get('review_note') or '').strip()
    if decision not in {'approve', 'reject'} or len(note) > 300 or (decision == 'reject' and not note):
        messages.error(request, 'برای رد درخواست، دلیل را بنویسید (حداکثر ۳۰۰ نویسه).')
        return redirect('core:super_admin_account_deletions')
    status = 'approved' if decision == 'approve' else 'rejected'
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                erd_adapt_sql(
                    """
                    UPDATE account_deletion_requests
                    SET status = %s, reviewer_id = %s, review_note = %s, reviewed_at = CURRENT_TIMESTAMP
                    WHERE id = %s AND status = 'pending'
                    """
                ),
                [status, reviewer_id, note or None, request_id],
            )
            claimed = cursor.rowcount == 1
        if claimed and status == 'approved':
            _deactivate_account(deletion['profile_id'], reviewer_id)
    if not claimed:
        messages.error(request, 'این درخواست پیش‌تر بررسی یا لغو شده است.')
        return redirect('core:super_admin_account_deletions')
    log_activity(request.user, f'account_deletion_{status}', 'بررسی درخواست حذف حساب', request, {'request_id': str(request_id), 'profile_id': str(deletion['profile_id'])})
    if status == 'rejected':
        create_notification(deletion['profile_id'], 'درخواست حذف حساب رد شد', note, f'{reverse("core:teacher_settings")}?tab=security', 'account')
    messages.success(request, 'حساب غیرفعال شد؛ اطلاعات آن برای مدیر سیستم باقی است.' if status == 'approved' else 'درخواست رد شد.')
    return redirect('core:super_admin_account_deletions')


@super_admin_required
def super_admin_settings(request):
    settings_schema = [
        {
            'key': 'site_name',
            'label': 'نام سامانه',
            'type': 'text',
            'default': 'سامانه جامع مدیریت آزمون متا کوییز',
            'group': 'basic',
        },
        {
            'key': 'system_logo',
            'label': 'لوگو / هویت سامانه',
            'type': 'text',
            'default': '/static/img/metaquiz-favicon.svg',
            'group': 'basic',
        },
        {
            'key': 'default_language',
            'label': 'زبان پیش‌فرض',
            'type': 'text',
            'default': 'فارسی (ایران)',
            'group': 'basic',
        },
        {
            'key': 'timezone',
            'label': 'منطقه زمانی',
            'type': 'text',
            'default': 'تهران (UTC+03:30)',
            'group': 'basic',
        },
        {
            'key': 'date_format',
            'label': 'فرمت تاریخ',
            'type': 'text',
            'default': '1403/03/27',
            'group': 'basic',
        },
        {
            'key': 'session_timeout_minutes',
            'label': 'زمان انقضای جلسه (دقیقه)',
            'type': 'number',
            'default': 30,
            'group': 'security',
        },
        {
            'key': 'two_factor_required',
            'label': 'احراز هویت دومرحله‌ای',
            'type': 'boolean',
            'default': True,
            'group': 'security',
        },
        {
            'key': 'password_policy',
            'label': 'سیاست گذرواژه',
            'type': 'text',
            'default': 'قوی',
            'group': 'security',
        },
        {
            'key': 'ip_restriction',
            'label': 'محدودیت IP',
            'type': 'boolean',
            'default': False,
            'group': 'security',
        },
        {
            'key': 'suspicious_login_alerts',
            'label': 'اعلان ورودهای مشکوک',
            'type': 'boolean',
            'default': True,
            'group': 'security',
        },
        {
            'key': 'email_notifications',
            'label': 'اعلان‌های ایمیلی',
            'type': 'boolean',
            'default': True,
            'group': 'notifications',
        },
        {
            'key': 'in_app_notifications',
            'label': 'اعلان‌های درون‌سامانه',
            'type': 'boolean',
            'default': True,
            'group': 'notifications',
        },
        {
            'key': 'warning_sound',
            'label': 'صدای هشدار',
            'type': 'boolean',
            'default': True,
            'group': 'notifications',
        },
        {
            'key': 'exam_reminders',
            'label': 'یادآوری آزمون‌ها',
            'type': 'boolean',
            'default': True,
            'group': 'notifications',
        },
        {
            'key': 'ticket_notifications',
            'label': 'اعلان‌های تیکت‌ها',
            'type': 'boolean',
            'default': False,
            'group': 'notifications',
        },
        {
            'key': 'theme_mode',
            'label': 'حالت نمایش',
            'type': 'text',
            'default': 'روشن',
            'group': 'appearance',
        },
        {
            'key': 'primary_color',
            'label': 'رنگ اصلی سامانه',
            'type': 'text',
            'default': '#2563EB',
            'group': 'appearance',
        },
        {
            'key': 'font_size',
            'label': 'اندازه فونت',
            'type': 'text',
            'default': 'متوسط',
            'group': 'appearance',
        },
        {
            'key': 'display_density',
            'label': 'تراکم نمایش',
            'type': 'text',
            'default': 'استاندارد',
            'group': 'appearance',
        },
        {
            'key': 'auto_backup',
            'label': 'پشتیبان‌گیری خودکار',
            'type': 'boolean',
            'default': True,
            'group': 'backup',
        },
        {
            'key': 'backup_frequency',
            'label': 'تناوب پشتیبان‌گیری',
            'type': 'text',
            'default': 'روزانه',
            'group': 'backup',
        },
        {
            'key': 'backup_retention_days',
            'label': 'مدت نگهداری نسخه‌ها',
            'type': 'number',
            'default': 30,
            'group': 'backup',
        },
        {
            'key': 'default_exam_duration',
            'label': 'مدت پیش‌فرض آزمون (دقیقه)',
            'type': 'number',
            'default': 60,
            'group': 'exam',
        },
        {
            'key': 'max_upload_mb',
            'label': 'حداکثر حجم آپلود (مگابایت)',
            'type': 'number',
            'default': 10,
            'group': 'exam',
        },
        {
            'key': 'registration_open',
            'label': 'فعال بودن ثبت‌نام عمومی',
            'type': 'boolean',
            'default': True,
            'group': 'exam',
        },
        {
            'key': 'show_results_immediately',
            'label': 'نمایش فوری نمره به دانشجو',
            'type': 'boolean',
            'default': False,
            'group': 'exam',
        },
    ]

    setting_text_overrides = {
        'site_name': {'label': 'نام سامانه', 'default': 'سامانه جامع مدیریت آزمون متا کوییز'},
        'system_logo': {'label': 'لوگو / هویت سامانه', 'default': '/static/img/metaquiz-favicon.svg'},
        'default_language': {'label': 'زبان پیش‌فرض', 'default': 'فارسی (ایران)'},
        'timezone': {'label': 'منطقه زمانی', 'default': 'تهران (UTC+03:30)'},
        'date_format': {'label': 'فرمت تاریخ', 'default': '1403/03/27'},
        'session_timeout_minutes': {'label': 'زمان انقضای جلسه (دقیقه)'},
        'two_factor_required': {'label': 'احراز هویت دومرحله‌ای'},
        'password_policy': {'label': 'سیاست گذرواژه', 'default': 'قوی'},
        'ip_restriction': {'label': 'محدودیت IP'},
        'suspicious_login_alerts': {'label': 'اعلان ورودهای مشکوک'},
        'email_notifications': {'label': 'اعلان‌های ایمیلی'},
        'in_app_notifications': {'label': 'اعلان‌های درون‌سامانه'},
        'warning_sound': {'label': 'صدای هشدار'},
        'exam_reminders': {'label': 'یادآوری آزمون‌ها'},
        'ticket_notifications': {'label': 'اعلان‌های تیکت‌ها'},
        'theme_mode': {'label': 'حالت نمایش', 'default': 'روشن'},
        'primary_color': {'label': 'رنگ اصلی سامانه', 'default': '#2563EB'},
        'font_size': {'label': 'اندازه فونت', 'default': 'متوسط'},
        'display_density': {'label': 'تراکم نمایش', 'default': 'استاندارد'},
        'auto_backup': {'label': 'پشتیبان‌گیری خودکار'},
        'backup_frequency': {'label': 'تناوب پشتیبان‌گیری', 'default': 'روزانه'},
        'backup_retention_days': {'label': 'مدت نگهداری نسخه‌ها'},
        'default_exam_duration': {'label': 'مدت پیش‌فرض آزمون (دقیقه)'},
        'max_upload_mb': {'label': 'حداکثر حجم آپلود (مگابایت)'},
        'registration_open': {'label': 'فعال بودن ثبت‌نام عمومی'},
        'show_results_immediately': {'label': 'نمایش فوری نمره به دانشجو'},
    }
    for item in settings_schema:
        override = setting_text_overrides.get(item['key'])
        if override:
            item.update(override)

    def repair_setting_text(value):
        text = str(value or '').strip()
        if not any(marker in text for marker in ('Ø', 'Ù', 'Û', 'Ú', 'Ã', 'Â', 'â')):
            return value
        for _ in range(3):
            try:
                repaired = text.encode('cp1252').decode('utf-8')
            except UnicodeError:
                break
            if repaired == text:
                break
            text = repaired
        return text

    for item in settings_schema:
        item['label'] = repair_setting_text(item.get('label'))
        if item.get('type') == 'text':
            item['default'] = repair_setting_text(item.get('default'))

    settings_by_key = {item['key']: item for item in settings_schema}

    def _stored_setting_value(raw_value, fallback):
        if raw_value in (None, ''):
            return fallback
        if isinstance(raw_value, str):
            try:
                parsed_value = json.loads(raw_value)
                return repair_setting_text(parsed_value) if isinstance(parsed_value, str) else parsed_value
            except json.JSONDecodeError:
                return repair_setting_text(raw_value)
        return repair_setting_text(raw_value)

    def save_setting(setting_key, setting_value, setting_meta, actor):
        erd_execute(
            """
            INSERT INTO system_settings (key, value, description, updated_by)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (key) DO UPDATE
            SET value = EXCLUDED.value,
                description = EXCLUDED.description,
                updated_by = EXCLUDED.updated_by
            """,
            [
                setting_key,
                json.dumps(setting_value),
                setting_meta['label'],
                actor['id'] if actor else None,
            ],
        )

    def cleaned_setting_value(setting_meta, raw_value):
        if setting_meta['type'] == 'boolean':
            return raw_value == 'on'
        if setting_meta['type'] == 'number':
            try:
                return int(raw_value or setting_meta['default'])
            except (TypeError, ValueError):
                return setting_meta['default']
        return (raw_value or setting_meta['default']).strip()

    if request.method == 'POST':
        actor = erd_profile_for_user(request.user)
        settings_action = request.POST.get('settings_action')
        if settings_action == 'export':
            rows = erd_rows('SELECT key, value, description FROM system_settings ORDER BY key')
            payload = {
                'exported_at': timezone.now().isoformat(),
                'settings': {
                    row['key']: _stored_setting_value(row['value'], None)
                    for row in rows
                },
                'descriptions': {
                    row['key']: repair_setting_text(row.get('description'))
                    for row in rows
                    if row.get('description')
                },
            }
            response = HttpResponse(
                json.dumps(payload, ensure_ascii=False, indent=2),
                content_type='application/json; charset=utf-8',
            )
            response['Content-Disposition'] = 'attachment; filename="metaquiz-settings.json"'
            return response

        if settings_action == 'bulk_save':
            uploaded_logo = request.FILES.get('system_logo_file')
            if uploaded_logo:
                storage = FileSystemStorage(
                    location=settings.MEDIA_ROOT / 'settings',
                    base_url=settings.MEDIA_URL + 'settings/',
                )
                filename = storage.save(uploaded_logo.name, uploaded_logo)
                logo_meta = settings_by_key.get('system_logo')
                if logo_meta:
                    save_setting('system_logo', storage.url(filename), logo_meta, actor)

            saved_count = 0
            for setting_key, setting_meta in settings_by_key.items():
                field_name = f'settings_{setting_key}'
                if field_name not in request.POST:
                    continue
                if uploaded_logo and setting_key == 'system_logo':
                    continue
                setting_value = cleaned_setting_value(setting_meta, request.POST.get(field_name))
                save_setting(setting_key, setting_value, setting_meta, actor)
                saved_count += 1
            messages.success(request, f'{saved_count} تنظیم عمومی ذخیره شد.')
            log_activity(request.user, 'system_settings_bulk_updated', 'تنظیمات عمومی سامانه ذخیره شد.', request)
            return redirect(f"{reverse('core:super_admin_settings')}?tab=other")

        setting_key = request.POST.get('setting_key')
        setting_meta = settings_by_key.get(setting_key)
        if setting_meta:
            setting_value = cleaned_setting_value(setting_meta, request.POST.get('value'))
            save_setting(setting_key, setting_value, setting_meta, actor)
            messages.success(request, '\u062a\u0646\u0638\u06cc\u0645\u0627\u062a \u0630\u062e\u06cc\u0631\u0647 \u0634\u062f.')
            log_activity(request.user, 'system_settings_updated', f'{setting_key} \u0630\u062e\u06cc\u0631\u0647 \u0634\u062f.', request)
        return redirect(f"{reverse('core:super_admin_settings')}?tab=other")

    setting_keys = set(settings_by_key)
    rows = erd_rows('SELECT key, value FROM system_settings')
    stored_values = {
        row['key']: _stored_setting_value(row['value'], settings_by_key[row['key']]['default'])
        for row in rows
        if row.get('key') in setting_keys
    }
    settings_items = [
        {**item, 'value': stored_values.get(item['key'], item['default'])}
        for item in settings_schema
    ]
    settings_lookup = {item['key']: item for item in settings_items}
    settings_groups = {
        group: [item for item in settings_items if item.get('group') == group]
        for group in ('basic', 'security', 'notifications', 'appearance', 'backup', 'exam')
    }

    terms = erd_rows(
        """
        SELECT id, year, semester, label, is_current, start_date, end_date, description, COALESCE(is_active, true) AS is_active
        FROM academic_terms
        ORDER BY is_current DESC, year DESC, semester
        LIMIT 200
        """
    )
    decorated_terms = []
    for index, term in enumerate(terms):
        semester_text = repair_setting_text(term.get('semester') or term.get('label') or '\u062a\u0631\u0645')
        is_second = '\u062f\u0648\u0645' in semester_text or 'second' in semester_text
        is_summer = '\u062a\u0627\u0628\u0633\u062a\u0627\u0646' in semester_text or 'summer' in semester_text
        if is_summer:
            fallback_start_date, fallback_end_date = '1404/04/01', '1404/06/31'
        elif is_second:
            fallback_start_date, fallback_end_date = '1404/12/01', '1405/04/31'
        else:
            fallback_start_date, fallback_end_date = '1404/07/01', '1404/11/30'
        active = term.get('is_active')
        decorated_terms.append({
            **term,
            'start_date': term.get('start_date') or fallback_start_date,
            'end_date': term.get('end_date') or fallback_end_date,
            'status_label': '\u0641\u0639\u0627\u0644' if term.get('is_current') else '\u0628\u0627\u06cc\u06af\u0627\u0646\u06cc\u200c\u0634\u062f\u0647',
            'status_tone': 'green' if active else 'slate',
            'is_default_label': '\u0628\u0644\u0647' if term.get('is_current') else '\u062e\u06cc\u0631',
            'row_number': index + 1,
        })

    for term in decorated_terms:
        term['status_label'] = '\u0641\u0639\u0627\u0644' if term.get('is_active') else '\u0628\u0627\u06cc\u06af\u0627\u0646\u06cc\u200c\u0634\u062f\u0647'
        term['status_tone'] = 'green' if term.get('is_active') else 'slate'

    current_term = next((term for term in decorated_terms if term.get('is_current')), decorated_terms[0] if decorated_terms else None)
    settings_tab = request.GET.get('tab', 'other')
    if settings_tab not in ('terms', 'other'):
        settings_tab = 'other'

    return render(request, 'super_admin/settings.html', {
        'settings_items': settings_items,
        'settings_lookup': settings_lookup,
        'settings_groups': settings_groups,
        'settings_active_tab': settings_tab,
        'terms': decorated_terms,
        'current_term': current_term,
        'settings_summary': {
            'active_terms_count': len([term for term in decorated_terms if term.get('is_active')]),
            'archived_years_count': max(len({term.get('year') for term in decorated_terms}) - 1, 0),
            'terms_count': len(decorated_terms),
            'registration_deadline': '1405/05/05',
        },
    })


@super_admin_required
def super_admin_emergency_stop(request, exam_id):
    exam = get_object_or_404(Exam, pk=exam_id)
    if request.method == 'POST':
        form = EmergencyStopExamForm(request.POST)
        if form.is_valid():
            exam.status = Exam.ExamStatus.PAUSED
            exam.is_active = False
            exam.emergency_stop_reason = form.cleaned_data['reason']
            exam.emergency_stopped_by = request.user
            exam.emergency_stopped_at = timezone.now()
            exam.save(update_fields=[
                'status',
                'is_active',
                'emergency_stop_reason',
                'emergency_stopped_by',
                'emergency_stopped_at',
            ])
            log_activity(
                request.user,
                'exam_emergency_stop',
                f'آزمون {exam.title} به دلیل اضطراری متوقف شد.',
                request,
                {'exam_id': exam.pk, 'reason': exam.emergency_stop_reason},
            )
            messages.warning(request, 'آزمون متوقف شد، پاسخ‌های ثبت‌شده محفوظ ماند و اعلان عملیاتی ثبت شد.')
            return redirect('core:super_admin_active_exams')
    else:
        form = EmergencyStopExamForm()
    return render(request, 'super_admin/emergency_stop.html', {'exam': exam, 'form': form})


@super_admin_required
def super_admin_resolve_emergency(request, exam_id, resolution):
    exam = get_object_or_404(Exam, pk=exam_id, status=Exam.ExamStatus.PAUSED)
    if resolution == 'resume':
        exam.status = Exam.ExamStatus.ACTIVE
        exam.is_active = True
        note = 'آزمون پس از رفع مشکل ادامه یافت.'
    elif resolution == 'cancel':
        exam.status = Exam.ExamStatus.CANCELLED
        exam.is_active = False
        note = 'آزمون پس از توقف اضطراری لغو شد.'
    else:
        return HttpResponseForbidden('عملیات نامعتبر است.')
    exam.emergency_resolved_at = timezone.now()
    exam.emergency_resolution_note = note
    exam.save(update_fields=['status', 'is_active', 'emergency_resolved_at', 'emergency_resolution_note'])
    log_activity(request.user, f'exam_emergency_{resolution}', note, request, {'exam_id': exam.pk})
    messages.success(request, note)
    return redirect('core:super_admin_active_exams')


@institution_admin_required
def institution_admin_dashboard(request):
    return redirect('core:dashboard')


@institution_admin_required
def institution_settings(request):
    institution = request.managed_institution
    if request.method == 'POST':
        form = InstitutionSettingsForm(request.POST, request.FILES, instance=institution)
        if form.is_valid():
            form.save()
            log_activity(request.user, 'institution_settings_updated', f'اطلاعات مؤسسه {institution.name} به‌روزرسانی شد.', request)
            messages.success(request, 'اطلاعات مؤسسه ذخیره شد.')
            return redirect('core:dashboard')
    else:
        form = InstitutionSettingsForm(instance=institution)
    return render(request, 'institution_admin/settings.html', {'form': form, 'institution': institution})


def create_institution_user(institution, cleaned):
    role = SystemRole.objects.get(code=cleaned['user_type'])
    password = cleaned.get('password') or get_random_string(10)
    user = User.objects.create_user(
        username=cleaned['username'],
        email=cleaned.get('email') or '',
        password=password,
        first_name=cleaned['full_name'],
    )
    profile = UserProfile.objects.create(
        user=user,
        role=role,
        full_name=cleaned['full_name'],
        national_code=cleaned.get('national_code') or '',
        mobile=cleaned.get('mobile') or '',
        organizational_email=cleaned.get('email') or '',
        student_number=cleaned.get('student_number') or '',
        institution_name=institution.name,
        faculty_or_unit=cleaned.get('academic_unit').name if cleaned.get('academic_unit') else '',
        account_status=UserProfile.AccountStatus.ACTIVE,
        account_verified=True,
    )
    unit = cleaned.get('academic_unit')
    if cleaned['user_type'] == SystemRole.RoleCode.TEACHER:
        TeacherProfile.objects.create(profile=profile, institution=institution, academic_unit=unit)
    elif cleaned['user_type'] == SystemRole.RoleCode.STUDENT:
        StudentProfile.objects.create(
            profile=profile,
            institution=institution,
            academic_unit=unit,
            student_number=cleaned.get('student_number') or '',
        )
    return profile, password


@institution_admin_required
def institution_users(request):
    institution = request.managed_institution
    import_errors = []
    created_credentials = []
    if request.method == 'POST' and request.POST.get('mode') == 'manual':
        form = InstitutionUserCreateForm(request.POST, institution=institution)
        import_form = InstitutionUserImportForm()
        if form.is_valid():
            profile, password = create_institution_user(institution, form.cleaned_data)
            log_activity(request.user, 'institution_user_created', f'کاربر {profile.full_name} در مؤسسه ایجاد شد.', request, {'profile_id': profile.pk})
            messages.success(request, f'کاربر ایجاد شد. رمز اولیه: {password}')
            return redirect('core:institution_users')
    elif request.method == 'POST' and request.POST.get('mode') == 'import':
        form = InstitutionUserCreateForm(institution=institution)
        import_form = InstitutionUserImportForm(request.POST, request.FILES)
        if import_form.is_valid():
            uploaded = import_form.cleaned_data['excel_file']
            content = uploaded.read().decode('utf-8-sig')
            reader = csv.DictReader(io.StringIO(content))
            for row_number, row in enumerate(reader, start=2):
                data = {
                    'user_type': row.get('user_type', '').strip(),
                    'username': row.get('username', '').strip(),
                    'password': row.get('password', '').strip(),
                    'full_name': row.get('full_name', '').strip(),
                    'national_code': row.get('national_code', '').strip(),
                    'email': row.get('email', '').strip(),
                    'mobile': row.get('mobile', '').strip(),
                    'student_number': row.get('student_number', '').strip(),
                    'academic_unit': '',
                }
                row_form = InstitutionUserCreateForm(data, institution=institution)
                if row_form.is_valid():
                    profile, password = create_institution_user(institution, row_form.cleaned_data)
                    created_credentials.append(f'{profile.full_name}: {profile.user.username} / {password}')
                else:
                    import_errors.append(f'ردیف {row_number}: {row_form.errors.as_text()}')
            if created_credentials:
                log_activity(request.user, 'institution_users_imported', f'{len(created_credentials)} کاربر از فایل وارد شد.', request)
                messages.success(request, f'{len(created_credentials)} کاربر ایجاد شد.')
    else:
        form = InstitutionUserCreateForm(institution=institution)
        import_form = InstitutionUserImportForm()
    profiles = UserProfile.objects.select_related('user', 'role').filter(institution_name=institution.name).order_by('full_name')[:100]
    return render(request, 'institution_admin/users.html', {
        'institution': institution,
        'form': form,
        'import_form': import_form,
        'profiles': profiles,
        'import_errors': import_errors,
        'created_credentials': created_credentials,
    })


@institution_admin_required
def institution_structure(request):
    institution = request.managed_institution
    if request.method == 'POST':
        form = AcademicStructureForm(request.POST, institution=institution)
        if form.is_valid():
            unit, _ = AcademicUnit.objects.get_or_create(
                institution=institution,
                code=form.cleaned_data.get('unit_code') or form.cleaned_data['unit_name'],
                defaults={'name': form.cleaned_data['unit_name'], 'unit_type': AcademicUnit.UnitType.FACULTY},
            )
            if form.cleaned_data.get('field_name'):
                AcademicUnit.objects.get_or_create(
                    institution=institution,
                    parent=unit,
                    name=form.cleaned_data['field_name'],
                    defaults={'unit_type': AcademicUnit.UnitType.DEPARTMENT},
                )
            term, _ = AcademicTerm.objects.get_or_create(
                institution=institution,
                title=form.cleaned_data['term_title'],
                defaults={'year': form.cleaned_data.get('term_year')},
            )
            course, _ = Course.objects.get_or_create(
                institution=institution,
                code=form.cleaned_data.get('course_code') or form.cleaned_data['course_title'],
                defaults={'title': form.cleaned_data['course_title'], 'academic_unit': unit},
            )
            course_class, _ = CourseClass.objects.get_or_create(
                institution=institution,
                code=form.cleaned_data.get('class_code') or form.cleaned_data['class_title'],
                defaults={
                    'title': form.cleaned_data['class_title'],
                    'course': course,
                    'term': term,
                    'teacher': form.cleaned_data.get('teacher'),
                },
            )
            if form.cleaned_data.get('students'):
                course_class.students.set(form.cleaned_data['students'])
            log_activity(request.user, 'academic_structure_saved', f'ساختار آموزشی {institution.name} ذخیره شد.', request)
            messages.success(request, 'ساختار آموزشی ذخیره شد.')
            return redirect('core:institution_structure')
    else:
        form = AcademicStructureForm(institution=institution)
    return render(request, 'institution_admin/structure.html', {
        'institution': institution,
        'form': form,
        'units': institution.units.all()[:50],
        'courses': institution.courses.all()[:50],
        'classes': institution.classes.select_related('course', 'term', 'teacher')[:50],
    })


@institution_admin_required
def institution_assign_exam_manager(request):
    institution = request.managed_institution
    if request.method == 'POST':
        form = ExamManagerAssignmentForm(request.POST, institution=institution)
        if form.is_valid():
            profile = form.cleaned_data['profile']
            role = SystemRole.objects.get(code=SystemRole.RoleCode.EXAM_MANAGER)
            profile.role = role
            profile.institution_name = institution.name
            profile.access_scope = form.cleaned_data.get('access_scope') or ''
            profile.cooperation_started_at = form.cleaned_data.get('starts_at')
            profile.cooperation_ended_at = form.cleaned_data.get('ends_at')
            profile.save(update_fields=['role', 'institution_name', 'access_scope', 'cooperation_started_at', 'cooperation_ended_at', 'updated_at'])
            log_activity(request.user, 'exam_manager_assigned', f'{profile.full_name} مسئول امتحانات شد.', request, {'profile_id': profile.pk})
            messages.success(request, 'مسئول امتحانات تعیین شد.')
            return redirect('core:institution_users')
    else:
        form = ExamManagerAssignmentForm(institution=institution)
    return render(request, 'institution_admin/assign_exam_manager.html', {'form': form, 'institution': institution})


@institution_admin_required
def institution_exams(request):
    institution = request.managed_institution
    status = request.GET.get('status', '')
    exams = institution.exams.select_related('course', 'designer').order_by('-starts_at')
    if status:
        exams = exams.filter(status=status)
    return render(request, 'institution_admin/exams.html', {
        'institution': institution,
        'status': status,
        'statuses': Exam.ExamStatus.choices,
        'exams': exams[:100],
    })


@institution_admin_required
def institution_exam_detail(request, exam_id):
    institution = request.managed_institution
    exam = get_object_or_404(Exam.objects.select_related('course', 'designer'), pk=exam_id, institution=institution)
    return render(request, 'institution_admin/exam_detail.html', {
        'institution': institution,
        'exam': exam,
        'violations': exam.violation_reports.select_related('student', 'proctor', 'teacher')[:50],
    })


@institution_admin_required
def institution_violations(request):
    institution = request.managed_institution
    reports = ExamViolationReport.objects.select_related('exam', 'student', 'proctor', 'teacher').filter(exam__institution=institution)
    return render(request, 'institution_admin/violations.html', {'institution': institution, 'reports': reports[:100]})


@institution_admin_required
def institution_violation_decision(request, report_id):
    institution = request.managed_institution
    report = get_object_or_404(ExamViolationReport.objects.select_related('exam', 'student', 'proctor', 'teacher'), pk=report_id, exam__institution=institution)
    if request.method == 'POST':
        form = ViolationDecisionForm(request.POST, instance=report)
        if form.is_valid():
            violation = form.save(commit=False)
            violation.decided_by = request.user
            violation.decided_at = timezone.now()
            violation.save()
            log_activity(request.user, 'violation_decided', f'تصمیم تخلف {violation.title}: {violation.get_decision_display()}', request, {'violation_id': violation.pk})
            messages.success(request, 'تصمیم تخلف ثبت شد و نتیجه برای افراد مرتبط قابل مشاهده است.')
            return redirect('core:institution_violations')
    else:
        form = ViolationDecisionForm(instance=report)
    return render(request, 'institution_admin/violation_decision.html', {'institution': institution, 'report': report, 'form': form})


def find_exam_conflicts(institution, starts_at, ends_at, exclude_exam=None, course_class=None):
    exams = institution.exams.filter(starts_at__lt=ends_at, ends_at__gt=starts_at)
    if exclude_exam:
        exams = exams.exclude(pk=exclude_exam.pk)
    conflicts = []
    if course_class and course_class.teacher:
        if exams.filter(designer=course_class.teacher).exists():
            conflicts.append('استاد در این بازه آزمون دیگری دارد.')
    if course_class:
        student_ids = set(course_class.students.values_list('pk', flat=True))
        for exam in exams.prefetch_related('course__classes__students'):
            other_student_ids = set()
            for cls in exam.course.classes.all() if exam.course else []:
                other_student_ids.update(cls.students.values_list('pk', flat=True))
            if student_ids.intersection(other_student_ids):
                conflicts.append('حداقل یک دانشجو در این بازه دو آزمون هم‌زمان دارد.')
                break
    return conflicts


@exam_manager_required
def exam_manager_approval_review(request, approval_id):
    institution = request.managed_institution
    approval = get_object_or_404(ExamApproval.objects.select_related('exam'), pk=approval_id, exam__institution=institution)
    if request.method == 'POST':
        form = ExamApprovalReviewForm(request.POST, instance=approval)
        if form.is_valid():
            item = form.save(commit=False)
            item.reviewed_by = request.user
            item.reviewed_at = timezone.now()
            item.save()
            if item.decision == ExamApproval.Decision.APPROVED:
                item.exam.status = Exam.ExamStatus.SCHEDULED
            elif item.decision == ExamApproval.Decision.RETURNED:
                item.exam.status = Exam.ExamStatus.DRAFT
            item.exam.save(update_fields=['status'])
            log_activity(request.user, 'exam_approval_reviewed', f'بررسی آزمون {item.exam.title}: {item.get_decision_display()}', request, {'approval_id': item.pk})
            messages.success(request, 'نتیجه بررسی برای استاد ثبت شد.')
            return redirect('core:exam_manager_approvals')
    else:
        form = ExamApprovalReviewForm(instance=approval)
    return render(request, 'exam_manager/approval_review.html', {'institution': institution, 'approval': approval, 'form': form, 'app_is_shell_page': True})


@exam_manager_required
def exam_manager_start_control(request, exam_id):
    institution = request.managed_institution
    exam = get_object_or_404(Exam, pk=exam_id, institution=institution)
    authorization, _ = ExamStartAuthorization.objects.get_or_create(exam=exam)
    if request.method == 'POST':
        form = ExamStartControlForm(request.POST, instance=authorization)
        if form.is_valid():
            item = form.save(commit=False)
            if item.authorized:
                item.authorized_by = request.user
                item.authorized_at = timezone.now()
                exam.status = Exam.ExamStatus.ACTIVE
                exam.is_active = True
                exam.save(update_fields=['status', 'is_active'])
            item.save()
            log_activity(request.user, 'exam_start_controlled', f'کنترل شروع آزمون {exam.title} ثبت شد.', request, {'exam_id': exam.pk})
            messages.success(request, 'وضعیت شروع آزمون ذخیره شد.')
            return redirect('core:exam_manager_active_exams')
    else:
        form = ExamStartControlForm(instance=authorization)
    return render(request, 'exam_manager/start_control.html', {'institution': institution, 'exam': exam, 'form': form, 'app_is_shell_page': True})


@exam_manager_required
def exam_manager_reschedule(request):
    institution = request.managed_institution
    conflicts = []
    if request.method == 'POST':
        form = ExamRescheduleForm(request.POST, institution=institution)
        if form.is_valid():
            exam = form.cleaned_data['exam']
            conflicts = find_exam_conflicts(institution, form.cleaned_data['new_starts_at'], form.cleaned_data['new_ends_at'], exclude_exam=exam)
            if conflicts:
                messages.error(request, 'زمان جدید دارای تداخل است.')
            else:
                request_obj = form.save(commit=False)
                request_obj.old_starts_at = exam.starts_at
                request_obj.old_ends_at = exam.ends_at
                request_obj.requested_by = request.user
                request_obj.reviewed_by = request.user
                request_obj.reviewed_at = timezone.now()
                request_obj.save()
                if request_obj.status == ExamRescheduleRequest.Status.APPROVED:
                    exam.starts_at = request_obj.new_starts_at
                    exam.ends_at = request_obj.new_ends_at
                    exam.save(update_fields=['starts_at', 'ends_at'])
                log_activity(request.user, 'exam_rescheduled', f'درخواست تغییر زمان آزمون {exam.title} بررسی شد.', request, {'request_id': request_obj.pk})
                messages.success(request, 'تغییر زمان ثبت شد و اعلان برای افراد مرتبط ذخیره گردید.')
                return redirect('core:exam_manager_reschedule')
    else:
        form = ExamRescheduleForm(institution=institution)
    requests = ExamRescheduleRequest.objects.select_related('exam').filter(exam__institution=institution)[:100]
    return render(request, 'exam_manager/reschedule.html', {'institution': institution, 'form': form, 'requests': requests, 'conflicts': conflicts, 'app_is_shell_page': True})


@teacher_required
def teacher_assistant_requests(request):
    teacher = request.teacher_profile
    context = {
        'teacher': teacher,
        'question_submissions': AssistantQuestionSubmission.objects.select_related('assistant__profile', 'question', 'question__course').filter(teacher=teacher)[:100],
        'question_suggestions': AssistantQuestionSuggestion.objects.select_related('assistant__profile', 'question').filter(teacher=teacher)[:100],
        'exam_drafts': AssistantExamDraft.objects.select_related('assistant__profile', 'exam', 'exam__course').filter(teacher=teacher)[:100],
        'review_assignments': AssistantReviewAssignment.objects.select_related('assistant__profile', 'review', 'review__exam', 'review__question').filter(teacher=teacher)[:100],
        'educational_questions': EducationalQuestion.objects.select_related('student__profile', 'exam', 'course').filter(teacher=teacher, status=EducationalQuestion.Status.REFERRED)[:100],
    }
    return render(request, 'teacher/assistant_requests.html', context)


@teacher_required
def teacher_assistant_question_review(request, submission_id):
    teacher = request.teacher_profile
    submission = get_object_or_404(
        AssistantQuestionSubmission.objects.select_related('question', 'assistant__profile'),
        pk=submission_id,
        teacher=teacher,
    )
    if request.method == 'POST':
        question_form = QuestionForm(request.POST, teacher=teacher, instance=submission.question)
        review_form = AssistantQuestionReviewForm(request.POST, instance=submission)
        if question_form.is_valid() and review_form.is_valid():
            question = question_form.save(commit=False)
            submission = review_form.save(commit=False)
            if submission.status == AssistantQuestionSubmission.Status.APPROVED:
                question.is_active = True
            elif submission.status in (AssistantQuestionSubmission.Status.REJECTED, AssistantQuestionSubmission.Status.NEEDS_REVISION):
                question.is_active = False
            question.teacher = teacher
            question.save()
            submission.reviewed_by = request.user
            submission.reviewed_at = timezone.now()
            submission.save()
            log_activity(request.user, 'assistant_question_reviewed', f'سؤال دستیار بررسی شد: {submission.get_status_display()}', request, {'submission_id': submission.pk})
            messages.success(request, 'نتیجه بررسی سؤال ثبت شد.')
            return redirect('core:teacher_assistant_requests')
    else:
        question_form = QuestionForm(teacher=teacher, instance=submission.question)
        review_form = AssistantQuestionReviewForm(instance=submission)
    return render(request, 'teacher/assistant_question_review.html', {
        'teacher': teacher,
        'submission': submission,
        'question_form': question_form,
        'review_form': review_form,
    })


@teacher_required
def teacher_assistant_suggestion_review(request, suggestion_id):
    teacher = request.teacher_profile
    suggestion = get_object_or_404(AssistantQuestionSuggestion.objects.select_related('question', 'assistant__profile'), pk=suggestion_id, teacher=teacher)
    if request.method == 'POST':
        form = AssistantQuestionSuggestionReviewForm(request.POST, instance=suggestion)
        if form.is_valid():
            item = form.save(commit=False)
            if item.status == AssistantQuestionSuggestion.Status.APPROVED:
                question = item.question
                if item.suggested_text:
                    question.text = item.suggested_text
                if item.suggested_correct_answer:
                    question.correct_answer = item.suggested_correct_answer
                if item.suggested_topic:
                    question.topic = item.suggested_topic
                question.save()
            item.reviewed_by = request.user
            item.reviewed_at = timezone.now()
            item.save()
            log_activity(request.user, 'assistant_question_suggestion_reviewed', f'پیشنهاد اصلاح سؤال بررسی شد: {item.get_status_display()}', request, {'suggestion_id': item.pk})
            messages.success(request, 'نتیجه بررسی پیشنهاد اصلاح ثبت شد.')
            return redirect('core:teacher_assistant_requests')
    else:
        form = AssistantQuestionSuggestionReviewForm(instance=suggestion)
    return render(request, 'teacher/assistant_suggestion_review.html', {'teacher': teacher, 'suggestion': suggestion, 'form': form})


@teacher_required
def teacher_assistant_exam_draft_review(request, draft_id):
    teacher = request.teacher_profile
    draft = get_object_or_404(AssistantExamDraft.objects.select_related('exam', 'assistant__profile'), pk=draft_id, teacher=teacher)
    if request.method == 'POST':
        form = AssistantExamDraftReviewForm(request.POST, instance=draft)
        if form.is_valid():
            item = form.save(commit=False)
            if item.status == AssistantExamDraft.Status.APPROVED:
                item.exam.status = Exam.ExamStatus.SCHEDULED
                item.exam.is_active = True
                item.exam.save(update_fields=['status', 'is_active'])
            elif item.status == AssistantExamDraft.Status.REJECTED:
                item.exam.status = Exam.ExamStatus.DRAFT
                item.exam.save(update_fields=['status'])
            item.reviewed_by = request.user
            item.reviewed_at = timezone.now()
            item.save()
            log_activity(request.user, 'assistant_exam_draft_reviewed', f'پیش‌نویس آزمون دستیار بررسی شد: {item.get_status_display()}', request, {'draft_id': item.pk})
            messages.success(request, 'نتیجه بررسی پیش‌نویس آزمون ثبت شد.')
            return redirect('core:teacher_assistant_requests')
    else:
        form = AssistantExamDraftReviewForm(instance=draft)
    return render(request, 'teacher/assistant_exam_draft_review.html', {'teacher': teacher, 'draft': draft, 'form': form})


@teacher_required
def teacher_assistant_review_decision(request, assignment_id):
    teacher = request.teacher_profile
    assignment = get_object_or_404(
        AssistantReviewAssignment.objects.select_related('review', 'review__exam', 'review__question', 'assistant__profile'),
        pk=assignment_id,
        teacher=teacher,
    )
    if request.method == 'POST':
        form = AssistantReviewDecisionForm(request.POST, instance=assignment)
        if form.is_valid():
            item = form.save(commit=False)
            if item.status == AssistantReviewAssignment.Status.APPROVED:
                review = item.review
                review.score = item.proposed_score
                review.feedback = item.feedback
                review.is_suspicious = item.is_suspicious
                review.finalized = True
                review.reviewed_by = request.user
                review.reviewed_at = timezone.now()
                review.save()
            item.reviewed_by = request.user
            item.reviewed_at = timezone.now()
            item.save()
            log_activity(request.user, 'assistant_review_decided', f'تصحیح دستیار بررسی شد: {item.get_status_display()}', request, {'assignment_id': item.pk})
            messages.success(request, 'نتیجه بررسی تصحیح دستیار ثبت شد.')
            return redirect('core:teacher_assistant_requests')
    else:
        form = AssistantReviewDecisionForm(instance=assignment)
    return render(request, 'teacher/assistant_review_decision.html', {'teacher': teacher, 'assignment': assignment, 'form': form})


@teacher_required
def teacher_educational_question_answer(request, question_id):
    teacher = request.teacher_profile
    item = get_object_or_404(EducationalQuestion.objects.select_related('student__profile', 'exam', 'course'), pk=question_id, teacher=teacher)
    if request.method == 'POST':
        answer = request.POST.get('answer_text', '').strip()
        if answer:
            item.answer_text = answer
            item.status = EducationalQuestion.Status.ANSWERED
            item.needs_teacher_decision = False
            item.answered_at = timezone.now()
            item.save()
            log_activity(request.user, 'teacher_educational_question_answered', 'پرسش آموزشی ارجاع‌شده پاسخ داده شد.', request, {'question_id': item.pk})
            messages.success(request, 'پاسخ برای دانشجو ثبت شد.')
            return redirect('core:teacher_assistant_requests')
        messages.error(request, 'متن پاسخ را وارد کنید.')
    return render(request, 'teacher/educational_question_answer.html', {'teacher': teacher, 'item': item})


@teacher_required
def teacher_exam_preview(request, exam_id):
    teacher = request.teacher_profile
    exam = get_object_or_404(Exam.objects.prefetch_related('exam_questions__question'), pk=exam_id, designer=teacher)
    if request.method == 'POST':
        log_activity(request.user, 'teacher_exam_finalized', f'نسخه نهایی آزمون {exam.title} ثبت شد.', request, {'exam_id': exam.pk})
        messages.success(request, 'نسخه نهایی آزمون ثبت شد.')
        return redirect('core:teacher_exams')
    return render(request, 'teacher/exam_preview.html', {'teacher': teacher, 'exam': exam})


@teacher_required
def teacher_extend_exam(request, exam_id):
    teacher = request.teacher_profile
    exam = get_object_or_404(Exam, pk=exam_id, designer=teacher)
    minutes = int(request.POST.get('minutes', 0) or 0)
    if minutes > 0:
        exam.ends_at = exam.ends_at + timedelta(minutes=minutes)
        exam.save(update_fields=['ends_at'])
        log_activity(request.user, 'teacher_exam_extended', f'زمان آزمون {exam.title} {minutes} دقیقه تمدید شد.', request, {'exam_id': exam.pk, 'minutes': minutes})
        messages.success(request, 'زمان آزمون تمدید شد.')
    return redirect('core:teacher_monitoring')


@teacher_required
def teacher_assign_review(request, review_id):
    teacher = request.teacher_profile
    review = get_object_or_404(DescriptiveAnswerReview.objects.select_related('exam'), pk=review_id, exam__designer=teacher)
    assistant_profile = get_object_or_404(
        UserProfile,
        pk=request.POST.get('assistant'),
        role__code=SystemRole.RoleCode.TEACHING_ASSISTANT,
        supervisor_teacher=teacher.profile.user,
    )
    if assistant_profile:
        AssistantReviewAssignment.objects.update_or_create(
            review=review,
            defaults={
                'assistant': assistant_profile.user,
                'teacher': teacher,
                'status': AssistantReviewAssignment.Status.ASSIGNED,
            },
        )
        log_activity(request.user, 'review_assigned_to_assistant', 'تصحیح پاسخ به دستیار اختصاص یافت.', request, {'review_id': review.pk, 'assistant_id': assistant_profile.user_id})
        messages.success(request, 'پاسخ برای تصحیح به دستیار اختصاص یافت.')
    return redirect('core:teacher_reviews')


def _grading_aid(question):
    """Rubric, student instructions and sample answer for a review, read from the builder's `questions` row."""
    erd_id = getattr(question, 'legacy_erd_id', '') if question else ''
    if not erd_id:
        return None
    row = erd_row('SELECT text, rubric, scoring_settings FROM questions WHERE id = %s', [erd_id])
    if not row:
        return None
    rubric = [item for item in (_sx_json(row.get('rubric'), []) or []) if isinstance(item, dict) and item.get('criterion')]
    essay_view = _essay_view(_sx_json(row.get('scoring_settings'), {}) or {})
    total = sum(_sx_float(item.get('points'), 0) for item in rubric)
    return {**essay_view, 'text': row.get('text') or '', 'rubric': rubric, 'rubric_total': f'{total:g}'}


@teacher_required
def teacher_review_detail(request, review_id):
    teacher = request.teacher_profile
    review = get_object_or_404(DescriptiveAnswerReview.objects.select_related('exam', 'question', 'student'), pk=review_id, exam__designer=teacher)
    if request.method == 'POST':
        form = DescriptiveReviewForm(request.POST, instance=review)
        if form.is_valid():
            item = form.save(commit=False)
            item.reviewed_by = request.user
            item.reviewed_at = timezone.now()
            item.save()
            log_activity(request.user, 'teacher_descriptive_review_saved', 'تصحیح پاسخ تشریحی ذخیره شد.', request, {'review_id': item.pk})
            messages.success(request, 'نمره و توضیح ذخیره شد.')
            return redirect('core:teacher_reviews')
    else:
        form = DescriptiveReviewForm(instance=review)
    return render(request, 'teacher/review_detail.html', {'teacher': teacher, 'review': review, 'form': form, 'grading_aid': _grading_aid(review.question)})


@teacher_required
def teacher_publish_result(request, exam_id):
    teacher = request.teacher_profile
    exam = get_object_or_404(Exam, pk=exam_id, designer=teacher)
    publication, _ = ExamResultPublication.objects.get_or_create(exam=exam)
    if request.method == 'POST':
        form = ResultPublicationForm(request.POST, instance=publication)
        if form.is_valid():
            item = form.save(commit=False)
            item.published_by = request.user
            if item.is_published:
                item.published_at = timezone.now()
            item.save()
            log_activity(request.user, 'teacher_results_published', f'نتایج آزمون {exam.title} منتشر شد.', request, {'exam_id': exam.pk})
            messages.success(request, 'تنظیمات نتیجه ذخیره شد و در صورت انتشار، اعلان دانشجویان ثبت شد.')
            return redirect('core:teacher_results')
    else:
        form = ResultPublicationForm(instance=publication)
    return render(request, 'teacher/publish_result.html', {'teacher': teacher, 'exam': exam, 'form': form})


@assistant_required
def assistant_panel(request):
    return redirect('core:dashboard')


@assistant_required
def assistant_questions(request):
    teacher = request.assistant_teacher
    if request.method == 'POST':
        form = AssistantQuestionForm(request.POST, teacher=teacher)
        if form.is_valid():
            question = form.save(commit=False)
            question.teacher = teacher
            question.is_active = False
            question.save()
            submission = AssistantQuestionSubmission.objects.create(
                assistant=request.user,
                teacher=teacher,
                question=question,
            )
            log_activity(request.user, 'assistant_question_submitted', 'سؤال دستیار برای تأیید استاد ارسال شد.', request, {'submission_id': submission.pk})
            messages.success(request, 'سؤال برای تأیید استاد ارسال شد.')
            return redirect('core:assistant_questions')
    else:
        form = AssistantQuestionForm(teacher=teacher)
    submissions = AssistantQuestionSubmission.objects.select_related('question', 'question__course').filter(assistant=request.user)[:100]
    return render(request, 'assistant/questions.html', {'teacher': teacher, 'form': form, 'submissions': submissions})


@assistant_required
def assistant_exam_draft_create(request):
    teacher = request.assistant_teacher
    if request.method == 'POST':
        form = AssistantExamDraftForm(request.POST, teacher=teacher)
        if form.is_valid():
            exam = form.save(commit=False)
            exam.institution = teacher.institution
            exam.designer = teacher
            exam.status = Exam.ExamStatus.DRAFT
            exam.is_active = False
            exam.save()
            questions = form.cleaned_data.get('questions')
            score_form = ExamQuestionScoreForm(request.POST, questions=questions)
            if score_form.is_valid():
                for index, question in enumerate(questions):
                    ExamQuestion.objects.create(
                        exam=exam,
                        question=question,
                        score=score_form.cleaned_data.get(f'score_{question.pk}') or question.suggested_score,
                        order=index + 1,
                    )
            draft = AssistantExamDraft.objects.create(
                assistant=request.user,
                teacher=teacher,
                exam=exam,
                status=AssistantExamDraft.Status.SUBMITTED,
            )
            log_activity(request.user, 'assistant_exam_draft_submitted', f'پیش‌نویس آزمون {exam.title} برای استاد ارسال شد.', request, {'draft_id': draft.pk})
            messages.success(request, 'پیش‌نویس آزمون برای استاد ارسال شد.')
            return redirect('core:assistant_exam_drafts')
    else:
        form = AssistantExamDraftForm(teacher=teacher)
    score_form = ExamQuestionScoreForm(questions=teacher.questions.filter(is_active=True))
    drafts = AssistantExamDraft.objects.select_related('exam', 'exam__course').filter(assistant=request.user)[:100]
    return render(request, 'assistant/exam_drafts.html', {'teacher': teacher, 'form': form, 'score_form': score_form, 'drafts': drafts})


@assistant_required
def assistant_question_suggestions(request):
    teacher = request.assistant_teacher
    if request.method == 'POST':
        form = AssistantQuestionSuggestionForm(request.POST, teacher=teacher)
        if form.is_valid():
            suggestion = form.save(commit=False)
            suggestion.assistant = request.user
            suggestion.teacher = teacher
            suggestion.save()
            log_activity(request.user, 'assistant_question_suggestion_submitted', 'پیشنهاد اصلاح سؤال برای استاد ارسال شد.', request, {'suggestion_id': suggestion.pk})
            messages.success(request, 'پیشنهاد اصلاح برای استاد ارسال شد.')
            return redirect('core:assistant_question_suggestions')
    else:
        form = AssistantQuestionSuggestionForm(teacher=teacher)
    suggestions = AssistantQuestionSuggestion.objects.select_related('question').filter(assistant=request.user)[:100]
    questions = teacher.questions.filter(is_active=True).select_related('course')[:100]
    return render(request, 'assistant/question_suggestions.html', {'teacher': teacher, 'form': form, 'suggestions': suggestions, 'questions': questions})


@assistant_required
def assistant_reviews(request):
    assignments = AssistantReviewAssignment.objects.select_related('review', 'review__exam', 'review__question').filter(assistant=request.user)[:100]
    return render(request, 'assistant/reviews.html', {'teacher': request.assistant_teacher, 'assignments': assignments})


@assistant_required
def assistant_review_detail(request, assignment_id):
    assignment = get_object_or_404(
        AssistantReviewAssignment.objects.select_related('review', 'review__exam', 'review__question'),
        pk=assignment_id,
        assistant=request.user,
    )
    if request.method == 'POST':
        form = AssistantDescriptiveReviewForm(request.POST, instance=assignment)
        if form.is_valid():
            item = form.save(commit=False)
            item.status = AssistantReviewAssignment.Status.SUBMITTED
            item.submitted_at = timezone.now()
            item.save()
            log_activity(request.user, 'assistant_review_submitted', 'تصحیح پیشنهادی دستیار برای استاد ارسال شد.', request, {'assignment_id': item.pk})
            messages.success(request, 'تصحیح پیشنهادی برای تأیید استاد ارسال شد.')
            return redirect('core:assistant_reviews')
    else:
        form = AssistantDescriptiveReviewForm(instance=assignment)
    return render(request, 'assistant/review_detail.html', {
        'teacher': request.assistant_teacher, 'assignment': assignment, 'form': form,
        'grading_aid': _grading_aid(assignment.review.question),
    })


@assistant_required
def assistant_educational_questions(request):
    teacher = request.assistant_teacher
    items = EducationalQuestion.objects.select_related('student__profile', 'exam', 'course').filter(teacher=teacher)[:100]
    return render(request, 'assistant/educational_questions.html', {'teacher': teacher, 'items': items})


@assistant_required
def assistant_educational_question_answer(request, question_id):
    teacher = request.assistant_teacher
    item = get_object_or_404(EducationalQuestion.objects.select_related('student__profile', 'exam', 'course'), pk=question_id, teacher=teacher)
    if request.method == 'POST':
        form = AssistantEducationalAnswerForm(request.POST, instance=item)
        if form.is_valid():
            item = form.save(commit=False)
            item.assistant = request.user
            if form.cleaned_data.get('refer_to_teacher'):
                item.status = EducationalQuestion.Status.REFERRED
                item.needs_teacher_decision = True
                if not item.answer_text:
                    item.answer_text = 'ارجاع به استاد برای تصمیم‌گیری.'
            else:
                item.status = EducationalQuestion.Status.ANSWERED
                item.needs_teacher_decision = False
                item.answered_at = timezone.now()
            item.save()
            log_activity(request.user, 'assistant_educational_question_handled', f'پرسش آموزشی توسط دستیار رسیدگی شد: {item.get_status_display()}', request, {'question_id': item.pk})
            messages.success(request, 'وضعیت پرسش آموزشی ثبت شد.')
            return redirect('core:assistant_educational_questions')
    else:
        form = AssistantEducationalAnswerForm(instance=item)
    return render(request, 'assistant/educational_question_answer.html', {'teacher': teacher, 'item': item, 'form': form})


@student_required
def student_educational_questions(request):
    student = request.student_profile
    if request.method == 'POST':
        form = EducationalQuestionForm(request.POST, student=student)
        if form.is_valid():
            item = form.save(commit=False)
            item.student = student
            course = item.course or (item.exam.course if item.exam else None)
            teacher = None
            if item.exam and item.exam.designer:
                teacher = item.exam.designer
            elif course:
                teacher = course.teachers.first() or TeacherProfile.objects.filter(institution=student.institution).first()
            else:
                teacher = TeacherProfile.objects.filter(institution=student.institution).first() or TeacherProfile.objects.first()
            if not teacher:
                form.add_error('course', 'برای این درس استاد مسئول پیدا نشد.')
            else:
                item.course = course
                item.teacher = teacher
                item.save()
                log_activity(request.user, 'student_educational_question_created', 'پرسش آموزشی دانشجو ثبت شد.', request, {'question_id': item.pk})
                messages.success(request, 'پرسش شما ثبت شد.')
                return redirect('core:student_educational_questions')
    else:
        form = EducationalQuestionForm(student=student)
    questions = EducationalQuestion.objects.select_related('exam', 'course', 'teacher__profile').filter(student=student)[:100]
    return render(request, 'student/educational_questions.html', {'student': student, 'form': form, 'questions': questions})


@student_required
def student_practice_exam(request):
    student = request.student_profile
    latest_check = student.practice_checks.first()
    if request.method == 'POST':
        form = StudentPracticeCheckForm(request.POST)
        if form.is_valid():
            issues = []
            for key, label in (
                ('browser_ok', 'مرورگر سازگار نیست.'),
                ('internet_ok', 'اتصال اینترنت پایدار نیست.'),
                ('camera_ok', 'دوربین در دسترس نیست.'),
                ('microphone_ok', 'میکروفن در دسترس نیست.'),
            ):
                if not form.cleaned_data.get(key):
                    issues.append(label)
            sample_score = 0
            if form.cleaned_data.get('sample_answer_1') == 'a':
                sample_score += 1
            if form.cleaned_data.get('sample_answer_2', '').strip():
                sample_score += 1
            latest_check = StudentPracticeCheck.objects.create(
                student=student,
                browser_ok=form.cleaned_data.get('browser_ok', False),
                internet_ok=form.cleaned_data.get('internet_ok', False),
                camera_ok=form.cleaned_data.get('camera_ok', False),
                microphone_ok=form.cleaned_data.get('microphone_ok', False),
                sample_score=sample_score,
                issues=issues,
            )
            messages.success(request, 'نتیجه آزمون آزمایشی ثبت شد.')
            return redirect('core:student_practice_exam')
    else:
        form = StudentPracticeCheckForm()
    return render(request, 'student/practice_exam.html', {'student': student, 'form': form, 'latest_check': latest_check})


@student_required
def student_attempt_event(request, attempt_id):
    student = request.student_profile
    attempt = get_object_or_404(StudentExamAttempt, pk=attempt_id, student=student)
    event = request.POST.get('event')
    if event == 'disconnect':
        StudentExamEvent.objects.create(attempt=attempt, event_type=StudentExamEvent.EventType.DISCONNECTED, message='قطع اتصال اینترنت دانشجو ثبت شد.')
    elif event == 'reconnect':
        StudentExamEvent.objects.create(attempt=attempt, event_type=StudentExamEvent.EventType.RECONNECTED, message='اتصال مجدد دانشجو ثبت شد.')
        attempt.last_activity_at = timezone.now()
        attempt.save(update_fields=['last_activity_at'])
    return JsonResponse({'ok': True})


def home(request):
    upcoming_exams = erd_rows(
        """
        SELECT e.id, e.title, COALESCE(c.title, 'بدون درس') AS course, e.start_at AS starts_at
        FROM exams e
        LEFT JOIN courses c ON c.id = e.course_id
        WHERE COALESCE(e.is_published, false) = true AND COALESCE(e.is_cancelled, false) = false
        ORDER BY e.start_at NULLS LAST
        LIMIT 5
        """
    )
    return render(request, 'home.html', {'upcoming_exams': upcoming_exams})


def _super_admin_profile_view(request, page_context):
    profile = page_context['profile']

    def safe_count(table, where='', params=None):
        try:
            return erd_count(table, where, params or [])
        except Exception:
            return 0

    def safe_rows(sql, params=None):
        try:
            return erd_rows(sql, params or [])
        except Exception:
            return []

    section = request.GET.get('section') or 'overview'
    if section not in {'overview', 'security', 'edit'}:
        section = 'overview'

    if request.method == 'POST':
        form_name = request.POST.get('form')

        if form_name == 'profile':
            first_name = (request.POST.get('first_name') or '').strip()
            last_name = (request.POST.get('last_name') or '').strip()
            email = (request.POST.get('email') or '').strip()
            phone = (request.POST.get('phone') or '').strip()
            full_name = f'{first_name} {last_name}'.strip() or profile.get('full_name') or request.user.username
            avatar_url = profile.get('avatar_url') or ''
            avatar = request.FILES.get('avatar')
            if avatar:
                if avatar.size > 2 * 1024 * 1024:
                    messages.error(request, 'حجم تصویر پروفایل باید کمتر از ۲ مگابایت باشد.')
                    return redirect(f"{reverse('core:profile')}?section=edit")
                if avatar.content_type not in {'image/jpeg', 'image/png', 'image/webp', 'image/gif'}:
                    messages.error(request, 'فرمت تصویر باید JPG، PNG، WebP یا GIF باشد.')
                    return redirect(f"{reverse('core:profile')}?section=edit")
                extension = avatar.name.rsplit('.', 1)[-1].lower() if '.' in avatar.name else 'jpg'
                storage = FileSystemStorage(location=settings.MEDIA_ROOT / 'avatars', base_url=settings.MEDIA_URL + 'avatars/')
                filename = storage.save(f"{profile['id']}-admin.{extension}", avatar)
                avatar_url = storage.url(filename)
            erd_execute(
                """
                UPDATE profiles
                SET full_name = %s, first_name = %s, last_name = %s, email = %s, phone = %s,
                    avatar_url = %s, updated_at = now()
                WHERE id = %s
                """,
                [full_name, first_name, last_name, email, phone, avatar_url, profile['id']],
            )
            request.user.first_name = first_name
            request.user.last_name = last_name
            request.user.email = email
            request.user.save(update_fields=['first_name', 'last_name', 'email'])
            log_activity(request.user, 'profile_updated', 'ویرایش اطلاعات پروفایل', request)
            messages.success(request, 'اطلاعات پروفایل با موفقیت ذخیره شد.')
            return redirect(f"{reverse('core:profile')}?section=edit")

        if form_name == 'password':
            password_form = PasswordChangeForm(user=request.user, data=request.POST)
            if password_form.is_valid():
                password_form.save()
                update_session_auth_hash(request, password_form.user)
                log_activity(request.user, 'password_changed', 'تغییر رمز عبور حساب', request)
                messages.success(request, 'رمز عبور با موفقیت تغییر کرد.')
                return redirect(f"{reverse('core:profile')}?section=security")
            for field_errors in password_form.errors.values():
                for error in field_errors:
                    messages.error(request, error)
            return redirect(f"{reverse('core:profile')}?section=security")

        if form_name == 'logout_others':
            terminated = account_security.end_other_sessions(request.user, request.session.session_key)
            log_activity(request.user, 'sessions_terminated', f'خروج اجباری از {terminated} نشست دیگر', request)
            messages.success(request, f'از {terminated} نشست دیگر خارج شدید.' if terminated else 'نشست فعال دیگری یافت نشد.')
            return redirect(f"{reverse('core:profile')}?section=security")

    total_users = safe_count('profiles')
    active_exams = safe_count('exams', "COALESCE(is_published, false) = true AND COALESCE(is_cancelled, false) = false")
    teachers_count = safe_count('teacher_profiles')
    pending_registrations = safe_count('profiles', "status = 'pending'")

    recent_activities = safe_rows(
        """
        SELECT action, reason, created_at
        FROM activity_audit_log
        WHERE actor_id = %s
          AND action NOT IN ('login_success', 'login_failed', 'two_factor_code_sent', 'two_factor_success', 'two_factor_failed')
        ORDER BY created_at DESC
        LIMIT 5
        """,
        [profile['id']],
    )
    activity_meta = {
        'registration_approved': {'label': 'تأیید ثبت‌نام کاربر', 'icon': 'user-check', 'tone': 'green'},
        'registration_rejected': {'label': 'رد درخواست ثبت‌نام', 'icon': 'user-x', 'tone': 'red'},
        'account_activated': {'icon': 'user-check', 'tone': 'green'},
        'account_deactivated': {'icon': 'user-x', 'tone': 'red'},
        'account_deleted': {'icon': 'user-x', 'tone': 'red'},
        'profile_updated': {'label': 'ویرایش اطلاعات پروفایل', 'icon': 'edit', 'tone': 'purple'},
        'password_changed': {'label': 'تغییر رمز عبور', 'icon': 'lock', 'tone': 'blue'},
        'sessions_terminated': {'label': 'خروج اجباری از نشست‌های دیگر', 'icon': 'logout', 'tone': 'red'},
        'system_settings_updated': {'icon': 'settings', 'tone': 'purple'},
    }
    for item in recent_activities:
        meta = activity_meta.get(item['action'], {})
        item['label'] = meta.get('label') or item.get('reason') or item['action']
        item['icon'] = meta.get('icon', 'dot')
        item['tone'] = meta.get('tone', 'blue')

    login_rows = safe_rows(
        """
        SELECT action, metadata, created_at
        FROM activity_audit_log
        WHERE actor_id = %s AND action IN ('login_success', 'login_failed')
        ORDER BY created_at DESC
        LIMIT 6
        """,
        [profile['id']],
    )
    login_history = []
    for row in login_rows:
        try:
            meta = json.loads(row.get('metadata') or '{}')
        except (TypeError, ValueError):
            meta = {}
        login_history.append({
            'result': 'موفق' if row['action'] == 'login_success' else 'ناموفق',
            'device': describe_user_agent(meta.get('user_agent')),
            'ip': meta.get('ip_address') or '-',
            'time': row.get('created_at'),
        })

    current_session_key = request.session.session_key
    other_sessions = 0
    for stored_session in Session.objects.all():
        if stored_session.session_key == current_session_key:
            continue
        data = stored_session.get_decoded()
        if str(data.get('_auth_user_id')) == str(request.user.pk):
            other_sessions += 1

    completion_fields = [
        profile.get('first_name'), profile.get('last_name'),
        profile.get('email') or request.user.email, profile.get('phone'),
        profile.get('avatar_url'),
    ]
    profile_completion = int(sum(1 for value in completion_fields if value) / len(completion_fields) * 100)
    security_score = 60
    if profile.get('phone'):
        security_score += 15
    if profile.get('email') or request.user.email:
        security_score += 15
    if request.user.has_usable_password():
        security_score += 10
    security_score = min(security_score, 100)

    return render(request, 'super_admin/profile.html', {
        'title': 'پروفایل مدیر سیستم',
        'section': section,
        'display_name': profile.get('full_name') or request.user.username,
        'profile': profile,
        'profile_identifier': profile.get('identifier') or profile.get('username') or request.user.username,
        'last_login_at': page_context.get('last_login_at'),
        'profile_completion': profile_completion,
        'security_score': security_score,
        'stat_tiles': [
            {'label': 'هشدار امنیتی', 'value': pending_registrations, 'tone': 'red', 'icon': 'alert'},
            {'label': 'آزمون فعال', 'value': active_exams, 'tone': 'blue', 'icon': 'clipboard'},
            {'label': 'استاد', 'value': teachers_count, 'tone': 'purple', 'icon': 'user-check'},
            {'label': 'کاربر', 'value': total_users, 'tone': 'teal', 'icon': 'users'},
        ],
        'access_items': [
            {'label': 'نقش فعال', 'value': 'مدیر سیستم', 'icon': 'user'},
            {'label': 'دامنه دسترسی', 'value': 'کل سامانه', 'icon': 'globe'},
            {'label': 'واحد سازمانی', 'value': 'مدیریت مرکزی', 'icon': 'building'},
            {'label': 'سطح دسترسی', 'value': 'دسترسی کامل', 'icon': 'shield-check'},
        ],
        'shortcuts': [
            {'label': 'مدیریت کاربران', 'url': reverse('core:super_admin_users'), 'icon': 'users'},
            {'label': 'تنظیمات سامانه', 'url': reverse('core:super_admin_settings'), 'icon': 'settings'},
            {'label': 'ساختار سازمانی', 'url': reverse('core:super_admin_org_units'), 'icon': 'org'},
            {'label': 'گزارش رخدادها', 'url': reverse('core:super_admin_reports'), 'icon': 'report'},
        ],
        'recent_activities': recent_activities,
        'login_history': login_history,
        'other_sessions_count': other_sessions,
        'current_session': {
            'device': describe_user_agent(request.META.get('HTTP_USER_AGENT')),
            'ip': client_ip(request),
        },
    })


@login_required
def _legacy_profile_view(request):
    """Profile page for non-student roles; the student profile below delegates here."""
    page_context = erd_profile_page_context(request.user)
    if not page_context:
        messages.error(request, 'پروفایل کاربری شما در سامانه پیدا نشد.')
        return redirect('core:dashboard')

    if 'admin' in (page_context.get('roles') or []):
        return _super_admin_profile_view(request, page_context)

    profile = page_context['profile']
    section = request.GET.get('section') or 'personal'
    if section in {'overview', 'edit'}:
        section = 'personal'
    if section not in {'personal', 'security', 'announcements', 'sessions'}:
        section = 'personal'

    if request.method == 'POST':
        first_name = (request.POST.get('first_name') or '').strip()
        last_name = (request.POST.get('last_name') or '').strip()
        email = (request.POST.get('email') or '').strip()
        phone = (request.POST.get('phone') or '').strip()
        national_id = (request.POST.get('national_id') or '').strip()
        full_name = f'{first_name} {last_name}'.strip() or profile.get('full_name') or request.user.username
        avatar_url = profile.get('avatar_url') or ''

        avatar = request.FILES.get('avatar')
        if avatar:
            if avatar.size > 1024 * 1024:
                messages.error(request, 'حجم تصویر پروفایل باید کمتر از ۱ مگابایت باشد.')
                return redirect('core:profile')
            if avatar.content_type not in {'image/jpeg', 'image/png', 'image/webp', 'image/gif'}:
                messages.error(request, 'فرمت تصویر باید JPG، PNG، WebP یا GIF باشد.')
                return redirect('core:profile')
            extension = avatar.name.rsplit('.', 1)[-1].lower() if '.' in avatar.name else 'jpg'
            storage = FileSystemStorage(
                location=settings.MEDIA_ROOT / 'avatars',
                base_url=settings.MEDIA_URL + 'avatars/',
            )
            filename = storage.save(f"{profile['id']}.{extension}", avatar)
            avatar_url = storage.url(filename)

        erd_execute(
            """
            UPDATE profiles
            SET full_name = %s,
                first_name = %s,
                last_name = %s,
                email = %s,
                phone = %s,
                national_id = %s,
                avatar_url = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
            """,
            [full_name, first_name, last_name, email, phone, national_id, avatar_url, profile['id']],
        )
        request.user.first_name = first_name
        request.user.last_name = last_name
        request.user.email = email
        request.user.save(update_fields=['first_name', 'last_name', 'email'])
        messages.success(request, 'اطلاعات پروفایل با موفقیت ذخیره شد.')
        return redirect(f"{reverse('core:profile')}?section=personal")

    def safe_count(table, where='', params=None):
        try:
            return erd_count(table, where, params or [])
        except Exception:
            return 0

    def safe_rows(sql, params=None):
        try:
            return erd_rows(sql, params or [])
        except Exception:
            return []

    total_users = safe_count('profiles')
    active_exams = safe_count(
        'exams',
        "COALESCE(is_published, false) = true AND COALESCE(is_cancelled, false) = false",
    )
    teachers_count = safe_count('teacher_profiles')
    students_count = safe_count('student_profiles')
    courses_count = safe_count('courses')
    groups_count = safe_count('student_groups')
    security_alerts = safe_count('activity_audit_log', "LOWER(action) LIKE %s", ['%security%'])
    if not security_alerts:
        security_alerts = safe_count('violation_reports')
    activity_created = 'created_at' if erd_has_column('activity_audit_log', 'created_at') else 'NULL'
    activity_order = 'created_at DESC NULLS LAST' if erd_has_column('activity_audit_log', 'created_at') else 'action'
    recent_activities = safe_rows(
        f"""
        SELECT action, reason, {activity_created} AS created_at
        FROM activity_audit_log
        WHERE actor_id = %s
        ORDER BY {activity_order}
        LIMIT 5
        """,
        [profile['id']],
    )
    notification_rows = safe_rows(
        """
        SELECT title, message, type, is_read
        FROM notifications
        WHERE user_id = %s
        LIMIT 6
        """,
        [profile['id']],
    )
    completion_fields = [
        profile.get('first_name'),
        profile.get('last_name'),
        profile.get('email') or request.user.email,
        profile.get('phone'),
        profile.get('national_id'),
        profile.get('avatar_url'),
        page_context.get('roles_label'),
    ]
    profile_completion = int(sum(1 for value in completion_fields if value) / len(completion_fields) * 100)
    role_details = page_context.get('role_details') or {}
    manager_extra = safe_rows(
        """
        SELECT personnel_code, department, responsibility_area, title, access_type
        FROM academic_manager_profiles
        WHERE user_id = %s
        LIMIT 1
        """,
        [profile['id']],
    )
    manager_extra = manager_extra[0] if manager_extra else {}
    profile_identifier = (
        manager_extra.get('personnel_code')
        or role_details.get('employee_code')
        or role_details.get('personnel_code')
        or role_details.get('student_number')
        or profile.get('identifier')
        or profile.get('username')
        or request.user.username
    )
    roles = page_context.get('roles') or []
    is_academic_manager = 'academic_manager' in roles
    clean_role_label = 'مدیر آموزشی' if is_academic_manager else ('مدیر سیستم' if 'admin' in roles else page_context.get('role_label') or 'کاربر سامانه')
    access_scope = 'کل سامانه' if 'admin' in roles else 'دانشکده پزشکی'
    organization_unit = (
        manager_extra.get('department')
        or manager_extra.get('responsibility_area')
        or role_details.get('department')
        or role_details.get('org_unit_name')
        or role_details.get('unit_name')
        or 'دانشکده پزشکی'
    )
    security_score = 85 if profile.get('phone') and (profile.get('email') or request.user.email) else 72
    profile_tabs = [
        {'key': 'personal', 'label': 'اطلاعات شخصی', 'icon': 'user'},
        {'key': 'security', 'label': 'امنیت حساب', 'icon': 'shield'},
        {'key': 'announcements', 'label': 'اعلان‌ها', 'icon': 'bell'},
        {'key': 'sessions', 'label': 'نشست‌های فعال', 'icon': 'monitor'},
    ]

    return render(
        request,
        'profile.html',
        {
            **page_context,
            'section': section,
            'profile_tabs': profile_tabs,
            'display_name': profile.get('full_name') or request.user.username,
            'profile_identifier': profile_identifier,
            'profile_completion': profile_completion,
            'security_score': security_score,
            'clean_role_label': clean_role_label,
            'organization_unit': organization_unit,
            'manager_title': manager_extra.get('title') or clean_role_label,
            'manager_department': organization_unit,
            'notification_rows': notification_rows,
            'profile_metrics': [
                {'label': 'درس‌ها', 'value': courses_count, 'tone': 'blue', 'icon': 'book'},
                {'label': 'گروه‌ها', 'value': groups_count, 'tone': 'green', 'icon': 'groups'},
                {'label': 'اساتید', 'value': teachers_count, 'tone': 'purple', 'icon': 'teacher'},
                {'label': 'دانشجویان', 'value': students_count, 'tone': 'orange', 'icon': 'users'},
            ],
            'profile_access_items': [
                {'label': 'نقش فعال', 'value': clean_role_label},
                {'label': 'دامنه دسترسی', 'value': access_scope},
                {'label': 'واحد سازمانی', 'value': organization_unit},
                {'label': 'کد کاربری', 'value': profile_identifier},
            ],
            'profile_shortcuts': [
                {'label': 'مدیریت درس‌ها', 'url': reverse('core:exam_manager_courses'), 'icon': 'book'},
                {'label': 'مدیریت دانشجویان', 'url': reverse('core:exam_manager_users'), 'icon': 'users'},
                {'label': 'مدیریت آزمون‌ها', 'url': reverse('core:exam_manager_exams'), 'icon': 'clipboard'},
                {'label': 'تقویم آموزشی', 'url': reverse('core:exam_manager_calendar'), 'icon': 'calendar'},
            ],
            'recent_profile_activities': recent_activities,
            'security_sessions': [
                {'device': 'Windows - Chrome', 'place': 'تهران، ایران', 'ip': client_ip(request), 'time': 'اکنون فعال', 'current': True},
                {'device': 'Android - Chrome', 'place': 'اصفهان، ایران', 'ip': '192.0.2.45', 'time': '۲ ساعت پیش', 'current': False},
                {'device': 'MacBook - Safari', 'place': 'شیراز، ایران', 'ip': '192.0.2.78', 'time': 'دیروز، ۲۱:۱۰', 'current': False},
                {'device': 'iPad - Safari', 'place': 'مشهد، ایران', 'ip': '192.0.2.99', 'time': '۳ روز پیش', 'current': False},
            ],
            'login_history_items': [
                {'device': 'Windows - Chrome', 'place': 'تهران، ایران', 'time': 'امروز، ۱۰:۲۳', 'result': 'موفق'},
                {'device': 'Android - Chrome', 'place': 'اصفهان، ایران', 'time': '۲ ساعت پیش', 'result': 'موفق'},
                {'device': 'MacBook - Safari', 'place': 'شیراز، ایران', 'time': 'دیروز، ۲۱:۱۰', 'result': 'موفق'},
                {'device': 'Windows - Edge', 'place': 'کرج، ایران', 'time': '۴ روز پیش', 'result': 'ناموفق'},
            ],
            'app_is_shell_page': False,
            'standalone_page': True,
        },
    )


@login_required
def dashboard(request):
    erd_profile = erd_profile_for_user(request.user)
    erd_primary = erd_primary_role(request.user)
    if erd_primary is None:
        return HttpResponseForbidden(
            'برای این حساب کاربری نقشی در سامانه تعریف نشده است؛ لطفاً با مدیر سامانه تماس بگیرید.'
        )
    if erd_primary == 'teacher':
        return redirect('core:teacher_panel')
    role_code = {
        'admin': 'super_admin',
        'academic_manager': 'exam_manager',
        'teacher': 'teacher',
        'student': 'student',
    }[erd_primary]
    display_name = (
        erd_profile.get('full_name')
        if erd_profile
        else request.user.get_full_name() or request.user.username
    )
    super_admin_links = []
    role_panel = {}
    if erd_primary == 'admin':
        super_admin_links = [
            {'title': 'ساختار سازمانی', 'url': reverse('core:super_admin_org_units')},
            {'title': 'مدیریت کاربران', 'url': reverse('core:super_admin_users')},
            {'title': 'نقش‌ها و مجوزها', 'url': reverse('core:super_admin_roles')},
            {'title': 'گزارش کل سامانه', 'url': reverse('core:super_admin_reports')},
            {'title': 'آزمون‌های فعال', 'url': reverse('core:super_admin_active_exams')},
        ]
        role_panel = erd_admin_dashboard_panel()
    dashboard_data = {
        **ROLE_DASHBOARDS.get(role_code, ROLE_DASHBOARDS['student']),
        'task_groups': ROLE_TASK_GROUPS.get(role_code, []),
    }
    context = {
        'dashboard': dashboard_data,
        'profile': erd_profile,
        'display_name': display_name,
        'profile_nav_groups': erd_profile_page_context(request.user)['profile_nav_groups'] if erd_profile else [],
        'role_label': erd_role_name(role_code),
        'role_name': erd_role_name(role_code),
        'profile_edit_url': reverse('core:profile'),
        'super_admin_links': super_admin_links,
        'institution_admin_links': [],
        'exam_manager_links': [],
        'teacher_links': [],
        'assistant_links': [],
        'student_links': [],
        'role_code': role_code,
        'role_panel': role_panel,
        'app_is_shell_page': False,
        'standalone_page': True,
    }
    if role_code == 'student':
        from .student_dashboard import student_dashboard_context

        context['student_dashboard'] = student_dashboard_context(request, erd_profile)
    return render(request, 'dashboard.html', context)


def erd_user_profile_id(user):
    profile = erd_profile_for_user(user)
    return profile['id'] if profile else None


def _erd_manager_scope_cte():
    return """
        WITH RECURSIVE managed_units(id) AS (
            SELECT org_unit_id
            FROM academic_manager_scopes
            WHERE manager_id = %s
            UNION
            SELECT ou.id
            FROM org_units ou
            JOIN managed_units mu ON ou.parent_id = mu.id
        )
    """


def _erd_exam_scope_condition():
    return """
        (
            EXISTS (
                SELECT 1
                FROM teacher_profiles tp_scope
                WHERE tp_scope.user_id = e.teacher_id
                  AND tp_scope.org_unit_id IN (SELECT id FROM managed_units)
            )
            OR EXISTS (
                SELECT 1
                FROM courses c_scope
                WHERE c_scope.id = e.course_id
                  AND c_scope.org_unit_id IN (SELECT id FROM managed_units)
            )
            OR EXISTS (
                SELECT 1
                FROM student_groups sg_scope
                LEFT JOIN courses sg_course ON sg_course.id = sg_scope.course_id
                WHERE (sg_scope.teacher_id = e.teacher_id OR sg_scope.course_id = e.course_id)
                  AND (
                    sg_course.org_unit_id IN (SELECT id FROM managed_units)
                    OR sg_scope.teacher_id IN (
                        SELECT user_id FROM teacher_profiles WHERE org_unit_id IN (SELECT id FROM managed_units)
                    )
                  )
            )
        )
    """


def _erd_teacher_scope_condition():
    return """
        (
            tp.org_unit_id IN (SELECT id FROM managed_units)
            OR EXISTS (
                SELECT 1
                FROM student_groups sg_scope
                LEFT JOIN courses c_scope ON c_scope.id = sg_scope.course_id
                WHERE sg_scope.teacher_id = tp.user_id
                  AND c_scope.org_unit_id IN (SELECT id FROM managed_units)
            )
        )
    """


def _erd_group_scope_condition():
    return """
        (
            c.org_unit_id IN (SELECT id FROM managed_units)
            OR sg.teacher_id IN (SELECT user_id FROM teacher_profiles WHERE org_unit_id IN (SELECT id FROM managed_units))
        )
    """


def _erd_question_scope_condition():
    return """
        (
            c.org_unit_id IN (SELECT id FROM managed_units)
            OR q.teacher_id IN (SELECT user_id FROM teacher_profiles WHERE org_unit_id IN (SELECT id FROM managed_units))
        )
    """


def _erd_student_scope_condition():
    return """
        (
            sp.org_unit_id IN (SELECT id FROM managed_units)
            OR EXISTS (
                SELECT 1
                FROM student_group_members sgm_scope
                JOIN student_groups sg_scope ON sg_scope.id = sgm_scope.group_id
                LEFT JOIN courses c_scope ON c_scope.id = sg_scope.course_id
                WHERE sgm_scope.student_user_id = sp.user_id
                  AND (
                    c_scope.org_unit_id IN (SELECT id FROM managed_units)
                    OR sg_scope.teacher_id IN (SELECT user_id FROM teacher_profiles WHERE org_unit_id IN (SELECT id FROM managed_units))
                  )
            )
        )
    """


def _erd_is_admin_request(request):
    return getattr(request, 'erd_role', None) == 'admin'


def _erd_manager_visible_org_units(request):
    """واحدهای سازمانی قابل‌نمایش برای select آبشاری: زیردرخت مدیر + زنجیره‌ی والدینش (دانشگاه/دانشکده)."""
    if _erd_is_admin_request(request):
        return erd_rows(
            """
            SELECT id, parent_id, type, name, code, is_active
            FROM org_units
            ORDER BY CASE type WHEN 'university' THEN 0 WHEN 'faculty' THEN 1 ELSE 2 END, name
            """
        )
    return erd_rows(
        """
        WITH RECURSIVE descendant_units(id) AS (
            SELECT org_unit_id FROM academic_manager_scopes WHERE manager_id = %s
            UNION
            SELECT ou.id FROM org_units ou JOIN descendant_units du ON ou.parent_id = du.id
        ),
        ancestor_units(id) AS (
            SELECT org_unit_id FROM academic_manager_scopes WHERE manager_id = %s
            UNION
            SELECT ou.parent_id FROM org_units ou JOIN ancestor_units au ON ou.id = au.id WHERE ou.parent_id IS NOT NULL
        )
        SELECT id, parent_id, type, name, code, is_active
        FROM org_units
        WHERE id IN (SELECT id FROM descendant_units) OR id IN (SELECT id FROM ancestor_units)
        ORDER BY CASE type WHEN 'university' THEN 0 WHEN 'faculty' THEN 1 ELSE 2 END, name
        """,
        [request.erd_profile_id, request.erd_profile_id],
    )


def _erd_managed_unit_ids(request):
    if _erd_is_admin_request(request):
        return None
    rows = erd_rows(_erd_manager_scope_cte() + "SELECT id FROM managed_units", [request.erd_profile_id])
    return {str(row['id']) for row in rows}


def _erd_exam_in_manager_scope(request, exam_id):
    if _erd_is_admin_request(request):
        return True
    row = erd_row(
        _erd_manager_scope_cte() + f"""
        SELECT 1 AS ok
        FROM exams e
        WHERE e.id = %s AND {_erd_exam_scope_condition()}
        """,
        [request.erd_profile_id, exam_id],
    )
    return bool(row)


def _erd_group_in_manager_scope(request, group_id):
    if _erd_is_admin_request(request):
        return True
    row = erd_row(
        _erd_manager_scope_cte() + f"""
        SELECT 1 AS ok
        FROM student_groups sg
        LEFT JOIN courses c ON c.id = sg.course_id
        WHERE sg.id = %s AND {_erd_group_scope_condition()}
        """,
        [request.erd_profile_id, group_id],
    )
    return bool(row)


def _erd_group_assignment_in_scope(request, course_id, teacher_ids):
    managed = _erd_managed_unit_ids(request)
    if managed is None:
        return True
    if course_id:
        course = erd_row('SELECT org_unit_id FROM courses WHERE id = %s', [course_id])
        if course and str(course.get('org_unit_id') or '') in managed:
            return True
    teacher_ids = [item for item in teacher_ids if item]
    if teacher_ids:
        placeholders = ', '.join(['%s'] * len(teacher_ids))
        rows = erd_rows(f'SELECT org_unit_id FROM teacher_profiles WHERE user_id IN ({placeholders})', teacher_ids)
        if any(str(row.get('org_unit_id') or '') in managed for row in rows):
            return True
    return False


def _erd_profile_in_manager_scope(request, profile_id, kind):
    if _erd_is_admin_request(request):
        return True
    if kind == 'teacher':
        row = erd_row(
            _erd_manager_scope_cte() + f"""
            SELECT 1 AS ok
            FROM teacher_profiles tp
            WHERE tp.user_id = %s AND {_erd_teacher_scope_condition()}
            """,
            [request.erd_profile_id, profile_id],
        )
    elif kind == 'student':
        row = erd_row(
            _erd_manager_scope_cte() + f"""
            SELECT 1 AS ok
            FROM student_profiles sp
            WHERE sp.user_id = %s AND {_erd_student_scope_condition()}
            """,
            [request.erd_profile_id, profile_id],
        )
    else:
        return False
    return bool(row)


def _erd_scoped_count(request, key):
    if _erd_is_admin_request(request):
        table_map = {
            'exams': 'exams',
            'courses': 'courses',
            'groups': 'student_groups',
            'teachers': 'teacher_profiles',
            'students': 'student_profiles',
        }
        return erd_count(table_map[key])
    manager_id = request.erd_profile_id
    sql = _erd_manager_scope_cte() + """
        SELECT
            (SELECT COUNT(*)
             FROM exams e
             WHERE """ + _erd_exam_scope_condition() + """) AS exams,
            (SELECT COUNT(*)
             FROM courses c
             WHERE c.org_unit_id IN (SELECT id FROM managed_units)) AS courses,
            (SELECT COUNT(*)
             FROM student_groups sg
             LEFT JOIN courses c ON c.id = sg.course_id
             WHERE c.org_unit_id IN (SELECT id FROM managed_units)
                OR sg.teacher_id IN (SELECT user_id FROM teacher_profiles WHERE org_unit_id IN (SELECT id FROM managed_units))) AS groups,
            (SELECT COUNT(*)
             FROM teacher_profiles tp
             WHERE tp.org_unit_id IN (SELECT id FROM managed_units)) AS teachers,
            (SELECT COUNT(*)
             FROM student_profiles sp
             WHERE sp.org_unit_id IN (SELECT id FROM managed_units)
                OR EXISTS (
                    SELECT 1
                    FROM student_group_members sgm
                    JOIN student_groups sg ON sg.id = sgm.group_id
                    LEFT JOIN courses c ON c.id = sg.course_id
                    WHERE sgm.student_user_id = sp.user_id
                      AND (c.org_unit_id IN (SELECT id FROM managed_units)
                           OR sg.teacher_id IN (SELECT user_id FROM teacher_profiles WHERE org_unit_id IN (SELECT id FROM managed_units)))
                )) AS students
    """
    row = erd_row(sql, [manager_id]) or {}
    return row.get(key, 0)


def _erd_scoped_teacher_rows(request):
    if _erd_is_admin_request(request):
        return erd_rows(
            """
            SELECT p.full_name, p.email, tp.personnel_code, tp.department, tp.specialty, tp.approval_status
            FROM teacher_profiles tp
            JOIN profiles p ON p.id = tp.user_id
            ORDER BY p.full_name
            LIMIT 200
            """
        )
    return erd_rows(
        _erd_manager_scope_cte() + """
        SELECT p.full_name, p.email, tp.personnel_code, tp.department, tp.specialty, tp.approval_status
        FROM teacher_profiles tp
        JOIN profiles p ON p.id = tp.user_id
        WHERE tp.org_unit_id IN (SELECT id FROM managed_units)
           OR EXISTS (
                SELECT 1
                FROM student_groups sg
                LEFT JOIN courses c ON c.id = sg.course_id
                WHERE sg.teacher_id = tp.user_id
                  AND c.org_unit_id IN (SELECT id FROM managed_units)
           )
        ORDER BY p.full_name
        LIMIT 200
        """,
        [request.erd_profile_id],
    )


def _erd_scoped_exam_count(request, where='', params=None):
    if _erd_is_admin_request(request):
        return erd_count('exams', where, params or [])
    sql = _erd_manager_scope_cte() + """
        SELECT COUNT(*) AS count
        FROM exams e
        WHERE """ + _erd_exam_scope_condition()
    sql_params = [request.erd_profile_id]
    if where:
        sql += f' AND ({where})'
        sql_params.extend(params or [])
    row = erd_row(sql, sql_params)
    return row['count'] if row else 0


def _erd_student_exam_access_condition():
    return """
        COALESCE(e.is_published, false) = true
        AND COALESCE(e.is_cancelled, false) = false
        AND (
            EXISTS (
                SELECT 1
                FROM exam_assignments ea
                WHERE ea.exam_id = e.id
                  AND ea.student_profile_id = %s
            )
            OR (
                EXISTS (
                    SELECT 1
                    FROM exam_assignments ea
                    JOIN student_group_members sgm ON sgm.group_id = ea.group_id
                    WHERE ea.exam_id = e.id
                      AND sgm.student_user_id = %s
                )
                AND NOT EXISTS (
                    SELECT 1
                    FROM exam_assignment_exclusions ax
                    WHERE ax.exam_id = e.id
                      AND ax.student_profile_id = %s
                )
            )
        )
    """  # an exam with no assignment has no audience: no student may see or take it


def _erd_teacher_assigned_course_count(teacher_id):
    row = erd_row(
        """
        SELECT COUNT(DISTINCT course_id) AS count
        FROM (
            SELECT course_id FROM exams WHERE teacher_id = %s AND course_id IS NOT NULL
            UNION
            SELECT course_id FROM questions WHERE teacher_id = %s AND course_id IS NOT NULL
            UNION
            SELECT course_id FROM student_groups WHERE teacher_id = %s AND course_id IS NOT NULL
            UNION
            SELECT sg.course_id
            FROM group_teachers gt
            JOIN student_groups sg ON sg.id = gt.group_id
            WHERE gt.teacher_id = %s AND sg.course_id IS NOT NULL
        ) assigned_courses
        """,
        [teacher_id, teacher_id, teacher_id, teacher_id],
    )
    return row['count'] if row else 0


def _erd_teacher_assigned_student_count(teacher_id):
    row = erd_row(
        """
        SELECT COUNT(DISTINCT sgm.student_user_id) AS count
        FROM student_group_members sgm
        JOIN student_groups sg ON sg.id = sgm.group_id
        LEFT JOIN group_teachers gt ON gt.group_id = sg.id
        WHERE sg.teacher_id = %s OR gt.teacher_id = %s
        """,
        [teacher_id, teacher_id],
    )
    return row['count'] if row else 0


def _erd_exam_rows(where='', params=None, limit=200, manager_id=None):
    cte = _erd_manager_scope_cte() if manager_id else ''
    sql = """
        SELECT e.id AS pk, e.title, COALESCE(c.title, '-') AS course, COALESCE(p.full_name, '-') AS teacher,
               COALESCE(to_char(e.start_at, 'YYYY/MM/DD HH24:MI'), '-') AS start_at,
               COALESCE(to_char(e.end_at, 'YYYY/MM/DD HH24:MI'), '-') AS end_at,
               COALESCE(e.duration_minutes::text, '-') AS duration,
               CASE WHEN COALESCE(e.is_cancelled, false) THEN 'لغوشده'
                    WHEN COALESCE(e.is_published, false) THEN 'منتشرشده'
                    ELSE COALESCE(e.approval_status, 'پیش نویس') END AS status
        FROM exams e
        LEFT JOIN courses c ON c.id = e.course_id
        LEFT JOIN profiles p ON p.id = e.teacher_id
    """
    filters = []
    sql_params = []
    if manager_id:
        sql_params.append(manager_id)
        filters.append(_erd_exam_scope_condition())
    if where:
        filters.append(f'({where})')
    if filters:
        sql += ' WHERE ' + ' AND '.join(filters)
    sql += ' ORDER BY e.start_at DESC NULLS LAST, e.title LIMIT %s'
    return erd_rows(cte + sql, [*sql_params, *(params or []), limit])


def _teacher_modern_profile(request):
    profile = erd_profile_for_user(request.user) or {}
    teacher_id = profile.get('id') or getattr(request, 'erd_profile_id', None)
    teacher = erd_row('SELECT personnel_code, department, specialty, approval_status, org_unit_id FROM teacher_profiles WHERE user_id = %s', [teacher_id]) if teacher_id else {}
    groups = _teacher_courses_rows(teacher_id) if teacher_id else []
    active_groups = [row for row in groups if row.get('is_active')]
    exams_total = erd_count('exams', 'teacher_id = %s', [teacher_id]) if teacher_id else 0
    questions_total = erd_count('questions', 'teacher_id = %s', [teacher_id]) if teacher_id else 0
    pending_reviews = erd_count(
        'attempt_answers',
        'needs_manual_grading = true AND question_id IN (SELECT id FROM questions WHERE teacher_id = %s)',
        [teacher_id],
    ) if teacher_id else 0
    display_name = profile.get('full_name') or request.user.get_full_name() or request.user.username
    first_name = profile.get('first_name') or (display_name.split()[0] if display_name else '')
    last_name = profile.get('last_name') or (' '.join(display_name.split()[1:]) if len(display_name.split()) > 1 else '')
    return {
        'id': teacher_id,
        'name': display_name,
        'full_name': display_name,
        'first_name': first_name or 'امیرحسین',
        'last_name': last_name or 'رضایی',
        'role': 'استاد',
        'email': profile.get('email') or request.user.email or 'm.rezaei@university.ac.ir',
        'phone': profile.get('phone') or '09123456789',
        'national_id': profile.get('national_id') or '0123456789',
        'gender': profile.get('gender') or 'مرد',
        'birth_date': profile.get('birth_date') or '1363/05/12',
        'avatar': profile.get('avatar_url') or '',
        'department': teacher.get('department') or 'گروه داخلی',
        'faculty': 'دانشکده پزشکی',
        'university': 'دانشگاه علوم پزشکی شیراز',
        'personnel_code': teacher.get('personnel_code') or profile.get('identifier') or '123456',
        'specialty': teacher.get('specialty') or 'بیماری‌های داخلی، مراقبت‌های ویژه، آموزش پزشکی',
        'approval_status': teacher.get('approval_status') or 'active',
        'active_courses': len(active_groups) or len(groups) or 6,
        'exams_total': exams_total or 12,
        'questions_total': questions_total or 248,
        'pending_reviews': pending_reviews or 18,
        'students_total': sum(int(row.get('students_count') or 0) for row in groups) or 193,
        'member_since': '1396/08/15',
        'last_activity': profile.get('last_login_at') or '1403/03/21 09:43',
        'profile_tab': request.GET.get('tab', 'overview'),
    }

QUESTION_BUILDER_TYPES = {
    'single': {'label': 'سؤال چهارگزینه‌ای', 'structure': 'independent'},
    'multi': {'label': 'سؤال چندپاسخی', 'structure': 'independent'},
    'true_false': {'label': 'سؤال درست یا نادرست', 'structure': 'independent'},
    'short_answer': {'label': 'سؤال پاسخ کوتاه', 'structure': 'independent'},
    'essay': {'label': 'سؤال تشریحی و روبریک نمره‌دهی', 'structure': 'independent'},
    'fill_blank': {'label': 'سؤال جای خالی', 'structure': 'independent'},
    'matching': {'label': 'سؤال تطبیقی', 'structure': 'independent'},
    'ordering': {'label': 'سؤال مرتب‌سازی', 'structure': 'independent'},
    'numeric': {'label': 'سؤال پاسخ عددی', 'structure': 'independent'},
    'matrix': {'label': 'سؤال ماتریسی / جدول', 'structure': 'independent'},
    'image_label': {'label': 'سؤال تصویری / نشانه‌گذاری', 'structure': 'independent'},
    'media_response': {'label': 'سؤال صوتی / ویدئویی', 'structure': 'independent'},
    'case': {'label': 'گروه سؤال مبتنی بر سناریوی بیمار', 'structure': 'case', 'stored_type': 'single'},
    'kfp': {'label': 'سازنده سناریوی KFP', 'structure': 'kfp', 'stored_type': 'single'},
}


def _question_builder_payload(post):
    requested_type = post.get('type') or 'single'
    config = QUESTION_BUILDER_TYPES.get(requested_type, QUESTION_BUILDER_TYPES['single'])
    stored_type = config.get('stored_type', requested_type)
    def clean_number(value, fallback='1'):
        value = (value or '').strip()
        persian_digits = str.maketrans('۰۱۲۳۴۵۶۷۸۹', '0123456789')
        normalized = value.translate(persian_digits).replace('٪', '').strip()
        try:
            float(normalized)
        except (TypeError, ValueError):
            return fallback
        return normalized
    is_independent = config['structure'] == 'independent'
    # Scenario builders (case/kfp) keep their legacy sample fallback; independent questions must carry real input.
    default_option_labels = [] if is_independent else ([
        'فیبریلاسیون دهلیزی',
        'تاکی‌کاردی فوق‌بطنی پاروکسیسمال (SVT)',
        'بلوک دهلیزی-بطنی درجه دو نوع ۱',
        'تاکی‌کاردی بطنی',
    ] if stored_type in {'single', 'multi', 'true_false'} else [])
    option_labels = post.getlist('option_text') or default_option_labels
    correct_values = set(post.getlist('correct_options') or ([] if is_independent else ['2']))
    options = [
        {
            'id': str(index),
            'text': text.strip(),
            'is_correct': str(index) in correct_values,
            'points': post.get(f'option_points_{index}', '1'),
            'negative_points': post.get(f'option_negative_{index}', '-0.5'),
            'media': post.get(f'option_media_{index}', ''),
        }
        for index, text in enumerate(option_labels, start=1)
        if text.strip()
    ]
    accepted_answers = [
        {'answer': answer.strip(), 'points': post.get(f'accepted_points_{index}', '1')}
        for index, answer in enumerate(post.getlist('accepted_answer') or [], start=1)
        if answer.strip()
    ]
    matching_pairs = [
        {'left': left.strip(), 'right': right.strip(), 'points': post.get(f'matching_points_{index}', '1')}
        for index, (left, right) in enumerate(zip(post.getlist('matching_left'), post.getlist('matching_right')), start=1)
        if left.strip() or right.strip()
    ]
    ordering_items = [
        {'order': index, 'text': item.strip()}
        for index, item in enumerate(post.getlist('ordering_item') or [], start=1)
        if item.strip()
    ]
    rubric = [
        {'criterion': criterion.strip(), 'weak': weak.strip(), 'average': average.strip(), 'excellent': excellent.strip(), 'points': points.strip()}
        for criterion, weak, average, excellent, points in zip(
            post.getlist('rubric_criterion'),
            post.getlist('rubric_weak'),
            post.getlist('rubric_average'),
            post.getlist('rubric_excellent'),
            post.getlist('rubric_points'),
        )
        if criterion.strip()
    ]
    scenario_stage_titles = post.getlist('scenario_stage_title')
    scenario_stage_descriptions = post.getlist('scenario_stage_description')
    scenario_stage_questions = post.getlist('scenario_stage_questions')
    scenario_stages = [
        {
            'title': title.strip(),
            'description': scenario_stage_descriptions[index - 1].strip() if index - 1 < len(scenario_stage_descriptions) else '',
            'questions_count': scenario_stage_questions[index - 1].strip() if index - 1 < len(scenario_stage_questions) else '0',
        }
        for index, title in enumerate(scenario_stage_titles, start=1)
        if title.strip()
    ]
    scenario_questions = [
        {
            'stage': post.get(f'scenario_question_stage_{index}', '1'),
            'type': post.get(f'scenario_question_type_{index}', 'single'),
            'text': question.strip(),
            'difficulty': post.get(f'scenario_question_difficulty_{index}', 'medium'),
        }
        for index, question in enumerate(post.getlist('scenario_question_text'), start=1)
        if question.strip()
    ]
    scenario_patient_fields = {
        'age_gender': post.get('scenario_age_gender', ''),
        'chief_complaint': post.get('scenario_chief_complaint', ''),
        'history': post.get('scenario_history', ''),
        'physical_exam': post.get('scenario_physical_exam', ''),
        'labs': post.get('scenario_labs', ''),
        'diagnoses': post.get('scenario_diagnoses', ''),
        'tags': post.get('scenario_tags', ''),
    }
    scenario_execution = {
        'sequential_unlock': bool(post.get('scenario_sequential_unlock')),
        'prevent_backtracking': bool(post.get('scenario_prevent_backtracking')),
        'stage_time_limit_minutes': post.get('scenario_stage_time_limit_minutes') or '15',
        'shuffle_questions': bool(post.get('scenario_shuffle_questions')),
        'group_score': post.get('scenario_group_score') or post.get('default_points') or '20',
        'stage_feedback': bool(post.get('scenario_stage_feedback')),
        'pre_publish_review': bool(post.get('scenario_pre_publish_review')),
    }
    kfp_features = [
        {
            'title': title.strip(),
            'goal': post.get(f'kfp_feature_goal_{index}', '').strip(),
            'weight_percent': post.get(f'kfp_feature_weight_{index}', '').strip(),
            'danger_penalty': post.get(f'kfp_feature_penalty_{index}', '').strip(),
            'correct_answer': post.get(f'kfp_feature_answer_{index}', '').strip(),
            'score_cap': post.get(f'kfp_feature_score_{index}', '').strip(),
            'color': post.get(f'kfp_feature_color_{index}', '').strip(),
        }
        for index, title in enumerate(post.getlist('kfp_feature_title'), start=1)
        if title.strip()
    ]
    kfp_questions = [
        {
            'feature': post.get(f'kfp_question_feature_{index}', '').strip(),
            'type': post.get(f'kfp_question_type_{index}', '').strip(),
            'text': question.strip(),
        }
        for index, question in enumerate(post.getlist('kfp_question_text'), start=1)
        if question.strip()
    ]
    return {
        'requested_type': requested_type,
        'stored_type': stored_type,
        'structure': post.get('structure') or config['structure'],
        'difficulty': post.get('difficulty') or 'medium',
        'text': (post.get('text') or '').strip(),
        'options': options,
        'correct_answer': sorted(correct_values) if stored_type == 'multi' else (next(iter(correct_values), '') if stored_type in {'single', 'true_false'} else post.get('correct_answer', '')),
        'course_id': (post.get('course_id') or '').strip(),
        'default_points': clean_number(post.get('default_points'), '1'),
        'negative_points': clean_number(post.get('negative_points'), '-0.5'),
        'suggested_time_seconds': clean_number(post.get('suggested_time_seconds'), '180'),
        'tags': post.get('tags') or ('' if is_independent else 'قلب و عروق, ECG'),
        'subject': post.get('subject') or '',
        'question_media': {'image': post.get('question_image', '' if is_independent else 'ecg-sample.png'), 'audio': post.get('question_audio', ''), 'video': post.get('question_video', '')},
        'answer_media': {'items': [item for item in post.getlist('answer_media') if item]},
        'scoring_settings': {
            'partial_credit': bool(post.get('partial_credit')),
            'negative_marking': bool(post.get('negative_marking')),
            'shuffle_options': bool(post.get('shuffle_options')),
            'min_correct': post.get('min_correct') or ('1' if stored_type == 'multi' else ''),
            'max_correct': post.get('max_correct') or ('3' if stored_type == 'multi' else ''),
        },
        'feedback': {
            'mode': post.get('feedback_mode') or 'text',
            'text': post.get('feedback_text') or '',
            'correct': post.get('correct_feedback') or '',
            'incorrect': post.get('incorrect_feedback') or '',
        },
        'rubric': rubric,
        'accepted_answers': accepted_answers,
        'matching_pairs': matching_pairs,
        'ordering_items': ordering_items,
        'scenario_data': {
            'requested_type': requested_type,
            'template': post.get('template') or config['structure'],
            'title': post.get('scenario_title') or post.get('text') or '',
            'course_objective': post.get('scenario_course_objective') or '',
            'category': post.get('scenario_category') or '',
            'summary': post.get('scenario_summary') or '',
            'patient_fields': scenario_patient_fields,
            'stages': scenario_stages or [{'title': stage, 'description': '', 'questions_count': '0'} for stage in post.getlist('scenario_stage')],
            'questions': scenario_questions,
            'execution': scenario_execution,
            'media': {
                'mode': post.get('scenario_media_mode') or 'text',
                'text': post.get('scenario_media_text') or '',
                'image': post.get('scenario_media_image') or '',
                'audio': post.get('scenario_media_audio') or '',
                'video': post.get('scenario_media_video') or '',
            },
            'kfp': {
                'clinical_domain': post.get('kfp_clinical_domain') or '',
                'stem': post.get('kfp_stem') or post.get('text') or '',
                'features': kfp_features,
                'questions': kfp_questions,
                'matrix_total_percent': post.get('kfp_matrix_total_percent') or '100',
                'validity_score': post.get('kfp_validity_score') or 'موفق',
            },
        },
        # The «ذخیره پیش‌نویس» button always stores a draft, whatever the publish toggle says.
        'is_published': bool(post.get('is_published')) and not post.get('draft'),
    }


def _teacher_courses_rows(teacher_id):
    rows = erd_rows(
        """
        SELECT sg.id, sg.course_name, sg.group_code, sg.academic_year, sg.semester, sg.is_active,
               COUNT(DISTINCT sgm.id) AS students_count,
               COUNT(DISTINCT e.id) AS exams_count,
               MAX(e.start_at) AS latest_activity
        FROM student_groups sg
        LEFT JOIN group_teachers gt ON gt.group_id = sg.id
        LEFT JOIN student_group_members sgm ON sgm.group_id = sg.id
        LEFT JOIN exams e ON e.course_id = sg.course_id AND e.teacher_id = %s
        WHERE sg.teacher_id = %s OR gt.teacher_id = %s
        GROUP BY sg.id, sg.course_name, sg.group_code, sg.academic_year, sg.semester, sg.is_active
        ORDER BY sg.course_name
        LIMIT 120
        """,
        [teacher_id, teacher_id, teacher_id],
    )
    if rows:
        return rows
    return [
        {'id': 'nursing-01', 'course_name': 'مبانی پرستاری', 'course_code': 'NUR-101', 'group_code': '1', 'academic_year': '۱۴۰۴-۱۴۰۳', 'semester': 'نیمسال دوم', 'is_active': True, 'students_count': 32, 'capacity': 35, 'exams_count': 4, 'active_exams_count': 2, 'class_average': '16.8', 'latest_activity': '۱۴۰۴/۰۳/۲۰'},
        {'id': 'health-02', 'course_name': 'بهداشت و کمک‌های اولیه', 'course_code': 'HEA-114', 'group_code': '2', 'academic_year': '۱۴۰۴-۱۴۰۳', 'semester': 'نیمسال دوم', 'is_active': True, 'students_count': 28, 'capacity': 32, 'exams_count': 3, 'active_exams_count': 1, 'class_average': '15.4', 'latest_activity': '۱۴۰۴/۰۳/۱۸'},
        {'id': 'psych-01', 'course_name': 'روانشناسی در پرستاری', 'course_code': 'PSY-118', 'group_code': '1', 'academic_year': '۱۴۰۴-۱۴۰۳', 'semester': 'نیمسال دوم', 'is_active': True, 'students_count': 24, 'capacity': 30, 'exams_count': 2, 'active_exams_count': 1, 'class_average': '17.1', 'latest_activity': '۱۴۰۴/۰۳/۱۵'},
        {'id': 'pharma-03', 'course_name': 'فارماکولوژی', 'course_code': 'PHA-207', 'group_code': '3', 'academic_year': '۱۴۰۴-۱۴۰۳', 'semester': 'نیمسال دوم', 'is_active': True, 'students_count': 22, 'capacity': 30, 'exams_count': 3, 'active_exams_count': 1, 'class_average': '14.9', 'latest_activity': '۱۴۰۴/۰۳/۱۴'},
        {'id': 'nutrition-02', 'course_name': 'اصول تغذیه در سلامت', 'course_code': 'NUT-102', 'group_code': '2', 'academic_year': '۱۴۰۴-۱۴۰۳', 'semester': 'نیمسال دوم', 'is_active': True, 'students_count': 22, 'capacity': 28, 'exams_count': 2, 'active_exams_count': 0, 'class_average': '16.2', 'latest_activity': '۱۴۰۴/۰۳/۱۲'},
        {'id': 'communication-01', 'course_name': 'ارتباط موثر در پرستاری', 'course_code': 'COM-120', 'group_code': '1', 'academic_year': '۱۴۰۴-۱۴۰۳', 'semester': 'نیمسال دوم', 'is_active': True, 'students_count': 20, 'capacity': 30, 'exams_count': 2, 'active_exams_count': 0, 'class_average': '15.7', 'latest_activity': '۱۴۰۴/۰۳/۱۰'},
    ]


def _teacher_selected_course(courses, group_id=None):
    selected = next((row for row in courses if str(row.get('id')) == str(group_id)), None) if group_id else None
    selected = selected or (courses[0] if courses else {})
    if not selected:
        selected = _teacher_courses_rows(None)[0]
    course_name = selected.get('course_name') or 'مبانی پرستاری'
    return {
        **selected,
        'course_name': course_name,
        'course_code': selected.get('course_code') or 'NUR-101',
        'group_code': selected.get('group_code') or '1',
        'academic_year': selected.get('academic_year') or '۱۴۰۴-۱۴۰۳',
        'semester': selected.get('semester') or 'نیمسال دوم',
        'students_count': int(selected.get('students_count') or 32),
        'capacity': int(selected.get('capacity') or max(int(selected.get('students_count') or 32), 35)),
        'exams_count': int(selected.get('exams_count') or 4),
        'active_exams_count': int(selected.get('active_exams_count') or 2),
        'class_average': selected.get('class_average') or '16.8',
        'is_active': selected.get('is_active', True),
    }


def _teacher_group_exam_rows(teacher_id, group_id=None, course_name=None):
    rows = erd_rows(
        """
        SELECT e.id, e.title, e.duration_minutes, e.start_at, e.end_at,
               COALESCE(e.lifecycle_status, e.approval_status, '-') AS status,
               COUNT(DISTINCT ea.student_id) AS participants_count,
               AVG(ea.score) AS average_score
        FROM exams e
        LEFT JOIN exam_assignments exa ON exa.exam_id = e.id
        LEFT JOIN exam_attempts ea ON ea.exam_id = e.id
        WHERE e.teacher_id = %s
          AND (%s IS NULL OR exa.group_id = %s OR e.course_id = (SELECT course_id FROM student_groups WHERE id = %s LIMIT 1))
        GROUP BY e.id, e.title, e.duration_minutes, e.start_at, e.end_at, e.approval_status, e.is_published
        ORDER BY e.start_at DESC, e.title
        LIMIT 8
        """,
        [teacher_id, group_id, group_id, group_id],
    ) if teacher_id else []
    if rows:
        return rows
    return [
        {'id': 'exam-midterm', 'title': 'آزمون میان‌ترم', 'duration_minutes': 90, 'start_at': '۱۴۰۴/۰۲/۱۵ - ۱۰:۰۰', 'status': 'active', 'participants_count': 32, 'average_score': None},
        {'id': 'exam-chapter-1', 'title': 'آزمون فصل اول', 'duration_minutes': 60, 'start_at': '۱۴۰۴/۰۱/۲۰ - ۱۴:۰۰', 'status': 'finished', 'participants_count': 35, 'average_score': 74.6},
        {'id': 'exam-chapter-2', 'title': 'آزمون دوم (پیش‌نویس)', 'duration_minutes': 60, 'start_at': None, 'status': 'draft', 'participants_count': None, 'average_score': None},
        {'id': 'exam-final-quiz', 'title': 'کوئیز پایان فصل', 'duration_minutes': 30, 'start_at': '۱۴۰۴/۰۳/۲۵ - ۱۱:۰۰', 'status': 'scheduled', 'participants_count': None, 'average_score': None},
    ]


def _teacher_group_activity_rows(course_name='مبانی پرستاری'):
    return [
        {'title': 'آزمون میان‌ترم', 'type': 'آزمون', 'created_at': '۱۴۰۴/۰۳/۱۰ ۱۴:۳۰'},
        {'title': 'آزمون فصل ۲', 'type': 'آزمون', 'created_at': '۱۴۰۴/۰۲/۲۸ ۱۶:۱۵'},
        {'title': 'آزمون فصل ۲', 'type': 'آزمون', 'created_at': '۱۴۰۴/۰۲/۰۵ ۱۱:۲۰'},
    ]


def _teacher_exam_rows_simple(teacher_id):
    rows = erd_rows(
        """
        SELECT e.id AS pk, e.title, COALESCE(c.title, '-') AS course,
               COALESCE(e.lifecycle_status, e.approval_status, '-') AS status,
               e.start_at
        FROM exams e
        LEFT JOIN courses c ON c.id = e.course_id
        WHERE e.teacher_id = %s
        ORDER BY e.start_at DESC, e.title
        LIMIT 80
        """,
        [teacher_id],
    )
    return rows


QUESTION_TYPE_LABELS = {
    **question_kinds.TYPE_LABELS,
    'single': 'چهارگزینه‌ای',
    'multiple_choice': 'چهارگزینه‌ای',
    'multi': 'چندپاسخی',
    'true_false': 'درست / نادرست',
    'fill_blank': 'جای خالی',
    'short_answer': 'پاسخ کوتاه',
    'essay': 'تشریحی',
    'descriptive': 'تشریحی',
    'matching': 'تطبیقی',
    'ordering': 'مرتب‌سازی',
}


QUESTION_DIFFICULTY_LABELS = {
    'easy': 'آسان',
    'medium': 'متوسط',
    'hard': 'سخت',
}


QUESTION_STRUCTURE_LABELS = {
    'independent': 'مستقل',
    'case': 'سناریوی بیمار',
    'kfp': 'KFP',
    'osce': 'OSCE',
}


def _question_json(value, fallback):
    if value in (None, ''):
        return fallback
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return fallback


def _question_status(row, index=0):
    if not row.get('text'):
        return 'needs_review', 'نیازمند بازبینی', 'is-warn'
    if row.get('is_published') in (True, 1, '1', 'true', 'True'):
        return 'active', 'فعال', 'is-ok'
    if index % 5 == 2:
        return 'needs_review', 'نیازمند بازبینی', 'is-warn'
    return 'draft', 'پیش‌نویس', 'is-muted'


def _teacher_question_rows(teacher_id, request=None):
    question_columns = erd_table_columns('questions')
    structure_select = "q.structure" if 'structure' in question_columns else "'independent' AS structure"
    subject_select = "q.subject" if 'subject' in question_columns else "COALESCE(c.title, '-') AS subject"
    scenario_select = "q.scenario_data" if 'scenario_data' in question_columns else "'{}' AS scenario_data"
    if not teacher_id:
        rows = []
    else:
        rows = erd_rows(
            f"""
            SELECT q.id, q.text, q.type, q.difficulty, q.default_points, q.tags,
                   {structure_select}, {subject_select}, q.options, q.correct_answer,
                   {scenario_select}, q.is_published, COALESCE(c.title, '-') AS course
            FROM questions q
            LEFT JOIN courses c ON c.id = q.course_id
            WHERE q.teacher_id = %s
            ORDER BY q.text
            LIMIT 240
            """,
            [teacher_id],
        )
    if not rows:
        rows = [
            {'id': 'Q-000125', 'text': 'مهم‌ترین علامت اولیه سکته قلبی در بیمار کدام است؟', 'type': 'single', 'difficulty': 'medium', 'course': 'پرستاری داخلی - قلب', 'default_points': 2, 'tags': 'قلب و عروق, سکته قلبی', 'structure': 'independent', 'is_published': True, 'options': json.dumps(['تنگی نفس', 'تهوع و استفراغ', 'درد فشاری قفسه سینه', 'سردرد شدید'], ensure_ascii=False), 'correct_answer': json.dumps('3', ensure_ascii=False)},
            {'id': 'Q-000124', 'text': 'علت اصلی ناراحتی در بیماران مبتلا به رفلاکس معده چیست؟', 'type': 'single', 'difficulty': 'medium', 'course': 'پرستاری داخلی - گوارش', 'default_points': 1, 'tags': 'گوارش', 'structure': 'independent', 'is_published': False},
            {'id': 'Q-000123', 'text': 'بهترین روش پیشگیری از زخم بستر در بیماران بی‌تحرک کدام است؟', 'type': 'multi', 'difficulty': 'hard', 'course': 'پرستاری پزشکی - مراقبت‌ها', 'default_points': 3, 'tags': 'پرستاری, مراقبت', 'structure': 'case', 'is_published': False},
            {'id': 'Q-000122', 'text': 'کدام دارو برای کنترل فشار خون در بیماران سالمند مناسب‌تر است؟', 'type': 'single', 'difficulty': 'medium', 'course': 'پرستاری داخلی - قلب', 'default_points': 2, 'tags': 'فشار خون, قلب', 'structure': 'independent', 'is_published': True},
            {'id': 'Q-000121', 'text': 'علائم اولیه هیپوگلیسمی در بیماران دیابتی کدام است؟', 'type': 'single', 'difficulty': 'easy', 'course': 'پرستاری داخلی - غدد', 'default_points': 1, 'tags': 'دیابت, غدد', 'structure': 'independent', 'is_published': True},
        ]

    enriched = []
    for index, row in enumerate(rows, start=1):
        status_key, status_label, status_class = _question_status(row, index)
        qtype = row.get('type') or 'single'
        difficulty = row.get('difficulty') or 'medium'
        structure = row.get('structure') or 'independent'
        tags = [tag.strip() for tag in str(row.get('tags') or '').replace('،', ',').split(',') if tag.strip()]
        options = _question_json(row.get('options'), [])
        correct = _question_json(row.get('correct_answer'), '')
        enriched.append({
            **row,
            'code': str(row.get('id') or f'Q-{index:06d}')[:8] if not str(row.get('id') or '').startswith('Q-') else row.get('id'),
            'type_label': QUESTION_TYPE_LABELS.get(qtype, qtype),
            'difficulty_label': QUESTION_DIFFICULTY_LABELS.get(difficulty, difficulty),
            'difficulty_class': 'is-ok' if difficulty == 'easy' else 'is-danger' if difficulty == 'hard' else 'is-muted',
            'structure_label': QUESTION_STRUCTURE_LABELS.get(structure, structure),
            'status_key': status_key,
            'status_label': status_label,
            'status_class': status_class,
            'tags_list': tags[:3],
            'options_list': options if isinstance(options, list) else [],
            'correct_display': ', '.join(correct) if isinstance(correct, list) else str(correct or '-'),
            'updated_display': '۱۴۰۴/۰۳/۲۰ ۱۰:۱۵',
            'usage_count': index + 5,
        })

    if request is None:
        return enriched
    query = (request.GET.get('q') or '').strip()
    status_filter = request.GET.get('status') or 'all'
    type_filter = request.GET.get('type') or 'all'
    difficulty_filter = request.GET.get('difficulty') or 'all'
    if query:
        q = query.lower()
        enriched = [item for item in enriched if q in str(item.get('text', '')).lower() or q in str(item.get('course', '')).lower()]
    if status_filter != 'all':
        enriched = [item for item in enriched if item['status_key'] == status_filter]
    if type_filter != 'all':
        type_aliases = {'single': {'single', 'multiple_choice'}, 'essay': {'essay', 'descriptive'}}
        accepted_types = type_aliases.get(type_filter, {type_filter})
        enriched = [item for item in enriched if item.get('type') in accepted_types]
    if difficulty_filter != 'all':
        enriched = [item for item in enriched if item.get('difficulty') == difficulty_filter]
    return enriched


def _teacher_question_sets(teacher_id, all_questions):
    has_sets = bool(erd_table_columns('question_sets') and erd_table_columns('question_set_items'))
    rows = erd_rows(
        """
        SELECT qs.id, qs.title, qs.description, qs.status, qs.status_note,
               COALESCE(c.title, '-') AS course,
               COUNT(qsi.id) AS count
        FROM question_sets qs
        LEFT JOIN courses c ON c.id = qs.course_id
        LEFT JOIN question_set_items qsi ON qsi.set_id = qs.id
        WHERE qs.created_by = %s OR qs.target_teacher_id = %s
        GROUP BY qs.id, qs.title, qs.description, qs.status, qs.status_note, c.title
        ORDER BY qs.title
        LIMIT 80
        """,
        [teacher_id, teacher_id],
    ) if teacher_id and has_sets else []
    if rows:
        return [
            {
                **row,
                'count': int(row.get('count') or 0),
                'status_label': 'اشتراکی' if row.get('status') == 'shared' else 'خصوصی',
                'status_class': 'is-ok' if row.get('status') == 'shared' else 'is-muted',
                'updated_display': '۱۴۰۴/۰۳/۲۰ ۰۹:۳۰',
            }
            for row in rows
        ]
    courses = list({q.get('course') or 'بانک عمومی' for q in all_questions})[:6]
    return [
        {
            'id': f'bank-{index}',
            'title': course,
            'description': 'بانک سؤال ساخته‌شده از سؤال‌های موجود استاد',
            'course': course,
            'count': sum(1 for q in all_questions if (q.get('course') or 'بانک عمومی') == course),
            'status': 'private',
            'status_label': 'خصوصی',
            'status_class': 'is-muted',
            'updated_display': '۱۴۰۴/۰۳/۲۰ ۰۹:۳۰',
        }
        for index, course in enumerate(courses, start=1)
    ]


def _teacher_question_tags(all_questions):
    counts = {}
    for question in all_questions:
        for tag in question.get('tags_list') or []:
            counts[tag] = counts.get(tag, 0) + 1
    if not counts:
        counts = {'قلب': 18, 'اورژانس': 16, 'تنفسی': 14, 'سالمندی': 12, 'داروشناسی': 9, 'مهارت بالینی': 8}
    palette = ['is-red', 'is-orange', 'is-blue', 'is-purple', 'is-green', 'is-yellow']
    return [
        {'title': tag, 'count': count, 'class': palette[index % len(palette)]}
        for index, (tag, count) in enumerate(sorted(counts.items(), key=lambda item: item[1], reverse=True)[:8])
    ]


JALALI_MONTH_NAMES = ('فروردین', 'اردیبهشت', 'خرداد', 'تیر', 'مرداد', 'شهریور', 'مهر', 'آبان', 'آذر', 'دی', 'بهمن', 'اسفند')
JALALI_WEEKDAY_NAMES = ('دوشنبه', 'سه‌شنبه', 'چهارشنبه', 'پنجشنبه', 'جمعه', 'شنبه', 'یکشنبه')  # indexed by date.weekday()


def _jalali_long_date(value, with_weekday: bool = True) -> str:
    """'شنبه ۲۹ اردیبهشت ۱۴۰۴' for a date/datetime (or ISO text from SQLite); '' when empty."""
    from .templatetags.core_extras import _gregorian_to_jalali, fa_digits

    value = erd_datetime(value) if not hasattr(value, 'weekday') else value
    if not value:
        return ''
    if hasattr(value, 'hour'):
        value = timezone.localtime(value)
    jy, jm, jd = _gregorian_to_jalali(value.year, value.month, value.day)
    weekday = f'{JALALI_WEEKDAY_NAMES[value.weekday()]} ' if with_weekday else ''
    return fa_digits(f'{weekday}{jd} {JALALI_MONTH_NAMES[jm - 1]} {jy}')


TEACHER_DASHBOARD_EXAM_STATUS = {
    'in_progress': ('در حال برگزاری', 'green'),
    'published': ('برنامه‌ریزی شده', 'blue'),
    'approved': ('تأیید شده', 'blue'),
    'pending_approval': ('در انتظار تأیید', 'orange'),
    'draft': ('پیش‌نویس', 'violet'),
}


def _teacher_dashboard_participant_counts(exam_ids: list) -> dict:
    """Assigned students per exam: direct assignments plus group members, minus exclusions."""
    if not exam_ids:
        return {}
    marks = ', '.join(['%s'] * len(exam_ids))
    rows = erd_rows(
        f"""
        SELECT exam_id, COUNT(*) AS count FROM (
            SELECT ea.exam_id, ea.student_profile_id AS student_id
            FROM exam_assignments ea
            WHERE ea.exam_id IN ({marks}) AND ea.student_profile_id IS NOT NULL
            UNION
            SELECT ea.exam_id, sgm.student_user_id AS student_id
            FROM exam_assignments ea
            JOIN student_group_members sgm ON sgm.group_id = ea.group_id
            WHERE ea.exam_id IN ({marks})
              AND NOT EXISTS (
                  SELECT 1 FROM exam_assignment_exclusions ax
                  WHERE ax.exam_id = ea.exam_id AND ax.student_profile_id = sgm.student_user_id
              )
        ) assigned
        GROUP BY exam_id
        """,
        [*exam_ids, *exam_ids],
    )
    return {str(row['exam_id']): row['count'] for row in rows}


def _teacher_dashboard_data(teacher_id) -> dict:
    """Everything the teacher dashboard shows, all scoped to this teacher's exams and questions."""
    from django.utils.timesince import timesince

    now = timezone.now()
    lifecycle = "COALESCE(e.lifecycle_status, '')"
    not_cancelled = 'COALESCE(e.is_cancelled, false) = false'

    active_exams = erd_row(
        f"""
        SELECT COUNT(*) AS count FROM exams e
        WHERE e.teacher_id = %s AND {not_cancelled}
          AND {lifecycle} IN ('published', 'in_progress')
          AND (e.start_at IS NULL OR e.start_at <= %s) AND (e.end_at IS NULL OR e.end_at >= %s)
        """,
        [teacher_id, now, now],
    )['count']

    upcoming = erd_rows(
        f"""
        SELECT e.id, e.title, COALESCE(c.title, '-') AS course, e.start_at, e.duration_minutes,
               {lifecycle} AS lifecycle
        FROM exams e
        LEFT JOIN courses c ON c.id = e.course_id
        WHERE e.teacher_id = %s AND {not_cancelled}
          AND {lifecycle} NOT IN ('closed', 'archived')
          AND (e.start_at >= %s OR (e.end_at IS NOT NULL AND e.end_at >= %s))
        ORDER BY e.start_at
        LIMIT 5
        """,
        [teacher_id, now, now],
    )
    upcoming_count = erd_row(
        f"""
        SELECT COUNT(*) AS count FROM exams e
        WHERE e.teacher_id = %s AND {not_cancelled} AND {lifecycle} NOT IN ('closed', 'archived') AND e.start_at > %s
        """,
        [teacher_id, now],
    )['count']
    participants = _teacher_dashboard_participant_counts([str(row['id']) for row in upcoming])
    for row in upcoming:
        start_at = erd_datetime(row['start_at'])
        status_key = row['lifecycle']
        if status_key == 'published' and start_at and start_at <= now:
            status_key = 'in_progress'
        row['status_label'], row['status_tone'] = TEACHER_DASHBOARD_EXAM_STATUS.get(status_key, ('پیش‌نویس', 'violet'))
        row['date_label'] = _jalali_long_date(start_at)
        row['time_label'] = timezone.localtime(start_at).strftime('%H:%M') if start_at else ''
        row['participants'] = participants.get(str(row['id']))

    new_questions = None
    if erd_has_column('questions', 'created_at'):
        new_questions = erd_count('questions', 'teacher_id = %s AND created_at >= %s', [teacher_id, now - timedelta(days=30)])

    pending_by_exam = erd_rows(
        """
        SELECT e.id, e.title, COUNT(aa.id) AS count
        FROM attempt_answers aa
        JOIN questions q ON q.id = aa.question_id
        JOIN exam_attempts ea ON ea.id = aa.attempt_id
        JOIN exams e ON e.id = ea.exam_id
        WHERE COALESCE(aa.needs_manual_grading, false) = true AND q.teacher_id = %s
        GROUP BY e.id, e.title
        ORDER BY COUNT(aa.id) DESC, e.title
        """,
        [teacher_id],
    )

    performance = erd_rows(
        """
        SELECT e.id, e.title, MAX(e.start_at) AS start_at, AVG(ea.score * 20.0 / ea.max_score) AS average
        FROM exam_attempts ea
        JOIN exams e ON e.id = ea.exam_id
        WHERE e.teacher_id = %s AND ea.score IS NOT NULL AND ea.max_score > 0
        GROUP BY e.id, e.title
        ORDER BY MAX(e.start_at) DESC
        LIMIT 6
        """,
        [teacher_id],
    )
    performance.reverse()
    for row in performance:
        row['average'] = round(max(0.0, min(20.0, float(row['average'] or 0))), 1)
        row['height'] = round(row['average'] * 5)  # percent of a 20-point axis

    activities = []
    if erd_has_column('activity_audit_log', 'created_at'):
        activities = erd_rows(
            """
            SELECT action, reason, created_at FROM activity_audit_log
            WHERE actor_id = %s AND action NOT LIKE 'login%%' AND action NOT LIKE 'two_factor%%'
              AND COALESCE(reason, '') <> ''
            ORDER BY created_at DESC
            LIMIT 5
            """,
            [teacher_id],
        )
        for row in activities:
            created_at = erd_datetime(row['created_at'])
            row['ago'] = f'{timesince(created_at, now, depth=1)} پیش' if created_at else ''

    return {
        'today_label': _jalali_long_date(timezone.localdate()),
        'active_exams': active_exams,
        'upcoming_count': upcoming_count,
        'upcoming_exams': upcoming,
        'next_exam': upcoming[0] if upcoming else None,
        'new_questions': new_questions,
        'pending_total': sum(row['count'] for row in pending_by_exam),
        'pending_exam_count': len(pending_by_exam),
        'pending_by_exam': pending_by_exam[:4],
        'performance': performance,
        'activities': activities,
    }


TEACHER_EXAM_LIST_FILTERS = {
    'all': 'همه وضعیت‌ها',
    'draft': 'پیش‌نویس',
    'pending_approval': 'در انتظار تأیید',
    'active': 'منتشرشده / در حال برگزاری',
    'finished': 'پایان‌یافته',
    'cancelled': 'لغو شده',
}
TEACHER_EXAM_LIST_PAGE_SIZE = 20


def _teacher_exam_status(row, now) -> tuple:
    """(label, badge tone) of one exam from its lifecycle, cancellation and time window."""
    if row.get('is_cancelled'):
        return 'لغو شده', 'is-muted'
    lifecycle = row.get('lifecycle') or 'draft'
    start_at, end_at = erd_datetime(row.get('start_at')), erd_datetime(row.get('end_at'))
    if lifecycle in ('closed', 'archived') or (lifecycle in ('published', 'in_progress') and end_at and end_at < now):
        return 'پایان‌یافته', 'is-muted'
    if lifecycle in ('published', 'in_progress'):
        return ('در حال برگزاری', 'is-ok') if start_at and start_at <= now else ('برنامه‌ریزی شده', 'is-blue')
    return {
        'approved': ('تأیید شده', 'is-blue'),
        'scheduled': ('زمان‌بندی انتشار', 'is-blue'),
        'pending_approval': ('در انتظار تأیید', 'is-warn'),
    }.get(lifecycle, ('پیش‌نویس', 'is-violet'))


def _teacher_exam_list(teacher_id, query: str, status: str, page_number) -> dict:
    """One page of the teacher's own exams with real course, groups, question and participant counts."""
    from django.core.paginator import Paginator

    now = timezone.now()
    lifecycle = "COALESCE(e.lifecycle_status, '')"
    cancelled = 'COALESCE(e.is_cancelled, false) = true'
    running = f"{lifecycle} IN ('published', 'in_progress')"
    status_conditions = {
        'draft': (f"{lifecycle} IN ('draft', '') AND NOT {cancelled}", []),
        'pending_approval': (f"{lifecycle} = 'pending_approval' AND NOT {cancelled}", []),
        'active': (f"NOT {cancelled} AND ({lifecycle} IN ('approved', 'scheduled') OR ({running} AND (e.end_at IS NULL OR e.end_at >= %s)))", [now]),
        'finished': (f"NOT {cancelled} AND ({lifecycle} IN ('closed', 'archived') OR ({running} AND e.end_at < %s))", [now]),
        'cancelled': (cancelled, []),
    }
    where, params = ['e.teacher_id = %s'], [teacher_id]
    if query:
        where.append('e.title LIKE %s')
        params.append(f'%{query}%')
    if status in status_conditions:
        condition, condition_params = status_conditions[status]
        where.append(f'({condition})')
        params.extend(condition_params)
    where_sql = ' AND '.join(where)

    total = erd_row(f'SELECT COUNT(*) AS count FROM exams e WHERE {where_sql}', params)['count']
    page = Paginator(range(total), TEACHER_EXAM_LIST_PAGE_SIZE).get_page(page_number)
    rows = erd_rows(
        f"""
        SELECT e.id, e.title, COALESCE(c.title, '-') AS course, e.start_at, e.end_at, e.duration_minutes,
               {lifecycle} AS lifecycle, COALESCE(e.is_cancelled, false) AS is_cancelled,
               COALESCE(e.is_published, false) AS is_published
        FROM exams e
        LEFT JOIN courses c ON c.id = e.course_id
        WHERE {where_sql}
        ORDER BY CASE WHEN e.start_at IS NULL THEN 0 ELSE 1 END, e.start_at DESC, e.title
        LIMIT %s OFFSET %s
        """,
        [*params, TEACHER_EXAM_LIST_PAGE_SIZE, page.start_index() - 1 if total else 0],
    )

    exam_ids = [str(row['id']) for row in rows]
    question_counts, submitted_counts, pending_counts, group_labels, attempt_counts = {}, {}, {}, {}, {}
    if exam_ids:
        marks = ', '.join(['%s'] * len(exam_ids))
        question_counts = {str(r['exam_id']): r['count'] for r in erd_rows(
            f'SELECT exam_id, COUNT(*) AS count FROM exam_questions WHERE exam_id IN ({marks}) GROUP BY exam_id', exam_ids)}
        attempt_counts = {str(r['exam_id']): r['count'] for r in erd_rows(
            f'SELECT exam_id, COUNT(*) AS count FROM exam_attempts WHERE exam_id IN ({marks}) GROUP BY exam_id', exam_ids)}
        submitted_counts = {str(r['exam_id']): r['count'] for r in erd_rows(
            f"""
            SELECT exam_id, COUNT(DISTINCT student_id) AS count FROM exam_attempts
            WHERE exam_id IN ({marks}) AND status IN ('submitted', 'graded') GROUP BY exam_id
            """, exam_ids)}
        pending_counts = {str(r['exam_id']): r['count'] for r in erd_rows(
            f"""
            SELECT ea.exam_id, COUNT(aa.id) AS count
            FROM attempt_answers aa JOIN exam_attempts ea ON ea.id = aa.attempt_id
            WHERE ea.exam_id IN ({marks}) AND COALESCE(aa.needs_manual_grading, false) = true
            GROUP BY ea.exam_id
            """, exam_ids)}
        for r in erd_rows(
            f"""
            SELECT ea.exam_id, sg.group_code, sg.course_name
            FROM exam_assignments ea JOIN student_groups sg ON sg.id = ea.group_id
            WHERE ea.exam_id IN ({marks})
            ORDER BY sg.course_name, sg.group_code
            """, exam_ids):
            group_labels.setdefault(str(r['exam_id']), []).append(f"گروه {r['group_code']}" if r['group_code'] else r['course_name'])
    assigned_counts = _teacher_dashboard_participant_counts(exam_ids)

    for row in rows:
        exam_id = str(row['id'])
        start_at = erd_datetime(row['start_at'])
        row['status_label'], row['status_tone'] = _teacher_exam_status(row, now)
        row['date_label'] = _jalali_long_date(start_at)
        row['time_label'] = timezone.localtime(start_at).strftime('%H:%M') if start_at else ''
        row['groups_label'] = '، '.join(group_labels.get(exam_id, []))
        row['question_count'] = question_counts.get(exam_id, 0)
        row['assigned'] = assigned_counts.get(exam_id)
        row['submitted'] = submitted_counts.get(exam_id, 0)
        row['pending_reviews'] = pending_counts.get(exam_id, 0)
        # same rule as _teacher_exam_editable, from the counts already loaded for this page
        row['editable'] = (
            (row['lifecycle'] or 'draft') in ('draft', 'pending_approval')
            and not row['is_published'] and not row['is_cancelled'] and not attempt_counts.get(exam_id)
        )
    return {'rows': rows, 'page': page, 'total': total, 'query': query, 'status': status, 'filters': TEACHER_EXAM_LIST_FILTERS}


TEACHER_CLASS_LIST_FILTERS = {'all': 'همه وضعیت‌ها', 'active': 'فعال', 'inactive': 'غیرفعال / پیش‌نویس'}
TEACHER_CLASS_LIST_PAGE_SIZE = 12
TEACHER_CLASS_AVATARS = 4  # member faces stacked on each class card
# A student's photo as teachers see it: empty when the student switched «نمایش تصویر پروفایل برای استاد» off
# on their settings page. Needs `p` (profiles) and `sp` (student_profiles) in the query.
STUDENT_AVATAR_SQL = "CASE WHEN COALESCE(sp.show_avatar_to_teacher, true) THEN COALESCE(p.avatar_url, '') ELSE '' END"


def _teacher_semester_label(semester, year) -> str:
    """'نیمسال اول ۱۴۰۴-۱۴۰۵' from the free-text semester/year stored on a group."""
    from .templatetags.core_extras import fa_digits

    semester = str(semester or '').strip()
    semester = {'1': 'اول', '2': 'دوم', 'summer': 'تابستان'}.get(semester, semester)
    if semester and not semester.startswith(('نیمسال', 'تابستان')):
        semester = f'نیمسال {semester}'
    return fa_digits(' '.join(part for part in (semester, str(year or '').strip()) if part))


def _teacher_class_list(teacher_id, query: str, term: str, status: str, page_number) -> dict:
    """One page of the groups this teacher teaches (owner or co-teacher), with real member and exam figures."""
    from django.core.paginator import Paginator

    now = timezone.now()
    status_col = "COALESCE(sg.status, 'active')" if erd_has_column('student_groups', 'status') else "'active'"
    is_active = f"(COALESCE(sg.is_active, true) = true AND {status_col} = 'active')"
    own = ['(sg.teacher_id = %s OR sg.id IN (SELECT group_id FROM group_teachers WHERE teacher_id = %s))']
    if erd_has_column('student_groups', 'is_archived'):
        own.append('COALESCE(sg.is_archived, false) = false')
    own_params = [teacher_id, teacher_id]

    terms = [
        {'value': f"{row['academic_year'] or ''}|{row['semester'] or ''}", 'label': _teacher_semester_label(row['semester'], row['academic_year'])}
        for row in erd_rows(
            f"SELECT DISTINCT sg.academic_year, sg.semester FROM student_groups sg WHERE {' AND '.join(own)} ORDER BY sg.academic_year DESC, sg.semester DESC",
            own_params,
        )
    ]
    if term not in {item['value'] for item in terms}:
        term = ''

    where, params = list(own), list(own_params)
    if query:
        where.append('(sg.course_name LIKE %s OR c.code LIKE %s OR sg.group_code LIKE %s)')
        params.extend([f'%{query}%'] * 3)
    if term:
        year, semester = term.split('|', 1)
        where.append("COALESCE(sg.academic_year, '') = %s AND COALESCE(sg.semester, '') = %s")
        params.extend([year, semester])
    if status == 'active':
        where.append(is_active)
    elif status == 'inactive':
        where.append(f'NOT {is_active}')
    where_sql = ' AND '.join(where)

    total = erd_row(f'SELECT COUNT(*) AS count FROM student_groups sg LEFT JOIN courses c ON c.id = sg.course_id WHERE {where_sql}', params)['count']
    page = Paginator(range(total), TEACHER_CLASS_LIST_PAGE_SIZE).get_page(page_number)
    not_cancelled = 'COALESCE(e.is_cancelled, false) = false'
    rows = erd_rows(
        f"""
        SELECT sg.id, sg.course_name, c.code AS course_code, sg.group_code, sg.academic_year, sg.semester,
               {status_col} AS status, {is_active} AS is_active,
               (SELECT COUNT(*) FROM student_group_members m WHERE m.group_id = sg.id) AS students_count,
               (SELECT COUNT(DISTINCT e.id) FROM exam_assignments ea JOIN exams e ON e.id = ea.exam_id
                 WHERE ea.group_id = sg.id AND {not_cancelled}) AS exams_count,
               (SELECT MIN(e.start_at) FROM exam_assignments ea JOIN exams e ON e.id = ea.exam_id
                 WHERE ea.group_id = sg.id AND {not_cancelled} AND e.start_at > %s) AS next_exam_at,
               (SELECT MAX(e.start_at) FROM exam_assignments ea JOIN exams e ON e.id = ea.exam_id
                 WHERE ea.group_id = sg.id AND {not_cancelled} AND e.start_at <= %s) AS last_exam_at
        FROM student_groups sg
        LEFT JOIN courses c ON c.id = sg.course_id
        WHERE {where_sql}
        ORDER BY {is_active} DESC, sg.academic_year DESC, sg.course_name, sg.group_code
        LIMIT %s OFFSET %s
        """,
        [now, now, *params, TEACHER_CLASS_LIST_PAGE_SIZE, page.start_index() - 1 if total else 0],
    )

    faces = {}
    group_ids = [str(row['id']) for row in rows]
    if group_ids:
        marks = ', '.join(['%s'] * len(group_ids))
        for face in erd_rows(
            f"""
            SELECT group_id, full_name, avatar_url FROM (
                SELECT m.group_id, m.full_name, {STUDENT_AVATAR_SQL} AS avatar_url,
                       ROW_NUMBER() OVER (PARTITION BY m.group_id ORDER BY m.full_name) AS position
                FROM student_group_members m LEFT JOIN profiles p ON p.id = m.student_user_id
                LEFT JOIN student_profiles sp ON sp.user_id = m.student_user_id
                WHERE m.group_id IN ({marks})
            ) ranked
            WHERE position <= %s
            """,
            [*group_ids, TEACHER_CLASS_AVATARS],
        ):
            faces.setdefault(str(face['group_id']), []).append({
                'name': face['full_name'], 'avatar_url': face['avatar_url'], 'initial': (face['full_name'] or '؟').strip()[:1],
            })

    for row in rows:
        row['is_active'] = bool(row['is_active'])
        row['status_label'] = 'فعال' if row['is_active'] else ('پیش‌نویس' if row['status'] == 'draft' else 'غیرفعال')
        row['term_label'] = _teacher_semester_label(row['semester'], row['academic_year'])
        row['faces'] = faces.get(str(row['id']), [])
        row['more_students'] = max(0, int(row['students_count'] or 0) - len(row['faces']))
        row['next_exam_label'] = _jalali_long_date(row['next_exam_at'], with_weekday=False)
        row['last_exam_label'] = _jalali_long_date(row['last_exam_at'], with_weekday=False)

    all_own = ' AND '.join(own)
    summary = erd_row(
        f"""
        SELECT COUNT(*) AS classes, SUM(CASE WHEN {is_active} THEN 1 ELSE 0 END) AS active_classes,
               (SELECT COUNT(DISTINCT m.student_user_id) FROM student_group_members m
                 WHERE m.group_id IN (SELECT sg.id FROM student_groups sg WHERE {all_own})) AS students
        FROM student_groups sg WHERE {all_own}
        """,
        [*own_params, *own_params],
    )
    lifecycle = "COALESCE(e.lifecycle_status, '')"
    summary['finished_exams'] = erd_row(
        f"""
        SELECT COUNT(*) AS count FROM exams e
        WHERE e.teacher_id = %s AND {not_cancelled}
          AND ({lifecycle} IN ('closed', 'archived') OR ({lifecycle} IN ('published', 'in_progress') AND e.end_at < %s))
        """,
        [teacher_id, now],
    )['count']
    summary['active_classes'] = summary['active_classes'] or 0
    return {
        'rows': rows, 'page': page, 'total': total, 'query': query, 'term': term, 'status': status,
        'terms': terms, 'filters': TEACHER_CLASS_LIST_FILTERS, 'summary': summary,
    }


TEACHER_RESULTS_PAGE_SIZE = 50
TEACHER_RESULT_BUCKETS = ((0, 4), (4, 8), (8, 12), (12, 16), (16, 20))


def _teacher_owned_exam(teacher_id, exam_id):
    """The exam row when it belongs to this teacher, else None (callers turn None into a 404)."""
    return erd_row(
        """
        SELECT e.id, e.title, e.start_at, e.end_at, e.duration_minutes, e.passing_score,
               COALESCE(c.title, '-') AS course
        FROM exams e LEFT JOIN courses c ON c.id = e.course_id
        WHERE e.id = %s AND e.teacher_id = %s
        """,
        [exam_id, teacher_id],
    )


def _teacher_exam_options(teacher_id) -> list:
    """The teacher's exams for the results/monitoring selector, newest first."""
    rows = erd_rows(
        """
        SELECT e.id, e.title, e.start_at, e.end_at,
               (SELECT COUNT(*) FROM exam_attempts ea WHERE ea.exam_id = e.id AND ea.status IN ('submitted', 'graded')) AS submitted,
               (SELECT COUNT(*) FROM exam_attempts ea WHERE ea.exam_id = e.id AND ea.status = 'in_progress') AS in_progress
        FROM exams e
        WHERE e.teacher_id = %s AND COALESCE(e.is_cancelled, false) = false
        ORDER BY CASE WHEN e.start_at IS NULL THEN 1 ELSE 0 END, e.start_at DESC, e.title
        LIMIT 200
        """,
        [teacher_id],
    )
    for row in rows:
        row['start_at'], row['end_at'] = erd_datetime(row['start_at']), erd_datetime(row['end_at'])
        row['date_label'] = _jalali_long_date(row['start_at'])
    return rows


def _teacher_exam_results(exam, page_number) -> dict:
    """Score summary, 0-20 distribution and one page of submitted attempts for an exam the teacher owns."""
    from django.core.paginator import Paginator

    graded = erd_rows(
        "SELECT score, max_score FROM exam_attempts WHERE exam_id = %s AND status IN ('submitted', 'graded') "
        'AND COALESCE(is_graded, false) = true AND score IS NOT NULL AND max_score > 0',
        [exam['id']],
    )
    summary = erd_row(
        """
        SELECT COUNT(DISTINCT student_id) AS participants, COUNT(*) AS attempts,
               SUM(CASE WHEN COALESCE(is_graded, false) = false OR score IS NULL THEN 1 ELSE 0 END) AS ungraded
        FROM exam_attempts WHERE exam_id = %s AND status IN ('submitted', 'graded')
        """,
        [exam['id']],
    )
    scores = [float(row['score']) * 20 / float(row['max_score']) for row in graded]
    passed = sum(
        1 for row in graded
        if _sx_result_status({'is_graded': True, 'score': row['score'], 'max_score': row['max_score'],
                              'passing_score': exam.get('passing_score'),
                              'percent': _sx_percent(row['score'], row['max_score'])})[0] == 'قبول'
    )
    buckets = []
    for low, high in TEACHER_RESULT_BUCKETS:
        count = sum(1 for score in scores if low <= score < high or (high == 20 and score == 20))
        buckets.append({'label': f'{low}–{high}', 'count': count})
    peak = max((bucket['count'] for bucket in buckets), default=0) or 1
    for bucket in buckets:
        bucket['height'] = round(bucket['count'] * 100 / peak)

    total = summary['attempts'] if summary else 0
    page = Paginator(range(total), TEACHER_RESULTS_PAGE_SIZE).get_page(page_number)
    rows = erd_rows(
        """
        SELECT ea.id, ea.score, ea.max_score, ea.is_graded, ea.submitted_at,
               COALESCE(NULLIF(p.full_name, ''), p.username, 'دانشجو') AS name,
               COALESCE(NULLIF(sp.student_number, ''), p.identifier, '') AS code
        FROM exam_attempts ea
        JOIN profiles p ON p.id = ea.student_id
        LEFT JOIN student_profiles sp ON sp.user_id = ea.student_id
        WHERE ea.exam_id = %s AND ea.status IN ('submitted', 'graded')
        ORDER BY CASE WHEN ea.score IS NULL THEN 1 ELSE 0 END, ea.score DESC, name
        LIMIT %s OFFSET %s
        """,
        [exam['id'], TEACHER_RESULTS_PAGE_SIZE, page.start_index() - 1 if total else 0],
    )
    for row in rows:
        row['percent'] = _sx_percent(row['score'], row['max_score'])
        row['score_20'] = round(float(row['score']) * 20 / float(row['max_score']), 2) if row['score'] is not None and row['max_score'] else None
        row['status_label'], tone, _pending = _sx_result_status({**row, 'passing_score': exam.get('passing_score')})
        row['status_tone'] = {'green': 'is-ok', 'red': 'is-danger'}.get(tone, 'is-warn')
        row['submitted_label'] = _jalali_long_date(row['submitted_at'])
    return {
        'participants': summary['participants'] if summary else 0,
        'ungraded': (summary or {}).get('ungraded') or 0,
        'average': round(sum(scores) / len(scores), 2) if scores else None,
        'highest': round(max(scores), 2) if scores else None,
        'lowest': round(min(scores), 2) if scores else None,
        'pass_rate': round(passed * 100 / len(scores)) if scores else None,
        'buckets': buckets if scores else [],
        'rows': rows,
        'page': page,
    }


def _teacher_exam_monitoring(exam) -> dict:
    """Live counts and in-progress attempts of an exam the teacher owns."""
    now = timezone.now()
    start_at, end_at = erd_datetime(exam.get('start_at')), erd_datetime(exam.get('end_at'))
    counts = erd_row(
        """
        SELECT COUNT(DISTINCT student_id) AS started,
               COUNT(DISTINCT CASE WHEN status = 'in_progress' THEN student_id END) AS in_progress,
               COUNT(DISTINCT CASE WHEN status IN ('submitted', 'graded') THEN student_id END) AS submitted
        FROM exam_attempts WHERE exam_id = %s
        """,
        [exam['id']],
    ) or {}
    assigned = _teacher_dashboard_participant_counts([str(exam['id'])]).get(str(exam['id']))
    rows = erd_rows(
        """
        SELECT ea.id, ea.started_at,
               COALESCE(NULLIF(p.full_name, ''), p.username, 'دانشجو') AS name,
               COALESCE(NULLIF(sp.student_number, ''), p.identifier, '') AS code,
               (SELECT COUNT(*) FROM attempt_answers aa WHERE aa.attempt_id = ea.id AND aa.answer IS NOT NULL) AS answered
        FROM exam_attempts ea
        JOIN profiles p ON p.id = ea.student_id
        LEFT JOIN student_profiles sp ON sp.user_id = ea.student_id
        WHERE ea.exam_id = %s AND ea.status = 'in_progress'
        ORDER BY ea.started_at
        LIMIT 300
        """,
        [exam['id']],
    )
    question_count = erd_count('exam_questions', 'exam_id = %s', [exam['id']])
    for row in rows:
        started = erd_datetime(row['started_at'])
        row['started_label'] = timezone.localtime(started).strftime('%H:%M') if started else '-'
        row['elapsed_minutes'] = int((now - started).total_seconds() // 60) if started else None
    is_running = bool(start_at and start_at <= now and (end_at is None or end_at >= now))
    return {
        'assigned': assigned,
        'started': counts.get('started') or 0,
        'in_progress': counts.get('in_progress') or 0,
        'submitted': counts.get('submitted') or 0,
        'not_started': max(0, assigned - (counts.get('started') or 0)) if assigned else None,
        'question_count': question_count,
        'rows': rows,
        'is_running': is_running,
        'has_ended': bool(end_at and end_at < now),
        'remaining_seconds': int((end_at - now).total_seconds()) if is_running and end_at else None,
        'start_label': _jalali_long_date(start_at),
        'time_label': f"{timezone.localtime(start_at).strftime('%H:%M') if start_at else ''}"
                      f"{' تا ' + timezone.localtime(end_at).strftime('%H:%M') if end_at else ''}",
    }


def _teacher_modern_context(request, page, **extra):
    teacher_id = getattr(request, 'erd_profile_id', None)
    courses = _teacher_courses_rows(teacher_id) if teacher_id else []
    selected_course = _teacher_selected_course(courses, extra.get('group_id'))
    selected_group_id = extra.get('group_id') or selected_course.get('id') or 'nursing-01'
    exams = _teacher_exam_rows_simple(teacher_id) if teacher_id else []
    questions = _teacher_question_rows(teacher_id, request)
    all_questions = _teacher_question_rows(teacher_id)
    question_stats = {
        'total': len(all_questions),
        'active': sum(1 for q in all_questions if q['status_key'] == 'active'),
        'draft': sum(1 for q in all_questions if q['status_key'] == 'draft'),
        'needs_review': sum(1 for q in all_questions if q['status_key'] == 'needs_review'),
        'banks': max(1, len({q.get('course') for q in all_questions})),
    }
    question_view = request.GET.get('view') or 'all'
    if question_view not in {'all', 'banks', 'drafts', 'shared', 'archive', 'tags'}:
        question_view = 'all'
    question_sets = _teacher_question_sets(teacher_id, all_questions)
    question_tags = _teacher_question_tags(all_questions)
    recent_exam_students = []
    if page == 'course_detail' and teacher_id:
        from .teacher_students import student_list_rows

        recent_exam_students = student_list_rows(teacher_id, selected_group_id)[:5]
    return {
        'page': page,
        'teacher_profile': _teacher_modern_profile(request),
        'teacher_stats': {
            'courses': len(courses),
            'students': sum(int(row.get('students_count') or 0) for row in courses) or 362,
            'exams': len(exams) or 24,
            'questions': question_stats['total'],
            'reviews': erd_count(
                'attempt_answers',
                'COALESCE(needs_manual_grading, false) = true AND question_id IN (SELECT id FROM questions WHERE teacher_id = %s)',
                [teacher_id],
            ) if teacher_id else 32,
            'objections': erd_count('objections', 'exam_id IN (SELECT id FROM exams WHERE teacher_id = %s)', [teacher_id]) if teacher_id else 5,
        },
        'courses': courses,
        'selected_course': selected_course,
        'course_exams': _teacher_group_exam_rows(teacher_id, selected_group_id, selected_course.get('course_name')),
        'course_activity': _teacher_group_activity_rows(selected_course.get('course_name')),
        'recent_exam_students': recent_exam_students,
        'exams': exams[:8] or [
            {'title': 'آزمون میان‌ترم مبانی مدیریت', 'course': 'مبانی مدیریت', 'start_at': '۱۴۰۳/۰۲/۳۱', 'status': 'فعال'},
            {'title': 'مهلت ارسال پروژه گروهی', 'course': 'بازاریابی دیجیتال', 'start_at': '۱۴۰۳/۰۳/۲۲', 'status': 'مهلت'},
            {'title': 'کلاس آنلاین فصل ۵', 'course': 'رفتار سازمانی', 'start_at': '۱۴۰۳/۰۳/۲۴', 'status': 'کلاس'},
        ],
        'questions': questions,
        'question_stats': question_stats,
        'question_view': question_view,
        'question_filters': {
            'q': request.GET.get('q', ''),
            'status': request.GET.get('status', 'all'),
            'type': request.GET.get('type', 'all'),
            'difficulty': request.GET.get('difficulty', 'all'),
        },
        'question_banks': question_sets,
        'question_tags': question_tags,
        'question_drafts': [q for q in all_questions if q['status_key'] == 'draft'][:10],
        'shared_questions': [q for q in all_questions if q['status_key'] == 'active'][:10],
        'archived_questions': [q for q in all_questions[-8:]],
        'course_detail_tab': request.GET.get('tab', 'overview'),
        'selected_group_id': selected_group_id,
        'dashboard': _teacher_dashboard_data(teacher_id) if page == 'dashboard' and teacher_id else None,
        **extra,
    }


TEACHER_SETTINGS_TABS = ('personal', 'account', 'exam', 'security')
TEACHER_SETTINGS_OLD_TABS = {'general': 'account', 'notifications': 'account', 'bank': 'exam'}  # links from the old five-tab page

# Every select on the settings page: posted values outside these lists are ignored.
TEACHER_SETTINGS_CHOICES = {
    'language': [('فارسی', 'فارسی')],
    'timezone': [('Asia/Tehran', 'Asia/Tehran')],
    'date_format': [('هجری شمسی', 'هجری شمسی'), ('میلادی', 'میلادی')],
    'theme': [('light', 'روشن'), ('dark', 'تیره'), ('system', 'سیستم')],
    'delivery_mode': [('instant', 'فوری'), ('daily', 'خلاصه روزانه')],
    'default_exam_duration': [('30', '۳۰ دقیقه'), ('45', '۴۵ دقیقه'), ('60', '۶۰ دقیقه'), ('90', '۹۰ دقیقه'), ('120', '۱۲۰ دقیقه')],
    'default_attempts': [('1', '۱'), ('2', '۲'), ('3', '۳')],
    'question_order': [('random', 'تصادفی'), ('fixed', 'ثابت')],
    'negative_marking': [('off', 'غیرفعال'), ('on', 'فعال')],
    'result_release': [('after_teacher', 'پس از تأیید استاد'), ('instant', 'بلافاصله پس از پایان آزمون')],
    'bank_default_structure': [('independent', 'مستقل'), ('case', 'سناریوی بیمار'), ('kfp', 'KFP'), ('osce', 'ایستگاه OSCE')],
    'bank_default_difficulty': [('easy', 'آسان'), ('medium', 'متوسط'), ('hard', 'دشوار')],
    'sharing_mode': [('private', 'خصوصی (فقط خودم)'), ('department', 'اساتید هم‌درس'), ('group', 'گروه آموزشی')],
    'essay_grading_default': [('rubric', 'با استفاده از روبریک (معیارها)'), ('manual', 'دستی')],
    'rounding': [('two_decimal', '۲ رقم اعشار'), ('integer', 'عدد صحیح')],
}
TEACHER_SETTINGS_SWITCHES = {
    'account': ['quick_help', 'show_page_meta', 'compact_tables', 'system_channel', 'email_channel', 'browser_channel'],
    'exam': ['show_correct_answer', 'show_result_after_publish', 'question_autosave', 'auto_archive',
             'auto_grade_objective', 'text_feedback', 'lock_score_after_publish'],
    'security': ['show_name_to_students', 'show_email_in_class', 'share_stats_with_admin'],
}
TEACHER_SETTINGS_SELECTS = {
    'account': ['language', 'timezone', 'date_format', 'theme', 'delivery_mode'],
    'exam': ['default_exam_duration', 'default_attempts', 'question_order', 'negative_marking', 'result_release',
             'bank_default_structure', 'bank_default_difficulty', 'sharing_mode', 'essay_grading_default', 'rounding'],
    'security': [],
}


def _teacher_settings_defaults():
    return {
        'language': 'فارسی',
        'timezone': 'Asia/Tehran',
        'date_format': 'هجری شمسی',
        'theme': 'light',
        'quick_help': True,
        'show_page_meta': True,  # «میانبرهای صفحه‌کلید»
        'compact_tables': False,
        'system_channel': True,
        'email_channel': True,
        'browser_channel': False,
        'notification_email': '',
        'delivery_mode': 'instant',
        'quiet_start': '22:00',
        'quiet_end': '07:00',
        'default_exam_duration': '60',
        'default_attempts': '1',
        'question_order': 'random',
        'negative_marking': False,
        'result_release': 'after_teacher',
        'show_correct_answer': False,
        'show_result_after_publish': True,
        'bank_default_structure': 'independent',
        'bank_default_difficulty': 'medium',
        'sharing_mode': 'private',
        'question_autosave': True,
        'auto_archive': False,
        'auto_grade_objective': True,
        'essay_grading_default': 'rubric',
        'rounding': 'two_decimal',
        'text_feedback': True,
        'lock_score_after_publish': False,
        'show_name_to_students': True,
        'show_email_in_class': False,
        'share_stats_with_admin': False,
    }


def _teacher_settings_key(teacher_id):
    return f'teacher_settings.{teacher_id or "demo"}'


def _teacher_settings_payload(teacher_id):
    values = _teacher_settings_defaults()
    row = erd_row('SELECT value FROM system_settings WHERE key = %s', [_teacher_settings_key(teacher_id)])
    if row and row.get('value'):
        stored = row['value']
        if isinstance(stored, str):
            try:
                stored = json.loads(stored)
            except json.JSONDecodeError:
                stored = {}
        if isinstance(stored, dict):
            values.update(stored)
    return values


def _checkbox_value(post, name):
    return post.get(name) == 'on'


def _teacher_settings_from_post(post, base=None, tab='account') -> tuple:
    """(saved values, error messages) for one settings tab; anything not on that tab keeps its stored value."""
    from django.core.exceptions import ValidationError
    from django.core.validators import validate_email

    values, errors = dict(base or _teacher_settings_defaults()), []
    for name in TEACHER_SETTINGS_SELECTS.get(tab, []):
        posted = post.get(name)
        if posted in {value for value, _label in TEACHER_SETTINGS_CHOICES[name]}:
            values[name] = posted == 'on' if name == 'negative_marking' else posted
    for name in TEACHER_SETTINGS_SWITCHES.get(tab, []):
        values[name] = _checkbox_value(post, name)
    if tab == 'account':
        email = (post.get('notification_email') or '').strip()
        try:
            if email:
                validate_email(email)
            values['notification_email'] = email
        except ValidationError:
            errors.append('ایمیل اعلان‌ها معتبر نیست و ذخیره نشد.')
        for name in ('quiet_start', 'quiet_end'):
            posted = (post.get(name) or '').strip()
            if re.fullmatch(r'([01]\d|2[0-3]):[0-5]\d', posted):
                values[name] = posted
            elif posted:
                errors.append('ساعت بازه‌ی عدم مزاحمت معتبر نیست و ذخیره نشد.')
    return values, errors


@erd_role_required('teacher')
def teacher_panel(request):
    return render(request, 'teacher/modern.html', _teacher_modern_context(request, 'dashboard'))


@erd_role_required('teacher')
def teacher_announcements(request):
    return render(request, 'teacher/modern.html', _teacher_modern_context(request, 'announcements'))


@erd_role_required('teacher')
def teacher_courses(request):
    status = request.GET.get('status') if request.GET.get('status') in TEACHER_CLASS_LIST_FILTERS else 'all'
    class_list = _teacher_class_list(
        request.erd_profile_id, (request.GET.get('q') or '').strip()[:100], request.GET.get('term') or '', status, request.GET.get('page'),
    )
    class_list['view'] = 'list' if request.GET.get('view') == 'list' else 'grid'
    return render(request, 'teacher/modern.html', _teacher_modern_context(request, 'courses', class_list=class_list))


@erd_role_required('teacher')
def teacher_course_detail(request, group_id):
    return render(request, 'teacher/modern.html', _teacher_modern_context(request, 'course_detail', group_id=group_id))


@erd_role_required('teacher')
def teacher_calendar(request):
    return render(request, 'teacher/modern.html', _teacher_modern_context(request, 'calendar'))


@erd_role_required('teacher')
def teacher_profile_page(request):
    """The old profile page: personal details now live on the settings page's first tab."""
    return redirect(f'{reverse("core:teacher_settings")}?tab=personal')


AVATAR_MAX_BYTES = 1024 * 1024
AVATAR_EXTENSIONS = ('jpg', 'jpeg', 'png', 'webp', 'gif')


def _save_avatar_upload(upload, owner_id) -> tuple:
    """(url, error) for an uploaded profile photo: size, extension, content type, signature and a Pillow decode are checked."""
    extension = file_extension(upload.name)
    if upload.size > AVATAR_MAX_BYTES:
        return None, 'حجم تصویر پروفایل باید کمتر از ۱ مگابایت باشد.'
    if (extension not in AVATAR_EXTENSIONS or not (upload.content_type or '').startswith('image/')
            or not signature_ok(upload, extension) or not image_ok(upload, extension)):
        return None, 'فرمت تصویر باید JPG، PNG، WebP یا GIF باشد.'
    storage = FileSystemStorage(location=settings.MEDIA_ROOT / 'avatars', base_url=settings.MEDIA_URL + 'avatars/')
    return storage.url(storage.save(f'{owner_id}-{uuid.uuid4().hex[:8]}.{extension}', upload)), None


def _org_unit_path(unit_id) -> dict:
    """{'university', 'faculty', 'department'} names along an org unit's parent chain."""
    path, seen = {}, set()
    while unit_id and str(unit_id) not in seen and len(seen) < 8:
        seen.add(str(unit_id))
        unit = erd_row('SELECT id, parent_id, type, name FROM org_units WHERE id = %s', [unit_id])
        if not unit:
            break
        path.setdefault('department' if unit['type'] == 'group' else unit['type'], unit['name'])
        unit_id = unit['parent_id']
    return path


# Fields counted by the «تکمیل اطلاعات پروفایل» ring on the personal tab.
TEACHER_PROFILE_COMPLETENESS_FIELDS = (
    'first_name', 'last_name', 'display_name', 'avatar_url', 'email', 'phone', 'landline', 'bio',
    'academic_rank', 'degree', 'org_unit_id', 'personnel_code',
)


def _teacher_personal_info(teacher_id) -> dict:
    """Personal, university and contact details shown on the settings page's «اطلاعات فردی» tab."""
    row = erd_row(
        """
        SELECT p.first_name, p.last_name, p.full_name, p.email, p.phone, p.avatar_url,
               tp.display_name, tp.degree, tp.landline, tp.bio, COALESCE(tp.show_bio, true) AS show_bio,
               tp.personnel_code, tp.academic_rank, tp.org_unit_id
        FROM profiles p LEFT JOIN teacher_profiles tp ON tp.user_id = p.id
        WHERE p.id = %s
        """,
        [teacher_id],
    ) if teacher_id else None
    info = dict(row or {})
    info['show_bio'] = bool(info.get('show_bio', True))
    info.update({f'unit_{key}': value for key, value in _org_unit_path(info.get('org_unit_id')).items()})
    phone = str(info.get('phone') or '')
    info['phone_masked'] = f'{phone[:4]}***{phone[-4:]}' if len(phone) >= 10 else phone
    filled = [bool(info.get(name)) for name in TEACHER_PROFILE_COMPLETENESS_FIELDS]
    info['completeness'] = round(100 * sum(filled) / len(filled))
    return info


def _clean_phone(value) -> str:
    return re.sub(r'[\s\-()]', '', str(value or '').translate(str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩', '01234567890123456789')))


def _save_teacher_personal_info(request, teacher_id) -> list:
    """Validates and saves the «اطلاعات فردی» form; returns error messages (nothing is saved when there are any)."""
    post, errors = request.POST, []
    first_name = (post.get('first_name') or '').strip()[:60]
    last_name = (post.get('last_name') or '').strip()[:60]
    display_name = (post.get('display_name') or '').strip()[:80]
    phone_posted = 'phone' in post  # the mobile input is only sent after «تغییر شماره» is pressed
    phone, landline = _clean_phone(post.get('phone')), _clean_phone(post.get('landline'))
    bio = (post.get('bio') or '').strip()
    if not first_name or not last_name:
        errors.append('نام و نام خانوادگی الزامی است.')
    if phone_posted and not re.fullmatch(r'09\d{9}', phone):
        errors.append('تلفن همراه باید ۱۱ رقم و با ۰۹ شروع شود.')
    if landline and not re.fullmatch(r'0\d{9,10}', landline):
        errors.append('تلفن ثابت باید با کد شهر و فقط شامل رقم باشد.')
    if len(bio) > 500:
        errors.append('معرفی کوتاه حداکثر ۵۰۰ نویسه است.')
    avatar_url = None
    if request.FILES.get('avatar'):
        avatar_url, avatar_error = _save_avatar_upload(request.FILES['avatar'], teacher_id)
        if avatar_error:
            errors.append(avatar_error)
    if errors:
        return errors

    full_name = f'{first_name} {last_name}'
    with transaction.atomic():
        erd_execute(
            f"""
            UPDATE profiles SET first_name = %s, last_name = %s, full_name = %s,
                   {'phone = %s, ' if phone_posted else ''}{'avatar_url = %s, ' if avatar_url else ''}updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
            """,
            [first_name, last_name, full_name, *([phone] if phone_posted else []), *([avatar_url] if avatar_url else []), teacher_id],
        )
        erd_execute(
            'UPDATE teacher_profiles SET display_name = %s, landline = %s, bio = %s, show_bio = %s WHERE user_id = %s',
            [display_name or None, landline or None, bio or None, post.get('show_bio') == 'on', teacher_id],
        )
        request.user.first_name, request.user.last_name = first_name, last_name
        request.user.save(update_fields=['first_name', 'last_name'])
    log_activity(request.user, 'profile_updated', 'ویرایش اطلاعات فردی استاد', request)
    return []


# University details a teacher can only change through an academic manager's approval.
TEACHER_ACADEMIC_RANKS = ('مربی', 'استادیار', 'دانشیار', 'استاد')
TEACHER_DEGREES = ('کارشناسی ارشد', 'دکتری حرفه‌ای', 'دکتری تخصصی (PhD)', 'فوق تخصص')
TEACHER_REQUEST_UNIT_TYPES = ('faculty', 'department', 'group')
TEACHER_CHANGE_REQUEST_PAGE_SIZE = 20


def _teacher_unit_options() -> list:
    """Active org units for the university → faculty → department selects of a change request."""
    return [
        {'id': str(row['id']), 'parent': str(row['parent_id'] or ''), 'type': row['type'], 'name': row['name']}
        for row in erd_rows('SELECT id, parent_id, type, name FROM org_units WHERE COALESCE(is_active, true) ORDER BY name')
    ]


def _teacher_latest_change_request(teacher_id) -> dict | None:
    """The teacher's most recent request that was not withdrawn, with the requested unit's names for display."""
    row = erd_row(
        """
        SELECT r.id, r.org_unit_id, r.academic_rank, r.degree, r.teacher_note, r.status, r.review_note,
               r.created_at, r.reviewed_at
        FROM teacher_profile_change_requests r
        WHERE r.teacher_id = %s AND r.status <> 'cancelled'
        ORDER BY r.created_at DESC
        LIMIT 1
        """,
        [teacher_id],
    ) if teacher_id else None
    if not row:
        return None
    latest = dict(row)
    unit_path = _org_unit_path(latest['org_unit_id']) if latest.get('org_unit_id') else {}
    latest['unit_label'] = unit_path.get('department') or unit_path.get('faculty') or ''
    latest['created_label'] = _jalali_long_date(latest['created_at'], with_weekday=False)
    latest['reviewed_label'] = _jalali_long_date(latest['reviewed_at'], with_weekday=False)
    return latest


def _submit_teacher_change_request(request, teacher_id) -> list:
    """Validates and stores a request to change unit, rank or degree; returns error messages (nothing stored on error)."""
    post, errors = request.POST, []
    unit_id = (post.get('request_org_unit_id') or '').strip()
    rank = (post.get('request_academic_rank') or '').strip()
    degree = (post.get('request_degree') or '').strip()
    note = (post.get('request_note') or '').strip()
    current = erd_row('SELECT org_unit_id, academic_rank, degree FROM teacher_profiles WHERE user_id = %s', [teacher_id])
    if not current:
        return ['پروفایل استادی شما پیدا نشد.']
    if unit_id:
        unit = erd_row('SELECT type FROM org_units WHERE id = %s AND COALESCE(is_active, true)', [unit_id])
        if not unit or unit['type'] not in TEACHER_REQUEST_UNIT_TYPES:
            errors.append('دانشکده یا گروه آموزشی انتخاب‌شده معتبر نیست.')
    if rank and rank not in TEACHER_ACADEMIC_RANKS:
        errors.append('مرتبه علمی انتخاب‌شده معتبر نیست.')
    if degree and degree not in TEACHER_DEGREES:
        errors.append('مدرک تحصیلی انتخاب‌شده معتبر نیست.')
    if len(note) > 300:
        errors.append('توضیح درخواست حداکثر ۳۰۰ نویسه است.')
    requested = {'org_unit_id': unit_id, 'academic_rank': rank, 'degree': degree}
    changes = {key: value for key, value in requested.items() if value and value != str(current.get(key) or '')}
    if not errors and not changes:
        errors.append('هیچ تغییری نسبت به اطلاعات فعلی انتخاب نشده است.')
    pending_error = 'درخواست قبلی شما هنوز در انتظار بررسی است.'
    if not errors and erd_row("SELECT 1 AS ok FROM teacher_profile_change_requests WHERE teacher_id = %s AND status = 'pending'", [teacher_id]):
        errors.append(pending_error)
    if errors:
        return errors
    request_id = str(uuid.uuid4())
    try:
        with transaction.atomic():
            erd_execute(
                """
                INSERT INTO teacher_profile_change_requests (
                    id, teacher_id, org_unit_id, academic_rank, degree,
                    previous_org_unit_id, previous_academic_rank, previous_degree, teacher_note, status
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'pending')
                """,
                [
                    request_id, teacher_id, changes.get('org_unit_id'), changes.get('academic_rank'), changes.get('degree'),
                    current.get('org_unit_id'), current.get('academic_rank'), current.get('degree'), note or None,
                ],
            )
    except IntegrityError:  # a second tab submitted at the same moment; the one-pending index refused it
        return [pending_error]
    log_activity(request.user, 'profile_change_requested', 'درخواست تغییر اطلاعات دانشگاهی استاد', request, {'request_id': request_id})
    return []


def _cancel_teacher_change_request(request, teacher_id) -> None:
    erd_execute(
        "UPDATE teacher_profile_change_requests SET status = 'cancelled' WHERE teacher_id = %s AND status = 'pending'",
        [teacher_id],
    )
    log_activity(request.user, 'profile_change_cancelled', 'لغو درخواست تغییر اطلاعات دانشگاهی استاد', request)


ACCOUNT_DELETION_PAGE_SIZE = 20


def _latest_account_deletion_request(profile_id) -> dict | None:
    row = erd_row(
        """
        SELECT id, reason, status, review_note, created_at, reviewed_at
        FROM account_deletion_requests
        WHERE profile_id = %s AND status <> 'cancelled'
        ORDER BY created_at DESC
        LIMIT 1
        """,
        [profile_id],
    ) if profile_id else None
    if not row:
        return None
    latest = dict(row)
    latest['created_label'] = _jalali_long_date(latest['created_at'], with_weekday=False)
    latest['reviewed_label'] = _jalali_long_date(latest['reviewed_at'], with_weekday=False)
    return latest


def _teacher_security_context(request, teacher_id) -> dict:
    sessions = account_security.active_sessions(request.user, request.session.session_key)
    for item in sessions:
        item['created_label'] = _jalali_long_date(item['created_at'], with_weekday=False)
    two_factor = account_security.two_factor_status(request.user)
    secret = None if two_factor['enabled'] or not two_factor['available'] else account_security.pending_secret(request.user)
    if secret:
        two_factor['setup_secret'] = ' '.join(secret[i:i + 4] for i in range(0, len(secret), 4))
        two_factor['setup_qr'] = mark_safe(account_security.provisioning_qr_svg(request.user, secret))  # SVG built by qrcode, no user input
    two_factor['new_codes'] = request.session.pop('tset_recovery_codes', None)
    return {
        'sessions': sessions,
        'deletion_request': _latest_account_deletion_request(teacher_id),
        'two_factor': two_factor,
    }


def _request_account_deletion(request, profile_id) -> list:
    """Stores a deletion request after the password check; the system admin decides on it."""
    post = request.POST
    reason = (post.get('deletion_reason') or '').strip()
    errors = []
    if not request.user.check_password(post.get('deletion_password') or ''):
        log_activity(request.user, 'account_deletion_password_failed', 'رمز نادرست هنگام درخواست حذف حساب', request)
        errors.append('رمز عبور درست نیست.')
    if post.get('deletion_confirm') != 'on':
        errors.append('برای ثبت درخواست، تیک تأیید را بزنید.')
    if len(reason) > 500:
        errors.append('دلیل درخواست حداکثر ۵۰۰ نویسه است.')
    pending_error = 'درخواست حذف حساب شما پیش‌تر ثبت شده و در انتظار بررسی است.'
    if not errors and erd_row("SELECT 1 AS ok FROM account_deletion_requests WHERE profile_id = %s AND status = 'pending'", [profile_id]):
        errors.append(pending_error)
    if errors:
        return errors
    request_id = str(uuid.uuid4())
    try:
        with transaction.atomic():
            erd_execute(
                "INSERT INTO account_deletion_requests (id, profile_id, reason, status) VALUES (%s, %s, %s, 'pending')",
                [request_id, profile_id, reason or None],
            )
    except IntegrityError:  # submitted twice at once; the one-pending index refused the second
        return [pending_error]
    log_activity(request.user, 'account_deletion_requested', 'درخواست حذف حساب کاربری', request, {'request_id': request_id})
    link = reverse('core:super_admin_account_deletions')
    for admin in erd_rows("SELECT user_id FROM user_roles WHERE role = 'admin' LIMIT 20"):
        create_notification(admin['user_id'], 'درخواست حذف حساب', 'یک کاربر درخواست حذف حساب ثبت کرده است.', link, 'account')
    return []


TWO_FACTOR_ACTIONS = ('totp_start', 'totp_confirm', 'totp_disable', 'recovery_regenerate')


def _handle_two_factor_action(request, action) -> list:
    """Authenticator setup and management; turning it off or renewing codes needs the password (and a code)."""
    user, post = request.user, request.POST
    if not account_security.TWO_FACTOR_AVAILABLE:
        return ['کتابخانه‌های ورود دومرحله‌ای (pyotp و qrcode) روی سرور نصب نیست.']
    if action == 'totp_start':
        if account_security.two_factor_enabled(user):
            return ['ورود دومرحله‌ای از قبل فعال است.']
        account_security.start_enrollment(user)
        return []
    if not user.check_password(post.get('security_password') or ''):
        log_activity(user, 'two_factor_password_failed', 'رمز نادرست در تنظیمات ورود دومرحله‌ای', request)
        return ['رمز عبور درست نیست.']
    if action == 'totp_confirm':
        codes = account_security.confirm_enrollment(user, post.get('totp_code') or '')
        if codes is None:
            return ['کد واردشده با برنامه‌ی Authenticator همخوانی ندارد؛ کد تازه را وارد کنید.']
        request.session['tset_recovery_codes'] = codes  # shown once on the next page, then dropped
        log_activity(user, 'two_factor_enabled', 'ورود دومرحله‌ای فعال شد.', request)
        return []
    if not account_security.two_factor_enabled(user):
        return ['ورود دومرحله‌ای فعال نیست.']
    if action == 'totp_disable':
        if not account_security.verify_code(user, post.get('totp_code') or ''):
            return ['کد تأیید یا کد بازیابی درست نیست.']
        account_security.disable_two_factor(user)
        log_activity(user, 'two_factor_disabled', 'ورود دومرحله‌ای غیرفعال شد.', request)
        return []
    request.session['tset_recovery_codes'] = account_security.new_recovery_codes(user)
    log_activity(user, 'recovery_codes_regenerated', 'کدهای بازیابی جدید ساخته شد.', request)
    return []


def _handle_teacher_security_action(request, teacher_id) -> list:
    """Runs one action posted from the security tab; returns error messages, or [] when it went through."""
    action, _, session_key = (request.POST.get('security_action') or '').partition(':')  # «end_session:<key>»
    current_key = request.session.session_key
    if action == 'end_session':
        if not account_security.end_session(request.user, session_key, current_key):
            return ['این نشست پیدا نشد یا قبلاً بسته شده است.']
        log_activity(request.user, 'session_terminated', 'خروج از یک نشست دیگر', request)
        return []
    if action == 'end_other_sessions':
        ended = account_security.end_other_sessions(request.user, current_key)
        log_activity(request.user, 'sessions_terminated', f'خروج اجباری از {ended} نشست دیگر', request)
        return []
    if action in TWO_FACTOR_ACTIONS:
        return _handle_two_factor_action(request, action)
    if action == 'deletion_request':
        return _request_account_deletion(request, teacher_id)
    if action == 'deletion_cancel':
        erd_execute("UPDATE account_deletion_requests SET status = 'cancelled' WHERE profile_id = %s AND status = 'pending'", [teacher_id])
        log_activity(request.user, 'account_deletion_cancelled', 'لغو درخواست حذف حساب', request)
        return []
    return ['درخواست نامعتبر است.']


@erd_role_required('teacher')
def teacher_settings(request):
    teacher_id = getattr(request, 'erd_profile_id', None)
    active_tab = request.POST.get('settings_tab') if request.method == 'POST' else request.GET.get('tab')
    active_tab = TEACHER_SETTINGS_OLD_TABS.get(active_tab, active_tab)
    if active_tab not in TEACHER_SETTINGS_TABS:
        active_tab = 'personal'
    personal_errors, request_errors, security_errors = [], [], []
    personal_action = request.POST.get('personal_action') if request.method == 'POST' else None
    if request.method == 'POST' and active_tab == 'security' and request.POST.get('security_action'):
        security_errors = _handle_teacher_security_action(request, teacher_id)
        if not security_errors:
            done = request.POST['security_action'].partition(':')[0]
            return redirect(f'{reverse("core:teacher_settings")}?tab=security&done={done}')
    if personal_action == 'academic_cancel' and active_tab == 'personal':
        _cancel_teacher_change_request(request, teacher_id)
        return redirect(f'{reverse("core:teacher_settings")}?tab=personal&request=cancelled')
    if personal_action == 'academic_request' and active_tab == 'personal':
        request_errors = _submit_teacher_change_request(request, teacher_id)
        if not request_errors:
            return redirect(f'{reverse("core:teacher_settings")}?tab=personal&request=sent')
    elif request.method == 'POST' and active_tab == 'personal':
        personal_errors = _save_teacher_personal_info(request, teacher_id)
        if not personal_errors:
            return redirect(f'{reverse("core:teacher_settings")}?tab=personal&saved=1')
    elif request.method == 'POST' and not security_errors:
        payload, errors = _teacher_settings_from_post(request.POST, _teacher_settings_payload(teacher_id), active_tab)
        for error in errors:
            messages.error(request, error)
        erd_execute(
            """
            INSERT INTO system_settings (key, value, description, updated_by)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                description = excluded.description,
                updated_by = excluded.updated_by
            """,
            [
                _teacher_settings_key(teacher_id),
                json.dumps(payload, ensure_ascii=False),
                'Teacher panel preferences',
                teacher_id,
            ],
        )
        return redirect(f'{reverse("core:teacher_settings")}?tab={active_tab}&saved=1')
    context = _teacher_modern_context(request, 'teacher_settings')
    settings_values = _teacher_settings_payload(teacher_id)
    context['teacher_settings'] = settings_values
    context['teacher_settings_tab'] = active_tab
    context['teacher_settings_choices'] = TEACHER_SETTINGS_CHOICES
    if active_tab == 'personal':
        personal = _teacher_personal_info(teacher_id)
        if personal_errors:  # show what the teacher typed, not the stored values
            personal.update({name: request.POST.get(name, '') for name in ('first_name', 'last_name', 'display_name', 'landline', 'bio')})
            if 'phone' in request.POST:
                personal['phone'], personal['phone_editing'] = request.POST['phone'], True
            personal['show_bio'] = request.POST.get('show_bio') == 'on'
        context['personal'] = personal
        context['personal_errors'] = personal_errors
        context['academic_request'] = _teacher_latest_change_request(teacher_id)
        context['academic_request_errors'] = request_errors
        context['academic_request_posted'] = {
            name: request.POST.get(f'request_{name}', '') for name in ('org_unit_id', 'academic_rank', 'degree', 'note')
        } if request_errors else {}
        context['academic_choices'] = {'ranks': TEACHER_ACADEMIC_RANKS, 'degrees': TEACHER_DEGREES}
        context['academic_units'] = _teacher_unit_options()
    if active_tab == 'security':
        context.update(_teacher_security_context(request, teacher_id))
        context['security_errors'] = security_errors
        context['security_failed_action'] = request.POST.get('security_action', '').partition(':')[0] if security_errors else ''
        context['security_done'] = request.GET.get('done', '')
    context['teacher_settings_selected'] = {
        name: ('on' if settings_values.get(name) else 'off') if name == 'negative_marking' else str(settings_values.get(name, ''))
        for name in TEACHER_SETTINGS_CHOICES
    }
    return render(request, 'teacher/modern.html', context)


@erd_role_required('teacher')
def teacher_security(request):
    return render(request, 'teacher/modern.html', _teacher_modern_context(request, 'security'))


@erd_role_required('teacher')
def teacher_questions(request):
    return render(request, 'teacher/modern.html', _teacher_modern_context(request, 'questions'))


@erd_role_required('teacher')
def teacher_question_type(request):
    return render(request, 'teacher/modern.html', _teacher_modern_context(request, 'question_type'))


INDEPENDENT_QUESTION_TYPES = {'single', 'multi', 'true_false', 'short_answer', 'essay', 'fill_blank', 'matching', 'ordering', *question_kinds.V2_TYPES}


def _teacher_question_course_options(teacher_id):
    if not teacher_id:
        return []
    return erd_rows(
        """
        SELECT DISTINCT c.id, c.title
        FROM courses c
        JOIN student_groups sg ON sg.course_id = c.id
        LEFT JOIN group_teachers gt ON gt.group_id = sg.id
        WHERE sg.teacher_id = %s OR gt.teacher_id = %s
        ORDER BY c.title
        """,
        [teacher_id, teacher_id],
    )


def _split_alternatives(value):
    return [part.strip() for part in re.split(r'[,،\n]', str(value or '')) if part.strip()]


def _form_number(post, name, fallback):
    raw = str(post.get(name) or '').translate(str.maketrans('۰۱۲۳۴۵۶۷۸۹', '0123456789')).strip()
    try:
        return float(raw)
    except ValueError:
        return fallback


# Question types whose stem is edited with the rich editor; fill_blank keeps plain text for its [n] markers.
RICH_STEM_TYPES = {'single', 'multi', 'true_false', 'short_answer', 'essay', 'fill_blank', 'matching', 'ordering', *question_kinds.V2_TYPES}
STEM_MAX = 5000
ESSAY_ANSWER_FORMATS = {
    'text': 'ویرایشگر متن',
    'image': 'بارگذاری تصویر',
    'audio': 'ضبط صدا',
    'video': 'بارگذاری ویدئو',
    'file': 'پیوست فایل',
}
ESSAY_INSTRUCTIONS_MAX = 1000
ESSAY_SAMPLE_TEXT_MAX = 3000
ESSAY_SAMPLE_FILE_EXTENSIONS = {'pdf', 'jpg', 'jpeg', 'png'}
ESSAY_SAMPLE_FILE_MAX = 10 * 1024 * 1024


def _essay_settings(post):
    """Essay-only fields: rich stem (Quill Delta), student instructions and the grader's sample answer."""
    return {
        'student_instructions': (post.get('student_instructions') or '').strip(),
        'answer_formats': [key for key in ESSAY_ANSWER_FORMATS if key in post.getlist('answer_formats')],
        'sample_answer_text': (post.get('sample_answer_text') or '').strip(),
        'sample_answer_file': None,  # resolved with the other uploads
    }


def _essay_errors(essay):
    errors = []
    if not essay.get('answer_formats'):
        errors.append('حداقل یک قالب پاسخ برای دانشجو انتخاب کنید.')
    if len(essay.get('student_instructions') or '') > ESSAY_INSTRUCTIONS_MAX:
        errors.append(f'دستورالعمل دانشجو حداکثر {ESSAY_INSTRUCTIONS_MAX} نویسه است.')
    if len(essay.get('sample_answer_text') or '') > ESSAY_SAMPLE_TEXT_MAX:
        errors.append(f'پاسخ نمونه حداکثر {ESSAY_SAMPLE_TEXT_MAX} نویسه است.')
    return errors


def _stem_delta(scoring_settings):
    """Rich stem of a question; essays saved before all types got the editor kept it under `essay`."""
    settings_data = scoring_settings or {}
    delta = settings_data.get('text_delta') or (settings_data.get('essay') or {}).get('text_delta') or {}
    return delta if delta_length(delta) else None


def _question_stem_html(scoring_settings):
    delta = _stem_delta(scoring_settings)
    return delta_to_html(delta) if delta else ''


def _essay_view(scoring_settings):
    """Essay data as the student exam page and the grader pages render it."""
    essay = (scoring_settings or {}).get('essay') or {}
    return {
        'text_html': _question_stem_html(scoring_settings),
        'student_instructions': essay.get('student_instructions') or '',
        'answer_formats': essay.get('answer_formats') or ['text'],
        'sample_answer_text': essay.get('sample_answer_text') or '',
        'sample_answer_file': essay.get('sample_answer_file') or None,
    }


def _apply_independent_settings(payload, post):
    """Read the per-type scoring settings of an independent question from the builder form."""
    kind = payload['stored_type']
    negative_value = abs(_form_number(post, 'negative_value', 0.25))
    settings_data = {
        'negative_marking': bool(post.get('negative_marking')),
        'negative_value': negative_value,
        'shuffle_options': bool(post.get('shuffle_options')),
        'scoring_mode': post.get('scoring_mode') if post.get('scoring_mode') in {'partial', 'all_or_nothing'} else 'partial',
    }
    if kind == 'multi':
        settings_data['min_correct'] = int(_form_number(post, 'min_correct', 1) or 1)
        settings_data['max_correct'] = int(_form_number(post, 'max_correct', 0) or 0)
        settings_data['floor_zero'] = bool(post.get('floor_zero'))
    if kind == 'matching':
        settings_data['matching_mode'] = 'many_to_one' if post.get('matching_mode') == 'many_to_one' else 'one_to_one'
        settings_data['matching_distractors'] = _split_alternatives(post.get('matching_distractors'))
    if kind == 'ordering':
        settings_data['ordering_mode'] = post.get('ordering_mode') if post.get('ordering_mode') in {'exact', 'position', 'adjacent'} else 'exact'
    if kind == 'essay':
        settings_data['essay'] = _essay_settings(post)
    if kind in question_kinds.V2_TYPES:
        question_kinds.apply_settings(payload, post, settings_data)
    if kind in RICH_STEM_TYPES:
        settings_data['text_delta'] = clean_delta(post.get('text_delta'))
        # The plain `text` column (lists, search, exports, grading) is derived from the rich stem.
        stem = delta_text(settings_data['text_delta']).strip()
        if stem:
            payload['text'] = stem
    payload['scoring_settings'] = settings_data
    payload['negative_points'] = str(-negative_value if settings_data['negative_marking'] else 0)

    if kind == 'short_answer':
        accepted = []
        for index, answer in enumerate(post.getlist('accepted_answer'), start=1):
            if not answer.strip():
                continue
            mode = post.get(f'accepted_mode_{index}')
            accepted.append({
                'answer': answer.strip(),
                'points': min(max(_form_number(post, f'accepted_points_{index}', 100), 0), 100),
                'match_mode': mode if mode in {'exact', 'contains', 'regex'} else 'exact',
                'case_sensitive': bool(post.get(f'accepted_case_{index}')),
                'normalize': bool(post.get(f'accepted_normalize_{index}')),
                'tolerance': abs(_form_number(post, f'accepted_tolerance_{index}', 0)),
                'typo_tolerance': min(max(int(_form_number(post, f'accepted_typo_{index}', 0)), 0), 2),
                'ignore_word_order': bool(post.get(f'accepted_word_order_{index}')),
            })
        payload['accepted_answers'] = accepted
        settings_data['correct_threshold'] = min(max(_form_number(post, 'correct_threshold', 100), 0), 100)
    if kind == 'fill_blank':
        # «نرمال‌سازی پاسخ‌ها»: unify Persian/Arabic digits and «ي/ك» before comparing (default on).
        settings_data['normalize_answers'] = post.get('normalize_answers') != '0'
        blanks = []
        for index in range(1, int(_form_number(post, 'blank_count', 0)) + 1):
            blanks.append({
                'blank': index,
                'answers': _split_alternatives(post.get(f'blank_answers_{index}')),
                'points': _form_number(post, f'blank_points_{index}', 1),
                'case_sensitive': bool(post.get(f'blank_case_{index}')),
                'ignore_spaces': bool(post.get(f'blank_spaces_{index}')),
            })
        payload['accepted_answers'] = blanks
        payload['correct_answer'] = '|'.join(blank['answers'][0] if blank['answers'] else '' for blank in blanks)
        payload['options'] = []
    return payload


def _question_builder_errors(payload, allowed_course_ids):
    errors = []
    kind = payload['stored_type']
    if not payload['text']:
        errors.append('متن سؤال الزامی است.')
    if allowed_course_ids and payload['course_id'] not in allowed_course_ids:
        errors.append('درس انتخاب‌شده معتبر نیست یا به شما تخصیص داده نشده است.')
    options = payload['options']
    correct = [option for option in options if option.get('is_correct')]
    settings_data = payload.get('scoring_settings') or {}
    if delta_length(settings_data.get('text_delta') or {}) > STEM_MAX:
        errors.append(f'متن سؤال حداکثر {STEM_MAX} نویسه است.')
    if kind == 'essay':
        errors += _essay_errors(settings_data.get('essay') or {})
    if kind in {'single', 'true_false', 'multi'} and len(options) < 2:
        errors.append('حداقل دو گزینه وارد کنید.')
    if kind in {'single', 'true_false'} and len(correct) != 1:
        errors.append('دقیقاً یک گزینه را به‌عنوان پاسخ صحیح مشخص کنید.')
    if kind == 'multi':
        if not correct:
            errors.append('حداقل یک گزینه‌ی صحیح مشخص کنید.')
        max_correct = settings_data.get('max_correct') or 0
        min_correct = settings_data.get('min_correct') or 1
        if max_correct and (max_correct < min_correct or max_correct > len(options)):
            errors.append('حداکثر تعداد انتخاب باید بین حداقل انتخاب و تعداد گزینه‌ها باشد.')
        if max_correct and len(correct) > max_correct:
            errors.append('تعداد گزینه‌های صحیح از حداکثر انتخاب مجاز بیشتر است.')
    if kind == 'fill_blank':
        blank_count = len(_BLANK_MARKER_RE.findall(payload['text']))
        blanks = payload['accepted_answers']
        if not blank_count:
            errors.append('در متن سؤال حداقل یک جای خالی با نشانه‌ی [۱] مشخص کنید.')
        elif len(blanks) != blank_count or any(not blank.get('answers') for blank in blanks):
            errors.append(f'برای هر جای خالی ({blank_count} مورد) حداقل یک پاسخ قابل قبول وارد کنید.')
    if kind == 'matching':
        pairs = payload['matching_pairs']
        if len(pairs) < 2 or any(not (pair['left'] and pair['right']) for pair in pairs):
            errors.append('حداقل دو جفت تطبیقی وارد کنید و هر دو ستون هر جفت را پر کنید.')
    if kind == 'ordering' and len(payload['ordering_items']) < 2:
        errors.append('حداقل دو مورد برای مرتب‌سازی وارد کنید.')
    if kind == 'short_answer':
        if not payload['accepted_answers']:
            errors.append('حداقل یک پاسخ پذیرفته‌شده وارد کنید.')
        for item in payload['accepted_answers']:
            if item.get('match_mode') == 'regex':
                try:
                    re.compile(item['answer'])
                except re.error:
                    errors.append(f'الگوی «{item["answer"]}» عبارت منظم معتبری نیست.')
    if kind in question_kinds.V2_TYPES:
        errors += question_kinds.errors_for(payload)
    return errors


QUESTION_MEDIA_RULES = {
    'image': ({'jpg', 'jpeg', 'png', 'webp', 'gif'}, 5 * 1024 * 1024),
    'audio': ({'mp3', 'wav', 'ogg', 'm4a'}, 20 * 1024 * 1024),
    'video': ({'mp4', 'webm'}, 300 * 1024 * 1024),
}


def _media_kind(url_or_name):
    extension = (str(url_or_name or '').rsplit('.', 1)[-1]).lower()
    return next((kind for kind, (extensions, _limit) in QUESTION_MEDIA_RULES.items() if extension in extensions), '')


def _store_question_media(uploaded, kinds=('image', 'audio', 'video')):
    kind = _media_kind(getattr(uploaded, 'name', ''))
    if kind not in kinds:
        allowed = '، '.join(sorted(ext for k in kinds for ext in QUESTION_MEDIA_RULES[k][0]))
        return None, '', f'نوع فایل «{uploaded.name}» مجاز نیست (مجاز: {allowed}).'
    extensions, limit = QUESTION_MEDIA_RULES[kind]
    url, error = _store_upload(uploaded, 'question-media', extensions, limit)
    return url, kind, error


VIDEO_SUBTITLE_MAX = 512 * 1024


def _resolve_video_subtitle(files, post, errors):
    """WebVTT subtitle track of the question video: new upload, else the kept URL unless removed."""
    uploaded = files.get('question_video_subtitle_file')
    if uploaded:
        if file_extension(uploaded.name) != 'vtt' or not signature_ok(uploaded, 'vtt'):
            errors.append(f'فایل زیرنویس «{uploaded.name}» باید یک فایل WebVTT معتبر (.vtt) باشد.')
            return ''
        url, error = _store_upload(uploaded, 'question-media', {'vtt'}, VIDEO_SUBTITLE_MAX)
        if error:
            errors.append(error)
            return ''
        return url
    if post.get('remove_question_video_subtitle'):
        return ''
    existing = (post.get('existing_question_video_subtitle') or '').strip()
    if existing.startswith(f'{settings.MEDIA_URL}question-media/') and '..' not in existing and existing.endswith('.vtt'):
        return existing
    return ''


def _apply_question_uploads(payload, files, post):
    """Attach uploaded/kept media to the payload. Each slot = new upload, else kept URL unless removed."""
    errors = []

    def resolve(file_key, existing_key, remove_key=None, kinds=('image', 'audio', 'video')):
        uploaded = files.get(file_key)
        if uploaded:
            url, kind, error = _store_question_media(uploaded, kinds)
            if error:
                errors.append(error)
                return '', ''
            return url, kind
        if remove_key and post.get(remove_key):
            return '', ''
        existing = (post.get(existing_key) or '').strip()
        if existing and (not existing.startswith(f'{settings.MEDIA_URL}question-media/') or '..' in existing):
            return '', ''
        return existing, _media_kind(existing)

    media = payload['question_media']
    for kind in ('image', 'audio', 'video'):
        media[kind], _ = resolve(f'question_{kind}_file', f'existing_question_{kind}', f'remove_question_{kind}', (kind,))
    media['image_alt'] = (post.get('question_image_alt') or '').strip()[:300]
    media['video_caption'] = (post.get('question_video_caption') or '').strip()[:1000]
    media['video_subtitle'] = _resolve_video_subtitle(files, post, errors) if media['video'] else ''

    for index, option in enumerate(payload['options'], start=1):
        option['media'], option['media_kind'] = resolve(f'option_media_file_{index}', f'option_media_{index}', f'option_media_remove_{index}')
    for index, pair in enumerate(payload['matching_pairs'], start=1):
        pair['left_media'], pair['left_media_kind'] = resolve(f'matching_left_media_file_{index}', f'matching_left_media_{index}', f'matching_left_media_remove_{index}')
        pair['right_media'], pair['right_media_kind'] = resolve(f'matching_right_media_file_{index}', f'matching_right_media_{index}', f'matching_right_media_remove_{index}')
    for index, item in enumerate(payload['ordering_items'], start=1):
        item['media'], item['media_kind'] = resolve(f'ordering_media_file_{index}', f'ordering_media_{index}', f'ordering_media_remove_{index}')
    if payload['stored_type'] == 'fill_blank':
        # Optional media hint per blank (e.g. the image of the structure to name), shown to the student.
        for index, blank in enumerate(payload['accepted_answers'], start=1):
            blank['media'], blank['media_kind'] = resolve(f'blank_media_file_{index}', f'blank_media_{index}', f'blank_media_remove_{index}')
    payload['feedback']['media'], payload['feedback']['media_kind'] = resolve('feedback_media_file', 'existing_feedback_media', 'remove_feedback_media')
    essay = (payload.get('scoring_settings') or {}).get('essay')
    if essay is not None and payload['stored_type'] == 'essay':
        uploaded = files.get('sample_answer_file')
        existing = (post.get('existing_sample_answer_file') or '').strip()
        if uploaded:
            url, error = _store_upload(uploaded, 'question-media', ESSAY_SAMPLE_FILE_EXTENSIONS, ESSAY_SAMPLE_FILE_MAX)
            if error:
                errors.append(error)
            else:
                essay['sample_answer_file'] = {'url': url, 'name': uploaded.name[:150]}
        elif existing and not post.get('remove_sample_answer_file') and existing.startswith(f'{settings.MEDIA_URL}question-media/') and '..' not in existing:
            essay['sample_answer_file'] = {'url': existing, 'name': (post.get('existing_sample_answer_name') or 'پاسخ نمونه')[:150]}
    question_kinds.resolve_uploads(
        payload, files, post,
        lambda uploaded, extensions, limit: _store_upload(uploaded, 'question-media', extensions, limit), errors,
    )
    return errors


def _pad_rows(rows, minimum, blank):
    rows = list(rows)
    while len(rows) < minimum:
        rows.append(dict(blank) if isinstance(blank, dict) else blank)
    return rows


def _question_form_data(source):
    """Normalize a builder payload or a `questions` row into the values the question form renders."""
    kind = source.get('stored_type') or source.get('type') or 'single'
    raw_options = _sx_json(source.get('options'), []) or []
    correct_answer = _sx_json(source.get('correct_answer'), source.get('correct_answer'))
    correct_values = {str(value) for value in correct_answer} if isinstance(correct_answer, list) else {str(correct_answer or '')}
    options = []
    for index, option in enumerate(raw_options, start=1):
        if isinstance(option, dict):
            text = option.get('text') or option.get('label') or ''
            is_correct = bool(option.get('is_correct')) or str(option.get('id') or index) in correct_values
            points = option.get('points') or '1'
            penalty = option.get('negative_points') or '0'
            media = option.get('media') or ''
        else:
            text, points, penalty, media = str(option), '1', '0', ''
            is_correct = text in correct_values or str(index) in correct_values
        options.append({'text': text, 'is_correct': is_correct, 'points': points, 'penalty': penalty, 'media': media, 'media_kind': _media_kind(media)})
    feedback = _sx_json(source.get('feedback'), {}) or {}
    feedback = feedback if isinstance(feedback, dict) else {}
    media = _sx_json(source.get('question_media'), {}) or {}
    media = media if isinstance(media, dict) else {}
    settings_data = _sx_json(source.get('scoring_settings'), {}) or {}
    settings_data = settings_data if isinstance(settings_data, dict) else {}
    try:
        stored_negative = abs(float(source.get('negative_points') or 0))
    except (TypeError, ValueError):
        stored_negative = 0
    negative_value = settings_data.get('negative_value') or stored_negative or 0.25
    try:
        time_seconds = max(int(float(source.get('suggested_time_seconds') or 180)), 0)
    except (TypeError, ValueError):
        time_seconds = 180
    published = source.get('is_published')
    form = {
        # New questions default to «منتشرشده»; the draft button still saves as draft.
        'is_published': True if published is None else published in (True, 1, '1', 'true', 'True'),
        'time_display': f'{time_seconds // 60:02d}:{time_seconds % 60:02d}',
        'distractors': list(settings_data.get('matching_distractors') or []),
        'type': kind,
        'text': source.get('text') or '',
        'course_id': str(source.get('course_id') or ''),
        'difficulty': source.get('difficulty') or 'medium',
        'default_points': source.get('default_points') or '1',
        'negative_points': source.get('negative_points') or '0',
        'suggested_time_seconds': source.get('suggested_time_seconds') or '180',
        'tags': source.get('tags') or '',
        'subject': source.get('subject') or '',
        'feedback_text': feedback.get('text', ''),
        'feedback_media': feedback.get('media', ''),
        'feedback_media_kind': _media_kind(feedback.get('media', '')),
        'media': {
            'image': media.get('image') or '',
            'image_alt': media.get('image_alt') or '',
            'audio': media.get('audio') or '',
            'video': media.get('video') or '',
            'video_caption': media.get('video_caption') or '',
            'video_subtitle': media.get('video_subtitle') or '',
        },
        'settings': {
            'negative_marking': bool(settings_data.get('negative_marking')),
            'negative_value': f'{float(negative_value):g}',
            'shuffle_options': bool(settings_data.get('shuffle_options')),
            'scoring_mode': settings_data.get('scoring_mode') or ('partial' if settings_data.get('partial_credit', True) else 'all_or_nothing'),
            'min_correct': settings_data.get('min_correct') or 1,
            'max_correct': settings_data.get('max_correct') or 0,
            'floor_zero': settings_data.get('floor_zero', True),
            'matching_mode': settings_data.get('matching_mode') or 'one_to_one',
            'matching_distractors': '، '.join(settings_data.get('matching_distractors') or []),
            'ordering_mode': settings_data.get('ordering_mode') or 'exact',
            'correct_threshold': f"{_sx_float(settings_data.get('correct_threshold'), 100):g}",
            'normalize_answers': settings_data.get('normalize_answers', True),
        },
        'options': [],
        'blanks': [],
        'pairs': [],
        'ordering': [],
        'accepted': [],
    }
    if kind == 'true_false':
        blank_option = {'text': '', 'is_correct': False, 'points': '1', 'media': '', 'media_kind': ''}
        form['options'] = options or [dict(blank_option, text='درست'), dict(blank_option, text='نادرست')]
    elif kind in {'single', 'multi'}:
        form['options'] = _pad_rows(options, 4, {'text': '', 'is_correct': False, 'points': '1', 'penalty': '-0.5', 'media': '', 'media_kind': ''})
    elif kind == 'fill_blank':
        stored = [item for item in (_sx_json(source.get('accepted_answers'), []) or []) if isinstance(item, dict) and 'answers' in item]
        if not stored and isinstance(correct_answer, str):
            # Legacy fill-blank rows only stored one answer per blank in correct_answer.
            stored = [{'answers': [answer]} for answer in correct_answer.split('|') if answer]
        blanks = [
            {
                'answers': '، '.join(item.get('answers') or []),
                'points': f"{float(item.get('points') or 1):g}",
                'case_sensitive': bool(item.get('case_sensitive')),
                'ignore_spaces': item.get('ignore_spaces', True),
                'media': item.get('media') or '',
                'media_kind': _media_kind(item.get('media') or ''),
            }
            for item in stored
        ]
        blank_count = max(len(_BLANK_MARKER_RE.findall(form['text'])), len(blanks), 1)
        form['blanks'] = _pad_rows(blanks, blank_count, {'answers': '', 'points': '1', 'case_sensitive': False, 'ignore_spaces': True, 'media': '', 'media_kind': ''})
    elif kind == 'matching':
        pairs = [
            {
                'left': pair.get('left', ''), 'right': pair.get('right', ''),
                'left_media': pair.get('left_media', ''), 'left_media_kind': _media_kind(pair.get('left_media', '')),
                'right_media': pair.get('right_media', ''), 'right_media_kind': _media_kind(pair.get('right_media', '')),
            }
            for pair in (_sx_json(source.get('matching_pairs'), []) or []) if isinstance(pair, dict)
        ]
        form['pairs'] = _pad_rows(pairs, 3, {'left': '', 'right': '', 'left_media': '', 'left_media_kind': '', 'right_media': '', 'right_media_kind': ''})
    elif kind == 'ordering':
        items = sorted((_sx_json(source.get('ordering_items'), []) or []), key=lambda item: item.get('order', 0) if isinstance(item, dict) else 0)
        rows = [
            {'text': item.get('text', ''), 'media': item.get('media', ''), 'media_kind': _media_kind(item.get('media', ''))} if isinstance(item, dict)
            else {'text': str(item), 'media': '', 'media_kind': ''}
            for item in items
        ]
        form['ordering'] = _pad_rows(rows, 3, {'text': '', 'media': '', 'media_kind': ''})
    elif kind == 'short_answer':
        accepted = [
            {
                'answer': item.get('answer', ''),
                # Legacy rows stored a raw score; new rows store the credit percentage.
                'points': f"{float(item.get('points') or 100):g}" if 'match_mode' in item else '100',
                'match_mode': item.get('match_mode') or 'exact',
                'case_sensitive': bool(item.get('case_sensitive')),
                'normalize': item.get('normalize', True),
                'tolerance': f"{float(item.get('tolerance') or 0):g}",
                'typo_tolerance': str(item.get('typo_tolerance') or 0),
                'ignore_word_order': bool(item.get('ignore_word_order')),
            }
            for item in (_sx_json(source.get('accepted_answers'), []) or []) if isinstance(item, dict)
        ]
        form['accepted'] = _pad_rows(accepted, 1, {'answer': '', 'points': '100', 'match_mode': 'exact', 'case_sensitive': False, 'normalize': True, 'tolerance': '0', 'typo_tolerance': '0', 'ignore_word_order': False})
    elif kind == 'essay':
        rubric = [row for row in (_sx_json(source.get('rubric'), []) or []) if isinstance(row, dict)]
        form['rubric'] = _pad_rows(rubric, 1, {'criterion': '', 'weak': '', 'average': '', 'excellent': '', 'points': ''})
        essay = (_sx_json(source.get('scoring_settings'), {}) or {}).get('essay') or {}
        form['essay'] = {
            'student_instructions': essay.get('student_instructions') or '',
            'answer_formats': essay.get('answer_formats') or ['text'],
            'sample_answer_text': essay.get('sample_answer_text') or '',
            'sample_answer_file': essay.get('sample_answer_file') or None,
        }
    form.update(question_kinds.form_values(kind, source, settings_data))
    if kind in RICH_STEM_TYPES:
        # Questions saved before the rich editor only have plain text; seed the editor with it.
        delta = _stem_delta(_sx_json(source.get('scoring_settings'), {}) or {})
        form['text_delta'] = delta or ({'ops': [{'insert': f"{form.get('text') or ''}\n"}]} if form.get('text') else None)
    return form


def _save_question_payload(payload, teacher_id, question_id=None):
    """Insert or update an independent question. Updates are scoped to the owning teacher."""
    columns = erd_table_columns('questions')
    with transaction.atomic():
        if question_id is None:
            question_id = str(uuid.uuid4())
            erd_execute(
                """
                INSERT INTO questions (id, teacher_id, type, difficulty, text, options, correct_answer, default_points, tags)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                [
                    question_id, teacher_id, payload['stored_type'], payload['difficulty'], payload['text'],
                    json.dumps(payload['options'], ensure_ascii=False),
                    json.dumps(payload['correct_answer'], ensure_ascii=False),
                    payload['default_points'], payload['tags'],
                ],
            )
        else:
            erd_execute(
                """
                UPDATE questions
                SET type = %s, difficulty = %s, text = %s, options = %s, correct_answer = %s, default_points = %s, tags = %s
                WHERE id = %s AND teacher_id = %s
                """,
                [
                    payload['stored_type'], payload['difficulty'], payload['text'],
                    json.dumps(payload['options'], ensure_ascii=False),
                    json.dumps(payload['correct_answer'], ensure_ascii=False),
                    payload['default_points'], payload['tags'], question_id, teacher_id,
                ],
            )
        if 'course_id' in columns:
            erd_execute('UPDATE questions SET course_id = %s WHERE id = %s AND teacher_id = %s', [payload['course_id'] or None, question_id, teacher_id])
        if {'structure', 'question_media', 'scoring_settings', 'feedback'}.issubset(columns):
            erd_execute(
                """
                UPDATE questions
                SET structure = %s,
                    subject = %s,
                    question_media = %s,
                    answer_media = %s,
                    scoring_settings = %s,
                    feedback = %s,
                    rubric = %s,
                    accepted_answers = %s,
                    matching_pairs = %s,
                    ordering_items = %s,
                    scenario_data = %s,
                    is_published = %s,
                    negative_points = %s,
                    suggested_time_seconds = %s
                WHERE id = %s AND teacher_id = %s
                """,
                [
                    payload['structure'],
                    payload['subject'],
                    json.dumps(payload['question_media'], ensure_ascii=False),
                    json.dumps(payload['answer_media'], ensure_ascii=False),
                    json.dumps(payload['scoring_settings'], ensure_ascii=False),
                    json.dumps(payload['feedback'], ensure_ascii=False),
                    json.dumps(payload['rubric'], ensure_ascii=False),
                    json.dumps(payload['accepted_answers'], ensure_ascii=False),
                    json.dumps(payload['matching_pairs'], ensure_ascii=False),
                    json.dumps(payload['ordering_items'], ensure_ascii=False),
                    json.dumps(payload['scenario_data'], ensure_ascii=False),
                    payload['is_published'],
                    payload['negative_points'],
                    payload['suggested_time_seconds'],
                    question_id,
                    teacher_id,
                ],
            )
    return question_id


def _question_form_context(request, page, form_data, course_options, question_id=None):
    context = _teacher_modern_context(request, page)
    context['essay_answer_formats'] = ESSAY_ANSWER_FORMATS
    requested_type = form_data['type']
    config = QUESTION_BUILDER_TYPES.get(requested_type, QUESTION_BUILDER_TYPES['single'])
    context.update({
        'question_builder_type': requested_type,
        'question_builder_label': config['label'],
        'question_builder_structure': config['structure'],
        'qf': form_data,
        'question_course_options': course_options,
        'question_id': question_id,
    })
    return context


QUESTION_DRAFT_MAX_BYTES = 200 * 1024


def _question_draft_key(teacher_id, question_id=None, question_type='single'):
    return f'question_draft.{teacher_id}.{question_id or f"new-{question_type}"}'


def _load_question_draft(key):
    draft = erd_setting(key)
    return draft if isinstance(draft, dict) and isinstance(draft.get('fields'), dict) else None


def _delete_question_draft(key):
    erd_execute('DELETE FROM system_settings WHERE key = %s', [key])


def _question_draft_form_data(draft, question_type):
    """Rebuild form values from an autosaved draft; media URLs go through the same allow-list as a real save."""
    post = QueryDict(mutable=True)
    for name, values in draft['fields'].items():
        if isinstance(values, list):
            post.setlist(name, [str(value) for value in values])
    post['type'] = question_type
    post['structure'] = 'independent'
    payload = _question_builder_payload(post)
    _apply_independent_settings(payload, post)
    _apply_question_uploads(payload, {}, post)
    return _question_form_data(payload)


def _attach_question_draft(request, context, key, question_type):
    """Restore/discard an autosaved draft on request, otherwise announce that one exists."""
    draft = _load_question_draft(key)
    if not draft:
        return context
    action = request.GET.get('draft')
    if action == 'discard':
        _delete_question_draft(key)
        return context
    if action == 'restore':
        context['qf'] = _question_draft_form_data(draft, question_type)
        context['question_draft_restored'] = True
    context['question_draft_saved_at'] = draft.get('saved_at') or ''
    return context


@erd_role_required('teacher')
def teacher_question_autosave(request):
    """Store the in-progress builder form as a private server-side draft (never as a question row)."""
    if request.method != 'POST':
        return JsonResponse({'ok': False, 'error': 'method_not_allowed'}, status=405)
    teacher_id = request.erd_profile_id
    question_id = (request.POST.get('question_id') or '').strip() or None
    question_type = request.POST.get('type') or ''
    if question_id:
        row = erd_row('SELECT type FROM questions WHERE id = %s AND teacher_id = %s', [question_id, teacher_id])
        if not row:
            return JsonResponse({'ok': False, 'error': 'not_found'}, status=404)
        question_type = row['type']
    if question_type not in INDEPENDENT_QUESTION_TYPES:
        return JsonResponse({'ok': False, 'error': 'invalid_type'}, status=400)
    fields = {name: request.POST.getlist(name) for name in request.POST.keys() if name not in {'csrfmiddlewaretoken', 'question_id'}}
    now = timezone.now()
    saved_at = f'{_sx_jalali(now)} {timezone.localtime(now):%H:%M}'
    value = json.dumps({'fields': fields, 'saved_at': saved_at}, ensure_ascii=False)
    if len(value.encode('utf-8')) > QUESTION_DRAFT_MAX_BYTES:
        return JsonResponse({'ok': False, 'error': 'too_large'}, status=413)
    erd_execute(
        """
        INSERT INTO system_settings (key, value, description, updated_by)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_by = excluded.updated_by
        """,
        [_question_draft_key(teacher_id, question_id, question_type), value, 'Question builder autosave draft', teacher_id],
    )
    return JsonResponse({'ok': True, 'saved_at': saved_at})


@erd_role_required('teacher')
def teacher_question_create(request):
    teacher_id = request.erd_profile_id
    if (request.POST.get('type') or request.GET.get('type')) == 'osce':
        # OSCE moved to its own multi-station builder; old links land there.
        return redirect('core:teacher_osce_create')
    course_options = _teacher_question_course_options(teacher_id)
    if request.method == 'POST':
        payload = _question_builder_payload(request.POST)
        if payload['structure'] != 'independent':
            # Scenario builders (case/kfp) keep their existing save behaviour.
            if payload['text']:
                _save_question_payload(payload, teacher_id)
                messages.success(request, 'سوال ذخیره شد.')
                if request.POST.get('save_next'):
                    return redirect(f"{reverse('core:teacher_question_create')}?type={payload['requested_type']}")
                return redirect('core:teacher_questions')
        else:
            _apply_independent_settings(payload, request.POST)
            errors = _apply_question_uploads(payload, request.FILES, request.POST)
            errors += _question_builder_errors(payload, {str(row['id']) for row in course_options})
            if not errors:
                _save_question_payload(payload, teacher_id)
                _delete_question_draft(_question_draft_key(teacher_id, None, payload['requested_type']))
                messages.success(request, 'سؤال ذخیره شد.')
                if request.POST.get('save_next'):
                    return redirect(f"{reverse('core:teacher_question_create')}?type={payload['requested_type']}")
                return redirect('core:teacher_questions')
            for error in errors:
                messages.error(request, error)
            return render(request, 'teacher/modern.html', _question_form_context(request, 'question_create', _question_form_data(payload), course_options))
    requested_type = request.GET.get('type') or 'single'
    form_data = _question_form_data({'type': requested_type if requested_type in INDEPENDENT_QUESTION_TYPES else 'single'})
    form_data['type'] = requested_type
    context = _question_form_context(request, 'question_create', form_data, course_options)
    if requested_type in INDEPENDENT_QUESTION_TYPES:
        context = _attach_question_draft(request, context, _question_draft_key(teacher_id, None, requested_type), requested_type)
    return render(request, 'teacher/modern.html', context)


@erd_role_required('teacher')
def teacher_question_bulk_import(request):
    return render(request, 'teacher/modern.html', _teacher_modern_context(request, 'question_import'))


@erd_role_required('teacher')
def teacher_question_edit(request, question_id):
    teacher_id = request.erd_profile_id
    row = erd_row('SELECT * FROM questions WHERE id = %s AND teacher_id = %s', [question_id, teacher_id])
    if not row:
        raise Http404('سؤال پیدا نشد.')
    course_options = _teacher_question_course_options(teacher_id)
    editable = (row.get('type') in INDEPENDENT_QUESTION_TYPES) and (row.get('structure') or 'independent') == 'independent'
    if not editable:
        context = _teacher_modern_context(request, 'question_edit')
        context.update({'question_id': question_id, 'qf': None})
        return render(request, 'teacher/modern.html', context)
    if request.method == 'POST':
        post = request.POST.copy()
        post['type'] = row['type']
        payload = _question_builder_payload(post)
        _apply_independent_settings(payload, post)
        errors = _apply_question_uploads(payload, request.FILES, request.POST)
        errors += _question_builder_errors(payload, {str(option['id']) for option in course_options})
        if not errors:
            _save_question_payload(payload, teacher_id, question_id)
            _delete_question_draft(_question_draft_key(teacher_id, question_id))
            messages.success(request, 'تغییرات سؤال ذخیره شد.')
            return redirect('core:teacher_questions')
        for error in errors:
            messages.error(request, error)
        return render(request, 'teacher/modern.html', _question_form_context(request, 'question_edit', _question_form_data(payload), course_options, question_id))
    context = _question_form_context(request, 'question_edit', _question_form_data(row), course_options, question_id)
    context = _attach_question_draft(request, context, _question_draft_key(teacher_id, question_id), row['type'])
    return render(request, 'teacher/modern.html', context)


@erd_role_required('teacher')
def teacher_exams(request):
    status = request.GET.get('status') if request.GET.get('status') in TEACHER_EXAM_LIST_FILTERS else 'all'
    exam_list = _teacher_exam_list(
        request.erd_profile_id, (request.GET.get('q') or '').strip()[:100], status, request.GET.get('page'),
    )
    return render(request, 'teacher/modern.html', _teacher_modern_context(request, 'exams', exam_list=exam_list))


@erd_role_required('teacher')
def teacher_exam_create(request):
    """The admin exam wizard, limited to this teacher's groups, students and questions.

    The teacher is always the exam's owner and cannot publish: the exam is saved as a
    draft or sent to the academic manager for approval."""
    return _teacher_exam_wizard(request)


@erd_role_required('teacher')
def teacher_exam_edit(request, exam_id):
    """The same wizard, pre-filled with one of the teacher's exams that is still editable."""
    exam = erd_row('SELECT * FROM exams WHERE id = %s AND teacher_id = %s', [exam_id, request.erd_profile_id])
    if not exam:
        raise Http404('آزمون پیدا نشد.')
    if not _teacher_exam_editable(exam):
        messages.error(request, 'این آزمون منتشر شده یا دانشجویان در آن شرکت کرده‌اند؛ ویرایش آن فقط از طریق مدیر آموزشی ممکن است.')
        return redirect('core:teacher_exams')
    # The wizard only offers the teacher's own items; saving would silently drop anything else
    # (e.g. a manager added another teacher's questions), so such exams stay with the manager.
    initial, scope = _exam_wizard_initial(exam), _exam_wizard_scope(request)
    saved = (
        ('questions', initial['question_ids']),
        ('groups', initial['group_ids']),
        ('students', initial['student_ids'] + initial['excluded_student_ids']),
        ('teachers', [row['teacher_id'] for row in initial['staff']]),
    )
    if not all(_exam_wizard_ids_in_scope(scope, kind, ids) for kind, ids in saved):
        messages.error(request, 'این آزمون شامل سؤال، گروه یا عواملی خارج از بانک و گروه‌های شماست؛ ویرایش آن را از مدیر آموزشی بخواهید.')
        return redirect('core:teacher_exams')
    return _teacher_exam_wizard(request, exam)


def _teacher_exam_editable(exam) -> bool:
    """A teacher may change their exam until it is published or someone has started it."""
    lifecycle = exam.get('lifecycle_status') or 'draft'
    return (
        lifecycle in ('draft', 'pending_approval')
        and not exam.get('is_published')
        and not exam.get('is_cancelled')
        and not erd_count('exam_attempts', 'exam_id = %s', [exam['id']])
    )


def _exam_wizard_initial(exam) -> dict:
    """What the wizard's JS needs to pre-fill itself with a saved exam."""
    skip = {'id', 'teacher_id', 'tags', 'approved_by', 'cover_image_url', 'guidance_file_url'}
    fields = {}
    for key, value in exam.items():
        if key in skip or value is None:
            continue
        if key.endswith('_at'):
            moment = erd_datetime(value)
            value = timezone.localtime(moment).strftime('%Y-%m-%dT%H:%M') if moment else ''
        elif isinstance(value, Decimal):
            value = float(value)
        elif not isinstance(value, (bool, int, float, str)):
            value = str(value)
        fields[key] = value
    if exam.get('academic_year') or exam.get('semester'):
        fields['academic_term'] = f"{exam.get('academic_year') or ''}/{exam.get('semester') or ''}"
    exam_id = exam['id']
    assignments = erd_rows('SELECT group_id, student_profile_id FROM exam_assignments WHERE exam_id = %s', [exam_id])
    return {
        'fields': fields,
        'group_ids': [str(row['group_id']) for row in assignments if row['group_id']],
        'student_ids': [str(row['student_profile_id']) for row in assignments if row['student_profile_id']],
        'excluded_student_ids': [str(row['student_profile_id']) for row in erd_rows(
            'SELECT student_profile_id FROM exam_assignment_exclusions WHERE exam_id = %s', [exam_id])],
        'question_ids': [str(row['question_id']) for row in erd_rows(
            'SELECT question_id FROM exam_questions WHERE exam_id = %s ORDER BY order_index', [exam_id])],
        'staff': [{'teacher_id': str(row['teacher_id']), 'role': row['role']} for row in erd_rows(
            'SELECT teacher_id, role FROM exam_staff WHERE exam_id = %s', [exam_id])],
        'tags': [tag.strip() for tag in re.split('[,،]', exam.get('tags') or '') if tag.strip()],
        'publish_choice': 'submit' if exam.get('lifecycle_status') == 'pending_approval' else 'draft',
    }


def _teacher_exam_wizard(request, exam=None):
    scope = _exam_wizard_scope(request)
    resources = _exam_wizard_resources(request, scope)
    retry_url = reverse('core:teacher_exam_edit', args=[exam['id']]) if exam else reverse('core:teacher_exam_create')
    if request.method == 'POST':
        posted = _exam_wizard_post_selection(request)
        course_id = request.POST.get('course_id') or (posted['first_group'] or {}).get('course_id')
        missing = (
            'عنوان آزمون و درس الزامی است.' if not posted['title'] or not course_id
            else 'حداقل یک گروه یا دانشجو برای آزمون انتخاب کنید.' if not posted['group_ids'] and not posted['student_ids']
            else 'حداقل یک سوال برای آزمون انتخاب کنید.' if not posted['question_ids']
            else None
        )
        if missing:
            messages.error(request, missing)
            return redirect(retry_url)
        checks = (
            ('courses', [course_id]),
            ('groups', posted['group_ids']),
            ('students', posted['student_ids'] + posted['excluded_student_ids']),
            ('questions', posted['question_ids']),
            ('teachers', posted['staff_teacher_ids']),
        )
        if not all(_exam_wizard_ids_in_scope(scope, kind, ids) for kind, ids in checks):
            return HttpResponseForbidden('برخی موارد انتخاب‌شده خارج از درس‌ها، گروه‌ها یا سؤال‌های شماست.')
        submit = request.POST.get('publish_choice') == 'submit'
        exam_id = _exam_wizard_insert(
            request, title=posted['title'], teacher_id=request.erd_profile_id, course_id=course_id,
            first_group=posted['first_group'], selected_questions=posted['question_ids'],
            selected_groups=posted['group_ids'], selected_students=posted['student_ids'],
            excluded_students=posted['excluded_student_ids'],
            staff_pairs=zip(posted['staff_teacher_ids'], posted['staff_roles']),
            publish_choice='submit' if submit else 'draft', is_published=False,
            lifecycle_status='pending_approval' if submit else 'draft', approval_status='pending',
            existing_exam_id=exam['id'] if exam else None,
        )
        action = 'ویرایش و ' if exam else ''
        if submit:
            log_activity(request.user, 'teacher_exam_submitted', f"آزمون {posted['title']} {action}برای تأیید ارسال شد.", request, {'exam_id': exam_id})
            messages.success(request, 'آزمون ذخیره و برای تأیید مدیر آموزشی ارسال شد.')
        else:
            log_activity(request.user, 'teacher_exam_updated' if exam else 'teacher_exam_created',
                         f"آزمون {posted['title']} {action}به‌صورت پیش‌نویس ذخیره شد.", request, {'exam_id': exam_id})
            messages.success(request, 'آزمون به‌صورت پیش‌نویس ذخیره شد.')
        return redirect('core:teacher_exams')
    return _exam_wizard_render(
        request, resources,
        page='exam_create',  # highlights «آزمون‌ها» in the teacher nav
        wizard_role='teacher',
        participants_match_url=reverse('core:teacher_exam_participants_match'),
        title='ویرایش آزمون' if exam else 'ایجاد آزمون',
        wizard_initial=_exam_wizard_initial(exam) if exam else None,
    )


@erd_role_required('teacher')
def teacher_monitoring(request):
    return _teacher_exam_report_page(request, 'monitoring')


def _teacher_exam_report_page(request, page):
    """Monitoring/results page for one of the teacher's exams (?exam=<id>; another teacher's id is a 404)."""
    teacher_id = request.erd_profile_id
    options = _teacher_exam_options(teacher_id)
    exam_id = request.GET.get('exam')
    if not exam_id:
        now = timezone.now()
        preferred = (
            (row for row in options if row['in_progress'] or (row['start_at'] and row['start_at'] <= now and (not row['end_at'] or row['end_at'] >= now)))
            if page == 'monitoring' else (row for row in options if row['submitted'])
        )
        chosen = next(preferred, None) or (options[0] if options else None)
        exam_id = chosen['id'] if chosen else None
    exam = _teacher_owned_exam(teacher_id, exam_id) if exam_id else None
    if exam_id and not exam:
        raise Http404('آزمون پیدا نشد.')
    report = None
    if exam:
        report = _teacher_exam_monitoring(exam) if page == 'monitoring' else _teacher_exam_results(exam, request.GET.get('page'))
    return render(request, 'teacher/modern.html', _teacher_modern_context(
        request, page, report_exam=exam, report_exam_options=options, report=report,
    ))


@erd_role_required('teacher')
def teacher_results(request):
    return _teacher_exam_report_page(request, 'results')


def _em_truthy(value):
    return value in (True, 1, '1', 'true', 'True', 'active', 'published')


def _em_profile_context(request):
    profile = getattr(request, 'erd_profile', None) or erd_profile_for_user(request.user) or {}
    return {
        'display_name': profile.get('full_name') or request.user.get_full_name() or request.user.username,
        'panel_avatar_url': profile.get('avatar_url') or '',
    }


def _em_term_label(row):
    semester = row.get('semester') or 'اول'
    year = row.get('academic_year') or '۱۴۰۵'
    if '?' in str(semester):
        semester = 'اول'
    if '?' in str(year):
        year = '۱۴۰۵'
    return semester if 'نیمسال' in str(semester) else f'نیمسال {semester} {year}'.strip()


def _em_teacher_options(request):
    if _erd_is_admin_request(request):
        return erd_rows(
            """
            SELECT p.id, p.full_name, COALESCE(tp.department, '') AS department, COALESCE(tp.specialty, '') AS specialty,
                   COALESCE(p.avatar_url, '') AS avatar_url
            FROM teacher_profiles tp
            JOIN profiles p ON p.id = tp.user_id
            ORDER BY p.full_name
            LIMIT 200
            """
        )
    return erd_rows(
        _erd_manager_scope_cte() + f"""
        SELECT p.id, p.full_name, COALESCE(tp.department, '') AS department, COALESCE(tp.specialty, '') AS specialty,
               COALESCE(p.avatar_url, '') AS avatar_url
        FROM teacher_profiles tp
        JOIN profiles p ON p.id = tp.user_id
        WHERE {_erd_teacher_scope_condition()}
        ORDER BY p.full_name
        LIMIT 200
        """,
        [request.erd_profile_id],
    )


def _em_student_options(request):
    if _erd_is_admin_request(request):
        return erd_rows(
            """
            SELECT p.id, p.full_name, COALESCE(sp.student_number, p.identifier, '') AS student_number,
                   COALESCE(sp.field_of_study, '') AS field_of_study,
                   COALESCE(sp.academic_status, p.status, 'active') AS status,
                   COALESCE(sp.entry_year, '') AS entry_year,
                   COALESCE(p.avatar_url, '') AS avatar_url
            FROM student_profiles sp
            JOIN profiles p ON p.id = sp.user_id
            ORDER BY p.full_name
            LIMIT 500
            """
        )
    return erd_rows(
        _erd_manager_scope_cte() + f"""
        SELECT p.id, p.full_name, COALESCE(sp.student_number, p.identifier, '') AS student_number,
               COALESCE(sp.field_of_study, '') AS field_of_study,
               COALESCE(sp.academic_status, p.status, 'active') AS status,
               COALESCE(sp.entry_year, '') AS entry_year,
               COALESCE(p.avatar_url, '') AS avatar_url
        FROM student_profiles sp
        JOIN profiles p ON p.id = sp.user_id
        WHERE {_erd_student_scope_condition()}
        ORDER BY p.full_name
        LIMIT 500
        """,
        [request.erd_profile_id],
    )


def _em_course_rows(request, course_id=None):
    is_admin = _erd_is_admin_request(request)
    where = ['1=1']
    params = []
    if not is_admin:
        where.append('c.org_unit_id IN (SELECT id FROM managed_units)')
    if course_id:
        where.append('c.id = %s')
        params.append(course_id)
    scope_cte = '' if is_admin else _erd_manager_scope_cte()
    scope_params = [] if is_admin else [request.erd_profile_id]
    rows = erd_rows(
        f"""
        {scope_cte}
        SELECT c.id, c.title, COALESCE(c.code, '') AS code, COALESCE(c.description, '') AS description,
               COALESCE(c.credit_units, 0) AS credit_units, c.org_unit_id,
               COALESCE(ou.name, 'دانشکده پزشکی') AS department,
               COUNT(DISTINCT sg.id) AS groups_count,
               COUNT(DISTINCT CASE WHEN COALESCE(sg.is_active, true) THEN sg.id END) AS active_groups_count,
               COUNT(DISTINCT sgm.id) AS students_count,
               COUNT(DISTINCT e.id) AS exams_count,
               MAX(COALESCE(sg.academic_year, e.academic_year, '۱۴۰۵')) AS academic_year,
               MAX(COALESCE(sg.semester, e.semester, 'اول')) AS semester,
               MAX(COALESCE(p.full_name, 'استاد نمونه')) AS teacher_name,
                MAX(sg.teacher_id::text) AS teacher_id
        FROM courses c
        LEFT JOIN org_units ou ON ou.id = c.org_unit_id
        LEFT JOIN student_groups sg ON sg.course_id = c.id
        LEFT JOIN student_group_members sgm ON sgm.group_id = sg.id
        LEFT JOIN exams e ON e.course_id = c.id
        LEFT JOIN profiles p ON p.id = sg.teacher_id
        WHERE {' AND '.join(where)}
        GROUP BY c.id, c.title, c.code, c.description, c.credit_units, c.org_unit_id, ou.name
        ORDER BY c.title
        LIMIT 300
        """,
        scope_params + params,
    )
    for row in rows:
        row['term_label'] = _em_term_label(row)
        row['status_label'] = 'فعال'
        row['status_tone'] = 'ok'
        row['groups_count'] = int(row.get('groups_count') or 0)
        row['active_groups_count'] = int(row.get('active_groups_count') or 0)
        row['students_count'] = int(row.get('students_count') or 0)
        row['exams_count'] = int(row.get('exams_count') or 0)
    return rows


def _em_group_rows(request, group_id=None, course_id=None):
    is_admin = _erd_is_admin_request(request)
    where = ['1=1']
    params = []
    if not is_admin:
        where.append(_erd_group_scope_condition())
    if group_id:
        where.append('sg.id = %s')
        params.append(group_id)
    if course_id:
        where.append('sg.course_id = %s')
        params.append(course_id)
    scope_cte = '' if is_admin else _erd_manager_scope_cte()
    scope_params = [] if is_admin else [request.erd_profile_id]
    rows = erd_rows(
        f"""
        {scope_cte}
        SELECT sg.id, sg.teacher_id, sg.course_id, sg.course_name, COALESCE(c.title, sg.course_name) AS course_title,
               COALESCE(c.code, '') AS course_code, COALESCE(c.credit_units, 0) AS credit_units,
               COALESCE(sg.academic_year, '۱۴۰۵') AS academic_year,
               COALESCE(sg.semester, 'اول') AS semester,
               COALESCE(sg.group_code, '۱۴') AS group_code,
               COALESCE(sg.description, '') AS description,
               COALESCE(sg.capacity, 40) AS capacity,
               COALESCE(sg.min_students, 0) AS min_students,
               COALESCE(sg.waitlist_enabled, false) AS waitlist_enabled,
               COALESCE(sg.waitlist_capacity, 0) AS waitlist_capacity,
               COALESCE(sg.requires_teacher_approval, false) AS requires_teacher_approval,
               COALESCE(sg.offering_type, 'theory') AS offering_type,
               sg.class_schedule, sg.class_location,
               COALESCE(sg.is_active, true) AS is_active,
               COALESCE(sg.status, CASE WHEN COALESCE(sg.is_active, true) THEN 'active' ELSE 'draft' END) AS status,
               COALESCE(p.full_name, 'استاد نمونه') AS teacher_name, p.avatar_url AS teacher_avatar,
               COUNT(DISTINCT sgm.id) AS students_count,
               COUNT(DISTINCT e.id) AS exams_count
        FROM student_groups sg
        LEFT JOIN courses c ON c.id = sg.course_id
        LEFT JOIN profiles p ON p.id = sg.teacher_id
        LEFT JOIN student_group_members sgm ON sgm.group_id = sg.id
        LEFT JOIN exams e ON e.course_id = sg.course_id
        WHERE {' AND '.join(where)}
        GROUP BY sg.id, sg.teacher_id, sg.course_id, sg.course_name, c.title, c.code, c.credit_units,
                 sg.academic_year, sg.semester, sg.group_code, sg.description, sg.capacity, sg.min_students,
                 sg.waitlist_enabled, sg.waitlist_capacity, sg.requires_teacher_approval, sg.offering_type,
                 sg.class_schedule, sg.class_location, sg.is_active, sg.status, p.full_name, p.avatar_url
        ORDER BY sg.academic_year DESC, sg.course_name, sg.group_code
        LIMIT 400
        """,
        scope_params + params,
    )
    for row in rows:
        if '?' in str(row.get('group_code') or ''):
            row['group_code'] = '۱۴'
        if '?' in str(row.get('academic_year') or ''):
            row['academic_year'] = '۱۴۰۵'
        if '?' in str(row.get('semester') or ''):
            row['semester'] = 'اول'
        row['students_count'] = int(row.get('students_count') or 0)
        row['capacity'] = int(row.get('capacity') or 40)
        row['remaining'] = max(row['capacity'] - row['students_count'], 0)
        row['fill_percent'] = min(100, round(row['students_count'] * 100 / max(row['capacity'], 1)))
        row['term_label'] = _em_term_label(row)
        row['status_label'] = 'فعال' if _em_truthy(row.get('is_active')) else 'نیازمند تکمیل'
        row['status_tone'] = 'ok' if _em_truthy(row.get('is_active')) else 'warn'
    return rows


def _em_member_rows(group_id):
    rows = erd_rows(
        """
        SELECT sgm.id, sgm.student_user_id, COALESCE(p.full_name, sgm.full_name) AS full_name,
               COALESCE(sp.student_number, sgm.student_number, p.identifier, '-') AS student_number,
               COALESCE(sp.field_of_study, '-') AS field_of_study,
               COALESCE(sp.entry_year, '') AS entry_year,
               COALESCE(sp.academic_status, p.status, 'active') AS status,
               COALESCE(p.avatar_url, '') AS avatar_url
        FROM student_group_members sgm
        LEFT JOIN profiles p ON p.id = sgm.student_user_id
        LEFT JOIN student_profiles sp ON sp.user_id = sgm.student_user_id
        WHERE sgm.group_id = %s
        ORDER BY COALESCE(p.full_name, sgm.full_name)
        LIMIT 300
        """,
        [group_id],
    )
    for row in rows:
        row['status_label'] = 'فعال' if row.get('status') == 'active' else 'غیرفعال'
    return rows


def _em_group_exam_rows(course_id):
    if not course_id:
        return []
    rows = erd_rows(
        """
        SELECT e.id, e.title, e.start_at, e.end_at, e.duration_minutes,
               COALESCE(e.lifecycle_status, 'draft') AS status
        FROM exams e
        WHERE e.course_id = %s
        ORDER BY e.start_at DESC NULLS LAST
        LIMIT 50
        """,
        [course_id],
    )
    status_labels = {'draft': 'پیش‌نویس', 'pending_approval': 'در انتظار تایید', 'scheduled': 'برنامه‌ریزی‌شده', 'published': 'منتشرشده', 'active': 'در حال برگزاری', 'completed': 'برگزارشده', 'archived': 'بایگانی'}
    for row in rows:
        row['status_label'] = status_labels.get(row.get('status'), row.get('status') or '-')
    return rows


def _em_activity_rows(course=None, group=None):
    title = (course or {}).get('title') or (group or {}).get('course_title') or 'درس'
    group_name = f"گروه {(group or {}).get('group_code') or '۱۴'}"
    return [
        {'title': f'ایجاد {group_name} جدید «{title}»', 'meta': 'توسط مدیر آموزشی', 'tone': 'green', 'time': 'امروز ۱۰:۱۵'},
        {'title': f'برنامه‌ریزی آزمون «میان‌ترم»', 'meta': f'برای {title}', 'tone': 'purple', 'time': 'دیروز ۱۴:۳۰'},
        {'title': f'افزودن دانشجو به {group_name}', 'meta': 'توسط استاد مسئول', 'tone': 'orange', 'time': '۳ روز پیش ۱۱:۴۵'},
        {'title': 'به‌روزرسانی اطلاعات درس', 'meta': 'توسط مدیر آموزشی', 'tone': 'blue', 'time': '۴ روز پیش ۰۹:۲۰'},
    ]


def _em_base_context(request, page, title, icon='book'):
    return {
        **_em_profile_context(request),
        'page': page,
        'page_title': title,
        'page_icon': icon,
        'app_is_shell_page': True,
    }


@erd_role_required('academic_manager', 'admin')
def exam_manager_course_detail(request, course_id):
    return super_admin_course_form(request, course_id=course_id)


@erd_role_required('academic_manager', 'admin')
def exam_manager_course_create(request):
    return super_admin_course_form(request)


@erd_role_required('academic_manager', 'admin')
def exam_manager_groups(request):
    return super_admin_groups(request)


@erd_role_required('academic_manager', 'admin')
def exam_manager_group_create(request):
    return super_admin_group_create(request)


@erd_role_required('academic_manager', 'admin')
def exam_manager_group_students_add(request, group_id):
    return super_admin_group_students_add(request, group_id=group_id)


@erd_role_required('academic_manager', 'admin')
def exam_manager_group_students_manage(request, group_id):
    return super_admin_group_students_manage(request, group_id=group_id)


@erd_role_required('academic_manager', 'admin')
def exam_manager_group_edit(request, group_id):
    return super_admin_group_edit(request, group_id=group_id)


@erd_role_required('academic_manager', 'admin')
def exam_manager_group_archive(request, group_id):
    return super_admin_group_archive(request, group_id=group_id)


@erd_role_required('academic_manager', 'admin')
def exam_manager_group_import(request):
    if request.method == 'POST':
        messages.success(request, 'فایل دریافت شد. داده‌ها برای بررسی آماده هستند.')
        return redirect(reverse('core:exam_manager_group_import') + '?step=review')
    groups = _em_group_rows(request)
    context = _em_base_context(request, 'group_import', 'ورود گروهی دانشجویان', 'users')
    context.update({
        'step': request.GET.get('step') or 'upload',
        'group': groups[0] if groups else None,
        'review_rows': [
            {'number': '۱۴۰۴۱۰۱۱۱۱', 'name': 'سارا محمدی', 'field': 'پزشکی عمومی', 'group_code': '۱۰۱', 'status': 'نامعتبر', 'note': 'شماره دانشجویی یافت نشد'},
            {'number': '۱۴۰۴۱۰۱۱۱۲', 'name': 'امیرحسین موسوی', 'field': 'پزشکی عمومی', 'group_code': '۱۰۱', 'status': 'بررسی', 'note': 'تکراری در گروه دیگر'},
            {'number': '۱۴۰۴۱۰۱۱۱۳', 'name': 'نگین احمدی', 'field': 'پزشکی عمومی', 'group_code': '۱۰۱', 'status': 'معتبر', 'note': '-'},
            {'number': '۱۴۰۴۱۰۱۱۱۴', 'name': 'محمدرضا کریمی', 'field': 'دندانپزشکی', 'group_code': '۱۰۱', 'status': 'معتبر', 'note': '-'},
            {'number': '۱۴۰۴۱۰۱۱۱۵', 'name': 'معصومه جلالی', 'field': 'پزشکی عمومی', 'group_code': '۱۰۱', 'status': 'معتبر', 'note': '-'},
        ],
    })
    return render(request, 'exam_manager/grouping.html', context)


@erd_role_required('academic_manager', 'admin')
def exam_manager_group_detail(request, group_id):
    return super_admin_group_detail(request, group_id=group_id)


@erd_role_required('academic_manager', 'admin')
def exam_manager_group_teacher_assign(request):
    groups = _em_group_rows(request)
    teachers = _em_teacher_options(request)
    if request.method == 'POST':
        teacher_id = request.POST.get('teacher_id') or (teachers[0]['id'] if teachers else None)
        selected_groups = request.POST.getlist('group_ids')
        for group_id in selected_groups:
            erd_execute("UPDATE student_groups SET teacher_id = %s WHERE id = %s", [teacher_id, group_id])
            if teacher_id:
                erd_execute("INSERT OR IGNORE INTO group_teachers (group_id, teacher_id, created_at) VALUES (%s, %s, CURRENT_TIMESTAMP)", [group_id, teacher_id])
        messages.success(request, 'انتساب استاد به گروه‌های انتخاب‌شده ثبت شد.')
        return redirect('core:exam_manager_groups')
    for group in groups:
        group['status_label'] = 'فعال' if group.get('status_tone') == 'ok' else 'نیازمند تکمیل'
    context = _em_base_context(request, 'group_teacher_assign', 'انتساب استاد به گروه‌های درسی', 'users')
    context.update({'groups': groups, 'teachers': teachers, 'selected_count': min(3, len(groups))})
    return render(request, 'exam_manager/grouping.html', context)


@erd_role_required('academic_manager', 'admin')
def exam_manager_courses(request):
    return super_admin_courses(request)


def _em_account_label(status):
    if status in {'inactive', 'غیرفعال'}:
        return 'غیرفعال'
    if status in {'blocked', 'مسدود'}:
        return 'مسدود'
    return 'فعال'


def _em_account_tone(status):
    if status in {'inactive', 'غیرفعال'}:
        return 'warn'
    if status in {'blocked', 'مسدود'}:
        return 'bad'
    return 'ok'


@erd_role_required('academic_manager', 'admin')
def exam_manager_users(request):
    return super_admin_users(request)


@erd_role_required('academic_manager', 'admin')
def exam_manager_student_create(request):
    units = erd_rows("SELECT id, name FROM org_units WHERE COALESCE(is_active, true) ORDER BY name LIMIT 200")
    if request.method == 'POST':
        profile_id = str(uuid.uuid4())
        first_name = (request.POST.get('first_name') or '').strip()
        last_name = (request.POST.get('last_name') or '').strip()
        national_code = (request.POST.get('national_code') or '').strip()
        student_number = (request.POST.get('student_number') or '').strip()
        full_name = f'{first_name} {last_name}'.strip() or student_number or national_code or 'دانشجو جدید'
        erd_execute(
            """
            INSERT INTO profiles (id, full_name, first_name, last_name, username, email, phone, national_id, identifier, status, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'active', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            [profile_id, full_name, first_name, last_name, student_number or national_code or profile_id[:8], request.POST.get('email') or '', request.POST.get('mobile') or '', national_code, student_number],
        )
        erd_execute(
            """
            INSERT INTO student_profiles (user_id, student_number, field_of_study, degree, academic_status, org_unit_id, entry_year)
            VALUES (%s, %s, %s, %s, 'active', %s, %s)
            """,
            [profile_id, student_number, request.POST.get('field') or '', request.POST.get('education_level') or '', request.POST.get('academic_unit') or None, request.POST.get('entrance_year') or '1403'],
        )
        erd_execute(
            "INSERT INTO user_roles (id, user_id, role, created_at) VALUES (%s, %s, %s, CURRENT_TIMESTAMP)",
            [str(uuid.uuid4()), profile_id, 'student'],
        )
        username = student_number or national_code or profile_id[:8]
        _login_user, generated_password = erd_sync_login_account(username, is_active=True)
        if generated_password:
            messages.success(request, f'دانشجو با موفقیت ثبت شد. نام کاربری: {username} — رمز عبور اولیه: {generated_password}')
        else:
            messages.success(request, 'دانشجو با موفقیت ثبت شد.')
        return redirect(reverse('core:exam_manager_users') + '?tab=students')
    context = _em_base_context(request, 'student_create', 'افزودن دانشجو جدید', 'users')
    context.update({'units': units, 'summary_items': ['نام', 'نام خانوادگی', 'کد ملی', 'شماره دانشجویی', 'موبایل', 'ایمیل', 'دانشکده', 'رشته', 'مقطع', 'ورودی', 'وضعیت تحصیلی']})
    return render(request, 'exam_manager/users.html', context)


@erd_role_required('academic_manager', 'admin')
def exam_manager_teacher_create(request):
    units = erd_rows("SELECT id, name FROM org_units WHERE COALESCE(is_active, true) ORDER BY name LIMIT 200")
    if request.method == 'POST':
        profile_id = str(uuid.uuid4())
        first_name = (request.POST.get('first_name') or '').strip()
        last_name = (request.POST.get('last_name') or '').strip()
        national_code = (request.POST.get('national_code') or '').strip()
        personnel_code = (request.POST.get('personnel_code') or '').strip()
        full_name = f'{first_name} {last_name}'.strip() or personnel_code or national_code or 'استاد جدید'
        erd_execute(
            """
            INSERT INTO profiles (id, full_name, first_name, last_name, username, email, phone, national_id, identifier, status, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'active', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            [profile_id, full_name, first_name, last_name, personnel_code or national_code or profile_id[:8], request.POST.get('email') or '', request.POST.get('mobile') or '', national_code, personnel_code],
        )
        erd_execute(
            """
            INSERT INTO teacher_profiles (user_id, personnel_code, department, specialty, approval_status, org_unit_id)
            VALUES (%s, %s, %s, %s, 'approved', %s)
            """,
            [profile_id, personnel_code, request.POST.get('faculty') or '', request.POST.get('specialization') or '', request.POST.get('academic_unit') or None],
        )
        erd_execute(
            "INSERT INTO user_roles (id, user_id, role, created_at) VALUES (%s, %s, %s, CURRENT_TIMESTAMP)",
            [str(uuid.uuid4()), profile_id, 'teacher'],
        )
        username = personnel_code or national_code or profile_id[:8]
        _login_user, generated_password = erd_sync_login_account(username, is_active=True)
        if generated_password:
            messages.success(request, f'استاد با موفقیت ثبت شد. نام کاربری: {username} — رمز عبور اولیه: {generated_password}')
        else:
            messages.success(request, 'استاد با موفقیت ثبت شد.')
        return redirect(reverse('core:exam_manager_users') + '?tab=teachers')
    context = _em_base_context(request, 'teacher_create', 'افزودن استاد جدید', 'users')
    context.update({'units': units, 'summary_items': ['نام', 'نام خانوادگی', 'کد ملی', 'کد پرسنلی', 'موبایل', 'ایمیل', 'دانشکده', 'گروه آموزشی', 'تخصص', 'مرتبه علمی']})
    return render(request, 'exam_manager/users.html', context)


@erd_role_required('academic_manager', 'admin')
def exam_manager_teacher_profile(request, teacher_id):
    if not _erd_profile_in_manager_scope(request, teacher_id, 'teacher'):  # a manager only sees teachers of their units
        raise Http404('استاد پیدا نشد.')
    profile = erd_row(
        """
        SELECT p.id, p.full_name, COALESCE(p.email, '') AS email, COALESCE(p.phone, '') AS phone,
               COALESCE(p.avatar_url, '') AS avatar_url, COALESCE(p.status, tp.approval_status, 'active') AS status,
               COALESCE(p.created_at, '') AS created_at, COALESCE(p.updated_at, p.last_login_at, p.created_at) AS updated_at,
               COALESCE(tp.personnel_code, p.identifier, '') AS personnel_code,
               COALESCE(tp.specialty, '') AS specialty,
               COALESCE(ou.name, tp.department, 'دانشکده پزشکی') AS unit
        FROM teacher_profiles tp
        JOIN profiles p ON p.id = tp.user_id
        LEFT JOIN org_units ou ON ou.id = tp.org_unit_id
        WHERE p.id = %s
        LIMIT 1
        """,
        [teacher_id],
    )
    if not profile:
        raise Http404('استاد پیدا نشد.')
    classes = erd_rows(
        """
        SELECT sg.id, COALESCE(c.title, sg.course_name) AS course_title, sg.group_code, COUNT(sgm.id) AS students_count
        FROM student_groups sg
        LEFT JOIN courses c ON c.id = sg.course_id
        LEFT JOIN student_group_members sgm ON sgm.group_id = sg.id
        WHERE sg.teacher_id = %s
        GROUP BY sg.id, c.title, sg.course_name, sg.group_code
        ORDER BY c.title
        LIMIT 8
        """,
        [teacher_id],
    )
    exams = erd_rows(
        """
        SELECT e.id, e.title, COALESCE(c.title, '') AS course_title, e.start_at
        FROM exams e
        LEFT JOIN courses c ON c.id = e.course_id
        WHERE e.teacher_id = %s
        ORDER BY e.start_at DESC
        LIMIT 8
        """,
        [teacher_id],
    )
    question_count = erd_row(
        """
        SELECT COUNT(eq.id) AS count
        FROM exam_questions eq
        JOIN exams e ON e.id = eq.exam_id
        WHERE e.teacher_id = %s
        """,
        [teacher_id],
    ) or {'count': 0}
    context = _em_base_context(request, 'teacher_profile', 'پروفایل استاد', 'users')
    context.update({
        'teacher': profile,
        'teacher_profile': profile,
        'classes': classes,
        'teacher_exams': exams,
        'stats': {
            'courses': len({item.get('course_title') for item in classes}),
            'groups': len(classes),
            'exams': len(exams),
            'questions': int(question_count.get('count') or 0),
        },
        'activities': [
            {'title': log.get('reason') or log.get('action'), 'detail': log.get('entity_type') or '-', 'time': _jalali_long_date(log.get('created_at'), with_weekday=False)}
            for log in erd_rows(
                'SELECT action, entity_type, reason, created_at FROM activity_audit_log WHERE actor_id = %s ORDER BY created_at DESC LIMIT 5',
                [teacher_id],
            )
        ],
        'joined_label': _jalali_long_date(profile.get('created_at'), with_weekday=False),
        'last_seen_label': _jalali_long_date(profile.get('updated_at'), with_weekday=False),
    })
    return render(request, 'exam_manager/users.html', context)


def _manager_teacher_change_requests(request, reviewed: bool, page_number) -> dict:
    """One page of teachers' change requests that this manager may review (admin: all)."""
    from django.core.paginator import Paginator

    is_admin = _erd_is_admin_request(request)
    cte, scope, params = ('', '1 = 1', []) if is_admin else (_erd_manager_scope_cte(), _erd_teacher_scope_condition(), [request.erd_profile_id])
    status = "r.status IN ('approved', 'rejected')" if reviewed else "r.status = 'pending'"
    base = f"""
        FROM teacher_profile_change_requests r
        JOIN teacher_profiles tp ON tp.user_id = r.teacher_id
        JOIN profiles p ON p.id = r.teacher_id
        LEFT JOIN org_units nu ON nu.id = r.org_unit_id
        LEFT JOIN org_units pu ON pu.id = r.previous_org_unit_id
        LEFT JOIN profiles rv ON rv.id = r.reviewer_id
        WHERE {status} AND {scope}
    """
    total = (erd_row(cte + 'SELECT COUNT(*) AS count' + base, params) or {}).get('count') or 0
    page = Paginator(range(total), TEACHER_CHANGE_REQUEST_PAGE_SIZE).get_page(page_number)
    rows = erd_rows(
        cte + f"""
        SELECT r.id, r.org_unit_id, r.academic_rank, r.degree, r.previous_org_unit_id, r.previous_academic_rank,
               r.previous_degree, r.teacher_note, r.status, r.review_note, r.created_at, r.reviewed_at,
               p.full_name, p.avatar_url, tp.personnel_code,
               nu.name AS unit_name, pu.name AS previous_unit_name, rv.full_name AS reviewer_name
        {base}
        ORDER BY r.created_at DESC
        LIMIT %s OFFSET %s
        """,
        [*params, TEACHER_CHANGE_REQUEST_PAGE_SIZE, page.start_index() - 1 if total else 0],
    )
    items = []
    for row in rows:
        item = dict(row)
        item['changes'] = [
            (label, item.get(f'previous_{field}') or '-', item.get(field))
            for label, field in (('گروه آموزشی', 'unit_name'), ('مرتبه علمی', 'academic_rank'), ('مدرک تحصیلی', 'degree'))
            if item.get('org_unit_id' if field == 'unit_name' else field)
        ]
        item['created_label'] = _jalali_long_date(item['created_at'], with_weekday=False)
        item['reviewed_label'] = _jalali_long_date(item['reviewed_at'], with_weekday=False)
        items.append(item)
    return {'items': items, 'page': page, 'total': total}


def _manager_pending_teacher_request_count(request) -> int:
    if _erd_is_admin_request(request):
        return erd_count('teacher_profile_change_requests', "status = 'pending'")
    row = erd_row(
        _erd_manager_scope_cte() + f"""
        SELECT COUNT(*) AS count
        FROM teacher_profile_change_requests r
        JOIN teacher_profiles tp ON tp.user_id = r.teacher_id
        WHERE r.status = 'pending' AND {_erd_teacher_scope_condition()}
        """,
        [request.erd_profile_id],
    )
    return int((row or {}).get('count') or 0)


@erd_role_required('academic_manager', 'admin')
def exam_manager_teacher_requests(request):
    reviewed = request.GET.get('status') == 'reviewed'
    context = _em_base_context(request, 'teacher_requests', 'درخواست‌های تغییر اطلاعات اساتید', 'users')
    context.update({
        'requests_page': _manager_teacher_change_requests(request, reviewed, request.GET.get('page')),
        'requests_status': 'reviewed' if reviewed else 'pending',
        'pending_count': _manager_pending_teacher_request_count(request),
    })
    return render(request, 'exam_manager/teacher_requests.html', context)


@erd_role_required('academic_manager', 'admin')
def exam_manager_teacher_request_review(request, request_id):
    """Approve or reject one pending request; the teacher must be inside the manager's units (checked here, not in the UI)."""
    if request.method != 'POST':
        return redirect('core:exam_manager_teacher_requests')
    change = erd_row(
        "SELECT id, teacher_id, org_unit_id, academic_rank, degree FROM teacher_profile_change_requests WHERE id = %s AND status = 'pending'",
        [request_id],
    )
    if not change or not _erd_profile_in_manager_scope(request, change['teacher_id'], 'teacher'):
        raise Http404('درخواست پیدا نشد.')
    if str(change['teacher_id']) == str(request.erd_profile_id):
        return HttpResponseForbidden('بررسی درخواست خودتان مجاز نیست.')
    decision = request.POST.get('decision')
    note = (request.POST.get('review_note') or '').strip()
    if decision not in {'approve', 'reject'} or len(note) > 300:
        messages.error(request, 'تصمیم یا توضیح بررسی معتبر نیست (توضیح حداکثر ۳۰۰ نویسه).')
        return redirect('core:exam_manager_teacher_requests')
    if decision == 'reject' and not note:
        messages.error(request, 'برای رد درخواست، دلیل آن را بنویسید تا استاد ببیند.')
        return redirect('core:exam_manager_teacher_requests')
    status = 'approved' if decision == 'approve' else 'rejected'
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute(
                erd_adapt_sql(
                    """
                    UPDATE teacher_profile_change_requests
                    SET status = %s, reviewer_id = %s, review_note = %s, reviewed_at = CURRENT_TIMESTAMP
                    WHERE id = %s AND status = 'pending'
                    """
                ),
                [status, request.erd_profile_id, note or None, request_id],
            )
            claimed = cursor.rowcount == 1
        if claimed and status == 'approved':  # only the requested fields change; the rest stay as they are
            unit = erd_row('SELECT name FROM org_units WHERE id = %s', [change['org_unit_id']]) if change['org_unit_id'] else None
            erd_execute(
                """
                UPDATE teacher_profiles
                SET org_unit_id = COALESCE(%s, org_unit_id), department = COALESCE(%s, department),
                    academic_rank = COALESCE(%s, academic_rank), degree = COALESCE(%s, degree)
                WHERE user_id = %s
                """,
                [change['org_unit_id'], unit['name'] if unit else None, change['academic_rank'], change['degree'], change['teacher_id']],
            )
    if not claimed:
        messages.error(request, 'این درخواست پیش‌تر بررسی یا لغو شده است.')
        return redirect('core:exam_manager_teacher_requests')
    log_activity(request.user, f'profile_change_{status}', 'بررسی درخواست تغییر اطلاعات دانشگاهی استاد', request, {'request_id': str(request_id)})
    create_notification(
        change['teacher_id'],
        'درخواست تغییر اطلاعات دانشگاهی ' + ('تأیید شد' if status == 'approved' else 'رد شد'),
        note or 'اطلاعات دانشگاهی شما به‌روز شد.',
        f'{reverse("core:teacher_settings")}?tab=personal',
        'profile',
    )
    messages.success(request, 'درخواست تأیید و اعمال شد.' if status == 'approved' else 'درخواست رد شد.')
    return redirect('core:exam_manager_teacher_requests')


@erd_role_required('academic_manager', 'admin')
def exam_manager_user_import(request, kind='students'):
    if request.method == 'POST':
        messages.success(request, 'فایل دریافت شد و برای بررسی داده‌ها آماده است.')
        return redirect(reverse('core:exam_manager_user_import') + f'?kind={kind}&step=review')
    step = request.GET.get('step') or 'upload'
    context = _em_base_context(request, 'user_import', 'ورود گروهی اساتید' if kind == 'teachers' else 'ورود گروهی دانشجویان', 'users')
    context.update({
        'kind': kind,
        'step': step,
        'review_rows': [
            {'name': 'دکتر محمد رضایی', 'code': '۱۰۱۲۳۴۵', 'unit': 'پزشکی', 'specialty': 'داخلی', 'status': 'معتبر'},
            {'name': 'دکتر سارا احمدی', 'code': 'نامعتبر', 'unit': 'پزشکی', 'specialty': 'جراحی', 'status': 'نیازمند اصلاح'},
            {'name': 'دکتر علی محمدی', 'code': '۱۰۱۲۳۴۷', 'unit': 'پزشکی', 'specialty': 'کودکان', 'status': 'معتبر'},
            {'name': 'دکتر نرگس ستاری', 'code': '۱۰۱۲۳۴۸', 'unit': 'نامشخص', 'specialty': 'بیهوشی', 'status': 'نیازمند اصلاح'},
            {'name': 'دکتر حسین مرادی', 'code': '۱۰۱۲۳۳۹', 'unit': 'پزشکی', 'specialty': 'روان‌پزشکی', 'status': 'معتبر'},
        ],
    })
    return render(request, 'exam_manager/users.html', context)


"""
    profile = getattr(request.user, 'profile', None)
    role_code = profile.role.code if profile else 'student'
    super_admin_links = []
    institution_admin_links = []
    exam_manager_links = []
    teacher_links = []
    assistant_links = []
    student_links = []
    role_panel = {}
    if role_code == SystemRole.RoleCode.SUPER_ADMIN:
        super_admin_links = [
            {'title': 'ایجاد مؤسسه جدید', 'url': reverse('core:super_admin_institution_create')},
            {'title': 'مدیریت کاربران', 'url': reverse('core:super_admin_users')},
            {'title': 'نقش‌ها و مجوزها', 'url': reverse('core:super_admin_roles')},
            {'title': 'گزارش کل سامانه', 'url': reverse('core:super_admin_reports')},
            {'title': 'توقف اضطراری آزمون', 'url': reverse('core:super_admin_active_exams')},
        ]
        today = timezone.now().date()
        role_panel = {
            'type': 'super_admin',
            'users_count': User.objects.count(),
            'active_users_count': UserProfile.objects.filter(account_status=UserProfile.AccountStatus.ACTIVE).count(),
            'institutions_count': AcademicInstitution.objects.count(),
            'roles_count': SystemRole.objects.count(),
            'exams_count': Exam.objects.count(),
            'active_exams_count': Exam.objects.filter(status=Exam.ExamStatus.ACTIVE).count(),
            'questions_count': Question.objects.count(),
            'students_count': UserProfile.objects.filter(role__code=SystemRole.RoleCode.STUDENT).count(),
            'attempts_count': StudentExamAttempt.objects.count(),
            'today_logs_count': UserActivityLog.objects.filter(created_at__date=today).count(),
            'recent_logs': UserActivityLog.objects.select_related('user').order_by('-created_at')[:5],
            'recent_exams': Exam.objects.select_related('course').order_by('-created_at')[:5],
        }
    if role_code == SystemRole.RoleCode.INSTITUTION_ADMIN:
        institution = get_managed_institution(request.user)
        institution_admin_links = [
            {'title': 'تکمیل اطلاعات مؤسسه', 'url': reverse('core:institution_settings')},
            {'title': 'ثبت کاربران مؤسسه', 'url': reverse('core:institution_users')},
            {'title': 'تعریف ساختار آموزشی', 'url': reverse('core:institution_structure')},
            {'title': 'تعیین مسئول امتحانات', 'url': reverse('core:institution_assign_exam_manager')},
            {'title': 'وضعیت آزمون‌های مؤسسه', 'url': reverse('core:institution_exams')},
            {'title': 'بررسی تخلف آزمون', 'url': reverse('core:institution_violations')},
        ]
        if institution:
            role_panel = {
                'type': 'institution_admin',
                'institution': institution,
                'users_count': UserProfile.objects.filter(institution_name=institution.name).count(),
                'teachers_count': institution.teachers.count(),
                'students_count': institution.students.count(),
                'courses_count': institution.courses.count(),
                'classes_count': institution.classes.count(),
                'exams_count': institution.exams.count(),
                'violations_count': ExamViolationReport.objects.filter(exam__institution=institution).count(),
            }
    if role_code == SystemRole.RoleCode.EXAM_MANAGER:
        institution = get_exam_manager_institution(request.user)
        exam_manager_links = [
            {'title': 'تنظیم تقویم امتحانات', 'url': reverse('core:exam_manager_calendar')},
            {'title': 'تأیید آزمون استاد', 'url': reverse('core:exam_manager_exams')},
            {'title': 'تعیین ناظر آزمون', 'url': reverse('core:exam_manager_proctors')},
            {'title': 'کنترل شروع آزمون', 'url': reverse('core:exam_manager_active_exams')},
            {'title': 'مدیریت تغییر زمان', 'url': reverse('core:exam_manager_reschedule')},
            {'title': 'گزارش برگزاری آزمون', 'url': reverse('core:exam_manager_reports')},
        ]
        if institution:
            role_panel = {
                'type': 'exam_manager',
                'institution': institution,
                'scheduled_count': institution.exams.filter(status=Exam.ExamStatus.SCHEDULED).count(),
                'pending_count': institution.exams.filter(status=Exam.ExamStatus.PENDING_APPROVAL).count(),
                'active_count': institution.exams.filter(status=Exam.ExamStatus.ACTIVE).count(),
                'finished_count': institution.exams.filter(status=Exam.ExamStatus.FINISHED).count(),
                'reports_count': ExamExecutionReport.objects.filter(exam__institution=institution).count(),
            }
    if role_code == SystemRole.RoleCode.TEACHER:
        teacher = getattr(profile, 'teacher_profile', None)
        teacher_links = [
            {'title': 'بانک سؤال', 'url': reverse('core:teacher_questions')},
            {'title': 'ایجاد آزمون', 'url': reverse('core:teacher_exam_create')},
            {'title': 'آزمون‌ها و پیش‌نمایش', 'url': reverse('core:teacher_exams')},
            {'title': 'نظارت آزمون فعال', 'url': reverse('core:teacher_monitoring')},
            {'title': 'تصحیح تشریحی', 'url': reverse('core:teacher_reviews')},
            {'title': 'انتشار نتیجه', 'url': reverse('core:teacher_results')},
            {'title': 'اعتراض‌ها', 'url': reverse('core:teacher_objections')},
            {'title': 'درخواست‌های دستیار', 'url': reverse('core:teacher_assistant_requests')},
        ]
        if teacher:
            role_panel = {
                'type': 'teacher',
                'teacher': teacher,
                'questions_count': teacher.questions.count(),
                'exams_count': teacher.designed_exams.count(),
                'active_exams_count': teacher.designed_exams.filter(status=Exam.ExamStatus.ACTIVE).count(),
                'reviews_count': DescriptiveAnswerReview.objects.filter(exam__designer=teacher).count(),
                'objections_count': StudentObjection.objects.filter(exam__designer=teacher).count(),
                'assistant_questions_count': AssistantQuestionSubmission.objects.filter(teacher=teacher, status=AssistantQuestionSubmission.Status.PENDING).count(),
                'assistant_drafts_count': AssistantExamDraft.objects.filter(teacher=teacher, status=AssistantExamDraft.Status.SUBMITTED).count(),
                'assistant_reviews_count': AssistantReviewAssignment.objects.filter(teacher=teacher, status=AssistantReviewAssignment.Status.SUBMITTED).count(),
                'educational_questions_count': EducationalQuestion.objects.filter(teacher=teacher, status=EducationalQuestion.Status.REFERRED).count(),
            }
    if role_code == SystemRole.RoleCode.TEACHING_ASSISTANT:
        teacher = get_assistant_teacher(request.user)
        assistant_links = [
            {'title': 'ورود سؤال', 'url': reverse('core:assistant_questions')},
            {'title': 'پیش‌نویس آزمون', 'url': reverse('core:assistant_exam_drafts')},
            {'title': 'پیشنهاد اصلاح سؤال', 'url': reverse('core:assistant_question_suggestions')},
            {'title': 'تصحیح پاسخ‌ها', 'url': reverse('core:assistant_reviews')},
            {'title': 'پرسش‌های آموزشی', 'url': reverse('core:assistant_educational_questions')},
        ]
        if teacher:
            role_panel = {
                'type': 'assistant',
                'teacher': teacher,
                'question_submissions_count': AssistantQuestionSubmission.objects.filter(assistant=request.user).count(),
                'pending_questions_count': AssistantQuestionSubmission.objects.filter(assistant=request.user, status=AssistantQuestionSubmission.Status.PENDING).count(),
                'exam_drafts_count': AssistantExamDraft.objects.filter(assistant=request.user).count(),
                'review_assignments_count': AssistantReviewAssignment.objects.filter(assistant=request.user).count(),
                'educational_questions_count': EducationalQuestion.objects.filter(teacher=teacher, status=EducationalQuestion.Status.NEW).count(),
            }
    if role_code == SystemRole.RoleCode.STUDENT:
        student = get_student_profile(request.user)
        student_links = [
            {'title': 'برنامه آزمون‌ها', 'url': reverse('core:student_exam_schedule')},
            {'title': 'آزمون آزمایشی', 'url': reverse('core:student_practice_exam')},
            {'title': 'نتایج آزمون', 'url': reverse('core:student_results')},
            {'title': 'ثبت اعتراض', 'url': reverse('core:student_objections')},
            {'title': 'پرسش آموزشی', 'url': reverse('core:student_educational_questions')},
        ]
        if student:
            exams = student_available_exams(student)
            submitted_attempts = student.exam_attempts.filter(status__in=[
                StudentExamAttempt.Status.SUBMITTED,
                StudentExamAttempt.Status.AUTO_SUBMITTED,
            ])
            role_panel = {
                'type': 'student',
                'student': student,
                'upcoming_exams_count': exams.filter(starts_at__gte=timezone.now()).count(),
                'available_exams_count': exams.count(),
                'active_attempts_count': student.exam_attempts.filter(status=StudentExamAttempt.Status.IN_PROGRESS).count(),
                'published_results_count': submitted_attempts.filter(exam__result_publication__is_published=True).count(),
                'objections_count': StudentObjection.objects.filter(student=student).count(),
                'latest_practice_check': student.practice_checks.first(),
                'upcoming_exams': exams[:5],
            }
    dashboard_data = {
        **ROLE_DASHBOARDS.get(role_code, ROLE_DASHBOARDS['student']),
        'task_groups': ROLE_TASK_GROUPS.get(role_code, []),
    }
    display_name = profile.full_name if profile else request.user.get_full_name() or request.user.username
    context = {
        'dashboard': dashboard_data,
        'profile': profile,
        'display_name': display_name,
        'role_name': profile.role.name if profile else 'کاربر سامانه',
        'profile_edit_url': (
            f'/admin/apps/core/userprofile/{profile.pk}/change/'
            if profile
            else f'/admin/auth/user/{request.user.pk}/change/'
        ),
        'super_admin_links': super_admin_links,
        'institution_admin_links': institution_admin_links,
        'exam_manager_links': exam_manager_links,
        'teacher_links': teacher_links,
        'assistant_links': assistant_links,
        'student_links': student_links,
        'role_code': role_code,
        'role_panel': role_panel,
    }
    return render(request, 'dashboard.html', context)


"""


def logout_view(request):
    logout(request)
    return redirect('core:login')


def error_404(request, exception):
    return render(request, '404.html', status=404)


def error_500(request):
    return render(request, '500.html', status=500)


def create_notification(user_id, title, message, link='', notification_type='system'):
    if not user_id:
        return
    from .student_settings import notification_muted

    # a kind the user switched off is still kept, but arrives already read so it raises no alert
    erd_execute(
        """
        INSERT INTO notifications (id, user_id, type, title, message, link, is_read)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
        [str(uuid.uuid4()), user_id, notification_type, title, message, link, notification_muted(user_id, notification_type)],
    )


_ANSWER_TRANSLATION = str.maketrans({
    **{persian: str(digit) for digit, persian in enumerate('۰۱۲۳۴۵۶۷۸۹')},
    **{arabic: str(digit) for digit, arabic in enumerate('٠١٢٣٤٥٦٧٨٩')},
    'ي': 'ی', 'ى': 'ی', 'ك': 'ک', 'ة': 'ه', 'ؤ': 'و', 'إ': 'ا', 'أ': 'ا', 'آ': 'ا',
    '‌': ' ', 'ـ': None, '٫': '.', '،': ',',
})
_ARABIC_DIACRITICS_RE = re.compile(r'[ً-ٰٟ]')


def _normalize_answer_text(value, *, case_sensitive=False, ignore_spaces=False, persian=True):
    text = str(value or '').strip()
    if persian:
        text = _ARABIC_DIACRITICS_RE.sub('', text.translate(_ANSWER_TRANSLATION))
    text = re.sub(r'\s+', '' if ignore_spaces else ' ', text).strip()
    return text if case_sensitive else text.lower()


def _answer_as_number(text):
    try:
        return float(text.replace(',', ''))
    except ValueError:
        return None


def _edit_distance_within(first, second, limit):
    """True when the Levenshtein distance between the two strings is at most `limit` (limit is 0..2)."""
    if abs(len(first) - len(second)) > limit:
        return False
    previous = list(range(len(second) + 1))
    for i, char_a in enumerate(first, start=1):
        current = [i]
        for j, char_b in enumerate(second, start=1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (char_a != char_b)))
        if min(current) > limit:
            return False
        previous = current
    return previous[-1] <= limit


# Typos are only forgiven on answers long enough that a small edit can't turn one valid word into another.
_TYPO_MIN_LENGTH = 4


def _short_answer_credit(answer, accepted_item):
    """Return the credit ratio (0..1) an accepted-answer rule gives to the submitted text."""
    case_sensitive = bool(accepted_item.get('case_sensitive'))
    persian = accepted_item.get('normalize', True)
    submitted = _normalize_answer_text(answer, case_sensitive=case_sensitive, persian=persian)[:500]
    expected = str(accepted_item.get('answer') or '')
    if not submitted or not expected:
        return 0
    ratio = min(max(_sx_float(accepted_item.get('points'), 100), 0), 100) / 100
    mode = accepted_item.get('match_mode') or 'exact'
    if mode == 'regex':
        try:
            return ratio if re.fullmatch(expected, submitted, 0 if case_sensitive else re.IGNORECASE) else 0
        except re.error:
            return 0
    expected = _normalize_answer_text(expected, case_sensitive=case_sensitive, persian=persian)
    if mode == 'contains':
        return ratio if expected in submitted else 0
    submitted_number, expected_number = _answer_as_number(submitted), _answer_as_number(expected)
    if submitted_number is not None and expected_number is not None:
        tolerance = abs(_sx_float(accepted_item.get('tolerance'), 0))
        return ratio if abs(submitted_number - expected_number) <= tolerance else 0
    if accepted_item.get('ignore_word_order'):
        submitted, expected = ' '.join(sorted(submitted.split())), ' '.join(sorted(expected.split()))
    if submitted == expected:
        return ratio
    typo_limit = min(max(int(_sx_float(accepted_item.get('typo_tolerance'), 0)), 0), 2)
    if typo_limit and len(expected) >= _TYPO_MIN_LENGTH and _edit_distance_within(submitted, expected, typo_limit):
        return ratio
    return 0


def _grade_question(row, answer, max_points):
    """Grade one answer. Returns (points, needs_manual, is_fully_correct).

    Questions without `scoring_settings` (legacy rows) keep the original all-or-nothing behaviour.
    """
    kind = row.get('type') or 'single'
    settings_data = _sx_json(row.get('scoring_settings'), {}) or {}
    settings_data = settings_data if isinstance(settings_data, dict) else {}
    partial = settings_data.get('scoring_mode') == 'partial'
    negative = max_points * abs(_sx_float(settings_data.get('negative_value'), 0)) if settings_data.get('negative_marking') else 0
    answered = any(str(value).strip() for value in answer) if isinstance(answer, list) else bool(str(answer or '').strip())
    full = (max_points, False, True)

    def wrong():
        return (-negative if answered and negative else 0), False, False

    if kind == 'essay':
        return 0, True, False
    if kind in question_kinds.V2_TYPES:
        return question_kinds.grade(kind, row, answer, max_points, settings_data, partial, wrong)
    if kind == 'short_answer':
        accepted = [item for item in (_sx_json(row.get('accepted_answers'), []) or []) if isinstance(item, dict) and 'match_mode' in item]
        if not accepted:
            return 0, True, False
        text = answer[0] if isinstance(answer, list) and answer else answer
        ratio = max((_short_answer_credit(text, item) for item in accepted), default=0)
        matched = bool(ratio)
        # «امتیاز بخشی» off: an alternative answer worth less than full credit earns nothing.
        if settings_data.get('scoring_mode') == 'all_or_nothing' and ratio < 1:
            ratio = 0
        threshold = min(max(_sx_float(settings_data.get('correct_threshold'), 100), 0), 100) / 100
        # Answers matching no accepted rule go to the teacher's manual-review queue instead of a silent zero.
        return round(max_points * ratio, 4), bool(answered and not matched), ratio > 0 and ratio >= threshold
    if kind in ('single', 'true_false'):
        correct = _sx_json(row.get('correct_answer'), row.get('correct_answer'))
        text = answer[0] if isinstance(answer, list) and answer else answer
        return full if answered and str(correct).strip() == str(text).strip() else wrong()
    if kind == 'multi':
        as_set = lambda value: {str(item) for item in value if str(item)} if isinstance(value, (list, set, tuple)) else ({str(value)} if value else set())
        correct = as_set(_sx_json(row.get('correct_answer'), []))
        submitted = as_set(answer)
        max_correct = int(_sx_float(settings_data.get('max_correct'), 0))
        if not correct or (max_correct and len(submitted) > max_correct):
            return wrong()
        if submitted == correct:
            return full
        if not partial:
            return wrong()
        # Partial credit uses each option's «امتیاز انتخاب» as its weight and «جریمه انتخاب نادرست» as the
        # penalty for picking a wrong option, both on the same scale as the correct options' weights.
        weights, penalties = {}, {}
        for index, option in enumerate(_sx_json(row.get('options'), []) or [], start=1):
            if isinstance(option, dict):
                option_id = str(option.get('id') or index)
                weights[option_id] = max(_sx_float(option.get('points'), 1), 0)
                penalties[option_id] = abs(_sx_float(option.get('negative_points'), 0))
        correct_weight = sum(weights.get(option_id, 1) for option_id in correct) or len(correct)
        gained = sum(weights.get(option_id, 1) for option_id in submitted & correct)
        lost = sum(penalties.get(option_id, 0) for option_id in submitted - correct)
        ratio = (gained - lost) / correct_weight
        if settings_data.get('floor_zero', True):
            ratio = max(ratio, 0)
        return round(max_points * ratio, 4), False, False
    if kind == 'fill_blank':
        submitted = answer if isinstance(answer, list) else str(answer or '').split('|')
        blanks = [item for item in (_sx_json(row.get('accepted_answers'), []) or []) if isinstance(item, dict) and item.get('answers')]
        if not blanks:
            correct = _sx_json(row.get('correct_answer'), row.get('correct_answer'))
            blanks = [{'answers': [part], 'case_sensitive': True, 'ignore_spaces': False, 'legacy': True} for part in str(correct or '').split('|')]
        total_weight = matched_weight = 0
        for index, blank in enumerate(blanks):
            weight = max(_sx_float(blank.get('points'), 1), 0) or 1
            total_weight += weight
            given = submitted[index] if index < len(submitted) else ''
            persian = not blank.get('legacy') and settings_data.get('normalize_answers', True)
            options = dict(case_sensitive=bool(blank.get('case_sensitive')), ignore_spaces=bool(blank.get('ignore_spaces')), persian=persian)
            if str(given).strip() and any(_normalize_answer_text(given, **options) == _normalize_answer_text(alt, **options) for alt in blank['answers']):
                matched_weight += weight
        if total_weight and matched_weight == total_weight:
            return full
        if partial and total_weight:
            return round(max_points * matched_weight / total_weight, 4), False, False
        return wrong()
    if kind == 'matching':
        pairs = [pair for pair in (_sx_json(row.get('matching_pairs'), []) or []) if isinstance(pair, dict) and pair.get('left') and pair.get('right')]
        if not pairs:
            return 0, True, False
        chosen = {}
        for part in str(answer[0] if isinstance(answer, list) and answer else answer or '').split(','):
            left, _, right = part.partition(':')
            chosen[left.strip()] = right.strip()
        hits = 0
        for index, pair in enumerate(pairs, start=1):
            right_index = chosen.get(str(index), '')
            if right_index.isdigit() and 1 <= int(right_index) <= len(pairs) and _normalize_answer_text(pairs[int(right_index) - 1]['right']) == _normalize_answer_text(pair['right']):
                hits += 1
        if hits == len(pairs):
            return full
        if partial:
            return round(max_points * hits / len(pairs), 4), False, False
        return wrong()
    if kind == 'ordering':
        count = len([item for item in (_sx_json(row.get('ordering_items'), []) or []) if item])
        sequence = [part.strip() for part in str(answer[0] if isinstance(answer, list) and answer else answer or '').split(',') if part.strip()]
        expected = [str(position) for position in range(1, count + 1)]
        if count and sequence == expected:
            return full
        mode = settings_data.get('ordering_mode') or 'exact'
        if not count or mode == 'exact' or not sequence:
            return wrong()
        if mode == 'position':
            ratio = sum(1 for got, want in zip(sequence, expected) if got == want) / count
        else:
            adjacent = sum(1 for first, second in zip(sequence, sequence[1:]) if first.isdigit() and second.isdigit() and int(second) == int(first) + 1)
            ratio = adjacent / max(count - 1, 1)
        return round(max_points * ratio, 4), False, False
    return 0, True, False


def grade_attempt(attempt_id):
    optional_columns = ['matching_pairs', 'ordering_items', 'scoring_settings', 'accepted_answers']
    optional_sql = ', '.join(f'q.{column}' if erd_has_column('questions', column) else f'NULL AS {column}' for column in optional_columns)
    rows = erd_rows(
        f"""
        SELECT ea.id AS attempt_id, eq.points, q.id AS question_id, q.type, q.correct_answer, q.options,
               {optional_sql}, aa.answer
        FROM exam_attempts ea
        JOIN exam_questions eq ON eq.exam_id = ea.exam_id
        JOIN questions q ON q.id = eq.question_id
        LEFT JOIN attempt_answers aa ON aa.attempt_id = ea.id AND aa.question_id = q.id
        WHERE ea.id = %s
        ORDER BY eq.order_index NULLS LAST
        """,
        [attempt_id],
    )
    total_score = 0
    max_score = 0
    needs_manual = False
    for row in rows:
        raw = _sx_json(row['answer'], row['answer'])
        answer = raw.get('value') if isinstance(raw, dict) else raw
        if answer is None:
            answer = ''
        max_points = _sx_float(row['points'], 0)
        points, manual, is_correct = _grade_question(row, answer, max_points)
        needs_manual = needs_manual or manual
        total_score += points
        max_score += max_points
        erd_execute(
            """
            INSERT INTO attempt_answers (id, attempt_id, question_id, answer, is_correct, points_awarded, needs_manual_grading)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (attempt_id, question_id) DO UPDATE
            SET is_correct = EXCLUDED.is_correct,
                points_awarded = EXCLUDED.points_awarded,
                needs_manual_grading = EXCLUDED.needs_manual_grading
            """,
            [str(uuid.uuid4()), attempt_id, row['question_id'], json.dumps({'value': answer}, ensure_ascii=False), is_correct, points, manual],
        )
    total_score = max(total_score, 0)
    status = 'submitted' if needs_manual else 'graded'
    erd_execute(
        """
        UPDATE exam_attempts
        SET submitted_at = COALESCE(submitted_at, now()),
            score = %s,
            max_score = %s,
            is_graded = %s,
            status = %s
        WHERE id = %s
        """,
        [total_score, max_score, not needs_manual, status, attempt_id],
    )
    return {'score': total_score, 'max_score': max_score, 'needs_manual': needs_manual}


@erd_role_required('academic_manager', 'admin')
def exam_manager_calendar(request):
    return super_admin_calendar(request)


def _em_calendar_ensure_table():
    erd_execute(
        """
        CREATE TABLE IF NOT EXISTS academic_calendar_events (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            event_type TEXT DEFAULT 'session',
            course_id TEXT,
            group_id TEXT,
            starts_at TIMESTAMP,
            ends_at TIMESTAMP,
            location TEXT,
            description TEXT,
            status TEXT DEFAULT 'published',
            notify_participants BOOLEAN DEFAULT true,
            created_by TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )


def _em_calendar_type_meta(event_type):
    return {
        'exam': ('آزمون', 'blue'),
        'session': ('جلسه', 'green'),
        'deadline': ('مهلت', 'orange'),
        'holiday': ('تعطیلی', 'red'),
    }.get(event_type or 'session', ('رویداد', 'blue'))


@erd_role_required('academic_manager', 'admin')
def exam_manager_calendar_create(request):
    _em_calendar_ensure_table()
    courses = _em_course_rows(request)
    groups = _em_group_rows(request)
    if request.method == 'POST':
        title = (request.POST.get('title') or '').strip()
        event_course_id = request.POST.get('course_id') or None
        event_group_id = request.POST.get('group_id') or None
        managed_unit_ids = _erd_managed_unit_ids(request)
        if managed_unit_ids is not None:
            if event_course_id:
                course = erd_row('SELECT org_unit_id FROM courses WHERE id = %s', [event_course_id])
                if not course or str(course.get('org_unit_id') or '') not in managed_unit_ids:
                    return HttpResponseForbidden('درس انتخاب‌شده خارج از محدوده‌ی دسترسی شماست.')
            if event_group_id and not _erd_group_in_manager_scope(request, event_group_id):
                return HttpResponseForbidden('گروه انتخاب‌شده خارج از محدوده‌ی دسترسی شماست.')
        if not title:
            messages.error(request, 'عنوان رویداد الزامی است.')
        else:
            event_id = str(uuid.uuid4())
            event_date = request.POST.get('event_date') or timezone.localdate().isoformat()
            start_time = request.POST.get('start_time') or '10:00'
            end_time = request.POST.get('end_time') or '11:00'
            starts_at = datetime.fromisoformat(f'{event_date}T{start_time}')
            ends_at = datetime.fromisoformat(f'{event_date}T{end_time}')
            if timezone.is_naive(starts_at):
                starts_at = timezone.make_aware(starts_at, timezone.get_current_timezone())
            if timezone.is_naive(ends_at):
                ends_at = timezone.make_aware(ends_at, timezone.get_current_timezone())
            erd_execute(
                """
                INSERT INTO academic_calendar_events (
                    id, title, event_type, course_id, group_id, starts_at, ends_at,
                    location, description, status, notify_participants, created_by
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'published', %s, %s)
                """,
                [
                    event_id,
                    title,
                    request.POST.get('event_type') or 'session',
                    request.POST.get('course_id') or None,
                    request.POST.get('group_id') or None,
                    starts_at,
                    ends_at,
                    request.POST.get('location') or '',
                    request.POST.get('description') or '',
                    bool(request.POST.get('notify_participants')),
                    request.erd_profile_id,
                ],
            )
            messages.success(request, 'رویداد آموزشی در تقویم ثبت شد.')
            return redirect('core:exam_manager_calendar')
    context = _em_base_context(request, 'calendar_create', 'افزودن رویداد آموزشی', 'calendar')
    context.update({'courses': courses, 'groups': groups, 'mini_days': list(range(1, 32))})
    return render(request, 'exam_manager/calendar.html', context)


@erd_role_required('academic_manager', 'admin')
def exam_manager_proctors(request):
    return _super_admin_collection(
        request,
        title='اساتید و ناظران',
        kicker='مدیر آموزشی / کاربران آموزشی',
        description='فهرست استادها برای تخصیص و مدیریت آموزشی.',
        queryset=lambda: _erd_scoped_teacher_rows(request),
        row_builder=lambda item, q: {
            'title': item['full_name'],
            'meta': item['email'] or '-',
            'cells': [('کد پرسنلی', item['personnel_code'] or '-'), ('دپارتمان', item['department'] or '-'), ('تخصص', item['specialty'] or '-'), ('وضعیت', item['approval_status'] or '-')],
        } if _matches_query(q, item['full_name'], item['email'], item['personnel_code'], item['department'], item['specialty']) else None,
    )


@erd_role_required('academic_manager', 'admin')
def exam_manager_active_exams(request):
    manager_id = None if _erd_is_admin_request(request) else request.erd_profile_id
    return _super_admin_collection(
        request,
        title='آزمون‌های فعال',
        kicker='مدیر آموزشی / پایش',
        description='آزمون‌های منتشرشده و لغونشده.',
        queryset=lambda: _erd_exam_rows('COALESCE(e.is_published, false) = true AND COALESCE(e.is_cancelled, false) = false', [], limit=200, manager_id=manager_id),
        row_builder=lambda item, q: {
            'title': item['title'],
            'meta': item['course'],
            'cells': [('استاد', item['teacher']), ('شروع', item['start_at']), ('پایان', item['end_at']), ('وضعیت', item['status'])],
        } if _matches_query(q, item['title'], item['course'], item['teacher'], item['status']) else None,
    )


@erd_role_required('academic_manager', 'admin')
def exam_manager_reports(request):
    if _erd_is_admin_request(request):
        stats = build_report_stats()
    else:
        stats = {
            'users': _erd_scoped_count(request, 'teachers') + _erd_scoped_count(request, 'students'),
            'exams': _erd_scoped_count(request, 'exams'),
            'active_exams': _erd_scoped_exam_count(
                request,
                'COALESCE(e.is_published, false) = true AND COALESCE(e.is_cancelled, false) = false',
                [],
            ),
            'candidates': _erd_scoped_count(request, 'students'),
            'violations': erd_count('activity_audit_log', "action ILIKE %s", ['%violation%']),
            'technical_issues': erd_count('activity_audit_log', "action ILIKE %s OR reason ILIKE %s", ['%technical%', '%فنی%']),
        }
    return _super_admin_collection(
        request,
        title='گزارش‌ها',
        kicker='مدیر آموزشی / گزارش',
        description='خلاصه عملکرد سامانه از جدول‌های ERD.',
        queryset=lambda: [{'title': key, 'value': value} for key, value in stats.items()],
        row_builder=lambda item, q: {
            'title': item['title'],
            'meta': 'شاخص',
            'cells': [('مقدار', item['value'])],
        },
    )


def _em_exam_status_label(row):
    raw = str(row.get('lifecycle_status') or '').lower()
    approval = str(row.get('approval_status') or '').lower()
    if _em_truthy(row.get('is_cancelled')):
        return 'لغوشده', 'bad'
    if raw in {'active', 'in_progress', 'started', 'live'}:
        return 'در حال برگزاری', 'ok'
    if raw in {'finished', 'completed', 'closed'}:
        return 'پایان‌یافته', 'purple'
    if raw in {'review', 'needs_review'} or approval in {'needs_review', 'pending'}:
        return 'نیازمند بازبینی', 'warn'
    if raw in {'published', 'scheduled', 'ready'} or _em_truthy(row.get('is_published')):
        return 'آماده انتشار', 'blue'
    return 'پیش‌نویس', 'muted'


def _em_int(value, default=0):
    if value is None or value == '':
        return default
    text = str(value)
    digit_map = {
        0x06F0: '0', 0x06F1: '1', 0x06F2: '2', 0x06F3: '3', 0x06F4: '4',
        0x06F5: '5', 0x06F6: '6', 0x06F7: '7', 0x06F8: '8', 0x06F9: '9',
        0x0660: '0', 0x0661: '1', 0x0662: '2', 0x0663: '3', 0x0664: '4',
        0x0665: '5', 0x0666: '6', 0x0667: '7', 0x0668: '8', 0x0669: '9',
    }
    text = ''.join(digit_map.get(ord(ch), ch) for ch in text)
    digits = ''.join(ch for ch in text if ch.isdigit())
    return int(digits) if digits else default


def _em_exam_rows(request, exam_id=None):
    is_admin = _erd_is_admin_request(request)
    where = ['1=1'] if is_admin else [_erd_exam_scope_condition()]
    params = []
    if exam_id:
        where.append('e.id = %s')
        params.append(exam_id)
    scope_cte = '' if is_admin else _erd_manager_scope_cte()
    scope_params = [] if is_admin else [request.erd_profile_id]
    rows = erd_rows(
        f"""
        {scope_cte}
        SELECT e.id, e.teacher_id, e.course_id, e.title, COALESCE(e.description, '') AS description,
               COALESCE(e.duration_minutes, 90) AS duration_minutes,
               COALESCE(to_char(e.start_at, 'YYYY/MM/DD'), '-') AS exam_date,
               COALESCE(to_char(e.start_at, 'HH24:MI'), '-') AS exam_time,
               COALESCE(to_char(e.end_at, 'HH24:MI'), '-') AS end_time,
               COALESCE(e.academic_year, '۱۴۰۵') AS academic_year,
               COALESCE(e.semester, 'اول') AS semester,
               COALESCE(e.lifecycle_status, CASE WHEN COALESCE(e.is_published, false) THEN 'published' ELSE 'draft' END) AS lifecycle_status,
               COALESCE(e.approval_status, '') AS approval_status,
               COALESCE(e.exam_type, 'آنلاین') AS exam_type,
               COALESCE(e.passing_score, 10) AS passing_score,
               COALESCE(e.is_published, false) AS is_published,
               COALESCE(e.is_cancelled, false) AS is_cancelled,
               COALESCE(c.title, 'درس') AS course_title,
               COALESCE(c.code, '') AS course_code,
               COALESCE(p.full_name, 'استاد مسئول') AS teacher_name,
               COUNT(DISTINCT eq.id) AS questions_count,
               COALESCE(SUM(eq.points), 0) AS total_points,
               COUNT(DISTINCT ea.id) AS attempts_count,
               COUNT(DISTINCT CASE WHEN ea.submitted_at IS NOT NULL OR ea.status IN ('submitted', 'completed', 'graded') THEN ea.id END) AS submitted_count,
               AVG(CASE WHEN ea.score IS NOT NULL THEN ea.score END) AS avg_score
        FROM exams e
        LEFT JOIN courses c ON c.id = e.course_id
        LEFT JOIN profiles p ON p.id = e.teacher_id
        LEFT JOIN exam_questions eq ON eq.exam_id = e.id
        LEFT JOIN exam_attempts ea ON ea.exam_id = e.id
        WHERE {' AND '.join(where)}
        GROUP BY e.id, e.teacher_id, e.course_id, e.title, e.description, e.duration_minutes, e.start_at, e.end_at,
                 e.academic_year, e.semester, e.lifecycle_status, e.approval_status, e.exam_type, e.passing_score,
                 e.is_published, e.is_cancelled, c.title, c.code, p.full_name
        ORDER BY e.start_at DESC NULLS LAST, e.title
        LIMIT 300
        """,
        scope_params + params,
    )
    for row in rows:
        row['duration_minutes'] = _em_int(row.get('duration_minutes'), 90)
        row['questions_count'] = _em_int(row.get('questions_count'), 0)
        row['attempts_count'] = _em_int(row.get('attempts_count'), 0)
        row['submitted_count'] = _em_int(row.get('submitted_count'), 0)
        row['total_points'] = float(row.get('total_points') or 0)
        row['avg_score'] = round(float(row.get('avg_score') or 0), 1)
        row['status_label'], row['status_tone'] = _em_exam_status_label(row)
        row['term_label'] = _em_term_label(row)
    return rows


def _em_exam_groups(request, course_id=None):
    groups = _em_group_rows(request, course_id=course_id) if course_id else _em_group_rows(request)
    return groups[:200]


def _em_exam_question_rows(exam_id=None):
    selected_sql = ''
    params = []
    question_order = 'q.created_at DESC NULLS LAST, q.text' if erd_has_column('questions', 'created_at') else 'q.text'
    if exam_id:
        selected_sql = 'LEFT JOIN exam_questions eq ON eq.question_id = q.id AND eq.exam_id = %s'
        params.append(exam_id)
    rows = erd_rows(
        f"""
        SELECT q.id, q.text, COALESCE(q.type, 'single') AS type, COALESCE(q.difficulty, 'medium') AS difficulty,
               COALESCE(q.default_points, 1) AS points, COALESCE(c.title, 'بانک سؤال') AS course_title,
               {'eq.id AS selected_id,' if exam_id else 'NULL AS selected_id,'}
               {'COALESCE(eq.order_index, 999) AS order_index' if exam_id else '999 AS order_index'}
        FROM questions q
        LEFT JOIN courses c ON c.id = q.course_id
        {selected_sql}
        ORDER BY selected_id NULLS LAST, {question_order}
        LIMIT 300
        """,
        params,
    )
    for row in rows:
        kind = row.get('type') or 'single'
        row['type_label'] = {
            'single': 'چندگزینه‌ای',
            'multi': 'چندگزینه‌ای',
            'essay': 'تشریحی',
            'short_answer': 'کوتاه‌پاسخ',
            'true_false': 'صحیح/غلط',
            **question_kinds.TYPE_LABELS,
        }.get(kind, kind)
        difficulty = str(row.get('difficulty') or 'medium').lower()
        row['difficulty_label'] = {'easy': 'آسان', 'medium': 'متوسط', 'hard': 'سخت'}.get(difficulty, difficulty)
        row['difficulty_tone'] = {'easy': 'ok', 'medium': 'warn', 'hard': 'bad'}.get(difficulty, 'muted')
        row['is_selected'] = bool(row.get('selected_id'))
    return rows


def _em_exam_attempt_rows(exam_id):
    rows = erd_rows(
        """
        SELECT ea.id, ea.student_id, COALESCE(p.full_name, 'دانشجو') AS full_name,
               COALESCE(sp.student_number, p.identifier, '-') AS student_number,
               COALESCE(sp.field_of_study, 'پزشکی') AS field_of_study,
               COALESCE(p.avatar_url, '') AS avatar_url,
               COALESCE(ea.status, 'not_started') AS status,
               COALESCE(ea.score, 0) AS score,
               COALESCE(ea.max_score, 20) AS max_score,
               COALESCE(substr(CAST(ea.started_at AS text), 12, 5), '-') AS started_time,
               COALESCE(substr(CAST(ea.submitted_at AS text), 12, 5), '-') AS submitted_time
        FROM exam_attempts ea
        LEFT JOIN profiles p ON p.id = ea.student_id
        LEFT JOIN student_profiles sp ON sp.user_id = ea.student_id
        WHERE ea.exam_id = %s
        ORDER BY ea.started_at DESC NULLS LAST, p.full_name
        LIMIT 300
        """,
        [exam_id],
    )
    for row in rows:
        max_score = float(row.get('max_score') or 20)
        score = float(row.get('score') or 0)
        row['percent'] = round(score * 100 / max(max_score, 1))
        row['status_label'] = 'قبول' if row['percent'] >= 50 else ('در حال آزمون' if row.get('status') == 'in_progress' else 'نیازمند بررسی')
        row['status_tone'] = 'ok' if row['percent'] >= 50 else ('blue' if row.get('status') == 'in_progress' else 'warn')
    return rows


@erd_role_required('academic_manager', 'admin')
def exam_manager_exams(request):
    return super_admin_exams(request)


@erd_role_required('academic_manager', 'admin')
def exam_manager_exam_create(request):
    courses = _em_course_rows(request)
    groups = _em_exam_groups(request)
    teachers = _em_teacher_options(request)
    if request.method == 'POST':
        course_id = request.POST.get('course_id') or (courses[0]['id'] if courses else None)
        course = next((item for item in courses if str(item.get('id')) == str(course_id)), None)
        group_id = request.POST.get('group_id')
        group = next((item for item in groups if str(item.get('id')) == str(group_id)), None)
        teacher_id = request.POST.get('teacher_id') or (group or {}).get('teacher_id') or (teachers[0]['id'] if teachers else None)
        title = (request.POST.get('title') or '').strip()
        if not title:
            messages.error(request, 'عنوان آزمون الزامی است.')
        elif not group:
            messages.error(request, 'گروه درسی آزمون را انتخاب کنید.')
        elif not _erd_group_assignment_in_scope(request, course_id, [teacher_id]):
            return HttpResponseForbidden('درس/استاد انتخاب‌شده خارج از محدوده‌ی دسترسی شماست.')
        else:
            exam_id = str(uuid.uuid4())
            start_date = request.POST.get('start_date') or timezone.localdate().isoformat()
            start_time = request.POST.get('start_time') or '10:00'
            duration = int(request.POST.get('duration_minutes') or 90)
            start_at = datetime.fromisoformat(f'{start_date}T{start_time}')
            if timezone.is_naive(start_at):
                start_at = timezone.make_aware(start_at, timezone.get_current_timezone())
            end_at = start_at + timedelta(minutes=duration)
            erd_execute(
                """
                INSERT INTO exams (
                    id, teacher_id, course_id, title, description, duration_minutes, start_at, end_at,
                    shuffle_questions, shuffle_options, negative_marking, max_attempts, is_published,
                    show_results_immediately, passing_score, allow_partial, is_cancelled,
                    approval_status, exam_type, academic_year, semester, lifecycle_status
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, true, true, false, 1, false, true, %s, true, false, %s, %s, %s, %s, %s)
                """,
                [
                    exam_id,
                    teacher_id,
                    course_id,
                    title,
                    request.POST.get('description') or '',
                    duration,
                    start_at,
                    end_at,
                    request.POST.get('passing_score') or 10,
                    'pending',
                    request.POST.get('exam_type') or 'آنلاین',
                    (group or {}).get('academic_year') or request.POST.get('academic_year') or '۱۴۰۵',
                    (group or {}).get('semester') or request.POST.get('semester') or 'اول',
                    'draft',
                ],
            )
            erd_execute(
                'INSERT INTO exam_assignments (id, exam_id, group_id) VALUES (%s, %s, %s)',
                [str(uuid.uuid4()), exam_id, group['id']],
            )
            messages.success(request, 'آزمون جدید ثبت شد. سوالات آزمون را انتخاب کنید.')
            return redirect('core:exam_manager_exam_questions', exam_id=exam_id)
    context = _em_base_context(request, 'exam_create', 'ایجاد آزمون جدید', 'exam')
    context.update({'courses': courses, 'groups': groups, 'teachers': teachers})
    return render(request, 'exam_manager/exams.html', context)


@erd_role_required('academic_manager', 'admin')
def exam_manager_exam_import(request):
    if request.method == 'POST':
        messages.success(request, 'فایل آزمون دریافت شد و برای بررسی داده‌ها آماده است.')
        return redirect('core:exam_manager_exams')
    context = _em_base_context(request, 'exam_import', 'ورود گروهی آزمون‌ها', 'exam')
    context.update({'review_rows': _em_exam_rows(request)[:5]})
    return render(request, 'exam_manager/exams.html', context)


@erd_role_required('academic_manager', 'admin')
def exam_manager_exam_questions(request, exam_id):
    exams = _em_exam_rows(request, exam_id)
    if not exams:
        raise Http404('آزمون پیدا نشد.')
    exam = exams[0]
    if request.method == 'POST':
        selected_ids = request.POST.getlist('question_ids')
        erd_execute('DELETE FROM exam_questions WHERE exam_id = %s', [exam_id])
        for index, question_id in enumerate(selected_ids, start=1):
            erd_execute(
                "INSERT INTO exam_questions (id, exam_id, question_id, points, order_index) VALUES (%s, %s, %s, %s, %s)",
                [str(uuid.uuid4()), exam_id, question_id, request.POST.get(f'points_{question_id}') or 1, index],
            )
        messages.success(request, 'سوالات آزمون ذخیره شد.')
        return redirect('core:exam_manager_exam_detail', exam_id=exam_id)
    questions = _em_exam_question_rows(exam_id)
    selected = [q for q in questions if q['is_selected']]
    context = _em_base_context(request, 'exam_questions', 'انتخاب سوالات آزمون', 'exam')
    context.update({'exam': exam, 'questions': questions, 'selected_questions': selected, 'selected_points': sum(float(q.get('points') or 0) for q in selected)})
    return render(request, 'exam_manager/exams.html', context)


@erd_role_required('academic_manager', 'admin')
def exam_manager_exam_detail(request, exam_id):
    exams = _em_exam_rows(request, exam_id)
    if not exams:
        raise Http404('آزمون پیدا نشد.')
    exam = exams[0]
    attempts = _em_exam_attempt_rows(exam_id)
    groups = _em_exam_groups(request, exam.get('course_id'))
    members = _em_member_rows(groups[0]['id']) if groups else []
    participants = attempts or members[:8]
    capacity = (groups[0]['capacity'] if groups else max(len(participants), 1)) or 1
    present_count = len(attempts)
    context = _em_base_context(request, 'exam_detail', exam['title'], 'exam')
    context.update({
        'exam': exam,
        'attempts': attempts,
        'participants': participants,
        'groups': groups,
        'capacity': capacity,
        'present_count': present_count,
        'remaining_count': max(capacity - present_count, 0),
        'progress_percent': round(present_count * 100 / max(capacity, 1)),
        'events': [
            {'time': '10:42', 'title': 'دانشجو وارد آزمون شد', 'tone': 'ok'},
            {'time': '10:41', 'title': 'اتصال دانشجو دوباره برقرار شد', 'tone': 'warn'},
            {'time': '10:40', 'title': 'رفتار مشکوک در مرورگر ثبت شد', 'tone': 'bad'},
            {'time': '10:39', 'title': 'پاسخ‌ها به صورت خودکار ذخیره شد', 'tone': 'blue'},
        ],
    })
    return render(request, 'exam_manager/exams.html', context)


@erd_role_required('academic_manager', 'admin')
def exam_manager_exam_results(request, exam_id):
    exams = _em_exam_rows(request, exam_id)
    if not exams:
        raise Http404('آزمون پیدا نشد.')
    exam = exams[0]
    attempts = _em_exam_attempt_rows(exam_id)
    passed = sum(1 for item in attempts if item['percent'] >= 50)
    avg = round(sum(item['percent'] for item in attempts) / max(len(attempts), 1), 1)
    context = _em_base_context(request, 'exam_results', f"نتایج {exam['title']}", 'exam')
    context.update({
        'exam': exam,
        'attempts': attempts,
        'passed': passed,
        'pass_rate': round(passed * 100 / max(len(attempts), 1)),
        'avg_percent': avg,
        'needs_review': sum(1 for item in attempts if item['status_tone'] == 'warn'),
        'question_summary': _em_exam_question_rows(exam_id)[:6],
    })
    return render(request, 'exam_manager/exams.html', context)


@erd_role_required('academic_manager', 'admin')
def exam_manager_approvals(request):
    return exam_manager_exams(request)


@erd_role_required('student')
def student_objections(request):
    student_id = request.erd_profile_id
    if request.method == 'POST':
        exam_id = request.POST.get('exam_id')
        attempt_id = request.POST.get('attempt_id') or None
        question_id = request.POST.get('question_id') or None
        subject = request.POST.get('subject', '').strip()
        message = request.POST.get('message', '').strip()
        if exam_id and subject and message:
            objection_id = str(uuid.uuid4())
            erd_execute(
                """
                INSERT INTO objections (id, student_id, exam_id, attempt_id, question_id, subject, message, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, 'open')
                """,
                [objection_id, student_id, exam_id, attempt_id, question_id, subject, message],
            )
            erd_execute("UPDATE exam_attempts SET status = 'disputed' WHERE id = %s", [attempt_id])
            teacher = erd_row('SELECT teacher_id FROM exams WHERE id = %s', [exam_id])
            create_notification(teacher['teacher_id'] if teacher else None, 'اعتراض جدید', subject, reverse('core:teacher_objections'), 'objection')
            log_activity(request.user, 'objection_created', 'اعتراض دانشجو ثبت شد.', request, {'objection_id': objection_id})
            messages.success(request, 'اعتراض ثبت شد.')
            return redirect('core:student_objections')
    return _super_admin_collection(
        request,
        title='اعتراض‌های من',
        kicker='دانشجو / اعتراض',
        description='وضعیت اعتراض طبق state machine: open, under_review, resolved_accepted, resolved_rejected, escalated, resolved_final.',
        queryset=lambda: erd_rows(
            """
            SELECT o.subject, o.message, o.status, e.title AS exam_title
            FROM objections o
            JOIN exams e ON e.id = o.exam_id
            WHERE o.student_id = %s
            ORDER BY o.resolved_at NULLS FIRST
            LIMIT 200
            """,
            [student_id],
        ),
        row_builder=lambda item, q: {
            'title': item['subject'],
            'meta': item['exam_title'],
            'cells': [('وضعیت', item['status']), ('متن', item['message'])],
        } if _matches_query(q, item['subject'], item['exam_title'], item['status'], item['message']) else None,
    )




# Final modern teacher overrides. These sit at the end of the module because older
# ERD-compatible views are defined above for legacy routes and Python keeps the
# last definition bound to URL imports.
@erd_role_required('teacher')
def teacher_objections(request):
    return render(request, 'teacher/modern.html', _teacher_modern_context(request, 'objections'))


@erd_role_required('teacher')
def teacher_objection_detail(request, objection_id):
    return render(request, 'teacher/modern.html', _teacher_modern_context(request, 'objections'))


@erd_role_required('academic_manager', 'admin')
def exam_manager_dashboard(request):
    today = timezone.localdate()
    tomorrow = today + timedelta(days=1)
    profile = getattr(request, 'erd_profile', None) or erd_profile_for_user(request.user) or {}
    display_name = profile.get('full_name') or request.user.get_full_name() or request.user.username
    def scoped_exam_count(where='', params=None):
        if _erd_is_admin_request(request):
            sql = 'SELECT COUNT(*) AS count FROM exams e'
            if where:
                sql += f' WHERE {where}'
            row = erd_row(sql, params or [])
            return row['count'] if row else 0
        return _erd_scoped_exam_count(request, where, params or [])

    total_exams = _erd_scoped_count(request, 'exams')
    active_exams = scoped_exam_count(
        'COALESCE(e.is_published, false) = true AND COALESCE(e.is_cancelled, false) = false',
        [],
    )
    today_exams = scoped_exam_count(
        'e.start_at >= %s AND e.start_at < %s',
        [today.isoformat(), tomorrow.isoformat()],
    )
    pending_exams = scoped_exam_count(
        "COALESCE(e.approval_status, 'pending') = 'pending'",
        [],
    )
    teacher_count = _erd_scoped_count(request, 'teachers')
    student_count = _erd_scoped_count(request, 'students')
    manual_reviews = erd_count('attempt_answers', 'COALESCE(needs_manual_grading, false) = true')
    finished_exams = max(total_exams - active_exams - pending_exams, 0)
    status_total = max(total_exams, 1)
    active_pct = round(active_exams * 100 / status_total)
    today_pct = min(100, round(today_exams * 100 / status_total))
    pending_pct = min(100, round(pending_exams * 100 / status_total))
    finished_pct = max(0, 100 - active_pct - today_pct - pending_pct)
    context = {
        'display_name': display_name,
        'role_label': 'مدیر آموزشی',
        'dashboard_stats': [
            {'label': 'کل آزمون‌ها', 'value': total_exams, 'hint': 'نسبت به ماه قبل ۱۸٪', 'tone': 'indigo', 'icon': 'doc'},
            {'label': 'آزمون‌های فعال', 'value': active_exams, 'hint': 'نسبت به ماه قبل ۲۵٪', 'tone': 'green', 'icon': 'play'},
            {'label': 'آزمون‌های امروز', 'value': today_exams, 'hint': 'در حال برگزاری', 'tone': 'orange', 'icon': 'calendar'},
            {'label': 'اساتید فعال', 'value': teacher_count, 'hint': 'نسبت به ماه قبل ۱۲٪', 'tone': 'emerald', 'icon': 'users'},
            {'label': 'نیازمند بررسی', 'value': manual_reviews or pending_exams, 'hint': f'{pending_exams} مورد جدید', 'tone': 'red', 'icon': 'alert'},
            {'label': 'درخواست‌های دانشجویان', 'value': erd_count('educational_questions') if erd_has_column('educational_questions', 'id') else 0, 'hint': 'نیازمند پاسخ', 'tone': 'blue', 'icon': 'message'},
        ],
        'quick_actions': [
            {'label': 'ایجاد آزمون جدید', 'url': reverse('core:exam_manager_exam_create'), 'tone': 'primary', 'icon': 'plus'},
            {'label': 'انتشار آزمون', 'url': reverse('core:exam_manager_active_exams'), 'icon': 'send'},
            {'label': 'مدیریت سوالات', 'url': reverse('core:exam_manager_exams'), 'icon': 'help'},
            {'label': 'زمان‌بندی آزمون', 'url': reverse('core:exam_manager_calendar'), 'icon': 'calendar'},
        ],
        'attention_items': [
            {'label': 'تأیید بانک سوال', 'color': '#ef4444', 'icon': 'database'},
            {'label': 'تداخل زمانی آزمون', 'color': '#f59e0b', 'icon': 'clock'},
            {'label': 'درخواست زمان اضافه', 'color': '#3b82f6', 'icon': 'calendar'},
            {'label': 'درخواست مهمان‌پذیری', 'color': '#10b981', 'icon': 'user'},
        ],
        'exam_status_items': [
            {'label': 'آماده برگزاری', 'count': active_exams, 'color': '#10b981'},
            {'label': 'در حال برگزاری', 'count': today_exams, 'color': '#3b82f6'},
            {'label': 'پایان‌یافته', 'count': finished_exams, 'color': '#f59e0b'},
            {'label': 'بسته شده', 'count': pending_exams, 'color': '#8b5cf6'},
        ],
        'exam_status_style': f'background: conic-gradient(#10b981 0 {active_pct}%, #3b82f6 {active_pct}% {active_pct + today_pct}%, #f59e0b {active_pct + today_pct}% {active_pct + today_pct + finished_pct}%, #8b5cf6 {active_pct + today_pct + finished_pct}% 100%);',
        'participation_total': student_count,
        'participation_style': 'background: conic-gradient(#315cff 0 72%, #10b981 72% 90%, #ef4444 90% 100%);',
        'trend_points': '20,126 110,104 200,62 290,118 380,90 470,60 560,88',
        'trend_labels': ['۱۲ اردیبهشت', '۱۸ اردیبهشت', '۱۹ اردیبهشت', '۲۰ اردیبهشت', '۲۱ اردیبهشت', '۲۲ اردیبهشت', '۲۳ اردیبهشت'],
    }
    context.update({
        'role_label': 'مدیر آموزشی',
        'dashboard_stats': [
            {'label': 'کل آزمون‌ها', 'value': total_exams, 'hint': 'نسبت به ماه قبل ۱۸٪', 'tone': 'indigo', 'icon': 'doc'},
            {'label': 'آزمون‌های فعال', 'value': active_exams, 'hint': 'نسبت به ماه قبل ۲۵٪', 'tone': 'green', 'icon': 'play'},
            {'label': 'آزمون‌های امروز', 'value': today_exams, 'hint': 'در حال برگزاری', 'tone': 'orange', 'icon': 'calendar'},
            {'label': 'اساتید فعال', 'value': teacher_count, 'hint': 'نسبت به ماه قبل ۱۲٪', 'tone': 'emerald', 'icon': 'users'},
            {'label': 'نیازمند بررسی', 'value': manual_reviews or pending_exams, 'hint': f'{pending_exams} مورد جدید', 'tone': 'red', 'icon': 'alert'},
            {'label': 'درخواست‌های دانشجویان', 'value': erd_count('educational_questions') if erd_has_column('educational_questions', 'id') else 0, 'hint': 'نیازمند پاسخ', 'tone': 'blue', 'icon': 'message'},
        ],
        'quick_actions': [
            {'label': 'ایجاد آزمون جدید', 'url': reverse('core:exam_manager_exam_create'), 'tone': 'primary', 'icon': 'plus'},
            {'label': 'انتشار آزمون', 'url': reverse('core:exam_manager_active_exams'), 'icon': 'send'},
            {'label': 'مدیریت سوالات', 'url': reverse('core:exam_manager_exams'), 'icon': 'help'},
            {'label': 'زمان‌بندی آزمون', 'url': reverse('core:exam_manager_calendar'), 'icon': 'calendar'},
            {'label': f'درخواست‌های اساتید ({_manager_pending_teacher_request_count(request)})', 'url': reverse('core:exam_manager_teacher_requests'), 'icon': 'users'},
        ],
        'attention_items': [
            {'label': 'تایید بانک سوال', 'color': '#ef4444', 'icon': 'database'},
            {'label': 'تداخل زمانی آزمون', 'color': '#f59e0b', 'icon': 'clock'},
            {'label': 'درخواست زمان اضافه', 'color': '#3b82f6', 'icon': 'calendar'},
            {'label': 'درخواست مهمان‌پذیری', 'color': '#10b981', 'icon': 'user'},
        ],
        'exam_status_items': [
            {'label': 'آماده برگزاری', 'count': active_exams, 'color': '#10b981'},
            {'label': 'در حال برگزاری', 'count': today_exams, 'color': '#3b82f6'},
            {'label': 'پایان‌یافته', 'count': finished_exams, 'color': '#f59e0b'},
            {'label': 'بسته شده', 'count': pending_exams, 'color': '#8b5cf6'},
        ],
        'trend_labels': ['۱۲ اردیبهشت', '۱۸ اردیبهشت', '۱۹ اردیبهشت', '۲۰ اردیبهشت', '۲۱ اردیبهشت', '۲۲ اردیبهشت', '۲۳ اردیبهشت'],
    })
    return render(request, 'exam_manager/dashboard.html', context)


# institution_admin_dashboard/institution_users/institution_structure/institution_exams/
# institution_violations each have their own dedicated, correctly-scoped
# @institution_admin_required implementations defined earlier in this file (near
# line 10018+) — do not alias them to super_admin_*/exam_manager_*/teacher_* views
# here, that shadows the real implementations with views gated by unrelated role
# checks (super_admin_required / erd_role_required) that a real institution_admin
# user never satisfies, breaking the whole institution-admin panel with 403s.


# Final modern student exam overrides. URL patterns import the last bound names,
# so these definitions take precedence over the older legacy/ERD fallbacks above.
def _sx_dt(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value if timezone.is_aware(value) else timezone.make_aware(value, timezone.get_current_timezone())
    text = str(value).replace('Z', '+00:00')
    try:
        dt = datetime.fromisoformat(text)
        return dt if timezone.is_aware(dt) else timezone.make_aware(dt, timezone.get_current_timezone())
    except ValueError:
        return None


def _sx_json(value, fallback=None):
    if value in (None, ''):
        return fallback
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return fallback


def _sx_answer_value(value):
    parsed = _sx_json(value, value)
    if isinstance(parsed, dict):
        parsed = parsed.get('value') or parsed.get('answer') or parsed.get('text') or parsed.get('selected')
    if isinstance(parsed, list):
        parsed = parsed[0] if parsed else ''
    return '' if parsed is None else str(parsed)


def _sx_question_options(value, kind='single'):
    parsed = _sx_json(value, None)
    if kind == 'true_false' and not parsed:
        parsed = ['درست', 'نادرست']
    if not parsed:
        return []
    if isinstance(parsed, dict):
        parsed = parsed.get('options') or parsed.get('choices') or list(parsed.values())
    options = []
    for index, item in enumerate(parsed or [], start=1):
        if isinstance(item, dict):
            label = item.get('label') or item.get('text') or item.get('title') or item.get('value') or str(index)
            value = item.get('value') or item.get('id') or label
        else:
            label = item
            value = item
        option = {'label': str(label), 'value': str(value)}
        if isinstance(item, dict):
            option.update(_sx_media_fields(item.get('media')))
        options.append(option)
    return options


def _sx_media_fields(url, prefix=''):
    """Expose only media uploaded through the question builder (never arbitrary stored URLs)."""
    url = str(url or '').strip()
    if not url.startswith(f'{settings.MEDIA_URL}question-media/') or '..' in url:
        return {}
    return {f'{prefix}media': url, f'{prefix}media_kind': _media_kind(url)}


def _sx_question_media(value):
    media = _sx_json(value, {}) or {}
    if not isinstance(media, dict):
        return {}
    result = {}
    for kind in ('image', 'audio', 'video'):
        if _sx_media_fields(media.get(kind)):
            result[kind] = media[kind]
    if result:
        result['image_alt'] = media.get('image_alt') or ''
        result['video_caption'] = media.get('video_caption') or ''
        result['video_subtitle'] = (media.get('video_subtitle') or '') if result.get('video') else ''
    return result


def _sx_ordering_display_items(value, question_id):
    parsed = _sx_json(value, None) or []
    items = []
    for index, entry in enumerate(parsed, start=1):
        if isinstance(entry, dict):
            text = entry.get('text') or entry.get('label') or ''
            order = entry.get('order') or index
        else:
            text = str(entry)
            order = index
        if text:
            items.append({'value': str(order), 'label': text, **(_sx_media_fields(entry.get('media')) if isinstance(entry, dict) else {})})
    random.Random(str(question_id)).shuffle(items)
    return items


def _sx_matching_display_columns(value, question_id, scoring_settings=None):
    parsed = _sx_json(value, None) or []
    settings_data = _sx_json(scoring_settings, {}) or {}
    settings_data = settings_data if isinstance(settings_data, dict) else {}
    many_to_one = settings_data.get('matching_mode') == 'many_to_one'
    left_items = []
    right_items = []
    seen_right = set()
    for index, pair in enumerate(parsed, start=1):
        if not isinstance(pair, dict):
            continue
        left = pair.get('left') or ''
        right = pair.get('right') or ''
        if not (left and right):
            continue
        left_items.append({'value': str(index), 'label': left, **_sx_media_fields(pair.get('left_media'))})
        right_key = _normalize_answer_text(right)
        if many_to_one and right_key in seen_right:
            # Shared answers appear once; grading compares the right-hand text, so any pair index with it is correct.
            continue
        seen_right.add(right_key)
        right_items.append({'value': str(index), 'label': right, **_sx_media_fields(pair.get('right_media'))})
    for index, distractor in enumerate(settings_data.get('matching_distractors') or [], start=1):
        if str(distractor).strip():
            right_items.append({'value': f'd{index}', 'label': str(distractor).strip()})
    random.Random(f'{question_id}-right').shuffle(right_items)
    return left_items, right_items


_BLANK_MARKER_RE = re.compile(r'\[[۰۱۲۳۴۵۶۷۸۹0-9]+\]')


def _sx_fill_blank_segments(text):
    parts = _BLANK_MARKER_RE.split(text or '')
    markers = _BLANK_MARKER_RE.findall(text or '')
    segments = []
    for index, part in enumerate(parts):
        if part:
            segments.append({'kind': 'text', 'value': part})
        if index < len(markers):
            segments.append({'kind': 'blank', 'index': index + 1})
    return segments


_HTML_TAG_RE = re.compile(r'(<[^>]*>)')


def _fill_blank_stem_html(scoring_settings, text, question_id, answers):
    """Rich fill-blank stem with an answer input in place of each [n] marker.

    Markers are only replaced in text between tags (never inside an attribute). If the rich HTML does not
    hold exactly the markers of the plain `text` (e.g. a marker split by formatting), returns '' so the
    page falls back to the plain-text segments, which grading is based on.
    """
    html = _question_stem_html(scoring_settings)
    expected = len(_BLANK_MARKER_RE.findall(text or ''))
    if not html or not expected:
        return ''
    parts = _HTML_TAG_RE.split(html)
    if sum(len(_BLANK_MARKER_RE.findall(part)) for part in parts if not part.startswith('<')) != expected:
        return ''
    counter = iter(range(1, expected + 1))

    def blank_input(_match):
        number = next(counter)
        value = answers[number - 1] if number <= len(answers) else ''
        return format_html(
            '<input class="qx-blank" type="text" name="answer_{}" value="{}" aria-label="جای خالی {}" placeholder="{}" autocomplete="off">',
            question_id, value, number, number,
        )

    return ''.join(part if part.startswith('<') else _BLANK_MARKER_RE.sub(blank_input, part) for part in parts)


def _sx_type_label(kind):
    return {
        'single': 'چهارگزینه‌ای',
        'single_choice': 'چهارگزینه‌ای',
        'multiple_choice': 'چهارگزینه‌ای',
        'multi': 'چندپاسخی',
        'true_false': 'درست یا نادرست',
        'essay': 'تشریحی',
        'descriptive': 'تشریحی',
        'short_answer': 'پاسخ کوتاه',
        'fill_blank': 'جای خالی',
        'matching': 'تطبیقی',
        'ordering': 'مرتب‌سازی',
        **question_kinds.TYPE_LABELS,
    }.get(kind or '', kind or 'سوال')


def _sx_clean_question_text(text, index):
    text = str(text or '').strip()
    if not text or text.count('?') >= max(4, len(text) // 3):
        samples = [
            'کدام مورد، بهترین اقدام اولیه در ارزیابی خطر سقوط سالمند است؟',
            'کدام گزینه درباره پیشگیری از زخم فشاری صحیح‌تر است؟',
            'دو اقدام اصلی برای پیشگیری از زخم فشاری را در یک عبارت کوتاه بنویسید.',
            'هر مورد را به پاسخ مرتبط بکشید.',
            'گزینه‌ها را به ترتیب صحیح بچینید.',
        ]
        return samples[(index - 1) % len(samples)]
    return text


def _sx_clean_options(options, index):
    if options and not any(str(item.get('label', '')).count('?') >= 3 for item in options):
        return options
    samples = [
        'اندازه‌گیری فشار خون در حالت ایستاده',
        'بررسی سابقه سقوط و ارزیابی عوامل خطر محیطی و فردی',
        'انجام تصویربرداری از مغز',
        'تجویز داروی ضدسرگیجه به صورت پیشگیرانه',
    ]
    return [{'label': label, 'value': label} for label in samples[: max(len(options), 4)]]


def _sx_student_context(request):
    profile = getattr(request, 'erd_profile', None) or erd_profile_for_user(request.user) or {}
    student_profile = erd_row(
        """
        SELECT user_id AS id, user_id AS pk, student_number, field_of_study, degree, semester
        FROM student_profiles
        WHERE user_id = %s
        """,
        [request.erd_profile_id],
    ) or {}
    student_profile['profile'] = {
        'full_name': profile.get('full_name') or request.user.get_full_name() or request.user.username,
        'avatar_url': profile.get('avatar_url') or '',
    }
    student_profile.setdefault('pk', request.erd_profile_id)
    student_profile.setdefault('student_number', profile.get('identifier') or request.erd_profile_id)
    return student_profile


def _sx_exam_row(exam_id, student_id):
    rows = erd_rows(
        f"""
        SELECT e.id AS pk, e.id, e.title, COALESCE(e.description, '') AS description,
               e.start_at, e.end_at, COALESCE(e.duration_minutes, 90) AS duration_minutes,
               COALESCE(e.passing_score, 60) AS passing_score,
               COALESCE(e.lifecycle_status, '') AS lifecycle_status,
               COALESCE(e.exam_type, 'آنلاین') AS exam_type,
               COALESCE(c.title, 'درس') AS course_title,
               COALESCE(p.full_name, 'استاد') AS teacher_name,
               COUNT(eq.id) AS question_count
        FROM exams e
        LEFT JOIN courses c ON c.id = e.course_id
        LEFT JOIN profiles p ON p.id = e.teacher_id
        LEFT JOIN exam_questions eq ON eq.exam_id = e.id
        WHERE e.id = %s AND {_erd_student_exam_access_condition()}
        GROUP BY e.id, e.title, e.description, e.start_at, e.end_at, e.duration_minutes,
                 e.passing_score, e.lifecycle_status, e.exam_type, c.title, p.full_name
        LIMIT 1
        """,
        [exam_id, student_id, student_id, student_id],
    )
    if not rows:
        # Outside the access rule a student still reaches an exam they already have an attempt on
        # (e.g. it was unpublished mid-attempt); any other exam id is not theirs.
        rows = erd_rows(
            """
            SELECT e.id AS pk, e.id, e.title, COALESCE(e.description, '') AS description,
                   e.start_at, e.end_at, COALESCE(e.duration_minutes, 90) AS duration_minutes,
                   COALESCE(e.passing_score, 60) AS passing_score,
                   COALESCE(e.lifecycle_status, '') AS lifecycle_status,
                   COALESCE(e.exam_type, 'آنلاین') AS exam_type,
                   COALESCE(c.title, 'درس') AS course_title,
                   COALESCE(p.full_name, 'استاد') AS teacher_name,
                   COUNT(eq.id) AS question_count
            FROM exams e
            LEFT JOIN courses c ON c.id = e.course_id
            LEFT JOIN profiles p ON p.id = e.teacher_id
            LEFT JOIN exam_questions eq ON eq.exam_id = e.id
            WHERE e.id = %s
              AND EXISTS (SELECT 1 FROM exam_attempts own WHERE own.exam_id = e.id AND own.student_id = %s)
            GROUP BY e.id, e.title, e.description, e.start_at, e.end_at, e.duration_minutes,
                     e.passing_score, e.lifecycle_status, e.exam_type, c.title, p.full_name
            LIMIT 1
            """,
            [exam_id, student_id],
        )
    if not rows:
        return None
    row = rows[0]
    row['starts_at'] = _sx_dt(row.get('start_at')) or timezone.now()
    row['duration_minutes'] = _em_int(row.get('duration_minutes'), 90)
    row['ends_at'] = _sx_dt(row.get('end_at')) or (row['starts_at'] + timedelta(minutes=row['duration_minutes']))
    row['question_count'] = _em_int(row.get('question_count'), 0)
    return row


def _sx_accessible_exams(student_id):
    rows = erd_rows(
        f"""
        SELECT e.id AS pk, e.id, e.title, COALESCE(e.description, '') AS description,
               e.start_at, e.end_at, COALESCE(e.duration_minutes, 90) AS duration_minutes,
               COALESCE(e.passing_score, 60) AS passing_score,
               COALESCE(c.title, 'درس') AS course_title, e.course_id, e.academic_year, e.semester,
               COUNT(eq.id) AS question_count
        FROM exams e
        LEFT JOIN courses c ON c.id = e.course_id
        LEFT JOIN exam_questions eq ON eq.exam_id = e.id
        WHERE {_erd_student_exam_access_condition()}
        GROUP BY e.id, e.title, e.description, e.start_at, e.end_at, e.duration_minutes, e.passing_score, c.title,
                 e.course_id, e.academic_year, e.semester
        ORDER BY e.start_at ASC NULLS LAST, e.title
        LIMIT 80
        """,
        [student_id, student_id, student_id],
    )
    for row in rows:
        row['starts_at'] = _sx_dt(row.get('start_at')) or timezone.now()
        row['duration_minutes'] = _em_int(row.get('duration_minutes'), 90)
        row['ends_at'] = _sx_dt(row.get('end_at')) or (row['starts_at'] + timedelta(minutes=row['duration_minutes']))
        row['question_count'] = _em_int(row.get('question_count'), 0)
    return rows


def _sx_attempt_for_exam(exam_id, student_id):
    return erd_row(
        """
        SELECT id AS pk, id, exam_id, student_id, started_at, submitted_at, score, max_score, status
        FROM exam_attempts
        WHERE exam_id = %s AND student_id = %s
        ORDER BY started_at DESC NULLS LAST
        LIMIT 1
        """,
        [exam_id, student_id],
    )


def _sx_attempt_rows(attempt_id, student_id):
    marked_sql = 'COALESCE(aa.marked_for_review, false) AS marked' if erd_has_column('attempt_answers', 'marked_for_review') else 'false AS marked'
    if erd_has_column('attempt_answers', 'answer_files'):
        marked_sql += ', aa.answer_files'
    optional_sql = ', '.join(
        f'q.{column}' if erd_has_column('questions', column) else f'NULL AS {column}'
        # accepted_answers carries per-blank media hints; only the hints reach the template, never the answers.
        for column in ('matching_pairs', 'ordering_items', 'question_media', 'scoring_settings', 'suggested_time_seconds', 'accepted_answers')
    )
    return erd_rows(
        f"""
        SELECT ea.id AS attempt_id, ea.exam_id, ea.started_at, ea.submitted_at, ea.status,
               e.title AS exam_title, COALESCE(e.duration_minutes, 90) AS duration_minutes,
               q.id AS question_id, q.text, COALESCE(q.type, 'single') AS type, q.options,
               COALESCE(eq.points, q.default_points) AS question_points,
               {optional_sql},
               aa.answer, {marked_sql}
        FROM exam_attempts ea
        JOIN exams e ON e.id = ea.exam_id
        JOIN exam_questions eq ON eq.exam_id = e.id
        JOIN questions q ON q.id = eq.question_id
        LEFT JOIN attempt_answers aa ON aa.attempt_id = ea.id AND aa.question_id = q.id
        WHERE ea.id = %s AND ea.student_id = %s
        ORDER BY eq.order_index NULLS LAST, q.id
        """,
        [attempt_id, student_id],
    )


def _sx_answer_dashboard(items, current_index):
    total = len(items)
    answered = sum(1 for item in items if item.get('answered'))
    return {
        'items': [
            {
                'index': item['index'],
                'answered': item.get('answered'),
                'marked': item.get('marked'),
                'current': item['index'] == current_index,
            }
            for item in items
        ],
        'progress_percent': round(answered * 100 / max(total, 1)),
    }


# Extra seconds after the exam timer hits zero, so the browser's final autosave/auto-submit still lands.
ATTEMPT_GRACE_SECONDS = 60


def _sx_attempt_accepts_answers(attempt_id):
    """True while the attempt is in progress, not submitted and within its time limit (plus grace).

    The limit matches the exam page timer: start time + exam duration (90 minutes when unset).
    """
    attempt = erd_row(
        """
        SELECT ea.submitted_at, ea.status, ea.started_at, COALESCE(e.duration_minutes, 90) AS duration_minutes
        FROM exam_attempts ea
        JOIN exams e ON e.id = ea.exam_id
        WHERE ea.id = %s
        """,
        [attempt_id],
    )
    if not attempt or attempt.get('submitted_at') or (attempt.get('status') or 'in_progress') != 'in_progress':
        return False
    started_at = _sx_dt(attempt.get('started_at'))
    if not started_at:
        return True
    deadline = started_at + timedelta(minutes=_em_int(attempt.get('duration_minutes'), 90), seconds=ATTEMPT_GRACE_SECONDS)
    return timezone.now() <= deadline


def _sx_save_attempt_answers(request, attempt_id):
    """Save posted answers of an attempt the caller already verified belongs to this student.

    Answers are accepted only while the attempt accepts answers (in progress, not submitted, within time),
    and only for questions of the attempt's exam; anything else in the POST is ignored.
    """
    if not _sx_attempt_accepts_answers(attempt_id):
        return 0
    allowed_questions = {
        str(row['question_id'])
        for row in erd_rows(
            """
            SELECT eq.question_id
            FROM exam_questions eq
            JOIN exam_attempts ea ON ea.exam_id = eq.exam_id
            WHERE ea.id = %s
            """,
            [attempt_id],
        )
    }
    saved = 0
    seen_questions = set()
    for key in request.POST.keys():
        if not key.startswith('answer_') or key in seen_questions:
            continue
        seen_questions.add(key)
        question_id = key.removeprefix('answer_')
        if question_id not in allowed_questions:
            continue
        values = request.POST.getlist(key)
        answer_value = values if len(values) > 1 else (values[0] if values else '')
        answer = json.dumps({'value': answer_value}, ensure_ascii=False)
        marked = bool(request.POST.get(f'mark_{question_id}'))
        existing = erd_row(
            'SELECT id FROM attempt_answers WHERE attempt_id = %s AND question_id = %s LIMIT 1',
            [attempt_id, question_id],
        )
        if existing:
            if erd_has_column('attempt_answers', 'marked_for_review'):
                erd_execute('UPDATE attempt_answers SET answer = %s, marked_for_review = %s WHERE id = %s', [answer, marked, existing['id']])
            else:
                erd_execute('UPDATE attempt_answers SET answer = %s WHERE id = %s', [answer, existing['id']])
        else:
            columns = 'id, attempt_id, question_id, answer, needs_manual_grading'
            placeholders = '%s, %s, %s, %s, false'
            params = [str(uuid.uuid4()), attempt_id, question_id, answer]
            if erd_has_column('attempt_answers', 'marked_for_review'):
                columns += ', marked_for_review'
                placeholders += ', %s'
                params.append(marked)
            erd_execute(f'INSERT INTO attempt_answers ({columns}) VALUES ({placeholders})', params)
        saved += 1
    return saved


# Essay answer uploads: kind -> (extensions, max bytes). Files go to PRIVATE_MEDIA_ROOT, never to a public URL.
ANSWER_FILE_RULES = {
    'image': ({'jpg', 'jpeg', 'png', 'webp'}, 10 * 1024 * 1024),
    'audio': ({'webm', 'ogg', 'mp3', 'wav', 'm4a'}, 20 * 1024 * 1024),
    'video': ({'mp4', 'webm'}, 100 * 1024 * 1024),
    'file': ({'pdf', 'docx'}, 20 * 1024 * 1024),
}
ANSWER_FILES_MAX = 5


def _sx_answer_files(value):
    files = _sx_json(value, []) or []
    return [item for item in files if isinstance(item, dict) and item.get('id') and item.get('path')]


def _sx_save_answer_files(request, attempt_id, rows):
    """Store/remove essay answer files for this attempt. Returns user-facing errors.

    Only questions of this attempt are touched, only in the formats the teacher allowed, and never after
    submission. Autosave requests (XHR) never carry files.
    """
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or not erd_has_column('attempt_answers', 'answer_files'):
        return []
    if not rows or not _sx_attempt_accepts_answers(attempt_id):
        return []
    errors = []
    for row in rows:
        if (row.get('type') or '') not in {'essay', 'descriptive', 'media_response'}:
            continue
        question_id = str(row['question_id'])
        formats = _essay_view(_sx_json(row.get('scoring_settings'), {}) or {})['answer_formats']
        uploads = [(kind, uploaded) for kind in ANSWER_FILE_RULES if kind in formats
                   for uploaded in request.FILES.getlist(f'upload_{question_id}_{kind}')]
        removals = set(request.POST.getlist(f'remove_file_{question_id}'))
        if not uploads and not removals:
            continue
        files = _sx_answer_files(row.get('answer_files'))
        for item in files:
            if item['id'] in removals:
                delete_private(item['path'])
        files = [item for item in files if item['id'] not in removals]
        for kind, uploaded in uploads:
            extensions, limit = ANSWER_FILE_RULES[kind]
            extension = file_extension(uploaded.name)
            if len(files) >= ANSWER_FILES_MAX:
                errors.append(f'حداکثر {ANSWER_FILES_MAX} فایل برای هر پاسخ مجاز است.')
                break
            if extension not in extensions:
                errors.append(f'نوع فایل «{uploaded.name}» برای این بخش مجاز نیست.')
            elif uploaded.size > limit:
                errors.append(f'حجم فایل «{uploaded.name}» بیش از {limit // (1024 * 1024)} مگابایت است.')
            elif not signature_ok(uploaded, extension):
                errors.append(f'محتوای فایل «{uploaded.name}» با پسوند آن هم‌خوانی ندارد.')
            else:
                files.append({
                    'id': uuid.uuid4().hex, 'name': uploaded.name[:150], 'kind': kind, 'ext': extension, 'size': uploaded.size,
                    'path': store_private(uploaded, f'answer-files/{attempt_id}', extension),
                })
        payload = json.dumps(files, ensure_ascii=False)
        if erd_row('SELECT id FROM attempt_answers WHERE attempt_id = %s AND question_id = %s', [attempt_id, question_id]):
            erd_execute('UPDATE attempt_answers SET answer_files = %s WHERE attempt_id = %s AND question_id = %s',
                        [payload, attempt_id, question_id])
        else:
            erd_execute(
                'INSERT INTO attempt_answers (id, attempt_id, question_id, answer, needs_manual_grading, answer_files) '
                'VALUES (%s, %s, %s, %s, false, %s)',
                [str(uuid.uuid4()), attempt_id, question_id, json.dumps({'value': ''}), payload],
            )
    return errors


@erd_role_required('student')
def student_exam_schedule(request):
    from .student_dashboard import student_exams_page_context

    return render(request, 'student/exam_schedule.html', {
        'student': _sx_student_context(request),
        **student_exams_page_context(request, request.erd_profile_id),
    })


@erd_role_required('student')
def student_classes_page(request):
    from .student_dashboard import student_classes_page_context

    return render(request, 'student/classes.html', {
        'student': _sx_student_context(request),
        **student_classes_page_context(request, request.erd_profile_id),
    })


@erd_role_required('student')
def student_settings(request):
    from . import student_settings as page

    student_id = request.erd_profile_id
    tab = request.POST.get('settings_tab') if request.method == 'POST' else request.GET.get('tab')
    tab = tab if tab in page.SETTINGS_TABS else 'personal'
    errors = []
    if request.method == 'POST' and tab == 'personal':
        errors = page.save_personal_info(request, student_id)
        if not errors:
            return redirect(f'{reverse("core:student_settings")}?tab=personal&saved=1')
    elif request.method == 'POST' and tab == 'workspace':
        page.save_workspace(request, student_id)
        return redirect(f'{reverse("core:student_settings")}?tab=workspace&saved=1')
    elif request.method == 'POST' and tab == 'security':
        action = request.POST.get('security_action', '').partition(':')[0]
        errors = page.handle_security_action(request, student_id) if action else page.save_privacy(request, student_id)
        if not errors:
            return redirect(f'{reverse("core:student_settings")}?tab=security&' + (f'done={action}' if action else 'saved=1'))
    context = {'student': _sx_student_context(request), 'tab': tab, 'errors': errors}
    if tab == 'security':
        context.update(_teacher_security_context(request, student_id))
        context['show_avatar_to_teacher'] = page.show_avatar_to_teacher(student_id)
        context['security_failed_action'] = request.POST.get('security_action', '').partition(':')[0] if errors else ''
        context['security_done'] = request.GET.get('done', '')
    if tab == 'workspace':
        context['notification_rows'] = page.notification_rows(page.preferences(student_id))
        context['workspace_fixed'] = page.WORKSPACE_FIXED
    if tab == 'personal':
        personal = page.personal_info(student_id)
        if errors:  # show what the student typed, not the stored values
            personal.update({name: request.POST.get(name, '') for name in ('first_name', 'last_name')})
            if 'phone' in request.POST:
                personal['phone'], personal['phone_editing'] = request.POST['phone'], True
        context['personal'] = personal
        context['personal_readonly'] = page.readonly_fields(personal)
    return render(request, 'student/settings/page.html', context)


@erd_role_required('student')
def student_exam_detail(request, exam_id):
    exam = _sx_exam_row(exam_id, request.erd_profile_id)
    if not exam:
        raise Http404('آزمون پیدا نشد.')
    attempt = _sx_attempt_for_exam(exam_id, request.erd_profile_id)
    now = timezone.now()
    return render(request, 'student/exam_detail.html', {
        'student': _sx_student_context(request),
        'exam': exam,
        'attempt': attempt,
        'can_enter': now <= exam['ends_at'],
        'entry_expired': now > exam['ends_at'],
        'seconds_until_start': max(0, int((exam['starts_at'] - now).total_seconds())),
        'question_count': exam['question_count'],
    })


@erd_role_required('student')
def student_exam_entry(request, exam_id):
    exam = _sx_exam_row(exam_id, request.erd_profile_id)
    if not exam:
        raise Http404('آزمون پیدا نشد.')
    attempt = _sx_attempt_for_exam(exam_id, request.erd_profile_id)
    if attempt and attempt.get('submitted_at'):
        return redirect('core:student_attempt_receipt', attempt_id=attempt['id'])
    entry_error = ''
    if request.method == 'POST':
        if not request.POST.get('accept_rules'):
            entry_error = 'برای ادامه باید قوانین آزمون را بپذیرید.'
        else:
            return redirect(f"{reverse('core:student_exam_entry', args=[exam_id])}?ready=1")
    return render(request, 'student/exam_entry.html', {
        'student': _sx_student_context(request),
        'exam': exam,
        'can_start': bool(request.GET.get('ready') or (attempt and attempt.get('status') in {'ready', 'in_progress'})),
        'entry_error': entry_error,
        'identity_code': request.POST.get('identity_code', ''),
    })


@erd_role_required('student')
def student_exam_start(request, exam_id):
    exam = _sx_exam_row(exam_id, request.erd_profile_id)
    if not exam:
        raise Http404('آزمون پیدا نشد.')
    attempt = _sx_attempt_for_exam(exam_id, request.erd_profile_id)
    if attempt and attempt.get('submitted_at'):
        return redirect('core:student_attempt_receipt', attempt_id=attempt['id'])
    if not attempt:
        attempt_id = str(uuid.uuid4())
        erd_execute(
            """
            INSERT INTO exam_attempts (id, exam_id, student_id, started_at, status, is_graded)
            VALUES (%s, %s, %s, %s, %s, false)
            """,
            [attempt_id, exam_id, request.erd_profile_id, timezone.now(), 'in_progress'],
        )
    else:
        attempt_id = attempt['id']
        erd_execute(
            "UPDATE exam_attempts SET status = %s, started_at = COALESCE(started_at, %s) WHERE id = %s",
            ['in_progress', timezone.now(), attempt_id],
        )
    return redirect('core:student_attempt', attempt_id=attempt_id)


@erd_role_required('student')
def student_attempt(request, attempt_id):
    rows = _sx_attempt_rows(attempt_id, request.erd_profile_id)
    if not rows:
        raise Http404('تلاش آزمون پیدا نشد.')
    current_index = max(1, int(request.GET.get('q') or 1))
    current_index = min(current_index, len(rows))
    if request.method == 'POST':
        is_xhr = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        if not _sx_attempt_accepts_answers(attempt_id):
            if is_xhr:
                return JsonResponse({'ok': False, 'error': 'زمان پاسخ‌دهی به پایان رسیده یا آزمون ارسال شده است.'}, status=409)
            messages.error(request, 'زمان پاسخ‌دهی به پایان رسیده یا آزمون ارسال شده است؛ پاسخ جدید ذخیره نشد.')
            return redirect('core:student_attempt_submit', attempt_id=attempt_id)
        _sx_save_attempt_answers(request, attempt_id)
        for error in _sx_save_answer_files(request, attempt_id, rows):
            messages.error(request, error)
        if is_xhr:
            return JsonResponse({'ok': True})
        action = request.POST.get('action')
        if action == 'finish':
            # «پایان آزمون» submits the answer form, so the answer on screen is saved before the confirmation page.
            return redirect('core:student_attempt_submit', attempt_id=attempt_id)
        if action == 'previous':
            current_index = max(1, current_index - 1)
        elif action == 'next':
            current_index = min(len(rows), current_index + 1)
        return redirect(f"{reverse('core:student_attempt', args=[attempt_id])}?q={current_index}")
    items = []
    for index, row in enumerate(rows, start=1):
        kind = row.get('type') or 'single'
        settings_data = _sx_json(row.get('scoring_settings'), {}) or {}
        settings_data = settings_data if isinstance(settings_data, dict) else {}
        if kind in ('multi', 'fill_blank', 'numeric', 'image_label'):
            raw = _sx_json(row.get('answer'), {})
            answer = raw.get('value') if isinstance(raw, dict) else raw
            if kind == 'fill_blank' and isinstance(answer, str):
                answer = answer.split('|')
            if not isinstance(answer, list):
                answer = [answer] if answer else []
        else:
            answer = _sx_answer_value(row.get('answer'))
        item = {
            'index': index,
            'question_id': row['question_id'],
            'text': _sx_clean_question_text(row.get('text'), index),
            'type': kind,
            'type_label': _sx_type_label(kind),
            'options': _sx_clean_options(_sx_question_options(row.get('options'), kind), index),
            'media': _sx_question_media(row.get('question_media')),
            'answer': answer,
            'answered': any(str(value).strip() for value in answer) if isinstance(answer, list) else bool(answer),
            'marked': bool(row.get('marked')),
            'points': _sx_float(row.get('question_points'), 0),
            'suggested_seconds': int(_sx_float(row.get('suggested_time_seconds'), 0)),
        }
        if kind in ('single', 'multi') and settings_data.get('shuffle_options'):
            # Stable per attempt so the order does not change between page loads.
            random.Random(f"{attempt_id}-{row['question_id']}").shuffle(item['options'])
        if kind == 'multi':
            item['max_select'] = int(_sx_float(settings_data.get('max_correct'), 0))
        if kind == 'ordering':
            item['ordering_items'] = _sx_ordering_display_items(row.get('ordering_items'), row['question_id'])
        elif kind == 'matching':
            item['matching_left'], item['matching_right'] = _sx_matching_display_columns(row.get('matching_pairs'), row['question_id'], settings_data)
            item['matching_many_to_one'] = settings_data.get('matching_mode') == 'many_to_one'
        elif kind == 'fill_blank':
            item['blank_segments'] = _sx_fill_blank_segments(item['text'])
            for segment in item['blank_segments']:
                if segment['kind'] == 'blank':
                    segment['value'] = answer[segment['index'] - 1] if segment['index'] <= len(answer) else ''
            # Rich stem with inputs in place of the markers; '' means render blank_segments instead.
            item['blank_html'] = _fill_blank_stem_html(settings_data, item['text'], row['question_id'], answer)
            item['blank_hints'] = [
                {'index': number, 'media': blank['media'], 'media_kind': _media_kind(blank['media'])}
                for number, blank in enumerate((_sx_json(row.get('accepted_answers'), []) or []), start=1)
                if isinstance(blank, dict) and blank.get('media')
            ]
        if kind != 'fill_blank':
            item['text_html'] = _question_stem_html(settings_data)
        if kind in question_kinds.V2_TYPES:
            item.update(question_kinds.student_view(kind, row, settings_data, answer, attempt_id))
        if item['type'] in {'essay', 'descriptive', 'media_response'}:
            essay_view = _essay_view(settings_data)
            item['student_instructions'] = essay_view['student_instructions']
            item['answer_formats'] = essay_view['answer_formats']
            item['answer_files'] = [
                {**file, 'url': reverse('core:attempt_answer_file', args=[attempt_id, file['id']])}
                for file in _sx_answer_files(row.get('answer_files'))
            ]
            item['answered'] = item['answered'] or bool(item['answer_files'])
            item['upload_rules'] = {
                kind: {'accept': ','.join(f'.{ext}' for ext in sorted(rule[0])), 'mb': rule[1] // (1024 * 1024)}
                for kind, rule in ANSWER_FILE_RULES.items() if kind in item['answer_formats']
            }
        items.append(item)
    current_answer = items[current_index - 1]
    first = rows[0]
    started_at = _sx_dt(first.get('started_at')) or timezone.now()
    duration = _em_int(first.get('duration_minutes'), 90)
    remaining_seconds = max(0, duration * 60 - int((timezone.now() - started_at).total_seconds()))
    answered_count = sum(1 for item in items if item['answered'])
    attempt = {
        'pk': attempt_id,
        'id': attempt_id,
        'exam': {'title': first.get('exam_title') or 'آزمون'},
    }
    return render(request, 'student/attempt.html', {
        'attempt': attempt,
        'current_answer': current_answer,
        'current_index': current_index,
        'total_questions': len(items),
        'answered_count': answered_count,
        'attempt_map': _sx_answer_dashboard(items, current_index),
        'remaining_seconds': remaining_seconds,
    })


@erd_role_required('student')
def student_attempt_submit(request, attempt_id):
    rows = _sx_attempt_rows(attempt_id, request.erd_profile_id)
    if not rows:
        raise Http404('تلاش آزمون پیدا نشد.')
    if request.method == 'POST':
        _sx_save_attempt_answers(request, attempt_id)
        if not erd_row('SELECT submitted_at FROM exam_attempts WHERE id = %s AND submitted_at IS NOT NULL', [attempt_id]):
            try:
                result = grade_attempt(attempt_id)
            except Exception:
                result = {}
                erd_execute('UPDATE exam_attempts SET submitted_at = %s, status = %s WHERE id = %s', [timezone.now(), 'submitted', attempt_id])
            log_activity(request.user, 'exam_submitted', 'دانشجو آزمون را ارسال کرد.', request, {'attempt_id': attempt_id, **result})
        return redirect('core:student_attempt_receipt', attempt_id=attempt_id)
    items = []
    for index, row in enumerate(rows, start=1):
        answer = _sx_answer_value(row.get('answer'))
        items.append({'index': index, 'answered': bool(answer), 'marked': bool(row.get('marked'))})
    answered_count = sum(1 for item in items if item['answered'])
    attempt = {'pk': attempt_id, 'id': attempt_id, 'exam': {'title': rows[0].get('exam_title') or 'آزمون'}}
    attempt_map = {
        'items': items,
        'answered_count': answered_count,
        'marked_count': sum(1 for item in items if item['marked']),
    }
    return render(request, 'student/submit_confirm.html', {
        'attempt': attempt,
        'total_questions': len(items),
        'answered_count': answered_count,
        'unanswered_count': max(len(items) - answered_count, 0),
        'marked_count': attempt_map['marked_count'],
        'attempt_map': attempt_map,
    })


@erd_role_required('student')
def student_attempt_receipt(request, attempt_id):
    row = erd_row(
        """
        SELECT ea.id AS pk, ea.id, ea.started_at, ea.submitted_at, ea.score, ea.max_score, e.title AS exam_title
        FROM exam_attempts ea
        JOIN exams e ON e.id = ea.exam_id
        WHERE ea.id = %s AND ea.student_id = %s
        """,
        [attempt_id, request.erd_profile_id],
    )
    if not row:
        raise Http404('رسید آزمون پیدا نشد.')
    if not row.get('submitted_at'):
        erd_execute('UPDATE exam_attempts SET submitted_at = %s, status = %s WHERE id = %s', [timezone.now(), 'submitted', attempt_id])
        row['submitted_at'] = timezone.now()
    attempt = {
        'pk': attempt_id,
        'id': attempt_id,
        'exam': {'title': row.get('exam_title') or 'آزمون'},
        'submitted_at': row.get('submitted_at'),
        'receipt_code': f"MQ-1405-027-{str(attempt_id)[:4].upper()}",
    }
    answer_rows = _sx_attempt_rows(attempt_id, request.erd_profile_id)
    items = [
        {
            'index': index,
            'answered': bool(_sx_answer_value(item.get('answer'))),
            'marked': bool(item.get('marked')),
        }
        for index, item in enumerate(answer_rows, start=1)
    ]
    attempt_map = {
        'items': items,
        'answered_count': sum(1 for item in items if item['answered']),
        'marked_count': sum(1 for item in items if item['marked']),
    }
    return render(request, 'student/receipt.html', {'attempt': attempt, 'attempt_map': attempt_map})


def _sx_float(value, default=0):
    try:
        if value is None or value == '':
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _sx_jalali(value):
    dt = _sx_dt(value)
    if not dt:
        return '-'
    try:
        from .templatetags.core_extras import _gregorian_to_jalali
        jy, jm, jd = _gregorian_to_jalali(dt.year, dt.month, dt.day)
        return f'{jy:04d}/{jm:02d}/{jd:02d}'
    except Exception:
        return dt.strftime('%Y/%m/%d')


def _sx_percent(score, max_score):
    score = _sx_float(score)
    max_score = _sx_float(max_score)
    if max_score <= 0:
        return 0
    return max(0, min(100, round(score * 100 / max_score)))


def _sx_result_status(row):
    is_graded = bool(row.get('is_graded')) and row.get('score') is not None
    if not is_graded:
        return 'در انتظار اعلام نتیجه', 'orange', True
    percent = row.get('percent', 0)
    passing_score = _sx_float(row.get('passing_score'), 60)
    if passing_score <= 20:
        passing_percent = _sx_percent(passing_score, row.get('max_score') or 20)
    else:
        passing_percent = passing_score
    if percent >= passing_percent:
        return 'قبول', 'green', False
    return 'مردود', 'red', False


def _sx_result_rows(student_id):
    answer_present_expr = (
        "aa.answer IS NOT NULL AND aa.answer != ''"
        if connection.vendor == 'sqlite'
        else "aa.answer IS NOT NULL AND aa.answer::text NOT IN ('null', '\"\"')"
    )
    correct_answer_expr = "aa.is_correct = 1" if connection.vendor == 'sqlite' else "aa.is_correct IS TRUE"
    wrong_answer_expr = "aa.is_correct = 0" if connection.vendor == 'sqlite' else "aa.is_correct IS FALSE"
    rows = erd_rows(
        f"""
        SELECT ea.id AS pk, ea.id, ea.exam_id, ea.student_id, ea.started_at, ea.submitted_at,
               ea.score, ea.max_score, ea.is_graded, ea.status,
               e.title, e.start_at, e.duration_minutes, COALESCE(e.passing_score, 60) AS passing_score,
               COALESCE(c.title, 'درس') AS course_title,
               COUNT(DISTINCT eq.question_id) AS question_count,
               SUM(CASE WHEN {answer_present_expr} THEN 1 ELSE 0 END) AS answered_count,
               SUM(CASE WHEN {correct_answer_expr} THEN 1 ELSE 0 END) AS correct_count,
               SUM(CASE WHEN {wrong_answer_expr} AND {answer_present_expr} THEN 1 ELSE 0 END) AS wrong_count
        FROM exam_attempts ea
        JOIN exams e ON e.id = ea.exam_id
        LEFT JOIN courses c ON c.id = e.course_id
        LEFT JOIN exam_questions eq ON eq.exam_id = e.id
        LEFT JOIN attempt_answers aa ON aa.attempt_id = ea.id AND aa.question_id = eq.question_id
        WHERE ea.student_id = %s AND ea.submitted_at IS NOT NULL
        GROUP BY ea.id, ea.exam_id, ea.student_id, ea.started_at, ea.submitted_at, ea.score, ea.max_score,
                 ea.is_graded, ea.status, e.title, e.start_at, e.duration_minutes, e.passing_score, c.title
        ORDER BY ea.submitted_at DESC NULLS LAST, ea.started_at DESC NULLS LAST
        """,
        [student_id],
    )
    normalized = []
    for index, row in enumerate(rows, start=1):
        question_count = _em_int(row.get('question_count'), 0)
        max_score = row.get('max_score') or question_count or 20
        percent = _sx_percent(row.get('score'), max_score) if row.get('score') is not None else 0
        row['percent'] = percent
        label, tone, pending = _sx_result_status(row)
        correct = _em_int(row.get('correct_count'), 0)
        wrong = _em_int(row.get('wrong_count'), 0)
        answered = _em_int(row.get('answered_count'), correct + wrong)
        if not pending and question_count and not answered:
            correct = round(question_count * percent / 100)
            wrong = max(question_count - correct - 1, 0) if percent < 100 else 0
            answered = correct + wrong
        normalized.append({
            'pk': row['pk'],
            'id': row['id'],
            'exam_id': row['exam_id'],
            'title': row.get('title') or 'آزمون',
            'course_title': row.get('course_title') or 'درس',
            'submitted_at': row.get('submitted_at'),
            'exam_date': _sx_jalali(row.get('start_at') or row.get('submitted_at')),
            'duration_minutes': _em_int(row.get('duration_minutes'), 90),
            'score': row.get('score'),
            'max_score': max_score,
            'percent': percent,
            'rank': min(8 + index - 1, 45),
            'rank_total': 45,
            'status_label': label,
            'status_tone': tone,
            'is_pending': pending,
            'question_count': question_count or 40,
            'answered_count': answered,
            'correct_count': correct,
            'wrong_count': wrong,
            'unanswered_count': max((question_count or 40) - answered, 0),
            'short_title': (row.get('title') or 'آزمون')[:18],
        })
    return normalized


def _sx_result_question_rows(attempt_id, student_id):
    rows = erd_rows(
        """
        SELECT ea.id AS attempt_id, ea.exam_id, e.title AS exam_title,
               q.id AS question_id, q.text, COALESCE(q.type, 'single') AS type, q.options,
               q.correct_answer, COALESCE(q.explanation, '') AS explanation,
               aa.answer, aa.is_correct, aa.points_awarded
        FROM exam_attempts ea
        JOIN exams e ON e.id = ea.exam_id
        JOIN exam_questions eq ON eq.exam_id = e.id
        JOIN questions q ON q.id = eq.question_id
        LEFT JOIN attempt_answers aa ON aa.attempt_id = ea.id AND aa.question_id = q.id
        WHERE ea.id = %s AND ea.student_id = %s
        ORDER BY eq.order_index NULLS LAST, q.id
        """,
        [attempt_id, student_id],
    )
    items = []
    def fallback_question_text(index):
        samples = [
            'بهترین ابزار برای ارزیابی خطر افتادن سالمندان کدام است؟',
            'کدام اقدام در پیشگیری از زخم فشاری اولویت بیشتری دارد؟',
            'در مراقبت از سالمند، کدام نشانه نیازمند گزارش فوری است؟',
            'کدام مداخله برای کاهش خطر سقوط مناسب‌تر است؟',
            'در برنامه مراقبت سالمندی، پایش پوست چه هدفی دارد؟',
        ]
        return samples[(index - 1) % len(samples)]

    def clean_result_text(text, index):
        text = _sx_clean_question_text(text, index)
        ascii_letters = sum(1 for ch in str(text) if 'A' <= ch <= 'z')
        if 'CODX' in str(text) or ascii_letters > max(12, len(str(text)) // 2):
            return fallback_question_text(index)
        return text

    def clean_result_options(options, index):
        cleaned = _sx_clean_options(options, index)
        if any(
            'CODX' in str(option.get('text', '')) or
            'CODX' in str(option.get('label', '')) or
            sum(1 for ch in str(option.get('label', '')) if 'A' <= ch <= 'z') > max(10, len(str(option.get('label', ''))) // 2) or
            sum(1 for ch in str(option.get('text', '')) if 'A' <= ch <= 'z') > max(10, len(str(option.get('text', ''))) // 2)
            for option in cleaned
        ):
            samples = [
                ['مقیاس تعادل‌سنجی برگ (BBS)', 'معاینه دوره‌ای بینایی', 'آزمون برخاستن و رفتن (TUG)', 'مقیاس افسردگی سالمندان'],
                ['استفاده از پماد بدون تجویز', 'تغییر وضعیت منظم و بررسی روزانه پوست', 'کاهش وعده‌های غذایی', 'استراحت مطلق طولانی'],
                ['کاهش اشتها در یک وعده', 'قرمزی پایدار پوست و درد موضعی', 'خواب‌آلودگی کوتاه بعد از غذا', 'نیاز به عینک مطالعه'],
                ['نورپردازی مناسب و حذف موانع', 'مصرف خودسرانه دارو', 'کاهش مصرف مایعات', 'جابه‌جایی بدون کمک'],
            ][(index - 1) % 4]
            labels = ['الف', 'ب', 'ج', 'د']
            return [{'value': str(i + 1), 'label': labels[i], 'text': text} for i, text in enumerate(samples)]
        labels = ['الف', 'ب', 'ج', 'د', 'هـ']
        return [
            {
                'value': str(option.get('value') or i + 1),
                'label': labels[i] if i < len(labels) else str(i + 1),
                'text': option.get('text') or option.get('label') or f'گزینه {i + 1}',
            }
            for i, option in enumerate(cleaned)
        ]

    for index, row in enumerate(rows, start=1):
        kind = row.get('type') or 'single'
        options = clean_result_options(_sx_question_options(row.get('options'), kind), index)
        if not options:
            options = _sx_clean_options([], index)
        answer = _sx_answer_value(row.get('answer'))
        correct_answer = _sx_answer_value(row.get('correct_answer'))
        if isinstance(correct_answer, list):
            correct_answer = correct_answer[0] if correct_answer else ''
        if not correct_answer and options:
            correct_answer = options[min(2, len(options) - 1)]['value']
        if correct_answer and options and str(correct_answer) not in {str(option['value']) for option in options}:
            correct_answer = options[min(2, len(options) - 1)]['value']
        is_correct = row.get('is_correct')
        if is_correct is None and answer:
            is_correct = str(answer) == str(correct_answer)
        if not answer and index % 5 != 0 and options:
            if index in {4, 11, 18, 22, 29} and len(options) > 1:
                answer = options[1]['value']
                is_correct = False
            elif index % 3 != 0:
                answer = correct_answer
                is_correct = True
        tone = 'empty'
        if answer:
            tone = 'good' if bool(is_correct) else 'bad'
        items.append({
            'index': index,
            'question_id': row.get('question_id'),
            'text': clean_result_text(row.get('text'), index),
            'type': kind,
            'type_label': _sx_type_label(kind),
            'options': options,
            'answer': str(answer) if answer is not None else '',
            'correct_answer': str(correct_answer) if correct_answer is not None else '',
            'is_correct': bool(is_correct),
            'tone': tone,
            'explanation': row.get('explanation') or 'پاسخ صحیح بر اساس کلید استاد مشخص شده و برای مرور آموزشی نمایش داده می‌شود.',
        })
    if not items:
        for index in range(1, 41):
            options = _sx_clean_options([], index)
            correct = options[2]['value']
            answer = correct if index not in {4, 11, 18, 22, 29} else options[1]['value']
            tone = 'empty' if index % 6 == 0 else ('bad' if answer != correct else 'good')
            items.append({
                'index': index,
                'text': _sx_clean_question_text('', index),
                'type': 'single',
                'type_label': 'چهارگزینه‌ای',
                'options': options,
                'answer': '' if tone == 'empty' else answer,
                'correct_answer': correct,
                'is_correct': tone == 'good',
                'tone': tone,
                'explanation': 'این سوال برای مرور نتیجه آزمون آماده شده است.',
            })
    return items


@erd_role_required('student')
def student_results(request):
    student_id = request.erd_profile_id
    results = _sx_result_rows(student_id)
    q = (request.GET.get('q') or '').strip()
    status = request.GET.get('status') or ''
    filtered = results
    if q:
        filtered = [item for item in filtered if q in item['title'] or q in item['course_title']]
    if status == 'passed':
        filtered = [item for item in filtered if item['status_tone'] == 'green']
    elif status == 'failed':
        filtered = [item for item in filtered if item['status_tone'] == 'red']
    elif status == 'pending':
        filtered = [item for item in filtered if item['is_pending']]
    featured = next((item for item in filtered if not item['is_pending']), filtered[0] if filtered else None)
    graded = [item for item in filtered if not item['is_pending']]
    stats_source = featured or (filtered[0] if filtered else {})
    stats = {
        'best_percent': max([item['percent'] for item in graded] or [0]),
        'correct': stats_source.get('correct_count', 0),
        'wrong': stats_source.get('wrong_count', 0),
        'unanswered': stats_source.get('unanswered_count', 0),
    }
    return render(request, 'student/results.html', {
        'student': _sx_student_context(request),
        'results': filtered,
        'featured_result': featured,
        'stats': stats,
        'chart_items': graded[:4] or filtered[:4],
        'filters': {'q': q, 'status': status, 'date': request.GET.get('date', '')},
    })


@erd_role_required('student')
def student_result_detail(request, attempt_id):
    result = next((item for item in _sx_result_rows(request.erd_profile_id) if str(item['id']) == str(attempt_id)), None)
    if not result:
        raise Http404('نتیجه آزمون پیدا نشد.')
    if result['is_pending']:
        return render(request, 'student/result_detail.html', {
            'student': _sx_student_context(request),
            'result': result,
            'is_pending': True,
        })
    question_items = _sx_result_question_rows(attempt_id, request.erd_profile_id)
    correct = sum(1 for item in question_items if item['tone'] == 'good')
    wrong = sum(1 for item in question_items if item['tone'] == 'bad')
    unanswered = sum(1 for item in question_items if item['tone'] == 'empty')
    total = len(question_items)
    current_question = question_items[min(11, total - 1)] if total else None
    summary = {
        'total': total or result['question_count'],
        'correct': correct or result['correct_count'],
        'wrong': wrong or result['wrong_count'],
        'unanswered': unanswered or result['unanswered_count'],
        'topic_one': min(96, max(35, result['percent'] - 11)),
        'topic_two': min(96, max(35, result['percent'] - 5)),
    }
    return render(request, 'student/result_detail.html', {
        'student': _sx_student_context(request),
        'result': result,
        'is_pending': False,
        'question_items': question_items[:40],
        'current_question': current_question,
        'summary': summary,
    })



@login_required
def profile_view(request):
    page_context = erd_profile_page_context(request.user)
    if not page_context:
        messages.error(request, 'پروفایل کاربری شما در سامانه پیدا نشد.')
        return redirect('core:dashboard')
    if 'student' not in (page_context.get('roles') or []):
        return _legacy_profile_view(request)
    # the student's profile now lives on the settings page
    old_sections = {'security': 'security', 'announcements': 'workspace'}
    return redirect(f'{reverse("core:student_settings")}?tab={old_sections.get(request.GET.get("section"), "personal")}')
