"""
apps/core/models.py — طراحی مدل پس از مهاجرت (فاز ۱ نقشه‌راه)

نکات مهم قبل از استفاده:
  ۱. این فایل بر اساس توصیف گزارش نویسی فاز ۱ نوشته شده، نه ویرایش مستقیم
     models.py واقعی پروژه — چون آن فایل در اختیارم نبود. قبل از اجرا حتماً
     با مدل‌های فعلی diff بگیرید تا فیلدهای موجود (مثل created_at/updated_at
     پایه، یا فیلدهای اضافه‌ای که در گزارش نیامده) گم نشوند.
  ۲. فقط PostgreSQL مد نظر است — از JSONField بومی (jsonb) استفاده شده که فقط
     روی پستگرس بهینه است (روی SQLite هم کار می‌کند ولی ایندکس GIN نمی‌گیرد).
  ۳. تصمیم سلسله‌مراتب مدیران (بخش ۹.۲ گزارش فاز اول): مدیر آموزشی از طریق
     تودرتویی AcademicUnit به زیرشاخه‌ها دسترسی دارد، FK مستقیم
     manager-to-manager عمداً اضافه نشده. اگر کارفرما رابطه‌ی مستقیم
     «مدیر بالادست ↔ مدیر زیردست» را (جدا از واحد سازمانی) بخواهد، این
     تصمیم باید قبل از اجرای migration بازبینی شود.
"""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone
from django.contrib.postgres.indexes import GinIndex


# =============================================================================
# نقش‌ها و کاربر پایه
# =============================================================================

class SystemRole(models.Model):
    """جدول مرجع نقش‌ها — بدون تغییر نسبت به وضعیت فعلی."""

    class RoleCode(models.TextChoices):
        SUPER_ADMIN = "super_admin", "مدیر سیستم"
        INSTITUTION_ADMIN = "institution_admin", "مدیر مؤسسه"
        EXAM_MANAGER = "exam_manager", "مدیر آموزشی"
        TEACHER = "teacher", "استاد"
        TEACHING_ASSISTANT = "teaching_assistant", "دستیار آموزشی"
        STUDENT = "student", "دانشجو"
        EXAM_PROCTOR = "exam_proctor", "ناظر آزمون"
        TECH_SUPPORT = "tech_support", "پشتیبانی فنی"

    code = models.CharField(max_length=32, choices=RoleCode.choices, unique=True)
    label = models.CharField(max_length=128)

    def __str__(self):
        return self.get_code_display()


# =============================================================================
# ساختار سازمانی — پایه‌ی سلسله‌مراتب
# =============================================================================

class Institution(models.Model):
    """مؤسسه‌ی آموزشی سطح بالا (چند مؤسسه در یک سامانه پشتیبانی می‌شود)."""

    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255, unique=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class AcademicUnit(models.Model):
    """
    واحد سازمانی درختی (دانشکده/گروه/زیرمجموعه). خودارجاع برای پشتیبانی
    از عمق دلخواه. سلسله‌مراتب مدیران آموزشی از طریق همین درخت استنتاج
    می‌شود: مدیری که به یک AcademicUnit متصل است، به همه‌ی زیرشاخه‌های آن
    هم دسترسی دارد.
    """

    institution = models.ForeignKey(
        Institution, on_delete=models.CASCADE, related_name="academic_units"
    )
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="children",
    )
    name = models.CharField(max_length=255)

    # مسیر ماتریالایز‌شده برای کوئری سریع زیرشاخه‌ها بدون CTE بازگشتی
    # (جایگزین _erd_manager_scope_cte در فایل خام). با هر ذخیره به‌روزرسانی
    # می‌شود، مثال: "1/4/17/" یعنی واحد ۱۷ زیرمجموعه‌ی ۴ زیرمجموعه‌ی ۱ است.
    path = models.CharField(max_length=1024, editable=False, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["institution", "parent"]),
            models.Index(fields=["path"]),
        ]

    def __str__(self):
        return self.name

    def clean(self):
        # جلوگیری از حلقه در درخت (والد نمی‌تواند خودش یا یکی از نوادگانش باشد)
        if self.parent_id:
            node = self.parent
            while node is not None:
                if node.pk == self.pk:
                    raise ValidationError("امکان ایجاد حلقه در ساختار سازمانی وجود ندارد.")
                node = node.parent

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        new_path = f"{self.parent.path}{self.pk}/" if self.parent_id else f"{self.pk}/"
        if new_path != self.path:
            AcademicUnit.objects.filter(pk=self.pk).update(path=new_path)
            self.path = new_path

    def descendant_ids(self, include_self=True):
        """لیست id همه‌ی زیرشاخه‌ها (برای فیلتر کوئری‌ست‌ها) — جایگزین CTE خام."""
        qs = AcademicUnit.objects.filter(path__startswith=self.path)
        ids = list(qs.values_list("id", flat=True))
        if not include_self and self.pk in ids:
            ids.remove(self.pk)
        return ids


class AcademicTerm(models.Model):
    institution = models.ForeignKey(
        Institution, on_delete=models.CASCADE, related_name="terms"
    )
    name = models.CharField(max_length=128)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                check=Q(ends_at__gt=models.F("starts_at")),
                name="term_end_after_start",
            )
        ]


class SystemSetting(models.Model):
    """معادل ORM جدول system_settings خام — کلید/مقدار با jsonb."""

    key = models.CharField(max_length=255, unique=True)
    value = models.JSONField(default=dict)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [GinIndex(fields=["value"])]

    def __str__(self):
        return self.key


# =============================================================================
# پروفایل‌های نقش — همه با OneToOne به User
# =============================================================================

class SystemAdminProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="system_admin_profile"
    )


class InstitutionAdminProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="institution_admin_profile"
    )
    institution = models.ForeignKey(
        Institution, on_delete=models.CASCADE, related_name="admin_profiles"
    )
    managed_units = models.ManyToManyField(
        AcademicUnit, blank=True, related_name="institution_admins"
    )


class ExamManagerProfile(models.Model):
    """
    جدید — تا‌کنون در ORM وجود نداشت (بخش ۳ گزارش فاز اول). دامنه‌ی دسترسی
    از طریق managed_unit + descendant_ids() محدود می‌شود، نه کل مؤسسه.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="exam_manager_profile"
    )
    institution = models.ForeignKey(
        Institution, on_delete=models.CASCADE, related_name="exam_manager_profiles"
    )
    managed_unit = models.ForeignKey(
        AcademicUnit,
        on_delete=models.PROTECT,
        related_name="exam_managers",
        help_text="واحد سازمانی که این مدیر مسئول آن (و همه‌ی زیرشاخه‌هایش) است.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def accessible_unit_ids(self):
        return self.managed_unit.descendant_ids(include_self=True)


class TeacherProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="teacher_profile"
    )
    institution = models.ForeignKey(Institution, on_delete=models.CASCADE, related_name="teachers")
    academic_unit = models.ForeignKey(
        AcademicUnit, null=True, blank=True, on_delete=models.SET_NULL, related_name="teachers"
    )


class TeachingAssistantProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="ta_profile"
    )
    supervising_teacher = models.ForeignKey(
        TeacherProfile, on_delete=models.CASCADE, related_name="assistants"
    )


class StudentProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="student_profile"
    )
    institution = models.ForeignKey(Institution, on_delete=models.CASCADE, related_name="students")
    academic_unit = models.ForeignKey(
        AcademicUnit, null=True, blank=True, on_delete=models.SET_NULL, related_name="students"
    )
    student_number = models.CharField(max_length=64, unique=True)


class ExamProctorProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="proctor_profile"
    )
    institution = models.ForeignKey(Institution, on_delete=models.CASCADE, related_name="proctors")


class TechnicalSupportProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="tech_support_profile"
    )


# =============================================================================
# درس‌ها و گروه‌بندی
# =============================================================================

class Course(models.Model):
    institution = models.ForeignKey(Institution, on_delete=models.CASCADE, related_name="courses")
    code = models.CharField(max_length=32)
    title = models.CharField(max_length=255)

    class Meta:
        unique_together = [("institution", "code")]


class CourseClass(models.Model):
    """معادل ORM جدول ERD خام student_groups + کلاس درس."""

    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="classes")
    term = models.ForeignKey(AcademicTerm, on_delete=models.PROTECT, related_name="classes")
    teacher = models.ForeignKey(
        TeacherProfile, on_delete=models.SET_NULL, null=True, related_name="classes"
    )
    academic_unit = models.ForeignKey(
        AcademicUnit, on_delete=models.PROTECT, related_name="course_classes"
    )
    students = models.ManyToManyField(StudentProfile, blank=True, related_name="classes")
    title = models.CharField(max_length=255, blank=True)


# =============================================================================
# بانک سؤال
# =============================================================================

class Question(models.Model):
    class QuestionType(models.TextChoices):
        MULTIPLE_CHOICE = "multiple_choice", "چهارگزینه‌ای"
        MULTI_SELECT = "multi_select", "چندپاسخی"          # جدید — طبق تصمیم ۹.۵
        ORDERING = "ordering", "مرتب‌سازی"                  # جدید — طبق تصمیم ۹.۵
        TRUE_FALSE = "true_false", "درست/نادرست"
        FILL_BLANK = "fill_blank", "جای‌خالی"
        SHORT_ANSWER = "short_answer", "پاسخ کوتاه"
        ESSAY = "essay", "تشریحی"
        MATCHING = "matching", "تطبیقی"

    institution = models.ForeignKey(Institution, on_delete=models.CASCADE, related_name="questions")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    question_type = models.CharField(max_length=32, choices=QuestionType.choices)
    body = models.TextField()

    # ساختار پاسخ‌ها/گزینه‌ها به‌صورت jsonb — چون شکل داده بسته به question_type
    # کاملاً متفاوت است (گزینه‌ها برای چندگزینه‌ای‌ها، ترتیب صحیح برای مرتب‌سازی،
    # rubric برای تشریحی). به‌جای جدول‌های جدا برای هر نوع، انعطاف با jsonb حفظ می‌شود.
    payload = models.JSONField(default=dict)

    # فیلد باز برای ساختارهای پیچیده‌تر (سناریوی بیمار / KFP / OSCE) که طبق
    # تصمیم ۹.۶ هنوز مشخص نیست الزامی فاز اول باشند — این فیلد صرفاً جای
    # ذخیره‌سازی را باز می‌گذارد بدون اینکه مدل جداگانه بسازیم زودتر از تصمیم.
    scenario_data = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [GinIndex(fields=["payload"])]


# =============================================================================
# آزمون
# =============================================================================

class Exam(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "پیش‌نویس"
        PENDING_APPROVAL = "pending_approval", "در انتظار تأیید"
        SCHEDULED = "scheduled", "زمان‌بندی‌شده"
        ACTIVE = "active", "در حال اجرا"
        PAUSED = "paused", "متوقف‌شده"
        FINISHED = "finished", "پایان‌یافته"
        CANCELLED = "cancelled", "لغوشده"

    institution = models.ForeignKey(Institution, on_delete=models.CASCADE, related_name="exams")
    course_class = models.ForeignKey(
        CourseClass, on_delete=models.CASCADE, related_name="exams"
    )
    title = models.CharField(max_length=255)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.DRAFT)

    # تنظیمات آزمون (randomize_questions, negative_marking, duration_minutes, ...)
    settings_payload = models.JSONField(default=dict)

    questions = models.ManyToManyField(Question, through="ExamQuestion", related_name="exams")

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)


class ExamQuestion(models.Model):
    exam = models.ForeignKey(Exam, on_delete=models.CASCADE)
    question = models.ForeignKey(Question, on_delete=models.PROTECT)
    order = models.PositiveIntegerField(default=0)
    points = models.DecimalField(max_digits=6, decimal_places=2, default=1)

    class Meta:
        unique_together = [("exam", "question")]
        ordering = ["order"]


class ExamApproval(models.Model):
    class Decision(models.TextChoices):
        PENDING = "pending", "در انتظار"
        APPROVED = "approved", "تأییدشده"
        REJECTED = "rejected", "ردشده"

    exam = models.ForeignKey(Exam, on_delete=models.CASCADE, related_name="approvals")
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    decision = models.CharField(max_length=16, choices=Decision.choices, default=Decision.PENDING)
    decided_at = models.DateTimeField(null=True, blank=True)
    note = models.TextField(blank=True)


class ExamStartAuthorization(models.Model):
    exam = models.ForeignKey(Exam, on_delete=models.CASCADE, related_name="start_authorizations")
    authorized_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    code = models.CharField(max_length=32, unique=True)
    expires_at = models.DateTimeField()


# =============================================================================
# اجرای آزمون توسط دانشجو
# =============================================================================

class StudentExamAttempt(models.Model):
    class Status(models.TextChoices):
        IN_PROGRESS = "in_progress", "در حال انجام"
        SUBMITTED = "submitted", "ثبت‌شده"
        GRADED = "graded", "نمره‌داده‌شده"
        VOIDED = "voided", "باطل‌شده"

    exam = models.ForeignKey(Exam, on_delete=models.CASCADE, related_name="attempts")
    student = models.ForeignKey(StudentProfile, on_delete=models.CASCADE, related_name="attempts")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.IN_PROGRESS)
    started_at = models.DateTimeField(default=timezone.now)
    submitted_at = models.DateTimeField(null=True, blank=True)
    total_score = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)

    class Meta:
        unique_together = [("exam", "student")]


class StudentQuestionAnswer(models.Model):
    attempt = models.ForeignKey(
        StudentExamAttempt, on_delete=models.CASCADE, related_name="answers"
    )
    question = models.ForeignKey(Question, on_delete=models.PROTECT, related_name="+")
    answer_payload = models.JSONField(default=dict)
    score = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    graded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        unique_together = [("attempt", "question")]


class StudentExamEvent(models.Model):
    """رویدادهای تایمر/فوکوس/خروج از تب و... برای مانیتورینگ حین آزمون."""

    attempt = models.ForeignKey(
        StudentExamAttempt, on_delete=models.CASCADE, related_name="events"
    )
    event_type = models.CharField(max_length=64)
    occurred_at = models.DateTimeField(default=timezone.now)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        indexes = [models.Index(fields=["attempt", "occurred_at"])]
