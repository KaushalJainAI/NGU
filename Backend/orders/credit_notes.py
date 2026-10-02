"""Issue GST credit notes: the TAX documents that reverse output tax.

A credit note is the tax document; `OrderRefund` stays the cash record. Two
origins: (a) every recorded refund, and (b) cancelling an invoiced order while
no money is held (e.g. a COD parcel returned to origin).

Number format: `CN/25-26/000001`. Series: `f"CN/{financial_year_label(when)}"`.
The counter table (`InvoiceCounter`) works for any series name, so it is reused
via `allocate_invoice_number` from `orders/invoicing.py`.
"""
import logging
from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction
from django.utils import timezone

from spices_backend.timeranges import range_filter  # noqa: F401  (re-exported for tests)

from .invoicing import _s, allocate_invoice_number, financial_year_label

logger = logging.getLogger(__name__)

PAISA = Decimal('0.01')


def _split_tax(tax, interstate):
    """Split `tax` into heads using the FROZEN interstate flag.

    Interstate → all IGST; otherwise CGST = half rounded to paisa, SGST = rest.
    The three always sum back to `tax` exactly.
    """
    tax = Decimal(str(tax or 0)).quantize(PAISA, rounding=ROUND_HALF_UP)
    zero = Decimal('0.00')
    if tax <= 0:
        return {'cgst': zero, 'sgst': zero, 'igst': zero}
    if interstate:
        return {'cgst': zero, 'sgst': zero, 'igst': tax}
    cgst = (tax / 2).quantize(PAISA, rounding=ROUND_HALF_UP)
    return {'cgst': cgst, 'sgst': tax - cgst, 'igst': zero}


def _snapshot_rows(rows, interstate):
    """Build snapshot rows (strings, 2 decimals) from rate/taxable/tax triples."""
    out = []
    for row in rows:
        rate = row.get('rate')
        taxable = row.get('taxable_value')
        tax = Decimal(str(row.get('tax_amount') or 0)).quantize(PAISA)
        heads = _split_tax(tax, interstate)
        out.append({
            'rate': None if rate is None else str(rate),
            'taxable_value': None if taxable is None else _s(taxable),
            'tax_amount': _s(tax),
            'cgst': _s(heads['cgst']),
            'sgst': _s(heads['sgst']),
            'igst': _s(heads['igst']),
        })
    return out


def _allocate(series):
    number, sequence = allocate_invoice_number(series)
    return number, sequence


def issue_credit_note_for_refund(refund):
    """Issue the credit note for one `OrderRefund`. Returns CreditNote|None.

    Idempotent: an existing note for this refund is returned untouched. None
    when the order has no invoice (nothing to cite).
    """
    from .invoice import credit_note_tax_rows
    from .models import CreditNote

    if CreditNote.objects.filter(refund=refund).exists():
        return CreditNote.objects.filter(refund=refund).first()
    order = refund.order
    invoice = getattr(order, 'invoice', None)
    if invoice is None:
        # Refresh through the DB: `order.invoice` reverse-OneToOne may be cached
        # as missing on a stale instance.
        from .models import Invoice
        invoice = Invoice.objects.filter(order_id=order.pk).first()
        if invoice is None:
            return None
    pos = (invoice.snapshot or {}).get('place_of_supply', {}) or {}
    interstate = bool(pos.get('interstate'))
    tax_rows = credit_note_tax_rows(refund)
    if not tax_rows and Decimal(str(refund.amount or 0)) > 0:
        # A refund that reverses no tax is a refund of nil-rated goods (papad):
        # `credit_note_tax_rows` scales by tax share, so it has nothing to
        # scale and returns no rows. The credited VALUE is still real and must
        # appear under the 0% slab, or the state-wise report overstates it.
        tax_rows = [{'rate': 0.0, 'taxable_value': refund.amount, 'tax_amount': 0}]
    rows = _snapshot_rows(tax_rows, interstate)
    issued_at = refund.created_at or timezone.now()
    series = f"CN/{financial_year_label(issued_at)}"
    number, sequence = _allocate(series)
    snapshot = {
        'version': 1,
        'invoice_number': invoice.number,
        'place_of_supply': {'code': pos.get('code', ''), 'interstate': interstate},
        'rows': rows,
    }
    note = CreditNote.objects.create(
        order=order, invoice=invoice, refund=refund, reason='refund',
        number=number, series=series, sequence=sequence, issued_at=issued_at,
        total_amount=Decimal(str(refund.amount or 0)).quantize(PAISA),
        total_tax=Decimal(str(refund.tax_amount or 0)).quantize(PAISA),
        snapshot=snapshot,
    )
    logger.info("Issued credit note %s for refund %s.", number, refund.pk)
    return note


def issue_credit_note_for_cancellation(order):
    """Issue the credit note for cancelling an invoiced, unpaid order.

    Returns None unless ALL are true: status cancelled, has invoice,
    payment_status NOT in (paid, refunded), and no cancellation note exists yet.
    Covers the remaining invoice value (invoice total minus earlier notes).
    """
    from .models import CreditNote, Invoice

    if (order.status or '') != 'cancelled':
        return None
    invoice = getattr(order, 'invoice', None)
    if invoice is None:
        invoice = Invoice.objects.filter(order_id=order.pk).first()
        if invoice is None:
            return None
    if (order.payment_status or '') in ('paid', 'refunded'):
        return None
    if CreditNote.objects.filter(order_id=order.pk, reason='cancellation').exists():
        return None
    existing = CreditNote.objects.filter(order_id=order.pk)
    credited_amount = sum((n.total_amount for n in existing), Decimal('0.00'))
    credited_tax = sum((n.total_tax for n in existing), Decimal('0.00'))
    total_amount = Decimal(str(invoice.total_amount or 0)) - credited_amount
    total_tax = Decimal(str(invoice.total_tax or 0)) - credited_tax
    if total_amount <= 0:
        return None
    pos = (invoice.snapshot or {}).get('place_of_supply', {}) or {}
    interstate = bool(pos.get('interstate'))
    gst_rows = (invoice.snapshot or {}).get('gst_summary', []) or []
    inv_tax = Decimal(str(invoice.total_tax or 0))
    scale = (total_tax / inv_tax) if inv_tax > 0 else Decimal('0')
    scaled = []
    for row in gst_rows:
        taxable = row.get('taxable_value')
        tax = Decimal(str(row.get('tax_amount') or 0)) * scale
        scaled.append({
            'rate': (Decimal(str(row['rate'])) if row.get('rate') is not None else None),
            'taxable_value': (
                None if taxable is None
                else float((Decimal(str(taxable)) * scale).quantize(PAISA, rounding=ROUND_HALF_UP))),
            'tax_amount': float(tax.quantize(PAISA, rounding=ROUND_HALF_UP)),
        })
    # Fix the rounding residual so rows sum to total_tax.
    current = sum((Decimal(str(r['tax_amount'])) for r in scaled), Decimal('0.00'))
    residual = (total_tax.quantize(PAISA) - current).quantize(PAISA)
    if residual and scaled:
        biggest = max(range(len(scaled)), key=lambda i: scaled[i]['tax_amount'])
        scaled[biggest]['tax_amount'] = float(
            (Decimal(str(scaled[biggest]['tax_amount'])) + residual).quantize(PAISA))
    rows = _snapshot_rows(scaled, interstate)
    issued_at = timezone.now()
    series = f"CN/{financial_year_label(issued_at)}"
    number, sequence = _allocate(series)
    snapshot = {
        'version': 1,
        'invoice_number': invoice.number,
        'place_of_supply': {'code': pos.get('code', ''), 'interstate': interstate},
        'rows': rows,
    }
    note = CreditNote.objects.create(
        order=order, invoice=invoice, refund=None, reason='cancellation',
        number=number, series=series, sequence=sequence, issued_at=issued_at,
        total_amount=total_amount.quantize(PAISA),
        total_tax=total_tax.quantize(PAISA),
        snapshot=snapshot,
    )
    logger.info("Issued cancellation credit note %s for order %s.", number, order.pk)
    return note


def maybe_issue_credit_note_for_refund(refund):
    """Issue the refund credit note, swallowing any failure. Returns note|None."""
    try:
        with transaction.atomic():
            return issue_credit_note_for_refund(refund)
    except Exception:  # noqa: BLE001 — never break the refund over a document
        logger.exception("Failed to issue credit note for refund %s", getattr(refund, 'pk', None))
        return None


def maybe_issue_credit_note_for_cancellation(order):
    """Issue the cancellation credit note, swallowing any failure."""
    try:
        with transaction.atomic():
            return issue_credit_note_for_cancellation(order)
    except Exception:  # noqa: BLE001
        logger.exception("Failed to issue cancellation credit note for order %s", getattr(order, 'pk', None))
        return None
