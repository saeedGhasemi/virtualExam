from django.core.management.base import BaseCommand

from apps.core.views import erd_rows, erd_sync_login_account


class Command(BaseCommand):
    help = (
        'Creates a matching Django auth_user (with a random password) for every ERD '
        'profile that has a username but no login account yet. Use this to fix '
        'existing students/teachers created before the login bug was fixed.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--role',
            default=None,
            choices=['student', 'teacher', 'academic_manager', 'admin'],
            help='Only sync profiles holding this role; without it, every role is checked.',
        )

    def handle(self, *args, **options):
        role = options.get('role')
        if role:
            rows = erd_rows(
                """
                SELECT DISTINCT p.username, p.status
                FROM profiles p
                JOIN user_roles ur ON ur.user_id = p.id
                WHERE ur.role = %s AND p.username IS NOT NULL AND p.username <> ''
                """,
                [role],
            )
        else:
            rows = erd_rows(
                "SELECT username, status FROM profiles WHERE username IS NOT NULL AND username <> ''"
            )

        created_count = 0
        for row in rows:
            _user, generated_password = erd_sync_login_account(
                row['username'], is_active=(row.get('status') == 'active')
            )
            if generated_password:
                created_count += 1
                self.stdout.write(f"{row['username']}: {generated_password}")

        if created_count:
            self.stdout.write(self.style.SUCCESS(f'{created_count} login account(s) created.'))
        else:
            self.stdout.write(self.style.SUCCESS('Every profile already had a login account.'))
