"""«تنظیمات سامانه» → «تنظیمات عمومی» (system_settings.py) and the exam hub's «تنظیمات» / «موارد نیازمند بررسی» forms:
only changed settings are saved and reported, option settings refuse values outside their lists, the IP restriction
is enforced without shutting out the admin who sets it, and the logo upload is checked and shown as the brand logo."""
import io
import json
import shutil
import tempfile

from django.contrib.messages import get_messages
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from django.test import TestCase

from .tests import _ScopedOrgFixture


def _messages(response):
    return [str(m) for m in get_messages(response.wsgi_request)]


class GeneralSettingsTests(_ScopedOrgFixture):
    def setUp(self):
        from . import system_settings

        system_settings.forget_ip_rule()
        self.addCleanup(system_settings.forget_ip_rule)
        self.url = reverse('core:super_admin_settings')
        self.client.force_login(self.admin_user)

    def _page(self):
        return self.client.get(self.url, {'tab': 'other'})

    def _form_values(self):
        """What the «تنظیمات عمومی» form posts when nothing is touched."""
        lookup = self._page().context['settings_lookup']
        data = {'settings_action': 'bulk_save'}
        for key, item in lookup.items():
            value = item['value']
            if item['type'] == 'boolean':
                value = 'on' if value else 'off'
            data[f'settings_{key}'] = value
        return data

    def _save(self, **changes):
        data = self._form_values()
        data.update({f'settings_{key}': value for key, value in changes.items()})
        return self.client.post(self.url, data)

    def _stored(self, key):
        from .views import erd_setting

        return erd_setting(key)

    def _log_count(self):
        from .views import erd_row

        return erd_row("SELECT COUNT(*) AS n FROM activity_audit_log WHERE action = 'system_settings_bulk_updated'")['n']

    def test_unchanged_form_saves_nothing(self):
        before = self._log_count()
        response = self._save()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(_messages(response), ['تغییری ثبت نشد؛ مقدارها همان مقادیر ذخیره‌شده‌اند.'])
        self.assertEqual(self._log_count(), before)
        page = self._page()
        self.assertContains(page, 'data-dirty-form')
        self.assertContains(page, 'data-dirty-submit')
        self.assertContains(page, 'data-dirty-reset')
        self.assertContains(page, 'هنوز تغییری در تنظیمات ثبت نشده است.')

    def test_only_changed_settings_are_saved_and_listed(self):
        response = self._save(primary_color='#7c3aed', session_timeout_minutes='45')
        self.assertEqual(_messages(response), ['2 تنظیم ذخیره شد: «زمان انقضای جلسه»، «رنگ اصلی سامانه».'])
        self.assertEqual(self._stored('primary_color'), '#7C3AED')
        self.assertEqual(self._stored('session_timeout_minutes'), 45)
        self.assertIsNone(self._stored('site_name'))  # untouched settings are not written
        page = self._page()
        changes = page.context['settings_changes']
        self.assertEqual([c['label'] for c in changes], ['زمان انقضای جلسه', 'رنگ اصلی سامانه'])
        self.assertEqual(changes[1]['values'][1], {'text': '#7C3AED', 'color': '#7C3AED', 'latin': True})
        self.assertContains(page, 'class="gs-swatch" style="--sw:#7C3AED"')
        self.assertEqual(changes[0]['values'][1]['text'], '45 دقیقه')

    def test_choice_settings_accept_only_their_options(self):
        self._save(default_language='ح)', timezone='Mars/Base', date_format='whatever', password_policy='خیلی قوی')
        for key, expected in (('default_language', None), ('timezone', None), ('date_format', None), ('password_policy', None)):
            self.assertEqual(self._stored(key), expected, key)  # each fell back to the default: nothing changed
        self._save(timezone='Asia/Kabul', password_policy='weak')
        self.assertEqual(self._stored('timezone'), 'Asia/Kabul')
        self.assertEqual(self._stored('password_policy'), 'weak')
        page = self._page()
        self.assertContains(page, '<option value="medium">متوسط</option>')
        self.assertContains(page, '<option value="weak" selected>ضعیف</option>')

    def test_old_free_text_values_map_to_options(self):
        from .views import erd_execute

        for key, value in (('default_language', 'ح)'), ('timezone', 'تهران (UTC+03:30)'), ('password_policy', 'متوسط')):
            erd_execute('INSERT INTO system_settings (key, value) VALUES (%s, %s)', [key, json.dumps(value)])
        lookup = self._page().context['settings_lookup']
        self.assertEqual([lookup[k]['value'] for k in ('default_language', 'timezone', 'password_policy')], ['fa', 'Asia/Tehran', 'medium'])

    def test_ip_restriction_refuses_lists_that_lock_out_the_admin(self):
        response = self._save(ip_restriction='on', ip_allow_list='10.0.0.0/8')
        self.assertIn('دسترسی خود شما', _messages(response)[0])
        self.assertIsNone(self._stored('ip_restriction'))
        response = self._save(ip_restriction='on', ip_allow_list='', ip_block_list='127.0.0.1')
        self.assertIn('دسترسی خود شما', _messages(response)[0])
        response = self._save(ip_restriction='on', ip_allow_list='not-an-ip')
        self.assertIn('معتبر', _messages(response)[0])
        response = self._save(ip_restriction='on')
        self.assertIn('دست‌کم یک نشانی', _messages(response)[0])
        self.assertIsNone(self._stored('ip_restriction'))

    def test_ip_restriction_is_enforced(self):
        response = self._save(ip_restriction='on', ip_allow_list='127.0.0.1, 192.168.1.0/24', ip_block_list='192.168.1.66')
        self.assertTrue(_messages(response)[0].startswith('3 تنظیم ذخیره شد'))
        self.assertEqual(self._stored('ip_allow_list'), '127.0.0.1, 192.168.1.0/24')
        login = reverse('core:login')
        self.assertEqual(self.client.get(login).status_code, 200)
        self.assertEqual(self.client.get(login, REMOTE_ADDR='192.168.1.20').status_code, 200)
        blocked = self.client.get(login, REMOTE_ADDR='192.168.1.66')
        self.assertEqual(blocked.status_code, 403)
        self.assertContains(blocked, 'دسترسی از این شبکه مجاز نیست', status_code=403)
        self.assertEqual(self.client.get(login, REMOTE_ADDR='10.9.9.9').status_code, 403)
        self.assertEqual(self.client.get(self.url, {'tab': 'other'}, REMOTE_ADDR='10.9.9.9').status_code, 403)
        # switched off: the lists stay stored but nobody is refused
        self._save(ip_restriction='off')
        self.assertEqual(self.client.get(login, REMOTE_ADDR='10.9.9.9').status_code, 200)
        self.assertEqual(self._stored('ip_allow_list'), '127.0.0.1, 192.168.1.0/24')


class SystemLogoTests(_ScopedOrgFixture):
    def setUp(self):
        self.media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.media, True)
        override = self.settings(MEDIA_ROOT=self.media)
        override.enable()
        self.addCleanup(override.disable)
        self.url = reverse('core:super_admin_settings')
        self.client.force_login(self.admin_user)

    @staticmethod
    def _png():
        from PIL import Image

        buffer = io.BytesIO()
        Image.new('RGB', (900, 300), '#22c55e').save(buffer, 'PNG')
        return SimpleUploadedFile('logo.png', buffer.getvalue(), content_type='image/png')

    def test_logo_upload_is_checked_stored_and_shown(self):
        from .views import erd_setting

        response = self.client.post(self.url, {'settings_action': 'bulk_save',
                                               'system_logo_file': SimpleUploadedFile('x.png', b'<svg onload=alert(1)>', content_type='image/png')})
        self.assertIn('تصویر معتبری نیست', _messages(response)[0])
        self.assertIsNone(erd_setting('system_logo'))
        response = self.client.post(self.url, {'settings_action': 'bulk_save', 'system_logo_file': self._png()})
        self.assertEqual(_messages(response)[-1], '1 تنظیم ذخیره شد: «لوگو / هویت سامانه».')
        logo = erd_setting('system_logo')
        self.assertRegex(logo, r'^/media/settings/logo-[0-9a-f]{32}\.png$')
        from PIL import Image

        with Image.open(f"{self.media}/settings/{logo.rsplit('/', 1)[1]}") as stored:
            self.assertEqual(stored.size, (512, 171))  # scaled down to 512px
        self.client.logout()
        self.assertContains(self.client.get(reverse('core:login')), f'<img src="{logo}" alt="">')
        # a forged value (another URL) is not accepted; the default is
        self.client.force_login(self.admin_user)
        self.client.post(self.url, {'settings_action': 'bulk_save', 'settings_system_logo': 'https://evil.example/x.png'})
        self.assertEqual(erd_setting('system_logo'), logo)
        self.client.post(self.url, {'settings_action': 'bulk_save', 'settings_system_logo': '/static/img/metaquiz-favicon.svg'})
        self.assertEqual(erd_setting('system_logo'), '/static/img/metaquiz-favicon.svg')
        self.client.logout()
        self.assertNotContains(self.client.get(reverse('core:login')), 'mq-brand-mark is-image')


class ExamHubFormsTests(_ScopedOrgFixture):
    """«تنظیمات» of the exam hub saves only real changes; «موارد نیازمند بررسی» knows when a filter is applied."""

    def setUp(self):
        self.client.force_login(self.admin_user)
        self.hub = reverse('core:super_admin_exam_hub', args=[self.exam_in_id])
        self.action = reverse('core:super_admin_exam_hub_action', args=[self.exam_in_id])

    def _form(self):
        page = self.client.get(self.hub, {'tab': 'settings'})
        self.assertContains(page, 'data-dirty-submit')
        self.assertContains(page, 'data-help-tip="اگر روشن باشد، سؤال‌ها')
        s = page.context['settings']
        exam = page.context['exam']
        data = {'action': 'settings', 'back': '?tab=settings', 'title': exam['title'], 'start_at': s['start_value'],
                'end_at': s['end_value'], 'duration_minutes': exam.get('duration_minutes') or 90,
                'max_attempts': s['max_attempts'], 'score_display_mode': s['score_mode']}
        if s['shuffle']:
            data['shuffle_questions'] = '1'
        if s['key_shown']:
            data['show_key'] = '1'
        return data

    def test_settings_without_changes_are_not_claimed_saved(self):
        from .views import erd_row

        response = self.client.post(self.action, self._form())
        self.assertEqual(_messages(response), ['تغییری ثبت نشد؛ تنظیمات آزمون همان مقادیر قبلی است.'])
        data = self._form()
        data['max_attempts'] = '3'
        response = self.client.post(self.action, data)
        self.assertEqual(_messages(response)[-1], 'تنظیمات آزمون ذخیره شد.')
        self.assertEqual(erd_row('SELECT max_attempts FROM exams WHERE id = %s', [self.exam_in_id])['max_attempts'], 3)
        log = erd_row("SELECT metadata FROM activity_audit_log WHERE action = 'exam_settings_updated' ORDER BY created_at DESC LIMIT 1")
        meta = log['metadata'] if isinstance(log['metadata'], dict) else json.loads(log['metadata'])
        self.assertEqual(meta['fields'], ['max_attempts'])

    def test_review_filter_knows_when_something_is_applied(self):
        page = self.client.get(self.hub, {'tab': 'review'})
        self.assertFalse(page.context['review']['is_filtered'])
        self.assertContains(page, 'data-dirty-reset')
        page = self.client.get(self.hub, {'tab': 'review', 'k_flagged': '1'})
        self.assertTrue(page.context['review']['is_filtered'])
        self.assertContains(page, 'href="?tab=review"')


class PasswordPolicySettingTests(TestCase):
    """«سیاست گذرواژه» is enforced: the validators follow the chosen policy (strong is the default)."""

    def _set(self, policy):
        from apps.core.views import erd_execute
        erd_execute('DELETE FROM system_settings WHERE key = %s', ['password_policy'])
        if policy:
            erd_execute("INSERT INTO system_settings (key, value) VALUES (%s, %s)", ['password_policy', json.dumps(policy)])

    def test_policy_changes_what_is_accepted(self):
        from django.contrib.auth.password_validation import validate_password
        from django.core.exceptions import ValidationError

        self._set(None)
        with self.assertRaises(ValidationError):
            validate_password('abcdefg1')
        self._set('medium')
        validate_password('abcdefg1x')
        with self.assertRaises(ValidationError):
            validate_password('abcdefgh')
        self._set('weak')
        validate_password('mz7kpw')
        with self.assertRaises(ValidationError):
            validate_password('abc')
