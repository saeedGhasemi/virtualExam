import io
import json
import random
import re
import tempfile
import uuid
from datetime import datetime, timedelta
from decimal import Decimal

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
        cls.question_in2_id = str(uuid.uuid4())
        _insert('questions', ['id', 'teacher_id', 'course_id', 'text', 'default_points'],
                [cls.question_in2_id, cls.teacher_in_id, cls.course_in_id, 'آ - سوال دوم داخل محدوده', 3])
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

    def test_scheduled_publish_waits_for_its_time(self):
        from django.core.management import call_command
        from apps.core.exam_schedule import publish_due_exams
        self.client.force_login(self.admin_user)
        url = reverse('core:super_admin_exam_create')
        response = self.client.post(url, self._base_payload(title='بدون زمان', publish_choice='scheduled'), follow=True)
        self.assertContains(response, 'زمان انتشار باید در آینده باشد؛ آزمون به‌صورت پیش‌نویس ذخیره شد.')
        later = (timezone.localtime() + timedelta(hours=2)).strftime('%Y-%m-%dT%H:%M')
        self.client.post(url, self._base_payload(publish_choice='scheduled', scheduled_publish_at=later))
        state = "SELECT lifecycle_status, approval_status, is_published FROM exams WHERE title = %s"
        with connection.cursor() as cursor:
            cursor.execute(state, ['بدون زمان'])
            self.assertEqual(cursor.fetchone(), ('draft', 'pending', False))
            cursor.execute(state, ['آزمون تست'])
            self.assertEqual(cursor.fetchone(), ('approved', 'approved', False))
        self.assertEqual(publish_due_exams(), [])  # not yet
        call_command('publish_scheduled_exams', stdout=io.StringIO())
        self.assertEqual([row['title'] for row in publish_due_exams(timezone.now() + timedelta(hours=3))], ['آزمون تست'])
        with connection.cursor() as cursor:
            cursor.execute(state, ['آزمون تست'])
            self.assertEqual(cursor.fetchone(), ('published', 'approved', True))

    def test_a_question_serves_practice_or_course_exams_not_both(self):
        _insert('exam_questions', ['id', 'exam_id', 'question_id', 'points', 'order_index'], [str(uuid.uuid4()), self.exam_in_id, self.question_in_id, 1, 1])
        self.client.force_login(self.admin_user)
        response = self.client.post(reverse('core:super_admin_exam_create'), self._base_payload(exam_mode='practice'), follow=True)
        self.assertContains(response, 'سؤال انتخاب‌شده در آزمون درسی هم آمده است')
        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM exams WHERE title = 'آزمون تست'")
            self.assertEqual(cursor.fetchone()[0], 0)
        self.client.post(reverse('core:super_admin_exam_create'), self._base_payload())  # another course exam may reuse it
        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM exams WHERE title = 'آزمون تست'")
            self.assertEqual(cursor.fetchone()[0], 1)

    def test_manager_question_picker_keeps_to_own_units(self):
        self.client.force_login(self.manager_user)
        url = reverse('core:exam_manager_exam_questions', args=[self.exam_in_id])
        self.assertEqual(self.client.post(url, {'question_ids': [self.question_out_id]}).status_code, 403)
        self.assertEqual(self.client.post(url, {'question_ids': [self.question_in_id]}).status_code, 302)

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
            staff_rows = [(str(teacher_id), role) for teacher_id, role in cursor.fetchall()]
        self.assertEqual(staff_rows, [(self.teacher_in_id, 'designer')])

    def test_exam_questions_preserve_submitted_order_not_alphabetical(self):
        """
        ترتیب چینش سوالات (drag-reorder در ویزارد) باید همان ترتیبی باشد که کاربر
        submit کرده، نه ترتیب الفبایی متن سوال - چون قبلاً کوئری با ORDER BY text
        این ترتیب را نادیده می‌گرفت.
        """
        self.client.force_login(self.manager_user)
        payload = self._base_payload(question_ids=[self.question_in_id, self.question_in2_id])
        response = self.client.post(reverse('core:super_admin_exam_create'), payload, follow=True)
        self.assertEqual(response.status_code, 200)
        with connection.cursor() as cursor:
            cursor.execute("SELECT id FROM exams WHERE title = 'آزمون تست'")
            exam_id = cursor.fetchone()[0]
            cursor.execute('SELECT question_id FROM exam_questions WHERE exam_id = %s ORDER BY order_index', [exam_id])
            ordered_question_ids = [str(row[0]) for row in cursor.fetchall()]
        self.assertEqual(ordered_question_ids, [self.question_in_id, self.question_in2_id])

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

    def test_manager_blocked_from_assigning_out_of_scope_group_or_student(self):
        self.client.force_login(self.manager_user)
        for payload in (
            self._base_payload(group_ids=[self.group_in_id, self.group_out_id]),
            self._base_payload(group_ids=[], student_ids=[self.student_out_id]),
            self._base_payload(excluded_student_ids=[self.student_out_id]),
        ):
            response = self.client.post(reverse('core:super_admin_exam_create'), payload)
            self.assertEqual(response.status_code, 403)
        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM exams WHERE title = 'آزمون تست'")
            self.assertEqual(cursor.fetchone()[0], 0)

    def test_manager_can_assign_in_scope_student_directly(self):
        self.client.force_login(self.manager_user)
        payload = self._base_payload(group_ids=[], student_ids=[self.student_in_id])
        response = self.client.post(reverse('core:super_admin_exam_create'), payload)
        self.assertEqual(response.status_code, 302)

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


class TeacherQuestionBuilderTests(_ScopedOrgFixture):
    """
    فرم ایجاد/ویرایش سؤال استاد: قبلاً داده‌ی پاسخ از فیلدهای مخفیِ هاردکد
    (seed) ارسال می‌شد، course_id اصلاً ذخیره نمی‌شد، و صفحه‌ی ویرایش یک
    ماکاپ بی‌عملکرد بود. این تست‌ها ذخیره‌ی واقعی، اعتبارسنجی سمت سرور،
    محدودیت درس و مالکیت سؤال در ویرایش را پوشش می‌دهند.
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        User = get_user_model()
        cls.teacher_user = User.objects.create_user(username='teacher_in_scope', email='t_in@example.com', password='x')
        cls.other_teacher_user = User.objects.create_user(username='teacher_out_scope', email='t_out@example.com', password='x')

    def _create(self, qtype, data):
        url = f"{reverse('core:teacher_question_create')}?type={qtype}"
        payload = {'type': qtype, 'structure': 'independent', 'course_id': self.course_in_id, 'is_published': '1'}
        payload.update(data)
        return self.client.post(url, payload)

    def _row(self, text):
        with connection.cursor() as cursor:
            cursor.execute(
                'SELECT id, type, course_id, options, correct_answer, matching_pairs, ordering_items, teacher_id FROM questions WHERE text = %s',
                [text],
            )
            return cursor.fetchone()

    def test_matching_question_saves_real_pairs_and_course(self):
        self.client.force_login(self.teacher_user)
        response = self._create('matching', {
            'text': 'سوال تطبیقی تست',
            'matching_left': ['الف۱', 'الف۲'],
            'matching_right': ['ب۱', 'ب۲'],
        })
        self.assertEqual(response.status_code, 302)
        row = self._row('سوال تطبیقی تست')
        self.assertIsNotNone(row)
        self.assertEqual(row[1], 'matching')
        self.assertEqual(str(row[2]), self.course_in_id)
        pairs = json.loads(row[5])
        self.assertEqual([(p['left'], p['right']) for p in pairs], [('الف۱', 'ب۱'), ('الف۲', 'ب۲')])

    def test_study_resource_is_saved_only_with_a_web_link(self):
        self.client.force_login(self.teacher_user)
        base = {'matching_left': ['الف۱', 'الف۲'], 'matching_right': ['ب۱', 'ب۲']}
        for url in ('javascript:alert(1)', 'ftp://example.com/x'):
            response = self._create('matching', {**base, 'text': 'سوال با منبع نامعتبر', 'resource_title': 'منبع', 'resource_url': url})
            self.assertEqual(response.status_code, 200, url)
            self.assertContains(response, 'لینک منبع مطالعه معتبر نیست')
            self.assertIsNone(self._row('سوال با منبع نامعتبر'))
        response = self._create('matching', {**base, 'text': 'سوال با منبع', 'resource_title': 'مرور مبحث ایمنی دارویی',
                                             'resource_url': 'https://example.com/drug-safety'})
        self.assertEqual(response.status_code, 302)
        with connection.cursor() as cursor:
            cursor.execute('SELECT feedback FROM questions WHERE text = %s', ['سوال با منبع'])
            feedback = json.loads(cursor.fetchone()[0])
        self.assertEqual((feedback['resource_title'], feedback['resource_url']), ('مرور مبحث ایمنی دارویی', 'https://example.com/drug-safety'))

    def test_fill_blank_saves_typed_alternatives_per_blank(self):
        self.client.force_login(self.teacher_user)
        text = 'جمجمه از [۱] و [۲] تشکیل شده است.'
        response = self._create('fill_blank', {
            'text': text,
            'blank_count': '2',
            'blank_answers_1': 'نوروکرانیوم، neurocranium',
            'blank_points_1': '2',
            'blank_answers_2': 'ویسروکرانیوم',
            'blank_spaces_2': '1',
        })
        self.assertEqual(response.status_code, 302)
        row = self._row(text)
        self.assertEqual(json.loads(row[4]), 'نوروکرانیوم|ویسروکرانیوم')
        self.assertEqual(json.loads(row[3]), [])
        with connection.cursor() as cursor:
            cursor.execute('SELECT accepted_answers FROM questions WHERE id = %s', [row[0]])
            blanks = json.loads(cursor.fetchone()[0])
        self.assertEqual(blanks[0]['answers'], ['نوروکرانیوم', 'neurocranium'])
        self.assertEqual(blanks[0]['points'], 2)
        self.assertTrue(blanks[1]['ignore_spaces'])

    def test_scoring_settings_are_saved(self):
        self.client.force_login(self.teacher_user)
        response = self._create('multi', {
            'text': 'چندپاسخی با تنظیمات',
            'option_text': ['الف', 'ب', 'ج', 'د'],
            'correct_options': ['1', '2'],
            'scoring_mode': 'partial',
            'min_correct': '1',
            'max_correct': '3',
            'floor_zero': '1',
            'negative_marking': '1',
            'negative_value': '۰.۲۵',
            'shuffle_options': '1',
        })
        self.assertEqual(response.status_code, 302)
        with connection.cursor() as cursor:
            cursor.execute('SELECT scoring_settings, negative_points FROM questions WHERE text = %s', ['چندپاسخی با تنظیمات'])
            settings_json, negative_points = cursor.fetchone()
        settings_data = json.loads(settings_json)
        self.assertEqual(settings_data['scoring_mode'], 'partial')
        self.assertEqual(settings_data['max_correct'], 3)
        self.assertTrue(settings_data['shuffle_options'])
        self.assertEqual(settings_data['negative_value'], 0.25)
        self.assertEqual(float(negative_points), -0.25)

    def test_multi_max_selection_must_cover_correct_options(self):
        self.client.force_login(self.teacher_user)
        response = self._create('multi', {
            'text': 'چندپاسخی ناسازگار',
            'option_text': ['الف', 'ب', 'ج'],
            'correct_options': ['1', '2', '3'],
            'max_correct': '2',
        })
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(self._row('چندپاسخی ناسازگار'))

    def test_multi_form_layout_and_all_or_nothing_choice(self):
        self.client.force_login(self.teacher_user)
        page = self.client.get(f"{reverse('core:teacher_question_create')}?type=multi")
        self.assertContains(page, 'class="qb qb--mc qb--v2"')
        self.assertContains(page, 'name="scoring_mode" value="all_or_nothing"')
        self.assertNotContains(page, '<select data-template-select>')  # template pills replace the side select
        self.assertContains(page, 'data-penalty-all')
        response = self._create('multi', {
            'text': 'چندپاسخی همه یا هیچ', 'option_text': ['الف', 'ب', 'ج'], 'correct_options': ['1', '2'],
            'scoring_mode': 'all_or_nothing', 'min_correct': '1', 'max_correct': '3',
        })
        self.assertEqual(response.status_code, 302)
        with connection.cursor() as cursor:
            cursor.execute("SELECT scoring_settings FROM questions WHERE text = %s", ['چندپاسخی همه یا هیچ'])
            self.assertEqual(json.loads(cursor.fetchone()[0])['scoring_mode'], 'all_or_nothing')

    def test_short_answer_invalid_regex_is_rejected(self):
        self.client.force_login(self.teacher_user)
        response = self._create('short_answer', {'text': 'regex نامعتبر', 'accepted_answer': ['(abc'], 'accepted_mode_1': 'regex'})
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(self._row('regex نامعتبر'))

    def test_short_answer_saves_typo_word_order_and_scoring_settings(self):
        self.client.force_login(self.teacher_user)
        response = self._create('short_answer', {
            'text': 'پاسخ کوتاه با قواعد جدید',
            'accepted_answer': ['گاستریت هلیکوباکتر', 'H. pylori gastritis'],
            'accepted_points_1': '100', 'accepted_mode_1': 'exact', 'accepted_typo_1': '1', 'accepted_word_order_1': '1',
            'accepted_points_2': '50', 'accepted_mode_2': 'contains', 'accepted_typo_2': '9',
            'scoring_mode': ['all_or_nothing', 'partial'],
            'correct_threshold': '50',
        })
        self.assertEqual(response.status_code, 302)
        with connection.cursor() as cursor:
            cursor.execute('SELECT accepted_answers, scoring_settings FROM questions WHERE text = %s', ['پاسخ کوتاه با قواعد جدید'])
            accepted, settings_data = (json.loads(v) if isinstance(v, str) else v for v in cursor.fetchone())
        self.assertEqual(accepted[0]['typo_tolerance'], 1)
        self.assertTrue(accepted[0]['ignore_word_order'])
        self.assertEqual(accepted[1]['typo_tolerance'], 2)  # clamped
        self.assertFalse(accepted[1]['ignore_word_order'])
        self.assertEqual(settings_data['scoring_mode'], 'partial')
        self.assertEqual(settings_data['correct_threshold'], 50)

    def test_question_image_upload_is_validated_and_stored(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        self.client.force_login(self.teacher_user)
        with self.settings(MEDIA_ROOT=tempfile.mkdtemp()):
            bad = SimpleUploadedFile('payload.exe', b'MZ', content_type='application/octet-stream')
            response = self._create('single', {'text': 'سوال با فایل بد', 'option_text': ['الف', 'ب'], 'correct_options': ['1'], 'question_image_file': bad})
            self.assertEqual(response.status_code, 200)
            self.assertIsNone(self._row('سوال با فایل بد'))
            image = SimpleUploadedFile('ecg.png', b'\x89PNG\r\n\x1a\n' + b'0' * 32, content_type='image/png')
            response = self._create('single', {
                'text': 'سوال با تصویر', 'option_text': ['الف', 'ب'], 'correct_options': ['1'],
                'question_image_file': image, 'question_image_alt': 'نوار قلب',
            })
            self.assertEqual(response.status_code, 302)
        with connection.cursor() as cursor:
            cursor.execute('SELECT question_media FROM questions WHERE text = %s', ['سوال با تصویر'])
            media = json.loads(cursor.fetchone()[0])
        self.assertTrue(media['image'].startswith('/media/question-media/') or 'question-media/' in media['image'])
        self.assertTrue(media['image'].endswith('.png'))
        self.assertEqual(media['image_alt'], 'نوار قلب')

    def test_fill_blank_media_hint_is_stored_reloaded_and_validated(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from apps.core.views import _question_form_data
        self.client.force_login(self.teacher_user)
        base = {'text': 'جمجمه [۱] و [۲]', 'blank_count': '2', 'blank_answers_1': 'الف', 'blank_answers_2': 'ب'}
        with self.settings(MEDIA_ROOT=tempfile.mkdtemp()):
            bad = SimpleUploadedFile('hint.exe', b'MZ', content_type='application/octet-stream')
            self.assertEqual(self._create('fill_blank', dict(base, blank_media_file_2=bad)).status_code, 200)
            self.assertIsNone(self._row('جمجمه [۱] و [۲]'))
            image = SimpleUploadedFile('skull.png', b'\x89PNG\r\n\x1a\n' + b'0' * 32, content_type='image/png')
            self.assertEqual(self._create('fill_blank', dict(base, blank_media_file_2=image)).status_code, 302)
        with connection.cursor() as cursor:
            cursor.execute('SELECT accepted_answers, type, text FROM questions WHERE text = %s', ['جمجمه [۱] و [۲]'])
            accepted, kind, text = cursor.fetchone()
        blanks = json.loads(accepted)
        self.assertEqual(blanks[0]['media'], '')
        self.assertIn('question-media/', blanks[1]['media'])
        self.assertEqual(blanks[1]['media_kind'], 'image')
        form = _question_form_data({'type': kind, 'text': text, 'accepted_answers': accepted})
        self.assertEqual([blank['media_kind'] for blank in form['blanks']], ['', 'image'])

    def test_video_subtitle_is_validated_and_needs_a_video(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        self.client.force_login(self.teacher_user)
        base = {'option_text': ['الف', 'ب'], 'correct_options': ['1']}
        video = lambda: SimpleUploadedFile('case.mp4', b'\x00\x00\x00\x18ftypmp42' + b'0' * 32, content_type='video/mp4')
        vtt = lambda body=b'\xef\xbb\xbfWEBVTT\n\n00:00.000 --> 00:02.000\n\xd8\xb3\xd9\x84\xd8\xa7\xd9\x85\n': SimpleUploadedFile('sub.vtt', body, content_type='text/vtt')
        with self.settings(MEDIA_ROOT=tempfile.mkdtemp()):
            fake = vtt(b'<script>alert(1)</script>')
            response = self._create('single', dict(base, text='زیرنویس جعلی', question_video_file=video(), question_video_subtitle_file=fake))
            self.assertEqual(response.status_code, 200)
            self.assertIsNone(self._row('زیرنویس جعلی'))
            self.assertEqual(self._create('single', dict(base, text='با زیرنویس', question_video_file=video(), question_video_subtitle_file=vtt())).status_code, 302)
            self.assertEqual(self._create('single', dict(base, text='زیرنویس بی‌ویدئو', question_video_subtitle_file=vtt())).status_code, 302)
        with connection.cursor() as cursor:
            cursor.execute('SELECT text, question_media FROM questions WHERE text IN (%s, %s)', ['با زیرنویس', 'زیرنویس بی‌ویدئو'])
            media = {text: json.loads(value) for text, value in cursor.fetchall()}
        self.assertTrue(media['با زیرنویس']['video_subtitle'].endswith('.vtt'))
        self.assertEqual(media['زیرنویس بی‌ویدئو']['video_subtitle'], '')

    def test_autosave_stores_private_draft_and_restores_it(self):
        self.client.force_login(self.teacher_user)
        autosave_url = reverse('core:teacher_question_autosave')
        response = self.client.post(autosave_url, {'type': 'ordering', 'text': 'پیش‌نویس خودکار', 'ordering_item': ['الف', 'ب']})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['ok'])
        self.assertIsNone(self._row('پیش‌نویس خودکار'))  # a draft never becomes a question row
        create_url = f"{reverse('core:teacher_question_create')}?type=ordering"
        self.assertTrue(self.client.get(create_url).context['question_draft_saved_at'])
        restored = self.client.get(f'{create_url}&draft=restore').context['qf']
        self.assertEqual(restored['text'], 'پیش‌نویس خودکار')
        self.assertEqual([item['text'] for item in restored['ordering'][:2]], ['الف', 'ب'])
        self._create('ordering', {'text': 'پیش‌نویس خودکار', 'ordering_item': ['الف', 'ب']})
        self.assertNotIn('question_draft_saved_at', self.client.get(create_url).context)

    def test_autosave_rejects_other_teachers_question_and_invalid_type(self):
        self.client.force_login(self.other_teacher_user)
        autosave_url = reverse('core:teacher_question_autosave')
        self.assertEqual(self.client.post(autosave_url, {'type': 'single', 'question_id': self.question_in_id, 'text': 'x'}).status_code, 404)
        self.assertEqual(self.client.post(autosave_url, {'type': 'osce', 'text': 'x'}).status_code, 400)
        self.assertEqual(self.client.get(autosave_url).status_code, 405)

    def test_kept_media_url_outside_question_media_is_dropped(self):
        self.client.force_login(self.teacher_user)
        self._create('single', {
            'text': 'سوال با آدرس دستکاری‌شده', 'option_text': ['الف', 'ب'], 'correct_options': ['1'],
            'existing_question_image': 'https://evil.example/x.png',
        })
        with connection.cursor() as cursor:
            cursor.execute('SELECT question_media FROM questions WHERE text = %s', ['سوال با آدرس دستکاری‌شده'])
            media = json.loads(cursor.fetchone()[0])
        self.assertEqual(media['image'], '')

    def test_no_hardcoded_sample_data_is_saved_for_independent_questions(self):
        self.client.force_login(self.teacher_user)
        self._create('ordering', {'text': 'سوال مرتب‌سازی تست', 'ordering_item': ['اول', 'دوم']})
        with connection.cursor() as cursor:
            cursor.execute('SELECT options, tags, question_media FROM questions WHERE text = %s', ['سوال مرتب‌سازی تست'])
            options, tags, media = cursor.fetchone()
        self.assertEqual(json.loads(options), [])
        self.assertEqual(tags, '')
        self.assertEqual(json.loads(media)['image'], '')

    def test_invalid_matching_is_rejected_and_input_is_kept(self):
        self.client.force_login(self.teacher_user)
        response = self._create('matching', {'text': 'تطبیقی ناقص', 'matching_left': ['فقط چپ'], 'matching_right': ['']})
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(self._row('تطبیقی ناقص'))
        self.assertEqual(response.context['qf']['text'], 'تطبیقی ناقص')
        self.assertEqual(response.context['qf']['pairs'][0]['left'], 'فقط چپ')

    def test_fill_blank_answer_count_must_match_markers(self):
        self.client.force_login(self.teacher_user)
        text = 'دو جای خالی [۱] و [۲]'
        response = self._create('fill_blank', {'text': text, 'blank_count': '1', 'blank_answers_1': 'تنها'})
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(self._row(text))

    def test_out_of_scope_course_is_rejected(self):
        self.client.force_login(self.teacher_user)
        response = self._create('ordering', {'text': 'درس نفوذی', 'ordering_item': ['اول', 'دوم'], 'course_id': self.course_out_id})
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(self._row('درس نفوذی'))

    def test_teacher_can_edit_own_question(self):
        self.client.force_login(self.teacher_user)
        self._create('ordering', {'text': 'قبل از ویرایش', 'ordering_item': ['اول', 'دوم']})
        question_id = self._row('قبل از ویرایش')[0]
        edit_url = reverse('core:teacher_question_edit', args=[question_id])
        get_response = self.client.get(edit_url)
        self.assertEqual(get_response.status_code, 200)
        self.assertEqual([item['text'] for item in get_response.context['qf']['ordering'][:2]], ['اول', 'دوم'])
        response = self.client.post(edit_url, {
            'text': 'بعد از ویرایش',
            'course_id': self.course_in_id,
            'ordering_item': ['دوم', 'اول', 'سوم'],
            'is_published': '1',
        })
        self.assertEqual(response.status_code, 302)
        row = self._row('بعد از ویرایش')
        self.assertEqual(row[0], question_id)
        self.assertEqual([item['text'] for item in json.loads(row[6])], ['دوم', 'اول', 'سوم'])

    def test_teacher_cannot_view_or_edit_another_teachers_question(self):
        self.client.force_login(self.other_teacher_user)
        edit_url = reverse('core:teacher_question_edit', args=[self.question_in_id])
        self.assertEqual(self.client.get(edit_url).status_code, 404)
        self.assertEqual(self.client.post(edit_url, {'text': 'دستکاری', 'type': 'single'}).status_code, 404)
        with connection.cursor() as cursor:
            cursor.execute('SELECT text FROM questions WHERE id = %s', [self.question_in_id])
            self.assertEqual(cursor.fetchone()[0], 'سوال داخل محدوده')

    def test_exam_style_preview_for_every_independent_type(self):
        from apps.core.views import _sx_type_label
        self.client.force_login(self.teacher_user)
        url = reverse('core:teacher_question_create')
        for kind in ('single', 'multi', 'true_false', 'short_answer', 'essay', 'fill_blank', 'matching', 'ordering'):
            html = self.client.get(f'{url}?type={kind}').content.decode()
            self.assertIn('data-exam-preview', html, kind)
            self.assertIn('data-qx-area', html, kind)
            # Same type label as the student exam page.
            self.assertIn(f'سؤال ۱ — {_sx_type_label(kind)}', html, kind)
            self.assertIn('css/exam-view', html, kind)
            self.assertIn('js/exam-interactions', html, kind)
            # The old modal preview is gone.
            self.assertNotIn('data-preview-modal', html, kind)
        multi = self.client.get(f'{url}?type=multi').content.decode()
        self.assertIn('data-qx-guide-variant="max"', multi)
        self.assertIn('حداکثر __N__ گزینه', multi)
        essay = self.client.get(f'{url}?type=essay').content.decode()
        self.assertIn('data-qx-guide-variant="upload"', essay)

    def test_true_false_layout_moves_stem_media_to_side_card(self):
        self.client.force_login(self.teacher_user)
        url = reverse('core:teacher_question_create')
        html = self.client.get(f'{url}?type=true_false').content.decode()
        self.assertIn('qb--tf', html)
        self.assertIn('رسانه سؤال', html)
        self.assertIn('class="qf-drop qb-tf-drop"', html)
        # Stem media fields still render exactly once, so uploads keep their names.
        self.assertEqual(html.count('name="question_video_file"'), 1)
        self.assertIn('<span>صوت</span>', html)
        # Exam-style student preview is included (its markup is covered by the preview tests).
        self.assertIn('data-exam-preview', html)
        single = self.client.get(f'{url}?type=single').content.decode()
        self.assertNotIn('class="qf-drop qb-tf-drop"', single)
        self.assertNotIn('<span>صوت</span>', single)
        self.assertEqual(single.count('name="question_video_file"'), 1)

    def test_fill_blank_layout_shows_media_tiles_and_marker_view(self):
        self.client.force_login(self.teacher_user)
        url = reverse('core:teacher_question_create')
        html = self.client.get(f'{url}?type=fill_blank').content.decode()
        self.assertIn('qb--fb qb--v2', html)
        self.assertIn('class="qf-drop qb-fb-add"', html)
        self.assertIn('تلفظ واژه‌ها (اختیاری)', html)
        self.assertIn('class="qb-fb-markers"', html)
        self.assertEqual(html.count('name="question_image_file"'), 1)
        # Each blank row carries a real media slot for its hint (names assigned per row at submit).
        self.assertIn('data-media-base="blank_media"', html)
        self.assertNotIn('در حال توسعه', html.split('data-row-list="blank"')[1].split('</section>')[0])
        single = self.client.get(f'{url}?type=single').content.decode()
        self.assertNotIn('class="qf-drop qb-fb-add"', single)

    def test_true_false_question_saves_chosen_answer(self):
        self.client.force_login(self.teacher_user)
        response = self._create('true_false', {
            'text': 'سوال درست نادرست تست',
            'option_text': ['درست', 'نادرست'],
            'correct_options': ['2'],
        })
        self.assertEqual(response.status_code, 302)
        row = self._row('سوال درست نادرست تست')
        options = json.loads(row[3])
        self.assertEqual([item['text'] for item in options], ['درست', 'نادرست'])
        self.assertEqual(json.loads(row[4]), options[1]['id'])

    def test_question_bank_type_strip_filters_list(self):
        self.client.force_login(self.teacher_user)
        self._create('true_false', {'text': 'فیلتر نوع درست نادرست', 'option_text': ['درست', 'نادرست'], 'correct_options': ['1']})
        self._create('ordering', {'text': 'فیلتر نوع ترتیبی', 'ordering_item': ['الف', 'ب']})
        page = self.client.get(f"{reverse('core:teacher_questions')}?type=ordering&q=فیلتر نوع")
        html = page.content.decode()
        listed = html.split('question-bank-table')[1].split('</table>')[0]  # «فعالیت‌های اخیر» below is not filtered
        self.assertIn('فیلتر نوع ترتیبی', listed)
        self.assertNotIn('فیلتر نوع درست نادرست', listed)
        # کارت فعال اکنون باید فیلتر را بردارد و بقیه‌ی فیلترها حفظ شوند
        self.assertIn('class="is-active" aria-current="true"', html)
        from urllib.parse import urlencode
        self.assertIn('?' + urlencode({'q': 'فیلتر نوع', 'status': 'all', 'difficulty': 'all'}).replace('&', '&amp;') + '&amp;type=all', html)
        self.assertNotIn('teacher_question_create', html.split('question-type-strip')[1].split('</nav>')[0])


class AttemptGradingTests(_ScopedOrgFixture):
    """
    رگرسیون باگ‌های تصحیح خودکار: پاسخ و correct_answer هر دو JSON-بسته‌بندی
    ذخیره می‌شوند و قبلاً بدون باز کردن مقایسه می‌شدند؛ چندپاسخی فقط یک
    مقدار ذخیره می‌کرد؛ تطبیقی/مرتب‌سازی از ستون‌های اختصاصی خوانده نمی‌شدند.
    """

    def _score(self, question_columns, answer_value):
        from apps.core.views import grade_attempt
        question_id = str(uuid.uuid4())
        _insert(
            'questions',
            ['id', 'teacher_id', 'course_id', 'text', 'default_points'] + list(question_columns),
            [question_id, self.teacher_in_id, self.course_in_id, 'سوال تصحیح', 2] + list(question_columns.values()),
        )
        exam_id = str(uuid.uuid4())
        _insert('exams', ['id', 'title', 'teacher_id', 'course_id', 'start_at'],
                [exam_id, 'آزمون تصحیح', self.teacher_in_id, self.course_in_id, timezone.now()])
        _insert('exam_questions', ['id', 'exam_id', 'question_id', 'points', 'order_index'],
                [str(uuid.uuid4()), exam_id, question_id, 2, 1])
        attempt_id = str(uuid.uuid4())
        _insert('exam_attempts', ['id', 'exam_id', 'student_id', 'started_at', 'status'],
                [attempt_id, exam_id, self.student_in_id, timezone.now(), 'in_progress'])
        _insert('attempt_answers', ['id', 'attempt_id', 'question_id', 'answer', 'needs_manual_grading'],
                [str(uuid.uuid4()), attempt_id, question_id, json.dumps({'value': answer_value}, ensure_ascii=False), False])
        return grade_attempt(attempt_id)['score']

    def test_single_choice_graded_after_unwrapping_json(self):
        correct = {'type': 'single', 'correct_answer': json.dumps('2')}
        self.assertEqual(self._score(correct, '2'), 2)
        self.assertEqual(self._score(correct, '1'), 0)

    def test_multi_choice_compares_full_selection(self):
        correct = {'type': 'multi', 'correct_answer': json.dumps(['1', '2'])}
        self.assertEqual(self._score(correct, ['1', '2']), 2)
        self.assertEqual(self._score(correct, ['1']), 0)

    def test_fill_blank_ordering_and_matching(self):
        fill = {'type': 'fill_blank', 'correct_answer': json.dumps('الف|ب', ensure_ascii=False)}
        self.assertEqual(self._score(fill, 'الف|ب'), 2)
        self.assertEqual(self._score(fill, 'ب|الف'), 0)
        ordering = {'type': 'ordering', 'ordering_items': json.dumps([{'order': 1, 'text': 'x'}, {'order': 2, 'text': 'y'}, {'order': 3, 'text': 'z'}])}
        self.assertEqual(self._score(ordering, '1,2,3'), 2)
        self.assertEqual(self._score(ordering, '2,1,3'), 0)
        matching = {'type': 'matching', 'matching_pairs': json.dumps([{'left': 'a', 'right': 'b'}, {'left': 'c', 'right': 'd'}])}
        self.assertEqual(self._score(matching, '1:1,2:2'), 2)
        self.assertEqual(self._score(matching, '1:2,2:1'), 0)

    def test_negative_marking_applies_only_to_wrong_answers(self):
        single = {'type': 'single', 'correct_answer': json.dumps('2'),
                  'scoring_settings': json.dumps({'negative_marking': True, 'negative_value': 0.25})}
        self.assertEqual(self._score(single, '2'), 2)
        self.assertEqual(self._score(single, '1'), 0)  # total attempt score is floored at zero
        from apps.core.views import _grade_question
        row = {'type': 'single', 'correct_answer': json.dumps('2'), 'scoring_settings': {'negative_marking': True, 'negative_value': 0.25}}
        self.assertEqual(_grade_question(row, '1', 2)[0], -0.5)
        self.assertEqual(_grade_question(row, '', 2)[0], 0)

    def test_multi_partial_credit_and_selection_limit(self):
        from apps.core.views import _grade_question
        options = [{'id': str(i), 'text': t, 'points': '1', 'negative_points': '-0.5'} for i, t in enumerate('ابجد', start=1)]
        row = {'type': 'multi', 'correct_answer': json.dumps(['1', '2']), 'options': options,
               'scoring_settings': {'scoring_mode': 'partial', 'max_correct': 3, 'floor_zero': True}}
        self.assertEqual(_grade_question(row, ['1', '2'], 4)[0], 4)
        self.assertEqual(_grade_question(row, ['1'], 4)[0], 2)
        self.assertEqual(_grade_question(row, ['1', '3'], 4)[0], 1)  # (1 − 0.5) / 2 of the points
        self.assertEqual(_grade_question(row, ['3', '4'], 4)[0], 0)  # floored at zero
        self.assertEqual(_grade_question(row, ['1', '2', '3', '4'], 4)[0], 0)  # above max selection
        options[0]['points'] = '3'  # weighted option
        self.assertEqual(_grade_question(row, ['1'], 4)[0], 3)
        row['scoring_settings']['floor_zero'] = False
        self.assertEqual(_grade_question(row, ['3', '4'], 4)[0], -1)  # (0 − 1) / 4 of the points

    def test_short_answer_auto_grading_rules(self):
        from apps.core.views import _grade_question
        accepted = [
            {'answer': 'آتروپین', 'points': 100, 'match_mode': 'exact', 'case_sensitive': False, 'normalize': True, 'tolerance': 0},
            {'answer': '120', 'points': 100, 'match_mode': 'exact', 'case_sensitive': False, 'normalize': True, 'tolerance': 5},
            {'answer': 'adrenal', 'points': 50, 'match_mode': 'contains', 'case_sensitive': False, 'normalize': True, 'tolerance': 0},
        ]
        row = {'type': 'short_answer', 'accepted_answers': accepted}
        self.assertEqual(_grade_question(row, ' آتروپين ', 2), (2, False, True))  # Arabic ي normalised
        self.assertEqual(_grade_question(row, '۱۲۴', 2)[0], 2)  # Persian digits + tolerance
        self.assertEqual(_grade_question(row, '130', 2), (0, True, False))  # unmatched → manual review
        self.assertEqual(_grade_question(row, '', 2), (0, False, False))
        self.assertEqual(_grade_question(row, 'Adrenal gland', 2)[0], 1)
        legacy = {'type': 'short_answer', 'accepted_answers': [{'answer': 'x', 'points': '1'}]}
        self.assertEqual(_grade_question(legacy, 'x', 2), (0, True, False))

    def test_short_answer_typo_word_order_and_partial_switch(self):
        from apps.core.views import _grade_question
        accepted = [
            {'answer': 'سندرم کوشینگ', 'points': 100, 'match_mode': 'exact', 'normalize': True, 'typo_tolerance': 1, 'ignore_word_order': True},
            {'answer': 'cushing', 'points': 50, 'match_mode': 'exact', 'normalize': True, 'typo_tolerance': 0},
            {'answer': 'کم', 'points': 100, 'match_mode': 'exact', 'normalize': True, 'typo_tolerance': 2},
        ]
        row = {'type': 'short_answer', 'accepted_answers': accepted}
        self.assertEqual(_grade_question(row, 'کوشینگ سندرم', 2), (2, False, True))  # word order ignored
        self.assertEqual(_grade_question(row, 'سندروم کوشینگ', 2)[0], 2)  # one-letter typo forgiven
        self.assertEqual(_grade_question(row, 'سندروم کوشنگ', 2), (0, True, False))  # two typos > tolerance
        self.assertEqual(_grade_question(row, 'کو', 2), (0, True, False))  # short answers never fuzzy-matched
        self.assertEqual(_grade_question(row, 'Cushing', 2), (1, False, False))  # 50% < default 100% threshold
        row['scoring_settings'] = {'correct_threshold': 50}
        self.assertEqual(_grade_question(row, 'Cushing', 2), (1, False, True))
        row['scoring_settings'] = {'scoring_mode': 'all_or_nothing'}
        self.assertEqual(_grade_question(row, 'Cushing', 2), (0, False, False))  # matched, so no manual review
        self.assertEqual(_grade_question(row, 'سندرم کوشینگ', 2), (2, False, True))

    def test_fill_blank_alternatives_and_partial(self):
        from apps.core.views import _grade_question
        blanks = [
            {'blank': 1, 'answers': ['قلب', 'heart'], 'points': 1, 'case_sensitive': False, 'ignore_spaces': True},
            {'blank': 2, 'answers': ['ریه'], 'points': 3, 'case_sensitive': False, 'ignore_spaces': True},
        ]
        row = {'type': 'fill_blank', 'accepted_answers': blanks, 'scoring_settings': {'scoring_mode': 'partial'}}
        self.assertEqual(_grade_question(row, ['HEART', 'ریه'], 4)[0], 4)
        self.assertEqual(_grade_question(row, ['قلب', 'کبد'], 4)[0], 1)
        row['scoring_settings'] = {'scoring_mode': 'all_or_nothing'}
        self.assertEqual(_grade_question(row, ['قلب', 'کبد'], 4)[0], 0)

    def test_fill_blank_normalization_can_be_turned_off(self):
        from apps.core.views import _grade_question
        blanks = [{'blank': 1, 'answers': ['کلية ۱۲'], 'points': 1, 'case_sensitive': False, 'ignore_spaces': False}]
        row = {'type': 'fill_blank', 'accepted_answers': blanks, 'scoring_settings': {'scoring_mode': 'partial'}}
        # Default (and «نرمال‌سازی پاسخ‌ها» on): Arabic «ي/ك» and Latin digits match their Persian forms.
        self.assertEqual(_grade_question(row, ['کليه 12'], 2)[0], 2)
        row['scoring_settings'] = {'scoring_mode': 'partial', 'normalize_answers': False}
        self.assertEqual(_grade_question(row, ['کليه 12'], 2)[0], 0)
        self.assertEqual(_grade_question(row, ['کلية ۱۲'], 2)[0], 2)

    def test_ordering_and_matching_partial_modes(self):
        from apps.core.views import _grade_question
        items = [{'order': i, 'text': str(i)} for i in range(1, 5)]
        row = {'type': 'ordering', 'ordering_items': items, 'scoring_settings': {'scoring_mode': 'partial', 'ordering_mode': 'position'}}
        self.assertEqual(_grade_question(row, '1,2,4,3', 4)[0], 2)
        row['scoring_settings']['ordering_mode'] = 'adjacent'
        self.assertEqual(_grade_question(row, '2,3,4,1', 3)[0], 2)
        row['scoring_settings']['ordering_mode'] = 'exact'
        self.assertEqual(_grade_question(row, '1,2,4,3', 4)[0], 0)
        pairs = [{'left': 'a', 'right': 'x'}, {'left': 'b', 'right': 'x'}, {'left': 'c', 'right': 'y'}]
        matching = {'type': 'matching', 'matching_pairs': pairs, 'scoring_settings': {'scoring_mode': 'partial', 'matching_mode': 'many_to_one'}}
        self.assertEqual(_grade_question(matching, '1:1,2:1,3:3', 3)[0], 3)  # same right text accepted
        self.assertEqual(_grade_question(matching, '1:1,2:3,3:d1', 3)[0], 1)


class OsceBuilderTests(_ScopedOrgFixture):
    """سازنده‌ی آزمون OSCE: ذخیره‌ی واقعی ایستگاه‌ها و محدودشدن دسترسی به استاد مالک."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        User = get_user_model()
        cls.teacher_user = User.objects.create_user(username='teacher_in_scope', email='teacher_in_scope@example.com', password='x')
        cls.other_teacher_user = User.objects.create_user(username='teacher_out_scope', email='teacher_out_scope@example.com', password='x')

    def _basic(self, **overrides):
        data = {
            'tab': 'basic', 'exam_title': 'آزمون OSCE کودکان', 'course_id': self.course_in_id,
            'title': 'ارزیابی معاینه قلب', 'code': 'OSCE-01', 'station_type': 'clinical', 'domain': 'قلب و عروق کودکان',
            'difficulty': 'medium', 'description': 'ارزیابی مهارت معاینه قلب', 'position': '1', 'duration_minutes': '10',
            'is_active': '1', 'objectives': ['انجام معاینه دقیق قلب', 'ارتباط مؤثر با والدین'],
        }
        data.update(overrides)
        return data

    def _create_osce(self):
        self.client.force_login(self.teacher_user)
        response = self.client.post(reverse('core:teacher_osce_create'), self._basic())
        self.assertEqual(response.status_code, 302)
        with connection.cursor() as cursor:
            cursor.execute('SELECT id FROM osce_exams WHERE teacher_id = %s', [self.teacher_in_id])
            return str(cursor.fetchone()[0])

    def _stations(self, osce_id):
        with connection.cursor() as cursor:
            cursor.execute(
                'SELECT id, position, title, code, objectives, details, is_active FROM osce_stations WHERE osce_exam_id = %s ORDER BY position',
                [osce_id],
            )
            return cursor.fetchall()

    def test_structure_page_routes_osce_to_builder(self):
        self.client.force_login(self.teacher_user)
        response = self.client.get(reverse('core:teacher_question_type'))
        self.assertContains(response, reverse('core:teacher_osce_create'))

    def test_create_saves_exam_and_first_station(self):
        osce_id = self._create_osce()
        stations = self._stations(osce_id)
        self.assertEqual(len(stations), 1)
        self.assertEqual(stations[0][2], 'ارزیابی معاینه قلب')
        self.assertEqual(json.loads(stations[0][4]), ['انجام معاینه دقیق قلب', 'ارتباط مؤثر با والدین'])
        response = self.client.get(reverse('core:teacher_osce_builder', args=[osce_id]))
        self.assertContains(response, 'ارزیابی معاینه قلب')
        self.assertContains(response, 'tab=settings')

    def test_create_rejects_invalid_input_and_foreign_course(self):
        self.client.force_login(self.teacher_user)
        response = self.client.post(
            reverse('core:teacher_osce_create'),
            self._basic(title='', duration_minutes='0', course_id=self.course_out_id),
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'عنوان ایستگاه الزامی است.')
        self.assertContains(response, 'درس انتخاب‌شده معتبر نیست.')
        with connection.cursor() as cursor:
            cursor.execute('SELECT COUNT(*) FROM osce_exams')
            self.assertEqual(cursor.fetchone()[0], 0)

    def test_type_tab_saves_details(self):
        osce_id = self._create_osce()
        station_id = str(self._stations(osce_id)[0][0])
        response = self.client.post(reverse('core:teacher_osce_builder', args=[osce_id]), {
            'tab': 'type', 'station_id': station_id, 'station_type': 'skill', 'execution_mode': 'mannequin',
            'assessment_method': 'checklist', 'examiner_present': '1',
        })
        self.assertEqual(response.status_code, 302)
        details = json.loads(self._stations(osce_id)[0][5])
        self.assertEqual(details['execution_mode'], 'mannequin')
        self.assertTrue(details['examiner_present'])
        self.assertFalse(details['needs_standardized_patient'])

    def test_duplicate_code_is_rejected(self):
        osce_id = self._create_osce()
        self.client.post(reverse('core:teacher_osce_station_add', args=[osce_id]))
        second_id = str(self._stations(osce_id)[1][0])
        response = self.client.post(
            reverse('core:teacher_osce_builder', args=[osce_id]),
            self._basic(station_id=second_id, position='2'),
        )
        self.assertContains(response, 'این کد ایستگاه قبلاً در همین آزمون استفاده شده است.')

    def test_add_reorder_and_delete_stations(self):
        osce_id = self._create_osce()
        self.client.post(reverse('core:teacher_osce_station_add', args=[osce_id]))
        self.client.post(reverse('core:teacher_osce_station_add', args=[osce_id]))
        ids = [str(row[0]) for row in self._stations(osce_id)]
        self.assertEqual([row[3] for row in self._stations(osce_id)], ['OSCE-01', 'OSCE-02', 'OSCE-03'])
        url = reverse('core:teacher_osce_station_reorder', args=[osce_id])
        response = self.client.post(url, json.dumps({'order': list(reversed(ids))}), content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual([str(row[0]) for row in self._stations(osce_id)], list(reversed(ids)))
        bad = self.client.post(url, json.dumps({'order': ids[:2]}), content_type='application/json')
        self.assertEqual(bad.status_code, 400)
        self.client.post(reverse('core:teacher_osce_station_delete', args=[osce_id, ids[1]]))
        self.assertEqual([row[1] for row in self._stations(osce_id)], [1, 2])

    def test_other_teacher_cannot_read_or_change_osce(self):
        osce_id = self._create_osce()
        station_id = str(self._stations(osce_id)[0][0])
        self.client.force_login(self.other_teacher_user)
        self.assertEqual(self.client.get(reverse('core:teacher_osce_builder', args=[osce_id])).status_code, 404)
        self.assertEqual(
            self.client.post(reverse('core:teacher_osce_builder', args=[osce_id]), self._basic(station_id=station_id, title='تغییر')).status_code,
            404,
        )
        self.assertEqual(self.client.post(reverse('core:teacher_osce_station_add', args=[osce_id])).status_code, 404)
        self.assertEqual(self.client.post(reverse('core:teacher_osce_station_delete', args=[osce_id, station_id])).status_code, 404)
        reorder = self.client.post(
            reverse('core:teacher_osce_station_reorder', args=[osce_id]),
            json.dumps({'order': [station_id]}), content_type='application/json',
        )
        self.assertEqual(reorder.status_code, 404)
        self.assertEqual(self.client.post(reverse('core:teacher_osce_settings', args=[osce_id]), {'exam_title': 'تغییر'}).status_code, 404)
        self.assertNotContains(self.client.get(reverse('core:teacher_osce_list')), 'آزمون OSCE کودکان')
        self.assertEqual(self._stations(osce_id)[0][2], 'ارزیابی معاینه قلب')

    def test_station_id_from_another_exam_is_not_editable(self):
        osce_id = self._create_osce()
        self.client.force_login(self.other_teacher_user)
        other = self.client.post(reverse('core:teacher_osce_create'), self._basic(course_id='', code='X-1'))
        self.assertEqual(other.status_code, 302)
        with connection.cursor() as cursor:
            cursor.execute(
                'SELECT s.id FROM osce_stations s JOIN osce_exams o ON o.id = s.osce_exam_id WHERE o.teacher_id = %s',
                [self.teacher_out_id],
            )
            foreign_station = str(cursor.fetchone()[0])
        self.client.force_login(self.teacher_user)
        response = self.client.post(reverse('core:teacher_osce_builder', args=[osce_id]), self._basic(station_id=foreign_station))
        self.assertEqual(response.status_code, 404)

    def _details(self, osce_id):
        return json.loads(self._stations(osce_id)[0][5])

    def _post_tab(self, osce_id, tab, data):
        station_id = str(self._stations(osce_id)[0][0])
        return self.client.post(reverse('core:teacher_osce_builder', args=[osce_id]), {'tab': tab, 'station_id': station_id, **data})

    def test_scenario_tab_saves_rich_text_media_and_new_objective(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        osce_id = self._create_osce()
        story = {'ops': [{'insert': 'کودک ۷ ساله '}, {'insert': 'VSD', 'attributes': {'bold': True}}, {'insert': '\n'}]}
        with self.settings(MEDIA_ROOT=tempfile.mkdtemp()):
            response = self._post_tab(osce_id, 'scenario', {
                'patient_age': '۷ سال', 'patient_gender': 'boy', 'patient_chief_complaint': 'تنگی نفس', 'patient_role': 'parent',
                'scenario_story': json.dumps(story), 'scenario_notes': 'نکته ایمنی',
                'focus_objectives': ['انجام معاینه دقیق قلب'], 'new_objective': 'تصمیم‌گیری بالینی اولیه',
                'scenario_media': [
                    SimpleUploadedFile('cxr.png', b'\x89PNG\r\n\x1a\n' + b'0' * 32, content_type='image/png'),
                    SimpleUploadedFile('lab.pdf', b'%PDF-1.4 test', content_type='application/pdf'),
                ],
            })
            self.assertEqual(response.status_code, 302)
            scenario = self._details(osce_id)['scenario']
            self.assertEqual(scenario['patient']['role'], 'parent')
            self.assertEqual(scenario['story'], story)
            self.assertEqual([item['kind'] for item in scenario['media']], ['image', 'pdf'])
            self.assertIn('تصمیم‌گیری بالینی اولیه', scenario['focus_objectives'])
            self.assertIn('تصمیم‌گیری بالینی اولیه', json.loads(self._stations(osce_id)[0][4]))
            removed = self._post_tab(osce_id, 'scenario', {'remove_media': [scenario['media'][0]['url']]})
            self.assertEqual(removed.status_code, 302)
            self.assertEqual([item['name'] for item in self._details(osce_id)['scenario']['media']], ['lab.pdf'])

    def test_scenario_upload_rejects_disguised_file_and_keeps_old_data(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        osce_id = self._create_osce()
        with self.settings(MEDIA_ROOT=tempfile.mkdtemp()):
            response = self._post_tab(osce_id, 'scenario', {
                'scenario_media': [SimpleUploadedFile('report.pdf', b'<script>alert(1)</script>', content_type='application/pdf')],
            })
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, 'با پسوند آن هم‌خوانی ندارد')
            response = self._post_tab(osce_id, 'scenario', {
                'scenario_media': [SimpleUploadedFile('run.exe', b'MZ', content_type='application/octet-stream')],
            })
            self.assertContains(response, 'مجاز نیست')
        self.assertNotIn('scenario', self._details(osce_id))

    def test_scenario_requires_patient_when_station_needs_standardized_patient(self):
        osce_id = self._create_osce()
        self._post_tab(osce_id, 'type', {'station_type': 'clinical', 'execution_mode': 'standardized_patient',
                                         'assessment_method': 'checklist', 'needs_standardized_patient': '1'})
        response = self._post_tab(osce_id, 'scenario', {'patient_age': '۷ سال'})
        self.assertContains(response, 'این ایستگاه به بیمار استانداردشده نیاز دارد')

    def test_instructions_tab_requires_body_and_renders_escaped_preview(self):
        osce_id = self._create_osce()
        response = self._post_tab(osce_id, 'instructions', {'instructions_body': json.dumps({'ops': [{'insert': '\n'}]})})
        self.assertContains(response, 'متن دستورالعمل دانشجو الزامی است.')
        body = {'ops': [{'insert': '<script>alert(1)</script> معاینه کنید'}, {'insert': '\n', 'attributes': {'list': 'ordered'}}]}
        response = self._post_tab(osce_id, 'instructions', {'instructions_body': json.dumps(body), 'show_task_list': '1'})
        self.assertEqual(response.status_code, 302)
        instructions = self._details(osce_id)['instructions']
        self.assertTrue(instructions['show_task_list'])
        self.assertFalse(instructions['show_start_button'])
        page = self.client.get(response['Location'])
        self.assertContains(page, '<ol><li>&lt;script&gt;alert(1)&lt;/script&gt; معاینه کنید</li></ol>', html=False)
        self.assertNotContains(page, '<script>alert(1)</script>')

    def _criteria_post(self, **overrides):
        data = {
            'criteria_uid': ['criteria-0', 'criteria-1', 'criteria-2'],
            'criteria_text': ['معرفی خود', 'معاینه قلب به ترتیب صحیح', ''],
            'criteria_type': ['binary', 'scale', 'binary'],
            'criteria_points': ['2', '8.5', '1'],
            'criteria_guide': ['خود را معرفی می‌کند', '', ''],
            'criteria_required': ['criteria-1'],
            'global_uid': ['global-0'], 'global_text': ['عملکرد کلی'], 'global_points': ['4'], 'global_guide': [''],
            'level_label': ['عالی', 'خوب', 'متوسط', 'ضعیف تا متوسط', 'ضعیف'],
            'level_description': ['کامل', 'جزئی', 'با کمک', 'ناقص', 'انجام نمی‌دهد'],
            'scoring_mode': 'per_item', 'show_descriptions': '1',
        }
        data.update(overrides)
        return data

    def test_criteria_tab_saves_items_levels_and_totals(self):
        osce_id = self._create_osce()
        response = self._post_tab(osce_id, 'criteria', self._criteria_post())
        self.assertEqual(response.status_code, 302)
        criteria = self._details(osce_id)['criteria']
        self.assertEqual([item['text'] for item in criteria['items']], ['معرفی خود', 'معاینه قلب به ترتیب صحیح'])
        self.assertEqual([item['required'] for item in criteria['items']], [False, True])
        self.assertEqual(criteria['items'][1]['points'], '8.5')
        self.assertEqual(criteria['total_points'], '14.5')
        self.assertEqual(criteria['global_items'][0]['type'], 'scale')
        self.assertEqual(criteria['scale_levels'][3]['label'], 'ضعیف تا متوسط')
        self.assertEqual(criteria['display'], {'show_descriptions': True, 'show_item_points': False,
                                               'show_running_total': False, 'show_examiner_notes': False})
        page = self.client.get(response['Location'])
        self.assertContains(page, 'معاینه قلب به ترتیب صحیح')
        self.assertContains(page, 'معاینه قلب کودکان')  # built-in template list

    def test_criteria_tab_validates_points_pass_score_and_method(self):
        osce_id = self._create_osce()
        response = self._post_tab(osce_id, 'criteria', self._criteria_post(
            criteria_points=['0', 'abc', '1'], scoring_mode='pass_fail', pass_score='99'))
        self.assertContains(response, 'امتیاز باید عددی بزرگ‌تر از صفر')
        self.assertContains(response, 'حد نصاب قبولی باید')
        self._post_tab(osce_id, 'type', {'station_type': 'clinical', 'execution_mode': 'mannequin', 'assessment_method': 'combined'})
        response = self._post_tab(osce_id, 'criteria', self._criteria_post(global_uid=[], global_text=[], global_points=[], global_guide=[]))
        self.assertContains(response, 'حداقل یک مورد ارزیابی کلی')
        self.assertNotIn('criteria', self._details(osce_id))

    def test_teacher_templates_are_saved_listed_and_scoped(self):
        url = reverse('core:teacher_osce_template_save')
        self.client.force_login(self.teacher_user)
        items = [{'text': 'شستن دست', 'type': 'binary', 'points': '1', 'required': True, 'guide': ''}]
        response = self.client.post(url, json.dumps({'title': 'قالب من', 'items': items}), content_type='application/json')
        self.assertEqual(response.status_code, 200)
        template_id = response.json()['template']['id']
        duplicate = self.client.post(url, json.dumps({'title': 'قالب من', 'items': items}), content_type='application/json')
        self.assertEqual(duplicate.status_code, 400)
        invalid = self.client.post(url, json.dumps({'title': 'بد', 'items': [{'text': 'x', 'type': 'evil', 'points': '-1'}]}), content_type='application/json')
        self.assertEqual(invalid.status_code, 400)
        osce_id = self._create_osce()
        station_id = str(self._stations(osce_id)[0][0])
        page = self.client.get(reverse('core:teacher_osce_builder', args=[osce_id]) + f'?station={station_id}&tab=criteria')
        self.assertContains(page, 'قالب من')
        delete_url = reverse('core:teacher_osce_template_delete', args=[template_id])
        self.client.force_login(self.other_teacher_user)
        self.assertEqual(self.client.post(delete_url).status_code, 404)
        self.client.force_login(self.teacher_user)
        self.assertEqual(self.client.post(delete_url).status_code, 200)
        with connection.cursor() as cursor:
            cursor.execute('SELECT COUNT(*) FROM osce_criteria_templates')
            self.assertEqual(cursor.fetchone()[0], 0)

    def _timing_post(self, **overrides):
        data = {
            'duration_minutes': '8', 'study_minutes': '2', 'transition_minutes': '1', 'execution_pattern': 'rotation',
            'capacity': '1', 'groups_count': '4', 'students_per_group': '6', 'start_time': '09:00',
            'primary_examiner': self.teacher_in_id, 'second_examiner': '', 'alert_type': 'audio_visual',
            'timer_student': '1', 'end_sound': '1',
        }
        data.update(overrides)
        return data

    def _settings_post(self, **overrides):
        data = {'access_scope': 'selected', 'max_attempts': '1', 'exam_pass_score': '60', 'negative_mark': '0.25',
                'show_remaining_time': '1', 'notify_students': '1', 'tags': ['بالینی', 'ارتباطی', 'بالینی'], 'exam_notes': ''}
        data.update(overrides)
        return data

    def test_resources_tab_saves_tables_and_rejects_bad_rows(self):
        osce_id = self._create_osce()
        response = self._post_tab(osce_id, 'resources', {
            'equipment_name': ['تخت معاینه', ''], 'equipment_count': ['1', '1'], 'equipment_status': ['required', 'optional'],
            'supplies_name': ['دستکش'], 'supplies_count': ['10'], 'supplies_status': ['required'],
            'staff_name': ['بیمار استانداردشده'], 'staff_count': ['1'], 'staff_note': ['آموزش‌دیده'],
            'safety_notes': 'بررسی دستگاه قبل از شروع',
        })
        self.assertEqual(response.status_code, 302)
        resources = self._details(osce_id)['resources']
        self.assertEqual(resources['equipment'], [{'name': 'تخت معاینه', 'count': 1, 'status': 'required'}])
        self.assertEqual(resources['staff'][0]['note'], 'آموزش‌دیده')
        bad = self._post_tab(osce_id, 'resources', {
            'equipment_name': ['تخت'], 'equipment_count': ['0'], 'equipment_status': ['evil'],
            'supplies_name': ['a', 'b'], 'supplies_count': ['1'], 'supplies_status': ['required'],
        })
        self.assertContains(bad, 'تعداد باید عددی بین')
        self.assertContains(bad, 'وضعیت نامعتبر است')
        self.assertContains(bad, 'ناقص ارسال شده است')
        self.assertEqual(self._details(osce_id)['resources']['equipment'][0]['name'], 'تخت معاینه')

    def test_timing_tab_saves_and_limits_examiners_to_org_unit(self):
        osce_id = self._create_osce()
        outsider = self._post_tab(osce_id, 'timing', self._timing_post(primary_examiner=self.teacher_out_id))
        self.assertContains(outsider, 'ارزیاب اصلی را از فهرست انتخاب کنید.')
        response = self._post_tab(osce_id, 'timing', self._timing_post())
        self.assertEqual(response.status_code, 302)
        timing = self._details(osce_id)['timing']
        self.assertEqual(timing['study_minutes'], 2)
        self.assertTrue(timing['alerts']['timer_student'])
        self.assertFalse(timing['alerts']['one_minute_warning'])
        with connection.cursor() as cursor:
            cursor.execute('SELECT duration_minutes FROM osce_stations WHERE osce_exam_id = %s', [osce_id])
            self.assertEqual(cursor.fetchone()[0], 8)
            cursor.execute('SELECT settings FROM osce_exams WHERE id = %s', [osce_id])
            self.assertEqual(json.loads(cursor.fetchone()[0])['rotation']['start_time'], '09:00')
        page = self.client.get(response['Location'])
        self.assertContains(page, '۰۹:۰۰ - ۰۹:۱۰')
        self.assertContains(page, self.teacher_in_id)
        self.assertNotContains(page, self.teacher_out_id)

    def test_rotation_schedule_shifts_groups_and_runs_extra_circuits(self):
        from apps.core.osce_views import build_rotation_schedule
        stations = [
            {'title': f'S{i}', 'is_active': True, 'duration_minutes': 8,
             'details': {'timing': {'study_minutes': 2 if i == 1 else 0, 'transition_minutes': 1}}}
            for i in range(1, 4)
        ] + [{'title': 'off', 'is_active': False, 'duration_minutes': 5, 'details': {}}]
        schedule = build_rotation_schedule(stations, {'start_time': '09:00', 'groups_count': 4})
        self.assertEqual(schedule['stations'], ['S1', 'S2', 'S3'])
        self.assertEqual(schedule['round_minutes'], 10)
        self.assertEqual(schedule['rows'][0]['cells'], ['09:00 - 09:10', '09:11 - 09:21', '09:22 - 09:32'])
        self.assertEqual(schedule['rows'][1]['cells'], ['09:22 - 09:32', '09:00 - 09:10', '09:11 - 09:21'])
        self.assertEqual(schedule['rows'][3]['circuit'], 2)
        self.assertEqual(schedule['rows'][3]['cells'][0], '09:33 - 09:43')
        self.assertEqual(schedule['end_time'], '10:05')
        self.assertIsNone(build_rotation_schedule(stations, {'start_time': '25:00', 'groups_count': 1}))

    def test_settings_tab_saves_exam_level_settings(self):
        osce_id = self._create_osce()
        bad = self._post_tab(osce_id, 'settings', self._settings_post(negative_mark='2', max_attempts='9', access_scope='all'))
        self.assertContains(bad, 'نمره منفی باید عددی بین ۰ و ۱ باشد.')
        self.assertContains(bad, 'محدودیت تعداد تلاش')
        response = self._post_tab(osce_id, 'settings', self._settings_post())
        self.assertEqual(response.status_code, 302)
        with connection.cursor() as cursor:
            cursor.execute('SELECT settings FROM osce_exams WHERE id = %s', [osce_id])
            exam = json.loads(cursor.fetchone()[0])['exam']
        self.assertEqual(exam['tags'], ['بالینی', 'ارتباطی'])
        self.assertTrue(exam['show_remaining_time'])
        self.assertFalse(exam['show_progress'])

    def test_publish_requires_complete_exam_and_locks_editing(self):
        osce_id = self._create_osce()
        preview_url = reverse('core:teacher_osce_preview', args=[osce_id])
        publish_url = reverse('core:teacher_osce_publish', args=[osce_id])
        self.assertContains(self.client.get(preview_url), 'دستورالعمل دانشجو ثبت نشده است')
        self.client.post(publish_url, {'action': 'publish'})
        with connection.cursor() as cursor:
            cursor.execute('SELECT status FROM osce_exams WHERE id = %s', [osce_id])
            self.assertEqual(cursor.fetchone()[0], 'draft')
        self._post_tab(osce_id, 'type', {'station_type': 'clinical', 'execution_mode': 'mannequin', 'assessment_method': 'checklist'})
        self._post_tab(osce_id, 'instructions', {'instructions_body': json.dumps({'ops': [{'insert': 'معاینه کنید\n'}]})})
        self._post_tab(osce_id, 'criteria', self._criteria_post(global_uid=[], global_text=[], global_points=[], global_guide=[]))
        self._post_tab(osce_id, 'timing', self._timing_post())
        self._post_tab(osce_id, 'settings', self._settings_post())
        self.assertContains(self.client.get(preview_url), 'آماده انتشار است')
        self.client.post(publish_url, {'action': 'publish'})
        with connection.cursor() as cursor:
            cursor.execute('SELECT status FROM osce_exams WHERE id = %s', [osce_id])
            self.assertEqual(cursor.fetchone()[0], 'published')
        self._post_tab(osce_id, 'basic', self._basic(title='تغییر بعد از انتشار'))
        self.assertEqual(self._stations(osce_id)[0][2], 'ارزیابی معاینه قلب')
        self.client.post(reverse('core:teacher_osce_station_add', args=[osce_id]))
        self.assertEqual(len(self._stations(osce_id)), 1)
        self.client.force_login(self.other_teacher_user)
        self.assertEqual(self.client.get(preview_url).status_code, 404)
        self.assertEqual(self.client.post(publish_url, {'action': 'unpublish'}).status_code, 404)
        self.client.force_login(self.teacher_user)
        self.client.post(publish_url, {'action': 'unpublish'})
        self._post_tab(osce_id, 'basic', self._basic(title='ویرایش پس از برگشت'))
        self.assertEqual(self._stations(osce_id)[0][2], 'ویرایش پس از برگشت')

    def test_legacy_osce_builder_redirects_to_new_builder(self):
        self.client.force_login(self.teacher_user)
        new_url = reverse('core:teacher_osce_create')
        self.assertRedirects(self.client.get(reverse('core:teacher_question_create') + '?type=osce'), new_url, fetch_redirect_response=False)
        response = self.client.post(reverse('core:teacher_question_create'), {'type': 'osce', 'text': 'ایستگاه قدیمی'})
        self.assertRedirects(response, new_url, fetch_redirect_response=False)
        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM questions WHERE text = 'ایستگاه قدیمی'")
            self.assertEqual(cursor.fetchone()[0], 0)
        self.assertContains(self.client.get(reverse('core:teacher_exams')), reverse('core:teacher_osce_list'))

    def test_template_library_is_shared_within_org_unit_only(self):
        colleague_id = self._make_profile('teacher_colleague', 'استاد همکار')
        _insert('teacher_profiles', ['user_id', 'org_unit_id'], [colleague_id, self.ou_scoped])
        _insert('user_roles', ['id', 'user_id', 'role'], [str(uuid.uuid4()), colleague_id, 'teacher'])
        colleague = get_user_model().objects.create_user(username='teacher_colleague', email='teacher_colleague@example.com', password='x')
        items = [{'text': 'معاینه ریه', 'type': 'binary', 'points': '2', 'required': False, 'guide': ''}]
        self.client.force_login(self.teacher_user)
        saved = self.client.post(reverse('core:teacher_osce_template_save'), json.dumps({'title': 'قالب ریه', 'items': items}), content_type='application/json')
        template = saved.json()['template']
        library_url = reverse('core:teacher_osce_template_library')

        self.client.force_login(colleague)
        self.assertEqual(self.client.get(library_url).json()['templates'], [])  # not shared yet
        self.assertEqual(self.client.post(template['share_url'], json.dumps({'shared': True}), content_type='application/json').status_code, 404)

        self.client.force_login(self.teacher_user)
        self.assertTrue(self.client.post(template['share_url'], json.dumps({'shared': True}), content_type='application/json').json()['shared'])
        self.assertEqual(self.client.get(library_url).json()['templates'], [])  # own templates are not listed

        self.client.force_login(colleague)
        shared = self.client.get(library_url).json()['templates']
        self.assertEqual([(item['title'], item['author']) for item in shared], [('قالب ریه', 'استاد داخل محدوده')])
        self.assertEqual(self.client.get(library_url, {'q': 'ریه'}).json()['templates'][0]['items'][0]['text'], 'معاینه ریه')
        self.assertEqual(self.client.get(library_url, {'q': 'قلب'}).json()['templates'], [])

        self.client.force_login(self.other_teacher_user)  # other org unit
        self.assertEqual(self.client.get(library_url).json()['templates'], [])


class RichTextTests(TestCase):
    def test_delta_to_html_escapes_text_and_filters_attributes(self):
        from apps.core.rich_text import clean_delta, delta_to_html
        delta = {'ops': [
            {'insert': 'سلام <b>', 'attributes': {'bold': True, 'color': 'red', 'script': 'x'}},
            {'insert': 'لینک', 'attributes': {'link': 'javascript:alert(1)'}},
            {'insert': 'خوب', 'attributes': {'link': 'https://example.com/?a="b"'}},
            {'insert': {'image': 'https://evil.example/x.png'}},
            {'insert': '\n', 'attributes': {'header': 1, 'align': 'center'}},
            {'insert': 'یک'}, {'insert': '\n', 'attributes': {'list': 'bullet'}},
            {'insert': 'دو'}, {'insert': '\n', 'attributes': {'list': 'bullet'}},
            {'insert': 'پایان\n'},
        ]}
        html = delta_to_html(delta)
        self.assertEqual(
            html,
            '<h3 style="text-align:center"><strong>سلام &lt;b&gt;</strong>لینک'
            '<a href="https://example.com/?a=&quot;b&quot;" target="_blank" rel="noopener noreferrer">خوب</a></h3>'
            '<ul><li>یک</li><li>دو</li></ul><p>پایان</p>',
        )
        self.assertEqual(clean_delta('not json'), {'ops': []})
        self.assertEqual(clean_delta({'ops': 'x'}), {'ops': []})


class EssayQuestionBuilderTests(_ScopedOrgFixture):
    """سؤال تشریحی: صورت سؤال قالب‌دار (Quill)، دستورالعمل دانشجو، پاسخ نمونه و نمایش برای مصحح."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.teacher_user = get_user_model().objects.create_user(username='teacher_in_scope', email='t_in@example.com', password='x')

    def _post_essay(self, **overrides):
        data = {
            'type': 'essay', 'structure': 'independent', 'course_id': self.course_in_id, 'is_published': '1',
            'text': '',
            'text_delta': json.dumps({'ops': [
                {'insert': 'نقش '}, {'insert': 'بارورفلکس', 'attributes': {'bold': True}}, {'insert': ' را توضیح دهید <b>\n'},
            ]}),
            'student_instructions': 'با استناد به منابع درسی پاسخ دهید.',
            'sample_answer_text': 'بارورفلکس با حس فشار...',
            'rubric_criterion': ['دقت علمی'], 'rubric_weak': ['نادرست'], 'rubric_average': ['ناقص'],
            'rubric_excellent': ['دقیق'], 'rubric_points': ['10'], 'default_points': '10',
            'answer_formats': ['text', 'file'],
        }
        data.update(overrides)
        return self.client.post(f"{reverse('core:teacher_question_create')}?type=essay", data)

    def _essay_row(self):
        with connection.cursor() as cursor:
            cursor.execute("SELECT id, text, scoring_settings FROM questions WHERE type = 'essay' AND teacher_id = %s", [self.teacher_in_id])
            row = cursor.fetchone()
        return row and (str(row[0]), row[1], json.loads(row[2]))

    def test_essay_saves_rich_stem_instructions_and_sample_answer(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        self.client.force_login(self.teacher_user)
        with self.settings(MEDIA_ROOT=tempfile.mkdtemp()):
            response = self._post_essay(sample_answer_file=SimpleUploadedFile('sample.pdf', b'%PDF-1.4 x', content_type='application/pdf'))
            self.assertEqual(response.status_code, 302)
            question_id, text, settings_data = self._essay_row()
            self.assertEqual(text, 'نقش بارورفلکس را توضیح دهید <b>')
            essay = settings_data['essay']
            self.assertEqual(settings_data['text_delta']['ops'][1]['attributes'], {'bold': True})
            self.assertEqual(essay['student_instructions'], 'با استناد به منابع درسی پاسخ دهید.')
            self.assertTrue(essay['sample_answer_file']['url'].startswith('/media/question-media/'))
            self.assertEqual(essay['answer_formats'], ['text', 'file'])
            page = self.client.get(reverse('core:teacher_question_edit', args=[question_id]))
            self.assertContains(page, 'با استناد به منابع درسی پاسخ دهید.')
            self.assertContains(page, 'sample.pdf')
            self.assertContains(page, 'id="question-text-delta"')

    def test_essay_rejects_bad_sample_file_and_long_instructions(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        self.client.force_login(self.teacher_user)
        with self.settings(MEDIA_ROOT=tempfile.mkdtemp()):
            response = self._post_essay(
                student_instructions='x' * 1001,
                sample_answer_file=SimpleUploadedFile('run.exe', b'MZ', content_type='application/octet-stream'),
            )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'دستورالعمل دانشجو حداکثر')
        self.assertContains(response, 'مجاز نیست')
        self.assertIsNone(self._essay_row())

    def test_grading_aid_and_student_view_render_escaped_rich_text(self):
        from types import SimpleNamespace
        from apps.core.views import _essay_view, _grading_aid
        self.client.force_login(self.teacher_user)
        self._post_essay()
        question_id, _text, settings_data = self._essay_row()
        student_view = _essay_view(settings_data)
        self.assertEqual(student_view['text_html'], '<p>نقش <strong>بارورفلکس</strong> را توضیح دهید &lt;b&gt;</p>')
        aid = _grading_aid(SimpleNamespace(legacy_erd_id=question_id))
        self.assertEqual(aid['rubric'][0]['criterion'], 'دقت علمی')
        self.assertEqual(aid['rubric_total'], '10')
        self.assertEqual(aid['sample_answer_text'], 'بارورفلکس با حس فشار...')
        self.assertIsNone(_grading_aid(SimpleNamespace(legacy_erd_id='')))

    def test_student_attempt_page_shows_points_time_and_no_navigation(self):
        question_id, attempt_id = str(uuid.uuid4()), str(uuid.uuid4())
        _insert('questions', ['id', 'teacher_id', 'text', 'type', 'default_points', 'suggested_time_seconds'], [question_id, self.teacher_in_id, 'تشخیص را بنویسید', 'short_answer', 1, 120])
        _insert('exam_questions', ['id', 'exam_id', 'question_id', 'points', 'order_index'], [str(uuid.uuid4()), self.exam_in_id, question_id, 2.5, 1])
        _insert('exam_attempts', ['id', 'exam_id', 'student_id', 'started_at', 'status'], [attempt_id, self.exam_in_id, self.student_in_id, timezone.now(), 'in_progress'])
        student = get_user_model().objects.create_user(username='student_in_scope', email='student_in_scope@example.com', password='x')
        self.client.force_login(student)
        page = self.client.get(reverse('core:student_attempt', args=[attempt_id])).content.decode()
        self.assertIn('۲.۵ نمره', page)  # exam_questions.points wins over the question's default
        self.assertIn('زمان پیشنهادی: ۲ دقیقه', page)
        self.assertIn('سؤال ۱ — پاسخ کوتاه', page)
        self.assertIn('data-connection', page)
        # No way out of the attempt from the header: no dashboard link.
        self.assertNotIn(f'href="{reverse("core:dashboard")}"', page)
        # The mark checkbox sits in the side card but still submits with the answer form.
        self.assertIn(f'name="mark_{question_id}" form="answer-form"', page)

    def test_finish_button_saves_the_answer_before_leaving(self):
        question_id, attempt_id = str(uuid.uuid4()), str(uuid.uuid4())
        _insert('questions', ['id', 'teacher_id', 'text', 'type', 'default_points'], [question_id, self.teacher_in_id, 'تشخیص را بنویسید', 'short_answer', 1])
        _insert('exam_questions', ['id', 'exam_id', 'question_id', 'points', 'order_index'], [str(uuid.uuid4()), self.exam_in_id, question_id, 1, 1])
        _insert('exam_attempts', ['id', 'exam_id', 'student_id', 'started_at', 'status'], [attempt_id, self.exam_in_id, self.student_in_id, timezone.now(), 'in_progress'])
        self.client.force_login(get_user_model().objects.create_user(username='student_in_scope', email='student_in_scope@example.com', password='x'))
        url = reverse('core:student_attempt', args=[attempt_id])
        self.assertContains(self.client.get(url), 'form="answer-form" name="action" value="finish"')
        response = self.client.post(url, {f'answer_{question_id}': 'گاستریت', 'action': 'finish'})
        self.assertRedirects(response, reverse('core:student_attempt_submit', args=[attempt_id]), fetch_redirect_response=False)
        with connection.cursor() as cursor:
            cursor.execute('SELECT answer FROM attempt_answers WHERE attempt_id = %s AND question_id = %s', [attempt_id, question_id])
            saved = cursor.fetchone()
        self.assertIsNotNone(saved)
        self.assertIn('گاستریت', saved[0] if isinstance(saved[0], str) else json.dumps(saved[0], ensure_ascii=False))

    def test_student_attempt_page_renders_fill_blank_answers_and_essay(self):
        """Regression: the essay block must not swallow the fill-blank answer refill."""
        fill_id, essay_id, attempt_id = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
        _insert('questions', ['id', 'teacher_id', 'text', 'type', 'default_points'], [fill_id, self.teacher_in_id, 'قلب [۱] حفره دارد', 'fill_blank', 1])
        _insert('questions', ['id', 'teacher_id', 'text', 'type', 'default_points', 'scoring_settings'], [
            essay_id, self.teacher_in_id, 'نقش بارورفلکس', 'essay', 5,
            json.dumps({'essay': {'text_delta': {'ops': [{'insert': 'نقش '}, {'insert': 'بارورفلکس', 'attributes': {'bold': True}}, {'insert': '\n'}]},
                                  'student_instructions': 'با منابع پاسخ دهید.'}}),
        ])
        _insert('exam_questions', ['id', 'exam_id', 'question_id', 'points', 'order_index'], [str(uuid.uuid4()), self.exam_in_id, fill_id, 1, 1])
        _insert('exam_questions', ['id', 'exam_id', 'question_id', 'points', 'order_index'], [str(uuid.uuid4()), self.exam_in_id, essay_id, 5, 2])
        _insert('exam_attempts', ['id', 'exam_id', 'student_id', 'started_at', 'status'], [attempt_id, self.exam_in_id, self.student_in_id, timezone.now(), 'in_progress'])
        _insert('attempt_answers', ['id', 'attempt_id', 'question_id', 'answer'], [str(uuid.uuid4()), attempt_id, fill_id, json.dumps({'value': ['چهار']})])
        student = get_user_model().objects.create_user(username='student_in_scope', email='student_in_scope@example.com', password='x')
        self.client.force_login(student)
        url = reverse('core:student_attempt', args=[attempt_id])
        fill_page = self.client.get(url + '?q=1')
        self.assertEqual(fill_page.status_code, 200)
        self.assertContains(fill_page, 'value="چهار"')
        essay_page = self.client.get(url + '?q=2')
        self.assertEqual(essay_page.status_code, 200)
        self.assertContains(essay_page, '<strong>بارورفلکس</strong>', html=False)
        self.assertContains(essay_page, 'با منابع پاسخ دهید.')

    def test_student_attempt_renders_rich_fill_blank_and_media_hints(self):
        fill_id, attempt_id = str(uuid.uuid4()), str(uuid.uuid4())
        hint = '/media/question-media/skull.png'
        _insert('questions', ['id', 'teacher_id', 'text', 'type', 'default_points', 'scoring_settings', 'accepted_answers'], [
            fill_id, self.teacher_in_id, 'جمجمه [۱] و [۲]', 'fill_blank', 1,
            json.dumps({'text_delta': {'ops': [{'insert': 'جمجمه', 'attributes': {'bold': True}}, {'insert': ' [۱] و [۲]\n'}]}}),
            json.dumps([{'blank': 1, 'answers': ['نوروکرانیوم'], 'media': ''}, {'blank': 2, 'answers': ['ویسروکرانیوم'], 'media': hint}]),
        ])
        _insert('exam_questions', ['id', 'exam_id', 'question_id', 'points', 'order_index'], [str(uuid.uuid4()), self.exam_in_id, fill_id, 1, 1])
        _insert('exam_attempts', ['id', 'exam_id', 'student_id', 'started_at', 'status'], [attempt_id, self.exam_in_id, self.student_in_id, timezone.now(), 'in_progress'])
        _insert('attempt_answers', ['id', 'attempt_id', 'question_id', 'answer'], [str(uuid.uuid4()), attempt_id, fill_id, json.dumps({'value': ['پاسخ', '']})])
        student = get_user_model().objects.create_user(username='student_in_scope', email='student_in_scope@example.com', password='x')
        self.client.force_login(student)
        page = self.client.get(reverse('core:student_attempt', args=[attempt_id]) + '?q=1').content.decode()
        self.assertIn('qx-fillblank--rich', page)
        self.assertIn('<strong>جمجمه</strong>', page)
        self.assertEqual(page.count(f'name="answer_{fill_id}"'), 2)
        self.assertIn('value="پاسخ"', page)
        self.assertIn(f'<img src="{hint}"', page)
        # The hint list is built from accepted_answers, but the accepted answers themselves never reach the page.
        self.assertNotIn('نوروکرانیوم', page)
        self.assertNotIn('ویسروکرانیوم', page)

    def test_essay_requires_an_answer_format(self):
        self.client.force_login(self.teacher_user)
        response = self._post_essay(answer_formats=[])
        self.assertContains(response, 'حداقل یک قالب پاسخ')
        self.assertIsNone(self._essay_row())

    def test_rich_stem_is_saved_and_seeded_for_all_independent_types(self):
        from apps.core.views import _question_form_data
        self.client.force_login(self.teacher_user)
        delta = {'ops': [{'insert': 'کدام '}, {'insert': 'صحیح', 'attributes': {'italic': True}}, {'insert': ' است؟'}, {'insert': '\n'}]}
        response = self.client.post(f"{reverse('core:teacher_question_create')}?type=single", {
            'type': 'single', 'structure': 'independent', 'course_id': self.course_in_id, 'text': '', 'text_delta': json.dumps(delta),
            'option_text': ['الف', 'ب'], 'correct_options': ['1'],
        })
        self.assertEqual(response.status_code, 302)
        with connection.cursor() as cursor:
            cursor.execute("SELECT text, scoring_settings FROM questions WHERE type = 'single' AND teacher_id = %s", [self.teacher_in_id])
            text, settings_data = cursor.fetchone()
        self.assertEqual(text, 'کدام صحیح است؟')
        self.assertEqual(json.loads(settings_data)['text_delta'], delta)
        # Fill-in-the-blank now has the rich editor too; a legacy plain stem seeds it with its [n] markers.
        self.assertEqual(_question_form_data({'type': 'fill_blank', 'text': 'قلب [۱]', 'scoring_settings': {}})['text_delta'], {'ops': [{'insert': 'قلب [۱]\n'}]})

    def test_fill_blank_rich_stem_saves_and_renders_inputs_for_markers(self):
        from apps.core.views import _fill_blank_stem_html
        self.client.force_login(self.teacher_user)
        delta = {'ops': [{'insert': 'جمجمه از '}, {'insert': 'دو بخش', 'attributes': {'bold': True}}, {'insert': ' [۱] و [۲] است.\n'}]}
        response = self.client.post(f"{reverse('core:teacher_question_create')}?type=fill_blank", {
            'type': 'fill_blank', 'structure': 'independent', 'course_id': self.course_in_id, 'text': '', 'text_delta': json.dumps(delta),
            'blank_count': '2', 'blank_answers_1': 'نوروکرانیوم', 'blank_answers_2': 'ویسروکرانیوم',
        })
        self.assertEqual(response.status_code, 302)
        with connection.cursor() as cursor:
            cursor.execute("SELECT text, scoring_settings FROM questions WHERE type = 'fill_blank' AND teacher_id = %s", [self.teacher_in_id])
            text, settings_data = cursor.fetchone()
        self.assertEqual(text, 'جمجمه از دو بخش [۱] و [۲] است.')
        html = _fill_blank_stem_html(json.loads(settings_data), text, 'q1', ['نورو<x>', ''])
        self.assertIn('<strong>دو بخش</strong>', html)
        self.assertEqual(html.count('class="qx-blank"'), 2)
        self.assertIn('value="نورو&lt;x&gt;"', html)
        self.assertNotIn('[۱]', html)
        # A marker split by formatting no longer matches the plain text: fall back to the plain segments.
        split = {'text_delta': {'ops': [{'insert': 'قلب [۱'}, {'insert': ']', 'attributes': {'bold': True}}, {'insert': '\n'}]}}
        self.assertEqual(_fill_blank_stem_html(split, 'قلب [۱]', 'q1', []), '')

    def test_legacy_plain_essay_seeds_the_editor(self):
        from apps.core.views import _question_form_data
        form = _question_form_data({'type': 'essay', 'text': 'سؤال قدیمی', 'scoring_settings': {}})
        self.assertEqual(form['text_delta'], {'ops': [{'insert': 'سؤال قدیمی\n'}]})


class EssayAnswerFlowTests(_ScopedOrgFixture):
    """پیوست پاسخ تشریحی توسط دانشجو، دسترسی محدود به فایل‌ها و تصحیح واقعی با روبریک."""

    PNG = b'\x89PNG\r\n\x1a\n' + b'0' * 32

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        User = get_user_model()
        cls.teacher_user = User.objects.create_user(username='teacher_in_scope', email='t_in@example.com', password='x')
        cls.other_teacher_user = User.objects.create_user(username='teacher_out_scope', email='t_out@example.com', password='x')
        cls.student_user = User.objects.create_user(username='student_in_scope', email='student_in_scope@example.com', password='x')
        cls.other_student_user = User.objects.create_user(username='student_out_scope', email='student_out_scope@example.com', password='x')
        cls.question_id, cls.attempt_id = str(uuid.uuid4()), str(uuid.uuid4())
        _insert('questions', ['id', 'teacher_id', 'text', 'type', 'default_points', 'rubric', 'scoring_settings'], [
            cls.question_id, cls.teacher_in_id, 'سازوکار بارورفلکس را توضیح دهید', 'essay', 5,
            json.dumps([{'criterion': 'دقت علمی', 'points': '6'}, {'criterion': 'ساختار', 'points': '4'}]),
            json.dumps({'essay': {'answer_formats': ['text', 'image', 'file'], 'sample_answer_text': 'پاسخ مرجع'}}),
        ])
        _insert('exam_questions', ['id', 'exam_id', 'question_id', 'points', 'order_index'], [str(uuid.uuid4()), cls.exam_in_id, cls.question_id, 5, 1])
        _insert('exam_attempts', ['id', 'exam_id', 'student_id', 'started_at', 'status'], [cls.attempt_id, cls.exam_in_id, cls.student_in_id, timezone.now(), 'in_progress'])

    def setUp(self):
        self.private_root = tempfile.mkdtemp()
        override = self.settings(PRIVATE_MEDIA_ROOT=self.private_root)
        override.enable()
        self.addCleanup(override.disable)

    def _upload(self, **files):
        from django.core.files.uploadedfile import SimpleUploadedFile
        data = {f'answer_{self.question_id}': 'متن پاسخ'}
        for kind, (name, content) in files.items():
            data[f'upload_{self.question_id}_{kind}'] = SimpleUploadedFile(name, content)
        return self.client.post(reverse('core:student_attempt', args=[self.attempt_id]), data)

    def _files(self):
        with connection.cursor() as cursor:
            cursor.execute('SELECT answer_files FROM attempt_answers WHERE attempt_id = %s AND question_id = %s', [self.attempt_id, self.question_id])
            row = cursor.fetchone()
        return json.loads(row[0]) if row else []

    def _submit(self):
        with connection.cursor() as cursor:
            cursor.execute("UPDATE exam_attempts SET submitted_at = %s, status = 'submitted' WHERE id = %s", [timezone.now(), self.attempt_id])
            cursor.execute('UPDATE attempt_answers SET needs_manual_grading = %s WHERE attempt_id = %s', [True, self.attempt_id])

    def test_student_uploads_only_allowed_validated_files(self):
        self.client.force_login(self.student_user)
        self._upload(image=('scan.png', self.PNG), video=('clip.mp4', b'\x00\x00\x00\x18ftypmp42'))
        files = self._files()
        self.assertEqual([(item['kind'], item['name']) for item in files], [('image', 'scan.png')])  # video not allowed here
        from pathlib import Path
        self.assertTrue((Path(self.private_root) / files[0]['path']).is_file())
        response = self._upload(file=('notes.pdf', b'MZ not a pdf'))
        self.assertEqual(len(self._files()), 1)
        self.assertEqual(response.status_code, 302)
        page = self.client.get(response['Location'])
        self.assertContains(page, 'با پسوند آن هم‌خوانی ندارد')
        from django.core.files.uploadedfile import SimpleUploadedFile
        self.client.post(reverse('core:student_attempt', args=[self.attempt_id]), {
            f'upload_{self.question_id}_image': SimpleUploadedFile('x.png', self.PNG),
        }, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(len(self._files()), 1)  # autosave never stores files
        self.client.post(reverse('core:student_attempt', args=[self.attempt_id]), {f'remove_file_{self.question_id}': files[0]['id']})
        self.assertEqual(self._files(), [])
        self.assertFalse((Path(self.private_root) / files[0]['path']).exists())

    def _answer(self, question_id):
        with connection.cursor() as cursor:
            cursor.execute('SELECT answer FROM attempt_answers WHERE attempt_id = %s AND question_id = %s', [self.attempt_id, question_id])
            row = cursor.fetchone()
        return json.loads(row[0])['value'] if row else None

    def test_finishing_grading_on_a_published_exam_notifies_the_student_once(self):
        self.client.force_login(self.student_user)
        self._upload()
        self._submit()
        with connection.cursor() as cursor:
            cursor.execute('UPDATE exams SET results_published_at = %s WHERE id = %s', [timezone.now(), self.exam_in_id])
            cursor.execute('SELECT id FROM attempt_answers WHERE attempt_id = %s', [self.attempt_id])
            detail_url = reverse('core:teacher_grading_detail', args=[str(cursor.fetchone()[0])])
        self.client.force_login(self.teacher_user)
        self.client.post(detail_url, {'score_0': '6', 'score_1': '2'})
        self.client.post(detail_url, {'score_0': '5', 'score_1': '2'})  # a later correction sends nothing new
        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM notifications WHERE user_id = %s AND type = 'exam_results'", [self.student_in_id])
            self.assertEqual(cursor.fetchone()[0], 1)

    def test_grading_failure_is_logged_and_the_submission_kept(self):
        from unittest import mock
        self.client.force_login(self.student_user)
        with mock.patch('apps.core.views.grade_attempt', side_effect=RuntimeError('boom')), \
                self.assertLogs('apps.core.views', level='ERROR') as logs:
            self.client.post(reverse('core:student_attempt_submit', args=[self.attempt_id]), {f'answer_{self.question_id}': 'متن پاسخ'})
        self.assertIn(self.attempt_id, logs.output[0])
        with connection.cursor() as cursor:
            cursor.execute('SELECT status, submitted_at FROM exam_attempts WHERE id = %s', [self.attempt_id])
            status, submitted_at = cursor.fetchone()
        self.assertEqual(status, 'submitted')
        self.assertIsNotNone(submitted_at)
        self.assertEqual(self._answer(self.question_id), 'متن پاسخ')

    def test_unmatched_short_answer_reaches_teacher_grading_queue(self):
        short_id = str(uuid.uuid4())
        _insert('questions', ['id', 'teacher_id', 'text', 'type', 'default_points', 'accepted_answers'], [
            short_id, self.teacher_in_id, 'داروی انتخابی برادی‌کاردی علامت‌دار؟', 'short_answer', 2,
            json.dumps([{'answer': 'آتروپین', 'points': '100', 'match_mode': 'exact'}]),
        ])
        _insert('exam_questions', ['id', 'exam_id', 'question_id', 'points', 'order_index'], [str(uuid.uuid4()), self.exam_in_id, short_id, 2, 2])
        self.client.force_login(self.student_user)
        self.client.post(reverse('core:student_attempt_submit', args=[self.attempt_id]), {
            f'answer_{self.question_id}': 'متن پاسخ', f'answer_{short_id}': 'اپی‌نفرین با دوز بالا',
        })
        with connection.cursor() as cursor:
            cursor.execute('SELECT id, needs_manual_grading FROM attempt_answers WHERE attempt_id = %s AND question_id = %s', [self.attempt_id, short_id])
            answer_id, pending = cursor.fetchone()
        self.assertTrue(pending)

        self.client.force_login(self.teacher_user)
        self.assertContains(self.client.get(reverse('core:teacher_reviews')), 'داروی انتخابی برادی‌کاردی')
        detail_url = reverse('core:teacher_grading_detail', args=[str(answer_id)])
        page = self.client.get(detail_url)
        self.assertContains(page, 'تصحیح پاسخ کوتاه')
        self.assertContains(page, 'اپی‌نفرین با دوز بالا')
        self.assertContains(page, 'آتروپین')  # the teacher's accepted answer as grading reference
        self.client.post(detail_url, {'score': '0.5'})
        with connection.cursor() as cursor:
            cursor.execute('SELECT points_awarded, needs_manual_grading FROM attempt_answers WHERE id = %s', [answer_id])
            points, pending = cursor.fetchone()
        self.assertEqual((float(points), bool(pending)), (0.5, False))

        self.client.force_login(self.other_teacher_user)
        self.assertEqual(self.client.get(detail_url).status_code, 404)

    def test_answers_only_for_own_exam_questions_and_only_before_submission(self):
        url = reverse('core:student_attempt', args=[self.attempt_id])
        self.client.force_login(self.student_user)
        self.client.post(url, {f'answer_{self.question_id}': 'پاسخ اول', f'answer_{self.question_in_id}': 'نفوذ'})
        self.assertEqual(self._answer(self.question_id), 'پاسخ اول')
        self.assertIsNone(self._answer(self.question_in_id))  # question exists but is not part of this exam
        self.client.post(url, {f'answer_{self.question_id}': 'تغییر خودکار'}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(self._answer(self.question_id), 'تغییر خودکار')
        self._submit()
        self.client.post(url, {f'answer_{self.question_id}': 'تغییر پس از ارسال'})
        self.client.post(url, {f'answer_{self.question_id}': 'تغییر پس از ارسال'}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.client.post(reverse('core:student_attempt_submit', args=[self.attempt_id]), {f'answer_{self.question_id}': 'تغییر پس از ارسال'})
        self.assertEqual(self._answer(self.question_id), 'تغییر خودکار')

    def _started(self, minutes_ago, seconds_ago=0):
        from datetime import timedelta
        with connection.cursor() as cursor:
            cursor.execute('UPDATE exam_attempts SET started_at = %s WHERE id = %s',
                           [timezone.now() - timedelta(minutes=minutes_ago, seconds=seconds_ago), self.attempt_id])

    def test_answers_are_refused_after_the_time_limit(self):
        url = reverse('core:student_attempt', args=[self.attempt_id])
        self.client.force_login(self.student_user)
        self._started(90, 30)  # exam has no duration -> 90 minutes; still inside the 60s grace
        self.client.post(url, {f'answer_{self.question_id}': 'در مهلت'}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(self._answer(self.question_id), 'در مهلت')
        self._started(92)
        late = self.client.post(url, {f'answer_{self.question_id}': 'دیرهنگام'}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(late.status_code, 409)
        response = self.client.post(url, {f'answer_{self.question_id}': 'دیرهنگام'})
        self.assertRedirects(response, reverse('core:student_attempt_submit', args=[self.attempt_id]), fetch_redirect_response=False)
        self._upload(image=('late.png', self.PNG))
        self.client.post(reverse('core:student_attempt_submit', args=[self.attempt_id]), {f'answer_{self.question_id}': 'دیرهنگام'})
        self.assertEqual(self._answer(self.question_id), 'در مهلت')
        self.assertEqual(self._files(), [])

    def test_uploads_are_refused_after_submission(self):
        self.client.force_login(self.student_user)
        self._submit()
        self._upload(image=('late.png', self.PNG))
        self.assertEqual(self._files(), [])

    def test_answer_file_access_is_limited_to_student_and_grading_teacher(self):
        self.client.force_login(self.student_user)
        self._upload(image=('scan.png', self.PNG))
        url = reverse('core:attempt_answer_file', args=[self.attempt_id, self._files()[0]['id']])
        self.assertEqual(self.client.get(url).status_code, 200)
        self.client.force_login(self.teacher_user)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['X-Content-Type-Options'], 'nosniff')
        for user in (self.other_teacher_user, self.other_student_user):
            self.client.force_login(user)
            self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.get(reverse('core:attempt_answer_file', args=[self.attempt_id, '..'])).status_code, 404)

    def test_teacher_grades_with_rubric_and_attempt_score_updates(self):
        self.client.force_login(self.student_user)
        self._upload(image=('scan.png', self.PNG))
        self._submit()
        with connection.cursor() as cursor:
            cursor.execute('SELECT id FROM attempt_answers WHERE attempt_id = %s', [self.attempt_id])
            answer_id = str(cursor.fetchone()[0])
        detail_url = reverse('core:teacher_grading_detail', args=[answer_id])

        self.client.force_login(self.other_teacher_user)
        self.assertNotContains(self.client.get(reverse('core:teacher_reviews')), 'سازوکار بارورفلکس')
        self.assertEqual(self.client.get(detail_url).status_code, 404)
        self.assertEqual(self.client.post(detail_url, {'score_0': '6', 'score_1': '4'}).status_code, 404)

        self.client.force_login(self.teacher_user)
        self.assertContains(self.client.get(reverse('core:teacher_reviews')), 'سازوکار بارورفلکس')
        page = self.client.get(detail_url)
        self.assertContains(page, 'متن پاسخ')
        self.assertContains(page, 'scan.png')
        self.assertContains(page, 'پاسخ مرجع')
        bad = self.client.post(detail_url, {'score_0': '9', 'score_1': '2'})
        self.assertEqual(bad.status_code, 200)
        self.assertContains(bad, 'باید بین ۰ و 6 باشد')
        self.client.post(detail_url, {'score_0': '6', 'score_1': '2', 'feedback': 'ساختار ضعیف بود'})
        with connection.cursor() as cursor:
            cursor.execute('SELECT points_awarded, needs_manual_grading, grader_feedback FROM attempt_answers WHERE id = %s', [answer_id])
            points, pending, feedback = cursor.fetchone()
            cursor.execute('SELECT score, status, is_graded FROM exam_attempts WHERE id = %s', [self.attempt_id])
            score, status, is_graded = cursor.fetchone()
        self.assertEqual(float(points), 4.0)  # 8 of 10 rubric points scaled to the question's 5 exam points
        self.assertFalse(pending)
        self.assertEqual(feedback, 'ساختار ضعیف بود')
        self.assertEqual((float(score), status, bool(is_graded)), (4.0, 'graded', True))


class QuestionTypesV2Tests(_ScopedOrgFixture):
    """سؤال‌های پاسخ عددی، ماتریسی، تصویری/نشانه‌گذاری و صوتی/ویدئویی: سازنده، تصحیح و صفحه‌ی آزمون دانشجو."""

    PNG = b'\x89PNG\r\n\x1a\n' + b'0' * 32
    MP3 = b'ID3' + b'0' * 32

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        User = get_user_model()
        cls.teacher_user = User.objects.create_user(username='teacher_in_scope', email='t_in@example.com', password='x')
        cls.student_user = User.objects.create_user(username='student_in_scope', email='student_in_scope@example.com', password='x')

    def setUp(self):
        for override in (self.settings(MEDIA_ROOT=tempfile.mkdtemp()), self.settings(PRIVATE_MEDIA_ROOT=tempfile.mkdtemp())):
            override.enable()
            self.addCleanup(override.disable)

    def _create(self, qtype, data):
        payload = {'type': qtype, 'structure': 'independent', 'course_id': self.course_in_id, 'is_published': '1', 'default_points': '2'}
        payload.update(data)
        return self.client.post(f"{reverse('core:teacher_question_create')}?type={qtype}", payload)

    def _row(self, text):
        with connection.cursor() as cursor:
            cursor.execute('SELECT id, type, options, correct_answer, accepted_answers, scoring_settings, rubric, question_media FROM questions WHERE text = %s', [text])
            row = cursor.fetchone()
        if not row:
            return None
        load = lambda value: json.loads(value) if isinstance(value, str) and value else value
        return {'id': row[0], 'type': row[1], 'options': load(row[2]), 'correct_answer': load(row[3]), 'accepted_answers': load(row[4]),
                'scoring_settings': load(row[5]), 'rubric': load(row[6]), 'question_media': load(row[7])}

    def _attempt(self, question_columns, answer_value=None):
        question_id, attempt_id = str(uuid.uuid4()), str(uuid.uuid4())
        columns = {'type': 'numeric', **question_columns}
        _insert('questions', ['id', 'teacher_id', 'course_id', 'text', 'default_points'] + list(columns),
                [question_id, self.teacher_in_id, self.course_in_id, 'سؤال نوع جدید', 2] + [
                    json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value for value in columns.values()])
        exam_id = str(uuid.uuid4())
        _insert('exams', ['id', 'title', 'teacher_id', 'course_id', 'start_at'], [exam_id, 'آزمون نوع جدید', self.teacher_in_id, self.course_in_id, timezone.now()])
        _insert('exam_questions', ['id', 'exam_id', 'question_id', 'points', 'order_index'], [str(uuid.uuid4()), exam_id, question_id, 2, 1])
        _insert('exam_attempts', ['id', 'exam_id', 'student_id', 'started_at', 'status'], [attempt_id, exam_id, self.student_in_id, timezone.now(), 'in_progress'])
        if answer_value is not None:
            _insert('attempt_answers', ['id', 'attempt_id', 'question_id', 'answer', 'needs_manual_grading'],
                    [str(uuid.uuid4()), attempt_id, question_id, json.dumps({'value': answer_value}, ensure_ascii=False), False])
        return question_id, attempt_id

    def _score(self, question_columns, answer_value):
        from apps.core.views import grade_attempt
        _question_id, attempt_id = self._attempt(question_columns, answer_value)
        return grade_attempt(attempt_id)

    # ----- builder -----

    def test_builder_pages_render_for_new_types_and_picker_links_them(self):
        from apps.core.views import _sx_type_label
        self.client.force_login(self.teacher_user)
        url = reverse('core:teacher_question_create')
        markers = {'numeric': 'name="numeric_answer"', 'matrix': 'data-matrix-table', 'image_label': 'data-label-canvas', 'media_response': 'name="media_max_plays"'}
        for kind, marker in markers.items():
            html = self.client.get(f'{url}?type={kind}').content.decode()
            self.assertIn(marker, html, kind)
            self.assertIn(f'سؤال ۱ — {_sx_type_label(kind)}', html, kind)
            self.assertIn('js/question-types-v2', html, kind)
        picker = self.client.get(reverse('core:teacher_question_type')).content.decode()
        for kind in markers:
            self.assertIn(f'?type={kind}"', picker, kind)
        self.assertIn('نقطه‌ای / مربوط به تصویر', picker)  # hotspot stays «در حال توسعه»

    def test_numeric_question_saves_tolerance_and_reloads_in_edit_form(self):
        self.client.force_login(self.teacher_user)
        response = self._create('numeric', {
            'text': 'حجم دارو را محاسبه کنید', 'numeric_answer': '۵', 'numeric_unit': 'mL', 'numeric_decimals': '1',
            'numeric_tolerance_mode': 'absolute', 'numeric_tolerance': '0.1', 'numeric_accept_persian': '1', 'numeric_require_unit': '1',
        })
        self.assertEqual(response.status_code, 302)
        row = self._row('حجم دارو را محاسبه کنید')
        self.assertEqual(row['type'], 'numeric')
        self.assertEqual(row['correct_answer'], '5')
        numeric = row['scoring_settings']['numeric']
        self.assertEqual((numeric['value'], numeric['unit'], numeric['tolerance'], numeric['require_unit']), (5.0, 'mL', 0.1, True))
        edit = self.client.get(reverse('core:teacher_question_edit', args=[row['id']])).content.decode()
        self.assertIn('name="numeric_answer" value="5"', edit)
        self.assertIn('name="numeric_unit" value="mL"', edit)

    def test_numeric_question_validation(self):
        self.client.force_login(self.teacher_user)
        response = self._create('numeric', {'text': 'عدد نامعتبر', 'numeric_answer': 'پنج', 'numeric_require_unit': '1'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'پاسخ صحیح عددی را به‌صورت عدد وارد کنید.')
        self.assertContains(response, 'واحد پاسخ را وارد کنید')
        self.assertIsNone(self._row('عدد نامعتبر'))

    def test_matrix_question_saves_rows_with_server_ids(self):
        self.client.force_login(self.teacher_user)
        data = {
            'columns': [{'id': 'cx', 'text': 'پرکاری تیروئید'}, {'id': 'cy', 'text': 'کم‌کاری تیروئید'}],
            'rows': [
                {'id': 'ra', 'text': 'تاکی‌کاردی', 'points': 1, 'correct': ['cx']},
                {'id': 'rb', 'text': 'افزایش وزن', 'points': 2, 'correct': ['cy', 'bogus']},
            ],
        }
        response = self._create('matrix', {'text': 'علائم تیروئید', 'matrix_json': json.dumps(data, ensure_ascii=False),
                                           'matrix_selection': 'single', 'matrix_show_column_titles': '1', 'scoring_mode': 'partial'})
        self.assertEqual(response.status_code, 302)
        row = self._row('علائم تیروئید')
        self.assertEqual([(item['id'], item['correct'], item['points']) for item in row['options']], [('r1', ['c1'], 1.0), ('r2', ['c2'], 2.0)])
        self.assertEqual(row['correct_answer'], ['r1:c1', 'r2:c2'])
        self.assertEqual(row['scoring_settings']['matrix']['columns'][0], {'id': 'c1', 'text': 'پرکاری تیروئید'})

    def test_matrix_validation(self):
        self.client.force_login(self.teacher_user)
        data = {'columns': [{'id': 'a', 'text': 'الف'}], 'rows': [{'id': 'r', 'text': 'سطر', 'correct': []}]}
        response = self._create('matrix', {'text': 'ماتریس ناقص', 'matrix_json': json.dumps(data), 'matrix_selection': 'single'})
        self.assertContains(response, 'حداقل دو ستون با عنوان وارد کنید.')
        self.assertContains(response, 'حداقل دو سطر با متن وارد کنید.')
        self.assertContains(response, 'برای هر سطر پاسخ صحیح را در جدول مشخص کنید.')
        two = {'columns': [{'id': 'a', 'text': 'الف'}, {'id': 'b', 'text': 'ب'}],
               'rows': [{'id': 'r1', 'text': 'یک', 'correct': ['a', 'b']}, {'id': 'r2', 'text': 'دو', 'correct': ['a']}]}
        response = self._create('matrix', {'text': 'ماتریس تک‌گزینه‌ای', 'matrix_json': json.dumps(two), 'matrix_selection': 'single'})
        self.assertContains(response, 'در حالت تک‌گزینه‌ای هر سطر فقط یک پاسخ صحیح دارد.')
        self.assertIsNone(self._row('ماتریس تک‌گزینه‌ای'))

    def test_image_label_requires_image_and_saves_markers(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        self.client.force_login(self.teacher_user)
        markers = [{'x': 40.5, 'y': 20, 'answer': 'آئورت', 'synonyms': 'آئورت صعودی، سرخرگ آئورت', 'points': 1},
                   {'x': 150, 'y': 70, 'answer': 'بطن چپ', 'synonyms': '', 'points': 2}]
        response = self._create('image_label', {'text': 'بخش‌های قلب', 'label_markers_json': json.dumps(markers, ensure_ascii=False)})
        self.assertContains(response, 'تصویر سؤال را برای نشانه‌گذاری بارگذاری کنید.')
        response = self._create('image_label', {
            'text': 'بخش‌های قلب', 'label_markers_json': json.dumps(markers, ensure_ascii=False), 'label_answer_mode': 'drag',
            'label_accept_synonyms': '1', 'question_image_file': SimpleUploadedFile('heart.png', self.PNG, content_type='image/png'),
        })
        self.assertEqual(response.status_code, 302)
        row = self._row('بخش‌های قلب')
        self.assertTrue(row['question_media']['image'].endswith('.png'))
        self.assertEqual([(m['marker'], m['x'], m['answer'], m['synonyms']) for m in row['accepted_answers']],
                         [(1, 40.5, 'آئورت', ['آئورت صعودی', 'سرخرگ آئورت']), (2, 100.0, 'بطن چپ', [])])
        self.assertEqual(row['scoring_settings']['image_label'], {'answer_mode': 'drag', 'accept_synonyms': True})

    def test_media_response_requires_media_and_saves_playback_rubric_and_attachment(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        self.client.force_login(self.teacher_user)
        base = {
            'text': 'صدای قلب را توضیح دهید', 'media_allow_replay': '1', 'media_range_start': '00:10', 'media_range_end': '00:40',
            'media_max_plays': '3', 'media_transcript': 'صدای قلب بیمار ۶۵ ساله', 'media_show_transcript': '1',
            'answer_formats': ['audio', 'text', 'image'], 'media_max_record_seconds': '120',
            'media_rubric_criterion': ['تشخیص صدا', 'استدلال بالینی'], 'media_rubric_description': ['شناسایی سوفل', 'ارتباط با بیمار'],
            'media_rubric_points': ['2', '3'],
        }
        response = self._create('media_response', base)
        self.assertContains(response, 'فایل صوتی یا ویدئویی سؤال را بارگذاری کنید.')
        response = self._create('media_response', {**base, 'media_range_end': '00:05'})
        self.assertContains(response, 'پایان بازه‌ی مجاز پخش باید بعد از شروع آن باشد.')
        bad = SimpleUploadedFile('notes.exe', b'MZ')
        response = self._create('media_response', {**base, 'question_audio_file': SimpleUploadedFile('heart.mp3', self.MP3), 'media_attachment_file': bad})
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(self._row('صدای قلب را توضیح دهید'))
        response = self._create('media_response', {
            **base, 'question_audio_file': SimpleUploadedFile('heart.mp3', self.MP3),
            'media_attachment_file': SimpleUploadedFile('guide.pdf', b'%PDF-1.4 test'),
        })
        self.assertEqual(response.status_code, 302)
        row = self._row('صدای قلب را توضیح دهید')
        media = row['scoring_settings']['media_response']
        self.assertEqual((media['range_start'], media['range_end'], media['max_plays'], media['max_record_seconds']), (10, 40, 3, 120))
        self.assertEqual(media['attachment']['name'], 'guide.pdf')
        self.assertEqual(row['scoring_settings']['essay']['answer_formats'], ['text', 'audio'])  # image is not offered here
        self.assertEqual([(item['criterion'], item['points']) for item in row['rubric']], [('تشخیص صدا', '2'), ('استدلال بالینی', '3')])
        edit = self.client.get(reverse('core:teacher_question_edit', args=[row['id']])).content.decode()
        self.assertIn('name="media_range_start" value="00:10"', edit)
        self.assertIn('guide.pdf', edit)

    # ----- grading -----

    def test_numeric_grading_tolerance_digits_and_unit(self):
        numeric = {'value': 5, 'unit': 'mL', 'tolerance_mode': 'absolute', 'tolerance': 0.1, 'accept_persian_digits': True, 'require_unit': False}
        settings_of = lambda **changes: {'scoring_settings': {'numeric': {**numeric, **changes}}}
        self.assertEqual(self._score(settings_of(), '5.08')['score'], 2)
        self.assertEqual(self._score(settings_of(), '۵٫۰۵')['score'], 2)
        self.assertEqual(self._score(settings_of(), '5.2')['score'], 0)
        self.assertEqual(self._score(settings_of(accept_persian_digits=False), '۵')['score'], 0)
        self.assertEqual(self._score(settings_of(tolerance_mode='percent', tolerance=10), '5.4')['score'], 2)
        self.assertEqual(self._score(settings_of(require_unit=True), ['5', 'ml'])['score'], 2)
        self.assertEqual(self._score(settings_of(require_unit=True), ['5', 'L'])['score'], 0)
        self.assertEqual(self._score(settings_of(require_unit=True), '5')['score'], 0)

    def test_matrix_grading_full_partial_and_all_or_nothing(self):
        rows = [{'id': 'r1', 'text': 'الف', 'points': 1, 'correct': ['c1']}, {'id': 'r2', 'text': 'ب', 'points': 3, 'correct': ['c2']}]
        question = lambda mode: {'type': 'matrix', 'options': rows, 'scoring_settings': {'scoring_mode': mode, 'matrix': {'columns': [{'id': 'c1'}, {'id': 'c2'}]}}}
        self.assertEqual(self._score(question('partial'), 'r1:c1,r2:c2')['score'], 2)
        self.assertEqual(self._score(question('partial'), 'r1:c2,r2:c2')['score'], 1.5)  # 3 of 4 row weight
        self.assertEqual(self._score(question('all_or_nothing'), 'r1:c2,r2:c2')['score'], 0)
        self.assertEqual(self._score(question('partial'), 'r1:c1,r1:c2,r2:c2')['score'], 1.5)  # extra pick breaks row 1

    def test_image_label_grading_synonyms_and_partial(self):
        markers = [{'marker': 1, 'x': 10, 'y': 10, 'answer': 'آئورت', 'synonyms': ['سرخرگ آئورت'], 'points': 1},
                   {'marker': 2, 'x': 50, 'y': 50, 'answer': 'بطن چپ', 'synonyms': [], 'points': 1}]
        question = lambda synonyms, mode='partial': {'type': 'image_label', 'accepted_answers': markers,
                                                     'scoring_settings': {'scoring_mode': mode, 'image_label': {'accept_synonyms': synonyms}}}
        self.assertEqual(self._score(question(True), ['سرخرگ آئورت', 'بطن  چپ'])['score'], 2)
        self.assertEqual(self._score(question(False), ['سرخرگ آئورت', 'بطن چپ'])['score'], 1)
        self.assertEqual(self._score(question(False, 'all_or_nothing'), ['سرخرگ آئورت', 'بطن چپ'])['score'], 0)

    def test_media_response_goes_to_manual_grading_queue(self):
        result = self._score({'type': 'media_response', 'scoring_settings': {'essay': {'answer_formats': ['text']}}}, 'پاسخ متنی')
        self.assertEqual(result['score'], 0)
        with connection.cursor() as cursor:
            cursor.execute("SELECT aa.needs_manual_grading FROM attempt_answers aa JOIN questions q ON q.id = aa.question_id WHERE q.type = 'media_response'")
            self.assertTrue(cursor.fetchone()[0])
        self.client.force_login(self.teacher_user)
        self.assertContains(self.client.get(reverse('core:teacher_reviews')), 'سؤال نوع جدید')

    # ----- student exam page -----

    def test_student_page_renders_matrix_without_correct_answers(self):
        rows = [{'id': 'r1', 'text': 'تاکی‌کاردی', 'points': 1, 'correct': ['c1']}, {'id': 'r2', 'text': 'افزایش وزن', 'points': 1, 'correct': ['c2']}]
        _question_id, attempt_id = self._attempt({'type': 'matrix', 'options': rows, 'scoring_settings': {'matrix': {
            'columns': [{'id': 'c1', 'text': 'پرکاری'}, {'id': 'c2', 'text': 'کم‌کاری'}], 'selection': 'single',
            'show_column_titles': True, 'show_row_titles': True}}}, 'r1:c1')
        self.client.force_login(self.student_user)
        page = self.client.get(reverse('core:student_attempt', args=[attempt_id])).content.decode()
        self.assertIn('data-matrix', page)
        self.assertIn('<th scope="col">کم‌کاری</th>', page)
        self.assertIn('value="r1:c1" data-matrix-cell checked', page)
        self.assertIn('value="r1:c1" data-matrix-answer', page)
        self.assertNotIn('"correct"', page)

    def test_student_page_saves_numeric_answer_with_unit(self):
        question_id, attempt_id = self._attempt({'scoring_settings': {'numeric': {'value': 5, 'unit': 'mL', 'require_unit': True}}})
        self.client.force_login(self.student_user)
        url = reverse('core:student_attempt', args=[attempt_id])
        self.assertContains(self.client.get(url), 'aria-label="واحد پاسخ"')
        self.client.post(url, {f'answer_{question_id}': ['۵', 'mL']})
        page = self.client.get(url).content.decode()
        self.assertIn('value="۵"', page)
        self.assertIn('value="mL"', page)

    def test_student_page_renders_image_label_pins_and_drag_bank(self):
        markers = [{'marker': 1, 'x': 33.3333, 'y': 20, 'answer': 'آئورت', 'synonyms': ['سرخرگ آئورت'], 'points': 1}]
        _question_id, attempt_id = self._attempt({'type': 'image_label', 'accepted_answers': markers,
                                                  'question_media': {'image': '/media/question-media/heart.png'},
                                                  'scoring_settings': {'image_label': {'answer_mode': 'drag'}}})
        self.client.force_login(self.student_user)
        page = self.client.get(reverse('core:student_attempt', args=[attempt_id])).content.decode()
        self.assertIn('style="left:33.33%;top:20.00%"', page)
        self.assertIn('data-label-chip>آئورت</button>', page)
        self.assertNotIn('سرخرگ آئورت', page)  # synonyms never reach the student
        self.assertEqual(page.count('/media/question-media/heart.png'), 1)  # not repeated as a plain figure

    def test_student_media_response_page_and_recorded_audio_upload(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        question_id, attempt_id = self._attempt({'type': 'media_response', 'question_media': {'audio': '/media/question-media/heart.mp3'},
                                                 'scoring_settings': {'essay': {'answer_formats': ['audio', 'video']}, 'media_response': {
                                                     'allow_replay': True, 'max_plays': 3, 'range_start': 10, 'range_end': 40,
                                                     'transcript': 'متن گفتار', 'show_transcript': True, 'max_record_seconds': 90}}})
        self.client.force_login(self.student_user)
        url = reverse('core:student_attempt', args=[attempt_id])
        page = self.client.get(url).content.decode()
        self.assertIn('data-playback', page)
        self.assertIn('"max_plays": 3', page)
        self.assertIn('data-record-kind="video" data-record-max="90"', page)
        self.assertIn('متن گفتار', page)
        self.client.post(url, {f'answer_{question_id}': '', f'upload_{question_id}_audio': SimpleUploadedFile('recording.mp3', self.MP3)})
        with connection.cursor() as cursor:
            cursor.execute('SELECT answer_files FROM attempt_answers WHERE attempt_id = %s AND question_id = %s', [attempt_id, question_id])
            files = json.loads(cursor.fetchone()[0])
        self.assertEqual([(item['kind'], item['name']) for item in files], [('audio', 'recording.mp3')])


class TeacherDashboardTests(_ScopedOrgFixture):
    """داشبورد استاد فقط داده‌ی آزمون‌ها و سؤال‌های همان استاد را نشان می‌دهد."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        User = get_user_model()
        cls.teacher_user = User.objects.create_user(username='teacher_in_scope', email='t_in@example.com', password='x')

    def _pending_answer(self, exam_id, question_id):
        attempt_id = str(uuid.uuid4())
        _insert('exam_attempts', ['id', 'exam_id', 'student_id', 'started_at', 'status'],
                [attempt_id, exam_id, self.student_in_id, timezone.now(), 'submitted'])
        _insert('attempt_answers', ['id', 'attempt_id', 'question_id', 'answer', 'needs_manual_grading'],
                [str(uuid.uuid4()), attempt_id, question_id, json.dumps({'value': 'x'}), True])

    def test_pending_review_count_excludes_other_teachers_answers(self):
        self._pending_answer(self.exam_out_id, self.question_out_id)
        self._pending_answer(self.exam_out_id, self.question_out_id)
        self._pending_answer(self.exam_in_id, self.question_in_id)
        self.client.force_login(self.teacher_user)
        response = self.client.get(reverse('core:teacher_panel'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['dashboard']['pending_total'], 1)  # the number the dashboard shows

    def _exam(self, teacher_id, title, start_at, **columns):
        exam_id = str(uuid.uuid4())
        _insert('exams', ['id', 'title', 'teacher_id', 'course_id', 'start_at', 'duration_minutes'] + list(columns),
                [exam_id, title, teacher_id, self.course_in_id, start_at, 60] + list(columns.values()))
        return exam_id

    def test_dashboard_lists_only_own_upcoming_exams_with_participants(self):
        from datetime import timedelta
        soon = timezone.now() + timedelta(days=3)
        own_id = self._exam(self.teacher_in_id, 'آزمون آینده من', soon, lifecycle_status='published')
        self._exam(self.teacher_out_id, 'آزمون آینده دیگری', soon, lifecycle_status='published')
        _insert('student_group_members', ['id', 'group_id', 'student_user_id', 'full_name', 'national_id', 'student_number'],
                [str(uuid.uuid4()), self.group_in_id, self.student_in_id, 'دانشجو', '1', '1'])
        _insert('exam_assignments', ['id', 'exam_id', 'group_id'], [str(uuid.uuid4()), own_id, self.group_in_id])
        self.client.force_login(self.teacher_user)
        response = self.client.get(reverse('core:teacher_panel'))
        data = response.context['dashboard']
        self.assertEqual([row['title'] for row in data['upcoming_exams']], ['آزمون آینده من'])
        self.assertEqual(data['upcoming_count'], 1)
        self.assertEqual(data['upcoming_exams'][0]['participants'], 1)
        self.assertEqual(data['upcoming_exams'][0]['status_label'], 'برنامه‌ریزی شده')
        self.assertEqual(data['next_exam']['title'], 'آزمون آینده من')
        page = response.content.decode()
        self.assertIn('آزمون آینده من', page)
        self.assertNotIn('آزمون آینده دیگری', page)
        for section in ('دسترسی سریع', 'آزمون‌های پیش رو', 'یادآور آزمون آینده', 'فعالیت‌های اخیر', 'عملکرد دانشجویان', 'پاسخ‌های نیازمند تصحیح'):
            self.assertIn(section, page)
        self.assertNotIn('۷۸٪', page)  # the old hard-coded participation figure is gone

    def test_dashboard_pending_and_performance_are_scoped(self):
        self._pending_answer(self.exam_in_id, self.question_in_id)
        self._pending_answer(self.exam_in_id, self.question_in2_id)
        self._pending_answer(self.exam_out_id, self.question_out_id)
        for exam_id, score in ((self.exam_in_id, 15), (self.exam_in_id, 17), (self.exam_out_id, 2)):
            _insert('exam_attempts', ['id', 'exam_id', 'student_id', 'started_at', 'status', 'score', 'max_score'],
                    [str(uuid.uuid4()), exam_id, self.student_in_id, timezone.now(), 'graded', score, 20])
        self.client.force_login(self.teacher_user)
        data = self.client.get(reverse('core:teacher_panel')).context['dashboard']
        self.assertEqual(data['pending_total'], 2)
        self.assertEqual(data['pending_exam_count'], 1)
        self.assertEqual([(row['title'], row['count']) for row in data['pending_by_exam']], [('آزمون داخل محدوده', 2)])
        self.assertEqual([(row['title'], row['average']) for row in data['performance']], [('آزمون داخل محدوده', 16.0)])

    def test_jalali_long_date(self):
        from datetime import date
        from apps.core.views import _jalali_long_date
        self.assertEqual(_jalali_long_date(date(2025, 5, 19)), 'دوشنبه ۲۹ اردیبهشت ۱۴۰۴')
        self.assertEqual(_jalali_long_date(None), '')


class TeacherExamWizardTests(_ScopedOrgFixture):
    """
    استاد همان ویزارد ایجاد آزمون مدیر را می‌بیند ولی فقط با گروه‌ها، دانشجویان و
    سؤال‌های خودش؛ مالک آزمون همیشه خود اوست، نمی‌تواند منتشر کند، و همه‌ی
    انتخاب‌ها هنگام ثبت دوباره سمت سرور بررسی می‌شوند.
    """

    NID_IN = 'NID-TW-IN'
    NID_OUT = 'NID-TW-OUT'

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        User = get_user_model()
        cls.teacher_user = User.objects.create_user(username='teacher_in_scope', email='t_in@example.com', password='x')
        for student_id, group_id, nid in ((cls.student_in_id, cls.group_in_id, cls.NID_IN), (cls.student_out_id, cls.group_out_id, cls.NID_OUT)):
            _insert('student_group_members', ['id', 'group_id', 'student_user_id', 'full_name', 'national_id', 'student_number'],
                    [str(uuid.uuid4()), group_id, student_id, 'دانشجو', nid, nid])
            with connection.cursor() as cursor:
                cursor.execute('UPDATE profiles SET national_id = %s WHERE id = %s', [nid, student_id])

    def _payload(self, **overrides):
        payload = {
            'title': 'آزمون استاد',
            'course_id': self.course_in_id,
            'group_ids': [self.group_in_id],
            'question_ids': [self.question_in_id, self.question_in2_id],
            'duration_minutes': '60',
            'start_at': '2026-11-10T09:00',
            'publish_choice': 'draft',
        }
        payload.update(overrides)
        return payload

    def _exam(self, title='آزمون استاد'):
        with connection.cursor() as cursor:
            cursor.execute('SELECT id, teacher_id, lifecycle_status, approval_status, is_published FROM exams WHERE title = %s', [title])
            return cursor.fetchall()

    def test_get_offers_only_own_resources(self):
        self.client.force_login(self.teacher_user)
        response = self.client.get(reverse('core:teacher_exam_create'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'super_admin/exam_wizard.html')
        ctx = response.context
        self.assertEqual(ctx['wizard_role'], 'teacher')
        self.assertEqual({g['id'] for g in ctx['groups']}, {self.group_in_id})
        self.assertEqual({c['id'] for c in ctx['courses']}, {self.course_in_id})
        self.assertEqual({q['id'] for q in ctx['questions']}, {self.question_in_id, self.question_in2_id})
        self.assertEqual({s['id'] for s in ctx['students']}, {self.student_in_id})
        self.assertEqual({t['id'] for t in ctx['teachers']}, {self.teacher_in_id})
        page = response.content.decode()
        self.assertIn('ارسال برای تأیید', page)
        self.assertNotIn('value="immediate"><strong>', page)
        self.assertIn(reverse('core:teacher_exam_participants_match'), page)

    def test_draft_is_owned_by_teacher_even_if_another_teacher_is_posted(self):
        self.client.force_login(self.teacher_user)
        response = self.client.post(reverse('core:teacher_exam_create'), self._payload(teacher_id=self.teacher_out_id))
        self.assertTrue(response['Location'].startswith(reverse('core:teacher_exams') + '?saved='))
        [(exam_id, teacher_id, lifecycle, approval, is_published)] = self._exam()
        self.assertEqual((str(teacher_id), lifecycle, approval, bool(is_published)), (self.teacher_in_id, 'draft', 'pending', False))
        with connection.cursor() as cursor:
            cursor.execute('SELECT question_id FROM exam_questions WHERE exam_id = %s ORDER BY order_index', [exam_id])
            self.assertEqual([str(row[0]) for row in cursor.fetchall()], [self.question_in_id, self.question_in2_id])
            cursor.execute('SELECT group_id FROM exam_assignments WHERE exam_id = %s', [exam_id])
            self.assertEqual([str(row[0]) for row in cursor.fetchall()], [self.group_in_id])

    def test_submit_sends_for_approval_and_cannot_publish(self):
        self.client.force_login(self.teacher_user)
        self.client.post(reverse('core:teacher_exam_create'), self._payload(publish_choice='submit'))
        [(_id, _teacher, lifecycle, approval, is_published)] = self._exam()
        self.assertEqual((lifecycle, approval, bool(is_published)), ('pending_approval', 'pending', False))
        self.client.post(reverse('core:teacher_exam_create'), self._payload(title='آزمون فوری', publish_choice='immediate'))
        [(_id, _teacher, lifecycle, approval, is_published)] = self._exam('آزمون فوری')
        self.assertEqual((lifecycle, approval, bool(is_published)), ('draft', 'pending', False))

    def test_out_of_scope_selections_are_rejected(self):
        self.client.force_login(self.teacher_user)
        for overrides in (
            {'course_id': self.course_out_id},
            {'group_ids': [self.group_in_id, self.group_out_id]},
            {'student_ids': [self.student_out_id]},
            {'excluded_student_ids': [self.student_out_id]},
            {'question_ids': [self.question_in_id, self.question_out_id]},
            {'staff_teacher_id': [self.teacher_out_id], 'staff_role': ['observer']},
        ):
            response = self.client.post(reverse('core:teacher_exam_create'), self._payload(**overrides))
            self.assertEqual(response.status_code, 403, overrides)
        self.assertEqual(self._exam(), [])

    def test_missing_audience_or_questions_shows_error(self):
        self.client.force_login(self.teacher_user)
        response = self.client.post(reverse('core:teacher_exam_create'), self._payload(group_ids=[]))
        self.assertRedirects(response, reverse('core:teacher_exam_create'), fetch_redirect_response=False)
        response = self.client.post(reverse('core:teacher_exam_create'), self._payload(question_ids=[]))
        self.assertRedirects(response, reverse('core:teacher_exam_create'), fetch_redirect_response=False)
        self.assertEqual(self._exam(), [])

    def test_participants_match_is_limited_to_own_group_members(self):
        self.client.force_login(self.teacher_user)
        upload = io.BytesIO(f'کد ملی یا شماره دانشجویی\n{self.NID_IN}\n{self.NID_OUT}\n'.encode('utf-8-sig'))
        upload.name = 'participants.csv'
        data = self.client.post(reverse('core:teacher_exam_participants_match'), {'excel_file': upload}).json()
        self.assertEqual([row['id'] for row in data['found']], [self.student_in_id])
        self.assertEqual(data['not_found'], [self.NID_OUT])

    def test_wizard_is_teacher_only(self):
        self.client.force_login(self.manager_user)
        self.assertEqual(self.client.get(reverse('core:teacher_exam_create')).status_code, 403)
        self.assertEqual(self.client.post(reverse('core:teacher_exam_participants_match')).status_code, 403)


class TeacherExamListTests(_ScopedOrgFixture):
    """صفحه‌ی «آزمون‌های من» فقط آزمون‌های خود استاد را با شمارش‌های واقعی، جستجو، فیلتر و صفحه‌بندی نشان می‌دهد."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        User = get_user_model()
        cls.teacher_user = User.objects.create_user(username='teacher_in_scope', email='t_in@example.com', password='x')

    def _get(self, **params):
        self.client.force_login(self.teacher_user)
        response = self.client.get(reverse('core:teacher_exams'), params)
        self.assertEqual(response.status_code, 200)
        return response

    def _exam(self, title, **columns):
        exam_id = str(uuid.uuid4())
        _insert('exams', ['id', 'title', 'teacher_id', 'course_id'] + list(columns),
                [exam_id, title, self.teacher_in_id, self.course_in_id] + list(columns.values()))
        return exam_id

    def test_lists_only_own_exams_with_real_counts(self):
        _insert('exam_questions', ['id', 'exam_id', 'question_id', 'points', 'order_index'], [str(uuid.uuid4()), self.exam_in_id, self.question_in_id, 1, 1])
        _insert('exam_questions', ['id', 'exam_id', 'question_id', 'points', 'order_index'], [str(uuid.uuid4()), self.exam_in_id, self.question_in2_id, 1, 2])
        _insert('student_group_members', ['id', 'group_id', 'student_user_id', 'full_name', 'national_id', 'student_number'],
                [str(uuid.uuid4()), self.group_in_id, self.student_in_id, 'دانشجو', '1', '1'])
        _insert('exam_assignments', ['id', 'exam_id', 'group_id'], [str(uuid.uuid4()), self.exam_in_id, self.group_in_id])
        attempt_id = str(uuid.uuid4())
        _insert('exam_attempts', ['id', 'exam_id', 'student_id', 'started_at', 'status'], [attempt_id, self.exam_in_id, self.student_in_id, timezone.now(), 'submitted'])
        _insert('attempt_answers', ['id', 'attempt_id', 'question_id', 'answer', 'needs_manual_grading'], [str(uuid.uuid4()), attempt_id, self.question_in_id, '{}', True])
        response = self._get()
        rows = response.context['exam_list']['rows']
        self.assertEqual([row['title'] for row in rows], ['آزمون داخل محدوده'])
        row = rows[0]
        self.assertEqual((row['question_count'], row['assigned'], row['submitted'], row['pending_reviews']), (2, 1, 1, 1))
        page = response.content.decode()
        self.assertNotIn('آزمون خارج محدوده', page)
        for leftover in ('ریاضی دهم', 'گروه الف', '۲۸/۳۰'):
            self.assertNotIn(leftover, page)
        self.assertIn('تصحیح (۱)', page)

    def test_status_filter_and_search(self):
        self._exam('پیش‌نویس فیزیولوژی', lifecycle_status='draft')
        self._exam('ارسالی فیزیولوژی', lifecycle_status='pending_approval')
        self._exam('لغوشده قلب', lifecycle_status='published', is_cancelled=True)
        titles = lambda response: {row['title'] for row in response.context['exam_list']['rows']}
        self.assertEqual(titles(self._get(status='pending_approval')), {'ارسالی فیزیولوژی'})
        self.assertEqual(titles(self._get(status='cancelled')), {'لغوشده قلب'})
        self.assertEqual(titles(self._get(q='فیزیولوژی')), {'پیش‌نویس فیزیولوژی', 'ارسالی فیزیولوژی'})
        self.assertEqual(titles(self._get(status='bogus', q='قلب')), {'لغوشده قلب'})  # unknown filter falls back to all
        self.assertIn('آزمونی با این جستجو یا وضعیت پیدا نشد', self._get(q='ناموجود').content.decode())

    def test_pagination(self):
        for index in range(24):
            self._exam(f'آزمون شماره {index}')
        first, second = self._get(), self._get(page='2')
        self.assertEqual(first.context['exam_list']['total'], 25)
        self.assertEqual(len(first.context['exam_list']['rows']), 20)
        self.assertEqual(len(second.context['exam_list']['rows']), 5)
        self.assertIn('صفحه ۱ از ۲', first.content.decode())

    def test_status_labels_follow_time_window(self):
        from datetime import timedelta
        from apps.core.views import _teacher_exam_status
        now = timezone.now()
        hour = timedelta(hours=1)
        self.assertEqual(_teacher_exam_status({'lifecycle': 'published', 'start_at': now - hour, 'end_at': now + hour}, now)[0], 'در حال برگزاری')
        self.assertEqual(_teacher_exam_status({'lifecycle': 'published', 'start_at': now + hour}, now)[0], 'برنامه‌ریزی شده')
        self.assertEqual(_teacher_exam_status({'lifecycle': 'published', 'start_at': now - 2 * hour, 'end_at': now - hour}, now)[0], 'پایان‌یافته')
        self.assertEqual(_teacher_exam_status({'lifecycle': 'pending_approval'}, now)[0], 'در انتظار تأیید')
        self.assertEqual(_teacher_exam_status({'lifecycle': 'published', 'is_cancelled': True}, now)[0], 'لغو شده')
        self.assertEqual(_teacher_exam_status({'lifecycle': ''}, now)[0], 'پیش‌نویس')


class TeacherClassListTests(_ScopedOrgFixture):
    """صفحه‌ی «کلاس‌های من» فقط گروه‌های خود استاد (مالک یا هم‌تدریس) را با آمار واقعی، جستجو، فیلتر و صفحه‌بندی نشان می‌دهد."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        User = get_user_model()
        cls.teacher_user = User.objects.create_user(username='teacher_in_scope', email='t_in@example.com', password='x')

    def _get(self, **params):
        self.client.force_login(self.teacher_user)
        response = self.client.get(reverse('core:teacher_courses'), params)
        self.assertEqual(response.status_code, 200)
        return response

    def _group(self, name, teacher_id=None, **columns):
        group_id = str(uuid.uuid4())
        columns = {'academic_year': '1404', **columns}
        _insert('student_groups', ['id', 'teacher_id', 'course_id', 'course_name'] + list(columns),
                [group_id, teacher_id or self.teacher_in_id, self.course_in_id, name] + list(columns.values()))
        return group_id

    def _member(self, group_id, student_id, name):
        _insert('student_group_members', ['id', 'group_id', 'student_user_id', 'full_name', 'national_id', 'student_number'],
                [str(uuid.uuid4()), group_id, student_id, name, '1', '1'])

    def test_lists_own_and_co_taught_groups_with_real_figures(self):
        shared_id = self._group('کلاس هم‌تدریس', teacher_id=self.teacher_out_id)
        _insert('group_teachers', ['group_id', 'teacher_id'], [shared_id, self.teacher_in_id])
        self._member(self.group_in_id, self.student_in_id, 'دانشجوی الف')
        self._member(shared_id, self.student_in_id, 'دانشجوی الف')
        self._member(shared_id, self.student_out_id, 'دانشجوی ب')
        _insert('exam_assignments', ['id', 'exam_id', 'group_id'], [str(uuid.uuid4()), self.exam_in_id, self.group_in_id])
        response = self._get()
        rows = {row['course_name']: row for row in response.context['class_list']['rows']}
        self.assertEqual(set(rows), {'درس داخل محدوده', 'کلاس هم‌تدریس'})
        self.assertEqual((rows['درس داخل محدوده']['students_count'], rows['درس داخل محدوده']['exams_count']), (1, 1))
        self.assertEqual(rows['کلاس هم‌تدریس']['students_count'], 2)
        self.assertEqual(response.context['class_list']['summary']['students'], 2)  # distinct across classes
        page = response.content.decode()
        self.assertNotIn('درس خارج محدوده', page)
        for leftover in ('مبانی پرستاری', 'فارماکولوژی', '۱۴۰۴/۰۳/۲۰'):
            self.assertNotIn(leftover, page)

    def test_search_term_and_status_filters(self):
        self._group('فیزیولوژی پایه', semester='اول', status='active')
        self._group('فیزیولوژی پیشرفته', semester='دوم', status='draft')
        self._group('آناتومی', academic_year='1403', semester='دوم', is_active=False)
        names = lambda response: {row['course_name'] for row in response.context['class_list']['rows']}
        self.assertEqual(names(self._get(q='فیزیولوژی')), {'فیزیولوژی پایه', 'فیزیولوژی پیشرفته'})
        self.assertEqual(names(self._get(term='1404|دوم')), {'فیزیولوژی پیشرفته'})
        # the fixture group keeps the column default status 'draft', as on the admin groups page
        self.assertEqual(names(self._get(status='inactive')), {'فیزیولوژی پیشرفته', 'آناتومی', 'درس داخل محدوده'})
        self.assertNotIn('آناتومی', names(self._get(status='active')))
        self.assertIn('فیزیولوژی پایه', names(self._get(term='9999|bogus', status='bogus')))  # unknown filters fall back to all
        self.assertIn('کلاسی با این جستجو یا فیلتر پیدا نشد', self._get(q='ناموجود').content.decode())

    def test_pagination_and_list_view(self):
        for index in range(13):
            self._group(f'کلاس شماره {index}')
        first, second = self._get(), self._get(page='2')
        self.assertEqual(first.context['class_list']['total'], 14)
        self.assertEqual(len(first.context['class_list']['rows']), 12)
        self.assertEqual(len(second.context['class_list']['rows']), 2)
        self.assertIn('صفحه ۱ از ۲', first.content.decode())
        self.assertIn('class="tclass-table"', self._get(view='list').content.decode())


class TeacherStudentScopeTests(_ScopedOrgFixture):
    """بخش «دانشجویان» استاد: فقط دانشجویان گروه‌های خودش (مالک یا هم‌تدریس) و فقط آزمون‌های منتشرشده‌ی خودش.

    هر شناسه‌ی دیگر در URL یا فرم ارسالی پاسخ ۴۰۴ می‌گیرد، نه داده‌ی ساختگی یا دانشجوی دیگری.
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        User = get_user_model()
        cls.teacher_user = User.objects.create_user(username='teacher_in_scope', email='t_in@example.com', password='x')
        cls.student2_id = cls._make_profile('student_second', 'دانشجوی دوم')
        _insert('student_profiles', ['user_id', 'student_number'], [cls.student2_id, '40112033'])
        for group_id, student_id in ((cls.group_in_id, cls.student_in_id), (cls.group_in_id, cls.student2_id), (cls.group_out_id, cls.student_out_id)):
            cls._member(group_id, student_id)
        cls.shared_group_id = str(uuid.uuid4())
        _insert('student_groups', ['id', 'teacher_id', 'course_id', 'course_name', 'academic_year'],
                [cls.shared_group_id, cls.teacher_out_id, cls.course_out_id, 'کلاس هم‌تدریس', '1404'])
        _insert('group_teachers', ['group_id', 'teacher_id'], [cls.shared_group_id, cls.teacher_in_id])
        cls.shared_student_id = cls._make_profile('student_shared', 'دانشجوی کلاس هم‌تدریس')
        _insert('student_profiles', ['user_id'], [cls.shared_student_id])
        cls._member(cls.shared_group_id, cls.shared_student_id)

        now = timezone.now()
        day = timedelta(days=1)
        cls.past_exam = cls._exam('آزمون گذشته', cls.teacher_in_id, now - 10 * day, now - 9 * day, cls.group_in_id)
        cls.unfinished_exam = cls._exam('آزمون نیمه‌کاره', cls.teacher_in_id, now - 5 * day, now - 4 * day, cls.group_in_id)
        cls.upcoming_exam = cls._exam('آزمون آینده', cls.teacher_in_id, now + 5 * day, now + 6 * day, cls.group_in_id)
        cls.draft_exam = cls._exam('آزمون پیش‌نویس', cls.teacher_in_id, now - 3 * day, now - 2 * day, cls.group_in_id, published=False)
        cls.other_exam = cls._exam('آزمون استاد دیگر', cls.teacher_out_id, now - 10 * day, now - 9 * day, cls.group_out_id)
        cls._attempt(cls.past_exam, cls.student_in_id, now - 10 * day, 'graded', 15, 20)
        cls._attempt(cls.unfinished_exam, cls.student_in_id, now - 5 * day, 'graded', 12, 20)
        cls._attempt(cls.unfinished_exam, cls.student2_id, now - 5 * day, 'in_progress')
        cls._attempt(cls.other_exam, cls.student_out_id, now - 10 * day, 'graded', 20, 20)

    @staticmethod
    def _member(group_id, student_id):
        _insert('student_group_members', ['id', 'group_id', 'student_user_id', 'full_name', 'national_id', 'student_number'],
                [str(uuid.uuid4()), group_id, student_id, 'عضو', '', ''])

    @staticmethod
    def _exam(title, teacher_id, start_at, end_at, group_id, published=True):
        exam_id = str(uuid.uuid4())
        _insert('exams', ['id', 'title', 'teacher_id', 'start_at', 'end_at', 'is_published', 'is_cancelled'],
                [exam_id, title, teacher_id, start_at, end_at, published, False])
        _insert('exam_assignments', ['id', 'exam_id', 'group_id'], [str(uuid.uuid4()), exam_id, group_id])
        return exam_id

    @staticmethod
    def _attempt(exam_id, student_id, started_at, status, score=None, max_score=None):
        submitted = started_at + timedelta(minutes=30) if status == 'graded' else None
        _insert('exam_attempts', ['id', 'exam_id', 'student_id', 'started_at', 'submitted_at', 'score', 'max_score', 'is_graded', 'status'],
                [str(uuid.uuid4()), exam_id, student_id, started_at, submitted, score, max_score, status == 'graded', status])

    def _get(self, url, data=None):
        self.client.force_login(self.teacher_user)
        return self.client.get(url, data or {})

    def _post(self, url, data):
        self.client.force_login(self.teacher_user)
        return self.client.post(url, data)

    def _notifications(self):
        with connection.cursor() as cursor:
            cursor.execute('SELECT user_id FROM notifications')
            return [str(row[0]) for row in cursor.fetchall()]

    def _notes(self):
        with connection.cursor() as cursor:
            cursor.execute('SELECT id, teacher_id, student_id, body, is_shared FROM teacher_student_notes ORDER BY body')
            return cursor.fetchall()

    def _list_ids(self, **params):
        response = self._get(reverse('core:teacher_students'), params)
        self.assertEqual(response.status_code, 200)
        return {row['id'] for row in response.context['sl']['rows']}

    # -- list
    def test_list_has_own_and_co_taught_students_only(self):
        self.assertEqual(self._list_ids(), {self.student_in_id, self.student2_id, self.shared_student_id})
        self.assertNotContains(self._get(reverse('core:teacher_students')), 'سارا احمدی')

    def test_list_figures_count_only_own_published_exams(self):
        rows = {row['id']: row for row in self._get(reverse('core:teacher_students')).context['sl']['rows']}
        first, second = rows[self.student_in_id], rows[self.student2_id]
        self.assertEqual((first['assigned_count'], first['attended_count'], first['absent_count']), (3, 2, 0))
        self.assertEqual(first['average'], 13.5)
        self.assertEqual(first['last_exam']['title'], 'آزمون نیمه‌کاره')
        self.assertEqual((second['absent_count'], second['unfinished_count']), (1, 1))
        self.assertEqual(second['last_exam']['state'], 'unfinished')

    def test_tabs_and_filters(self):
        self.assertEqual(self._list_ids(tab='absent'), {self.student2_id})
        self.assertEqual(self._list_ids(tab='unfinished'), {self.student2_id})
        self.assertEqual(self._list_ids(tab='review'), {self.student_in_id})  # average 13.5 < 14
        self.assertEqual(self._list_ids(q='40112033'), {self.student2_id})
        self.assertEqual(self._list_ids(group=self.shared_group_id), {self.shared_student_id})
        self.assertEqual(len(self._list_ids(group=self.group_out_id)), 3)  # another teacher's group is ignored

    # -- profile
    def test_profile_tabs_render_for_own_and_co_taught_students(self):
        for student_id in (self.student_in_id, self.shared_student_id):
            for tab in ('overview', 'courses', 'exams', 'analytics', 'notes'):
                response = self._get(reverse('core:teacher_student_profile', args=[student_id]), {'tab': tab})
                self.assertEqual(response.status_code, 200, (student_id, tab))
                self.assertEqual(response.context['profile']['student']['id'], student_id)

    def test_exams_tab_states_and_scope(self):
        url = reverse('core:teacher_student_profile', args=[self.student2_id])
        states = {row['title']: row['state'] for row in self._get(url, {'tab': 'exams'}).context['profile']['exam_rows']}
        self.assertEqual(states, {'آزمون گذشته': 'absent', 'آزمون نیمه‌کاره': 'unfinished', 'آزمون آینده': 'upcoming'})
        filtered = self._get(url, {'tab': 'exams', 'state': 'absent'}).context['profile']['exam_rows']
        self.assertEqual([row['title'] for row in filtered], ['آزمون گذشته'])

    def test_courses_tab_lists_only_own_groups(self):
        response = self._get(reverse('core:teacher_student_profile', args=[self.student_in_id]), {'tab': 'courses'})
        self.assertEqual([group['id'] for group in response.context['profile']['groups']], [self.group_in_id])

    def test_analytics_compares_with_class(self):
        response = self._get(reverse('core:teacher_student_profile', args=[self.student_in_id]), {'tab': 'analytics'})
        analytics = response.context['profile']['analytics']
        self.assertTrue(analytics['has_data'])
        self.assertEqual([point['student'] for point in analytics['points']], [15.0, 12.0])
        self.assertEqual(analytics['points'][0]['minutes'], 30.0)

    def test_other_or_unknown_student_is_404_not_a_stand_in(self):
        for student_id in (self.student_out_id, str(uuid.uuid4()), '14021057', 'sara'):
            for name in ('core:teacher_student_profile', 'core:teacher_student_report'):
                self.assertEqual(self._get(reverse(name, args=[student_id])).status_code, 404, (name, student_id))

    def test_group_pages_redirect_to_filtered_list_or_404(self):
        for name in ('core:teacher_group_students', 'core:teacher_group_activity'):
            response = self._get(reverse(name, args=[self.shared_group_id]))
            self.assertRedirects(response, f"{reverse('core:teacher_students')}?group={self.shared_group_id}")
            self.assertEqual(self._get(reverse(name, args=[self.group_out_id])).status_code, 404)
            self.assertEqual(self._get(reverse(name, args=['nursing-01'])).status_code, 404)

    def test_report_card(self):
        response = self._get(reverse('core:teacher_student_report', args=[self.student_in_id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'آزمون گذشته')
        self.assertNotContains(response, 'آزمون استاد دیگر')
        self.assertNotContains(response, 'آزمون پیش‌نویس')

    # -- messages
    def test_message_reaches_only_own_students(self):
        url = reverse('core:teacher_students_message')
        response = self._post(url, {'student_ids': [self.student_in_id, self.shared_student_id], 'title': 'یادآوری', 'body': 'سلام'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(sorted(self._notifications()), sorted([self.student_in_id, self.shared_student_id]))
        tampered = self._post(url, {'student_ids': [self.student_in_id, self.student_out_id], 'title': 'x', 'body': 'y'})
        self.assertEqual(tampered.status_code, 404)
        self._post(url, {'student_ids': [self.student_in_id], 'title': '', 'body': 'y'})
        self.assertEqual(len(self._notifications()), 2)

    # -- notes
    def test_notes_are_private_and_scoped(self):
        url = reverse('core:teacher_student_note_create', args=[self.student_in_id])
        self._post(url, {'body': 'الف: نیاز به تمرین بیشتر', 'action': 'save'})
        self._post(url, {'body': 'ب: آفرین', 'action': 'share'})
        self._post(url, {'body': 'x' * 1001, 'action': 'save'})
        notes = self._notes()
        self.assertEqual(len(notes), 2)
        self.assertEqual(self._notifications(), [self.student_in_id])  # only the shared note reaches the student
        self.assertEqual(self._post(reverse('core:teacher_student_note_create', args=[self.student_out_id]), {'body': 'x'}).status_code, 404)

        foreign_note = str(uuid.uuid4())
        _insert('teacher_student_notes', ['id', 'teacher_id', 'student_id', 'body'], [foreign_note, self.teacher_out_id, self.student_in_id, 'ج: خصوصی استاد دیگر'])
        page = self._get(reverse('core:teacher_student_profile', args=[self.student_in_id]), {'tab': 'notes'})
        self.assertNotContains(page, 'خصوصی استاد دیگر')
        self.assertEqual(self._post(reverse('core:teacher_student_note_delete', args=[self.student_in_id, foreign_note]), {}).status_code, 404)
        self._post(reverse('core:teacher_student_note_delete', args=[self.student_in_id, str(notes[0][0])]), {})
        self.assertEqual([row[3] for row in self._notes()], ['ب: آفرین', 'ج: خصوصی استاد دیگر'])

    # -- export
    def test_export_contains_only_filtered_own_students(self):
        response = self._get(reverse('core:teacher_students_export'), {'tab': 'absent'})
        self.assertEqual(response.status_code, 200)
        self.assertIn('attachment;', response['Content-Disposition'])
        if response['Content-Disposition'].endswith('.csv"'):
            text = response.content.decode('utf-8-sig')
        else:
            from openpyxl import load_workbook
            sheet = load_workbook(io.BytesIO(response.content)).active
            text = ' '.join(str(cell.value) for row in sheet.iter_rows() for cell in row)
        self.assertIn('دانشجوی دوم', text)
        self.assertNotIn('دانشجوی داخل محدوده', text)
        self.assertNotIn('دانشجوی خارج محدوده', text)

    def test_formula_like_cells_are_neutralised(self):
        from .teacher_students import _cell

        self.assertEqual(_cell('=HYPERLINK("x")'), "'=HYPERLINK(\"x\")")
        self.assertEqual(_cell('علی'), 'علی')


class TeacherSettingsTests(_ScopedOrgFixture):
    """تنظیمات پنل استاد: سه تب، ذخیره فقط فیلدهای همان تب، و ردکردن مقدارهای خارج از گزینه‌ها سمت سرور."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        User = get_user_model()
        cls.teacher_user = User.objects.create_user(username='teacher_in_scope', email='t_in@example.com', password='x')

    def setUp(self):
        self.client.force_login(self.teacher_user)

    def _stored(self):
        from apps.core.views import _teacher_settings_payload
        return _teacher_settings_payload(self.teacher_in_id)

    def _post(self, tab, **data):
        return self.client.post(reverse('core:teacher_settings'), {'settings_tab': tab, **data})

    def test_tabs_render_and_old_tab_names_map_to_new_ones(self):
        for tab, marker in (('account', 'محیط کار'), ('exam', 'پیش‌فرض آزمون'), ('security', 'حریم خصوصی و نمایش اطلاعات')):
            response = self.client.get(reverse('core:teacher_settings'), {'tab': tab})
            self.assertEqual(response.status_code, 200)
            self.assertIn(marker, response.content.decode())
        self.assertEqual(self.client.get(reverse('core:teacher_settings'), {'tab': 'bank'}).context['teacher_settings_tab'], 'exam')
        self.assertEqual(self.client.get(reverse('core:teacher_settings'), {'tab': 'notifications'}).context['teacher_settings_tab'], 'account')
        self.assertEqual(self.client.get(reverse('core:teacher_settings'), {'tab': 'bogus'}).context['teacher_settings_tab'], 'personal')

    def test_saves_only_the_posted_tab_and_validates_choices(self):
        self._post('exam', default_exam_duration='90', negative_marking='on', sharing_mode='department', auto_archive='on')
        stored = self._stored()
        self.assertEqual((stored['default_exam_duration'], stored['negative_marking'], stored['sharing_mode'], stored['auto_archive']), ('90', True, 'department', True))
        self.assertFalse(stored['text_feedback'])  # an unchecked switch on the posted tab turns off
        self.assertTrue(stored['quick_help'])  # switches on other tabs keep their value

        self._post('exam', default_exam_duration='9999', sharing_mode='<script>')
        stored = self._stored()
        self.assertEqual((stored['default_exam_duration'], stored['sharing_mode']), ('90', 'department'))

    def test_account_tab_validates_email_and_quiet_hours(self):
        self._post('account', theme='dark', delivery_mode='daily', notification_email='me@uni.ac.ir', quiet_start='23:30', quiet_end='06:15')
        stored = self._stored()
        self.assertEqual(
            (stored['theme'], stored['delivery_mode'], stored['notification_email'], stored['quiet_start'], stored['quiet_end']),
            ('dark', 'daily', 'me@uni.ac.ir', '23:30', '06:15'),
        )
        response = self._post('account', notification_email='not-an-email', quiet_start='25:99')
        stored = self._stored()
        self.assertEqual((stored['notification_email'], stored['quiet_start']), ('me@uni.ac.ir', '23:30'))
        self.assertIn('ایمیل اعلان‌ها معتبر نیست', self.client.get(response['Location']).content.decode())

    def test_personal_tab_saves_validated_details_only_for_this_teacher(self):
        response = self._post('personal', first_name='سارا', last_name='احمدی', display_name='دکتر سارا احمدی',
                              phone='۰۹۱۷ ۱۲۳ ۴۵۶۷', landline='071-3222-1111', bio='پرستاری سالمندی', show_bio='on',
                              academic_rank='استاد', personnel_code='999')  # not editable here: ignored
        self.assertEqual(response.status_code, 302)
        from apps.core.views import erd_row
        row = erd_row(
            """SELECT p.full_name, p.phone, tp.display_name, tp.landline, tp.bio, tp.show_bio, tp.academic_rank, tp.personnel_code
               FROM profiles p JOIN teacher_profiles tp ON tp.user_id = p.id WHERE p.id = %s""", [self.teacher_in_id])
        self.assertEqual((row['full_name'], row['phone'], row['display_name'], row['landline'], row['bio']),
                         ('سارا احمدی', '09171234567', 'دکتر سارا احمدی', '07132221111', 'پرستاری سالمندی'))
        self.assertTrue(row['show_bio'])
        self.assertIsNone(row['academic_rank'])
        self.assertIsNone(row['personnel_code'])
        self.assertEqual(erd_row('SELECT full_name FROM profiles WHERE id = %s', [self.teacher_out_id])['full_name'], 'استاد خارج محدوده')

    def test_personal_tab_rejects_invalid_input_and_keeps_typed_values(self):
        response = self._post('personal', first_name='', last_name='احمدی', phone='12345', landline='abc')
        self.assertEqual(response.status_code, 200)
        page = response.content.decode()
        for error in ('نام و نام خانوادگی الزامی است', 'تلفن همراه باید', 'تلفن ثابت باید'):
            self.assertIn(error, page)
        self.assertIn('value="12345"', page)
        from apps.core.views import erd_row
        self.assertEqual(erd_row('SELECT full_name FROM profiles WHERE id = %s', [self.teacher_in_id])['full_name'], 'استاد داخل محدوده')

    def test_avatar_upload_checks_the_file_itself(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        fake = SimpleUploadedFile('photo.png', b'<?php echo 1; ?>', content_type='image/png')
        response = self._post('personal', first_name='سارا', last_name='احمدی', phone='09171234567', avatar=fake)
        self.assertIn('فرمت تصویر باید', response.content.decode())
        big = SimpleUploadedFile('photo.png', b'\x89PNG\r\n\x1a\n' + b'0' * (1024 * 1024), content_type='image/png')
        self.assertIn('حجم تصویر', self._post('personal', first_name='سارا', last_name='احمدی', phone='09171234567', avatar=big).content.decode())
        header_only = SimpleUploadedFile('photo.png', b'\x89PNG\r\n\x1a\n' + b'0' * 64, content_type='image/png')
        self.assertIn('فرمت تصویر باید', self._post('personal', first_name='سارا', last_name='احمدی', avatar=header_only).content.decode())

    def test_real_image_is_accepted_as_avatar(self):
        import io as _io
        import shutil
        import tempfile
        from django.core.files.uploadedfile import SimpleUploadedFile
        from PIL import Image
        buffer = _io.BytesIO()
        Image.new('RGB', (8, 8), 'blue').save(buffer, 'PNG')
        media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, media, ignore_errors=True)
        from pathlib import Path
        with self.settings(MEDIA_ROOT=Path(media)):
            photo = SimpleUploadedFile('photo.png', buffer.getvalue(), content_type='image/png')
            response = self._post('personal', first_name='سارا', last_name='احمدی', avatar=photo)
        self.assertEqual(response.status_code, 302)
        from apps.core.views import _teacher_personal_info
        self.assertIn('/avatars/', _teacher_personal_info(self.teacher_in_id)['avatar_url'])

    def test_phone_is_kept_unless_changed_and_shown_masked(self):
        self._post('personal', first_name='سارا', last_name='احمدی', phone='09171234567')
        self._post('personal', first_name='سارا', last_name='رضایی')  # «تغییر شماره» not pressed: no phone field
        from apps.core.views import _teacher_personal_info
        info = _teacher_personal_info(self.teacher_in_id)
        self.assertEqual((info['last_name'], info['phone'], info['phone_masked']), ('رضایی', '09171234567', '0917***4567'))
        self.assertTrue(0 < info['completeness'] < 100)
        page = self.client.get(reverse('core:teacher_settings'), {'tab': 'personal'}).content.decode()
        self.assertIn('۰۹۱۷***۴۵۶۷', page)
        self.assertNotIn('09171234567" ', page.split('data-tset-phone-view')[1].split('</span>')[0])

    def test_old_profile_page_redirects_to_personal_tab(self):
        response = self.client.get(reverse('core:teacher_profile_page'))
        self.assertRedirects(response, f"{reverse('core:teacher_settings')}?tab=personal", fetch_redirect_response=False)

    def test_security_tab_shows_no_fake_sessions(self):
        page = self.client.get(reverse('core:teacher_settings'), {'tab': 'security'}).content.decode()
        for fake in ('Windows 11', 'Android · Chrome', 'حساب شما ایمن است', 'در حال توسعه'):
            self.assertNotIn(fake, page)


from apps.core.views import erd_execute, erd_row, erd_rows  # noqa: E402


class ManagerTeacherProfileScopeTests(_ScopedOrgFixture):
    """پروفایل استاد در پنل مدیر آموزشی: فقط استادهای واحد خود مدیر، بدون فعالیت ساختگی."""

    def test_manager_sees_only_teachers_of_own_units(self):
        self.client.force_login(self.manager_user)
        inside = self.client.get(reverse('core:exam_manager_teacher_profile', args=[self.teacher_in_id]))
        self.assertEqual(inside.status_code, 200)
        page = inside.content.decode()
        for fake in ('آزمون نوبت دوم', 'رشد و تکامل', '۱۴۰۳/۰۱/۱۵'):
            self.assertNotIn(fake, page)
        self.assertEqual(self.client.get(reverse('core:exam_manager_teacher_profile', args=[self.teacher_out_id])).status_code, 404)
        self.client.force_login(self.admin_user)
        self.assertEqual(self.client.get(reverse('core:exam_manager_teacher_profile', args=[self.teacher_out_id])).status_code, 200)


class TeacherProfileChangeRequestTests(_ScopedOrgFixture):
    """درخواست تغییر اطلاعات دانشگاهی استاد: فقط با تأیید مدیر آموزشیِ همان واحد اعمال می‌شود."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        User = get_user_model()
        cls.teacher_user = User.objects.create_user(username='teacher_in_scope', email='t_in@example.com', password='x')
        cls.teacher_out_user = User.objects.create_user(username='teacher_out_scope', email='t_out@example.com', password='x')

    def _request(self, user, **data):
        self.client.force_login(user)
        return self.client.post(reverse('core:teacher_settings'), {'settings_tab': 'personal', 'personal_action': 'academic_request', **data})

    def _profile(self, teacher_id):
        return erd_row('SELECT org_unit_id, academic_rank, degree FROM teacher_profiles WHERE user_id = %s', [teacher_id])

    def _requests(self, teacher_id):
        return erd_rows('SELECT id, status, org_unit_id, academic_rank, degree FROM teacher_profile_change_requests WHERE teacher_id = %s', [teacher_id])

    def _review(self, user, request_id, **data):
        self.client.force_login(user)
        return self.client.post(reverse('core:exam_manager_teacher_request_review', args=[request_id]), data)

    def test_request_is_stored_pending_and_profile_is_untouched(self):
        response = self._request(self.teacher_user, request_academic_rank='دانشیار', request_org_unit_id=self.ou_other, request_note='حکم جدید')
        self.assertRedirects(response, f"{reverse('core:teacher_settings')}?tab=personal&request=sent", fetch_redirect_response=False)
        [stored] = self._requests(self.teacher_in_id)
        self.assertEqual((stored['status'], stored['academic_rank'], str(stored['org_unit_id'])), ('pending', 'دانشیار', self.ou_other))
        self.assertIsNone(stored['degree'])  # not changed, so not requested
        self.assertEqual(str(self._profile(self.teacher_in_id)['org_unit_id']), self.ou_scoped)
        page = self.client.get(reverse('core:teacher_settings'), {'tab': 'personal'}).content.decode()
        self.assertIn('در انتظار تأیید', page)

    def test_invalid_or_empty_or_duplicate_requests_are_refused(self):
        page = self._request(self.teacher_user, request_academic_rank='رئیس کل').content.decode()
        self.assertIn('مرتبه علمی انتخاب‌شده معتبر نیست', page)
        page = self._request(self.teacher_user, request_org_unit_id=self.ou_scoped).content.decode()
        self.assertIn('هیچ تغییری', page)
        self.assertEqual(self._requests(self.teacher_in_id), [])
        self._request(self.teacher_user, request_degree='دکتری حرفه‌ای')
        page = self._request(self.teacher_user, request_degree='فوق تخصص').content.decode()
        self.assertIn('در انتظار بررسی', page)
        self.assertEqual(len(self._requests(self.teacher_in_id)), 1)

    def test_manager_in_scope_approves_and_only_requested_fields_change(self):
        erd_execute("UPDATE teacher_profiles SET degree = 'دکتری حرفه‌ای' WHERE user_id = %s", [self.teacher_in_id])
        self._request(self.teacher_user, request_academic_rank='استاد')
        [stored] = self._requests(self.teacher_in_id)
        response = self._review(self.manager_user, stored['id'], decision='approve')
        self.assertEqual(response.status_code, 302)
        profile = self._profile(self.teacher_in_id)
        self.assertEqual((profile['academic_rank'], profile['degree'], str(profile['org_unit_id'])), ('استاد', 'دکتری حرفه‌ای', self.ou_scoped))
        self.assertEqual(self._requests(self.teacher_in_id)[0]['status'], 'approved')
        self.assertTrue(erd_row("SELECT 1 AS ok FROM notifications WHERE user_id = %s", [self.teacher_in_id]))
        # a second decision on the same request does nothing
        self._review(self.manager_user, stored['id'], decision='reject', review_note='دیر')
        self.assertEqual(self._requests(self.teacher_in_id)[0]['status'], 'approved')

    def test_manager_cannot_see_or_review_requests_outside_scope(self):
        self._request(self.teacher_out_user, request_academic_rank='استاد')
        [stored] = self._requests(self.teacher_out_id)
        self.client.force_login(self.manager_user)
        page = self.client.get(reverse('core:exam_manager_teacher_requests')).content.decode()
        self.assertNotIn('استاد خارج محدوده', page)
        self.assertEqual(self._review(self.manager_user, stored['id'], decision='approve').status_code, 404)
        self.assertEqual(self._requests(self.teacher_out_id)[0]['status'], 'pending')
        self.assertNotEqual(self._profile(self.teacher_out_id)['academic_rank'], 'استاد')
        # the system admin sees every unit
        self._review(self.admin_user, stored['id'], decision='approve')
        self.assertEqual(self._profile(self.teacher_out_id)['academic_rank'], 'استاد')

    def test_reject_needs_a_reason_and_keeps_the_profile(self):
        self._request(self.teacher_user, request_academic_rank='استاد')
        [stored] = self._requests(self.teacher_in_id)
        self._review(self.manager_user, stored['id'], decision='reject')
        self.assertEqual(self._requests(self.teacher_in_id)[0]['status'], 'pending')
        self._review(self.manager_user, stored['id'], decision='reject', review_note='حکم ارائه نشده است')
        self.assertEqual(self._requests(self.teacher_in_id)[0]['status'], 'rejected')
        self.assertNotEqual(self._profile(self.teacher_in_id)['academic_rank'], 'استاد')
        self.client.force_login(self.teacher_user)
        page = self.client.get(reverse('core:teacher_settings'), {'tab': 'personal'}).content.decode()
        self.assertIn('حکم ارائه نشده است', page)

    def test_teacher_can_cancel_but_not_review(self):
        self._request(self.teacher_user, request_academic_rank='استاد')
        [stored] = self._requests(self.teacher_in_id)
        self.assertEqual(self._review(self.teacher_user, stored['id'], decision='approve').status_code, 403)
        self.assertEqual(self._requests(self.teacher_in_id)[0]['status'], 'pending')
        self.client.post(reverse('core:teacher_settings'), {'settings_tab': 'personal', 'personal_action': 'academic_cancel'})
        self.assertEqual(self._requests(self.teacher_in_id)[0]['status'], 'cancelled')


class TeacherSecurityTabTests(_ScopedOrgFixture):
    """تب امنیت استاد: نشست‌های واقعی خود کاربر و درخواست حذف منطقی حساب با تأیید مدیر سیستم."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        User = get_user_model()
        cls.teacher_user = User.objects.create_user(username='teacher_in_scope', email='t_in@example.com', password='pass-1234')
        cls.teacher_out_user = User.objects.create_user(username='teacher_out_scope', email='t_out@example.com', password='pass-1234')

    def _login(self, user, client=None):
        client = client or self.client
        self.assertTrue(client.login(username=user.username, password='pass-1234'))
        return client

    def _security(self, client, **data):
        return client.post(reverse('core:teacher_settings'), {'settings_tab': 'security', **data})

    def test_sessions_are_listed_and_only_own_sessions_can_be_ended(self):
        from django.test import Client
        main = self._login(self.teacher_user)
        other = self._login(self.teacher_user, Client())
        stranger = self._login(self.teacher_out_user, Client())
        page = main.get(reverse('core:teacher_settings'), {'tab': 'security'})
        sessions = page.context['sessions']
        self.assertEqual(len(sessions), 2)
        self.assertEqual(sum(item['is_current'] for item in sessions), 1)
        stranger_key = stranger.session.session_key
        response = self._security(main, security_action=f'end_session:{stranger_key}')
        self.assertIn('پیدا نشد', response.content.decode())
        self.assertEqual(stranger.get(reverse('core:teacher_settings')).status_code, 200)  # still signed in
        other_key = next(item['key'] for item in sessions if not item['is_current'])
        self._security(main, security_action=f'end_session:{other_key}')
        self.assertEqual(other.get(reverse('core:teacher_settings')).status_code, 302)  # sent to login
        self.assertEqual(main.get(reverse('core:teacher_settings')).status_code, 200)

    def test_end_other_sessions_keeps_the_current_one(self):
        from django.test import Client
        main = self._login(self.teacher_user)
        other = self._login(self.teacher_user, Client())
        self._security(main, security_action='end_other_sessions')
        self.assertEqual(other.get(reverse('core:teacher_settings')).status_code, 302)
        self.assertEqual(main.get(reverse('core:teacher_settings')).status_code, 200)

    def test_deletion_request_needs_password_and_confirmation(self):
        client = self._login(self.teacher_user)
        page = self._security(client, security_action='deletion_request', deletion_password='wrong', deletion_confirm='on').content.decode()
        self.assertIn('رمز عبور درست نیست', page)
        page = self._security(client, security_action='deletion_request', deletion_password='pass-1234').content.decode()
        self.assertIn('تیک تأیید', page)
        self.assertFalse(erd_rows('SELECT id FROM account_deletion_requests', []))
        self._security(client, security_action='deletion_request', deletion_password='pass-1234', deletion_confirm='on', deletion_reason='بازنشستگی')
        [stored] = erd_rows('SELECT id, status FROM account_deletion_requests WHERE profile_id = %s', [self.teacher_in_id])
        self.assertEqual(stored['status'], 'pending')
        self.assertTrue(get_user_model().objects.get(pk=self.teacher_user.pk).is_active)  # nothing happens before review
        self.assertIn('در انتظار بررسی', client.get(reverse('core:teacher_settings'), {'tab': 'security'}).content.decode())
        self._security(client, security_action='deletion_cancel')
        self.assertEqual(erd_row('SELECT status FROM account_deletion_requests WHERE id = %s', [stored['id']])['status'], 'cancelled')

    def test_admin_approval_deactivates_but_keeps_data(self):
        teacher = self._login(self.teacher_user)
        self._security(teacher, security_action='deletion_request', deletion_password='pass-1234', deletion_confirm='on')
        [stored] = erd_rows('SELECT id FROM account_deletion_requests WHERE profile_id = %s', [self.teacher_in_id])
        from django.test import Client
        manager = Client()
        manager.force_login(self.manager_user)
        self.assertEqual(manager.post(reverse('core:super_admin_account_deletion_review', args=[stored['id']]), {'decision': 'approve'}).status_code, 403)
        admin = Client()
        admin.force_login(self.admin_user)
        self.assertIn('در انتظار', admin.get(reverse('core:super_admin_account_deletions')).content.decode())
        admin.post(reverse('core:super_admin_account_deletion_review', args=[stored['id']]), {'decision': 'approve'})
        self.assertFalse(get_user_model().objects.get(pk=self.teacher_user.pk).is_active)
        self.assertEqual(teacher.get(reverse('core:teacher_settings')).status_code, 302)  # session ended
        fresh = Client()
        fresh.post(reverse('core:login'), {'username': 'teacher_in_scope', 'password': 'pass-1234'})  # the real login form
        self.assertNotIn('_auth_user_id', fresh.session)
        profile = erd_row('SELECT status, deleted_at FROM profiles WHERE id = %s', [self.teacher_in_id])
        self.assertEqual(profile['status'], 'inactive')
        self.assertIsNotNone(profile['deleted_at'])
        self.assertTrue(erd_row('SELECT 1 AS ok FROM teacher_profiles WHERE user_id = %s', [self.teacher_in_id]))  # data kept

    def test_admin_reject_needs_a_reason(self):
        teacher = self._login(self.teacher_user)
        self._security(teacher, security_action='deletion_request', deletion_password='pass-1234', deletion_confirm='on')
        [stored] = erd_rows('SELECT id FROM account_deletion_requests WHERE profile_id = %s', [self.teacher_in_id])
        from django.test import Client
        admin = Client()
        admin.force_login(self.admin_user)
        url = reverse('core:super_admin_account_deletion_review', args=[stored['id']])
        admin.post(url, {'decision': 'reject'})
        self.assertEqual(erd_row('SELECT status FROM account_deletion_requests WHERE id = %s', [stored['id']])['status'], 'pending')
        admin.post(url, {'decision': 'reject', 'review_note': 'کلاس فعال دارید'})
        self.assertEqual(erd_row('SELECT status FROM account_deletion_requests WHERE id = %s', [stored['id']])['status'], 'rejected')
        self.assertTrue(get_user_model().objects.get(pk=self.teacher_user.pk).is_active)
        self.assertIn('کلاس فعال دارید', teacher.get(reverse('core:teacher_settings'), {'tab': 'security'}).content.decode())


from unittest import mock, skipUnless  # noqa: E402

from apps.core import account_security  # noqa: E402


class TwoFactorTests(_ScopedOrgFixture):
    """ورود دومرحله‌ای با برنامه‌ی Authenticator: فعال‌سازی با کد واقعی، ورود، کد بازیابی و محدودیت تلاش."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.teacher_user = get_user_model().objects.create_user(username='teacher_in_scope', email='t_in@example.com', password='pass-1234')

    def _security(self, **data):
        return self.client.post(reverse('core:teacher_settings'), {'settings_tab': 'security', **data})

    def _enable(self):
        import pyotp
        self.client.force_login(self.teacher_user)
        self._security(security_action='totp_start')
        secret = account_security.pending_secret(self.teacher_user)
        self._security(security_action='totp_confirm', totp_code=pyotp.TOTP(secret).now(), security_password='pass-1234')
        self.client.logout()
        return secret

    def _password_step(self, client=None):
        client = client or self.client
        return client.post(reverse('core:login'), {'username': 'teacher_in_scope', 'password': 'pass-1234'})

    def test_without_the_libraries_the_tab_says_so_instead_of_failing(self):
        self.client.force_login(self.teacher_user)
        with mock.patch.object(account_security, 'TWO_FACTOR_AVAILABLE', False):
            page = self.client.get(reverse('core:teacher_settings'), {'tab': 'security'}).content.decode()
            self.assertIn('نیازمند نصب کتابخانه', page)
            self.assertIn('pyotp', self._security(security_action='totp_start').content.decode())
        self.assertFalse(account_security.two_factor_enabled(self.teacher_user))

    @skipUnless(account_security.TWO_FACTOR_AVAILABLE, 'pyotp/qrcode not installed')
    def test_enrollment_needs_a_real_code_and_the_password(self):
        import pyotp
        self.client.force_login(self.teacher_user)
        self._security(security_action='totp_start')
        page = self.client.get(reverse('core:teacher_settings'), {'tab': 'security'}).content.decode()
        self.assertIn('<svg', page)
        secret = account_security.pending_secret(self.teacher_user)
        self.assertIn('رمز عبور درست نیست', self._security(security_action='totp_confirm', totp_code=pyotp.TOTP(secret).now(), security_password='bad').content.decode())
        self.assertIn('همخوانی ندارد', self._security(security_action='totp_confirm', totp_code='000000', security_password='pass-1234').content.decode())
        self.assertFalse(account_security.two_factor_enabled(self.teacher_user))
        self._security(security_action='totp_confirm', totp_code=pyotp.TOTP(secret).now(), security_password='pass-1234')
        self.assertTrue(account_security.two_factor_enabled(self.teacher_user))
        first = self.client.get(reverse('core:teacher_settings'), {'tab': 'security'}).content.decode()
        self.assertIn('فقط همین یک بار', first)
        self.assertNotIn('فقط همین یک بار', self.client.get(reverse('core:teacher_settings'), {'tab': 'security'}).content.decode())

    @skipUnless(account_security.TWO_FACTOR_AVAILABLE, 'pyotp/qrcode not installed')
    def test_login_needs_the_app_code_and_a_code_cannot_be_replayed(self):
        import pyotp
        from django.test import Client
        secret = self._enable()
        response = self._password_step()
        self.assertRedirects(response, reverse('core:login_2fa'), fetch_redirect_response=False)
        self.assertNotIn('_auth_user_id', self.client.session)  # the password alone does not sign in
        code = pyotp.TOTP(secret).at(timezone.now() + timedelta(seconds=30))  # next step: enrollment used this one
        self.client.post(reverse('core:login_2fa'), {'code': code})
        self.assertIn('_auth_user_id', self.client.session)
        other = Client()
        self._password_step(other)
        other.post(reverse('core:login_2fa'), {'code': code})  # same code again
        self.assertNotIn('_auth_user_id', other.session)

    @skipUnless(account_security.TWO_FACTOR_AVAILABLE, 'pyotp/qrcode not installed')
    def test_recovery_code_works_once_and_attempts_are_limited(self):
        from django.test import Client
        self._enable()
        self.client.force_login(self.teacher_user)
        self._security(security_action='recovery_regenerate', security_password='pass-1234')
        page = self.client.get(reverse('core:teacher_settings'), {'tab': 'security'})
        codes = page.context['two_factor']['new_codes']
        self.client.logout()
        fresh = Client()
        self._password_step(fresh)
        fresh.post(reverse('core:login_2fa'), {'code': codes[0].lower()})
        self.assertIn('_auth_user_id', fresh.session)
        again = Client()
        self._password_step(again)
        again.post(reverse('core:login_2fa'), {'code': codes[0]})
        self.assertNotIn('_auth_user_id', again.session)
        for _ in range(4):
            again.post(reverse('core:login_2fa'), {'code': '123456'})
        self.assertNotIn('pending_2fa_user_id', again.session)  # five wrong codes: back to the password step

    @skipUnless(account_security.TWO_FACTOR_AVAILABLE, 'pyotp/qrcode not installed')
    def test_disabling_needs_password_and_code(self):
        import pyotp
        secret = self._enable()
        self.client.force_login(self.teacher_user)
        self._security(security_action='totp_disable', security_password='pass-1234', totp_code='000000')
        self.assertTrue(account_security.two_factor_enabled(self.teacher_user))
        later = timezone.now() + timedelta(seconds=60)  # a fresh step; the enrollment code cannot be replayed
        with mock.patch('django.utils.timezone.now', return_value=later):
            self._security(security_action='totp_disable', security_password='pass-1234', totp_code=pyotp.TOTP(secret).at(later))
        self.assertFalse(account_security.two_factor_enabled(self.teacher_user))


class SuperAdminExamEditScopeTests(_ScopedOrgFixture):
    """صفحه‌ی ویرایش آزمون مدیر آموزشی: فهرست‌ها و هر شناسه‌ی ارسالی باید داخل محدوده‌ی او باشد."""

    def _post(self, step, **data):
        self.client.force_login(self.manager_user)
        return self.client.post(reverse('core:super_admin_exam_edit', args=[self.exam_in_id]), {'edit_step': step, **data})

    def test_pickers_are_scoped(self):
        self.client.force_login(self.manager_user)
        ctx = self.client.get(reverse('core:super_admin_exam_edit', args=[self.exam_in_id])).context
        self.assertNotIn(self.course_out_id, {c['id'] for c in ctx['courses']})
        self.assertNotIn(self.teacher_out_id, {t['id'] for t in ctx['teachers']})
        self.assertNotIn(self.group_out_id, {g['id'] for g in ctx['groups']})
        self.assertNotIn(self.student_out_id, {s['id'] for s in ctx['students']})
        self.assertNotIn(self.question_out_id, {q['id'] for q in ctx['questions']})
        self.assertIn(self.group_in_id, {g['id'] for g in ctx['groups']})

    def test_out_of_scope_ids_are_rejected_per_step(self):
        cases = (
            ('1', {'title': 'x', 'course_id': self.course_out_id}),
            ('1', {'title': 'x', 'teacher_id': self.teacher_out_id}),
            ('2', {'group_ids': [self.group_out_id]}),
            ('2', {'student_ids': [self.student_out_id]}),
            ('3', {'question_ids': [self.question_out_id]}),
        )
        for step, data in cases:
            self.assertEqual(self._post(step, **data).status_code, 403, data)
        with connection.cursor() as cursor:
            cursor.execute('SELECT course_id, teacher_id FROM exams WHERE id = %s', [self.exam_in_id])
            self.assertEqual(tuple(map(str, cursor.fetchone())), (self.course_in_id, self.teacher_in_id))
            cursor.execute('SELECT COUNT(*) FROM exam_assignments WHERE exam_id = %s', [self.exam_in_id])
            self.assertEqual(cursor.fetchone()[0], 0)

    def test_in_scope_assignment_is_saved(self):
        response = self._post('2', group_ids=[self.group_in_id], student_ids=[self.student_in_id])
        self.assertEqual(response.status_code, 302)
        with connection.cursor() as cursor:
            cursor.execute('SELECT COUNT(*) FROM exam_assignments WHERE exam_id = %s', [self.exam_in_id])
            self.assertEqual(cursor.fetchone()[0], 2)


class TeacherExamReportTests(_ScopedOrgFixture):
    """صفحه‌های «نتایج» و «پایش زنده» استاد: داده‌ی واقعی آزمون خود او، و ۴۰۴ برای آزمون استاد دیگر."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        User = get_user_model()
        cls.teacher_user = User.objects.create_user(username='teacher_in_scope', email='t_in@example.com', password='x')

    def _attempt(self, exam_id, status, score=None, max_score=20):
        _insert('exam_attempts', ['id', 'exam_id', 'student_id', 'started_at', 'status', 'score', 'max_score', 'is_graded'],
                [str(uuid.uuid4()), exam_id, self.student_in_id, timezone.now(), status, score, max_score, score is not None])

    def test_results_use_real_scores(self):
        self._attempt(self.exam_in_id, 'graded', 18)
        self._attempt(self.exam_in_id, 'graded', 6)
        self._attempt(self.exam_in_id, 'submitted')
        self.client.force_login(self.teacher_user)
        response = self.client.get(reverse('core:teacher_results'), {'exam': self.exam_in_id})
        report = response.context['report']
        self.assertEqual((report['average'], report['highest'], report['lowest'], report['ungraded']), (12.0, 18.0, 6.0, 1))
        self.assertEqual(report['pass_rate'], 50)
        self.assertEqual([bucket['count'] for bucket in report['buckets']], [0, 1, 0, 0, 1])
        page = response.content.decode()
        for leftover in ('۶۴.۲', '۹۸.۵', '۷۲.۶٪', 'انتشار نتایج برای دانشجویان'):
            self.assertNotIn(leftover, page)

    def test_results_default_to_exam_with_submissions(self):
        self._attempt(self.exam_in_id, 'graded', 15)
        self.client.force_login(self.teacher_user)
        response = self.client.get(reverse('core:teacher_results'))
        self.assertEqual(str(response.context['report_exam']['id']), self.exam_in_id)

    def test_monitoring_counts_live_attempts(self):
        from datetime import timedelta
        with connection.cursor() as cursor:
            cursor.execute('UPDATE exams SET start_at = %s, end_at = %s WHERE id = %s',
                           [timezone.now() - timedelta(minutes=10), timezone.now() + timedelta(minutes=50), self.exam_in_id])
        self._attempt(self.exam_in_id, 'in_progress')
        self.client.force_login(self.teacher_user)
        response = self.client.get(reverse('core:teacher_monitoring'))
        report = response.context['report']
        self.assertTrue(report['is_running'])
        self.assertEqual((report['in_progress'], report['submitted'], len(report['rows'])), (1, 0, 1))
        self.assertGreater(report['remaining_seconds'], 0)
        page = response.content.decode()
        for leftover in ('اصول حسابداری', 'قفل کردن آزمون', 'سارا محمدی قطع اتصال داشت'):
            self.assertNotIn(leftover, page)

    def test_other_teachers_exam_is_404(self):
        self.client.force_login(self.teacher_user)
        for name in ('core:teacher_results', 'core:teacher_monitoring'):
            self.assertEqual(self.client.get(reverse(name), {'exam': self.exam_out_id}).status_code, 404)


class StudentExamAccessFallbackTests(_ScopedOrgFixture):
    """دانشجو با دانستن شناسه نباید به آزمون دیگران برسد؛ قبلاً هر دو تابع دسترسی بدون شرط به همه‌ی آزمون‌ها برمی‌گشتند."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        User = get_user_model()
        cls.student_user = User.objects.create_user(username='student_in_scope', email='s_in@example.com', password='x')
        with connection.cursor() as cursor:
            cursor.execute('UPDATE exams SET is_published = %s, lifecycle_status = %s WHERE id = %s', [True, 'published', cls.exam_out_id])
        _insert('exam_assignments', ['id', 'exam_id', 'group_id'], [str(uuid.uuid4()), cls.exam_out_id, cls.group_out_id])

    def test_other_groups_exam_is_not_listed_or_reachable(self):
        from apps.core.views import _sx_accessible_exams
        self.assertEqual(_sx_accessible_exams(self.student_in_id), [])
        self.client.force_login(self.student_user)
        for name in ('core:student_exam_detail', 'core:student_exam_entry', 'core:student_exam_start'):
            self.assertEqual(self.client.get(reverse(name, args=[self.exam_out_id])).status_code, 404, name)
        with connection.cursor() as cursor:
            cursor.execute('SELECT COUNT(*) FROM exam_attempts WHERE exam_id = %s', [self.exam_out_id])
            self.assertEqual(cursor.fetchone()[0], 0)

    def test_student_keeps_access_to_an_exam_they_already_attempted(self):
        from apps.core.views import _sx_exam_row
        _insert('exam_attempts', ['id', 'exam_id', 'student_id', 'started_at', 'status'],
                [str(uuid.uuid4()), self.exam_out_id, self.student_in_id, timezone.now(), 'submitted'])
        self.assertIsNotNone(_sx_exam_row(self.exam_out_id, self.student_in_id))
        self.assertIsNone(_sx_exam_row(self.exam_out_id, self.student_out_id))


class StudentExamStartWindowTests(_ScopedOrgFixture):
    """شروع آزمون فقط در بازه‌ی برگزاری مجاز است؛ قبلاً با فراخوانی مستقیم آدرس شروع، هر زمانی شروع می‌شد."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        User = get_user_model()
        cls.student_user = User.objects.create_user(username='student_in_scope', email='s_in@example.com', password='x')
        with connection.cursor() as cursor:
            cursor.execute('UPDATE exams SET is_published = %s, lifecycle_status = %s, duration_minutes = 30 WHERE id = %s',
                           [True, 'published', cls.exam_in_id])
        _insert('exam_assignments', ['id', 'exam_id', 'student_profile_id'], [str(uuid.uuid4()), cls.exam_in_id, cls.student_in_id])

    def _window(self, start_minutes, end_minutes):
        now = timezone.now()
        with connection.cursor() as cursor:
            cursor.execute('UPDATE exams SET start_at = %s, end_at = %s WHERE id = %s',
                           [now + timedelta(minutes=start_minutes), now + timedelta(minutes=end_minutes), self.exam_in_id])

    def _attempts(self):
        with connection.cursor() as cursor:
            cursor.execute('SELECT COUNT(*) FROM exam_attempts WHERE exam_id = %s', [self.exam_in_id])
            return cursor.fetchone()[0]

    def test_start_is_refused_outside_the_exam_window(self):
        url = reverse('core:student_exam_start', args=[self.exam_in_id])
        detail = reverse('core:student_exam_detail', args=[self.exam_in_id])
        self.client.force_login(self.student_user)
        for window, message in (((10, 40), 'آزمون هنوز شروع نشده است.'), ((-60, -30), 'زمان ورود به این آزمون به پایان رسیده است.')):
            self._window(*window)
            response = self.client.post(url, follow=True)
            self.assertRedirects(response, detail)
            self.assertContains(response, message)
            self.assertEqual(self._attempts(), 0)
        self._window(10, 40)
        self.assertNotContains(self.client.get(detail), 'آماده‌ام؛ ورود به آزمون')

    def test_detail_links_the_uploaded_guide_only_when_there_is_one(self):
        self._window(-5, 25)
        detail = reverse('core:student_exam_detail', args=[self.exam_in_id])
        self.client.force_login(self.student_user)
        self.assertNotContains(self.client.get(detail), 'دانلود راهنمای آزمون')
        with connection.cursor() as cursor:
            cursor.execute('UPDATE exams SET guidance_file_url = %s WHERE id = %s', ['/media/exam-guidance/guide.pdf', self.exam_in_id])
        page = self.client.get(detail)
        self.assertContains(page, 'href="/media/exam-guidance/guide.pdf"')
        self.assertNotContains(page, 'href="#"')

    def test_start_is_refused_after_the_last_entry_time(self):
        self._window(-30, 30)
        with connection.cursor() as cursor:
            cursor.execute('UPDATE exams SET last_entry_at = %s WHERE id = %s', [timezone.now() - timedelta(minutes=5), self.exam_in_id])
        self.client.force_login(self.student_user)
        response = self.client.post(reverse('core:student_exam_start', args=[self.exam_in_id]), follow=True)
        self.assertContains(response, 'زمان ورود به این آزمون به پایان رسیده است.')
        self.assertEqual(self._attempts(), 0)

    def test_a_future_last_entry_time_still_lets_students_in(self):
        # last_entry_at is 'timestamp without time zone' (UTC on PostgreSQL); it was read as Tehran time, 3:30 early.
        self._window(-30, 120)
        with connection.cursor() as cursor:
            cursor.execute('UPDATE exams SET last_entry_at = %s WHERE id = %s', [timezone.now() + timedelta(minutes=30), self.exam_in_id])
        self.client.force_login(self.student_user)
        response = self.client.post(reverse('core:student_exam_start', args=[self.exam_in_id]))
        self.assertTrue(response['Location'].startswith('/student/attempts/'))
        self.assertEqual(self._attempts(), 1)

    def test_started_attempt_can_be_resumed_after_the_window_closes(self):
        url = reverse('core:student_exam_start', args=[self.exam_in_id])
        self.client.force_login(self.student_user)
        self._window(-5, 25)
        self.assertEqual(self.client.post(url).status_code, 302)
        self.assertEqual(self._attempts(), 1)
        self._window(-40, -1)
        response = self.client.post(url)
        self.assertTrue(response['Location'].startswith('/student/attempts/'))
        self.assertEqual(self._attempts(), 1)


class StudentPracticeExamAccessTests(_ScopedOrgFixture):
    """آزمون آزمایشی (exam_mode='practice') بخش جدای خودش را دارد: چند بار قابل تکرار تا سقف تعداد تلاش، با حالت انتخابی،
    و هرگز قاطی آزمون‌ها و نتایج درسی دانشجو نمی‌شود. دسترسی همان قاعده‌ی تخصیص آزمون‌های درسی است."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        User = get_user_model()
        cls.student_user = User.objects.create_user(username='student_in_scope', email='s_in@example.com', password='x')
        now = timezone.now()
        day = timedelta(days=1)
        cls.practice_id = TeacherStudentScopeTests._exam('آزمون آزمایشی من', cls.teacher_in_id, now - day, now + day, cls.group_in_id)
        cls.course_exam_id = TeacherStudentScopeTests._exam('آزمون درسی من', cls.teacher_in_id, now - day, now + day, cls.group_in_id)
        cls.other_practice_id = TeacherStudentScopeTests._exam('آزمون آزمایشی دیگران', cls.teacher_out_id, now - day, now + day, cls.group_out_id)
        TeacherStudentScopeTests._member(cls.group_in_id, cls.student_in_id)
        with connection.cursor() as cursor:
            cursor.execute("UPDATE exams SET exam_mode = 'practice', max_attempts = 2 WHERE id IN (%s, %s)", [cls.practice_id, cls.other_practice_id])
        for exam_id in (cls.practice_id, cls.other_practice_id):
            _insert('exam_questions', ['id', 'exam_id', 'question_id', 'points', 'order_index'], [str(uuid.uuid4()), exam_id, cls.question_in_id, 2, 1])

    def setUp(self):
        self.client.force_login(self.student_user)
        self.start_url = reverse('core:student_practice_start', args=[self.practice_id])

    def _attempts(self, exam_id=None):
        with connection.cursor() as cursor:
            cursor.execute('SELECT id, practice_mode FROM exam_attempts WHERE exam_id = %s ORDER BY started_at', [exam_id or self.practice_id])
            return cursor.fetchall()

    def _refusal(self):
        from django.contrib.messages import get_messages
        response = self.client.post(self.start_url, {'accept_rules': '1'})
        self.assertRedirects(response, reverse('core:student_practice_detail', args=[self.practice_id]), fetch_redirect_response=False)
        return ' '.join(str(message) for message in get_messages(response.wsgi_request))

    def _submit_all(self):
        with connection.cursor() as cursor:
            cursor.execute("UPDATE exam_attempts SET submitted_at = %s, status = 'graded' WHERE exam_id = %s",
                           [timezone.now(), self.practice_id])

    def test_practice_and_course_exams_are_listed_apart(self):
        from apps.core.views import _sx_accessible_exams
        self.assertEqual([row['title'] for row in _sx_accessible_exams(self.student_in_id)], ['آزمون درسی من'])
        self.assertEqual([row['title'] for row in _sx_accessible_exams(self.student_in_id, practice=True)], ['آزمون آزمایشی من'])
        self.assertEqual(_sx_accessible_exams(self.student_out_id, practice=True), [])  # not a member of group_out
        self.assertNotContains(self.client.get(reverse('core:student_exam_schedule')), 'آزمون آزمایشی من')

    def test_course_exam_flow_sends_practice_exams_to_their_section(self):
        for name in ('core:student_exam_detail', 'core:student_exam_entry', 'core:student_exam_start'):
            response = self.client.post(reverse(name, args=[self.practice_id]))
            self.assertRedirects(response, reverse('core:student_practice_detail', args=[self.practice_id]),
                                 fetch_redirect_response=False, msg_prefix=name)
        self.assertEqual(self._attempts(), [])

    def test_start_needs_the_rules_and_keeps_the_chosen_mode(self):
        self.client.post(self.start_url, {'mode': 'simulation'})
        self.assertEqual(self._attempts(), [])
        response = self.client.post(self.start_url, {'mode': 'simulation', 'accept_rules': '1'})
        (attempt_id, mode), = self._attempts()
        self.assertEqual(mode, 'simulation')
        self.assertRedirects(response, reverse('core:student_attempt', args=[attempt_id]), fetch_redirect_response=False)
        self.client.post(self.start_url, {'mode': 'tutorial', 'accept_rules': '1'})  # resumes the unfinished one
        self.assertEqual(self._attempts(), [(attempt_id, 'simulation')])
        self.client.post(reverse('core:student_practice_start', args=[self.course_exam_id]), {'accept_rules': '1'})
        self.assertEqual(self._attempts(self.course_exam_id), [])  # the course exam is not a practice exam: 404

    def test_attempts_are_capped_by_the_exams_limit(self):
        for _ in range(2):
            self.client.post(self.start_url, {'mode': 'bogus', 'accept_rules': '1'})
            self._submit_all()
        self.assertEqual([mode for _id, mode in self._attempts()], ['tutorial', 'tutorial'])
        self.assertEqual(self._refusal(), 'تعداد دفعات مجاز شرکت در این آزمون آزمایشی به پایان رسیده است.')
        self.assertEqual(len(self._attempts()), 2)
        with connection.cursor() as cursor:  # no limit (0) means as many as the student likes
            cursor.execute('UPDATE exams SET max_attempts = 0 WHERE id = %s', [self.practice_id])
        self.client.post(self.start_url, {'accept_rules': '1'})
        self.assertEqual(len(self._attempts()), 3)

    def test_unstarted_or_foreign_practice_exam_cannot_be_started(self):
        with connection.cursor() as cursor:
            cursor.execute('UPDATE exams SET start_at = %s WHERE id = %s', [timezone.now() + timedelta(hours=1), self.practice_id])
        self.assertEqual(self._refusal(), 'این آزمون آزمایشی هنوز شروع نشده است.')
        other = reverse('core:student_practice_start', args=[self.other_practice_id])
        self.assertEqual(self.client.post(other, {'accept_rules': '1'}).status_code, 404)
        self.assertEqual(self._attempts() + self._attempts(self.other_practice_id), [])

    def test_practice_results_stay_out_of_course_results_and_show_at_once(self):
        from apps.core.views import _sx_result_rows
        TeacherStudentScopeTests._attempt(self.practice_id, self.student_in_id, timezone.now() - timedelta(hours=1), 'graded', 2, 2)
        TeacherStudentScopeTests._attempt(self.course_exam_id, self.student_in_id, timezone.now() - timedelta(hours=1), 'graded', 15, 20)
        self.assertEqual([row['title'] for row in _sx_result_rows(self.student_in_id, practice=False)], ['آزمون درسی من'])
        practice, = _sx_result_rows(self.student_in_id, practice=True)
        self.assertEqual((practice['is_pending'], practice['percent']), (False, 100))  # no publishing step for practice
        self.assertTrue(practice['visibility']['correct_answers'] and practice['visibility']['explanations'])
        course, = _sx_result_rows(self.student_in_id, practice=False)
        self.assertTrue(course['awaiting_publication'])  # course exams still wait for the results to be published
        dashboard = self.client.get(reverse('core:dashboard')).context['student_dashboard']
        self.assertEqual(dashboard['results'], [])


    def test_list_page_shows_own_practice_exams_and_attempts(self):
        with connection.cursor() as cursor:
            cursor.execute("UPDATE exams SET tags = %s, description = %s WHERE id = %s", ['مفهومی، تحلیلی', 'مرور فصل ۱', self.practice_id])
        TeacherStudentScopeTests._attempt(self.practice_id, self.student_in_id, timezone.now() - timedelta(hours=2), 'graded', 1, 2)
        response = self.client.get(reverse('core:student_practice_exam'))
        self.assertEqual(response.status_code, 200)
        card, = response.context['page_obj'].object_list
        self.assertEqual((card['title'], card['tags'], card['used'], card['limit']), ('آزمون آزمایشی من', ['مفهومی', 'تحلیلی'], 1, 2))
        self.assertEqual(card['action'], {'label': 'تمرین دوباره', 'url': reverse('core:student_practice_detail', args=[self.practice_id])})
        attempt, = response.context['recent_attempts']
        self.assertEqual((attempt['percent'], attempt['state_label'], attempt['minutes']), (50, 'پایان یافته', 30))
        self.assertEqual(response.context['tags'], ['تحلیلی', 'مفهومی'])
        for hidden in ('آزمون آزمایشی دیگران', 'آزمون درسی من', 'پاسخ سؤال آزمایشی'):
            self.assertNotContains(response, hidden)
        filtered = self.client.get(reverse('core:student_practice_exam'), {'tag': 'محاسباتی'})
        self.assertEqual(list(filtered.context['page_obj'].object_list), [])

    def test_list_card_offers_only_what_the_server_would_allow(self):
        self.client.post(self.start_url, {'accept_rules': '1'})
        (attempt_id, _mode), = self._attempts()
        card, = self.client.get(reverse('core:student_practice_exam')).context['page_obj'].object_list
        self.assertEqual(card['action'], {'label': 'ادامه تمرین', 'url': reverse('core:student_attempt', args=[attempt_id])})
        self._submit_all()
        self.client.post(self.start_url, {'accept_rules': '1'})
        self._submit_all()
        card, = self.client.get(reverse('core:student_practice_exam')).context['page_obj'].object_list
        self.assertEqual(card['action'], {'label': 'سقف تلاش تکمیل شد', 'url': ''})

    def test_preparation_page(self):
        url = reverse('core:student_practice_detail', args=[self.practice_id])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual([mode['key'] for mode in response.context['modes']], ['tutorial', 'simulation'])
        self.assertContains(response, f'action="{self.start_url}"')
        self.assertContains(response, 'این آزمون نیازی به میکروفون ندارد.')
        self.assertContains(response, 'حداکثر ۲ بار می‌توانید در این آزمون شرکت کنید')
        for exam_id in (self.other_practice_id, self.course_exam_id):
            self.assertEqual(self.client.get(reverse('core:student_practice_detail', args=[exam_id])).status_code, 404)
        self.client.post(self.start_url, {'mode': 'simulation', 'accept_rules': '1'})
        (attempt_id, _mode), = self._attempts()
        resumed = self.client.get(url)
        self.assertContains(resumed, reverse('core:student_attempt', args=[attempt_id]))
        self.assertContains(resumed, 'حالت شبیه‌ساز')
        self.assertNotContains(resumed, f'action="{self.start_url}"')
        self._submit_all()
        self.client.post(self.start_url, {'accept_rules': '1'})
        self._submit_all()
        refused = self.client.get(url)
        self.assertContains(refused, 'تعداد دفعات مجاز شرکت در این آزمون آزمایشی به پایان رسیده است.')
        self.assertNotContains(refused, '<button class="sx-btn primary" type="submit">')

class StudentPracticeTutorialTests(_ScopedOrgFixture):
    """حالت آموزشی: «ثبت پاسخ و مشاهده بازخورد» پاسخ را با همان قواعد تصحیح ارزیابی و قفل می‌کند؛ حالت شبیه‌ساز و آزمون درسی بازخورد ندارند."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        User = get_user_model()
        cls.student_user = User.objects.create_user(username='student_in_scope', email='s_in@example.com', password='x')
        now = timezone.now()
        cls.exam_id = TeacherStudentScopeTests._exam('آزمون آزمایشی دارویی', cls.teacher_in_id, now - timedelta(days=1), now + timedelta(days=1), cls.group_in_id)
        TeacherStudentScopeTests._member(cls.group_in_id, cls.student_in_id)
        with connection.cursor() as cursor:
            cursor.execute("UPDATE exams SET exam_mode = 'practice', max_attempts = 0, duration_minutes = 30 WHERE id = %s", [cls.exam_id])
        cls.question_id = str(uuid.uuid4())
        _insert('questions', ['id', 'teacher_id', 'course_id', 'text', 'type', 'options', 'correct_answer', 'feedback', 'default_points'],
                [cls.question_id, cls.teacher_in_id, cls.course_in_id, 'کدام اقدام پیش از تجویز دارو ضروری است؟', 'single',
                 json.dumps(['بررسی هویت بیمار', 'ثبت دارو در پرونده'], ensure_ascii=False), json.dumps('بررسی هویت بیمار', ensure_ascii=False),
                 json.dumps({'text': 'تطبیق هویت بیمار بخشی از ایمنی دارویی است.', 'correct': 'آفرین!', 'incorrect': 'مبحث ایمنی دارویی را مرور کنید.',
                             'resource_title': 'مرور مبحث ایمنی دارویی', 'resource_url': 'https://example.com/drug-safety'}, ensure_ascii=False), 2])
        _insert('exam_questions', ['id', 'exam_id', 'question_id', 'points', 'order_index'], [str(uuid.uuid4()), cls.exam_id, cls.question_id, 2, 1])

    def setUp(self):
        self.client.force_login(self.student_user)

    def _start(self, mode):
        self.client.post(reverse('core:student_practice_start', args=[self.exam_id]), {'mode': mode, 'accept_rules': '1'})
        with connection.cursor() as cursor:
            cursor.execute('SELECT id FROM exam_attempts WHERE exam_id = %s AND submitted_at IS NULL', [self.exam_id])
            return cursor.fetchone()[0]

    def _answer_row(self, attempt_id):
        with connection.cursor() as cursor:
            cursor.execute('SELECT answer, is_correct, points_awarded, feedback_shown_at FROM attempt_answers WHERE attempt_id = %s', [attempt_id])
            return cursor.fetchone()

    def test_feedback_grades_and_locks_the_answer(self):
        attempt_id = self._start('tutorial')
        url = reverse('core:student_attempt', args=[attempt_id])
        page = self.client.get(url)
        self.assertContains(page, 'ثبت پاسخ و مشاهده بازخورد')
        self.assertContains(page, 'qx-practice-badge')
        self.assertNotContains(page, 'تطبیق هویت بیمار بخشی از ایمنی دارویی است.')  # nothing of the key before answering
        answer = f'answer_{self.question_id}'
        self.client.post(f'{url}?q=1', {answer: 'ثبت دارو در پرونده', 'action': 'feedback'})
        stored, is_correct, points, shown_at = self._answer_row(attempt_id)
        self.assertEqual((json.loads(stored)['value'], bool(is_correct), float(points)), ('ثبت دارو در پرونده', False, 0.0))
        self.assertIsNotNone(shown_at)
        page = self.client.get(url)
        for text in ('پاسخ شما نادرست است', 'مبحث ایمنی دارویی را مرور کنید.', 'تطبیق هویت بیمار بخشی از ایمنی دارویی است.', 'پاسخ صحیح',
                     '<fieldset class="qx-lock" disabled>', 'href="https://example.com/drug-safety"'):
            self.assertContains(page, text)
        self.assertEqual([option['feedback'] for option in page.context['current_answer']['options']], ['correct', 'wrong'])
        # A locked answer keeps its value, through the form and the autosave alike; only the review mark still changes.
        self.client.post(f'{url}?q=1', {answer: 'بررسی هویت بیمار', f'mark_{self.question_id}': 'on', 'action': 'next'})
        self.assertEqual(json.loads(self._answer_row(attempt_id)[0])['value'], 'ثبت دارو در پرونده')
        self.assertTrue(self.client.get(url).context['current_answer']['marked'])
        self.client.post(url, {answer: 'بررسی هویت بیمار'}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')  # mark box left unticked
        self.assertEqual(json.loads(self._answer_row(attempt_id)[0])['value'], 'ثبت دارو در پرونده')
        self.assertFalse(self.client.get(url).context['current_answer']['marked'])

    def test_mark_without_an_answer_is_kept(self):
        attempt_id = self._start('simulation')
        url = reverse('core:student_attempt', args=[attempt_id])
        self.client.post(url, {f'seen_{self.question_id}': '1', f'mark_{self.question_id}': 'on'}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        page = self.client.get(url)
        self.assertTrue(page.context['current_answer']['marked'])
        self.assertFalse(page.context['current_answer']['answered'])
        self.client.post(url, {f'seen_{self.question_id}': '1'}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertFalse(self.client.get(url).context['current_answer']['marked'])

    def test_feedback_needs_an_answer(self):
        attempt_id = self._start('tutorial')
        response = self.client.post(f"{reverse('core:student_attempt', args=[attempt_id])}?q=1", {'action': 'feedback'}, follow=True)
        self.assertContains(response, 'برای دیدن بازخورد، ابتدا به سؤال پاسخ دهید.')
        self.assertIsNone(self._answer_row(attempt_id))

    def test_simulation_and_course_exams_give_no_feedback(self):
        attempt_id = self._start('simulation')
        url = reverse('core:student_attempt', args=[attempt_id])
        page = self.client.get(url)
        self.assertNotContains(page, 'ثبت پاسخ و مشاهده بازخورد')
        self.assertContains(page, 'پایان آزمون آزمایشی')
        for dialog in ('data-offline-dialog', 'data-timeup-dialog', "exam:time-up"):
            self.assertContains(page, dialog)
        self.client.post(f'{url}?q=1', {f'answer_{self.question_id}': 'بررسی هویت بیمار', 'action': 'feedback'})
        stored, is_correct, _points, shown_at = self._answer_row(attempt_id)
        self.assertEqual((json.loads(stored)['value'], is_correct, shown_at), ('بررسی هویت بیمار', None, None))
        with connection.cursor() as cursor:  # the same exam as a course exam: no practice parts at all
            cursor.execute("UPDATE exams SET exam_mode = 'standard' WHERE id = %s", [self.exam_id])
        page = self.client.get(url)
        self.assertIsNone(page.context['practice'])
        for text in ('qx-practice-badge', 'ثبت پاسخ و مشاهده بازخورد', '<fieldset class="qx-lock" disabled>', 'data-offline-dialog', 'data-timeup-dialog'):
            self.assertNotContains(page, text)

    def test_review_submit_receipt_and_report_card(self):
        with connection.cursor() as cursor:
            cursor.execute('UPDATE questions SET subject = %s WHERE id = %s', ['ایمنی دارویی', self.question_id])
        attempt_id = self._start('simulation')
        submit_url = reverse('core:student_attempt_submit', args=[attempt_id])
        receipt_url = reverse('core:student_attempt_receipt', args=[attempt_id])
        # Opening the receipt early must not close the attempt ungraded.
        self.assertRedirects(self.client.get(receipt_url), submit_url, fetch_redirect_response=False)
        review = self.client.get(submit_url)
        self.assertTemplateUsed(review, 'student/practice_review.html')
        self.assertEqual((review.context['answered_count'], review.context['unanswered_count']), (0, 1))
        self.assertContains(review, 'سؤال هنوز پاسخ داده نشده است.')
        self.client.post(f"{reverse('core:student_attempt', args=[attempt_id])}?q=1",
                         {f'answer_{self.question_id}': 'بررسی هویت بیمار', f'mark_{self.question_id}': 'on', 'action': 'next'})
        review = self.client.get(submit_url)
        self.assertEqual((review.context['unanswered_count'], review.context['marked_count']), (0, 1))
        self.assertRedirects(self.client.post(submit_url), receipt_url, fetch_redirect_response=False)
        receipt = self.client.get(receipt_url)
        self.assertTemplateUsed(receipt, 'student/practice_receipt.html')
        self.assertContains(receipt, 'MQ-P-')
        self.assertContains(receipt, reverse('core:student_result_detail', args=[attempt_id]))
        report = self.client.get(reverse('core:student_result_detail', args=[attempt_id]))
        self.assertTemplateUsed(report, 'student/practice_result.html')
        self.assertEqual((report.context['counts']['correct'], float(report.context['score']), report.context['topics']),
                         (1, 2.0, [{'title': 'ایمنی دارویی', 'percent': 100,
                                     'resources': [{'title': 'مرور مبحث ایمنی دارویی', 'url': 'https://example.com/drug-safety'}]}]))
        self.assertContains(report, 'تطبیق هویت بیمار بخشی از ایمنی دارویی است.')  # the builder's explanation
        self.assertEqual(report.context['topics'][0]['resources'],
                         [{'title': 'مرور مبحث ایمنی دارویی', 'url': 'https://example.com/drug-safety'}])
        self.assertContains(report, 'href="https://example.com/drug-safety"')
        self.assertEqual(report.context['retry'], {'label': 'تمرین دوباره', 'url': reverse('core:student_practice_detail', args=[self.exam_id])})
        self.assertEqual(report.context['review_topics'], [])

    def test_other_students_cannot_open_the_practice_pages(self):
        attempt_id = self._start('tutorial')
        User = get_user_model()
        self.client.force_login(User.objects.create_user(username='student_out_scope', email='s_out@example.com', password='x'))
        for name in ('core:student_attempt', 'core:student_attempt_submit', 'core:student_attempt_receipt', 'core:student_result_detail'):
            self.assertEqual(self.client.get(reverse(name, args=[attempt_id])).status_code, 404, name)
        self.assertEqual(self.client.post(reverse('core:student_attempt', args=[attempt_id]), {'action': 'feedback'}).status_code, 404)

    def test_connection_events_reach_the_activity_log_for_own_attempts_only(self):
        attempt_id = self._start('tutorial')
        url = reverse('core:student_attempt_event', args=[attempt_id])
        self.assertEqual(self.client.post(url, {'event': 'disconnect'}).json(), {'ok': True, 'logged': True})
        self.assertEqual(self.client.post(url, {'event': 'reconnect'}).status_code, 200)
        self.assertEqual(self.client.post(url, {'event': 'bogus'}).status_code, 400)
        with connection.cursor() as cursor:
            cursor.execute("SELECT action FROM activity_audit_log WHERE action LIKE 'exam_%%connected' ORDER BY action")
            self.assertEqual([row[0] for row in cursor.fetchall()], ['exam_disconnected', 'exam_reconnected'])
        User = get_user_model()
        self.client.force_login(User.objects.create_user(username='student_out_scope', email='s_out@example.com', password='x'))
        self.assertEqual(self.client.post(url, {'event': 'disconnect'}).status_code, 404)

class UnassignedExamAccessTests(_ScopedOrgFixture):
    """آزمونی که هیچ تخصیصی ندارد برای هیچ دانشجویی باز نیست؛ مسیرهای ایجاد سریع گروه را به‌عنوان مخاطب ذخیره می‌کنند."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        User = get_user_model()
        cls.student_user = User.objects.create_user(username='student_in_scope', email='s_in@example.com', password='x')
        with connection.cursor() as cursor:
            cursor.execute('UPDATE exams SET is_published = %s, lifecycle_status = %s WHERE id = %s', [True, 'published', cls.exam_in_id])

    def _accessible(self):
        from apps.core.views import _sx_accessible_exams
        return {str(row['id']) for row in _sx_accessible_exams(self.student_in_id)}

    def test_published_exam_without_assignment_is_hidden(self):
        self.assertNotIn(self.exam_in_id, self._accessible())
        self.client.force_login(self.student_user)
        self.assertEqual(self.client.get(reverse('core:student_exam_detail', args=[self.exam_in_id])).status_code, 404)

    def test_group_assignment_opens_it_for_members_only(self):
        _insert('student_group_members', ['id', 'group_id', 'student_user_id', 'full_name', 'national_id', 'student_number'],
                [str(uuid.uuid4()), self.group_in_id, self.student_in_id, 'دانشجو', '1', '1'])
        _insert('exam_assignments', ['id', 'exam_id', 'group_id'], [str(uuid.uuid4()), self.exam_in_id, self.group_in_id])
        self.assertIn(self.exam_in_id, self._accessible())
        from apps.core.views import _sx_accessible_exams
        self.assertNotIn(self.exam_in_id, {str(row['id']) for row in _sx_accessible_exams(self.student_out_id)})

    def test_quick_create_saves_the_group_as_audience(self):
        self.client.force_login(self.manager_user)
        response = self.client.post(reverse('core:super_admin_exams'), {
            'exam_action': 'create', 'group_id': self.group_in_id, 'title': 'آزمون سریع',
            'question_ids': [self.question_in_id], 'duration_minutes': '30',
        })
        exam_id = response.json().get('exam_id')
        self.assertTrue(response.json()['ok'], response.json())
        with connection.cursor() as cursor:
            cursor.execute('SELECT group_id FROM exam_assignments WHERE exam_id = %s', [exam_id])
            self.assertEqual([str(row[0]) for row in cursor.fetchall()], [self.group_in_id])


class TeacherExamEditTests(_ScopedOrgFixture):
    """ویرایش آزمون استاد با همان ویزارد: فقط آزمون خودش، فقط تا پیش از انتشار و شرکت دانشجو."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        User = get_user_model()
        cls.teacher_user = User.objects.create_user(username='teacher_in_scope', email='t_in@example.com', password='x')

    def setUp(self):
        self.client.force_login(self.teacher_user)
        self.client.post(reverse('core:teacher_exam_create'), {
            'title': 'آزمون قابل ویرایش', 'course_id': self.course_in_id, 'group_ids': [self.group_in_id],
            'question_ids': [self.question_in_id, self.question_in2_id], 'duration_minutes': '60',
            'start_at': '2026-11-10T09:00', 'tags': 'قلب، عروق', 'publish_choice': 'submit',
        })
        with connection.cursor() as cursor:
            cursor.execute("SELECT id FROM exams WHERE title = 'آزمون قابل ویرایش'")
            self.exam_id = cursor.fetchone()[0]
        self.url = reverse('core:teacher_exam_edit', args=[self.exam_id])

    def _rows(self, sql):
        with connection.cursor() as cursor:
            cursor.execute(sql, [self.exam_id])
            return [tuple(str(v) if isinstance(v, uuid.UUID) else v for v in row) for row in cursor.fetchall()]

    def test_get_prefills_wizard_with_saved_exam(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        initial = response.context['wizard_initial']
        self.assertEqual(initial['fields']['title'], 'آزمون قابل ویرایش')
        self.assertEqual(initial['fields']['start_at'], '2026-11-10T09:00')
        self.assertEqual(initial['question_ids'], [self.question_in_id, self.question_in2_id])
        self.assertEqual(initial['group_ids'], [self.group_in_id])
        self.assertEqual(initial['tags'], ['قلب', 'عروق'])
        self.assertEqual(initial['publish_choice'], 'submit')
        self.assertIn('id="wizard-initial"', response.content.decode())
        self.assertIn('ویرایش آزمون', response.content.decode())

    def test_post_updates_in_place_and_replaces_children(self):
        response = self.client.post(self.url, {
            'title': 'آزمون ویرایش‌شده', 'course_id': self.course_in_id, 'group_ids': [self.group_in_id],
            'question_ids': [self.question_in2_id], 'duration_minutes': '45', 'publish_choice': 'draft',
        })
        self.assertTrue(response['Location'].startswith(reverse('core:teacher_exams') + '?saved='))
        self.assertEqual(self._rows('SELECT title, duration_minutes, lifecycle_status, teacher_id FROM exams WHERE id = %s'),
                         [('آزمون ویرایش‌شده', 45, 'draft', self.teacher_in_id)])
        self.assertEqual(self._rows('SELECT question_id FROM exam_questions WHERE exam_id = %s'), [(self.question_in2_id,)])
        self.assertEqual(self._rows('SELECT group_id FROM exam_assignments WHERE exam_id = %s'), [(self.group_in_id,)])
        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM exams WHERE title LIKE 'آزمون%%ویرایش%%'")
            self.assertEqual(cursor.fetchone()[0], 1)

    def test_wizard_offers_unlimited_attempts(self):
        self.assertContains(self.client.get(self.url), '<option value="0">نامحدود</option>')
        for posted, stored in (('0', 0), ('abc', 1), ('99', 10)):
            self.client.post(self.url, {
                'title': 'آزمون قابل ویرایش', 'course_id': self.course_in_id, 'group_ids': [self.group_in_id],
                'question_ids': [self.question_in_id], 'exam_mode': 'practice', 'max_attempts': posted, 'publish_choice': 'draft',
            })
            self.assertEqual(self._rows('SELECT exam_mode, max_attempts FROM exams WHERE id = %s'), [('practice', stored)], posted)

    def test_out_of_scope_ids_rejected_on_edit(self):
        response = self.client.post(self.url, {
            'title': 'x', 'course_id': self.course_in_id, 'group_ids': [self.group_out_id], 'question_ids': [self.question_in_id],
        })
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self._rows('SELECT title FROM exams WHERE id = %s'), [('آزمون قابل ویرایش',)])

    def test_published_or_started_exam_is_not_editable(self):
        _insert('exam_attempts', ['id', 'exam_id', 'student_id', 'started_at', 'status'],
                [str(uuid.uuid4()), self.exam_id, self.student_in_id, timezone.now(), 'in_progress'])
        self.assertRedirects(self.client.get(self.url), reverse('core:teacher_exams'), fetch_redirect_response=False)
        self.assertRedirects(self.client.post(self.url, {'title': 'x'}), reverse('core:teacher_exams'), fetch_redirect_response=False)
        with connection.cursor() as cursor:
            cursor.execute('UPDATE exams SET is_published = %s, lifecycle_status = %s WHERE id = %s', [True, 'published', self.exam_out_id])
        self.assertEqual(self.client.get(reverse('core:teacher_exam_edit', args=[self.exam_out_id])).status_code, 404)

    def test_exam_list_links_to_edit_only_when_editable(self):
        with connection.cursor() as cursor:
            cursor.execute('UPDATE exams SET is_published = %s, lifecycle_status = %s WHERE id = %s', [True, 'published', self.exam_in_id])
        page = self.client.get(reverse('core:teacher_exams')).content.decode()
        self.assertIn(self.url, page)
        self.assertNotIn(reverse('core:teacher_exam_edit', args=[self.exam_in_id]), page)

    def test_exam_with_items_outside_teacher_scope_is_not_editable(self):
        _insert('exam_questions', ['id', 'exam_id', 'question_id', 'points', 'order_index'],
                [str(uuid.uuid4()), self.exam_id, self.question_out_id, 1, 9])
        response = self.client.get(self.url)
        self.assertRedirects(response, reverse('core:teacher_exams'), fetch_redirect_response=False)
        self.assertEqual(len(self._rows('SELECT question_id FROM exam_questions WHERE exam_id = %s')), 3)  # nothing dropped


class MalformedIdNotFoundTests(TestCase):
    """شناسه‌ی غیر UUID در آدرس روی PostgreSQL خطای DataError می‌دهد؛ پاسخ باید ۴۰۴ باشد نه ۵۰۰، و خطاهای دیگر دست نخورند."""

    def test_only_the_uuid_syntax_error_becomes_404(self):
        from django.db import DataError
        from django.test import RequestFactory
        from apps.core.middleware import MalformedIdNotFoundMiddleware
        middleware = MalformedIdNotFoundMiddleware(lambda request: None)
        request = RequestFactory().get('/super-admin/exams/abc/')
        response = middleware.process_exception(request, DataError('invalid input syntax for type uuid: "abc"'))
        self.assertEqual(response.status_code, 404)
        self.assertIsNone(middleware.process_exception(request, DataError('value too long for type character varying(10)')))
        self.assertIsNone(middleware.process_exception(request, ValueError('invalid input syntax for type uuid')))


class AdminExamPagesOpenTests(_ScopedOrgFixture):
    """صفحه‌ی «آزمون‌های در حال برگزاری» با آدرس جزئیات آزمون گرفته می‌شد و داشبورد مدیر آموزشی برای مدیر سیستم خطای SQL می‌داد."""

    def test_active_exams_page_and_dashboard_open_for_admin(self):
        from django.urls import resolve
        self.assertEqual(resolve('/super-admin/exams/active/').url_name, 'super_admin_active_exams')
        self.client.force_login(self.admin_user)
        self.assertEqual(self.client.get(reverse('core:super_admin_active_exams')).status_code, 200)
        self.assertEqual(self.client.get(reverse('core:exam_manager_dashboard')).status_code, 200)


class ExamManagerGroupTeacherAssignTests(_ScopedOrgFixture):
    """انتساب استاد به گروه: فقط گروه‌ها و استادهای محدوده‌ی مدیر، و بدون SQL مخصوص SQLite (INSERT OR IGNORE)."""

    def _teachers(self, group_id):
        with connection.cursor() as cursor:
            cursor.execute('SELECT teacher_id FROM group_teachers WHERE group_id = %s', [group_id])
            return {str(row[0]) for row in cursor.fetchall()}

    def test_manager_assigns_only_inside_own_units(self):
        self.client.force_login(self.manager_user)
        url = reverse('core:exam_manager_group_teacher_assign')
        self.assertEqual(self.client.post(url, {'teacher_id': self.teacher_in_id, 'group_ids': [self.group_out_id]}).status_code, 403)
        self.assertEqual(self.client.post(url, {'teacher_id': self.teacher_out_id, 'group_ids': [self.group_in_id]}).status_code, 403)
        self.assertNotIn(self.teacher_in_id, self._teachers(self.group_out_id))
        for _ in range(2):  # the second time the row exists already
            self.assertEqual(self.client.post(url, {'teacher_id': self.teacher_in_id, 'group_ids': [self.group_in_id]}).status_code, 302)
        self.assertIn(self.teacher_in_id, self._teachers(self.group_in_id))


class QuestionBankForAdminsTests(_ScopedOrgFixture):
    """مدیر سیستم و مدیر آموزشی هم بانک سؤال دارند: مدیر سیستم برای هر درس، مدیر آموزشی فقط برای درس‌های واحد خودش."""

    def _create(self, text, course_id):
        return self.client.post(reverse('core:teacher_question_create'), {
            'type': 'single', 'structure': 'independent', 'text': text, 'course_id': course_id, 'default_points': '1',
            'option_text': ['الف', 'ب'], 'correct_options': '1', 'is_published': '1'})

    def _owner(self, text):
        with connection.cursor() as cursor:
            cursor.execute('SELECT teacher_id FROM questions WHERE text = %s', [text])
            row = cursor.fetchone()
            return str(row[0]) if row else None

    def test_admin_builds_questions_for_any_course(self):
        self.client.force_login(self.admin_user)
        self.assertEqual(self.client.get(reverse('core:teacher_questions')).status_code, 200)
        self.assertEqual(self._create('سؤال مدیر سیستم', self.course_out_id).status_code, 302)
        owner = self._owner('سؤال مدیر سیستم')
        self.assertIsNotNone(owner)
        self.assertContains(self.client.get(reverse('core:teacher_questions')), 'سؤال مدیر سیستم')
        wizard = self.client.get(reverse('core:super_admin_exam_create'))
        self.assertIn('سؤال مدیر سیستم', [question['text'] for question in wizard.context['questions']])

    def test_manager_builds_questions_only_for_own_courses(self):
        self.client.force_login(self.manager_user)
        self.assertEqual(self._create('سؤال خارج واحد', self.course_out_id).status_code, 200)
        self.assertIsNone(self._owner('سؤال خارج واحد'))
        self.assertEqual(self._create('سؤال داخل واحد', self.course_in_id).status_code, 302)
        self.assertEqual(self._owner('سؤال داخل واحد'), self.manager_id)


class ExamManagerUserImportPageTests(_ScopedOrgFixture):
    """ورود گروهی مدیر آموزشی همان ورود گروهی مدیر سیستم است، فقط در واحدهای خود او؛ قبلاً صفحه‌ای نمایشی بود که چیزی ثبت نمی‌کرد."""

    HEADERS = ['نام', 'نام خانوادگی', 'کد ملی', 'کد دانشجویی', 'سال ورود', 'مقطع', 'رشته', 'واحد سازمانی', 'شماره همراه', 'ایمیل', 'گروه آموزشی', 'درس‌ها', 'وضعیت حساب']

    def _import(self, *rows):
        import csv
        from django.core.files.uploadedfile import SimpleUploadedFile
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(self.HEADERS)
        writer.writerows(rows)
        url = reverse('core:super_admin_student_bulk_import')
        self.client.post(url, {'step': '1', 'excel_file': SimpleUploadedFile('s.csv', buffer.getvalue().encode('utf-8-sig'))})
        return self.client.post(url, {'step': '4', 'confirm_final': '1', 'create_accounts': 'on'}, follow=True)

    def _usernames(self, *names):
        with connection.cursor() as cursor:
            cursor.execute(f"SELECT username FROM profiles WHERE username IN ({', '.join(['%s'] * len(names))}) ORDER BY 1", list(names))
            return [row[0] for row in cursor.fetchall()]

    def test_manager_imports_students_into_own_units_only(self):
        self.client.force_login(self.manager_user)
        self.assertRedirects(self.client.get(reverse('core:exam_manager_user_import'), {'kind': 'teachers'}),
                             reverse('core:super_admin_teacher_bulk_import'), fetch_redirect_response=False)
        row = lambda code, unit, national: ['سارا', 'نمونه', national, code, '1403', 'کارشناسی', 'پزشکی', unit, '09120000000', '', '', '', 'فعال']
        self._import(row('S-1001', 'واحد دیگر', '0012345671'))  # another unit: the whole import stops
        self.assertEqual(self._usernames('S-1001'), [])
        self._import(row('student_out_scope', 'واحد تحت مدیریت', '0012345672'))  # would overwrite a student of another unit
        with connection.cursor() as cursor:
            cursor.execute('SELECT full_name FROM profiles WHERE id = %s', [self.student_out_id])
            self.assertEqual(cursor.fetchone()[0], 'دانشجوی خارج محدوده')
        self._import(row('S-1002', 'واحد تحت مدیریت', '0012345673'))
        self.assertEqual(self._usernames('S-1002'), ['S-1002'])
        with connection.cursor() as cursor:
            cursor.execute("SELECT sp.org_unit_id FROM student_profiles sp JOIN profiles p ON p.id = sp.user_id WHERE p.username = 'S-1002'")
            self.assertEqual(str(cursor.fetchone()[0]), self.ou_scoped)

class SuperAdminManagerBulkImportTests(_ScopedOrgFixture):
    """ثبت گروهی «مدیر سیستم»: قبلاً برای او هم محدوده‌ی مدیر آموزشی نوشته می‌شد و کل ثبت با خطای کلید خارجی، نیمه‌کاره می‌ماند."""

    def test_system_admins_are_imported_whole(self):
        import csv
        from django.core.files.uploadedfile import SimpleUploadedFile
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(['نام', 'نام خانوادگی', 'کد ملی', 'شماره پرسنلی', 'شماره همراه', 'نوع مدیر', 'واحد سازمانی', 'الگوی دسترسی', 'ایمیل', 'وضعیت حساب'])
        writer.writerow(['سارا', 'مدیری', '0011223344', 'P-9001', '09120000001', 'مدیر سیستم', 'واحد تحت مدیریت', '', 'p9001@example.com', 'فعال'])
        writer.writerow(['رضا', 'آموزشی', '0011223355', 'P-9002', '09120000002', 'مدیر آموزشی', 'واحد تحت مدیریت', '', 'p9002@example.com', 'فعال'])
        self.client.force_login(self.admin_user)
        url = reverse('core:super_admin_manager_bulk_import')
        self.client.post(url, {'step': '1', 'excel_file': SimpleUploadedFile('m.csv', buffer.getvalue().encode('utf-8-sig'))})
        self.client.post(url, {'step': '4', 'confirm_final': '1', 'create_accounts': 'on'})
        with connection.cursor() as cursor:
            cursor.execute("""SELECT p.username, r.role, (SELECT COUNT(*) FROM academic_manager_scopes s WHERE s.manager_id = p.id)
                              FROM profiles p JOIN user_roles r ON r.user_id = p.id WHERE p.username IN ('P-9001', 'P-9002') ORDER BY 1""")
            self.assertEqual(cursor.fetchall(), [('P-9001', 'admin', 0), ('P-9002', 'academic_manager', 1)])
        self.assertTrue(get_user_model().objects.filter(username__in=['P-9001', 'P-9002']).count() == 2)


class StudentExamIntegrityTests(_ScopedOrgFixture):
    """راه‌های تقلب در آزمون درسی که در آزمون بار ۱۶۰ کاربره پیدا شد: کلید ترتیب/تطبیق در صفحه، رسید بدون تصحیح،
    آزمون لغوشده، شماره‌ی سؤال نامعتبر، پاسخ بیش از حد بزرگ و ترتیب ثابت سؤال‌ها."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        User = get_user_model()
        cls.student_user = User.objects.create_user(username='student_in_scope', email='s_in@example.com', password='x')
        now = timezone.now()
        cls.exam_id = TeacherStudentScopeTests._exam('آزمون درسی', cls.teacher_in_id, now - timedelta(minutes=5), now + timedelta(hours=2), cls.group_in_id)
        TeacherStudentScopeTests._member(cls.group_in_id, cls.student_in_id)
        with connection.cursor() as cursor:
            cursor.execute("UPDATE exams SET lifecycle_status = 'published', duration_minutes = 30 WHERE id = %s", [cls.exam_id])
        cls.ordering_id, cls.matching_id = str(uuid.uuid4()), str(uuid.uuid4())
        _insert('questions', ['id', 'teacher_id', 'course_id', 'text', 'type', 'ordering_items', 'default_points'],
                [cls.ordering_id, cls.teacher_in_id, cls.course_in_id, 'مسیر خون را مرتب کنید.', 'ordering',
                 json.dumps([{'text': 'دهلیز راست'}, {'text': 'بطن راست'}, {'text': 'ریه'}], ensure_ascii=False), 1])
        _insert('questions', ['id', 'teacher_id', 'course_id', 'text', 'type', 'matching_pairs', 'default_points'],
                [cls.matching_id, cls.teacher_in_id, cls.course_in_id, 'دارو را به گروهش وصل کنید.', 'matching',
                 json.dumps([{'left': 'آسپرین', 'right': 'NSAID'}, {'left': 'وارفارین', 'right': 'ضدانعقاد'}], ensure_ascii=False), 1])
        for order, question_id in enumerate((cls.ordering_id, cls.matching_id), start=1):
            _insert('exam_questions', ['id', 'exam_id', 'question_id', 'points', 'order_index'], [str(uuid.uuid4()), cls.exam_id, question_id, 1, order])

    def setUp(self):
        self.client.force_login(self.student_user)

    def _start(self):
        response = self.client.post(reverse('core:student_exam_start', args=[self.exam_id]))
        return response['Location'].rstrip('/').split('/')[-1]

    def _points(self, attempt_id):
        with connection.cursor() as cursor:
            cursor.execute('SELECT question_id, points_awarded FROM attempt_answers WHERE attempt_id = %s', [attempt_id])
            return {str(question_id): float(points or 0) for question_id, points in cursor.fetchall()}

    def test_ordering_and_matching_keys_stay_off_the_page(self):
        from apps.core.views import _sx_item_token
        attempt_id = self._start()
        url = reverse('core:student_attempt', args=[attempt_id])
        html = self.client.get(f'{url}?q=1').content.decode() + self.client.get(f'{url}?q=2').content.decode()
        values = re.findall(r'<li draggable="true" data-value="([^"]+)"', html) + re.findall(r'data-side="right" data-value="([^"]+)"', html)
        self.assertEqual(len(values), 5)
        self.assertFalse(any(value.isdigit() for value in values))
        # The guessable answers (1,2,…,n and i:i) are not this attempt's tokens, so nothing is stored.
        self.client.post(url, {f'answer_{self.ordering_id}': '1,2,3', f'answer_{self.matching_id}': '1:1,2:2'})
        with connection.cursor() as cursor:
            cursor.execute('SELECT answer FROM attempt_answers WHERE attempt_id = %s', [attempt_id])
            self.assertEqual({json.loads(row[0])['value'] for row in cursor.fetchall()}, {''})
        token = lambda question_id, value: _sx_item_token(attempt_id, question_id, value)
        self.client.post(url, {f'answer_{self.ordering_id}': ','.join(token(self.ordering_id, v) for v in '123'),
                               f'answer_{self.matching_id}': f'1:{token(self.matching_id, "1")},2:{token(self.matching_id, "2")}'})
        page = self.client.get(f'{url}?q=1')  # the saved order comes back as tokens, in the student's order
        self.assertEqual(page.context['current_answer']['answer'].split(',')[0], token(self.ordering_id, '1'))
        self.client.post(reverse('core:student_attempt_submit', args=[attempt_id]))
        self.assertEqual(self._points(attempt_id), {self.ordering_id: 1.0, self.matching_id: 1.0})

    def test_receipt_of_an_open_attempt_leads_to_the_submit_page(self):
        attempt_id = self._start()
        response = self.client.get(reverse('core:student_attempt_receipt', args=[attempt_id]))
        self.assertRedirects(response, reverse('core:student_attempt_submit', args=[attempt_id]), fetch_redirect_response=False)
        with connection.cursor() as cursor:
            cursor.execute('SELECT submitted_at FROM exam_attempts WHERE id = %s', [attempt_id])
            self.assertIsNone(cursor.fetchone()[0])

    def test_cancelled_exam_stops_taking_answers(self):
        attempt_id = self._start()
        with connection.cursor() as cursor:
            cursor.execute('UPDATE exams SET is_cancelled = %s WHERE id = %s', [True, self.exam_id])
        self.client.post(reverse('core:student_attempt', args=[attempt_id]), {f'answer_{self.ordering_id}': 'x'})
        self.assertEqual(self._points(attempt_id), {})

    def test_bad_question_index_and_oversized_answer(self):
        attempt_id = self._start()
        url = reverse('core:student_attempt', args=[attempt_id])
        self.assertEqual(self.client.get(f'{url}?q=abc').status_code, 200)
        essay_id = str(uuid.uuid4())
        _insert('questions', ['id', 'teacher_id', 'text', 'type', 'default_points'], [essay_id, self.teacher_in_id, 'تشریحی', 'essay', 1])
        _insert('exam_questions', ['id', 'exam_id', 'question_id', 'points', 'order_index'], [str(uuid.uuid4()), self.exam_id, essay_id, 1, 3])
        self.client.post(url, {f'answer_{essay_id}': 'ا' * 200000})
        with connection.cursor() as cursor:
            cursor.execute('SELECT answer FROM attempt_answers WHERE attempt_id = %s AND question_id = %s', [attempt_id, essay_id])
            self.assertEqual(len(json.loads(cursor.fetchone()[0])['value']), 50000)

    def test_shuffled_exam_gives_each_attempt_a_stable_order_of_its_own(self):
        from apps.core.views import _sx_attempt_rows
        attempt_id = self._start()
        base = [row['question_id'] for row in _sx_attempt_rows(attempt_id, self.student_in_id)]
        self.assertEqual(base, [self.ordering_id, self.matching_id])
        with connection.cursor() as cursor:
            cursor.execute('UPDATE exams SET shuffle_questions = %s WHERE id = %s', [True, self.exam_id])
        expected = list(base)
        random.Random(f'{attempt_id}-questions').shuffle(expected)
        for _ in range(2):
            self.assertEqual([row['question_id'] for row in _sx_attempt_rows(attempt_id, self.student_in_id)], expected)

    def test_attempt_time_never_runs_past_the_exam_end(self):
        with connection.cursor() as cursor:
            cursor.execute('UPDATE exams SET end_at = %s WHERE id = %s', [timezone.now() + timedelta(minutes=5), self.exam_id])
        attempt_id = self._start()
        url = reverse('core:student_attempt', args=[attempt_id])
        self.assertLessEqual(self.client.get(url).context['remaining_seconds'], 5 * 60)  # not the exam's 30 minutes
        with connection.cursor() as cursor:
            cursor.execute('UPDATE exams SET end_at = %s WHERE id = %s', [timezone.now() - timedelta(minutes=2), self.exam_id])
        self.assertEqual(self.client.get(url).context['remaining_seconds'], 0)
        self.client.post(url, {f'answer_{self.ordering_id}': 'x'})
        self.assertEqual(self._points(attempt_id), {})

    def test_an_attempt_is_answered_from_one_device(self):
        from django.test import Client
        attempt_id = self._start()
        url = reverse('core:student_attempt', args=[attempt_id])
        self.assertEqual(self.client.get(url).status_code, 200)  # binds the attempt to this session
        other = Client()
        other.force_login(self.student_user)
        self.assertContains(other.get(url), 'این آزمون روی دستگاه دیگری باز است')
        other.post(url, {f'answer_{self.ordering_id}': 'x', 'action': 'next'})
        self.assertEqual(other.post(url, {'x': '1'}, HTTP_X_REQUESTED_WITH='XMLHttpRequest').status_code, 423)
        other.post(reverse('core:student_attempt_submit', args=[attempt_id]))
        with connection.cursor() as cursor:
            cursor.execute('SELECT COUNT(*) FROM attempt_answers WHERE attempt_id = %s', [attempt_id])
            self.assertEqual(cursor.fetchone()[0], 0)
            cursor.execute('SELECT submitted_at FROM exam_attempts WHERE id = %s', [attempt_id])
            self.assertIsNone(cursor.fetchone()[0])
        other.post(url, {'action': 'take_over'})
        self.assertEqual(other.get(url).status_code, 200)
        self.assertEqual(self.client.post(url, {'x': '1'}, HTTP_X_REQUESTED_WITH='XMLHttpRequest').status_code, 423)  # the first device is out
        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM activity_audit_log WHERE action = 'attempt_device_takeover'")
            self.assertEqual(cursor.fetchone()[0], 1)

    def test_proctoring_signals_reach_the_teacher(self):
        with connection.cursor() as cursor:
            cursor.execute('UPDATE exams SET track_tab_exit = %s, fullscreen_required = %s WHERE id = %s', [True, True, self.exam_id])
        attempt_id = self._start()
        page = self.client.get(reverse('core:student_attempt', args=[attempt_id]))
        self.assertEqual(page.context['proctoring'], {'track': True, 'fullscreen': True, 'copy_paste': False,
                                                      'screenshot': False, 'webcam': False, 'mic': False})
        self.assertContains(page, "addEventListener('visibilitychange'")
        self.assertContains(page, 'requestFullscreen')
        url = reverse('core:student_attempt_event', args=[attempt_id])
        for event in ('tab_hidden', 'tab_hidden', 'fullscreen_exit', 'copy', 'paste', 'disconnect'):
            self.assertTrue(self.client.post(url, {'event': event}).json()['logged'])
        self.client.force_login(get_user_model().objects.create_user(username='teacher_in_scope', email='t_in@example.com', password='x'))
        report = self.client.get(reverse('core:teacher_monitoring'), {'exam': self.exam_id})
        self.assertEqual(report.context['report']['rows'][0]['flags'],
                         {'tab': 2, 'fullscreen': 1, 'copy_paste': 2, 'disconnect': 1, 'device': 0, 'screenshot': 0, 'camera': 0, 'total': 6})
        self.assertContains(report, 'خروج از صفحه ۲')

    def test_proctoring_log_has_a_ceiling_per_attempt(self):
        from apps.core import views
        attempt_id = self._start()
        url = reverse('core:student_attempt_event', args=[attempt_id])
        limit = views.ATTEMPT_EVENT_LIMIT
        views.ATTEMPT_EVENT_LIMIT = 2
        try:
            results = [self.client.post(url, {'event': 'copy'}).json()['logged'] for _ in range(3)]
        finally:
            views.ATTEMPT_EVENT_LIMIT = limit
        self.assertEqual(results, [True, True, False])

    def test_second_start_resumes_the_same_attempt(self):
        first, second = self._start(), self._start()
        self.assertEqual(first, second)
        with connection.cursor() as cursor:
            cursor.execute('SELECT COUNT(*) FROM exam_attempts WHERE exam_id = %s', [self.exam_id])
            self.assertEqual(cursor.fetchone()[0], 1)

    def test_practice_exam_cannot_start_after_it_ends(self):
        with connection.cursor() as cursor:
            cursor.execute("UPDATE exams SET exam_mode = 'practice', max_attempts = 0, start_at = %s, end_at = %s WHERE id = %s",
                           [timezone.now() - timedelta(days=2), timezone.now() - timedelta(days=1), self.exam_id])
        response = self.client.post(reverse('core:student_practice_start', args=[self.exam_id]), {'mode': 'tutorial', 'accept_rules': '1'}, follow=True)
        self.assertContains(response, 'زمان شرکت در این آزمون آزمایشی به پایان رسیده است.')
        with connection.cursor() as cursor:
            cursor.execute('SELECT COUNT(*) FROM exam_attempts WHERE exam_id = %s', [self.exam_id])
            self.assertEqual(cursor.fetchone()[0], 0)


class StudentDashboardTests(_ScopedOrgFixture):
    """داشبورد دانشجو فقط آزمون‌های منتشرشده‌ی اختصاص‌یافته به خود او را نشان می‌دهد و داده‌ی ساختگی ندارد."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        User = get_user_model()
        cls.student_user = User.objects.create_user(username='student_in_scope', email='s_in@example.com', password='x')
        cls.empty_user = User.objects.create_user(username='student_out_scope', email='s_out@example.com', password='x')
        TeacherStudentScopeTests._member(cls.group_in_id, cls.student_in_id)
        now = timezone.now()
        day = timedelta(days=1)
        exam = TeacherStudentScopeTests._exam
        cls.live_exam = exam('آزمون در حال برگزاری', cls.teacher_in_id, now - day, now + day, cls.group_in_id)
        cls.next_exam = exam('آزمون هفته بعد', cls.teacher_in_id, now + 7 * day, now + 8 * day, cls.group_in_id)
        cls.graded_exam = exam('آزمون تصحیح‌شده', cls.teacher_in_id, now - 9 * day, now - 8 * day, cls.group_in_id)
        TeacherStudentScopeTests._attempt(cls.graded_exam, cls.student_in_id, now - 9 * day, 'graded', 17, 20)
        with connection.cursor() as cursor:  # results are visible to students once published
            cursor.execute('UPDATE exams SET results_published_at = %s WHERE id = %s', [now - 8 * day, cls.graded_exam])
        exam('آزمون پیش‌نویس داشبورد', cls.teacher_in_id, now + day, now + 2 * day, cls.group_in_id, published=False)
        exam('آزمون گروه دیگر', cls.teacher_out_id, now - day, now + day, cls.group_out_id)
        excluded = exam('آزمون مستثنا', cls.teacher_in_id, now + day, now + 2 * day, cls.group_in_id)
        _insert('exam_assignment_exclusions', ['id', 'exam_id', 'student_profile_id'], [str(uuid.uuid4()), excluded, cls.student_in_id])

    def _dashboard(self, user):
        self.client.force_login(user)
        response = self.client.get(reverse('core:dashboard'))
        self.assertEqual(response.status_code, 200)
        return response

    def test_only_own_published_assigned_exams(self):
        response = self._dashboard(self.student_user)
        data = response.context['student_dashboard']
        self.assertEqual(data['next_exam']['title'], 'آزمون در حال برگزاری')
        self.assertEqual(data['next_exam']['state'], 'ready')
        rows = [(row['title'], row['state'], row['action']['label']) for row in data['exam_rows']]
        self.assertEqual(rows, [
            ('آزمون در حال برگزاری', 'ready', 'مشاهده جزئیات و ورود'),
            ('آزمون هفته بعد', 'upcoming', 'مشاهده جزئیات'),
            ('آزمون تصحیح‌شده', 'done', 'مشاهده کارنامه'),
        ])
        self.assertEqual(data['stats'], {'upcoming': 2, 'classes': 1, 'new_results': 1})
        self.assertEqual([(item['title'], item['score_20']) for item in data['results']], [('آزمون تصحیح‌شده', 17.0)])
        self.assertContains(response, 'سلام')
        for hidden in ('آزمون پیش‌نویس داشبورد', 'آزمون گروه دیگر', 'آزمون مستثنا', 'آزمون خارج محدوده'):
            self.assertNotContains(response, hidden)

    def test_classes_are_own_unarchived_groups(self):
        archived = str(uuid.uuid4())
        _insert('student_groups', ['id', 'teacher_id', 'course_id', 'course_name', 'academic_year', 'is_archived'],
                [archived, self.teacher_in_id, self.course_in_id, 'کلاس بایگانی‌شده', '1402', True])
        TeacherStudentScopeTests._member(archived, self.student_in_id)
        response = self._dashboard(self.student_user)
        classes = response.context['student_dashboard']['classes']
        self.assertEqual([(group['course_title'], group['teacher_name']) for group in classes], [('درس داخل محدوده', 'استاد داخل محدوده')])
        self.assertContains(response, f'class="sdb-more" href="{reverse("core:student_classes")}"')

    def test_notifications_are_own_and_links_stay_internal(self):
        from .views import create_notification as create

        create(self.student_in_id, 'اعلان من', 'متن', link='javascript:alert(1)')
        create(self.student_out_id, 'اعلان دیگری', 'متن', link='/x/')
        response = self._dashboard(self.student_user)
        self.assertEqual([note['title'] for note in response.context['student_dashboard']['notifications']], ['اعلان من'])
        self.assertNotContains(response, 'javascript:alert')
        self.assertNotContains(response, 'اعلان دیگری')

    def test_no_stand_in_data_without_exams(self):
        response = self._dashboard(self.empty_user)
        data = response.context['student_dashboard']
        self.assertIsNone(data['next_exam'])
        self.assertEqual(data['stats'], {'upcoming': 0, 'classes': 0, 'new_results': 0})
        self.assertEqual((data['exam_rows'], data['classes'], data['results'], data['notifications']), ([], [], [], []))
        self.assertContains(response, 'هنوز آزمونی به شما اختصاص داده نشده است.')
        for fake in ('روانشناسی سلامت', 'مهارت‌های ارتباطی', '۰۲:۱۵:۳۲', 'آزمون گروه دیگر'):
            self.assertNotContains(response, fake)


class StudentExamsAndClassesPagesTests(_ScopedOrgFixture):
    """صفحه‌های «آزمون‌های من» و «کلاس‌های من» فقط داده‌ی خود دانشجو را نشان می‌دهند و دکمه‌ی هر آزمون با وضعیتش جور است."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        User = get_user_model()
        cls.student_user = User.objects.create_user(username='student_in_scope', email='s_in@example.com', password='x')
        TeacherStudentScopeTests._member(cls.group_in_id, cls.student_in_id)
        TeacherStudentScopeTests._member(cls.group_out_id, cls.student_out_id)
        now = timezone.now()
        day = timedelta(days=1)
        exam = TeacherStudentScopeTests._exam
        attempt = TeacherStudentScopeTests._attempt
        cls.ready_exam = exam('آزمون آماده', cls.teacher_in_id, now - day, now + day, cls.group_in_id)
        cls.running_exam = exam('آزمون نیمه‌کاره', cls.teacher_in_id, now - day, now + 2 * day, cls.group_in_id)
        attempt(cls.running_exam, cls.student_in_id, now - timedelta(minutes=10), 'in_progress')
        cls.upcoming_exam = exam('آزمون آینده', cls.teacher_in_id, now + 3 * day, now + 4 * day, cls.group_in_id)
        cls.graded_exam = exam('آزمون نمره‌دار', cls.teacher_in_id, now - 9 * day, now - 8 * day, cls.group_in_id)
        attempt(cls.graded_exam, cls.student_in_id, now - 9 * day, 'graded', 17, 20)
        cls.pending_exam = exam('آزمون در صف تصحیح', cls.teacher_in_id, now - 6 * day, now - 5 * day, cls.group_in_id)
        cls.pending_attempt = str(uuid.uuid4())
        _insert('exam_attempts', ['id', 'exam_id', 'student_id', 'started_at', 'submitted_at', 'is_graded', 'status'],
                [cls.pending_attempt, cls.pending_exam, cls.student_in_id, now - 6 * day, now - 6 * day + timedelta(minutes=20), False, 'submitted'])
        cls.absent_exam = exam('آزمون غیبت', cls.teacher_in_id, now - 4 * day, now - 3 * day, cls.group_in_id)
        exam('آزمون پیش‌نویس صفحه', cls.teacher_in_id, now + day, now + 2 * day, cls.group_in_id, published=False)
        exam('آزمون کلاس دیگر', cls.teacher_out_id, now - day, now + day, cls.group_out_id)

    def _get(self, name, user=None, **params):
        self.client.force_login(user or self.student_user)
        response = self.client.get(reverse(name), params)
        self.assertEqual(response.status_code, 200)
        return response

    def test_exam_states_and_actions_follow_the_attempt(self):
        response = self._get('core:student_exam_schedule')
        rows = {row['title']: (row['page_label'], row['page_action']['label']) for row in response.context['page_obj']}
        self.assertEqual(rows, {
            'آزمون نیمه‌کاره': ('در حال انجام', 'ادامه آزمون'),
            'آزمون آماده': ('آماده ورود', 'جزئیات و ورود'),
            'آزمون آینده': ('برگزار نشده', 'مشاهده جزئیات'),
            'آزمون غیبت': ('غایب', 'مشاهده جزئیات'),
            'آزمون در صف تصحیح': ('در انتظار تصحیح', 'رسید تحویل'),
            'آزمون نمره‌دار': ('نتیجه منتشر شده', 'مشاهده کارنامه'),
        })
        self.assertEqual({tab['key']: tab['count'] for tab in response.context['tabs']},
                         {'all': 6, 'upcoming': 2, 'in_progress': 1, 'finished': 3})
        self.assertEqual(response.context['featured']['title'], 'آزمون نیمه‌کاره')
        self.assertContains(response, reverse('core:student_attempt_receipt', args=[self.pending_attempt]))
        for hidden in ('آزمون پیش‌نویس صفحه', 'آزمون کلاس دیگر', 'ارزیابی اولیه وضعیت سالمند', 'مرداد ۱۴۰۵'):
            self.assertNotContains(response, hidden)

    def test_results_icon_only_links_submitted_attempts(self):
        response = self._get('core:student_exam_schedule')
        linked = {row['title'] for row in response.context['page_obj'] if row['result_url']}
        self.assertEqual(linked, {'آزمون در صف تصحیح', 'آزمون نمره‌دار'})
        pending_url = reverse('core:student_result_detail', args=[self.pending_attempt])
        self.assertContains(response, f'href="{pending_url}"')
        self.assertEqual(self.client.get(pending_url).status_code, 200)
        for removed in ('/student/results/', '/student/objections/', '/student/educational-questions/'):
            self.assertEqual(self.client.get(removed).status_code, 404)

    def test_tab_filter_and_pagination(self):
        finished = self._get('core:student_exam_schedule', tab='finished').context
        self.assertEqual({row['page_state'] for row in finished['page_obj']}, {'absent', 'pending', 'graded'})
        searched = self._get('core:student_exam_schedule', q='غیبت').context
        self.assertEqual([row['title'] for row in searched['page_obj']], ['آزمون غیبت'])
        from unittest import mock as page_mock

        from . import student_dashboard
        with page_mock.patch.object(student_dashboard, 'EXAM_PAGE_SIZE', 4):
            second = self._get('core:student_exam_schedule', page=2).context['page_obj']
        self.assertEqual((second.number, len(second.object_list), second.paginator.count), (2, 2, 6))

    def test_other_students_class_filter_is_ignored(self):
        context = self._get('core:student_exam_schedule', **{'class': self.group_out_id}).context
        self.assertIsNone(context['selected_class'])
        self.assertNotIn('آزمون کلاس دیگر', [row['title'] for row in context['page_obj']])
        own = self._get('core:student_exam_schedule', **{'class': self.group_in_id}).context
        self.assertEqual(own['selected_class']['id'], self.group_in_id)
        self.assertEqual(own['total'], 6)

    def test_classes_are_own_with_exam_count_and_next_exam(self):
        archived = str(uuid.uuid4())
        _insert('student_groups', ['id', 'teacher_id', 'course_id', 'course_name', 'academic_year', 'is_archived'],
                [archived, self.teacher_in_id, self.course_in_id, 'کلاس قدیمی', '1402', True])
        TeacherStudentScopeTests._member(archived, self.student_in_id)
        response = self._get('core:student_classes')
        cards = list(response.context['page_obj'])
        self.assertEqual([(card['course_title'], card['teacher_name'], card['exam_count']) for card in cards],
                         [('درس داخل محدوده', 'استاد داخل محدوده', 6)])
        # both open exams start at the same moment, so either one is the next exam
        self.assertIn(cards[0]['next_exam']['title'], {'آزمون آماده', 'آزمون نیمه‌کاره'})
        self.assertEqual(response.context['counts'], {'current': 1, 'past': 1})
        self.assertNotContains(response, 'درس خارج محدوده')
        past = self._get('core:student_classes', tab='past', view='list').context
        self.assertEqual([card['id'] for card in past['page_obj']], [archived])

    def test_student_without_exams_or_classes_sees_empty_states(self):
        loner_id = self._make_profile('student_loner', 'دانشجوی بی‌کلاس')
        _insert('student_profiles', ['user_id', 'org_unit_id'], [loner_id, self.ou_scoped])
        _insert('user_roles', ['id', 'user_id', 'role'], [str(uuid.uuid4()), loner_id, 'student'])
        loner = get_user_model().objects.create_user(username='student_loner', email='student_loner@example.com', password='x')
        exams = self._get('core:student_exam_schedule', user=loner)
        self.assertIsNone(exams.context['featured'])
        self.assertEqual(exams.context['total'], 0)
        self.assertContains(exams, 'هنوز آزمونی به شما اختصاص داده نشده است.')
        classes = self._get('core:student_classes', user=loner)
        self.assertEqual(classes.context['counts'], {'current': 0, 'past': 0})
        self.assertContains(classes, 'هنوز در کلاسی عضو نشده‌اید.')

    def test_top_menu_links_both_pages(self):
        response = self._get('core:student_classes')
        self.assertContains(response, 'آزمون‌های من')
        self.assertContains(response, f'href="{reverse("core:student_classes")}"')


class StudentSettingsTests(_ScopedOrgFixture):
    """صفحه‌ی «تنظیمات» دانشجو: فقط اطلاعات خود دانشجو را نشان می‌دهد و ذخیره می‌کند؛ اطلاعات تحصیلی از این صفحه تغییر نمی‌کند."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        User = get_user_model()
        cls.student_user = User.objects.create_user(username='student_in_scope', email='s_in@example.com', password='old-pass-123')
        cls.teacher_user = User.objects.create_user(username='teacher_in_scope', email='t_in@example.com', password='x')
        with connection.cursor() as cursor:
            cursor.execute(
                'UPDATE student_profiles SET student_number = %s, field_of_study = %s, degree = %s WHERE user_id = %s',
                ['14051234', 'پرستاری', 'کارشناسی', cls.student_in_id],
            )
            cursor.execute('UPDATE profiles SET phone = %s WHERE id = %s', ['09171111234', cls.student_in_id])

    def _profile(self, student_id=None):
        with connection.cursor() as cursor:
            cursor.execute('SELECT first_name, last_name, full_name, phone FROM profiles WHERE id = %s', [student_id or self.student_in_id])
            return cursor.fetchone()

    def _post(self, data, tab='personal'):
        self.client.force_login(self.student_user)
        return self.client.post(reverse('core:student_settings'), {'settings_tab': tab, **data})

    def test_menu_links_the_settings_page(self):
        self.client.force_login(self.student_user)
        response = self.client.get(reverse('core:student_classes'))
        self.assertContains(response, f'href="{reverse("core:student_settings")}"')

    def test_personal_tab_shows_own_details_with_academic_fields_read_only(self):
        self.client.force_login(self.student_user)
        response = self.client.get(reverse('core:student_settings'))
        self.assertEqual(response.status_code, 200)
        personal = response.context['personal']
        self.assertEqual((personal['student_number'], personal['field_of_study'], personal['phone_masked']),
                         ('14051234', 'پرستاری', '0917***1234'))
        self.assertEqual(personal['faculty'], 'واحد تحت مدیریت')
        for locked in ('student_number', 'field_of_study', 'degree', 'email'):
            self.assertNotContains(response, f'name="{locked}"')
        self.assertNotContains(response, 'دانشجوی خارج محدوده')

    def test_saving_names_and_phone_ignores_academic_fields(self):
        response = self._post({'first_name': 'علی', 'last_name': 'محمدی', 'phone': '۰۹۱۲۳۴۵۶۷۸۹', 'field_of_study': 'پزشکی'})
        self.assertRedirects(response, f'{reverse("core:student_settings")}?tab=personal&saved=1', fetch_redirect_response=False)
        self.assertEqual(self._profile(), ('علی', 'محمدی', 'علی محمدی', '09123456789'))
        with connection.cursor() as cursor:
            cursor.execute('SELECT field_of_study FROM student_profiles WHERE user_id = %s', [self.student_in_id])
            self.assertEqual(cursor.fetchone()[0], 'پرستاری')
        self.assertEqual(self._profile(self.student_out_id)[2], 'دانشجوی خارج محدوده')

    def test_phone_is_kept_when_not_posted_and_invalid_input_saves_nothing(self):
        self._post({'first_name': 'علی', 'last_name': 'محمدی'})
        self.assertEqual(self._profile()[3], '09171111234')
        response = self._post({'first_name': 'رضا', 'last_name': '', 'phone': '12345'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['errors'], ['نام و نام خانوادگی الزامی است.', 'شماره همراه باید ۱۱ رقم و با ۰۹ شروع شود.'])
        self.assertEqual(self._profile()[:2], ('علی', 'محمدی'))
        self.assertContains(response, 'value="رضا"')

    def test_old_profile_page_redirects_and_other_roles_are_refused(self):
        self.client.force_login(self.student_user)
        response = self.client.get(reverse('core:profile'), {'section': 'security'})
        self.assertRedirects(response, f'{reverse("core:student_settings")}?tab=security', fetch_redirect_response=False)
        self.client.force_login(self.teacher_user)
        self.assertEqual(self.client.get(reverse('core:student_settings')).status_code, 403)

    def test_class_notifications_switched_off_arrive_already_read(self):
        from .views import create_notification

        response = self._post({}, tab='workspace')  # every switch off
        self.assertRedirects(response, f'{reverse("core:student_settings")}?tab=workspace&saved=1', fetch_redirect_response=False)
        create_notification(self.student_in_id, 'پیام استاد', 'متن', notification_type='teacher_message')
        create_notification(self.student_in_id, 'حساب', 'متن', notification_type='account')
        create_notification(self.student_out_id, 'پیام استاد', 'متن', notification_type='teacher_message')
        with connection.cursor() as cursor:
            cursor.execute('SELECT user_id, type, is_read FROM notifications WHERE user_id IN (%s, %s)', [self.student_in_id, self.student_out_id])
            rows = {(str(user_id), kind): bool(is_read) for user_id, kind, is_read in cursor.fetchall()}
        self.assertEqual(rows, {
            (self.student_in_id, 'teacher_message'): True,  # kept, but silent
            (self.student_in_id, 'account'): False,  # kinds without a switch are untouched
            (self.student_out_id, 'teacher_message'): False,  # another student's choice is their own
        })
        self._post({'inapp_class_message': 'on', 'inapp_new_exam': 'on'}, tab='workspace')
        rows = {row['key']: (row['enabled'], row['on']) for row in self.client.get(reverse('core:student_settings'), {'tab': 'workspace'}).context['notification_rows']}
        self.assertEqual(rows['class_message'], (True, True))
        self.assertEqual(rows['new_exam'], (True, True))  # sent when an exam is published (announce_exam_published)

    def test_workspace_options_without_an_effect_are_marked_in_development(self):
        self.client.force_login(self.student_user)
        response = self.client.get(reverse('core:student_settings'), {'tab': 'workspace'})
        self.assertContains(response, 'در حال توسعه')
        self.assertContains(response, 'name="inapp_class_message"')
        for fake in ('name="theme"', 'name="language"', 'name="compact_tables"', 'name="email_'):
            self.assertNotContains(response, fake)

    def _security(self, action, **data):
        return self._post({'security_action': action, **data}, tab='security')

    def test_password_change_needs_the_current_password_and_keeps_this_session(self):
        response = self._security('password_change', old_password='wrong', new_password1='N3w-pass-Strong!', new_password2='N3w-pass-Strong!')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['errors'])
        self.student_user.refresh_from_db()
        self.assertTrue(self.student_user.check_password('old-pass-123'))
        response = self._security('password_change', old_password='old-pass-123', new_password1='N3w-pass-Strong!', new_password2='N3w-pass-Strong!')
        self.assertRedirects(response, f'{reverse("core:student_settings")}?tab=security&done=password_change', fetch_redirect_response=False)
        self.student_user.refresh_from_db()
        self.assertTrue(self.student_user.check_password('N3w-pass-Strong!'))
        self.assertEqual(self.client.get(reverse('core:student_settings'), {'tab': 'security'}).status_code, 200)  # still signed in

    def test_sessions_are_own_and_unknown_actions_are_refused(self):
        self.client.force_login(self.student_user)
        response = self.client.get(reverse('core:student_settings'), {'tab': 'security'})
        self.assertEqual(response.status_code, 200)
        self.assertIn('two_factor', response.context)
        for action in ('deletion_request', 'end_session:not-a-key', 'bogus'):
            response = self._security(action, deletion_password='old-pass-123', deletion_confirm='on')
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.context['errors'])
        with connection.cursor() as cursor:
            cursor.execute('SELECT COUNT(*) FROM account_deletion_requests WHERE profile_id = %s', [self.student_in_id])
            self.assertEqual(cursor.fetchone()[0], 0)

    def test_hidden_photo_is_not_sent_to_teacher_pages(self):
        TeacherStudentScopeTests._member(self.group_in_id, self.student_in_id)
        with connection.cursor() as cursor:
            cursor.execute('UPDATE profiles SET avatar_url = %s WHERE id = %s', ['/media/avatars/me.png', self.student_in_id])

        def teacher_sees():
            self.client.force_login(self.teacher_user)
            listed = {row['id']: row['avatar_url'] for row in self.client.get(reverse('core:teacher_students')).context['sl']['rows']}
            profile = self.client.get(reverse('core:teacher_student_profile', args=[self.student_in_id])).context['profile']['student']
            faces = [face['avatar_url'] for row in self.client.get(reverse('core:teacher_courses')).context['class_list']['rows'] for face in row['faces']]
            return listed[self.student_in_id], profile['avatar_url'], faces

        self.assertEqual(teacher_sees(), ('/media/avatars/me.png', '/media/avatars/me.png', ['/media/avatars/me.png']))
        response = self._post({}, tab='security')  # privacy switch off
        self.assertRedirects(response, f'{reverse("core:student_settings")}?tab=security&saved=1', fetch_redirect_response=False)
        self.assertEqual(teacher_sees(), ('', '', ['']))
        self._post({'show_avatar_to_teacher': 'on'}, tab='security')
        self.assertEqual(teacher_sees()[0], '/media/avatars/me.png')


class LegacyQuestionFormatMigrationTests(_ScopedOrgFixture):
    """تبدیل سؤال‌های ذخیره‌شده با فرم قدیمی به قالبی که نمره‌دهی می‌خواند؛ برگشت‌پذیر و بدون دست‌زدن به سؤال‌های جدید."""

    LEGACY = {'partial_credit': True, 'negative_marking': True, 'shuffle_options': True, 'min_correct': '', 'max_correct': ''}

    def _question(self, kind, text, points, accepted, settings=None, negative='-0.5'):
        question_id = str(uuid.uuid4())
        _insert('questions', ['id', 'teacher_id', 'text', 'type', 'default_points', 'negative_points', 'accepted_answers',
                              'correct_answer', 'scoring_settings'], [
            question_id, self.teacher_in_id, text, kind, points, negative, json.dumps(accepted, ensure_ascii=False),
            json.dumps(''), json.dumps(settings or self.LEGACY),
        ])
        return question_id

    def _row(self, question_id):
        from apps.core.views import erd_row
        return erd_row('SELECT * FROM questions WHERE id = %s', [question_id])

    def _run(self, name):
        import importlib
        from types import SimpleNamespace
        module = importlib.import_module('apps.core.migrations.0048_legacy_question_formats')
        getattr(module, name)(None, SimpleNamespace(connection=connection))

    def test_legacy_rows_are_graded_as_the_editor_shows_them_and_can_be_restored(self):
        from apps.core.views import _grade_question
        short = self._question('short_answer', 'نام دارو؟', 2, [{'answer': 'آتروپین', 'points': '۲'}, {'answer': 'atropine', 'points': '۱'}])
        blank = self._question('fill_blank', 'استخوان [1] است.', 3, [{'answer': 'ران', 'points': '۳'}, {'answer': 'فمور', 'points': '۳'}])
        multi_blank = self._question('fill_blank', '[1] و [2] و [3]', 3, [{'answer': 'a', 'points': '1'}, {'answer': 'b', 'points': '1'}])
        modern_settings = {'scoring_mode': 'all_or_nothing', 'negative_marking': False, 'negative_value': 0.25}
        modern = self._question('short_answer', 'جدید', 2, [{'answer': 'x', 'points': 100, 'match_mode': 'exact'}], modern_settings)
        before = {question_id: self._row(question_id) for question_id in (short, blank, multi_blank, modern)}

        self._run('convert_legacy_questions')
        self.assertEqual(_grade_question(self._row(short), 'آتروپین', 2.0), (2.0, False, True))
        self.assertEqual(_grade_question(self._row(short), 'atropine', 2.0)[:2], (1.0, False))  # raw 1 of 2 -> 50% credit
        self.assertEqual(_grade_question(self._row(blank), ['فمور'], 3.0), (3.0, False, True))  # rows were alternatives
        self.assertEqual(_grade_question(self._row(blank), ['درشت‌نی'], 3.0), (0.0, False, False))  # partial mode: no penalty
        self.assertEqual(json.loads(self._row(multi_blank)['accepted_answers']), [{'answer': 'a', 'points': '1'}, {'answer': 'b', 'points': '1'}])
        self.assertEqual(self._row(modern), before[modern])
        self._run('convert_legacy_questions')  # idempotent
        self.assertEqual(json.loads(self._row(short)['scoring_settings'])['scoring_mode'], 'partial')

        self._run('restore_legacy_questions')
        for question_id, row in before.items():
            self.assertEqual(self._row(question_id), row)


class StudentResultRankAndTopicsTests(_ScopedOrgFixture):
    """رتبه و عملکرد موضوعی صفحه‌ی نتیجه از داده‌ی واقعی آزمون؛ قبلاً رتبه «۸ از ۴۵» و درصد موضوع‌ها از روی درصد کل ساخته می‌شد."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        User = get_user_model()
        cls.student_user = User.objects.create_user(username='student_in_scope', email='s_in@example.com', password='x')
        cls.heart, cls.lung = str(uuid.uuid4()), str(uuid.uuid4())
        for order, (question_id, subject, points) in enumerate(((cls.heart, 'قلب و عروق', 4), (cls.lung, 'تنفس', 6)), start=1):
            _insert('questions', ['id', 'teacher_id', 'text', 'type', 'default_points', 'subject'],
                    [question_id, cls.teacher_in_id, f'سؤال {subject}', 'single', points, subject])
            _insert('exam_questions', ['id', 'exam_id', 'question_id', 'points', 'order_index'],
                    [str(uuid.uuid4()), cls.exam_in_id, question_id, points, order])
        cls.attempt_id = cls._graded(cls.student_in_id, 4, {cls.heart: 4, cls.lung: 0})
        cls._graded(cls.student_out_id, 9, {cls.heart: 4, cls.lung: 5})
        with connection.cursor() as cursor:
            cursor.execute("UPDATE exams SET score_display_mode = 'immediate' WHERE id = %s", [cls.exam_in_id])

    @classmethod
    def _graded(cls, student_id, score, awarded):
        attempt_id = str(uuid.uuid4())
        _insert('exam_attempts', ['id', 'exam_id', 'student_id', 'started_at', 'submitted_at', 'score', 'max_score', 'is_graded', 'status'],
                [attempt_id, cls.exam_in_id, student_id, timezone.now(), timezone.now(), score, 10, True, 'graded'])
        for question_id, points in awarded.items():
            _insert('attempt_answers', ['id', 'attempt_id', 'question_id', 'answer', 'is_correct', 'points_awarded', 'needs_manual_grading'],
                    [str(uuid.uuid4()), attempt_id, question_id, json.dumps({'value': '1'}), points > 0, points, False])
        return attempt_id

    def test_rank_and_topics_come_from_the_exam(self):
        self.client.force_login(self.student_user)
        response = self.client.get(reverse('core:student_result_detail', args=[self.attempt_id]))
        self.assertEqual((response.context['rank'], response.context['rank_total']), (2, 2))
        self.assertEqual(response.context['topics'], [{'title': 'تنفس', 'percent': 0}, {'title': 'قلب و عروق', 'percent': 100}])
        page = response.content.decode()
        self.assertIn('۲ از ۲', page)
        for leftover in ('از ۴۵', 'ارزیابی و مراقبت‌های پایه', 'سلامت جسمی و پیشگیری'):
            self.assertNotIn(leftover, page)


class SingleChoiceCorrectFlagsMigrationTests(_ScopedOrgFixture):
    """هم‌راستا کردن گزینه‌ی «صحیح» سؤال تک‌گزینه‌ای با correct_answer که نمره‌دهی همیشه بر اساس آن بوده است."""

    def _run(self, name):
        import importlib
        from types import SimpleNamespace
        module = importlib.import_module('apps.core.migrations.0049_single_choice_correct_flags')
        getattr(module, name)(None, SimpleNamespace(connection=connection))

    def _flags(self, question_id):
        with connection.cursor() as cursor:
            cursor.execute('SELECT options FROM questions WHERE id = %s', [question_id])
            return [option['id'] for option in json.loads(cursor.fetchone()[0]) if option['is_correct']]

    def test_flags_follow_correct_answer_and_can_be_restored(self):
        options = [{'id': str(index), 'text': f'گزینه {index}', 'is_correct': index in (2, 4)} for index in range(1, 5)]
        broken, fine = str(uuid.uuid4()), str(uuid.uuid4())
        for question_id, flags in ((broken, options), (fine, [dict(option, is_correct=option['id'] == '4') for option in options])):
            _insert('questions', ['id', 'teacher_id', 'text', 'type', 'options', 'correct_answer', 'scoring_settings'],
                    [question_id, self.teacher_in_id, 'سؤال', 'single', json.dumps(flags), json.dumps('4'), json.dumps({'scoring_mode': 'partial'})])
        self._run('align_correct_flags')
        self.assertEqual((self._flags(broken), self._flags(fine)), (['4'], ['4']))
        self._run('restore_correct_flags')
        self.assertEqual(self._flags(broken), ['2', '4'])


class StudentResultShowsStoredDataTests(_ScopedOrgFixture):
    """صفحه‌ی نتیجه و صفحه‌ی آزمون فقط داده‌ی ذخیره‌شده را نشان می‌دهند؛ قبلاً متن لاتین با سؤال نمونه، گزینه‌ها با گزینه‌ی
    ساختگی و سؤال بی‌پاسخ با «پاسخ صحیح» ساختگی جایگزین می‌شد."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        User = get_user_model()
        cls.student_user = User.objects.create_user(username='student_in_scope', email='s_in@example.com', password='x')
        options = [{'id': '1', 'text': 'Atropine'}, {'id': '2', 'text': 'Adenosine'}]
        cls.choice, cls.skipped = str(uuid.uuid4()), str(uuid.uuid4())
        for order, (question_id, text) in enumerate(((cls.choice, 'CODX first drug for bradycardia?'), (cls.skipped, 'سؤال بی‌پاسخ')), start=1):
            _insert('questions', ['id', 'teacher_id', 'text', 'type', 'default_points', 'options', 'correct_answer'],
                    [question_id, cls.teacher_in_id, text, 'single', 2, json.dumps(options), json.dumps('1')])
            _insert('exam_questions', ['id', 'exam_id', 'question_id', 'points', 'order_index'], [str(uuid.uuid4()), cls.exam_in_id, question_id, 2, order])
        cls.attempt_id = str(uuid.uuid4())
        _insert('exam_attempts', ['id', 'exam_id', 'student_id', 'started_at', 'submitted_at', 'score', 'max_score', 'is_graded', 'status'],
                [cls.attempt_id, cls.exam_in_id, cls.student_in_id, timezone.now(), timezone.now(), 0, 4, True, 'graded'])
        _insert('attempt_answers', ['id', 'attempt_id', 'question_id', 'answer', 'is_correct', 'points_awarded', 'needs_manual_grading'],
                [str(uuid.uuid4()), cls.attempt_id, cls.choice, json.dumps({'value': '2'}), False, 0, False])
        with connection.cursor() as cursor:
            cursor.execute("UPDATE exams SET score_display_mode = 'immediate' WHERE id = %s", [cls.exam_in_id])

    def test_result_page_shows_the_stored_questions_and_answers(self):
        self.client.force_login(self.student_user)
        url = reverse('core:student_result_detail', args=[self.attempt_id])
        response = self.client.get(url)
        items = response.context['question_items']
        self.assertEqual([item['text'] for item in items], ['CODX first drug for bradycardia?', 'سؤال بی‌پاسخ'])
        self.assertEqual([item['tone'] for item in items], ['bad', 'empty'])
        self.assertEqual([(o['label'], o['chosen'], o['correct']) for o in items[0]['options']],
                         [('Atropine', False, True), ('Adenosine', True, False)])
        self.assertEqual(response.context['summary'], {'total': 2, 'correct': 0, 'partial': 0, 'wrong': 1, 'unanswered': 1})
        self.assertContains(response, 'href="?q=2"')
        second = self.client.get(url, {'q': 2})
        self.assertEqual(second.context['current_question']['text'], 'سؤال بی‌پاسخ')
        self.assertNotContains(second, 'پاسخ شما</b>')
        self.assertNotIn('سالمند', response.content.decode())
        self.assertContains(response, 'data-print-report')
        self.assertNotContains(response, 'href="#"')


class ExamResultReleaseTests(_ScopedOrgFixture):
    """اعلام نتیجه طبق «نمایش نمره / پاسخ صحیح / توضیح پاسخ» آزمون؛ «پس از انتشار نتایج» تا انتشار استاد یا مدیر پنهان است."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        User = get_user_model()
        cls.student_user = User.objects.create_user(username='student_in_scope', email='s_in@example.com', password='x')
        cls.teacher_user = User.objects.create_user(username='teacher_in_scope', email='t_in@example.com', password='x')
        cls.other_teacher_user = User.objects.create_user(username='teacher_out_scope', email='t_out@example.com', password='x')
        cls.question_id, cls.attempt_id = str(uuid.uuid4()), str(uuid.uuid4())
        _insert('questions', ['id', 'teacher_id', 'text', 'type', 'default_points', 'options', 'correct_answer', 'explanation'],
                [cls.question_id, cls.teacher_in_id, 'داروی انتخابی؟', 'single', 2,
                 json.dumps([{'id': '1', 'text': 'آتروپین'}, {'id': '2', 'text': 'آدنوزین'}]), json.dumps('1'), 'توضیح کلید'])
        _insert('exam_questions', ['id', 'exam_id', 'question_id', 'points', 'order_index'], [str(uuid.uuid4()), cls.exam_in_id, cls.question_id, 2, 1])
        _insert('exam_attempts', ['id', 'exam_id', 'student_id', 'started_at', 'submitted_at', 'score', 'max_score', 'is_graded', 'status'],
                [cls.attempt_id, cls.exam_in_id, cls.student_in_id, timezone.now(), timezone.now(), 2, 2, True, 'graded'])
        _insert('attempt_answers', ['id', 'attempt_id', 'question_id', 'answer', 'is_correct', 'points_awarded', 'needs_manual_grading'],
                [str(uuid.uuid4()), cls.attempt_id, cls.question_id, json.dumps({'value': '1'}), True, 2, False])

    def _modes(self, score, correct='after_publish'):
        with connection.cursor() as cursor:
            cursor.execute('UPDATE exams SET score_display_mode = %s, correct_answer_display_mode = %s, explanation_display_mode = %s WHERE id = %s',
                           [score, correct, correct, self.exam_in_id])

    def _student_view(self):
        self.client.force_login(self.student_user)
        return self.client.get(reverse('core:student_result_detail', args=[self.attempt_id]))

    def test_result_waits_for_publication_and_teacher_publishes_it(self):
        self._modes('after_publish')
        waiting = self._student_view()
        self.assertTrue(waiting.context['is_pending'])
        self.assertContains(waiting, 'در انتظار انتشار نتیجه')
        self.assertIsNone(waiting.context['result']['score'])

        url = reverse('core:teacher_publish_result', args=[self.exam_in_id])
        self.client.force_login(self.other_teacher_user)
        self.assertEqual(self.client.post(url, {'action': 'publish'}).status_code, 404)
        self.client.force_login(self.teacher_user)
        self.assertContains(self.client.get(reverse('core:teacher_results'), {'exam': self.exam_in_id}), 'انتشار نتایج و ارسال اعلان')
        self.client.post(url, {'action': 'publish'})
        with connection.cursor() as cursor:
            cursor.execute('SELECT type, link FROM notifications WHERE user_id = %s', [self.student_in_id])
            self.assertEqual(cursor.fetchall(), [('exam_results', reverse('core:student_result_detail', args=[self.attempt_id]))])

        shown = self._student_view()
        self.assertFalse(shown.context['is_pending'])
        self.assertTrue(shown.context['show_correct'])
        self.assertContains(shown, 'توضیح کلید')

        self.client.force_login(self.teacher_user)
        self.client.post(url, {'action': 'unpublish'})
        self.assertTrue(self._student_view().context['is_pending'])

    def test_immediate_score_keeps_the_answer_key_for_its_own_setting(self):
        self._modes('immediate', correct='manual')
        page = self._student_view()
        self.assertFalse(page.context['is_pending'])
        self.assertFalse(page.context['show_correct'])
        self.assertNotContains(page, 'پاسخ صحیح</b>')
        self.assertNotContains(page, 'توضیح کلید')

    def test_manager_sets_modes_and_publishes_results(self):
        self.client.force_login(self.manager_user)
        url = reverse('core:super_admin_exam_edit', args=[self.exam_in_id])
        self.client.post(url, {'edit_step': '5', 'score_display_mode': 'manual', 'correct_answer_display_mode': 'immediate',
                               'explanation_display_mode': 'bogus'})
        from apps.core.views import erd_row
        exam = erd_row('SELECT score_display_mode, correct_answer_display_mode, explanation_display_mode, results_published_at FROM exams WHERE id = %s', [self.exam_in_id])
        self.assertEqual((exam['score_display_mode'], exam['correct_answer_display_mode'], exam['explanation_display_mode']),
                         ('manual', 'immediate', 'after_publish'))
        self.assertTrue(self._student_view().context['is_pending'])
        self.client.force_login(self.manager_user)
        self.client.post(url, {'edit_step': '5', 'publish_action': 'publish_results'})
        self.assertFalse(self._student_view().context['is_pending'])


class TeacherQuestionBankPaginationTests(_ScopedOrgFixture):
    """بانک سؤال استاد صفحه‌بندی واقعی دارد و فقط سؤال‌های خود او را نشان می‌دهد؛ قبلاً دکمه‌های صفحه بی‌اثر بودند،
    فهرست بی‌صدا به ۲۴۰ سؤال بریده می‌شد و بانک خالی پنج سؤال نمونه نشان می‌داد."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        User = get_user_model()
        cls.teacher_user = User.objects.create_user(username='teacher_in_scope', email='t_in@example.com', password='x')
        cls.other_teacher_user = User.objects.create_user(username='teacher_out_scope', email='t_out@example.com', password='x')
        for number in range(25):
            _insert('questions', ['id', 'teacher_id', 'text', 'type', 'is_published'],
                    [str(uuid.uuid4()), cls.teacher_in_id, f'سؤال شماره {number:02d}', 'single', False])

    def test_pages_keep_filters_and_show_only_stored_questions(self):
        self.client.force_login(self.teacher_user)
        url = reverse('core:teacher_questions')
        first = self.client.get(url, {'type': 'single'})
        self.assertEqual(len(first.context['questions']), 20)
        self.assertContains(first, '<input type="hidden" name="type" value="single">')
        second = self.client.get(url, {'type': 'single', 'page': 2})
        self.assertEqual([q['text'] for q in second.context['questions']], [f'سؤال شماره {n}' for n in range(20, 25)])
        self.assertEqual({q['status_key'] for q in second.context['questions']}, {'draft'})
        self.assertNotContains(second, '۱۴۰۴/۰۳/۲۰')

        self.client.force_login(self.other_teacher_user)
        other = self.client.get(url)
        self.assertFalse(any(q['text'].startswith('سؤال شماره') for q in other.context['questions']))
        self.assertNotContains(other, 'سکته قلبی')
        with connection.cursor() as cursor:
            cursor.execute('DELETE FROM questions WHERE teacher_id = %s', [self.teacher_out_id])
        self.assertEqual(self.client.get(url).context['questions'], [])

    def test_filters_run_in_the_database_and_other_pages_skip_the_bank(self):
        _insert('questions', ['id', 'teacher_id', 'text', 'type', 'is_published', 'difficulty'],
                [str(uuid.uuid4()), self.teacher_in_id, 'دوز ۵۰% آتروپین', 'multi', True, 'hard'])
        self.client.force_login(self.teacher_user)
        url = reverse('core:teacher_questions')
        found = self.client.get(url, {'q': '۵۰%'}).context['questions']
        self.assertEqual([q['text'] for q in found], ['دوز ۵۰% آتروپین'])
        self.assertEqual(self.client.get(url, {'q': '_'}).context['question_page'].paginator.count, 0)  # "_" is literal
        active = self.client.get(url, {'status': 'active', 'difficulty': 'hard', 'type': 'multi'}).context
        self.assertEqual([q['status_label'] for q in active['questions']], ['فعال'])
        self.assertEqual(active['question_stats'], {'total': 28, 'active': 1, 'draft': 27, 'needs_review': 0, 'archived': 0, 'banks': 2})  # a course + «بدون درس»
        self.assertNotIn('question_page', self.client.get(reverse('core:teacher_panel')).context)


class ScenarioBuildersInDevelopmentTests(_ScopedOrgFixture):
    """سازنده‌ی KFP و سناریوی بیمار ماکت بودند و هر چه استاد وارد می‌کرد، یک سناریوی ثابت ذخیره می‌کردند؛ تا ساخت واقعی بسته‌اند."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.teacher_user = get_user_model().objects.create_user(username='teacher_in_scope', email='t_in@example.com', password='x')

    def _count(self):
        with connection.cursor() as cursor:
            cursor.execute('SELECT COUNT(*) FROM questions WHERE teacher_id = %s', [self.teacher_in_id])
            return cursor.fetchone()[0]

    def test_kfp_and_case_cannot_be_opened_or_saved(self):
        self.client.force_login(self.teacher_user)
        url = reverse('core:teacher_question_create')
        before = self._count()
        for kind in ('kfp', 'case'):
            self.assertRedirects(self.client.get(url, {'type': kind}), reverse('core:teacher_question_type'))
            response = self.client.post(url, {'type': kind, 'structure': kind, 'text': 'سناریو', 'is_published': '1'}, follow=True)
            self.assertContains(response, 'در حال توسعه')
        self.assertEqual(self._count(), before)
        self.assertNotContains(self.client.get(reverse('core:teacher_question_type')), '?type=kfp')


class ManagerExamReviewStepTests(_ScopedOrgFixture):
    """مرحله‌ی «بازبینی و انتشار» مدیر: چک‌لیست از داده، یادداشت و اطلاع‌رسانی واقعی؛ قبلاً چک‌لیست همیشه ✓، یادداشت از پیش پر
    و ذخیره‌نشده، تیک اطلاع‌رسانی بی‌اثر و تعداد شرکت‌کنندگان در نبود داده ۱۲۸ بود."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        _insert('exam_assignments', ['id', 'exam_id', 'student_profile_id'], [str(uuid.uuid4()), cls.exam_in_id, cls.student_in_id])

    def test_review_reflects_the_exam_and_republish_notifies_the_audience(self):
        self.client.force_login(self.manager_user)
        url = reverse('core:super_admin_exam_edit', args=[self.exam_in_id])
        page = self.client.get(url, {'step': '5'})
        checks = dict(page.context['review_checks'])
        self.assertTrue(checks['شرکت‌کننده دارد'])
        self.assertFalse(checks['دست‌کم یک سؤال با بارم مثبت دارد'])
        self.assertEqual(page.context['stats']['participant_count'], 1)
        self.assertNotContains(page, 'تغییر زمان پایان به ۱۰:۳۰')

        self.client.post(url, {'edit_step': '5', 'publish_action': 'republish', 'change_note': 'زمان پایان تمدید شد.', 'notify_participants': 'on'})
        with connection.cursor() as cursor:
            cursor.execute('SELECT user_id, message FROM notifications')
            self.assertEqual([(str(user_id), message) for user_id, message in cursor.fetchall()], [(self.student_in_id, 'آزمون «آزمون داخل محدوده» به‌روزرسانی شد. زمان پایان تمدید شد.')])
        self.client.post(url, {'edit_step': '5', 'publish_action': 'republish'})
        with connection.cursor() as cursor:
            cursor.execute('SELECT COUNT(*) FROM notifications')
            self.assertEqual(cursor.fetchone()[0], 1)  # unticked: nobody is notified


class TeacherQuestionArchiveTests(_ScopedOrgFixture):
    """آرشیو واقعی سؤال: از فهرست و انتخاب آزمون جدید خارج می‌شود، تاریخ واقعی دارد و بازیابی می‌شود."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        User = get_user_model()
        cls.teacher_user = User.objects.create_user(username='teacher_in_scope', email='t_in@example.com', password='x')
        cls.other_teacher_user = User.objects.create_user(username='teacher_out_scope', email='t_out@example.com', password='x')
        cls.question_id = str(uuid.uuid4())
        _insert('questions', ['id', 'teacher_id', 'course_id', 'text', 'type', 'is_published', 'default_points'],
                [cls.question_id, cls.teacher_in_id, cls.course_in_id, 'سؤال قابل آرشیو', 'single', True, 1])

    def _archived_at(self):
        from apps.core.views import erd_row
        return erd_row('SELECT archived_at FROM questions WHERE id = %s', [self.question_id])['archived_at']

    def test_archive_hides_the_question_and_restore_brings_it_back(self):
        from apps.core.views import _exam_wizard_resources, _exam_wizard_scope
        url = reverse('core:teacher_question_archive', args=[self.question_id])
        self.client.force_login(self.other_teacher_user)
        self.assertEqual(self.client.post(url, {'action': 'archive'}).status_code, 404)
        self.assertIsNone(self._archived_at())

        self.client.force_login(self.teacher_user)
        self.client.post(url, {'action': 'archive'})
        self.assertIsNotNone(self._archived_at())
        bank = reverse('core:teacher_questions')
        self.assertNotIn(self.question_id, [q['id'] for q in self.client.get(bank).context['questions']])
        archive = self.client.get(bank, {'view': 'archive'})
        self.assertEqual([q['id'] for q in archive.context['questions']], [self.question_id])
        self.assertEqual(archive.context['question_stats']['archived'], 1)
        self.assertNotContains(archive, 'تکراری')

        request = self.client.get(bank).wsgi_request
        request.erd_profile_id, request.erd_role = self.teacher_in_id, 'teacher'
        ids = lambda exam_id=None: {str(q['id']) for q in _exam_wizard_resources(request, _exam_wizard_scope(request), exam_id)['questions']}
        self.assertNotIn(self.question_id, ids())
        _insert('exam_questions', ['id', 'exam_id', 'question_id', 'points', 'order_index'], [str(uuid.uuid4()), self.exam_in_id, self.question_id, 1, 1])
        self.assertIn(self.question_id, ids(self.exam_in_id))  # an exam that already uses it keeps it

        self.client.post(url, {'action': 'restore'})
        self.assertIsNone(self._archived_at())
        self.assertIn(self.question_id, ids())


class TeacherQuestionDraftsTabTests(_ScopedOrgFixture):
    """تب پیش‌نویس‌ها از داده‌ی واقعی: سؤال‌های منتشرنشده و فرم‌های ذخیره‌خودکار؛ قبلاً درصد تکمیل چرخشی و تاریخ ثابت بود."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.teacher_user = get_user_model().objects.create_user(username='teacher_in_scope', email='t_in@example.com', password='x')
        cls.draft_id = str(uuid.uuid4())
        _insert('questions', ['id', 'teacher_id', 'text', 'type', 'is_published', 'updated_at'],
                [cls.draft_id, cls.teacher_in_id, 'پیش‌نویس قدیمی', 'single', False, timezone.now() - timedelta(days=20)])
        _insert('questions', ['id', 'teacher_id', 'text', 'type', 'is_published'], [str(uuid.uuid4()), cls.teacher_in_id, 'سؤال منتشرشده', 'single', True])
        _insert('system_settings', ['key', 'value'], [f'question_draft.{cls.teacher_in_id}.new-essay',
                json.dumps({'fields': {'text': ['شرح فرم ناتمام']}, 'saved_at': '۱۴۰۵/۰۸/۰۹ ۱۰:۲۰'}, ensure_ascii=False)])
        _insert('system_settings', ['key', 'value'], [f'question_draft.{cls.teacher_out_id}.new-single',
                json.dumps({'fields': {'text': ['فرم استاد دیگر']}, 'saved_at': 'x'}, ensure_ascii=False)])

    def test_drafts_tab_lists_unpublished_questions_and_own_autosaves(self):
        self.client.force_login(self.teacher_user)
        page = self.client.get(reverse('core:teacher_questions'), {'view': 'drafts'})
        texts = [q['text'] for q in page.context['questions']]
        self.assertIn('پیش‌نویس قدیمی', texts)
        self.assertNotIn('سؤال منتشرشده', texts)
        self.assertEqual([(d['title'], d['kind']) for d in page.context['autosaved_drafts']], [('شرح فرم ناتمام', 'جدید')])
        self.assertEqual(page.context['stale_drafts'], 1)
        self.assertContains(page, '?type=essay&amp;draft=restore')
        self.assertNotContains(page, 'فرم استاد دیگر')
        self.assertNotContains(page, 'width: 75%')


class TeacherQuestionBanksAndCategoriesTests(_ScopedOrgFixture):
    """بانک = درس، و دسته‌بندی‌ها = مبحث و برچسب واقعی سؤال‌ها؛ قبلاً بانک‌ها و برچسب‌ها و تاریخ‌ها ساختگی بودند."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.teacher_user = get_user_model().objects.create_user(username='teacher_in_scope', email='t_in@example.com', password='x')
        with connection.cursor() as cursor:
            cursor.execute('DELETE FROM questions WHERE teacher_id = %s', [cls.teacher_in_id])
        rows = [
            ('سؤال قلب ۱', cls.course_in_id, 'قلب و عروق', 'ECG, قلب', True),
            ('سؤال قلب ۲', cls.course_in_id, 'قلب و عروق', 'قلب و عروق، ECG', False),
            ('سؤال بدون درس', None, '', '', True),
        ]
        for text, course, subject, tags, published in rows:
            _insert('questions', ['id', 'teacher_id', 'course_id', 'text', 'type', 'subject', 'tags', 'is_published'],
                    [str(uuid.uuid4()), cls.teacher_in_id, course, text, 'single', subject, tags, published])

    def test_banks_categories_and_their_filters(self):
        self.client.force_login(self.teacher_user)
        url = reverse('core:teacher_questions')
        banks = self.client.get(url, {'view': 'banks'}).context['question_banks']
        self.assertEqual([(b['title'], b['active'], b['draft']) for b in banks], [('درس داخل محدوده', 1, 1), ('بدون درس', 1, 0)])
        self.assertEqual(sorted(q['text'] for q in self.client.get(url, {'course': self.course_in_id}).context['questions']), ['سؤال قلب ۱', 'سؤال قلب ۲'])
        self.assertEqual([q['text'] for q in self.client.get(url, {'course': 'none'}).context['questions']], ['سؤال بدون درس'])

        categories = self.client.get(url, {'view': 'tags'}).context['question_categories']
        self.assertEqual([(t['title'], t['count']) for t in categories['tags']], [('ECG', 2), ('قلب', 1), ('قلب و عروق', 1)])
        self.assertEqual([(s['title'], s['count']) for s in categories['subjects']], [('قلب و عروق', 2)])
        self.assertEqual([q['text'] for q in self.client.get(url, {'tag': 'قلب'}).context['questions']], ['سؤال قلب ۱'])  # exact tag, not "قلب و عروق"
        page = self.client.get(url, {'tag': 'ECG', 'subject': 'قلب و عروق'})
        self.assertEqual(page.context['question_page'].paginator.count, 2)
        self.assertContains(page, 'برچسب «ECG»')
        self.assertNotContains(self.client.get(url, {'view': 'tags'}), 'داروشناسی')


class TeacherQuestionSharingTests(_ScopedOrgFixture):
    """اشتراک سؤال فقط با اساتید همان درس (سمت سرور) و افزودن نسخه‌ی پیش‌نویس به بانک خود؛ قبلاً تب اشتراکی سؤال‌های خود استاد را
    با نام «استاد نمونه» نشان می‌داد."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        User = get_user_model()
        cls.teacher_user = User.objects.create_user(username='teacher_in_scope', email='t_in@example.com', password='x')
        cls.co_teacher_user = User.objects.create_user(username='teacher_out_scope', email='t_out@example.com', password='x')
        _insert('group_teachers', ['group_id', 'teacher_id'], [cls.group_in_id, cls.teacher_out_id])  # co-teaches course_in
        cls.question_id, cls.other_course_id = str(uuid.uuid4()), str(uuid.uuid4())
        _insert('questions', ['id', 'teacher_id', 'course_id', 'text', 'type', 'is_published', 'options', 'correct_answer'],
                [cls.question_id, cls.teacher_in_id, cls.course_in_id, 'سؤال قابل اشتراک', 'single', True,
                 json.dumps([{'id': '1', 'text': 'الف', 'is_correct': True}]), json.dumps('1')])
        _insert('questions', ['id', 'teacher_id', 'course_id', 'text', 'type', 'is_published', 'shared_at'],
                [cls.other_course_id, cls.teacher_out_id, cls.course_out_id, 'سؤال درس دیگر', 'single', True, timezone.now()])

    def _shared_texts(self, user):
        self.client.force_login(user)
        return [q['text'] for q in self.client.get(reverse('core:teacher_questions'), {'view': 'shared'}).context['questions']]

    def test_sharing_reaches_only_teachers_of_the_course_and_copies_as_draft(self):
        share = reverse('core:teacher_question_share', args=[self.question_id])
        self.client.force_login(self.co_teacher_user)
        self.assertEqual(self.client.post(share, {'action': 'share'}).status_code, 404)  # not the owner
        self.assertEqual(self._shared_texts(self.co_teacher_user), [])

        self.client.force_login(self.teacher_user)
        self.client.post(share, {'action': 'share'})
        self.assertEqual(self._shared_texts(self.co_teacher_user), ['سؤال قابل اشتراک'])
        self.assertContains(self.client.get(reverse('core:teacher_questions'), {'view': 'shared'}), 'استاد خارج محدوده')
        self.assertEqual(self._shared_texts(self.teacher_user), [])  # not own questions, nor the other course's share

        copy_other = reverse('core:teacher_shared_question_copy', args=[self.other_course_id])
        self.assertEqual(self.client.post(copy_other).status_code, 404)  # teacher_in does not teach that course

        self.client.force_login(self.co_teacher_user)
        response = self.client.post(reverse('core:teacher_shared_question_copy', args=[self.question_id]))
        from apps.core.views import erd_row
        copy = erd_row("SELECT * FROM questions WHERE teacher_id = %s AND text = 'سؤال قابل اشتراک'", [self.teacher_out_id])
        self.assertRedirects(response, reverse('core:teacher_question_edit', args=[copy['id']]), fetch_redirect_response=False)
        self.assertEqual((bool(copy['is_published']), copy['shared_at'], str(copy['course_id'])), (False, None, self.course_in_id))
        self.assertEqual(json.loads(copy['options'])[0]['text'], 'الف')

        self.client.force_login(self.teacher_user)
        self.client.post(share, {'action': 'unshare'})
        self.assertEqual(self._shared_texts(self.co_teacher_user), [])


class TeacherPanelRealNumbersTests(_ScopedOrgFixture):
    """جزئیات کلاس و پروفایل پنل استاد از داده‌ی واقعی؛ قبلاً میانگین ۱۶٫۸، آزمون‌ها و فعالیت‌های نمونه و تلفن و کد ملی ساختگی بود."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        User = get_user_model()
        cls.teacher_user = User.objects.create_user(username='teacher_in_scope', email='t_in@example.com', password='x')
        _insert('student_group_members', ['id', 'group_id', 'student_user_id', 'full_name', 'national_id', 'student_number'],
                [str(uuid.uuid4()), cls.group_in_id, cls.student_in_id, 'دانشجوی داخل محدوده', '0000000000', 'S-1'])
        with connection.cursor() as cursor:
            cursor.execute("UPDATE exams SET is_published = %s, lifecycle_status = 'published', start_at = %s, end_at = %s WHERE id = %s",
                           [True, timezone.now() - timedelta(days=2), timezone.now() - timedelta(days=1), cls.exam_in_id])
        _insert('exam_attempts', ['id', 'exam_id', 'student_id', 'started_at', 'submitted_at', 'score', 'max_score', 'is_graded', 'status'],
                [str(uuid.uuid4()), cls.exam_in_id, cls.student_in_id, timezone.now(), timezone.now(), 15, 20, True, 'graded'])

    def test_course_detail_shows_real_numbers_and_only_own_groups(self):
        self.client.force_login(self.teacher_user)
        self.assertEqual(self.client.get(reverse('core:teacher_course_detail', args=[self.group_out_id])).status_code, 404)
        page = self.client.get(reverse('core:teacher_course_detail', args=[self.group_in_id]))
        summary = page.context['course_summary']
        self.assertEqual((summary['students_count'], summary['exams_count'], summary['active_exams_count'], summary['class_average']), (1, 1, 0, 15.0))
        self.assertEqual([(item['title'], item['type']) for item in page.context['course_activity']], [('آزمون داخل محدوده', 'برگزاری آزمون')])
        exams = self.client.get(reverse('core:teacher_course_detail', args=[self.group_in_id]), {'tab': 'exams', 'exam_status': 'پایان‌یافته'}).context['course_exams']
        self.assertEqual([(e['status_label'], e['participants_count'], e['average_score']) for e in exams], [('پایان‌یافته', 1, 15.0)])
        html = page.content.decode()
        for invented in ('۱۶.۸', 'آزمون میان‌ترم', '۱۴۰۴/۰۳/۱۰'):
            self.assertNotIn(invented, html)

    def test_profile_has_no_invented_identity(self):
        self.client.force_login(self.teacher_user)
        profile = self.client.get(reverse('core:teacher_panel')).context['teacher_profile']
        self.assertEqual(profile['phone'], '')
        self.assertNotIn('national_id', profile)
        self.assertEqual(profile['faculty'], '')


class ManagerDashboardCardsTests(_ScopedOrgFixture):
    """کارت‌های داشبورد مدیر فقط عدد محاسبه‌شده دارند؛ قبلاً «۲۵٪ نسبت به ماه قبل» و «۸ مورد جدید» ثابت بود و «نیازمند بررسی»
    پاسخ‌های تصحیح‌نشده‌ی کل سامانه را می‌شمرد."""

    def test_exam_manager_cards_are_computed_within_scope(self):
        _insert('exam_attempts', ['id', 'exam_id', 'student_id', 'started_at', 'status'], [str(uuid.uuid4()), self.exam_out_id, self.student_out_id, timezone.now(), 'submitted'])
        self.client.force_login(self.manager_user)
        page = self.client.get(reverse('core:exam_manager_dashboard'))
        self.assertNotContains(page, 'نسبت به ماه قبل')
        cards = {card['label']: card for card in page.context['dashboard_stats']}
        self.assertEqual(cards['نیازمند بررسی']['hint'], 'آزمون در انتظار تأیید')
        self.assertIn('در حال برگزاری', cards['آزمون‌های منتشرشده']['hint'])


class DashboardChartsRealDataTests(_ScopedOrgFixture):
    """نمودارها و وضعیت سلامت داشبوردهای مدیر از داده‌ی واقعی؛ قبلاً روند از «تعداد تلاش + ۴، + ۸…» با تاریخ‌های ثابت اردیبهشت،
    سلامت همیشه «سالم»، مشارکت ۷۲/۱۸/۱۰ ثابت و اقدامات نیازمند توجه چهار برچسب ثابت بود."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        now = timezone.now()
        with connection.cursor() as cursor:
            cursor.execute("UPDATE exams SET is_published = %s, lifecycle_status = 'published', start_at = %s, end_at = %s WHERE id = %s",
                           [True, now - timedelta(hours=1), now + timedelta(hours=1), cls.exam_in_id])
            cursor.execute("UPDATE exams SET lifecycle_status = 'pending_approval' WHERE id = %s", [cls.exam_out_id])
        _insert('exam_attempts', ['id', 'exam_id', 'student_id', 'started_at', 'submitted_at', 'is_graded', 'status'],
                [str(uuid.uuid4()), cls.exam_in_id, cls.student_in_id, now, now, True, 'graded'])
        _insert('exam_attempts', ['id', 'exam_id', 'student_id', 'started_at', 'status'],
                [str(uuid.uuid4()), cls.exam_out_id, cls.student_out_id, now, 'in_progress'])

    def test_system_dashboard_uses_measured_values(self):
        import tempfile
        from apps.core.views import erd_admin_dashboard_panel
        panel = erd_admin_dashboard_panel()
        statuses = {item['label']: item['count'] for item in panel['exam_status_items']}
        self.assertEqual(sum(statuses.values()), panel['exams_count'])
        self.assertEqual(statuses['در حال برگزاری'], 1)
        self.assertEqual((panel['trend_started_total'], panel['trend_submitted_total']), (2, 1))
        from apps.core.views import _jalali_long_date
        self.assertEqual(panel['trend_labels'][-1], ' '.join(_jalali_long_date(timezone.localdate(), with_weekday=False).split()[:2]))
        health = {item['label']: item for item in panel['health_items']}
        self.assertTrue(health['پایگاه داده']['status'].startswith('سالم'))
        with self.settings(BACKUP_DIR=''):
            self.assertEqual({i['label']: i for i in erd_admin_dashboard_panel()['health_items']}['پشتیبان‌گیری']['status'], 'پایش نشده')
        with tempfile.TemporaryDirectory() as folder, self.settings(BACKUP_DIR=folder):
            self.assertEqual({i['label']: i for i in erd_admin_dashboard_panel()['health_items']}['پشتیبان‌گیری']['status'], 'نسخه‌ای پیدا نشد')
            open(f'{folder}/db.dump', 'w').close()
            backup = {i['label']: i for i in erd_admin_dashboard_panel()['health_items']}['پشتیبان‌گیری']
            self.assertEqual(backup['tone'], 'ok')

    def test_manager_dashboard_charts_stay_in_scope(self):
        self.client.force_login(self.manager_user)
        page = self.client.get(reverse('core:exam_manager_dashboard'))
        context = page.context
        self.assertEqual({i['label']: i['value'] for i in context['participation_items']},
                         {'تصحیح‌شده': 1, 'در انتظار تصحیح': 0, 'ناتمام (ارسال‌نشده)': 0})  # the out-of-scope attempt is not counted
        self.assertEqual(context['trend_submitted_total'], 1)
        self.assertEqual([item['label'] for item in context['attention_items']], [])  # the pending exam is outside the scope
        html = page.content.decode()
        for invented in ('۷۲٪', 'تداخل زمانی آزمون', 'درخواست مهمان‌پذیری', 'cx="200" cy="62"'):
            self.assertNotIn(invented, html)


class BackupDatabaseCommandTests(TestCase):
    """دستور backup_database نسخه‌ی واقعی در BACKUP_DIR می‌سازد و داشبورد سلامت همان را پایش می‌کند."""

    def test_backup_is_written_kept_and_seen_by_the_dashboard(self):
        import tempfile
        from pathlib import Path
        from django.core.management import CommandError, call_command
        from apps.core.views import _system_health_items
        with self.settings(BACKUP_DIR=''):
            with self.assertRaises(CommandError):
                call_command('backup_database', stdout=io.StringIO())
        with tempfile.TemporaryDirectory() as folder, self.settings(BACKUP_DIR=folder):
            call_command('backup_database', stdout=io.StringIO())
            call_command('backup_database', '--keep', '1', stdout=io.StringIO())
            files = list(Path(folder).glob('db-*.dump' if connection.vendor == 'postgresql' else 'db-*.sqlite3'))
            self.assertEqual(len(files), 1)
            self.assertGreater(files[0].stat().st_size, 0)
            backup = {item['label']: item for item in _system_health_items()}['پشتیبان‌گیری']
            self.assertEqual(backup['tone'], 'ok')


class _EnforcedExamFixture(_ScopedOrgFixture):
    """A published course exam whose settings were saved through the wizard (settings_enforced), assigned to the
    in-scope group with the in-scope student as a member, and three questions: single choice, multi answer, essay."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        User = get_user_model()
        cls.teacher_user = User.objects.create_user(username='teacher_in_scope', email='t_in@example.com', password='x')
        cls.student_user = User.objects.create_user(username='student_in_scope', email='s_in@example.com', password='x')
        TeacherStudentScopeTests._member(cls.group_in_id, cls.student_in_id)
        with connection.cursor() as cursor:
            cursor.execute('UPDATE profiles SET national_id = %s WHERE id = %s', ['0012345678', cls.student_in_id])
        options = json.dumps([{'id': '1', 'text': 'الف'}, {'id': '2', 'text': 'ب'}, {'id': '3', 'text': 'ج'}], ensure_ascii=False)
        cls.single_id, cls.multi_id, cls.essay_id = (str(uuid.uuid4()) for _ in range(3))
        _insert('questions', ['id', 'teacher_id', 'course_id', 'text', 'type', 'options', 'correct_answer', 'default_points'],
                [cls.single_id, cls.teacher_in_id, cls.course_in_id, 'تک‌گزینه‌ای', 'single', options, json.dumps('2'), 2])
        _insert('questions', ['id', 'teacher_id', 'course_id', 'text', 'type', 'options', 'correct_answer', 'scoring_settings', 'default_points'],
                [cls.multi_id, cls.teacher_in_id, cls.course_in_id, 'چندپاسخی', 'multi', options, json.dumps(['1', '2']),
                 json.dumps({'scoring_mode': 'partial'}), 2])
        _insert('questions', ['id', 'teacher_id', 'course_id', 'text', 'type', 'default_points'],
                [cls.essay_id, cls.teacher_in_id, cls.course_in_id, 'تشریحی', 'essay', 2])

    def _exam(self, **settings):
        now = timezone.now()
        exam_id = str(uuid.uuid4())
        columns = {'id': exam_id, 'title': 'آزمون قوانین', 'teacher_id': self.teacher_in_id, 'course_id': self.course_in_id,
                   'start_at': now - timedelta(minutes=5), 'end_at': now + timedelta(hours=2), 'duration_minutes': 30,
                   'is_published': True, 'is_cancelled': False, 'lifecycle_status': 'published', 'settings_enforced': True,
                   'review_answers_enabled': True, 'allow_answer_changes': True, 'one_question_per_page': True,
                   'webcam_monitoring': False, 'copy_paste_prevention': False, 'screenshot_prevention': False,
                   'identity_verification_required': False, 'show_instructions_before_start': False,
                   'internet_disconnect_policy': 'none', **settings}
        _insert('exams', list(columns), list(columns.values()))
        _insert('exam_assignments', ['id', 'exam_id', 'group_id'], [str(uuid.uuid4()), exam_id, self.group_in_id])
        for order, question_id in enumerate((self.single_id, self.multi_id, self.essay_id), start=1):
            _insert('exam_questions', ['id', 'exam_id', 'question_id', 'points', 'order_index'],
                    [str(uuid.uuid4()), exam_id, question_id, 2, order])
        return exam_id

    def _start(self, exam_id, client=None):
        client = client or self.client
        response = client.post(reverse('core:student_exam_start', args=[exam_id]))
        location = response.get('Location', '')
        is_attempt = '/student/attempts/' in location and not location.rstrip('/').endswith('/receipt')
        return location.rstrip('/').split('/')[-1] if is_attempt else None

    def _rows(self, sql, params):
        with connection.cursor() as cursor:
            cursor.execute(sql, params)
            return cursor.fetchall()


class ExamWizardSettingsSavedTests(_ScopedOrgFixture):
    """تنظیمات ویزارد که قبلاً ذخیره نمی‌شد یا گم می‌شد: نمره‌ی کل، درصد قبولی، دوره/ترم، نمره‌ی هر سؤال،
    روش نمره‌دهی یکسان، و اعتبارسنجی زمان‌ها و محدوده‌ی IP در سمت سرور."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.teacher_user = get_user_model().objects.create_user(username='teacher_in_scope', email='t_in@example.com', password='x')

    def _post(self, **overrides):
        payload = {'title': 'آزمون ویزارد', 'course_id': self.course_in_id, 'group_ids': [self.group_in_id],
                   'question_ids': [self.question_in_id, self.question_in2_id], 'duration_minutes': '60',
                   'start_at': '2026-12-10T09:00', 'publish_choice': 'submit', 'passing_score_total': '100',
                   'min_passing_percent': '55', 'academic_term': '1405/دوم', 'grading_method': 'weighted_by_type',
                   f'question_points_{self.question_in_id}': '7.5'}
        payload.update(overrides)
        self.client.force_login(self.teacher_user)
        return self.client.post(reverse('core:teacher_exam_create'), payload)

    def _exam(self):
        with connection.cursor() as cursor:
            cursor.execute("SELECT id, total_score, passing_percent, passing_score, academic_year, semester, settings_enforced "
                           "FROM exams WHERE title = 'آزمون ویزارد'")
            return cursor.fetchall()

    def test_scale_pass_percent_term_and_points_are_saved(self):
        self._post()
        [(exam_id, total, percent, passing, year, semester, enforced)] = self._exam()
        self.assertEqual((float(total), float(percent), float(passing), year, semester, bool(enforced)), (100.0, 55.0, 55.0, '1405', 'دوم', True))
        with connection.cursor() as cursor:
            cursor.execute('SELECT question_id, points FROM exam_questions WHERE exam_id = %s ORDER BY order_index', [exam_id])
            self.assertEqual([(str(q), float(p)) for q, p in cursor.fetchall()], [(self.question_in_id, 7.5), (self.question_in2_id, 3.0)])
        initial = self.client.get(reverse('core:teacher_exam_edit', args=[exam_id])).context['wizard_initial']
        self.assertEqual((initial['fields']['passing_score_total'], initial['fields']['min_passing_percent']), (100.0, 55.0))
        self.assertEqual(initial['question_points'][self.question_in_id], 7.5)

    def test_uniform_grading_weighs_every_question_the_same(self):
        self._post(grading_method='uniform')
        exam_id = self._exam()[0][0]
        with connection.cursor() as cursor:
            cursor.execute('SELECT points FROM exam_questions WHERE exam_id = %s', [exam_id])
            self.assertEqual({float(row[0]) for row in cursor.fetchall()}, {1.0})

    def test_server_refuses_inconsistent_times_and_ip_ranges(self):
        for overrides, message in (
            ({'last_entry_at': '2026-12-10T12:00'}, 'آخرین زمان مجاز ورود'),
            ({'registration_start_at': '2026-12-10T10:00'}, 'شروع دسترسی'),
            ({'start_at': ''}, 'تاریخ و زمان شروع آزمون'),
            ({'min_passing_percent': '130'}, 'نمره قبولی'),
            ({'ip_restriction_enabled': '1', 'ip_restriction_range': 'not-an-ip'}, 'محدودیت IP'),
        ):
            response = self._post(**overrides)
            self.assertRedirects(response, reverse('core:teacher_exam_create'), fetch_redirect_response=False)
            page = self.client.get(response['Location'])
            self.assertIn(message, ' '.join(str(m) for m in page.context['messages']), overrides)
            self.assertEqual(self._exam(), [], overrides)
        self.assertEqual(self._post(start_at='', publish_choice='draft').status_code, 302)  # a draft may lack its date
        self.assertEqual(len(self._exam()), 1)


class ExamGradingRulesTests(_EnforcedExamFixture):
    """«نمره منفی»، «نمره جزئی»، درصد قبولی و حالت‌های نمایش نتیجه‌ی ویزارد واقعاً در تصحیح و کارنامه اعمال می‌شوند."""

    def _submit(self, exam_id, answers):
        self.client.force_login(self.student_user)
        attempt_id = self._start(exam_id)
        self.client.post(reverse('core:student_attempt', args=[attempt_id]), answers)
        self.client.post(reverse('core:student_attempt_submit', args=[attempt_id]))
        return attempt_id

    def _points(self, attempt_id):
        return {str(q): float(p or 0) for q, p in self._rows('SELECT question_id, points_awarded FROM attempt_answers WHERE attempt_id = %s', [attempt_id])}

    def test_exam_negative_marking_and_partial_switch(self):
        exam_id = self._exam(negative_marking=True, negative_factor=0.25, allow_partial=False)
        attempt_id = self._submit(exam_id, {f'answer_{self.single_id}': '1', f'answer_{self.multi_id}': ['1']})
        points = self._points(attempt_id)
        self.assertEqual(points[self.single_id], -0.5)  # 0.25 of its 2 points
        self.assertEqual(points[self.multi_id], -0.5)  # «نمره جزئی» off: one of two correct options is wrong, penalised
        legacy = self._exam(negative_marking=True, negative_factor=0.25, allow_partial=False, settings_enforced=None)
        attempt_id = self._submit(legacy, {f'answer_{self.single_id}': '1', f'answer_{self.multi_id}': ['1']})
        points = self._points(attempt_id)
        self.assertEqual((points[self.single_id], points[self.multi_id]), (0.0, 1.0))  # an exam not saved by the wizard grades as before

    def test_pass_percent_scale_and_display_modes(self):
        exam_id = self._exam(total_score=100, passing_percent=40, score_display_mode='immediate',
                             correct_answer_display_mode='manual', explanation_display_mode='immediate')
        attempt_id = self._submit(exam_id, {f'answer_{self.single_id}': '2', f'answer_{self.multi_id}': ['1', '2']})
        with connection.cursor() as cursor:  # the essay is graded by hand: 1 of its 2 points
            cursor.execute('UPDATE attempt_answers SET points_awarded = 1, needs_manual_grading = false WHERE attempt_id = %s AND question_id = %s',
                           [attempt_id, self.essay_id])
            cursor.execute('UPDATE exam_attempts SET score = 5, is_graded = true, status = %s WHERE id = %s', ['graded', attempt_id])
        page = self.client.get(reverse('core:student_result_detail', args=[attempt_id]))
        self.assertEqual(page.context['result']['status_label'], 'قبول')  # 5/6 = 83% >= 40%
        self.assertEqual((page.context['result']['scaled_score'], page.context['result']['scale']), (83.33, '100'))
        self.assertFalse(page.context['show_correct'])  # «نمایش داده نشود»
        self.assertTrue(page.context['show_explanation'])
        with connection.cursor() as cursor:
            cursor.execute("UPDATE exams SET grading_template = 'total_score' WHERE id = %s", [exam_id])
        page = self.client.get(reverse('core:student_result_detail', args=[attempt_id]))
        self.assertContains(page, 'فقط نمره‌ی کل اعلام می‌شود')
        self.assertNotContains(page, 'دسترسی سریع به سوالات')

    def test_training_exam_releases_results_on_grading(self):
        exam_id = self._exam(exam_mode='training', score_display_mode='after_publish')
        attempt_id = self._submit(exam_id, {f'answer_{self.single_id}': '2'})
        with connection.cursor() as cursor:
            cursor.execute('UPDATE exam_attempts SET is_graded = true, status = %s WHERE id = %s', ['graded', attempt_id])
        result = self.client.get(reverse('core:student_result_detail', args=[attempt_id])).context['result']
        self.assertTrue(result['visibility']['score'] and result['visibility']['correct_answers'])

    def test_min_correct_choices(self):
        from apps.core.views import _grade_question
        row = {'type': 'multi', 'correct_answer': json.dumps(['1', '2']), 'scoring_settings': {'scoring_mode': 'partial', 'min_correct': 2}}
        self.assertEqual(_grade_question(row, ['1'], 2)[0], 0)  # fewer choices than «حداقل پاسخ صحیح»
        self.assertEqual(_grade_question(row, ['1', '2'], 2)[0], 2)


class ExamAttemptRulesTests(_EnforcedExamFixture):
    """قوانین مرحله‌ی ۲ و ۶ ویزارد در صفحه‌ی آزمون دانشجو: بازگشت، تغییر پاسخ، علامت‌گذاری، یک سؤال در صفحه،
    فهرست سؤالات، محدودیت دستگاه، IP، ذخیره‌ی خودکار و ابزارهای مراقبت."""

    def setUp(self):
        self.client.force_login(self.student_user)

    def test_forward_only_navigation(self):
        exam_id = self._exam(review_answers_enabled=False)
        attempt_id = self._start(exam_id)
        url = reverse('core:student_attempt', args=[attempt_id])
        self.assertRedirects(self.client.post(f'{url}?q=1', {'action': 'next'}), f'{url}?q=2', fetch_redirect_response=False)
        self.assertRedirects(self.client.post(f'{url}?q=2', {'action': 'previous'}), f'{url}?q=2', fetch_redirect_response=False)
        self.assertRedirects(self.client.get(f'{url}?q=1'), f'{url}?q=2', fetch_redirect_response=False)
        page = self.client.get(f'{url}?q=2')
        self.assertNotContains(page, 'value="previous"')
        self.assertContains(page, 'بازگشت به سؤال‌های قبلی ممکن نیست')

    def test_answer_is_locked_after_leaving_it(self):
        exam_id = self._exam(allow_answer_changes=False)
        attempt_id = self._start(exam_id)
        url = reverse('core:student_attempt', args=[attempt_id])
        self.client.post(f'{url}?q=1', {f'answer_{self.single_id}': '1', 'action': 'next'})
        self.client.post(f'{url}?q=1', {f'answer_{self.single_id}': '2'}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        [(answer,)] = self._rows('SELECT answer FROM attempt_answers WHERE attempt_id = %s AND question_id = %s', [attempt_id, self.single_id])
        self.assertEqual(json.loads(answer)['value'], '1')
        self.assertContains(self.client.get(f'{url}?q=1'), 'دیگر تغییر نمی‌کند')

    def test_flagging_list_and_one_page_switches(self):
        exam_id = self._exam(allow_flagging_questions=False, show_question_list=False, one_question_per_page=False)
        attempt_id = self._start(exam_id)
        url = reverse('core:student_attempt', args=[attempt_id])
        page = self.client.get(url)
        self.assertEqual(page.content.decode().count('class="qx-qblock"'), 3)  # all questions on one page
        self.assertNotContains(page, 'علامت‌گذاری برای مرور')
        self.assertNotContains(page, 'aria-label="فهرست سؤالات"')
        self.client.post(url, {f'answer_{self.single_id}': '2', f'mark_{self.single_id}': 'on'}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(self._rows('SELECT marked_for_review FROM attempt_answers WHERE attempt_id = %s', [attempt_id]), [(False,)])

    def test_device_limit_off_lets_a_second_device_answer(self):
        from django.test import Client
        exam_id = self._exam(device_limit_enabled=False)
        attempt_id = self._start(exam_id)
        url = reverse('core:student_attempt', args=[attempt_id])
        self.assertEqual(self.client.get(url).status_code, 200)
        other = Client()
        other.force_login(self.student_user)
        self.assertEqual(other.post(url, {f'answer_{self.single_id}': '2'}, HTTP_X_REQUESTED_WITH='XMLHttpRequest').status_code, 200)

    def test_ip_restriction(self):
        exam_id = self._exam(ip_restriction_enabled=True, ip_restriction_range='10.10.0.0/16')
        self.assertIsNone(self._start(exam_id))  # the test client's 127.0.0.1 is outside the range
        self.assertEqual(self._rows('SELECT COUNT(*) FROM exam_attempts WHERE exam_id = %s', [exam_id]), [(0,)])
        response = self.client.post(reverse('core:student_exam_start', args=[exam_id]), REMOTE_ADDR='10.10.4.7')
        self.assertIn('/student/attempts/', response['Location'])
        forged = self.client.post(reverse('core:student_exam_start', args=[exam_id]), REMOTE_ADDR='8.8.8.8', HTTP_X_FORWARDED_FOR='10.10.4.7')
        self.assertNotIn('/student/attempts/', forged.get('Location', ''))  # a forged X-Forwarded-For is not trusted

    def test_page_gets_its_autosave_offline_and_proctoring_rules(self):
        exam_id = self._exam(autosave_enabled=True, autosave_interval_seconds=30, internet_disconnect_policy='pause',
                             copy_paste_prevention=True, screenshot_prevention=True, webcam_monitoring=True)
        page = self.client.get(reverse('core:student_attempt', args=[self._start(exam_id)]))
        self.assertEqual((page.context['page_rules']['autosave_seconds'], page.context['page_rules']['offline']), (30, 'pause'))
        self.assertEqual({key: page.context['proctoring'][key] for key in ('copy_paste', 'screenshot', 'webcam')},
                         {'copy_paste': True, 'screenshot': True, 'webcam': True})
        self.assertContains(page, 'id="attempt-rules"')
        events = reverse('core:student_attempt_event', args=[page.context['attempt']['id']])
        for event in ('screenshot', 'camera_off'):
            self.assertTrue(self.client.post(events, {'event': event}).json()['logged'])

    def test_legacy_exam_keeps_its_old_behaviour(self):
        exam_id = self._exam(settings_enforced=None, review_answers_enabled=False, one_question_per_page=False, webcam_monitoring=True)
        page = self.client.get(reverse('core:student_attempt', args=[self._start(exam_id)]))
        self.assertTrue(page.context['page_rules']['one_per_page'] and page.context['page_rules']['back'])
        self.assertFalse(page.context['proctoring']['webcam'])


class ExamEntryRulesTests(_EnforcedExamFixture):
    """ورود به آزمون: قوانین واقعی آزمون، احراز هویت با کد ملی/شماره دانشجویی، دور زدن ?ready=1، شروع با GET
    و تعداد تلاش مجاز در آزمون درسی."""

    def setUp(self):
        self.client.force_login(self.student_user)

    def test_identity_verification_and_no_bypass(self):
        exam_id = self._exam(identity_verification_required=True)
        entry = reverse('core:student_exam_entry', args=[exam_id])
        self.assertFalse(self.client.get(f'{entry}?ready=1').context['can_start'])  # the address alone does not pass the step
        self.assertIsNone(self._start(exam_id))
        response = self.client.post(entry, {'accept_rules': '1', 'identity_code': '999'})
        self.assertContains(response, 'مطابقت ندارد')
        self.client.post(entry, {'accept_rules': '1', 'identity_code': '۰۰۱۲۳۴۵۶۷۸'})  # Persian digits accepted
        self.assertTrue(self.client.get(entry).context['can_start'])
        self.assertIsNotNone(self._start(exam_id))
        self.assertEqual(self.client.get(reverse('core:student_exam_start', args=[exam_id])).status_code, 302)  # GET never creates

    def test_rules_shown_come_from_the_exam(self):
        exam_id = self._exam(review_answers_enabled=False, copy_paste_prevention=True, max_attempts=3)
        page = self.client.get(reverse('core:student_exam_detail', args=[exam_id]))
        lines = ' '.join(page.context['rule_lines'])
        for expected in ('بازگشت به سؤال‌های قبلی ممکن نیست', 'کپی و چسباندن', 'حداکثر 3 بار'):
            self.assertIn(expected, lines)
        self.assertNotContains(page, '۰۲:۱۵:۳۲')
        self.assertNotContains(self.client.get(reverse('core:student_exam_entry', args=[exam_id])), 'MQ-1405-027')

    def test_max_attempts_on_a_course_exam(self):
        exam_id = self._exam(max_attempts=2)
        attempts = []
        for _ in range(3):
            attempt_id = self._start(exam_id)
            if attempt_id:
                attempts.append(attempt_id)
                self.client.post(reverse('core:student_attempt_submit', args=[attempt_id]))
        self.assertEqual(len(set(attempts)), 2)
        self.assertContains(self.client.get(reverse('core:student_exam_detail', args=[exam_id])), 'فرصت‌های شرکت شما در این آزمون تمام شده است')

    def test_access_window(self):
        now = timezone.now()
        exam_id = self._exam(registration_start_at=now + timedelta(hours=1), start_at=now - timedelta(minutes=5))
        self.assertTrue(self.client.get(reverse('core:student_exam_detail', args=[exam_id])).context['access_not_open'])
        ended = self._exam(registration_end_at=now - timedelta(minutes=1))
        self.assertIsNone(self._start(ended))


class ExamTimedTasksTests(_EnforcedExamFixture):
    """کارهای زمان‌دار: تلاش‌های تمام‌شده ارسال یا منقضی می‌شوند و نتایج طبق «زمان اعلام نمره» منتشر می‌شود."""

    def _expired_attempt(self, **settings):
        exam_id = self._exam(**settings)
        attempt_id = str(uuid.uuid4())
        _insert('exam_attempts', ['id', 'exam_id', 'student_id', 'started_at', 'status'],
                [attempt_id, exam_id, self.student_in_id, timezone.now() - timedelta(hours=1), 'in_progress'])
        _insert('attempt_answers', ['id', 'attempt_id', 'question_id', 'answer', 'needs_manual_grading'],
                [str(uuid.uuid4()), attempt_id, self.single_id, json.dumps({'value': '2'}), False])
        return exam_id, attempt_id

    def test_expired_attempts_are_submitted_or_closed(self):
        from apps.core.exam_schedule import finalize_expired_attempts
        _exam, submitted = self._expired_attempt(auto_submit_on_time_end=True)
        _exam, expired = self._expired_attempt(auto_submit_on_time_end=False)
        _exam, legacy = self._expired_attempt(settings_enforced=None)
        self.assertEqual(set(finalize_expired_attempts()), {submitted, expired})
        status = lambda attempt_id: self._rows('SELECT status, score FROM exam_attempts WHERE id = %s', [attempt_id])[0]
        self.assertEqual(status(submitted)[0], 'submitted')  # the essay still waits for the teacher
        self.assertEqual(float(status(submitted)[1]), 2.0)
        self.assertEqual(status(expired), ('expired', None))
        self.assertEqual(status(legacy)[0], 'in_progress')
        self.client.force_login(self.student_user)
        self.client.post(reverse('core:student_attempt_submit', args=[expired]))
        self.assertEqual(status(expired)[0], 'expired')  # a late «پایان آزمون» does not submit it

    def test_results_are_released_when_due(self):
        from apps.core.exam_schedule import release_due_results
        now = timezone.now()
        ended = {'start_at': now - timedelta(days=4), 'end_at': now - timedelta(days=4) + timedelta(hours=1)}
        auto = self._exam(correction_mode='auto_then_manual', results_deadline='manual', **ended)
        waiting = self._exam(correction_mode='auto_then_manual', results_deadline='manual', **ended)
        deadline = self._exam(correction_mode='manual', results_deadline='3_days_after_end', **ended)
        manual = self._exam(correction_mode='manual', results_deadline='manual', **ended)
        for exam_id, graded in ((auto, True), (waiting, False), (deadline, False), (manual, True)):
            _insert('exam_attempts', ['id', 'exam_id', 'student_id', 'started_at', 'submitted_at', 'status', 'is_graded', 'score', 'max_score'],
                    [str(uuid.uuid4()), exam_id, self.student_in_id, ended['start_at'], ended['start_at'] + timedelta(minutes=20),
                     'graded' if graded else 'submitted', graded, 4 if graded else None, 6])
        self.assertEqual(set(release_due_results()), {auto, deadline})


class ExamPublishNoticeAndCalendarTests(_EnforcedExamFixture):
    """اعلان انتشار طبق «پس از انتشار» آزمون، و تقویم‌های استاد و مدیر از داده‌ی واقعی."""

    def test_publish_notifies_by_the_exams_settings(self):
        from apps.core.views import announce_exam_published
        loud = self._exam(notify_students_system_message=True, notify_students_email=False)
        quiet = self._exam(notify_students_system_message=False, notify_students_email=False)
        self.assertEqual((announce_exam_published(loud), announce_exam_published(quiet)), (1, 0))
        self.assertEqual(self._rows("SELECT type FROM notifications WHERE user_id = %s", [self.student_in_id]), [('new_exam',)])

    def test_manager_approving_a_teachers_exam_announces_it(self):
        exam_id = self._exam(is_published=False, lifecycle_status='pending_approval', notify_students_system_message=True)
        self.client.force_login(self.manager_user)
        self.client.post(reverse('core:super_admin_exam_edit', args=[exam_id]), {'edit_step': '5', 'publish_action': 'republish'})
        self.assertEqual(self._rows('SELECT is_published FROM exams WHERE id = %s', [exam_id]), [(True,)])
        self.assertEqual(len(self._rows("SELECT id FROM notifications WHERE user_id = %s AND type = 'new_exam'", [self.student_in_id])), 1)

    def test_teacher_calendar_shows_real_exams(self):
        exam_id = self._exam(title='آزمون تقویم')
        self.client.force_login(self.teacher_user)
        page = self.client.get(reverse('core:teacher_calendar'))
        self.assertContains(page, 'آزمون تقویم')
        self.assertNotContains(page, 'خرداد ۱۴۰۳')
        self.assertIn(exam_id, page.content.decode())

    def test_manager_calendar_follows_the_calendar_switch(self):
        self._exam(title='در تقویم', show_in_academic_calendar=True)
        self._exam(title='خارج از تقویم', show_in_academic_calendar=False)
        self.client.force_login(self.manager_user)
        titles = {event['title'] for event in self.client.get(reverse('core:exam_manager_calendar')).context['events']}
        self.assertIn('در تقویم', titles)
        self.assertNotIn('خارج از تقویم', titles)


class ExamStaffAccessTests(_EnforcedExamFixture):
    """«عوامل آزمون»: همکار تصحیح پاسخ‌ها را تصحیح می‌کند و ناظر نتایج را می‌بیند؛ انتشار نتایج با مالک آزمون است."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.helper_user = get_user_model().objects.create_user(username='teacher_out_scope', email='t_out@example.com', password='x')

    def test_co_grader_and_observer(self):
        exam_id = self._exam()
        attempt_id = str(uuid.uuid4())
        _insert('exam_attempts', ['id', 'exam_id', 'student_id', 'started_at', 'submitted_at', 'status'],
                [attempt_id, exam_id, self.student_in_id, timezone.now(), timezone.now(), 'submitted'])
        answer_id = str(uuid.uuid4())
        _insert('attempt_answers', ['id', 'attempt_id', 'question_id', 'answer', 'needs_manual_grading'],
                [answer_id, attempt_id, self.essay_id, json.dumps({'value': 'متن'}), True])
        self.client.force_login(self.helper_user)
        grading = reverse('core:teacher_grading_detail', args=[answer_id])
        self.assertEqual(self.client.get(grading).status_code, 404)
        _insert('exam_staff', ['id', 'exam_id', 'teacher_id', 'role'], [str(uuid.uuid4()), exam_id, self.teacher_out_id, 'co_grader'])
        self.assertEqual(self.client.get(grading).status_code, 200)
        results = self.client.get(reverse('core:teacher_results'), {'exam': exam_id})
        self.assertEqual(results.status_code, 200)
        self.assertContains(results, 'انتشار نتایج با استاد مالک آزمون است')
        self.assertEqual(self.client.post(reverse('core:teacher_publish_result', args=[exam_id]), {'action': 'publish'}).status_code, 404)


class QuestionBankRealFeaturesTests(_EnforcedExamFixture):
    """بانک سؤال: استفاده در آزمون‌ها و آخرین آزمون، کنار گذاشتن پیش‌نویس از ویزارد، و ورود گروهی واقعی سؤال."""

    def test_usage_and_drafts(self):
        exam_id = self._exam(title='آزمون آخر')
        draft_id = str(uuid.uuid4())
        _insert('questions', ['id', 'teacher_id', 'course_id', 'text', 'type', 'is_published', 'scoring_settings', 'default_points'],
                [draft_id, self.teacher_in_id, self.course_in_id, 'سؤال پیش‌نویس', 'single', False, json.dumps({}), 1])
        self.client.force_login(self.teacher_user)
        rows = {row['text']: row for row in self.client.get(reverse('core:teacher_questions')).context['questions']}
        self.assertEqual((rows['تک‌گزینه‌ای']['usage_count'], rows['تک‌گزینه‌ای']['last_exam_title']), (1, 'آزمون آخر'))
        offered = {str(q['id']): q for q in self.client.get(reverse('core:teacher_exam_create')).context['questions']}
        self.assertNotIn(draft_id, offered)
        self.assertEqual(offered[self.single_id]['last_exam_title'], 'آزمون آخر')
        self.assertIsNotNone(exam_id)

    def test_bulk_import_checks_rows_then_saves_the_valid_ones(self):
        self.client.force_login(self.teacher_user)
        url = reverse('core:teacher_question_bulk_import')
        self.assertTrue(self.client.get(url, {'template': '1'})['Content-Disposition'].endswith('.xlsx"'))
        content = ('نوع,متن سؤال,گزینه ۱,گزینه ۲,گزینه ۳,پاسخ صحیح,بارم,دشواری,تگ‌ها\n'
                   'تک‌گزینه‌ای,سؤال وارداتی یک,الف,ب,ج,2,3,سخت,وارداتی\n'
                   'چندگزینه‌ای,سؤال وارداتی دو,الف,ب,ج,"1,3",2,آسان,\n'
                   'درست/نادرست,سؤال وارداتی سه,,,,نادرست,1,,\n'
                   'پاسخ کوتاه,سؤال وارداتی چهار,,,,آب|water,1,,\n'
                   'تک‌گزینه‌ای,سؤال خراب,الف,ب,,7,1,,\n'
                   'نامعلوم,سؤال بی‌نوع,,,,,1,,\n')
        upload = io.BytesIO(content.encode('utf-8-sig'))
        upload.name = 'questions.csv'
        preview = self.client.post(url, {'course_id': self.course_in_id, 'import_file': upload})
        self.assertEqual((preview.context['import_valid'], preview.context['import_invalid']), (4, 2))
        self.assertRedirects(self.client.post(url, {'action': 'confirm'}), reverse('core:teacher_questions'), fetch_redirect_response=False)
        rows = {text: (kind, json.loads(correct) if correct else None, float(points), difficulty)
                for text, kind, correct, points, difficulty in self._rows(
                    "SELECT text, type, correct_answer, default_points, difficulty FROM questions WHERE text LIKE 'سؤال وارداتی%%'", [])}
        self.assertEqual(set(rows), {'سؤال وارداتی یک', 'سؤال وارداتی دو', 'سؤال وارداتی سه', 'سؤال وارداتی چهار'})
        self.assertEqual((rows['سؤال وارداتی یک'][0], rows['سؤال وارداتی یک'][2], rows['سؤال وارداتی یک'][3]), ('single', 3.0, 'hard'))
        self.assertEqual(rows['سؤال وارداتی دو'][0], 'multi')
        self.assertEqual(len(rows['سؤال وارداتی دو'][1]), 2)


class ManagerExamEditFixesTests(_EnforcedExamFixture):
    """صفحه‌ی ویرایش آزمون مدیر دیگر سؤال/گروه‌های بیرون از ۱۲/۸ ردیف اول را پاک نمی‌کند، ترتیب و نمره‌ی سؤال‌ها
    را نگه می‌دارد، «بازگشت به سوال قبلی» را خاموش نمی‌کند، و ویرایش کامل با ویزارد ممکن است."""

    def test_step_saves_keep_order_points_and_review(self):
        exam_id = self._exam(review_answers_enabled=True)
        with connection.cursor() as cursor:
            cursor.execute('UPDATE exam_questions SET points = 5 WHERE exam_id = %s AND question_id = %s', [exam_id, self.essay_id])
        self.client.force_login(self.manager_user)
        url = reverse('core:super_admin_exam_edit', args=[exam_id])
        page = self.client.get(f'{url}?step=3')
        self.assertContains(page, f'value="{self.essay_id}" checked')
        self.client.post(url, {'edit_step': '3', 'question_ids': [self.essay_id, self.single_id, self.multi_id]})
        self.assertEqual([(str(q), float(p)) for q, p in self._rows('SELECT question_id, points FROM exam_questions WHERE exam_id = %s ORDER BY order_index', [exam_id])],
                         [(self.single_id, 2.0), (self.multi_id, 2.0), (self.essay_id, 5.0)])
        self.client.post(url, {'edit_step': '4', 'duration_minutes': '30', 'review_answers_enabled': 'on'})
        self.assertEqual(self._rows('SELECT review_answers_enabled FROM exams WHERE id = %s', [exam_id]), [(True,)])

    def test_manager_full_wizard_edit(self):
        exam_id = self._exam(is_published=False, lifecycle_status='pending_approval', approval_status='pending')
        self.client.force_login(self.manager_user)
        url = reverse('core:super_admin_exam_wizard_edit', args=[exam_id])
        page = self.client.get(url)
        self.assertEqual(page.context['wizard_initial']['question_ids'], [self.single_id, self.multi_id, self.essay_id])
        self.client.post(url, {'title': 'آزمون بازبینی‌شده', 'course_id': self.course_in_id, 'group_ids': [self.group_in_id],
                               'question_ids': [self.single_id], 'duration_minutes': '40', 'start_at': '2026-12-01T10:00',
                               'webcam_monitoring': '1', 'publish_choice': 'draft'})
        self.assertEqual(self._rows('SELECT title, webcam_monitoring, lifecycle_status, is_published, teacher_id FROM exams WHERE id = %s', [exam_id])[0][:4],
                         ('آزمون بازبینی‌شده', True, 'pending_approval', False))
        _insert('exam_attempts', ['id', 'exam_id', 'student_id', 'started_at', 'status'],
                [str(uuid.uuid4()), exam_id, self.student_in_id, timezone.now(), 'in_progress'])
        self.assertRedirects(self.client.get(url), reverse('core:super_admin_exam_edit', args=[exam_id]), fetch_redirect_response=False)


class ExamEndToEndTests(_EnforcedExamFixture):
    """سناریوی کامل یک آزمون واقعی: استاد با ویزارد می‌سازد و برای تأیید می‌فرستد، مدیر تأیید و منتشر می‌کند، دانشجو
    اعلان می‌گیرد، با کد ملی وارد می‌شود، پاسخ می‌دهد و ارسال می‌کند، استاد تشریحی را تصحیح و نتایج را منتشر می‌کند و
    دانشجو کارنامه را روی مقیاس آزمون می‌بیند. زمان‌ها به وقت تهران و تاریخ‌ها شمسی نمایش داده می‌شوند."""

    def test_full_exam_lifecycle(self):
        from zoneinfo import ZoneInfo
        from apps.core.templatetags.core_extras import jalali_long
        tehran = ZoneInfo('Asia/Tehran')
        start_local = (timezone.now() - timedelta(minutes=2)).astimezone(tehran).replace(second=0, microsecond=0)
        self.client.force_login(self.teacher_user)
        response = self.client.post(reverse('core:teacher_exam_create'), {
            'title': 'آزمون پایان‌ترم', 'course_id': self.course_in_id, 'group_ids': [self.group_in_id],
            'question_ids': [self.single_id, self.multi_id, self.essay_id], 'exam_mode': 'standard',
            f'question_points_{self.single_id}': '4', f'question_points_{self.multi_id}': '4', f'question_points_{self.essay_id}': '2',
            'start_at': start_local.strftime('%Y-%m-%dT%H:%M'), 'duration_minutes': '45', 'max_attempts': '1',
            'passing_score_total': '20', 'min_passing_percent': '50', 'grading_method': 'weighted_by_type',
            'negative_marking': '1', 'negative_factor': '0.25', 'allow_partial': '1', 'auto_submit_on_time_end': '1',
            'allow_answer_changes': '1', 'review_answers_enabled': '1', 'show_question_list': '1',
            'identity_verification_required': '1', 'score_display_mode': 'after_publish',
            'correct_answer_display_mode': 'after_publish', 'explanation_display_mode': 'after_publish',
            'notify_students_system_message': '1', 'show_in_academic_calendar': '1', 'publish_choice': 'submit',
            'correction_instructions': 'به استدلال نمره بدهید.',
        })
        self.assertEqual(response.status_code, 302)
        [(exam_id, status, published, start_at, end_at)] = self._rows(
            "SELECT id, lifecycle_status, is_published, start_at, end_at FROM exams WHERE title = 'آزمون پایان‌ترم'", [])
        exam_id = str(exam_id)
        self.assertEqual((status, published), ('pending_approval', False))
        self.assertEqual(timezone.localtime(start_at).strftime('%H:%M'), start_local.strftime('%H:%M'))  # Tehran wall clock kept
        self.assertEqual(end_at - start_at, timedelta(minutes=45))
        self.assertEqual(self._rows('SELECT count(*) FROM notifications WHERE user_id = %s', [self.student_in_id]), [(0,)])

        self.client.force_login(self.student_user)  # not visible before approval
        self.assertNotEqual(self.client.get(reverse('core:student_exam_detail', args=[exam_id])).status_code, 200)

        self.client.force_login(self.manager_user)
        self.client.post(reverse('core:super_admin_exam_edit', args=[exam_id]), {'edit_step': '5', 'publish_action': 'republish'})
        self.assertEqual(self._rows('SELECT is_published, lifecycle_status FROM exams WHERE id = %s', [exam_id]), [(True, 'published')])
        self.assertEqual(self._rows("SELECT count(*) FROM notifications WHERE user_id = %s AND type = 'new_exam'", [self.student_in_id]), [(1,)])

        self.client.force_login(self.student_user)
        detail = self.client.get(reverse('core:student_exam_detail', args=[exam_id]))
        self.assertContains(detail, 'آزمون پایان‌ترم')
        self.assertContains(detail, jalali_long(start_at))  # «سه‌شنبه، ۱۲ آبان ۱۴۰۵»: the Jalali day of the Tehran start
        self.assertContains(detail, timezone.localtime(start_at).strftime('%H:%M').translate(str.maketrans('0123456789', '۰۱۲۳۴۵۶۷۸۹')))
        entry_url = reverse('core:student_exam_entry', args=[exam_id])
        self.client.post(entry_url, {'accept_rules': '1', 'identity_code': '9999999999'})
        self.assertIsNone(self._start(exam_id))  # wrong national id: no attempt
        self.client.post(entry_url, {'accept_rules': '1', 'identity_code': '۰۰۱۲۳۴۵۶۷۸'})  # Persian digits accepted
        attempt_id = self._start(exam_id)
        self.assertTrue(attempt_id)
        self.assertEqual(self.client.get(reverse('core:student_attempt', args=[attempt_id])).status_code, 200)
        self.client.post(reverse('core:student_attempt', args=[attempt_id]), {
            f'answer_{self.single_id}': '2', f'answer_{self.multi_id}': ['1', '3'], f'answer_{self.essay_id}': 'پاسخ تشریحی من'})
        self.client.post(reverse('core:student_attempt_submit', args=[attempt_id]))
        points = {str(q): float(p or 0) for q, p in self._rows('SELECT question_id, points_awarded FROM attempt_answers WHERE attempt_id = %s', [attempt_id])}
        self.assertEqual(points[self.single_id], 4.0)
        self.assertEqual(points[self.multi_id], 2.0)  # partial: one of two correct options; «3» has no «جریمه انتخاب نادرست»
        self.assertIsNone(self._start(exam_id))  # one attempt allowed
        result = self.client.get(reverse('core:student_result_detail', args=[attempt_id])).context['result']
        self.assertFalse(result['visibility']['score'])  # not published yet

        self.client.force_login(self.teacher_user)
        [(answer_id,)] = self._rows('SELECT id FROM attempt_answers WHERE attempt_id = %s AND question_id = %s', [attempt_id, self.essay_id])
        grading = self.client.get(reverse('core:teacher_grading_detail', args=[answer_id]))
        self.assertContains(grading, 'به استدلال نمره بدهید.')
        self.client.post(reverse('core:teacher_grading_detail', args=[answer_id]), {'score': '2', 'feedback': 'خوب'})
        [(score, graded)] = self._rows('SELECT score, is_graded FROM exam_attempts WHERE id = %s', [attempt_id])
        self.assertEqual((float(score), bool(graded)), (8.0, True))
        self.client.post(reverse('core:teacher_publish_result', args=[exam_id]), {'action': 'publish'})

        self.client.force_login(self.student_user)
        page = self.client.get(reverse('core:student_result_detail', args=[attempt_id]))
        result = page.context['result']
        self.assertTrue(result['visibility']['score'])
        self.assertEqual((result['scaled_score'], result['scale'], result['status_label']), (16.0, '20', 'قبول'))  # 8/10 on a 20 scale
        self.assertTrue(page.context['show_correct'])


class ExamTimingScenariosTests(_EnforcedExamFixture):
    """زمان‌های آزمون با جابه‌جا کردن ساعت: شروع، «آخرین زمان مجاز ورود»، مدت پاسخ و مهلت اضافه، پایان آزمون،
    «شروع/پایان دسترسی»، ارسال خودکار، انتشار زمان‌بندی‌شده، مخاطب گروهی و ذخیره‌ی زمان‌های ویزارد به وقت تهران."""

    def setUp(self):
        self.t0 = timezone.now().replace(second=0, microsecond=0)

    def at(self, moment):
        return mock.patch('django.utils.timezone.now', return_value=moment)

    def _student(self, username, group_id=None):
        profile_id = self._make_profile(username, 'دانشجوی ' + username)
        _insert('student_profiles', ['user_id', 'org_unit_id'], [profile_id, self.ou_scoped])
        _insert('user_roles', ['id', 'user_id', 'role'], [str(uuid.uuid4()), profile_id, 'student'])
        if group_id:
            TeacherStudentScopeTests._member(group_id, profile_id)
        return get_user_model().objects.create_user(username=username, email=f'{username}@example.com', password='x')

    def _save(self, attempt_id, value='2'):
        return self.client.post(reverse('core:student_attempt', args=[attempt_id]), {f'answer_{self.single_id}': value},
                                HTTP_X_REQUESTED_WITH='XMLHttpRequest')

    def _detail(self, exam_id, client=None):
        return (client or self.client).get(reverse('core:student_exam_detail', args=[exam_id]))

    def test_last_entry_time_lets_in_before_and_shuts_out_after(self):
        start = self.t0 + timedelta(hours=1)
        exam_id = self._exam(start_at=start, end_at=start + timedelta(hours=1), duration_minutes=30,
                             last_entry_at=start + timedelta(minutes=5))
        late = self.client_class()
        late.force_login(self._student('student_late', self.group_in_id))
        self.client.force_login(self.student_user)

        with self.at(start - timedelta(minutes=10)):  # before the start: countdown, no entry
            page = self._detail(exam_id)
            self.assertEqual((page.context['can_enter'], page.context['seconds_until_start']), (False, 600))
            self.assertIn(f"آخرین زمان ورود به آزمون ساعت {timezone.localtime(start + timedelta(minutes=5)):%H:%M} است.",
                          page.context['rule_lines'])  # Tehran time
            refused = self.client.post(reverse('core:student_exam_start', args=[exam_id]), follow=True)
            self.assertContains(refused, 'آزمون هنوز شروع نشده است.')
        with self.at(start + timedelta(minutes=4, seconds=59)):  # one second before the last entry time
            self.assertTrue(self._detail(exam_id).context['can_enter'])
            attempt_id = self._start(exam_id)
            self.assertTrue(attempt_id)
        with self.at(start + timedelta(minutes=5, seconds=1)):  # one second after it
            page = self._detail(exam_id, late)
            self.assertEqual((page.context['can_enter'], page.context['entry_expired']), (False, True))
            refused = late.post(reverse('core:student_exam_start', args=[exam_id]), follow=True)
            self.assertContains(refused, 'زمان ورود به این آزمون به پایان رسیده است.')
            self.assertEqual(self._rows('SELECT count(*) FROM exam_attempts WHERE exam_id = %s', [exam_id]), [(1,)])
            # the student who entered in time keeps working and may come back to the same attempt
            self.assertTrue(self._detail(exam_id).context['can_enter'])
            self.assertEqual(self._start(exam_id), attempt_id)
            self.assertEqual(self._save(attempt_id).json(), {'ok': True})
            remaining = self.client.get(reverse('core:student_attempt', args=[attempt_id])).context['remaining_seconds']
            self.assertEqual(remaining, 30 * 60 - 2)  # 30 minutes from its own start, not from the exam's

    def test_duration_grace_and_auto_submit(self):
        from apps.core.exam_schedule import finalize_expired_attempts
        start = self.t0
        exam_id = self._exam(start_at=start, end_at=start + timedelta(hours=2), duration_minutes=30, auto_submit_on_time_end=True)
        self.client.force_login(self.student_user)
        with self.at(start + timedelta(minutes=1)):
            attempt_id = self._start(exam_id)
        with self.at(start + timedelta(minutes=11)):
            self.assertEqual(self.client.get(reverse('core:student_attempt', args=[attempt_id])).context['remaining_seconds'], 20 * 60)
        with self.at(start + timedelta(minutes=30, seconds=59)):  # last second of the 30 minutes
            self.assertEqual(self._save(attempt_id, '1').json(), {'ok': True})
        with self.at(start + timedelta(minutes=31, seconds=50)):  # inside the 60 s grace for a slow network
            self.assertEqual(self.client.get(reverse('core:student_attempt', args=[attempt_id])).context['remaining_seconds'], 0)
            self.assertEqual(self._save(attempt_id, '2').json(), {'ok': True})
        with self.at(start + timedelta(minutes=32, seconds=1)):  # time is up: nothing more is saved
            self.assertEqual(self._save(attempt_id, '3').status_code, 409)
        self.assertEqual(finalize_expired_attempts(now=start + timedelta(minutes=32, seconds=1)), [attempt_id])  # browser closed
        [(status, score)] = self._rows('SELECT status, score FROM exam_attempts WHERE id = %s', [attempt_id])
        self.assertEqual((status, float(score)), ('submitted', 2.0))  # the answer saved in time («2») counts
        [(answer,)] = self._rows('SELECT answer FROM attempt_answers WHERE attempt_id = %s AND question_id = %s', [attempt_id, self.single_id])
        self.assertEqual(json.loads(answer) if isinstance(answer, str) else answer, {'value': '2'})

    def test_late_start_is_cut_at_the_exam_end(self):
        start = self.t0
        exam_id = self._exam(start_at=start, end_at=start + timedelta(minutes=40), duration_minutes=30)
        self.client.force_login(self.student_user)
        with self.at(start + timedelta(minutes=25)):
            attempt_id = self._start(exam_id)
            self.assertEqual(self.client.get(reverse('core:student_attempt', args=[attempt_id])).context['remaining_seconds'], 15 * 60)
        with self.at(start + timedelta(minutes=40, seconds=30)):
            self.assertEqual(self._save(attempt_id).json(), {'ok': True})  # grace
        with self.at(start + timedelta(minutes=41, seconds=1)):
            self.assertEqual(self._save(attempt_id).status_code, 409)

    def test_no_new_attempt_after_the_exam_end(self):
        start = self.t0
        exam_id = self._exam(start_at=start, end_at=start + timedelta(minutes=40), duration_minutes=30)
        self.client.force_login(self.student_user)
        with self.at(start + timedelta(minutes=40, seconds=1)):
            self.assertIsNone(self._start(exam_id))
            self.assertTrue(self._detail(exam_id).context['entry_expired'])

    def test_access_end_closes_entry_and_answers(self):
        start = self.t0
        exam_id = self._exam(start_at=start, end_at=start + timedelta(hours=1), duration_minutes=30,
                             registration_end_at=start + timedelta(minutes=20))
        other = self.client_class()
        other.force_login(self._student('student_other', self.group_in_id))
        self.client.force_login(self.student_user)
        with self.at(start + timedelta(minutes=10)):
            attempt_id = self._start(exam_id)
            self.assertEqual(self.client.get(reverse('core:student_attempt', args=[attempt_id])).context['remaining_seconds'], 10 * 60)
        with self.at(start + timedelta(minutes=20, seconds=1)):
            self.assertIsNone(self._start(exam_id, other))
        with self.at(start + timedelta(minutes=21, seconds=1)):
            self.assertEqual(self._save(attempt_id).status_code, 409)

    def test_access_start_opens_the_entry_page_but_not_the_exam(self):
        start = self.t0 + timedelta(hours=1)
        exam_id = self._exam(start_at=start, end_at=start + timedelta(hours=1), show_instructions_before_start=True,
                             registration_start_at=start - timedelta(minutes=30))
        entry = reverse('core:student_exam_entry', args=[exam_id])
        self.client.force_login(self.student_user)
        with self.at(start - timedelta(minutes=40)):
            early = self.client.post(entry, {'accept_rules': '1'})
            self.assertContains(early, 'ورود به این آزمون از ')
            self.assertFalse(early.context['can_start'])
        with self.at(start - timedelta(minutes=20)):
            self.assertEqual(self.client.post(entry, {'accept_rules': '1'}).status_code, 302)  # rules accepted early
            self.assertIsNone(self._start(exam_id))  # but the exam itself starts on time
        with self.at(start + timedelta(minutes=1)):
            self.assertTrue(self._start(exam_id))

    def test_no_auto_submit_closes_an_unsent_attempt(self):
        start = self.t0
        exam_id = self._exam(start_at=start, end_at=start + timedelta(hours=2), duration_minutes=30, auto_submit_on_time_end=False)
        self.client.force_login(self.student_user)
        with self.at(start + timedelta(minutes=1)):
            attempt_id = self._start(exam_id)
            self._save(attempt_id)
        with self.at(start + timedelta(minutes=33)):
            self.client.post(reverse('core:student_attempt_submit', args=[attempt_id]))
        self.assertEqual(self._rows('SELECT status, submitted_at FROM exam_attempts WHERE id = %s', [attempt_id]), [('expired', None)])

    def test_exam_reaches_only_its_groups_students(self):
        start = self.t0 + timedelta(hours=1)
        exam_id = self._exam(title='آزمون گروه الف', start_at=start, end_at=start + timedelta(hours=1))
        hidden_id = self._exam(title='آزمون منتشرنشده', start_at=start, end_at=start + timedelta(hours=1),
                               is_published=False, lifecycle_status='pending_approval')
        outsider = self.client_class()
        outsider.force_login(self._student('student_outsider'))  # same unit, not in the exam's group
        self.client.force_login(self.student_user)
        schedule = self.client.get(reverse('core:student_exam_schedule'))
        self.assertContains(schedule, 'آزمون گروه الف')
        self.assertNotContains(schedule, 'آزمون منتشرنشده')
        self.assertEqual(self._detail(hidden_id).status_code, 404)
        self.assertNotContains(outsider.get(reverse('core:student_exam_schedule')), 'آزمون گروه الف')
        self.assertEqual(self._detail(exam_id, outsider).status_code, 404)
        with self.at(start + timedelta(minutes=1)):
            self.assertEqual(outsider.post(reverse('core:student_exam_start', args=[exam_id])).status_code, 404)
            self.assertTrue(self._start(exam_id))

    def test_scheduled_publish_happens_at_its_time(self):
        from apps.core.exam_schedule import publish_due_exams
        exam_id = self._exam(start_at=self.t0 + timedelta(hours=1), end_at=self.t0 + timedelta(hours=2), is_published=False,
                             lifecycle_status='approved', scheduled_publish_at=self.t0 + timedelta(minutes=10))
        self.client.force_login(self.student_user)
        self.assertEqual(publish_due_exams(now=self.t0 + timedelta(minutes=9, seconds=59)), [])
        self.assertEqual(self._detail(exam_id).status_code, 404)
        self.assertEqual([str(exam['id']) for exam in publish_due_exams(now=self.t0 + timedelta(minutes=10, seconds=1))], [exam_id])
        self.assertEqual(self._detail(exam_id).status_code, 200)

    def test_wizard_times_are_tehran_times(self):
        self.client.force_login(self.teacher_user)
        payload = {'title': 'آزمون زمان', 'course_id': self.course_in_id, 'group_ids': [self.group_in_id],
                   'question_ids': [self.single_id], 'duration_minutes': '30', 'publish_choice': 'submit',
                   'start_at': '2026-12-10T16:00', 'end_at': '2026-12-10T17:00', 'last_entry_at': '2026-12-10T15:55'}
        self.client.post(reverse('core:teacher_exam_create'), payload)
        self.assertEqual(self._rows("SELECT count(*) FROM exams WHERE title = 'آزمون زمان'", []), [(0,)])  # last entry before start
        self.client.post(reverse('core:teacher_exam_create'), {**payload, 'last_entry_at': '2026-12-10T16:05'})
        [(start, end, last_entry)] = self._rows("SELECT start_at, end_at, last_entry_at FROM exams WHERE title = 'آزمون زمان'", [])
        from datetime import timezone as dt_timezone
        aware = lambda value: value if timezone.is_aware(value) else value.replace(tzinfo=dt_timezone.utc)  # UTC columns
        local = lambda value: timezone.localtime(aware(value)).strftime('%Y-%m-%d %H:%M')
        self.assertEqual((local(start), local(end), local(last_entry)), ('2026-12-10 16:00', '2026-12-10 17:00', '2026-12-10 16:05'))
        self.assertEqual(timezone.localtime(start).utcoffset(), timedelta(hours=3, minutes=30))
        [(exam_id,)] = self._rows("SELECT id FROM exams WHERE title = 'آزمون زمان'", [])
        fields = self.client.get(reverse('core:teacher_exam_edit', args=[exam_id])).context['wizard_initial']['fields']
        self.assertEqual((fields['start_at'], fields['last_entry_at']), ('2026-12-10T16:00', '2026-12-10T16:05'))  # edit shows them back


class ExamCodeJoinTests(_EnforcedExamFixture):
    """«ورود با کد آزمون» در صفحه‌ی اول: کد اختصاصی هر آزمون، ورود و بازگشت به همان آزمون، و همه‌ی حالت‌های زمان و دسترسی."""

    def _join(self, code, client=None, **extra):
        return (client or self.client).get(reverse('core:exam_join'), {'code': code}, **extra)

    def _code(self, exam_id):
        from apps.core.views import exam_access_code
        return exam_access_code(exam_id)

    def test_code_formats(self):
        from apps.core.views import _normalize_exam_code
        for typed in ('MQ-1A2B3C', 'mq1a2b3c', '1a2b3c', ' MQ 1A2B3C ', 'MQ-۱A۲B۳C', 'پض-۱ش۲ذ۳ز', 'MQ_1A2B3C'):
            self.assertEqual(_normalize_exam_code(typed), '1a2b3c', typed)
        for typed in ('', 'EX-8421', 'MQ-1A2B3', 'MQ-1A2B3CD', 'MQ-GGGGGG', '<script>', '1a2b3c%'):
            self.assertEqual(_normalize_exam_code(typed), '', typed)
        exam_id = self._exam()
        self.assertRegex(self._code(exam_id), r'^MQ-[0-9A-F]{6}$')
        self.assertEqual(self._code(exam_id), 'MQ-' + exam_id.replace('-', '')[:6].upper())

    def test_guest_signs_in_and_lands_on_the_exam(self):
        exam_id = self._exam()
        code = self._code(exam_id)
        response = self._join(code.lower())
        self.assertEqual(response.status_code, 302)
        login_url = response['Location']
        self.assertTrue(login_url.startswith(reverse('core:login') + '?'))
        login_page = self.client.get(login_url)
        self.assertContains(login_page, code)  # «کد آزمون: MQ-…» on the login page
        next_url = login_page.context['next']
        self.assertEqual(next_url, f"{reverse('core:exam_join')}?code={code}")
        self.student_user.set_password('Pass@12345')
        self.student_user.save()
        signed_in = self.client.post(login_url, {'username': self.student_user.username, 'password': 'Pass@12345', 'next': next_url})
        self.assertEqual(signed_in['Location'], next_url)
        landed = self.client.get(next_url)
        self.assertRedirects(landed, reverse('core:student_exam_entry', args=[exam_id]), fetch_redirect_response=False)
        entry = self.client.get(landed['Location'])
        self.assertContains(entry, code)
        self.client.post(landed['Location'], {'accept_rules': '1'})
        self.assertTrue(self._start(exam_id))

    def test_every_moment_of_the_exam(self):
        now = timezone.now()
        self.client.force_login(self.student_user)
        upcoming = self._exam(start_at=now + timedelta(hours=3), end_at=now + timedelta(hours=4))
        response = self._join(self._code(upcoming))
        self.assertRedirects(response, reverse('core:student_exam_entry', args=[upcoming]), fetch_redirect_response=False)
        entry = self.client.get(response['Location'])
        self.assertFalse(entry.context['can_enter'])
        self.assertGreater(entry.context['seconds_until_start'], 3 * 3600 - 60)  # countdown to the start
        self.client.post(response['Location'], {'accept_rules': '1'})
        self.assertContains(self.client.get(response['Location']), 'آزمون هنوز شروع نشده است')
        self.assertIsNone(self._start(upcoming))

        running = self._exam()
        response = self._join(self._code(running))
        self.client.post(response['Location'], {'accept_rules': '1'})
        attempt_id = self._start(running)
        self.assertTrue(attempt_id)
        # the code again during the attempt: straight back into it
        self.assertRedirects(self._join(self._code(running)), reverse('core:student_attempt', args=[attempt_id]), fetch_redirect_response=False)
        self.client.post(reverse('core:student_attempt_submit', args=[attempt_id]))
        # after submitting (one attempt): the entry page sends to the receipt
        entry = self.client.get(self._join(self._code(running))['Location'])
        self.assertRedirects(entry, reverse('core:student_attempt_receipt', args=[attempt_id]), fetch_redirect_response=False)

        closed = self._exam(start_at=now - timedelta(hours=1), end_at=now + timedelta(hours=1), last_entry_at=now - timedelta(minutes=30))
        entry = self.client.get(self._join(self._code(closed))['Location'])
        self.assertTrue(entry.context['entry_expired'])
        self.assertIsNone(self._start(closed))

        ended = self._exam(start_at=now - timedelta(hours=3), end_at=now - timedelta(hours=2))
        entry = self.client.get(self._join(self._code(ended))['Location'])
        self.assertTrue(entry.context['entry_expired'])

    def test_codes_that_do_not_lead_in(self):
        now = timezone.now()
        home = reverse('core:home')
        self.client.force_login(self.student_user)
        unpublished = self._exam(is_published=False, lifecycle_status='pending_approval')
        cancelled = self._exam(is_cancelled=True)
        for exam_id in (unpublished, cancelled):
            response = self._join(self._code(exam_id))
            self.assertTrue(response['Location'].startswith(home + '?join=not_found'))
            self.assertContains(self.client.get(response['Location']), f'آزمونی با کد {self._code(exam_id)} برای شما پیدا نشد')
            self.client.force_login(self.student_user)  # opening the home page signed out
        other_group = self._exam()
        with connection.cursor() as cursor:
            cursor.execute('UPDATE exam_assignments SET group_id = %s WHERE exam_id = %s', [self.group_out_id, other_group])
        self.assertIn('join=not_found', self._join(self._code(other_group))['Location'])
        self.assertIn('join=not_found', self._join('MQ-000000')['Location'])
        invalid = self._join('EX-8421')
        self.assertIn('join=invalid', invalid['Location'])
        self.assertContains(self.client.get(invalid['Location']), 'این کد آزمون درست نیست')
        self.assertIn('join=missing', self._join('')['Location'])

    def test_same_prefix_goes_to_the_students_exam(self):
        mine = self._exam()
        prefix = mine.replace('-', '')[:6]
        twin = f"{prefix}{uuid.uuid4().hex[6:8]}-{uuid.uuid4().hex[:4]}-4{uuid.uuid4().hex[:3]}-a{uuid.uuid4().hex[:3]}-{uuid.uuid4().hex[:12]}"
        _insert('exams', ['id', 'title', 'teacher_id', 'course_id', 'start_at', 'end_at', 'is_published', 'is_cancelled', 'lifecycle_status'],
                [twin, 'آزمون دیگر', self.teacher_out_id, self.course_out_id, timezone.now(), timezone.now() + timedelta(hours=1), True, False, 'published'])
        _insert('exam_assignments', ['id', 'exam_id', 'group_id'], [str(uuid.uuid4()), twin, self.group_out_id])
        self.client.force_login(self.student_user)
        self.assertRedirects(self._join(self._code(mine)), reverse('core:student_exam_entry', args=[mine]), fetch_redirect_response=False)

    def test_practice_exam_code_opens_the_practice_page(self):
        practice = self._exam(exam_mode='practice', max_attempts=0)
        self.client.force_login(self.student_user)
        self.assertRedirects(self._join(self._code(practice)), reverse('core:student_practice_detail', args=[practice]), fetch_redirect_response=False)

    def test_teacher_and_manager_see_the_code(self):
        exam_id = self._exam(title='آزمون کددار')
        code = self._code(exam_id)
        self.client.force_login(self.teacher_user)
        self.assertContains(self.client.get(reverse('core:teacher_exams')), code)
        created = self.client.post(reverse('core:teacher_exam_create'), {
            'title': 'آزمون تازه', 'course_id': self.course_in_id, 'group_ids': [self.group_in_id], 'question_ids': [self.single_id],
            'duration_minutes': '30', 'publish_choice': 'submit', 'start_at': '2026-12-10T16:00'}, follow=True)
        [(new_id,)] = self._rows("SELECT id FROM exams WHERE title = 'آزمون تازه'", [])
        self.assertContains(created, f'data-copy-code="{self._code(new_id)}"', count=2)  # the new exam's code card and row
        self.client.force_login(self.manager_user)
        self.assertContains(self.client.get(reverse('core:super_admin_exam_edit', args=[exam_id])), code)
        found = self.client.get(reverse('core:super_admin_exams'), {'q': code.lower()})
        self.assertContains(found, 'آزمون کددار')


class AttemptReceiptCodeTests(_EnforcedExamFixture):
    """«شناسه رسید»: یکتا، ثابت، از روی کد آزمون، در رسید و نتیجه‌ی دانشجو، و قابل جستجو برای استاد و مدیر."""

    PATTERN = r'^MQ-[0-9A-F]{6}-[23456789ABCDEFGHJKLMNPQRSTUVWXYZ]{6}$'

    def _submitted(self, exam_id=None, client=None):
        exam_id = exam_id or self._exam()
        client = client or self.client
        attempt_id = self._start(exam_id, client)
        client.post(reverse('core:student_attempt', args=[attempt_id]), {f'answer_{self.single_id}': '2'})
        client.post(reverse('core:student_attempt_submit', args=[attempt_id]))
        return exam_id, attempt_id

    def _receipt(self, attempt_id):
        return self._rows('SELECT receipt_code FROM exam_attempts WHERE id = %s', [attempt_id])[0][0]

    def test_submission_gets_a_lasting_receipt_shown_to_the_student(self):
        from apps.core.views import attempt_receipt_code, exam_access_code
        self.client.force_login(self.student_user)
        exam_id, attempt_id = self._submitted()
        code = self._receipt(attempt_id)
        self.assertRegex(code, self.PATTERN)
        self.assertTrue(code.startswith(exam_access_code(exam_id) + '-'))
        receipt = self.client.get(reverse('core:student_attempt_receipt', args=[attempt_id]))
        self.assertContains(receipt, code)
        self.assertNotContains(receipt, 'MQ-1405-027')
        self.assertContains(receipt, '۱۴۰')  # «زمان اتمام آزمون» in the Jalali calendar
        self.assertContains(self.client.get(reverse('core:student_result_detail', args=[attempt_id])), code)
        self.client.post(reverse('core:student_attempt_submit', args=[attempt_id]))  # a second «پایان آزمون»
        self.assertEqual((self._receipt(attempt_id), attempt_receipt_code(attempt_id)), (code, code))

    def test_no_receipt_before_submission(self):
        from apps.core.views import attempt_receipt_code
        self.client.force_login(self.student_user)
        attempt_id = self._start(self._exam())
        self.assertEqual((attempt_receipt_code(attempt_id), self._receipt(attempt_id)), ('', None))

    def test_unique_even_when_the_random_part_repeats(self):
        from django.db import IntegrityError, transaction
        from apps.core.views import attempt_receipt_code
        self.client.force_login(self.student_user)
        exam_id = self._exam(max_attempts=0)
        _exam, first = self._submitted(exam_id)
        second = self._start(exam_id)
        self.client.post(reverse('core:student_attempt', args=[second]), {f'answer_{self.single_id}': '2'})
        taken = self._receipt(first)
        with connection.cursor() as cursor:  # the database itself refuses a second attempt with the same receipt
            cursor.execute("UPDATE exam_attempts SET submitted_at = now(), status = 'submitted' WHERE id = %s", [second])
            with self.assertRaises(IntegrityError), transaction.atomic():
                cursor.execute('UPDATE exam_attempts SET receipt_code = %s WHERE id = %s', [taken, second])
        # the first draw repeats the existing receipt: a new one is drawn
        draws = iter(taken.split('-')[2] + 'KKKKKK')
        with mock.patch('apps.core.views.secrets.choice', side_effect=lambda alphabet: next(draws)):
            code = attempt_receipt_code(second)
        self.assertEqual(code, taken.rsplit('-', 1)[0] + '-KKKKKK')
        self.assertNotEqual(code, taken)

    def test_auto_submitted_and_failed_grading_attempts_get_one_too(self):
        from apps.core.exam_schedule import finalize_expired_attempts
        exam_id = self._exam(auto_submit_on_time_end=True)
        expired = str(uuid.uuid4())
        _insert('exam_attempts', ['id', 'exam_id', 'student_id', 'started_at', 'status'],
                [expired, exam_id, self.student_in_id, timezone.now() - timedelta(hours=1), 'in_progress'])
        finalize_expired_attempts()
        self.assertRegex(self._receipt(expired), self.PATTERN)
        self.client.force_login(self.student_user)
        attempt_id = self._start(self._exam())
        with mock.patch('apps.core.views.grade_attempt', side_effect=RuntimeError('grading failed')):
            self.client.post(reverse('core:student_attempt_submit', args=[attempt_id]))
        self.assertRegex(self._receipt(attempt_id), self.PATTERN)

    def test_typed_receipt_forms(self):
        from apps.core.views import normalize_receipt_code
        for typed in ('MQ-1A2B3C-7KQ4RZ', 'mq-1a2b3c-7kq4rz', ' MQ 1A2B3C 7KQ4RZ ', '1A2B3C7KQ4RZ', 'MQ-۱A۲B۳C-۷KQ۴RZ'):
            self.assertEqual(normalize_receipt_code(typed), 'MQ-1A2B3C-7KQ4RZ', typed)
        for typed in ('', 'MQ-1405-027-6532', 'MQ-1A2B3C', 'MQ-1A2B3C-7KQ4R0', "x' OR 1=1"):
            self.assertEqual(normalize_receipt_code(typed), '', typed)

    def test_teacher_and_manager_find_an_attempt_by_receipt(self):
        self.client.force_login(self.student_user)
        exam_id, attempt_id = self._submitted(self._exam(title='آزمون رسیددار', max_attempts=0))
        _exam, other_attempt = self._submitted(exam_id)
        code, other_code = self._receipt(attempt_id), self._receipt(other_attempt)
        self.client.force_login(self.teacher_user)
        page = self.client.get(reverse('core:teacher_results'), {'receipt': code.lower()})
        self.assertEqual(str(page.context['report_exam']['id']), exam_id)
        self.assertEqual([str(row['id']) for row in page.context['report']['rows']], [attempt_id])
        self.assertContains(page, code)
        self.assertNotContains(page, other_code)
        full = self.client.get(reverse('core:teacher_results'), {'exam': exam_id})
        self.assertContains(full, code)
        self.assertContains(full, other_code)
        self.assertContains(self.client.get(reverse('core:teacher_results'), {'receipt': 'MQ-000000-KKKKKK'}),
                            'رسیدی با شناسه‌ی MQ-000000-KKKKKK در آزمون‌های شما پیدا نشد')
        self.assertContains(self.client.get(reverse('core:teacher_results'), {'receipt': 'abc'}), 'شناسه‌ی رسید درست نیست')
        outsider = get_user_model().objects.create_user(username='teacher_out_scope', email='t_out@example.com', password='x')
        self.client.force_login(outsider)  # another teacher's exam: not found, nothing shown
        self.assertContains(self.client.get(reverse('core:teacher_results'), {'receipt': code}), 'در آزمون‌های شما پیدا نشد')
        self.client.force_login(self.manager_user)
        self.assertContains(self.client.get(reverse('core:super_admin_exams'), {'q': code}), 'آزمون رسیددار')


class ExamCodeStaffJoinTests(_EnforcedExamFixture):
    """کد آزمون برای همه‌ی نقش‌ها: استاد مالک یا عامل آزمون، مدیر آموزشی در محدوده‌اش و مدیر سیستم، هرکدام در پنل خودش."""

    def _join(self, exam_id):
        from apps.core.views import exam_access_code
        return self.client.get(reverse('core:exam_join'), {'code': exam_access_code(exam_id)})

    def _lands(self, exam_id, expected):
        response = self._join(exam_id)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], expected)
        self.assertEqual(self.client.get(response['Location']).status_code, 200)

    def test_teacher_owner_lands_on_edit_monitoring_or_results(self):
        now = timezone.now()
        self.client.force_login(self.teacher_user)
        draft = self._exam(is_published=False, lifecycle_status='draft')
        self._lands(draft, reverse('core:teacher_exam_edit', args=[draft]))
        running = self._exam()
        self._lands(running, f"{reverse('core:teacher_monitoring')}?exam={running}")
        ended = self._exam(start_at=now - timedelta(hours=3), end_at=now - timedelta(hours=2))
        self._lands(ended, f"{reverse('core:teacher_results')}?exam={ended}")

    def test_guest_teacher_signs_in_and_lands_in_the_teacher_panel(self):
        from apps.core.views import exam_access_code
        exam_id = self._exam()
        login_url = self._join(exam_id)['Location']
        next_url = self.client.get(login_url).context['next']
        self.teacher_user.set_password('Pass@12345')
        self.teacher_user.save()
        self.client.post(login_url, {'username': self.teacher_user.username, 'password': 'Pass@12345', 'next': next_url})
        self.assertEqual(self.client.get(next_url)['Location'], f"{reverse('core:teacher_monitoring')}?exam={exam_id}")
        self.assertIn(exam_access_code(exam_id), next_url)

    def test_staff_teacher_sees_reports_and_others_are_refused(self):
        exam_id = self._exam(is_published=False, lifecycle_status='draft')
        outsider = get_user_model().objects.create_user(username='teacher_out_scope', email='t_out@example.com', password='x')
        self.client.force_login(outsider)
        refused = self._join(exam_id)
        self.assertIn('join=not_found_staff', refused['Location'])
        self.assertContains(self.client.get(refused['Location']), 'در حساب شما پیدا نشد')
        self.client.force_login(outsider)  # opening the home page signed out
        _insert('exam_staff', ['id', 'exam_id', 'teacher_id', 'role'], [str(uuid.uuid4()), exam_id, self.teacher_out_id, 'co_grader'])
        self._lands(exam_id, f"{reverse('core:teacher_results')}?exam={exam_id}")  # not the owner: never the edit page

    def test_manager_in_scope_and_admin(self):
        mine = self._exam()
        self.client.force_login(self.manager_user)
        self._lands(mine, reverse('core:super_admin_exam_detail', args=[mine]))
        self.assertIn('join=not_found_staff', self._join(self.exam_out_id)['Location'])  # another unit's exam
        self.client.force_login(self.admin_user)
        self._lands(self.exam_out_id, reverse('core:super_admin_exam_detail', args=[self.exam_out_id]))


class WizardQuestionUsageCountTests(_EnforcedExamFixture):
    """ستون «تعداد استفاده» در جدول انتخاب سؤال ویزارد: در چند آزمون (لغونشده) آمده، هر آزمونی که باشد."""

    def test_usage_count_column(self):
        self._exam(title='آزمون یک')
        self._exam(title='آزمون دو')
        self._exam(title='آزمون لغوشده', is_cancelled=True)
        self.client.force_login(self.teacher_user)
        page = self.client.get(reverse('core:teacher_exam_create'))
        self.assertContains(page, '<th>تعداد استفاده</th>')
        offered = {str(q['id']): q for q in page.context['questions']}
        self.assertEqual(int(offered[self.single_id]['usage_count']), 2)
        self.assertContains(page, '<td data-usage-count>۲ آزمون</td>')


class AccountProfilePagesTests(_ScopedOrgFixture):
    """«پروفایل من» برای هر نقش: صفحه‌ی واقعی همان نقش، ذخیره‌ی واقعی و معتبرسنجی‌شده، رمز عبور، ورود دومرحله‌ای و نشست‌ها."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        User = get_user_model()
        cls.teacher_user = User.objects.create_user(username='teacher_in_scope', email='t_in@example.com', password='Old#Pass123')
        cls.student_user = User.objects.create_user(username='student_in_scope', email='s_in@example.com', password='x')
        cls.manager_user.set_password('Mgr#Pass123')
        cls.manager_user.save()

    def _profile(self, profile_id):
        with connection.cursor() as cursor:
            cursor.execute('SELECT first_name, last_name, full_name, email, phone, avatar_url FROM profiles WHERE id = %s', [profile_id])
            return cursor.fetchone()

    def _png(self, name='a.png'):
        from PIL import Image
        from django.core.files.uploadedfile import SimpleUploadedFile
        buffer = io.BytesIO()
        Image.new('RGB', (8, 8), 'red').save(buffer, 'PNG')
        return SimpleUploadedFile(name, buffer.getvalue(), content_type='image/png')

    def test_each_role_lands_on_its_own_account_page(self):
        url = reverse('core:profile')
        self.client.force_login(self.student_user)
        self.assertTrue(self.client.get(url)['Location'].startswith(reverse('core:student_settings')))
        self.client.force_login(self.teacher_user)
        self.assertEqual(self.client.get(url)['Location'], f"{reverse('core:teacher_settings')}?tab=personal")
        self.assertEqual(self.client.get(url, {'section': 'security'})['Location'], f"{reverse('core:teacher_settings')}?tab=security")
        self.assertEqual(self.client.get(reverse('core:teacher_security'))['Location'], f"{reverse('core:teacher_settings')}?tab=security")
        self.client.force_login(self.manager_user)
        page = self.client.get(url)
        self.assertTemplateUsed(page, 'super_admin/profile.html')
        self.assertEqual(page.context['role_label'], 'مدیر آموزشی')
        self.assertEqual(page.context['unit_label'], 'واحد تحت مدیریت')
        self.assertNotContains(self.client.get(url, {'section': 'security'}), 'در حال توسعه')
        self.client.force_login(self.admin_user)
        page = self.client.get(url, {'section': 'edit'})
        self.assertEqual(page.context['role_label'], 'مدیر سیستم')
        self.assertNotContains(page, 'ذخیره نمی‌شود')

    def test_manager_saves_validated_details(self):
        self.client.force_login(self.manager_user)
        url = reverse('core:profile')
        post = {'form': 'profile', 'first_name': ' سارا ', 'last_name': 'احمدی', 'email': 'Sara.Ahmadi@Example.com', 'phone': '۰۹۱۲ ۳۴۵ ۶۷۸۹'}
        self.client.post(url, post)
        self.assertEqual(self._profile(self.manager_id)[:5], ('سارا', 'احمدی', 'سارا احمدی', 'sara.ahmadi@example.com', '09123456789'))
        self.manager_user.refresh_from_db()
        self.assertEqual((self.manager_user.first_name, self.manager_user.email), ('سارا', 'sara.ahmadi@example.com'))
        self.assertEqual(self.client.get(url).status_code, 200)  # still the same account after the email change
        for bad, message in ((dict(email='not-an-email'), 'ایمیل واردشده معتبر نیست'),
                             (dict(email='admin_test@example.com'), 'این ایمیل برای حساب دیگری ثبت شده است'),
                             (dict(phone='12345'), 'شماره همراه باید ۱۱ رقم'),
                             (dict(first_name=''), 'نام را وارد کنید')):
            response = self.client.post(url, {**post, **bad}, follow=True)
            self.assertContains(response, message)
        self.assertEqual(self._profile(self.manager_id)[3], 'sara.ahmadi@example.com')  # nothing saved by the bad posts

    def test_avatar_must_be_a_real_image(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        self.client.force_login(self.admin_user)
        post = {'form': 'profile', 'first_name': 'مدیر', 'last_name': 'سیستم', 'email': 'admin_test@example.com'}
        fake = SimpleUploadedFile('x.png', b'<script>alert(1)</script>', content_type='image/png')
        self.assertContains(self.client.post(reverse('core:profile'), {**post, 'avatar': fake}, follow=True), 'فرمت تصویر')
        self.assertFalse(self._profile(self.admin_id)[5])
        from pathlib import Path
        with self.settings(MEDIA_ROOT=Path(tempfile.mkdtemp())):
            self.client.post(reverse('core:profile'), {**post, 'avatar': self._png()})
        self.assertRegex(self._profile(self.admin_id)[5] or '', r'/avatars/.+\.png$')

    def test_manager_two_factor_and_sessions(self):
        from apps.core import account_security
        if not account_security.TWO_FACTOR_AVAILABLE:
            self.skipTest('pyotp/qrcode not installed')
        import pyotp
        self.client.force_login(self.manager_user)
        url = reverse('core:profile')
        self.client.post(url, {'form': 'security', 'security_action': 'totp_start'})
        page = self.client.get(url, {'section': 'security'})
        secret = page.context['two_factor']['setup_secret'].replace(' ', '')
        self.client.post(url, {'form': 'security', 'security_action': 'totp_confirm', 'totp_code': pyotp.TOTP(secret).now(),
                               'security_password': 'Mgr#Pass123'})
        self.assertTrue(account_security.two_factor_enabled(self.manager_user))
        self.assertEqual(len(self.client.get(url, {'section': 'security'}).context['sessions']), 1)
        self.assertContains(self.client.post(url, {'form': 'security', 'security_action': 'drop_tables'}, follow=True), 'درخواست نامعتبر است')

    def test_teacher_changes_password_on_the_security_tab(self):
        self.client.force_login(self.teacher_user)
        url = reverse('core:teacher_settings')
        post = {'settings_tab': 'security', 'security_action': 'password_change', 'old_password': 'wrong',
                'new_password1': 'Brand#New456', 'new_password2': 'Brand#New456'}
        self.assertContains(self.client.post(url, post), 'رمز عبور فعلی')  # wrong current password
        response = self.client.post(url, {**post, 'old_password': 'Old#Pass123'})
        self.assertEqual(response['Location'], f'{url}?tab=security&done=password_change')
        self.teacher_user.refresh_from_db()
        self.assertTrue(self.teacher_user.check_password('Brand#New456'))
        self.assertContains(self.client.get(response['Location']), 'رمز عبور تغییر کرد')


class TeacherPreferencesTakeEffectTests(_EnforcedExamFixture):
    """تنظیمات استاد واقعاً کار می‌کنند: پیش‌فرض آزمون، بانک سؤال، تصحیح، حریم خصوصی، تقویم، پوسته و کانال‌های اعلان."""

    def _set_prefs(self, **values):
        from apps.core.views import _teacher_settings_key, _teacher_settings_payload
        payload = {**_teacher_settings_payload(self.teacher_in_id), **values}
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO system_settings (key, value, description) VALUES (%s, %s, 'test') "
                'ON CONFLICT(key) DO UPDATE SET value = excluded.value',
                [_teacher_settings_key(self.teacher_in_id), json.dumps(payload, ensure_ascii=False)],
            )

    def test_settings_page_saves_and_new_exam_starts_from_them(self):
        self.client.force_login(self.teacher_user)
        self.client.post(reverse('core:teacher_settings'), {
            'settings_tab': 'exam', 'default_exam_duration': '45', 'default_attempts': '2', 'question_order': 'fixed',
            'negative_marking': 'on', 'result_release': 'instant', 'show_correct_answer': 'on', 'show_result_after_publish': 'on',
            'bank_default_structure': 'independent', 'bank_default_difficulty': 'hard', 'sharing_mode': 'private',
            'essay_grading_default': 'rubric', 'rounding': 'two_decimal', 'text_feedback': 'on'})
        fields = self.client.get(reverse('core:teacher_exam_create')).context['wizard_initial']['fields']
        self.assertEqual(fields, {'duration_minutes': '45', 'max_attempts': '2', 'shuffle_questions': False, 'negative_marking': True,
                                  'score_display_mode': 'immediate', 'correct_answer_display_mode': 'immediate', 'correction_mode': 'manual'})
        page = self.client.get(reverse('core:teacher_question_create'), {'type': 'single'})
        self.assertEqual(page.context['qf']['difficulty'], 'hard')
        self.assertFalse(page.context['question_autosave'])  # not posted: switched off
        self.assertNotContains(page, 'data-autosave-url')
        self._set_prefs(question_autosave=True, auto_grade_objective=True, show_result_after_publish=False, show_correct_answer=False)
        fields = self.client.get(reverse('core:teacher_exam_create')).context['wizard_initial']['fields']
        self.assertEqual((fields['correction_mode'], fields['score_display_mode'], fields['correct_answer_display_mode']),
                         ('auto_then_manual', 'manual', 'manual'))
        self.assertContains(self.client.get(reverse('core:teacher_question_create'), {'type': 'single'}), 'data-autosave-url')

    def test_sharing_and_auto_archive(self):
        from apps.core.teacher_preferences import archive_stale_drafts, share_new_question
        self._set_prefs(sharing_mode='department', auto_archive=True)
        with connection.cursor() as cursor:
            cursor.execute('UPDATE questions SET is_published = true WHERE id = %s', [self.single_id])
        share_new_question(self.teacher_in_id, self.single_id)
        self.assertIsNotNone(self._rows('SELECT shared_at FROM questions WHERE id = %s', [self.single_id])[0][0])
        old_draft = str(uuid.uuid4())
        _insert('questions', ['id', 'teacher_id', 'course_id', 'text', 'type', 'is_published', 'default_points', 'updated_at'],
                [old_draft, self.teacher_in_id, self.course_in_id, 'پیش‌نویس قدیمی', 'single', False, 1, timezone.now() - timedelta(days=120)])
        self.assertEqual(archive_stale_drafts(), [old_draft])
        self.assertIsNone(self._rows('SELECT archived_at FROM questions WHERE id = %s', [self.single_id])[0][0])

    def _essay_answer(self, **exam):
        exam_id = self._exam(**exam)
        attempt_id, answer_id = str(uuid.uuid4()), str(uuid.uuid4())
        _insert('exam_attempts', ['id', 'exam_id', 'student_id', 'started_at', 'submitted_at', 'status'],
                [attempt_id, exam_id, self.student_in_id, timezone.now(), timezone.now(), 'submitted'])
        _insert('attempt_answers', ['id', 'attempt_id', 'question_id', 'answer', 'needs_manual_grading', 'grader_feedback'],
                [answer_id, attempt_id, self.essay_id, json.dumps({'value': 'پاسخ'}), True, 'بازخورد قبلی'])
        return exam_id, answer_id

    def test_grading_follows_the_teachers_rules(self):
        self._set_prefs(rounding='integer', text_feedback=False, lock_score_after_publish=True)
        exam_id, answer_id = self._essay_answer()
        self.client.force_login(self.teacher_user)
        url = reverse('core:teacher_grading_detail', args=[answer_id])
        page = self.client.get(url)
        self.assertNotContains(page, 'name="feedback"')
        self.assertContains(page, 'step="1"')
        self.client.post(url, {'score': '1.6', 'feedback': 'نباید ثبت شود'})
        self.assertEqual(self._rows('SELECT points_awarded, grader_feedback FROM attempt_answers WHERE id = %s', [answer_id])[0],
                         (Decimal('2.00'), 'بازخورد قبلی'))
        with connection.cursor() as cursor:
            cursor.execute('UPDATE exams SET results_published_at = now() WHERE id = %s', [exam_id])
        self.assertContains(self.client.post(url, {'score': '0'}, follow=True), 'قفل است')
        self.assertEqual(self._rows('SELECT points_awarded FROM attempt_answers WHERE id = %s', [answer_id])[0][0], Decimal('2.00'))

    def test_what_students_see_of_their_teacher(self):
        with connection.cursor() as cursor:
            cursor.execute("UPDATE teacher_profiles SET display_name = 'دکتر الف', bio = 'متخصص فیزیولوژی', show_bio = true WHERE user_id = %s",
                           [self.teacher_in_id])
            cursor.execute("UPDATE profiles SET email = 'teacher@uni.ac.ir' WHERE id = %s", [self.teacher_in_id])
        self.client.force_login(self.student_user)
        self._set_prefs(show_name_to_students=True, show_email_in_class=True)
        page = self.client.get(reverse('core:student_classes'))
        for text in ('دکتر الف', 'متخصص فیزیولوژی', 'teacher@uni.ac.ir'):
            self.assertContains(page, text)
        self._set_prefs(show_name_to_students=True, show_email_in_class=False)
        self.assertNotContains(self.client.get(reverse('core:student_classes')), 'teacher@uni.ac.ir')
        self._set_prefs(show_name_to_students=False, show_email_in_class=True)
        page = self.client.get(reverse('core:student_classes'))
        self.assertContains(page, 'دکتر الف')
        self.assertNotContains(page, 'متخصص فیزیولوژی')
        self.assertNotContains(page, 'teacher@uni.ac.ir')

    def test_calendar_theme_and_console_options(self):
        from apps.core.templatetags.core_extras import CALENDAR, jalali_long
        moment = timezone.make_aware(datetime(2026, 12, 10, 16, 0))
        self.assertIn('آذر', jalali_long(moment))
        token = CALENDAR.set('gregorian')
        try:
            self.assertEqual(jalali_long(moment), 'پنجشنبه، ۱۰ دسامبر ۲۰۲۶')
        finally:
            CALENDAR.reset(token)
        self._exam(title='آزمون تقویم', start_at=moment, end_at=moment + timedelta(hours=1))
        self.client.force_login(self.teacher_user)
        self._set_prefs(date_format='میلادی', theme='dark', compact_tables=True, quick_help=True, show_page_meta=False)
        page = self.client.get(reverse('core:teacher_exams'))
        self.assertContains(page, 'دسامبر')
        self.assertNotContains(page, 'آذر ۱۴۰۵')
        self.assertEqual(page.context['teacher_ui']['theme'], 'dark')
        self.assertContains(page, 'راهنمای سریع')
        self.assertNotContains(page, 'میانبرهای صفحه‌کلید</h3>')
        self.assertIn('آذر', jalali_long(moment))  # other users' requests are not affected
        self._set_prefs(date_format='هجری شمسی', quick_help=False)
        page = self.client.get(reverse('core:teacher_exams'))
        self.assertContains(page, 'آذر')
        self.assertNotContains(page, 'id="tq-help-panel"')

    def test_notification_channels(self):
        from django.core import mail
        from apps.core.teacher_preferences import send_due_emails
        from apps.core.views import create_notification
        self._set_prefs(system_channel=False)
        create_notification(self.teacher_in_id, 'عنوان', 'متن')
        self.assertEqual(self._rows('SELECT is_read FROM notifications WHERE user_id = %s', [self.teacher_in_id]), [(True,)])
        self._set_prefs(system_channel=True, browser_channel=True, email_channel=True, delivery_mode='instant',
                        notification_email='alerts@uni.ac.ir', quiet_start='', quiet_end='')
        self.client.force_login(self.teacher_user)
        start = timezone.now() - timedelta(seconds=5)
        create_notification(self.teacher_in_id, 'آزمون تأیید شد', 'آزمون شما منتشر شد.')
        feed = self.client.get(reverse('core:teacher_notification_feed'), {'since': start.isoformat()}).json()
        self.assertEqual([item['title'] for item in feed['items']], ['آزمون تأیید شد'])
        with self.settings(EMAIL_HOST='smtp.example.com', EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend'):
            self.assertEqual(send_due_emails(), [])  # first run starts the cursor
            create_notification(self.teacher_in_id, 'پاسخ جدید برای تصحیح', 'یک پاسخ تشریحی منتظر شماست.')
            self.assertEqual(send_due_emails(now=timezone.now() + timedelta(seconds=15)), [self.teacher_in_id])
            self.assertEqual(mail.outbox[-1].to, ['alerts@uni.ac.ir'])
            self.assertIn('پاسخ جدید برای تصحیح', mail.outbox[-1].body)
            sent = len(mail.outbox)
            self.assertEqual(send_due_emails(now=timezone.now() + timedelta(seconds=16)), [])  # never twice
            now = timezone.localtime()
            self._set_prefs(quiet_start=(now - timedelta(hours=1)).strftime('%H:%M'), quiet_end=(now + timedelta(hours=1)).strftime('%H:%M'))
            create_notification(self.teacher_in_id, 'در ساعت سکوت', 'متن')
            self.assertEqual(send_due_emails(now=timezone.now() + timedelta(seconds=30)), [])
            self.assertEqual(len(mail.outbox), sent)  # held back during the quiet hours
            self.assertTrue(self.client.get(reverse('core:teacher_notification_feed')).json()['quiet'])


class ExamCodeAndAttemptFlowFixesTests(_EnforcedExamFixture):
    """کد آزمون برجسته و قابل کپی، ورود با کد بدون ماندن در حساب وقتی کد به جایی نمی‌رسد، و آزمون تمام‌شده که با بازگشت مرورگر باز نمی‌شود."""

    def _code(self, exam_id):
        from apps.core.views import exam_access_code
        return exam_access_code(exam_id)

    def test_unknown_code_is_refused_before_sign_in(self):
        response = self.client.get(reverse('core:exam_join'), {'code': 'MQ-000000'})
        self.assertIn('join=no_exam', response['Location'])
        self.assertContains(self.client.get(response['Location']), 'آزمونی با کد MQ-000000 وجود ندارد')

    def test_sign_in_made_for_a_code_that_fails_is_undone(self):
        exam_id = self._exam()
        with connection.cursor() as cursor:  # the exam is another group's: this student cannot take it
            cursor.execute('UPDATE exam_assignments SET group_id = %s WHERE exam_id = %s', [self.group_out_id, exam_id])
        code = self._code(exam_id)
        login_url = self.client.get(reverse('core:exam_join'), {'code': code})['Location']
        self.assertTrue(login_url.startswith(reverse('core:login')))
        self.student_user.set_password('Pass@12345')
        self.student_user.save()
        next_url = self.client.get(login_url).context['next']
        self.client.post(login_url, {'username': self.student_user.username, 'password': 'Pass@12345', 'next': next_url})
        refused = self.client.get(next_url)
        self.assertIn('join=not_found', refused['Location'])
        self.assertNotIn('_auth_user_id', self.client.session)  # signed out again
        self.assertTrue(self.client.get(reverse('core:exam_join'), {'code': code})['Location'].startswith(reverse('core:login')))

    def test_home_page_signs_out_any_account(self):
        for user in (self.student_user, self.teacher_user, self.manager_user, self.admin_user):
            self.client.force_login(user)
            self.assertEqual(self.client.get(reverse('core:home')).status_code, 200)
            self.assertNotIn('_auth_user_id', self.client.session)
        self.client.force_login(self.student_user)
        refused = self.client.get(reverse('core:exam_join'), {'code': 'MQ-000000'})
        self.assertIn('join=not_found', refused['Location'])
        self.assertContains(self.client.get(refused['Location']), 'برای شما پیدا نشد')  # the message still shows
        self.assertTrue(self.client.get(reverse('core:exam_join'), {'code': 'MQ-000000'})['Location'].startswith(reverse('core:home')))

    def test_finished_attempt_is_not_shown_again(self):
        self.client.force_login(self.student_user)
        exam_id = self._exam()
        attempt_id = self._start(exam_id)
        page = self.client.get(reverse('core:student_attempt', args=[attempt_id]))
        self.assertIn('no-store', page['Cache-Control'])
        self.client.post(reverse('core:student_attempt_submit', args=[attempt_id]))
        self.assertRedirects(self.client.get(reverse('core:student_attempt', args=[attempt_id])),
                             reverse('core:student_attempt_receipt', args=[attempt_id]), fetch_redirect_response=False)
        self.assertIn('no-store', self.client.get(reverse('core:student_exam_detail', args=[exam_id]))['Cache-Control'])

    def test_teacher_sees_the_new_exams_code_large_and_copyable(self):
        self.client.force_login(self.teacher_user)
        self.client.post(reverse('core:teacher_exam_create'), {
            'title': 'آزمون کد بزرگ', 'course_id': self.course_in_id, 'group_ids': [self.group_in_id], 'question_ids': [self.single_id],
            'duration_minutes': '30', 'publish_choice': 'submit', 'start_at': '2026-12-10T16:00'})
        [(exam_id,)] = self._rows("SELECT id FROM exams WHERE title = 'آزمون کد بزرگ'", [])
        code = self._code(exam_id)
        page = self.client.get(reverse('core:teacher_exams'), {'saved': str(exam_id)})
        self.assertContains(page, 'class="texams-saved"')
        self.assertContains(page, f'data-copy-code="{code}"', count=2)  # the card and the exam's row
        self.assertNotContains(self.client.get(reverse('core:teacher_exams'), {'saved': str(uuid.uuid4())}), 'class="texams-saved"')


class TeacherExamListActionLinksTests(_EnforcedExamFixture):
    """از لیست آزمون‌ها: «پایش زنده» برای آزمون در حال برگزاری و «نتایج و انتشار» برای آزمونی که تحویل یا پایان دارد."""

    def test_results_and_monitoring_links(self):
        now = timezone.now()
        running = self._exam(title='آزمون جاری')
        ended = self._exam(title='آزمون تمام‌شده', start_at=now - timedelta(hours=3), end_at=now - timedelta(hours=2))
        self.client.force_login(self.teacher_user)
        page = self.client.get(reverse('core:teacher_exams')).content.decode()
        self.assertIn(f"{reverse('core:teacher_monitoring')}?exam={running}", page)
        self.assertIn(f"{reverse('core:teacher_results')}?exam={ended}", page)
        self.assertNotIn(f"{reverse('core:teacher_results')}?exam={running}", page)  # nobody handed it in yet
        self.assertIn('data-latin-digits>MQ-', page)


class QuestionImportExcelTests(_EnforcedExamFixture):
    """ورود گروهی سؤال با فایل Excel (xlsx): بررسی ردیف‌ها، ثبت ردیف‌های درست و سطح دشواری فارسی."""

    def test_xlsx_rows_are_checked_then_saved(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from openpyxl import Workbook
        book = Workbook()
        sheet = book.active
        sheet.append(['نوع', 'متن سؤال', 'گزینه ۱', 'گزینه ۲', 'گزینه ۳', 'پاسخ صحیح', 'بارم', 'دشواری'])
        sheet.append(['تک‌گزینه‌ای', 'سؤال اکسل یک', 'الف', 'ب', 'ج', 2, 3, 'سخت'])
        sheet.append(['چندگزینه‌ای', 'سؤال اکسل دو', 'الف', 'ب', 'ج', '1,3', 2, 'آسان'])
        sheet.append(['تشریحی', 'سؤال اکسل سه', '', '', '', '', 5, 'متوسط'])
        sheet.append(['تک‌گزینه‌ای', 'سؤال خراب', 'الف', '', '', 7, 1, ''])
        buffer = io.BytesIO()
        book.save(buffer)
        self.client.force_login(self.teacher_user)
        url = reverse('core:teacher_question_bulk_import')
        preview = self.client.post(url, {'course_id': self.course_in_id, 'import_file': SimpleUploadedFile('q.xlsx', buffer.getvalue())})
        self.assertEqual(sum(1 for row in preview.context['import_rows'] if row.get('errors')), 1)
        self.client.post(url, {'action': 'confirm'})
        saved = self._rows("SELECT text, type, difficulty FROM questions WHERE text LIKE 'سؤال اکسل%%' ORDER BY text", [])
        self.assertEqual(saved, [('سؤال اکسل دو', 'multi', 'easy'), ('سؤال اکسل سه', 'essay', 'medium'), ('سؤال اکسل یک', 'single', 'hard')])


class QuestionImportScenariosTests(_EnforcedExamFixture):
    """ورود گروهی سؤال در همه‌ی حالت‌ها: فایل نمونه‌ی Excel، گزینه‌های خالی، بارم، شماره‌ی ردیف، تکراری، ستون‌های لازم و CSV ویندوز."""

    HEAD = ['نوع', 'متن سؤال', 'گزینه ۱', 'گزینه ۲', 'گزینه ۳', 'گزینه ۴', 'پاسخ صحیح', 'بارم', 'دشواری']

    def setUp(self):
        self.client.force_login(self.teacher_user)
        self.url = reverse('core:teacher_question_bulk_import')

    def _xlsx(self, rows, head=None):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from openpyxl import Workbook
        book = Workbook()
        sheet = book.active
        sheet.append(head or self.HEAD)
        for row in rows:
            sheet.append(row)
        buffer = io.BytesIO()
        book.save(buffer)
        return SimpleUploadedFile('q.xlsx', buffer.getvalue())

    def _preview(self, upload):
        page = self.client.post(self.url, {'course_id': self.course_in_id, 'import_file': upload})
        return page.context['import_error'], {row['number']: row['errors'] for row in page.context['import_rows'] or []}

    def _saved(self, pattern):
        return self._rows('SELECT text, type, difficulty, default_points, options, correct_answer FROM questions WHERE text LIKE %s ORDER BY text', [pattern])

    def test_sample_excel_file_round_trip(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        sample = self.client.get(self.url, {'template': '1'})
        self.assertTrue(sample['Content-Disposition'].endswith('.xlsx"'))
        self.assertTrue(self.client.get(self.url, {'template': 'csv'})['Content-Disposition'].endswith('.csv"'))
        error, rows = self._preview(SimpleUploadedFile('sample.xlsx', sample.content))
        self.assertEqual((error, len(rows), [r for r in rows.values() if r]), ('', 5, []))  # every sample row is valid
        before = self._rows('SELECT count(*) FROM questions WHERE teacher_id = %s', [self.teacher_in_id])[0][0]
        self.client.post(self.url, {'action': 'confirm'})
        self.assertEqual(self._rows('SELECT count(*) FROM questions WHERE teacher_id = %s', [self.teacher_in_id])[0][0], before + 5)
        error, rows = self._preview(SimpleUploadedFile('sample.xlsx', sample.content))  # the same file again
        self.assertTrue(rows and all('از قبل در بانک سؤال شما هست' in r[0] for r in rows.values()))

    def test_options_points_and_answers(self):
        error, rows = self._preview(self._xlsx([
            ['تک‌گزینه‌ای', 'آزمایشی گزینه خالی وسط', 'الف', '', 'ج', '', 3, '۲٫۵', 'آسان'],
            ['تک‌گزینه‌ای', 'آزمایشی پاسخ به گزینه خالی', 'الف', '', 'ج', '', 2, 1, ''],
            ['تک‌گزینه‌ای', 'آزمایشی دو پاسخ', 'الف', 'ب', '', '', '1,2', 1, ''],
            ['چندگزینه‌ای', 'آزمایشی چند پاسخ', 'الف', 'ب', 'ج', 'د', '۱،۴', 2, 'دشوار'],
            ['تشریحی', 'آزمایشی بارم نامعتبر', '', '', '', '', '', 'abc', ''],
            ['تشریحی', 'آزمایشی بارم صفر', '', '', '', '', '', 0, ''],
            ['تشریحی', 'آزمایشی بارم منفی', '', '', '', '', '', -1, ''],
            ['درست/نادرست', 'آزمایشی درست نادرست', '', '', '', '', 'غلط', 1, ''],
            ['پاسخ کوتاه', 'آزمایشی پاسخ کوتاه', '', '', '', '', 'H2O|آب', 1, ''],
        ]))
        self.assertEqual(error, '')
        self.assertEqual(rows[2], [])
        self.assertIn('گزینه 2', rows[3][0])
        self.assertIn('دقیقاً یک گزینه', rows[4][0])
        self.assertEqual(rows[5], [])
        for number in (6, 7, 8):
            self.assertIn('«بارم»', rows[number][0])
        self.client.post(self.url, {'action': 'confirm'})
        saved = {row[0]: row for row in self._saved('آزمایشی%')}
        self.assertEqual(set(saved), {'آزمایشی گزینه خالی وسط', 'آزمایشی چند پاسخ', 'آزمایشی درست نادرست', 'آزمایشی پاسخ کوتاه'})
        gap = saved['آزمایشی گزینه خالی وسط']
        options = gap[4] if isinstance(gap[4], list) else json.loads(gap[4])
        correct = json.loads(gap[5]) if isinstance(gap[5], str) else gap[5]
        correct_id = correct[0] if isinstance(correct, list) else correct
        self.assertEqual(([option.get('text') for option in options], gap[2], float(gap[3])), (['الف', 'ج'], 'easy', 2.5))
        self.assertEqual(next(o for o in options if str(o.get('id')) == str(correct_id)).get('text'), 'ج')  # «گزینه ۳» of the file
        self.assertEqual(saved['آزمایشی چند پاسخ'][2], 'hard')

    def test_row_numbers_duplicates_and_headers(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        error, rows = self._preview(self._xlsx([
            ['تشریحی', 'سؤال ردیف دو', '', '', '', '', '', 1, ''],
            [None] * 9,
            ['نوع غلط', 'سؤال ردیف چهار', '', '', '', '', '', 1, ''],
            ['تشریحی', 'سؤال ردیف دو', '', '', '', '', '', 1, ''],
        ]))
        self.assertEqual(sorted(rows), [2, 4, 5])  # the sheet's own row numbers, blank row 3 skipped
        self.assertIn('نوع سؤال نامعتبر', rows[4][0])
        self.assertIn('ردیف 2', rows[5][0])
        error, rows = self._preview(self._xlsx([['x', 'متن', '', '', '', '', '', 1, '']], head=['ستون', 'متن سؤال', 'a', 'b', 'c', 'd', 'پاسخ', 'بارم', 'د']))
        self.assertIn('ستون «نوع»', error)
        self.assertIn('ردیف اول', self._preview(self._xlsx([]))[0])
        self.assertIn('خوانده نشد', self._preview(SimpleUploadedFile('q.xlsx', b'not a zip'))[0])
        self.assertIn('Excel', self._preview(SimpleUploadedFile('q.pdf', b'x'))[0])

    def test_csv_from_excel_on_windows(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        text = 'نوع;متن سؤال;پاسخ صحیح\nتشریحی;سؤال کدگذاری ویندوز;\n'
        windows = text.replace('ی', 'ي').replace('ک', 'ك').encode('cp1256')
        error, rows = self._preview(SimpleUploadedFile('q.csv', windows))
        self.assertEqual((error, rows), ('', {2: []}))
        self.client.post(self.url, {'action': 'confirm'})
        self.assertEqual(self._saved('سؤال کدگذاری%')[0][0], 'سؤال کدگذاری ویندوز')  # Persian «ی» and «ک» again
        confirm_again = self.client.post(self.url, {'action': 'confirm'})  # a second click saves nothing more
        self.assertRedirects(confirm_again, reverse('core:teacher_questions'), fetch_redirect_response=False)
        self.assertEqual(len(self._saved('سؤال کدگذاری%')), 1)
