"""Configure the calendar-audit Django application."""

from django.apps import AppConfig


class CalauditConfig(AppConfig):
    """Identify the audit app and its default database key type."""

    name = 'calaudit'
