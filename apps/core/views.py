import csv
import io
import random
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import get_user_model, login as auth_login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.db.models import Count, Q
from django.http import HttpResponse, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.crypto import get_random_string

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
    StudentAnswerForm,
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
    ResultPublicationForm,
    StyledAuthenticationForm,
    SuperAdminInstitutionForm,
    SuperAdminReportFilterForm,
    SuperAdminRoleForm,
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


def log_activity(user, action, description='', request=None, metadata=None):
    UserActivityLog.objects.create(
        user=user,
        action=action,
        description=description,
        ip_address=client_ip(request) if request else None,
        user_agent=request.META.get('HTTP_USER_AGENT', '') if request else '',
        metadata=metadata or {},
    )


def is_super_admin(user):
    if not user.is_authenticated:
        return False
    profile = getattr(user, 'profile', None)
    return bool(profile and profile.role.code == SystemRole.RoleCode.SUPER_ADMIN)


def super_admin_required(view_func):
    @login_required
    def wrapped(request, *args, **kwargs):
        if not is_super_admin(request.user):
            return HttpResponseForbidden('دسترسی فقط برای مدیر کل سیستم مجاز است.')
        return view_func(request, *args, **kwargs)
    return wrapped


def get_managed_institution(user):
    profile = getattr(user, 'profile', None)
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
    profile = getattr(user, 'profile', None)
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
    profile = getattr(user, 'profile', None)
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
    profile = getattr(user, 'profile', None)
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
    profile = getattr(user, 'profile', None)
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


def remaining_exam_seconds(attempt):
    if not attempt.started_at:
        return None
    duration = attempt.exam.duration_minutes or max(1, int((attempt.exam.ends_at - attempt.exam.starts_at).total_seconds() // 60))
    ends_at = attempt.started_at + timedelta(minutes=duration)
    return int((ends_at - timezone.now()).total_seconds())


def finalize_student_attempt(attempt, event_type=StudentExamEvent.EventType.SUBMITTED, message=''):
    if attempt.is_locked:
        return attempt
    now = timezone.now()
    attempt.status = (
        StudentExamAttempt.Status.AUTO_SUBMITTED
        if event_type == StudentExamEvent.EventType.AUTO_SUBMITTED
        else StudentExamAttempt.Status.SUBMITTED
    )
    attempt.submitted_at = now
    attempt.last_activity_at = now
    if not attempt.receipt_code:
        attempt.receipt_code = get_random_string(10).upper()
    attempt.save(update_fields=['status', 'submitted_at', 'last_activity_at', 'receipt_code'])
    attempt.answers.filter(submitted_at__isnull=True).update(submitted_at=now)
    StudentExamEvent.objects.create(attempt=attempt, event_type=event_type, message=message)
    return attempt


def calculate_attempt_score(attempt):
    score = 0
    total = 0
    for answer in attempt.answers.select_related('exam_question__question'):
        exam_question = answer.exam_question
        question = exam_question.question
        total += float(exam_question.score)
        if question.correct_answer and answer.answer_text.strip() == question.correct_answer.strip():
            score += float(exam_question.score)
    return score, total


class SecureLoginView(LoginView):
    template_name = 'login.html'
    authentication_form = StyledAuthenticationForm

    def form_invalid(self, form):
        username = self.request.POST.get('username', '')
        attempts = StyledAuthenticationForm.record_failed_attempt(username)
        failed_user = User.objects.filter(username=username).first()
        if failed_user:
            UserLoginRecord.objects.create(
                user=failed_user,
                ip_address=client_ip(self.request),
                user_agent=self.request.META.get('HTTP_USER_AGENT', ''),
                was_successful=False,
            )
        if attempts >= StyledAuthenticationForm.max_attempts:
            messages.error(self.request, 'تعداد تلاش ناموفق زیاد است. حساب به‌صورت موقت قفل شد.')
        else:
            messages.error(self.request, 'نام کاربری یا رمز عبور درست نیست.')
        return super().form_invalid(form)

    def form_valid(self, form):
        user = form.get_user()
        StyledAuthenticationForm.clear_failed_attempts(user.get_username())
        profile = getattr(user, 'profile', None)
        UserLoginRecord.objects.create(
            user=user,
            ip_address=client_ip(self.request),
            user_agent=self.request.META.get('HTTP_USER_AGENT', ''),
            was_successful=True,
        )
        if profile and profile.two_factor_enabled:
            code = f'{random.randint(100000, 999999)}'
            self.request.session['pending_2fa_user_id'] = user.pk
            self.request.session['pending_2fa_code'] = code
            self.request.session['pending_2fa_next'] = self.get_success_url()
            messages.info(self.request, f'کد تأیید دومرحله‌ای برای محیط آزمایشی: {code}')
            log_activity(user, 'two_factor_code_sent', 'کد تأیید دومرحله‌ای ایجاد شد.', self.request)
            return redirect('core:login_2fa')
        auth_login(self.request, user)
        log_activity(user, 'login_success', 'ورود موفق به سامانه', self.request)
        return redirect(self.get_success_url())


def login_2fa(request):
    user_id = request.session.get('pending_2fa_user_id')
    expected_code = request.session.get('pending_2fa_code')
    if not user_id or not expected_code:
        return redirect('core:login')

    user = get_object_or_404(User, pk=user_id)
    if request.method == 'POST':
        form = TwoFactorCodeForm(request.POST)
        if form.is_valid():
            if form.cleaned_data['code'] == expected_code:
                auth_login(request, user)
                next_url = request.session.pop('pending_2fa_next', reverse('core:dashboard'))
                request.session.pop('pending_2fa_user_id', None)
                request.session.pop('pending_2fa_code', None)
                log_activity(user, 'two_factor_success', 'ورود دومرحله‌ای موفق بود.', request)
                return redirect(next_url)
            messages.error(request, 'کد تأیید نادرست است.')
            log_activity(user, 'two_factor_failed', 'کد تأیید نادرست وارد شد.', request)
    else:
        form = TwoFactorCodeForm()
    return render(request, 'login_2fa.html', {'form': form})


@super_admin_required
def super_admin_dashboard(request):
    return redirect('core:dashboard')


@super_admin_required
def super_admin_institution_create(request):
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


@super_admin_required
def super_admin_users(request):
    query = request.GET.get('q', '').strip()
    profiles = UserProfile.objects.select_related('user', 'role').order_by('full_name')
    if query:
        profiles = profiles.filter(
            Q(full_name__icontains=query)
            | Q(user__username__icontains=query)
            | Q(user__email__icontains=query)
            | Q(national_code__icontains=query)
            | Q(institution_name__icontains=query)
        )
    return render(request, 'super_admin/users.html', {'profiles': profiles[:100], 'query': query})


@super_admin_required
def super_admin_user_detail(request, profile_id):
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
    exams = Exam.objects.select_related('institution', 'course', 'designer').filter(
        status__in=[Exam.ExamStatus.ACTIVE, Exam.ExamStatus.SCHEDULED, Exam.ExamStatus.PAUSED]
    ).order_by('-starts_at')
    return render(request, 'super_admin/active_exams.html', {'exams': exams})


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
def exam_manager_dashboard(request):
    return redirect('core:dashboard')


@exam_manager_required
def exam_manager_calendar(request):
    institution = request.managed_institution
    conflicts = []
    if request.method == 'POST':
        form = ExamCalendarScheduleForm(request.POST, institution=institution)
        if form.is_valid():
            exam = form.cleaned_data.get('exam')
            course_class = form.cleaned_data.get('course_class')
            starts_at = form.cleaned_data['starts_at']
            ends_at = form.cleaned_data['ends_at']
            conflicts = find_exam_conflicts(institution, starts_at, ends_at, exclude_exam=exam, course_class=course_class)
            if conflicts:
                messages.error(request, 'تداخل زمانی پیدا شد و برنامه ثبت نشد.')
            else:
                if not exam:
                    exam = Exam.objects.create(
                        institution=institution,
                        course=course_class.course,
                        designer=course_class.teacher,
                        title=form.cleaned_data['title'],
                        starts_at=starts_at,
                        ends_at=ends_at,
                        status=Exam.ExamStatus.SCHEDULED,
                        is_active=True,
                    )
                else:
                    exam.starts_at = starts_at
                    exam.ends_at = ends_at
                    exam.status = Exam.ExamStatus.SCHEDULED
                    exam.save(update_fields=['starts_at', 'ends_at', 'status'])
                log_activity(request.user, 'exam_calendar_scheduled', f'برنامه آزمون {exam.title} ثبت شد.', request, {'exam_id': exam.pk})
                messages.success(request, 'برنامه آزمون ثبت شد و اعلان برای استادان و دانشجویان ثبت گردید.')
                return redirect('core:exam_manager_calendar')
    else:
        form = ExamCalendarScheduleForm(institution=institution)
    exams = institution.exams.select_related('course', 'designer').order_by('-starts_at')[:100]
    return render(request, 'exam_manager/calendar.html', {'institution': institution, 'form': form, 'exams': exams, 'conflicts': conflicts})


@exam_manager_required
def exam_manager_approvals(request):
    institution = request.managed_institution
    approvals = ExamApproval.objects.select_related('exam', 'requested_by').filter(exam__institution=institution)
    return render(request, 'exam_manager/approvals.html', {'institution': institution, 'approvals': approvals[:100]})


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
    return render(request, 'exam_manager/approval_review.html', {'institution': institution, 'approval': approval, 'form': form})


@exam_manager_required
def exam_manager_proctors(request):
    institution = request.managed_institution
    if request.method == 'POST':
        form = ProctorAssignmentForm(request.POST, institution=institution)
        if form.is_valid():
            exam = form.cleaned_data['exam']
            note = form.cleaned_data.get('note') or ''
            for proctor in form.cleaned_data['proctors']:
                ExamProctorAssignment.objects.update_or_create(
                    exam=exam,
                    proctor=proctor,
                    defaults={'assigned_by': request.user, 'note': note, 'status': ExamProctorAssignment.Status.ASSIGNED},
                )
                exam.proctors.add(proctor)
            log_activity(request.user, 'exam_proctors_assigned', f'ناظران آزمون {exam.title} تعیین شدند.', request, {'exam_id': exam.pk})
            messages.success(request, 'ناظران تعیین شدند و اعلان مسئولیت ثبت شد.')
            return redirect('core:exam_manager_proctors')
    else:
        form = ProctorAssignmentForm(institution=institution)
    assignments = ExamProctorAssignment.objects.select_related('exam', 'proctor').filter(exam__institution=institution)[:100]
    return render(request, 'exam_manager/proctors.html', {'institution': institution, 'form': form, 'assignments': assignments})


@exam_manager_required
def exam_manager_active_exams(request):
    institution = request.managed_institution
    exams = institution.exams.filter(status__in=[Exam.ExamStatus.SCHEDULED, Exam.ExamStatus.ACTIVE]).order_by('starts_at')
    return render(request, 'exam_manager/active_exams.html', {'institution': institution, 'exams': exams})


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
    return render(request, 'exam_manager/start_control.html', {'institution': institution, 'exam': exam, 'form': form})


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
    return render(request, 'exam_manager/reschedule.html', {'institution': institution, 'form': form, 'requests': requests, 'conflicts': conflicts})


@exam_manager_required
def exam_manager_reports(request):
    institution = request.managed_institution
    if request.method == 'POST':
        form = ExamExecutionReportForm(request.POST, institution=institution)
        if form.is_valid():
            report = form.save(commit=False)
            report.prepared_by = request.user
            report.save()
            log_activity(request.user, 'exam_execution_report_saved', f'گزارش برگزاری آزمون {report.exam.title} ثبت شد.', request, {'report_id': report.pk})
            messages.success(request, 'گزارش نهایی ثبت و برای مدیر مؤسسه ارسال شد.')
            return redirect('core:exam_manager_reports')
    else:
        form = ExamExecutionReportForm(institution=institution)
    reports = ExamExecutionReport.objects.select_related('exam').filter(exam__institution=institution)[:100]
    return render(request, 'exam_manager/reports.html', {'institution': institution, 'form': form, 'reports': reports})


@teacher_required
def teacher_panel(request):
    return redirect('core:dashboard')


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
def teacher_questions(request):
    teacher = request.teacher_profile
    if request.method == 'POST':
        form = QuestionForm(request.POST, teacher=teacher)
        if form.is_valid():
            question = form.save()
            log_activity(request.user, 'teacher_question_created', 'سؤال جدید در بانک سؤال ذخیره شد.', request, {'question_id': question.pk})
            messages.success(request, 'سؤال ذخیره شد.')
            return redirect('core:teacher_questions')
    else:
        form = QuestionForm(teacher=teacher)
    questions = teacher.questions.select_related('course')[:100]
    return render(request, 'teacher/questions.html', {'teacher': teacher, 'form': form, 'questions': questions})


@teacher_required
def teacher_exams(request):
    teacher = request.teacher_profile
    exams = teacher.designed_exams.select_related('course').order_by('-created_at')[:100]
    return render(request, 'teacher/exams.html', {'teacher': teacher, 'exams': exams})


@teacher_required
def teacher_exam_create(request):
    teacher = request.teacher_profile
    if request.method == 'POST':
        form = TeacherExamForm(request.POST, teacher=teacher)
        if form.is_valid():
            exam = form.save(commit=False)
            exam.institution = teacher.institution
            exam.designer = teacher
            exam.status = Exam.ExamStatus.PENDING_APPROVAL
            exam.is_active = True
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
            ExamApproval.objects.update_or_create(
                exam=exam,
                defaults={'requested_by': teacher, 'decision': ExamApproval.Decision.PENDING, 'question_count': exam.exam_questions.count()},
            )
            log_activity(request.user, 'teacher_exam_created', f'آزمون {exam.title} برای تأیید ارسال شد.', request, {'exam_id': exam.pk})
            messages.success(request, 'آزمون ذخیره و برای تأیید ارسال شد.')
            return redirect('core:teacher_exams')
    else:
        form = TeacherExamForm(teacher=teacher)
    score_form = ExamQuestionScoreForm(questions=teacher.questions.filter(is_active=True))
    return render(request, 'teacher/exam_form.html', {'teacher': teacher, 'form': form, 'score_form': score_form})


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
def teacher_monitoring(request):
    teacher = request.teacher_profile
    exams = teacher.designed_exams.filter(status=Exam.ExamStatus.ACTIVE).order_by('starts_at')
    return render(request, 'teacher/monitoring.html', {'teacher': teacher, 'exams': exams})


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
def teacher_reviews(request):
    teacher = request.teacher_profile
    reviews = DescriptiveAnswerReview.objects.select_related('exam', 'question', 'student').filter(exam__designer=teacher)
    assistants = UserProfile.objects.select_related('user').filter(
        role__code=SystemRole.RoleCode.TEACHING_ASSISTANT,
        supervisor_teacher=teacher.profile.user,
    )
    return render(request, 'teacher/reviews.html', {'teacher': teacher, 'reviews': reviews[:100], 'assistants': assistants})


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
    return render(request, 'teacher/review_detail.html', {'teacher': teacher, 'review': review, 'form': form})


@teacher_required
def teacher_results(request):
    teacher = request.teacher_profile
    exams = teacher.designed_exams.all()[:100]
    return render(request, 'teacher/results.html', {'teacher': teacher, 'exams': exams})


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


@teacher_required
def teacher_objections(request):
    teacher = request.teacher_profile
    objections = StudentObjection.objects.select_related('exam', 'question', 'student').filter(exam__designer=teacher)
    return render(request, 'teacher/objections.html', {'teacher': teacher, 'objections': objections[:100]})


@teacher_required
def teacher_objection_detail(request, objection_id):
    teacher = request.teacher_profile
    objection = get_object_or_404(StudentObjection.objects.select_related('exam', 'question', 'student'), pk=objection_id, exam__designer=teacher)
    if request.method == 'POST':
        form = ObjectionReviewForm(request.POST, instance=objection)
        if form.is_valid():
            item = form.save(commit=False)
            item.reviewed_by = request.user
            item.reviewed_at = timezone.now()
            item.save()
            log_activity(request.user, 'teacher_objection_reviewed', f'اعتراض دانشجو بررسی شد: {item.get_decision_display()}', request, {'objection_id': item.pk})
            messages.success(request, 'نتیجه اعتراض برای دانشجو ثبت شد.')
            return redirect('core:teacher_objections')
    else:
        form = ObjectionReviewForm(instance=objection)
    return render(request, 'teacher/objection_detail.html', {'teacher': teacher, 'objection': objection, 'form': form})


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
    return render(request, 'assistant/review_detail.html', {'teacher': request.assistant_teacher, 'assignment': assignment, 'form': form})


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
def student_exam_schedule(request):
    student = request.student_profile
    exams = student_available_exams(student)
    attempts = {
        attempt.exam_id: attempt
        for attempt in student.exam_attempts.select_related('exam').filter(exam__in=exams)
    }
    return render(request, 'student/exam_schedule.html', {'student': student, 'exams': exams, 'attempts': attempts, 'now': timezone.now()})


@student_required
def student_exam_detail(request, exam_id):
    student = request.student_profile
    exam = get_object_or_404(student_available_exams(student).prefetch_related('exam_questions__question'), pk=exam_id)
    attempt = get_student_attempt(student, exam)
    now = timezone.now()
    seconds_until_start = max(0, int((exam.starts_at - now).total_seconds()))
    can_enter = exam.starts_at <= now <= exam.ends_at and not attempt.is_locked
    entry_expired = now > exam.ends_at and not attempt.is_locked
    if seconds_until_start:
        StudentExamEvent.objects.get_or_create(
            attempt=attempt,
            event_type=StudentExamEvent.EventType.ENTERED_EARLY,
            defaults={'message': 'دانشجو پیش از زمان مجاز وارد جزئیات آزمون شد.'},
        )
    if entry_expired:
        StudentExamEvent.objects.get_or_create(
            attempt=attempt,
            event_type=StudentExamEvent.EventType.ENTRY_EXPIRED,
            defaults={'message': 'دانشجو پس از پایان بازه ورود مراجعه کرد.'},
        )
    return render(request, 'student/exam_detail.html', {
        'student': student,
        'exam': exam,
        'attempt': attempt,
        'can_enter': can_enter,
        'entry_expired': entry_expired,
        'seconds_until_start': seconds_until_start,
        'now': now,
    })


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
def student_exam_entry(request, exam_id):
    student = request.student_profile
    exam = get_object_or_404(student_available_exams(student), pk=exam_id)
    attempt = get_student_attempt(student, exam)
    now = timezone.now()
    if attempt.is_locked:
        return redirect('core:student_attempt_receipt', attempt_id=attempt.pk)
    if now < exam.starts_at:
        StudentExamEvent.objects.create(attempt=attempt, event_type=StudentExamEvent.EventType.ENTERED_EARLY, message='ورود زودتر از زمان مجاز.')
        messages.error(request, 'زمان آزمون هنوز شروع نشده است.')
        return redirect('core:student_exam_detail', exam_id=exam.pk)
    if now > exam.ends_at:
        attempt.status = StudentExamAttempt.Status.BLOCKED
        attempt.save(update_fields=['status'])
        StudentExamEvent.objects.create(attempt=attempt, event_type=StudentExamEvent.EventType.ENTRY_EXPIRED, message='زمان ورود به آزمون گذشته است.')
        messages.error(request, 'زمان ورود به آزمون گذشته است.')
        return redirect('core:student_exam_detail', exam_id=exam.pk)
    if request.method == 'POST':
        form = StudentExamEntryForm(request.POST, request.FILES, exam=exam, instance=attempt)
        if form.is_valid():
            attempt = form.save(commit=False)
            identity_missing = exam.require_identity_verification and not (attempt.identity_code or attempt.identity_image)
            if identity_missing:
                attempt.status = StudentExamAttempt.Status.WAITING_PROCTOR
                attempt.save(update_fields=['identity_code', 'identity_image', 'status'])
                StudentExamEvent.objects.create(attempt=attempt, event_type=StudentExamEvent.EventType.IDENTITY_FAILED, message='احراز هویت ناقص بود و برای ناظر ارسال شد.')
                messages.error(request, 'احراز هویت کامل نیست؛ درخواست برای ناظر ثبت شد.')
                return redirect('core:student_exam_detail', exam_id=exam.pk)
            attempt.identity_confirmed = True
            attempt.rules_accepted = form.cleaned_data['accept_rules']
            attempt.save(update_fields=['identity_code', 'identity_image', 'identity_confirmed', 'rules_accepted'])
            messages.success(request, 'احراز هویت و قوانین تأیید شد. اکنون می‌توانید آزمون را شروع کنید.')
            return redirect('core:student_exam_entry', exam_id=exam.pk)
    else:
        form = StudentExamEntryForm(exam=exam, instance=attempt)
    can_start = attempt.identity_confirmed and attempt.rules_accepted and exam.starts_at <= now <= exam.ends_at
    return render(request, 'student/exam_entry.html', {'student': student, 'exam': exam, 'attempt': attempt, 'form': form, 'can_start': can_start})


@student_required
def student_exam_start(request, exam_id):
    student = request.student_profile
    exam = get_object_or_404(student_available_exams(student), pk=exam_id)
    attempt = get_student_attempt(student, exam)
    now = timezone.now()
    if not (attempt.identity_confirmed and attempt.rules_accepted):
        messages.error(request, 'ابتدا احراز هویت و قوانین آزمون را تکمیل کنید.')
        return redirect('core:student_exam_entry', exam_id=exam.pk)
    if now < exam.starts_at or now > exam.ends_at:
        messages.error(request, 'اکنون زمان مجاز شروع آزمون نیست.')
        return redirect('core:student_exam_detail', exam_id=exam.pk)
    if not attempt.started_at:
        attempt.started_at = now
        attempt.status = StudentExamAttempt.Status.IN_PROGRESS
        attempt.last_activity_at = now
        attempt.save(update_fields=['started_at', 'status', 'last_activity_at'])
        StudentExamEvent.objects.create(attempt=attempt, event_type=StudentExamEvent.EventType.STARTED, message='دانشجو آزمون را آغاز کرد.')
    return redirect('core:student_attempt', attempt_id=attempt.pk)


@student_required
def student_attempt(request, attempt_id):
    student = request.student_profile
    attempt = get_object_or_404(
        StudentExamAttempt.objects.select_related('exam', 'exam__course', 'exam__designer', 'exam__designer__profile'),
        pk=attempt_id,
        student=student,
    )
    if attempt.is_locked:
        return redirect('core:student_attempt_receipt', attempt_id=attempt.pk)
    remaining = remaining_exam_seconds(attempt)
    if remaining is not None and remaining <= 0:
        finalize_student_attempt(attempt, StudentExamEvent.EventType.AUTO_SUBMITTED, 'زمان آزمون به پایان رسید و آزمون خودکار ارسال شد.')
        messages.info(request, 'زمان آزمون به پایان رسید و پاسخ‌ها به‌صورت خودکار ارسال شدند.')
        return redirect('core:student_attempt_receipt', attempt_id=attempt.pk)
    answers = list(attempt.answers.select_related('exam_question__question').all())
    current_index = int(request.GET.get('q', 1) or 1)
    current_index = max(1, min(current_index, len(answers) or 1))
    current_answer = answers[current_index - 1] if answers else None
    if not current_answer:
        messages.error(request, 'برای این آزمون سؤالی ثبت نشده است.')
        return redirect('core:student_exam_detail', exam_id=attempt.exam_id)
    if request.method == 'POST':
        form = StudentAnswerForm(
            request.POST,
            request.FILES,
            instance=current_answer,
            exam_question=current_answer.exam_question,
            allow_file_upload=attempt.exam.allow_file_upload,
        )
        if form.is_valid():
            item = form.save(commit=False)
            item.autosaved_at = timezone.now()
            item.save()
            attempt.last_activity_at = timezone.now()
            attempt.save(update_fields=['last_activity_at'])
            StudentExamEvent.objects.create(attempt=attempt, event_type=StudentExamEvent.EventType.ANSWER_SAVED, message=f'پاسخ سؤال {current_index} ذخیره شد.')
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({'ok': True, 'saved_at': item.autosaved_at.isoformat()})
            action = request.POST.get('action')
            if action == 'previous':
                current_index = max(1, current_index - 1)
            elif action == 'submit':
                return redirect('core:student_attempt_submit', attempt_id=attempt.pk)
            else:
                current_index = min(len(answers), current_index + 1)
            return redirect(f'{reverse("core:student_attempt", args=[attempt.pk])}?q={current_index}')
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            StudentExamEvent.objects.create(attempt=attempt, event_type=StudentExamEvent.EventType.FILE_REJECTED, message=str(form.errors))
            return JsonResponse({'ok': False, 'errors': form.errors}, status=400)
    else:
        form = StudentAnswerForm(instance=current_answer, exam_question=current_answer.exam_question, allow_file_upload=attempt.exam.allow_file_upload)
    answered_count = sum(1 for item in answers if item.has_answer)
    marked_count = sum(1 for item in answers if item.marked_for_review)
    return render(request, 'student/attempt.html', {
        'student': student,
        'attempt': attempt,
        'answers': answers,
        'current_answer': current_answer,
        'current_index': current_index,
        'total_questions': len(answers),
        'answered_count': answered_count,
        'unanswered_count': len(answers) - answered_count,
        'marked_count': marked_count,
        'remaining_seconds': remaining,
        'form': form,
    })


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


@student_required
def student_attempt_submit(request, attempt_id):
    student = request.student_profile
    attempt = get_object_or_404(StudentExamAttempt.objects.select_related('exam'), pk=attempt_id, student=student)
    if attempt.is_locked:
        return redirect('core:student_attempt_receipt', attempt_id=attempt.pk)
    answers = attempt.answers.select_related('exam_question__question')
    unanswered_count = sum(1 for answer in answers if not answer.has_answer)
    if request.method == 'POST':
        event_type = StudentExamEvent.EventType.AUTO_SUBMITTED if request.POST.get('auto') else StudentExamEvent.EventType.SUBMITTED
        finalize_student_attempt(attempt, event_type, 'پاسخ‌نامه قفل و ارسال شد.')
        messages.success(request, 'آزمون ارسال شد و پاسخ‌نامه قفل شد.')
        return redirect('core:student_attempt_receipt', attempt_id=attempt.pk)
    return render(request, 'student/submit_confirm.html', {'student': student, 'attempt': attempt, 'unanswered_count': unanswered_count})


@student_required
def student_attempt_receipt(request, attempt_id):
    student = request.student_profile
    attempt = get_object_or_404(StudentExamAttempt.objects.select_related('exam'), pk=attempt_id, student=student)
    return render(request, 'student/receipt.html', {'student': student, 'attempt': attempt})


@student_required
def student_results(request):
    student = request.student_profile
    attempts = StudentExamAttempt.objects.select_related('exam', 'exam__result_publication').filter(
        student=student,
        status__in=[StudentExamAttempt.Status.SUBMITTED, StudentExamAttempt.Status.AUTO_SUBMITTED],
        exam__result_publication__is_published=True,
    )
    return render(request, 'student/results.html', {'student': student, 'attempts': attempts})


@student_required
def student_result_detail(request, attempt_id):
    student = request.student_profile
    attempt = get_object_or_404(
        StudentExamAttempt.objects.select_related('exam', 'exam__result_publication'),
        pk=attempt_id,
        student=student,
        exam__result_publication__is_published=True,
    )
    score, total = calculate_attempt_score(attempt)
    publication = attempt.exam.result_publication
    passed = attempt.exam.passing_score is None or score >= float(attempt.exam.passing_score)
    return render(request, 'student/result_detail.html', {
        'student': student,
        'attempt': attempt,
        'score': score,
        'total': total,
        'passed': passed,
        'publication': publication,
    })


@student_required
def student_objections(request):
    student = request.student_profile
    if request.method == 'POST':
        form = StudentObjectionCreateForm(request.POST, request.FILES, student=student)
        if form.is_valid():
            objection = form.save(commit=False)
            objection.student = student
            objection.save()
            log_activity(request.user, 'student_objection_created', 'اعتراض دانشجو ثبت شد.', request, {'objection_id': objection.pk})
            messages.success(request, 'اعتراض شما ثبت شد و برای بررسی ارسال گردید.')
            return redirect('core:student_objections')
    else:
        form = StudentObjectionCreateForm(student=student)
    objections = StudentObjection.objects.select_related('exam', 'question').filter(student=student)[:100]
    return render(request, 'student/objections.html', {'student': student, 'form': form, 'objections': objections})


def home(request):
    upcoming_exams = Exam.objects.filter(is_active=True)[:5]
    return render(request, 'home.html', {'upcoming_exams': upcoming_exams})


@login_required
def dashboard(request):
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
            'today_logs_count': UserActivityLog.objects.filter(created_at__date=today).count(),
            'recent_logs': UserActivityLog.objects.select_related('user').order_by('-created_at')[:5],
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
            {'title': 'تأیید آزمون استاد', 'url': reverse('core:exam_manager_approvals')},
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


def logout_view(request):
    logout(request)
    return redirect('core:login')


def error_404(request, exception):
    return render(request, '404.html', status=404)


def error_500(request):
    return render(request, '500.html', status=500)
