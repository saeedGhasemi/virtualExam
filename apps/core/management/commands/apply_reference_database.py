from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection


class Command(BaseCommand):
    help = "Apply the unchanged Supabase/PostgreSQL database migrations from the reference site."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="List the reference SQL migrations without executing them.",
        )
        parser.add_argument(
            "--allow-non-postgres",
            action="store_true",
            help="Bypass the PostgreSQL engine guard. Use only for advanced/manual checks.",
        )

    def handle(self, *args, **options):
        migrations_dir = Path(settings.BASE_DIR) / "supabase" / "migrations"
        if not migrations_dir.exists():
            raise CommandError(f"Reference migrations directory was not found: {migrations_dir}")

        migration_files = sorted(migrations_dir.glob("*.sql"))
        if not migration_files:
            raise CommandError(f"No SQL migrations were found in: {migrations_dir}")

        if options["dry_run"]:
            self.stdout.write(f"Reference migrations: {len(migration_files)}")
            for migration_file in migration_files:
                self.stdout.write(f"- {migration_file.name}")
            return

        engine = settings.DATABASES["default"]["ENGINE"]
        if "postgresql" not in engine and not options["allow_non_postgres"]:
            raise CommandError(
                "The reference database is Supabase/PostgreSQL. "
                "Set DATABASE_URL or DB_ENGINE=postgres before running this command."
            )

        self.stdout.write(f"Applying {len(migration_files)} unchanged reference migrations...")
        with connection.cursor() as cursor:
            for migration_file in migration_files:
                sql = migration_file.read_text(encoding="utf-8")
                self.stdout.write(f"Applying {migration_file.name}")
                cursor.execute(sql)

        self.stdout.write(self.style.SUCCESS("Reference database schema applied successfully."))
