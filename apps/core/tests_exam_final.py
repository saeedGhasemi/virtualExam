"""Final exam acceptance suite (2026-11-20, user's request: «تست نهایی بخش آزمون»).

Every scenario moves the clock (timezone.now patched) through one exam's life: the start to the second, the end of the
window, the student's own time, «افزودن زمان» from the live monitor, an end moved later / earlier, a second attempt,
unpublished / cancelled / empty exams, late or repeated submits, the scheduler closing what the browser did not, and
what another student may reach. The older suites (tests.py: ExamTimingScenariosTests, ExamAttemptRulesTests,
ExamEntryRulesTests, ExamEndToEndTests, …) keep covering the rest."""
import json
import uuid
from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from .tests import TeacherStudentScopeTests, _EnforcedExamFixture, _insert
from .views import erd_execute


class ExamFinalScenarioTests(_EnforcedExamFixture):
    AJAX = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'}

    def setUp(self):
        self.t0 = timezone.now().replace(second=0, microsecond=0)
        self.client.force_login(self.student_user)

    # ------------------------------------------------------------------ helpers

    def at(self, moment):
        return mock.patch('django.utils.timezone.now', return_value=moment)

    def _student(self, username, group_id=None):
        profile_id = self._make_profile(username, 'دانشجوی ' + username)
        _insert('student_profiles', ['user_id', 'org_unit_id'], [profile_id, self.ou_scoped])
        _insert('user_roles', ['id', 'user_id', 'role'], [str(uuid.uuid4()), profile_id, 'student'])
        if group_id:
            TeacherStudentScopeTests._member(group_id, profile_id)
        client = self.client_class()
        client.force_login(get_user_model().objects.create_user(username=username, email=f'{username}@example.com', password='x'))
        return client

    def _save(self, attempt_id, value='2', client=None):
        return (client or self.client).post(reverse('core:student_attempt', args=[attempt_id]),
                                            {f'answer_{self.single_id}': value}, **self.AJAX)

    def _live(self, attempt_id, client=None):
        return (client or self.client).get(reverse('core:student_attempt_live', args=[attempt_id])).json()

    def _page_remaining(self, attempt_id):
        return self.client.get(reverse('core:student_attempt', args=[attempt_id])).context['remaining_seconds']

    def _attempt(self, attempt_id):
        return self._rows('SELECT status, submitted_at, score FROM exam_attempts WHERE id = %s', [attempt_id])[0]

    def _count(self, exam_id):
        return self._rows('SELECT COUNT(*) FROM exam_attempts WHERE exam_id = %s', [exam_id])[0][0]

    def _submit(self, attempt_id, **data):
        return self.client.post(reverse('core:student_attempt_submit', args=[attempt_id]), data)

    def _hub_action(self, exam_id, **data):
        teacher = self.client_class()
        teacher.force_login(self.teacher_user)
        return teacher.post(reverse('core:teacher_exam_hub_action', args=[exam_id]), data)

    # ------------------------------------------------------------------ starting

    def test_start_opens_to_the_second(self):
        start = self.t0 + timedelta(hours=1)
        exam_id = self._exam(start_at=start, end_at=start + timedelta(hours=1), duration_minutes=30)
        with self.at(start - timedelta(seconds=1)):
            self.assertIsNone(self._start(exam_id))
            self.assertFalse(self.client.get(reverse('core:student_exam_detail', args=[exam_id])).context['can_enter'])
        self.assertEqual(self._count(exam_id), 0)
        with self.at(start):
            attempt_id = self._start(exam_id)
            self.assertTrue(attempt_id)
            self.assertEqual(self._page_remaining(attempt_id), 30 * 60)  # the full duration from its own start

    def test_no_start_when_no_time_is_left(self):
        """At the exam's last moment a start would give an attempt that is already over: refused."""
        start = self.t0
        exam_id = self._exam(start_at=start, end_at=start + timedelta(minutes=40), duration_minutes=30)
        with self.at(start + timedelta(minutes=40)):
            self.assertIsNone(self._start(exam_id))
        self.assertEqual(self._count(exam_id), 0)
        with self.at(start + timedelta(minutes=39, seconds=30)):  # 30 seconds left: allowed, and it gets those 30
            attempt_id = self._start(exam_id)
            self.assertEqual(self._page_remaining(attempt_id), 30)

    def test_resume_keeps_the_running_clock(self):
        exam_id = self._exam(start_at=self.t0, end_at=self.t0 + timedelta(hours=2), duration_minutes=30)
        with self.at(self.t0 + timedelta(minutes=1)):
            attempt_id = self._start(exam_id)
            self._save(attempt_id, '1')
        with self.at(self.t0 + timedelta(minutes=16)):  # the browser was closed for 15 minutes: the time kept running
            self.assertEqual(self._start(exam_id), attempt_id)
            self.assertEqual(self._page_remaining(attempt_id), 15 * 60)
            self.assertEqual(self._live(attempt_id)['remaining_seconds'], 15 * 60)
        self.assertEqual(self._count(exam_id), 1)
        [(answer,)] = self._rows('SELECT answer FROM attempt_answers WHERE attempt_id = %s AND question_id = %s', [attempt_id, self.single_id])
        self.assertEqual(json.loads(answer)['value'], '1')  # the saved answer is still there

    def test_second_attempt_gets_its_own_full_time(self):
        exam_id = self._exam(start_at=self.t0, end_at=self.t0 + timedelta(hours=3), duration_minutes=30, max_attempts=2)
        with self.at(self.t0 + timedelta(minutes=1)):
            first = self._start(exam_id)
        with self.at(self.t0 + timedelta(minutes=10)):
            self._submit(first)
        with self.at(self.t0 + timedelta(minutes=50)):
            second = self._start(exam_id)
            self.assertTrue(second and second != first)
            self.assertEqual(self._page_remaining(second), 30 * 60)
        with self.at(self.t0 + timedelta(minutes=55)):
            self._submit(second)
            self.assertIsNone(self._start(exam_id))  # 2 of 2 used
        self.assertEqual(self._count(exam_id), 2)

    def test_unpublished_or_cancelled_exam_gives_no_new_attempt(self):
        """A student who has an attempt still reaches the exam's pages, but may not begin another one once the exam
        is unpublished or cancelled."""
        for change in ({'is_published': False}, {'is_cancelled': True}):
            exam_id = self._exam(start_at=self.t0, end_at=self.t0 + timedelta(hours=3), duration_minutes=30, max_attempts=3)
            with self.at(self.t0 + timedelta(minutes=1)):
                first = self._start(exam_id)
                self._submit(first)
            column, value = next(iter(change.items()))
            erd_execute(f'UPDATE exams SET {column} = %s WHERE id = %s', [value, exam_id])
            with self.at(self.t0 + timedelta(minutes=5)):
                self.assertIsNone(self._start(exam_id), change)
            self.assertEqual(self._count(exam_id), 1, change)

    def test_cancelled_exam_cannot_be_resumed(self):
        exam_id = self._exam(start_at=self.t0, end_at=self.t0 + timedelta(hours=1), duration_minutes=30)
        with self.at(self.t0 + timedelta(minutes=1)):
            attempt_id = self._start(exam_id)
        erd_execute('UPDATE exams SET is_cancelled = %s WHERE id = %s', [True, exam_id])
        with self.at(self.t0 + timedelta(minutes=2)):
            response = self.client.post(reverse('core:student_exam_start', args=[exam_id]))
            self.assertNotIn(f'/student/attempts/{attempt_id}', response.get('Location', ''))
            self.assertEqual(self._save(attempt_id).status_code, 409)
            self.assertEqual(self._live(attempt_id), {'ok': True, 'open': False})

    def test_exam_without_questions_cannot_be_started(self):
        exam_id = self._exam(start_at=self.t0, end_at=self.t0 + timedelta(hours=1))
        erd_execute('DELETE FROM exam_questions WHERE exam_id = %s', [exam_id])
        with self.at(self.t0 + timedelta(minutes=1)):
            self.assertIsNone(self._start(exam_id))
        self.assertEqual(self._count(exam_id), 0)

    # ------------------------------------------------------------------ the student's time

    def test_duration_longer_than_the_window_is_cut_at_the_end(self):
        exam_id = self._exam(start_at=self.t0, end_at=self.t0 + timedelta(minutes=60), duration_minutes=120)
        with self.at(self.t0):
            attempt_id = self._start(exam_id)
            self.assertEqual(self._page_remaining(attempt_id), 60 * 60)

    def test_end_moved_later_lengthens_only_up_to_the_duration(self):
        exam_id = self._exam(start_at=self.t0, end_at=self.t0 + timedelta(minutes=20), duration_minutes=30)
        with self.at(self.t0):
            attempt_id = self._start(exam_id)
        with self.at(self.t0 + timedelta(minutes=5)):
            self.assertEqual(self._live(attempt_id)['remaining_seconds'], 15 * 60)
            erd_execute('UPDATE exams SET end_at = %s WHERE id = %s', [self.t0 + timedelta(hours=2), exam_id])
            self.assertEqual(self._live(attempt_id)['remaining_seconds'], 25 * 60)  # its own 30 minutes, not 2 hours
        with self.at(self.t0 + timedelta(minutes=25)):  # past the old end: still answering
            self.assertEqual(self._save(attempt_id).json(), {'ok': True})

    def test_extra_time_from_the_live_monitor(self):
        from apps.core.exam_schedule import finalize_expired_attempts
        from apps.core.views import _sx_dt
        exam_id = self._exam(start_at=self.t0, end_at=self.t0 + timedelta(minutes=30), duration_minutes=30, auto_submit_on_time_end=True)
        with self.at(self.t0):
            attempt_id = self._start(exam_id)
        with self.at(self.t0 + timedelta(minutes=20)):
            # what the monitor refuses: a duration not in the list, no reason
            self._hub_action(exam_id, action='add_time', attempt=attempt_id, minutes='7', reason='قطعی برق')
            self._hub_action(exam_id, action='add_time', attempt=attempt_id, minutes='10', reason='  ')
            self.assertEqual(self._live(attempt_id)['remaining_seconds'], 10 * 60)
            self._hub_action(exam_id, action='add_time', attempt=attempt_id, minutes='10', reason='قطعی برق')
            self.assertEqual(self._live(attempt_id)['remaining_seconds'], 20 * 60)  # beyond the exam's own end
            self.assertEqual(self._page_remaining(attempt_id), 20 * 60)
        with self.at(self.t0 + timedelta(minutes=35)):
            self.assertEqual(self._save(attempt_id, '2').json(), {'ok': True})
        self.assertEqual(finalize_expired_attempts(now=self.t0 + timedelta(minutes=40, seconds=20)), [])  # in its grace
        self.assertEqual(finalize_expired_attempts(now=self.t0 + timedelta(minutes=40, seconds=31)), [attempt_id])
        status, submitted_at, score = self._attempt(attempt_id)
        self.assertEqual((status, _sx_dt(submitted_at), float(score)), ('graded', self.t0 + timedelta(minutes=40), 2.0))
        self.assertEqual(self._rows("SELECT COUNT(*) FROM activity_audit_log WHERE action = 'exam_time_extended' AND entity_id = %s",
                                    [attempt_id])[0][0], 1)
        # a closed attempt gets no more time
        self._hub_action(exam_id, action='add_time', attempt=attempt_id, minutes='10', reason='دیر رسید')
        self.assertEqual(self._rows('SELECT extra_minutes FROM exam_attempts WHERE id = %s', [attempt_id])[0][0], 10)

    def test_extra_time_is_only_for_that_student(self):
        exam_id = self._exam(start_at=self.t0, end_at=self.t0 + timedelta(hours=1), duration_minutes=30)
        other = self._student('student_neighbour', self.group_in_id)
        with self.at(self.t0):
            mine, theirs = self._start(exam_id), self._start(exam_id, other)
            self._hub_action(exam_id, action='add_time', attempt=mine, minutes='15', reason='نیاز ویژه')
            self.assertEqual((self._live(mine)['remaining_seconds'], self._live(theirs, other)['remaining_seconds']), (45 * 60, 30 * 60))

    def test_a_late_submit_after_the_grace_keeps_only_answers_saved_in_time(self):
        """A device that was offline long after the time ran out sends «پایان آزمون» with a changed answer: the
        attempt is submitted at its deadline with what was saved in time."""
        from apps.core.views import _sx_dt
        exam_id = self._exam(start_at=self.t0, end_at=self.t0 + timedelta(hours=2), duration_minutes=10, auto_submit_on_time_end=True)
        with self.at(self.t0):
            attempt_id = self._start(exam_id)
        with self.at(self.t0 + timedelta(minutes=5)):
            self._save(attempt_id, '2')
        with self.at(self.t0 + timedelta(minutes=25)):
            self.assertEqual(self._save(attempt_id, '1').status_code, 409)
            self._submit(attempt_id, **{f'answer_{self.single_id}': '1'})
        status, submitted_at, score = self._attempt(attempt_id)
        self.assertEqual((status, _sx_dt(submitted_at), float(score)), ('graded', self.t0 + timedelta(minutes=10), 2.0))

    def test_page_opened_after_the_time_shows_zero_and_closes_cleanly(self):
        exam_id = self._exam(start_at=self.t0, end_at=self.t0 + timedelta(hours=2), duration_minutes=10, auto_submit_on_time_end=True)
        with self.at(self.t0):
            attempt_id = self._start(exam_id)
            self._save(attempt_id, '2')
        with self.at(self.t0 + timedelta(minutes=12)):  # before the scheduler ran
            self.assertEqual(self._page_remaining(attempt_id), 0)
            self.assertEqual(self._live(attempt_id)['remaining_seconds'], 0)
            self.assertEqual(self._start(exam_id), attempt_id)  # «ادامه» leads to the same, time-up attempt
            self._submit(attempt_id, auto='1')  # the page's auto-submit at zero
            self.assertRedirects(self.client.get(reverse('core:student_attempt', args=[attempt_id])),
                                 reverse('core:student_attempt_receipt', args=[attempt_id]), fetch_redirect_response=False)
            self.assertEqual(self._live(attempt_id), {'ok': True, 'open': False})
        self.assertEqual(self._attempt(attempt_id)[0], 'graded')

    def test_without_auto_submit_the_time_up_never_submits(self):
        """«ارسال خودکار» off (browser run S4: the page submitted at zero, 0.4 s before the deadline): the page's time-up
        opens the confirmation with ?timeup=1 and the attempt is closed as expired; a «پایان آزمون» pressed in time and
        arriving within the grace still counts; the confirmation opened after the deadline offers no late submit."""
        submit = lambda attempt_id, **query: reverse('core:student_attempt_submit', args=[attempt_id]) + ('?timeup=1' if query else '')
        exam_id = self._exam(start_at=self.t0, end_at=self.t0 + timedelta(hours=2), duration_minutes=10, auto_submit_on_time_end=False,
                             max_attempts=0)
        with self.at(self.t0):
            first = self._start(exam_id)
        with self.at(self.t0 + timedelta(minutes=9)):  # a minute left: the normal confirmation page
            self.assertEqual(self.client.get(submit(first)).status_code, 200)
        with self.at(self.t0 + timedelta(minutes=9, seconds=59, milliseconds=600)):  # the page's clock reached zero first
            self.assertRedirects(self.client.get(submit(first, timeup=1)), reverse('core:student_exam_detail', args=[exam_id]),
                                 fetch_redirect_response=False)
        self.assertEqual(self._attempt(first)[:2], ('expired', None))

        with self.at(self.t0 + timedelta(minutes=20)):
            second = self._start(exam_id)
        with self.at(self.t0 + timedelta(minutes=30, seconds=10)):  # past the deadline: the confirmation closes it
            self.client.get(submit(second))
        self.assertEqual(self._attempt(second)[:2], ('expired', None))

        with self.at(self.t0 + timedelta(minutes=40)):
            third = self._start(exam_id)
        with self.at(self.t0 + timedelta(minutes=50, seconds=10)):  # «تأیید و ثبت نهایی» sent at the last second, late on the network
            self._submit(third)
        self.assertEqual(self._attempt(third)[0], 'graded')

    def test_access_end_with_extra_time(self):
        """«پایان دسترسی» before the exam's end cuts the time; extra time from the monitor lengthens past it."""
        exam_id = self._exam(start_at=self.t0, end_at=self.t0 + timedelta(hours=2), duration_minutes=60,
                             registration_end_at=self.t0 + timedelta(minutes=30))
        with self.at(self.t0):
            attempt_id = self._start(exam_id)
            self.assertEqual(self._page_remaining(attempt_id), 30 * 60)
            self._hub_action(exam_id, action='add_time', attempt=attempt_id, minutes='5', reason='مشکل فنی')
            self.assertEqual(self._live(attempt_id)['remaining_seconds'], 35 * 60)

    # ------------------------------------------------------------------ after the end

    def test_closed_attempt_takes_nothing_more(self):
        exam_id = self._exam(start_at=self.t0, end_at=self.t0 + timedelta(hours=1), duration_minutes=30)
        with self.at(self.t0):
            attempt_id = self._start(exam_id)
            self._save(attempt_id, '2')
        with self.at(self.t0 + timedelta(minutes=5)):
            self._submit(attempt_id)
            self._submit(attempt_id, **{f'answer_{self.single_id}': '1'})  # a second «پایان آزمون» changes nothing
            self.assertEqual(self._save(attempt_id, '1').status_code, 409)
            response = self.client.post(reverse('core:student_attempt', args=[attempt_id]), {'action': 'clear_all'})
            self.assertEqual(response.status_code, 302)
        [(answer, points)] = self._rows('SELECT answer, points_awarded FROM attempt_answers WHERE attempt_id = %s AND question_id = %s',
                                        [attempt_id, self.single_id])
        self.assertEqual((json.loads(answer)['value'], float(points)), ('2', 2.0))
        self.assertEqual(self._rows("SELECT COUNT(*) FROM activity_audit_log WHERE action = 'exam_submitted' "
                                    "AND CAST(metadata AS TEXT) LIKE %s", [f'%{attempt_id}%'])[0][0], 1)

    def test_get_of_submit_and_receipt_never_closes_an_attempt(self):
        exam_id = self._exam(start_at=self.t0, end_at=self.t0 + timedelta(hours=1), duration_minutes=30)
        with self.at(self.t0):
            attempt_id = self._start(exam_id)
        with self.at(self.t0 + timedelta(minutes=5)):
            self.assertEqual(self.client.get(reverse('core:student_attempt_submit', args=[attempt_id])).status_code, 200)  # the confirmation
            self.assertRedirects(self.client.get(reverse('core:student_attempt_receipt', args=[attempt_id])),
                                 reverse('core:student_attempt_submit', args=[attempt_id]), fetch_redirect_response=False)
            self.assertNotEqual(self.client.get(reverse('core:student_result_detail', args=[attempt_id])).status_code, 500)
        self.assertEqual(self._attempt(attempt_id)[:2], ('in_progress', None))

    def test_scheduler_closes_every_kind_once(self):
        from apps.core.exam_schedule import finalize_expired_attempts
        auto = self._exam(start_at=self.t0, end_at=self.t0 + timedelta(hours=1), duration_minutes=10, auto_submit_on_time_end=True)
        manual = self._exam(start_at=self.t0, end_at=self.t0 + timedelta(hours=1), duration_minutes=10, auto_submit_on_time_end=False)
        running = self._exam(start_at=self.t0, end_at=self.t0 + timedelta(hours=1), duration_minutes=60)
        with self.at(self.t0):
            a, m, r = self._start(auto), self._start(manual), self._start(running)
        closed = finalize_expired_attempts(now=self.t0 + timedelta(minutes=11))
        self.assertEqual(set(closed), {a, m})
        self.assertEqual(finalize_expired_attempts(now=self.t0 + timedelta(minutes=12)), [])
        self.assertEqual((self._attempt(a)[0], self._attempt(m)[:2], self._attempt(r)[0]), ('graded', ('expired', None), 'in_progress'))

    # ------------------------------------------------------------------ who may reach what

    def test_another_student_reaches_nothing_of_my_attempt(self):
        exam_id = self._exam(start_at=self.t0, end_at=self.t0 + timedelta(hours=1), duration_minutes=30)
        other = self._student('student_snoop', self.group_in_id)
        with self.at(self.t0):
            attempt_id = self._start(exam_id)
            self._save(attempt_id, '2')
            for name, method in (('core:student_attempt', 'get'), ('core:student_attempt', 'post'), ('core:student_attempt_submit', 'get'),
                                 ('core:student_attempt_submit', 'post'), ('core:student_attempt_receipt', 'get'),
                                 ('core:student_attempt_live', 'get'), ('core:student_result_detail', 'get')):
                response = getattr(other, method)(reverse(name, args=[attempt_id]), {f'answer_{self.single_id}': '1'} if method == 'post' else {})
                self.assertEqual(response.status_code, 404, (name, method))
        self.assertEqual(self._attempt(attempt_id)[:2], ('in_progress', None))
        [(answer,)] = self._rows('SELECT answer FROM attempt_answers WHERE attempt_id = %s', [attempt_id])
        self.assertEqual(json.loads(answer)['value'], '2')

    def test_answers_to_questions_outside_the_exam_are_ignored(self):
        exam_id = self._exam(start_at=self.t0, end_at=self.t0 + timedelta(hours=1), duration_minutes=30)
        stranger = str(uuid.uuid4())
        _insert('questions', ['id', 'teacher_id', 'course_id', 'text', 'type', 'default_points'],
                [stranger, self.teacher_in_id, self.course_in_id, 'سؤال دیگر', 'essay', 50])
        with self.at(self.t0):
            attempt_id = self._start(exam_id)
            self.client.post(reverse('core:student_attempt', args=[attempt_id]),
                             {f'answer_{stranger}': 'x', f'answer_{self.single_id}': '2'}, **self.AJAX)
            self._submit(attempt_id)
        self.assertEqual(self._rows('SELECT COUNT(*) FROM attempt_answers WHERE attempt_id = %s AND question_id = %s',
                                    [attempt_id, stranger])[0][0], 0)
        self.assertEqual(float(self._rows('SELECT max_score FROM exam_attempts WHERE id = %s', [attempt_id])[0][0]), 6.0)

    def test_student_outside_the_group_cannot_start_even_with_the_link(self):
        exam_id = self._exam(start_at=self.t0, end_at=self.t0 + timedelta(hours=1))
        outsider = self._student('student_stranger')
        with self.at(self.t0 + timedelta(minutes=1)):
            self.assertEqual(outsider.post(reverse('core:student_exam_start', args=[exam_id])).status_code, 404)
        self.assertEqual(self._count(exam_id), 0)


class ItemAnalysisScoreTests(_EnforcedExamFixture):
    """«تحلیل سؤالات»: «میانگین نمره (٪)» is the difficulty index p in percent (mean share of the question's points,
    like Moodle's Facility index), so it agrees with «سختی»; a 3/4 essay is 75 %, not «0 % correct»; answers still
    waiting for the teacher are not counted as zero."""

    def _attempt(self, exam_id, answers):
        attempt_id = str(uuid.uuid4())
        _insert('exam_attempts', ['id', 'exam_id', 'student_id', 'started_at', 'submitted_at', 'status'],
                [attempt_id, exam_id, self.student_in_id, timezone.now() - timedelta(minutes=30), timezone.now(), 'submitted'])
        for question_id, (points, correct, waiting) in answers.items():
            _insert('attempt_answers', ['id', 'attempt_id', 'question_id', 'answer', 'points_awarded', 'is_correct', 'needs_manual_grading'],
                    [str(uuid.uuid4()), attempt_id, question_id, json.dumps({'value': 'x'}), points, correct, waiting])

    def test_score_percent_follows_points_and_skips_ungraded(self):
        from apps.core.exam_hub import _item_analysis
        exam_id = self._exam()
        self._attempt(exam_id, {self.single_id: (2, True, False), self.multi_id: (1, False, False), self.essay_id: (1.5, None, False)})
        items, takers = _item_analysis({'id': exam_id})
        by_id = {item['id']: item for item in items}
        self.assertEqual(takers, 1)
        self.assertEqual((by_id[self.single_id]['score_pct'], by_id[self.multi_id]['score_pct'], by_id[self.essay_id]['score_pct']), (100, 50, 75))
        self.assertEqual(by_id[self.essay_id]['p'], 0.75)

        waiting_exam = self._exam()
        self._attempt(waiting_exam, {self.single_id: (2, True, False), self.essay_id: (0, None, True)})
        items, _ = _item_analysis({'id': waiting_exam})
        essay = next(item for item in items if item['id'] == self.essay_id)
        self.assertEqual((essay['score_pct'], essay['p'], essay['waiting']), (None, None, 1))  # not graded yet: no figure, not 0 %
