"""The exam page's «every question at once» part (?part=questions, views._sx_render_attempt_page): served only where
the student may open any question and change any answer anyway, with the stored answers, and changing nothing."""
import re

from django.urls import reverse

from .tests import _EnforcedExamFixture


class AttemptQuestionsPartTests(_EnforcedExamFixture):

    def _attempt(self, **settings):
        exam_id = self._exam(**settings)
        self.client.force_login(self.student_user)
        attempt_id = self._start(exam_id)
        self.assertTrue(attempt_id)
        return exam_id, reverse('core:student_attempt', args=[attempt_id])

    def test_every_question_with_its_stored_answer(self):
        _, url = self._attempt()
        saved = self.client.post(url + '?q=1', {f'answer_{self.single_id}': '2', f'seen_{self.single_id}': '1'},
                                 HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(saved.json(), {'ok': True})
        part = self.client.get(url + '?part=questions')
        self.assertEqual(part.status_code, 200)
        self.assertTemplateUsed(part, 'student/_attempt_questions.html')
        self.assertTemplateNotUsed(part, 'student/attempt.html')
        html = part.content.decode()
        self.assertEqual(re.findall(r'<template data-question="(\d+)"', html), ['1', '2', '3'])
        for question_id in (self.single_id, self.multi_id, self.essay_id):
            self.assertIn(f'name="seen_{question_id}"', html)
        self.assertRegex(html, rf'name="answer_{self.single_id}" value="2"[^>]*checked')
        self.assertIn('data-answered="1"', html)
        self.assertNotIn('<html', html)
        self.assertNotIn('<script', html)
        # the page itself still renders the question on screen the same way
        page = self.client.get(url + '?q=2')
        self.assertTemplateUsed(page, 'student/attempt.html')
        self.assertContains(page, f'name="seen_{self.multi_id}"')
        self.assertContains(page, 'data-question-index="2"')

    def test_not_served_where_questions_must_not_show_early(self):
        for settings in ({'review_answers_enabled': False}, {'allow_answer_changes': False}, {'one_question_per_page': False}):
            with self.subTest(settings=settings):
                _, url = self._attempt(**settings)
                self.assertEqual(self.client.get(url + '?part=questions').status_code, 404)
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_forward_only_part_does_not_move_the_student(self):
        _, url = self._attempt(review_answers_enabled=False)
        self.client.get(url + '?q=3&part=questions')
        page = self.client.get(url)
        self.assertEqual(page.context['current_index'], 1)

    def test_preview_serves_it_too(self):
        exam_id = self._exam()
        self.client.force_login(self.teacher_user)
        preview = reverse('core:exam_preview', args=[exam_id])
        self.client.get(preview + '?new=1')
        part = self.client.get(preview + '?part=questions')
        self.assertEqual(part.status_code, 200)
        self.assertEqual(len(re.findall(r'<template data-question=', part.content.decode())), 3)
        locked = self._exam(allow_answer_changes=False)
        preview = reverse('core:exam_preview', args=[locked])
        self.client.get(preview + '?new=1')
        self.assertEqual(self.client.get(preview + '?part=questions').status_code, 404)

    def test_anonymous_and_other_roles_get_nothing(self):
        _, url = self._attempt()
        self.client.logout()
        response = self.client.get(url + '?part=questions')
        self.assertNotEqual(response.status_code, 200)
        self.client.force_login(self.teacher_user)
        self.assertNotEqual(self.client.get(url + '?part=questions').status_code, 200)
