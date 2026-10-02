# NGU — Recent Changes & Design Decisions

*Covering the work in the current uncommitted working tree, 2026-08-01 → 2026-08-04.
Last committed state across all three repos is 2026-07-25; everything below is
staged-but-unshipped code across `Backend/`, `Frontend/nidhi-brand-forge/` and
`Admin Panel/e-commerce-command-center/`.*

---

## 1. What this body of work is

One theme, worked end to end: **the store had the money right and the paperwork
wrong.** Every rupee charged to a customer was correct, but almost none of the
fields a GST return actually asks for existed — no HSN codes, no place of supply,
no invoice document, no credit note, no refund ledger, an untaxed delivery fee,
and COD cash that the system could not see at all.

The trigger was the accounting audit written up in [tmp/accounting-open-items.md](tmp/accounting-open-items.md).
This document records what got built in response and, more importantly, **why each
decision went the way it did** — including the alternatives that were considered
and rejected, since those are the parts that are expensive to re-derive later.

Supporting documents already in the tree:

| Doc | What it holds |
|---|---|
| [tmp/accounting-open-items.md](tmp/accounting-open-items.md) | The audit findings, item by item, with effort estimates and a recommended order |
| [tmp/AUDIT_2026-08-01.md](tmp/AUDIT_2026-08-01.md) | Static code review of the WIP tree (combo restock bug, etc.) |
| [tmp/refund-pipeline.md](tmp/refund-pipeline.md) | The full refund pipeline as it runs today, with known gaps |
| [Backend/docs/ORDER_LIFECYCLE.md](Backend/docs/ORDER_LIFECYCLE.md) | Updated with the new pricing and invoicing rules |

---

## 2. Changes by area

### 2.1 Pricing — GST became inclusive, and delivery became taxable

Two opposite conventions now coexist **on purpose**, and mixing them up is the
single most likely way to break the bill:

| | Convention | Where the tax lives |
|---|---|---|
| **Goods** (products, combos) | Price is MRP — **GST-inclusive** | Extracted from the price for disclosure. Never added to the total. |
| **Delivery** | Fee is quoted **net** — GST on top | A genuine addend. Customer pays ₹59 + ₹10.62 = ₹69.62. |

- New module [Backend/orders/pricing.py](Backend/orders/pricing.py) is the single home for
  `extract_tax` / `add_tax` / `refund_tax_for`. Previously three surfaces (cart preview,
  coupon preview, placed order) each carried their own copy of the additive formula —
  which is precisely how they drifted apart.
- `Order.tax_inclusive` (migration `orders/0014`) flags the convention per order.
  Historical orders are backfilled `False` and their stored money columns are
  **deliberately not recomputed** — those totals are what the customer was actually
  charged, and the flag is what lets the invoice renderer reprint old bills so they
  still add up.
- `Order.shipping_tax` is stored separately from `Order.shipping_charge`. Never fold
  one into the other or the invoice's GST summary stops reconciling.
- **Output tax is `Order.total_tax` (= `tax` + `shipping_tax`), never `Order.tax`.**
  Every reporting surface reads `total_tax`; `tax` alone understates liability by the
  GST on every delivery charged.
- New shared component [PriceBreakup.tsx](Frontend/nidhi-brand-forge/src/components/PriceBreakup.tsx)
  renders the bill identically in cart, checkout and My Orders. Layout encodes the
  two conventions: things that *add* to the total are flush-left; things that merely
  *explain* a line above are indented and muted.

### 2.2 Combos — components became real

- `ProductComboItem` now points at a **`ProductVariant` (a specific size)**, not a
  Product (`products/0038`). With two active sizes, a combo previously meant
  "whichever size is default today" and drew stock from a mirror column no sale
  reads — an oversell path.
- `ProductCombo.price` and `ProductCombo.tax_rate` **were dropped** (`products/0040`).
  MRP is now derived from the component sizes, and GST is charged per component at
  its own product's rate. A bundle mixing 0% papad with 5% spices used to be billed
  at one hand-entered blended rate, which is simply wrong on a tax invoice.
  The migration copies the current selling price into `discount_price` first, so
  dropping the column cannot silently reprice the catalogue.
- `OrderItemComponent` (`orders/0017`) snapshots what each combo line actually drew:
  variant, units, rate, HSN, allocated amount, tax. Allocations sum exactly to the
  combo line's `final_price`, so nothing double-counts or leaks between the two paths.

### 2.3 Refunds — a ledger, partials, and manual-only recording

- `OrderRefund` (`orders/0016`) is the ledger; [orders/refunds.py](Backend/orders/refunds.py)
  `record_refund` is the **single write path**. One entry point is what guarantees the
  GST reversal, the denormalised order totals and the order status can never disagree.
- **Partial refunds** are supported via an optional `refund_amount`. Consequence worth
  repeating: `status='refunded'` now means *"a refund was recorded"*, **not** *"the whole
  order came back"*. Every surface showing that flag must also show `refunded_amount`.
- **Eligibility:** online-paid orders only (`payment_method` in {ONLINE, razorpay} and
  `payment_status` in {paid, refunded}). A ledger row reverses GST, so writing one for
  money that never reached us understates tax owed.
- **Restock:** recording a refund restocks the order, once, guarded by
  `Order.stock_restored_at` — so cancel-then-refund or two instalments can't credit the
  same units twice.
- **Credit notes** are issued: `CN-000012` series, its own PDF, citing the original
  invoice number and date.

### 2.4 COD — cash is now a fact the system knows

- `Order.cod_paid_at` + `cod_confirmed_by` (`orders/0019`), set when an admin ticks
  "Paid in cash" (PATCH `cod_paid: true`). It is **not** a side effect of marking an
  order delivered — couriers remit days later.
- Before this, a genuine COD return could not be recorded **at all**, so its GST stayed
  owed forever. That was the bug this closes.
- Dashboard gained `cod_pending_amount` / `_count` / `_aged_count` (cash the courier is
  holding, live) and `cod_collected_today`. `DailySalesRollup.cod_collected` buckets by
  **confirmation** date, like refunds.

### 2.5 HSN classification

- `Product.hsn_code` (`products/0041`), snapshotted onto `OrderItem` and
  `OrderItemComponent` (`orders/0021`), printed on the invoice, aggregated by
  `/api/admin/hsn-summary/` into the GSTR-1 Table 12 report.
- [Backend/products/hsn.py](Backend/products/hsn.py) is a **curated reference table**, not
  policy — the published rate for each code, shown beside the rate the product charges,
  with mismatches flagged. It is never auto-applied.
- Migration `products/0042` populated the live catalogue by keyword.
- New admin screen [GstReport.tsx](Admin%20Panel/e-commerce-command-center/src/pages/GstReport.tsx)
  at `/gst`: coverage (unclassified + rate-mismatched products) and the HSN summary
  with CSV export, defaulting to the previous calendar month.

### 2.6 Place of supply / IGST

- `Order.shipping_state`, `shipping_pincode`, `place_of_supply_state_code`
  (`orders/0020`), resolved by [orders/place_of_supply.py](Backend/orders/place_of_supply.py)
  and driving the CGST+SGST vs IGST split on the invoice.
- The *amount* is identical either way — this was never an under-collection — but the
  heads credit different governments and GSTR-1 Table 7 is reported **by** place of supply.

### 2.7 Tax invoices as issued documents

- `Invoice` (OneToOne, `on_delete=PROTECT`) + `InvoiceCounter` (`orders/0022`).
  Numbering and triggers in [orders/invoicing.py](Backend/orders/invoicing.py).
- Number is `NM/25-26/000123` — prefix / Indian FY / sequence from a row-locked counter,
  continuous within the year.
- `Invoice.snapshot` freezes seller + buyer + lines + totals + GST heads at issue, and
  the renderer reads **only** that.
- `GET /orders/{id}/invoice/` is now a reprint; 409 `invoice_not_issued` when none exists.
- One-off backfill command: `python manage.py backfill_invoices --dry-run`.

### 2.8 Reporting integrity

- Nightly rollup backfill widened **3 → 35 days** (`ROLLUP_BACKFILL_DAYS`). The interval
  job only ever touches today, so anything corrected after 72 h previously left that
  day's revenue and GST overstated permanently, with nothing to detect it.
- New [check_rollup_drift](Backend/analytics/management/commands/check_rollup_drift.py),
  scheduled nightly at 04:00. It **never writes** — recomputing on detection would hide
  the one signal worth having.
- New [spices_backend/timeranges.py](Backend/spices_backend/timeranges.py): half-open
  aware datetime ranges instead of Django's `__date` lookup, which renders as an
  expression over the column and makes every dated report a sequential scan.
- `Payment.gateway_fee` / `gateway_tax` (`payments/0005`) captured from the payment
  entity — a real ~2% expense that was missing from the books, and ITC that was going
  unclaimed.
- `net_revenue` (gross − refunds) surfaced in Insights and under the dashboard headline.
- New rollup columns: `gst_collected`, `refunds`, `gst_refunded`, `shipping_collected`,
  `shipping_tax_collected`, `shipping_cost`, `cod_collected`.

---

## 3. The decisions, and why they went that way

### D1 — Rename `SHIPPING_CHARGE` → `SHIPPING_CHARGE_NET` rather than reuse the name

Every deployed `.env` pins `SHIPPING_CHARGE=69` from the untaxed era. Reusing the name
would have changed what that number *means* under deployments still holding it — 69 goes
from "what the customer pays" to "the net fee", silently billing 69 + 18% = ₹81.42.

Manually fixing the env was no safer, in either order: change it first and you bill ₹59
with no tax; ship the code first and you overcharge until someone remembers.

**Decision:** rename, making a stale value inert everywhere, and warn at boot
([orders/apps.py](Backend/orders/apps.py)) that a dead variable is sitting in the env.
A warning, not `ImproperlyConfigured` — pricing is already correct by then, and taking
the whole API down over a leftover env line is a worse outage than the tidy-up it asks for.

> **Do not "tidy" the name back.**

### D2 — Invoices are issued at supply, not at PDF download

Rendering on demand meant an unpaid, about-to-be-auto-cancelled order could pull a page
headed **TAX INVOICE**. So the trigger is the point a taxable supply becomes true, and it
differs by payment method:

- **ONLINE** — at payment capture (and at placement for a zero-total, fully-coupon-waived
  order, which is already paid with no capture coming).
- **COD** — at **dispatch**, not at cash confirmation. The bill must physically travel
  with the goods, and the courier remits days later; waiting would leave delivered goods
  uninvoiced. GST on goods accrues at the invoice, not at the payment.

`invoice_is_due` accepts **either** evidence: money received (`paid` *or* `refunded`) or
goods dispatched. `refunded` must count — a refund is only recordable against money
actually taken, so excluding it would leave historical refunded orders unnumbered and
their credit notes with no serial to cite. A cancelled order is never invoiced.

### D3 — Invoice numbers come from a counter, not from `Order.id`

`ORD-{order.id}` skips every abandoned checkout and cancelled order. A GST series is
supposed to be continuous, so that could never be lawful. `InvoiceCounter` issues under a
row lock, per financial year. The 15-character format fits GST's 16-char cap.

### D4 — The invoice renders from a frozen snapshot

Seller name, address and GSTIN used to be read from `settings` at render time, so
changing `SELLER_ADDRESS` reprinted every historical invoice differently. **A bill that
changes after issue is not a bill.** Editing a shipping address or re-rating a product
now cannot alter an issued invoice.

### D5 — Place of supply resolves by state **name**, not PIN code

Checkout already asks for state as a required field, and an alias table absorbs the
realistic variants ("M.P.", "Madhya Pradesh", "मध्य प्रदेश").

A PIN-code lookup was **considered and rejected**: India's 3-digit prefixes split across
state lines in enough places (Uttarakhand inside UP's block, Jharkhand inside Bihar's,
Chandigarh inside Punjab's) that a compact table produces *confidently wrong* tax heads —
worse than a declared fallback. Unresolvable addresses fall back to the seller's own state
(the historical behaviour, and the safe one for a mostly-local store); an admin can correct
the order before the return is filed.

### D6 — HSN codes are stored, and the published rate is never auto-applied

`tax_rate` records *what* is charged; it cannot record *why*, and there is no derivation
in either direction — 5% spans 0904 / 0909 / 0910, and 2103 moved 12% → 18% on 2025-09-22
without any product changing.

Classification is a judgement call with money attached, so the panel **shows** the
statutory rate and **flags** a mismatch but never writes it. An auto-applied wrong rate
would silently change the GST split on every future order.

**Two open questions deliberately left for the CA**, both surfaced on the `/gst` screen:

1. Masala blends are coded `09109100` (5%). A blend containing salt / sugar / starch / oil
   is arguably `21039040`, now **18%** — a 13-point swing on roughly half the catalogue.
2. "Chana papad masala" / "Moong papad masala" are spice blends, but migration
   `products/0024` zero-rated every name containing "papad", so they charge 0% while coded
   `09109100` (5%). Left for the owner to correct rather than auto-changed.

### D7 — Refunds are manual-only

The `refund.processed` webhook branch in `payments/views.py::_dispatch_webhook_event` is
**commented out**. A refund webhook is signature-verified, logged at WARNING, and
otherwise ignored.

⇒ After issuing any refund in the Razorpay dashboard, an admin **must** mark the order
refunded in the panel, or the order reads `paid` forever and its GST is never reversed —
tax paid on money already returned.

To re-enable: un-comment the branch **and** the disabled test
`test_refund_webhook_without_order_id_still_refunds`.

Side effect worth noting: this makes the long-standing missing `RAZORPAY_WEBHOOK_SECRET`
in production much cheaper than it was. Gateway refunds are no longer auto-recorded even
with a working secret.

### D8 — A partial refund restocks the whole order, once

Accepted asymmetry. Idempotence via `stock_restored_at` matters more than proportional
restocking, which would need per-line refund attribution the admin UI does not ask for.

Likewise the GST reversal is exact on a full refund and a **blended-rate apportionment**
on a partial — so on a mixed 0%/5% order a partial is an estimate. Accepted deliberately
as the price of the feature.

### D9 — Ticking "Paid in cash" is a cash fact, never a tax one

GST accrued at the order date and must not move when the money turns up. The tick affects
`payment_status`, the COD ledger and refund eligibility — not the tax period.

### D10 — The HSN summary does **not** net off refunds

A refund reverses tax, but it is a **credit note**, and credit notes are GSTR-1 Table 9B,
not Table 12. Netting them into the HSN rows would silently under-report outward supply.
`refunded_in_period` is reported alongside as a reconciling figure, not subtracted.

The summary also reads **line snapshots, never the catalogue** — re-classifying a product
today must not change a return already filed for last quarter. And it uses the same
`countable_orders()` filter as the sales dashboard, so the HSN summary and the revenue
figure on the next screen cannot disagree.

### D11 — Drift is detected, not silently repaired

`check_rollup_drift` reports and exits; the fix stays a deliberate `rollup_analytics --days N`.
Auto-recomputing would hide exactly the signal worth having: that something is reaching
back further than the backfill window. Tolerance is 1 paisa — flagging rounding noise
trains everyone to ignore the alert. Only the **financial** fields are checked, because a
narrow check is one people actually act on.

### D12 — What was deliberately *not* built

| Item | Decision |
|---|---|
| **Input tax credit / COGS ledger** | **Don't build.** Tally / Zoho Books / Vyapar already do this better. NGU should export cleanly into them — which the CSV export mostly does. What NGU owes is the honest label: the GST figure on the dashboard is output tax, *not* the amount payable. |
| **Settlement reconciliation** | Deferred. Fee capture from the payment entity gets ~90% of the value for a fraction of the work. |
| **Revenue recognised at delivery** | Low priority. GST accrual at order date is *correct* and must not change; with COD cash now visible the practical damage is mostly gone. |

---

## 4. Migrations added

| App | Migration | What it does |
|---|---|---|
| products | `0038_combo_item_variant` | Combo components point at a size, not a product |
| products | `0039_backfill_missing_variants` | Mints variants for products that had none |
| products | `0040_combo_derived_mrp_drop_tax_rate` | Combo MRP derived; per-component GST |
| products | `0041_product_hsn_code` | `Product.hsn_code` |
| products | `0042_populate_hsn_codes` | Classifies the live catalogue by keyword |
| orders | `0014_order_tax_inclusive` | GST-inclusive flag, historical orders `False` |
| orders | `0015_order_shipping_cost_item_tax_rate` | Courier cost + per-line rate snapshot |
| orders | `0016_order_refund_ledger` | `OrderRefund` + denormalised order totals |
| orders | `0017_order_item_component` | Combo component snapshots |
| orders | `0018_order_stock_restored_at` | Restock idempotence stamp |
| orders | `0019_order_cod_confirmed_by_...` | COD cash confirmation |
| orders | `0020_order_place_of_supply` | State / pincode / place-of-supply code |
| orders | `0021_order_line_hsn_code` | HSN snapshot on lines and components |
| orders | `0022_invoicecounter_invoice` | Issued invoice documents + counter |
| payments | `0005_payment_gateway_fee_...` | Razorpay fee + GST on fee |
| analytics | `0004_sales_rollup_gst_shipping` | GST / shipping rollup columns |
| analytics | `0005_rollup_refunds` | Refund + GST-refunded columns |
| analytics | `0006_dailysalesrollup_cod_collected_...` | COD cash collected |

---

## 5. New API surface

| Route | Purpose |
|---|---|
| `GET /api/admin/hsn-reference/` | Curated HSN list + statutory rate for each |
| `GET /api/admin/hsn-coverage/` | Unclassified + rate-mismatched products |
| `GET /api/admin/hsn-summary/` | GSTR-1 Table 12 data (`?format=csv` to download) |

`GET /orders/{id}/invoice/` changed behaviour: reprint only, 409 `invoice_not_issued`
when no invoice exists. Order responses now carry `invoice: {number, issued_at} | null`.

Per project convention, [Backend/docs/API.md](Backend/docs/API.md) has been updated for
these rows in the same change.

---

## 6. Deployment notes for this batch

1. **No prod `.env` edit is required.** The `SHIPPING_CHARGE` rename (D1) makes the stale
   value inert. Delete the dead line when convenient; startup logs a warning until you do.
2. **Run migrations**, then the one-off invoice backfill so historical paid/dispatched
   orders get numbers (oldest-first, stamped with each order's own date):
   ```bash
   docker compose -f docker-compose.prod.yml exec -T backend python manage.py migrate
   docker compose -f docker-compose.prod.yml exec -T backend python manage.py backfill_invoices --dry-run
   # then without --dry-run
   ```
   Issuing never raises, so a failure just leaves a gap — the backfill is also the repair tool.
3. **A one-off rollup backfill** is worth running once, to correct days that drifted under
   the old 3-day window: `rollup_analytics --days 400`, then `check_rollup_drift`.
4. **Reload the frontend nginx** after any deploy that recreates the admin-panel or backend
   container: `docker exec ngu-frontend nginx -s reload` (otherwise `/panel/` 502s against
   a dead container IP).

---

## 7. Verification status

Last recorded full run, on the 2026-08-01 tree (see [tmp/AUDIT_2026-08-01.md](tmp/AUDIT_2026-08-01.md)):

```
cd Backend && venv/Scripts/python.exe -m pytest -q
=> 928 passed, 8 skipped, 2 failed  (~3.5 min)
```

The 2 failures are `orders/test_concurrency.py::test_G4/G5` — the documented SQLite
row-locking limitation; they pass on Postgres. `makemigrations --check` was clean and
`tsc --noEmit` was clean on both frontends.

**This has not been re-run since the invoicing, HSN and place-of-supply work landed
(2026-08-02 → 08-04).** Re-run before shipping. New test files added in this batch:
`orders/test_invoicing.py`, `test_refunds.py`, `test_gst_breakup.py`, `test_hsn_summary.py`,
`test_place_of_supply.py`, `test_shipping_gst_and_cod.py`, `test_combo_component_tax.py`,
`products/test_hsn.py`, `analytics/test_gst_rollup.py`, `analytics/test_drift_and_gateway_cost.py`.

> ⚠ A first audit pass reported 62 failures + 37 errors. That was a half-saved tree that
> grew mid-run. Re-run on a settled tree before trusting any failure count.

---

## 8. Still open

| # | Item | Status |
|---|---|---|
| 3 | Credit notes | **Mostly done** — number, PDF, invoice reference all exist. Remaining gap: `CN-{refund.pk}` is increasing but **not gapless**, unlike the invoice series. Worth moving onto `InvoiceCounter`. |
| 8 | Revenue recognised at order date | Open, low priority (see D12) |
| 13 | No ITC / COGS | Won't build (see D12) |
| 14 | No period lock | **Open, and now more necessary** — a 35-day backfill window will reach back into a filed month. At minimum, snapshot what was filed. |
| — | No refund email on the admin path | Open. The customer only sees a refund in My Orders. |
| — | Inter-state order share unknown | **Free to check, and it was the biggest open question in the audit.** Place of supply is now implemented either way, so this is no longer blocking — but it tells you how much the old intra-state-only billing actually mis-stated. |
