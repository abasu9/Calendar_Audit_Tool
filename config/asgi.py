"""Expose the ASGI application used by asynchronous web servers.

Loading Django's ASGI factory with the project settings creates the callable
that a deployment server imports as ``application``.
"""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

application = get_asgi_application()
