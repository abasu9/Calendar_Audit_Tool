"""Configure the calendar-sync Django application."""

from django.apps import AppConfig


class CalsyncConfig(AppConfig):
    """Identify the sync app and its default database key type."""

    name = 'calsync'
