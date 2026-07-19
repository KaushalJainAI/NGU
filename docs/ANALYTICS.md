# Analytics & Insights

The `analytics` app does two jobs:

1. **Behavioral signal** for the recommendation engine (raw `UserEvent` rows for
   logged-in users — see `RECOMMENDATIONS.md`).
2. **Business insights** for the admin dashboard — aggregate sales + behavioral
   analytics surfaced on the admin-panel **Insights** page.

This document covers (2) and the anonymous-traffic tracking that feeds it.

## Two-track ingest

```
LOGGED-IN visitor                          ANONYMOUS visitor
   POST /api/events/  (raw, batched)          POST /api/anon-events/ (beacon, public)
        │                                           │
        ▼                                           ▼
   UserEvent rows (Postgres)               Redis INCR  ngu:anon:{date}:{metric}:{dim}
        │                                           │  (periodic flush)
        │  rollup_analytics (scheduled)             ▼
        ├───────────────────────────────►  DailyAnonStat (Postgres)
        ▼
   DailySalesRollup / DailyFunnelRollup / SearchTermStat
        │
        ▼
   /api/analytics/*  (IsAdminUser, Redis-cached)
        │
        ▼
   Admin Panel  Insights page  (recharts)
```

### Why two tracks

Logged-in events are bounded by user count and carry identity (needed for
personalisation). Anonymous traffic is unbounded and must stay **identity-free**
and **storage-bounded**, so we never store a row per anonymous event — we only
increment pre-aggregated counters. This is the difference between "row count
grows with traffic" (explodes) and "row count grows with `days × metric ×
dimension`" (flat).

## Anonymous counters (`analytics/anon.py`)

- `record_anon(metric, request, ...)` increments daily counters for each coarse,
  non-identifying **dimension** of the request:
  - `''` — the day/metric grand total
  - `device:{mobile|desktop|tablet|bot}` — parsed from User-Agent
  - `state:{...}` / `city:{...}` — coarse IP geo (see GeoIP below)
  - `source:{google|search|social|referral}` — from the referrer (internal nav excluded)
- **Allowed metrics:** `page_view`, `product_view`, `add_to_cart`, `search`,
  `search_zero_result`, `checkout_started`, `checkout_completed`. Anything else
  is silently dropped.
- **No identity, no session, no cookie.** A returning visitor is — by design —
  indistinguishable from a new one.

### Execution modes

| Redis available? | Write path | `flush_anon_to_db` |
|------------------|-----------|--------------------|
| **Yes** (prod) | Pipeline `INCR` + index `SADD`, TTL 3 days | drains counters (GETSET) into `DailyAnonStat` |
| **No** (tests/dev) | Direct `F()` UPSERT into `DailyAnonStat` | no-op (already in DB) |

Both modes share the dimension-building and aggregation logic, so the test suite
(SQLite + LocMemCache, no Redis) exercises the same business logic used in prod.

### Counter-key schema

```
ngu:anon:{YYYY-MM-DD}:{metric}:{dimension_key|_}   → integer counter
ngu:anon:index:{YYYY-MM-DD}                         → set of "{metric}|{dim}" touched today
```

## Rollup tables

Populated **only** by `python manage.py rollup_analytics` — never by request
views. Idempotent: each run deletes-and-recomputes the target day(s).

| Table | Source | Notes |
|-------|--------|-------|
| `DailySalesRollup` | `orders` | revenue/orders/units/AOV/coupon impact/new-vs-returning. **Excludes `cancelled`.** |
| `DailyFunnelRollup` | `UserEvent` | per-event-type counts/day (logged-in funnel) |
| `SearchTermStat` | `UserEvent(search)` | per-term counts + zero-result flag (from `metadata`) |
| `DailyAnonStat` | Redis counters | flushed by the same command |

New-vs-returning: a customer is **new** on the day of their first-ever
non-cancelled order; everyone else who ordered that day is **returning**.

### Scheduling

Run frequently for "today" + a nightly full pass:

```bash
# every ~5 min (today partial + anon flush)
python manage.py rollup_analytics
# nightly backfill / correction
python manage.py rollup_analytics --days 2
```

Wire via container cron / host crontab / celery-beat — see `DEPLOYMENT.md`.
Until scheduled, the command is fully usable manually. Dashboard "today" is
current within the rollup cadence.

## Insights API

All admin-only (`IsAdminUser`), accept `?from=&to=&granularity=day|week|month`,
Redis-cached for `CACHE_TTL_INSIGHTS` (5 min). Read the rollups.

| Endpoint | Returns |
|----------|---------|
| `GET /api/analytics/sales/` | KPIs (with period-over-period deltas), revenue series, top products/categories |
| `GET /api/analytics/funnel/` | logged-in funnel stage counts + conversion |
| `GET /api/analytics/search/` | top terms, zero-result terms, viewed-not-bought |
| `GET /api/analytics/customers/` | new vs returning, repeat rate, geo, top customers |
| `GET /api/analytics/anonymous/` | macro funnel + device/region/source breakdowns |

The **anonymous funnel is "macro"** — ratios of aggregate stage counts, not a
per-visitor path (we keep no identity). Directional, not exact conversion.

## Decoupled server-side capture (`analytics/signals.py`)

Purchase events are captured via a `post_save` receiver on `Order` (registered
in `AnalyticsConfig.ready()`), deferred to `transaction.on_commit` so order
items are committed before they're read. The orders app does **not** call
analytics inline — analytics subscribes. Removing the app removes its wiring.

## GeoIP (coarse, optional)

Anonymous region uses a local **MaxMind GeoLite2-City** database via Django's
`GeoIP2` (`analytics/geoip.py`). No per-request external call.

- `pip` dep: `geoip2`. Data file at `GEOIP_PATH` (default `Backend/geoip/`).
- Download `GeoLite2-City.mmdb` with a free MaxMind licence key and bake it into
  the image; do **not** commit the file or the key.
- Fully optional: if the package or file is missing, geo is omitted and
  everything else works (`coarse_geo` returns `None`).

## Datastore decision

Postgres (rollups + JSONB `metadata`) + Redis (hot counters) only — **no
separate NoSQL store**. The counter-based anonymous design already bounds row
growth, and JSONB covers schemaless event fields. If analytical volume ever
outgrows this, the documented escape hatch is **TimescaleDB** (a Postgres
extension — same operations, no new database).

## Privacy

Logged-in behavioral tracking and anonymous aggregate analytics are disclosed in
the **Privacy Policy** (`Policy(type='privacy')`), shown at signup (required
agreement) and linked in the storefront footer. Anonymous tracking stores no
identifiers, so there is nothing to "consent to" beyond the policy text — hence
no separate cookie banner.

## Tests

`analytics/tests.py` covers: anon dimension building + bot
bucketing, counter accumulation (bounded-row property), the rollup command
(sales/funnel/search, new-vs-returning, idempotency), insights aggregation
(PoP deltas, funnel/macro-funnel), and API admin-only permissions.
