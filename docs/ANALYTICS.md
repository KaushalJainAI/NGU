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
| `DailySalesRollup` | `orders` | revenue/orders/units/AOV/coupon impact/new-vs-returning, plus `gst_collected`, `shipping_collected`, `shipping_cost`. **Excludes `cancelled`.** |
| `DailyFunnelRollup` | `UserEvent` | per-event-type counts/day (logged-in funnel) |
| `SearchTermStat` | `UserEvent(search)` | per-term counts + zero-result flag (from `metadata`) |
| `DailyAnonStat` | Redis counters | flushed by the same command |

New-vs-returning: a customer is **new** on the day of their first-ever
non-cancelled order; everyone else who ordered that day is **returning**.

### Revenue is GROSS — GST is reported alongside, never deducted

`revenue` is `Sum(total_amount)`: the money actually collected, so it reconciles
against Razorpay settlements. GST and delivery are surfaced as **separate**
figures rather than subtracted from it:

| Field | Meaning |
|-------|---------|
| `gst_collected` | Output tax on sales — `Sum(Order.tax)`. Prices are GST-inclusive, so this is contained in `revenue`. |
| `gst_refunded` | Output tax **reversed by refunds**, bucketed by the day the refund happened. |
| `refunds` | Money returned to customers that day. |
| `shipping_collected` | Delivery fees charged to customers. |
| `shipping_cost` | What couriers charged **us**, admin-entered per order (`0` until recorded). Margin = collected − cost. |

`DailySalesRollup.net_gst_collected` = `gst_collected − gst_refunded`. That is the
figure the dashboard tile and the Insights `net_gst_collected` KPI lead with.
`taxable_sales` (`revenue − gst_collected`) is reported next to it: tax collected
means nothing without the sales value it was collected on.

**Refunds reduce GST, and they do it in their own period.** A refund is booked on
the day it happened, never the day of the sale — a credit note reduces output tax
in the period it is issued, so a March refund must not retroactively rewrite a
January return you have already filed. The ledger is `orders.OrderRefund`; see
`orders/refunds.py::refunded_totals_between`.

⚠ **NGU reports tax COLLECTED, never tax PAYABLE — by design.** What is remitted is
output tax minus **input tax credit** on purchases (ingredients, packaging, courier,
gateway fees, rent), and NGU deliberately keeps no purchase ledger: that is what
accounting software is for, and a half-built one produces a number that looks
filed-ready and isn't. So the rule for every surface (dashboard tile, digest, weekly
summary, Insights, HSN report):

* Report **what was sold** and **what tax was collected on it**. Both, together.
* Never name a field `*_payable`, never present a total as "what you owe", and never
  net a partial input credit off the collected figure.
* `mtd_gateway_tax` (GST we paid Razorpay) is shown **on its own line, unsubtracted** —
  it is one evidenced input among many unseen ones, for the owner to carry into their
  books.
* Deciding the liability is the owner's / their accountant's call.

The dashboard still emits `today_gst_payable`, `mtd_gst_payable` and
`mtd_gst_payable_after_known_itc` as **deprecated aliases** so an older admin build
keeps rendering across a rolling deploy. Delete them from `admin_panel/views.py` once
the admin image is rolled out; do not read them in new code.

⚠ **Gateway refunds never reach the ledger — refunds are MANUAL-ONLY (2026-08-01).**
The `refund.processed` branch in `payments/views.py` is commented out, so a Razorpay
refund is logged and ignored, not recorded. Every refund — online or COD — must be
entered by an admin in the order dialog, which writes the same ledger. An unentered
refund leaves its GST un-reversed and overstates the tax owed.

Averages over `shipping_cost` use only orders **with a cost recorded** as the
denominator — averaging across all orders would silently understate it with zeros.

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

⚠ **One-off after deploying migration `analytics/0004`.** It adds
`gst_collected` / `shipping_collected` / `shipping_cost` with `default=0` and
does **not** backfill. The scheduled run only recomputes yesterday + today, so
every historical row keeps reporting ₹0 GST and the Insights GST series
silently under-reports for any range before deploy day. Recompute the whole
history once:

```bash
docker compose -f docker-compose.prod.yml exec backend \
  python manage.py rollup_analytics --days 400   # or however far back orders go
```

`shipping_cost` legitimately stays 0 for past orders — it is admin-entered per
order and was never recorded before this feature existed.

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

## Owner email digests

Two store-owner emails are pushed on a schedule by the `scheduler` container
(`manage.py run_scheduler`, using APScheduler cron triggers), so the owner gets a
summary without opening the dashboard:

| Command | Schedule | Contents |
|---------|----------|----------|
| `send_daily_digest` | daily 08:00 | Yesterday's orders + revenue, orders waiting to ship, and products at/under `low_stock_threshold` |
| `send_weekly_summary` | Mondays 08:30 | Revenue vs. last week, best sellers, and zero-result ("not found") searches |

Both reuse `orders.emails._send_async` (best-effort; a mail failure never breaks the
scheduler). They can also be run manually: `python manage.py send_daily_digest`.

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

## Improvement plan notes (2026-10-01)

- Dashboard actions (cache 
gu:dashboard:actions:v2) reports real sales only (paid online + all COD), with last-week/last-month comparisons, unshipped-aged/out-of-stock/missing-invoice/unclassified-HSN/failed-payment attention counts, and top sellers. MTD GST collected/refunded/net come from the invoice-basis ledger (orders/gst_ledger.py).
- /api/admin/books/summary/ (see admin_panel/books.py) estimates monthly profit and GST from invoices, credit notes, gateway fees, courier costs and Expense rows; always is_estimate: true.

