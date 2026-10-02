"""GST ledger on the INVOICE basis — what the return is filed from.

GST is owed on INVOICES by INVOICE DATE, not on orders by order date. Every
figure here reads issued `Invoice` / `CreditNote` rows (and their frozen
snapshots), never live orders:

* an order with no invoice appears in NO report — nothing was supplied;
* a COD order placed on the 30th and dispatched on the 2nd is invoiced (and
  reported) in the new month;
* cancelling an invoiced order never deletes its invoice — the reversal is a
  credit note in its own period.

Invoices count even if the order was later cancelled or moved to the Recycle
Bin. The credit note is what reverses them.
"""
from collections import defaultdict
from decimal import Decimal

from django.utils import timezone

from spices_backend.timeranges import range_filter

from .models import CreditNote, Invoice
from .place_of_supply import state_name

PAISA = Decimal('0.01')


def invoices_in(start, end):
    return Invoice.objects.filter(**range_filter('issued_at', start, end)).select_related('order')


def credit_notes_in(start, end):
    return CreditNote.objects.filter(**range_filter('issued_at', start, end)).select_related('order', 'invoice')


def _heads_of(rows):
    cgst = sgst = igst = Decimal('0.00')
    for row in rows or []:
        cgst += Decimal(str(row.get('cgst') or 0))
        sgst += Decimal(str(row.get('sgst') or 0))
        igst += Decimal(str(row.get('igst') or 0))
    return cgst, sgst, igst


def _block(count, total, tax, cgst, sgst, igst):
    total = Decimal(str(total or 0))
    tax = Decimal(str(tax or 0))
    return {
        'count': count,
        'taxable_value': total - tax,
        'cgst': cgst,
        'sgst': sgst,
        'igst': igst,
        'tax': tax,
        'total': total,
    }


def period_summary(start, end):
    """Invoices, credit notes and net for [start, end] (inclusive dates)."""
    invoices = list(invoices_in(start, end))
    notes = list(credit_notes_in(start, end))

    inv_total = sum((Decimal(str(i.total_amount or 0)) for i in invoices), Decimal('0.00'))
    inv_tax = sum((Decimal(str(i.total_tax or 0)) for i in invoices), Decimal('0.00'))
    inv_cgst = inv_sgst = inv_igst = Decimal('0.00')
    for inv in invoices:
        c, s, g = _heads_of((inv.snapshot or {}).get('gst_summary'))
        inv_cgst += c
        inv_sgst += s
        inv_igst += g

    cn_total = sum((Decimal(str(n.total_amount or 0)) for n in notes), Decimal('0.00'))
    cn_tax = sum((Decimal(str(n.total_tax or 0)) for n in notes), Decimal('0.00'))
    cn_cgst = cn_sgst = cn_igst = Decimal('0.00')
    for note in notes:
        c, s, g = _heads_of((note.snapshot or {}).get('rows'))
        cn_cgst += c
        cn_sgst += s
        cn_igst += g

    inv_block = _block(len(invoices), inv_total, inv_tax, inv_cgst, inv_sgst, inv_igst)
    cn_block = _block(len(notes), cn_total, cn_tax, cn_cgst, cn_sgst, cn_igst)
    net = {k: inv_block[k] - cn_block[k] for k in
           ('taxable_value', 'cgst', 'sgst', 'igst', 'tax', 'total')}
    return {'invoices': inv_block, 'credit_notes': cn_block, 'net': net}


def _rate_key(rate):
    if rate is None:
        return None
    try:
        return float(Decimal(str(rate)))
    except Exception:  # noqa: BLE001
        return None


def b2c_by_state(start, end):
    """Gross/credit/net per (place-of-supply, rate)."""
    gross = defaultdict(lambda: {'taxable': Decimal('0.00'), 'cgst': Decimal('0.00'),
                                 'sgst': Decimal('0.00'), 'igst': Decimal('0.00')})
    credit = defaultdict(lambda: {'taxable': Decimal('0.00'), 'cgst': Decimal('0.00'),
                                  'sgst': Decimal('0.00'), 'igst': Decimal('0.00')})

    for inv in invoices_in(start, end):
        pos = (inv.snapshot or {}).get('place_of_supply', {}) or {}
        code = pos.get('code') or ''
        for row in (inv.snapshot or {}).get('gst_summary', []) or []:
            key = (code, _rate_key(row.get('rate')))
            taxable = row.get('taxable_value')
            gross[key]['taxable'] += Decimal(str(taxable or 0))
            gross[key]['cgst'] += Decimal(str(row.get('cgst') or 0))
            gross[key]['sgst'] += Decimal(str(row.get('sgst') or 0))
            gross[key]['igst'] += Decimal(str(row.get('igst') or 0))

    for note in credit_notes_in(start, end):
        pos = (note.snapshot or {}).get('place_of_supply', {}) or {}
        code = pos.get('code') or ''
        for row in (note.snapshot or {}).get('rows', []) or []:
            key = (code, _rate_key(row.get('rate')))
            taxable = row.get('taxable_value')
            credit[key]['taxable'] += Decimal(str(taxable or 0))
            credit[key]['cgst'] += Decimal(str(row.get('cgst') or 0))
            credit[key]['sgst'] += Decimal(str(row.get('sgst') or 0))
            credit[key]['igst'] += Decimal(str(row.get('igst') or 0))

    rows = []
    for (code, rate) in sorted(set(list(gross) + list(credit)),
                               key=lambda k: (k[0], k[1] if k[1] is not None else -1)):
        g = gross.get((code, rate), {'taxable': Decimal('0.00'), 'cgst': Decimal('0.00'),
                                     'sgst': Decimal('0.00'), 'igst': Decimal('0.00')})
        c = credit.get((code, rate), {'taxable': Decimal('0.00'), 'cgst': Decimal('0.00'),
                                      'sgst': Decimal('0.00'), 'igst': Decimal('0.00')})
        rows.append({
            'state_code': code,
            'state_name': state_name(code) or ('Unattributed' if not code else code),
            'rate': rate,
            'rate_label': 'Unattributed' if rate is None else f"{rate:g}%",
            'gross_taxable_value': g['taxable'],
            'gross_cgst': g['cgst'],
            'gross_sgst': g['sgst'],
            'gross_igst': g['igst'],
            'credit_taxable_value': c['taxable'],
            'credit_cgst': c['cgst'],
            'credit_sgst': c['sgst'],
            'credit_igst': c['igst'],
            'net_taxable_value': g['taxable'] - c['taxable'],
            'net_cgst': g['cgst'] - c['cgst'],
            'net_sgst': g['sgst'] - c['sgst'],
            'net_igst': g['igst'] - c['igst'],
        })
    return rows


def documents_issued(start, end):
    """Per-series document ranges with gap detection."""
    out = {'invoices': [], 'credit_notes': []}
    for key, qs in (('invoices', invoices_in(start, end)), ('credit_notes', credit_notes_in(start, end))):
        by_series = defaultdict(list)
        for doc in qs:
            by_series[doc.series].append(doc)
        for series in sorted(by_series):
            docs = sorted(by_series[series], key=lambda d: d.sequence)
            sequences = [d.sequence for d in docs]
            count = len(docs)
            gap = (max(sequences) - min(sequences) + 1) - count if sequences else 0
            out[key].append({
                'series': series,
                'from_number': docs[0].number,
                'to_number': docs[-1].number,
                'count': count,
                'gap': gap,
            })
    return out


def _taxable_of(total, tax):
    return Decimal(str(total or 0)) - Decimal(str(tax or 0))


def invoice_register(start, end):
    rows = []
    for inv in invoices_in(start, end).order_by('issued_at', 'id'):
        snap = inv.snapshot or {}
        totals_pos = snap.get('place_of_supply', {}) or {}
        buyer = snap.get('buyer', {}) or {}
        order = getattr(inv, 'order', None)
        c, s, g = _heads_of(snap.get('gst_summary'))
        rows.append({
            'number': inv.number,
            'issued_on': timezone.localtime(inv.issued_at).date().isoformat(),
            'order_number': f"ORD-{inv.order_id:06d}",
            'buyer': buyer.get('name', ''),
            'place_of_supply': totals_pos.get('name', ''),
            'taxable_value': _taxable_of(inv.total_amount, inv.total_tax),
            'cgst': c,
            'sgst': s,
            'igst': g,
            'total_tax': inv.total_tax,
            'total': inv.total_amount,
            'payment_method': getattr(order, 'payment_method', '') or '',
            'status': getattr(order, 'status', '') or '',
        })
    return rows


def credit_note_register(start, end):
    rows = []
    for note in credit_notes_in(start, end).order_by('issued_at', 'id'):
        c, s, g = _heads_of((note.snapshot or {}).get('rows'))
        rows.append({
            'number': note.number,
            'issued_on': timezone.localtime(note.issued_at).date().isoformat(),
            'reason': note.reason,
            'invoice_number': getattr(note.invoice, 'number', ''),
            'order_number': f"ORD-{note.order_id:06d}",
            'taxable_value': _taxable_of(note.total_amount, note.total_tax),
            'cgst': c,
            'sgst': s,
            'igst': g,
            'total_tax': note.total_tax,
            'total': note.total_amount,
        })
    return rows


def fallback_place_of_supply(start, end):
    rows = []
    for inv in invoices_in(start, end).order_by('issued_at', 'id'):
        order = getattr(inv, 'order', None)
        if order is None or not getattr(order, 'place_of_supply_is_fallback', False):
            continue
        rows.append({
            'number': inv.number,
            'order_number': f"ORD-{inv.order_id:06d}",
            'address': getattr(order, 'shipping_address', '') or '',
        })
    return rows
