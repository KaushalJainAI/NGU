# NGU Platform Quality Playbook — UX, Robustness & Security

**Purpose:** a practical, repeatable way to answer three questions before and
during running the business on this platform:

1. **Customer UX** — will a shopper reach "order placed" without confusion, dead
   ends, or broken promises?
2. **Admin UX** — can the operator run day-to-day work (orders, stock, payments,
   coupons) quickly and without foot-guns?
3. **Backend robustness & security** — will the API stay correct and stand up
   under real, hostile, and edge-case traffic without breaking (500s), leaking
   data, or losing money?

This is not a one-off audit. It is the checklist you re-run each release. §6
lists the **concrete issues found today** (2026-07-10), prioritized.

---

## 1. How to know the *customer* UX is good

UX quality is verified against **journeys**, not pages. For each journey, prove
the happy path *and* every "unhappy" branch renders a clear state.

### 1.1 The journeys that must never break
| Journey | Must prove |
|---------|-----------|
| Browse → product detail → add to cart | price, weight, stock, images correct; out-of-stock disables add |
| Cart → change qty / remove → checkout | totals recompute; qty bounded (1..`MAX_ITEM_QUANTITY`); empty cart redirects |
| Checkout → pay → confirmation | address validation, coupon apply/remove, **the amount shown = the amount charged = the order's real total**, a real confirmation with the order number + next step |
| My Orders → view → **download invoice** → cancel | list is user-scoped, invoice PDF downloads, cancel restores stock and is reflected immediately |
| Track order | entering an order id shows that order's **real** status |
| Login / register / forgot-password | truthful errors, no enumeration, lockout messaging |
| Search / autocomplete | relevant results, graceful empty state, oversized/garbage query handled |

### 1.2 The four states every screen owes the user
For every data-driven screen, verify all four exist and look intentional:
- **Loading** (skeleton/spinner, no layout jump),
- **Empty** (explains what to do next, not a blank box),
- **Error** (a human sentence + a retry/next action, never a raw stack or silent failure),
- **Success/normal**.

A screen that only handles "success" is a latent bug. Grep for API calls whose
`catch` only `console.error`s with no user-visible feedback.

### 1.3 Truthfulness (the cheapest way to lose trust)
Every promise in copy must be backed by a real mechanism:
- "confirmation email" → an email is actually sent.
- "real-time order updates" → status is actually fetched.
- "we will verify your payment" → an admin can actually see and verify it.

**Verification method:** for each user-facing sentence that asserts a system
behavior, trace it to the code that performs it. No code → fix the code or the
copy. (§6 has three live examples.)

### 1.4 Reach & performance
- **Mobile-first:** every journey on a 360px viewport; tap targets ≥ 40px; no
  horizontal scroll; sticky bottom bars don't cover the primary button.
- **Accessibility:** keyboard-only pass through checkout; labels tied to inputs;
  visible focus; color contrast AA; images have `alt`.
- **Performance budget:** first meaningful paint < 2.5s on a mid phone / 4G;
  images sized/lazy-loaded; no layout shift on load.
- **i18n:** switching language doesn't break layout or leave untranslated keys.

### 1.5 How to actually run these checks
- **Automated E2E** already exists (`testing/e2e/`, black-box HTTP) — extend it
  per journey. Keep the Playwright storefront walkthrough (`testing/ui/`) current.
- **Manual device pass** on real Android + iOS Safari before each release.
- **Lighthouse** (performance/a11y/best-practices) per key page; treat scores as
  a budget, not a vanity metric.

---

## 2. How to know the *admin* UX is good

The operator's time is the business's cost. Optimize for "few clicks, no fear."

### 2.1 Principles
- **Every action is reversible or confirmed.** Destructive actions (cancel,
  delete, price change) ask once and show the consequence ("this restocks N
  units").
- **One source of truth.** Filtering/sorting/searching must run over the **whole
  dataset server-side**, not the current page — otherwise the admin makes
  decisions on partial data.
- **State machines, not free text.** Order status transitions should be
  constrained (you can't move `delivered → pending`), and every transition must
  have consistent side effects (see §6, the two-cancel-paths bug).
- **The admin can see and act on everything the business needs**, especially
  **payment status** for a manual-UPI flow.
- **Bulk operations** for anything done more than ~10×/day (status updates, stock).

### 2.2 Verification checklist
- Can the admin find *any* order by id/customer/status across all pages?
- Does every status change do the right thing to **stock** and **payment**?
- Are money values ever computed in the browser for decisions? (They shouldn't be.)
- Does a failed save show why, and leave the form recoverable?
- Are admin endpoints rejected for non-staff? (Least privilege — already tested.)

---

## 3. How to know the backend *won't break*

"Won't break" = **no 500 on any input, no lost or double-counted money, no
oversell, no data served to the wrong user, no unbounded work.**

### 3.1 Boundedness (already implemented — keep it enforced)
Every externally-influenced value is bounded and clamped, returning **400, never
500**, on out-of-range input: item qty, cart size, sync size, order total,
review length, search length/`top_k`/threshold (`spices_backend/limits.py`,
mirrored in `Frontend/.../config/limits.ts`). Rule: **a new input field is not
"done" until it has a documented bound and a test that a huge/negative/garbage
value yields 400.**

### 3.2 Concurrency & money correctness
- **No oversell:** stock decrements happen under `select_for_update` and are
  re-checked against the locked row (G4). Keep the two-thread race tests green.
- **No coupon over-redemption:** usage counted under a row lock (G5).
- **Totals reconcile:** header tax = sum of line taxes; per-item discounts sum to
  the order discount. Any new pricing rule needs an exact-money test
  (`orders/test_pricing_math.py` is the pattern).
- **Cancel is symmetric with create:** whatever create decremented, cancel
  restores — *for every path that cancels* (see §6).

### 3.3 Idempotency & payment integrity
- Order placement and payment confirmation must be **idempotent** — a double
  submit or a retry must not create two orders or double-decrement stock.
- **Never trust the client for "paid."** Payment state must be established by a
  server-side signal (gateway webhook/signature, or an explicit admin
  verification for manual UPI) — not a self-checked box.

### 3.4 Failure isolation
- External deps (Cloudinary, Redis, LLM, whisper, geocode, email) must **fail
  soft**: a down dependency degrades one feature, it does not 500 the request or
  the app. (Abuse middleware already fails open; keep that discipline.)
- Every outbound call has a **timeout** and a fallback.

### 3.5 Abuse resistance (already implemented — keep it)
Rate limits on login/register/order/cart/assistant; abuse strike-counting +
manual IP ban (`spices_backend/abuse.py`, `throttles.py`, `abuse_ban`
command). Rule: any new expensive or writing endpoint gets a throttle scope.

### 3.6 Observability (the difference between "broke" and "broke silently")
- Structured logs with request id; error rate + p95 latency per endpoint;
  alert on 5xx spikes and on abuse-strike spikes.
- A synthetic "canary" that runs the core journey against prod every few minutes.

### 3.7 How to actually run these checks
- **The test pyramid is the spec.** Current baseline: **Django suite 529 passed
  / 8 skipped** (Postgres) + **e2e/security 74 passed / 3 skipped**. Run
  `testing/tools/run_full_audit.py` before every deploy; a red run blocks
  release.
- **Fault injection:** periodically run with Redis/Cloudinary/LLM unreachable and
  confirm graceful degradation (no 500).
- **Load smoke:** hit the catalog, search, and order endpoints at 5–10× normal
  concurrency and watch for 500s, lock timeouts, and p95 blowups.

---

## 4. How to ensure security

Verify these classes explicitly; most already have adversarial tests in
`testing/security/` — keep them green and extend per feature.

| Class | What to verify | Status here |
|-------|----------------|-------------|
| **AuthN** | httpOnly cookie JWT, CSRF on unsafe methods, no tokens in localStorage | ✅ cookie-based (admin + storefront) |
| **AuthZ / BOLA** | user A can never read/act on user B's cart/order/invoice; admin-only endpoints reject non-staff | ✅ tested (incl. invoice BOLA) |
| **Input validation** | bounded + typed; SQLi/XSS payloads neither 500 nor reflect | ✅ tested |
| **Error hygiene** | no stack traces, driver names, or `str(e)` leaked to clients; DEBUG off in prod | ✅ tested |
| **Secrets** | only via env; none committed; rotate on exposure | audit each release |
| **Transport** | HTTPS everywhere; secure cookies in prod; HSTS; `server_tokens off` | ✅ (F-2 fixed) |
| **Payment integrity** | server establishes "paid"; amount charged == server total | ⚠️ see §6 (self-attested) |
| **Dependencies** | scan for CVEs (`pip-audit`, `npm audit`) each release | add to CI |
| **PII / logs** | don't log OTPs, tokens, full addresses; coarse geo only | ✅ geo rounded server-side |
| **Rate limit / abuse** | brute-force + flood protection with tracking & manual ban | ✅ implemented |

**Method:** treat `testing/security/` as living coverage. Every new endpoint gets
(1) an auth test, (2) a BOLA test if it touches user-owned data, (3) a
bounds/injection test if it takes input.

---

## 5. Release gate (run this every deploy)

1. `run_full_audit.py` green (unit+integration+e2e+security).
2. `pip-audit` / `npm audit` — no high/critical.
3. Manual journey pass on a real phone: browse → checkout → order → invoice →
   cancel; admin: find order → change status → verify stock & payment.
4. Fault drill (optional but recommended): kill Redis/LLM, confirm no 500.
5. Copy-truth check: any new user-facing promise is backed by real code.
6. Canary/synthetic monitor green post-deploy.

---

## 6. Issues found today (2026-07-10) — prioritized

Evidence is cited by file. Severity: **P0** = breaks money/trust or blocks a core
journey; **P1** = significant UX/ops gap; **P2** = cleanup/maintainability.

### P0 — Payment is self-attested; stock is committed to unpaid orders
- **What:** checkout places the order with `payment_method: 'ONLINE'` after the
  user ticks *"I have completed the payment"* — there is **no verification** of
  the UPI transfer (`Frontend/.../pages/Billing.tsx:319`, `:342`). Order creation
  **immediately decrements stock** (`Backend/orders/views.py` create path).
- **Impact:** anyone can place unlimited "paid" orders without paying, exhausting
  inventory and locking out real buyers; the business can't tell paid from
  unpaid because **`payment_status` is not exposed or editable in the admin**
  (`OrderDetailSerializer` omits it; `Admin Panel/.../pages/Orders.tsx` has no
  payment control).
- **Fix direction:** (a) surface & control `payment_status` in admin with an
  explicit "Verify payment" action; (b) consider not decrementing stock (or
  holding a short reservation) until payment is verified for manual-UPI orders;
  (c) show the customer their real order number + pending-verification state.

### P0 — Two different "cancel" paths, only one restocks
- **What:** the admin status dropdown → **"cancelled"** calls
  `updateOrder` = `PATCH /orders/{id}/ {status}` (`Admin Panel/.../api/orders.ts:54`),
  which just sets the field. The **Trash button** calls the `cancel` action
  (`orders/views.py:508`) which restores stock. Setting status to *cancelled* via
  the dropdown therefore **cancels without restocking** → permanent inventory
  drift.
- **Fix direction:** route all cancellations through the stock-restoring path;
  constrain status transitions server-side (reject arbitrary PATCH to
  `cancelled`/`delivered`), i.e. a real state machine.

### P1 — "Track Order" is non-functional
- **What:** `TrackOrder.tsx` `handleSubmit` does nothing (`// Track order logic
  here`, `:23`); the journey is a hardcoded `activeIndex = 2` "In Transit"
  illustration (`:33`) regardless of the real order.
- **Impact:** a customer entering their order id gets a fake status — directly
  contradicts the "Real-time order updates" banner (`:45`).
- **Fix direction:** fetch the order and render its real status, or remove the
  page and point customers to **My Orders** (which is real).

### P1 — Broken promise: "confirmation email" that is never sent
- **What:** the only emails the backend sends are password-reset OTPs
  (`Backend/users/views.py`). No order-confirmation email exists. Yet TrackOrder
  tells users "You can find your order ID in the confirmation email"
  (`TrackOrder.tsx:91`), and checkout says "We will verify your payment soon"
  (`Billing.tsx:349`).
- **Fix direction:** send an order-confirmation email (with order number + the
  existing PDF invoice), or change the copy to match reality (My Orders).

### P1 — Post-order redirect frames a purchase as "interest"
- **What:** after placing an order, checkout navigates to `/interest-success`
  ("Thank you for showing interest in our products!", `InterestSuccess.tsx`)
  rather than an order confirmation showing the **order number** and a link to
  **My Orders / invoice**. `/order-success` exists but is bypassed
  (`Billing.tsx:351`).
- **Impact:** the highest-intent moment gives no order reference and confusing
  wording.
- **Fix direction:** show a real confirmation with order number, status, and an
  invoice link.

### P1 — Checkout total (and the amount the user pays) can under-quote tax
- **What:** Billing computes tax client-side as `item.price*qty*((tax_rate ?? 0)
  /100)` (`Billing.tsx:111`). When a line lacks `tax_rate` the client uses **0**,
  but the backend uses `DEFAULT_TAX_RATE = 5` (`spices_backend/limits.py`). The
  UPI **QR is generated for the client-computed total** (`:126`), so the customer
  can be shown/charged **less than the order's real `total_amount`**.
- **Fix direction:** don't compute payable totals in the browser — fetch the
  authoritative total from the backend (a "quote" endpoint) and generate the QR
  from that.

### P1 — Admin order filters/sort run on one page only
- **What:** `Orders.tsx` fetches a single (paginated) response and filters/sorts
  in the browser (`applyFilters`, `:63`). Filters therefore apply only to the
  current page.
- **Impact:** "no cancelled orders" can be false; amount filters/sorts are
  wrong once there is more than one page. Doesn't scale for a live business.
- **Fix direction:** push status/amount/sort/search to server-side query params
  with pagination.

### P2 — Dead, stale checkout file
- **What:** `Frontend/.../pages/Checkout.tsx` is 226 lines, **entirely commented
  out**, not routed (the live page is `Billing.tsx` at `/billing`), and its
  comments hardcode the **old** shipping (₹50 / threshold 500) — now ₹69.
- **Fix direction:** delete it to avoid confusion.

---

### Suggested order of work
1. Payment verification + stock-commit policy (P0) and the cancel/restock
   unification + status state-machine (P0) — these protect money and inventory.
2. Confirmation email + real order-success page + Track Order (P1 cluster) —
   these are the trust/clarity wins on the core journey.
3. Server-side admin filtering and the client-tax fix (P1).
4. Delete dead code (P2).

Each fix should land with a test at the matching layer (unit for money/state,
e2e for the journey, security for any new endpoint), per §§1–5.
