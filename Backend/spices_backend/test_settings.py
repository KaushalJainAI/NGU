"""Settings for local test runs.

Default: in-memory SQLite + locmem cache (fast, no services needed — used by CI).

    pytest --ds=spices_backend.test_settings

Set TEST_DB=postgres to run the suite against the local docker-compose Postgres
instead. Postgres avoids the SQLite ":memory:" "database is locked" failures that
appear under full-suite load, and matches production more closely:

    docker compose up -d
    TEST_DB=postgres pytest --ds=spices_backend.test_settings

The developer .env may point DB_HOST at a remote Postgres; the SQLite default
guarantees tests never create/drop databases there unless you opt in above.
"""
import os
from .settings import *  # noqa: F401,F403

# Marks the test environment. Used to skip real background threads / LLM calls
# (see products.utils.run_in_background).
TESTING = True

if os.getenv('TEST_DB') == 'postgres':
    # Reuse the DATABASES already built from env by .settings (local docker PG).
    # pytest-django will create/destroy a test_<DB_NAME> database there.
    pass
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': ':memory:',
        }
    }

CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'tests',
    }
}

# Speed up user fixtures
PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']

# Tests must never touch the network. The base settings point media storage at
# Cloudinary (USE_CLOUDINARY defaults True); without this override, every fixture
# that attaches an image uploads to the real Cloudinary account — slow, flaky, and
# rate-limited. In-memory storage keeps the uploaded filename (so extension
# validators still see e.g. ".jpg") while staying entirely offline.
USE_CLOUDINARY = False
USE_S3 = False
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
