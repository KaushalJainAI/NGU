# API Reference — Code Review Map

A per-endpoint index of the whole HTTP surface, built to be a **starting point for
reviewing this codebase**. For every endpoint it records:

0. **URL** + method
1. **What** it does (one line)
2. **Access** — permission class / who can call it
3. **Complexity** — rough cost of one call (see legend)
4. **Tested** — is there a unit/integration test, for the happy path (✅ good) and
   failure paths (✅ bad)? See the *Tests* column.
5. **Serializer** — DRF serializer(s) used (`—` = hand-built dict / no serializer)
6. **DB tables** — models the request reads or writes
7. **Atomic** — does the write run inside `transaction.atomic()`?
8. **Risk** — blast radius if this endpoint is broken, abused, or mis-permissioned
9. **Notes** — the one thing worth knowing before you read the code

> This file is hand-derived from the source (`*/views.py`, `*/urls.py`, `*/tests.py`)
> on 2026-07-23 (route/serializer/permission rows reverified against code 2026-07-24;
> **Risk** column added 2026-07-25 — it is a review judgement, not generated).
>
> **Security pass 2026-07-25** — a review driven by this file's Risk-vs-Tests columns
> shipped three fixes: `/api/auth/google/` now requires Google's `email_verified`
> claim (it previously allowed takeover of any account by email), the dj-rest-auth
> routes were unmounted, and product-image uploads gained a size/type cap. New tests
> cover all three plus `/api/payment-account/`. See `docs/AUTH.md` for the Google flow.
> The `urls.py` files remain the source of truth — if you add a route, add a row. For
> the auth-focused view, see [API_PERMISSIONS.md](API_PERMISSIONS.md).

> **⚠ Production runtime state (observed 2026-07-24 — point-in-time, not code).** The
> code below is correct, but two prod env facts change how the payment surface actually
> behaves on the live box (`13.235.238.99`); see CLAUDE.md for the full trail:
> - **`RAZORPAY_WEBHOOK_SECRET` is unset in prod** → `/api/payments/webhook/` fails
>   closed and rejects **every** delivery, so L2 reconciliation is NOT running and
>   admin payment-instrument details (method/UPI/card) stay blank. `/verify/` still
>   captures (it uses `RAZORPAY_KEY_SECRET`, a different credential), so payments
>   succeed — only the webhook-sourced enrichment/reconciliation is dark.
> - **Prod is in Razorpay TEST mode** (`RAZORPAY_TEST_MODE=True`, resolved key is
>   `rzp_test_`). Flip to live before real customers pay.
>
> These are deployment-config gaps, not defects in the routes below. Verify current
> state on the box, don't trust this line blindly.

## Legend

**Complexity**
- `O(1)` — one indexed row lookup / single write
- `O(n)` — linear in the returned rows or posted items
- `Cached` — normally served from Redis (falls through to a DB query on miss)
- `Aggregate` — DB-side GROUP BY / annotate over many rows
- `External` — makes a blocking call to a third party (Razorpay, Nominatim, LLM, whisper)
- `Heavy` — in-process search / ranking / PDF generation

**Access**
- `Public` = `AllowAny` · `Auth` = `IsAuthenticated` · `Admin` = `IsAdminUser`/`is_staff`
- `Auth+RO/Public` = `IsAuthenticatedOrReadOnly` · `Admin+RO/Public` = read public, write staff

**Tested**: `✅ good / ✅ bad` = both covered · `✅ / —` = happy path only · `— / —` = no direct test.

**Atomic**: `Yes` inside a transaction · `N/A` read-only · `No` single write (implicitly atomic) · `⚠` write with no explicit transaction where one might be expected.

**Risk** — what it costs when this endpoint goes wrong (bug, abuse, or a permission
regression). Rank review effort by this column, not by complexity.

- 🔴 **Critical** — direct money loss, account takeover, or bulk PII/private-data
  exposure. Every change here needs a test and a second pair of eyes.
- 🟠 **High** — corrupts customer-visible state that is hard or impossible to undo:
  stock, order status, irreversible emails, catalog-wide writes, LLM/3rd-party spend.
- 🟡 **Medium** — recoverable damage or degraded UX: wrong list/report, failed upload,
  a single soft-deleted row, cache staleness.
- 🟢 **Low** — read-only, idempotent, or self-scoped; worst case is a bad response to
  one user.

Risk tracks **consequence, not complexity** — a one-line `O(1)` route can outrank an
`Aggregate` report. The combinations that raise a row: public + write, staff-only data
returned in bulk, anything that moves money, anything that sends an email or spends on a
third party, and anything that mutates stock.

---

## Routing overview

Almost everything is registered in [spices_backend/urls.py](../spices_backend/urls.py)
via a single DRF `DefaultRouter` plus explicit `path()` entries. The only app with
its own `urls.py` is `payments` (Razorpay endpoints). ViewSets on the router expand
to the standard `list / create / retrieve / update / partial_update / destroy`
actions plus any `@action` methods.

`api/schema/` + `api/docs/` (drf-spectacular Swagger UI) are mounted **only when
`DEBUG=True`**.

---

## 1. Auth & Users — app: `users` — [users/views.py](../users/views.py)

| URL | Method | What | Access | Complexity | Tests | Serializer | DB tables | Atomic | Risk | Notes |
|-----|--------|------|--------|-----------|-------|-----------|-----------|--------|------|-------|
| `/api/auth/register/` | POST | Create a user | Public (throttle 3/min) | O(1) | ✅ good / ✅ bad | `UserRegistrationSerializer` → `UserSerializer` | User | No | 🟠 High | Public write; weak validation = spam accounts / account pre-registration on a victim's email. SQLi/XSS/oversized/unicode all tested |
| `/api/auth/login/` | POST | Obtain JWT, set HttpOnly cookies | Public (throttle 5/min) | O(1) | ✅ good / ✅ bad | `CustomTokenObtainPairSerializer` | User | No | 🔴 Critical | Account takeover surface — credential stuffing, token leakage. Tokens go to cookies only, never JSON body; case-insensitive email |
| `/api/auth/token/refresh/` | POST | Refresh access cookie | Public | O(1) | ✅ good / ✅ bad | SimpleJWT | (outstanding token) | No | 🔴 Critical | A stolen refresh token renews access indefinitely if rotation/blacklist regresses. Reads refresh from body or cookie |
| `/api/auth/profile/` | GET/PUT/PATCH | Read / update own profile | Auth | O(1) | ✅ good / ✅ bad | `UserSerializer` | User | No | 🟠 High | Writable `is_staff`/`email` would be privilege escalation — read-only fields are the guard. `ensure_csrf_cookie`; email normalized |
| `/api/auth/change-password/` | POST | Change password | Auth (UserRateThrottle) | O(1) | ✅ good / ✅ bad | — (raw fields) | User | No | 🔴 Critical | Skipping the old-password check turns any session hijack into permanent takeover. Validates old pw + Django password validators |
| `/api/auth/password-reset-request/` | POST | Email a 6-digit OTP | Public (10/day) | O(1)+email | ✅ good / ✅ bad | `PasswordResetRequestSerializer` | User, PasswordResetOTP | No | 🔴 Critical | Public + sends email: enumeration and mail-bombing risk. Background thread; generic 200 to prevent enumeration |
| `/api/auth/password-reset-verify/` | POST | Verify OTP, mint reset token | Public (10/day) | O(1) | ✅ good / ✅ bad | `OTPVerifySerializer` | User, PasswordResetOTP | No | 🔴 Critical | 6 digits = brute-forceable without the lockout. OTP hashed at rest; failed-attempt lockout |
| `/api/auth/password-reset-confirm/` | POST | Set new password via reset token | Public (10/day) | O(1) | ✅ good / ✅ bad | `PasswordResetConfirmSerializer` | User, PasswordResetOTP | No | 🔴 Critical | Terminal step of takeover; single-use token + expiry are the only gate |
| `/api/auth/google/` | POST | Google id_token login/signup | Public (5/min) | External | ✅ good / ✅ bad | `UserSerializer` (out) | User | No | 🔴 Critical | Verifies signature vs Google certs **and requires `email_verified`** — without that check a validly-signed token carrying an unverified address logs the holder in as any existing user with that email (fixed 2026-07-25). Case-insensitive match; username de-duplicated across domains. Tests: [users/test_google_login.py](../users/test_google_login.py) |

---

## 2. Products, Categories, Combos, Sections, Variants — app: `products` — [products/views.py](../products/views.py)

Router basenames: `categories`, `products`, `combos`, `product-images`,
`product-variants`, `product-sections`. All use `IsAdminOrReadOnly` (public read,
staff write). List/retrieve for the storefront resources are **Redis-cached per
language** for non-staff.

| URL | Method | What | Access | Complexity | Tests | Serializer | DB tables | Atomic | Risk | Notes |
|-----|--------|------|--------|-----------|-------|-----------|-----------|--------|------|-------|
| `/api/categories/` | GET | List categories | Admin+RO/Public | Cached / Aggregate | ✅ good / ✅ bad | `CategorySerializer` | Category, Product (count) | N/A | 🟢 Low | Public read of public data; worst case a stale count. Annotates active-product count |
| `/api/categories/` | POST | Create category | Admin | O(1) | ✅ good / ✅ bad | `CategorySerializer` | Category | No | 🟡 Medium | Storefront navigation change, easily undone. Regular user + anon forbidden (tested) |
| `/api/categories/{slug}/` | GET | Category detail (slug or id) | Admin+RO/Public | O(1) | ✅ good / ✅ bad | `CategorySerializer` | Category | N/A | 🟢 Low | |
| `/api/categories/{slug}/` | PUT/PATCH/DELETE | Update / soft-delete | Admin | O(1) | ✅ good / ✅ bad | `CategorySerializer` | Category | No | 🟠 High | Hiding a category hides every product under it from the storefront. DELETE = `is_active=False` (soft) |
| `/api/products/` | GET | List products (+filters, search, ordering) | Admin+RO/Public | Cached / Aggregate | ✅ good / ✅ bad | `ProductListSerializer` | Product, Category, Review, ProductVariant, ProductSection | N/A | 🟡 Medium | Highest-traffic read — a cache-key or filter bug breaks the whole storefront. `ProductFilter` matches canonical **and** extra categories |
| `/api/products/` | POST | Create product | Admin | O(1) | ✅ good / ✅ bad | `ProductDetailSerializer` | Product | No | 🟠 High | Wrong price or GST rate here is sold at that price until caught. Negative/zero price, discount>price, SQLi/XSS tested |
| `/api/products/{slug}/` | GET | Product detail (slug / id / variant-slug / retired-slug) | Admin+RO/Public | O(1) | ✅ good / ✅ bad | `ProductDetailSerializer` | Product, ProductVariant, ProductSlugAlias, images | N/A | 🟡 Medium | 4-way slug resolution — a regression 404s live SEO URLs |
| `/api/products/{slug}/` | PUT/PATCH/DELETE | Update / soft-delete to Recycle Bin | Admin | O(1) | ✅ good / ✅ bad | `ProductDetailSerializer` | Product | No | 🔴 Critical | Price/tax/stock edits move real money; DELETE starts the 30-day purge clock. DELETE stamps `deactivated_at` |
| `/api/products/sections/` | GET | Homepage sections w/ nested products+combos | Admin+RO/Public | Cached / O(n) | ✅ good / — | `HomepageSectionSerializer` | ProductSection, placements, Product, ProductCombo | N/A | 🟡 Medium | The homepage itself; failure = empty landing page. Rich storefront payload |
| `/api/combos/` | GET | List combos | Admin+RO/Public | Cached / O(n) | ✅ good / ✅ bad | `ProductComboSerializer` | ProductCombo, ProductComboItem, Product, sections | N/A | 🟢 Low | |
| `/api/combos/` | POST | Create combo | Admin | O(1) | ✅ good / ✅ bad | `ProductComboSerializer` | ProductCombo, ProductComboItem | No | 🟠 High | Combo priced below its own components sells at a loss. Negative price, discount>price, SQLi tested |
| `/api/combos/{slug}/` | GET | Combo detail (slug/id) | Admin+RO/Public | O(1) | ✅ good / ✅ bad | `ProductComboSerializer` | ProductCombo, ProductComboItem | N/A | 🟢 Low | |
| `/api/combos/{slug}/` | PUT/PATCH/DELETE | Update / soft-delete | Admin | O(1) | ✅ good / ✅ bad | `ProductComboSerializer` | ProductCombo | No | 🟠 High | Same pricing exposure as create. Soft-delete to Recycle Bin |
| `/api/product-images/` | GET/POST | List / upload product images | Admin+RO/Public | O(1) | ✅ good / ✅ bad | `ProductImageSerializer` | ProductImage, Product | No | 🟠 High | Upload to a third-party store (Cloudinary quota). 5 MB cap + content-type allowlist added 2026-07-25; Pillow decode on the model `ImageField` is the real type gate (client content-type is defence-in-depth). Multipart |
| `/api/product-images/{id}/` | GET/PUT/PATCH/DELETE | Image CRUD | Admin | O(1) | — / — | `ProductImageSerializer` | ProductImage | No | 🟡 Medium | Untested; deletes a live product image |
| `/api/product-variants/` | GET/POST | List / create packaging sizes | Admin+RO/Public | O(1) | ✅ good / ✅ bad | `ProductVariantWriteSerializer` | ProductVariant, Product | No | 🔴 Critical | Variants carry the price and stock customers actually buy. Ensures single default per product. Bad paths: [products/test_variant_image_badpaths.py](../products/test_variant_image_badpaths.py) |
| `/api/product-variants/{id}/` | PUT/PATCH/DELETE | Variant CRUD | Admin | O(1) | ✅ good / ✅ bad | `ProductVariantWriteSerializer` | ProductVariant | No | 🔴 Critical | Editing price/stock of a sellable SKU; DELETE would orphan order history if not protected. DELETE deactivates if referenced by an order (ProtectedError) |
| `/api/product-sections/` | GET/POST | Flat sections list / create | Admin+RO/Public | O(n) | ✅ good / ✅ bad | `ProductSectionSerializer` | ProductSection | No | 🟡 Medium | Merchandising only. Powers admin Sections page |
| `/api/product-sections/{id}/` | PUT/PATCH/DELETE | Section CRUD | Admin | O(1) | ✅ good / — | `ProductSectionSerializer` | ProductSection | No | 🟡 Medium | DELETE soft-hides a homepage row |
| `/api/product-sections/{id}/products/` | GET/PUT | Read / replace ordered product list | Admin+RO(GET)/Admin(PUT) | O(n) | ✅ good / ✅ bad | — (dict) | ProductSectionPlacement, Product | **Yes** (PUT) | 🟠 High | PUT is destructive-replace — a partial payload wipes the row's curation. Rebuilds placements atomically |
| `/api/spice-forms/` | GET | Enumerate spice-form choices | Public | O(1) | ✅ good / — | — | (none — choices) | N/A | 🟢 Low | Static enum |
| `/api/search/` | GET | Unified product+combo fuzzy search | Public | Heavy | ✅ good / ✅ bad | — | (in-memory corpus over Product/Combo/KB) | N/A | 🟠 High | Public + `Heavy` = the cheapest DoS lever in the API; clamps are load-bearing. `q` length + `top_k`/`threshold` clamped; SQLi tested |
| `/api/search/suggest/` | GET | Autocomplete suggestions | Public (own throttle) | Cached / Heavy | ✅ good / ✅ bad | — | search corpus | N/A | 🟠 High | Fires on every keystroke; a cache miss storm is the failure mode. <2 chars → empty |
| `/api/recommendations/` | GET | Personalized recommendations | Auth (401 for anon) | Heavy | — / — | — | UserEvent, Product | N/A | 🟡 Medium | Untested + heavy, but read-only and degrades to a fallback. Cold-start → featured-popular |

---

## 3. Bulk product tools — app: `products` — [products/bulk_views.py](../products/bulk_views.py)

All staff-only (`IsStaff`), read/write on **Product** only.

| URL | Method | What | Access | Complexity | Tests | Serializer | DB tables | Atomic | Risk | Notes |
|-----|--------|------|--------|-----------|-------|-----------|-----------|--------|------|-------|
| `/api/admin/bulk-products/` | GET | Flat editable product grid | Admin | O(n) | ✅ / — | — | Product, Category | N/A | 🟡 Medium | Unpaginated whole catalog — grows without bound as the catalog does |
| `/api/admin/bulk-products/apply/` | POST | Apply price/stock changes, all-or-nothing | Admin | O(n) | ✅ good / ✅ bad | — | Product | **Yes** | 🔴 Critical | **Highest-blast-radius write in the API** — one call can reprice or zero the stock of the entire catalog, with no undo. Validates every row first; `select_for_update` on save |
| `/api/admin/bulk-products/import/` | POST | Validate a CSV, return **preview** (no save) | Admin | O(n) | ✅ good / ✅ bad | — | Product (read) | N/A | 🟠 High | Read-only itself, but it is the safety gate in front of `apply/` — a preview that misreports is worse than no preview. Name-matched; BOM-tolerant |
| `/api/admin/products-export/` | GET | Download catalog CSV | Admin | O(n) | ✅ / ✅ (staff) | — | Product, Category | N/A | 🟡 Medium | Full cost/pricing catalog leaves the system as a file — CSV formula-injection surface |

---

## 4. Cart & Favorites — app: `cart` — [cart/views.py](../cart/views.py)

Router basenames `cart`, `favorites`; plus two `APIView`s. All `IsAuthenticated`.
Every mutation runs inside `transaction.atomic()` with `select_for_update` locks.

| URL | Method | What | Access | Complexity | Tests | Serializer | DB tables | Atomic | Risk | Notes |
|-----|--------|------|--------|-----------|-------|-----------|-----------|--------|------|-------|
| `/api/cart/` | GET | Get current cart | Auth | O(n) | ✅ good / ✅ bad | `CartResponseSerializer` | Cart, CartItem, Product, ProductVariant, ProductCombo | N/A | 🟡 Medium | Queryset scoping is the only thing between users' carts. Cross-user isolation tested |
| `/api/cart/add_item/` | POST | Add product/combo line | Auth (CartWriteThrottle) | O(1) | ✅ good / ✅ bad | `CartResponseSerializer` | Cart, CartItem, Product, ProductVariant, ProductCombo | **Yes** | 🟠 High | Sets the price basis carried into checkout; qty/stock caps are the anti-abuse gate. SQLi, float/string qty tested |
| `/api/cart/update_item/` | POST | Change line qty (0 = remove) | Auth (throttle) | O(1) | ✅ good / ✅ bad | `CartResponseSerializer` | Cart, CartItem, Product, ProductVariant | **Yes** | 🟠 High | Negative/overflow qty here would corrupt order totals. Over-max qty flagged as abuse |
| `/api/cart/remove_item/` | POST/DELETE | Remove a line (composite key) | Auth (throttle) | O(1) | ✅ good / ✅ bad | `CartResponseSerializer` | Cart, CartItem | **Yes** | 🟡 Medium | Composite-key parsing is the spot to check. Accepts `"product-123"` / `"combo-4"` |
| `/api/cart/clear/` | POST | Empty the cart | Auth (throttle) | O(n) | ✅ / — | — | Cart, CartItem | **Yes** | 🟡 Medium | Destructive but self-scoped and re-fillable; no bad-path test |
| `/api/cart/sync/` | POST | Merge localStorage cart on login | Auth (throttle) | O(n) | ✅ good / ✅ bad | `CartResponseSerializer` | Cart, CartItem, Product, ProductVariant, ProductCombo | **Yes** | 🟠 High | Clears then rebuilds — a mid-way failure loses the cart; client-supplied payload. Validates ALL before clearing; size capped; returns `skipped[]` |
| `/api/auth/validate-coupon/` | POST | Validate coupon vs cart total | Auth | O(1) | ✅ good / ✅ bad | `ValidateCouponSerializer` | Coupon, Cart | N/A | 🟠 High | Discount math customers see; must agree with checkout or it's a dispute. Case-insensitive; honors min-order |
| `/api/favorites/` | GET | List favorites | Auth | O(n) | ✅ good / ✅ bad | `FavoriteItemSerializer` | Favorite, Product | N/A | 🟢 Low | |
| `/api/favorites/` | POST | Add favorite | Auth | O(1) | ✅ good / ✅ bad | — | Favorite, Product | No | 🟢 Low | `get_or_create` (idempotent) |
| `/api/favorites/{pk}/` | DELETE | Remove favorite | Auth | O(1) | ✅ good / ✅ bad | — | Favorite | No | 🟢 Low | Cross-user delete blocked (tested) |
| `/api/favorites/sync/` | POST | Bulk sync favorites | Auth | O(n) | ✅ / — | `FavoriteItemSerializer` | Favorite, Product | **Yes** | 🟡 Medium | Unbounded client list, no bad-path test. `bulk_create(ignore_conflicts=True)` |

> `CartPaymentQRView` exists in the file (UPI QR generation) but is **not routed** in
> the current `urls.py` — dead code path, worth flagging in review.

---

## 5. Orders — app: `orders` — [orders/views.py](../orders/views.py)

Router basename `orders`, `IsAuthenticated`. Customers see only their own
(non-deleted) orders; staff see all (paginated, with server-side filter/sort/search).
This is the **most complex** module — checkout does pricing, per-line tax, stock
reservation, coupon locking, and cart clearing in one transaction.

| URL | Method | What | Access | Complexity | Tests | Serializer | DB tables | Atomic | Risk | Notes |
|-----|--------|------|--------|-----------|-------|-----------|-----------|--------|------|-------|
| `/api/orders/` | GET | List orders (customer array / admin paginated + CSV) | Auth (admin sees all) | O(n)/Aggregate | ✅ good / ✅ bad | `OrderListSerializer` | Order, OrderItem, User, Payment | N/A | 🔴 Critical | One missing `is_staff` branch exposes every customer's name, address, phone and spend. `?export=csv`, `?deleted=true`, admin filter/sort/search all DB-side |
| `/api/orders/` | POST | **Create order / checkout** | Auth (OrderRate + Daily throttle) | O(n) + locks | ✅ good / ✅ bad | `OrderCreateSerializer` → `OrderDetailSerializer` | Order, OrderItem, Cart, CartItem, Product, ProductVariant, ProductComboItem, Coupon, Payment | **Yes** | 🔴 Critical | The money path: computes what the customer pays, reserves stock, redeems coupons. Bugs = oversell, under-charge, or coupon over-redemption. Locks Cart; supersedes stale ONLINE order; per-line proportional discount + GST |
| `/api/orders/{id}/` | GET | Order detail | Auth (owner/staff) | O(1) | ✅ good / ✅ bad | `OrderDetailSerializer` | Order, OrderItem, Payment | N/A | 🔴 Critical | IDOR target — full PII + payment instrument on one object. Other-user access 404s |
| `/api/orders/{id}/` | PUT/PATCH | Admin edit (status/tracking/address/payment_status) | **Admin only** | O(1) + locks | ✅ good / ✅ bad | `OrderDetailSerializer` | Order, Payment, Product, ProductVariant | **Yes** | 🔴 Critical | Can flip `payment_status` (marks an unpaid order paid) and fires the irreversible shipping email. Cancel-via-status restocks; only tracking-added emails |
| `/api/orders/{id}/cancel/` | POST | Cancel + restock | Auth (owner/staff) | O(n) + locks | ✅ good / ✅ bad | `OrderDetailSerializer` | Order, Payment, Product, ProductVariant, ProductComboItem | **Yes** | 🔴 Critical | Restock double-run inflates inventory; and cancel does **not** refund — money stays captured. Blocks self-cancel of a captured-payment order |
| `/api/orders/{id}/` | DELETE | Soft-delete to Recycle Bin | **Admin only** | O(1) | ✅ good / ✅ bad | — | Order | No | 🟠 High | Financial record leaves reports; purged for real after 30 days. Never hard-deletes |
| `/api/orders/{id}/restore/` | POST | Restore from Recycle Bin | **Admin only** | O(1) | ✅ good / ✅ bad | `OrderDetailSerializer` | Order | No | 🟡 Medium | Recovery path — its own failure is what makes DELETE dangerous |
| `/api/orders/validate_coupon/` | POST | Preview coupon breakdown vs cart | Auth | O(n) | ✅ good / ✅ bad | — | Cart, CartItem, Coupon | N/A | 🟠 High | Duplicates checkout math; divergence = customer charged more than quoted |
| `/api/orders/{id}/invoice/` | GET | PDF tax invoice | Auth (owner/staff) | Heavy | ✅ good / — | — (reportlab) | Order, OrderItem, User | N/A | 🟠 High | Legal GST document with PII; wrong tax figures are a compliance problem. 503 if reportlab missing |
| `/api/orders/{id}/packing-slip/` | GET | PDF packing slip (no prices) | **Staff only** | Heavy | ✅ good / ✅ bad | — (reportlab) | Order, OrderItem | N/A | 🟡 Medium | Staff-gated; leak exposes addresses. Customer 403 (tested) |
| `/api/orders/{id}/delivery_bill/` | GET/POST/DELETE | Admin-private courier bill store | **Staff only** | O(1) | ✅ good / ✅ bad | — | Order (file field) | No | 🟠 High | Authenticated file upload + private file serving — must never become a public URL. Magic-byte type check; 10 MB cap; streamed inline |

> **G4/G5 concurrency** (oversell + coupon over-redeem) are covered in
> [orders/test_concurrency.py](../orders/test_concurrency.py) — these pass on Postgres
> and fail on SQLite (documented). Checkout pricing/shipping/combo cases live in
> [orders/test_checkout_and_ops.py](../orders/test_checkout_and_ops.py).

---

## 6. Payments — app: `payments` — [payments/views.py](../payments/views.py) + [payments/urls.py](../payments/urls.py)

`PaymentMethodViewSet` (router `payment-methods`, saved instruments) is `IsAuthenticated`
per-user. The four Razorpay function endpoints live under `/api/payments/`.

| URL | Method | What | Access | Complexity | Tests | Serializer | DB tables | Atomic | Risk | Notes |
|-----|--------|------|--------|-----------|-------|-----------|-----------|--------|------|-------|
| `/api/payment-methods/` | GET/POST | List / add saved instrument | Auth | O(n)/O(1) | ✅ good / ✅ bad | `PaymentMethodSerializer` / `…CreateSerializer` | PaymentMethod | No | 🟠 High | Stores payment-instrument metadata — never let full PAN/VPA land here. Per-user queryset; SQLi tested |
| `/api/payment-methods/{id}/` | GET/PUT/PATCH/DELETE | Instrument CRUD (soft delete) | Auth (owner) | O(1) | ✅ good / ✅ bad | `PaymentMethodSerializer` | PaymentMethod | No | 🟠 High | IDOR here leaks another user's instruments. Cross-user access blocked |
| `/api/payment-methods/{id}/set_default/` | POST | Mark default | Auth | O(n) | ✅ / — | `PaymentMethodSerializer` | PaymentMethod | No | 🟡 Medium | Multi-row write with no bad-path test. Clears other defaults |
| `/api/payment-methods/default/` | GET | Get default | Auth | O(1) | ✅ good / ✅ bad | `PaymentMethodSerializer` | PaymentMethod | N/A | 🟢 Low | 404 when none |
| `/api/payment-methods/by_type/` | GET | Filter by UPI/CARD/… | Auth | O(n) | ✅ good / ✅ bad | `PaymentMethodSerializer` | PaymentMethod | N/A | 🟢 Low | Invalid/missing type 400 |
| `/api/payment-methods/stats/` | GET | Counts by type | Auth | Aggregate | ✅ / — | — | PaymentMethod | N/A | 🟢 Low | |
| `/api/payments/create-order/` | POST | Create/reuse Razorpay order for an Order | Auth (PaymentRateThrottle) | External + locks | ✅ good / ✅ bad | `CreateOrderSerializer` | Order, Payment | **Yes** | 🔴 Critical | If the amount ever came from the client, the customer picks their own price. Amount computed server-side; idempotent (one live order) |
| `/api/payments/verify/` | POST | L1 browser signature verify → capture | Auth (throttle) | External + locks | ✅ good / ✅ bad | `VerifyPaymentSerializer` | Payment, Order (+ Cart on capture) | **Yes** (in `services`) | 🔴 Critical | Client-supplied payload that marks an order paid — the HMAC check is the entire defense. Honest "cancelled" response after capture-after-cancel |
| `/api/payments/webhook/` | POST | L2 Razorpay webhook (source of truth) | **Public**, signature-gated (`@csrf_exempt`) | External + locks | ✅ good / ✅ bad | — (raw body) | Payment, Order, PaymentEvent | **Yes** (in `services`) | 🔴 Critical | Unauthenticated public endpoint that settles money; signature over the **raw** body is the only gate, and it is replayed/retried by Razorpay so idempotency is mandatory. **Fail-closed if `RAZORPAY_WEBHOOK_SECRET` unset** (→ 400) — **currently unset in prod, so L2 is dark; see the runtime-state note at top**; 1 MB body cap; unknown events ACK 200; orphans logged + still ACKed |
| `/api/payments/status/` | GET | Non-alarming payment state for polling | Auth (owner) | O(1) | ✅ good / — | — | Order, Payment | N/A | 🟡 Medium | Polled in a loop; over-reporting "paid" would mislead the customer. "Confirming…" during the verify/webhook gap |

> Capture/verify/webhook idempotency, L1/L2 race, double-capture, refund, and
> instrument-detail capture are all covered in
> [payments/test_razorpay_and_payment_flow.py](../payments/test_razorpay_and_payment_flow.py).
> Note: the shared atomicity lives in `payments/services.py` (`mark_payment_*`), not
> the view — review that file alongside these endpoints.

---

## 7. Reviews — app: `reviews` — [reviews/views.py](../reviews/views.py)

Router basename `reviews`, `IsAuthenticatedOrReadOnly`. Verified-purchase gated;
staff moderation via `is_hidden`.

| URL | Method | What | Access | Complexity | Tests | Serializer | DB tables | Atomic | Risk | Notes |
|-----|--------|------|--------|-----------|-------|-----------|-----------|--------|------|-------|
| `/api/reviews/` | GET | List reviews (filter by product/combo) | Auth+RO/Public | O(n) | ✅ good / ✅ bad | `ReviewSerializer` | Review, User, Product, ProductCombo | N/A | 🟠 High | Public read that joins User — over-serializing leaks buyer identity, and a visibility bug un-hides moderated content. Hidden reviews visible only to staff + author |
| `/api/reviews/` | POST | Create review | Auth | O(1) | ✅ good / ✅ bad | `ReviewSerializer` | Review, OrderItem, Order | No | 🟠 High | Public-facing UGC; the verified-purchase check is the anti-astroturfing gate. Enforces no duplicate |
| `/api/reviews/{id}/` | GET | Review detail | Auth+RO/Public | O(1) | ✅ / — | `ReviewSerializer` | Review | N/A | 🟡 Medium | No bad-path test; must respect `is_hidden` |
| `/api/reviews/{id}/` | PUT/PATCH | Edit own review | Auth (owner) | O(1) | ✅ good / ✅ bad | `ReviewSerializer` | Review | No | 🟠 High | Edit-then-repoint would launder a verified review onto an unbought product. Cannot re-point (anti-fraud) |
| `/api/reviews/{id}/` | DELETE | Delete own review | Auth (owner/staff) | O(1) | ✅ / — | — | Review | No | 🟡 Medium | Hard delete, no bad-path test. Non-owner queryset excluded |
| `/api/reviews/can-review/` | GET | May the user review X? (UX hint) | Auth | O(1) | ✅ good / ✅ bad | — | Review, OrderItem | N/A | 🟢 Low | Advisory only — POST re-checks. Exactly one of product/combo |
| `/api/reviews/{id}/set-hidden/` | POST | Moderate (hide/show) | **Staff only** | O(1) | ✅ good / ✅ bad | — | Review | No | 🟠 High | Censorship control — if it leaked to non-staff, anyone could bury bad reviews. Non-staff 403 |

---

## 8. Admin panel — app: `admin_panel` — [admin_panel/views.py](../admin_panel/views.py)

| URL | Method | What | Access | Complexity | Tests | Serializer | DB tables | Atomic | Risk | Notes |
|-----|--------|------|--------|-----------|-------|-----------|-----------|--------|------|-------|
| `/api/receivable-accounts/` | GET/POST/…/DELETE | Payment-collection accounts CRUD | **Admin** | O(1) | ✅ / ✅ | `ReceivableAccountSerializer` | ReceivableAccount | No | 🔴 Critical | Bank account / UPI ID that customers pay into — a wrong or tampered row sends money to the wrong place. Admin only |
| `/api/payment-account/` | GET | Default UPI account for checkout | Auth | O(1) | ✅ good / ✅ bad | — | ReceivableAccount | N/A | 🔴 Critical | Hands the payee UPI ID to every logged-in user; over-serializing would expose full bank details. Hand-built dict returns only `id`/`account_name`/`upi_id` — a test asserts bank number/IFSC/contacts never appear ([admin_panel/test_payment_account.py](../admin_panel/test_payment_account.py)) |
| `/api/coupons/` | GET/POST | List / create coupons | **Admin** | O(n) | ✅ good / ✅ bad | `CouponSerializer` | Coupon | No | 🟠 High | Creates real discount liability; a bad percentage is money given away. Unpaginated; dup code / >100% / negative tested |
| `/api/coupons/{id}/` | GET/PUT/PATCH/DELETE | Coupon CRUD | **Admin** | O(1) | ✅ good / ✅ bad | `CouponSerializer` | Coupon | No | 🟠 High | Editing an in-flight coupon changes what live carts get charged |
| `/api/coupons/validate/` | POST | Admin structural coupon check | **Admin** | O(1) | ✅ good / ✅ bad | `CouponSerializer` | Coupon | N/A | 🟢 Low | Read-only; ignores per-cart concerns by design |
| `/api/dashboard/` | GET | Sales/counts summary | **Admin** | Aggregate (cached 2m) | ✅ good / ✅ bad | `RecentOrderSerializer` | Order, Product, ProductCombo, Coupon | N/A | 🟡 Medium | Revenue figures the owner makes decisions on; cached so errors persist minutes |
| `/api/dashboard/actions/` | GET | "Today" action inbox | **Admin** | Aggregate (cached 60s) | ✅ good / ✅ bad | — | Order, Product, AssistantConversation | N/A | 🟠 High | The owner's whole workflow — a missed count means orders never ship. Confirmable/ship/low-stock/stuck-payment counts |
| `/api/dashboard/send-report/` | POST | Trigger daily/weekly email now | **Admin** | External (email) | ✅ good / ✅ bad | — | (rollups) | N/A | 🟠 High | On-demand outbound email = unrecallable send + spam-reputation risk if loopable. `{type: daily\|weekly}` |
| `/api/admin-search/` | GET | Global search (orders/products/customers/coupons) | **Admin** | O(n) | ✅ good / ✅ bad | — | Order, Product, User, Coupon | N/A | 🔴 Critical | Cross-table free-text over customer PII; a permission slip here is a full-database search box. Capped per group |
| `/api/admin-customers/` | GET | Customer directory (paginated, search) | **Admin** | Aggregate | ✅ good / ✅ bad | `AdminCustomerListSerializer` | User, Order | N/A | 🔴 Critical | Bulk PII listing. Order count + total spent annotated |
| `/api/admin-customers/{id}/` | GET | Customer detail + order history | **Admin** | O(n) | ✅ good / — | `AdminCustomer*Serializer` | User, Order | N/A | 🔴 Critical | Complete profile of one person; no bad-path test. Last 50 orders |
| `/api/admin-customers/export/` | GET | Customer CSV | **Admin** | O(n) | ✅ / — | — | User, Order | N/A | 🔴 Critical | Exfiltration in one click — the entire customer list as a portable file. Formula-injection escaped (tested) |

> `PolicyViewSet` exists (`IsReadOnlyOrAdmin`) with full retire/create logic and
> tests, but **is not registered** in the current router — the storefront serves
> static policy pages. Flag as intentionally-dormant code when reviewing.

---

## 9. Support (contact) — app: `support` — [support/views.py](../support/views.py)

| URL | Method | What | Access | Complexity | Tests | Serializer | DB tables | Atomic | Risk | Notes |
|-----|--------|------|--------|-----------|-------|-----------|-----------|--------|------|-------|
| `/api/contact/` | POST | Submit contact form | **Public** (5/hr throttle) | O(1) | ✅ good / ✅ bad | `ContactSubmissionSerializer` | ContactSubmission, User | No | 🟠 High | Unauthenticated write storing attacker-controlled text later rendered in the admin panel — throttle + sanitization are the gate. XSS/SQLi/oversized tested |
| `/api/contact/` | GET | List submissions | **Admin** | O(n) | ✅ good / ✅ bad | `ContactSubmissionAdminSerializer` | ContactSubmission | N/A | 🟠 High | Unpaginated inbox of public-submitted PII; grows unbounded. Regular user 403 |
| `/api/contact/{id}/` | GET/PUT/DELETE | Submission detail/admin edit | **Admin** | O(1) | — / — | `ContactSubmissionAdminSerializer` | ContactSubmission | No | 🟡 Medium | No tests at all; DELETE is a hard delete |
| `/api/contact/{id}/mark_read/` | POST | Mark read | **Admin** | O(1) | — / — | — | ContactSubmission | No | 🟢 Low | Untested flag flip |
| `/api/contact/{id}/reply/` | POST | Mark replied + notes | **Admin** | O(1) | — / — | — | ContactSubmission | No | 🟡 Medium | Untested; stores admin-authored text. Notes sanitized (`strip_tags`+`escape`) |

---

## 10. Assistant (unified AI chat + support) — app: `assistant` — [assistant/views.py](../assistant/views.py)

Login-only by design (see the `assistant-login-only` memory). Customer chat runs a
tool-calling agent; a separate admin persona reads business data.

| URL | Method | What | Access | Complexity | Tests | Serializer | DB tables | Atomic | Risk | Notes |
|-----|--------|------|--------|-----------|-------|-----------|-----------|--------|------|-------|
| `/api/assistant/chat/` | POST | Send message, AI replies (tool agent) | Auth (Burst+Daily throttle) | External (LLM) | ✅ good / ✅ bad | `AssistantChatRequestSerializer` | AssistantConversation, AssistantMessage (+tools read catalog/orders) | No | 🔴 Critical | Prompt injection reaching order-reading tools = cross-user data leak; also metered LLM spend per call. User injected by view (G1); escalation flag |
| `/api/assistant/admin-chat/` | POST | Store-owner Q&A over business data | **Admin** | External (LLM) | ✅ good / ✅ bad | — | (read-only reporting tools) | N/A | 🟠 High | Whole-business data into a third-party model; read-only persona is the containment. Stateless; `persona='admin'`; no action tools |
| `/api/assistant/transcribe/` | POST | Voice → text (whisper.cpp) | Auth (throttle) | External (whisper) | — / — | — | (none — persists nothing) | N/A | 🟡 Medium | Binary upload to a sidecar container, but bounded: 8 MB cap, burst+daily throttles, `USE_SELF_HOSTED_STT` gate, persists nothing. Untested; `language` is passed through unvalidated |
| `/api/assistant/conversations/` | GET/POST | List own threads / create thread | Auth | O(n)/O(1) | ✅ good / ✅ bad | `ConversationSummarySerializer` | AssistantConversation, AssistantMessage | No | 🟡 Medium | Self-scoped. Last-message annotated (no N+1) |
| `/api/assistant/conversations/{uuid}/messages/` | GET | Full message history | Auth (owner/staff) | O(n) | ✅ good / ✅ bad | `MessageSerializer` | AssistantConversation, AssistantMessage | N/A | 🟠 High | UUID-addressed transcript — ownership check is the only thing preventing chat-history IDOR. Excludes tool/system roles |
| `/api/assistant/conversations/admin/` | GET | Admin: list all threads (filters) | **Admin** | O(n) | ✅ good / ✅ bad | `ConversationSummarySerializer` | AssistantConversation | N/A | 🟠 High | Every customer's conversations in one list. `needs_human`/`status`/`user_id` filters |
| `/api/assistant/conversations/{uuid}/admin-reply/` | POST | Admin: reply into a thread | **Admin** | O(1) | ✅ good / ✅ bad | `AdminReplySerializer` | AssistantConversation, AssistantMessage | No | 🟠 High | Writes a message the customer reads as the store speaking; wrong thread = misdirected reply. Clears `needs_human` |
| `/api/assistant/conversations/{uuid}/` | PATCH | Admin: update status/assigned_to | **Admin** | O(1) | ✅ good / ✅ bad | `ConversationPatchSerializer` | AssistantConversation | No | 🟡 Medium | Route-ordering hazard: static `admin/` is declared before `<uuid>` so it isn't shadowed |

> Extensive guardrail tests (prompt injection, cross-user isolation, tool allowlist,
> escalation, degrade-without-LLM) in
> [assistant/test_guardrails.py](../assistant/test_guardrails.py) and
> [assistant/test_chat_and_tools.py](../assistant/test_chat_and_tools.py).

---

## 11. Analytics & Location — app: `analytics` — [analytics/views.py](../analytics/views.py) + [analytics/insights_views.py](../analytics/insights_views.py)

| URL | Method | What | Access | Complexity | Tests | Serializer | DB tables | Atomic | Risk | Notes |
|-----|--------|------|--------|-----------|-------|-----------|-----------|--------|------|-------|
| `/api/events/` | POST | Ingest behavioral event(s) | Auth (throttle) | O(n) | ✅ good / ✅ bad | `UserEventSerializer` | UserEvent | No | 🟡 Medium | High-volume unbounded-growth table; feeds recommendations. Batch; invalid items skipped not failed; `bulk_create` |
| `/api/anon-events/` | POST | Anonymous aggregate counter | **Public**, no auth/CSRF | O(1) | ✅ good / ✅ bad | — | AnonymousCounter (aggregate) | No | 🟠 High | The only unauthenticated, CSRF-exempt write in the API — trivially spoofable, so treat its numbers as untrusted and watch it as a write-amplification target. Always 204; identity-free by design |
| `/api/geocode/reverse/` | GET | Reverse-geocode via Nominatim (proxied) | Auth (throttle) | External (cached 30d) | — / — | — | (Redis cache only) | N/A | 🟡 Medium | Not SSRF — the upstream URL is a module constant and only validated lat/lng are forwarded. The real exposure is outbound-call amplification under **our** IP (abuse gets the shop rate-limited by Nominatim); throttle + 30d cache are the controls. Untested |
| `/api/geo/` | GET/PUT | Read / upsert coarse user location | Auth | O(1) | — / — | `UserGeoSerializer` | UserGeo | No | 🟠 High | Untested location PII write; precision rounding is the privacy control |
| `/api/analytics/overview/` | GET | KPI overview | **Admin** | Aggregate (cached) | ✅ good / ✅ bad | — | Sales/behavioral rollups | N/A | 🟡 Medium | Business figures drive decisions; reads pre-computed rollups |
| `/api/analytics/sales/` | GET | Sales series + KPIs | **Admin** | Aggregate (cached) | ✅ good / ✅ bad | — | Sales rollups | N/A | 🟡 Medium | Revenue reporting — wrong ≠ broken, which is why it goes unnoticed. `?from&to&granularity` |
| `/api/analytics/funnel/` | GET | Conversion funnel | **Admin** | Aggregate (cached) | ✅ good / ✅ bad | — | Behavioral rollups | N/A | 🟢 Low | |
| `/api/analytics/search/` | GET | Search insights | **Admin** | Aggregate (cached) | ✅ good / ✅ bad | — | Search rollups | N/A | 🟢 Low | |
| `/api/analytics/customers/` | GET | Customer insights (repeat rate, geo) | **Admin** | Aggregate (cached) | ✅ good / ✅ bad | — | rollups, UserGeo | N/A | 🟡 Medium | Aggregated, but small cohorts can re-identify individuals |
| `/api/analytics/anonymous/` | GET | Anonymous-traffic macro funnel | **Admin** | Aggregate (cached) | ✅ good / ✅ bad | — | AnonymousCounter rollups | N/A | 🟢 Low | Downstream of a spoofable counter — read accordingly |

---

## 12. Infrastructure / SEO — app: `spices_backend` (project root urls) + `products` (sitemap)

| URL | Method | What | Access | Complexity | Tests | Serializer | DB tables | Atomic | Risk | Notes |
|-----|--------|------|--------|-----------|-------|-----------|-----------|--------|------|-------|
| `/api/health/` | GET | Docker health check | Public | O(1) | — / — | — | (none) | N/A | 🟡 Medium | Static JSON, but the container's liveness verdict depends on it — and it never fails, so it can't detect a sick app |
| `/sitemap.xml` | GET | SEO sitemap | Public | O(n) (cached) | ✅ good / ✅ bad | — | Product, ProductCombo, Category | N/A | 🟡 Medium | SEO regression is slow and invisible; must not list inactive products. nginx-proxied to site root |
| `/robots.txt` | GET | SEO robots policy | Public | O(1) | ✅ good / ✅ bad | — | (none) | N/A | 🟠 High | A wrong line here can deindex the whole store, or invite crawlers into `/panel/`. Keeps private routes out |
| `/api/schema/`, `/api/docs/` | GET | drf-spectacular schema + Swagger UI | Public | O(1) | — / — | — | (introspection) | N/A | 🔴 Critical | Publishes the entire API surface if ever exposed — safe **only** because it is `DEBUG`-gated; verify that gate on every settings change |

---

## Cross-cutting notes for reviewers

- **Where the 🔴 rows cluster.** Risk is not spread evenly — it concentrates in four
  places, and a review with limited time should spend it here:
  1. **Auth** (`users`) — every password/OTP/token route. (The unused dj-rest-auth
     surface that used to sit alongside them at `api/auth/` was **unmounted
     2026-07-25**; the apps stay in `INSTALLED_APPS` for allauth, but no route
     reaches them.)
  2. **Money** (`orders` checkout + all four `payments` routes) — especially
     `/api/payments/webhook/`, the one public unauthenticated endpoint that settles funds,
     and `/api/orders/{id}/` PATCH, which can mark an unpaid order paid.
  3. **Bulk PII reads** (`admin_panel`) — `admin-search`, `admin-customers*`, and the
     customer CSV export; also `/api/orders/` GET, whose staff branch returns everyone.
  4. **Catalog-wide writes** — `bulk-products/apply/` and the variant routes, where one
     call can reprice or zero-stock the whole catalog with no undo.
- **Risk vs. test coverage is the sharpest signal in this file.** Rows that are 🔴/🟠
  *and* `— / —` or `✅ / —` are the review backlog. The 2026-07-25 pass cleared the top
  of it — `/api/auth/google/`, `/api/payment-account/`, `/api/product-variants/*` and
  `/api/product-images/` (POST) now have bad-path tests, and the dj-rest-auth routes are
  gone. **What remains:** `/api/product-images/{id}/` (CRUD, no tests),
  `/api/assistant/transcribe/`, `/api/geocode/reverse/`, `/api/geo/`, and the
  `✅ / —` rows in §4–§8 (`cart/clear`, `favorites/sync`, `set_default`, contact-detail
  routes).
- **Atomicity lives in a few hotspots.** The transactional writes worth reading
  closely: order checkout (`OrderViewSet.create`), order edit/cancel, all cart
  mutations, `bulk_products_apply`, and the payment capture path in
  `payments/services.py`. Everything else is a single implicit-atomic write.
- **Soft-delete is the norm** for products, combos, categories, sections, orders,
  payment methods, and receivable accounts — DELETE rarely removes a row. The
  nightly `purge_recycle_bin` job is the only hard-deleter.
- **Caching + language.** Storefront read endpoints cache per active language;
  a review of the cache keys should confirm `get_language()` is always in the key
  (it is, in products/categories/combos/sections/search).
- **Two dormant code paths** are routed nowhere but still present: `CartPaymentQRView`
  and `PolicyViewSet`. Confirm intent before relying on or deleting them.
- **Test suites by area:** `users/tests.py` + `test_google_login.py`,
  `products/tests.py` + `test_model_variants_and_sections.py` +
  `test_admin_and_seo.py` + `test_variant_image_badpaths.py`, `cart/tests.py`,
  `orders/tests.py` + `test_checkout_and_ops.py` + `test_concurrency.py`,
  `payments/test_razorpay_and_payment_flow.py`, `reviews/tests.py`,
  `admin_panel/tests.py` + `test_coupons.py` + `test_payment_account.py`,
  `support/tests.py`,
  `assistant/test_guardrails.py` + `test_chat_and_tools.py`, `analytics/tests.py` +
  `test_geoip.py`, plus `spices_backend/` (limits, abuse, middleware, throttles,
  validators). Run from `Backend/`: `venv/Scripts/python.exe -m pytest -q`.
