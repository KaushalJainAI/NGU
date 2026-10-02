# Local development

Run the whole backend on your machine against a **local** Postgres + Redis
(Docker), with no dependency on the remote/production database.

## Prerequisites

- Docker Desktop (running)
- Python venv already set up at `Backend/venv`

## 1. Start the local services (Postgres + Redis)

```bash
docker compose up -d        # starts postgres on :5432, redis on :6379
docker compose ps           # both should be "healthy"
```

Data persists in named volumes across restarts. To wipe it: `docker compose down -v`.

## 2. Point the app at the local services

Use the provided template (no real secrets in it):

```bash
cp .env.dev .env
```

`.env.dev` sets `DB_HOST=127.0.0.1`, the local Redis URL, and disables
Cloudinary/S3 so media is stored on local disk (`Backend/media/`).

> Paste an `LLM_API_KEY` into `.env` if you want to exercise the AI assistant /
> search-synonym features; otherwise they degrade gracefully.

## 3. Migrate and run

```bash
python manage.py migrate
python manage.py createsuperuser     # optional: for /admin and admin-only APIs
python manage.py runserver
```

App: http://127.0.0.1:8000/api/  •  Admin: http://127.0.0.1:8000/admin/

The local DB starts empty. Add data via the Django admin, or load a fixture if
you have one (`python manage.py loaddata <fixture>`).

## 4. Run the tests

Two modes:

```bash
# Fast, no services needed (in-memory SQLite) — same as CI:
pytest --ds=spices_backend.test_settings

# Against the local Postgres (matches prod; avoids SQLite "database is locked"
# flakiness and runs ~10x faster on the full suite):
TEST_DB=postgres pytest --ds=spices_backend.test_settings
```

On Windows PowerShell, set the env var first:

```powershell
$env:TEST_DB="postgres"; pytest --ds=spices_backend.test_settings
```

## Homepage product placement (admin-curated)

Admins control which products appear in each homepage section **and their order**:

1. `/admin/` → **Product Sections** → open or create a section.
2. In the **Product section placements** inline, add products and **drag the
   handle** to reorder them. `position` is saved automatically.
3. The order flows through `GET /api/products/sections/` (and `ProductSection.get_products()`).

Section order on the page itself is controlled by each section's `display_order`.

## Notes

- `docker-compose.yml` runs only the stateful services; Django runs on the host
  for fast autoreload. The `Dockerfile` is for production/container builds.
- Credentials in `docker-compose.yml` / `.env.dev` are local throwaways — never
  reuse production secrets locally.
