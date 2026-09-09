"""Verify the configured database connection without exposing credentials."""

from django.core.management.base import BaseCommand, CommandError
from django.db import connection


class Command(BaseCommand):
    help = "Check the configured PostgreSQL/Supabase database connection."

    def handle(self, *args, **options):
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        current_database(),
                        current_user,
                        current_setting('server_version'),
                        COALESCE(
                            (SELECT ssl FROM pg_stat_ssl WHERE pid = pg_backend_pid()),
                            FALSE
                        )
                    """
                )
                database_name, database_user, server_version, ssl_enabled = (
                    cursor.fetchone()
                )
        except Exception as exc:
            raise CommandError(f"Database connection failed: {exc}") from exc

        self.stdout.write(self.style.SUCCESS("Database connection successful."))
        self.stdout.write(f"  Database: {database_name}")
        self.stdout.write(f"  User: {database_user}")
        self.stdout.write(f"  PostgreSQL: {server_version}")
        self.stdout.write(f"  SSL: {'enabled' if ssl_enabled else 'disabled'}")
