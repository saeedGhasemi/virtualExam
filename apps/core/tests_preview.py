"""«پیش‌نمایش» of exams and questions (apps/core/exam_preview.py) for every role."""
import json
import uuid

from django.contrib.auth import get_user_model
from django.db import connection
from django.urls import reverse

from .tests import _EnforcedExamFixture, _insert

SECRET_TEXT = 'متن محرمانه‌ی سؤال آزمون'
SECRET_OPTION = 'گزینه‌ی محرمانه‌ی درست'


class ExamPreviewTests(_EnforcedExamFixture):
    """Staff see the real exam on the student exam page; students see sample questions with the exam's structure;
    nothing is written to the database; the exam's rules apply as in a real attempt."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.teacher_out_user = get_user_model().objects.create_user(username='teacher_out_scope', email='t_out@example.com', password='x')
        cls.secret_id = str(uuid.uuid4())
        options = json.dumps([{'id': '1', 'text': SECRET_OPTION}, {'id': '2', 'text': 'گزینه‌ی دوم محرمانه'},
                              {'id': '3', 'text': 'گزینه‌ی سوم'}, {'id': '4', 'text': 'گزینه‌ی چهارم'}, {'id': '5', 'text': 'پنجم'}],
                             ensure_ascii=False)
        _insert('questions', ['id', 'teacher_id', 'course_id', 'text', 'type', 'options', 'correct_answer', 'default_points'],
                [cls.secret_id, cls.teacher_in_id, cls.course_in_id, SECRET_TEXT, 'single', options, json.dumps('1'), 3])

    def _secret_exam(self, **settings):
        exam_id = self._exam(**settings)
        _insert('exam_questions', ['id', 'exam_id', 'question_id', 'points', 'order_index'], [str(uuid.uuid4()), exam_id, self.secret_id, 3, 4])
        return exam_id

    def _url(self, exam_id, suffix=''):
        return reverse('core:exam_preview', args=[exam_id]) + suffix

    def _count(self, sql, params):
        with connection.cursor() as cursor:
            cursor.execute(sql, params)
            return cursor.fetchone()[0]

    def test_teacher_sees_the_real_exam_page_and_nothing_is_saved(self):
        exam_id = self._secret_exam()
        self.client.force_login(self.teacher_user)
        page = self.client.get(self._url(exam_id, '?new=1'), follow=True)
        self.assertTemplateUsed(page, 'student/attempt.html')
        self.assertContains(page, 'data-preview-bar')
        self.assertEqual(page.context['total_questions'], 4)
        self.assertNotContains(page, 'id="auto-submit-form"')
        last = self.client.get(self._url(exam_id, '?q=4'))
        self.assertContains(last, SECRET_TEXT)
        self.assertContains(last, SECRET_OPTION)
        saved = self.client.post(self._url(exam_id, '?q=1'), {f'answer_{self.single_id}': '2', f'seen_{self.single_id}': '1',
                                                             f'mark_{self.single_id}': 'on', 'action': 'next'})
        self.assertRedirects(saved, self._url(exam_id, '?q=2'), fetch_redirect_response=False)
        back = self.client.get(self._url(exam_id, '?q=1'))
        self.assertTrue(back.context['current_answer']['answered'] and back.context['current_answer']['marked'])
        self.assertEqual(self._count('SELECT COUNT(*) FROM exam_attempts WHERE exam_id = %s', [exam_id]), 0)
        finish = self.client.get(self._url(exam_id, 'finish/'))
        self.assertEqual((finish.context['answered_count'], finish.context['unanswered_count'], finish.context['marked_count']), (1, 3, 1))
        self.assertEqual(finish.context['total_points'], 9)
        self.client.post(self._url(exam_id), {'action': 'restart'})
        self.assertEqual(self.client.get(self._url(exam_id, 'finish/')).context['answered_count'], 0)

    def test_student_sees_sample_questions_only(self):
        exam_id = self._secret_exam()
        self.client.force_login(self.student_user)
        for q in range(1, 5):
            page = self.client.get(self._url(exam_id, f'?new=1&q={q}' if q == 1 else f'?q={q}'), follow=True)
            self.assertEqual(page.status_code, 200)
            for secret in (SECRET_TEXT, SECRET_OPTION, 'گزینه‌ی دوم محرمانه', 'تک‌گزینه‌ای', 'الف'):
                self.assertNotContains(page, secret)
            self.assertContains(page, 'سؤال نمونه')
            self.assertTrue(page.context['preview']['sample'])
        # same structure: four questions, the real types and points, five options on the last one
        self.assertEqual([item['type'] for item in page.context['items']], ['single', 'multi', 'essay', 'single'])
        self.assertEqual(len(page.context['current_answer']['options']), 5)
        self.assertEqual(page.context['current_answer']['points'], 3)
        self.assertEqual(self._count('SELECT COUNT(*) FROM exam_attempts WHERE exam_id = %s', [exam_id]), 0)
        self.assertContains(self.client.get(reverse('core:student_exam_schedule')), self._url(exam_id))
        self.assertContains(self.client.get(reverse('core:student_exam_detail', args=[exam_id])), self._url(exam_id))

    def test_access_follows_each_role(self):
        exam_id = self._secret_exam()
        self.client.force_login(self.student_user)
        self.assertEqual(self.client.get(self._url(self.exam_out_id)).status_code, 404)  # not the student's exam
        self.assertEqual(self.client.get(reverse('core:question_preview', args=[self.secret_id])).status_code, 403)
        self.assertEqual(self.client.get(self._url('not-a-uuid')).status_code, 404)
        self.client.force_login(self.teacher_out_user)
        self.assertEqual(self.client.get(self._url(exam_id)).status_code, 404)
        self.assertEqual(self.client.get(reverse('core:question_preview', args=[self.secret_id])).status_code, 404)
        for user in (self.manager_user, self.admin_user):
            self.client.force_login(user)
            page = self.client.get(self._url(exam_id, '?q=4'))
            self.assertEqual(page.status_code, 200, user.username)
            self.assertContains(page, SECRET_TEXT)
        self.client.logout()
        self.assertEqual(self.client.get(self._url(exam_id)).status_code, 302)

    def test_rules_apply_as_in_the_exam(self):
        exam_id = self._exam(review_answers_enabled=False, allow_answer_changes=False, copy_paste_prevention=True,
                             webcam_monitoring=True)
        self.client.force_login(self.teacher_user)
        self.client.get(self._url(exam_id, '?new=1'))
        self.client.post(self._url(exam_id, '?q=1'), {f'answer_{self.single_id}': '1', f'seen_{self.single_id}': '1', 'action': 'next'})
        self.assertRedirects(self.client.get(self._url(exam_id, '?q=1')), self._url(exam_id, '?q=2'), fetch_redirect_response=False)
        page = self.client.get(self._url(exam_id, '?q=2'))
        self.assertNotContains(page, 'value="previous"')
        self.assertEqual({key: page.context['proctoring'][key] for key in ('copy_paste', 'webcam', 'fullscreen', 'track')},
                         {'copy_paste': True, 'webcam': False, 'fullscreen': False, 'track': False})  # camera only listed
        self.assertIn('نظارت وبکم', page.context['preview']['rules'])
        # the answer left behind is locked: a later change is ignored
        self.client.post(self._url(exam_id, '?q=2'), {f'answer_{self.single_id}': '2', f'seen_{self.single_id}': '1'},
                         HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        state = self.client.session['mq_previews'][f'exam:{exam_id}']
        self.assertEqual(json.loads(state['answers'][self.single_id])['value'], '1')

    def test_question_preview_and_list_links(self):
        self.client.force_login(self.teacher_user)
        page = self.client.get(reverse('core:question_preview', args=[self.secret_id]) + '?new=1', follow=True)
        self.assertTemplateUsed(page, 'student/attempt.html')
        self.assertContains(page, SECRET_TEXT)
        self.assertIsNone(page.context['remaining_seconds'])  # a single question has no exam timer
        self.assertContains(self.client.get(reverse('core:teacher_questions')), reverse('core:question_preview', args=[self.secret_id]))
        exam_id = self._exam()
        self.assertContains(self.client.get(reverse('core:teacher_exams')), self._url(exam_id))
        self.assertRedirects(self.client.get(reverse('core:teacher_exam_preview', args=[exam_id])), self._url(exam_id, '?new=1'),
                             fetch_redirect_response=False)
        self.client.force_login(self.admin_user)
        self.assertContains(self.client.get(reverse('core:super_admin_exams')), self._url(exam_id))

    def test_exam_without_questions(self):
        exam_id = str(uuid.uuid4())
        _insert('exams', ['id', 'title', 'teacher_id', 'course_id', 'duration_minutes'], [exam_id, 'بدون سؤال', self.teacher_in_id, self.course_in_id, 20])
        self.client.force_login(self.teacher_user)
        page = self.client.get(self._url(exam_id, '?new=1'), follow=True)
        self.assertContains(page, 'این آزمون هنوز سؤالی ندارد')
