# NGU — Open Accounting & Billing Items

*Written 2026-08-04, after the shipping-GST and COD-cash work shipped.*

This is the discussion document for the items raised in the accounting audit.
Items 9, 12 and 15 have since been implemented and are marked as such; the rest
are **still open** and nothing in those sections is built. Each section says what is
actually wrong, what it costs you, what fixing it involves, and — where it
matters — what I'd recommend and what I'd leave alone.

**Read the last section first if you only read one.** Not everything here is
worth doing, and a couple of these are cheap enough that leaving them undone is
the expensive choice.

---

## Where things stand

Closed since the audit:

| | |
|---|---|
| ✅ Soft-deleted orders counted as revenue | Fixed; needs a one-off prod backfill |
| ✅ Delivery was untaxed | Now ₹59 net + 18% GST, its own slab everywhere |
| ✅ COD cash was invisible | "Paid in cash" tick, dashboard ledger, rollup column |
| ✅ COD returns couldn't be recorded at all | Unblocked by the tick |
| ✅ Dashboard "today" used the UTC date | Fixed (was silently wrong 00:00–05:30 IST) |

**Closed in a second pass (2026-08-04)** — items 9, 12 and 15 below are now done,
and the shipping deploy trap is defused by renaming the env var so a stale value
is inert rather than mis-priced:

| | |
|---|---|
| ✅ **Item 9** — rollups went stale after 3 days | Backfill widened to 35 days (`ROLLUP_BACKFILL_DAYS`) + `check_rollup_drift` nightly at 04:00 |
| ✅ **Item 12** — Razorpay fees invisible | `Payment.gateway_fee`/`gateway_tax` captured from the payment entity; ITC surfaced on the GST tile, order dialog and CSV |
| ✅ **Item 15** — no net revenue figure | `net_revenue` in Insights; "net of refunds" under the dashboard headline |

The sections for 9, 12 and 15 are kept below as the record of what was wrong and
why the fix took the shape it did.

Still open — the rest of this document:

| # | Item | Class |
|---|---|---|
| 1 | No HSN codes | Can't file |
| 2 | No place of supply → no IGST | Can't file |
| 3 | No credit note document | Can't file |
| 4 | Invoice numbers aren't invoice numbers | Can't file |
| 8 | Revenue recognised at order date regardless of payment/delivery | Misstatement |
| 13 | No COGS / no purchase-side ITC | Wrong number filed |
| 14 | No period lock | Filed periods can change |

---

# Group A — "You cannot produce a correct GSTR-1"

These four are one problem wearing four hats: the system has the *money* right
but not the *paperwork*. Everything you charge is correct; almost none of the
fields a return actually asks for exist.

## 1. No HSN codes anywhere

**What's wrong.** `grep -ri hsn` over the backend returns nothing. Products carry
`tax_rate` but no HSN. GSTR-1 **Table 12 (HSN summary)** is mandatory.

**Why `tax_rate` can't substitute.** Both directions fail. 5% spans many HSN
headings — 0904 (pepper, chilli), 0910 (ginger, turmeric, masala mixes), 2103
(sauces/mixed condiments). And one HSN can move slabs when the law changes.
There's no derivation; it has to be stored.

**What it costs.** Your return is filed with a fabricated or blank Table 12.
Small turnover keeps this low-risk in practice, but it's the kind of gap that
turns a routine scrutiny into a long one.

**What fixing it involves.**
- `Product.hsn_code` (CharField, 4/6/8 digits) + admin field + CSV import/export
  column.
- Snapshot to `OrderItem.hsn_code` at checkout — exactly like `tax_rate` already
  is, and for the identical reason: a product re-coded next year must not rewrite
  last year's invoice.
- Print it on the invoice line table (a GST invoice is supposed to show it).
- An HSN summary export: HSN × rate → quantity, taxable value, tax.

**Effort:** ~1 day of code. The real work is you assigning HSN codes to ~50
products, which nobody can do for you. It's a spreadsheet exercise, once.

**Recommendation: do this one.** It's the cheapest of the four and the most
mechanically required.

---

## 2. No place of supply → every sale is billed intra-state

**What's wrong.** `invoice.py` hardcodes `Place of Supply: {SELLER_STATE}` —
always Madhya Pradesh (23). `Order.shipping_address` is a free-text blob with no
state or pincode column, so the real place of supply is genuinely unknowable from
the data.

**Two separate consequences, different severities.**

*The tax total is fine.* Whether a 5% supply is CGST 2.5 + SGST 2.5 or IGST 5,
you collected 5%. **You are not under-collecting.** This is worth being clear
about, because it's the reason this isn't an emergency.

*The heads and the tables are wrong.* An inter-state B2C supply must be **IGST**.
You're reporting it as CGST+SGST, which credits the wrong governments. And
GSTR-1 **Table 7 (B2C others)** is reported **by place of supply** — you cannot
produce it at all.

**What fixing it involves.**
- Structured `state` + `pincode` on the order (and on the saved address), captured
  at checkout. This is the actual work — it's a checkout-form change, a data
  migration decision for existing addresses, and a validation question.
- A `place_of_supply_state_code` snapshot on the order.
- Split the tax into CGST/SGST vs IGST on the invoice, driven by
  `place_of_supply == SELLER_STATE_CODE`.
- Historical orders: leave them. They were billed as intra-state and reprinting
  them differently would make old bills disagree with old returns.

**Effort:** 2–3 days, and it touches the customer-facing checkout — the only item
in this document that does.

**Honest note on urgency.** If ~all your orders ship within MP, the current
behaviour is *accidentally correct* and this drops to a paperwork item. If you
ship across India, every out-of-state order is misclassified today. **I don't
know your split — that single fact decides whether this is item #1 or item #6 on
the list.** Worth checking before anything else here.

---

## 3. No credit note document for refunds

**What's wrong.** The refund ledger (`OrderRefund`) reverses GST internally and
correctly — bucketed by refund date, capped, idempotent. But there is **no
document**: no credit note number, no separate series, no PDF, no reference to
the original invoice. The invoice PDF doesn't even mention that a refund
happened; a fully-refunded order still prints its original full-value bill.

**What it costs.** Under GST you reduce output tax by issuing a **credit note**
with its own serial, its own date, and a reference to the original invoice. Your
liability reduction is real and correctly computed — it just has no paperwork
behind it. If asked to evidence a reversal, you'd have a database row.

**What fixing it involves.**
- A credit-note number series (see item 4 — same machinery).
- `OrderRefund.credit_note_number` + `issued_at`.
- A PDF renderer (largely a variation of the existing invoice template).
- Show the refund on the order's invoice, or at minimum stamp it.

**Effort:** ~1 day *if* item 4 is done first, because it needs the same
numbering. Doing it standalone means building the numbering twice.

**Recommendation: bundle with item 4.** They're the same work.

---

## 4. Invoice numbers aren't real invoice numbers

**What's wrong.** `_order_number()` is `f"ORD-{order.id:06d}"`, computed at PDF
render time. Nothing is stored. Three problems fall out:

- **The series has gaps.** Every cancelled or abandoned order burns a number. A
  GST invoice series is supposed to be continuous.
- **Reprints mutate.** Seller name, address and GSTIN are read from `settings` at
  render time. Change `SELLER_ADDRESS` and every historical invoice reprints with
  the new one. A bill that changes after issue is not a bill.
- **No status gate.** The `invoice` endpoint has no check — a `pending`, unpaid
  order can pull a document headed **TAX INVOICE**, including one that L3
  auto-cancels 15 minutes later.

**What fixing it involves.**
- An `Invoice` model: number, series, issued_at, and a **frozen snapshot** of
  seller details + totals.
- Issue it at a defined trigger — payment confirmed or dispatch, not at PDF
  download.
- Render from the stored snapshot, never from live settings.
- Gate the endpoint on an issued invoice existing.

**Effort:** ~1–2 days. Mostly design decisions (when is an invoice issued?)
rather than hard code.

**Recommendation: do this with item 3.** The "reprints mutate" bug is the one
that would actually embarrass you, and it's live today.

---

# Group B — Numbers that drift

## 9. Rollups go stale after 3 days ⚠ *cheapest real win*

**What's wrong.** The scheduler recomputes yesterday+today every 5 minutes, plus
`--days 3` nightly. **Anything that changes an order more than 72 hours after it
was placed never rewrites history.** A cancellation on day 5, a corrected
`shipping_cost`, an order restored from the Recycle Bin — that day's `revenue`
and `gst_collected` stay wrong permanently, and nothing detects it.

**What it costs.** Your reported revenue and output tax drift upward over time,
by exactly the value of every late cancellation. Silently. Forever. This is the
same class of bug as the soft-delete one just fixed, and it's still live.

**What fixing it involves.** Two options, and I'd do both:

1. **Widen the nightly backfill** to ~35 days. One config change. Catches
   essentially every real correction, since almost nothing changes after a month.
2. **Add a drift check** — a job that re-aggregates a window from source orders,
   compares against the stored rollups, and logs/alerts on any mismatch. This is
   the part that means you find out *next time* instead of never.

A third, cleaner option: mark orders dirty on save and recompute touched days.
More correct, more moving parts. I'd start with 1+2.

**Effort:** an hour for (1), half a day for (2).

**Recommendation: do this next.** Highest value-to-effort ratio in the document
by a wide margin.

---

## 14. No period lock

**What's wrong.** `rollup_analytics --days 30` will cheerfully rewrite a month
you have already filed. Refunds are carefully bucketed by refund date to avoid
exactly this — but a late *cancellation* isn't, and nothing marks a period closed.

**What it costs.** Today: you can't reproduce the numbers you filed from, because
the source can move under you. That's a reconciliation problem, not a compliance
one — until the day it matters.

**What fixing it involves.** A `FiledPeriod` marker (month, filed_at, the totals
as filed). Recompute refuses to touch a locked period, or writes an adjustment
row instead. Plus a "these figures are locked" indicator in Insights.

**Interaction with item 9 worth noticing:** widening the backfill makes this
*more* necessary, not less — a 35-day window will reach back into a filed month.
If you do item 9, do at least the "snapshot what was filed" half of this.

**Effort:** ~half a day for the snapshot; a day for full enforcement.

---

# Group C — Revenue means something different than you think

## 8. Revenue and GST are recognised at order date, regardless of payment or delivery

**What's wrong.** The rollup filters on `created_at` and excludes only
`cancelled`. So an order counts as revenue *and output tax* the moment it's
placed — including a COD order that is never dispatched, refused at the door, or
quietly returned.

**Important nuance, now that COD cash is tracked.** The GST side of this is
**correct and should not change**: time of supply for goods is the invoice, not
the payment. Accruing GST at order date is right. What's missing is that
"revenue" has no *delivered* or *collected* variant sitting beside it. The COD
tile added part of that — you can now see cash in hand — but the headline revenue
number still counts orders that may never complete.

**What fixing it involves.** Not a rewrite — an additional figure:
`delivered_revenue` (orders that reached `delivered`) alongside the accrued one,
and a "never dispatched, >30 days" list to catch orders that should have been
cancelled.

**Recommendation: low priority.** With COD cash now visible, the practical damage
is mostly gone. Worth revisiting only if you find a lot of stale undispatched
orders.

---

## 15. Gross revenue shown without a net figure

Insights shows gross revenue with refunds in a separate tile, deliberately, and
documented. But "Revenue ₹1,20,000" reads as net to almost everyone.

**Fix:** show `net revenue = gross − refunds` under the headline. Half an hour.

**Recommendation: do it.** Trivial, and it's your own dashboard misleading you.

---

# Group D — Things the system doesn't know exist

## 12. Razorpay fees are invisible

**What's wrong.** Revenue is `Sum(total_amount)` — what the customer paid.
Razorpay keeps roughly **2% + 18% GST on that fee**, and nothing records it.
Nothing reconciles our totals against actual settlement payouts either.

**What it costs.** Two things:
- A real expense (~2%) missing from your books. Your margin is overstated by it.
- **The GST on those fees is input tax credit you are entitled to and not
  claiming.** On ₹10L of annual online sales that's roughly ₹20,000 of fees and
  ~₹3,600 of ITC left on the table every year.
- No settlement reconciliation means a short payout would never be noticed.

**What fixing it involves.** Either capture `fee`/`tax` from the payment entity
(Razorpay returns both on a captured payment — we already receive it and drop
these fields), or import the settlement report periodically. The first is much
cheaper and gets you 90% of the value.

**Effort:** ~half a day for fee capture. Settlement reconciliation is a bigger,
separate project.

**Recommendation: do the fee capture.** It pays for itself, literally, and the
data is already arriving in the webhook payload.

---

## 13. No input tax credit, no COGS

**What's wrong.** `net_gst_payable` in Insights is output tax minus refund
reversals. The model docstring is honest that it's before ITC — but it needs
saying plainly:

> **The GST figure on your dashboard is not the amount you pay.** Your actual
> liability is output tax **minus** input credit on everything you bought:
> ingredients, packaging, courier services, Razorpay fees, rent.

Likewise there's no cost of goods anywhere, so "revenue" is not profit. The only
cost tracked at all is `shipping_cost` per order.

**What fixing it involves.** This is the largest item here and the least like the
others: it's a purchase/expense ledger, which is genuinely a different feature
from an e-commerce backend. Minimum viable: a `Purchase` model (date, vendor,
GSTIN, taxable value, GST, category) with manual entry, feeding an ITC total.

**Effort:** several days, plus ongoing data entry discipline.

**Recommendation: don't build this.** This is what accounting software (Tally,
Zoho Books, Vyapar) already does, and does better. What NGU should do instead is
**export cleanly into it** — which the CSV export already mostly does. The one
thing worth adding here is the honest label, which the dashboard already carries.

---

# What I'd actually do, in order

1. **Item 9 — widen the backfill + drift check.** An hour plus half a day. Stops
   live, ongoing corruption of your numbers. Nothing else here is this cheap.
2. **Item 15 — net revenue line.** Half an hour.
3. **Item 12 — capture Razorpay fees.** Half a day, and it recovers real money
   in unclaimed ITC.
4. **Check your inter-state order share.** Free. Decides whether item 2 is urgent
   or cosmetic — and that's the biggest open question in this document.
5. **Items 4 + 3 together — invoice records and credit notes.** 2–3 days. The
   mutating-reprint bug is the one that would genuinely embarrass you.
6. **Item 1 — HSN codes.** 1 day of code; the rest is your spreadsheet.
7. **Item 2 — place of supply**, if step 4 says you ship out of state.
8. **Item 14 — period lock**, once you're filing from these numbers.
9. **Item 8** — revisit only if stale undispatched orders turn out to be common.
10. **Item 13 — don't build it.** Buy it, and export into it.

Steps 1–3 are about half a day together and are pure win. Everything after step 4
is a real project and should be scheduled, not squeezed in.
