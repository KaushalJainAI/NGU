# Payment Gateway Integration Plan — Razorpay + Zero-Total Coupons

**Project:** NGU (Nidhi Masala) backend
**Scope:** Razorpay online payments + zero-total (full-coupon) checkout. Stripe stays modeled but unwired.
**Status:** Plan only — no code written yet.
**Author:** Claude
**Date:** 2026-06-19 (failure-mode review pass: 2026-07-10 — added §7.2 lock-ordering, §7.7–7.9, cancel/refund interaction, disaster recovery)
(payment-policy pass: 2026-07-10 — COD/manual-UPI removed from self-serve checkout; added §14 Coupons; §15 admin QR page)

> ### Payment policy (current product decision — supersedes older COD/manual-UPI wording below)
> Self-serve checkout offers exactly two outcomes:
> 1. **Razorpay** for any order with a payable total (still deferred — this plan), or
> 2. A **zero-total order** — a coupon (see §14) that brings the total to **₹0**, placed
>    directly as `payment_status='paid'` with **no gateway call** (shipping + tax waived).
>
> **COD is not offered self-serve.** Customers who want Cash on Delivery are told to
> **contact the store directly**. The **manual UPI-QR checkout flow is retired from
> checkout**; the admin-entered static QR (`ReceivableAccount`) survives only as a
> standalone "manual payment" page (see §15). Sections below that describe COD or manual
> UPI as *live checkout paths* are historical — read them through this policy.

---

## 1. Where we stand today

Already in place (no work needed):

| Item | Location |
|------|----------|
| `razorpay==2.0.0` + `stripe==13.2.0` pinned | `requirements.txt:24-25` |
| `RAZORPAY_KEY_ID` / `RAZORPAY_KEY_SECRET` config stubs | `spices_backend/settings.py:372-373` |
| `Payment` model (one-to-one with `Order`, `stripe`/`razorpay`/`cod` gateways, `transaction_details` JSON, `unique` `payment_id`) | `payments/models.py:7` |
| `PaymentMethod` model (saved UPI/card/netbanking/wallet, only last-4 + token stored) | `payments/models.py:34` |
| `Order` model with `payment_method` (`COD`/`ONLINE`/`razorpay`) + `payment_status` | `orders/models.py:8` |
| Order creation w/ cart→order, stock decrement, coupon, atomic txn | `orders/views.py:138` |

**The gap:** `payments/views.py` only does CRUD on saved `PaymentMethod`s. There is:
- ❌ No endpoint to create a Razorpay order
- ❌ No signature verification
- ❌ No webhook handler
- ❌ No link between a placed `Order` and an actual paid transaction

So checkout → paid does not exist yet. The `Payment` row is never created.

---

## 1b. System-fit reconciliation (verified against the codebase — read first)

Four things about *this* codebase change how the plan must be built. These are verified, not assumed.

1. **Order-level `payment_method` is `{'COD','ONLINE'}` only — there is no `'razorpay'` choice.**
   `OrderCreateSerializer.payment_method` (`orders/serializers.py:9`) is `ChoiceField(choices=['COD','ONLINE'])`.
   The model's `PAYMENT_METHOD_CHOICES` (`orders/models.py:20`) *also* lists `stripe`/`razorpay`, but the create API can't set them.
   → **Decision:** keep the gateway distinction on the **`Payment`** model (`payment_gateway='razorpay'`). The **`Order`** stays `payment_method='ONLINE'` for all gateway payments. Every place this plan said "order with `payment_method='razorpay'`" means **`payment_method='ONLINE'` + `Payment.payment_gateway='razorpay'`**. No serializer change needed.

2. **`Order.payment_status` is a free-text `CharField`, default `'pending'`, with no `choices`** (`orders/models.py:37`). Only `'pending'` is currently used; the frontend/assistant reads it (`assistant/tools.py:169`).
   → **Decision:** define and standardise the vocabulary now: **`pending` → `paid` → `failed` → `refunded`**. Recommend adding `choices` + a one-line migration so values can't drift. The plan's `'paid'`/`'failed'` are *new* values this work introduces.

3. **Celery is a dependency but is NOT operationally wired.** `celery==5.5.3` is installed and `settings.py:506-511` has serializer config, but **`CELERY_BROKER_URL`/`RESULT_BACKEND` are commented out**, there is **no `spices_backend/celery.py` app module**, and no worker/beat runs. Redis *is* available (`django_redis`).
   → **Decision:** the L3 reconciliation job (§7) has a **prerequisite**: either (a) stand up Celery — add `celery.py`, uncomment the Redis broker, run a worker + `celery beat`; or (b) ship L3 as a **Django management command** (`python manage.py reconcile_payments`) driven by an external scheduler (Windows Task Scheduler in dev / cron in prod). **(b) is the lower-risk start** and needs no new infra. Pick one before building §7.4/§8 step 8.

4. **A manual UPI collection flow already exists and is live** — `ReceivableAccount` (`admin_panel/models.py:6`) + `PaymentAccountView` (`admin_panel/views.py:58`) return the store's static UPI ID, and `admin_panel/utils.py` builds a `upi://pay?pa=…` QR. Customers currently pay the store's UPI directly and admin reconciles by hand.
   → **Decision (updated per payment policy above):** Razorpay is the online method; the
   static-UPI/QR path is **retired from self-serve checkout** and demoted to a standalone
   **manual-payment page** (§15). `ONLINE` routes to Razorpay (or, when a coupon zeroes the
   total, straight to `paid` with no gateway — §14). **Don't delete `ReceivableAccount`** —
   the §15 page still reads it. Note the naming overlap: this static flow is unrelated to
   the `PaymentMethod` model (saved customer methods) and to the new `Payment` gateway rows
   — keep the three concepts distinct in code review.

---

## 2. Design decisions

1. **Razorpay-first.** INR, domestic customers. Native UPI/cards/netbanking/wallets. Stripe deferred (kept in model choices, not wired).
2. **Order is created first, then paid.** Reuse the existing `OrderViewSet.create` flow unchanged. After an order exists with `payment_method='ONLINE'` (gateway recorded on the `Payment` row, see §1b.1), the client requests a Razorpay order against it.
3. **Webhook is the source of truth**, not the browser callback. The client callback gives fast UX feedback; the webhook reconciles reality (user may close the tab mid-payment).
4. **Amount is always computed server-side** from `Order.total_amount`. The client never sends an amount. Razorpay works in **paise** → `int(order.total_amount * 100)`.
5. **Idempotency** keyed on `Payment.payment_id` (already `unique=True`). Webhook + callback may both fire; neither double-applies.
6. **Zero-total (full-coupon) needs no gateway call.** When a coupon brings the total to
   ₹0 (§14), the order is placed as `payment_status='paid'` / `status='confirmed'` with **no
   gateway and no `Payment` row** (nothing to capture). This is the only Razorpay skip.
   *(Historical: COD was previously the no-gateway path — `Payment(gateway='cod')`, marked
   paid on delivery. COD is no longer offered self-serve; see the payment policy above.)*

---

## 3. Order / payment state machine

```
Zero-total (full-coupon) path:   [current no-gateway path — see §14/§4.4]
  place order (total = ₹0) ─► Order.status='confirmed', payment_status='paid'
                           ─► no gateway, no Payment row

COD path:   [HISTORICAL — COD no longer offered self-serve; see payment policy §top]
  place order ─► Order.payment_status = 'pending'
              ─► Payment(gateway='cod', status='pending')
              ─► (on delivery) Payment.status='completed', Order.payment_status='paid'

Razorpay path:
  place order ─► Order.payment_status = 'pending'  (no Payment row yet)
  create-order ─► razorpay.Order.create() ─► Payment(gateway='razorpay',
                  payment_id=razorpay_order_id, status='pending')
  user pays in Razorpay Checkout (frontend)
  verify  ─► verify signature ─► Payment.status='completed',
             Order.payment_status='paid', Order.status='confirmed'
  webhook ─► payment.captured  ─► same as verify (idempotent)
          ─► payment.failed    ─► Payment.status='failed'
```

> **Note on `Payment.payment_id`:** during the Razorpay flow this initially holds the
> `razorpay_order_id` (created before payment), then we also persist the
> `razorpay_payment_id` into `transaction_details`. Decide a convention and keep it
> consistent (recommended: `payment_id` = razorpay_order_id, since it exists earliest
> and is unique per order).

---

## 4. New endpoints

All under `payments/`. Register a `PaymentViewSet` (or plain APIViews) in `spices_backend/urls.py`.

### 4.1 `POST /api/payments/create-order/`
- **Auth:** required. **Input:** `{ "order_id": <Order.id> }`
- Loads the user's `Order`, asserts it belongs to them and is unpaid.
- Computes `amount = int(order.total_amount * 100)`.
- **Idempotent re-request rule (§7.7):** if a `pending` `Payment` with a still-valid `razorpay_order_id` already exists for this Order, return it — never mint a second live Razorpay order for the same Order.
- Otherwise calls `razorpay.Order.create({amount, currency:'INR', receipt:f'order_{order.id}', payment_capture:1})`.
- Creates/updates `Payment(order=order, payment_gateway='razorpay', payment_id=rzp_order['id'], amount=order.total_amount, status='pending')`.
- Rejects if `Order.status == 'cancelled'` or `payment_status == 'paid'`.
- **Returns:** `{ razorpay_order_id, razorpay_key_id (public), amount, currency, order_id }`.

### 4.2 `POST /api/payments/verify/`
- **Auth:** required. **Input:** `{ razorpay_order_id, razorpay_payment_id, razorpay_signature }`
- Verifies HMAC-SHA256 signature via `client.utility.verify_payment_signature(...)`. **Reject if invalid.**
- On success (idempotent): `Payment.status='completed'`, store `razorpay_payment_id` in `transaction_details`, `Order.payment_status='paid'`, `Order.status='confirmed'`.
- **Returns:** `{ success: true, order_id }`.
- ⚠️ Treat this as UX confirmation only — do not ship product on this alone; webhook reconciles.

### 4.3 `POST /api/payments/webhook/`
- **Auth:** none (Razorpay calls it) — but **verify the webhook signature** using `RAZORPAY_WEBHOOK_SECRET` against the raw request body. `csrf_exempt`.
- Handle events: `payment.captured` → mark paid (idempotent); `payment.failed` → mark failed.
- Always return `200` quickly once verified; do heavy work async (Celery already available) if needed.
- Idempotent on `payment_id` / event id — a re-delivered webhook must not double-apply.

### 4.4 Zero-total (full-coupon) orders — no gateway
- **Replaces the old COD sub-flow.** COD is not offered self-serve (payment policy above).
- When a validated coupon makes the order total **₹0** (§14), `OrderViewSet.create` waives
  shipping + tax, sets `total_amount=0`, and places the order directly as
  `status='confirmed'`, `payment_status='paid'` — **no Razorpay call, no `Payment` row**.
- No new endpoint is required; this lives inside the existing order-creation flow. The
  coupon's `usage_count` is still incremented under the row lock (as today).
- **Manual/COD fallback:** for buyers who cannot pay online, the store's static UPI/QR is
  shown on the standalone manual-payment page (§15) with a "contact us directly" note;
  the admin reconciles those orders by hand exactly as before.

---

## 5. Files to add / change

| File | Change |
|------|--------|
| `payments/gateway.py` *(new)* | Thin Razorpay client factory: `get_razorpay_client()` reading keys from settings. Keeps SDK calls in one place. |
| `payments/views.py` | Add `create-order`, `verify`, `webhook`, COD-mark views. Keep existing `PaymentMethodViewSet`. |
| `payments/serializers.py` | Add `CreateOrderSerializer`, `VerifyPaymentSerializer` (input validation). |
| `payments/urls.py` *(new, optional)* | Route the new endpoints; include from main `urls.py`. |
| `spices_backend/urls.py` | Register payment routes (`create-order`, `verify`, `webhook`). |
| `spices_backend/settings.py` | Add `RAZORPAY_WEBHOOK_SECRET = config('RAZORPAY_WEBHOOK_SECRET', default='')`. |
| `payments/tests.py` | Tests: signature verify (valid/invalid), idempotent webhook, COD path, amount-from-server. |
| `.env` / deployment secrets | `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`, `RAZORPAY_WEBHOOK_SECRET` (test keys first). |

No model migration strictly required (Payment/Order already support this). Optional: add a `razorpay_payment_id` field to `Payment` instead of stuffing it in `transaction_details` — cleaner querying, costs one migration.

---

## 6. Frontend touchpoints (nidhi-brand-forge)

1. On checkout with online payment: `POST /api/payments/create-order/` → receive `razorpay_order_id` + `razorpay_key_id`.
2. Load Razorpay Checkout script, open with that order id + key.
3. On Checkout success callback → `POST /api/payments/verify/` with the three returned fields.
4. Show success on verify `200`; show pending/failed otherwise.
5. COD: just place the order; show "Pay on delivery" confirmation.
6. **Retry-payment UX (important — the cart is gone):** order creation clears the cart *inside* the
   order transaction (`orders/views.py:476`). If Checkout is abandoned or the payment fails, the
   user has an order but an empty cart. The retry path is therefore a **"Retry payment" button on
   the pending order** (order list/detail) that re-calls `create-order` for the *same* Order —
   never "add everything to cart again". Without this, every failed payment strands the customer.

(Frontend work is out of scope for this backend plan but listed so the contract is clear.)

---

## 7. Resilience — the core of a robust integration

> **Governing principle:** the money moves between the customer's browser and
> Razorpay. **Our server is never in the money path.** Our database is a *cache* of
> Razorpay's truth, not the source of it. Downtime, crashes and races can only make us
> temporarily **stale** — never **wrong** — provided every state transition is
> idempotent and reconcilable. Everything below follows from that one idea.

Razorpay's webhook contract (from official docs) that drives this design:
- **At-least-once delivery** — the same event can arrive multiple times.
- **No ordering guarantee** — `payment.failed` can arrive *before* `payment.captured`.
- **5-second ACK window** — you must return `2xx` within 5s or it's treated as failed.
- **Retries with exponential backoff for 24h**, then the webhook is auto-disabled and an alert email is sent.
- Each delivery carries a unique **`x-razorpay-event-id`** header — the idempotency key.

### 7.1 The three-layer reconciliation model (defence in depth)

No single mechanism is trusted. State converges through three independent layers:

| Layer | Trigger | Catches | Mechanism |
|-------|---------|---------|-----------|
| **L1 — Client callback** | Browser returns from Checkout → `POST /verify/` | Happy path, instant UX | Signature verify → mark paid |
| **L2 — Webhook** | Razorpay server → `POST /webhook/` (retried 24h) | Tab closed, callback lost, L1 server blip | Signature + event-id idempotency → mark paid |
| **L3 — Active reconciliation** | Celery beat job, every ~15 min + nightly sweep | Webhook lost to >24h outage, missed events, abandoned orders | Poll `client.order.fetch`/`payment.fetch` for stuck `pending` |

L3 is the backstop that makes the whole thing robust: even if L1 **and** L2 both fail, the system self-heals on the next poll. Build all three.

### 7.2 Concurrency & idempotency (races)

Multiple actors can touch one payment simultaneously: L1 callback + L2 webhook, webhook redelivery, double-clicks, a user **cancelling the order mid-payment**, and the L3 job. The rule: **every transition is guarded by row locks taken in one canonical order + a status check + a recorded event id.**

> **Canonical lock order (project-wide invariant): lock the `Order` row FIRST, then the `Payment` row.**
> Every code path that mutates payment/order state — verify, webhook, L3 reconcile, COD-mark-paid,
> and (after this work) `OrderViewSet.cancel` — must acquire `select_for_update()` in this order.
> Today `cancel` (`orders/views.py:519`) locks only the Order, and a naive capture handler would
> lock only the Payment and write the Order unlocked. Those two, interleaved, can produce a
> **cancelled order (stock restored) that is simultaneously marked paid** — the worst possible
> inconsistent state. One shared lock order makes that impossible and prevents deadlocks.

```python
# verify and webhook BOTH funnel through one idempotent function
def mark_payment_captured(razorpay_order_id, razorpay_payment_id, event_id=None, source='webhook'):
    with transaction.atomic():
        # Canonical lock order: Order first, then Payment.
        payment_ref = Payment.objects.get(payment_id=razorpay_order_id)  # unlocked lookup for the order id
        order = Order.objects.select_for_update().get(pk=payment_ref.order_id)
        payment = Payment.objects.select_for_update().get(pk=payment_ref.pk)

        # Idempotency guard — second caller (race or redelivery) is a no-op
        if payment.status in ('completed', 'refunded'):
            return payment
        if event_id and ProcessedWebhookEvent.objects.filter(event_id=event_id).exists():
            return payment

        # Cancelled-order guard: money arrived for an order the user (or L3) already
        # cancelled and whose stock is already restored. DO NOT confirm the order.
        # Record the exception and route to refund — never resurrect a cancelled order.
        if order.status == 'cancelled':
            payment.status = 'completed'   # the money IS captured — record the truth
            payment.save(update_fields=['status', 'updated_at'])
            log_payment_event(payment, 'captured_after_cancel', source=source,
                              raw=..., alert_admin=True)   # → refund queue (§7.8)
            if event_id:
                ProcessedWebhookEvent.objects.create(event_id=event_id)
            return payment

        payment.status = 'completed'
        payment.transaction_details = {**(payment.transaction_details or {}),
                                       'razorpay_payment_id': razorpay_payment_id}
        payment.save(update_fields=['status', 'transaction_details', 'updated_at'])

        order.payment_status = 'paid'
        order.status = 'confirmed'
        order.save(update_fields=['payment_status', 'status', 'updated_at'])

        if event_id:
            # Unique constraint is the real guard: two workers can both pass the
            # exists() check above before either commits. Catch IntegrityError
            # and treat it as "duplicate — someone else won"; do NOT 500.
            ProcessedWebhookEvent.objects.create(event_id=event_id)

        log_payment_event(payment, 'captured', source=source, from_status='pending',
                          to_status='completed', raw=...)  # §7.6a — same txn

        # side-effects exactly once, after the txn commits
        transaction.on_commit(lambda: send_order_confirmation(order.id))
```

Key points:
- `select_for_update()` serialises the L1/L2 race; the loser sees `completed` and no-ops. The `unique=True` on `payment_id` prevents duplicate *rows* but does **not** prevent a lost update — the lock does.
- **Lock the Order too, and in the canonical order.** Locking only the Payment leaves the Order writable by `cancel` in parallel (see box above).
- **The `ProcessedWebhookEvent.exists()` check is advisory; the unique constraint is authoritative.** Wrap the insert so an `IntegrityError` from a concurrent duplicate resolves to a clean no-op + `200`, not a `500` (which would trigger pointless Razorpay retries).
- **Out-of-order safety:** never downgrade a terminal state. `payment.failed` arriving after `payment.captured` must not flip a paid order back to failed. Only apply `failed` if status is still `pending`.
- **Never resurrect a cancelled order.** Capture-after-cancel records the money truthfully on the `Payment`, raises an admin exception, and goes to refund (§7.8) — it does not flip `Order.status` back.
- **Side-effects via `transaction.on_commit`** so a rolled-back txn never emails a customer about a payment that didn't persist.

### 7.3 Server crash / downtime matrix

| When the server dies | What happens to the money | Recovery |
|----------------------|---------------------------|----------|
| During `create-order`, before Razorpay order made | Nothing charged | Client retries; `get_or_create` returns existing pending Payment |
| After Razorpay order made, before `Payment` row commits | Nothing charged; orphan RZP order expires | `transaction.atomic()` rolls back cleanly — no partial row |
| **While user pays in Checkout** | **Captured by Razorpay regardless** | L1 callback fails (cosmetic) → **L2 webhook reconciles on retry** |
| During `/verify/` processing | Captured | Webhook + L3 reconcile; atomic txn means no half-update |
| During webhook processing, before ACK | Captured | **Must not 200 early** → Razorpay redelivers → idempotent no-op |
| Down > 24h (webhook disabled) | Captured | **L3 polling job** fetches truth from Razorpay API |

**The ACK-ordering rule (critical):** return `200` to the webhook **only after** the DB transaction commits. ACK-before-commit + crash = silently lost event with no retry. It is always safer to crash and be redelivered than to ACK early.

**The 5-second rule:** signature-verify and persist a minimal record fast, then ACK; push slow side-effects (email, analytics, invoice PDF) to a background worker (Celery once wired — §1b.3; until then keep the handler's work minimal so even a synchronous path stays well under 5s, and let L3 backfill anything skipped). Never do blocking I/O before the ACK.

### 7.4 Stock policy: reservation-until-cancel (and the abandoned-order leak)

**Stock policy (explicit design decision):** decrementing stock at order creation is **correct and
stays** — it is a *reservation*. From the moment an order exists, its stock is consumed and is not
sellable to anyone else, through the whole payment window and fulfilment. This is what prevents
overselling ("two customers buy the last jar, only one payment succeeds"). The rules:

1. **Stock is consumed at order creation and held for the entire life of the order** — pending,
   awaiting payment, paid, shipped. A pending-payment order's stock is never quietly freed while
   the order is alive.
2. **Cancellation is the ONLY release valve.** Stock returns exclusively through the cancel path
   (`OrderViewSet.cancel` restore logic — user cancel, admin cancel, or L3 auto-cancel), which
   flips the order to `cancelled` and restores stock **in the same atomic transaction**. Release
   is therefore exactly-once (the status guard under the Order lock stops double-restores) and the
   order state always agrees with inventory.
3. **No other code path touches stock** — not the webhook, not verify, not the reconciliation job
   directly. If L3 decides an order is truly abandoned, it releases stock *by cancelling the
   order* through the same logic, never by editing stock numbers on the side.

The remaining problem this section solves: an online order abandoned at Checkout holds its
reservation at `payment_status='pending'` **forever**, silently shrinking sellable inventory. The
fix is not to weaken the reservation — it's a bounded TTL after which the order is *cancelled*
(releasing stock through rule 2). The L3 job does this and does double duty:

```
for each Order where payment_method='ONLINE' and payment_status='pending'
                     and created_at < now() - TTL (e.g. 30 min):
                     # (gateway is on the Payment row; Order.payment_method is 'ONLINE', see §1b.1)
    truth = razorpay.order.fetch(payment.payment_id)   # ask the source of truth
    if truth shows a captured payment:  mark paid (a webhook was missed)  → L3 saves L2
    else:                               cancel order + restore stock (reuse Order.cancel logic)
```

COD orders are exempt (no online payment expected — their reservation lives until delivery or an
explicit cancel). Choose TTL ≥ Razorpay order validity, and generously — under this policy a too-long
TTL only holds stock a bit longer, while a too-short TTL cancels orders customers are still paying
for (safe thanks to the `captured_after_cancel` guard in §7.2, but a refund hassle you don't want).
If the L3 fetch shows a captured payment, the order is marked paid and **keeps its stock** — the
reservation simply converts to a sale.

### 7.5 Money-specific correctness

- **Amount integrity:** always `int(order.total_amount * 100)` (paise) computed server-side. Never accept an amount from the client. Verify the webhook's `amount` matches the stored `Payment.amount`; mismatch → flag, don't auto-fulfil.
- **Currency** pinned to `INR`.
- **Double-payment:** if a `Payment` is already `completed`, reject/refund a second capture for the same order rather than fulfilling twice.
- **Refunds:** `status='refunded'` already modeled. Handle `refund.processed` webhook; restore stock per business rule. (Phase 2 — see open questions.)
- **Reconciliation report:** nightly job diffs our `completed` payments against Razorpay settlement/transactions for the day; alert on any mismatch. This is the human-visible safety net.

### 7.6 Transparency — making every issue visible (customer + admin)

> Correctness that nobody can see is not assurance. **Every payment must have a truthful,
> queryable state and an immutable history; every anomaly must raise a durable record AND a
> notification — never just a log line.** Three mechanisms deliver this.

#### (a) The audit trail — `PaymentEvent` (single source of "what happened")

Add an append-only `PaymentEvent(payment FK, event_type, source, from_status, to_status, message, raw_payload JSON, created_at)`. **Every** transition writes one row, inside the same `transaction.atomic()` as the state change (so the history can never disagree with the state):

| `source` | Examples of `event_type` |
|----------|--------------------------|
| `client` | `order_created`, `verify_succeeded`, `verify_signature_failed` |
| `webhook` | `captured`, `failed`, `signature_invalid`, `duplicate_ignored`, `out_of_order_ignored` |
| `reconcile` | `recovered_paid`, `auto_cancelled`, `amount_mismatch`, `stuck_flagged` |
| `admin` | `manual_marked_paid`, `manual_refund`, `note_added` |

This is what makes an issue *explainable* after the fact: anyone can read the full lifecycle of a single payment — including the raw Razorpay payloads — in one place. It is also the evidence trail for disputes/chargebacks.

#### (b) Customer-facing transparency

- **Payment state is always surfaced on the order page**, mapped from `Order.payment_status`:
  `pending` → "Payment pending", `processing`* → "Confirming your payment…", `paid` → "Payment received", `failed` → "Payment failed — retry".
  *(\*optional intermediate `processing` state for the "paid at Razorpay but our `/verify/` hasn't confirmed yet" window — see §1b.2 vocabulary.)*
- **Never show a false failure.** The "paid but verify callback failed" case shows **"Confirming your payment…"**, not "failed". A short frontend poll on `GET /api/payments/status/?order_id=` (or order detail) flips it to "Payment received" once the webhook lands. This single rule prevents the worst customer experience: being told to pay again for an order you already paid.
- **Proactive notifications** on every terminal transition, reusing the existing email infra (you already send password-reset email): payment received, payment failed (+ retry link), refund processed. Optionally SMS for failures.
- **A reference the customer can quote** — show `razorpay_payment_id` / order number on the confirmation and in emails, so a support conversation starts with an ID, not "my payment didn't work."

#### (c) Admin-facing transparency + active alerting

- **Exceptions queue** — the highest-value piece. A filtered admin view (extend `payments/admin.py` and/or `DashboardViewSet`) listing payments **needing human attention**, never buried in normal traffic:
  - stuck `pending` past TTL, `amount_mismatch`, `signature_invalid` (possible fraud/misconfig), `recovered_paid` (a webhook was missed — worth knowing), Razorpay webhook **auto-disabled** (the 24h-failure email condition), nightly settlement diff mismatches.
- **Push alerts, don't wait for someone to look.** The reconciliation job and webhook handler **email the admin** (and/or post to a Slack/webhook URL) the moment any exception is recorded — same email backend you already use. Silence = healthy; an alert = a named payment + reason + link.
- **Watch the watcher (dead-man's switch).** "Silence = healthy" is only true if the L3 job is actually running — a dead cron looks identical to a healthy system. Fix: the reconcile job writes a `last_run` timestamp (Redis key or tiny model) on every run, and the daily digest (or a `/api/health/`-style check) **alerts if `last_run` is stale** (> 2× the schedule interval). Cheapest possible insurance against the failure mode where the safety net itself has failed.
- **Rich Django admin** on `Payment` + inline `PaymentEvent` history: status, gateway, amount, `razorpay_payment_id`, `failure_reason`, full timeline. Filters by status/gateway/date already partly exist for orders (`orders/admin.py:28`).
- **Admin actions, audited:** "mark COD paid", "mark as manually reconciled", "initiate refund" — each writes a `PaymentEvent(source='admin')` so manual interventions are as traceable as automated ones.
- **A daily digest** (even when nothing is wrong): "N payments, ₹X captured, M reconciled by job, K exceptions open." Turns "is the payment system OK?" into a glance.

**Net effect:** for any troubled transaction, the customer sees an honest, non-alarming status and a way forward; the admin gets pushed an alert with the exact payment, the reason, and the full event history to act on. Nothing fails silently.

### 7.7 Order-placement independence (double-submit / concurrent creates)

**Verified bug-in-waiting in the existing code:** `OrderViewSet.create` reads the cart items
**before** `transaction.atomic()` opens (`orders/views.py:224` vs `:358`). Two concurrent requests
from the same user (double-click, slow network + retry, two tabs) both see the full cart and both
create an order. The `select_for_update()` on stock rows prevents *overselling*, but you still get
**two duplicate orders**, double stock decrement, double coupon burn — and with online payment,
potentially two Razorpay orders the customer can pay. The per-minute throttle reduces the odds; it
is not a correctness guarantee.

Fixes (do the first; the second is optional hardening):

1. **Lock the cart inside the transaction.** First statement inside `transaction.atomic()`:
   `Cart.objects.select_for_update().get(user=request.user)`, then **re-check `cart.items.exists()`
   under the lock** before creating the Order. The loser of a double-submit finds an empty cart
   (the winner deleted the items inside its txn) and gets a clean "Cart is empty" 400 instead of a
   duplicate order. This is a small, surgical change to the existing view and is a **prerequisite**
   for wiring payments on top of it.
2. **Optional `Idempotency-Key` header** on `POST /api/orders/` and `POST /api/payments/create-order/`
   (client-generated UUID, stored unique for ~24h; replay returns the original response). Standard
   payment-industry practice; protects against retried requests that arrive after the cart is
   already empty *and* makes frontend retry logic safe to write aggressively.

**One Razorpay order per Order, ever (re-request rule).** `create-order` must be idempotent too:
if a `pending` `Payment` with a still-valid `razorpay_order_id` exists, **return the existing id —
never mint a second Razorpay order** for the same Order. Two live Razorpay orders for one Order is
a self-inflicted double-payment vector (the customer can complete both). Only create a fresh
Razorpay order if the previous one is expired/failed, and record the superseded id in
`transaction_details` so a late capture on the old id can still be resolved (→ auto-refund, §7.8).
The `OneToOneField(Order)` on `Payment` already enforces one Payment row per Order — good; reuse
the row, update `payment_id` only on legitimate supersession.

### 7.8 Cancellation ↔ payment interaction (the seam with existing code)

`OrderViewSet.cancel` (`orders/views.py:507`) predates payments and only blocks
`delivered / cancelled / delivering`. Three problems once real money flows:

1. **Cancel of a PAID order silently keeps the money.** A `confirmed` (paid) order passes the
   current guard: stock is restored, status flips to `cancelled`, and nothing refunds the customer.
   **Rule:** cancelling an order whose `Payment.status == 'completed'` must either (a) trigger the
   refund flow, or — until refunds ship (phase 2) — (b) be **blocked for self-service** with
   "contact support", routing to an admin exception. Never allow a paid order to reach `cancelled`
   with no refund record.
2. **Cancel racing an in-flight payment.** User opens Razorpay Checkout, then cancels the order in
   another tab; payment completes seconds later. Handled by the canonical lock order + the
   cancelled-order guard in §7.2: `cancel` must also lock the Payment (Order → Payment order) and
   the capture path never resurrects a cancelled order — the money lands as `captured_after_cancel`
   → admin alert → refund. Same mechanism covers **L3 auto-cancel racing a late webhook** (the
   fetch-then-cancel window in §7.4 is unavoidable; the guard makes it safe).
3. **Coupon usage is not restored on cancel** (today, and L3 auto-cancel would inherit this):
   an abandoned online order burns `usage_count` forever. Decide the business rule (§12); if
   restoring, decrement under the same `select_for_update()` pattern used at creation.

Also note: order status is otherwise mutated via the generic `ModelViewSet` PATCH (admin panel
sets `shipped`/`delivered`). The COD "mark paid on delivery" hook and the "don't cancel paid
orders without refund" guard must live where **all** status transitions pass (model-level
`transition()` helper or the ViewSet `update`), not only in the customer-facing `cancel` action.

### 7.9 Disaster recovery & compromise — recovering correct state from zero trust

> Scenario the design must survive: **the server is destroyed, the database is corrupted or
> restored from an old backup, or the platform is outright hacked.** The invariant that saves us:
> **Razorpay holds the authoritative, off-platform record of every money movement** (dashboard +
> API + settlement reports), and our keys can be rotated. We can always rebuild truthful payment
> state; we can never lose money state, only our copy of it.

- **Full-resync command:** ship `manage.py resync_payments --since <date>` alongside the L3 job
  (same code path, wider window). It walks Razorpay Orders/Payments via the API and re-derives
  every `Payment`/`Order.payment_status` in our DB, writing `PaymentEvent(source='reconcile')`
  rows for every correction. Recovery from *any* local data loss = restore latest DB backup →
  run resync since backup timestamp → review the exceptions queue. This makes "our DB is a cache
  of Razorpay's truth" (§7 principle) operational, not aspirational.
- **Backup-restore gap:** after restoring an old backup, payments may exist at Razorpay for orders
  that no longer exist locally (created after the backup). Resync must surface these as
  `orphan_payment` exceptions (admin decides: refund or manually recreate the order). The nightly
  settlement diff (§7.5) catches anything resync misses.
- **Compromise runbook (write it into `docs/`):**
  1. Rotate `RAZORPAY_KEY_SECRET` + `RAZORPAY_WEBHOOK_SECRET` in the Razorpay dashboard and
     redeploy — old stolen secrets go dead. (Keys live only in env via `python-decouple`; never in
     the repo, so a source-code leak alone exposes nothing.)
  2. An attacker **cannot forge a paid state from outside**: webhook requires the HMAC secret;
     `/verify/` requires a signature only Razorpay can produce; amounts are never client-supplied.
  3. An attacker **with DB write access** can flip flags — that's what the nightly settlement diff
     and resync exist for: our DB is never the final word on money. After any suspected compromise,
     run `resync_payments` + settlement diff and treat mismatches as the attack surface report.
  4. `PaymentEvent` is append-only by convention (no update/delete paths in code; optionally a DB
     trigger/permission), so tampering is at least detectable as gaps/inconsistencies.
- **Payout safety:** fulfilment (shipping goods) should key off `payment_status='paid'` **that has
  survived reconciliation**, and refunds are executed only via Razorpay's API (never a local flag),
  so even a fully compromised app server cannot move money out — Razorpay-side controls
  (dashboard 2FA, API key scope) are the money perimeter. Enable 2FA on the Razorpay account; it
  is part of this system's security boundary.

---

## 8. Security checklist (must-haves)

- [ ] Amount derived from `Order.total_amount` server-side — never from request body.
- [ ] Signature verified on **both** `/verify/` and `/webhook/` before marking paid.
- [ ] Webhook signature computed over the **raw request body bytes** (not re-serialised JSON) using HMAC-SHA256 with `RAZORPAY_WEBHOOK_SECRET`.
- [ ] Idempotency on **`x-razorpay-event-id`** (recorded in a `ProcessedWebhookEvent` table) **and** a status guard — webhook + callback + redelivery all safe.
- [ ] Never downgrade a terminal payment state (out-of-order event safety).
- [ ] `/webhook/` returns `2xx` within **5 seconds**; heavy work deferred to Celery.
- [ ] ACK the webhook **only after** DB commit (`transaction.on_commit` for side-effects).
- [ ] Keys via `python-decouple`, never committed. Test keys until go-live.
- [ ] `/webhook/` is `csrf_exempt` but signature-gated; reject unverified with `400`.
- [ ] TLS 1.2+ on the webhook endpoint; optionally allowlist Razorpay's webhook source IPs.
- [ ] Order ownership enforced (`order.user == request.user`) on create-order/verify.
- [ ] No raw card data ever touches the backend (Razorpay Checkout handles PCI scope).
- [ ] Verify webhook `amount`/`currency` match the stored `Payment` before fulfilling.
- [ ] **Canonical lock order everywhere** (Order → Payment, §7.2) — including `OrderViewSet.cancel`.
- [ ] Never create a second live Razorpay order for the same Order (§7.7).
- [ ] Cancelling a paid order without a refund record is impossible (§7.8).
- [ ] Throttle `/payments/create-order/` and `/payments/verify/` (reuse the DRF throttle pattern already on order create) — verify is an HMAC oracle if left unthrottled.
- [ ] Webhook: after signature check, ACK unknown/unsubscribed event types with `200` (don't 4xx — it just triggers 24h of retries); cap accepted body size.
- [ ] Prune `ProcessedWebhookEvent` rows older than ~30 days (well past the 24h retry window).
- [ ] 2FA on the Razorpay dashboard account; API keys scoped minimally (money perimeter, §7.9).

---

## 9. New model needs (for the resilience layer)

| Addition | Purpose |
|----------|---------|
| `ProcessedWebhookEvent(event_id unique, event_type, received_at)` *(new model)* | Idempotency ledger keyed on `x-razorpay-event-id`. One migration. |
| `Payment.razorpay_payment_id` *(optional field)* | First-class column instead of digging in `transaction_details` JSON — easier reconciliation queries. One migration. |
| `Payment.failure_reason` / `failure_code` *(optional)* | Store `payment.failed` error code for support + retry-UX. |
| `Order.payment_status` add `choices=['pending','paid','failed','refunded']` (+ optional `processing`) | Lock the vocabulary this work introduces (currently free text, see §1b.2). One migration; no data change. |
| `PaymentEvent(payment FK, event_type, source, from_status, to_status, message, raw_payload, created_at)` *(new model)* | Append-only audit trail powering all of §7.6 (admin history, exceptions, dispute evidence). One migration. |

---

## 10. Suggested build order

0. **Decide the §1b prerequisites:** Celery-vs-management-command for L3 (recommend management command first), and add `Order.payment_status` choices migration.
0b. **Harden the existing order code first (§7.7/§7.8 — prerequisites, small diffs):**
   lock the Cart inside `OrderViewSet.create`'s transaction + re-check items under the lock
   (kills double-submit duplicate orders); extend `OrderViewSet.cancel` to lock the Payment
   (canonical order) and block/route paid-order cancellation. Payments must not be wired on top
   of the unhardened flow.
1. Add `RAZORPAY_WEBHOOK_SECRET` to settings; put test keys in `.env`.
2. `payments/gateway.py` — client factory.
3. Add `ProcessedWebhookEvent` + `PaymentEvent` models + `payment_status` choices migration. Write a `PaymentEvent` row inside every state transition from the start (§7.6a).
4. `create-order` endpoint + serializer (with `get_or_create` guard) → test in Razorpay test mode. Order is `payment_method='ONLINE'`; gateway lives on `Payment`.
5. `verify` endpoint → routes through the shared `mark_payment_captured()` idempotent function.
6. `webhook` endpoint → signature + event-id idempotency, fast ACK, deferred side-effects.
7. **Zero-total path** wiring into `OrderViewSet.create` (coupon zeroes total → waive
   shipping+tax → place as `paid`, no gateway/Payment row — §14/§4.4). *(Replaces the
   old "COD path wiring" step; COD is no longer offered self-serve.)*
8. **L3 reconciliation** — as a `manage.py reconcile_payments` command (or Celery beat task if §1b.3 chose Celery): stuck-order reconciliation + stock restoration + nightly settlement diff. Wire to scheduler. Build `resync_payments --since` (§7.9) as the same code path with a wider window.
9. **Transparency layer (§7.6):** customer `GET /payments/status/` endpoint; admin exceptions queue + rich `Payment`/`PaymentEvent` admin; alert email on exceptions; customer notification emails (reuse existing email backend); optional daily digest.
10. Tests (`payments/tests.py`) — see §11.
11. Wire frontend Checkout (handle the "paid but verify failed → show *processing*, not *failed*" UX). Keep the existing `ReceivableAccount` UPI/QR path until Razorpay is proven.
12. Switch to live keys + register production webhook URL & subscribe events in Razorpay dashboard.

**Events to subscribe in dashboard:** `payment.captured`, `payment.failed`, `order.paid`, and (phase 2) `refund.processed`.

---

## 11. Test matrix (what "robust" must prove)

- [ ] Valid signature accepted; tampered/invalid signature rejected (verify + webhook).
- [ ] Duplicate webhook (same `event_id`) → second is a no-op, no double email.
- [ ] L1 callback and L2 webhook racing → exactly one set of side-effects.
- [ ] Out-of-order: `payment.failed` after `payment.captured` does not un-pay the order.
- [ ] Amount tampering in request body is ignored (server uses `Order.total_amount`).
- [ ] Webhook handler returns 2xx in <5s with side-effects deferred.
- [ ] Crash simulated between commit and ACK → redelivery reconciles, no dup.
- [ ] L3 job marks a paid-but-webhook-missed order as paid.
- [ ] L3 job cancels a truly-abandoned order and restores stock.
- [ ] COD order: Payment row created `pending`, flips on delivery.
- [ ] Every state transition writes exactly one `PaymentEvent` in the same transaction (history never disagrees with state).
- [ ] "Paid but verify failed" surfaces as *processing*/*confirming*, never *failed*, then flips to *paid* on webhook.
- [ ] Each exception type (`amount_mismatch`, `signature_invalid`, `stuck_flagged`, `recovered_paid`) lands in the admin exceptions queue **and** triggers an alert email.
- [ ] Customer notification email sent on paid / failed / refunded.
- [ ] Double-submit: two concurrent `POST /orders/` from one user → exactly one order; loser gets a clean 400 (cart lock, §7.7).
- [ ] `create-order` called twice for one Order → same `razorpay_order_id` returned, no second Razorpay order (§7.7).
- [ ] Cancel racing capture: order cancelled while payment completes → order stays cancelled, payment recorded `captured_after_cancel`, admin alerted, no stock inconsistency (§7.2/§7.8).
- [ ] Cancelling a paid order is blocked (or produces a refund record) — never cancelled + money kept (§7.8).
- [ ] Concurrent duplicate webhook workers → `IntegrityError` on `ProcessedWebhookEvent` resolves to no-op `200`, not `500` (§7.2).
- [ ] `resync_payments --since` rebuilds correct state from Razorpay after simulated data loss; orphan payments surface as exceptions (§7.9).
- [ ] Stock held by a pending-payment order is not sellable to others; released exactly once on cancel (any cancel path), never while the order is alive (§7.4).

---

## 12. Open questions before coding

- **`payment_id` convention:** store `razorpay_order_id` as the canonical `payment_id` (recommended — exists earliest, unique per order) vs `razorpay_payment_id`. Affects idempotency keys.
- ~~**COD "paid" trigger**~~ — resolved: COD is no longer offered self-serve (payment policy §top); the no-gateway path is the zero-total coupon order (§14/§4.4).
- **Refund flow:** in scope now or phase 2? (`status='refunded'` already modeled.)
- **Stuck-order TTL:** 30 min default — confirm against Razorpay order validity and your fulfilment SLA.
- **`razorpay_payment_id` as a column** vs reuse `transaction_details` JSON.
- **Coupon usage on cancel/auto-cancel:** restore `usage_count` or treat it as burned? (Today it is never restored — L3 auto-cancel inherits whatever you decide, §7.8.)
- **Self-cancel of paid orders:** blocked with "contact support" until refunds ship, or auto-refund from day one?
- **`Idempotency-Key` header** on order/payment creation: ship now or defer (cart lock alone already kills the common double-submit)?

---

## 13. Sources / references

- [Razorpay — Webhooks Best Practices](https://razorpay.com/docs/webhooks/best-practices/) — 5s ACK, at-least-once, `x-razorpay-event-id`, 24h backoff, TLS/IP.
- [Razorpay — Validate & Test Webhooks](https://razorpay.com/docs/webhooks/validate-test/) — HMAC-SHA256 over raw body, signature verification.
- [Razorpay — About Webhooks](https://razorpay.com/docs/webhooks/) and [Webhook FAQs](https://razorpay.com/docs/webhooks/faqs/) — retry/disable behaviour, ordering.
- [Razorpay — Payment Gateway API Integration Guide](https://razorpay.com/blog/payment-gateway-api-integration-guide/) — failure handling, reconciliation.
- [Payment Webhook Best Practices (apidog)](https://apidog.com/blog/payment-webhook-best-practices/) — idempotency & reconciliation patterns.
- [Unresponsive Payments: Retry & Fallback (Medium)](https://medium.com/@akshayp344/unresponsive-payments-handling-on-razorpay-platform-with-retry-and-fallback-mechanism-3f74e0f3b54d) — polling fallback design.

---

## 14. Coupons — discount types, special coupons, and the zero-total path

> **Status:** design-level, **not built yet** (like the rest of this plan). Describes the
> intended `Coupon` shape and the rules the order flow must enforce. The zero-total order
> (§4.4) is the checkout consequence of a full-value coupon, so coupons and payments are
> specified together.

### 14.1 Today (baseline)

`admin_panel.Coupon` (`admin_panel/models.py:39`) is **percent-only and global**:
`code`, `discount_percent` (1–100), `is_active`, `valid_until`, `max_usage`,
`usage_count`, `minimum_order_amount`. Validation lives in
`Coupon.get_invalid_reason(order_amount=None)`; the order flow calls it in
`OrderViewSet._validate_coupon` (`orders/views.py:76`) and re-checks it under a
`select_for_update()` row lock while incrementing `usage_count` (`orders/views.py:467`).
Discount is computed by `_calculate_discount` (`orders/views.py:130`) as a flat percentage.

### 14.2 New capabilities

| Field / rule | Purpose |
|--------------|---------|
| `discount_type = 'percent' \| 'fixed'` (default `'percent'`) | Choose percentage vs flat ₹. |
| `discount_amount` (Decimal, ₹) | The flat amount off when `discount_type='fixed'`. `discount_percent` still drives `'percent'`. |
| `assigned_user` (nullable FK → `AUTH_USER_MODEL`) | **Single-user special coupon** — only that customer may redeem. `null` = global (today's behaviour). |
| **Full-value coupon** | A coupon whose discount covers the whole subtotal → **₹0 total** (the only Razorpay skip). Achieved by `discount_percent=100` **or** a `fixed` `discount_amount ≥ subtotal`. |

**Validation extension** — `get_invalid_reason(self, order_amount=None, user=None)`:
- if `assigned_user_id` and (`user is None` or `user.id != assigned_user_id`) →
  *"This coupon is not available for your account."*
- keep the existing active / expiry / `max_usage` / `minimum_order_amount` checks.
- `_validate_coupon` and the row-locked re-check must **pass `request.user`** through.

**Discount computation** — replace `_calculate_discount` with a
`Coupon.discount_for(amount) -> Decimal` helper:
- `percent` → `amount * discount_percent / 100`
- `fixed`   → `discount_amount`
- **clamp to `amount`** so the discount never exceeds the subtotal (total floors at ₹0).

### 14.3 Zero-total behaviour (ties into §4.4)

When `subtotal - discount <= 0`:
- force `discounted_subtotal = 0`, **`shipping_charge = 0`, `tax = 0`, `total_amount = 0`**
  (a full coupon waives shipping and tax so the total is genuinely ₹0 — otherwise the
  `< FREE_SHIPPING_THRESHOLD` rule would re-add ₹69 shipping to a "free" order);
- place the order as `status='confirmed'`, `payment_status='paid'`, **no gateway, no
  `Payment` row**;
- still increment `usage_count` under the row lock.

Non-zero orders are unchanged: `status='pending'`, `payment_status='pending'`, routed to
Razorpay (when wired).

### 14.4 Admin generation of special coupons

Extend `CouponSerializer` (`admin_panel/serializers.py:13`, currently exposes only
`code`/`discount_percent`/`is_active`/`valid_until`) to accept `discount_type`,
`discount_amount`, `assigned_user`, `max_usage`, `minimum_order_amount`, plus a read-only
`assigned_user_email`; validate `fixed ⇒ discount_amount > 0` and
`percent ⇒ 1 ≤ discount_percent ≤ 100`. Admin-only CRUD as today. Typical special coupons:
- **Per-user, fixed ₹:** `discount_type='fixed'`, `discount_amount=200`, `assigned_user=<id>`, `max_usage=1`.
- **Per-user, full-value (free order):** `discount_percent=100`, `assigned_user=<id>`, `max_usage=1`.

### 14.5 Migration & open points

- One migration adds `discount_type`, `discount_amount`, `assigned_user` (all with safe
  defaults / nullable — no data change to existing coupons).
- **`usage_count` on cancel/auto-cancel** stays the existing open question (§12) — a
  cancelled zero-total order currently keeps the coupon burned; decide whether to restore.

---

## 15. Admin manual-payment QR page (`ReceivableAccount`)

The static UPI/QR the admin enters in the DB is **kept as a standalone "manual payment"
page**, decoupled from the main checkout.

- **Source of truth:** `ReceivableAccount` (`admin_panel/models.py:6`) — admin-configured
  UPI id / bank details, one `is_default` active account.
- **Endpoint (exists):** `GET /api/payment-account/` returns the default active account;
  `admin_panel/utils.py` builds the `upi://pay?pa=…` deep link + QR image.
- **Page behaviour:** display the admin's QR / UPI id with a **"Cash on Delivery or manual
  payment? Please contact us directly"** note, so buyers who cannot use Razorpay have a
  path. Orders paid this way are reconciled by the admin by hand (as before) — this page
  does **not** create a `Payment` row or auto-confirm anything.
- **Not in main checkout:** `Billing.tsx` no longer generates a per-amount QR; the manual
  QR lives only on this dedicated page. `ReceivableAccount` is therefore **retained, not
  deleted** (see §1b.4).
