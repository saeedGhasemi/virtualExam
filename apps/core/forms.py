from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm
from django.core.cache import cache
from django.contrib.auth import get_user_model

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
    ExamProctorProfile,
    ExamRescheduleRequest,
    ExamStartAuthorization,
    ExamQuestion,
    ExamResultPublication,
    ExamViolationReport,
    InstitutionAdminProfile,
    StudentProfile,
    Question,
    StudentObjection,
    StudentExamAttempt,
    StudentPracticeCheck,
    StudentQuestionAnswer,
    SystemRole,
    TeacherProfile,
    UserProfile,
)


class StyledAuthenticationForm(AuthenticationForm):
    lock_minutes = 15
    max_attempts = 5

    def __init__(self, request=None, *args, **kwargs):
        super().__init__(request, *args, **kwargs)
        self.fields['username'].widget.attrs.update({
            'placeholder': 'ایمیل یا نام کاربری',
            'autocomplete': 'username',
        })
        self.fields['password'].widget.attrs.update({
            'placeholder': 'رمز عبور',
            'autocomplete': 'current-password',
        })

    def clean(self):
        username = self.cleaned_data.get('username', '').strip().lower()
        if username and cache.get(self.lock_key(username)):
            raise forms.ValidationError(
                f'حساب به دلیل تلاش‌های ناموفق زیاد، به مدت {self.lock_minutes} دقیقه قفل شده است.'
            )
        return super().clean()

    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        profile = getattr(user, 'profile', None)
        if profile and profile.account_status == UserProfile.AccountStatus.BLOCKED:
            raise forms.ValidationError('حساب شما مسدود است و امکان ورود وجود ندارد.')
        if profile and profile.account_status == UserProfile.AccountStatus.INACTIVE:
            raise forms.ValidationError('حساب شما غیرفعال است. با مدیر سامانه تماس بگیرید.')

    @classmethod
    def attempts_key(cls, username):
        return f'login-attempts:{username}'

    @classmethod
    def lock_key(cls, username):
        return f'login-lock:{username}'

    @classmethod
    def record_failed_attempt(cls, username):
        username = (username or '').strip().lower()
        if not username:
            return 0
        attempts = cache.get(cls.attempts_key(username), 0) + 1
        cache.set(cls.attempts_key(username), attempts, cls.lock_minutes * 60)
        if attempts >= cls.max_attempts:
            cache.set(cls.lock_key(username), True, cls.lock_minutes * 60)
        return attempts

    @classmethod
    def clear_failed_attempts(cls, username):
        username = (username or '').strip().lower()
        cache.delete(cls.attempts_key(username))
        cache.delete(cls.lock_key(username))


class TwoFactorCodeForm(forms.Form):
    code = forms.CharField(label='کد تأیید', max_length=6, min_length=6)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['code'].widget.attrs.update({
            'placeholder': 'کد ۶ رقمی',
            'autocomplete': 'one-time-code',
        })


class SuperAdminInstitutionForm(forms.ModelForm):
    manager_profile = forms.ModelChoiceField(
        label='مدیر مرکز آموزشی',
        queryset=UserProfile.objects.none(),
        required=True,
    )

    class Meta:
        model = AcademicInstitution
        fields = (
            'name',
            'registration_code',
            'institution_type',
            'phone',
            'email',
            'address',
            'logo',
            'max_users',
            'max_exams',
        )
        labels = {
            'name': 'نام مؤسسه',
            'registration_code': 'کد مؤسسه',
            'institution_type': 'نوع مؤسسه',
            'phone': 'شماره تماس',
            'email': 'ایمیل',
            'address': 'آدرس',
            'logo': 'لوگو',
            'max_users': 'محدودیت تعداد کاربران',
            'max_exams': 'محدودیت تعداد آزمون‌ها',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['manager_profile'].queryset = UserProfile.objects.filter(
            role__code=SystemRole.RoleCode.INSTITUTION_ADMIN
        ).select_related('user', 'role')
        for name in ('registration_code', 'phone', 'email', 'address', 'manager_profile'):
            self.fields[name].required = True
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', 'super-admin-input')

    def clean_registration_code(self):
        code = self.cleaned_data['registration_code'].strip()
        if AcademicInstitution.objects.filter(registration_code=code).exists():
            raise forms.ValidationError('کد مؤسسه تکراری است.')
        return code


class SuperAdminUserActionForm(forms.Form):
    ACTION_ACTIVE = 'activate'
    ACTION_INACTIVE = 'deactivate'
    ACTION_BLOCK = 'block'
    ACTION_ROLE = 'change_role'
    ACTION_RESET = 'reset_password'
    ACTION_TRANSFER = 'transfer'

    action = forms.ChoiceField(label='عملیات', choices=(
        (ACTION_ACTIVE, 'فعال‌سازی حساب'),
        (ACTION_INACTIVE, 'غیرفعال‌سازی حساب'),
        (ACTION_BLOCK, 'مسدودکردن حساب'),
        (ACTION_ROLE, 'تغییر نقش'),
        (ACTION_RESET, 'بازنشانی رمز عبور'),
        (ACTION_TRANSFER, 'انتقال کاربر به مؤسسه دیگر'),
    ))
    role = forms.ModelChoiceField(label='نقش جدید', queryset=SystemRole.objects.all(), required=False)
    institution_name = forms.CharField(label='مؤسسه جدید', max_length=180, required=False)
    temporary_password = forms.CharField(label='رمز عبور جدید', max_length=128, required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', 'super-admin-input')

    def clean(self):
        cleaned = super().clean()
        action = cleaned.get('action')
        if action == self.ACTION_ROLE and not cleaned.get('role'):
            self.add_error('role', 'برای تغییر نقش، نقش جدید را انتخاب کنید.')
        if action == self.ACTION_TRANSFER and not cleaned.get('institution_name'):
            self.add_error('institution_name', 'نام مؤسسه مقصد را وارد کنید.')
        return cleaned


class SuperAdminRoleForm(forms.ModelForm):
    permissions_text = forms.CharField(
        label='مجوزها',
        widget=forms.Textarea,
        required=False,
        help_text='هر مجوز را در یک خط وارد کنید.',
    )

    class Meta:
        model = SystemRole
        fields = ('name', 'code', 'description', 'access_level', 'is_active')
        labels = {
            'name': 'نام نقش',
            'code': 'کد نقش',
            'description': 'توضیح',
            'access_level': 'سطح دسترسی',
            'is_active': 'فعال',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.fields['permissions_text'].initial = '\n'.join(self.instance.permissions or [])
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', 'super-admin-input')

    def save(self, commit=True):
        instance = super().save(commit=False)
        permissions_text = self.cleaned_data.get('permissions_text', '')
        instance.permissions = [line.strip() for line in permissions_text.splitlines() if line.strip()]
        if commit:
            instance.save()
        return instance


class SuperAdminReportFilterForm(forms.Form):
    date_from = forms.DateField(label='از تاریخ', required=False, widget=forms.DateInput(attrs={'type': 'date'}))
    date_to = forms.DateField(label='تا تاریخ', required=False, widget=forms.DateInput(attrs={'type': 'date'}))
    institution = forms.ModelChoiceField(label='مؤسسه', queryset=AcademicInstitution.objects.all(), required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', 'super-admin-input')


class EmergencyStopExamForm(forms.Form):
    reason = forms.CharField(label='دلیل توقف اضطراری', widget=forms.Textarea, min_length=10)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['reason'].widget.attrs.setdefault('class', 'super-admin-input')


class InstitutionSettingsForm(forms.ModelForm):
    class Meta:
        model = AcademicInstitution
        fields = ('name', 'phone', 'email', 'website', 'province', 'city', 'address', 'logo')
        labels = {
            'name': 'نام مرکز',
            'phone': 'شماره تماس',
            'email': 'ایمیل',
            'website': 'وب‌سایت',
            'province': 'استان',
            'city': 'شهر',
            'address': 'آدرس',
            'logo': 'لوگو',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', 'super-admin-input')


class InstitutionUserCreateForm(forms.Form):
    USER_TYPES = (
        ('exam_manager', 'مسئول امتحانات'),
        ('teacher', 'استاد'),
        ('teaching_assistant', 'دستیار'),
        ('student', 'دانشجو'),
    )
    user_type = forms.ChoiceField(label='نوع کاربر', choices=USER_TYPES)
    username = forms.CharField(label='نام کاربری', max_length=150)
    password = forms.CharField(label='رمز عبور اولیه', max_length=128, required=False)
    full_name = forms.CharField(label='نام کامل', max_length=180)
    national_code = forms.CharField(label='کد ملی', max_length=20, required=False)
    email = forms.EmailField(label='ایمیل', required=False)
    mobile = forms.CharField(label='موبایل', max_length=20, required=False)
    student_number = forms.CharField(label='شماره دانشجویی', max_length=50, required=False)
    academic_unit = forms.ModelChoiceField(label='واحد آموزشی', queryset=AcademicUnit.objects.none(), required=False)

    def __init__(self, *args, institution=None, **kwargs):
        self.institution = institution
        super().__init__(*args, **kwargs)
        if institution:
            self.fields['academic_unit'].queryset = institution.units.all()
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', 'super-admin-input')

    def clean_username(self):
        username = self.cleaned_data['username']
        if get_user_model().objects.filter(username=username).exists():
            raise forms.ValidationError('نام کاربری تکراری است.')
        return username

    def clean_national_code(self):
        code = self.cleaned_data.get('national_code', '').strip()
        if code and UserProfile.objects.filter(national_code=code).exists():
            raise forms.ValidationError('کد ملی تکراری است.')
        return code

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('user_type') == 'student':
            student_number = cleaned.get('student_number', '').strip()
            if not student_number:
                self.add_error('student_number', 'شماره دانشجویی برای دانشجو الزامی است.')
            elif StudentProfile.objects.filter(student_number=student_number).exists() or UserProfile.objects.filter(student_number=student_number).exists():
                self.add_error('student_number', 'شماره دانشجویی تکراری است.')
        return cleaned


class InstitutionUserImportForm(forms.Form):
    excel_file = forms.FileField(label='فایل Excel/CSV')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['excel_file'].widget.attrs.setdefault('class', 'super-admin-input')


class AcademicStructureForm(forms.Form):
    unit_name = forms.CharField(label='نام دانشکده یا واحد آموزشی', max_length=160)
    unit_code = forms.CharField(label='کد واحد', max_length=40, required=False)
    field_name = forms.CharField(label='رشته یا مقطع تحصیلی', max_length=160, required=False)
    term_title = forms.CharField(label='نیم‌سال تحصیلی', max_length=120)
    term_year = forms.IntegerField(label='سال تحصیلی', required=False)
    course_title = forms.CharField(label='نام درس', max_length=180)
    course_code = forms.CharField(label='کد درس', max_length=50, required=False)
    class_title = forms.CharField(label='نام کلاس', max_length=160)
    class_code = forms.CharField(label='کد کلاس', max_length=50, required=False)
    teacher = forms.ModelChoiceField(label='استاد کلاس', queryset=TeacherProfile.objects.none(), required=False)
    students = forms.ModelMultipleChoiceField(label='دانشجویان کلاس', queryset=StudentProfile.objects.none(), required=False)

    def __init__(self, *args, institution=None, **kwargs):
        self.institution = institution
        super().__init__(*args, **kwargs)
        if institution:
            self.fields['teacher'].queryset = institution.teachers.all()
            self.fields['students'].queryset = institution.students.all()
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', 'super-admin-input')


class ExamManagerAssignmentForm(forms.Form):
    profile = forms.ModelChoiceField(label='کاربر', queryset=UserProfile.objects.none())
    access_scope = forms.CharField(label='محدوده دسترسی', widget=forms.Textarea, required=False)
    starts_at = forms.DateField(label='تاریخ شروع مسئولیت', widget=forms.DateInput(attrs={'type': 'date'}), required=False)
    ends_at = forms.DateField(label='تاریخ پایان مسئولیت', widget=forms.DateInput(attrs={'type': 'date'}), required=False)

    def __init__(self, *args, institution=None, **kwargs):
        super().__init__(*args, **kwargs)
        qs = UserProfile.objects.select_related('user', 'role')
        if institution:
            qs = qs.filter(institution_name=institution.name)
        self.fields['profile'].queryset = qs
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', 'super-admin-input')


class ViolationDecisionForm(forms.ModelForm):
    class Meta:
        model = ExamViolationReport
        fields = ('decision', 'decision_note')
        labels = {
            'decision': 'تصمیم',
            'decision_note': 'توضیح تصمیم',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', 'super-admin-input')


class ExamCalendarScheduleForm(forms.Form):
    term = forms.ModelChoiceField(label='نیم‌سال تحصیلی', queryset=AcademicTerm.objects.none(), required=False)
    course_class = forms.ModelChoiceField(label='درس/کلاس دارای آزمون', queryset=CourseClass.objects.none(), required=False)
    exam = forms.ModelChoiceField(label='آزمون', queryset=Exam.objects.none(), required=False)
    title = forms.CharField(label='عنوان آزمون جدید', max_length=200, required=False)
    starts_at = forms.DateTimeField(label='تاریخ و ساعت شروع', widget=forms.DateTimeInput(attrs={'type': 'datetime-local'}))
    ends_at = forms.DateTimeField(label='تاریخ و ساعت پایان', widget=forms.DateTimeInput(attrs={'type': 'datetime-local'}))

    def __init__(self, *args, institution=None, **kwargs):
        self.institution = institution
        super().__init__(*args, **kwargs)
        if institution:
            self.fields['term'].queryset = institution.terms.all()
            self.fields['course_class'].queryset = institution.classes.select_related('course', 'teacher')
            self.fields['exam'].queryset = institution.exams.all()
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', 'super-admin-input')

    def clean(self):
        cleaned = super().clean()
        starts_at = cleaned.get('starts_at')
        ends_at = cleaned.get('ends_at')
        if starts_at and ends_at and starts_at >= ends_at:
            self.add_error('ends_at', 'زمان پایان باید بعد از شروع باشد.')
        if not cleaned.get('exam') and not cleaned.get('course_class'):
            self.add_error('course_class', 'برای ایجاد آزمون جدید، کلاس را انتخاب کنید.')
        if not cleaned.get('exam') and not cleaned.get('title'):
            self.add_error('title', 'برای ایجاد آزمون جدید، عنوان آزمون را وارد کنید.')
        return cleaned


class ExamApprovalReviewForm(forms.ModelForm):
    class Meta:
        model = ExamApproval
        fields = ('decision', 'question_count', 'participants_count', 'note')
        labels = {
            'decision': 'تصمیم',
            'question_count': 'تعداد سؤال',
            'participants_count': 'تعداد شرکت‌کنندگان',
            'note': 'یادداشت بررسی',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', 'super-admin-input')


class ProctorAssignmentForm(forms.Form):
    exam = forms.ModelChoiceField(label='آزمون', queryset=Exam.objects.none())
    proctors = forms.ModelMultipleChoiceField(label='ناظران در دسترس', queryset=ExamProctorProfile.objects.none())
    note = forms.CharField(label='توضیح برای ناظر', widget=forms.Textarea, required=False)

    def __init__(self, *args, institution=None, **kwargs):
        super().__init__(*args, **kwargs)
        if institution:
            self.fields['exam'].queryset = institution.exams.all()
            self.fields['proctors'].queryset = institution.proctors.all()
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', 'super-admin-input')


class ExamStartControlForm(forms.ModelForm):
    class Meta:
        model = ExamStartAuthorization
        fields = ('students_entered', 'absent_students', 'proctor_ready', 'teacher_ready', 'authorized', 'note')
        labels = {
            'students_entered': 'تعداد دانشجویان واردشده',
            'absent_students': 'تعداد غایبان',
            'proctor_ready': 'ناظر آماده است',
            'teacher_ready': 'استاد آماده است',
            'authorized': 'اجازه شروع صادر شود',
            'note': 'یادداشت',
        }

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('authorized') and (not cleaned.get('proctor_ready') or not cleaned.get('teacher_ready')):
            raise forms.ValidationError('برای صدور اجازه شروع، آماده‌بودن ناظر و استاد باید تأیید شود.')
        return cleaned

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', 'super-admin-input')


class ExamRescheduleForm(forms.ModelForm):
    class Meta:
        model = ExamRescheduleRequest
        fields = ('exam', 'new_starts_at', 'new_ends_at', 'reason', 'status', 'review_note')
        labels = {
            'exam': 'آزمون',
            'new_starts_at': 'زمان شروع جدید',
            'new_ends_at': 'زمان پایان جدید',
            'reason': 'دلیل درخواست',
            'status': 'تصمیم',
            'review_note': 'یادداشت بررسی',
        }
        widgets = {
            'new_starts_at': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
            'new_ends_at': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
        }

    def __init__(self, *args, institution=None, **kwargs):
        super().__init__(*args, **kwargs)
        if institution:
            self.fields['exam'].queryset = institution.exams.all()
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', 'super-admin-input')

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('new_starts_at') and cleaned.get('new_ends_at') and cleaned['new_starts_at'] >= cleaned['new_ends_at']:
            self.add_error('new_ends_at', 'زمان پایان جدید باید بعد از شروع باشد.')
        return cleaned


class ExamExecutionReportForm(forms.ModelForm):
    class Meta:
        model = ExamExecutionReport
        fields = (
            'exam',
            'participants_count',
            'absent_count',
            'incomplete_count',
            'internet_disconnects',
            'violations_count',
            'final_note',
            'sent_to_institution_manager',
        )
        labels = {
            'exam': 'آزمون پایان‌یافته',
            'participants_count': 'تعداد شرکت‌کنندگان',
            'absent_count': 'تعداد غایبان',
            'incomplete_count': 'آزمون‌های ناقص',
            'internet_disconnects': 'قطعی‌های اینترنت',
            'violations_count': 'تخلفات',
            'final_note': 'گزارش نهایی',
            'sent_to_institution_manager': 'ارسال برای مدیر مؤسسه',
        }

    def __init__(self, *args, institution=None, **kwargs):
        super().__init__(*args, **kwargs)
        if institution:
            self.fields['exam'].queryset = institution.exams.filter(status=Exam.ExamStatus.FINISHED)
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', 'super-admin-input')


class QuestionForm(forms.ModelForm):
    options_text = forms.CharField(label='گزینه‌ها', widget=forms.Textarea, required=False, help_text='هر گزینه را در یک خط وارد کنید.')

    class Meta:
        model = Question
        fields = ('course', 'question_type', 'text', 'correct_answer', 'difficulty', 'chapter', 'topic', 'suggested_score')
        labels = {
            'course': 'درس',
            'question_type': 'نوع سؤال',
            'text': 'متن سؤال',
            'correct_answer': 'پاسخ صحیح',
            'difficulty': 'سطح دشواری',
            'chapter': 'فصل',
            'topic': 'موضوع',
            'suggested_score': 'نمره پیشنهادی',
        }

    def __init__(self, *args, teacher=None, **kwargs):
        self.teacher = teacher
        super().__init__(*args, **kwargs)
        if teacher:
            self.fields['course'].queryset = teacher.courses.all() or Course.objects.filter(institution=teacher.institution)
        if self.instance and self.instance.pk:
            self.fields['options_text'].initial = '\n'.join(self.instance.options or [])
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', 'super-admin-input')

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.teacher:
            instance.teacher = self.teacher
        options_text = self.cleaned_data.get('options_text', '')
        instance.options = [line.strip() for line in options_text.splitlines() if line.strip()]
        if commit:
            instance.save()
        return instance


class TeacherExamForm(forms.ModelForm):
    course_class = forms.ModelChoiceField(label='کلاس', queryset=CourseClass.objects.none(), required=False)
    questions = forms.ModelMultipleChoiceField(label='انتخاب سؤال‌ها', queryset=Question.objects.none(), required=False)

    class Meta:
        model = Exam
        fields = (
            'title',
            'course',
            'starts_at',
            'ends_at',
            'duration_minutes',
            'instructions',
            'randomize_questions',
            'randomize_options',
            'negative_marking_enabled',
            'allow_backtracking',
            'show_result_after_submit',
        )
        labels = {
            'title': 'عنوان آزمون',
            'course': 'درس',
            'starts_at': 'تاریخ و ساعت شروع',
            'ends_at': 'تاریخ و ساعت پایان',
            'duration_minutes': 'مدت آزمون',
            'instructions': 'قوانین آزمون',
            'randomize_questions': 'تصادفی‌سازی سؤالات',
            'randomize_options': 'تصادفی‌سازی گزینه‌ها',
            'negative_marking_enabled': 'نمره منفی',
            'allow_backtracking': 'امکان بازگشت',
            'show_result_after_submit': 'نمایش نتیجه',
        }
        widgets = {
            'starts_at': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
            'ends_at': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
        }

    def __init__(self, *args, teacher=None, **kwargs):
        self.teacher = teacher
        super().__init__(*args, **kwargs)
        if teacher:
            self.fields['course'].queryset = teacher.courses.all() or Course.objects.filter(institution=teacher.institution)
            self.fields['course_class'].queryset = teacher.classes.all()
            self.fields['questions'].queryset = teacher.questions.filter(is_active=True)
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', 'super-admin-input')

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('starts_at') and cleaned.get('ends_at') and cleaned['starts_at'] >= cleaned['ends_at']:
            self.add_error('ends_at', 'زمان پایان باید بعد از شروع باشد.')
        return cleaned


class ExamQuestionScoreForm(forms.Form):
    def __init__(self, *args, questions=None, **kwargs):
        super().__init__(*args, **kwargs)
        for question in questions or []:
            self.fields[f'score_{question.pk}'] = forms.DecimalField(label=str(question)[:60], max_digits=6, decimal_places=2, initial=question.suggested_score)
            self.fields[f'score_{question.pk}'].widget.attrs.setdefault('class', 'super-admin-input')


class DescriptiveReviewForm(forms.ModelForm):
    class Meta:
        model = DescriptiveAnswerReview
        fields = ('score', 'feedback', 'is_suspicious', 'finalized')
        labels = {'score': 'نمره', 'feedback': 'توضیح', 'is_suspicious': 'پاسخ مشکوک', 'finalized': 'نهایی شود'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', 'super-admin-input')


class ResultPublicationForm(forms.ModelForm):
    class Meta:
        model = ExamResultPublication
        fields = ('show_score', 'show_correct_answers', 'show_rank', 'average_score', 'highest_score', 'lowest_score', 'is_published')
        labels = {
            'show_score': 'نمایش نمره',
            'show_correct_answers': 'نمایش پاسخ صحیح',
            'show_rank': 'نمایش رتبه',
            'average_score': 'میانگین',
            'highest_score': 'بالاترین نمره',
            'lowest_score': 'پایین‌ترین نمره',
            'is_published': 'انتشار نتایج',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', 'super-admin-input')


class ObjectionReviewForm(forms.ModelForm):
    class Meta:
        model = StudentObjection
        fields = ('decision', 'revised_score', 'decision_reason')
        labels = {'decision': 'تصمیم', 'revised_score': 'نمره اصلاح‌شده', 'decision_reason': 'دلیل تصمیم'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', 'super-admin-input')


class AssistantQuestionForm(QuestionForm):
    pass


class AssistantQuestionReviewForm(forms.ModelForm):
    class Meta:
        model = AssistantQuestionSubmission
        fields = ('status', 'teacher_note')
        labels = {
            'status': 'تصمیم استاد',
            'teacher_note': 'یادداشت استاد',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', 'super-admin-input')


class AssistantQuestionSuggestionForm(forms.ModelForm):
    class Meta:
        model = AssistantQuestionSuggestion
        fields = ('question', 'suggested_text', 'suggested_correct_answer', 'suggested_topic', 'note')
        labels = {
            'question': 'سؤال',
            'suggested_text': 'متن پیشنهادی سؤال',
            'suggested_correct_answer': 'پاسخ صحیح پیشنهادی',
            'suggested_topic': 'موضوع پیشنهادی',
            'note': 'توضیح اشکال یا دلیل اصلاح',
        }

    def __init__(self, *args, teacher=None, **kwargs):
        self.teacher = teacher
        super().__init__(*args, **kwargs)
        if teacher:
            self.fields['question'].queryset = teacher.questions.filter(is_active=True)
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', 'super-admin-input')


class AssistantQuestionSuggestionReviewForm(forms.ModelForm):
    class Meta:
        model = AssistantQuestionSuggestion
        fields = ('status', 'teacher_note')
        labels = {
            'status': 'تصمیم استاد',
            'teacher_note': 'یادداشت استاد',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', 'super-admin-input')


class AssistantExamDraftForm(TeacherExamForm):
    pass


class AssistantExamDraftReviewForm(forms.ModelForm):
    class Meta:
        model = AssistantExamDraft
        fields = ('status', 'teacher_note')
        labels = {
            'status': 'تصمیم استاد',
            'teacher_note': 'یادداشت استاد',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['status'].choices = (
            (AssistantExamDraft.Status.APPROVED, 'تأیید و انتشار'),
            (AssistantExamDraft.Status.REJECTED, 'رد پیش‌نویس'),
        )
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', 'super-admin-input')


class AssistantReviewAssignmentForm(forms.Form):
    assistant = forms.ModelChoiceField(label='دستیار', queryset=UserProfile.objects.none())

    def __init__(self, *args, teacher=None, **kwargs):
        super().__init__(*args, **kwargs)
        qs = UserProfile.objects.select_related('user', 'role').filter(
            role__code=SystemRole.RoleCode.TEACHING_ASSISTANT,
            supervisor_teacher=teacher.profile.user if teacher else None,
        )
        self.fields['assistant'].queryset = qs
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', 'super-admin-input')


class AssistantDescriptiveReviewForm(forms.ModelForm):
    class Meta:
        model = AssistantReviewAssignment
        fields = ('proposed_score', 'feedback', 'is_suspicious')
        labels = {
            'proposed_score': 'نمره پیشنهادی',
            'feedback': 'بازخورد',
            'is_suspicious': 'پاسخ مشکوک',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', 'super-admin-input')


class AssistantReviewDecisionForm(forms.ModelForm):
    class Meta:
        model = AssistantReviewAssignment
        fields = ('status', 'teacher_note')
        labels = {
            'status': 'تصمیم استاد',
            'teacher_note': 'یادداشت استاد',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['status'].choices = (
            (AssistantReviewAssignment.Status.APPROVED, 'تأیید نمره پیشنهادی'),
            (AssistantReviewAssignment.Status.RETURNED, 'برگشت برای اصلاح'),
        )
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', 'super-admin-input')


class EducationalQuestionForm(forms.ModelForm):
    class Meta:
        model = EducationalQuestion
        fields = ('exam', 'course', 'question_text')
        labels = {
            'exam': 'آزمون',
            'course': 'درس',
            'question_text': 'پرسش',
        }

    def __init__(self, *args, student=None, **kwargs):
        self.student = student
        super().__init__(*args, **kwargs)
        if student:
            self.fields['course'].queryset = student.courses.all() or Course.objects.filter(institution=student.institution)
            self.fields['exam'].queryset = Exam.objects.filter(course__in=self.fields['course'].queryset)
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', 'super-admin-input')

    def clean(self):
        cleaned = super().clean()
        exam = cleaned.get('exam')
        course = cleaned.get('course')
        if exam and not course:
            cleaned['course'] = exam.course
        return cleaned


class AssistantEducationalAnswerForm(forms.ModelForm):
    refer_to_teacher = forms.BooleanField(label='ارجاع به استاد', required=False)

    class Meta:
        model = EducationalQuestion
        fields = ('answer_text', 'refer_to_teacher')
        labels = {
            'answer_text': 'پاسخ دستیار',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', 'super-admin-input')


class StudentExamEntryForm(forms.ModelForm):
    accept_rules = forms.BooleanField(label='قوانین آزمون را مطالعه و تأیید می‌کنم.')

    class Meta:
        model = StudentExamAttempt
        fields = ('identity_code', 'identity_image', 'accept_rules')
        labels = {
            'identity_code': 'کد احراز هویت',
            'identity_image': 'تصویر احراز هویت',
        }

    def __init__(self, *args, exam=None, **kwargs):
        self.exam = exam
        super().__init__(*args, **kwargs)
        if exam and not exam.require_identity_verification:
            self.fields['identity_code'].required = False
            self.fields['identity_image'].required = False
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', 'super-admin-input')


class StudentAnswerForm(forms.ModelForm):
    class Meta:
        model = StudentQuestionAnswer
        fields = ('answer_text', 'marked_for_review', 'uploaded_file')
        labels = {
            'answer_text': 'پاسخ',
            'marked_for_review': 'علامت‌گذاری برای مرور',
            'uploaded_file': 'فایل پاسخ',
        }

    def __init__(self, *args, exam_question=None, allow_file_upload=False, **kwargs):
        self.exam_question = exam_question
        self.allow_file_upload = allow_file_upload
        super().__init__(*args, **kwargs)
        question = exam_question.question if exam_question else None
        if question and question.question_type in (Question.QuestionType.MULTIPLE_CHOICE, Question.QuestionType.TRUE_FALSE):
            choices = [(option, option) for option in (question.options or [])]
            if question.question_type == Question.QuestionType.TRUE_FALSE and not choices:
                choices = [('true', 'صحیح'), ('false', 'غلط')]
            self.fields['answer_text'] = forms.ChoiceField(label='گزینه پاسخ', choices=choices, required=False)
        if not allow_file_upload:
            self.fields.pop('uploaded_file', None)
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', 'super-admin-input')

    def clean_uploaded_file(self):
        file = self.cleaned_data.get('uploaded_file')
        if not file:
            return file
        allowed_extensions = {'.pdf', '.doc', '.docx', '.jpg', '.jpeg', '.png', '.zip'}
        name = file.name.lower()
        if not any(name.endswith(ext) for ext in allowed_extensions):
            raise forms.ValidationError('فرمت فایل مجاز نیست.')
        if file.size > 5 * 1024 * 1024:
            raise forms.ValidationError('حجم فایل نباید بیشتر از ۵ مگابایت باشد.')
        return file


class StudentPracticeCheckForm(forms.Form):
    browser_ok = forms.BooleanField(label='مرورگر سازگار است', required=False)
    internet_ok = forms.BooleanField(label='اتصال اینترنت برقرار است', required=False)
    camera_ok = forms.BooleanField(label='دوربین در دسترس است', required=False)
    microphone_ok = forms.BooleanField(label='میکروفن در دسترس است', required=False)
    sample_answer_1 = forms.ChoiceField(label='پاسخ سؤال آزمایشی ۱', choices=(('a', 'گزینه ۱'), ('b', 'گزینه ۲')))
    sample_answer_2 = forms.CharField(label='پاسخ کوتاه آزمایشی', max_length=120)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', 'super-admin-input')


class StudentObjectionCreateForm(forms.ModelForm):
    class Meta:
        model = StudentObjection
        fields = ('exam', 'question', 'objection_type', 'objection_text', 'evidence_file')
        labels = {
            'exam': 'آزمون',
            'question': 'سؤال',
            'objection_type': 'نوع اعتراض',
            'objection_text': 'توضیحات',
            'evidence_file': 'مستندات',
        }

    def __init__(self, *args, student=None, **kwargs):
        self.student = student
        super().__init__(*args, **kwargs)
        if student:
            attempts = student.exam_attempts.filter(status__in=[
                StudentExamAttempt.Status.SUBMITTED,
                StudentExamAttempt.Status.AUTO_SUBMITTED,
            ])
            self.fields['exam'].queryset = Exam.objects.filter(student_attempts__in=attempts).distinct()
            self.fields['question'].queryset = Question.objects.filter(exam_links__exam__in=self.fields['exam'].queryset).distinct()
        for field in self.fields.values():
            field.widget.attrs.setdefault('class', 'super-admin-input')

    def clean_evidence_file(self):
        file = self.cleaned_data.get('evidence_file')
        if file and file.size > 5 * 1024 * 1024:
            raise forms.ValidationError('حجم فایل مستندات نباید بیشتر از ۵ مگابایت باشد.')
        return file
