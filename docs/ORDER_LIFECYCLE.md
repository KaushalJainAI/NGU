# Order Lifecycle

Everything that happens from "Place Order" to delivery, including pricing rules, stock
management, and cancellation.

---

## Status Workflow

```
PENDING ──▶ CONFIRMED ──▶ PROCESSING ──▶ SHIPPED ──▶ DELIVERED
   │              │              │              │
   └──────────────┴──────────────┴──────────────┴──▶ CANCELLED
```

`DELIVERING` is an intermediate state used by some delivery integrations, sitting between
`SHIPPED` and `DELIVERED`. Orders in `delivered`, `cancelled`, or `delivering` cannot be
cancelled.

Status transitions are driven by admin updates (`PATCH /api/orders/{id}/`). There is no
automatic status progression — the admin panel's order detail view provides the dropdown.

---

## Order Creation Flow (`POST /api/orders/`)

`OrderViewSet.create` in `orders/views.py`. The entire flow is atomic with one deliberate
exception noted below.

### 1. Pre-transaction validation

```
Validate cart exists and has items
  └── If no cart or empty cart → 400

Validate coupon (if provided)
  └── Check is_active, valid_until, max_usage, minimum_order_amount
  └── If invalid → 400
```

Coupon validation happens **before** the transaction to fail fast without locking any rows.

### 2. Build order items (pre-transaction)

Cart items are read and validated outside the transaction. For each cart item:

| Item type | Price source | Weight source | Stock source |
|-----------|-------------|---------------|-------------|
| Product with variant | `variant.final_price` | `variant.formatted_weight` | `variant.stock` |
| Product without variant (legacy) | `product.final_price` | `product.formatted_weight` | `product.stock` |
| Combo | `combo.final_price` = `discount_price` or the DERIVED MRP (Σ component `variant.price × qty`) | `f"{combo.weight}{combo.unit}"` | min over components of `variant.stock // qty` |

If any item's available stock is less than the requested quantity, the entire request is
rejected with a `400` before the transaction opens.

### 3. Pricing calculation

Applied to the collected `subtotal`:

```
subtotal            = Σ (item_price × quantity)
total_discount      = coupon.discount_for(subtotal)      # percent OR flat ₹, clamped to subtotal
discounted_subtotal = subtotal − total_discount
shipping_charge     = ₹0   if discounted_subtotal ≥ FREE_SHIPPING_THRESHOLD
                    = SHIPPING_CHARGE  otherwise            # NET, GST-exclusive
shipping_tax        = shipping_charge × SHIPPING_TAX_RATE / 100   # 18%, ADDED on top
tax                 = Σ (discounted_line_total × rate / (100 + rate))   # rate = per-line tax_rate
total_amount        = discounted_subtotal + shipping_charge + shipping_tax
```

**Key points:**
- **Prices are GST-INCLUSIVE (MRP).** The price the admin enters and the customer
  sees is the final amount payable; GST is *extracted* from it for disclosure, never
  added on top. `tax` is therefore a component of `subtotal`, **not** a term in
  `total_amount` — see `orders/pricing.py::extract_tax`, the single implementation
  every surface (cart summary, coupon preview, order creation) must call.
- ⚠ **DELIVERY USES THE OPPOSITE CONVENTION TO GOODS.** The fee is quoted **net**
  and GST is **added on top** at `SHIPPING_TAX_RATE` (18%, SAC 9968 courier
  services). So `shipping_tax` **is** a term in `total_amount`, while the goods
  `tax` is not. Mixing the two up is the single easiest way to mis-bill this
  system — use `pricing.add_tax`/`shipping_tax_for` for delivery and
  `pricing.extract_tax` for goods, never the reverse.
- **`Order.total_tax` (= `tax + shipping_tax`) is the output-tax figure**, not
  `tax`. Every reporting surface (rollup `gst_collected`, dashboard tiles, daily
  digest, CSV export, invoice GST summary) must read it, or the liability is
  under-stated by the GST on every delivery charged.
- Free shipping threshold is checked against the **post-discount** subtotal;
  free shipping carries no `shipping_tax`.
- `SHIPPING_CHARGE` (default ₹59, **net**), `SHIPPING_TAX_RATE` (default 18),
  `FREE_SHIPPING_THRESHOLD` (default ₹499, `>=` so ₹499 itself ships free), and `DEFAULT_TAX_RATE` (default 5%,
  used only when a product/combo has no `tax_rate`) are env-configurable — see
  `spices_backend/limits.py`. ⚠ An existing `.env` that still pins
  `SHIPPING_CHARGE=69` overrides the default and will bill ₹69 + 18%.
- Goods tax is extracted from the **post-discount** line totals; the delivery fee
  is taxed separately and is not affected by coupons.
- Orders placed before delivery was taxed carry `shipping_tax=0` and still
  reconcile — no backfill is needed or wanted.
- **A COMBO is a mixed supply, taxed per component.** A combo has no `tax_rate` of
  its own. Its final line amount is split back across its components linearly by
  MRP share, and each part's GST extracted at its OWN product's rate:

  ```
  w_i   = variant_i.price × qty_i          # component weight
  a_i   = line_amount × w_i / Σw           # line_amount is POST combo-discount AND coupon
  tax_i = a_i × rate_i / (100 + rate_i)    # rate_i = component product's tax_rate
  ```

  Allocating once at the end is exact rather than a shortcut: both the combo
  discount and the coupon are linear in the same weights. The rounding residual
  goes to the largest component so `Σ a_i` equals the charged line total to the
  paisa — otherwise the invoice's GST SUMMARY would not reconcile. Each part is
  persisted as an `OrderItemComponent`; `OrderItem.tax_rate` holds only the
  blended effective rate, for display. See `pricing.allocate_combo_components`,
  and `pricing.combo_line_tax` for the cart/coupon previews, which MUST route
  through the same allocator or the quote and the bill will disagree.
- **GST breakup.** Each `OrderItem` snapshots the `tax_rate` it was charged at, so a
  bill can always reproduce its per-slab split even after the product is re-rated.
  Combo lines instead contribute one row per `OrderItemComponent`; combo lines with
  no components are pre-split history and fall back to the stored line rate.
  `orders/pricing.py::group_tax_by_rate` buckets lines into `{rate, taxable_value,
  tax_amount}` rows; `order_tax_breakdown(order)` does it for a placed order. These
  rows drive the cart summary, the checkout page, "My Orders", the admin order
  dialog and the invoice's **GST SUMMARY** table — one implementation, so they
  cannot disagree. `taxable_value` is the NET (pre-GST) value, which is what a GST
  return wants. This is a RATE-SLAB breakup; the CGST/SGST/IGST split is applied on
  top of these rows from the order's place of supply — see below.
- **HSN classification.** Each `OrderItem` also snapshots `hsn_code`, for exactly
  the same reason as `tax_rate`: re-classifying a product next year must not
  rewrite last year's invoice. The rate says WHAT was charged, the code says WHY,
  and neither can be derived from the other — 5% spans 0904, 0909 and 0910, while
  one heading can change slab when the law does (2103 went 12% → 18% on
  2025-09-22). A COMBO line carries **no** code (a bundle is a mixed supply with
  no single heading); its `OrderItemComponent` rows carry theirs instead. The code
  is printed as its own column on the tax invoice — Rule 46(g) requires it — and
  `orders/gst_reports.py::hsn_summary` aggregates it into the HSN-wise summary
  GSTR-1 Table 12 is filed from. An unclassified product bills a BLANK code, never
  a guessed one, and those sales surface under an explicit "NOT CLASSIFIED" row so
  the gap is visible rather than silently missing. The curated code list, and the
  statutory rate published for each code, live in `products/hsn.py`; the admin
  panel shows that rate beside the rate actually charged and flags a
  disagreement — but **never applies it**, because what is charged is the owner's
  decision.
- **`Order.shipping_cost`** is what the *courier* charged us, entered by the admin
  after dispatch (₹0 = not recorded). It is **admin-private**: `OrderMoneyMixin.
  to_representation` strips it from every non-staff response, the same way
  `delivery_bill` is protected. It never affects `total_amount` — it exists only to
  turn delivery margin into a real number instead of a guess.
- **COD cash is confirmed by hand.** A COD order takes no money at checkout, so
  `payment_status` stays `pending` and `Order.cod_paid_at` is NULL until an admin
  ticks **"Paid in cash"** (PATCH `cod_paid: true`). That stamps `cod_paid_at` +
  `cod_confirmed_by` and flips `payment_status` to `paid`. Deliberately **not** a
  side effect of marking the order delivered — couriers usually remit days later,
  and auto-ticking would record cash that has not arrived.
  - It is a **cash** fact, never a tax one: GST accrued at order date (time of
    supply for goods is the invoice, not the payment) and must not move when the
    money turns up.
  - Until it is ticked, a COD order **cannot be refunded** — there is no proof
    money was received, and recording one would reverse GST on cash that never
    came in. Before this existed a genuine COD return could not be recorded at
    all, so its GST stayed owed forever.
  - Un-ticking is allowed for a misclick (logged at WARNING) but refused once a
    refund has been recorded against the payment.
  - Reporting: `cod_pending_*` on the dashboard is a live point-in-time figure
    (dispatched COD orders not yet confirmed = cash the courier holds);
    `DailySalesRollup.cod_collected` buckets confirmations by **confirmation
    date**, like refunds, because the order being settled is rarely that day's.

- **COD placement is guarded (AP7b/S7).** A COD order reserves stock with no
  money down, so checkout requires all three *before* the transaction: a
  verified email (`email_verified`, 400 `email_not_verified`), a total at or
  under `COD_MAX_VALUE` (default ₹5,000, 400 `cod_value`), and fewer than
  `COD_MAX_OPEN` (default 3) unfinished COD orders in
  `pending/confirmed/processing/shipped/delivering` (400 `cod_limit`). Tunables
  live in `spices_backend/limits.py` (`COD_OPEN_STATUSES` documents what counts
  as open). Tests: `orders/test_cod_guard.py`.
- **Refunds reverse GST.** `orders.OrderRefund` is the ledger; `orders/refunds.py::
  record_refund` is the single write path. ⚠ **Since 2026-08-01 refunds are
  MANUAL-ONLY:** the `refund.processed` webhook branch is commented out, so the
  admin's entry in the order dialog is the *only* way a refund reaches the ledger —
  for online refunds issued at Razorpay as well as COD returns. Each row stores the money returned and the `tax_amount` it reverses,
  computed by `pricing.refund_tax_for`: refunds apply to **goods first, delivery
  last** (the courier was still paid), reverse the delivery's own 18% once the
  refund reaches into the fee, are apportioned at the order's blended rate across
  goods slabs when partial, and are capped so repeated partials can never reverse
  more GST than was collected.
  A gateway refund is idempotent on its `rfnd_…` reference. Reporting subtracts
  these **in the period the refund happened**, not the period of the sale.
- **Partial refunds (2026-08-01).** The admin PATCH takes an optional
  `refund_amount` (omit it and the whole outstanding balance goes back). Any
  admin-entered amount sets `status='refunded'`, so ⚠ **the flag means "a refund
  was recorded", NOT "the whole order came back"** — always render
  `refunded_amount` beside it. Re-sending an explicit amount on an already-refunded
  order records a further partial, so a refund can be settled in instalments. An
  unattended **gateway** partial still leaves the order's status alone
  (`record_refund(mark_refunded=False)`) so it stays visible as needing a human.
- **Only an order whose money was actually received can be refunded**
  (2026-08-02, widened 2026-08-04). `OrderViewSet._is_refundable_payment` gates the
  admin PATCH. Two ways an order qualifies, and `payment_status` must be in
  `{paid, refunded}` either way (`refunded` included so an instalment on an
  already-refunded order isn't stranded):

  | `payment_method` | Refundable when |
  |---|---|
  | `ONLINE` / `razorpay` | `payment_status` in `{paid, refunded}` |
  | `COD` | **`cod_paid_at` is set** (the "Paid in cash" tick) *and* `payment_status` in `{paid, refunded}` |

  Everything else 400s **before anything is written** (the COD branch adds a hint
  telling the admin to tick "Paid in cash" first). Rationale: a ledger row reverses
  GST, so recording one against money that never reached us — COD cash still with
  the courier, or a pending/failed/rejected order — would understate what is owed to
  the government. ⚠ Do **not** re-narrow this to ONLINE-only: until the COD tick
  existed, a genuine COD return could not be recorded at all and its GST stayed owed
  forever. That was the bug the tick closes (see the COD bullet above).
  An order with nothing left to give back is likewise a 400, not a silent success;
  accepting it used to leave the order reading `refunded` with an empty ledger.
- **A refund restocks (2026-08-02).** Money back means goods back, so
  `record_refund` calls `restore_order_stock`. Without it every return silently
  ratcheted inventory down — the refund path could not restock afterwards either,
  because `refunded` is in `UNCANCELLABLE_STATUSES`. Consequences to know:
  - `restore_order_stock` is now **idempotent**, stamping `Order.stock_restored_at`
    on its first run. Three paths can restock the same order (customer cancel,
    admin cancel, L3 stuck-payment auto-cancel, and now a refund), and crediting
    twice invents stock that never existed. It returns `True` only when it really
    restocked.
  - A **partial** refund returns the WHOLE order's stock, once. An amount alone
    doesn't say which lines came back, and under-restocking a genuine return is the
    worse error. Correct a mis-restock by editing variant stock directly.
- **Place of supply drives the tax heads.** For B2C goods the place of supply is the
  delivery address (CGST Act s.10(1)(a)). `Order.place_of_supply_state_code` is the
  two-digit GST state code of the destination, **resolved and frozen at checkout** by
  `orders/place_of_supply.py`:
  1. `shipping_state` — the checkout form's own state field, matched against full
     names, abbreviations ("M.P."), and Devanagari.
  2. failing that, a scan of the `shipping_address` blob for a full state name
     (abbreviations are deliberately *not* scanned there — "up" and "as" are
     ordinary words, and a false match is a tax bug).
  3. failing that, **the seller's own state** — the order bills intra-state, exactly
     as every order did before this existed.

  Equal to `SELLER_STATE_CODE` ⇒ CGST + SGST (half each); anything else ⇒ IGST for
  the identical amount. **The place of supply never changes the tax TOTAL**, only
  which government is credited and which GSTR-1 table the sale lands in — which is
  why the old hard-coded behaviour was mis-classifying, not under-collecting.

  It is a **snapshot, never a lookup**. An admin editing `shipping_address` does not
  re-derive it, or a courier-detail fix would silently re-head an invoice already
  filed. A misdetected destination is corrected explicitly by PATCHing
  `place_of_supply_state_code` (staff only, validated against the published state
  list, logged).

  **Blank = historical.** Rows written before the column existed keep `''`, which
  `is_interstate()` reads as intra-state, so their reprinted bills still match the
  returns they were filed on. They are deliberately *not* backfilled.

  Surfaces: the invoice's "Place of Supply" line and its GST SUMMARY head columns,
  the credit note (which reverses under the heads it was charged under), the
  `place_of_supply` block on order responses, and the `Place of Supply / POS Code /
  CGST / SGST / IGST` columns on the accountant CSV export.
- `Order.tax_inclusive` records the convention. It is `True` for every order placed
  since the switch; orders written before it are backfilled `False` (migration
  `orders/0014`) and keep their tax-added totals untouched. `orders/invoice.py`, the
  storefront "My Orders" card, and the admin order dialog all branch on this flag so
  a reprinted historical bill still reconciles.

### 4. Atomic transaction

Everything inside `with transaction.atomic()`:

#### 4a. Create Order row

```python
Order.objects.create(
    user=request.user,
    subtotal=subtotal,
    discount_amount=total_discount,
    shipping_charge=shipping_charge,
    tax=tax,                 # contained in subtotal, NOT added to total_amount
    total_amount=total_amount,
    coupon=coupon,
    status='pending',
    ...address fields from serializer...
)
```

#### 4b. Create OrderItems with proportional discounts

The total discount is distributed to line items proportionally to their share of the
subtotal, so the numbers always add up:

```python
item_discount = (item_total / subtotal) × total_discount
discounted_item_price = item_price − (item_discount / quantity)
discounted_item_total = discounted_item_price × quantity
item_tax = discounted_item_total × rate / (100 + rate)   # GST contained in the line
```

`Order.tax` is the **sum of the line taxes**, so the rows and the header always
agree to the paisa.

Each `OrderItem` stores a **snapshot** of `product_name` and `product_weight` at the time
of order. Historical orders remain accurate even if the product is later renamed, repriced,
or deleted.

#### 4c. Stock decrement (variant-first, with product mirror)

Stock lives on `ProductVariant`. `Product.stock` is a legacy mirror kept in sync for
product listing pages.

```
For each product line item:
  if variant:
    variant_updates[variant.pk] += quantity
    if variant.is_default:
      product_updates[variant.product_id] += quantity   ← mirror
  else (legacy, no variant):
    product_updates[product.pk] += quantity

Batch reduce variant stock (select_for_update to prevent race conditions)
Batch reduce product stock (clamp at 0, never go negative)
```

Combos have no `stock` field of their own, but they are **not** free of inventory:
a combo line draws down each component SIZE's `variant.stock` by `qty × line_qty`,
and cancelling restores exactly that (`restore_order_stock`). How many can still be
sold is `min(variant.stock // qty)` over the components, and the low-stock alert
fires when that buildable count crosses the combo's `low_stock_threshold`.

The `select_for_update()` lock on variants and products prevents two concurrent orders
from both seeing sufficient stock and both succeeding.

#### 4d. Coupon usage count

```python
coupon.usage_count = F('usage_count') + 1
coupon.save(update_fields=['usage_count'])
```

`F()` expression avoids a race condition where two orders applying the same coupon
simultaneously both read `usage_count=1`, write `2`, and report `2` when the correct
answer is `3`.

#### 4e. Cart clearing

The cart is cleared when the order is **complete**, not merely created:

```python
if order.payment_method == 'COD' or order.payment_status == 'paid':
    cart.items.all().delete()
```

- **COD** and **zero-total** (fully-couponed, `payment_status='paid'`) orders are complete at
  placement, so the cart is cleared **inside** the transaction. If the transaction rolls back
  (e.g. stock ran out mid-flight), the cart is preserved — the customer's items are not lost.
- A **pending ONLINE** order deliberately **keeps** the cart until its payment is captured
  (`payments.services.mark_payment_captured` clears it then). This means an abandoned or failed
  payment never strands the customer with an empty cart — "Proceed to checkout" still works.

To stop reserved stock leaking across retries, a fresh checkout first **supersedes** any earlier
pending ONLINE order from the same user: it cancels that order (`payment_status='rejected'`) and
restocks it under the cart lock before reserving stock for the new order. This guarantees exactly
one open ONLINE order per user and subsumes the old double-submit guard (which previously relied on
the cart being emptied at creation).

### 5. Post-transaction (best-effort)

After the transaction commits:

```python
record_purchase_events(order)   # analytics — never blocks or fails the order
```

Analytics outages do not prevent order creation.

### 6. Response

```json
{
  "message": "Order created successfully",
  "order_id": 42,
  "order_number": "ORD-000042",
  "total_amount": 540.75,
  "order": { ...OrderDetailSerializer... }
}
```

**Order number format:** `ORD-` prefix + zero-padded 6-digit primary key. This is
generated after the transaction and is returned in the response only — it is not stored
in the database (the PK is the canonical identifier).

---

## Order Cancellation (`POST /api/orders/{id}/cancel/`)

Cancellation is fully atomic. The same select-for-update locking pattern as creation:

```
Lock order row (select_for_update)
Check status: delivered / cancelled / delivering → reject

Restore stock:
  variants: stock += quantity (+ product mirror for default variants)
  products: stock += quantity  (legacy lines)
  combos:   stock += quantity  (if combo model has stock field)

order.status = 'cancelled'
order.cancelled_at = now()
```

**Who can cancel:** the order owner or any `is_staff` user.

---

## Tax Invoices (`orders/invoicing.py`)

An invoice is a **document that is issued**, not a view of an order rendered on
demand. It is a row in `Invoice` — one per order, `OneToOneField`, `on_delete=PROTECT`.

### When one is issued

| Payment method | Trigger |
|---|---|
| ONLINE / razorpay | **Payment captured** (`payments.services.mark_payment_captured`) |
| Zero-total (fully coupon-waived) | **At placement** — already `paid`, no capture is coming |
| COD | **At DISPATCH** — status reaching `shipped` / `delivering` / `delivered` |

A **cancelled order is never invoiced** — nothing was supplied, and a capture
against a cancelled order is an exception routed to a refund, not a sale.

Under the hood `invoice_is_due` asks one payment-method-agnostic question — *did
the supply happen?* — and accepts either piece of evidence:

- **money was received** (`payment_status` in {`paid`, `refunded`}), or
- **goods went out** (`status` in {`shipped`, `delivering`, `delivered`}).

⚠ `refunded` counts, and must: a refund can only be recorded against money
actually taken, so a refunded order was definitely supplied. Excluding it would
leave historical refunded orders unnumbered and their **credit notes with no
serial to cite** — they would fall back to the `ORD-` order reference.

COD is not *waiting* on the "Paid in cash" tick: the bill has to travel with the
goods and the courier remits days later, so dispatch normally fires first. But
confirmed cash on an undispatched COD order is also proof of supply, so that path
invoices too rather than leaving it uninvoiced. GST on goods accrues at the
invoice, not at the payment.

Issuing is idempotent (`invoice_is_due` → `issue_invoice`) and never raises —
`maybe_issue_invoice` swallows and logs failures, because nothing about document
generation may roll back a payment capture. Orders missed that way are picked up by
`python manage.py backfill_invoices` (also the migration path for historical orders;
processes oldest-first so the series follows the order of supply).

### The number

`NM/25-26/000123` — prefix (`INVOICE_NUMBER_PREFIX`, default `NM`), Indian financial
year (April–March), then a sequence drawn from `InvoiceCounter` **under a row lock**.
15 characters, within the GST limit of 16, using only permitted characters.

The series restarts each April and is **continuous within the year**. It is
emphatically not `ORD-{order.id}`, which skipped every abandoned checkout and
cancelled order and so could never be a lawful series.

### What is frozen

`Invoice.snapshot` (JSON) holds everything the PDF prints — seller identity, buyer
identity, lines with HSN, totals, GST summary already split into CGST/SGST or IGST,
and the resolved place of supply. `generate_invoice_pdf(invoice)` reads **only** this.

This is what stops reprints mutating. Changing `SELLER_ADDRESS`, an admin editing
`shipping_address`, a product being re-rated, or the seller registering in a new
state (which would flip `is_interstate`) cannot alter a bill already handed over.

Two bands are deliberately **live**, and say so on the page: the order's current
status, and any refunds recorded since (each citing its credit note serial). They
annotate the document; they never restate it.

### Downloading

`GET /api/orders/{id}/invoice/` is a **reprint**. It returns `409` with
`code: "invoice_not_issued"` when no invoice exists — an unpaid order can no longer
produce a page headed TAX INVOICE. Order responses carry `invoice: {number,
issued_at} | null` so both UIs hide (storefront) or disable (admin) the download
until there is something to download.

File name: `invoice-NM-25-26-000123.pdf` (the serial, not the order id).

⚠ An order with an issued invoice **cannot be purged** from the Recycle Bin
(`Invoice.order` is `PROTECT`); `purge_recycle_bin` reports it as skipped.

---

## Fulfilment Documents (admin-only)

Two documents support order fulfilment, both gated to staff:

- **Packing slip** — `GET /api/orders/{id}/packing-slip/` renders a picking/packing
  sheet PDF (`orders/invoice.py`).
- **Delivery bill** — `GET/POST/DELETE /api/orders/{id}/delivery-bill/` manages the
  courier/delivery receipt. Stored on **private FileSystemStorage** (`Order.delivery_bill`,
  `PRIVATE_MEDIA_ROOT`) with a UUID filename — it is served **only** through this staff-gated
  endpoint, never a public CDN URL, and is never shown to customers. Uploads are magic-byte
  sniffed (`_delivery_bill_bytes_match`) and `delivery_bill_uploaded_at` records the time.

---

## Coupon Rules

| Check | Detail |
|-------|--------|
| `is_active` | Coupon must be active |
| `valid_until` | Must be before expiry date |
| `max_usage` | If set, `usage_count < max_usage` |
| `minimum_order_amount` | Subtotal (pre-discount) must meet minimum |
| Discount type | Percentage only (`discount_percent` 1–100) |

Coupons are case-insensitive (`code__iexact`). Pre-validation via
`POST /api/auth/validate-coupon/` returns the full breakdown before order creation so the
checkout UI can show exact savings without committing an order.

---

## Stock Management — Source of Truth

```
ProductVariant.stock  ←── source of truth for all new products
       │
       └── is_default=True variant mirrors to Product.stock
                                      │
                                      └── used by listing pages & legacy cart lines
```

**Why the mirror?** Product listing pages and the old cart API read `Product.stock` for
display. Keeping them in sync avoids a full migration of all list queries. The mirror is
best-effort on the `Product.stock` side — it is clamped at 0 if it would go negative
(drift can accumulate from direct SQL edits; the canonical count is always on the variant).

**Combos never have stock decremented** — availability is `is_active` only. Attempting to
call `.stock` on a combo inside a batch update raises `FieldDoesNotExist`, which is why
combo lines are explicitly excluded from the decrement loop.

## Improvement plan notes (2026-10-01)

- `Order.courier_name` + `Order.tracking_url` are set on the admin PATCH (single call with the tracking number, so one shipped email). The shipped email names the courier and carries the tracking link; a link must be http(s) and at most 500 characters.
- Recording a refund (`status=refunded` + `record_refund`) emails the customer via `send_refund_recorded_email` with the recorded amount, and issues a `CN/<FY>/<seq>` credit note when the order has an invoice. Cancelling an invoiced order while no money is held issues a `cancellation` credit note for the remaining invoice value.
- `place_of_supply_state_code` cannot change once an invoice exists (400).
