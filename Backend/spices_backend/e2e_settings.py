"""Settings for running a LOCAL live server that the HTTP e2e/security suite
(in ../testing) can target.

Unlike test_settings (in-memory SQLite, per-process), this uses a file-backed
SQLite database so a separate `runserver` process and the seed script share the
same data. Media/static cloud backends are disabled so the server boots with no
external credentials.

Usage:
    USE_CLOUDINARY=False SECRET_KEY=e2e-insecure \
        python manage.py migrate --settings=spices_backend.e2e_settings
    python manage.py runserver 8011 --settings=spices_backend.e2e_settings
"""
import os

# Disable cloud storage + supply a throwaway secret BEFORE settings imports,
# so the `config()` calls in settings.py resolve without real credentials.
os.environ.setdefault("USE_CLOUDINARY", "False")
os.environ.setdefault("USE_S3", "False")
os.environ.setdefault("SECRET_KEY", "e2e-insecure-do-not-use-in-prod")

from .settings import *  # noqa: F401,F403

TESTING = True
DEBUG = False  # keep prod-like so the "DEBUG is off" security probe is meaningful
ALLOWED_HOSTS = ["*"]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": str(BASE_DIR / "e2e_db.sqlite3"),  # noqa: F405
    }
}

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "e2e",
    }
}

# Local filesystem media so product images don't require Cloudinary.
USE_CLOUDINARY = False
USE_S3 = False

# Relax the auth/registration throttles so the functional e2e flows (which
# register + log in many throwaway users in quick succession) are not blocked
# by the production rate limits. The real limits are still asserted to EXIST in
# the security audit; the dedicated throttle probe (security suite) tolerates a
# relaxed env by skipping rather than failing.
try:
    REST_FRAMEWORK = {**REST_FRAMEWORK}  # noqa: F405
    REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"] = {
        **REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"],
        "anon": "100000/hour",
        "user": "1000000/hour",
        "login": "100000/min",
        "register": "100000/min",
        "contact": "100000/min",
        "assistant": "100000/min",
        "order": "100000/min",
        "order_day": "100000/day",
        "cart_write": "100000/min",
    }
except (NameError, KeyError):  # pragma: no cover - settings shape changed
    pass
