from django.contrib import admin
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
    ExamQuestion,
    ExamProctorProfile,
    ExamProctorAssignment,
    ExamRescheduleRequest,
    ExamStartAuthorization,
    ExamViolationReport,
    ExamResultPublication,
    InstitutionAdminProfile,
    StudentProfile,
    StudentObjection,
    StudentExamAttempt,
    StudentExamEvent,
    StudentPracticeCheck,
    StudentQuestionAnswer,
    SystemAdminProfile,
    SystemRole,
    TeacherProfile,
    TechnicalSupportProfile,
    Question,
    UserActivityLog,
    UserLoginRecord,
    UserProfile,
)

admin.site.site_header = 'پنل مدیریت آزمون‌یار'
admin.site.site_title = 'مدیریت آزمون‌یار'
admin.site.index_title = 'مدیریت سامانه'
admin.site.index_template = 'admin/custom_index.html'


@admin.register(SystemRole)
class SystemRoleAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'access_level', 'is_active')
    list_filter = ('is_active', 'code')
    search_fields = ('name', 'description')
    ordering = ('-access_level', 'name')


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ('full_name', 'user', 'role', 'mobile', 'institution_name', 'account_status', 'account_verified')
    list_filter = ('role', 'account_status', 'account_verified', 'two_factor_enabled', 'gender')
    search_fields = (
        'full_name',
        'user__username',
        'user__email',
        'mobile',
        'national_code',
        'personnel_number',
        'student_number',
        'institution_name',
    )
    autocomplete_fields = ('user', 'role', 'supervisor_teacher')
    readonly_fields = ('created_at', 'updated_at')
    fieldsets = (
        ('اطلاعات اصلی', {
            'fields': (
                'user',
                'role',
                'full_name',
                'father_name',
                'national_code',
                'passport_number',
                'birth_date',
                'gender',
                'mobile',
                'organizational_email',
                'residential_address',
                'profile_image',
            )
        }),
        ('اطلاعات سازمانی و آموزشی', {
            'fields': (
                'personnel_number',
                'student_number',
                'applicant_code',
                'institution_name',
                'organizational_position',
                'faculty_or_unit',
                'department',
                'field_of_study',
                'specialization',
                'academic_rank_or_job_title',
                'education_level',
                'entrance_year',
                'semester',
                'class_or_group',
                'education_status',
            )
        }),
        ('دسترسی و وضعیت حساب', {
            'fields': (
                'account_status',
                'access_scope',
                'responsibility_scope',
                'cooperation_type',
                'cooperation_started_at',
                'cooperation_ended_at',
                'account_verified',
                'two_factor_enabled',
                'supervisor_teacher',
            )
        }),
        ('دوره‌ها و آزمون‌ها', {
            'fields': (
                'teachable_courses',
                'selected_courses',
                'related_courses',
                'devices',
                'login_records',
                'assigned_exams',
                'exam_status',
                'submitted_files',
                'violations',
                'objections',
            )
        }),
        ('مدارک و امضا', {
            'fields': (
                'position_documents',
                'resume_or_academic_document',
                'digital_signature',
                'digital_stamp',
            )
        }),
        ('زمان‌ها', {
            'fields': ('created_at', 'updated_at')
        }),
    )


@admin.register(AcademicInstitution)
class AcademicInstitutionAdmin(admin.ModelAdmin):
    list_display = ('name', 'institution_type', 'city', 'status', 'max_users', 'max_exams')
    list_filter = ('institution_type', 'status', 'province', 'city')
    search_fields = ('name', 'registration_code', 'national_id', 'phone', 'email')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(AcademicUnit)
class AcademicUnitAdmin(admin.ModelAdmin):
    list_display = ('name', 'institution', 'unit_type', 'code', 'is_active')
    list_filter = ('unit_type', 'is_active', 'institution')
    search_fields = ('name', 'code', 'institution__name')
    autocomplete_fields = ('institution', 'parent', 'manager')
    readonly_fields = ('created_at',)


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ('title', 'code', 'institution', 'academic_unit', 'credit_count', 'is_active')
    list_filter = ('is_active', 'institution', 'academic_unit')
    search_fields = ('title', 'code', 'institution__name')
    autocomplete_fields = ('institution', 'academic_unit')
    readonly_fields = ('created_at',)


@admin.register(AcademicTerm)
class AcademicTermAdmin(admin.ModelAdmin):
    list_display = ('title', 'institution', 'year', 'starts_at', 'ends_at', 'is_active')
    list_filter = ('institution', 'is_active', 'year')
    search_fields = ('title', 'institution__name')
    autocomplete_fields = ('institution',)
    readonly_fields = ('created_at',)


@admin.register(CourseClass)
class CourseClassAdmin(admin.ModelAdmin):
    list_display = ('title', 'institution', 'course', 'term', 'teacher', 'capacity', 'is_active')
    list_filter = ('institution', 'term', 'is_active')
    search_fields = ('title', 'code', 'course__title', 'institution__name')
    autocomplete_fields = ('institution', 'course', 'term', 'teacher', 'students')
    readonly_fields = ('created_at',)


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ('text', 'teacher', 'course', 'question_type', 'difficulty', 'suggested_score', 'is_active')
    list_filter = ('question_type', 'difficulty', 'is_active', 'course')
    search_fields = ('text', 'correct_answer', 'chapter', 'topic', 'teacher__profile__full_name')
    autocomplete_fields = ('teacher', 'course')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(ExamQuestion)
class ExamQuestionAdmin(admin.ModelAdmin):
    list_display = ('exam', 'question', 'score', 'order')
    search_fields = ('exam__title', 'question__text')
    autocomplete_fields = ('exam', 'question')


@admin.register(SystemAdminProfile)
class SystemAdminProfileAdmin(admin.ModelAdmin):
    list_display = ('profile', 'admin_code', 'can_manage_roles', 'can_manage_institutions', 'can_view_security_logs')
    list_filter = ('can_manage_roles', 'can_manage_institutions', 'can_manage_system_settings', 'can_view_security_logs')
    search_fields = ('profile__full_name', 'profile__user__username', 'admin_code')
    autocomplete_fields = ('profile',)
    readonly_fields = ('created_at', 'updated_at')


@admin.register(InstitutionAdminProfile)
class InstitutionAdminProfileAdmin(admin.ModelAdmin):
    list_display = ('profile', 'institution', 'employee_code', 'position_title', 'can_schedule_exams')
    list_filter = ('institution', 'can_approve_users', 'can_manage_teachers', 'can_manage_students', 'can_schedule_exams')
    search_fields = ('profile__full_name', 'profile__user__username', 'employee_code', 'position_title', 'institution__name')
    autocomplete_fields = ('profile', 'institution', 'managed_units')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(TeacherProfile)
class TeacherProfileAdmin(admin.ModelAdmin):
    list_display = ('profile', 'institution', 'academic_unit', 'personnel_code', 'academic_rank', 'can_design_exam')
    list_filter = ('institution', 'academic_unit', 'employment_type', 'can_design_exam', 'can_grade_answers')
    search_fields = ('profile__full_name', 'profile__user__username', 'personnel_code', 'specialization')
    autocomplete_fields = ('profile', 'institution', 'academic_unit', 'courses')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(StudentProfile)
class StudentProfileAdmin(admin.ModelAdmin):
    list_display = ('profile', 'institution', 'student_number', 'field_of_study', 'education_level', 'enrollment_status')
    list_filter = ('institution', 'academic_unit', 'education_level', 'enrollment_status')
    search_fields = ('profile__full_name', 'profile__user__username', 'student_number', 'applicant_code', 'field_of_study')
    autocomplete_fields = ('profile', 'institution', 'academic_unit', 'courses')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(ExamProctorProfile)
class ExamProctorProfileAdmin(admin.ModelAdmin):
    list_display = ('profile', 'institution', 'proctor_code', 'proctor_type', 'max_concurrent_sessions')
    list_filter = ('institution', 'proctor_type', 'can_verify_identity', 'can_pause_exam', 'can_report_violation')
    search_fields = ('profile__full_name', 'profile__user__username', 'proctor_code')
    autocomplete_fields = ('profile', 'institution')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(TechnicalSupportProfile)
class TechnicalSupportProfileAdmin(admin.ModelAdmin):
    list_display = ('profile', 'institution', 'support_code', 'support_level', 'expertise_area')
    list_filter = ('institution', 'support_level', 'can_access_logs', 'can_reset_sessions', 'can_manage_devices')
    search_fields = ('profile__full_name', 'profile__user__username', 'support_code', 'expertise_area')
    autocomplete_fields = ('profile', 'institution')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(UserActivityLog)
class UserActivityLogAdmin(admin.ModelAdmin):
    list_display = ('user', 'action', 'ip_address', 'created_at')
    list_filter = ('action', 'created_at')
    search_fields = ('user__username', 'user__email', 'action', 'description', 'ip_address')
    readonly_fields = ('created_at',)
    autocomplete_fields = ('user',)


@admin.register(UserLoginRecord)
class UserLoginRecordAdmin(admin.ModelAdmin):
    list_display = ('user', 'ip_address', 'device_name', 'was_successful', 'logged_in_at')
    list_filter = ('was_successful', 'logged_in_at')
    search_fields = ('user__username', 'user__email', 'ip_address', 'device_name')
    readonly_fields = ('logged_in_at',)
    autocomplete_fields = ('user',)


@admin.register(ExamViolationReport)
class ExamViolationReportAdmin(admin.ModelAdmin):
    list_display = ('title', 'exam', 'student', 'decision', 'occurred_at', 'created_at')
    list_filter = ('decision', 'exam__institution', 'created_at')
    search_fields = ('title', 'description', 'exam__title', 'student__profile__full_name')
    autocomplete_fields = ('exam', 'student', 'proctor', 'teacher', 'decided_by')
    readonly_fields = ('created_at',)


@admin.register(ExamApproval)
class ExamApprovalAdmin(admin.ModelAdmin):
    list_display = ('exam', 'decision', 'requested_by', 'reviewed_by', 'requested_at', 'reviewed_at')
    list_filter = ('decision', 'requested_at')
    search_fields = ('exam__title', 'note')
    autocomplete_fields = ('exam', 'requested_by', 'reviewed_by')
    readonly_fields = ('requested_at',)


@admin.register(ExamProctorAssignment)
class ExamProctorAssignmentAdmin(admin.ModelAdmin):
    list_display = ('exam', 'proctor', 'status', 'assigned_by', 'assigned_at')
    list_filter = ('status', 'assigned_at')
    search_fields = ('exam__title', 'proctor__profile__full_name')
    autocomplete_fields = ('exam', 'proctor', 'assigned_by')
    readonly_fields = ('assigned_at',)


@admin.register(ExamRescheduleRequest)
class ExamRescheduleRequestAdmin(admin.ModelAdmin):
    list_display = ('exam', 'status', 'new_starts_at', 'new_ends_at', 'requested_by', 'reviewed_by')
    list_filter = ('status', 'created_at')
    search_fields = ('exam__title', 'reason', 'review_note')
    autocomplete_fields = ('exam', 'requested_by', 'reviewed_by')
    readonly_fields = ('created_at',)


@admin.register(ExamStartAuthorization)
class ExamStartAuthorizationAdmin(admin.ModelAdmin):
    list_display = ('exam', 'authorized', 'students_entered', 'absent_students', 'proctor_ready', 'teacher_ready', 'authorized_at')
    list_filter = ('authorized', 'proctor_ready', 'teacher_ready')
    search_fields = ('exam__title', 'note')
    autocomplete_fields = ('exam', 'authorized_by')
    readonly_fields = ('created_at',)


@admin.register(ExamExecutionReport)
class ExamExecutionReportAdmin(admin.ModelAdmin):
    list_display = ('exam', 'participants_count', 'absent_count', 'incomplete_count', 'violations_count', 'sent_to_institution_manager')
    list_filter = ('sent_to_institution_manager', 'created_at')
    search_fields = ('exam__title', 'final_note')
    autocomplete_fields = ('exam', 'prepared_by')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(DescriptiveAnswerReview)
class DescriptiveAnswerReviewAdmin(admin.ModelAdmin):
    list_display = ('exam', 'question', 'student', 'score', 'is_suspicious', 'finalized', 'reviewed_at')
    list_filter = ('finalized', 'is_suspicious', 'created_at')
    search_fields = ('exam__title', 'question__text', 'student__profile__full_name', 'answer_text')
    autocomplete_fields = ('exam', 'question', 'student', 'reviewed_by')
    readonly_fields = ('created_at',)


@admin.register(ExamResultPublication)
class ExamResultPublicationAdmin(admin.ModelAdmin):
    list_display = ('exam', 'is_published', 'average_score', 'highest_score', 'lowest_score', 'published_at')
    list_filter = ('is_published', 'published_at')
    search_fields = ('exam__title',)
    autocomplete_fields = ('exam', 'published_by')
    readonly_fields = ('created_at',)


@admin.register(StudentObjection)
class StudentObjectionAdmin(admin.ModelAdmin):
    list_display = ('exam', 'student', 'question', 'decision', 'created_at', 'reviewed_at')
    list_filter = ('decision', 'created_at')
    search_fields = ('exam__title', 'student__profile__full_name', 'objection_text', 'decision_reason')
    autocomplete_fields = ('exam', 'question', 'student', 'reviewed_by')
    readonly_fields = ('created_at',)


@admin.register(AssistantQuestionSubmission)
class AssistantQuestionSubmissionAdmin(admin.ModelAdmin):
    list_display = ('question', 'assistant', 'teacher', 'status', 'created_at', 'reviewed_at')
    list_filter = ('status', 'created_at')
    search_fields = ('question__text', 'assistant__username', 'teacher__profile__full_name', 'teacher_note')
    autocomplete_fields = ('assistant', 'teacher', 'question', 'reviewed_by')
    readonly_fields = ('created_at',)


@admin.register(AssistantQuestionSuggestion)
class AssistantQuestionSuggestionAdmin(admin.ModelAdmin):
    list_display = ('question', 'assistant', 'teacher', 'status', 'created_at', 'reviewed_at')
    list_filter = ('status', 'created_at')
    search_fields = ('question__text', 'note', 'assistant__username', 'teacher__profile__full_name')
    autocomplete_fields = ('assistant', 'teacher', 'question', 'reviewed_by')
    readonly_fields = ('created_at',)


@admin.register(AssistantExamDraft)
class AssistantExamDraftAdmin(admin.ModelAdmin):
    list_display = ('exam', 'assistant', 'teacher', 'status', 'created_at', 'reviewed_at')
    list_filter = ('status', 'created_at')
    search_fields = ('exam__title', 'assistant__username', 'teacher__profile__full_name', 'teacher_note')
    autocomplete_fields = ('assistant', 'teacher', 'exam', 'reviewed_by')
    readonly_fields = ('created_at',)


@admin.register(AssistantReviewAssignment)
class AssistantReviewAssignmentAdmin(admin.ModelAdmin):
    list_display = ('review', 'assistant', 'teacher', 'proposed_score', 'is_suspicious', 'status', 'created_at')
    list_filter = ('status', 'is_suspicious', 'created_at')
    search_fields = ('review__exam__title', 'review__question__text', 'assistant__username', 'teacher__profile__full_name')
    autocomplete_fields = ('assistant', 'teacher', 'review', 'reviewed_by')
    readonly_fields = ('created_at', 'submitted_at')


@admin.register(EducationalQuestion)
class EducationalQuestionAdmin(admin.ModelAdmin):
    list_display = ('student', 'course', 'exam', 'teacher', 'status', 'needs_teacher_decision', 'created_at')
    list_filter = ('status', 'needs_teacher_decision', 'created_at')
    search_fields = ('question_text', 'answer_text', 'student__profile__full_name', 'teacher__profile__full_name')
    autocomplete_fields = ('student', 'exam', 'course', 'teacher', 'assistant')
    readonly_fields = ('created_at', 'answered_at')


@admin.register(StudentExamAttempt)
class StudentExamAttemptAdmin(admin.ModelAdmin):
    list_display = ('exam', 'student', 'status', 'identity_confirmed', 'rules_accepted', 'started_at', 'submitted_at')
    list_filter = ('status', 'identity_confirmed', 'rules_accepted', 'created_at')
    search_fields = ('exam__title', 'student__profile__full_name', 'receipt_code', 'identity_code')
    autocomplete_fields = ('exam', 'student')
    readonly_fields = ('created_at',)


@admin.register(StudentQuestionAnswer)
class StudentQuestionAnswerAdmin(admin.ModelAdmin):
    list_display = ('attempt', 'exam_question', 'marked_for_review', 'autosaved_at', 'submitted_at')
    list_filter = ('marked_for_review', 'autosaved_at', 'submitted_at')
    search_fields = ('attempt__exam__title', 'attempt__student__profile__full_name', 'answer_text')
    autocomplete_fields = ('attempt', 'exam_question')


@admin.register(StudentExamEvent)
class StudentExamEventAdmin(admin.ModelAdmin):
    list_display = ('attempt', 'event_type', 'created_at')
    list_filter = ('event_type', 'created_at')
    search_fields = ('attempt__exam__title', 'attempt__student__profile__full_name', 'message')
    autocomplete_fields = ('attempt',)
    readonly_fields = ('created_at',)


@admin.register(StudentPracticeCheck)
class StudentPracticeCheckAdmin(admin.ModelAdmin):
    list_display = ('student', 'browser_ok', 'internet_ok', 'camera_ok', 'microphone_ok', 'sample_score', 'created_at')
    list_filter = ('browser_ok', 'internet_ok', 'camera_ok', 'microphone_ok', 'created_at')
    search_fields = ('student__profile__full_name',)
    autocomplete_fields = ('student',)
    readonly_fields = ('created_at',)


@admin.register(Exam)
class ExamAdmin(admin.ModelAdmin):
    list_display = ('title', 'institution', 'course', 'designer', 'starts_at', 'ends_at', 'status', 'is_active')
    list_filter = ('status', 'is_active', 'institution', 'course')
    search_fields = ('title', 'description', 'institution__name', 'course__title')
    autocomplete_fields = ('institution', 'course', 'designer', 'proctors', 'technical_supports')
