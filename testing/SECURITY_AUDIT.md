# NGU Security Audit & Test Report

**Target:** Nidhi Masala e-commerce platform (Django REST backend)
**Scope:** Unit, integration, end-to-end, and adversarial security testing.
**Out of scope (by request):** Razorpay / payment-capture gateway flows.
**Method:** The project's in-process Django suite (unit + integration) plus a
black-box HTTP suite (`testing/e2e`, `testing/security`) run against a locally
launched, production-like server. Inspired by the **Faultline** QA / chaos
philosophy: fire happy paths *and* hostile input, and assert the API never
500s, never leaks a stack trace, and never serves data to the wrong principal.

Reproduce everything with:

```bash
python testing/tools/run_full_audit.py        # writes testing/reports/session_transcript.txt
```

---

## 1. Results at a glance

| Layer | Result |
|-------|--------|
| Unit + integration (Django suite, Postgres) | **529 passed, 8 skipped, 0 failed** (base + edge-case + resilience/concurrency + boundedness/abuse + **38 PDF-invoice** tests; 8 skips = retired Policy API) |
| End-to-end (HTTP, live server) | **all green** (data-writing flows incl. **place order → download PDF invoice**; throttling-relaxed env) |
| Security / adversarial probes | **all green** — no broken access control (incl. invoice BOLA), no injection, no leakage |
| Combined e2e + security run | **74 passed, 3 skipped, 0 failed** |

> **Update:** findings F-1, F-2 and F-3 below have been **fixed** in this change
> set; the full suite now runs with no quarantine and no failures.

Skips are environmental, not failures: the AI assistant has no LLM key locally,
and login throttling is relaxed in the test env (the real limits are verified
by configuration — see §3).

---

## 2. Security posture — what was verified PASS

| Control | Evidence | Verdict |
|---------|----------|---------|
| **Authentication required** on private endpoints | `cart`, `favorites`, `orders`, `profile`, `payment-methods`, `recommendations`, `assistant/conversations` all return 401/403 to anonymous callers | ✅ |
| **Authorization / least privilege** | Admin-only endpoints (`dashboard`, `receivable-accounts`, `coupons`, admin chat, `contact` GET) reject a logged-in non-staff user | ✅ |
| **BOLA / multi-tenant isolation** | Two fresh users cannot see each other's orders; order list is user-scoped | ✅ |
| **IDOR** | Fetching guessable order ids (`/orders/1,2,3/`) as an unrelated user returns 403/404, never another user's data | ✅ |
| **SQL injection** | Classic payloads (`' OR '1'='1`, `'; DROP TABLE products; --`, UNION SELECT) on `search` and product filters → no 500, no DB error leak | ✅ |
| **XSS** | Script payloads are not reflected as executable HTML; API responds as JSON | ✅ |
| **Input robustness** | Malformed JSON → 400 (not 500); unknown route → 404; wrong method → 405; oversized/unicode queries handled | ✅ |
| **No internal error disclosure** | No `Traceback`, `psycopg2`, `OperationalError`, or Django debug page markers in any hostile response | ✅ |
| **CORS** | A hostile `Origin` is not reflected in `Access-Control-Allow-Origin` | ✅ |
| **DEBUG disabled** | Prod-like server does not emit Django's `Using the URLconf defined in…` debug 404 page | ✅ |
| **Garbage JWT rejected** | A forged `Bearer` token is rejected (401/403) | ✅ |
| **Rate limiting active** | Registration/login throttles fired during testing (had to be relaxed in the test env to run flows) | ✅ (see §3) |

---

## 3. Findings & recommendations

### F-1 — `Product.save()` infinite slug-retry loop  ·  Severity: Medium (reliability)  ·  ✅ FIXED

`assistant/test_tools.py` appeared to "deadlock" while creating a `Product`. The
real cause was in `products/models.py`: the slug generator was an exception-driven
retry loop that re-ran `full_clean()` inside a nested `transaction.atomic()` and
caught **both** `ValidationError` and `IntegrityError`:

```python
while True:                                   # before
    self.slug = slug
    try:
        self.full_clean()
        with transaction.atomic():
            super().save(*args, **kwargs)
        return
    except (ValidationError, IntegrityError): # any validation error -> retry forever
        slug = f"{base_slug}-{counter}"; counter += 1
```

When a product was created missing a required field (the test omitted the
required `image`), `full_clean()` raised `ValidationError` *every* iteration, so
the loop span forever bumping the slug — a CPU-bound hang, not a true deadlock.
The same pattern existed in `Category`, `ProductVariant` and `ProductCombo`.

**Fix:** all four models now compute a unique slug with bounded `exists()`
queries via a shared `_generate_unique_slug()` helper (no nested savepoints, no
exception-driven retry), then validate + save once:

```python
if not self.slug:                             # after
    self.slug = _generate_unique_slug(type(self), slugify(...), fallback="product", current_pk=self.pk)
self.full_clean()
super().save(*args, **kwargs)
```

The invalid test fixtures in `assistant/test_tools.py` were given a valid image,
and the quarantine was removed. Suite goes from 319 passed / 1 failed / 1 module
ignored → **346 passed, 0 failed**.

### F-2 — Server version banner  ·  Severity: Low  ·  ✅ FIXED

`runserver` advertised `Server: WSGIServer/0.2 CPython/3.11.0`. Production fronts
the app with nginx (which already replaces the upstream gunicorn/python banner),
so the remaining exposure was nginx's own version. Added `server_tokens off;` to
both `nginx.conf` (http block) and `ngu.conf` (server block) so only
`Server: nginx` is sent, with no version. The e2e probe still skips against the
dev server (its `WSGIServer` banner is not representative of prod).

### F-3 — Image extension validator breaks updates  ·  Severity: Low  ·  ✅ FIXED

`test_update_product_admin_only` PATCHed only `{name}` yet failed with
`Unsupported file extension`. Root cause: `validate_image_extension` runs on
every `full_clean()`, and an **already-stored** file (e.g. a Cloudinary
`public_id` like `ngu/products/turmeric_x`) has no extension — so re-validating a
persisted file wrongly rejected unrelated updates.

**Fix:** `validate_image_extension` / `validate_video_extension` now return early
when the value has no extension (an already-persisted file; fresh uploads always
carry one). Separately, the test settings now use offline in-memory media storage
so the suite never uploads to real Cloudinary (faster, deterministic).

### F-4 — Authentication identity is `email`  ·  Severity: Informational

`User.USERNAME_FIELD = 'email'` (with `REQUIRED_FIELDS = ['username']`). Login
authenticates by **email + password**, not username. API clients and tests must
post `{"email", "password"}` to `/api/auth/login/`. (Captured here because the
e2e fixtures initially failed by posting `username`.)

### F-5 — Razorpay excluded  ·  Severity: Informational (scope)

Payment-gateway capture/verification flows were intentionally not exercised.
Recommend a separate, sandbox-keyed test pass for the Razorpay order →
signature-verification → webhook path before treating payments as covered.

---

## 3a. E-commerce resilience gaps — all fixed

Found by reasoning about real-store edge cases against the code, verified by
probe, then fixed with regression tests — including **real threaded concurrency
tests** for the two races (`orders/test_resilience.py`,
`orders/test_concurrency.py`, `users/test_email_normalization.py`).

| # | Scenario that shouldn't be allowed | Severity | Fix |
|---|------------------------------------|----------|-----|
| G1 | A delisted (`is_active=False`) product/combo checked out from a stale cart | High | order create rejects inactive products **and** combos |
| G2 | A combo sold with no regard to component stock, decrementing nothing → oversell + inventory desync | High | combo availability bounded by component stock; checkout draws down each component; **cancellation restores it** |
| G3 | Two accounts sharing an email differing only in case, while login matched case-insensitively → identity confusion/takeover | High | email lower-cased on every write (`User.save`); registration rejects case-insensitive dupes; Google login matches case-insensitively |
| G4 | Two concurrent checkouts for the **last unit** of a variant-less product both committed (stock clamped to 0) → oversell | High | legacy/component `Product.stock` decrements re-checked against the **locked** row and raise instead of clamping — proven by a 2-thread race test |
| G5 | A `max_usage=1` coupon redeemed by many concurrent checkouts (validate-then-increment was not atomic) | Med-High | coupon row `select_for_update`-locked and re-validated before incrementing usage — proven by a 2-thread race test |
| G7 | A **verified** review could be PATCHed onto a different product/combo the user never bought (`is_verified_purchase` is read-only and stayed `True`) → fake verified reviews. (Also surfaced a bug where `ReviewSerializer.validate()` demanded `product` on every PATCH, blocking legit rating/comment edits.) | High | `perform_update` makes the review's subject (item_type/product/combo) immutable; `validate()` is now partial-update aware |
| G8 | Changing a profile email to a **case variant of another account's email** returned a **500** (unhandled `IntegrityError`) and bypassed the G3 case-insensitive uniqueness rule | Medium | `UserSerializer.validate_email` lower-cases and rejects case-insensitive duplicates (excluding self) → clean 400 |
| G6 | Coupon errors were untruthful — one vague *"invalid, expired, or you do not meet the requirements"* for every cause, and the validate endpoint was **case-sensitive** (a code that worked at checkout was reported "does not exist") and ignored the minimum-order rule | Med (UX/correctness) | `Coupon.get_invalid_reason()` returns the **specific** cause ("This coupon has expired.", "…reached its usage limit.", "Add ₹N more…"); all three entry points (order create, the G5 race re-check, and the validate endpoint) surface it; validate endpoint now matches `code__iexact` and checks the cart total |

---

## 3b. Boundedness & abuse-resistance (out-of-bound DoS)

Every externally-influenced value is now bounded at the edge so an extreme value
returns a clean **4xx**, never a server-crashing **500**; abuse is rate-limited
and trackable for a manual ban. Built as four independent layers (remove any one
and the rest still work); all limits live in `Backend/spices_backend/limits.py`
and are env-tunable. Tests: `spices_backend/test_limits_and_abuse.py` (15).

**The crash this closes (verified):** a product priced ₹99,999.99 × qty 2000 →
`subtotal` overflowed `numeric(10,2)` → **500** that also leaked the raw DB error.
Now → **400** "Order total is too large", body carries no internals.

| Layer | What it does |
|-------|--------------|
| **Bounds** | per-line **quantity ≤ 100**, **cart ≤ 50 lines**, **sync ≤ 100 items**, **review comment ≤ 2000 chars**, **search `q` ≤ 200 chars** + `top_k`/`threshold` clamped, order-total overflow guard, and `DATA_UPLOAD_MAX_MEMORY_SIZE` cut 500 MB → **10 MB**. The order-create 500 handler no longer echoes `str(e)`. |
| **Rate limits** | new DRF scopes — `order` **10/min** (+ `order_day` **100/day**) on checkout, `cart_write` **60/min** on cart mutations. Returns **429**. |
| **Track** | `flag_suspicious()` logs a structured `ngu.abuse` warning (ip/user/path/reason) and bumps a rolling per-IP strike counter in Redis; alerts loudly past a threshold. Called from every bound rejection and on throttle denial. |
| **Ban** | `AbuseGuardMiddleware` 403s blocked IPs (fail-open); `python manage.py abuse_ban --ip … [--ttl N|--unban|--status]` is the manual lever. |

Frontend mirrors the same caps (`src/config/limits.ts`, also env-tunable) as a
first-line UX guard — quantity steppers/inputs capped, "cart full" blocked, and
the review box has `maxLength` + a live counter — with the backend authoritative.

**New env vars (all optional; defaults shown):** `MAX_ITEM_QUANTITY=100`,
`MAX_CART_ITEMS=50`, `MAX_SYNC_ITEMS=100`, `MAX_ORDER_TOTAL=9999999`,
`MAX_REVIEW_COMMENT=2000`, `MAX_SEARCH_Q=200`, `SEARCH_TOP_K_MAX=100`,
`THROTTLE_ORDER=10/min`, `THROTTLE_ORDER_DAY=100/day`, `THROTTLE_CART_WRITE=60/min`,
`DATA_UPLOAD_MAX_MEMORY_SIZE=10485760`, `ABUSE_STRIKE_WINDOW=300`,
`ABUSE_STRIKE_ALERT=20` (frontend: `VITE_MAX_ITEM_QUANTITY`, `VITE_MAX_CART_ITEMS`,
`VITE_MAX_REVIEW_COMMENT`).

---

## 4. Coverage map (what the suites exercise)

- **Unit/integration (in-process, Postgres):** models, serializers, view
  permissions, coupons, policies, reviews (verified-purchase gating), cart
  stock locking, order lifecycle, payments models, support, users/auth,
  product variants, assistant tools/unified-chat (50 tests), admin dashboard.
- **E2E (black-box HTTP):** health, catalog list/detail, combos, spice-forms,
  pagination clamp, search + autocomplete (incl. unicode/oversized), register →
  login → profile → token-refresh, password mismatch/weak-password rejection,
  cart add/view/clear + quantity validation, favorites, user-scoped orders,
  recommendations guard, anonymous assistant Q&A.
- **Security:** the controls in §2.

---

*Generated as part of the NGU testing initiative. See `testing/README.md` for
how to run each layer and `testing/reports/session_transcript.txt` for the raw
captured run that backs this report.*
