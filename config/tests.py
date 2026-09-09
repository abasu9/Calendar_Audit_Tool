"""Tests for project-level configuration helpers."""

from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase

from config.database import database_config_from_env


class DatabaseConfigTests(SimpleTestCase):
    def test_uses_discrete_postgres_variables_without_database_url(self):
        config = database_config_from_env(
            {
                "POSTGRES_DB": "calendar_audit",
                "POSTGRES_USER": "calendar_user",
                "POSTGRES_PASSWORD": "secret",
                "POSTGRES_HOST": "localhost",
                "POSTGRES_PORT": "5433",
            }
        )

        self.assertEqual(config["NAME"], "calendar_audit")
        self.assertEqual(config["USER"], "calendar_user")
        self.assertEqual(config["HOST"], "localhost")
        self.assertEqual(config["PORT"], "5433")

    def test_parses_supabase_session_pooler_url_and_requires_ssl(self):
        config = database_config_from_env(
            {
                "DATABASE_URL": (
                    "postgresql://postgres.project%2Dref:p%40ssword@"
                    "aws-0-us-east-1.pooler.supabase.com:5432/postgres"
                )
            }
        )

        self.assertEqual(config["NAME"], "postgres")
        self.assertEqual(config["USER"], "postgres.project-ref")
        self.assertEqual(config["PASSWORD"], "p@ssword")
        self.assertEqual(config["OPTIONS"]["sslmode"], "require")
        self.assertNotIn("DISABLE_SERVER_SIDE_CURSORS", config)

    def test_configures_transaction_pooler_safely(self):
        config = database_config_from_env(
            {
                "DATABASE_URL": (
                    "postgres://postgres.project:secret@"
                    "aws-0-us-east-1.pooler.supabase.com:6543/postgres"
                    "?sslmode=verify-full&sslrootcert=/tmp/supabase.crt"
                ),
                "DB_CONN_MAX_AGE": "0",
            }
        )

        self.assertTrue(config["DISABLE_SERVER_SIDE_CURSORS"])
        self.assertIsNone(config["OPTIONS"]["prepare_threshold"])
        self.assertEqual(config["OPTIONS"]["sslmode"], "verify-full")
        self.assertEqual(
            config["OPTIONS"]["sslrootcert"], "/tmp/supabase.crt"
        )

    def test_database_url_takes_precedence(self):
        config = database_config_from_env(
            {
                "DATABASE_URL": "postgresql://remote:secret@db.example.com/app",
                "POSTGRES_DB": "local_database",
            }
        )

        self.assertEqual(config["NAME"], "app")
        self.assertEqual(config["HOST"], "db.example.com")

    def test_rejects_non_postgres_url(self):
        with self.assertRaisesMessage(
            ImproperlyConfigured, "DATABASE_URL must start with"
        ):
            database_config_from_env(
                {"DATABASE_URL": "mysql://user:secret@db.example.com/app"}
            )
