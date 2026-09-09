"""Define database models owned by the calendar-audit app.

Audit reports currently read the synchronized models from ``calsync``, so this
module does not define its own tables.
"""

from django.db import models
