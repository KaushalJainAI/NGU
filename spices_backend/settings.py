from pathlib import Path
from datetime import timedelta
import os
from decouple import config
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent

# Security Settings
SECRET_KEY = config('SECRET_KEY')
DEBUG = config('DEBUG', default=False, cast=bool)
ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='localhost,127.0.0.1').split(',')

# Support for HTTPS when behind a reverse proxy
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
USE_X_FORWARDED_HOST = config('USE_X_FORWARDED_HOST', default=False, cast=bool)

# Application definition
INSTALLED_APPS = [
    # Must precede django.contrib.admin so translated fields appear in the admin.
    'modeltranslation',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.sites',
    
    # Third-party apps
    'rest_framework',
    'rest_framework_simplejwt',
    'rest_framework_simplejwt.token_blacklist',
    'corsheaders',
    'storages',
    'cloudinary_storage',
    'cloudinary',
    'django_filters',
    'adminsortable2',

    # Auth & Social Login
    'allauth',
    'allauth.account',
    'allauth.socialaccount',
    'allauth.socialaccount.providers.google',
    'dj_rest_auth',
    'dj_rest_auth.registration',
    
    # Local apps
    'users.apps.UsersConfig',
    'products.apps.ProductsConfig',
    'cart.apps.CartConfig',
    'orders.apps.OrdersConfig',
    'payments.apps.PaymentsConfig',
    'reviews.apps.ReviewsConfig',
    'admin_panel.apps.AdminPanelConfig',
    'support.apps.SupportConfig',
    'assistant.apps.AssistantConfig',
    'analytics.apps.AnalyticsConfig',
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    # Serve collected static files (Django admin CSS/JS, etc.) directly from
    # gunicorn in production. Must sit immediately after SecurityMiddleware.
    # No-op for URLs outside STATIC_URL, so S3/local media are unaffected.
    'whitenoise.middleware.WhiteNoiseMiddleware',
    # Reject manually-banned IPs early (fail-open).
    'spices_backend.middleware.AbuseGuardMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    # Activates ?lang= / X-Language for modeltranslation content.
    'spices_backend.middleware.LanguageQueryMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'allauth.account.middleware.AccountMiddleware',
]

ROOT_URLCONF = 'spices_backend.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'spices_backend.wsgi.application'

# Database
DATABASES = {
    'default': {
        'ENGINE': config('DB_ENGINE', default='django.db.backends.sqlite3'),
        'NAME': config('DB_NAME', default=str(BASE_DIR / 'db.sqlite3')),
        'USER': config('DB_USER', default=''),
        'PASSWORD': config('DB_PASSWORD', default=''),
        'HOST': config('DB_HOST', default=''),
        'PORT': config('DB_PORT', default=''),
        # Connection pooling - reuse connections for 60 seconds
        # Reduces connection overhead significantly
        'CONN_MAX_AGE': 60,
        'CONN_HEALTH_CHECKS': True,  # Django 4.1+ - check connection health
    }
}


# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

# Internationalization
LANGUAGE_CODE = 'en'
TIME_ZONE = 'Asia/Kolkata'
USE_I18N = True
USE_TZ = True

# Languages the storefront content can be translated into. Mirrors the frontend
# src/i18n SUPPORTED_LANGUAGES and the chat assistant language codes.
LANGUAGES = [
    ('en', 'English'),
    ('hi', 'Hindi'),
    ('hinglish', 'Hinglish'),
    ('gu', 'Gujarati'),
    ('mr', 'Marathi'),
    ('pa', 'Punjabi'),
]

# django-modeltranslation: per-language columns for Product/Category content.
MODELTRANSLATION_DEFAULT_LANGUAGE = 'en'
MODELTRANSLATION_LANGUAGES = ('en', 'hi', 'hinglish', 'gu', 'mr', 'pa')
# Any empty translation transparently falls back to English so newly added
# products (and untranslated fields) always render.
MODELTRANSLATION_FALLBACK_LANGUAGES = ('en',)

# Media / static storage configuration
#
# Media files (product/category/profile images, chat attachments) are served from
# Cloudinary's image CDN when USE_CLOUDINARY is on (the storefront default), giving
# fast global delivery. Static files (CSS/JS) continue to use S3 or local storage.
#
# Precedence for the `default` (media) storage backend:
#   USE_CLOUDINARY  ->  Cloudinary   (preferred)
#   USE_S3          ->  AWS S3
#   neither         ->  local filesystem
USE_CLOUDINARY = config('USE_CLOUDINARY', default=True, cast=bool)
USE_S3 = config('USE_S3', default=False, cast=bool)

# --- Self-hosted voice transcription (whisper.cpp) ---
# When enabled, the assistant's voice input is transcribed by the local whisper
# container (small-q5 model) instead of the browser Web Speech API. Off by
# default so dev environments without the container fall back to text.
USE_SELF_HOSTED_STT = config('USE_SELF_HOSTED_STT', default=False, cast=bool)
WHISPER_URL = config('WHISPER_URL', default='http://whisper:8080/inference')
WHISPER_TIMEOUT = config('WHISPER_TIMEOUT', default=30, cast=int)

if USE_CLOUDINARY:
    CLOUDINARY_STORAGE = {
        'CLOUD_NAME': config('CLOUDINARY_CLOUD_NAME'),
        'API_KEY': config('CLOUDINARY_API_KEY'),
        'API_SECRET': config('CLOUDINARY_API_SECRET'),
        'PREFIX': 'ngu',  # namespace all NGU media under the ngu/ folder in Cloudinary
    }

if USE_S3:
    AWS_ACCESS_KEY_ID = config('AWS_ACCESS_KEY_ID')
    AWS_SECRET_ACCESS_KEY = config('AWS_SECRET_ACCESS_KEY')
    AWS_STORAGE_BUCKET_NAME = config('AWS_STORAGE_BUCKET_NAME')
    AWS_S3_REGION_NAME = config('AWS_S3_REGION_NAME', default='ap-south-1')
    AWS_S3_SIGNATURE_VERSION = config('AWS_S3_SIGNATURE_VERSION', default='s3v4')
    
    AWS_S3_CUSTOM_DOMAIN = f'{AWS_STORAGE_BUCKET_NAME}.s3.{AWS_S3_REGION_NAME}.amazonaws.com'
    AWS_S3_OBJECT_PARAMETERS = {'CacheControl': 'max-age=86400'}
    AWS_DEFAULT_ACL = None  # Use bucket policy instead of ACL (AWS default)
    AWS_S3_FILE_OVERWRITE = False
    AWS_QUERYSTRING_AUTH = False  # No signed URLs for public files
    
    # Django 4.2+ / 5.x storage configuration
    STORAGES = {
        "default": {
            "BACKEND": "storages.backends.s3boto3.S3Boto3Storage",
            "OPTIONS": {
                "location": "media",  # Upload media files to 'media/' folder in bucket
            },
        },
        "staticfiles": {
            "BACKEND": "storages.backends.s3boto3.S3StaticStorage",
            "OPTIONS": {
                "location": "static",  # Static files go to 'static/' folder
            },
        },
    }
    
    STATIC_URL = f'https://{AWS_S3_CUSTOM_DOMAIN}/static/'
    MEDIA_URL = f'https://{AWS_S3_CUSTOM_DOMAIN}/media/'
    
    # Also define STATIC_ROOT for collectstatic command
    STATIC_ROOT = BASE_DIR / 'staticfiles'
else:
    STATIC_URL = '/static/'
    STATIC_ROOT = BASE_DIR / 'staticfiles'
    MEDIA_URL = '/media/'
    MEDIA_ROOT = BASE_DIR / 'media'

# Cloudinary takes over the `default` (media) storage backend. Static files keep
# whatever backend the S3/local branch above selected. Because Cloudinary's storage
# returns absolute res.cloudinary.com URLs, MEDIA_URL is unused for media but is left
# defined above as a harmless fallback.
if USE_CLOUDINARY:
    STORAGES = globals().get('STORAGES', {})
    # WhiteNoise storage: compresses collected static and adds cache-busting
    # hashes so gunicorn can serve admin/DRF static with far-future caching.
    STORAGES.setdefault(
        'staticfiles',
        {'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage'},
    )
    STORAGES['default'] = {
        'BACKEND': 'cloudinary_storage.storage.MediaCloudinaryStorage',
    }

# Private media root: LOCAL filesystem storage for admin-only files (e.g. order
# delivery bills) that must never be reachable by customers. Deliberately NOT
# under STATIC_ROOT/MEDIA_ROOT and not exposed via any URL — files here are only
# ever streamed through a staff-gated endpoint. In containers this should be a
# mounted volume so the files survive redeploys.
PRIVATE_MEDIA_ROOT = config('PRIVATE_MEDIA_ROOT', default=str(BASE_DIR / 'private_media'))

# File Upload Configuration.
# DATA_UPLOAD_MAX_MEMORY_SIZE caps non-file request bodies (JSON/form fields) held
# in memory — kept small (10MB) so a malicious oversized JSON payload can't exhaust
# memory. FILE_UPLOAD_MAX_MEMORY_SIZE only governs the in-memory threshold for
# uploaded FILES (images/videos stream past it), so large media uploads still work.
DATA_UPLOAD_MAX_MEMORY_SIZE = config('DATA_UPLOAD_MAX_MEMORY_SIZE', default=10 * 1024 * 1024, cast=int)
FILE_UPLOAD_MAX_MEMORY_SIZE = config('FILE_UPLOAD_MAX_MEMORY_SIZE', default=524288000, cast=int)

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Custom User Model
AUTH_USER_MODEL = 'users.User'
SITE_ID = 1

# Authentication Backends for allauth
AUTHENTICATION_BACKENDS = [
    'django.contrib.auth.backends.ModelBackend',
    'allauth.account.auth_backends.AuthenticationBackend',
]

# REST Framework Configuration
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'users.authentication.CookieJWTAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticatedOrReadOnly',
    ),
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 12,
    'DEFAULT_FILTER_BACKENDS': (
        'django_filters.rest_framework.DjangoFilterBackend',
        'rest_framework.filters.SearchFilter',
        'rest_framework.filters.OrderingFilter',
    ),
    'DEFAULT_RENDERER_CLASSES': (
        'rest_framework.renderers.JSONRenderer',
    ),
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
    # Custom exception handler: returns JSON 400/500 instead of HTML errors
    'EXCEPTION_HANDLER': 'spices_backend.exceptions.custom_exception_handler',
    # SECURITY: number of trusted reverse proxies in front of Django. With this
    # set, DRF derives the throttle identity from the Nth-from-last entry of
    # X-Forwarded-For (counting from the right) instead of concatenating the whole
    # header — so a client-supplied XFF prefix can no longer mint a fresh throttle
    # bucket per request and bypass the login/OTP/order rate limits.
    #   client -> host nginx -> frontend-container nginx -> backend  == 2 hops.
    # Both nginx layers append via `$proxy_add_x_forwarded_for`, so the real
    # client IP is always the 2nd-from-last entry. Override via env ONLY if the
    # proxy topology changes; too low re-opens the spoof, too high reads past our
    # own proxies into client-controlled data. (Requires the backend port to stay
    # bound to loopback so no one can reach Django on a shorter chain.)
    'NUM_PROXIES': config('NUM_PROXIES', default=2, cast=int),
    # Rate Limiting / Throttling
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'anon': '1000/hour',      # Anonymous users: 1000 requests per hour
        'user': '10000/hour',     # Authenticated users: 10000 requests per hour
        'login': '5/minute',     # Login attempts: 5 per minute
        'register': '3/minute',  # Registration: 3 per minute
        'contact': '5/hour',     # Contact form: 5 per hour
        'password_reset': '10/day',  # Password reset OTP: 10 per day
        'assistant': '20/min',   # AI assistant: 20 messages per minute
        'assistant_day': '500/day',  # AI assistant: hard daily cap (cost guard)
        'assistant_stt': config('THROTTLE_ASSISTANT_STT', default='15/min'),  # voice transcription (CPU-heavy)
        'events': '600/hour',    # Behavioral event ingest (batched on client)
        'anon_events': config('THROTTLE_ANON_EVENTS', default='120/min'),  # Anonymous counter beacons (per-IP)
        'search_suggest': '60/min',  # Autocomplete: keystroke-friendly but bounded
        'geocode': '60/hour',    # Reverse-geocode proxy (respects Nominatim policy)
        'order': config('THROTTLE_ORDER', default='10/min'),           # orders placed per minute
        'order_day': config('THROTTLE_ORDER_DAY', default='100/day'),  # daily order ceiling
        'cart_write': config('THROTTLE_CART_WRITE', default='60/min'), # cart mutations / minute
        # Payment endpoints — verify is an HMAC oracle if left unthrottled.
        'payment': config('THROTTLE_PAYMENT', default='20/min'),
    }
}

# JWT Configuration
SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(hours=1),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,
    'UPDATE_LAST_LOGIN': True,
    
    'ALGORITHM': 'HS256',
    'SIGNING_KEY': SECRET_KEY,
    'VERIFYING_KEY': None,
    
    'AUTH_HEADER_TYPES': ('Bearer',),
    'AUTH_HEADER_NAME': 'HTTP_AUTHORIZATION',
    'USER_ID_FIELD': 'id',
    'USER_ID_CLAIM': 'user_id',
    
    'AUTH_TOKEN_CLASSES': ('rest_framework_simplejwt.tokens.AccessToken',),
    'TOKEN_TYPE_CLAIM': 'token_type',
}

# dj-rest-auth configuration.
# NOTE (2026-07-25): the dj-rest-auth ROUTES are no longer mounted in urls.py —
# auth is served entirely by the hand-written views in users/views.py. The apps
# stay in INSTALLED_APPS (allauth wiring depends on them) and this config is kept
# so the settings stay coherent if the routes are ever restored.
REST_AUTH = {
    'USE_JWT': True,
    'TOKEN_MODEL': None,
    'JWT_AUTH_COOKIE': 'access_token',
    'JWT_AUTH_REFRESH_COOKIE': 'refresh_token',
    'JWT_AUTH_HTTPONLY': True,
    'USER_DETAILS_SERIALIZER': 'users.serializers.UserSerializer',
}

# allauth configuration
ACCOUNT_LOGIN_METHODS = {'email'}
ACCOUNT_SIGNUP_FIELDS = ['email*', 'password1*', 'password2*']
ACCOUNT_USER_MODEL_USERNAME_FIELD = 'username'
ACCOUNT_EMAIL_VERIFICATION = 'none'

SOCIALACCOUNT_PROVIDERS = {
    'google': {
        'APP': {
            'client_id': config('GOOGLE_CLIENT_ID', default=''),
            'secret': config('GOOGLE_CLIENT_SECRET', default=''),
            'key': ''
        },
        'SCOPE': [
            'profile',
            'email',
        ],
        'AUTH_PARAMS': {
            'access_type': 'online',
        }
    }
}

# CORS Settings - SECURITY CRITICAL
# In production, CORS_ALLOW_ALL_ORIGINS should ALWAYS be False
CORS_ALLOWED_ORIGINS = config(
    'CORS_ALLOWED_ORIGINS',
    default='http://localhost:5173,http://127.0.0.1:3000,http://localhost:3000,http://localhost:3001'
).split(',')

# WARNING: Set to False in production! True bypasses the whitelist above
CORS_ALLOW_ALL_ORIGINS = config('CORS_ALLOW_ALL_ORIGINS', default=False, cast=bool)
CORS_ALLOW_CREDENTIALS = True

# Allow the storefront's language header (used for modeltranslation content).
from corsheaders.defaults import default_headers as _cors_default_headers
CORS_ALLOW_HEADERS = list(_cors_default_headers) + ['x-language']

CORS_ALLOW_METHODS = [
    'GET',
    'POST',
    'PUT',
    'PATCH',
    'DELETE',
    'OPTIONS'
]

# CSRF Trusted Origins - Required for admin panel login
CSRF_TRUSTED_ORIGINS = config(
    'CSRF_TRUSTED_ORIGINS',
    default='http://localhost:3001,http://localhost:8000,http://127.0.0.1:8000'
).split(',')

# CSRF Cookie Settings
CSRF_COOKIE_HTTPONLY = False
CSRF_COOKIE_SAMESITE = 'Lax'

# -----------------------------------------------------------------------------
# Auth (JWT) cookie attributes — decoupled from DEBUG so they can be tuned per
# deployment without code changes.
#   AUTH_COOKIE_SAMESITE: 'Lax' for same-site (storefront + API on one origin,
#       the current prod setup). Set to 'None' if the storefront is ever served
#       from a different registrable domain than the API (cross-site cookies).
#   AUTH_COOKIE_SECURE: whether the cookie is HTTPS-only. Defaults to "not DEBUG"
#       but is overridable so DEBUG=False on plain HTTP still works. SameSite=None
#       legally requires Secure, so it is force-enabled in that case.
# -----------------------------------------------------------------------------
AUTH_COOKIE_SAMESITE = config('AUTH_COOKIE_SAMESITE', default='Lax')
AUTH_COOKIE_SECURE = config('AUTH_COOKIE_SECURE', default=not DEBUG, cast=bool)
if str(AUTH_COOKIE_SAMESITE).lower() == 'none':
    # Browsers reject SameSite=None cookies without the Secure attribute.
    AUTH_COOKIE_SECURE = True

# =============================================================================
# PRODUCTION SECURITY SETTINGS
# =============================================================================
# These are automatically enabled when DEBUG=False
if not DEBUG:
    # HTTPS Security
    SECURE_BROWSER_XSS_FILTER = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = 'DENY'
    
    # HSTS - Force HTTPS (1 year)
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    
    # Secure cookies — override via env when running on HTTP (no SSL)
    SESSION_COOKIE_SECURE = config('SESSION_COOKIE_SECURE', default=True, cast=bool)
    CSRF_COOKIE_SECURE = config('CSRF_COOKIE_SECURE', default=True, cast=bool)
    
    # SSL redirect (set to False if load balancer handles SSL)
    SECURE_SSL_REDIRECT = config('SECURE_SSL_REDIRECT', default=True, cast=bool)

# Payment Gateway Settings
#
# Both key pairs live in the environment at once; RAZORPAY_TEST_MODE picks which
# pair is active. Flipping that one flag and restarting is the whole switch — no
# other module reads the TEST_/LIVE_ variables, they all consume the resolved
# RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET / RAZORPAY_WEBHOOK_SECRET below.
#
# The webhook secret is per-mode: test and live webhooks are separate endpoints
# in the Razorpay dashboard with different signing secrets. It switches with the
# keys here so a mode flip can't leave the handler verifying against the wrong
# secret (which would fail-closed and silently reject every delivery).
RAZORPAY_TEST_MODE = config('RAZORPAY_TEST_MODE', default=True, cast=bool)

RAZORPAY_TEST_KEY_ID = config('RAZORPAY_TEST_KEY_ID', default='')
RAZORPAY_TEST_KEY_SECRET = config('RAZORPAY_TEST_KEY_SECRET', default='')
RAZORPAY_TEST_WEBHOOK_SECRET = config('RAZORPAY_TEST_WEBHOOK_SECRET', default='')

RAZORPAY_LIVE_KEY_ID = config('RAZORPAY_LIVE_KEY_ID', default='')
RAZORPAY_LIVE_KEY_SECRET = config('RAZORPAY_LIVE_KEY_SECRET', default='')
RAZORPAY_LIVE_WEBHOOK_SECRET = config('RAZORPAY_LIVE_WEBHOOK_SECRET', default='')

if RAZORPAY_TEST_MODE:
    RAZORPAY_KEY_ID = RAZORPAY_TEST_KEY_ID
    RAZORPAY_KEY_SECRET = RAZORPAY_TEST_KEY_SECRET
    RAZORPAY_WEBHOOK_SECRET = RAZORPAY_TEST_WEBHOOK_SECRET
else:
    RAZORPAY_KEY_ID = RAZORPAY_LIVE_KEY_ID
    RAZORPAY_KEY_SECRET = RAZORPAY_LIVE_KEY_SECRET
    RAZORPAY_WEBHOOK_SECRET = RAZORPAY_LIVE_WEBHOOK_SECRET

# Fall back to the flat pre-toggle names so an environment that hasn't been
# migrated to TEST_/LIVE_ yet keeps working instead of booting with no gateway.
if not RAZORPAY_KEY_ID:
    RAZORPAY_KEY_ID = config('RAZORPAY_KEY_ID', default='')
    RAZORPAY_KEY_SECRET = config('RAZORPAY_KEY_SECRET', default='')
    RAZORPAY_WEBHOOK_SECRET = config('RAZORPAY_WEBHOOK_SECRET', default='')

# Guardrail: the flag and the credential must agree. A `rzp_live_` key selected
# while RAZORPAY_TEST_MODE=True means real cards get charged by a build that
# believes it is in test mode, so refuse to boot rather than find out at checkout.
if RAZORPAY_KEY_ID:
    _is_live_key = RAZORPAY_KEY_ID.startswith('rzp_live_')
    if RAZORPAY_TEST_MODE and _is_live_key:
        raise ImproperlyConfigured(
            "RAZORPAY_TEST_MODE=True but the active key is a live key "
            f"({RAZORPAY_KEY_ID[:12]}...). Put test keys in RAZORPAY_TEST_KEY_ID "
            "/ RAZORPAY_TEST_KEY_SECRET, or set RAZORPAY_TEST_MODE=False."
        )
    if not RAZORPAY_TEST_MODE and not _is_live_key:
        raise ImproperlyConfigured(
            "RAZORPAY_TEST_MODE=False but the active key is not a live key "
            f"({RAZORPAY_KEY_ID[:12]}...). Set RAZORPAY_LIVE_KEY_ID to the "
            "rzp_live_ key from the Razorpay dashboard."
        )
    if not RAZORPAY_TEST_MODE and DEBUG:
        raise ImproperlyConfigured(
            "Refusing to run live Razorpay keys with DEBUG=True — this would "
            "charge real cards from a development server."
        )
# L3 reconciliation: an ONLINE order left unpaid longer than this is considered
# abandoned and auto-cancelled (stock released) unless Razorpay shows it captured.
PAYMENT_STUCK_TTL_MINUTES = config('PAYMENT_STUCK_TTL_MINUTES', default=15, cast=int)
# Address that receives payment exception alerts; falls back to EMAIL_HOST_USER.
PAYMENT_ALERT_EMAIL = config('PAYMENT_ALERT_EMAIL', default='') or config('EMAIL_HOST_USER', default='')
# Address that receives store-owner notifications (new orders, daily low-stock
# digest, weekly summary); falls back to EMAIL_HOST_USER like PAYMENT_ALERT_EMAIL.
ADMIN_ALERT_EMAIL = config('ADMIN_ALERT_EMAIL', default='') or config('EMAIL_HOST_USER', default='')

# --- Threshold-based store-owner alerts (all sent to ADMIN_ALERT_EMAIL) ---
# Real-time low-stock alert fires per crossing at checkout (see orders/views.py).
# These tune the other threshold alerts; each is env-overridable.
#
# Defaults are sized for the current business: ~Rs 1 crore/year of orders, which
# at a typical spice AOV of ~Rs 350-450 is ~25,000 orders/year — roughly 65-70
# orders/day, ~3/hour. The idea is "clearly abnormal, worth interrupting the
# owner", not "slightly busy". Bump these via env as volume grows.
#
# Spike of abandoned ONLINE checkouts auto-cancelled in a SINGLE reconcile run
# (every RECONCILE_INTERVAL_MINUTES = 5 min). At ~3 orders/hour a 5-min window
# normally sees <1 order, so 5 auto-cancels at once is a genuine burst (gateway
# down / checkout bug), not chance abandonment.
PAYMENT_STUCK_SPIKE_THRESHOLD = config('PAYMENT_STUCK_SPIKE_THRESHOLD', default=5, cast=int)
# Coupon usage alert: warn when usage_count reaches this % of max_usage (so the
# owner can extend/replace a promo before it runs out mid-campaign).
COUPON_USAGE_ALERT_PERCENT = config('COUPON_USAGE_ALERT_PERCENT', default=90, cast=int)
# (Order-backlog / waiting-chat alerts are covered by the daily digest, so there
# is no separate periodic checker for them.)

# Background scheduler cadence (see `manage.py run_scheduler`). Reconcile runs
# often enough that an abandoned checkout is cancelled within one interval of the
# 15-minute TTL; rollups keep the admin Insights dashboard live.
RECONCILE_INTERVAL_MINUTES = config('RECONCILE_INTERVAL_MINUTES', default=5, cast=int)
ROLLUP_INTERVAL_MINUTES = config('ROLLUP_INTERVAL_MINUTES', default=5, cast=int)
# How far back the NIGHTLY rollup rebuilds. The interval job above only ever
# recomputes today, so this window is the only thing that picks up an order
# changed after the fact — a late cancellation, a corrected courier cost, a
# Recycle Bin restore, a COD cash confirmation. It was 3 days, which meant
# anything corrected after 72h left that day's revenue and GST overstated
# permanently. 35 covers a full month plus slack; `check_rollup_drift` reports it
# if something ever reaches back further still.
ROLLUP_BACKFILL_DAYS = config('ROLLUP_BACKFILL_DAYS', default=35, cast=int)
# Admin Recycle Bin retention: a soft-deleted order/product/combo is permanently
# purged this many days after it was deleted (rolling per-item). The scheduler
# runs purge_recycle_bin nightly. 0 disables the purge entirely.
RECYCLE_BIN_RETENTION_DAYS = config('RECYCLE_BIN_RETENTION_DAYS', default=30, cast=int)
# Storefront base URL for links embedded in customer payment/order emails.
# Defaults to the live storefront so emails never leak a localhost link when the
# env var is unset (prod compose doesn't set it); override in local dev via .env.
FRONTEND_URL = config('FRONTEND_URL', default='https://nidhimasala.com')

# Email Configuration
EMAIL_BACKEND = config('EMAIL_BACKEND', default='django.core.mail.backends.console.EmailBackend')
EMAIL_HOST = config('EMAIL_HOST', default='smtp.gmail.com')
EMAIL_PORT = config('EMAIL_PORT', default=587, cast=int)
EMAIL_HOST_USER = config('EMAIL_HOST_USER', default='')
EMAIL_HOST_PASSWORD = config('EMAIL_HOST_PASSWORD', default='')
EMAIL_USE_TLS = config('EMAIL_USE_TLS', default=True, cast=bool)
DEFAULT_FROM_EMAIL = EMAIL_HOST_USER


# Logging
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {process:d} {thread:d} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
    # S3/AWS logging - captures upload failures and connection issues
    'loggers': {
        'boto3': {
            'handlers': ['console'],
            'level': 'WARNING',  # Change to DEBUG for verbose S3 debugging
            'propagate': False,
        },
        'botocore': {
            'handlers': ['console'],
            'level': 'WARNING',  # Change to DEBUG for verbose S3 debugging
            'propagate': False,
        },
        's3transfer': {
            'handlers': ['console'],
            'level': 'WARNING',  # Change to DEBUG for transfer details
            'propagate': False,
        },
        'storages': {
            'handlers': ['console'],
            'level': 'DEBUG',  # Django-storages logging
            'propagate': False,
        },
    },
}

# =============================================================================
# CACHE CONFIGURATION
# =============================================================================
# Redis caching - works on both Windows (Memurai) and Linux
# Set REDIS_URL in .env to enable Redis, otherwise falls back to local memory cache
#
# Examples:
#   - Local development: REDIS_URL=redis://127.0.0.1:6379/0
#   - Production Linux:  REDIS_URL=redis://redis-server:6379/0
#   - With password:     REDIS_URL=redis://:password@host:6379/0

REDIS_URL = config('REDIS_URL', default='')

if REDIS_URL:
    CACHES = {
        'default': {
            'BACKEND': 'django_redis.cache.RedisCache',
            'LOCATION': REDIS_URL,
            'OPTIONS': {
                'CLIENT_CLASS': 'django_redis.client.DefaultClient',
                # Connection settings
                'SOCKET_CONNECT_TIMEOUT': 5,
                'SOCKET_TIMEOUT': 5,
                'RETRY_ON_TIMEOUT': True,
                # Serialization
                'SERIALIZER': 'django_redis.serializers.json.JSONSerializer',
            },
            'KEY_PREFIX': 'ngu',
            'TIMEOUT': 300,  # 5 minutes default timeout
        }
    }
    # Use Redis for sessions too (optional, for better performance)
    SESSION_ENGINE = 'django.contrib.sessions.backends.cache'
    SESSION_CACHE_ALIAS = 'default'
else:
    # Fallback to local memory cache (for development without Redis)
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
            'LOCATION': 'unique-snowflake',
        }
    }

# Cache timeout constants (in seconds)
CACHE_TTL_SHORT = 60          # 1 minute - for frequently changing data
CACHE_TTL_MEDIUM = 300        # 5 minutes - for product lists
CACHE_TTL_LONG = 900          # 15 minutes - for categories, static data
CACHE_TTL_DASHBOARD = 120     # 2 minutes - for dashboard stats
CACHE_TTL_INSIGHTS = 300      # 5 minutes - for analytics insights endpoints

# Analytics / geocoding runtime knobs.
ANALYTICS_MAX_BATCH = config('ANALYTICS_MAX_BATCH', default=50, cast=int)
NOMINATIM_URL = config('NOMINATIM_URL', default='https://nominatim.openstreetmap.org/reverse')
NOMINATIM_USER_AGENT = config('NOMINATIM_USER_AGENT', default='NidhiMasala/1.0 (nidhimasala.com)')

# Invoice issuer details. Defaults are the current registered business details;
# override per deployment if billing identity changes.
SELLER_NAME = config('SELLER_NAME', default='Nidhi Grah Udyog')
SELLER_PROPRIETOR = config('SELLER_PROPRIETOR', default='Lalit Kumar Jain')
SELLER_TAGLINE = config('SELLER_TAGLINE', default='Pure & Authentic Indian Spices')
SELLER_ADDRESS = config('SELLER_ADDRESS', default='7, Industrial Area, Runija Road,<br/>Barnagar, Ujjain, Madhya Pradesh 456771')
SELLER_GSTIN = config('SELLER_GSTIN', default='23ABUPJ8925C1ZI')
SELLER_FSSAI = config('SELLER_FSSAI', default='11414730000288')
SELLER_STATE = config('SELLER_STATE', default='Madhya Pradesh')
SELLER_STATE_CODE = config('SELLER_STATE_CODE', default='23')
SELLER_EMAIL = config('SELLER_EMAIL', default='nidhispicesandfood@gmail.com')
SELLER_PHONE = config('SELLER_PHONE', default='+91 93000 05040')

# Prefix of the GST invoice serial: "<prefix>/<FY>/<6 digits>", e.g.
# NM/25-26/000123. Read from the environment because orders/invoicing.py resolves
# it via getattr(settings, ...) — without this line an INVOICE_NUMBER_PREFIX set
# in .env.backend is silently ignored and every invoice falls back to 'NM'.
#
# ⚠ DECIDE THIS BEFORE THE FIRST INVOICE IS ISSUED. The value is baked into every
# number in the series, and a GST series must be continuous within the financial
# year — changing the prefix later splits it in two, which is exactly the thing a
# numbered series exists to prevent. Max 3 chars: GST caps the whole number at 16
# and the FY plus sequence already take 13.
INVOICE_NUMBER_PREFIX = config('INVOICE_NUMBER_PREFIX', default='NM')

# Coarse IP -> region lookups for anonymous-traffic analytics (MaxMind GeoLite2).
# Optional: if the .mmdb is absent the analytics module degrades gracefully and
# simply omits the geo dimension. See analytics/geoip.py and ANALYTICS.md.
GEOIP_PATH = config('GEOIP_PATH', default=str(BASE_DIR / 'geoip'))

# Triggering auto-reload again to pick up .env changes
