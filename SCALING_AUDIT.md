# NGU — Resource Consumption & Scaling Audit

**Date:** 2026-08-27
**Target box (assumed fixed):** 1 VPS, 2 vCPU / 8 GB / 100 GB NVMe, Docker Compose.
**Load envelope:** 50k–200k visitors/month, 20–60 orders/day, seasonal spikes to 20×.

## How to read this

Everything below is derived from reading the code in this repo. Where I measured
something, I say **[measured]**. Where I am reasoning from the code without
running it against a real dataset, I say **[inferred]**. Per the standing rule in
CLAUDE.md I did **not** touch production or the prod database, so there are no
live timings here — the latency columns are estimates from query counts and known
network costs, not observations.

### Two facts that reshape the whole audit

1. **The catalogue is tiny.** `DATABASE_FILLING.md` records **25 products** and an
   empty combo table as of 2026-06-11 **[measured, from docs]**. Almost every
   "unbounded queryset" in this codebase is currently unbounded over ~25 rows.
   That moves a lot of classic scaling findings from *urgent* to *latent*.
2. **The concurrency budget is 6.** `Backend/Dockerfile` ends with
   `gunicorn ... --workers 3 --threads 2` **[measured]**. Three processes, two
   threads each. That is the entire request-handling capacity of the site. Every
   blocking-I/O finding below should be read against the number **6**.

The real risk in this system is **not** database volume. It is that a handful of
request paths can each hold one of those 6 slots open for an unbounded amount of
time, and there is nothing — not gunicorn, not nginx, not the HTTP clients —
configured to stop them.

### Deviations from the brief's assumed topology

The brief describes Celery, PgBouncer and Postgres 16 on the box. What's actually
deployed (`docker-compose.prod.yml` **[measured]**):

- **No Celery, no broker.** Background work is an APScheduler process
  (`scheduler` container, `manage.py run_scheduler`). Async email is raw
  `threading.Thread` (`orders/emails.py:93`). So "move it to Celery" is not a
  config change here — it is new infrastructure. Recommendations below prefer
  fixes that work *without* introducing a broker.
- **PgBouncer is on a different box** (`13.201.33.243:6432`), not this one, and
  its pool mode is not visible from this repo. Phase 3 flags what to check.
- Postgres is **17**, not 16, and also on the other box.

---

# Phase 1 — Request paths

## The 10 hottest endpoints

Ranked by inferred call volume, derived from what the storefront actually fetches.
`Frontend/nidhi-brand-forge/src/pages/Index.tsx:75-81` **[measured]** fires five
API calls in one `Promise.all` on every homepage mount, plus recommendations,
plus the cart, plus an analytics beacon.

| # | Endpoint | View | Sync/async | Est. queries | Blocking external calls | Est. p50 | Est. p99 |
|---|---|---|---|---|---|---|---|
| 1 | `GET /api/products/` | `ProductViewSet.list` | sync (WSGI) | **3** (cache miss) / **0** (hit) | none | 8 ms hit, 35 ms miss | 120 ms |
| 2 | `GET /api/products/sections/` | `ProductViewSet.sections` | sync | **1 + 4N** (N = sections) ≈ **25** | none | 10 ms hit, 180 ms miss | 900 ms |
| 3 | `GET /api/categories/` | `CategoryViewSet.list` | sync | 2 | none | 8 ms | 60 ms |
| 4 | `GET /api/combos/` | `ComboProductViewSet.list` | sync | 4 | none | 8 ms hit, 45 ms miss | 150 ms |
| 5 | `GET /api/reviews/featured/` | `ReviewViewSet.featured` | sync | **2, uncached** | none | 15 ms | 200 ms |
| 6 | `GET /api/cart/` | `CartViewSet.list` | sync | **6 + 4C** (C = combo lines) | none | 25 ms | 400 ms |
| 7 | `POST /api/anon-events/` | `ingest_anon` | sync | 0 (Redis INCR) | none | 4 ms | 40 ms |
| 8 | `GET /api/products/{slug}/` | `ProductViewSet.retrieve` | sync | 4 | none | 15 ms | 120 ms |
| 9 | `GET /api/search/?q=` | `unified_search` | sync | **2–4 + CPU fuzzy pass** | none | 25 ms | 300 ms |
| 10 | `GET /api/recommendations/` | `recommendations` | sync | **8 + full catalogue into RAM** | none | 20 ms hit, 120 ms miss | 600 ms |

**Everything is a synchronous WSGI view.** `spices_backend.wsgi:application` is what
gunicorn serves; there is not one `async def` handler in the project **[measured]**.
Async views would not help anyway without an ASGI server, which isn't deployed.

## Per-endpoint detail

### 1. `GET /api/products/` — the whole catalogue, every time

`products/views.py:236-289`. Three queries on a miss: the annotated product
queryset (`select_related('category')` + `Avg`/`Count` over reviews), then
prefetches for `variants` and `sections`. **No N+1** — this one is genuinely well
optimised. Two structural notes:

- `pagination_class = None` (`products/views.py:229`). The endpoint returns the
  **entire active catalogue** in one array. At 25 products that's ~60–150 KB of
  JSON **[inferred]**; at 2,000 products it is 5–12 MB and this becomes the single
  worst endpoint on the site. It is fine *today* and a landmine later.
- The cache key is built from **unfiltered user input** — see Phase 5, risk #4.
  This is the most exploitable line in the backend.

### 2. `GET /api/products/sections/` — the real N+1

`products/views.py:352-379` iterates `ProductSection.objects.filter(is_active=True)`
with **no `prefetch_related`**, then `HomepageSectionSerializer`
(`products/serializers.py:216-251`) calls `obj.get_products()` and
`obj.get_combos()` per section. Each of those
(`products/models.py:106-132`) is its own queryset with its own prefetch:

```
1   sections
+   per section:  products (1) + variants prefetch (1)
                  combos   (1) + combo-item prefetch (1)
```

Six sections ⇒ **25 queries** **[inferred from code]**. Worse: any section with no
curated placements falls into `_fallback_products`
(`products/serializers.py:230-243`), which does
`list(Product.objects.filter(is_active=True).select_related('category'))` — the
**entire catalogue materialised into a Python list, once per empty section**, just
to rotate it and slice `max_products` off the front. Six empty sections = six full
catalogue loads in one request.

This is cached for 5 minutes for anonymous users, so the cost lands on cache
misses only — but see Phase 5 for why the cache is easy to evict.

### 3–4. Categories / combos

`CategoryViewSet` annotates `_products_count` so the serializer doesn't COUNT per
row (`products/views.py:76-82`) — correct. `ComboProductViewSet.get_queryset`
uses `with_mrp()` plus prefetches of `productcomboitem_set__product/__variant`
(`products/views.py:404-437`) — also correct, and the comments show someone
already fixed an N+1 here.

### 5. `GET /api/reviews/featured/` — uncached, on every homepage load

`reviews/views.py:136-162`. Two queries, one of which is
`.order_by('-rating', '-created_at')`. `Review` has **no `Meta.indexes` at all**
**[measured]** — no index on `is_hidden`, `is_featured`, or `rating`. Trivial at
current row counts; a sort-on-disk once reviews reach five figures. There is no
caching on a payload that changes maybe weekly.

### 6. `GET /api/cart/` — N+1 on combo lines, called on every page

This is the worst read path for a logged-in user. `CartResponseSerializer`
(`cart/serializers.py:164-224`) runs **two independent querysets** over
`cart.items` — one in `get_items`, one in `get_summary` — neither shared, plus
`cart.total_price` (`cart/models.py:50-77`) which is a third aggregate query.

Then, per combo line, in `get_summary`:

- `allocate_combo_components(ci.combo, ...)` (`orders/pricing.py:279-286`) —
  `select_related` is only applied when `productcomboitem_set` was **not**
  prefetched, and `get_summary`'s queryset does **not** prefetch it. ⇒ **1 query
  per combo line.**
- `ci.subtotal` → `combo.final_price` → `ProductCombo.price` →
  `total_original_price` (`products/models.py:934-955`), which falls through to
  `self.productcomboitem_set.aggregate(...)` because `_mrp` is not annotated on
  this path. ⇒ **another query per combo line.**

And `CartItemResponseSerializer.get_price`/`get_originalPrice` walk the same
properties again in `get_items`. A cart with five combo lines is roughly
**6 + 4×5 = 26 queries** **[inferred]** for one `GET /api/cart/`.

### 7. `POST /api/anon-events/` — the best-engineered path here

`analytics/views.py:76-100`. Unauthenticated by design, no DB write, Redis
counters flushed by the scheduler. `DailyAnonStat` is bounded by
`days × metric × dimension` and does not grow with visitor count. This is the
right pattern; nothing to fix.

### 9. `GET /api/search/` — pure CPU, and **not cached**

`products/views.py:634-668` → `SpiceSearchEngine.unified_search`. The corpus is
Redis-cached for 15 min (`products/recommendations.py:117-118`), but the *result*
is not. Per request:

- JSON-deserialise the whole corpus out of Redis (the cache uses
  `django_redis.serializers.json.JSONSerializer`, `settings.py:677`), then
- **two full `rapidfuzz.process.extract` passes with `limit=None`** over every
  corpus entry — once with `token_set_ratio`, once with `WRatio`
  (`products/recommendations.py:165-171`), then
- a second pair of passes for combos, then DB fetches for the winners.

Corpus size ≈ 25 products × (name + slug + ~3 tokens + weight token + category +
up to 35 synonyms) ≈ **~1,000 entries** **[inferred]**. rapidfuzz is C++ and fast,
so ~2–5 ms of CPU per request today. At 2,000 products it is ~80,000 entries and
this becomes 100–300 ms of pure CPU **on a 2-vCPU box with 6 request slots**.

Note the interesting asymmetry: `search_suggest` **is** cached
(`products/views.py:686-687`) and has its own 60/min throttle; `unified_search`
has **neither**. It falls under the generic `anon: 1000/hour`.

### 10. `GET /api/recommendations/` — full catalogue scan per user, 60 s TTL

`products/personalization.py:154-190`. On a cache miss:
`OrderItem` category scan, `Favorite` scan, `CartItem` scan, `UserEvent` 30-day
scan, `_purchased_product_ids`, then `_copurchase_counts` — a **nested subquery
over the whole `OrderItem` table** (`personalization.py:107-119`) — then
`candidates = list(Product.objects.filter(is_active=True, stock__gt=0)...)`,
the entire catalogue into Python, scored in a Python loop. ~8 queries plus
O(catalogue) Python work.

Cached at `TTL_SHORT` = **60 seconds**, per `(user, context, limit, language)`.
That is a very short TTL for a signal that changes on the order of days. With
2,000 concurrent logged-in users you recompute this 2,000 times a minute.

## External network calls in the request cycle

| Call | Where | In request cycle? | Timeout | Notes |
|---|---|---|---|---|
| **Razorpay `order.create`** | `payments/views.py:247` | **YES** | **NONE** | See Phase 2 #1 |
| **Razorpay `utility.verify_payment_signature`** | `payments/views.py:326` | YES | local HMAC, no network | safe |
| **Razorpay webhook verify** | `payments/views.py:386` | YES | local HMAC | safe |
| **LLM (OpenRouter), 1–4× per turn** | `assistant/agent.py:156` | **YES** | **NONE set** | See Phase 2 #2 |
| **LLM synonym generation** | `products/recommendations.py:411` | No — admin/management only | none | acceptable |
| Voxtral STT | `assistant/voxtral_client.py:58` | YES | 30 s | bounded |
| whisper.cpp STT | `assistant/whisper_client.py:51` | YES | 30 s | bounded, but see Phase 2 #3 |
| Nominatim reverse-geocode | `analytics/views.py:154` | YES | 6 s | bounded + 30-day cache. Fine. |
| SMTP (order mail, OTP) | `orders/emails.py:70` | No — background thread | **none** | See Phase 2 #5 |
| Cloudinary | admin uploads only | YES | SDK default | admin-only, low volume |

**Cloudinary is not in any customer-facing request path** — images are served
directly from Cloudinary's CDN by URL. Good.

## File I/O, image processing, in-process inference

- **No in-process ML.** whisper runs in its own container; the LLM and STT are
  HTTP calls. Nothing loads a model into the Django process. **[measured]**
- **reportlab PDF generation** is in-request (`orders/views.py:1505`,
  `orders/views.py:1597`) — invoices, credit notes, packing slips. Staff/owner
  traffic, single-digit per day. CPU-bound for ~50–200 ms **[inferred]**. Not a
  concern at this volume.
- **Delivery-bill upload/stream** (`orders/views.py:1642`) — staff-only, 10 MB cap,
  reads into memory. Low volume.
- **Whitenoise** serves collected static through gunicorn (`settings.py:68`) when
  `USE_S3` is off. It's compressed + manifest-cached, but it does mean static
  requests consume one of the 6 slots. Prod uses S3 for static, so this is
  currently latent.

---

# Phase 2 — Worker-blocking operations

The pool is **3 processes × 2 threads = 6**. One important mechanical detail:
gunicorn's `--timeout` (default 30 s) is a **worker liveness** check, and the
`gthread` worker calls `notify()` from its accept loop independently of what its
threads are doing. **A slow request in a gthread worker does not trip the arbiter
timeout.** There is therefore *no* automatic recovery from a hung handler —
the thread stays consumed until the socket dies. **[inferred from gunicorn's
`ThreadWorker.run` design; verify against your installed version]**

Ranked by how easy it is to exhaust the pool.

### #1 — Razorpay SDK calls have no timeout at all

`payments/gateway.py:23` constructs `razorpay.Client(auth=...)` with no session and
no timeout. Reading the vendored SDK
(`venv/Lib/site-packages/razorpay/client.py:180-184`) **[measured]**:

```python
response = getattr(self.session, method)(url, auth=auth_to_use,
                                         verify=self.cert_path,
                                         **options)
```

No `timeout=` is passed and none is defaulted. `requests` with no timeout waits
for the OS TCP timeout — **minutes to hours** on a black-holed connection.

- **Blocks for:** unbounded. Realistically 15–20 min per hung call.
- **Users to exhaust the pool:** **6.** Six checkouts during a Razorpay network
  partition and the entire API — catalogue, cart, everything — stops responding.
- **Fix:** pass a session with a timeout (diff in the Concrete Diffs section).
  Cheap, ~10 lines, no behaviour change on the happy path.

### #2 — The assistant's agent loop: no timeout × up to 4 iterations

`assistant/agent.py:76-84` **[measured]**:

```python
return ChatOpenAI(
    model=model_name,
    openai_api_key=api_key,
    openai_api_base=...,
    temperature=0.2,
    max_tokens=MAX_OUTPUT_TOKENS,
    extra_body=openrouter_extra_body(),
)
```

No `timeout=` / `request_timeout=`, and no `max_retries=`. The underlying `openai`
SDK defaults to a **600 s timeout with 2 retries** — up to **1,800 s per
`_complete()` call**. `Agent.run` loops `for _ in range(MAX_ITERATIONS)` with
`MAX_ITERATIONS = 4` (`agent.py:26, 213`), calling `_complete` each pass, plus one
extra pass on a JSON-repair retry.

- **Blocks for:** p50 ~6–12 s (2–3 iterations of a real LLM call, plus tool
  round-trips). Worst case **~2 hours** for one HTTP request.
- **Users to exhaust the pool:** **6** — and the throttle is `assistant: 20/min`
  *per user*, so **one** logged-in account can open 6 parallel chat requests and
  take the site down. This is not a spike problem; it is a Tuesday problem.
- **Also:** `AssistantChatView.post` holds a DB connection for the entire LLM
  round-trip (`CONN_MAX_AGE = 60`), and each read-tool observation adds another
  DB query mid-loop.
- **Fix:** set a hard timeout, cut `max_retries`, and put an overall wall-clock
  budget on the loop. Longer term this endpoint wants to be
  `202 Accepted` + poll, but that needs a job runner you don't have yet.

### #3 — STT: up to 60 s per request, and the fallback is the slow path

`assistant/stt.py:72-84`. `voxtral` (30 s timeout) failing over to `whisper`
(30 s timeout) = **60 s worst case per request**. And per the module's own
docstring **[measured]**, whisper.cpp runs at *~20 s per second of audio* on a
2-vCPU box — so the fallback path essentially always burns its full 30 s and then
fails. Throttle is `assistant_stt: 15/min` per user.

- **Blocks for:** 1–60 s.
- **Users to exhaust the pool:** 6 concurrent voice messages during an OpenRouter
  outage.
- **Fix:** drop `WHISPER_TIMEOUT` to something honest (5 s) or, better, set
  `STT_FALLBACK_TO_WHISPER=False` in prod — a fallback that cannot succeed on
  this hardware is just a way to hold threads.

### #4 — `unified_search` is uncached CPU on a 2-vCPU box

Covered in Phase 1 #9. Not *blocking* I/O — it's the opposite, it's CPU — but it
matters because with `--threads 2` the GIL means two threads in one worker
contend for one core. Two concurrent searches in the same worker serialise.

- **Blocks for:** 2–5 ms today; 100–300 ms at 100× the catalogue.
- **Fix:** cache the response (same shape as `search_suggest` already does) and
  give it a dedicated throttle scope.

### #5 — Unbounded thread spawn for email

`orders/emails.py:93` **[measured]**:

```python
threading.Thread(target=_worker, daemon=True).start()
```

One raw OS thread per email, no pool, no queue. The worker retries 3× with
`time.sleep(2 * attempt)` — so **6 s of sleeping minimum** on a flaky SMTP, plus
SMTP socket time. `EMAIL_TIMEOUT` is **not set** in `settings.py` **[measured]**,
so `smtplib` uses the global default socket timeout (`None` unless something else
sets it) — a hung SMTP server holds the thread indefinitely.

This does **not** block a gunicorn worker (that's the point of the design), but:

- Each thread has an 8 MB stack reservation; RSS growth is small but real.
- Gmail SMTP will rate-limit and then these threads pile up.
- `connections.close_all()` in the `finally` is correct and worth keeping.

Low priority at 20–60 orders/day. It becomes a real problem the day someone
writes a bulk-notify feature.

### #6 — Synchronous `.get()` on Celery

**None found.** There is no Celery. Nothing to fix.

### #7 — Unbounded queryset iteration in a handler

- `personalization.py:172` — `list(Product.objects.filter(...))`, full catalogue.
- `serializers.py:233` — `list(Product.objects.filter(is_active=True)...)`, full
  catalogue, **once per empty homepage section**.
- `recommendations.py:186` — the corpus list, and the `texts = [e['text'] for e in corpus]`
  list rebuilt **four times per search request** (twice in `_score_matches`,
  once per object type).
- `orders/views.py:1755-1790` — CSV export streams via a generator but the
  queryset is *not* `.iterator()` (deliberately — the comment explains
  `prefetch_related` would be dropped). Admin-only, but it materialises every
  matching order. Cap it or accept the memory spike.

None of these are dangerous at 25 products. All of them are O(catalogue) per
request, which is the wrong shape.

---

# Phase 3 — Database

## Missing indexes

The model layer here is better-indexed than most. `Order`, `Product`,
`ProductCombo`, `Category`, `ProductVariant` and `UserEvent` all carry explicit
`Meta.indexes` **[measured]**. What's missing:

### 3.1 `User.email` — login does a sequential scan **[measured]**

`users/views.py:426`, `users/serializers.py:22`, `users/serializers.py:49`:

```python
user = User.objects.filter(email__iexact=email).first()
```

`email__iexact` compiles to `UPPER("email") = UPPER($1)` in Postgres, which
**cannot use the plain unique btree index on `email`**. Every login, every
registration uniqueness check, and every password-reset request does a full scan
of the user table.

There is a nice irony here: `User.save()` (`users/models.py:34-40`) already
normalises email to lower case on every write, so `__iexact` is **redundant** —
a plain `email=` lookup would be both correct and indexed. Two ways to fix it;
the functional index is the safe one because it works even if a legacy
mixed-case row exists.

```python
# Backend/users/migrations/00XX_user_email_lower_index.py
from django.db import migrations, models
from django.db.models.functions import Lower


class Migration(migrations.Migration):
    dependencies = [("users", "<previous>")]

    operations = [
        migrations.AddIndex(
            model_name="user",
            index=models.Index(Lower("email"), name="user_email_lower_idx"),
        ),
    ]
```

### 3.2 `UserEvent.created_at` alone **[measured]**

`analytics/models.py:67-73` indexes `('user', '-created_at')` and
`('user', 'event_type')`. But `rollup_analytics` scans **by date across all
users** (`rollup_analytics.py:179-181`, `:195-197`):

```python
UserEvent.objects.filter(created_at__gte=start, created_at__lt=end)
```

A leading-column-`user` composite index does not serve that. Today this is a seq
scan of a small table; it becomes a nightly full scan of a multi-million-row
table.

```python
# Backend/analytics/migrations/00XX_userevent_created_at_index.py
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("analytics", "<previous>")]

    operations = [
        migrations.AddIndex(
            model_name="userevent",
            index=models.Index(fields=["-created_at"], name="userevent_created_idx"),
        ),
        # _rollup_search filters event_type='search' within a date window.
        migrations.AddIndex(
            model_name="userevent",
            index=models.Index(fields=["event_type", "-created_at"],
                               name="userevent_type_created_idx"),
        ),
    ]
```

### 3.3 `Order.payment_status` **[measured]**

`Order.Meta.indexes` has `status`, `-created_at`, `(user, -created_at)`,
`(is_deleted, -created_at)` — but **not** `payment_status`.
`reconcile_payments` runs every 5 minutes forever with
(`payments/management/commands/reconcile_payments.py:54-56`):

```python
payment_status__in=['pending', 'processing'], created_at__lt=cutoff
```

```python
migrations.AddIndex(
    model_name="order",
    index=models.Index(fields=["payment_status", "created_at"],
                       name="order_paystatus_created_idx"),
),
```

This one is a partial-index candidate — the interesting rows are a tiny minority:

```python
migrations.AddIndex(
    model_name="order",
    index=models.Index(
        fields=["created_at"],
        name="order_unsettled_idx",
        condition=models.Q(payment_status__in=["pending", "processing"]),
    ),
),
```

### 3.4 `Review` has no indexes whatsoever **[measured]**

`reviews/models.py:46-60` declares only unique constraints. The product-list
annotation joins reviews filtered on `is_hidden=False`, and
`/reviews/featured/` sorts on `-rating, -created_at`.

```python
migrations.AddIndex(
    model_name="review",
    index=models.Index(fields=["product", "is_hidden"], name="review_prod_hidden_idx"),
),
migrations.AddIndex(
    model_name="review",
    index=models.Index(fields=["combo", "is_hidden"], name="review_combo_hidden_idx"),
),
migrations.AddIndex(
    model_name="review",
    index=models.Index(fields=["is_hidden", "-rating", "-created_at"],
                       name="review_featured_sort_idx"),
),
```

### 3.5 `AssistantMessage` / `AssistantConversation` **[measured]**

`assistant/models.py:81-84, 146-149` declare `ordering` but no indexes.
`_annotate_last_message` (`assistant/views.py:52-59`) runs a correlated subquery
per conversation row ordering by `-created_at, -id` filtered on
`conversation` + `role__in`. And the admin list sorts by `-updated_at`.

```python
migrations.AddIndex(
    model_name="assistantmessage",
    index=models.Index(fields=["conversation", "-created_at"], name="asstmsg_conv_created_idx"),
),
migrations.AddIndex(
    model_name="assistantconversation",
    index=models.Index(fields=["-updated_at"], name="asstconv_updated_idx"),
),
migrations.AddIndex(
    model_name="assistantconversation",
    index=models.Index(fields=["needs_human", "-updated_at"], name="asstconv_needshuman_idx"),
),
```

## Unbounded tables

| Table | Growth driver | Bounded? | Recommendation |
|---|---|---|---|
| `analytics_userevent` | up to 50/request, `events: 600/hour` per user | **No. No prune command exists.** **[measured]** | **Highest-priority retention item.** See below. |
| `assistant_assistantmessage` | 2 rows per chat turn, forever | **No** | Purge threads with no activity in 180 days. |
| `assistant_assistantconversation` | 1 per chat thread | **No** | Same job. |
| `payments_paymentevent` | one per gateway/reconcile transition; L3 runs every 5 min | **No** | Keep 24 months (audit value); archive beyond. |
| `orders_order` + items | 20–60/day ⇒ ~20k/year | Effectively yes | Nothing needed. `RECYCLE_BIN_RETENTION_DAYS` handles soft-deletes. |
| `analytics_dailyanonstat` | `days × metric × dimension` | **Yes, by design** | Nothing. This is the model to copy. |
| `analytics_searchtermstat` | distinct terms per day | Weakly — a search-spam run inflates it | Cap to top-N terms per day in the rollup. |
| Sessions | `SESSION_ENGINE = cache` | Yes (Redis TTL) | Nothing — but see Phase 5. |

`UserEvent` is the one that actually runs away. At 200k visitors/month with even a
5% login rate and 20 events per session, that is **~200k rows/month, 2.4M/year**,
and the rollups already extract everything the dashboard needs. The raw rows only
matter for the 30-day personalisation window (`RECENT_DAYS = 30`,
`personalization.py:48`).

```python
# Backend/analytics/management/commands/prune_events.py
from datetime import timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone
from analytics.models import UserEvent

RETENTION_DAYS = 90  # 3x the 30-day personalisation window


class Command(BaseCommand):
    help = "Delete UserEvent rows older than the retention window."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=RETENTION_DAYS)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **opts):
        cutoff = timezone.now() - timedelta(days=opts["days"])
        qs = UserEvent.objects.filter(created_at__lt=cutoff)
        if opts["dry_run"]:
            self.stdout.write(f"would delete {qs.count()} rows older than {cutoff}")
            return
        # Chunked so a single statement never holds a long lock or a huge
        # transaction on the shared DB box.
        total = 0
        while True:
            ids = list(qs.values_list("id", flat=True)[:10_000])
            if not ids:
                break
            deleted, _ = UserEvent.objects.filter(id__in=ids).delete()
            total += deleted
        self.stdout.write(f"deleted {total} rows older than {cutoff}")
```

Wire it into `run_scheduler` next to `purge_recycle_bin` (nightly, ~03:45).
**Run the rollup first, prune second** — the rollups are the durable record.

Partitioning `UserEvent` by month is the "right" answer if it ever exceeds ~10M
rows, but at this traffic a 90-day prune keeps it under ~600k rows forever, and
that is a far smaller change.

## Queries that degrade non-linearly

| Query | Where | Why it degrades |
|---|---|---|
| `_copurchase_counts` | `personalization.py:107-119` | `OrderItem.filter(product_id__in=purchased).values_list('order_id')` fed into a second `OrderItem.filter(order_id__in=...)`. Both sides grow with total order history; a repeat customer's set explodes. **O(orders × items)** per cache miss. |
| `_compute_popularity` | `personalization.py:222-227` | `OrderItem.values('product_id').annotate(Count)` over **the entire table, no date bound**. Cached 5 min globally, so cost is amortised — but it is a full-table aggregate forever. Bound it to the last 90 days. |
| `Product` list | `products/views.py:229` | `pagination_class = None`. Linear in catalogue size, and the payload is linear too. |
| `DashboardViewSet.list` | `admin_panel/views.py:161-170` | Bare `.count()` calls on `Order`, `Product`, `ProductCombo`. Postgres `COUNT(*)` is a full scan (no MVCC shortcut). Cached 120 s, admin-only. Fine now; swap for `pg_class.reltuples` if orders pass ~1M. |
| `DashboardViewSet.actions` | `admin_panel/views.py:189-399` | **~20 aggregates and counts in one handler.** Cached 60 s, admin-only. The 60 s TTL means the owner's dashboard tab recomputes all 20 every minute, all day. Raise to 300 s. |
| `GlobalAdminSearchView` | `admin_panel/views.py:556-579` | `name__icontains` / `code__icontains` ⇒ `ILIKE '%q%'` ⇒ **guaranteed seq scan, no index can help**. Admin-only. See fuzzy-search note below. |
| Offset pagination | `settings.py:305-306`, `PAGE_SIZE = 12` | `PageNumberPagination` = `LIMIT/OFFSET`. Page 5,000 of the admin order list means Postgres walks 60,000 rows. Only reachable by an admin deliberately deep-paging; keyset pagination is not worth it yet. |

## Full-text / fuzzy search — no pg_trgm anywhere **[measured]**

There is **no** `pg_trgm`, no `GinIndex`, no `SearchVector`, and no
`django.contrib.postgres` in `INSTALLED_APPS`. Two separate fuzzy surfaces:

1. **Customer search** does fuzzy matching **in Python** (rapidfuzz over a
   Redis-cached corpus). This is a legitimate architecture at 25 products and
   avoids the DB entirely — but it is O(corpus) CPU per request on your
   scarcest resource. The crossover where a trigram GIN index wins is roughly
   1,000–2,000 products.
2. **Admin search** (`admin_panel/views.py`) uses `icontains` against the DB with
   no index. This is where a trigram index actually pays off first:

```python
# Backend/products/migrations/00XX_trgm.py
from django.contrib.postgres.operations import TrigramExtension
from django.contrib.postgres.indexes import GinIndex
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("products", "<previous>")]

    operations = [
        TrigramExtension(),
        migrations.AddIndex(
            model_name="product",
            index=GinIndex(fields=["name"], name="product_name_trgm_idx",
                           opclasses=["gin_trgm_ops"]),
        ),
    ]
```
(requires adding `django.contrib.postgres` to `INSTALLED_APPS`.)

I would **not** do this yet. It is the correct fix for a problem you do not have.

## Connection handling

**[measured]** `settings.py:113-114`: `CONN_MAX_AGE = 60`, `CONN_HEALTH_CHECKS = True`.
`DB_HOST` points at PgBouncer on the other box (`13.201.33.243:6432`).

- 3 workers × 2 threads ⇒ at most **6 client connections** held for 60 s each.
  Well within any sane PgBouncer pool. No pressure here.
- **`CONN_HEALTH_CHECKS = True` + PgBouncer is slightly wasteful**: it fires an
  extra round-trip at the start of each request to validate a connection that
  PgBouncer is already managing. Minor.
- **Transaction-mode compatibility — I could not verify the pool mode from this
  repo, so this is a checklist, not a finding.** What I *can* say from the code:
  - Nothing uses `LISTEN`/`NOTIFY`, session-level `SET`, advisory locks, or
    server-side cursors **[measured]** — the usual transaction-mode landmines are
    all absent.
  - `psycopg2` (not `psycopg3`) is pinned, and Django does not use server-side
    prepared statements with psycopg2 by default, so the classic
    "prepared statement already exists" failure does not apply.
  - Every `select_for_update()` in the codebase is inside an explicit
    `transaction.atomic()` block (checked in `orders/views.py`, `cart/views.py`,
    `payments/views.py`) **[measured]** — which is required, and correct, under
    transaction pooling.
  - **Verify on the box:** `SHOW CONFIG;` on the PgBouncer admin console. If
    `pool_mode = transaction`, you are fine. If it is `session`, then
    `CONN_MAX_AGE = 60` pins a real backend per client connection for 60 s and
    you lose most of the benefit of pooling.

---

# Phase 4 — Memory

## Measured per-process footprint

I imported the app in this repo's venv and sampled RSS **[measured]**:

```
baseline python                    17.5 MB
after django.setup()              122.8 MB
+ products.recommendations          0.0 MB   (already pulled in by app loading)
+ assistant.agent, assistant.tools  0.3 MB
+ orders.invoice (reportlab)        0.2 MB
+ boto3, cloudinary                 8.0 MB
                                  --------
                                  131.3 MB
```

`django.setup()` alone costs **105 MB** because the `products` app imports
`products.recommendations` at module scope, which imports the whole
`langchain` / `langchain_core` / `langchain_openai` stack. That is the single
largest line item in this process's memory, and it is loaded **in every worker**
whether or not that worker ever serves a chat request.

(Measured on Windows with the dev venv. `python:3.12-slim` on x86_64 will land in
the same range, likely 110–130 MB.)

## Estimated steady-state RSS per container

| Container | Compose limit | Est. steady RSS | Verdict |
|---|---|---|---|
| `backend` (gunicorn, 1 master + 3 workers) | **512 M** | master ~130 MB + 3 × ~70 MB private after COW divergence ≈ **340 MB**; up to 3 × 131 MB ≈ **394 MB** if COW pages fully diverge | **Uncomfortably close to the limit.** ~120–170 MB of headroom for *all* request handling across 3 processes. |
| `scheduler` | 256 M | ~135 MB (same image, one process) | Fits, no headroom for a big rollup. |
| `redis` | 300 M | `maxmemory 256mb` | Fits. |
| `whisper` | 1 G | ~190 MB idle, >500 MB during inference (per the compose comment) | Fits, backed by swap. |
| `frontend` (nginx) | 128 M | ~15 MB | Fine. |
| `admin-panel` (nginx) | 64 M | ~15 MB | Fine. |
| **Total limits** | **2.26 G** | | ~~Leaves ~5.7 GB of the 8 GB unused.~~ **WRONG — see correction.** |

> ⚠️ **CORRECTION (2026-09-02, measured on the box).** The "8 GB" figure above is
> wrong, and so is every conclusion drawn from it. `13.235.238.99` has **1.9 GB
> of RAM and 2 vCPU** (`free -h`), with ~375 MB of swap already in use. The
> container *limits* total 2.26 G, which **over-commits** a 1.9 GB box — limits
> are caps, not reservations, so this works only because actual usage is lower.
> Measured RSS: backend ~380-495 MB (at 74-97% of its 512 M cap), scheduler
> ~148 MB, whisper ~49 MB, redis ~6 MB, the two nginx ~20 MB.
> ⇒ **Do NOT raise `backend` to 1.5 G as recommended below** — that RAM does not
> exist. The `--preload` recommendation still stands and is now the *only* cheap
> way to buy backend headroom.
> (Postgres + PgBouncer were added on-box on 2026-09-02 and cost ~77 MB.)

Two observations:

1. **The box is under-committed and the backend is over-constrained.** You have
   ~5.7 GB of RAM doing nothing while the container that actually serves traffic
   is capped at 512 MB with 3 workers. Raising `backend` to 1.5 G is free and is
   the single cheapest change in this document. (This is a *limit* change, not a
   hardware upgrade — the RAM is already there.)
2. **The `--preload` opportunity.** Gunicorn without `--preload` imports the app
   *after* forking, so each worker builds its own 131 MB heap from scratch — no
   COW sharing at all. Adding `--preload` imports once in the master and forks,
   which shares most of that 105 MB langchain heap. Expect **~150–200 MB saved**
   **[inferred]**. The tradeoff is that `--preload` breaks hot reload (irrelevant
   in prod) and means a code change requires a full restart (already true).

## The memory landmine: 500 MB uploads held in RAM **[measured]**

`settings.py:282`:

```python
FILE_UPLOAD_MAX_MEMORY_SIZE = config('FILE_UPLOAD_MAX_MEMORY_SIZE', default=524288000, cast=int)
```

That is **500 MB**. The comment above it says files "stream past it", which has
the logic exactly backwards: `FILE_UPLOAD_MAX_MEMORY_SIZE` is the threshold
**below which** an upload is kept as an `InMemoryUploadedFile`. Setting it to
500 MB means **every upload up to half a gigabyte is buffered entirely in the
worker's heap.**

And every nginx vhost sets `client_max_body_size 500M` (`ngu.conf:37, 88, 122`)
**[measured]**, so nginx will happily accept and forward it.

Against a **512 MB container limit**, a single 300 MB multipart POST is an
immediate OOM kill of the backend container. `AssistantTranscribeView` does check
`audio.size > 8 MB` — but that check runs **after** `request.FILES` has already
materialised the file, and then `audio.read()` copies it again.

There is no legitimate upload on this site above ~10 MB (product images, and a
10 MB-capped delivery bill). This should be **2 MB**, which is Django's default.

## Large querysets materialised into Python lists

| Location | What | Size today | Size at 2k products |
|---|---|---|---|
| `personalization.py:172` | whole catalogue, per rec cache-miss | ~25 objects | 2,000 model instances ≈ 6–10 MB |
| `serializers.py:233` | whole catalogue, **per empty section** | ~25 × 6 | 6 × 2,000 ≈ 40 MB in one request |
| `recommendations.py:166` | `texts = [e['text'] for e in entries]`, built ~4× per search | ~1k strings | ~80k strings × 4 |
| `recommendations.py:113` | full corpus dict list, JSON-decoded per request | ~1k dicts | ~80k dicts ≈ 30 MB per request |
| `orders/views.py:1755` | CSV export, no `.iterator()` | admin-triggered | unbounded by design |

`recommendations.py:113` is the one that scales worst: it deserialises the entire
corpus from Redis JSON **on every single search request**, in a worker capped at
512 MB shared with two other processes.

Nothing here loads a model, an embedding table, or a dataset. Good.

---

# Phase 5 — Caching

## What's already cached (and it's a lot)

| Key | TTL | Invalidation | Assessment |
|---|---|---|---|
| `products:list:<params>` | 300 s | `invalidate_product_cache()` on product save | Correct, **but the key is poisonable** — see below |
| `categories:list:lang` | 900 s | `invalidate_category_cache()` | Good |
| `combos:list:<params>` | 300 s | `invalidate_combo_cache()` | Same key flaw |
| `sections:all:lang` | 300 s | product + combo invalidation | Good; this one hides the worst N+1 |
| `search:corpus:v1` | 900 s | `invalidate_search_cache()` | Good |
| `search:suggest:<lang>:<q>:<n>` | 300 s | prefix invalidation | Good |
| `recs:<user>:<ctx>:<n>:<lang>` | **60 s** | `invalidate_user_recommendations` | **TTL far too short** |
| `recs:popularity:v1` | 300 s | TTL only | Good |
| `ngu:dashboard:stats` | 120 s | TTL only | Fine |
| `ngu:dashboard:actions` | **60 s** | TTL only | Too short for ~20 aggregates |
| `sitemap:xml` | 6 h | TTL only | Good |
| `geocode:rev:<lat>:<lng>` | 30 d | TTL only | Good |

Someone has clearly done a caching pass here. The gaps are specific.

## Highest-value additions

### 5.1 `/api/reviews/featured/` — uncached, on every homepage load

```
key:          reviews:featured:v1
TTL:          900 s
invalidation: ReviewViewSet.set_featured / set_hidden / perform_create → cache.delete
```

### 5.2 `unified_search` results

```
key:          search:unified:<lang>:<sha1(q)>:<top_k>:<threshold>
TTL:          300 s
invalidation: already covered by invalidate_search_cache()'s `search:*` prefix
```
Hash the query — do **not** put raw user text in the key (see 5.5).

### 5.3 Raise the recommendation TTL

`TTL_SHORT` (60 s) → `TTL_MEDIUM` (300 s), or 900 s. There is already an explicit
`invalidate_user_recommendations(user_id)` hook called after purchase
**[measured]**, so the short TTL is buying nothing that the invalidation
doesn't already deliver. This is a one-word change with a 5–15× reduction in
recompute rate.

### 5.4 Raise `ngu:dashboard:actions` 60 s → 300 s

~20 aggregates recomputed every minute for a screen the owner glances at.

## 5.5 — **Cache key poisoning. This is the most serious finding in the audit.**

`products/views.py:281-283` **[measured]**:

```python
query_params = dict(request.query_params)
cache_key = make_cache_key(CACHE_PREFIX_PRODUCTS, 'list', lang=get_language(), **query_params)
```

Identical code in `ComboProductViewSet.list` (`products/views.py:459-461`).

**Every query parameter goes into the cache key, unfiltered.** But `ProductFilter`
only recognises `category`, `spice_form`, `organic`, `is_featured`, `is_active`
(plus DRF's `search`/`ordering`). An unrecognised parameter is **silently ignored
by the filter and honoured by the cache key.**

So `/api/products/?zzz=1`, `?zzz=2`, `?zzz=3` … all:
1. miss the cache,
2. run the full 3-query un-paginated catalogue fetch and serialisation,
3. and **write a new full-catalogue payload into Redis**.

Three compounding consequences:

**(a) The cache stops working.** Legitimate `products:list:*` entries are evicted
almost immediately.

**(b) Redis fills, and the eviction policy makes it worse.**
`docker-compose.prod.yml` sets `--maxmemory 256mb --maxmemory-policy volatile-lru`
**[measured]** — evict only keys carrying a TTL. Every cache entry the app writes
carries a TTL.

**(c) — and this is the part that turns a performance bug into an availability
bug — DRF throttle state lives in the same Redis.**
`rest_framework/throttling.py:62` is `cache = default_cache`, and `settings.py`
defines exactly one cache alias, pointing at this Redis **[measured]**. Throttle
history keys carry a TTL, so they are `volatile-lru` eviction candidates. Flood
the cache and **the rate limiter's memory is evicted along with everything else.**
The throttles then permit unlimited requests, which accelerates the flood.

`SESSION_ENGINE = 'django.contrib.sessions.backends.cache'` (`settings.py:684`)
puts sessions in the same store, so they go too.

The fix is small and mechanical: whitelist the params that actually affect the
response.

```python
# products/views.py
ALLOWED_LIST_PARAMS = frozenset({
    'category', 'spice_form', 'organic', 'is_featured', 'is_active',
    'search', 'ordering', 'lang',
})

def _cache_params(self, request):
    """Only params that change the response may enter the cache key.

    dict(request.query_params) let an arbitrary unknown param mint a new key
    for an identical response — unbounded key cardinality on a shared,
    TTL-evicting Redis that also holds throttle state.
    """
    return {
        k: v for k, v in request.query_params.lists()
        if k in ALLOWED_LIST_PARAMS
    }
```

A second, milder instance: `search_suggest` (`products/views.py:686`) puts the
**raw user query** in the cache key with no length bound (`q` is only checked for
`len(query) < 2`). `make_cache_key` md5-hashes keys over 200 chars, so it is not a
protocol problem, but distinct queries still mint distinct keys. It is at least
throttled at `search_suggest: 60/min` per identity, which is why it ranks below
the product list.

## 5.6 — User-specific data in caches: **checked, and it's clean**

I looked specifically for the classic collision bug. Findings **[measured]**:

- `products:list:*` / `combos:list:*` — **staff bypass the cache entirely**
  (`if request.user and request.user.is_staff: return super().list(...)`), so
  admin-visible inactive products can never be cached and served to a customer.
  This is the right call and it's applied consistently across products, combos,
  categories and sections.
- `recs:<user_id>:<context>:<limit>:<lang>` — user id is the **first** key
  component. No collision.
- `geocode:rev:<lat>:<lng>` — coordinates only, deliberately shared. Correct.
- `ngu:dashboard:*` — admin-only endpoints behind an admin permission class.
- Throttle keys use `request.user.pk` when authenticated, else client IP
  (`assistant/throttles.py`, `products/views.py:672-677`).

No user-specific payload is cached under a user-agnostic key. Good.

One thing to watch: the language is part of the key everywhere it matters
(`lang=get_language()`), and `LanguageQueryMiddleware` also sets
`Vary: X-Language`. That pairing is correct and easy to break — if someone adds a
cached endpoint and forgets the `lang` component, Hindi users get English.

---

# Phase 6 — Failure under spike

## What breaks first, in order

**20× a 200k/month baseline ≈ 1,850 requests/minute ≈ 31 req/s sustained.**
With ~8 API calls per homepage view, that is roughly **250 page views/second** at
peak. Against 6 request slots.

### Stage 1 (0–60 s) — Redis eviction storm
**Symptom:** `docker exec ngu-redis redis-cli info stats | grep evicted_keys`
climbing fast. p50 latency roughly doubles across every endpoint.
**Cause:** 256 MB `maxmemory` with a spike's worth of distinct cache keys.
Product-list entries and throttle history evict each other.

### Stage 2 (30–90 s) — cache hit rate collapses, DB load goes vertical
**Symptom:** the DB box's CPU jumps. `/products/sections/` goes from 10 ms to
180 ms because every request now pays the 25-query N+1.
**Cause:** the sections cache is gone; there is no request coalescing, so **N
concurrent misses all recompute simultaneously** (classic cache stampede — there
is no lock or single-flight anywhere in `products/cache.py` **[measured]**).

### Stage 3 (60–120 s) — all 6 gunicorn threads occupied
**Symptom:** nginx `502`/`504` and rising `upstream_response_time` in
`/var/log/nginx/access.log`. The site appears **completely** down, not slow.
**Cause:** 6 slots × ~180 ms = ~33 req/s theoretical ceiling. At 31 req/s of
*mixed* traffic (some requests taking 400 ms+) you are already over it. The
listen backlog fills; nginx times out.
**Note:** because `gthread` keeps heartbeating, gunicorn will not recycle these
workers. It does not self-heal.

### Stage 4 (90–180 s) — throttles stop throttling
**Symptom:** request rate keeps climbing after you'd expect the limiter to bite.
**Cause:** Stage 1 evicted the throttle counters. The limiter fails **open**.

### Stage 5 (2–5 min) — memory pressure on the backend container
**Symptom:** `docker stats` shows `ngu-backend` at its 512 M limit; the host
starts swapping (2 GB swap was added per the deploy notes).
**Cause:** 3 × ~131 MB baseline plus per-request heap plus the corpus
deserialised per search request. Swap thrashing on 2 vCPUs is effectively an
outage.

### Stage 6 (variable) — the checkout path fails last and worst
**Symptom:** orders get created but customers never reach the Razorpay modal.
**Cause:** `create_razorpay_order` (Phase 2 #1) has no timeout. Under load
Razorpay's own latency rises; each slow call now pins one of 6 slots for however
long Razorpay takes. This is the failure that costs money — the rest only cost
goodwill.

### Stage 7 — the assistant takes down the store
**Symptom:** none, until everything stops.
**Cause:** 6 concurrent chat turns × up to 4 un-timeouted LLM calls. This does
not need a spike; it needs six people typing at once. It is listed last because
it is the least likely *during* a spike (people who came for a sale don't open
chat) and the most likely on an ordinary day.

## Tuned configuration for this box

### Gunicorn — the highest-leverage change here

Current: `--workers 3 --threads 2` = 6 slots.

This workload is **I/O-bound almost end to end** (DB on another box, Redis, and
several HTTP APIs). Sync/gthread workers are the wrong shape. Two options:

**Option A — more threads (no new dependency, ship today):**

```
gunicorn spices_backend.wsgi:application \
  --bind 0.0.0.0:8000 \
  --workers 3 --threads 8 \
  --worker-class gthread \
  --preload \
  --timeout 60 \
  --graceful-timeout 30 \
  --keep-alive 5 \
  --max-requests 1000 --max-requests-jitter 100 \
  --backlog 512 \
  --access-logfile - --error-logfile -
```

24 slots instead of 6. Workers = 3 is right for 2 vCPUs (`2×cores+1` is the old
rule; with threads, keep processes near core count). `--preload` recovers the
memory to afford it. `--max-requests` recycles workers periodically, which is
your only defence against a slow leak. `--timeout 60` will not stop a slow
request under gthread, but it does catch a genuinely wedged worker.

**Option B — gevent (better fit, one new dependency):**

```
pip install gevent==24.11.1
```
```
gunicorn spices_backend.wsgi:application \
  --worker-class gevent --workers 3 --worker-connections 200 \
  --preload --timeout 90 --max-requests 2000 --max-requests-jitter 200
```

600 concurrent slots on the same hardware, because a blocked socket yields
instead of holding an OS thread. Caveats you must verify before shipping:
`psycopg2-binary` needs `psycogreen` monkey-patching to yield properly, and the
raw `threading.Thread` email dispatch interacts oddly with gevent. **Option A
first.** Option B when Option A stops being enough.

Either way, **fix the timeouts first** — more slots just means more slots to hang.

### Container memory limits

```yaml
# docker-compose.prod.yml
  backend:
    deploy:
      resources:
        limits:
          memory: 1536M      # was 512M — 5.7 GB of the box's 8 GB is idle
  scheduler:
    deploy:
      resources:
        limits:
          memory: 512M       # was 256M
  redis:
    command: redis-server --appendonly yes --maxmemory 768mb --maxmemory-policy allkeys-lru
    deploy:
      resources:
        limits:
          memory: 900M       # was 300M
```

Note the eviction-policy change: **`volatile-lru` → `allkeys-lru`.** Under
`volatile-lru`, keys *without* a TTL are immortal and pressure falls entirely on
TTL'd keys — which is exactly your throttle counters and sessions.
`allkeys-lru` spreads the pain and makes eviction predictable. (The current
comment in the compose file justifies `volatile-lru` by wanting to protect the
anonymous analytics counters — those are flushed every 5 minutes by the
scheduler, so at worst you lose 5 minutes of anonymous counters instead of losing
your rate limiter. That is the right trade.)

### PgBouncer (on the DB box, `~/ngu-db/`)

```ini
pool_mode = transaction        ; verify — the code is compatible (see Phase 3)
max_client_conn = 200
default_pool_size = 20         ; 3 workers x 8 threads = 24 clients; 20 real backends is plenty
reserve_pool_size = 5
reserve_pool_timeout = 3
server_idle_timeout = 60
query_wait_timeout = 10        ; fail fast instead of queueing forever during a spike
```

`default_pool_size = 20` against a `max_connections` of ~100 leaves room for the
scheduler, psql sessions and backups.

### Postgres 17 (on the DB box)

Sizing for whatever that box has; assuming it mirrors this one at 8 GB:

```ini
shared_buffers = 2GB                  # 25% of RAM
effective_cache_size = 6GB            # planner hint: what the OS is likely caching
work_mem = 16MB                       # per sort/hash node. 20 conns x 2 nodes x 16MB = 640MB worst case
maintenance_work_mem = 512MB
random_page_cost = 1.1                # NVMe — the 4.0 default assumes spinning rust
effective_io_concurrency = 200        # NVMe
max_connections = 100                 # PgBouncer fronts this; no need to go higher
wal_compression = on
checkpoint_completion_target = 0.9
max_wal_size = 4GB
default_statistics_target = 100
```

`random_page_cost = 1.1` is the one that changes plans: at the default 4.0
Postgres systematically prefers seq scans over index scans on NVMe, which is
precisely wrong for the indexes recommended in Phase 3.

### Nginx — currently there is **no rate limiting whatsoever** **[measured]**

No `limit_req`, no `limit_conn`, in either `nginx.conf` or `ngu.conf`. The
*only* rate limiting on this system is DRF's, which lives in the Redis that
Phase 5 shows can be evicted. Add a layer that cannot be evicted:

```nginx
# /etc/nginx/nginx.conf, inside http { }
limit_req_zone  $binary_remote_addr zone=api:10m   rate=20r/s;
limit_req_zone  $binary_remote_addr zone=write:10m rate=2r/s;
limit_req_zone  $binary_remote_addr zone=llm:10m   rate=10r/m;
limit_conn_zone $binary_remote_addr zone=perip:10m;
limit_req_status 429;
limit_conn_status 429;

# 10m of zone holds ~160k IPs. rate=20r/s with burst=40 comfortably fits a
# homepage's 8 parallel calls plus navigation, and stops a scripted flood.
```

```nginx
# /etc/nginx/conf.d/ngu.conf — in EACH server block's location /
    limit_conn perip 20;
    client_max_body_size 12M;          # was 500M. Nothing here legitimately exceeds 10M.
    proxy_read_timeout 65s;            # slightly above gunicorn --timeout 60
    proxy_connect_timeout 5s;
    proxy_send_timeout 30s;

# and add these BEFORE `location /` so they match first:
location /api/assistant/ {
    limit_req zone=llm burst=5 nodelay;
    limit_conn perip 2;
    proxy_read_timeout 70s;
    proxy_pass http://localhost:3000;
    # ... same proxy_set_header block as location / ...
}

location /api/ {
    limit_req zone=api burst=40 nodelay;
    proxy_pass http://localhost:3000;
    # ... same proxy_set_header block as location / ...
}
```

Also raise `worker_connections` from 1024 — with `worker_processes auto` on
2 cores that's 2,048 total connections, and each proxied request uses two:

```nginx
events {
    worker_connections 4096;
    multi_accept on;
}
```

### One frontend change worth more than most of the backend ones

`Frontend/nidhi-brand-forge/src/App.tsx:49` **[measured]**:

```typescript
const queryClient = new QueryClient();
```

No defaults means React Query v5's: `staleTime: 0`, `refetchOnWindowFocus: true`,
`refetchOnMount: true`. **Every tab focus refetches every active query.** A user
with the storefront open in a background tab, alt-tabbing all day, is a traffic
generator. This is a five-line change that cuts real request volume
substantially:

```typescript
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 5 * 60 * 1000,     // matches the backend's CACHE_TTL_MEDIUM
      gcTime: 30 * 60 * 1000,
      refetchOnWindowFocus: false,
      retry: 1,
    },
  },
});
```

---

# Output

## 1. Top 10 risks, ranked

| # | Risk | Severity | Effort | Expected improvement |
|---|---|---|---|---|
| 1 | **Razorpay SDK has no HTTP timeout** — a hung gateway pins request slots indefinitely; 6 hung calls = total API outage | **Critical** | 30 min | Converts an unbounded outage into a 10 s error |
| 2 | **LLM agent loop has no timeout** — up to 4 un-timeouted calls × 600 s default; one user can occupy the whole pool | **Critical** | 1 h | Bounds the worst request from ~2 h to ~35 s |
| 3 | **`FILE_UPLOAD_MAX_MEMORY_SIZE=500MB` + `client_max_body_size 500M` vs a 512 MB container** — one large POST OOM-kills the backend | **Critical** | 15 min | Removes a single-request kill switch |
| 4 | **Cache key built from unfiltered query params** — unbounded Redis key cardinality; evicts throttle state under `volatile-lru`, so the rate limiter fails open | **Critical** | 1 h | Restores cache + rate limiting under load |
| 5 | **6 total request slots** (`--workers 3 --threads 2`), no `--preload`, no `--max-requests` | **High** | 30 min | 4× concurrency, ~150 MB saved, worker recycling |
| 6 | **No nginx rate limiting at all**; `worker_connections 1024` | **High** | 1 h | An eviction-proof limiter beneath DRF's |
| 7 | **`/products/sections/` N+1** (~25 queries, plus full catalogue per empty section) + no stampede protection | **High** | 3 h | ~25 queries → ~5; removes the stampede |
| 8 | **`GET /api/cart/` N+1 on combo lines** (~4 extra queries per combo line, on every page load) | Medium | 2 h | ~26 queries → ~6 for a 5-combo cart |
| 9 | **`UserEvent` grows forever, no prune, no `created_at` index**; login does a seq scan via `email__iexact` | Medium | 3 h | Bounds the largest table; login goes O(n) → O(log n) |
| 10 | **`recs` TTL 60 s; dashboard `actions` TTL 60 s; `/reviews/featured/` and `unified_search` uncached** | Medium | 2 h | 5–15× fewer recomputes of the most expensive reads |

## 2. Concrete diffs for the top 5

### Diff 1 — Razorpay timeout

```diff
--- a/Backend/payments/gateway.py
+++ b/Backend/payments/gateway.py
@@
 import razorpay
+import requests
 from django.conf import settings
+
+# The Razorpay SDK passes **options straight through to requests and never
+# supplies a timeout of its own (see razorpay/client.py::request). requests
+# with no timeout waits for the OS TCP timeout — minutes to hours. On a
+# 3-worker/2-thread gunicorn pool, six hung checkouts take the whole API down,
+# and gthread workers keep heartbeating so the arbiter never recycles them.
+RAZORPAY_TIMEOUT = (
+    getattr(settings, 'RAZORPAY_CONNECT_TIMEOUT', 5),
+    getattr(settings, 'RAZORPAY_READ_TIMEOUT', 10),
+)
+
+
+class _TimeoutSession(requests.Session):
+    """A Session that applies a default timeout to every request.
+
+    Done at the Session level rather than per call site so a new SDK method
+    can never reintroduce the unbounded wait.
+    """
+
+    def request(self, *args, **kwargs):
+        kwargs.setdefault('timeout', RAZORPAY_TIMEOUT)
+        return super().request(*args, **kwargs)
 
 
 class RazorpayNotConfigured(RuntimeError):
     """Raised when Razorpay keys are missing — surfaced as a 503, never a 500."""
 
 
 def get_razorpay_client():
     key_id = getattr(settings, 'RAZORPAY_KEY_ID', '')
     key_secret = getattr(settings, 'RAZORPAY_KEY_SECRET', '')
     if not key_id or not key_secret:
         raise RazorpayNotConfigured(
             "RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET are not configured."
         )
-    client = razorpay.Client(auth=(key_id, key_secret))
+    client = razorpay.Client(auth=(key_id, key_secret), session=_TimeoutSession())
     client.set_app_details({"title": "NGU", "version": "1.0"})
     return client
```

Callers already catch broad exceptions and return `502`/`503`
(`payments/views.py:253-256`), so a `requests.Timeout` surfaces correctly with no
further change.

### Diff 2 — LLM timeout + wall-clock budget on the agent loop

```diff
--- a/Backend/assistant/agent.py
+++ b/Backend/assistant/agent.py
@@
 import json
 import logging
 import os
+import time
@@
 MAX_ITERATIONS = 4
 MAX_MESSAGE_LEN = 1000         # input cap for a single *new* user turn (also enforced in the view)
 MAX_OUTPUT_TOKENS = int(os.getenv('ASSISTANT_MAX_OUTPUT_TOKENS', '600'))
+
+# Hard ceiling on ONE upstream LLM call. Without this the openai SDK applies its
+# own default (600s, 2 retries => up to 1800s per call), and MAX_ITERATIONS
+# multiplies it. On a 3-worker/2-thread pool that is six chat turns to a total
+# outage — reachable by one user, since the throttle is 20/min PER USER.
+LLM_TIMEOUT_SECONDS = float(os.getenv('ASSISTANT_LLM_TIMEOUT', '25'))
+LLM_MAX_RETRIES = int(os.getenv('ASSISTANT_LLM_MAX_RETRIES', '1'))
+# Ceiling on a whole turn, across every iteration. Bounds how long one request
+# can hold its worker thread even when each individual call stays under budget.
+TURN_BUDGET_SECONDS = float(os.getenv('ASSISTANT_TURN_BUDGET', '35'))
@@
         if provider == 'openrouter':
             from langchain_openai import ChatOpenAI
             from spices_backend.llm import openrouter_extra_body
             return ChatOpenAI(
                 model=model_name,
                 openai_api_key=api_key,
                 openai_api_base=os.getenv('OPENROUTER_API_BASE', 'https://openrouter.ai/api/v1'),
                 temperature=0.2,
                 max_tokens=MAX_OUTPUT_TOKENS,
+                timeout=LLM_TIMEOUT_SECONDS,
+                max_retries=LLM_MAX_RETRIES,
                 extra_body=openrouter_extra_body(),
             )
         from langchain.chat_models import init_chat_model
         return init_chat_model(
             model_name, model_provider=provider,
             temperature=0.2, api_key=api_key, max_tokens=MAX_OUTPUT_TOKENS,
+            timeout=LLM_TIMEOUT_SECONDS, max_retries=LLM_MAX_RETRIES,
         )
@@
     def _complete(self, messages):
         if self._completion is not None:
             return self._completion(messages)
-        resp = self._llm.invoke(messages)
+        try:
+            resp = self._llm.invoke(messages)
+        except Exception:
+            # A timeout/transport failure is not a bug in the envelope protocol —
+            # let run() fall through to FALLBACK_REPLY + escalate rather than
+            # 500-ing at the customer.
+            logger.warning("LLM call failed or timed out", exc_info=True)
+            return ''
         return getattr(resp, 'content', resp)
@@
         repaired = False
+        deadline = time.monotonic() + TURN_BUDGET_SECONDS
         for _ in range(MAX_ITERATIONS):
+            if time.monotonic() > deadline:
+                logger.warning("assistant turn exceeded %ss budget; falling back",
+                               TURN_BUDGET_SECONDS)
+                break
             raw = self._complete(messages)
             env = _parse_envelope(raw)
```

Worst case per chat request goes from ~2 hours to ~35 s. Set
`ASSISTANT_LLM_TIMEOUT` lower once you know your provider's real p99.

### Diff 3 — Upload size

```diff
--- a/Backend/spices_backend/settings.py
+++ b/Backend/spices_backend/settings.py
@@
 # File Upload Configuration.
 # DATA_UPLOAD_MAX_MEMORY_SIZE caps non-file request bodies (JSON/form fields) held
 # in memory — kept small (10MB) so a malicious oversized JSON payload can't exhaust
-# memory. FILE_UPLOAD_MAX_MEMORY_SIZE only governs the in-memory threshold for
-# uploaded FILES (images/videos stream past it), so large media uploads still work.
+# memory.
+#
+# FILE_UPLOAD_MAX_MEMORY_SIZE is the threshold BELOW which an upload is held
+# entirely in the worker's heap as an InMemoryUploadedFile; only files ABOVE it
+# spool to disk. The previous 500MB value therefore did the opposite of what the
+# old comment claimed: it guaranteed that any upload up to half a gigabyte was
+# buffered in RAM. Against the backend container's memory limit that is a
+# single-request OOM kill. Nothing on this site legitimately uploads more than a
+# product image or a 10MB delivery bill, so this is back to Django's default and
+# larger files stream to a temp file as intended.
 DATA_UPLOAD_MAX_MEMORY_SIZE = config('DATA_UPLOAD_MAX_MEMORY_SIZE', default=10 * 1024 * 1024, cast=int)
-FILE_UPLOAD_MAX_MEMORY_SIZE = config('FILE_UPLOAD_MAX_MEMORY_SIZE', default=524288000, cast=int)
+FILE_UPLOAD_MAX_MEMORY_SIZE = config('FILE_UPLOAD_MAX_MEMORY_SIZE', default=2 * 1024 * 1024, cast=int)
+# Absolute ceiling on any single uploaded file, enforced before it is read.
+MAX_UPLOAD_BYTES = config('MAX_UPLOAD_BYTES', default=12 * 1024 * 1024, cast=int)
```

```diff
--- a/ngu.conf
+++ b/ngu.conf
@@ (in every `location /` block — three occurrences)
-        client_max_body_size 500M;
+        # 500M let nginx accept a body far larger than the backend container's
+        # memory limit. Product images and the 10MB delivery bill are the only
+        # real uploads.
+        client_max_body_size 12M;
```

### Diff 4 — Cache key whitelist

```diff
--- a/Backend/products/views.py
+++ b/Backend/products/views.py
@@
 CACHE_TTL = getattr(settings, 'CACHE_TTL_MEDIUM', 300)
 CACHE_TTL_CATEGORIES = getattr(settings, 'CACHE_TTL_LONG', 900)
+
+# Query params that actually change a list response. ANY other param is ignored
+# by the filter backends, so letting it into the cache key mints a brand-new
+# entry for a byte-identical response.
+#
+# That is not merely wasteful. Redis is capped at maxmemory with an LRU eviction
+# policy and is ALSO the store DRF's throttles and the session backend use
+# (there is one cache alias). Unbounded key cardinality here evicts the rate
+# limiter's own counters, so the limiter fails open exactly when it is needed.
+PRODUCT_LIST_CACHE_PARAMS = frozenset({
+    'category', 'spice_form', 'organic', 'is_featured', 'is_active',
+    'search', 'ordering',
+})
+COMBO_LIST_CACHE_PARAMS = frozenset({'is_featured', 'is_active', 'search', 'ordering'})
+
+
+def cache_params(request, allowed):
+    """Whitelist request params for use in a cache key."""
+    return {k: v for k, v in request.query_params.lists() if k in allowed}
@@ class ProductViewSet
     def list(self, request, *args, **kwargs):
         """Cached product list for non-admin users."""
         # Skip cache for staff users
         if request.user and request.user.is_staff:
             return super().list(request, *args, **kwargs)
 
-        # Build cache key from query params — include language so Hindi/Gujarati/etc.
-        # requests don't get served the cached English product names.
-        query_params = dict(request.query_params)
-        cache_key = make_cache_key(CACHE_PREFIX_PRODUCTS, 'list', lang=get_language(), **query_params)
+        # Cache key from the WHITELISTED params only (see PRODUCT_LIST_CACHE_PARAMS),
+        # plus the language so Hindi/Gujarati/etc. requests don't get served the
+        # cached English product names.
+        cache_key = make_cache_key(
+            CACHE_PREFIX_PRODUCTS, 'list', lang=get_language(),
+            **cache_params(request, PRODUCT_LIST_CACHE_PARAMS)
+        )
@@ class ComboProductViewSet
-        query_params = dict(request.query_params)
-        cache_key = make_cache_key(CACHE_PREFIX_COMBOS, 'list', lang=get_language(), **query_params)
+        cache_key = make_cache_key(
+            CACHE_PREFIX_COMBOS, 'list', lang=get_language(),
+            **cache_params(request, COMBO_LIST_CACHE_PARAMS)
+        )
```

And close the loop on the eviction policy:

```diff
--- a/docker-compose.prod.yml
+++ b/docker-compose.prod.yml
@@
-    command: redis-server --appendonly yes --maxmemory 256mb --maxmemory-policy volatile-lru
+    # allkeys-lru, not volatile-lru: every key the app writes carries a TTL, so
+    # volatile-lru concentrated ALL eviction pressure on TTL'd keys — which
+    # includes DRF's throttle counters and the session store. Losing those under
+    # load disables rate limiting at the worst possible moment. allkeys-lru
+    # spreads eviction and keeps the limiter's memory competitive with cache
+    # payloads. The anonymous analytics counters this policy was protecting are
+    # flushed to the DB every 5 minutes by the scheduler, so the exposure is
+    # 5 minutes of counters, not the rate limiter.
+    command: redis-server --appendonly yes --maxmemory 768mb --maxmemory-policy allkeys-lru
```

### Diff 5 — Gunicorn

```diff
--- a/Backend/Dockerfile
+++ b/Backend/Dockerfile
@@
-# Default command - collect static files and run gunicorn
-CMD ["sh", "-c", "python manage.py collectstatic --noinput && python manage.py migrate --noinput && gunicorn spices_backend.wsgi:application --bind 0.0.0.0:8000 --workers 3 --threads 2"]
+# Default command - collect static files and run gunicorn.
+#
+# --threads 8 (was 2): this workload is I/O-bound end to end — Postgres is on a
+#   separate box, plus Redis, Razorpay, OpenRouter and SMTP. 3x2=6 slots meant
+#   six concurrent slow requests took the entire API down. Worker COUNT stays at
+#   3 to match the 2 vCPUs; only the thread count grows.
+# --preload: import the app once in the master and fork, so the ~105MB langchain
+#   heap that products.recommendations pulls in at module scope is shared
+#   copy-on-write instead of built independently in every worker.
+# --max-requests: periodically recycle workers so a slow leak can't accumulate.
+# --timeout 60: catches a genuinely wedged worker. Note it does NOT bound a slow
+#   request under gthread (the worker keeps heartbeating from its accept loop) —
+#   that is what the per-client HTTP timeouts are for.
+CMD ["sh", "-c", "python manage.py collectstatic --noinput && python manage.py migrate --noinput && gunicorn spices_backend.wsgi:application --bind 0.0.0.0:8000 --workers 3 --threads 8 --worker-class gthread --preload --timeout 60 --graceful-timeout 30 --keep-alive 5 --max-requests 1000 --max-requests-jitter 100 --backlog 512 --access-logfile - --error-logfile -"]
```

```diff
--- a/docker-compose.prod.yml
+++ b/docker-compose.prod.yml
@@ backend:
     deploy:
       resources:
         limits:
-          memory: 512M
+          # 3 gunicorn workers cost ~130MB each before serving anything (measured:
+          # django.setup() alone is ~105MB, mostly langchain imported at module
+          # scope by the products app). 512M left almost no headroom for request
+          # handling. The box has 8GB and ~5.7GB of it was idle.
+          memory: 1536M
```

⚠️ **`--preload` and `migrate` in the same CMD:** with `--preload` the app is
imported in the master before forking, which is fine — but `migrate` still runs
on **every container start**. That is pre-existing and unrelated to this change,
though it's worth splitting out into the documented deploy step
(`docker compose exec backend python manage.py migrate`) so that a container
restart during an incident can't start a migration.

## 3. Measurement plan

You cannot tune what you cannot see, and right now the only instrumentation is
Django's logger. In priority order:

### Tier 1 — no new dependencies, do this first

| Signal | How | Alert threshold |
|---|---|---|
| Upstream latency per endpoint | Add `$upstream_response_time $request_time` to nginx `log_format main` | p99 > 2 s over 5 min |
| 5xx / 429 rate | nginx access log | 5xx > 1% of requests over 5 min |
| Redis evictions | `redis-cli info stats` → `evicted_keys` | **any non-zero rate.** This is your leading indicator for everything in Phase 6. |
| Redis memory | `redis-cli info memory` → `used_memory` vs `maxmemory` | > 80% |
| Cache hit rate | `keyspace_hits / (hits+misses)` | < 70% |
| Container RSS | `docker stats --no-stream` | any container > 80% of its limit |
| Gunicorn busy workers | `--statsd-host` or count `ESTABLISHED` on :8000 | > 70% of slots busy for 60 s |
| Host swap | `vmstat 1` → `si`/`so` | any sustained swap-in |

A cron writing `docker stats --no-stream` and `redis-cli info` to a file every
minute gets you 80% of the value for zero dependencies.

### Tier 2 — a slow-request middleware

Do **not** ship `LOGGING['django.db.backends'] = DEBUG` in production (it logs
every query). Instead write a small middleware that records
`len(connection.queries)` and elapsed time per request and logs a WARNING above a
threshold:

| Metric | Threshold |
|---|---|
| Queries per request | > 20 ⇒ WARNING (this catches every N+1 in Phase 1) |
| Request duration | > 1 s ⇒ WARNING, > 5 s ⇒ ERROR |
| LLM call duration | > 15 s ⇒ WARNING (validates Diff 2's budget) |
| Razorpay call duration | > 3 s ⇒ WARNING |

Note `connection.queries` is only populated when `DEBUG=True` **or** you wrap the
block in `django.test.utils.CaptureQueriesContext`; the cheap production-safe
variant is a `connection.execute_wrapper` counter installed in the middleware.

### Tier 3 — Postgres-side

```sql
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
-- weekly:
SELECT calls, mean_exec_time, total_exec_time, query
FROM pg_stat_statements ORDER BY total_exec_time DESC LIMIT 20;

-- catches missing indexes directly:
SELECT relname, seq_scan, seq_tup_read, idx_scan
FROM pg_stat_user_tables WHERE seq_scan > idx_scan ORDER BY seq_tup_read DESC;
```
The second query will immediately show the `users_user` sequential scans from the
`email__iexact` finding.

### Thresholds that should trigger which action

| Observation | Action |
|---|---|
| Redis `evicted_keys` > 0 sustained | Raise `maxmemory` **and** audit for new unbounded cache keys |
| Cache hit rate < 70% | Look for a poisoned key pattern before adding more cache |
| Busy workers > 70% for 60 s | Raise `--threads`; if already at 8, move to gevent |
| Any endpoint p99 > 2 s | Profile it; it is holding slots |
| Queries/request > 20 on a hot path | Fix the N+1 — this is the sections/cart finding |
| `UserEvent` row count > 2M | The prune job is not running |
| Backend container > 80% of limit | Raise the limit (the RAM is there) before optimising |

## 4. Honest assessment — what actually matters now

### Fix this week (these are live exposure, not scaling theory)

1. **Razorpay timeout** (Diff 1). Not a scale issue — a *correctness under
   partial failure* issue. It can take the site down at 30 orders/day.
2. **LLM timeout** (Diff 2). Same reasoning, and one user can trigger it.
3. **Upload size** (Diff 3). One request kills the container. 15 minutes of work.
4. **Cache key whitelist + `allkeys-lru`** (Diff 4). The throttle-eviction
   cascade means this is a rate-limiter bypass, not just a cache miss.
5. **Gunicorn config + backend memory limit** (Diff 5). Highest ratio of benefit
   to effort in the document. You are running at 512 MB and 6 slots on an 8 GB
   box that is 70% idle.
6. **nginx `limit_req`.** Your only rate limiter currently lives in an evictable
   cache. This one does not.

### Fix this quarter

7. **`/products/sections/` N+1** (~25 queries + full catalogue per empty
   section). It is hidden behind a 5-minute cache today; it becomes the top
   endpoint by DB cost the moment that cache is under pressure.
8. **`GET /api/cart/` combo N+1.** Every page load for a logged-in shopper.
9. **`UserEvent` prune job + `created_at` index.** The table has no ceiling and
   there is no prune command at all. Cheap to add now, painful to add at 5M rows.
10. **`User.email` functional index.** Every login is a sequential scan today.
11. **Recommendation TTL 60 s → 300 s.** One-word change.
12. **React Query defaults.** Five lines in `App.tsx` that measurably reduce real
    request volume.

### Premature — do not do these yet

- **pg_trgm / GIN indexes.** Correct at ~1,500+ products. You have 25. The
  Python fuzzy search is genuinely the right call at this size.
- **Table partitioning for `UserEvent`.** A 90-day prune keeps it under ~600k
  rows forever. Partitioning is operational complexity you don't need.
- **Keyset pagination.** Offset pagination on 12-row pages is fine until the
  admin order list has six figures of rows.
- **Celery + Redis broker.** Real infrastructure, real operational burden. The
  APScheduler container already handles cron work correctly and the thread-based
  email is adequate at 60 orders/day. Revisit when you want async chat responses.
- **gevent.** Option A (`--threads 8`) buys 4× concurrency with zero new
  dependencies. Take that first and measure.
- **Replacing `COUNT(*)` with `reltuples`.** Matters past ~1M rows. You have
  thousands.
- **Async views / ASGI.** Would require replacing gunicorn/WSGI wholesale and
  rewriting every ORM call site. The thread-pool increase gets you the same
  concurrency win for this workload.

### The uncomfortable summary

**Nothing in this system is currently limited by data volume.** 25 products,
~60 orders/day, and a well-indexed schema. The database is not your problem and
probably will not be for two years.

What *is* your problem is that six request slots stand between the internet and
a set of HTTP clients that have no timeouts. The three critical findings
(Razorpay, LLM, upload size) are all reachable today, at current traffic, without
a spike. The 20× spike scenario in Phase 6 is a real risk, but it is second in
line behind the ways this can fall over on an ordinary Tuesday.

The codebase itself is in notably good shape — the annotation work in
`ProductViewSet`/`ComboProductViewSet`, the `DailyAnonStat` counter design, the
rollup tables, the invoice snapshotting, and the existing cache invalidation are
all things most projects this size get wrong. The gaps are concentrated at the
edges: process configuration, HTTP client defaults, and the boundary between
untrusted input and cache keys.

---

# Appendix — "How would this server realistically fall over?"

Four failure modes, ordered by how little effort each takes. These are written as
capacity/resilience scenarios for **your own infrastructure**, so you can
reproduce them against a **local or staging** stack and confirm the fixes work.
Per the standing rule in CLAUDE.md, do not run any of these against
`nidhigrahudyog.com` or the two EC2 boxes.

Each one names the specific mitigation from this document that closes it.

## A. The cheapest total outage: 6 slow requests

**What happens.** Six concurrent requests to `/api/assistant/chat/` from one
logged-in account. Each occupies a gunicorn thread for the duration of up to four
un-timeouted LLM round-trips. Six is the entire pool. The seventh request — and
every subsequent one, including the homepage and checkout — queues in the listen
backlog until nginx returns 504.

**Effort required:** one account, six browser tabs. No spike, no tooling.

**Why nothing stops it:** `assistant: 20/min` is per-user, so six parallel
requests are all within the limit. `gthread` workers keep heartbeating, so
gunicorn never recycles them. The LLM client has no timeout.

**What an operator sees:** the site is *completely* down, `docker stats` shows
the backend at ~2% CPU, the DB is idle, and `docker logs ngu-backend` is silent.
Everything looks healthy. That combination — total unavailability with no
resource under pressure — is the signature of worker starvation.

**Closed by:** Diff 2 (LLM timeout + turn budget), Diff 5 (24 slots instead of 6),
and the nginx `zone=llm` limit + `limit_conn perip 2` on `/api/assistant/`.

## B. Single-request OOM

**What happens.** One POST with a ~400 MB multipart body. nginx accepts it
(`client_max_body_size 500M`), buffers it, and forwards it. Django's
`MultiPartParser` builds an `InMemoryUploadedFile` because 400 MB is under
`FILE_UPLOAD_MAX_MEMORY_SIZE` (500 MB). The backend container's cgroup limit is
512 MB and three workers already hold ~340 MB of it. The OOM killer takes the
container.

**Effort required:** one HTTP request.

**Secondary effect:** nginx buffers request bodies to `client_body_temp` on disk
before proxying. Enough concurrent large bodies fills the 100 GB volume, which
takes down Docker, the Redis AOF, and nginx's own logging.

**What an operator sees:** `docker ps` shows `ngu-backend` restarting;
`dmesg | grep -i oom` names the python process. `restart: unless-stopped` brings
it back, so it looks like a flapping container rather than an attack.

**Closed by:** Diff 3 (`FILE_UPLOAD_MAX_MEMORY_SIZE` → 2 MB,
`client_max_body_size` → 12 M) and Diff 5's raised memory limit.

## C. Cache eviction → rate limiter bypass (the cascade)

**What happens.** A loop of `GET /api/products/?<random>=<n>`. Every request has a
distinct cache key, so every request:
1. misses the cache,
2. runs the 3-query un-paginated catalogue fetch and full serialisation,
3. writes a fresh full-catalogue payload into a 256 MB Redis.

Redis reaches `maxmemory` in seconds and starts evicting under `volatile-lru`.
Every key the app writes has a TTL — including **DRF's throttle counters**
(`rest_framework/throttling.py:62` uses the default cache, and there is only one
cache alias) and the **session store** (`SESSION_ENGINE = cache`).

The limiter's own memory is evicted, so `anon: 1000/hour` stops counting, which
lets the loop run faster, which evicts harder. The catalogue, sections, combo,
search-corpus and recommendation caches all go with it, so every remaining
legitimate request now pays full DB cost — including the 25-query
`/products/sections/` N+1, with no stampede protection, so N concurrent misses
recompute simultaneously.

**Effort required:** a `for` loop.

**What an operator sees, in order:** `evicted_keys` climbing → cache hit rate
collapsing → DB CPU spiking → nginx 502s → the throttle apparently not working.
The last symptom is the confusing one, and it is caused by the first.

**Closed by:** Diff 4 (param whitelist + `allkeys-lru` + larger Redis) and the
nginx `limit_req zone=api` — which lives in nginx's own shared memory and cannot
be evicted by anything happening in Redis.

## D. The slow-burn one: dependency latency, not volume

**What happens.** Nothing malicious. Razorpay has a bad ten minutes — not an
outage, just p99 latency climbing into the tens of seconds. Or an upstream
OpenRouter provider starts hanging connections.

The Razorpay SDK passes no timeout to `requests`, so each slow checkout holds a
thread for as long as the gateway takes. At 6 slots, a handful of concurrent
checkouts during a sale is enough to consume the pool. The storefront goes down
because the *payment gateway* was slow — and the outage outlasts the gateway's
problem, because gunicorn never recycles the stuck workers.

**Effort required:** none. This is a matter of when.

**Why it is the most likely of the four:** it needs no attacker. It needs a
third-party dependency to have an ordinary bad day.

**Closed by:** Diff 1 (connect 5 s / read 10 s), Diff 5 (`--max-requests` recycling
+ 24 slots), and `proxy_read_timeout 65s` in nginx.

## The pattern behind all four

Every one is the same shape: **an unbounded wait or an unbounded allocation,
sitting behind a bounded pool of six.** None is a database problem, none needs
data volume, and none needs a traffic spike. That is why Diffs 1–5 are ordered the
way they are — they bound the waits, bound the allocations, and widen the pool,
in that order.
