"""Issuing tax invoices: when one is raised, its number, and what it freezes.

This module owns the three decisions that make an invoice a document rather
than a rendering of an order.

**1. When is an invoice issued?**

Not at PDF download — that would mean an unpaid, about-to-be-auto-cancelled
order could pull a page headed TAX INVOICE. An invoice asserts a taxable supply
happened, so it is raised at the point that becomes true, which differs by
payment method:

  * ONLINE / razorpay — at payment capture. The money is ours; the supply is
    committed. (A zero-total, fully-coupon-waived order is 'paid' at placement
    and is invoiced there, for the same reason.)
  * COD — at DISPATCH (shipped / delivering / delivered), rather than waiting
    for the cash to be confirmed. Two reasons: the invoice must physically
    travel with the goods, and COD cash is remitted by the courier days later —
    waiting for it would leave delivered goods uninvoiced, and GST on goods
    accrues at the invoice, not at the payment. (If a COD order somehow reaches
    confirmed-cash without a dispatch status, that is also proof of supply and
    it is invoiced then — `invoice_is_due` accepts either piece of evidence.)

A cancelled order is never invoiced. An order invoiced and *then* cancelled or
refunded keeps its invoice — see "subsequent events" in `orders/invoice.py`.
A REFUNDED order is still due one if it never got there: a refund can only be
recorded against money actually received, so it evidences a real supply.

**2. What is the number?**

`NM/25-26/000123` — prefix, Indian financial year (Apr–Mar), sequence. Drawn
from `InvoiceCounter` under a row lock at issue time, so the series is
continuous within the year. It is emphatically NOT derived from `Order.id`,
which skips every abandoned checkout and cancelled order and so could never
form a lawful series. GST caps the number at 16 characters and allows only
alphanumerics, '-' and '/'; the format above is 15.

**3. What is frozen?**

Everything the PDF prints — seller identity, buyer identity, lines, totals, GST
summary — is copied into `Invoice.snapshot` at issue and never read live again.
Seller details come from settings, which a deployment can change; the buyer's
address is editable by an admin PATCH; and the catalogue moves under both. A
bill that changes after it was handed to a customer is not a bill.
"""
import logging
from decimal import Decimal

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from spices_backend.limits import SHIPPING_TAX_RATE

from .models import Invoice, InvoiceCounter
from .place_of_supply import (
    head_rate_label, is_interstate, seller_state_code, split_gst, state_name,
)
from .pricing import order_tax_breakdown

logger = logging.getLogger(__name__)

SNAPSHOT_VERSION = 1

# Order statuses that mean the parcel has left us. A COD order is invoiced on
# reaching any of them — the bill goes in the box.
DISPATCHED_STATUSES = frozenset({'shipped', 'delivering', 'delivered'})

# Payment states that assert money actually reached us. 'refunded' belongs here:
# a refund can only be recorded against money that was taken (orders/refunds.py
# enforces that), so it is evidence of a completed supply, not a cancelled one.
MONEY_RECEIVED_STATUSES = frozenset({'paid', 'refunded'})


# ---------------------------------------------------------------------------
# Numbering
# ---------------------------------------------------------------------------

def financial_year_label(when=None):
    """Indian financial year of `when` as 'YY-YY' (April–March).

    1 Apr 2025 – 31 Mar 2026 is '25-26'. Computed in the store's LOCAL time, not
    UTC: an order placed at 02:00 IST on 1 April belongs to the new year, and
    reading it as 20:30 UTC on 31 March would file it in the old one.
    """
    when = timezone.localtime(when or timezone.now())
    start = when.year if when.month >= 4 else when.year - 1
    return f"{start % 100:02d}-{(start + 1) % 100:02d}"


def invoice_series(when=None):
    """The series an invoice issued at `when` belongs to, e.g. 'NM/25-26'.

    One series per financial year, which is how the continuity requirement is
    scoped — the sequence restarts at 1 each April rather than running forever.
    """
    prefix = (getattr(settings, 'INVOICE_NUMBER_PREFIX', 'NM') or 'NM').strip()
    # The full number is "<prefix>/<FY>/<6 digits>" and GST allows 16 characters
    # total; the FY and sequence take 13, so the prefix cannot exceed 3.
    return f"{prefix[:3]}/{financial_year_label(when)}"


def allocate_invoice_number(series):
    """Reserve the next sequence in `series`. Returns (number, sequence).

    Takes a row lock on the counter so two payments captured in the same
    millisecond cannot be handed the same number. The lock spans one read and
    one write, so it is not a contention point at any volume this store will
    see, and it is released with the caller's transaction.
    """
    counter, _ = InvoiceCounter.objects.get_or_create(series=series)
    # Re-fetch FOR UPDATE: get_or_create cannot lock a row it may be creating.
    counter = InvoiceCounter.objects.select_for_update().get(pk=counter.pk)
    counter.last_number += 1
    counter.save(update_fields=['last_number', 'updated_at'])
    return f"{series}/{counter.last_number:06d}", counter.last_number


# ---------------------------------------------------------------------------
# The frozen snapshot
# ---------------------------------------------------------------------------

def _s(value):
    """Money as a plain string — JSON has no Decimal, and floats lose paise."""
    return str(Decimal(str(value or 0)).quantize(Decimal('0.01')))


def _customer_name(user):
    if not user:
        return "Guest"
    name = (getattr(user, 'name', '') or '').strip()
    if name:
        return name
    full = f"{user.first_name} {user.last_name}".strip()
    return full or user.email


def build_invoice_snapshot(order):
    """Everything the invoice PDF prints, captured as of now.

    Read once at issue and never again. The renderer takes this dict and nothing
    else — no settings lookup, no order attribute — which is what guarantees a
    reprint in two years is byte-identical to the original.

    Line items and their GST rates are ALREADY snapshotted on OrderItem /
    OrderItemComponent, so those figures cannot drift; they are copied here
    anyway so the renderer has a single source and the document survives even a
    schema change underneath it.
    """
    from .invoice import _amount_in_words, _line_hsn

    user = order.user
    items = [
        {
            'name': item.product_name,
            'hsn': _line_hsn(item),
            'pack': item.product_weight or '',
            'quantity': item.quantity,
            'rate': _s(item.price),
            'amount': _s(item.price * item.quantity),
        }
        for item in order.items.prefetch_related('components').all()
    ]

    # Place of supply decides whether the tax splits CGST+SGST or is charged as
    # IGST. The RESOLVED answer is frozen, not just the state code: `is_interstate`
    # compares the code against the seller's CURRENT state from settings, so a
    # seller who later registers in another state would otherwise flip the tax
    # heads on every historical bill.
    pos_code = order.place_of_supply_state_code or seller_state_code()
    interstate = is_interstate(order.place_of_supply_state_code)

    gst_summary = []
    for row in order_tax_breakdown(order):
        heads = split_gst(row['tax_amount'], order.place_of_supply_state_code)
        gst_summary.append({
            # None = "unattributed": a legacy line that carried tax but no rate.
            # Kept as None rather than 0, which would print as tax-exempt.
            'rate': None if row['rate'] is None else str(row['rate']),
            'rate_label': (None if row['rate'] is None else
                           head_rate_label(row['rate'], order.place_of_supply_state_code)),
            'taxable_value': (None if row['taxable_value'] is None
                              else _s(row['taxable_value'])),
            'tax_amount': _s(row['tax_amount']),
            'cgst': _s(heads['cgst']),
            'sgst': _s(heads['sgst']),
            'igst': _s(heads['igst']),
        })

    try:
        payment_method_label = order.get_payment_method_display()
    except Exception:  # noqa: BLE001 — unknown/blank method on a legacy row
        payment_method_label = order.payment_method or '-'

    return {
        'version': SNAPSHOT_VERSION,
        # Read from settings HERE, once. This is the fix for "reprints mutate":
        # changing SELLER_ADDRESS tomorrow cannot touch a bill issued today.
        'seller': {
            'name': settings.SELLER_NAME,
            'proprietor': settings.SELLER_PROPRIETOR,
            'tagline': settings.SELLER_TAGLINE,
            'address': settings.SELLER_ADDRESS,
            'gstin': settings.SELLER_GSTIN,
            'fssai': settings.SELLER_FSSAI,
            'state': settings.SELLER_STATE,
            'state_code': settings.SELLER_STATE_CODE,
            'email': settings.SELLER_EMAIL,
            'phone': settings.SELLER_PHONE,
        },
        # Frozen for the same reason: an admin can PATCH shipping_address after
        # dispatch, and that must not rewrite who the bill was made out to.
        'buyer': {
            'name': _customer_name(user),
            'address': order.shipping_address or '',
            'phone': order.phone_number or '',
            'email': getattr(user, 'email', '') or '',
        },
        'order': {
            'number': f"ORD-{order.id:06d}",
            'placed_at': order.created_at.isoformat(),
            'payment_method': order.payment_method or '',
            'payment_method_label': payment_method_label,
            # Status AT ISSUE. Always 'paid' for online, and 'pending' for a COD
            # order still awaiting the courier's cash — which is the truth on the
            # day the bill was raised, and stays true on the document forever.
            'payment_status': order.payment_status or '',
            'tax_inclusive': bool(getattr(order, 'tax_inclusive', True)),
        },
        'place_of_supply': {
            'code': pos_code,
            'name': state_name(pos_code) or settings.SELLER_STATE,
            'interstate': interstate,
        },
        'items': items,
        'totals': {
            'subtotal': _s(order.subtotal),
            'discount_amount': _s(order.discount_amount),
            'coupon_code': order.coupon_code or '',
            'shipping_charge': _s(order.shipping_charge),
            'shipping_tax': _s(order.shipping_tax),
            'shipping_tax_rate': str(SHIPPING_TAX_RATE),
            'tax': _s(order.tax),
            'total_tax': _s(order.total_tax),
            'total_amount': _s(order.total_amount),
            'amount_in_words': _amount_in_words(order.total_amount),
        },
        'gst_summary': gst_summary,
    }


# ---------------------------------------------------------------------------
# Issuing
# ---------------------------------------------------------------------------

def invoice_is_due(order):
    """True when `order` has reached the point a tax invoice must be raised.

    The test is "did the supply happen?", asked in a payment-method-agnostic
    way, because there are two independent pieces of evidence for it and either
    is sufficient:

    * **Money was received** — `payment_status` in {paid, refunded}. That is
      capture for an online order, and the confirmed-cash tick for a COD one.
      `refunded` counts and MUST count: a refund can only be recorded against
      money actually taken, so a refunded order is one that was definitely
      supplied. Leaving it uninvoiced would strand its credit note with nothing
      to cite (see `_credited_invoice_ref`) — the exact hole this closes for
      historical orders being backfilled.
    * **Goods went out** — status in `DISPATCHED_STATUSES`. This is the COD
      case, whose money arrives days after the parcel does.

    A CANCELLED order is never invoiced regardless: nothing was supplied. A
    capture against a cancelled order is an exception routed to a refund, not a
    sale (see payments/services.py).

    Returns False if one already exists — issuing is idempotent, and a second
    invoice for the same supply would bill it twice in the series.
    """
    if order.pk is None or (order.status or '') == 'cancelled':
        return False
    if Invoice.objects.filter(order_id=order.pk).exists():
        return False
    if (order.payment_status or '') in MONEY_RECEIVED_STATUSES:
        return True
    return (order.status or '') in DISPATCHED_STATUSES


def issue_invoice(order, when=None):
    """Raise the tax invoice for `order`. Returns (Invoice, created).

    Idempotent: an order that already has one gets it back untouched. Callers
    should normally use `maybe_issue_invoice`, which applies `invoice_is_due`
    first; this function issues unconditionally and exists for the backfill
    command and for tests.
    """
    existing = Invoice.objects.filter(order_id=order.pk).first()
    if existing:
        return existing, False

    issued_at = when or timezone.now()
    snapshot = build_invoice_snapshot(order)
    number, sequence = allocate_invoice_number(invoice_series(issued_at))
    try:
        # Own savepoint: losing the unique-constraint race must not poison the
        # caller's transaction (a payment capture, in the common case).
        with transaction.atomic():
            invoice = Invoice.objects.create(
                order=order,
                number=number,
                series=invoice_series(issued_at),
                sequence=sequence,
                issued_at=issued_at,
                total_amount=Decimal(snapshot['totals']['total_amount']),
                total_tax=Decimal(snapshot['totals']['total_tax']),
                snapshot=snapshot,
            )
    except IntegrityError:
        # Another worker invoiced the same order between our check and insert.
        # Theirs is as valid as ours would have been; ours burns a number, which
        # is a gap we accept over the alternative of two invoices for one supply.
        existing = Invoice.objects.filter(order_id=order.pk).first()
        if existing is None:
            raise
        logger.warning("Invoice race on order %s; kept %s, dropped %s",
                       order.pk, existing.number, number)
        return existing, False

    logger.info("Issued invoice %s for order %s (%s).",
                invoice.number, order.pk, invoice.total_amount)
    return invoice, True


def maybe_issue_invoice(order, when=None):
    """Issue the invoice if it is due, swallowing any failure. Returns Invoice|None.

    Called from payment capture and from the admin order edit, both of which run
    inside a transaction that has already done something more important — taken
    money, or dispatched goods. A bug in document generation must never roll
    that back, so failures are logged and left for `backfill_invoices` to pick
    up. The nested atomic() is what keeps a failure from poisoning the caller's
    transaction rather than merely being caught.
    """
    try:
        if not invoice_is_due(order):
            return None
        with transaction.atomic():
            invoice, _ = issue_invoice(order, when=when)
        return invoice
    except Exception:  # noqa: BLE001 — never break payment/dispatch over a PDF
        logger.exception("Failed to issue invoice for order %s", getattr(order, 'pk', None))
        return None
