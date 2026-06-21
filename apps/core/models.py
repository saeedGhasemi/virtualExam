from django.conf import settings
from django.db import models


class SystemRole(models.Model):
    class RoleCode(models.TextChoices):
        SUPER_ADMIN = 'super_admin', 'مدیر کل سیستم'
        INSTITUTION_ADMIN = 'institution_admin', 'مدیر مؤسسه، دانشگاه یا مدرسه'
        EXAM_MANAGER = 'exam_manager', 'مدیر آموزش یا مسئول امتحانات'
        TEACHER = 'teacher', 'استاد یا طراح سؤال'
        TEACHING_ASSISTANT = 'teaching_assistant', 'کمک‌استاد یا دستیار آموزشی'
        STUDENT = 'student', 'دانشجو یا داوطلب'
        EXAM_PROCTOR = 'exam_proctor', 'ناظر آزمون'
        TECH_SUPPORT = 'tech_support', 'پشتیبان فنی'

    code = models.CharField(max_length=40, choices=RoleCode.choices, unique=True)
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    access_level = models.PositiveSmallIntegerField(default=1)
    permissions = models.JSONField(default=list, blank=True)
    duties = models.JSONField(default=list, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-access_level', 'name']
        verbose_name = 'نقش سیستم'
        verbose_name_plural = 'نقش‌های سیستم'

    def __str__(self):
        return self.name


class AcademicInstitution(models.Model):
    class InstitutionType(models.TextChoices):
        UNIVERSITY = 'university', 'دانشگاه'
        SCHOOL = 'school', 'مدرسه'
        INSTITUTE = 'institute', 'مؤسسه'
        ORGANIZATION = 'organization', 'سازمان'

    class InstitutionStatus(models.TextChoices):
        ACTIVE = 'active', 'فعال'
        INACTIVE = 'inactive', 'غیرفعال'
        SUSPENDED = 'suspended', 'تعلیق'

    name = models.CharField(max_length=180)
    institution_type = models.CharField(max_length=30, choices=InstitutionType.choices, default=InstitutionType.INSTITUTE)
    registration_code = models.CharField(max_length=60, blank=True)
    national_id = models.CharField(max_length=30, blank=True)
    phone = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    website = models.URLField(blank=True)
    province = models.CharField(max_length=80, blank=True)
    city = models.CharField(max_length=80, blank=True)
    address = models.TextField(blank=True)
    logo = models.FileField(upload_to='institutions/logos/', blank=True)
    status = models.CharField(max_length=20, choices=InstitutionStatus.choices, default=InstitutionStatus.ACTIVE)
    max_users = models.PositiveIntegerField(null=True, blank=True)
    max_exams = models.PositiveIntegerField(null=True, blank=True)
    subscription_started_at = models.DateField(null=True, blank=True)
    subscription_ended_at = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        verbose_name = 'مرکز آموزشی'
        verbose_name_plural = 'مراکز آموزشی'

    def __str__(self):
        return self.name


class AcademicUnit(models.Model):
    class UnitType(models.TextChoices):
        FACULTY = 'faculty', 'دانشکده'
        DEPARTMENT = 'department', 'گروه آموزشی'
        GRADE = 'grade', 'پایه'
        CLASS_GROUP = 'class_group', 'کلاس یا گروه'

    institution = models.ForeignKey(AcademicInstitution, on_delete=models.CASCADE, related_name='units')
    parent = models.ForeignKey('self', on_delete=models.CASCADE, null=True, blank=True, related_name='children')
    name = models.CharField(max_length=160)
    code = models.CharField(max_length=40, blank=True)
    unit_type = models.CharField(max_length=30, choices=UnitType.choices, default=UnitType.DEPARTMENT)
    manager = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='managed_units')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['institution__name', 'name']
        unique_together = ('institution', 'code')
        verbose_name = 'واحد آموزشی'
        verbose_name_plural = 'واحدهای آموزشی'

    def __str__(self):
        return f'{self.name} - {self.institution}'


class Course(models.Model):
    institution = models.ForeignKey(AcademicInstitution, on_delete=models.CASCADE, related_name='courses')
    academic_unit = models.ForeignKey(AcademicUnit, on_delete=models.SET_NULL, null=True, blank=True, related_name='courses')
    title = models.CharField(max_length=180)
    code = models.CharField(max_length=50, blank=True)
    credit_count = models.PositiveSmallIntegerField(null=True, blank=True)
    education_level = models.CharField(max_length=80, blank=True)
    semester = models.CharField(max_length=40, blank=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['title']
        unique_together = ('institution', 'code')
        verbose_name = 'درس'
        verbose_name_plural = 'درس‌ها'

    def __str__(self):
        return self.title


class AcademicTerm(models.Model):
    institution = models.ForeignKey(AcademicInstitution, on_delete=models.CASCADE, related_name='terms')
    title = models.CharField(max_length=120)
    year = models.PositiveSmallIntegerField(null=True, blank=True)
    starts_at = models.DateField(null=True, blank=True)
    ends_at = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-year', 'title']
        unique_together = ('institution', 'title')
        verbose_name = 'نیم‌سال تحصیلی'
        verbose_name_plural = 'نیم‌سال‌های تحصیلی'

    def __str__(self):
        return f'{self.title} - {self.institution}'


class CourseClass(models.Model):
    institution = models.ForeignKey(AcademicInstitution, on_delete=models.CASCADE, related_name='classes')
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name='classes')
    term = models.ForeignKey(AcademicTerm, on_delete=models.SET_NULL, null=True, blank=True, related_name='classes')
    title = models.CharField(max_length=160)
    code = models.CharField(max_length=50, blank=True)
    teacher = models.ForeignKey('TeacherProfile', on_delete=models.SET_NULL, null=True, blank=True, related_name='classes')
    students = models.ManyToManyField('StudentProfile', blank=True, related_name='classes')
    capacity = models.PositiveIntegerField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['title']
        unique_together = ('institution', 'code')
        verbose_name = 'کلاس درس'
        verbose_name_plural = 'کلاس‌های درس'

    def __str__(self):
        return self.title


class Question(models.Model):
    class QuestionType(models.TextChoices):
        MULTIPLE_CHOICE = 'multiple_choice', 'چهارگزینه‌ای'
        TRUE_FALSE = 'true_false', 'صحیح و غلط'
        FILL_BLANK = 'fill_blank', 'جای‌خالی'
        SHORT_ANSWER = 'short_answer', 'پاسخ کوتاه'
        DESCRIPTIVE = 'descriptive', 'تشریحی'
        MATCHING = 'matching', 'تطبیقی'

    class Difficulty(models.TextChoices):
        EASY = 'easy', 'آسان'
        MEDIUM = 'medium', 'متوسط'
        HARD = 'hard', 'سخت'

    teacher = models.ForeignKey('TeacherProfile', on_delete=models.CASCADE, related_name='questions')
    course = models.ForeignKey(Course, on_delete=models.SET_NULL, null=True, blank=True, related_name='questions')
    question_type = models.CharField(max_length=30, choices=QuestionType.choices)
    text = models.TextField()
    options = models.JSONField(default=list, blank=True)
    correct_answer = models.TextField(blank=True)
    difficulty = models.CharField(max_length=20, choices=Difficulty.choices, default=Difficulty.MEDIUM)
    chapter = models.CharField(max_length=120, blank=True)
    topic = models.CharField(max_length=160, blank=True)
    suggested_score = models.DecimalField(max_digits=6, decimal_places=2, default=1)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'سؤال'
        verbose_name_plural = 'بانک سؤال'

    def __str__(self):
        return self.text[:80]


class ExamQuestion(models.Model):
    exam = models.ForeignKey('Exam', on_delete=models.CASCADE, related_name='exam_questions')
    question = models.ForeignKey(Question, on_delete=models.PROTECT, related_name='exam_links')
    score = models.DecimalField(max_digits=6, decimal_places=2, default=1)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order', 'id']
        unique_together = ('exam', 'question')
        verbose_name = 'سؤال آزمون'
        verbose_name_plural = 'سؤالات آزمون'

    def __str__(self):
        return f'{self.exam} - {self.question}'


class UserProfile(models.Model):
    class AccountStatus(models.TextChoices):
        ACTIVE = 'active', 'فعال'
        INACTIVE = 'inactive', 'غیرفعال'
        BLOCKED = 'blocked', 'مسدود'

    class Gender(models.TextChoices):
        MALE = 'male', 'مرد'
        FEMALE = 'female', 'زن'
        OTHER = 'other', 'سایر'

    class EducationStatus(models.TextChoices):
        ACTIVE = 'active', 'مشغول به تحصیل'
        GRADUATED = 'graduated', 'فارغ‌التحصیل'
        SUSPENDED = 'suspended', 'تعلیق'
        WITHDRAWN = 'withdrawn', 'انصراف'

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='profile')
    role = models.ForeignKey(SystemRole, on_delete=models.PROTECT, related_name='profiles')

    full_name = models.CharField(max_length=180)
    father_name = models.CharField(max_length=120, blank=True)
    national_code = models.CharField(max_length=20, blank=True)
    passport_number = models.CharField(max_length=30, blank=True)
    birth_date = models.DateField(null=True, blank=True)
    gender = models.CharField(max_length=20, choices=Gender.choices, blank=True)
    mobile = models.CharField(max_length=20, blank=True)
    organizational_email = models.EmailField(blank=True)
    residential_address = models.TextField(blank=True)
    profile_image = models.FileField(upload_to='profiles/', blank=True)

    personnel_number = models.CharField(max_length=40, blank=True)
    student_number = models.CharField(max_length=40, blank=True)
    applicant_code = models.CharField(max_length=40, blank=True)
    institution_name = models.CharField(max_length=180, blank=True)
    organizational_position = models.CharField(max_length=120, blank=True)
    faculty_or_unit = models.CharField(max_length=160, blank=True)
    department = models.CharField(max_length=160, blank=True)
    field_of_study = models.CharField(max_length=160, blank=True)
    specialization = models.CharField(max_length=160, blank=True)
    academic_rank_or_job_title = models.CharField(max_length=160, blank=True)
    education_level = models.CharField(max_length=80, blank=True)
    entrance_year = models.PositiveSmallIntegerField(null=True, blank=True)
    semester = models.CharField(max_length=40, blank=True)
    class_or_group = models.CharField(max_length=120, blank=True)
    education_status = models.CharField(max_length=30, choices=EducationStatus.choices, blank=True)

    account_status = models.CharField(max_length=20, choices=AccountStatus.choices, default=AccountStatus.ACTIVE)
    access_scope = models.TextField(blank=True)
    responsibility_scope = models.TextField(blank=True)
    cooperation_type = models.CharField(max_length=120, blank=True)
    cooperation_started_at = models.DateField(null=True, blank=True)
    cooperation_ended_at = models.DateField(null=True, blank=True)
    account_verified = models.BooleanField(default=False)
    two_factor_enabled = models.BooleanField(default=False)

    supervisor_teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assistant_profiles',
    )
    teachable_courses = models.JSONField(default=list, blank=True)
    selected_courses = models.JSONField(default=list, blank=True)
    related_courses = models.JSONField(default=list, blank=True)
    devices = models.JSONField(default=list, blank=True)
    login_records = models.JSONField(default=list, blank=True)
    assigned_exams = models.JSONField(default=list, blank=True)
    exam_status = models.JSONField(default=dict, blank=True)
    submitted_files = models.JSONField(default=list, blank=True)
    violations = models.JSONField(default=list, blank=True)
    objections = models.JSONField(default=list, blank=True)

    position_documents = models.FileField(upload_to='profile-documents/', blank=True)
    resume_or_academic_document = models.FileField(upload_to='profile-documents/', blank=True)
    digital_signature = models.FileField(upload_to='signatures/', blank=True)
    digital_stamp = models.FileField(upload_to='signatures/', blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['full_name']
        verbose_name = 'پروفایل کاربر'
        verbose_name_plural = 'پروفایل کاربران'

    def __str__(self):
        return f'{self.full_name} - {self.role.name}'


class SystemAdminProfile(models.Model):
    profile = models.OneToOneField(UserProfile, on_delete=models.CASCADE, related_name='system_admin_profile')
    admin_code = models.CharField(max_length=40, blank=True)
    access_scope = models.TextField(blank=True)
    can_manage_roles = models.BooleanField(default=True)
    can_manage_institutions = models.BooleanField(default=True)
    can_manage_system_settings = models.BooleanField(default=True)
    can_view_security_logs = models.BooleanField(default=True)
    can_backup_restore = models.BooleanField(default=True)
    emergency_contact = models.CharField(max_length=40, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'پروفایل مدیر کل سیستم'
        verbose_name_plural = 'پروفایل‌های مدیران کل سیستم'

    def __str__(self):
        return self.profile.full_name


class InstitutionAdminProfile(models.Model):
    profile = models.OneToOneField(UserProfile, on_delete=models.CASCADE, related_name='institution_admin_profile')
    institution = models.ForeignKey(AcademicInstitution, on_delete=models.PROTECT, related_name='admins')
    employee_code = models.CharField(max_length=40, blank=True)
    position_title = models.CharField(max_length=120, blank=True)
    managed_units = models.ManyToManyField(AcademicUnit, blank=True, related_name='institution_admins')
    can_approve_users = models.BooleanField(default=True)
    can_manage_teachers = models.BooleanField(default=True)
    can_manage_students = models.BooleanField(default=True)
    can_schedule_exams = models.BooleanField(default=True)
    can_view_reports = models.BooleanField(default=True)
    appointment_started_at = models.DateField(null=True, blank=True)
    appointment_ended_at = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'پروفایل مدیر مرکز آموزشی'
        verbose_name_plural = 'پروفایل‌های مدیران مراکز آموزشی'

    def __str__(self):
        return f'{self.profile.full_name} - {self.institution}'


class TeacherProfile(models.Model):
    class EmploymentType(models.TextChoices):
        FULL_TIME = 'full_time', 'تمام‌وقت'
        PART_TIME = 'part_time', 'پاره‌وقت'
        CONTRACT = 'contract', 'قراردادی'
        GUEST = 'guest', 'مدعو'

    profile = models.OneToOneField(UserProfile, on_delete=models.CASCADE, related_name='teacher_profile')
    institution = models.ForeignKey(AcademicInstitution, on_delete=models.PROTECT, related_name='teachers')
    academic_unit = models.ForeignKey(AcademicUnit, on_delete=models.SET_NULL, null=True, blank=True, related_name='teachers')
    personnel_code = models.CharField(max_length=40, blank=True)
    academic_rank = models.CharField(max_length=120, blank=True)
    specialization = models.CharField(max_length=160, blank=True)
    employment_type = models.CharField(max_length=30, choices=EmploymentType.choices, blank=True)
    courses = models.ManyToManyField(Course, blank=True, related_name='teachers')
    can_design_exam = models.BooleanField(default=True)
    can_grade_answers = models.BooleanField(default=True)
    can_publish_grades = models.BooleanField(default=False)
    max_active_exams = models.PositiveSmallIntegerField(null=True, blank=True)
    resume_file = models.FileField(upload_to='teachers/resumes/', blank=True)
    signature_file = models.FileField(upload_to='teachers/signatures/', blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'پروفایل استاد یا طراح آزمون'
        verbose_name_plural = 'پروفایل‌های استادان و طراحان آزمون'

    def __str__(self):
        return self.profile.full_name


class StudentProfile(models.Model):
    class EnrollmentStatus(models.TextChoices):
        ACTIVE = 'active', 'فعال'
        GRADUATED = 'graduated', 'فارغ‌التحصیل'
        SUSPENDED = 'suspended', 'تعلیق'
        WITHDRAWN = 'withdrawn', 'انصراف'

    profile = models.OneToOneField(UserProfile, on_delete=models.CASCADE, related_name='student_profile')
    institution = models.ForeignKey(AcademicInstitution, on_delete=models.PROTECT, related_name='students')
    academic_unit = models.ForeignKey(AcademicUnit, on_delete=models.SET_NULL, null=True, blank=True, related_name='students')
    student_number = models.CharField(max_length=50, blank=True)
    applicant_code = models.CharField(max_length=50, blank=True)
    field_of_study = models.CharField(max_length=160, blank=True)
    education_level = models.CharField(max_length=80, blank=True)
    entrance_year = models.PositiveSmallIntegerField(null=True, blank=True)
    semester = models.CharField(max_length=40, blank=True)
    class_group = models.CharField(max_length=120, blank=True)
    courses = models.ManyToManyField(Course, blank=True, related_name='students')
    enrollment_status = models.CharField(max_length=30, choices=EnrollmentStatus.choices, default=EnrollmentStatus.ACTIVE)
    guardian_mobile = models.CharField(max_length=20, blank=True)
    allowed_devices = models.JSONField(default=list, blank=True)
    accessibility_notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'پروفایل دانشجو یا داوطلب'
        verbose_name_plural = 'پروفایل‌های دانشجویان و داوطلبان'

    def __str__(self):
        return self.profile.full_name


class ExamProctorProfile(models.Model):
    class ProctorType(models.TextChoices):
        ONLINE = 'online', 'آنلاین'
        ONSITE = 'onsite', 'حضوری'
        HYBRID = 'hybrid', 'ترکیبی'

    profile = models.OneToOneField(UserProfile, on_delete=models.CASCADE, related_name='exam_proctor_profile')
    institution = models.ForeignKey(AcademicInstitution, on_delete=models.PROTECT, related_name='proctors')
    proctor_code = models.CharField(max_length=40, blank=True)
    proctor_type = models.CharField(max_length=20, choices=ProctorType.choices, default=ProctorType.ONLINE)
    supervision_scope = models.TextField(blank=True)
    max_concurrent_sessions = models.PositiveSmallIntegerField(default=1)
    can_verify_identity = models.BooleanField(default=True)
    can_pause_exam = models.BooleanField(default=False)
    can_report_violation = models.BooleanField(default=True)
    shift_days = models.JSONField(default=list, blank=True)
    shift_started_at = models.TimeField(null=True, blank=True)
    shift_ended_at = models.TimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'پروفایل ناظر آزمون'
        verbose_name_plural = 'پروفایل‌های ناظران آزمون'

    def __str__(self):
        return self.profile.full_name


class TechnicalSupportProfile(models.Model):
    class SupportLevel(models.TextChoices):
        LEVEL_1 = 'level_1', 'سطح یک'
        LEVEL_2 = 'level_2', 'سطح دو'
        LEVEL_3 = 'level_3', 'سطح سه'

    profile = models.OneToOneField(UserProfile, on_delete=models.CASCADE, related_name='technical_support_profile')
    institution = models.ForeignKey(AcademicInstitution, on_delete=models.SET_NULL, null=True, blank=True, related_name='technical_supports')
    support_code = models.CharField(max_length=40, blank=True)
    support_level = models.CharField(max_length=20, choices=SupportLevel.choices, default=SupportLevel.LEVEL_1)
    expertise_area = models.CharField(max_length=160, blank=True)
    can_access_logs = models.BooleanField(default=True)
    can_reset_sessions = models.BooleanField(default=False)
    can_manage_devices = models.BooleanField(default=False)
    can_resolve_tickets = models.BooleanField(default=True)
    availability_schedule = models.JSONField(default=dict, blank=True)
    emergency_phone = models.CharField(max_length=20, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'پروفایل پشتیبان فنی'
        verbose_name_plural = 'پروفایل‌های پشتیبانان فنی'

    def __str__(self):
        return self.profile.full_name


class UserActivityLog(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='activity_logs')
    action = models.CharField(max_length=160)
    description = models.TextField(blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'تاریخچه فعالیت'
        verbose_name_plural = 'تاریخچه فعالیت‌ها'

    def __str__(self):
        return f'{self.user} - {self.action}'


class UserLoginRecord(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='login_history')
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    device_name = models.CharField(max_length=160, blank=True)
    was_successful = models.BooleanField(default=True)
    logged_in_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-logged_in_at']
        verbose_name = 'سابقه ورود'
        verbose_name_plural = 'سوابق ورود'

    def __str__(self):
        return f'{self.user} - {self.ip_address or "بدون IP"}'


class ExamViolationReport(models.Model):
    class Decision(models.TextChoices):
        PENDING = 'pending', 'در انتظار بررسی'
        REJECTED = 'rejected', 'رد گزارش'
        WARNING = 'warning', 'اخطار'
        SCORE_DEDUCTION = 'score_deduction', 'کسر نمره'
        INVALIDATE_EXAM = 'invalidate_exam', 'ابطال آزمون'
        REFER_COMMITTEE = 'refer_committee', 'ارجاع به کمیته انضباطی'

    exam = models.ForeignKey('Exam', on_delete=models.CASCADE, related_name='violation_reports')
    student = models.ForeignKey(StudentProfile, on_delete=models.SET_NULL, null=True, blank=True, related_name='violation_reports')
    proctor = models.ForeignKey(ExamProctorProfile, on_delete=models.SET_NULL, null=True, blank=True, related_name='violation_reports')
    teacher = models.ForeignKey(TeacherProfile, on_delete=models.SET_NULL, null=True, blank=True, related_name='violation_reports')
    title = models.CharField(max_length=180)
    description = models.TextField()
    occurred_at = models.DateTimeField(null=True, blank=True)
    evidence_file = models.FileField(upload_to='violations/evidence/', blank=True)
    proctor_note = models.TextField(blank=True)
    teacher_note = models.TextField(blank=True)
    decision = models.CharField(max_length=30, choices=Decision.choices, default=Decision.PENDING)
    decision_note = models.TextField(blank=True)
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='decided_violations')
    decided_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'گزارش تخلف آزمون'
        verbose_name_plural = 'گزارش‌های تخلف آزمون'

    def __str__(self):
        return f'{self.title} - {self.exam}'


class DescriptiveAnswerReview(models.Model):
    exam = models.ForeignKey('Exam', on_delete=models.CASCADE, related_name='descriptive_reviews')
    question = models.ForeignKey(Question, on_delete=models.PROTECT, related_name='descriptive_reviews')
    student = models.ForeignKey(StudentProfile, on_delete=models.CASCADE, related_name='descriptive_reviews')
    answer_text = models.TextField()
    score = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    feedback = models.TextField(blank=True)
    is_suspicious = models.BooleanField(default=False)
    finalized = models.BooleanField(default=False)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='descriptive_reviews')
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['finalized', '-created_at']
        verbose_name = 'تصحیح پاسخ تشریحی'
        verbose_name_plural = 'تصحیح پاسخ‌های تشریحی'

    def __str__(self):
        return f'{self.exam} - {self.student}'


class ExamResultPublication(models.Model):
    exam = models.OneToOneField('Exam', on_delete=models.CASCADE, related_name='result_publication')
    published_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='published_exam_results')
    show_score = models.BooleanField(default=True)
    show_correct_answers = models.BooleanField(default=False)
    show_rank = models.BooleanField(default=False)
    average_score = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    highest_score = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    lowest_score = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    is_published = models.BooleanField(default=False)
    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'انتشار نتیجه آزمون'
        verbose_name_plural = 'انتشار نتایج آزمون'

    def __str__(self):
        return f'{self.exam} - {"منتشر شده" if self.is_published else "پیش‌نویس"}'


class StudentObjection(models.Model):
    class Decision(models.TextChoices):
        PENDING = 'pending', 'در انتظار بررسی'
        ACCEPTED = 'accepted', 'تأیید اعتراض'
        REJECTED = 'rejected', 'رد اعتراض'

    class ObjectionType(models.TextChoices):
        SCORE = 'score', 'اعتراض به نمره'
        QUESTION = 'question', 'اعتراض به سؤال'
        ANSWER_KEY = 'answer_key', 'اعتراض به کلید پاسخ'
        TECHNICAL = 'technical', 'مشکل فنی'

    exam = models.ForeignKey('Exam', on_delete=models.CASCADE, related_name='student_objections')
    question = models.ForeignKey(Question, on_delete=models.SET_NULL, null=True, blank=True, related_name='student_objections')
    student = models.ForeignKey(StudentProfile, on_delete=models.CASCADE, related_name='objection_records')
    objection_type = models.CharField(max_length=20, choices=ObjectionType.choices, default=ObjectionType.SCORE)
    objection_text = models.TextField()
    evidence_file = models.FileField(upload_to='objections/evidence/', blank=True)
    original_score = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    revised_score = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    decision = models.CharField(max_length=20, choices=Decision.choices, default=Decision.PENDING)
    decision_reason = models.TextField(blank=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='reviewed_objections')
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'اعتراض دانشجو'
        verbose_name_plural = 'اعتراض‌های دانشجویان'

    def __str__(self):
        return f'{self.student} - {self.exam}'


class ExamApproval(models.Model):
    class Decision(models.TextChoices):
        PENDING = 'pending', 'در انتظار بررسی'
        APPROVED = 'approved', 'تأیید شده'
        RETURNED = 'returned', 'بازگشت برای اصلاح'

    exam = models.OneToOneField('Exam', on_delete=models.CASCADE, related_name='approval')
    requested_by = models.ForeignKey(TeacherProfile, on_delete=models.SET_NULL, null=True, blank=True, related_name='exam_approval_requests')
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='reviewed_exam_approvals')
    decision = models.CharField(max_length=20, choices=Decision.choices, default=Decision.PENDING)
    question_count = models.PositiveIntegerField(null=True, blank=True)
    participants_count = models.PositiveIntegerField(null=True, blank=True)
    note = models.TextField(blank=True)
    requested_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-requested_at']
        verbose_name = 'تأیید آزمون'
        verbose_name_plural = 'تأیید آزمون‌ها'

    def __str__(self):
        return f'{self.exam} - {self.get_decision_display()}'


class ExamProctorAssignment(models.Model):
    class Status(models.TextChoices):
        ASSIGNED = 'assigned', 'تخصیص داده‌شده'
        ACCEPTED = 'accepted', 'پذیرفته‌شده'
        REJECTED = 'rejected', 'ردشده'

    exam = models.ForeignKey('Exam', on_delete=models.CASCADE, related_name='proctor_assignments')
    proctor = models.ForeignKey(ExamProctorProfile, on_delete=models.CASCADE, related_name='assignments')
    assigned_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='assigned_exam_proctors')
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ASSIGNED)
    note = models.TextField(blank=True)
    assigned_at = models.DateTimeField(auto_now_add=True)
    responded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-assigned_at']
        unique_together = ('exam', 'proctor')
        verbose_name = 'تخصیص ناظر آزمون'
        verbose_name_plural = 'تخصیص ناظران آزمون'

    def __str__(self):
        return f'{self.exam} - {self.proctor}'


class ExamRescheduleRequest(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'در انتظار بررسی'
        APPROVED = 'approved', 'تأیید شده'
        REJECTED = 'rejected', 'ردشده'

    exam = models.ForeignKey('Exam', on_delete=models.CASCADE, related_name='reschedule_requests')
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='exam_reschedule_requests')
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='reviewed_exam_reschedules')
    old_starts_at = models.DateTimeField()
    old_ends_at = models.DateTimeField()
    new_starts_at = models.DateTimeField()
    new_ends_at = models.DateTimeField()
    reason = models.TextField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    review_note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'درخواست تغییر زمان آزمون'
        verbose_name_plural = 'درخواست‌های تغییر زمان آزمون'

    def __str__(self):
        return f'{self.exam} - {self.get_status_display()}'


class ExamStartAuthorization(models.Model):
    exam = models.OneToOneField('Exam', on_delete=models.CASCADE, related_name='start_authorization')
    authorized_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='authorized_exam_starts')
    students_entered = models.PositiveIntegerField(default=0)
    absent_students = models.PositiveIntegerField(default=0)
    proctor_ready = models.BooleanField(default=False)
    teacher_ready = models.BooleanField(default=False)
    authorized = models.BooleanField(default=False)
    note = models.TextField(blank=True)
    authorized_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'مجوز شروع آزمون'
        verbose_name_plural = 'مجوزهای شروع آزمون'

    def __str__(self):
        return f'{self.exam} - {"مجاز" if self.authorized else "در انتظار"}'


class ExamExecutionReport(models.Model):
    exam = models.OneToOneField('Exam', on_delete=models.CASCADE, related_name='execution_report')
    prepared_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='prepared_exam_reports')
    participants_count = models.PositiveIntegerField(default=0)
    absent_count = models.PositiveIntegerField(default=0)
    incomplete_count = models.PositiveIntegerField(default=0)
    internet_disconnects = models.PositiveIntegerField(default=0)
    violations_count = models.PositiveIntegerField(default=0)
    final_note = models.TextField(blank=True)
    sent_to_institution_manager = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'گزارش برگزاری آزمون'
        verbose_name_plural = 'گزارش‌های برگزاری آزمون'

    def __str__(self):
        return f'گزارش {self.exam}'


class Exam(models.Model):
    class ExamStatus(models.TextChoices):
        DRAFT = 'draft', 'پیش‌نویس'
        PENDING_APPROVAL = 'pending_approval', 'در انتظار تأیید'
        SCHEDULED = 'scheduled', 'زمان‌بندی‌شده'
        ACTIVE = 'active', 'در حال برگزاری'
        PAUSED = 'paused', 'متوقف اضطراری'
        FINISHED = 'finished', 'پایان‌یافته'
        CANCELLED = 'cancelled', 'لغوشده'

    institution = models.ForeignKey(AcademicInstitution, on_delete=models.SET_NULL, null=True, blank=True, related_name='exams')
    course = models.ForeignKey(Course, on_delete=models.SET_NULL, null=True, blank=True, related_name='exams')
    designer = models.ForeignKey(TeacherProfile, on_delete=models.SET_NULL, null=True, blank=True, related_name='designed_exams')
    proctors = models.ManyToManyField(ExamProctorProfile, blank=True, related_name='supervised_exams')
    technical_supports = models.ManyToManyField(TechnicalSupportProfile, blank=True, related_name='supported_exams')
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    duration_minutes = models.PositiveIntegerField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=ExamStatus.choices, default=ExamStatus.DRAFT)
    total_score = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    passing_score = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    negative_marking_enabled = models.BooleanField(default=False)
    randomize_questions = models.BooleanField(default=False)
    randomize_options = models.BooleanField(default=False)
    allow_backtracking = models.BooleanField(default=True)
    show_result_after_submit = models.BooleanField(default=False)
    allow_file_upload = models.BooleanField(default=False)
    require_identity_verification = models.BooleanField(default=True)
    instructions = models.TextField(blank=True)
    emergency_stopped_at = models.DateTimeField(null=True, blank=True)
    emergency_stop_reason = models.TextField(blank=True)
    emergency_stopped_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='emergency_stopped_exams',
    )
    emergency_resolved_at = models.DateTimeField(null=True, blank=True)
    emergency_resolution_note = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-starts_at']

    def __str__(self):
        return self.title


class StudentExamAttempt(models.Model):
    class Status(models.TextChoices):
        NOT_STARTED = 'not_started', 'شروع نشده'
        WAITING_PROCTOR = 'waiting_proctor', 'در انتظار تصمیم ناظر'
        IN_PROGRESS = 'in_progress', 'در حال آزمون'
        SUBMITTED = 'submitted', 'ارسال شده'
        AUTO_SUBMITTED = 'auto_submitted', 'ارسال خودکار'
        BLOCKED = 'blocked', 'مسدود'

    exam = models.ForeignKey(Exam, on_delete=models.CASCADE, related_name='student_attempts')
    student = models.ForeignKey(StudentProfile, on_delete=models.CASCADE, related_name='exam_attempts')
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.NOT_STARTED)
    identity_confirmed = models.BooleanField(default=False)
    rules_accepted = models.BooleanField(default=False)
    identity_code = models.CharField(max_length=60, blank=True)
    identity_image = models.FileField(upload_to='attempts/identity/', blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    last_activity_at = models.DateTimeField(null=True, blank=True)
    receipt_code = models.CharField(max_length=40, blank=True)
    proctor_note = models.TextField(blank=True)
    can_continue_after_disconnect = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        unique_together = ('exam', 'student')
        verbose_name = 'شرکت دانشجو در آزمون'
        verbose_name_plural = 'شرکت دانشجویان در آزمون'

    def __str__(self):
        return f'{self.student} - {self.exam}'

    @property
    def is_locked(self):
        return self.status in {self.Status.SUBMITTED, self.Status.AUTO_SUBMITTED, self.Status.BLOCKED}


class StudentQuestionAnswer(models.Model):
    attempt = models.ForeignKey(StudentExamAttempt, on_delete=models.CASCADE, related_name='answers')
    exam_question = models.ForeignKey(ExamQuestion, on_delete=models.CASCADE, related_name='student_answers')
    answer_text = models.TextField(blank=True)
    selected_options = models.JSONField(default=list, blank=True)
    uploaded_file = models.FileField(upload_to='attempts/answers/', blank=True)
    marked_for_review = models.BooleanField(default=False)
    autosaved_at = models.DateTimeField(null=True, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['exam_question__order', 'id']
        unique_together = ('attempt', 'exam_question')
        verbose_name = 'پاسخ دانشجو'
        verbose_name_plural = 'پاسخ‌های دانشجویان'

    def __str__(self):
        return f'{self.attempt} - {self.exam_question}'

    @property
    def has_answer(self):
        return bool(self.answer_text or self.selected_options or self.uploaded_file)


class StudentExamEvent(models.Model):
    class EventType(models.TextChoices):
        ENTERED_EARLY = 'entered_early', 'مراجعه زودتر از زمان'
        ENTRY_EXPIRED = 'entry_expired', 'مراجعه پس از پایان زمان'
        IDENTITY_FAILED = 'identity_failed', 'احراز هویت ناموفق'
        STARTED = 'started', 'شروع آزمون'
        ANSWER_SAVED = 'answer_saved', 'ذخیره پاسخ'
        DISCONNECTED = 'disconnected', 'قطع اتصال'
        RECONNECTED = 'reconnected', 'اتصال مجدد'
        FILE_REJECTED = 'file_rejected', 'رد فایل پاسخ'
        SUBMITTED = 'submitted', 'ارسال نهایی'
        AUTO_SUBMITTED = 'auto_submitted', 'ارسال خودکار'

    attempt = models.ForeignKey(StudentExamAttempt, on_delete=models.CASCADE, related_name='events')
    event_type = models.CharField(max_length=30, choices=EventType.choices)
    message = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'رویداد آزمون دانشجو'
        verbose_name_plural = 'رویدادهای آزمون دانشجو'

    def __str__(self):
        return f'{self.attempt} - {self.get_event_type_display()}'


class StudentPracticeCheck(models.Model):
    student = models.ForeignKey(StudentProfile, on_delete=models.CASCADE, related_name='practice_checks')
    browser_ok = models.BooleanField(default=False)
    internet_ok = models.BooleanField(default=False)
    camera_ok = models.BooleanField(default=False)
    microphone_ok = models.BooleanField(default=False)
    sample_score = models.PositiveSmallIntegerField(default=0)
    issues = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'بررسی آزمون آزمایشی'
        verbose_name_plural = 'بررسی‌های آزمون آزمایشی'

    def __str__(self):
        return f'{self.student} - {self.created_at}'


class AssistantQuestionSubmission(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'در انتظار تأیید استاد'
        APPROVED = 'approved', 'تأیید شده'
        REJECTED = 'rejected', 'رد شده'
        NEEDS_REVISION = 'needs_revision', 'نیازمند اصلاح'

    assistant = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='assistant_question_submissions')
    teacher = models.ForeignKey(TeacherProfile, on_delete=models.CASCADE, related_name='assistant_question_submissions')
    question = models.OneToOneField(Question, on_delete=models.CASCADE, related_name='assistant_submission')
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.PENDING)
    teacher_note = models.TextField(blank=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='reviewed_assistant_questions')
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'ارسال سؤال توسط دستیار'
        verbose_name_plural = 'ارسال سؤال‌های دستیاران'

    def __str__(self):
        return f'{self.question} - {self.get_status_display()}'


class AssistantQuestionSuggestion(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'در انتظار بررسی'
        APPROVED = 'approved', 'تأیید شده'
        REJECTED = 'rejected', 'رد شده'

    assistant = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='assistant_question_suggestions')
    teacher = models.ForeignKey(TeacherProfile, on_delete=models.CASCADE, related_name='assistant_question_suggestions')
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name='assistant_suggestions')
    suggested_text = models.TextField(blank=True)
    suggested_correct_answer = models.TextField(blank=True)
    suggested_topic = models.CharField(max_length=160, blank=True)
    note = models.TextField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    teacher_note = models.TextField(blank=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='reviewed_question_suggestions')
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'پیشنهاد اصلاح سؤال'
        verbose_name_plural = 'پیشنهادهای اصلاح سؤال'

    def __str__(self):
        return f'{self.question} - {self.get_status_display()}'


class AssistantExamDraft(models.Model):
    class Status(models.TextChoices):
        DRAFT = 'draft', 'پیش‌نویس'
        SUBMITTED = 'submitted', 'ارسال شده برای استاد'
        APPROVED = 'approved', 'تأیید و منتشر شده'
        REJECTED = 'rejected', 'رد شده'

    assistant = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='assistant_exam_drafts')
    teacher = models.ForeignKey(TeacherProfile, on_delete=models.CASCADE, related_name='assistant_exam_drafts')
    exam = models.OneToOneField(Exam, on_delete=models.CASCADE, related_name='assistant_draft')
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.SUBMITTED)
    teacher_note = models.TextField(blank=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='reviewed_assistant_exam_drafts')
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'پیش‌نویس آزمون دستیار'
        verbose_name_plural = 'پیش‌نویس‌های آزمون دستیاران'

    def __str__(self):
        return f'{self.exam} - {self.get_status_display()}'


class AssistantReviewAssignment(models.Model):
    class Status(models.TextChoices):
        ASSIGNED = 'assigned', 'تخصیص داده شده'
        SUBMITTED = 'submitted', 'ارسال شده برای تأیید استاد'
        APPROVED = 'approved', 'تأیید شده'
        RETURNED = 'returned', 'برگشت برای اصلاح'

    assistant = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='assistant_review_assignments')
    teacher = models.ForeignKey(TeacherProfile, on_delete=models.CASCADE, related_name='assistant_review_assignments')
    review = models.OneToOneField(DescriptiveAnswerReview, on_delete=models.CASCADE, related_name='assistant_assignment')
    proposed_score = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    feedback = models.TextField(blank=True)
    is_suspicious = models.BooleanField(default=False)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ASSIGNED)
    teacher_note = models.TextField(blank=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='approved_assistant_reviews')
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    submitted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['status', '-created_at']
        verbose_name = 'تخصیص تصحیح به دستیار'
        verbose_name_plural = 'تخصیص‌های تصحیح دستیاران'

    def __str__(self):
        return f'{self.review.exam} - {self.get_status_display()}'


class EducationalQuestion(models.Model):
    class Status(models.TextChoices):
        NEW = 'new', 'جدید'
        ANSWERED = 'answered', 'پاسخ داده شده'
        REFERRED = 'referred', 'ارجاع شده به استاد'

    student = models.ForeignKey(StudentProfile, on_delete=models.CASCADE, related_name='educational_questions')
    exam = models.ForeignKey(Exam, on_delete=models.SET_NULL, null=True, blank=True, related_name='educational_questions')
    course = models.ForeignKey(Course, on_delete=models.SET_NULL, null=True, blank=True, related_name='educational_questions')
    teacher = models.ForeignKey(TeacherProfile, on_delete=models.CASCADE, related_name='educational_questions')
    assistant = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='answered_educational_questions')
    question_text = models.TextField()
    answer_text = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.NEW)
    needs_teacher_decision = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    answered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['status', '-created_at']
        verbose_name = 'پرسش آموزشی'
        verbose_name_plural = 'پرسش‌های آموزشی'

    def __str__(self):
        return f'{self.student} - {self.get_status_display()}'
