from django.core.management.base import BaseCommand

from apps.core.exam_schedule import publish_due_exams


class Command(BaseCommand):
    help = 'Publishes approved exams whose «زمان‌بندی انتشار» time has passed (for a cron/systemd timer; the site also checks every minute).'

    def handle(self, *args, **options):
        published = publish_due_exams()
        for exam in published:
            self.stdout.write(f"Published: {exam['title']} ({exam['id']})")
        self.stdout.write(self.style.SUCCESS(f'{len(published)} scheduled exam(s) published.'))
