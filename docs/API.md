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
8. **Notes** — the one thing worth knowing before you read the code

> This file is hand-derived from the source (`*/views.py`, `*/urls.py`, `*/tests.py`)
> on 2026-07-23. The `urls.py` files remain the source of truth — if you add a route,
> add a row. For the auth-focused view, see [API_PERMISSIONS.md](API_PERMISSIONS.md).

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

| URL | Method | What | Access | Complexity | Tests | Serializer | DB tables | Atomic | Notes |
|-----|--------|------|--------|-----------|-------|-----------|-----------|--------|-------|
| `/api/auth/register/` | POST | Create a user | Public (throttle 3/min) | O(1) | ✅ good / ✅ bad | `UserRegistrationSerializer` → `UserSerializer` | User | No | SQLi/XSS/oversized/unicode all tested |
| `/api/auth/login/` | POST | Obtain JWT, set HttpOnly cookies | Public (throttle 5/min) | O(1) | ✅ good / ✅ bad | `CustomTokenObtainPairSerializer` | User | No | Tokens go to cookies only, never JSON body; case-insensitive email |
| `/api/auth/token/refresh/` | POST | Refresh access cookie | Public | O(1) | ✅ good / ✅ bad | SimpleJWT | (outstanding token) | No | Reads refresh from body or cookie |
| `/api/auth/profile/` | GET/PUT/PATCH | Read / update own profile | Auth | O(1) | ✅ good / ✅ bad | `UserSerializer` | User | No | `ensure_csrf_cookie`; email normalized; read-only fields enforced |
| `/api/auth/change-password/` | POST | Change password | Auth (UserRateThrottle) | O(1) | ✅ good / ✅ bad | — (raw fields) | User | No | Validates old pw + Django password validators |
| `/api/auth/password-reset-request/` | POST | Email a 6-digit OTP | Public (10/day) | O(1)+email | ✅ good / ✅ bad | `PasswordResetRequestSerializer` | User, PasswordResetOTP | No | Email sent on a background thread; generic 200 to prevent enumeration |
| `/api/auth/password-reset-verify/` | POST | Verify OTP, mint reset token | Public (10/day) | O(1) | ✅ good / ✅ bad | `OTPVerifySerializer` | User, PasswordResetOTP | No | OTP hashed at rest; failed-attempt lockout |
| `/api/auth/password-reset-confirm/` | POST | Set new password via reset token | Public (10/day) | O(1) | ✅ good / ✅ bad | `PasswordResetConfirmSerializer` | User, PasswordResetOTP | No | Single-use token; expiry enforced |
| `/api/auth/google/` | POST | Google id_token login/signup | Public (5/min) | External | — / — | `UserSerializer` (out) | User | No | Verifies token vs Google certs; case-insensitive account match |
| `/api/auth/…` (dj-rest-auth) | * | Stock dj-rest-auth + registration routes | Public | O(1) | — / — | dj-rest-auth | User | No | Included but the SPA uses the custom routes above |

---

## 2. Products, Categories, Combos, Sections, Variants — app: `products` — [products/views.py](../products/views.py)

Router basenames: `categories`, `products`, `combos`, `product-images`,
`product-variants`, `product-sections`. All use `IsAdminOrReadOnly` (public read,
staff write). List/retrieve for the storefront resources are **Redis-cached per
language** for non-staff.

| URL | Method | What | Access | Complexity | Tests | Serializer | DB tables | Atomic | Notes |
|-----|--------|------|--------|-----------|-------|-----------|-----------|--------|-------|
| `/api/categories/` | GET | List categories | Admin+RO/Public | Cached / Aggregate | ✅ good / ✅ bad | `CategorySerializer` | Category, Product (count) | N/A | Annotates active-product count |
| `/api/categories/` | POST | Create category | Admin | O(1) | ✅ good / ✅ bad | `CategorySerializer` | Category | No | Regular user + anon forbidden (tested) |
| `/api/categories/{slug}/` | GET | Category detail (slug or id) | Admin+RO/Public | O(1) | ✅ good / ✅ bad | `CategorySerializer` | Category | N/A | |
| `/api/categories/{slug}/` | PUT/PATCH/DELETE | Update / soft-delete | Admin | O(1) | ✅ good / ✅ bad | `CategorySerializer` | Category | No | DELETE = `is_active=False` (soft) |
| `/api/products/` | GET | List products (+filters, search, ordering) | Admin+RO/Public | Cached / Aggregate | ✅ good / ✅ bad | `ProductListSerializer` | Product, Category, Review, ProductVariant, ProductSection | N/A | `ProductFilter` matches canonical **and** extra categories; rating annotated |
| `/api/products/` | POST | Create product | Admin | O(1) | ✅ good / ✅ bad | `ProductDetailSerializer` | Product | No | Negative/zero price, discount>price, SQLi/XSS tested |
| `/api/products/{slug}/` | GET | Product detail (slug / id / variant-slug / retired-slug) | Admin+RO/Public | O(1) | ✅ good / ✅ bad | `ProductDetailSerializer` | Product, ProductVariant, ProductSlugAlias, images | N/A | 4-way slug resolution incl. `ProductSlugAlias` |
| `/api/products/{slug}/` | PUT/PATCH/DELETE | Update / soft-delete to Recycle Bin | Admin | O(1) | ✅ good / ✅ bad | `ProductDetailSerializer` | Product | No | DELETE stamps `deactivated_at` for purge job |
| `/api/products/sections/` | GET | Homepage sections w/ nested products+combos | Admin+RO/Public | Cached / O(n) | ✅ good / — | `HomepageSectionSerializer` | ProductSection, placements, Product, ProductCombo | N/A | Rich storefront payload |
| `/api/combos/` | GET | List combos | Admin+RO/Public | Cached / O(n) | ✅ good / ✅ bad | `ProductComboSerializer` | ProductCombo, ProductComboItem, Product, sections | N/A | |
| `/api/combos/` | POST | Create combo | Admin | O(1) | ✅ good / ✅ bad | `ProductComboSerializer` | ProductCombo, ProductComboItem | No | Negative price, discount>price, SQLi tested |
| `/api/combos/{slug}/` | GET | Combo detail (slug/id) | Admin+RO/Public | O(1) | ✅ good / ✅ bad | `ProductComboSerializer` | ProductCombo, ProductComboItem | N/A | |
| `/api/combos/{slug}/` | PUT/PATCH/DELETE | Update / soft-delete | Admin | O(1) | ✅ good / ✅ bad | `ProductComboSerializer` | ProductCombo | No | Soft-delete to Recycle Bin |
| `/api/product-images/` | GET/POST | List / upload product images | Admin+RO/Public | O(1) | — / — | `ProductImageSerializer` | ProductImage, Product | No | Multipart; Cloudinary storage |
| `/api/product-images/{id}/` | GET/PUT/PATCH/DELETE | Image CRUD | Admin | O(1) | — / — | `ProductImageSerializer` | ProductImage | No | |
| `/api/product-variants/` | GET/POST | List / create packaging sizes | Admin+RO/Public | O(1) | ✅ good / — | `ProductVariantWriteSerializer` | ProductVariant, Product | No | Ensures single default per product |
| `/api/product-variants/{id}/` | PUT/PATCH/DELETE | Variant CRUD | Admin | O(1) | ✅ good / — | `ProductVariantWriteSerializer` | ProductVariant | No | DELETE deactivates if referenced by an order (ProtectedError) |
| `/api/product-sections/` | GET/POST | Flat sections list / create | Admin+RO/Public | O(n) | ✅ good / ✅ bad | `ProductSectionSerializer` | ProductSection | No | Powers admin Sections page |
| `/api/product-sections/{id}/` | PUT/PATCH/DELETE | Section CRUD | Admin | O(1) | ✅ good / — | `ProductSectionSerializer` | ProductSection | No | DELETE soft-hides |
| `/api/product-sections/{id}/products/` | GET/PUT | Read / replace ordered product list | Admin+RO(GET)/Admin(PUT) | O(n) | ✅ good / ✅ bad | — (dict) | ProductSectionPlacement, Product | **Yes** (PUT) | PUT rebuilds placements atomically |
| `/api/spice-forms/` | GET | Enumerate spice-form choices | Public | O(1) | ✅ good / — | — | (none — choices) | N/A | Static enum |
| `/api/search/` | GET | Unified product+combo fuzzy search | Public | Heavy | ✅ good / ✅ bad | — | (in-memory corpus over Product/Combo/KB) | N/A | `q` length + `top_k`/`threshold` clamped; SQLi tested |
| `/api/search/suggest/` | GET | Autocomplete suggestions | Public (own throttle) | Cached / Heavy | ✅ good / ✅ bad | — | search corpus | N/A | <2 chars → empty |
| `/api/recommendations/` | GET | Personalized recommendations | Auth (401 for anon) | Heavy | — / — | — | UserEvent, Product | N/A | Cold-start → featured-popular fallback |

---

## 3. Bulk product tools — app: `products` — [products/bulk_views.py](../products/bulk_views.py)

All staff-only (`IsStaff`), read/write on **Product** only.

| URL | Method | What | Access | Complexity | Tests | Serializer | DB tables | Atomic | Notes |
|-----|--------|------|--------|-----------|-------|-----------|-----------|--------|-------|
| `/api/admin/bulk-products/` | GET | Flat editable product grid | Admin | O(n) | ✅ / — | — | Product, Category | N/A | Unpaginated whole catalog |
| `/api/admin/bulk-products/apply/` | POST | Apply price/stock changes, all-or-nothing | Admin | O(n) | ✅ good / ✅ bad | — | Product | **Yes** | Validates every row first; `select_for_update` on save |
| `/api/admin/bulk-products/import/` | POST | Validate a CSV, return **preview** (no save) | Admin | O(n) | ✅ good / ✅ bad | — | Product (read) | N/A | Name-matched; BOM-tolerant |
| `/api/admin/products-export/` | GET | Download catalog CSV | Admin | O(n) | ✅ / ✅ (staff) | — | Product, Category | N/A | |

---

## 4. Cart & Favorites — app: `cart` — [cart/views.py](../cart/views.py)

Router basenames `cart`, `favorites`; plus two `APIView`s. All `IsAuthenticated`.
Every mutation runs inside `transaction.atomic()` with `select_for_update` locks.

| URL | Method | What | Access | Complexity | Tests | Serializer | DB tables | Atomic | Notes |
|-----|--------|------|--------|-----------|-------|-----------|-----------|--------|-------|
| `/api/cart/` | GET | Get current cart | Auth | O(n) | ✅ good / ✅ bad | `CartResponseSerializer` | Cart, CartItem, Product, ProductVariant, ProductCombo | N/A | Cross-user isolation tested |
| `/api/cart/add_item/` | POST | Add product/combo line | Auth (CartWriteThrottle) | O(1) | ✅ good / ✅ bad | `CartResponseSerializer` | Cart, CartItem, Product, ProductVariant, ProductCombo | **Yes** | Stock + qty caps; SQLi, float/string qty tested |
| `/api/cart/update_item/` | POST | Change line qty (0 = remove) | Auth (throttle) | O(1) | ✅ good / ✅ bad | `CartResponseSerializer` | Cart, CartItem, Product, ProductVariant | **Yes** | Over-max qty flagged as abuse |
| `/api/cart/remove_item/` | POST/DELETE | Remove a line (composite key) | Auth (throttle) | O(1) | ✅ good / ✅ bad | `CartResponseSerializer` | Cart, CartItem | **Yes** | Accepts `"product-123"` / `"combo-4"` |
| `/api/cart/clear/` | POST | Empty the cart | Auth (throttle) | O(n) | ✅ / — | — | Cart, CartItem | **Yes** | |
| `/api/cart/sync/` | POST | Merge localStorage cart on login | Auth (throttle) | O(n) | ✅ good / ✅ bad | `CartResponseSerializer` | Cart, CartItem, Product, ProductVariant, ProductCombo | **Yes** | Validates ALL before clearing; payload size capped; returns `skipped[]` |
| `/api/auth/validate-coupon/` | POST | Validate coupon vs cart total | Auth | O(1) | ✅ good / ✅ bad | `ValidateCouponSerializer` | Coupon, Cart | N/A | Case-insensitive; honors min-order |
| `/api/favorites/` | GET | List favorites | Auth | O(n) | ✅ good / ✅ bad | `FavoriteItemSerializer` | Favorite, Product | N/A | |
| `/api/favorites/` | POST | Add favorite | Auth | O(1) | ✅ good / ✅ bad | — | Favorite, Product | No | `get_or_create` (idempotent) |
| `/api/favorites/{pk}/` | DELETE | Remove favorite | Auth | O(1) | ✅ good / ✅ bad | — | Favorite | No | Cross-user delete blocked (tested) |
| `/api/favorites/sync/` | POST | Bulk sync favorites | Auth | O(n) | ✅ / — | `FavoriteItemSerializer` | Favorite, Product | **Yes** | `bulk_create(ignore_conflicts=True)` |

> `CartPaymentQRView` exists in the file (UPI QR generation) but is **not routed** in
> the current `urls.py` — dead code path, worth flagging in review.

---

## 5. Orders — app: `orders` — [orders/views.py](../orders/views.py)

Router basename `orders`, `IsAuthenticated`. Customers see only their own
(non-deleted) orders; staff see all (paginated, with server-side filter/sort/search).
This is the **most complex** module — checkout does pricing, per-line tax, stock
reservation, coupon locking, and cart clearing in one transaction.

| URL | Method | What | Access | Complexity | Tests | Serializer | DB tables | Atomic | Notes |
|-----|--------|------|--------|-----------|-------|-----------|-----------|--------|-------|
| `/api/orders/` | GET | List orders (customer array / admin paginated + CSV) | Auth (admin sees all) | O(n)/Aggregate | ✅ good / ✅ bad | `OrderListSerializer` | Order, OrderItem, User, Payment | N/A | `?export=csv`, `?deleted=true`, admin filter/sort/search all DB-side |
| `/api/orders/` | POST | **Create order / checkout** | Auth (OrderRate + Daily throttle) | O(n) + locks | ✅ good / ✅ bad | `OrderCreateSerializer` → `OrderDetailSerializer` | Order, OrderItem, Cart, CartItem, Product, ProductVariant, ProductComboItem, Coupon, Payment | **Yes** | Locks Cart; supersedes stale ONLINE order; per-line proportional discount + GST; zero-total coupon path; low-stock/coupon alerts on commit |
| `/api/orders/{id}/` | GET | Order detail | Auth (owner/staff) | O(1) | ✅ good / ✅ bad | `OrderDetailSerializer` | Order, OrderItem, Payment | N/A | Other-user access 404s |
| `/api/orders/{id}/` | PUT/PATCH | Admin edit (status/tracking/address/payment_status) | **Admin only** | O(1) + locks | ✅ good / ✅ bad | `OrderDetailSerializer` | Order, Payment, Product, ProductVariant | **Yes** | Cancel-via-status restocks; only tracking-added emails the customer |
| `/api/orders/{id}/cancel/` | POST | Cancel + restock | Auth (owner/staff) | O(n) + locks | ✅ good / ✅ bad | `OrderDetailSerializer` | Order, Payment, Product, ProductVariant, ProductComboItem | **Yes** | Blocks self-cancel of a captured-payment order; canonical Order→Payment lock |
| `/api/orders/{id}/` | DELETE | Soft-delete to Recycle Bin | **Admin only** | O(1) | ✅ good / ✅ bad | — | Order | No | Never hard-deletes (financial record) |
| `/api/orders/{id}/restore/` | POST | Restore from Recycle Bin | **Admin only** | O(1) | ✅ good / ✅ bad | `OrderDetailSerializer` | Order | No | |
| `/api/orders/validate_coupon/` | POST | Preview coupon breakdown vs cart | Auth | O(n) | ✅ good / ✅ bad | — | Cart, CartItem, Coupon | N/A | Mirrors checkout math (tax/shipping) |
| `/api/orders/{id}/invoice/` | GET | PDF tax invoice | Auth (owner/staff) | Heavy | ✅ good / — | — (reportlab) | Order, OrderItem, User | N/A | 503 if reportlab missing |
| `/api/orders/{id}/packing-slip/` | GET | PDF packing slip (no prices) | **Staff only** | Heavy | ✅ good / ✅ bad | — (reportlab) | Order, OrderItem | N/A | Customer 403 (tested) |
| `/api/orders/{id}/delivery_bill/` | GET/POST/DELETE | Admin-private courier bill store | **Staff only** | O(1) | ✅ good / ✅ bad | — | Order (file field) | No | Magic-byte type check; 10 MB cap; streamed inline, never a public URL |

> **G4/G5 concurrency** (oversell + coupon over-redeem) are covered in
> [orders/test_concurrency.py](../orders/test_concurrency.py) — these pass on Postgres
> and fail on SQLite (documented). Checkout pricing/shipping/combo cases live in
> [orders/test_checkout_and_ops.py](../orders/test_checkout_and_ops.py).

---

## 6. Payments — app: `payments` — [payments/views.py](../payments/views.py) + [payments/urls.py](../payments/urls.py)

`PaymentMethodViewSet` (router `payment-methods`, saved instruments) is `IsAuthenticated`
per-user. The four Razorpay function endpoints live under `/api/payments/`.

| URL | Method | What | Access | Complexity | Tests | Serializer | DB tables | Atomic | Notes |
|-----|--------|------|--------|-----------|-------|-----------|-----------|--------|-------|
| `/api/payment-methods/` | GET/POST | List / add saved instrument | Auth | O(n)/O(1) | ✅ good / ✅ bad | `PaymentMethodSerializer` / `…CreateSerializer` | PaymentMethod | No | Per-user queryset; SQLi tested |
| `/api/payment-methods/{id}/` | GET/PUT/PATCH/DELETE | Instrument CRUD (soft delete) | Auth (owner) | O(1) | ✅ good / ✅ bad | `PaymentMethodSerializer` | PaymentMethod | No | Cross-user access blocked |
| `/api/payment-methods/{id}/set_default/` | POST | Mark default | Auth | O(n) | ✅ / — | `PaymentMethodSerializer` | PaymentMethod | No | Clears other defaults |
| `/api/payment-methods/default/` | GET | Get default | Auth | O(1) | ✅ good / ✅ bad | `PaymentMethodSerializer` | PaymentMethod | N/A | 404 when none |
| `/api/payment-methods/by_type/` | GET | Filter by UPI/CARD/… | Auth | O(n) | ✅ good / ✅ bad | `PaymentMethodSerializer` | PaymentMethod | N/A | Invalid/missing type 400 |
| `/api/payment-methods/stats/` | GET | Counts by type | Auth | Aggregate | ✅ / — | — | PaymentMethod | N/A | |
| `/api/payments/create-order/` | POST | Create/reuse Razorpay order for an Order | Auth (PaymentRateThrottle) | External + locks | ✅ good / ✅ bad | `CreateOrderSerializer` | Order, Payment | **Yes** | Amount computed server-side; idempotent (one live order); supersede recorded |
| `/api/payments/verify/` | POST | L1 browser signature verify → capture | Auth (throttle) | External + locks | ✅ good / ✅ bad | `VerifyPaymentSerializer` | Payment, Order (+ Cart on capture) | **Yes** (in `services`) | Honest "cancelled" response after capture-after-cancel |
| `/api/payments/webhook/` | POST | L2 Razorpay webhook (source of truth) | **Public**, signature-gated (`@csrf_exempt`) | External + locks | ✅ good / ✅ bad | — (raw body) | Payment, Order, PaymentEvent | **Yes** (in `services`) | HMAC over raw body; **fail-closed if `RAZORPAY_WEBHOOK_SECRET` unset**; unknown events ACK 200; orphans logged |
| `/api/payments/status/` | GET | Non-alarming payment state for polling | Auth (owner) | O(1) | ✅ good / — | — | Order, Payment | N/A | "Confirming…" during the verify/webhook gap |

> Capture/verify/webhook idempotency, L1/L2 race, double-capture, refund, and
> instrument-detail capture are all covered in
> [payments/test_razorpay_and_payment_flow.py](../payments/test_razorpay_and_payment_flow.py).
> Note: the shared atomicity lives in `payments/services.py` (`mark_payment_*`), not
> the view — review that file alongside these endpoints.

---

## 7. Reviews — app: `reviews` — [reviews/views.py](../reviews/views.py)

Router basename `reviews`, `IsAuthenticatedOrReadOnly`. Verified-purchase gated;
staff moderation via `is_hidden`.

| URL | Method | What | Access | Complexity | Tests | Serializer | DB tables | Atomic | Notes |
|-----|--------|------|--------|-----------|-------|-----------|-----------|--------|-------|
| `/api/reviews/` | GET | List reviews (filter by product/combo) | Auth+RO/Public | O(n) | ✅ good / ✅ bad | `ReviewSerializer` | Review, User, Product, ProductCombo | N/A | Hidden reviews visible only to staff + author |
| `/api/reviews/` | POST | Create review | Auth | O(1) | ✅ good / ✅ bad | `ReviewSerializer` | Review, OrderItem, Order | No | Enforces verified purchase + no duplicate |
| `/api/reviews/{id}/` | GET | Review detail | Auth+RO/Public | O(1) | ✅ / — | `ReviewSerializer` | Review | N/A | |
| `/api/reviews/{id}/` | PUT/PATCH | Edit own review | Auth (owner) | O(1) | ✅ good / ✅ bad | `ReviewSerializer` | Review | No | Cannot re-point to another item (anti-fraud) |
| `/api/reviews/{id}/` | DELETE | Delete own review | Auth (owner/staff) | O(1) | ✅ / — | — | Review | No | Non-owner queryset excluded |
| `/api/reviews/can-review/` | GET | May the user review X? (UX hint) | Auth | O(1) | ✅ good / ✅ bad | — | Review, OrderItem | N/A | Exactly one of product/combo |
| `/api/reviews/{id}/set-hidden/` | POST | Moderate (hide/show) | **Staff only** | O(1) | ✅ good / ✅ bad | — | Review | No | Non-staff 403 |

---

## 8. Admin panel — app: `admin_panel` — [admin_panel/views.py](../admin_panel/views.py)

| URL | Method | What | Access | Complexity | Tests | Serializer | DB tables | Atomic | Notes |
|-----|--------|------|--------|-----------|-------|-----------|-----------|--------|-------|
| `/api/receivable-accounts/` | GET/POST/…/DELETE | Payment-collection accounts CRUD | **Admin** | O(1) | ✅ / ✅ | `ReceivableAccountSerializer` | ReceivableAccount | No | Sensitive — admin only |
| `/api/payment-account/` | GET | Default UPI account for checkout | Auth | O(1) | — / — | — | ReceivableAccount | N/A | Safe subset of fields |
| `/api/coupons/` | GET/POST | List / create coupons | **Admin** | O(n) | ✅ good / ✅ bad | `CouponSerializer` | Coupon | No | Unpaginated; dup code / >100% / negative tested |
| `/api/coupons/{id}/` | GET/PUT/PATCH/DELETE | Coupon CRUD | **Admin** | O(1) | ✅ good / ✅ bad | `CouponSerializer` | Coupon | No | |
| `/api/coupons/validate/` | POST | Admin structural coupon check | **Admin** | O(1) | ✅ good / ✅ bad | `CouponSerializer` | Coupon | N/A | Ignores per-cart concerns by design |
| `/api/dashboard/` | GET | Sales/counts summary | **Admin** | Aggregate (cached 2m) | ✅ good / ✅ bad | `RecentOrderSerializer` | Order, Product, ProductCombo, Coupon | N/A | Redis-cached |
| `/api/dashboard/actions/` | GET | "Today" action inbox | **Admin** | Aggregate (cached 60s) | ✅ good / ✅ bad | — | Order, Product, AssistantConversation | N/A | Confirmable/ship/low-stock/stuck-payment counts |
| `/api/dashboard/send-report/` | POST | Trigger daily/weekly email now | **Admin** | External (email) | ✅ good / ✅ bad | — | (rollups) | N/A | `{type: daily\|weekly}` |
| `/api/admin-search/` | GET | Global search (orders/products/customers/coupons) | **Admin** | O(n) | ✅ good / ✅ bad | — | Order, Product, User, Coupon | N/A | Capped per group; digit-search hits order id |
| `/api/admin-customers/` | GET | Customer directory (paginated, search) | **Admin** | Aggregate | ✅ good / ✅ bad | `AdminCustomerListSerializer` | User, Order | N/A | Order count + total spent annotated |
| `/api/admin-customers/{id}/` | GET | Customer detail + order history | **Admin** | O(n) | ✅ good / — | `AdminCustomer*Serializer` | User, Order | N/A | Last 50 orders |
| `/api/admin-customers/export/` | GET | Customer CSV | **Admin** | O(n) | ✅ / — | — | User, Order | N/A | Formula-injection escaped (tested) |

> `PolicyViewSet` exists (`IsReadOnlyOrAdmin`) with full retire/create logic and
> tests, but **is not registered** in the current router — the storefront serves
> static policy pages. Flag as intentionally-dormant code when reviewing.

---

## 9. Support (contact) — app: `support` — [support/views.py](../support/views.py)

| URL | Method | What | Access | Complexity | Tests | Serializer | DB tables | Atomic | Notes |
|-----|--------|------|--------|-----------|-------|-----------|-----------|--------|-------|
| `/api/contact/` | POST | Submit contact form | **Public** (5/hr throttle) | O(1) | ✅ good / ✅ bad | `ContactSubmissionSerializer` | ContactSubmission, User | No | XSS/SQLi/oversized tested |
| `/api/contact/` | GET | List submissions | **Admin** | O(n) | ✅ good / ✅ bad | `ContactSubmissionAdminSerializer` | ContactSubmission | N/A | Unpaginated inbox; regular user 403 |
| `/api/contact/{id}/` | GET/PUT/DELETE | Submission detail/admin edit | **Admin** | O(1) | — / — | `ContactSubmissionAdminSerializer` | ContactSubmission | No | |
| `/api/contact/{id}/mark_read/` | POST | Mark read | **Admin** | O(1) | — / — | — | ContactSubmission | No | |
| `/api/contact/{id}/reply/` | POST | Mark replied + notes | **Admin** | O(1) | — / — | — | ContactSubmission | No | Notes sanitized (`strip_tags`+`escape`) |

---

## 10. Assistant (unified AI chat + support) — app: `assistant` — [assistant/views.py](../assistant/views.py)

Login-only by design (see the `assistant-login-only` memory). Customer chat runs a
tool-calling agent; a separate admin persona reads business data.

| URL | Method | What | Access | Complexity | Tests | Serializer | DB tables | Atomic | Notes |
|-----|--------|------|--------|-----------|-------|-----------|-----------|--------|-------|
| `/api/assistant/chat/` | POST | Send message, AI replies (tool agent) | Auth (Burst+Daily throttle) | External (LLM) | ✅ good / ✅ bad | `AssistantChatRequestSerializer` | AssistantConversation, AssistantMessage (+tools read catalog/orders) | No | User injected by view (G1); escalation flag; auto-title first turn |
| `/api/assistant/admin-chat/` | POST | Store-owner Q&A over business data | **Admin** | External (LLM) | ✅ good / ✅ bad | — | (read-only reporting tools) | N/A | Stateless; `persona='admin'`; no action tools |
| `/api/assistant/transcribe/` | POST | Voice → text (whisper.cpp) | Auth (throttle) | External (whisper) | — / — | — | (none — persists nothing) | N/A | Gated by `USE_SELF_HOSTED_STT`; 8 MB cap |
| `/api/assistant/conversations/` | GET/POST | List own threads / create thread | Auth | O(n)/O(1) | ✅ good / ✅ bad | `ConversationSummarySerializer` | AssistantConversation, AssistantMessage | No | Last-message annotated (no N+1) |
| `/api/assistant/conversations/{uuid}/messages/` | GET | Full message history | Auth (owner/staff) | O(n) | ✅ good / ✅ bad | `MessageSerializer` | AssistantConversation, AssistantMessage | N/A | Excludes tool/system roles |
| `/api/assistant/conversations/admin/` | GET | Admin: list all threads (filters) | **Admin** | O(n) | ✅ good / ✅ bad | `ConversationSummarySerializer` | AssistantConversation | N/A | `needs_human`/`status`/`user_id` filters |
| `/api/assistant/conversations/{uuid}/admin-reply/` | POST | Admin: reply into a thread | **Admin** | O(1) | ✅ good / ✅ bad | `AdminReplySerializer` | AssistantConversation, AssistantMessage | No | Clears `needs_human` |
| `/api/assistant/conversations/{uuid}/` | PATCH | Admin: update status/assigned_to | **Admin** | O(1) | ✅ good / ✅ bad | `ConversationPatchSerializer` | AssistantConversation | No | Static `admin/` route declared before `<uuid>` so it isn't shadowed |

> Extensive guardrail tests (prompt injection, cross-user isolation, tool allowlist,
> escalation, degrade-without-LLM) in
> [assistant/test_guardrails.py](../assistant/test_guardrails.py) and
> [assistant/test_chat_and_tools.py](../assistant/test_chat_and_tools.py).

---

## 11. Analytics & Location — app: `analytics` — [analytics/views.py](../analytics/views.py) + [analytics/insights_views.py](../analytics/insights_views.py)

| URL | Method | What | Access | Complexity | Tests | Serializer | DB tables | Atomic | Notes |
|-----|--------|------|--------|-----------|-------|-----------|-----------|--------|-------|
| `/api/events/` | POST | Ingest behavioral event(s) | Auth (throttle) | O(n) | ✅ good / ✅ bad | `UserEventSerializer` | UserEvent | No | Batch; invalid items skipped not failed; `bulk_create` |
| `/api/anon-events/` | POST | Anonymous aggregate counter | **Public**, no auth/CSRF | O(1) | ✅ good / ✅ bad | — | AnonymousCounter (aggregate) | No | Always 204; identity-free by design |
| `/api/geocode/reverse/` | GET | Reverse-geocode via Nominatim (proxied) | Auth (throttle) | External (cached 30d) | — / — | — | (Redis cache only) | N/A | Server-side User-Agent; coords rounded for cache key |
| `/api/geo/` | GET/PUT | Read / upsert coarse user location | Auth | O(1) | — / — | `UserGeoSerializer` | UserGeo | No | Coords rounded before storage |
| `/api/analytics/overview/` | GET | KPI overview | **Admin** | Aggregate (cached) | ✅ good / ✅ bad | — | Sales/behavioral rollups | N/A | Reads pre-computed rollups |
| `/api/analytics/sales/` | GET | Sales series + KPIs | **Admin** | Aggregate (cached) | ✅ good / ✅ bad | — | Sales rollups | N/A | `?from&to&granularity` |
| `/api/analytics/funnel/` | GET | Conversion funnel | **Admin** | Aggregate (cached) | ✅ good / ✅ bad | — | Behavioral rollups | N/A | |
| `/api/analytics/search/` | GET | Search insights | **Admin** | Aggregate (cached) | ✅ good / ✅ bad | — | Search rollups | N/A | |
| `/api/analytics/customers/` | GET | Customer insights (repeat rate, geo) | **Admin** | Aggregate (cached) | ✅ good / ✅ bad | — | rollups, UserGeo | N/A | |
| `/api/analytics/anonymous/` | GET | Anonymous-traffic macro funnel | **Admin** | Aggregate (cached) | ✅ good / ✅ bad | — | AnonymousCounter rollups | N/A | |

---

## 12. Infrastructure / SEO — app: `spices_backend` (project root urls) + `products` (sitemap)

| URL | Method | What | Access | Complexity | Tests | Serializer | DB tables | Atomic | Notes |
|-----|--------|------|--------|-----------|-------|-----------|-----------|--------|-------|
| `/api/health/` | GET | Docker health check | Public | O(1) | — / — | — | (none) | N/A | Static JSON |
| `/sitemap.xml` | GET | SEO sitemap | Public | O(n) (cached) | ✅ good / ✅ bad | — | Product, ProductCombo, Category | N/A | nginx-proxied to site root |
| `/robots.txt` | GET | SEO robots policy | Public | O(1) | ✅ good / ✅ bad | — | (none) | N/A | Keeps private routes out |
| `/api/schema/`, `/api/docs/` | GET | drf-spectacular schema + Swagger UI | Public | O(1) | — / — | — | (introspection) | N/A | **DEBUG-only** |

---

## Cross-cutting notes for reviewers

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
- **Test suites by area:** `users/tests.py`, `products/tests.py` +
  `test_model_variants_and_sections.py` + `test_admin_and_seo.py`, `cart/tests.py`,
  `orders/tests.py` + `test_checkout_and_ops.py` + `test_concurrency.py`,
  `payments/test_razorpay_and_payment_flow.py`, `reviews/tests.py`,
  `admin_panel/tests.py` + `test_coupons.py`, `support/tests.py`,
  `assistant/test_guardrails.py` + `test_chat_and_tools.py`, `analytics/tests.py` +
  `test_geoip.py`, plus `spices_backend/` (limits, abuse, middleware, throttles,
  validators). Run from `Backend/`: `venv/Scripts/python.exe -m pytest -q`.
