"""CI/local test settings that avoid the in-memory SQLite locking that the
full suite hits under load (see test_settings docstring).

Uses a file-backed SQLite test database with a busy timeout, which lets the
constraint-validation read cursor coexist with the save transaction instead of
deadlocking the single in-memory connection.

    pytest --ds=spices_backend.citest_settings
"""
import os
import tempfile

from .test_settings import *  # noqa: F401,F403

# Only override when not explicitly targeting Postgres.
if os.getenv("TEST_DB") != "postgres":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": os.path.join(tempfile.gettempdir(), "ngu_citest.sqlite3"),
            "OPTIONS": {"timeout": 30},
            "TEST": {"NAME": os.path.join(tempfile.gettempdir(), "ngu_citest.sqlite3")},
        }
    }
