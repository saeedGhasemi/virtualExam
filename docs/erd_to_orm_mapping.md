# نگاشت جدول‌های ERD خام ↔ مدل‌های ORM

مرحلهٔ ۱ (envanتوری) طبق `docs/migration-plan/PROMPT_FOR_CLAUDE_CODE.md`. فقط خواندنی — هیچ کدی تغییر نکرده.

## یافتهٔ مهم قبل از جدول‌ها: تعداد جدول‌های خام واقعی بیشتر از فهرست پرامپت است

پرامپت ۱۳ جدول را نام برد، اما `migrations/0014_create_erd_tables.py` مجموعاً **۲۶ جدول** می‌سازد، و migrations `0015` تا `0022` روی همان جدول‌ها مدام ستون اضافه کرده‌اند (یعنی لایهٔ ERD هنوز به‌صورت فعال توسعه داده می‌شده، نه یک باقیماندهٔ رهاشده). جدول‌های اضافه‌ای که در پرامپت نامی از آن‌ها نبود: `admin_profiles`, `user_roles`, `notifications`, `activity_audit_log`, `courses`, `question_sets`, `course_audit_log`, `student_group_members`, `group_teachers`, `exam_assignments`, `exam_questions`, `objections`, `question_set_items`, و `student_course_enrollments` (این آخری در migration `0018` ساخته شده، حتی در migration `0014` هم نبود). این باید به‌عنوان **تناقض با فرض‌های پرامپت** ثبت شود؛ طبق قانون سخت‌گیرانهٔ شماره ۶، این یافته را گزارش می‌کنم و پیش‌فرض نمی‌گیرم که همه باید یکسان مهاجرت شوند — تصمیم دربارهٔ جدول‌های اضافه باید از شما گرفته شود (به بخش «نیازمند تصمیم» در پایان سند مراجعه شود).

---

## ۱. جدول‌های صریحاً نام‌برده‌شده در پرامپت

### `profiles`
**ستون‌ها (از `0014` + اضافه‌شده در `0019`):**
`id (uuid PK)`, `full_name`, `first_name`, `last_name`, `username (unique)`, `email`, `phone`, `national_id (unique)`, `identifier`, `avatar_url`, `status (active/inactive/blocked)`, `last_login_at`, `created_at`, `updated_at`, `gender`, `birth_date`, `password_method`, `must_change_password`, `email_verified_required`.

**نزدیک‌ترین معادل ORM:** هیچ مدل واحدی. این جدول معادل ترکیبی از `django.contrib.auth.User` + `apps.core.models.UserProfile` است، اما با شِمای متفاوت (فیلدهای هویتی مثل `national_id`/`identifier` که در `UserProfile` هم با نام‌های دیگر — `national_code`, `applicant_code` — وجود دارند اما یکسان نیستند).

**در `models_unified_postgres.py` پیشنهادی:** معادل صریحی برای `profiles` طراحی نشده — آن سند فرض کرده که `User` استاندارد جنگو (`settings.AUTH_USER_MODEL`) کافی است و پروفایل‌ها مستقیماً به آن OneToOne می‌شوند. **⚠️ تناقض:** ستون‌های `gender`, `birth_date`, `password_method`, `must_change_password`, `email_verified_required` در `profiles` خام هستند اما نه در `User` جنگو نه در هیچ مدل `models_unified_postgres.py` جایی ندارند. نیاز به تصمیم دارد.

### `org_units`
**ستون‌ها:** `id (uuid PK)`, `parent_id (self FK)`, `type (university/faculty/department/group)`, `name`, `code`, `is_active`.

**نزدیک‌ترین معادل ORM موجود:** `apps.core.models.AcademicUnit` (خودارجاع با `parent`، اما `unit_type` چهار مقدار متفاوت دارد: `faculty/department/grade/class_group` — نه `university/faculty/department/group`).

**در `models_unified_postgres.py`:** `AcademicUnit` بازطراحی شده با فیلد جدید `path` (ماتریالایز‌شده) و متد `descendant_ids()` به‌جای CTE بازگشتی. این دقیقاً جایگزین منطق `_erd_manager_scope_cte` (خط ۱۱۶۲۰ `views.py`) است. **نکته:** `models_unified_postgres.py` یک مدل جدید `Institution` هم دارد که در `models.py` واقعی وجود ندارد (آنجا مستقیماً `AcademicInstitution` نقش مؤسسه را دارد) — این باید هنگام diff گرفتن در مرحلهٔ ۳ دقت شود، چون تغییر نام مدل (`AcademicInstitution` → `Institution`) در قوانین سخت‌گیرانه («هیچ مدل موجود rename نشود») صراحتاً ممنوع است.

### `teacher_profiles`
**ستون‌ها:** `user_id (PK, FK→profiles)`, `personnel_code`, `department`, `specialty`, `approval_status (pending/approved/rejected)`, `org_unit_id (FK→org_units)`.

**معادل ORM:** `apps.core.models.TeacherProfile` — فیلدهای مشابه دارد (`personnel_code`, `academic_unit`) اما **فیلد `approval_status` در ORM وجود ندارد** (یعنی گردش کار تأیید استاد که در ERD هست، در ORM بی‌معادل است).

### `student_profiles`
**ستون‌ها (از `0014` + `0018`):** `user_id (PK)`, `student_number`, `field_of_study`, `degree`, `class_group`, `semester`, `academic_status (active/leave/graduated/inactive)`, `department`, `org_unit_id`, `entry_year`, `admission_type`, `password_method`, `must_change_password`, `send_welcome_message`.

**معادل ORM:** `apps.core.models.StudentProfile` — فیلدهای مشابه (`field_of_study`, `semester`, `enrollment_status`) اما مقادیر enum متفاوت (`EnrollmentStatus`: active/graduated/suspended/withdrawn در ORM، در برابر `academic_status`: active/leave/graduated/inactive در ERD) — **این دو enum یک‌به‌یک منطبق نیستند** (`leave` در ORM معادل ندارد، `suspended`/`withdrawn` در ERD معادل ندارند).

### `academic_manager_profiles`
**ستون‌ها (از `0014` + `0019`):** `user_id (PK)`, `personnel_code`, `department`, `responsibility_area`, `title`, `access_type`, `include_child_units (boolean, default true)`.

**معادل ORM:** **وجود ندارد.** طبق بخش ۳ گزارش فاز اول، هیچ `ExamManagerProfile` در ORM نیست. `models_unified_postgres.py` این را با مدل جدید `ExamManagerProfile` پر می‌کند، اما آن مدل فقط فیلد `managed_unit` (تک FK) دارد — ستون `include_child_units` (که یعنی «آیا دسترسی به زیرمجموعه‌ها هم شامل شود یا نه» به‌صورت boolean قابل‌تنظیم) **در طراحی جدید نیست**. این یک تفاوت رفتاری واقعی است: در ERD فعلی می‌شود یک مدیر را «فقط به همین واحد، نه زیرشاخه‌ها» محدود کرد؛ در طراحی ORM جدید این حالت اصلاً قابل بیان نیست (`descendant_ids(include_self=True)` همیشه شامل زیرشاخه‌هاست). **نیازمند تصمیم.**

### `academic_manager_scopes`
**ستون‌ها:** `id (uuid PK)`, `manager_id (FK→academic_manager_profiles)`, `org_unit_id (FK→org_units)`, `created_at`, `UNIQUE(manager_id, org_unit_id)`.

**معادل ORM:** **وجود ندارد** (نه در `models.py` فعلی، نه به‌صورت جدول جداگانه در `models_unified_postgres.py`). این جدول اجازه می‌دهد یک مدیر آموزشی به **چند واحد سازمانی مجزا** (نه فقط یک زیردرخت) هم‌زمان دسترسی داشته باشد (رابطهٔ چند-به-چند بین مدیر و واحد). طراحی `models_unified_postgres.py` این را با یک FK تکی `managed_unit` روی `ExamManagerProfile` جایگزین کرده — یعنی **هر مدیر فقط یک زیردرخت** می‌تواند داشته باشد، نه چند واحد ناهم‌بسته. اگر داده‌ی واقعی در `academic_manager_scopes` بیش از یک ردیف برای بعضی مدیرها دارد، این یک محدودیت واقعی در طراحی هدف است که باید قبل از مهاجرت مشخص شود. **نیازمند تصمیم (این دقیقاً همان چیزی است که نقشه‌راه هم در ردیف جدول‌های «بدون معادل ORM» علامت زده بود).**

### `exams`
**ستون‌ها (از `0014` + `0015` + `0020`، فهرست کامل):**
`id`, `teacher_id`, `course_id`, `title`, `description`, `duration_minutes`, `start_at`, `end_at`, `shuffle_questions`, `shuffle_options`, `negative_marking`, `negative_factor`, `max_attempts`, `is_published`, `show_results_immediately`, `passing_score`, `allow_partial`, `is_cancelled`, `cancel_reason`, `extend_reason`, `approval_status`, `approved_by`, `approved_at`, `exam_type`, `academic_year`, `semester`, `lifecycle_status` (از `0015`)، و از `0020`: `result_release_mode`, `review_answers_enabled`, `show_instructions_before_start`, `autosave_enabled`, `fullscreen_required`, `track_tab_exit`, `show_correct_answers`, `show_score`, `show_feedback`, `publish_mode`.

**معادل ORM:** `apps.core.models.Exam` — از نظر مفهومی غنی است (`ExamStatus` هفت‌حالته، `negative_marking_enabled`, `randomize_questions`, ...) اما **فیلدهای امنیتی نظارتی ERD مثل `fullscreen_required` و `track_tab_exit` در ORM نیستند.** این‌ها احتمالاً برای پیشگیری تخلف در حین آزمون استفاده می‌شوند و نبودشان در ORM یعنی این قابلیت‌ها با سوییچ به ORM (بدون افزودن معادل) **از دست می‌روند**، نه فقط بازسازی می‌شوند. `models_unified_postgres.py` همهٔ این تنظیمات ریز را در یک `settings_payload` (JSONField واحد) جمع کرده — یعنی تصمیم طراحی این بوده که این فیلدها به ستون‌های مجزا در ORM تبدیل نشوند، بلکه در یک JSON عمومی بمانند. **این باید صراحتاً تأیید شود** چون یعنی نمی‌توان روی این فیلدها ایندکس یا CHECK constraint مجزا گذاشت.

### `questions`
**ستون‌ها (از `0014` + `0022`، فهرست کامل):**
`id`, `teacher_id`, `course_id`, `type (single/multi/true_false/short_answer/essay/fill_blank/matching/ordering)`, `difficulty`, `text`, `options (jsonb)`, `correct_answer (jsonb)`, `explanation`, `default_points`, `tags`, `media_url`، و از `0022`: `structure (default 'independent')`, `subject`, `question_media (jsonb)`, `answer_media (jsonb)`, `scoring_settings (jsonb)`, `feedback (jsonb)`, `rubric (jsonb)`, `accepted_answers (jsonb)`, `matching_pairs (jsonb)`, `ordering_items (jsonb)`, `scenario_data (jsonb)`, `is_published`, `negative_points`, `suggested_time_seconds`.

**یافتهٔ مهم:** ستون `type` در ERD از ابتدا (`0014`) هشت مقدار را در CHECK constraint می‌پذیرد: `single, multi, true_false, short_answer, essay, fill_blank, matching, ordering` — یعنی **`multi` و `ordering` از قبل در لایهٔ خام SQL وجود داشتند**، برخلاف `apps.core.models.Question.QuestionType` که فقط ۶ مقدار دارد (بدون `multi`/`ordering`، طبق بخش ۴ ردیف ۶ گزارش فاز اول).

**یافتهٔ مهم‌تر:** ستون `structure` (اضافه‌شده در `0022`) دقیقاً معادل الزام «ساختار سؤال باید ابتدا مشخص باشد: مستقل / گروه سؤال مبتنی بر سناریوی بیمار / سازندهٔ سناریوی KFP / سازندهٔ ایستگاه OSCE» از بریف اصلی فاز اول است — با مقدار پیش‌فرض `'independent'`. یعنی **این ساختار در لایهٔ خام از قبل طراحی و پیاده شده**، برخلاف تصور بخش ۴ گزارش فاز اول که نوشته بود «این ساختارها در مدل دیده نشد» — آن نتیجه‌گیری فقط دربارهٔ ORM درست بود، نه دربارهٔ ERD. ستون‌های `matching_pairs`, `ordering_items`, `rubric`, `accepted_answers`, `question_media`, `answer_media` هم پوشش کامل انواع سؤال هشت‌گانه و رسانه را در همان لایه نشان می‌دهند.

**معادل در `models_unified_postgres.py`:** `Question.QuestionType` گسترش‌یافته با `multi_select` و `ordering` (طبق تصمیم ۹.۵) درست است، و فیلد `payload (jsonb)` + `scenario_data (jsonb)` هم برای نگه‌داشتن ساختار متغیر گزینه‌ها در نظر گرفته شده. اما **فیلد `structure` (که مقدار `independent`/سناریوی بیمار/KFP/OSCE را نگه می‌دارد) در طراحی `models_unified_postgres.py` مدل‌سازی نشده** — فقط `scenario_data` جنریک وجود دارد بدون فیلد صریح enum برای نوع ساختار. **نیازمند تصمیم**، چون این دقیقاً یکی از الزامات صریح بریف فاز اول است.

### `student_groups`
**ستون‌ها (از `0014` + `0021`):** `id`, `teacher_id`, `course_id`, `course_name`, `academic_year`, `semester`, `group_code`, `description`, `is_active`, `created_by`، و از `0021`: `capacity`, `min_students`, `waitlist_enabled`, `waitlist_capacity`, `requires_teacher_approval`, `offering_type`, `class_schedule`, `class_location`, `registration_start_at`, `registration_end_at`, `status`.

**معادل ORM:** `apps.core.models.CourseClass` — فیلد `capacity` مشترک است اما `min_students`, `waitlist_enabled/capacity`, `requires_teacher_approval`, `offering_type`, `class_schedule/location`, `registration_start_at/end_at`, `status` **هیچ‌کدام در `CourseClass` فعلی نیستند.** در `models_unified_postgres.py` هم `CourseClass` بازطراحی‌شده این فیلدها را ندارد — همهٔ این ستون‌ها باید یا به `settings_payload`-مانند اضافه شوند یا به‌صراحت از فاز اول خارج اعلام شوند. **نیازمند تصمیم.**

### `exam_attempts`
**ستون‌ها:** `id`, `exam_id`, `student_id (FK→profiles، نه student_profiles!)`, `started_at`, `submitted_at`, `score`, `max_score`, `is_graded`, `status (in_progress/submitted/graded/expired)` (و بعد از `0015`: مقادیر status تغییر کرده — باید در فاز ۲ عملی چک شود).

**نکتهٔ ظریف:** `student_id` در این جدول به `profiles(id)` رفرنس می‌دهد، نه به `student_profiles(user_id)` — یعنی حتی در خودِ لایهٔ ERD هم رفرنس این جدول با جداول دیگر (`objections.student_id` هم همین‌طور) به جدول کاربر عمومی است نه پروفایل دانشجو. باید در مهاجرت دقت شود این FK درست به `StudentProfile` نگاشت شود (از طریق `profiles.id` → کاربر جنگو → `StudentProfile`)، نه مستقیم.

**معادل ORM:** `apps.core.models.StudentExamAttempt` (وضعیت‌های `NOT_STARTED/WAITING_PROCTOR/IN_PROGRESS/SUBMITTED/AUTO_SUBMITTED/BLOCKED` — کاملاً متفاوت با enum چهارحالتهٔ ERD). در `models_unified_postgres.py`، `StudentExamAttempt.Status` باز هم متفاوت است (`IN_PROGRESS/SUBMITTED/GRADED/VOIDED`) — یعنی **سه enum متفاوت برای همین یک مفهوم** در سه جا (ERD، ORM فعلی، ORM هدف پیشنهادی). این باید یک‌دست شود قبل از نوشتن اسکریپت مهاجرت فاز ۲، وگرنه نگاشت status اشتباه انجام می‌شود.

### `attempt_answers`
**ستون‌ها:** `id`, `attempt_id`, `question_id`, `answer (jsonb)`, `is_correct`, `points_awarded`, `needs_manual_grading`, `UNIQUE(attempt_id, question_id)`.

**معادل ORM:** `apps.core.models.StudentQuestionAnswer` — از نظر مفهومی نزدیک است (`answer_text`, `selected_options`, `uploaded_file`) اما ساختار متفاوت: ORM فعلی answer را در چند فیلد جدا نگه می‌دارد، ERD در یک ستون `answer (jsonb)` واحد. `models_unified_postgres.py` با `answer_payload (jsonb)` به سمت ساختار ERD نزدیک شده — این تغییر معماری (چند فیلد → یک jsonb) باید صراحتاً به‌عنوان یک تصمیم طراحی (نه صرفاً «افزودن») در فاز ۱ نقشه‌راه ثبت شود، چون قانون سخت‌گیرانهٔ شماره ۳ دستورکار می‌گوید در فاز افزودن نباید فیلد موجود حذف/rename شود — اگر `StudentQuestionAnswer.answer_text`/`selected_options` در آینده با `answer_payload` جایگزین شوند، این یک تغییر جدا و باید با تأیید صریح انجام شود، نه ضمنی داخل فاز «فقط افزودن».

### `academic_terms`
**ستون‌ها (از `0014` + `0017`):** `id`, `year`, `semester`, `label`, `is_current`، و از `0017`: `start_date`, `end_date`, `description`, `is_active`.

**معادل ORM:** `apps.core.models.AcademicTerm` (`title`, `year`, `starts_at`, `ends_at`, `is_active`) — نگاشت نسبتاً مستقیم است (`start_date`→`starts_at`, `end_date`→`ends_at`) با تفاوت نام. `is_current` (ERD) در برابر نبود معادل در ORM — ORM راهی برای علامت‌گذاری «ترم جاری/پیش‌فرض» ندارد، درحالی‌که بریف فاز اول صریحاً «تعیین ترم پیش‌فرض» را به‌عنوان الزام آورده بود. **نیازمند تصمیم / احتمالاً باید فیلد `is_current` هم به ORM اضافه شود در فاز ۱.**

### `system_settings`
**ستون‌ها:** `key (PK)`, `value (jsonb)`, `description`, `updated_by (FK→profiles)`.

**معادل ORM:** `apps.core.models.SystemSetting` **از قبل وجود دارد** (migration `0013_systemsetting`) با `key`, `value (JSONField)`, `description`, `updated_at`. تفاوت: ORM فیلد `updated_by` (چه کسی تنظیم را عوض کرد) ندارد. این نزدیک‌ترین مورد به «یکسان» در کل این نگاشت است — فقط یک ستون کم دارد.

---

## ۲. جدول‌های ERD که در پرامپت نام برده نشدند (یافتهٔ این مرحله)

| جدول | نقش | معادل ORM |
|------|-----|-----------|
| `admin_profiles` | پروفایل مدیر سیستم (`title`, `access_level`) | `SystemAdminProfile` (فیلدهای دیگری دارد: `can_manage_roles` و...، تطبیق یک‌به‌یک نیست) |
| `user_roles` | رابطهٔ چند-نقشی کاربر↔نقش (یک کاربر می‌تواند چند نقش داشته باشد) | **وجود ندارد** — `UserProfile.role` در ORM فقط تک-نقشی (`ForeignKey`) است، نه چندگانه. تناقض معماری مهم: اگر داده‌ی واقعی کاربرانی با بیش از یک نقش در `user_roles` دارد، مدل تک-نقشی ORM نمی‌تواند آن را نمایش دهد. |
| `notifications` | اعلان‌های کاربر | **وجود ندارد در ORM** |
| `activity_audit_log` | لاگ عمومی فعالیت با `entity_type`/`entity_id` (polymorphic) | نزدیک‌ترین معادل `UserActivityLog` است، اما آن `metadata` دارد نه `entity_type/entity_id` صریح |
| `courses` | درس (`title`, `code`, `org_unit_id`, `credit_units`) | `apps.core.models.Course` — نگاشت نسبتاً مستقیم |
| `question_sets` / `question_set_items` | مجموعهٔ سؤال قابل‌اشتراک بین استادان | **وجود ندارد در ORM** |
| `course_audit_log` | تاریخچهٔ تغییرات درس | **وجود ندارد در ORM** |
| `student_group_members` | عضویت دانشجو در گروه (با کپی `full_name`/`national_id` — غیرنرمال) | نزدیک به `CourseClass.students` (M2M) ولی بدون denormalization |
| `group_teachers` | چند-استاد-به-یک-گروه (M2M) | `CourseClass.teacher` در ORM فقط تک-استاد (ForeignKey) است — **تناقض کاردینالیتی** |
| `exam_assignments` | تخصیص آزمون به گروه یا دانشجوی خاص | **وجود ندارد در ORM** به این شکل صریح |
| `exam_questions` | رابطهٔ آزمون↔سؤال با نمره/ترتیب | `apps.core.models.ExamQuestion` — معادل مستقیم دارد ✅ |
| `objections` | اعتراض دانشجو | `apps.core.models.StudentObjection` — معادل مستقیم دارد ✅ |
| `student_course_enrollments` | ثبت‌نام دانشجو در درس (مستقل از گروه/کلاس) | **وجود ندارد در ORM** — در ORM ثبت‌نام فقط از طریق `CourseClass.students` (که به گروه/کلاس وابسته است) قابل بیان است، نه به‌صورت مستقیم دانشجو↔درس |

---

## نیازمند تصمیم (قبل از فاز ۱ نقشه‌راه)

این‌ها مواردی هستند که طبق قانون سخت‌گیرانهٔ شماره ۶ دستورکار («اگر تناقضی دیدی، متوقف شو و بپرس، حدس نزن») باید قبل از نوشتن اولین migration واقعی فاز ۱ روشن شوند:

1. **چندنقشی کاربر (`user_roles`):** آیا در داده‌ی واقعی کاربری با بیش از یک نقش وجود دارد؟ اگر بله، مدل تک-نقشی فعلی ORM (`UserProfile.role` تک FK) کافی نیست و باید قبل از مهاجرت گسترش یابد.
2. **`academic_manager_scopes` چند-واحدی:** آیا مدیری با بیش از یک ردیف در این جدول (یعنی دسترسی به چند زیردرخت ناهم‌بسته) در داده‌ی واقعی وجود دارد؟ اگر بله، طراحی تک-FK `ExamManagerProfile.managed_unit` در `models_unified_postgres.py` این حالت را نمی‌تواند نمایش دهد.
3. **`include_child_units` روی `academic_manager_profiles`:** آیا این پرچم در عمل جایی `false` ست شده (یعنی مدیری که عمداً به زیرشاخه‌ها دسترسی ندارد)؟ طراحی هدف فعلی این حالت را ندارد.
4. **فیلد `structure` روی `questions` (مستقل/سناریوی بیمار/KFP/OSCE):** آیا این باید به‌صورت enum صریح در ORM هدف هم بیاید (نه فقط `scenario_data` جنریک)؟ این مستقیماً به یکی از الزامات صریح بریف فاز اول برمی‌گردد.
5. **چند-استاد-به-گروه (`group_teachers`):** آیا واقعاً یک گروه می‌تواند چند استاد داشته باشد؟ اگر بله، `CourseClass.teacher` (تک FK در هر دو نسخهٔ ORM) کافی نیست.
6. **فیلدهای نظارتی آزمون (`fullscreen_required`, `track_tab_exit`, ...):** آیا این‌ها باید ستون‌های صریح ORM شوند یا در `settings_payload` عمومی بمانند؟ تصمیم روی قابلیت گزارش‌گیری/فیلتر آینده اثر می‌گذارد.
7. **enum وضعیت percobaan (`exam_attempts.status` / `StudentExamAttempt.Status`)**: سه نگارش متفاوت (ERD، ORM فعلی، ORM هدف) — کدام معیار نهایی است؟
8. **جدول‌های بدون معادل ORM که در بالا فهرست شدند** (`notifications`, `question_sets`, `course_audit_log`, `exam_assignments`, `student_course_enrollments`, ...): آیا این‌ها باید در فاز ۱ مدل‌سازی شوند، یا داده‌شان اصلاً استفاده نمی‌شود و می‌توان از مهاجرت‌شان صرف‌نظر کرد؟ (شمارش رکورد واقعی این جدول‌ها هنوز گرفته نشده — به بخش «قدم بعدی» مراجعه شود.)

## قدم بعدی (خارج از دامنهٔ این مرحلهٔ read-only)

طبق فاز ۰ نقشه‌راه (بند ۳: «شمارش و پروفایل داده»)، باید تعداد رکورد واقعی هر جدول ERD از دیتابیس در حال اجرا خوانده شود تا معلوم شود کدام جدول‌ها داده‌ی واقعی/تولیدی دارند و کدام خالی/تستی‌اند. این کار نیاز به اتصال به دیتابیس دارد (نه فقط خواندن کد migration) — طبق دستورکار، این را در گزارش پایان مرحلهٔ ۱ به‌عنوان یک قدم مجزا (و نه بخشی از خودِ مرحلهٔ ۱ envanتوری کد) پیشنهاد می‌کنم تا هم دیتابیس فعلی (که ممکن است SQLite dev باشد، نه Postgres واقعی) و هم نوع محیط (dev/staging/production) قبل از اجرا با شما تأیید شود.
