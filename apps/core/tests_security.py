"""Security regression tests (Auth.md, Hack.md): route protection sweep, role isolation, login throttle and audit
trail, client IP, cookies/headers, deployment checks and data retention."""
import uuid
from datetime import timedelta
from io import StringIO

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import connection
from django.test import RequestFactory, TestCase, override_settings
from django.urls import URLResolver, get_resolver, reverse
from django.utils import timezone

from . import auth_guard
from .checks import production_secrets_check
from .tests import _insert, _ScopedOrgFixture
from .views import client_ip

# Pages anyone may open without signing in.
PUBLIC_ROUTES = {'core:home', 'core:login', 'core:register'}
# Public routes that only redirect (sign-out, exam-code entry, the 2FA step without a pending sign-in).
PUBLIC_REDIRECTS = {'core:logout', 'core:exam_join', 'core:login_2fa'}


def _routes():
    def walk(patterns, namespace=None):
        for pattern in patterns:
            if isinstance(pattern, URLResolver):
                yield from walk(pattern.url_patterns, pattern.namespace or namespace)
            elif pattern.name and namespace == 'core':
                yield f'{namespace}:{pattern.name}', pattern

    for name, pattern in walk(get_resolver().url_patterns):
        kwargs = {}
        for key, converter in pattern.pattern.converters.items():
            kind = type(converter).__name__
            kwargs[key] = uuid.uuid4() if kind == 'UUIDConverter' else 1 if kind == 'IntConverter' else 'x'
        yield name, reverse(name, kwargs=kwargs)


def _events(username):
    with connection.cursor() as cursor:
        cursor.execute('SELECT event, ip_address FROM auth_events WHERE username = %s ORDER BY id', [username])
        return cursor.fetchall()


class AnonymousRouteSweepTests(TestCase):
    """Every route of the app, opened without signing in, either is one of the public pages or sends the visitor to
    the sign-in page (or refuses the method) — for GET and for POST."""

    def test_every_route_requires_sign_in(self):
        login = reverse('core:login')
        routes = list(_routes())
        self.assertGreater(len(routes), 150)
        for name, url in routes:
            for method in ('get', 'post'):
                response = getattr(self.client, method)(url)
                with self.subTest(route=name, method=method, status=response.status_code):
                    if name in PUBLIC_ROUTES:
                        self.assertLess(response.status_code, 500)
                    elif name in PUBLIC_REDIRECTS:
                        self.assertIn(response.status_code, (302, 405))
                    elif response.status_code == 302:
                        self.assertTrue(response['Location'].startswith(login), response['Location'])
                    else:
                        self.assertIn(response.status_code, (403, 404, 405))

    def test_django_admin_login_goes_through_the_app_login(self):
        response = self.client.get('/admin/login/?next=/admin/')
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response['Location'].startswith(reverse('core:login')))
        self.assertEqual(self.client.post('/admin/login/', {'username': 'a', 'password': 'b'}).status_code, 302)


class RoleIsolationSweepTests(_ScopedOrgFixture):
    """A signed-in student / teacher opening another role's pages gets no page (403/302/404), never a 200."""

    FOREIGN = {
        'student': ('core:super_admin_', 'core:exam_manager_', 'core:teacher_', 'core:institution_', 'core:assistant_'),
        'teacher': ('core:super_admin_', 'core:exam_manager_', 'core:student_', 'core:institution_'),
    }

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        User = get_user_model()
        cls.users = {
            'student': User.objects.create_user(username='student_in_scope', email='s_in@example.com', password='x'),
            'teacher': User.objects.create_user(username='teacher_in_scope', email='t_in@example.com', password='x'),
        }

    def test_no_foreign_role_page_opens(self):
        routes = list(_routes())
        for role, prefixes in self.FOREIGN.items():
            self.client.force_login(self.users[role])
            for name, url in routes:
                if not name.startswith(prefixes):
                    continue
                status = self.client.get(url).status_code
                with self.subTest(role=role, route=name):
                    self.assertNotEqual(status, 200)
                    self.assertLess(status, 500)


@override_settings(LOGIN_MAX_FAILED_PER_USER=3, LOGIN_MAX_FAILED_PER_IP=6, LOGIN_LOCK_MINUTES=15)
class LoginThrottleTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.user = User.objects.create_user(username='victim', email='victim@example.com', password='Right-Pass-123')
        _insert('profiles', ['id', 'full_name', 'username', 'email', 'status'],
                [str(uuid.uuid4()), 'قربانی', 'victim', 'victim@example.com', 'active'])

    def _login(self, password, username='victim', ip='10.0.0.1'):
        return self.client.post(reverse('core:login'), {'username': username, 'password': password}, REMOTE_ADDR=ip)

    def test_account_locks_after_failed_passwords_even_for_the_right_one(self):
        for _ in range(3):
            self._login('wrong')
        response = self._login('Right-Pass-123')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('_auth_user_id', self.client.session)
        self.assertContains(response, 'قفل شده است')
        self.assertEqual([event for event, _ in _events('victim')], ['login_failed'] * 3 + ['login_blocked'])

    def test_the_lock_ends_after_the_window(self):
        for _ in range(3):
            self._login('wrong')
        with connection.cursor() as cursor:
            cursor.execute('UPDATE auth_events SET created_at = %s', [timezone.now() - timedelta(minutes=16)])
        self.assertEqual(self._login('Right-Pass-123').status_code, 302)
        self.assertIn('_auth_user_id', self.client.session)

    def test_e_mail_and_letter_case_count_against_the_same_account(self):
        self._login('wrong', username='VICTIM')
        self._login('wrong', username='victim@example.com')
        self._login('wrong')
        self.assertEqual(auth_guard.failed_for_user('victim'), 3)
        self.assertEqual(auth_guard.lock_reason('victim'), 'user')

    def test_a_correct_password_resets_the_count(self):
        self._login('wrong')
        self._login('wrong')
        self.assertEqual(self._login('Right-Pass-123').status_code, 302)
        self.client.logout()
        self._login('wrong')
        self.assertEqual(auth_guard.failed_for_user('victim'), 1)

    def test_one_ip_trying_many_accounts_is_throttled(self):
        for index in range(6):
            self._login('wrong', username=f'guess{index}', ip='10.9.9.9')
        response = self._login('Right-Pass-123', ip='10.9.9.9')
        self.assertNotIn('_auth_user_id', self.client.session)
        self.assertContains(response, 'از این نشانی')
        self.assertEqual(self._login('Right-Pass-123', ip='10.0.0.2').status_code, 302)  # another address is unaffected

    def test_sign_in_and_sign_out_are_logged_with_time_and_ip(self):
        before = timezone.now()
        self._login('Right-Pass-123', ip='192.0.2.7')
        self.client.get(reverse('core:logout'), REMOTE_ADDR='192.0.2.8')
        with connection.cursor() as cursor:
            cursor.execute("SELECT event, ip_address, user_id, created_at FROM auth_events WHERE username = 'victim' ORDER BY id")
            rows = cursor.fetchall()
        self.assertEqual([(event, ip) for event, ip, _, _ in rows],
                         [('password_ok', '192.0.2.7'), ('login_success', '192.0.2.7'), ('logout', '192.0.2.8')])
        self.assertTrue(all(user_id == self.user.pk and created >= before for _, _, user_id, created in rows[1:]))


@override_settings(LOGIN_MAX_FAILED_PER_USER=3)
class DeletedAccountSignInTests(TestCase):
    """Teacher's report: an account was deleted, a new one made with the same e-mail, and signing in with it kept
    failing until «قفل شده … ۱۵ دقیقه». Every way of deleting a person removes the login too, a leftover login of an
    older delete is not handed to the new account, and a refusal for the account's state never counts as a wrong
    password."""

    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.admin_id = str(uuid.uuid4())
        _insert('profiles', ['id', 'full_name', 'username', 'email', 'status'], [cls.admin_id, 'مدیر', 'del_admin', 'del_admin@example.com', 'active'])
        _insert('user_roles', ['id', 'user_id', 'role'], [str(uuid.uuid4()), cls.admin_id, 'admin'])
        cls.admin = User.objects.create_user(username='del_admin', password='x')
        cls.unit = str(uuid.uuid4())
        _insert('org_units', ['id', 'name', 'type'], [cls.unit, 'دانشگاه', 'university'])
        cls.department = str(uuid.uuid4())
        _insert('org_units', ['id', 'name', 'type', 'parent_id'], [cls.department, 'بخش', 'department', cls.unit])

    def _login(self, username, password):
        self.client.logout()
        response = self.client.post(reverse('core:login'), {'username': username, 'password': password})
        signed_in = '_auth_user_id' in self.client.session
        self.client.logout()
        return response, signed_in

    def _create(self, kind, email):
        """The admin's «افزودن …» wizard with only the e-mail typed; returns the password it shows."""
        self.client.force_login(self.admin)
        url = reverse(f'core:super_admin_{kind}_create')
        self.client.post(url, {'step': '1', 'first_name': 'زهرا', 'last_name': 'حسنی', 'email': email, 'student_number': '4001'})
        if kind == 'manager':
            self.client.post(url, {'step': '2', 'manager_level': '3', 'title': 'x', 'access_type': 'selected_units', 'primary_scope_id': self.department})
        else:
            self.client.post(url, {'step': '2', 'org_unit_id': self.department})
        self.client.post(url, {'step': '3'})
        response = self.client.post(url, {'step': '4', 'confirm_final': '1', 'account_status': 'active'}, follow=True)
        self.client.logout()
        found = [m for m in (str(message) for message in response.context['messages']) if 'رمز عبور اولیه' in m]
        self.assertTrue(found, f'no password shown for the new {kind}')
        return found[0].rsplit(' ', 1)[-1]

    def _profile_id(self, email):
        with connection.cursor() as cursor:
            cursor.execute('SELECT id FROM profiles WHERE email = %s', [email])
            return str(cursor.fetchone()[0])

    def test_deactivated_account_is_told_it_is_inactive(self):
        """User's report: an account the admin made «غیرفعال» got «نام کاربری یا رمز عبور درست نیست»."""
        for kind in ('teacher', 'student', 'manager'):
            email = f'off-{kind}@uni.ac.ir'
            with self.subTest(kind=kind):
                password = self._create(kind, email)
                self.client.force_login(self.admin)
                self.client.post(reverse('core:super_admin_toggle_account_status', args=[kind, self._profile_id(email)]),
                                 {'action': 'deactivate'})
                for typed in (email, email.upper()):
                    for _ in range(4):  # more than LOGIN_MAX_FAILED_PER_USER: never locks
                        response, signed_in = self._login(typed, password)
                        self.assertFalse(signed_in)
                        self.assertContains(response, 'حساب شما غیرفعال است')
                        self.assertNotContains(response, 'نام کاربری یا رمز عبور درست نیست')
                response, _ = self._login(email, 'wrong-password')  # a wrong password doesn't reveal the state
                self.assertContains(response, 'نام کاربری یا رمز عبور درست نیست')
                self.assertNotContains(response, 'غیرفعال است')
                self.client.force_login(self.admin)
                self.client.post(reverse('core:super_admin_toggle_account_status', args=[kind, self._profile_id(email)]),
                                 {'action': 'activate'})
                self.assertTrue(self._login(email, password)[1])

    def test_delete_and_recreate_with_the_same_e_mail_through_every_delete_button(self):
        cases = [
            ('teacher', lambda pid: self.client.post(reverse('core:super_admin_delete_account', args=['teacher', pid]), {'mode': 'only'})),
            ('student', lambda pid: self.client.post(reverse('core:super_admin_delete_account', args=['student', pid]), {'mode': 'all'})),
            ('manager', lambda pid: self.client.post(reverse('core:super_admin_delete_account', args=['manager', pid]), {'mode': 'only'})),
            ('teacher', lambda pid: self.client.post(reverse('core:super_admin_teachers'), {'teacher_action': 'delete', 'teacher_id': pid},
                                                     HTTP_X_REQUESTED_WITH='XMLHttpRequest')),
            ('student', lambda pid: self.client.post(reverse('core:super_admin_students'), {'student_action': 'delete', 'student_id': pid},
                                                     HTTP_X_REQUESTED_WITH='XMLHttpRequest')),
            ('manager', lambda pid: self.client.post(reverse('core:super_admin_academic_managers'), {'manager_action': 'delete', 'manager_id': pid},
                                                     HTTP_X_REQUESTED_WITH='XMLHttpRequest')),
        ]
        for index, (kind, delete) in enumerate(cases):
            email = f'same-{index}@uni.ac.ir'
            with self.subTest(kind=kind, button=index):
                first = self._create(kind, email)
                self.assertTrue(self._login(email, first)[1])  # it has worked (sign-in history, audit rows)
                self.client.force_login(self.admin)
                response = delete(self._profile_id(email))
                self.assertLess(response.status_code, 400)
                self.assertFalse(get_user_model().objects.filter(username=email).exists())
                self.assertEqual(_events_count(email, 'account_reset'), 2)  # password set, login removed
                second = self._create(kind, email)
                self.assertFalse(self._login(email, first)[1])
                response, signed_in = self._login(email, second)
                self.assertTrue(signed_in)
                self.assertEqual(response.status_code, 302)

    def test_a_leftover_login_of_an_older_delete_is_not_reused(self):
        from apps.core import account_security
        User = get_user_model()
        email = 'leftover@uni.ac.ir'
        old = User.objects.create_user(username=email, password='Old-Pass-123')
        old.date_joined = timezone.now() - timedelta(days=30)
        old.save()
        with connection.cursor() as cursor:  # the old owner had turned on the authenticator
            cursor.execute('INSERT INTO user_two_factor (user_id, secret, enabled) VALUES (%s, %s, %s)', [old.pk, 'JBSWY3DPEHPK3PXP', True])
        for _ in range(3):
            self._login(email, 'wrong')  # the old account was locked when it was deleted
        new_password = self._create('teacher', email)
        self.assertFalse(self._login(email, 'Old-Pass-123')[1])
        self.assertFalse(account_security.two_factor_enabled(User.objects.get(username=email)))
        self.assertTrue(self._login(email, new_password)[1])

    def test_pending_registration_is_explained_and_never_locks(self):
        self.client.post(reverse('core:register'), {'full_name': 'سارا احمدی', 'email': 'pending@uni.ac.ir',
                                                    'password': 'Pending-Pass-98', 'role': 'student'})
        for _ in range(5):
            response, signed_in = self._login('pending@uni.ac.ir', 'Pending-Pass-98')
            self.assertFalse(signed_in)
            self.assertContains(response, 'بررسی نشده')
            self.assertNotContains(response, 'رمز عبور درست نیست')
        username = get_user_model().objects.get(email='pending@uni.ac.ir').username
        self.assertEqual(auth_guard.lock_reason(username), '')
        self.client.force_login(self.admin)
        self.client.post(reverse('core:super_admin_toggle_account_status', args=['student', self._profile_id('pending@uni.ac.ir')]),
                         {'action': 'activate'})
        self.assertTrue(self._login('pending@uni.ac.ir', 'Pending-Pass-98')[1])

    def test_re_registering_an_e_mail_whose_account_was_deleted_long_ago(self):
        User = get_user_model()
        User.objects.create_user(username='oldname', email='again@uni.ac.ir', password='Old-Pass-123')  # no profile left
        self.client.post(reverse('core:register'), {'full_name': 'سارا احمدی', 'email': 'again@uni.ac.ir',
                                                    'password': 'Again-Pass-98', 'role': 'student'})
        self.assertFalse(User.objects.filter(username='oldname').exists())
        self.assertEqual(User.objects.filter(email__iexact='again@uni.ac.ir').count(), 1)

    def test_a_login_without_any_account_cannot_sign_in(self):
        get_user_model().objects.create_user(username='ghost', password='Ghost-Pass-123')
        response, signed_in = self._login('ghost', 'Ghost-Pass-123')
        self.assertFalse(signed_in)
        self.assertContains(response, 'حذف شده است')
        self.assertEqual(auth_guard.failed_for_user('ghost'), 0)

    def test_wizard_account_with_its_own_username_signs_in_with_its_e_mail(self):
        self.client.force_login(self.admin)
        url = reverse('core:super_admin_teacher_create')
        self.client.post(url, {'step': '1', 'first_name': 'زهرا', 'last_name': 'حسنی', 'email': 'own@uni.ac.ir'})
        self.client.post(url, {'step': '2', 'org_unit_id': self.department})
        self.client.post(url, {'step': '3'})
        response = self.client.post(url, {'step': '4', 'username': 'zahra_own', 'confirm_final': '1', 'account_status': 'active'}, follow=True)
        password = [str(m) for m in response.context['messages'] if 'رمز عبور اولیه' in str(m)][0].rsplit(' ', 1)[-1]
        self.assertTrue(self._login('own@uni.ac.ir', password)[1])
        self.assertTrue(self._login('zahra_own', password)[1])


def _events_count(username, event):
    with connection.cursor() as cursor:
        cursor.execute('SELECT COUNT(*) FROM auth_events WHERE username = %s AND event = %s', [username.lower(), event])
        return cursor.fetchone()[0]


class ClientIpTests(TestCase):
    def _request(self, forwarded=None, remote='127.0.0.1'):
        extra = {'REMOTE_ADDR': remote}
        if forwarded is not None:
            extra['HTTP_X_FORWARDED_FOR'] = forwarded
        return RequestFactory().get('/', **extra)

    def test_a_forged_left_entry_is_ignored(self):
        self.assertEqual(client_ip(self._request('6.6.6.6, 203.0.113.5')), '203.0.113.5')
        self.assertEqual(client_ip(self._request('203.0.113.5')), '203.0.113.5')
        self.assertEqual(client_ip(self._request()), '127.0.0.1')

    @override_settings(TRUSTED_PROXY_COUNT=0)
    def test_without_a_trusted_proxy_the_header_is_ignored(self):
        self.assertEqual(client_ip(self._request('6.6.6.6')), '127.0.0.1')


class CookieAndHeaderTests(TestCase):
    def test_cookie_and_header_settings(self):
        self.assertTrue(settings.SESSION_COOKIE_HTTPONLY)
        self.assertTrue(settings.CSRF_COOKIE_HTTPONLY)
        self.assertEqual(settings.SESSION_COOKIE_SAMESITE, 'Lax')
        self.assertEqual(settings.CSRF_COOKIE_SAMESITE, 'Lax')
        self.assertEqual(settings.X_FRAME_OPTIONS, 'DENY')
        self.assertTrue(settings.SECURE_CONTENT_TYPE_NOSNIFF)
        self.assertIn(settings.PASSWORD_HASHERS[0].rsplit('.', 1)[-1], ('PBKDF2PasswordHasher', 'Argon2PasswordHasher'))

    def test_security_headers(self):
        response = self.client.get(reverse('core:login'))
        self.assertIn("frame-ancestors 'none'", response['Content-Security-Policy'])
        self.assertIn("form-action 'self'", response['Content-Security-Policy'])
        self.assertIn('camera=(self)', response['Permissions-Policy'])
        self.assertEqual(response['X-Frame-Options'], 'DENY')
        self.assertEqual(response['X-Content-Type-Options'], 'nosniff')

    def test_demo_passwords_are_not_on_the_live_login_page(self):
        response = self.client.get(reverse('core:login'))  # tests run with DEBUG off, like production
        self.assertNotContains(response, 'data-password')
        with self.settings(DEBUG=True):
            self.assertContains(self.client.get(reverse('core:login')), 'data-password')

    def test_signed_in_pages_are_not_stored(self):
        user = get_user_model().objects.create_user(username='someone', password='x')
        self.client.force_login(user)
        response = self.client.get(reverse('core:dashboard'))
        self.assertIn('no-store', response['Cache-Control'])

    def test_session_cookie_flags_on_sign_in(self):
        get_user_model().objects.create_user(username='flags', password='Right-Pass-123')
        _insert('profiles', ['id', 'full_name', 'username', 'email', 'status'],
                [str(uuid.uuid4()), 'کوکی', 'flags', 'flags@example.com', 'active'])
        self.client.post(reverse('core:login'), {'username': 'flags', 'password': 'Right-Pass-123'})
        cookie = self.client.cookies[settings.SESSION_COOKIE_NAME]
        self.assertTrue(cookie['httponly'])
        self.assertEqual(cookie['samesite'], 'Lax')


class DeploymentCheckTests(TestCase):
    @override_settings(DEBUG=False, SECRET_KEY='django-insecure-local-development-only',
                       SESSION_COOKIE_SECURE=True, CSRF_COOKIE_SECURE=True)
    def test_placeholder_secret_key_fails_in_production(self):
        self.assertEqual([problem.id for problem in production_secrets_check(None)], ['core.S001'])

    @override_settings(DEBUG=False, SECRET_KEY='k8$Zq!2vR#pL9wX@4mN&7tY^1bC*6hJ%3fG(0dS)eA_uI+oP=', SESSION_COOKIE_SECURE=True,
                       CSRF_COOKIE_SECURE=True)
    def test_real_secret_key_passes(self):
        self.assertEqual(production_secrets_check(None), [])


class RetentionTests(TestCase):
    @override_settings(AUTH_EVENTS_RETENTION_DAYS=30)
    def test_purge_removes_only_expired_sign_in_rows(self):
        auth_guard.record('login_failed', username='old')
        auth_guard.record('login_failed', username='new')
        with connection.cursor() as cursor:
            cursor.execute("UPDATE auth_events SET created_at = %s WHERE username = 'old'", [timezone.now() - timedelta(days=31)])
        out = StringIO()
        call_command('purge_expired_data', '--dry-run', stdout=out)
        self.assertIn('would delete 1 auth_events', out.getvalue())
        self.assertEqual(len(_events('old')), 1)
        call_command('purge_expired_data', stdout=StringIO())
        self.assertEqual(_events('old'), [])
        self.assertEqual(len(_events('new')), 1)
