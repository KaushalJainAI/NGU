"""HSN-wise summary of outward supplies — the data behind GSTR-1 Table 12.

Table 12 asks, for every HSN code supplied in a return period: the unit
quantity, the total quantity, the taxable (net) value and the tax. Nothing else
in this codebase can produce it, because the per-slab breakup on an invoice is
keyed by RATE and a rate does not identify a heading — 5% alone covers 0904,
0909, 0910 and more.

WHERE THE NUMBERS COME FROM
---------------------------
Line snapshots, never the catalogue:

  * a PRODUCT line contributes its own `hsn_code`, `tax_rate`, `quantity` and
    `final_price` (post-discount, GST-INCLUSIVE, which is what was charged);
  * a COMBO line contributes NOTHING itself — a bundle is a mixed supply with no
    single code — and instead contributes one row per `OrderItemComponent`,
    which carries the component's own code, rate, units and allocated amount.
    Those allocations sum exactly to the combo line's `final_price`, so the two
    paths cannot double-count or lose money between them;
  * DELIVERY is a service, not goods, and is reported under its SAC on its own
    row. It is billed net + GST (the opposite convention to goods), so its gross
    is fee + `shipping_tax`.

Reading snapshots is the whole point: re-classifying a product today must not
change a return that was already filed for last quarter.

WHICH ORDERS COUNT
------------------
`analytics.management.commands.rollup_analytics.countable_orders()` — everything
except cancelled and soft-deleted orders. Deliberately the same filter the sales
dashboard uses, so the HSN summary and the revenue figure on the next screen
cannot disagree.

WHAT THIS DOES **NOT** DO
-------------------------
* **Refunds are not netted off.** A refund reverses tax (see
  `pricing.refund_tax_for`) but it is a credit note, and credit notes are
  Table 9B, not Table 12. Netting them into the HSN rows would silently
  under-report outward supply. `refunded_in_period` is reported alongside as a
  reconciling figure, not subtracted.
* **No CGST/SGST/IGST split.** That is a place-of-supply question and lives with
  the order, not the HSN.
* **It is not a filing.** It is the arithmetic, for a human (or their CA) to
  file. Unclassified lines are reported under an explicit '' code rather than
  being dropped, so an incomplete catalogue shows up as a visible hole instead
  of a summary that quietly does not add up.
"""
from decimal import Decimal

from django.db.models import Sum

from products.hsn import describe
from spices_backend.limits import SHIPPING_TAX_RATE
from spices_backend.timeranges import range_filter

from .models import OrderItem
from .pricing import PAISA

# Unit Quantity Code reported in Table 12. Everything in this catalogue is sold
# as a sealed pack of a fixed weight, and the order line counts PACKS, not grams
# — so PAC is the honest UQC. (Reporting KGS would require converting each
# line's pack weight, which the snapshot does not carry reliably.)
GOODS_UQC = 'PAC'

# Delivery is a service. 9968 is the postal/courier services heading; the app
# has charged delivery under it since shipping became taxable (see
# orders/invoice.py). OTH is the UQC used for services, which have no quantity.
SHIPPING_SAC = '9968'
SHIPPING_UQC = 'OTH'

# Reported in place of a code when a product was never classified. Kept as a
# real row so the total still reconciles and the gap is impossible to miss.
UNCLASSIFIED = ''


def _countable_orders():
    # Imported lazily: analytics imports orders models, so a module-level import
    # here would close the cycle.
    from analytics.management.commands.rollup_analytics import countable_orders
    return countable_orders()


def hsn_summary(start, end):
    """HSN x rate rows for orders placed in [start, end].

    `start`/`end` are dates (inclusive). Returns::

        {'rows': [{hsn_code, description, rate, uqc, quantity,
                   taxable_value, tax_amount, total_value, is_service,
                   is_unclassified}, …],
         'totals': {quantity, taxable_value, tax_amount, total_value},
         'order_count': int,
         'unclassified_value': Decimal,
         'refunded_in_period': {'amount': Decimal, 'tax': Decimal}}

    Rows are sorted by code then rate, with unclassified last so it reads as the
    exception it is.
    """
    # range_filter, not __date__gte: the latter wraps created_at in a timezone
    # expression and loses the index (see spices_backend/timeranges.py).
    orders = _countable_orders().filter(**range_filter('created_at', start, end))

    # (code, rate) -> {'qty', 'gross', 'tax'}. Amounts accumulate GROSS
    # (GST-inclusive) and the net is derived once at the end, so a slab's
    # taxable value is never the sum of independently-rounded per-line nets.
    buckets = {}

    def add(code, rate, qty, gross, tax):
        key = ((code or '').strip(), Decimal(str(rate or 0)))
        slab = buckets.setdefault(
            key, {'qty': 0, 'gross': Decimal('0.00'), 'tax': Decimal('0.00')})
        slab['qty'] += qty
        slab['gross'] += Decimal(str(gross or 0))
        slab['tax'] += Decimal(str(tax or 0))

    items = (OrderItem.objects
             .filter(order__in=orders)
             .prefetch_related('components')
             .only('id', 'item_type', 'hsn_code', 'tax_rate', 'quantity',
                   'final_price', 'tax_amount', 'order_id'))
    for item in items:
        components = list(item.components.all())
        if components:
            # Combo line: the components ARE the supply. The line itself is
            # skipped entirely — counting both would double the value.
            for c in components:
                add(c.hsn_code, c.tax_rate, c.quantity, c.allocated_amount, c.tax_amount)
            continue
        add(item.hsn_code, item.tax_rate, item.quantity,
            item.final_price, item.tax_amount)

    # Delivery, as its own service row. Only orders that actually carried a
    # shipping charge contribute — a free-shipping order supplies no service.
    ship = orders.filter(shipping_charge__gt=0).aggregate(
        fee=Sum('shipping_charge'), tax=Sum('shipping_tax'))
    fee = Decimal(str(ship['fee'] or 0))
    ship_tax = Decimal(str(ship['tax'] or 0))
    if fee > 0:
        # Gross = net fee + the GST added on top, matching how it was billed.
        add(SHIPPING_SAC, SHIPPING_TAX_RATE, 0, fee + ship_tax, ship_tax)

    rows = []
    for (code, rate), slab in buckets.items():
        gross = slab['gross'].quantize(PAISA)
        tax = slab['tax'].quantize(PAISA)
        ref = describe(code)
        rows.append({
            'hsn_code': code,
            'description': (
                'NOT CLASSIFIED — assign an HSN code to these products'
                if not code else
                ('Delivery / courier service' if code == SHIPPING_SAC
                 else (ref['description'] if ref else 'Not in the reference list'))
            ),
            'rate': float(rate),
            'uqc': SHIPPING_UQC if code == SHIPPING_SAC else GOODS_UQC,
            'quantity': slab['qty'],
            'taxable_value': gross - tax,
            'tax_amount': tax,
            'total_value': gross,
            'is_service': code == SHIPPING_SAC,
            'is_unclassified': not code,
        })

    # Unclassified last; everything else by code then rate.
    rows.sort(key=lambda r: (r['is_unclassified'], r['hsn_code'], r['rate']))

    totals = {
        'quantity': sum(r['quantity'] for r in rows),
        'taxable_value': sum((r['taxable_value'] for r in rows), Decimal('0.00')),
        'tax_amount': sum((r['tax_amount'] for r in rows), Decimal('0.00')),
        'total_value': sum((r['total_value'] for r in rows), Decimal('0.00')),
    }

    # Credit notes for the same window, reported but NOT netted off (Table 9B,
    # not Table 12). Bucketed by REFUND date, which is when the credit note
    # arises — not by the date of the order being refunded.
    refunds = _refunds_in_period(start, end)

    return {
        'rows': rows,
        'totals': totals,
        'order_count': orders.count(),
        'unclassified_value': sum(
            (r['total_value'] for r in rows if r['is_unclassified']), Decimal('0.00')),
        'refunded_in_period': refunds,
        'shipping_sac': SHIPPING_SAC,
    }


def _refunds_in_period(start, end):
    """Refunds recorded in the window, as a reconciling figure only.

    Falls back to zeroes if the refund ledger is not present in this deployment,
    so the HSN summary never fails wholesale over a supplementary number.
    """
    try:
        from .models import OrderRefund
    except ImportError:  # pragma: no cover - ledger always present today
        return {'amount': Decimal('0.00'), 'tax': Decimal('0.00')}
    agg = (OrderRefund.objects
           .filter(**range_filter('created_at', start, end))
           .aggregate(amount=Sum('amount'), tax=Sum('tax_amount')))
    return {
        'amount': Decimal(str(agg['amount'] or 0)),
        'tax': Decimal(str(agg['tax'] or 0)),
    }


def unclassified_products():
    """Active products with no HSN code — the work list for the admin.

    Anything here lands in the UNCLASSIFIED row of every future summary, so the
    admin panel shows the count as a standing warning rather than waiting for
    someone to run a report at filing time.
    """
    from products.models import Product
    return (Product.objects
            .filter(is_active=True, hsn_code='')
            .order_by('name')
            .values('id', 'name', 'tax_rate'))
