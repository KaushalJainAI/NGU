# Monitoring & Incident Plan

**Goal:** know within minutes when nidhimasala.com breaks, know *why* without SSHing
around blindly, and keep a record so the same failure never costs a second outage.

Today the stack has **no outward alerting**. If the site goes down at 2am, the first
signal is a customer complaining — or worse, silence and lost orders. This document
is the plan to close that gap, ordered so that the highest-value, lowest-effort work
lands first.

---

## What we have today

| Capability | Status |
|---|---|
| Container restart on crash | ✅ `restart: unless-stopped` on every service |
| Container healthchecks | ⚠️ present but **shallow** (see gap 1) |
| Backend logs | ⚠️ console → docker `json-file`, **unrotated, lost on recreate** |
| Frontend crash screen | ✅ `ErrorBoundary` (added — customer sees "contact us", not a white page) |
| Frontend crash *reporting* | ❌ console only; nobody sees it |
| Uptime alerting | ❌ nothing |
| Error tracking / stack traces | ❌ nothing |
| Host metrics (CPU/RAM/disk) | ❌ nothing |
| TLS expiry alerting | ❌ nothing |
| Incident record | ❌ nothing |

### The five gaps that will actually bite

1. **`/api/health/` lies.** `spices_backend/urls.py:12` returns
   `{'status': 'healthy'}` unconditionally. It never touches Postgres or Redis. So
   if the DB host (`13.201.33.243`) dies, the backend container still reports
   healthy, Docker never restarts it, and every dependent service starts happily
   against a dead database. **The one check the whole stack keys off is the one
   check that cannot fail.** Fixing this is prerequisite to everything else.
2. **Disk fill from unrotated logs.** `docker-compose.prod.yml` sets no `logging:`
   options, so Docker's `json-file` driver grows without bound. On a small EC2
   this is one of the most likely causes of a total, mysterious outage.
3. **Two failure domains, one blind spot.** App is on `13.235.238.99`, Postgres +
   PgBouncer on `13.201.33.243`. Nothing watches the second host at all.
4. **TLS expiry.** Four hostnames across two Let's Encrypt lineages. A silent
   renewal failure is a 100% outage on a 90-day fuse.
5. **No stack traces.** When something 500s, the traceback is in a container log
   that may already have rotated away, and nothing correlates it to the customer
   who hit it.

---

## Phase 1 — Know that it broke (do this first, ~1 hour)

### 1.1 Make the health endpoint tell the truth

Replace the stub in `Backend/spices_backend/urls.py` with two endpoints:

- **`/api/health/`** — liveness. Stays cheap and dependency-free. This is what the
  Docker healthcheck uses: it answers "is this process responsive?" A container
  should not be restart-looped because a *downstream* service is down.
- **`/api/health/ready/`** — readiness. Actually executes `SELECT 1` against
  Postgres and a `PING` against Redis, returns per-dependency status and
  `503` if any hard dependency is down. This is what the external monitor polls.

```python
# Backend/spices_backend/urls.py
import time
from django.db import connection
from django.core.cache import cache

def health_check(request):
    """Liveness: is this process answering? Deliberately touches nothing else —
    a downstream outage must not cause Docker to restart-loop a healthy app."""
    return JsonResponse({'status': 'healthy', 'service': 'ngu-backend'})

def readiness_check(request):
    """Readiness: can we actually serve a request end to end? Polled by the
    external uptime monitor, so it must fail when a dependency fails."""
    checks, healthy = {}, True
    for name, probe in (
        ('database', lambda: connection.cursor().execute('SELECT 1')),
        ('redis', lambda: cache.set('_health', '1', 10)),
    ):
        started = time.monotonic()
        try:
            probe()
            checks[name] = {'ok': True, 'ms': round((time.monotonic() - started) * 1000)}
        except Exception as exc:
            healthy = False
            # Exception text can carry credentials from a DSN — log it, don't return it.
            logger.exception('Readiness probe failed: %s', name)
            checks[name] = {'ok': False, 'error': type(exc).__name__}
    return JsonResponse({'status': 'ready' if healthy else 'degraded', 'checks': checks},
                        status=200 if healthy else 503)
```

Wire it up next to the existing route, and keep the Docker healthcheck pointed at
the **liveness** URL:

```python
path('api/health/', health_check, name='health-check'),
path('api/health/ready/', readiness_check, name='readiness-check'),
```

> Note the deliberate split: readiness returns only the *exception class name*, not
> its message. A `psycopg` connection error stringifies the full DSN, password
> included — and this endpoint is public.

### 1.2 External uptime monitoring (free)

Something outside the EC2 must do the watching — a monitor running on the box that
just died reports nothing. Use **UptimeRobot** (free: 50 monitors, 5-min interval)
or **BetterStack** (free: 10 monitors, 3-min) with alerts to **email + WhatsApp/SMS**.

| Monitor | URL / target | Catches |
|---|---|---|
| Storefront | `https://nidhimasala.com/` | nginx down, frontend container down, cert expired |
| Second domain | `https://nidhigrahudyog.com/` | per-domain cert lineage failure |
| API readiness | `https://nidhimasala.com/api/health/ready/` | DB down, Redis down, backend down |
| Admin panel | `https://nidhimasala.com/panel/` | admin container down |
| Keyword check | `https://nidhimasala.com/` contains `Nidhi` | "200 OK but blank page" — a build that shipped broken |
| TLS expiry | both domains | renewal failure, ~14 days of warning |

The keyword check matters more than it looks: a broken frontend build still serves
`index.html` with a 200. Only content inspection catches it.

### 1.3 Rotate the logs

Add to **every** service in `docker-compose.prod.yml`:

```yaml
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"
```

Then a disk alarm so you learn about it before it's fatal — a cron on both hosts:

```bash
# crontab -e  — hourly disk check, alerts above 80%
0 * * * * [ $(df / | awk 'NR==2{print $5}' | tr -d '%') -gt 80 ] && \
  curl -s -X POST "https://api.telegram.org/bot<TOKEN>/sendMessage" \
    -d chat_id=<CHAT_ID> -d text="⚠️ $(hostname): disk $(df -h / | awk 'NR==2{print $5}')"
```

**Deliverable of Phase 1:** you get a message on your phone within ~5 minutes of the
site going down, on any of the four domains, for any of the common causes.

---

## Phase 2 — Know *why* it broke (~2 hours)

### 2.1 Error tracking with Sentry (free tier: 5k errors/month)

This is the single highest-value addition after alerting. It turns "the site was
weird yesterday" into a stack trace with the exact request, user, and release.

```bash
# Backend/requirements.txt
sentry-sdk[django]==2.*
```

```python
# Backend/spices_backend/settings.py — near the bottom, prod only
SENTRY_DSN = os.environ.get('SENTRY_DSN', '')
if SENTRY_DSN and not DEBUG:
    import sentry_sdk
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        environment=os.environ.get('SENTRY_ENVIRONMENT', 'production'),
        release=os.environ.get('IMAGE_TAG', 'unknown'),   # ties an error to a deploy
        traces_sample_rate=0.05,        # 5% perf traces — enough to spot slow endpoints
        send_default_pii=False,         # never ship customer PII to a third party
    )
```

Add the same for both React apps (`@sentry/react`), so the `ErrorBoundary` reports
instead of only logging. In `ErrorBoundary.componentDidCatch`, replace the console
line with a `Sentry.captureException(error, { extra: { errorRef } })` — the
reference code shown to the customer then matches the Sentry event, so when someone
WhatsApps you "NGU-2607200855-MFKU", you search that string and see the exact crash.

**Alert rules worth setting:** any *new* error type; error rate spike >10×; any error
on `/billing`, `/api/orders/`, or `/api/payments/` (money paths get zero tolerance).

### 2.2 Client-error ingest (alternative, if you'd rather not use a third party)

Add `POST /api/client-errors/` — heavily throttled, unauthenticated, accepting
`{ref, message, stack, url, user_agent}` — writing to a `ClientError` model, and
surface a list in the admin panel. Cheaper on privacy, more work to build, and no
alerting unless you add it. Sentry is the better default; this is the fallback if
you want everything on your own infrastructure.

### 2.3 Structured logs with request IDs

Add a middleware that stamps every request with an ID (`X-Request-ID`, echoed in the
response header) and log in JSON. Then a customer-reported problem, an nginx access
log line, a Django traceback, and a Sentry event all join on one key. Without this,
correlating across those four sources is guesswork.

Ship logs off the host so a container recreate doesn't erase the evidence — Grafana
Cloud Loki's free tier (50GB/month) is comfortably more than this app produces.

### 2.4 Watch the money path specifically

Order and payment failures are the outages that cost real money, and they usually
do *not* take the site down — so uptime monitoring will never catch them. Add a
scheduled check (fits naturally into the existing `run_scheduler` container):

- Zero orders in the last 6 hours during business hours → alert.
- Any order stuck `payment_status='pending'` beyond `PAYMENT_STUCK_TTL_MINUTES` × 3
  → alert (means `reconcile_payments` itself is wedged).
- Razorpay webhook received but no matching order → alert.
- `reconcile_payments` / `rollup_analytics` hasn't logged a successful run in 30 min
  → alert. **The scheduler dying silently is a genuine risk**: nothing currently
  watches it, and its failure is invisible from the outside.

---

## Phase 3 — Fix it fast, and stop it recurring (~2 hours)

### 3.1 Host metrics

Netdata (free, one-line install, self-hosted dashboard) on **both** EC2 hosts gives
CPU, RAM, disk, and per-container stats with almost no configuration. Given the
history of OOM kills on this box (whisper hit its memory cap mid-inference), memory
alerting is not theoretical here.

Alert on: memory >85%, swap heavily used, disk >80%, CPU >90% sustained 10 min,
container restart count climbing.

### 3.2 A runbook, kept next to this file

For each alert, write down: what it means, the first command to run, the most likely
cause, and the fix. At 2am you want to follow a list, not think. Start with:

```
ALERT: api/health/ready → 503, database check failing
  1. curl -s https://nidhimasala.com/api/health/ready/ | jq   → which dep is down?
  2. ssh 13.201.33.243; docker compose ps                     → postgres/pgbouncer up?
  3. docker compose logs --tail=100 pgbouncer                 → connection pool exhausted?
  4. Most likely: PgBouncer max connections, or the app host's security group
     rule to :6432 changed.
  5. Fix: docker compose restart pgbouncer, then verify with step 1.
```

### 3.3 Incident log

Append-only `INCIDENTS.md`, one entry per outage — this is how uptime actually
improves, because it converts each outage into a permanent fix rather than a
repeated 2am scramble:

```markdown
## 2026-07-20 — Storefront 502 for 18 minutes
- **Detected:** UptimeRobot, 14:32 IST (alert → phone)
- **Impact:** all four domains, ~18 min, 3 checkouts abandoned
- **Cause:** backend OOM-killed; whisper container spiked during voice transcription
- **Fix:** raised whisper memory cap to 1G, added 2G swap
- **Prevention:** memory alert at 85% (Netdata); whisper capped below host limit
- **Time to detect / to fix:** 2 min / 16 min
```

Track two numbers over time: **time-to-detect** and **time-to-fix**. Phase 1 collapses
the first from hours to minutes; Phase 2 collapses the second.

### 3.4 Pre-deploy safety

Most outages are self-inflicted, arriving with a deploy. Cheap guards:

- Smoke-test after `up -d`: poll `/api/health/ready/` until 200, then `curl` the
  storefront and grep for a known string. Fail the deploy script if either fails.
- Keep the previous image tag pinned so rollback is `IMAGE_TAG=<prev> docker compose up -d`.
- Never `docker compose down` on prod — `up -d` recreates only changed containers.

---

## Suggested order of work

| # | Task | Effort | Value |
|---|---|---|---|
| 1 | Real readiness endpoint (1.1) | 30 min | 🔴 Critical — everything depends on it |
| 2 | UptimeRobot + phone alerts (1.2) | 20 min | 🔴 Critical — this is "I know it's down" |
| 3 | Log rotation + disk alarm (1.3) | 15 min | 🔴 Critical — prevents a likely outage |
| 4 | Sentry, backend + both frontends (2.1) | 1 hr | 🟠 High — this is "I know why" |
| 5 | Netdata on both hosts (3.1) | 30 min | 🟠 High |
| 6 | Runbook + INCIDENTS.md (3.2, 3.3) | 45 min | 🟠 High — compounding value |
| 7 | Business-metric alerts (2.4) | 1 hr | 🟡 Medium — catches silent money loss |
| 8 | Request IDs + log shipping (2.3) | 2 hr | 🟡 Medium |
| 9 | Deploy smoke tests (3.4) | 45 min | 🟡 Medium |

Total cost at these volumes: **₹0/month** — every tool listed has a free tier that
comfortably covers a store this size.

---

## Related

- `DEPLOYMENT.md` — EC2 deploy, nginx, cert issuance
- `TROUBLESHOOTING_AWS_MIGRATION.md` — past infrastructure failures worth re-reading
- `Backend/docs/PAYMENTS_INTEGRATION.md` — the reconciliation behaviour §2.4 monitors
- `Frontend/nidhi-brand-forge/src/components/ErrorBoundary.tsx` — customer-facing crash screen
