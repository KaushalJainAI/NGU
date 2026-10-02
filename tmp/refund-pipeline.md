# NGU — Refund Pipeline

*Compiled 2026-08-01 from the code in `Backend/`, `Frontend/`, `Admin Panel/`.
Reflects two changes made the same day: **manual-only refunds** and **partial
refund amounts**.*

---

## Current state in three lines

1. **No code issues a refund.** A human moves the money — Razorpay dashboard for
   online, cash/UPI/bank transfer for COD.
2. **No code records one automatically.** The `refund.processed` webhook branch is
   disabled. An admin records every refund by hand in the panel.
3. **Refunds can be partial.** The admin enters an amount (default: the whole
   outstanding balance). Any amount marks the order `refunded`, so that flag now
   means *"a refund was recorded"*, **not** *"all of it came back"*.

Point 3 is the one that bites. `status='refunded'` is no longer self-explanatory —
every surface must show `refunded_amount` beside it, or ₹200 back on a ₹500 order
looks identical to a full refund.

**Why any of this matters:** a refund reverses GST liability. An unrecorded refund
means paying tax to the government on money you already gave back.

---

## Who can do what

| | Issue money back | Record it in our ledger |
|---|---|---|
| **Razorpay dashboard** | ✅ the only way, for online orders | ❌ **disabled 2026-08-01** — `refund.processed` branch commented out |
| **Our admin panel** | ❌ nothing calls the refund API | ✅ **the only live path** — PATCH `status:'refunded'` (+ optional `refund_amount`) |

There has never been a `client.payment.refund(...)` call in the codebase;
`payments/gateway.py` is used only for order creation, verification and capture
reconciliation.

---

## The pipeline as it runs today

```
        ONLINE (Razorpay)                                      COD / manual
        ─────────────────                                      ─────────────
   Human opens Razorpay dashboard                      Human hands cash back /
   → issues refund on pay_XXX                          bank transfer, off-system
   → money leaves merchant account                     → money leaves your pocket
              │                    │                              │
              │                    │ ⚠ NO CODE PATH ISSUES THIS   │ no gateway,
              │                    │   in either column           │ no event
              ▼                    │                              │
   Razorpay emits webhook          │                              │
   event: refund.processed         │                              │
              │                    │                              │
              ▼                    │                              │
  ┌──────────────────────────────┐ │                              │
  │ POST /api/payments/webhook/  │ │                              │
  │ payments/views.py:432        │ │                              │
  │  ① HMAC signature verified   │ │                              │
  │  ② event = refund.processed  │ │                              │
  │  ③ ✂ BRANCH COMMENTED OUT    │ │                              │
  │      logger.warning(…)       │ │                              │
  │  ④ return 200 (ACK, no retry)│ │                              │
  └──────────────┬───────────────┘ │                              │
                 ✗ DEAD END        │                              │
        ledger untouched           │                              │
        order still reads 'paid'   │                              │
        GST NOT reversed           │                              │
                 │                 │                              │
                 └────────► A HUMAN MUST NOW ACT ◄────────────────┘
                                   │
                                   ▼
        ┌────────────────────────────────────────────────┐
        │ Admin panel → order dialog → "Record a refund"  │
        │ Orders.tsx:~1250                                │
        │                                                 │
        │   [ ₹469.00 ] [ Reason (optional) ] [Refund ₹…] │
        │     amount        note                button    │
        │   ↑ blank = full outstanding balance            │
        │   ↑ smaller = partial (warned inline)           │
        └───────────────────┬─────────────────────────────┘
                            │ PATCH /api/orders/<id>/
                            │  { status:'refunded',
                            │    refund_amount?: '200.00',
                            │    refund_note?: '…' }
                            ▼
        ┌────────────────────────────────────────────────┐
        │ orders/views.py::update()  (admin-only)         │
        │                                                 │
        │ ① parse refund_amount BEFORE the transaction    │
        │    → non-numeric / <= 0 ⇒ 400, nothing written  │
        │ ② lock Order, then Payment (canonical order)    │
        │ ③ order.status = 'refunded'; order.save()       │
        │ ④ amount = refund_amount OR refundable_balance  │
        │ ⑤ amount > refundable ⇒ RAISE ValidationError   │
        │    (raise, not return — §"the rollback trap")   │
        │ ⑥ record_refund(..., source='admin',            │
        │                 mark_refunded=True)             │
        └───────────────────┬─────────────────────────────┘
                            ▼
  ╔══════════════════════════════════════════════════════════════════════╗
  ║  orders/refunds.py :: record_refund()   ← THE SINGLE WRITE PATH      ║
  ║  ──────────────────────────────────────────────────────────────────  ║
  ║  with transaction.atomic():                                          ║
  ║    Order.objects.select_for_update()        ← serialise concurrent   ║
  ║                                                refunds on one order  ║
  ║    ① amount <= 0                     → return None                   ║
  ║    ② reference already in ledger?    → return existing  (IDEMPOTENT) ║
  ║    ③ refundable_balance <= 0         → warn + return None            ║
  ║    ④ amount > refundable             → CLAMP (never negative GST)    ║
  ║    ⑤ tax = refund_tax_for(order, amount)     ── see box below ──     ║
  ║    ⑥ INSERT OrderRefund(amount, tax_amount, source, reference, note) ║
  ║         IntegrityError on unique reference → lost race, return theirs║
  ║    ⑦ RECOMPUTE from ledger (not +=) so totals self-heal:             ║
  ║         order.refunded_amount = Sum(refunds.amount)                  ║
  ║         order.refunded_tax    = Sum(refunds.tax_amount)              ║
  ║         order.refunded_at     = now()                                ║
  ╚═════════════════════════════════╤════════════════════════════════════╝
                                    │
                fully_refunded = refunded_amount >= total_amount
                                    │
       ┌──────────── YES ───────────┴────────── NO (partial) ──────────────┐
       ▼                                                                    ▼
  status        = 'refunded'                        mark_refunded=True (ADMIN):
  payment_status= 'refunded'                          → status/payment_status
  email → "Refund processed"                            STILL flip to 'refunded'
  …but ONLY from the gateway path,                    mark_refunded=False (gateway):
  which is disabled ⇒ in practice                       → order left untouched,
  NO EMAIL IS SENT (see gap #2)                           logged for a human
       │                                                          │
       └───────────────────────┬──────────────────────────────────┘
                               ▼
  ┌────────────────────────────────────────────────────────────────────┐
  │ DOWNSTREAM READERS (all read the same ledger)                      │
  │                                                                    │
  │  GST        refunded_totals_between() → bucketed by REFUND date,   │
  │             orders/refunds.py:139       NOT order date             │
  │  Dashboard  today/mtd_gst_refunded, net_gst → Dashboard.tsx:190    │
  │  Analytics  rollups (analytics/0005_rollup_refunds)                │
  │  CSV export 'Refunded', 'GST Reversed', 'Net GST' columns          │
  │  Admin list status badge + "₹X refunded (partial)"  ← added today  │
  │  Admin dialog refunded block + per-refund rows                     │
  │  Customer   MyOrders card: always-visible "Refunded ₹X" row,       │
  │             partial notice, instalment rows  ← added today         │
  └────────────────────────────────────────────────────────────────────┘
```

---

## The API contract

`PATCH /api/orders/<id>/` — admin/staff only.

| Field | Required | Meaning |
|---|---|---|
| `status: 'refunded'` | ✅ | The instruction. An amount alone records nothing. |
| `refund_amount` | ❌ | How much went back. **Omit ⇒ the whole outstanding balance** (the pre-2026-08-01 behaviour, so old clients are unaffected). |
| `refund_note` | ❌ | Reason, truncated to 255 chars. |

**400s** when `refund_amount` is non-numeric, `<= 0`, or exceeds `refundable_balance`.

**Instalments:** re-sending an explicit `refund_amount` on an order that is *already*
`refunded` records a **further** partial. Without an explicit amount, a repeat PATCH
is a no-op (this is what keeps the old double-click-safe behaviour intact).

**Customer response** (`OrderDetailSerializer` / `OrderListSerializer`) already
carries `refunded_amount`, `refunded_tax`, `refunded_at` and `refunds[]` — it is the
customer's own money, so it was never admin-only.

---

## The GST apportionment

`refund_tax_for(order, amount)` — `Backend/orders/pricing.py:109`:

```
goods = subtotal − discount            (+ tax, if legacy tax_inclusive=False)

  ① GOODS FIRST      goods_refunded = min(refund_amount, goods)
                     → shipping isn't taxed, so a refund is assumed to be
                       returning goods until goods run out; the excess is
                       untaxed delivery. Never over-reverses.

  ② BLENDED RATE     tax = order.tax × goods_refunded / goods
                     → a refund gives an amount, not a line. A FULL refund is
                       exact (reverses order.tax precisely). A PARTIAL on a mixed
                       0%/5% order is an ESTIMATE — now reachable on purpose,
                       accepted as the price of the feature.

  ③ CAPPED           min(tax, order.tax − order.refunded_tax)
                     → repeated partials can never reverse more GST than
                       was collected.
```

Worked example (the `paid_order` test fixture — ₹400 goods @5% incl. ₹19.05 GST,
₹69 untaxed delivery, ₹469 total):

| Refund | GST reversed | Why |
|---|---|---|
| ₹469.00 (full) | ₹19.05 | exact — the whole tax charged |
| ₹200.00 | ₹9.53 | 200/400 of the goods |
| ₹400.00 | ₹19.05 | all goods; delivery excess adds nothing |
| ₹200 then ₹269 | ₹19.05 total | capped — instalments can't over-reverse |

---

## Two traps worth knowing about

**The rollback trap.** The `refund_amount > refundable` check happens *after*
`order.save()` has already written `status='refunded'` inside the same transaction.
Returning a `Response(400)` there would **commit** that write, leaving an order
marked refunded with no ledger row and no GST reversed. It raises
`DRFValidationError` instead, which rolls the transaction back and still renders as
a 400. Pinned by `test_refund_amount_above_the_balance_is_rejected`.

**Status no longer implies amount.** `mark_refunded=True` deliberately breaks the
old invariant. Anything reading `status`/`payment_status` without also reading
`refunded_amount` is now capable of lying. The three UI surfaces were fixed today;
new ones must follow the same rule.

---

## Why a ledger, not two columns on `Order`

`OrderRefund` (`Backend/orders/models.py:290`):

1. **Refunds can be partial and repeated** — each reverses its own slice of GST.
   No longer hypothetical: the admin can settle in instalments.
2. **GST is reversed in the period the refund happens, not the period of the sale.**
   A credit note reduces output tax in its own month. Attributing a March refund
   back to a January sale would retroactively change a return already filed.
   Reporting buckets by `OrderRefund.created_at`.
3. **Idempotency.** `reference` (the gateway `rfnd_…` id) is unique, so a
   redelivered webhook is a no-op instead of double-reversing tax. *Dormant while
   manual-only — admin rows carry `reference=None` — but it is what makes
   re-enabling the webhook safe.*

---

## Known gaps

**1. It all depends on the admin remembering.** No webhook, no reconciler, no nag.
Issue a refund at Razorpay and forget to record it, and the order reads `paid`
forever with its GST un-reversed. Nothing will catch it. This is the largest risk in
the design, and it is a process risk, not a code one.

**2. The customer is never emailed about a refund.** ⚠ *Found during this review.*
`_on_commit_customer_email('refunded', …)` is called **only** from
`mark_payment_refunded` (`payments/services.py:382`) — the disabled gateway path. The
admin path in `orders/views.py::update()` sends nothing; its only side-effect email
is for a newly-added tracking number. So today a customer learns of their refund
solely by opening My Orders. Two things would need doing:
   * call the refund email from the admin path, and
   * put the **amount** in it — the template (`payments/emails.py:90`) says only
     *"We've processed a refund for order {number}"*, which would misdescribe a
     partial.

**3. Nothing reconciles refunds.** `resync_payments` only looks for
`status == 'captured'` (`resync_payments.py:99`) and ignores the payment entity's
`amount_refunded`; L3 reconcile only scans pending/processing orders. A
refunded-but-`paid` order is invisible to both. Captures have a backstop; refunds
have none.

**4. Refunding STRANDS THE STOCK, with no way back.** ⚠ *Sharpened 2026-08-01 after
an external audit.* `record_refund` never calls `restore_order_stock` — its
docstring defers restocking to "the admin/cancel flow" — but `'refunded'` is in
`UNCANCELLABLE_STATUSES` (`orders/views.py:153`), so once the status flips **there
is no cancel flow left to reach**. The inventory is lost silently and permanently.

The audit framed this as mainly a *gateway* problem. That half is now moot — the
`refund.processed` branch is disabled, so nothing auto-flips an order any more. But
the admin half got **worse**, not better:

* Before, only a FULL refund flipped the status, so the trap needed a complete refund.
* Now `mark_refunded=True` flips it on **any** amount. Recording a ₹1 partial on a
  ₹5,000 order makes that order terminal and strands **all** of its stock.

The order of operations is the only defence: `cancelled → refunded` restocks
correctly, `refunded → cancelled` is blocked. That is an easy thing to get backwards
under time pressure, and nothing warns you.

Two candidate fixes: restock inside `record_refund` on the transition into
`refunded`, or drop `'refunded'` from `UNCANCELLABLE_STATUSES` so the existing cancel
path stays reachable. The first needs care — partial refunds don't say *which* items
came back, so "restock what the order consumed" is only obviously right for a full
refund.

**5. Order list queries don't prefetch `refunds`.** Both serializers nest
`refunds = OrderRefundSerializer(many=True)`, but neither queryset
(`orders/views.py:221` admin, `:240` customer) prefetches them — +1 query per order
per page. Now slightly worse than when the audit found it: the customer's My Orders
card renders individual refund rows for instalments, so the data is actually read on
every page load. Fix is `'refunds'` added to both `prefetch_related(...)` calls.

**6. Prod webhook secret still unset** (`RAZORPAY_LIVE_WEBHOOK_SECRET`, as of
2026-07-25). Moot for refunds now, but still costs instrument details on normal
orders and delays missed-capture healing to the ~20 min L3 cadence.

---

## Re-enabling the gateway path

1. Un-comment the `services.mark_payment_refunded(...)` call in
   `payments/views.py::_dispatch_webhook_event`; drop the `logger.warning`.
2. Un-comment `test_refund_webhook_without_order_id_still_refunds` and remove
   `test_refund_webhook_is_ignored_in_manual_only_mode`, which asserts the opposite.
3. Set `RAZORPAY_LIVE_WEBHOOK_SECRET` in prod and subscribe `refund.processed`.

Decide at that point what a **gateway partial** should do. It currently leaves the
order untouched (`mark_refunded=False`) while an admin partial flips it — a
deliberate asymmetry (unattended money movement stays visible as needing attention),
but worth a conscious re-confirmation rather than inheriting it by accident.

Still open, if genuine two-way management is the goal:

* **Teach resync/reconcile to read `amount_refunded`** — the missing backstop.
* **An "Issue refund" button** calling `client.payment.refund(payment_id, {...})`
  and recording the returned `rfnd_…` as `reference`: one action, money moves *and*
  the ledger is written, with the follow-up webhook deduping cleanly. Irreversible
  outward money movement, so it wants a confirm step and a permission tighter than
  the general admin PATCH.

---

## File map

| Concern | Location |
|---|---|
| Ledger write path | `Backend/orders/refunds.py` (`record_refund`, `mark_refunded` flag) |
| `OrderRefund` model | `Backend/orders/models.py:290` |
| GST apportionment | `Backend/orders/pricing.py:109` (`refund_tax_for`) |
| Admin → ledger (**the live path**) | `Backend/orders/views.py::update()` |
| Customer-facing fields | `Backend/orders/serializers.py` (`refunds`, `refunded_amount`, …) |
| Webhook handler (**refund branch disabled**) | `Backend/payments/views.py:432` |
| Gateway → ledger (retained, unreachable) | `Backend/payments/services.py:311` |
| Customer email (**not wired to admin path**) | `Backend/payments/emails.py:90` |
| Tests | `Backend/orders/test_refunds.py` (28), `Backend/payments/test_razorpay_and_payment_flow.py` |
| Admin UI — amount field + dialog + table badge | `Admin Panel/…/src/pages/Orders.tsx` |
| Admin API types | `Admin Panel/…/src/api/orders.ts` |
| Customer UI — refunded row | `Frontend/nidhi-brand-forge/src/pages/MyOrders.tsx` |
| Customer API types | `Frontend/nidhi-brand-forge/src/lib/api/orders.ts` |

## Changelog

* **2026-08-01 (c)** — Combo cancellation now restocks from the order's
  `OrderItemComponent` snapshot instead of the live combo recipe
  (`orders/views.py::restore_order_stock`), falling back to the recipe only for
  historical lines that predate the snapshot. 2 regression tests added in
  `orders/test_checkout_and_ops.py`.
* **2026-08-01 (b)** — Partial refunds. `refund_amount` added to the admin PATCH
  (optional, defaults to full balance); `record_refund(mark_refunded=…)` lets an
  admin partial flip the order to `refunded`; amount surfaced on the admin table,
  admin dialog and the customer's My Orders card; 8 tests added
  (`orders/test_refunds.py`, 28 passing).
* **2026-08-01 (a)** — Manual-only refunds. `refund.processed` branch commented out
  in `payments/views.py`; webhook test swapped for one asserting the event is
  ignored; CLAUDE.md, `docs/ORDER_LIFECYCLE.md`, `docs/ANALYTICS.md`, `docs/API.md`
  and `RAZORPAY_GO_LIVE_CHECKLIST.md` updated to match.

## Verification

* `Backend/`: **936 passed**, 1 failed, 8 skipped. The failure is
  `orders/test_concurrency.py::test_G4` ("database table is locked") — the known
  SQLite limitation documented in CLAUDE.md; the 8 skips are the retired Policy API.
* `npx tsc --noEmit` clean in both the admin panel and the customer frontend.
