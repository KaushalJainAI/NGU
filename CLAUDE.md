# NGU — Nidhi Masala Spices E-commerce

Full-stack e-commerce platform for Nidhi Masala, an Indian spice brand.

## Project layout

```
NGU/
├── Backend/              # Django REST Framework API
├── Frontend/             # React + Vite customer storefront (nidhi-brand-forge)
├── Admin Panel/          # React + Vite admin dashboard (e-commerce-command-center)
├── learning/             # HLD, LLD, interview kit, lessons (all teaching material)
├── testing/              # Black-box e2e + security suites (never run against prod)
├── whisper/              # Dockerfile for the self-hosted speech-to-text fallback
├── README.md                     # What the project is + a map of every doc
├── docker-compose.yml            # Local development stack
├── docker-compose.prod.yml       # Production stack (pre-built images)
├── DEPLOYMENT.md                 # EC2 deployment guide
├── TROUBLESHOOTING_AWS_MIGRATION.md
└── DATABASE_FILLING.md           # Catalog content update (2026-06-11)
```

## Repository (one git repo since 2026-10-02)

- **The NGU root is the git repository.** `Backend/`, `Frontend/nidhi-brand-forge/`
  and `Admin Panel/e-commerce-command-center/` are ordinary folders in it. Run git
  from the root; a feature that touches several parts is ONE commit.
- The three were separate repos until 2026-10-02. Their histories (89 + 84 + 43
  commits) were merged in under their folders, so `git blame` works back to the
  first commit. A path-limited `git log` stops at the merge unless given the old
  path too: `git log --full-history -- orders/views.py Backend/orders/views.py`.
- ⚠ **No remote is configured.** Nothing has been pushed. The old GitHub repos
  (`NGU_Backend`, `nidhi-brand-forge`, `e-commerce-command-center`) still exist
  and stop at the pre-merge commits (`134df35` / `8a5362d` / `3e3f2db`).
- `.git-backup/` (ignored) holds the three old `.git` folders: their branches, one
  backend stash, and the links for the worktrees `../NGU-Backend-audit`,
  `../NGU-Storefront-audit`, `../NGU-Panel-audit`. To use one:
  `git --git-dir=.git-backup/Backend.git <command>`. Don't delete the folder
  until those branches are known to be unneeded.
- ⚠ **Never commit**: any `.env*` (only `*.example` templates are tracked), `*.pem`,
  the access-key CSV, root PDFs (the GST certificate is one of them), admin panel
  screenshots. All are in `.gitignore`; check `git status` before `git add -A`.
  Docs must use placeholders for credentials — DEPLOYMENT.md once held a real
  Google client secret and an AWS access key id. Both were replaced with
  placeholders before the first commit, so neither is in this repo's history.
- Line endings: root `.gitattributes` pins LF for `*.sh`, `nginx.conf`, `Dockerfile`
  (the two frontends repeat it). See "Line endings" under the 2026-10-02 deploy.
- Images are still built per folder (`./Backend`, `./Frontend/nidhi-brand-forge`,
  `./Admin Panel/e-commerce-command-center`) — the build commands below are unchanged.

## Backend apps

| App | Purpose |
|-----|---------|
| `users` | Auth, profiles, JWT, Google OAuth |
| `products` | Catalog: products, combos, categories (+`extra_categories` multi-shelf), images, sections, search KB, bulk ops + CSV import/export, HSN classification (`hsn.py` reference table). ⚠ A combo has **no `price` and no `tax_rate` column** — its MRP is derived from its component sizes and its GST is charged per component (see ORDER_LIFECYCLE.md) |
| `cart` | Shopping cart, favorites |
| `orders` | Order lifecycle, coupons, invoices/packing slips, admin-only private delivery bills |
| `payments` | Razorpay (L1 verify / L2 webhook / L3 reconcile), payment methods, TEST/LIVE key toggle, admin-visible payment instrument details |
| `reviews` | Verified-purchase reviews + admin `is_hidden` moderation |
| `admin_panel` | Dashboard, coupons, policies, receivable accounts, global admin search |
| `support` | Contact form submissions |
| `assistant` | Unified chat: AI shopping assistant + voice + human-admin support (tool-calling agent); login-only; separate read-only admin business-data persona (`/admin-chat/`) |
| `analytics` | Behavioral event ingest (recommendations); anonymous counter tracking; sales/behavioral rollups + admin Insights API |

## Production stack

- ⚠️ **PRODUCTION MOVED TO GOOGLE CLOUD (2026-09-30/10-01, verified on the VM
  2026-10-01). Every AWS detail below this bullet — `13.235.238.99`, `ec2-user`,
  `my-pem.pem`, host nginx + certbot, `docker-compose.prod.yml` on the box, systemd
  backup timer — describes the OLD box, which no longer answers.** The authoritative
  description of the VM lives in `../AIAAS/DEPLOYMENT.md` → "Where production runs".
  - **VM**: GCP e2-medium (2 vCPU, 4 GB), Ubuntu 24.04, `asia-south2-b`, static IP
    **`34.0.5.162`**. **Shared with the AIAAS project** — 4 GB for both stacks, so
    check `docker stats --no-stream` before raising any memory limit.
  - **SSH**: `ssh -i ~/.ssh/id_ed25519 kaushaljain7000@34.0.5.162`. The AWS `.pem`
    keys are refused.
  - **Stack**: `~/NGU`, compose file is **`docker-compose.yml`** there (NOT
    `docker-compose.prod.yml`; `.orig-aws` is the pre-move copy). Same container
    names (`ngu-backend`, `ngu-scheduler`, `ngu-frontend`, `ngu-admin-panel`,
    `ngu-postgres`, `ngu-pgbouncer`, `ngu-redis`, `ngu-whisper`). Always run compose
    from `~/NGU` so it never touches `aiaas-*` or `edge-caddy`.
  - **Proxy/TLS**: one shared `edge-caddy` container (`~/edge/Caddyfile`) owns
    80/443 for both projects; reload with
    `docker exec edge-caddy caddy reload --config /etc/caddy/Caddyfile`. There is no
    host nginx and no certbot.
  - ✅ **HTTPS enabled 2026-10-01 for `nidhigrahudyog.com` + `www.`** (Caddy
    auto-certs; HTTP 308s to HTTPS). ⚠ **`nidhimasala.com` / `www.nidhimasala.com`
    are NOT in the Caddy site block**: their DNS still points elsewhere
    (`15.197.225.128`/`3.33.251.168`, no `www` record). Once the A records point at
    `34.0.5.162`, add both names to the NGU site line and reload.
    - ⚠ `~/edge/Caddyfile` is a **single-file bind mount**. Edit it IN PLACE
      (`cat new > Caddyfile`), never with `sed -i` or an editor that replaces the
      file — the container would keep reading the old inode and `caddy reload`
      would silently reload the old config. `~/edge/enable-ngu.sh` uses `sed -i`
      and insists on all four names resolving; it is stale, don't run it.
    - Backup of the pre-change file: `~/edge/Caddyfile.bak-20261001-165804`.
  - **Backups**: `~/NGU/pg_backup.sh` → `~/NGU/backups/` (host cron on this box, IST).
  - From this dev machine the **Bash tool has no outbound network; PowerShell does**
    (`ssh`, `scp`, `curl.exe`).
- **EC2 (deploy)** x86_64 (Amazon Linux 2023) at `13.235.238.99` — runs the app stack (backend, frontend, admin, redis) via `docker-compose.prod.yml`
- **Database — NOW ON THE DEPLOY BOX** (consolidated 2026-09-02). `postgres:17` +
  PgBouncer run as the `postgres`/`pgbouncer` services in `docker-compose.prod.yml`
  on `13.235.238.99`. App connects at `DB_HOST=pgbouncer`, `DB_PORT=6432` over the
  internal `ngu-network`; **PgBouncer is no longer published on a host port** and
  Postgres `5432` is bound to `127.0.0.1` only.
  - The former dedicated DB instance `13.201.33.243` (self-hosted pg17 + PgBouncer
    in `~/ngu-db/`) was left RUNNING AND UNTOUCHED as the rollback path. It holds
    the pre-cutover data. **Terminate it only after the new DB has taken real
    traffic.** Rollback = set `DB_HOST=172.31.39.8`/`DB_PORT=6432` in
    `~/NGU/.env.backend` and `up -d backend scheduler`.
  - `pg_data` is a Docker named volume on the 20 GB root disk (DB is ~16 MB).
    ⚠ There is **no automated backup**. See "Database backups" below.
- **Redis** (docker container, `ngu:` key prefix)
- **Cloudinary** — primary media storage (product/category/profile images)
- **AWS S3** `ngu-static-files0` — ⚠ **NOT ACTUALLY IN USE.** Prod has `USE_S3=False`
  (verified 2026-09-02); static files are served locally from the `ngu_static_data`
  volume (12 MB) and media from Cloudinary. ⇒ The app has **no runtime AWS
  dependency**, which is what makes leaving AWS straightforward. Don't assume the
  static volume is disposable — it is the live source of static files.
- **Live API**: `https://nidhigrahudyog.com/api/` — this is the domain that currently
  resolves to the deploy server. (`nidhimasala.com` is the intended long-term primary
  but its DNS points elsewhere — see DNS drift below.)
- **Domains**: `nidhigrahudyog.com` (currently the working one) and `nidhimasala.com`
  (both +`www.`, same app stack). TLS terminates at the host nginx (Let's Encrypt) — **no Cloudflare** — which redirects HTTP→HTTPS and proxies the frontend container. **One cert lineage per domain** (`nidhimasala.com` covers apex+www; `nidhigrahudyog.com` covers apex+www) — never bundle domains onto one cert: a single dead SAN fails the whole renewal. Backend `ALLOWED_HOSTS`/`CORS`/`CSRF` list all four; see DEPLOYMENT.md Part 6 for cert issuance.
- ⚠️ **DNS drift (observed 2026-07-20)** — the four names do NOT all point at the deploy server any more:
  - `nidhigrahudyog.com` → `13.235.238.99` ✅ deploy server
  - `nidhimasala.com` → `3.33.251.168` ❌ **not this server**
  - `www.nidhimasala.com` → *no A record* ❌

  The server itself serves all four vhosts correctly — verify with
  `curl --resolve nidhimasala.com:443:13.235.238.99 https://nidhimasala.com/api/products/`
  (returns 200). So a failure on `nidhimasala.com` is a DNS/registrar issue, not
  an app issue. Fix the A records to point at `13.235.238.99`.
- ⚠️ **Container `API_URL` must stay RELATIVE (`/api`)** so the SPA calls whatever
  origin it was loaded from and works on either domain. `frontend` already does this
  (`FRONTEND_API_URL:-/api`). `admin-panel` used to default to an ABSOLUTE
  `https://nidhimasala.com/api`, which silently broke the panel once that hostname
  stopped resolving — changed to `ADMIN_API_URL:-/api` on 2026-07-20. Don't
  reintroduce an absolute URL. The runtime `config.js` the container generates
  **overrides** the build-time `VITE_API_URL`, so rebuilding the image with a
  different `--build-arg` does NOT change this; the container env is what matters.
- ⚠️ **Do not health-check the live domains from a sandboxed/dev machine.** DNS is
  often intercepted there (all four resolving to one private RFC1918 address is the
  tell), which produces bogus 404s/redirects that never reached the server. Check
  from the EC2 box, or use `--resolve` as above.

## Database backups

Added 2026-09-02, when the DB moved onto the deploy box and the dedicated DB
instance (which had implicitly been a second copy of the data) was retired.

- `~/NGU/pg_backup.sh` — `pg_dump -Fc` + gzip into `~/NGU/backups/`, 14-day
  retention, driven by the **systemd timer** `ngu-pg-backup.timer` (02:30 UTC
  daily, `Persistent=true` so a missed run fires on boot).
  ⚠ `crontab` is NOT installed on this Amazon Linux 2023 box — use systemd, not cron.
- Check / run / inspect:
  ```bash
  systemctl list-timers ngu-pg-backup.timer
  sudo systemctl start ngu-pg-backup.service   # run one now
  tail ~/NGU/backups/backup.log
  ```
- Restore drill (verified working 2026-09-02, 0 errors) — restore into a scratch
  DB, never straight over `ngu_db`:
  ```bash
  gunzip -c ~/NGU/backups/<file>.dump.gz > /tmp/v.dump
  docker cp /tmp/v.dump ngu-postgres:/tmp/v.dump
  docker exec ngu-postgres psql -U KaushalJainAI -d postgres     -c 'CREATE DATABASE restore_test OWNER "KaushalJainAI";'
  docker exec ngu-postgres pg_restore -U KaushalJainAI -d restore_test     --no-owner --no-privileges /tmp/v.dump
  ```
- ⚠ **These dumps are ON THE SAME DISK AS THE DATABASE.** They protect against a
  bad migration, a dropped table, or data corruption — NOT against losing the
  instance or its EBS volume. Copying them off-box (S3 + lifecycle rule) is the
  remaining gap and the single most valuable follow-up.

## Key environment variables

```env
# Core
SECRET_KEY, DEBUG, ALLOWED_HOSTS, CORS_ALLOWED_ORIGINS

# Database
DB_ENGINE, DB_NAME, DB_USER, DB_PASSWORD, DB_HOST, DB_PORT

# Redis
REDIS_URL

# Media (Cloudinary — required, hard startup dependency)
USE_CLOUDINARY=True
CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, CLOUDINARY_API_SECRET

# Static files (optional S3)
USE_S3=True/False
AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_STORAGE_BUCKET_NAME

# Auth
GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET
EMAIL_HOST_USER, EMAIL_HOST_PASSWORD

# Payments — RAZORPAY_TEST_MODE picks the active key pair (True = test).
# settings.py resolves it into RAZORPAY_KEY_ID/SECRET/WEBHOOK_SECRET; the rest of
# the code only ever reads those. Boot guards reject flag/key-prefix mismatches
# and refuse live keys with DEBUG=True.
RAZORPAY_TEST_MODE=True
RAZORPAY_TEST_KEY_ID, RAZORPAY_TEST_KEY_SECRET, RAZORPAY_TEST_WEBHOOK_SECRET
RAZORPAY_LIVE_KEY_ID, RAZORPAY_LIVE_KEY_SECRET, RAZORPAY_LIVE_WEBHOOK_SECRET
# Webhook secret is per-mode and switches with the keys.
# REQUIRED for L2 webhook reconciliation — blank = ALL webhooks rejected (fail-closed)
#
# ⚠️ MIGRATION TRAP — an env still using the flat pre-toggle names will CRASH ON BOOT.
# RAZORPAY_TEST_MODE defaults to True; the compat fallback then loads the flat
# RAZORPAY_KEY_ID (an rzp_live_ key), and the guard "test mode + live key" raises
# ImproperlyConfigured at import time → Django never starts → WHOLE API DOWN, not
# just payments. Before shipping the toggle to any environment holding flat live
# keys, set RAZORPAY_TEST_MODE=False and populate RAZORPAY_LIVE_KEY_ID/SECRET.
#
# Prod env lives at ~/NGU/.env.backend on the deploy box (referenced via
# `env_file:` in docker-compose.prod.yml). ⚠ Since 2026-09-02 a SECOND file
# ~/NGU/.env DOES exist (mode 600): it holds only POSTGRES_PASSWORD, which Compose
# interpolates into the postgres/pgbouncer services. Compose reads it automatically
# from the project dir, so no `--env-file` flag is needed — but do not delete it or
# `docker compose` will refuse to start the DB.
# Migrated 2026-07-20: TEST_MODE=False + RAZORPAY_LIVE_* added; live keys unchanged.
# ✅ 2026-07-25: prod is LIVE — RAZORPAY_TEST_MODE=False, resolved key rzp_live_.
# (It had drifted back to TEST between 07-23 and 07-25.) Env backup of the previous
# state: ~/NGU/.env.backend.bak.20260725 on the deploy box.
# Verify resolved config without printing secrets (must use `manage.py shell -c`,
# NOT plain `python -c` — the latter dies with "settings are not configured"):
#   docker exec ngu-backend python manage.py shell -c "from django.conf import \
#     settings; print(settings.RAZORPAY_TEST_MODE, settings.RAZORPAY_KEY_ID[:9], \
#     bool(settings.RAZORPAY_WEBHOOK_SECRET))"
#
# ⚠️ AS OF 2026-07-25 PROD STILL HAS NO RAZORPAY_WEBHOOK_SECRET. Payments still succeed
# (the /verify/ browser callback uses RAZORPAY_KEY_SECRET, a different credential),
# but every webhook delivery is rejected fail-closed. Consequences, in order of pain:
#   1. (Moot since 2026-08-01 — see MANUAL-ONLY REFUNDS below. Gateway refunds are
#      no longer auto-recorded even with a working secret, so the missing secret
#      costs nothing here.) Refunds must be recorded by hand in the admin panel.
#   2. Instrument details (method/UPI/card) stay blank on normal orders — /verify/
#      doesn't pass payment_entity, and L3 (which does) only touches stuck orders.
#   3. Missed captures are still self-healed by L3 within ~TTL + cadence (~20 min),
#      just not in seconds. No money is lost.
# Fix: Razorpay dashboard (LIVE tab) → Settings →
# Webhooks → add https://nidhigrahudyog.com/api/payments/webhook/ (trailing slash
# required; use nidhigrahudyog.com — nidhimasala.com DNS still points elsewhere)
# with events payment.captured, payment.failed, order.paid (the three
# payments/views.py still ACTS on), then set RAZORPAY_LIVE_WEBHOOK_SECRET
# to the same secret and recreate the backend container.
#
# ⚠️ COD CASH IS CONFIRMED BY HAND (2026-08-04). A COD order takes no money at
# checkout, so `payment_status` stays 'pending' and `Order.cod_paid_at` is NULL
# until an admin ticks "Paid in cash" in the order dialog (PATCH `cod_paid:true`).
# That stamps cod_paid_at + cod_confirmed_by and flips payment_status to 'paid'.
# It is NOT a side effect of marking an order delivered — couriers remit later.
#   ⇒ A COD order CANNOT BE REFUNDED until it is ticked (no proof cash arrived).
#     Before this existed a genuine COD return could not be recorded AT ALL, so
#     its GST stayed owed forever — that was the bug this closes.
#   ⇒ Ticking is a CASH fact, never a tax one. GST accrued at order date and
#     must not move when the money turns up.
#   ⇒ Dashboard: cod_pending_amount/_count/_aged_count (live, = cash the courier
#     holds) + cod_collected_today. DailySalesRollup.cod_collected buckets by
#     CONFIRMATION date, like refunds.

# ⚠️ MANUAL-ONLY REFUNDS (2026-08-01). The `refund.processed` branch in
# payments/views.py::_dispatch_webhook_event is COMMENTED OUT — a refund webhook is
# now signature-verified, logged at WARNING, and otherwise ignored. It writes
# nothing to the OrderRefund ledger. `services.mark_payment_refunded` is retained
# but is no longer reachable from the webhook.
# ⇒ After issuing ANY refund in the Razorpay dashboard, an admin MUST mark the order
#   'refunded' in the panel (PATCH → orders/refunds.py::record_refund, source='admin'),
#   or the order reads 'paid' forever and its GST is never reversed — i.e. tax paid
#   on money already returned. Subscribing refund.processed at Razorpay is harmless
#   but pointless while this holds.
# To re-enable: un-comment the branch in payments/views.py AND the disabled test
# `test_refund_webhook_without_order_id_still_refunds` in
# payments/test_razorpay_and_payment_flow.py.
#
# ⚠️ PARTIAL REFUNDS (2026-08-01). The admin PATCH takes an optional `refund_amount`
# (omit ⇒ whole outstanding balance). Any admin-entered amount marks the order
# 'refunded', so `status`/`payment_status` = 'refunded' now means "a refund was
# RECORDED", NOT "the whole order came back" — anything reading those flags must
# read `refunded_amount` too or it will misreport a partial as a full refund.
# Instalments are supported (re-send an explicit amount on an already-refunded
# order). Since 2026-10-01 the admin path emails the customer the amount recorded
# (orders/emails.py::send_refund_recorded_email). See tmp/refund-pipeline.md for
# the full pipeline + known gaps.
#
# ⚠️ REFUND ELIGIBILITY + RESTOCK (2026-08-02).
#   * A refund can ONLY be recorded on an order whose money actually arrived —
#     gate is OrderViewSet._is_refundable_payment. payment_status must be in
#     {paid, refunded}, AND either payment_method in {ONLINE, razorpay}, OR it is
#     COD with cod_paid_at set (the "Paid in cash" tick — widened 2026-08-04).
#     Everything else 400s before anything is written. A ledger row reverses GST,
#     so writing one for money that never reached us understates tax owed.
#     ⚠ Do NOT re-narrow this to ONLINE-only: before the COD tick existed a
#     genuine COD return could not be recorded at all (see COD section above).
#   * Recording a refund now RESTOCKS the order (record_refund → restore_order_stock).
#     restore_order_stock is idempotent — it stamps Order.stock_restored_at, so
#     cancel-then-refund (or two instalments) can't credit the same units twice.
#     A partial refund returns the whole order's stock, once, by design.
PAYMENT_STUCK_TTL_MINUTES=15   # ONLINE order unpaid past this is auto-cancelled + restocked (payment_status 'rejected')

# Pricing — ⚠ TWO OPPOSITE GST CONVENTIONS, don't mix them up.
# Product prices are MRP (GST-INCLUSIVE, extracted for disclosure). The DELIVERY
# fee is the exception: quoted NET and taxed ON TOP at SHIPPING_TAX_RATE, so its
# GST really is an addend to total_amount while the goods GST never is.
SHIPPING_CHARGE_NET=59    # NET fee (was SHIPPING_CHARGE=69, untaxed, pre-2026-08-04)
SHIPPING_TAX_RATE=18      # GST on delivery, SAC 9968. Customer pays 59+10.62=69.62
FREE_SHIPPING_THRESHOLD=499   # >= this post-discount subtotal ships free.
# ✅ 2026-08-05: aligned to 499 EVERYWHERE — code defaults (backend limits.py +
# storefront config/limits.ts), all ten .env files, docs, and PROD (~/NGU/.env.backend
# edited 500→499, backend+scheduler recreated, verified `threshold 499`).
# Env backup on the deploy box: ~/NGU/.env.backend.bak.20260805-freeship.
# What this fixed: the storefront IMAGE bakes VITE_FREE_SHIPPING_THRESHOLD at build
# and had 499, while the backend env said 500 — and the frontend container passes an
# EMPTY FREE_SHIPPING_THRESHOLD, so runtime config could not correct it. A ₹499 cart
# showed "free delivery" and was then billed ₹69.62 at checkout.
#   ⇒ The storefront default is BAKED IN. Changing the number means rebuilding the
#     frontend image (or setting FREE_SHIPPING_THRESHOLD in the frontend service env,
#     which the entrypoint writes into config.js) — a backend-only env edit will
#     silently re-open exactly this split.
# ✅ DEPLOY TRAP DEFUSED (2026-08-04) — the variable was RENAMED, on purpose.
# Every deployed .env pins the OLD `SHIPPING_CHARGE=69` from the untaxed era.
# Reusing that name would have changed what the number MEANS under deployments
# still holding it (69 went from "what the customer pays" to "the net fee"),
# silently billing 69 + 18% = 81.42. Manually fixing the env was no safer: change
# it before the code ships and you bill 59 with NO tax; ship the code first and
# you overcharge until someone remembers.
#   ⇒ A stale SHIPPING_CHARGE is now INERT everywhere — backend, frontend
#     runtime config, and compose. No prod env edit is required to deploy safely.
#   ⇒ Startup warns if it is still present (orders/apps.py, and the frontend
#     entrypoint echoes a warning). Delete the dead line when convenient.
#   ⇒ DO NOT "tidy" the name back to SHIPPING_CHARGE.
# The storefront mirrors these as VITE_SHIPPING_CHARGE_NET / VITE_SHIPPING_TAX_RATE.
#
# Output tax = Order.total_tax (= tax + shipping_tax), NOT Order.tax. Every
# reporting surface reads total_tax; `tax` alone under-states the liability by
# the GST on every delivery charged.
#
# ⚠ HSN CLASSIFICATION (2026-08-04). `Product.hsn_code` (4/6/8 digits, blank =
# unclassified) is snapshotted onto OrderItem/OrderItemComponent at checkout,
# printed on the invoice, and aggregated by /api/admin/hsn-summary/ into the
# GSTR-1 Table 12 report. `tax_rate` says WHAT is charged; the code says WHY —
# neither derives from the other (5% spans 0904/0909/0910; 2103 moved 12%→18%
# on 2025-09-22). The curated code list + the statutory rate for each lives in
# Backend/products/hsn.py; migration products/0042 populated the live catalogue
# by keyword. The admin panel shows the published rate next to the rate charged
# and flags a mismatch, but NEVER applies it — the rate is the owner's call.
#   ⇒ ONE OPEN TAX QUESTION FOR THE CA, surfaced by /gst in the panel:
#        Masala blends are coded 09109100 (5%). A blend containing salt/sugar/
#        starch/oil is arguably 21039040, now **18%**. That is a 13-point swing
#        on roughly half the catalogue.
#   ✅ OWNER'S DECISION 2026-10-01: blends STAY at 5% (09109100). Verified in
#        prod that day — every non-papad product charges 5%, the three papads 0%.
#        Do not move blends to 18% or re-raise this unless the owner or CA does.
#   ✅ RESOLVED 2026-08-04 (owner's decision, migration products/0043):
#        "Chana papad masala" / "Moong papad masala" now charge 5%, not 0%.
#        They are sprinkle SEASONINGS (shelved under Sprinklers & Seasonings by
#        migration 0025) — the actual NIL-rated papads are SEPARATE SKUs (Chana
#        Papad / Moong Papad / Papad Katran, still 19059040 @ 0%, untouched).
#        Migration 0024 had zero-rated every name containing "papad" by string
#        match, which swept these two up. MRP is GST-inclusive, so the shelf
#        price did NOT move — only the tax extracted from it. Past orders keep
#        the 0% snapshotted onto their lines. These two remain candidates for
#        the 21039040 @ 18% question above (their copy promises a "namkeen
#        finish", i.e. salt) — 5% is the defensible floor, not the final word.

# Background scheduler (scheduler container, manage.py run_scheduler)
RECONCILE_INTERVAL_MINUTES=5   # payment self-healing cadence
ROLLUP_INTERVAL_MINUTES=5      # analytics rollup + anon-counter flush cadence
RECYCLE_BIN_RETENTION_DAYS=30  # admin Recycle Bin items (orders/products/combos) are
                               # permanently purged this many days after soft-deletion
                               # (rolling per-item). purge_recycle_bin runs nightly at
                               # 03:30. 0 disables. Products/combos referenced by a past
                               # order are DB-protected and skipped (kept in the bin).
                               # ⚠ Orders carrying an ISSUED TAX INVOICE are likewise
                               # PROTECTed and skipped — see TAX INVOICES below.
INVOICE_NUMBER_PREFIX=NM        # invoice serial prefix; max 3 chars (GST caps the
                               # whole number at 16, and FY+sequence take 13)

# ⚠️ TAX INVOICES ARE ISSUED DOCUMENTS (2026-08-04). An invoice is a row in
# `orders.Invoice` — ONE PER ORDER (OneToOne, on_delete=PROTECT) — not a PDF
# rendered on demand. Numbering and triggers live in `orders/invoicing.py`.
#   * Number: NM/25-26/000123 — prefix / Indian FY (Apr–Mar) / sequence from
#     `InvoiceCounter` under a row lock. CONTINUOUS within the year. It is NOT
#     `ORD-{order.id}` any more: order ids skip every abandoned checkout and
#     cancelled order, which can never be a lawful GST series.
#   * Issued at: payment capture (ONLINE), placement (zero-total coupon order —
#     already paid, no capture coming), or DISPATCH (COD: shipped/delivering/
#     delivered) — the bill travels with the goods and the courier remits days
#     later. `invoice_is_due` accepts EITHER evidence of supply: money received
#     (payment_status paid OR refunded) or goods dispatched. A cancelled order is
#     never invoiced. ⚠ 'refunded' MUST count — a refund is only recordable
#     against money actually taken, so excluding it would leave historical
#     refunded orders unnumbered and their credit notes with no serial to cite.
#   * `Invoice.snapshot` freezes seller + buyer + lines + totals + GST heads at
#     issue, and the renderer reads ONLY that. Changing SELLER_ADDRESS, editing
#     the shipping address, or re-rating a product CANNOT alter an issued bill.
#   * GET /orders/{id}/invoice/ is a REPRINT: 409 `invoice_not_issued` when none
#     exists. Order responses carry `invoice: {number, issued_at} | null`.
#   * Backfill/repair (issuing never raises, so a failure just leaves a gap):
#       docker compose -f docker-compose.prod.yml exec backend #         python manage.py backfill_invoices --dry-run
#     Run it ONCE after deploying this, to number historical paid/dispatched
#     orders (oldest-first, stamped with each order's own date).
#   * Credit notes are `orders.CreditNote` rows numbered CN/25-26/000001 from the
#     same InvoiceCounter (since 2026-10-01). The old PK-derived `CN-{refund.pk}`
#     survives only as the fallback for a refund whose order has no invoice; run
#     `backfill_invoices` then `backfill_credit_notes` to number historical ones.
# The scheduler ALSO fires store-owner emails on cron: send_daily_digest (08:00 —
# yesterday's sales + low-stock) and send_weekly_summary (Mon 08:30). See docs/ANALYTICS.md.

# AI (search synonyms + shopping assistant)
LLM_API_KEY, MODEL_PROVIDER, LLM_MODEL
ASSISTANT_MODEL_PROVIDER, ASSISTANT_LLM_MODEL  # optional override for assistant
# ⚠ OpenRouter serves ONE model id from MANY upstream providers and picks per
# request, so an unpinned call lands anywhere (deepseek-v4-flash was observed
# routing to GMICloud/Baidu). Pin it here — spices_backend/llm.py turns these
# into the `provider` body param for BOTH the assistant and the search-synonym
# engine (products/recommendations.py).
OPENROUTER_PROVIDER_ORDER=DeepInfra   # comma-separated, highest priority first. Unset = no pin.
OPENROUTER_ALLOW_FALLBACKS=True       # False = listed providers ONLY; all down ⇒ request FAILS.
# ⚠ `deepinfra/fp4` is an ENDPOINT TAG (provider + quantization), NOT a model id.
# It belongs in OPENROUTER_PROVIDER_ORDER (as `DeepInfra`), never in LLM_MODEL —
# setting LLM_MODEL=deepinfra/fp4 404s every call and takes the assistant down.
# ⚠ 2026-08-08: the previous LLM_API_KEY (and two older ones in Backend/.env*)
# all 401 with "User not found" — revoked upstream. That is an ACCOUNT-level
# failure, not credits (402) or rate limit (429); check GET /api/v1/key first.

# Voice transcription (assistant voice input) — TWO BACKENDS, see assistant/stt.py
USE_SELF_HOSTED_STT=True     # gates the /assistant/transcribe/ endpoint AS A WHOLE.
                             # Legacy name: it predates there being a hosted option,
                             # so it is NOT "use whisper" — that is STT_PROVIDER.
STT_PROVIDER=voxtral         # 'voxtral' (default) | 'whisper'
STT_FALLBACK_TO_WHISPER=True # voxtral failure -> retry on the local container
# voxtral = mistralai/voxtral-mini-transcribe over OpenRouter. ~1.1s for a ~5s
# utterance vs whisper.cpp's ~20s PER SECOND of audio on the 2 vCPU deploy box —
# the local container was too slow to actually use, which is why this exists.
# Cost: $0.003/min of audio, prorated to the second (~₹0.026 per utterance, so
# roughly ₹40-160/month at plausible volume). Reuses LLM_API_KEY unless
# OPENROUTER_API_KEY is set — prefer a SEPARATE key in prod so transcription and
# chat don't share a credit limit or a revocation.
OPENROUTER_API_KEY=          # optional; falls back to LLM_API_KEY
VOXTRAL_MODEL=mistralai/voxtral-mini-transcribe
VOXTRAL_TIMEOUT=30
WHISPER_URL=http://whisper:8080/inference     # internal whisper container (fallback)
WHISPER_TIMEOUT=30
# ⚠ The two backends express "autodetect the language" INCOMPATIBLY: whisper.cpp
# requires the literal 'auto' (omitting the field makes it assume English), while
# OpenRouter returns 422 on 'auto' and autodetects only when the field is ABSENT.
# stt.resolve_language() normalises to 'auto' and each client translates. Don't
# "simplify" this by passing the same body to both.
# ⚠ stt.DOMAIN_PROMPT (catalogue vocabulary priming) is a REAL accuracy win on
# whisper.cpp but a NO-OP on Voxtral — OpenRouter documents `prompt` as ignored by
# most providers, and a probe confirmed identical output with and without it.
# Don't expect it to fix a misheard spice name on the hosted path.
# ⚠ The endpoint returns {transcript, language} ONLY. OpenRouter also reports
# per-request usage/cost; that is logged at DEBUG and must NOT be added to the
# response — it goes straight to the customer's browser.
```

## Common commands

```bash
# Build & push Docker images (amd64/x86_64 — current prod EC2 instances are x86)
docker buildx build --platform linux/amd64 --push -t kaushaljainai/ngu-backend:latest ./Backend
docker buildx build --platform linux/amd64 --build-arg VITE_API_URL=https://nidhigrahudyog.com/api \
  --build-arg VITE_GOOGLE_CLIENT_ID=<id> --push -t kaushaljainai/ngu-frontend:latest "./Frontend/nidhi-brand-forge"
# Admin panel has Google sign-in for EXISTING staff accounts only (never creates one).
docker buildx build --platform linux/amd64 --build-arg VITE_API_URL=https://nidhigrahudyog.com/api \
  --build-arg VITE_GOOGLE_CLIENT_ID=<id> --push -t kaushaljainai/ngu-admin:latest "./Admin Panel/e-commerce-command-center"
# Self-hosted voice transcription (whisper.cpp, small-q5). Rebuild only when whisper/Dockerfile changes.
docker buildx build --platform linux/amd64 --push -t kaushaljainai/ngu-whisper:latest ./whisper

# Deploy on EC2 (ssh ec2-user@13.235.238.99, stack lives in ~/NGU)
# NOTE: the box has Compose **v2** — use `docker compose` (space), not `docker-compose`.
# Service names are: whisper redis backend admin-panel frontend scheduler postgres pgbouncer
#   (it is `admin-panel`, NOT `admin` — `pull admin` fails with "no such service")
cd ~/NGU
docker compose -f docker-compose.prod.yml pull backend scheduler admin-panel
docker compose -f docker-compose.prod.yml up -d backend scheduler admin-panel
docker compose -f docker-compose.prod.yml exec -T backend python manage.py migrate

# Frontend nginx now re-resolves upstreams itself (`resolver 127.0.0.11` +
# variable `proxy_pass` in `Frontend/nidhi-brand-forge/nginx.conf`), so
# recreating the backend or admin-panel container no longer needs a manual
# `docker exec ngu-frontend nginx -s reload`. The reload is only needed for
# images built before that change.

# Refresh AI search knowledge base after bulk SQL updates
docker compose -f docker-compose.prod.yml exec backend python manage.py populate_search_kb --force

# NOTE: reconcile_payments AND rollup_analytics now run AUTOMATICALLY in the
# dedicated `scheduler` container (manage.py run_scheduler) — reconcile every
# RECONCILE_INTERVAL_MINUTES, rollup every ROLLUP_INTERVAL_MINUTES + nightly.
# The commands below are for manual/one-off runs only.

# Recompute analytics rollups manually (also flushes anon counters)
docker compose -f docker-compose.prod.yml exec backend python manage.py rollup_analytics

# Manually reconcile stuck payments (auto-cancel + restock abandoned ONLINE orders)
docker compose -f docker-compose.prod.yml exec backend python manage.py reconcile_payments

# Migrate media from S3 to Cloudinary (one-time)
docker compose -f docker-compose.prod.yml exec backend python manage.py migrate_s3_to_cloudinary --apply

# Run unit and integration tests (SQLite) — MUST be run from Backend/, which owns
# pytest.ini. From the repo root it collects testing/ too and dies during collection
# with ImproperlyConfigured (that tree needs different settings).
cd Backend && venv/Scripts/python.exe -m pytest -q     # ~80s, 1280 passed / 8 skipped (2026-08-08)

# Known-expected results on SQLite:
#  - orders/test_concurrency.py::test_G4/G5 FAIL with "database table is locked".
#    SQLite can't do the row locking they assert; they pass on Postgres. Confirm any
#    "new" failure is really new by stashing your diff and re-running before debugging.
#  - 8 skips are all admin_panel/tests.py "Policy API retired" (routes unregistered).

# Run tests against local Postgres (required for concurrency locking tests)
$env:TEST_DB="postgres"; pytest

# Run the complete E2E & security audit (from repo root)
Backend/venv/Scripts/python testing/tools/run_full_audit.py
```

## ⚠️ Do NOT run tests against the production server / database

As of 2026-07-23, per the owner's directive: **do not execute test suites, scripts,
or ad-hoc write/payment flows against production** (`nidhigrahudyog.com`, the deploy
box `13.235.238.99`, or the DB box `13.201.33.243`). A full prod E2E validation was
completed on 2026-07-23 — **96 assertions + one real test-mode netbanking payment,
0 defects** (see `testing/PROD_TEST_REPORT.md`). It does not need repeating. Run the
suites against a **local seeded server or staging** instead:

- `testing/e2e/` + `testing/security/` — black-box HTTP suites (catalog, auth, cart,
  order lifecycle, payments, reviews, assistant, support). A prod-safe design exists
  (`NGU_IS_PROD=1` gate, one reusable account `qa.e2e@nidhimasala.com`, self-cleaning
  fixtures, `rzp_test_` charging guard) — but **prod runs are now off-limits by request.**
- `testing/ui/netbanking_prod.cjs` — real Razorpay test-mode netbanking capture via
  installed Chrome (has an `rzp_test_` hard guard). Point it at **staging only**.
- Local recipe: `Backend/venv/Scripts/python testing/tools/run_full_audit.py` spins up
  a throwaway SQLite server, seeds it, and runs the e2e/security suites — no live target.
- Observed prod throttles (for reference, do not probe them live): register 3/min,
  login 5/min, order 10/min, cart_write 60/min.

## Local dev / verification

- ⚠️ **`Backend/.env.local` points `DB_HOST` at a REMOTE database.** Never source it
  for local testing. `Backend/.env` and `.env.dev` expect a local Postgres that
  usually isn't running.
- To run the stack locally, override via env vars instead — `settings.py` falls back
  to SQLite when `DB_ENGINE` is unset, and `python-decouple` reads `os.environ`
  before `.env`. Set `USE_CLOUDINARY=False` too (it's a hard startup dependency).
- The admin panel dev server serves at **`http://127.0.0.1:5174/panel/`** (not `/`);
  keep `CORS_ALLOWED_ORIGINS` in sync with the port or every API call fails.
- Full recipe — including seeding, JWT auth, driving Chrome, and firing
  signature-valid Razorpay webhooks offline — is in `.claude/skills/verify/SKILL.md`.

## Docs

- `README.md` (root) — what the project is, quick start, and a map of every document.
- `learning/` — **all teaching material in one folder**: `01_HLD.md`,
  `02_LLD_Object_Model_and_Flows.md`, `03_LLD_Backend_Patterns.md` (was
  `BACKEND_PATTERNS.md`), `04_LLD_Frontend_Patterns.md` (was `FRONTEND_PATTERNS.md`),
  `05_Interview_Kit.md`, `lessons/` (one write-up per real problem) and `diagrams/`.
  Written for a reader still learning Django/React/OOP: plain words, every term
  defined on first use, every claim linked to the real file. ⚠ It quotes real
  numbers and flows (worker counts, limits, the checkout steps, invoice rules) —
  when a change makes one of them untrue, fix the guide in the same change. A new
  incident or hard-won fix gets a new file in `learning/lessons/` plus a row in
  `lessons/00_INDEX.md`.
- `Backend/docs/API.md` — **endpoint map / code-review index**: every HTTP route with its
  Django app, purpose, access, complexity, test coverage (good+bad), serializer, DB tables,
  atomicity, and gotchas. The first stop for reviewing the backend surface. ⚠ **Keep it
  current** — whenever you add, remove, or change a route (`spices_backend/urls.py` or any
  app's `urls.py`/router), its permission, or its serializer, update the matching row in
  `Backend/docs/API.md` in the same change. (Companion to `API_PERMISSIONS.md`, which is
  auth-only.)
- `HOSTINGER_MIGRATION.md` — **planned** move of the whole stack off AWS onto a
  Hostinger KVM 2 VPS (x86_64, 8 GB). Runbook + pre-flight checks; not executed.
- `Backend/docs/ARCHITECTURE.md` — design principles, app responsibilities
- `Backend/docs/AI_SEARCH_ENGINE.md` — AI search + synonym generation
- `Backend/docs/ASSISTANT.md` — AI shopping assistant (agent, tools, guardrails)
- `Backend/docs/RECOMMENDATIONS.md` — personalized recommendations engine
- `Backend/docs/ANALYTICS.md` — sales/behavioral rollups, anonymous counter tracking, admin Insights API
- `Backend/docs/LOCATION.md` — location detection, reverse-geocode proxy, coarse geo capture
- `Backend/docs/API_PERMISSIONS.md` — all endpoints with auth requirements
- `Backend/docs/CACHING_STRATEGY.md` — Redis caching strategy
- `Backend/docs/DATABASE_SCHEMA.md` — model reference
- `Backend/docs/PAYMENTS_INTEGRATION.md` — Razorpay flow, TEST/LIVE key toggle, instrument details captured from the webhook (admin-only nested `payment` on order responses)
- `Backend/docs/AUTH.md` — JWT cookie lifecycle, Google OAuth, password reset OTP flow, security properties
- `Backend/docs/CART.md` — cart backend (stock locking, sync), frontend state (optimistic updates, login/logout)
- `Backend/docs/ORDER_LIFECYCLE.md` — complete order creation flow, pricing rules, stock management, cancellation
- `Backend/docs/MULTILINGUAL.md` — multilingual setup, workflows, adding languages/fields
- `Backend/docs/S3_STORAGE.md` — storage backend configuration
- `Backend/docs/SETUP-GUIDE.md` — local dev setup
- `Backend/docs/SUPPORT_CHAT.md` — chat system
- `Frontend/nidhi-brand-forge/README.md` — frontend quick start
- `Frontend/nidhi-brand-forge/ARCHITECTURE.md` — frontend design patterns
- `Admin Panel/e-commerce-command-center/ARCHITECTURE.md` — admin panel design

## Improvement plan (2026-10-01)

- Admin panel has Google sign-in for existing staff accounts only (never creates one).
- Admin and customer sessions use separate cookies (`admin_access_token`/`admin_refresh_token` vs `access_token`/`refresh_token`); the panel sends `X-Admin-Panel: 1` so the backend reads the right one. ⚠ Permissions were NOT changed: a staff user logged into the storefront can still reach admin APIs with the customer cookie.
- `POST /api/auth/logout/` clears customer cookies; `POST /api/auth/admin/logout/` clears admin cookies. Neither touches the other session.
- GST reports are on the invoice basis (invoices by issue date); credit notes are `CN/<FY>/<seq>` rows in `orders.CreditNote` (`reason` = refund/cancellation). A refund of nil-rated goods gets a 0% row carrying the credited value.
- New: `Order.courier_name` + `Order.tracking_url`, `admin_panel.Expense`, `/accounts` page, `backfill_credit_notes` command.
- Recording a refund emails the customer (`send_refund_recorded_email`).

## Audit plan AP1–AP12 (2026-10-01, `audit-plan` branches — runs AFTER improvement-plan)

- Auth: `User.email_verified` gates customer + admin login (403 `email_not_verified`).
  Registration answers the same generic 201 for any valid form and the same 400 for
  any invalid one (no enumeration); re-registering over an UNCLAIMED row (unverified,
  never logged in, not staff) replaces its password. `POST /api/auth/verify-email/`
  takes `{email, otp_code, password}` — ⚠ the password is REQUIRED (the code proves
  the inbox, the password proves who set the credentials; do not drop it, that
  re-opens the pre-hijack). `/verify-email/request/` resends. Google sign-in kills the
  password + sessions ONLY on an unverified row (a verified account, incl. staff,
  keeps its password). Password change/reset/email change revokes ALL refresh tokens
  and re-issues the caller's own cookies; other devices' access tokens live out
  ≤ 15 min. A password reset also marks the email verified. Email changes only via
  `POST /api/auth/change-email/` (password + OTP, old address notified). Codes: one
  table (`PasswordResetOTP`) split by `purpose` (reset/verify/change_email), each
  with its own live code and 5/account/24 h quota; `secrets`; mail sent from a
  thread, `EMAIL_TIMEOUT=10`. Migrations: `users/0010` grandfathers delivered-order
  owners, unusable-password (Google) rows AND staff/superusers; `users/0011` adds
  `purpose`. `createsuperuser` accounts are born verified.
  UI: storefront `/verify-email` page (from Register, and from Login on the 403),
  Profile → "Change" email dialog; panel login grows a code field on the 403.
- Abuse: COD needs verified email + total ≤ `COD_MAX_VALUE` (₹5,000) + < `COD_MAX_OPEN`
  (3) open orders (400 `email_not_verified`/`cod_value`/`cod_limit`); chat 10/min +
  100/day, one in-flight turn per account (429, claimed before the message is saved);
  LLM 20 s timeout. Prompt ceiling ~12k tokens, of which ~4,900 is thread history
  (`ASSISTANT_TOOL_OBS_RESERVE_TOKENS=4000`).
  ⚠ These are env-overridable: check `~/NGU/.env.backend` does not still pin
  `ASSISTANT_MODEL_CONTEXT_TOKENS=200000` / `ASSISTANT_MAX_OUTPUT_TOKENS=600` /
  `ASSISTANT_TOOL_OBS_RESERVE_TOKENS=8000` (the old template values) — if it does,
  the cost cap is inert in prod and replies truncate at 600.
- Assistant: native function calling (several reads/round); `reason` ∈
  ok/llm_error/loop_exhausted/customer_asked — ONLY customer_asked flags
  needs_human AND emails the owner at once; truncation appends a continuation line;
  text sent in the same round as a lookup ("Let me check…") is not returned as the
  answer. Size-aware search (variant rows), `variant_id` proposals,
  `cart_proposal`/`edit_cart` one-confirm actions, offers/delivery/tracking tools,
  policies from `assistant/policies.py` (static-page source); SSE at
  `POST /api/assistant/chat/stream/` (⚠ chunks a finished reply — no latency gain,
  and the storefront does not use it); history returns saved proposals. The 43-case
  eval in `assistant/eval/` is SCRIPTED (model turns are hard-coded; it tests tools
  and validators, not model behaviour) — run with `ASSISTANT_EVAL_LIVE=1` and a
  working key for a real result. Admin tools mask PII by default (`include_contact`
  logged). ⚠ `get_offers` lists every active global coupon code to any logged-in
  customer who asks.
- Catalog: exact `stock`/`sku`/thresholds/buildable counts are staff-only in product,
  variant, combo and item serializers (panel reads with the admin session); search
  `in_stock` is boolean.
- Storefront: no fake counts/testimonials/coupons (FSSAI/Barnagar/COD facts instead);
  single discounts, no card squiggles/lifts, lucide icons, static USP strip, skeleton
  home (no all-products fetch), chat proposal card, voice as one-shot lists with
  silence stop + read-aloud toggle + search mic, `/admin/` no longer proxied publicly.
- CSP on both nginx configs (razorpay incl. `cdn.razorpay.com`, fonts, maps, Google
  sign-in script/style/frame). ⚠ The panel is served THROUGH the storefront nginx
  (`location /panel/`), so its responses carry BOTH policies and a source must be
  allowed in both files. Browser-verified locally 2026-10-02 (Chrome, real headers:
  Google button, Razorpay modal, all auth flows, 0 violations). Any new third-party
  script/frame needs adding to the policy or it silently breaks.
- Voice funnel events `voice_used`/`voice_confirmed` (`analytics/0007`).
- Branches: backend `audit-plan` (AP1–AP11); storefront `ap7a-nginx` (AP7a/AP8/AP10–AP12);
  panel `audit-plan` (AP8 CSP). The review fixes of 2026-10-02 sit on top of those
  branches in the worktrees `../NGU-Backend-audit`, `../NGU-Storefront-audit`,
  `../NGU-Panel-audit`. Merging backend `audit-plan` into `improvement-plan`
  conflicts only in `docs/ORDER_LIFECYCLE.md`; the merged tree passes the suite.


## Deployed 2026-10-02 (improvement plan + audit plan, all on `main`)

- Backend `e9c0a76`, panel `3e3f2db`, storefront `ad4b87c` are live on the GCP VM.
  Images also carry dated tags (`ngu-backend:2026-10-02`, `ngu-frontend`/`ngu-admin:2026-10-02b`);
  the pre-deploy images are kept on the VM as `:rollback-20261002`.
- Migrations applied: `admin_panel/0012`, `analytics/0007`, `assistant/0004`,
  `orders/0023`–`0024`, `users/0010`–`0011`. All 5 accounts came out verified;
  `backfill_invoices` / `backfill_credit_notes` dry runs found nothing to issue.
- ⚠ **Line endings.** The storefront and panel images are built on Windows. A CRLF
  `docker-entrypoint.d/40-runtime-config.sh` makes the container exit 127 and
  restart-loop (this took the site down for ~90 s). Both repos now have a
  `.gitattributes` pinning LF and the Dockerfiles strip CRs — don't remove either.
  Before switching prod, start the new image in a throwaway container and check it
  stays `running`.
- Deploy on the VM (no `-f`; every docker command needs `< /dev/null` when the
  script is piped over ssh, or `compose run` swallows the rest of it):
  ```bash
  cd ~/NGU && ./pg_backup.sh
  docker compose pull backend scheduler frontend admin-panel
  docker compose run --rm --no-deps -T backend python manage.py migrate --noinput
  docker compose up -d backend scheduler && docker compose up -d admin-panel frontend
  ```

## Deployed 2026-10-02 (later the same day): home page redesign + assistant model

- Storefront `8a5362d` (`ngu-frontend:2026-10-02c`): the hero is back to the earlier
  copy and figures (50+ / 100% / 1.1M+ / Since 1995 — the owner's call, overriding the
  AP12 "truth pass" for the hero only), and the home page is flat: no gradients,
  squiggle/star SVGs or ribbon emoji. Owner's taste: keep it plain; do not reintroduce
  gradient text/buttons or decorative shapes.
- Backend `134df35` (`ngu-backend:2026-10-02b`): `ASSISTANT_REASONING_EFFORT` (sent to
  OpenRouter as `reasoning.effort`; unset = provider default).
- Prod `~/NGU/.env.backend` now sets `ASSISTANT_LLM_MODEL=openai/gpt-6-luna`,
  `ASSISTANT_REASONING_EFFORT=high`, `ASSISTANT_MAX_OUTPUT_TOKENS=2500`,
  `ASSISTANT_MODEL_CONTEXT_TOKENS=13500` (history budget unchanged). Search synonyms
  stay on `LLM_MODEL` (deepseek). Backup: `.env.backend.bak-luna`; images
  `:rollback-20261002b`.
- ⚠ gpt-6-luna DOES accept tool calls with `reasoning.effort=high` on OpenRouter's
  chat-completions endpoint (probed 2026-10-02). An uncommitted edit to
  `Backend/spices_backend/llm.py` forcing `reasoning_effort=none` for gpt-5/gpt-6
  models appeared in the working tree during this deploy (not from this session); it
  was NOT shipped — the backend image was built from a clean checkout. Committing it
  would silently turn the assistant's reasoning off.

## Sizes, combos, bulk edit and the Recycle Bin (2026-10-02 — in the working tree, NOT deployed)

- ⚠ **Not committed, not deployed.** Needs migration `admin_panel/0013_deletedrecord`
  and a rebuild of BOTH the backend and admin-panel images (the panel calls the new
  `/api/admin/recycle-bin/` routes and reads new fields).
- **Recycle Bin now covers every admin delete.** Products, combos, sizes, categories,
  sections and orders were already soft-deleted. Coupons, reviews (staff deletes only —
  a customer deleting their own review is still a hard delete), expenses, gallery
  images, receivable accounts and contact messages are now snapshotted into
  `admin_panel.DeletedRecord` before the row is removed (`RecycleBinDestroyMixin` in
  `admin_panel/recycle.py`) and restored under their original id from the panel's
  Recycle Bin → "Other" tab. ⚠ A new admin-deletable model must take the mixin, or its
  DELETE is permanent again. Restore answers 409 with a reason when a unique value
  (coupon code, UPI id) has been reused or the parent row is gone.
- `purge_recycle_bin` also drops expired snapshots, and reports a binned product that
  is still a component of a combo as skipped for that reason. ⚠ Such a product could
  never be hard-deleted anyway: deleting it deletes its sizes, and
  `ProductComboItem.variant` is PROTECT (verified 2026-10-02 — `Product.delete()`
  raises `ProtectedError`). A combo line is only ever removed by editing the combo or
  deleting the combo itself.
- ✅ **A switched-off product is removed from every combo** (owner's decision
  2026-10-02; `products/combo_membership.py`, called from `Product.save()` on the
  `is_active` flip — PATCH, DELETE and Django admin alike). Each removed line is
  remembered in `products.DetachedComboLine` (migration `products/0044`).
  - A combo that was on sale is **switched off at the same moment** (no
    `deactivated_at` stamp, so the purge never takes it): it is no longer the bundle
    its price was set for. ⚠ Don't change this to "keep selling" without the owner —
    the customer would pay the old price for fewer goods.
  - Switching the product back on restores the lines and switches back on the combos
    this rule had switched off — unless an admin edited or re-activated the combo
    meanwhile (`forget_detached_lines`), or it was sent to the Recycle Bin.
  - The product PATCH response carries `combo_changes`; combos expose staff-only
    `missing_products`. `ProductCombo.clean()` now enforces price ≤ MRP only while the
    combo is ACTIVE, so a reduced combo can be edited/binned but not put back on sale
    above its new MRP.
  - Rows changed behind `save()` (queryset `.update()`, bulk SQL) are still covered:
    `available_stock` returns 0 and checkout refuses a combo whose component product
    is off. One-off for existing data, **dry-run first — it switches live combos off**:
    `python manage.py detach_inactive_products_from_combos --dry-run`.

### Availability gaps found 2026-10-02 — FIXED (in the working tree, NOT deployed)

All seven were one problem: something switched off, retired or sold out that one
surface had not been told about. The rule now lives in one place —
`Backend/products/availability.py` (`line_problem`, `line_max_quantity`,
`in_stock_products`/`product_has_stock`, `combo_can_be_built`,
`low_stock_sizes`/`out_of_stock_sizes`) — and every surface below reads from it.
Tests: `products/test_availability.py`, `cart/test_availability.py`,
`orders/test_retired_size_checkout.py`, `products/test_category_hide.py`,
`reviews/test_switched_off_items.py`, `admin_panel/test_low_stock_sizes.py`,
`assistant/test_availability_tools.py`. Full plan (defaults D1–D5, browser checks):
`GAP_FIX_PLAN_2026-10.md`.

- ✅ **A retired size in a cart can no longer be ordered.** Checkout asks
  `line_problem` (400 `no longer available`, no order, stock unchanged) and
  re-checks `is_active` on the locked rows (`orders/views.py`).
- ✅ **Combos show as unavailable before checkout.** Cart caps lines by
  `available_stock` (was hard-coded 999 in `cart/models.py`/`views.py`/
  `serializers.py`); every public combo payload carries boolean `in_stock`
  (assistant `_combo_public`/browse/proposals too).
- ✅ **Search, suggestions, recommendations and the product list's `in_stock`
  read every active size** (`in_stock_products`/`product_has_stock`), not the
  default-size `Product.stock` mirror.
- ✅ **Low-stock (dashboard, daily digest, weekly summary, admin assistant) is
  per size against the product's alert level** (`low_stock_sizes()`; dashboard
  counts distinct products, items name `name (size)`).
- ✅ **Hiding a category with active products is refused** (409 on DELETE / 400
  on PATCH, naming up to 10 products; secondary shelves don't block).
  Already-hidden categories list nothing publicly (`ProductFilter` +
  corpus + category fallback); staff still see them.
- ✅ **Reviews of switched-off products/combos are hidden from shoppers**
  (featured strip, public list; author still sees their own; staff see all;
  featuring one is refused). Nothing deleted — back when the item is back.
- ✅ **A switched-off product / retired size / unbuildable combo in a cart is
  flagged** (`available`/`unavailable_reason`/`in_stock`, summary excludes it,
  `unavailable_count`; storefront greys it, blocks checkout, offers "Remove
  unavailable items", Billing sends back to `/cart`).
- **Hard deletes outside the panel bypass every safeguard:** `Product.category` and
  `Order.user` are `CASCADE`, so deleting a category (Django admin) deletes its
  products, and deleting a user deletes their un-invoiced orders.
- **Bulk edit writes sizes only.** A change without `variant_id` lands on the product's
  default size, never on the Product mirror columns. Price > 0, discount < price (checked
  against the values the row ends up with), errors carry `variant_id`. The panel grid is
  one line per size.
- **Combo saves are one transaction**, lines validated before anything is written;
  `items` accepts a JSON list as well as the multipart JSON string.
- **Un-ticking a size (`PATCH is_active:false`) runs the same guards as DELETE**: refused
  for the last active size and for a size a combo is built from. The panel therefore
  saves active sizes first and retirements last.
- Catalog lookups go through `products.views._as_pk`: an id that is not an id is a 404 /
  empty list, not an exception.
- Local `Backend/.env` still pins `ASSISTANT_MODEL_CONTEXT_TOKENS=200000`, which fails
  two tests in `assistant/test_chat_limits.py` on this machine (unrelated to the above).
