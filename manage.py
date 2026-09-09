#!/usr/bin/env python
"""Run Django management commands with this project's settings.

The script selects ``config.settings`` and passes the command-line arguments to
Django's command runner.
"""
import os
import sys


def main():
    """Start Django's command runner using the arguments supplied by the user.

    The function selects the settings module, imports Django, and forwards
    ``sys.argv`` so built-in and project commands run in the same way.
    """
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
