# 05 — Invoice Numbers Are Not Order IDs

> Source: `Backend/orders/invoicing.py`, `Backend/orders/models.py`
> (`InvoiceCounter`, `Invoice`, `CreditNote`), `Backend/orders/credit_notes.py`
> Changed: 2026-08-04 (invoices), 2026-10-01 (credit notes)
> Tests: `Backend/orders/test_invoicing.py`

---

## The old design

An invoice was a PDF made whenever someone asked for one. Its number was the
order's id:

```python
invoice_number = f"ORD-{order.id:06d}"
```

It looks fine. It is wrong in three separate ways.

---

## Problem 1: the numbers have gaps

The database gives every new order the next id. But most orders never become
sales:

```
order 101   paid          → invoice ORD-000101
order 102   abandoned at payment, cancelled after 15 minutes
order 103   cancelled by the customer
order 104   paid          → invoice ORD-000104
```

A GST invoice series must be **continuous** within a financial year: 1, 2, 3,
with nothing missing. A gap is a question the tax office will ask: where is
invoice 102? "It was never an invoice" is not a good answer when the number
format says it should be.

**An id is a name for a row. An invoice number is a position in a legal
series.** They are different things that happened to both be integers.

## Problem 2: any order could print a "tax invoice"

The PDF was made on request. So an unpaid order, about to be auto-cancelled,
could produce a page headed TAX INVOICE. That page claims a sale that never
happened.

## Problem 3: the bill could change after it was given out

The PDF was drawn from live data: the shop's address from settings, the
customer's address from the order, product names from the catalogue. Change
any of those and a "reprint" differs from the original. A document that changes
after it is issued is not a document.

---

## The new design

An invoice is **a row in a table**, created once at a defined moment.

### A counter that only moves when an invoice is issued

```python
class InvoiceCounter(models.Model):
    series = models.CharField(max_length=16, unique=True)      # 'NM/25-26'
    last_number = models.PositiveIntegerField(default=0)
```

```python
def allocate_invoice_number(series):
    counter, _ = InvoiceCounter.objects.get_or_create(series=series)
    counter = InvoiceCounter.objects.select_for_update().get(pk=counter.pk)   # lock
    counter.last_number += 1
    counter.save(update_fields=['last_number', 'updated_at'])
    return f"{series}/{counter.last_number:06d}", counter.last_number
```

Three details:

- **`select_for_update()` locks the counter row.** Two payments captured in the
  same millisecond queue up here. They cannot both read 122 and both write 123.
- **The row is fetched twice on purpose.** `get_or_create` cannot lock a row it
  might be creating, so the code fetches it again with a lock.
- **One series per financial year**, `NM/25-26`. The Indian financial year runs
  April to March, and the year is worked out in *local* time. An order at 2 a.m.
  on 1 April in India is still 31 March in UTC, and must not be filed in the
  old year.

The whole number is `NM/25-26/000123`: 15 characters. GST allows 16.

### A defined moment

`invoice_is_due(order)` decides. In short: money was received, or the goods
went out. A cancelled order never gets one. The details are in
[Part 2 §8.2](../02_LLD_Object_Model_and_Flows.md).

For cash on delivery this means the invoice is issued **at dispatch**, not when
the cash arrives. The bill must be in the parcel, and the courier hands over
the cash days later.

### A frozen copy

```python
snapshot = models.JSONField()   # everything the PDF prints
```

The PDF renderer reads only the snapshot. Money inside it is stored as text
(`"210.00"`), because JSON has no exact decimal type and floats lose paise.

### Corrections are a new document

An issued invoice is never edited. If money goes back, a **credit note** is
issued: its own row, its own number (`CN/25-26/000001`) from the same kind of
counter, pointing at the invoice it corrects.

---

## What happens when two things collide

**Two workers try to invoice the same order.** The link from invoice to order
is one-to-one, so the database rejects the second insert. The code catches the
error and keeps the first:

```python
except IntegrityError:
    existing = Invoice.objects.filter(order_id=order.pk).first()
    ...
    return existing, False
```

The second worker had already taken a number from the counter. That number is
now unused: a gap. The code comment is honest about the trade: a burned number
is accepted over two invoices for one sale. Perfect continuity under every
race would need a heavier design. This one makes gaps rare, not impossible.

**Building the invoice fails during a payment capture.** The payment must not
be undone because a document failed. So `maybe_issue_invoice` catches every
error, logs it, and returns nothing. It runs inside its own inner transaction
(a savepoint) so the failure does not spoil the outer one. A command,
`backfill_invoices`, issues any that were missed, oldest first.

---

## The general lesson

> **Do not reuse a technical identifier as a business number.** They have
> different rules. An id must be unique. A document number must be unique,
> continuous, ordered, and sometimes restart each year.

Other places this shows up:

- A "customer number" printed on letters should not be the user table's id.
- A "ticket number" told to a customer should not reveal how many tickets you
  have.
- A URL should not expose a counting id that lets people guess the next one.

And the second lesson:

> **A document is something that was issued, not something that can be
> generated.** Store it. Freeze what it said. Correct it with another document.

---

## Interview questions

1. *Why not use the auto-increment id as the invoice number?*
   → Ids are used up by rows that never become invoices, so the series has
   gaps. A tax series must be continuous.

2. *How do you generate a gap-free sequence under concurrency?*
   → One counter row per series. Lock it, add one, save, all in a transaction.
   Add a unique constraint as the backstop.

3. *Is your sequence really gap-free?*
   → Almost. If two workers race on the same order, the loser's number is not
   used. I chose that over the risk of two invoices for one sale, and it is
   logged when it happens.

4. *Why store a snapshot when all the data is already in the database?*
   → The data changes: addresses are corrected, products renamed, the shop
   moves. The bill must show what was true when it was issued.

5. *The invoice step fails while a payment is being captured. What should
   happen?*
   → The capture succeeds. Document generation is less important than taking
   the money correctly. Log it and repair it afterwards.

6. *Why a savepoint and not only `try/except`?*
   → In Postgres a failed statement marks the whole transaction as failed.
   Catching the Python exception does not undo that. A savepoint lets the
   database roll back just the inner part.
