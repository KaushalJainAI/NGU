# Local Development Setup Guide

Django REST Framework backend for NGU Spices.

---

## Prerequisites

- Python 3.11+
- PostgreSQL 15+ (required; SQLite not supported — the app relies on PG-specific features)
- Redis (optional locally; falls back to in-memory cache)
- Node.js 18+ (for Frontend / Admin Panel)
- Docker + Docker Compose (optional — can run Redis and Postgres via Docker)

---

## Quick Start (Manual — Recommended for Dev)

### 1. Clone & enter the repo

```bash
cd NGU/Backend
```

### 2. Create a virtual environment

```bash
python -m venv venv

# Windows:
venv\Scripts\activate
# macOS/Linux:
source venv/bin/activate
```

### 3. Install dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### 4. Set up environment variables

A ready-to-use local dev env file is provided. Copy it:

```bash
# Windows:
copy .env.dev .env
# macOS/Linux:
cp .env.dev .env
```

`.env.dev` configures:
- `DEBUG=True`, SQLite-free local Postgres (`ngu_local` on `127.0.0.1:5432`)
- Redis at `127.0.0.1:6379`
- `USE_CLOUDINARY=False` / `USE_S3=False` — media stored locally
- Email printed to console (no SMTP needed)
- LLM key left blank (AI features gracefully disabled)

Edit `.env` to fill in `LLM_API_KEY` if you want AI search/assistant locally.

### 5. Start Redis + Postgres (via Docker, optional)

If you don't have Postgres/Redis installed natively:

```bash
# From the NGU root — starts only redis (postgres is commented out in compose)
docker-compose up redis -d
```

For Postgres, either install it natively or uncomment the `postgres` service in
`docker-compose.yml` and start it:

```bash
docker-compose up redis postgres -d
```

Then create the local database:

```bash
psql -U postgres -c "CREATE USER ngu WITH PASSWORD 'ngu_local_pw';"
psql -U postgres -c "CREATE DATABASE ngu_local OWNER ngu;"
```

### 6. Run migrations & create superuser

```bash
python manage.py migrate
python manage.py createsuperuser
```

### 7. (Optional) Warm the AI search knowledge base

```bash
python manage.py populate_search_kb
```

Requires `LLM_API_KEY` in `.env`. Skip if you don't have a key — search falls back
to name/slug/token matching.

### 8. Run the backend

```bash
python manage.py runserver
```

- **API**: `http://localhost:8000/api/`
- **Django Admin**: `http://localhost:8000/admin/`
- **Swagger Docs**: `http://localhost:8000/api/docs/` (DEBUG mode only)

---

## Running the Frontend / Admin Panel

```bash
# Customer storefront — http://localhost:5173
cd Frontend/nidhi-brand-forge
npm install
npm run dev

# Admin panel — http://localhost:5174
cd "Admin Panel/e-commerce-command-center"
npm install
npm run dev
```

Both Vite apps pick up `VITE_API_URL` from their local `.env.development` files.

---

## Running with Docker Compose

`docker-compose.yml` is a full-stack compose (production-style) that puts the
frontend on port 80 and keeps backend/admin internal.  It requires a
`DATABASE_URL` env var pointing at an external Postgres instance.

It is **not** the recommended local dev workflow; use the manual approach above
unless you specifically need to test the Dockerised build.

```bash
# From NGU root — provide your DATABASE_URL in the shell or a root .env
DATABASE_URL=postgresql://ngu:ngu_local_pw@localhost:5432/ngu_local docker-compose up --build
```

Accessible endpoints when running via Docker Compose:
- **Frontend + API (proxied)**: `http://localhost`
- **Admin Panel**: not published to a host port by default

---

## Full Environment Variable Reference

`Backend/.env.example` is the canonical reference. Key vars:

```env
# --- Core ---
SECRET_KEY=your-50-char-random-key    # generate: python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1
CORS_ALLOWED_ORIGINS=http://localhost:5173,http://localhost:5174
CSRF_TRUSTED_ORIGINS=http://localhost:5173,http://localhost:5174,http://localhost:8000
SECURE_SSL_REDIRECT=False

# --- Database (PostgreSQL required) ---
DB_ENGINE=django.db.backends.postgresql
DB_NAME=ngu_local
DB_USER=ngu
DB_PASSWORD=ngu_local_pw
DB_HOST=127.0.0.1
DB_PORT=5432

# --- Redis (optional) ---
REDIS_URL=redis://127.0.0.1:6379/0

# --- Media storage ---
USE_CLOUDINARY=False         # True in production (hard startup dependency)
# CLOUDINARY_CLOUD_NAME=...
# CLOUDINARY_API_KEY=...
# CLOUDINARY_API_SECRET=...

USE_S3=False                 # True in production for static files
# AWS_ACCESS_KEY_ID=...
# AWS_SECRET_ACCESS_KEY=...
# AWS_STORAGE_BUCKET_NAME=...
# AWS_S3_REGION_NAME=ap-south-1

# --- Email ---
EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend  # prints to terminal in dev

# --- Payments ---
# RAZORPAY_KEY_ID=...
# RAZORPAY_KEY_SECRET=...

# --- AI (search synonyms + shopping assistant) ---
# LLM_API_KEY=...
MODEL_PROVIDER=openrouter
LLM_MODEL=openai/gpt-4o-mini
# Optional: override model used specifically by the assistant
# ASSISTANT_MODEL_PROVIDER=openrouter
# ASSISTANT_LLM_MODEL=openai/gpt-4o-mini

# --- Google OAuth (optional for local dev) ---
# GOOGLE_CLIENT_ID=...
# GOOGLE_CLIENT_SECRET=...
```

---

## Project Structure

```
Backend/
├── spices_backend/      # Project config (settings, urls, wsgi)
├── users/               # Auth, profiles, JWT, Google OAuth
├── products/            # Catalog, search engine, recommendations
├── cart/                # Shopping cart, favorites
├── orders/              # Order lifecycle, coupons
├── payments/            # Razorpay, payment methods
├── reviews/             # Verified-purchase reviews
├── admin_panel/         # Dashboard, coupons, policies
├── support/             # Contact forms, order-scoped chat
├── assistant/           # AI shopping assistant
├── analytics/           # Behavioral event ingest
├── docs/                # This documentation
├── requirements.txt
├── manage.py
├── .env.dev             # Safe local dev defaults (no real secrets)
├── .env.example         # Full env var reference
└── Dockerfile
```

---

## Running Tests

The project uses `pytest` for all unit, integration, and E2E tests.

### 1. Run unit and integration tests (SQLite in-memory)
By default, tests run against an in-memory SQLite database. This is fast and requires no external services:
```bash
pytest
```
*Note: SQLite does not support true concurrency row-level locking. The test `orders/test_concurrency.py::test_G5_single_use_coupon_not_over_redeemed` will fail under SQLite due to database table locks.*

### 2. Run tests against PostgreSQL (Recommended)
To run the full test suite, including database concurrency checks under realistic production-style conditions:
1. Start the PostgreSQL test database container:
   ```bash
   docker compose up -d db
   ```
2. Run pytest with the `TEST_DB` env variable set to `postgres`:
   ```bash
   # On macOS/Linux:
   TEST_DB=postgres pytest
   
   # On Windows PowerShell:
   $env:TEST_DB="postgres"; pytest
   ```

### 3. Run the complete E2E & Security Audit
The project includes a test pyramid orchestrator that migrates a temporary DB, seeds a test catalog, launches a local server, and runs both unit and E2E/security test suites:
```bash
# From the repository root
Backend/venv/Scripts/python testing/tools/run_full_audit.py
```
This generates a consolidated test run transcript at `testing/reports/session_transcript.txt`.

---

## Useful Management Commands

```bash
# Migrations
python manage.py makemigrations
python manage.py migrate

# Superuser
python manage.py createsuperuser

# Static files (production)
python manage.py collectstatic

# AI search KB
python manage.py populate_search_kb          # warm KB for all products
python manage.py populate_search_kb --force  # force regenerate even fresh entries

# Media migration (one-time, S3 → Cloudinary)
python manage.py migrate_s3_to_cloudinary
python manage.py migrate_s3_to_cloudinary --apply

# Django shell
python manage.py shell
```

---

## Common Issues

| Issue | Solution |
|-------|----------|
| `ModuleNotFoundError: No module named 'decouple'` | `pip install python-decouple` |
| `No such table: auth_user` | `python manage.py migrate` |
| Backend crash-loops in Docker | Missing `CLOUDINARY_*` env vars — check `docker logs ngu-backend` |
| Search returns no results | Run `python manage.py populate_search_kb` to warm the KB |
| Port 8000 already in use | `python manage.py runserver 8001` |
| `connection refused` on DB | Ensure Postgres is running and `DB_*` vars match your local instance |

---

## Important Notes

1. **Never commit `.env`** — it is in `.gitignore`; use `.env.dev` as your starting point
2. **PostgreSQL is required** — SQLite is not supported (app uses PG-specific features)
3. **Cloudinary is a hard dependency in production** — `USE_CLOUDINARY=True` with all three `CLOUDINARY_*` vars required; locally set `USE_CLOUDINARY=False`
4. **`SECRET_KEY` must be unique and long** — `.env.dev` ships a placeholder; change it for any shared or deployed environment
5. **`DEBUG=False` in production** — also set `ALLOWED_HOSTS` to your real domain
