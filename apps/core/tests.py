import uuid

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.urls import reverse


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
