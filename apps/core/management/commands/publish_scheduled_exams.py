from django.core.management.base import BaseCommand

from apps.core.exam_schedule import run_due_tasks


class Command(BaseCommand):
    help = ('Runs the timed exam work (for a cron/systemd timer; the site also does it every minute): publishes exams '
            'whose «زمان‌بندی انتشار» has passed, closes attempts whose time ran out, and releases results that are due.')

    def handle(self, *args, **options):
        done = run_due_tasks()
        for exam in done['published']:
            self.stdout.write(f"Published: {exam['title']} ({exam['id']})")
        self.stdout.write(self.style.SUCCESS(
            f"{len(done['published'])} scheduled exam(s) published, {len(done['finalized'])} expired attempt(s) closed, "
            f"{len(done['released'])} exam result(s) released."))
