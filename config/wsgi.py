"""Expose the WSGI application used by traditional web servers.

Loading Django's WSGI factory with the project settings creates the callable
that a deployment server imports as ``application``.
"""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

application = get_wsgi_application()
