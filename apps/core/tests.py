import io
import uuid

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone


def _insert(table, columns, values):
    placeholders = ', '.join(['%s'] * len(values))
    column_list = ', '.join(columns)
    with connection.cursor() as cursor:
        cursor.execute(f'INSERT INTO {table} ({column_list}) VALUES ({placeholders})', values)


class _ScopedOrgFixture(TestCase):
    """فیکسچر مشترک: یک مدیر آموزشی با scope روی یک واحد سازمانی، به‌همراه استاد/دانشجوی داخل و خارج آن محدوده."""

    @classmethod
    def setUpTestData(cls):
        cls.ou_scoped = str(uuid.uuid4())
        cls.ou_other = str(uuid.uuid4())
        _insert('org_units', ['id', 'name', 'type'], [cls.ou_scoped, 'واحد تحت مدیریت', 'department'])
        _insert('org_units', ['id', 'name', 'type'], [cls.ou_other, 'واحد دیگر', 'department'])

        cls.manager_id = cls._make_profile('manager_test', 'مدیر آموزشی تست')
        _insert('academic_manager_profiles', ['user_id'], [cls.manager_id])
        _insert('academic_manager_scopes', ['id', 'manager_id', 'org_unit_id'],
                [str(uuid.uuid4()), cls.manager_id, cls.ou_scoped])
        _insert('user_roles', ['id', 'user_id', 'role'], [str(uuid.uuid4()), cls.manager_id, 'academic_manager'])

        cls.teacher_in_id = cls._make_profile('teacher_in_scope', 'استاد داخل محدوده')
        _insert('teacher_profiles', ['user_id', 'org_unit_id'], [cls.teacher_in_id, cls.ou_scoped])
        _insert('user_roles', ['id', 'user_id', 'role'], [str(uuid.uuid4()), cls.teacher_in_id, 'teacher'])

        cls.teacher_out_id = cls._make_profile('teacher_out_scope', 'استاد خارج محدوده')
        _insert('teacher_profiles', ['user_id', 'org_unit_id'], [cls.teacher_out_id, cls.ou_other])
        _insert('user_roles', ['id', 'user_id', 'role'], [str(uuid.uuid4()), cls.teacher_out_id, 'teacher'])

        cls.student_in_id = cls._make_profile('student_in_scope', 'دانشجوی داخل محدوده')
        _insert('student_profiles', ['user_id', 'org_unit_id'], [cls.student_in_id, cls.ou_scoped])
        _insert('user_roles', ['id', 'user_id', 'role'], [str(uuid.uuid4()), cls.student_in_id, 'student'])

        cls.student_out_id = cls._make_profile('student_out_scope', 'دانشجوی خارج محدوده')
        _insert('student_profiles', ['user_id', 'org_unit_id'], [cls.student_out_id, cls.ou_other])
        _insert('user_roles', ['id', 'user_id', 'role'], [str(uuid.uuid4()), cls.student_out_id, 'student'])

        cls.course_in_id = str(uuid.uuid4())
        _insert('courses', ['id', 'title', 'org_unit_id'], [cls.course_in_id, 'درس داخل محدوده', cls.ou_scoped])
        cls.course_out_id = str(uuid.uuid4())
        _insert('courses', ['id', 'title', 'org_unit_id'], [cls.course_out_id, 'درس خارج محدوده', cls.ou_other])

        cls.group_in_id = str(uuid.uuid4())
        _insert(
            'student_groups',
            ['id', 'teacher_id', 'course_id', 'course_name', 'academic_year'],
            [cls.group_in_id, cls.teacher_in_id, cls.course_in_id, 'درس داخل محدوده', '1403'],
        )
        cls.group_out_id = str(uuid.uuid4())
        _insert(
            'student_groups',
            ['id', 'teacher_id', 'course_id', 'course_name', 'academic_year'],
            [cls.group_out_id, cls.teacher_out_id, cls.course_out_id, 'درس خارج محدوده', '1403'],
        )

        now = timezone.now()
        cls.exam_in_id = str(uuid.uuid4())
        _insert('exams', ['id', 'title', 'teacher_id', 'course_id', 'start_at'], [cls.exam_in_id, 'آزمون داخل محدوده', cls.teacher_in_id, cls.course_in_id, now])
        cls.exam_out_id = str(uuid.uuid4())
        _insert('exams', ['id', 'title', 'teacher_id', 'course_id', 'start_at'], [cls.exam_out_id, 'آزمون خارج محدوده', cls.teacher_out_id, cls.course_out_id, now])

        cls.question_in_id = str(uuid.uuid4())
        _insert('questions', ['id', 'teacher_id', 'course_id', 'text', 'default_points'],
                [cls.question_in_id, cls.teacher_in_id, cls.course_in_id, 'سوال داخل محدوده', 2])
        cls.question_out_id = str(uuid.uuid4())
        _insert('questions', ['id', 'teacher_id', 'course_id', 'text', 'default_points'],
                [cls.question_out_id, cls.teacher_out_id, cls.course_out_id, 'سوال خارج محدوده', 2])

        cls.admin_id = cls._make_profile('admin_test', 'مدیر سیستم تست')
        _insert('user_roles', ['id', 'user_id', 'role'], [str(uuid.uuid4()), cls.admin_id, 'admin'])

        User = get_user_model()
        cls.manager_user = User.objects.create_user(username='manager_test', email='manager_test@example.com', password='x')
        cls.admin_user = User.objects.create_user(username='admin_test', email='admin_test@example.com', password='x')

    @staticmethod
    def _make_profile(username, full_name):
        profile_id = str(uuid.uuid4())
        _insert('profiles', ['id', 'full_name', 'username', 'email'], [profile_id, full_name, username, f'{username}@example.com'])
        return profile_id


class ExamManagerScopingTests(_ScopedOrgFixture):
    """
    مدیر آموزشی فقط باید اساتید و دانشجویانِ واحد سازمانیِ خودش را ببیند،
    نه همه‌ی کاربران سیستم را. این تست رگرسیون همان باگ دسترسی است که در
    exam_manager_users/courses/groups رفع شد.
    """

    def test_manager_sees_only_own_org_unit_users(self):
        self.client.force_login(self.manager_user)
        response = self.client.get(reverse('core:exam_manager_users'))
        self.assertEqual(response.status_code, 200)
        student_ids = {row['id'] for row in response.context['students']}
        teacher_ids = {row['id'] for row in response.context['teachers']}
        self.assertIn(self.student_in_id, student_ids)
        self.assertNotIn(self.student_out_id, student_ids)
        self.assertIn(self.teacher_in_id, teacher_ids)
        self.assertNotIn(self.teacher_out_id, teacher_ids)

    def test_manager_sees_only_own_org_unit_courses_and_groups(self):
        self.client.force_login(self.manager_user)
        courses_response = self.client.get(reverse('core:exam_manager_courses'))
        self.assertEqual(courses_response.status_code, 200)
        course_ids = {row['id'] for row in courses_response.context['rows']}
        self.assertIn(self.course_in_id, course_ids)
        self.assertNotIn(self.course_out_id, course_ids)

        groups_response = self.client.get(reverse('core:exam_manager_groups'))
        self.assertEqual(groups_response.status_code, 200)
        group_ids = {row['id'] for row in groups_response.context['rows']}
        self.assertIn(self.group_in_id, group_ids)
        self.assertNotIn(self.group_out_id, group_ids)

    def test_admin_still_sees_everyone_system_wide(self):
        self.client.force_login(self.admin_user)
        response = self.client.get(reverse('core:exam_manager_users'))
        self.assertEqual(response.status_code, 200)
        student_ids = {row['id'] for row in response.context['students']}
        teacher_ids = {row['id'] for row in response.context['teachers']}
        self.assertIn(self.student_in_id, student_ids)
        self.assertIn(self.student_out_id, student_ids)
        self.assertIn(self.teacher_in_id, teacher_ids)
        self.assertIn(self.teacher_out_id, teacher_ids)


class SuperAdminUsersUnificationTests(_ScopedOrgFixture):
    """
    صفحه‌ی کاربران مدیر آموزشی و مدیر سیستم اکنون یک صفحه‌ی مشترک است
    (super_admin_users) که فقط سطح دسترسی را بر اساس نقش محدود می‌کند:
    مدیر آموزشی فقط اساتید/دانشجویان واحد خودش را می‌بیند و تب «مدیران»
    و مدیریت سایر مدیران را ندارد؛ عملیات فعال/غیرفعال/حذف/پروفایل هم
    سمت سرور به همین محدوده گیت شده‌اند، نه فقط در UI.
    """

    def test_exam_manager_and_super_admin_urls_show_identical_scoped_content(self):
        self.client.force_login(self.manager_user)
        for url_name in ('core:exam_manager_users', 'core:super_admin_users'):
            response = self.client.get(reverse(url_name))
            self.assertEqual(response.status_code, 200)
            student_ids = {row['id'] for row in response.context['students']}
            teacher_ids = {row['id'] for row in response.context['teachers']}
            self.assertIn(self.student_in_id, student_ids)
            self.assertNotIn(self.student_out_id, student_ids)
            self.assertIn(self.teacher_in_id, teacher_ids)
            self.assertNotIn(self.teacher_out_id, teacher_ids)

    def test_manager_cannot_see_or_manage_other_managers(self):
        self.client.force_login(self.manager_user)
        response = self.client.get(reverse('core:super_admin_users'), {'tab': 'managers'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['active_tab'], 'students')
        self.assertEqual(list(response.context['managers']), [])

        save_response = self.client.post(reverse('core:super_admin_users'), {'admin_action': 'save', 'full_name': 'نفوذی'})
        self.assertEqual(save_response.status_code, 403)

    def test_manager_blocked_from_mutating_out_of_scope_accounts(self):
        self.client.force_login(self.manager_user)
        toggle_url = reverse('core:super_admin_toggle_account_status', args=['student', self.student_out_id])
        self.assertEqual(self.client.post(toggle_url, {'action': 'deactivate'}).status_code, 403)

        delete_url = reverse('core:super_admin_delete_account', args=['teacher', self.teacher_out_id])
        self.assertEqual(self.client.post(delete_url, {}).status_code, 403)

        manager_toggle_url = reverse('core:super_admin_toggle_account_status', args=['manager', self.admin_id])
        self.assertEqual(self.client.post(manager_toggle_url, {'action': 'deactivate'}).status_code, 403)

        profile_url = reverse('core:super_admin_user_profile', args=['student', self.student_out_id])
        self.assertEqual(self.client.get(profile_url).status_code, 404)

        manager_profile_url = reverse('core:super_admin_user_profile', args=['manager', self.admin_id])
        self.assertEqual(self.client.get(manager_profile_url).status_code, 404)

    def test_manager_can_mutate_and_view_in_scope_accounts(self):
        self.client.force_login(self.manager_user)
        toggle_url = reverse('core:super_admin_toggle_account_status', args=['student', self.student_in_id])
        response = self.client.post(toggle_url, {'action': 'deactivate'}, follow=True)
        self.assertEqual(response.status_code, 200)

        profile_url = reverse('core:super_admin_user_profile', args=['student', self.student_in_id])
        self.assertEqual(self.client.get(profile_url).status_code, 200)


class SuperAdminCoursesUnificationTests(_ScopedOrgFixture):
    """
    صفحه‌ی درس‌های مدیر آموزشی و مدیر سیستم هم اکنون یک صفحه‌ی مشترک است
    (super_admin_courses/super_admin_course_form). قبلاً exam_manager_courses
    به‌اشتباه لیست گروه‌ها را نشان می‌داد، نه لیست درس‌ها؛ این هم در همین
    یکسان‌سازی رفع شد.
    """

    def test_exam_manager_and_super_admin_course_urls_show_identical_scoped_content(self):
        self.client.force_login(self.manager_user)
        for url_name in ('core:exam_manager_courses', 'core:super_admin_courses'):
            response = self.client.get(reverse(url_name))
            self.assertEqual(response.status_code, 200)
            course_ids = {row['id'] for row in response.context['rows']}
            self.assertIn(self.course_in_id, course_ids)
            self.assertNotIn(self.course_out_id, course_ids)

    def test_manager_blocked_from_mutating_out_of_scope_course(self):
        self.client.force_login(self.manager_user)
        courses_url = reverse('core:super_admin_courses')

        delete_response = self.client.post(courses_url, {'course_action': 'delete', 'course_id': self.course_out_id})
        self.assertEqual(delete_response.status_code, 403)

        save_response = self.client.post(courses_url, {
            'course_action': 'save',
            'course_id': self.course_out_id,
            'title': 'دستکاری',
            'department_id': self.ou_scoped,
        })
        self.assertEqual(save_response.status_code, 403)

        hijack_response = self.client.post(courses_url, {
            'course_action': 'save',
            'title': 'درس جدید با واحد غیرمجاز',
            'department_id': self.ou_other,
        })
        self.assertEqual(hijack_response.status_code, 403)

    def test_manager_can_manage_in_scope_course(self):
        self.client.force_login(self.manager_user)
        courses_url = reverse('core:super_admin_courses')
        response = self.client.post(courses_url, {
            'course_action': 'save',
            'title': 'درس جدید داخل محدوده',
            'department_id': self.ou_scoped,
        })
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['ok'])


class SuperAdminGroupsUnificationTests(_ScopedOrgFixture):
    """
    صفحه‌ی گروه‌بندی مدیر آموزشی و مدیر سیستم هم اکنون یک صفحه‌ی مشترک
    است (super_admin_groups/super_admin_group_create/super_admin_group_edit).
    """

    def test_exam_manager_and_super_admin_group_urls_show_identical_scoped_content(self):
        self.client.force_login(self.manager_user)
        for url_name in ('core:exam_manager_groups', 'core:super_admin_groups'):
            response = self.client.get(reverse(url_name))
            self.assertEqual(response.status_code, 200)
            group_ids = {row['id'] for row in response.context['rows']}
            self.assertIn(self.group_in_id, group_ids)
            self.assertNotIn(self.group_out_id, group_ids)

    def test_manager_cannot_view_or_edit_out_of_scope_group(self):
        self.client.force_login(self.manager_user)
        edit_url = reverse('core:super_admin_group_edit', args=[self.group_out_id])
        self.assertEqual(self.client.get(edit_url).status_code, 404)

        detail_url = reverse('core:exam_manager_group_detail', args=[self.group_out_id])
        self.assertEqual(self.client.get(detail_url).status_code, 404)

    def test_manager_blocked_from_assigning_out_of_scope_course_or_teacher(self):
        self.client.force_login(self.manager_user)
        groups_url = reverse('core:super_admin_groups')

        delete_response = self.client.post(groups_url, {'group_action': 'delete', 'group_id': self.group_out_id})
        self.assertEqual(delete_response.status_code, 403)

        hijack_response = self.client.post(groups_url, {
            'group_action': 'save',
            'course_id': self.course_out_id,
            'teacher_id': self.teacher_out_id,
            'course_name': 'گروه نفوذی',
        })
        self.assertEqual(hijack_response.status_code, 403)

        edit_response = self.client.post(reverse('core:super_admin_group_edit', args=[self.group_in_id]), {
            'course_id': self.course_out_id,
            'teacher_ids': [self.teacher_out_id],
        })
        self.assertEqual(edit_response.status_code, 403)

    def test_manager_can_manage_in_scope_group(self):
        self.client.force_login(self.manager_user)
        groups_url = reverse('core:super_admin_groups')
        response = self.client.post(groups_url, {
            'group_action': 'save',
            'course_id': self.course_in_id,
            'teacher_id': self.teacher_in_id,
            'course_name': 'گروه جدید داخل محدوده',
        }, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['ok'])


class SuperAdminExamsUnificationTests(_ScopedOrgFixture):
    """
    صفحه‌ی آزمون‌های مدیر آموزشی و مدیر سیستم هم اکنون یک صفحه‌ی مشترک
    است (super_admin_exams/super_admin_exam_detail/super_admin_exam_edit).
    این تست همچنین حفره‌ی scope مستقلی را پوشش می‌دهد که در _em_exam_rows
    پیدا شد: قبلاً هر مدیر آموزشی همه‌ی آزمون‌های کل سیستم را می‌دید.
    """

    def test_exam_manager_and_super_admin_exam_urls_show_identical_scoped_content(self):
        self.client.force_login(self.manager_user)
        for url_name in ('core:exam_manager_exams', 'core:super_admin_exams'):
            response = self.client.get(reverse(url_name))
            self.assertEqual(response.status_code, 200)
            exam_ids = {row['id'] for row in response.context['rows']}
            self.assertIn(self.exam_in_id, exam_ids)
            self.assertNotIn(self.exam_out_id, exam_ids)

    def test_admin_still_sees_every_exam(self):
        self.client.force_login(self.admin_user)
        response = self.client.get(reverse('core:super_admin_exams'))
        exam_ids = {row['id'] for row in response.context['rows']}
        self.assertIn(self.exam_in_id, exam_ids)
        self.assertIn(self.exam_out_id, exam_ids)

    def test_manager_cannot_view_out_of_scope_exam(self):
        self.client.force_login(self.manager_user)
        self.assertEqual(self.client.get(reverse('core:super_admin_exam_detail', args=[self.exam_out_id])).status_code, 404)
        self.assertEqual(self.client.get(reverse('core:super_admin_exam_edit', args=[self.exam_out_id])).status_code, 404)
        self.assertEqual(self.client.get(reverse('core:exam_manager_exam_questions', args=[self.exam_out_id])).status_code, 404)

    def test_manager_can_view_in_scope_exam(self):
        self.client.force_login(self.manager_user)
        self.assertEqual(self.client.get(reverse('core:super_admin_exam_detail', args=[self.exam_in_id])).status_code, 200)
        self.assertEqual(self.client.get(reverse('core:super_admin_exam_edit', args=[self.exam_in_id])).status_code, 200)

    def test_manager_blocked_from_creating_exam_with_out_of_scope_group(self):
        self.client.force_login(self.manager_user)
        response = self.client.post(reverse('core:super_admin_exams'), {
            'exam_action': 'create',
            'group_id': self.group_out_id,
            'title': 'آزمون نفوذی',
        })
        self.assertEqual(response.status_code, 403)


class SuperAdminCalendarUnificationTests(_ScopedOrgFixture):
    """
    تقویم مدیر آموزشی و مدیر سیستم هم اکنون یک صفحه‌ی مشترک است
    (super_admin_calendar) که از تبدیل واقعی میلادی-به-جلالی استفاده
    می‌کند، نه محاسبه‌ی جعلی/هاردکد قبلی exam_manager (`is_today = day
    == 25` و ...). این هم اکنون حفره‌ی scope مستقل _em_calendar_rows را
    پوشش می‌دهد: قبلاً تقویم مدیر آموزشی همه‌ی آزمون‌ها و رویدادهای
    تقویمی کل سیستم را نشان می‌داد.
    """

    def test_exam_manager_and_super_admin_calendar_urls_show_identical_scoped_content(self):
        self.client.force_login(self.manager_user)
        for url_name in ('core:exam_manager_calendar', 'core:super_admin_calendar'):
            response = self.client.get(reverse(url_name))
            self.assertEqual(response.status_code, 200)
            event_ids = {event['id'] for event in response.context['events']}
            self.assertIn(self.exam_in_id, event_ids)
            self.assertNotIn(self.exam_out_id, event_ids)

    def test_admin_calendar_shows_every_exam(self):
        self.client.force_login(self.admin_user)
        response = self.client.get(reverse('core:super_admin_calendar'))
        event_ids = {event['id'] for event in response.context['events']}
        self.assertIn(self.exam_in_id, event_ids)
        self.assertIn(self.exam_out_id, event_ids)


class SuperAdminExamBulkImportScopeTests(_ScopedOrgFixture):
    """
    ویزارد ورود گروهی آزمون قبلاً کد درس/استاد/گروه را در کل سیستم
    تطبیق می‌داد (بدون scope) و برای هیچ نقشی جز admin در دسترس نبود.
    این تست تایید می‌کند مدیر آموزشی هم اکنون به آن دسترسی دارد، اما
    فقط می‌تواند به درس/استاد داخل محدوده‌ی خودش وصل شود.
    """

    def _set_draft(self, rows):
        session = self.client.session
        session['super_admin_exam_bulk_import'] = {
            'step': 3,
            'headers': list(rows[0].keys()),
            'rows': rows,
            'mapping': {
                'title': 'title', 'course_code': 'course_code', 'teacher_code': 'teacher_code',
                'group_code': 'group_code', 'date': 'date', 'start_time': 'start_time',
                'duration': 'duration', 'passing_score': 'passing_score',
            },
        }
        session.save()

    def test_manager_can_reach_wizard(self):
        self.client.force_login(self.manager_user)
        self.assertEqual(self.client.get(reverse('core:super_admin_exam_bulk_import')).status_code, 200)

    def test_manager_row_matching_in_scope_course_and_teacher_resolves_ok(self):
        self.client.force_login(self.manager_user)
        self._set_draft([{
            'title': 'آزمون وارداتی', 'course_code': 'درس داخل محدوده', 'teacher_code': 'استاد داخل محدوده',
            'group_code': '01', 'date': '1404/03/25', 'start_time': '09:00', 'duration': '90', 'passing_score': '10',
        }])
        response = self.client.get(reverse('core:super_admin_exam_bulk_import'), {'step': 3})
        record = response.context['records'][0]
        self.assertIn(record['level'], {'ok', 'warning'})
        self.assertEqual(record['course_id'], self.course_in_id)
        self.assertEqual(record['teacher_id'], self.teacher_in_id)

    def test_manager_row_matching_out_of_scope_course_and_teacher_fails(self):
        self.client.force_login(self.manager_user)
        self._set_draft([{
            'title': 'آزمون نفوذی', 'course_code': 'درس خارج محدوده', 'teacher_code': 'استاد خارج محدوده',
            'group_code': '01', 'date': '1404/03/25', 'start_time': '09:00', 'duration': '90', 'passing_score': '10',
        }])
        response = self.client.get(reverse('core:super_admin_exam_bulk_import'), {'step': 3})
        record = response.context['records'][0]
        self.assertEqual(record['level'], 'error')
        self.assertIn('کد درس در سامانه پیدا نشد.', record['issues'])
        self.assertIn('کد استاد در سامانه پیدا نشد.', record['issues'])
        self.assertEqual(record['course_id'], '')
        self.assertEqual(record['teacher_id'], '')

    def test_admin_row_matching_out_of_scope_course_and_teacher_resolves_ok(self):
        self.client.force_login(self.admin_user)
        self._set_draft([{
            'title': 'آزمون سراسری', 'course_code': 'درس خارج محدوده', 'teacher_code': 'استاد خارج محدوده',
            'group_code': '01', 'date': '1404/03/25', 'start_time': '09:00', 'duration': '90', 'passing_score': '10',
        }])
        response = self.client.get(reverse('core:super_admin_exam_bulk_import'), {'step': 3})
        record = response.context['records'][0]
        self.assertIn(record['level'], {'ok', 'warning'})
        self.assertEqual(record['course_id'], self.course_out_id)
        self.assertEqual(record['teacher_id'], self.teacher_out_id)


class SuperAdminExamWizardTests(_ScopedOrgFixture):
    """
    ویزارد ۷ مرحله‌ای ایجاد آزمون: منابع (درس/استاد/دانشجو/گروه/سوال) باید
    برای مدیر آموزشی scope شوند و ثبت نهایی هم سمت سرور دوباره بررسی شود،
    نه فقط مخفی‌کردن گزینه‌های خارج از محدوده در فرم.
    """

    def _base_payload(self, **overrides):
        payload = {
            'title': 'آزمون تست',
            'course_id': self.course_in_id,
            'teacher_id': self.teacher_in_id,
            'group_ids': [self.group_in_id],
            'question_ids': [self.question_in_id],
            'duration_minutes': '90',
            'start_at': '2026-09-10T09:00',
            'publish_choice': 'draft',
        }
        payload.update(overrides)
        return payload

    def test_manager_sees_only_in_scope_resources_on_get(self):
        self.client.force_login(self.manager_user)
        response = self.client.get(reverse('core:super_admin_exam_create'))
        self.assertEqual(response.status_code, 200)
        course_ids = {c['id'] for c in response.context['courses']}
        teacher_ids = {t['id'] for t in response.context['teachers']}
        question_ids = {q['id'] for q in response.context['questions']}
        group_ids = {g['id'] for g in response.context['groups']}
        self.assertIn(self.course_in_id, course_ids)
        self.assertNotIn(self.course_out_id, course_ids)
        self.assertIn(self.teacher_in_id, teacher_ids)
        self.assertNotIn(self.teacher_out_id, teacher_ids)
        self.assertIn(self.question_in_id, question_ids)
        self.assertNotIn(self.question_out_id, question_ids)
        self.assertIn(self.group_in_id, group_ids)
        self.assertNotIn(self.group_out_id, group_ids)

    def test_manager_can_create_exam_with_in_scope_resources_and_staff(self):
        self.client.force_login(self.manager_user)
        payload = self._base_payload(staff_teacher_id=[self.teacher_in_id], staff_role=['designer'])
        response = self.client.post(reverse('core:super_admin_exam_create'), payload, follow=True)
        self.assertEqual(response.status_code, 200)
        with connection.cursor() as cursor:
            cursor.execute("SELECT id, security_level, execution_mode, exam_mode FROM exams WHERE title = 'آزمون تست'")
            row = cursor.fetchone()
        self.assertIsNotNone(row)
        exam_id, security_level, execution_mode, exam_mode = row
        self.assertEqual(security_level, 'medium')
        self.assertEqual(execution_mode, 'web')
        self.assertEqual(exam_mode, 'standard')
        with connection.cursor() as cursor:
            cursor.execute('SELECT teacher_id, role FROM exam_staff WHERE exam_id = %s', [exam_id])
            staff_rows = cursor.fetchall()
        self.assertEqual(staff_rows, [(self.teacher_in_id, 'designer')])

    def test_manager_blocked_from_using_out_of_scope_course(self):
        self.client.force_login(self.manager_user)
        payload = self._base_payload(course_id=self.course_out_id)
        response = self.client.post(reverse('core:super_admin_exam_create'), payload)
        self.assertEqual(response.status_code, 403)

    def test_manager_blocked_from_using_out_of_scope_question(self):
        self.client.force_login(self.manager_user)
        payload = self._base_payload(question_ids=[self.question_out_id])
        response = self.client.post(reverse('core:super_admin_exam_create'), payload)
        self.assertEqual(response.status_code, 403)

    def test_manager_blocked_from_assigning_out_of_scope_staff(self):
        self.client.force_login(self.manager_user)
        payload = self._base_payload(staff_teacher_id=[self.teacher_out_id], staff_role=['observer'])
        response = self.client.post(reverse('core:super_admin_exam_create'), payload)
        self.assertEqual(response.status_code, 403)

    def test_admin_sees_all_resources_and_can_use_any(self):
        self.client.force_login(self.admin_user)
        response = self.client.get(reverse('core:super_admin_exam_create'))
        course_ids = {c['id'] for c in response.context['courses']}
        self.assertIn(self.course_in_id, course_ids)
        self.assertIn(self.course_out_id, course_ids)
        payload = self._base_payload(title='آزمون ادمین', course_id=self.course_out_id, teacher_id=self.teacher_out_id, question_ids=[self.question_out_id])
        response = self.client.post(reverse('core:super_admin_exam_create'), payload, follow=True)
        self.assertEqual(response.status_code, 200)
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM exams WHERE title = 'آزمون ادمین'")
            self.assertIsNotNone(cursor.fetchone())


class SuperAdminExamParticipantsMatchTests(_ScopedOrgFixture):
    """تطبیق فایل مخاطبان آزمون هم باید مثل تطبیق دانشجویان bulk-import محدود به scope مدیر باشد."""

    NID_IN = 'NID-IN-001'
    NID_OUT = 'NID-OUT-002'

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        with connection.cursor() as cursor:
            cursor.execute('UPDATE profiles SET national_id = %s WHERE id = %s', [cls.NID_IN, cls.student_in_id])
            cursor.execute('UPDATE profiles SET national_id = %s WHERE id = %s', [cls.NID_OUT, cls.student_out_id])

    def _upload_csv(self, url, identifier):
        content = f'کد ملی یا شماره دانشجویی\n{identifier}\n'.encode('utf-8-sig')
        upload = io.BytesIO(content)
        upload.name = 'participants.csv'
        return self.client.post(url, {'excel_file': upload})

    def test_manager_can_match_in_scope_student(self):
        self.client.force_login(self.manager_user)
        response = self._upload_csv(reverse('core:super_admin_exam_participants_match'), self.NID_IN)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data['found']), 1)
        self.assertEqual(data['found'][0]['id'], self.student_in_id)

    def test_manager_cannot_match_out_of_scope_student(self):
        self.client.force_login(self.manager_user)
        response = self._upload_csv(reverse('core:super_admin_exam_participants_match'), self.NID_OUT)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data['found']), 0)
        self.assertEqual(data['not_found'], [self.NID_OUT])

    def test_admin_can_match_any_student(self):
        self.client.force_login(self.admin_user)
        response = self._upload_csv(reverse('core:super_admin_exam_participants_match'), self.NID_OUT)
        data = response.json()
        self.assertEqual(len(data['found']), 1)
        self.assertEqual(data['found'][0]['id'], self.student_out_id)
