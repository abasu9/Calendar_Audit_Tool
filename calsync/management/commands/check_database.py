"""Provide a safe command for checking the configured PostgreSQL connection."""

from django.core.management.base import BaseCommand, CommandError
from django.db import connection


class Command(BaseCommand):
    """Query basic server details without printing the connection password."""

    help = "Check the configured PostgreSQL/Supabase database connection."

    def handle(self, *args, **options):
        """Open the connection and print safe database and SSL details.

        A single query reads the database name, user, server version, and SSL
        state. Connection failures are returned as Django command errors.
        """
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
