"""Shared money helpers for cart previews, coupon previews, and placed orders.

Prices in this store are **GST-inclusive** (MRP): the number the admin enters and
the number the customer sees on the product card is the final amount payable.
GST is therefore never *added* to a total — it is *extracted* from it for
disclosure on the cart summary, the checkout breakdown, and the tax invoice.

    gross = net + net * rate/100   =>   tax = gross * rate / (100 + rate)

Every surface that reports a tax figure must call `extract_tax` so the cart
preview, the coupon preview, and the order that finally gets written all agree
to the paisa. They used to carry three separate copies of the old additive
formula, which is exactly how they drifted apart.
"""

from decimal import Decimal, ROUND_HALF_UP

from spices_backend.limits import DEFAULT_TAX_RATE, SHIPPING_TAX_RATE

PAISA = Decimal('0.01')


def add_tax(net, rate):
    """GST payable ON TOP of `net` at `rate` percent, rounded to paisa.

    The mirror of `extract_tax`, for the one part of an order priced EXCLUSIVE
    of GST: the delivery fee. Goods carry GST inside their MRP, so they use
    `extract_tax`; shipping is quoted net and taxed on top, so it uses this.
    Mixing the two up silently mis-states the bill by the tax on the fee.
    """
    net = Decimal(str(net or 0))
    rate = Decimal(str(rate or 0))
    if net <= 0 or rate <= 0:
        return Decimal('0.00')
    return (net * rate / Decimal('100')).quantize(PAISA, rounding=ROUND_HALF_UP)


def shipping_tax_for(shipping_charge):
    """GST on a delivery fee at the configured SHIPPING_TAX_RATE.

    Free shipping (0) carries no tax, so a qualifying order stays untaxed on the
    delivery line rather than picking up a phantom 18% of nothing.
    """
    return add_tax(shipping_charge, SHIPPING_TAX_RATE)


def extract_tax(gross, rate):
    """GST contained *within* `gross` at `rate` percent, rounded to paisa.

    `rate` of 0 (papad / papad katran) returns 0. Both arguments are coerced to
    Decimal so callers may pass floats, strings, or Decimals.
    """
    gross = Decimal(str(gross or 0))
    rate = Decimal(str(rate or 0))
    if gross <= 0 or rate <= 0:
        return Decimal('0.00')
    return (gross * rate / (Decimal('100') + rate)).quantize(PAISA, rounding=ROUND_HALF_UP)


def group_tax_by_rate(lines):
    """Group `(gross, rate)` pairs into a per-slab GST breakdown.

    A cart legitimately mixes rates — papad is 0%, everything else 5% — so a
    single "GST ₹19.05" line doesn't tell the customer what was actually taxed.
    Returns one row per rate, cheapest slab first:

        [{'rate': 0.0,  'taxable_value': 100.0, 'tax_amount': 0.0},
         {'rate': 5.0,  'taxable_value': 400.0, 'tax_amount': 19.05}]

    `taxable_value` is the NET (pre-GST) value of that slab — gross minus the
    tax contained in it — which is the figure a GST return wants. Rows sum to
    the same total as summing `extract_tax` per line, because it is the same
    per-line rounding, only bucketed.

    NOTE: this is a rate-slab breakdown, not yet split into tax heads. The
    CGST/SGST vs IGST split is applied ON TOP of these rows from the order's
    `place_of_supply_state_code` — see `orders/place_of_supply.py::split_gst`.
    Kept separate because the slab breakdown is also quoted for a CART, which
    has no destination yet.
    """
    buckets = {}
    for gross, rate in lines:
        gross = Decimal(str(gross or 0))
        rate = Decimal(str(rate or 0))
        tax = extract_tax(gross, rate)
        slab = buckets.setdefault(rate, {'gross': Decimal('0.00'), 'tax': Decimal('0.00')})
        slab['gross'] += gross
        slab['tax'] += tax
    return [
        {
            'rate': float(rate),
            'taxable_value': float((slab['gross'] - slab['tax']).quantize(PAISA)),
            'tax_amount': float(slab['tax'].quantize(PAISA)),
        }
        for rate, slab in sorted(buckets.items())
    ]


def order_tax_breakdown(order):
    """Per-GST-slab breakup for a PLACED order, from its stored line snapshots.

    Uses each line's snapshotted `tax_rate` and its post-discount `final_price`,
    so the rows reproduce what was actually charged even if the product has since
    been re-rated. Legacy lines (written before the rate was snapshotted) carry
    tax_rate=0 but a non-zero tax_amount; those go under a `rate: None` row
    rather than being mislabelled as 0% — which would read as "tax-exempt" on a
    bill and be plainly wrong.

    The rows always sum to `order.total_tax` — goods GST plus the GST on the
    delivery fee, which appears as its own 18% slab. Anything the lines can't
    account for — an old order that only ever carried an order-level tax figure
    — lands in the `rate: None` row, so the invoice's GST summary reconciles
    against its own total instead of quietly disagreeing with it.

    Both serializers call this per order in a paginated list, so it must never
    issue its own queries when the caller has prefetched. `order.items.all()` is
    served straight from the prefetch cache; adding `.prefetch_related()` here
    would clone the queryset, drop that cache, and re-query per row.
    """
    lines, legacy_tax = [], Decimal('0.00')
    items = order.items.all()
    if 'items' not in getattr(order, '_prefetched_objects_cache', {}):
        # Unprefetched caller (invoice rendering, a single order) — pull the
        # components in one go rather than one query per line.
        items = items.prefetch_related('components')
    for item in items:
        # A combo line is a MIXED SUPPLY. Its stored `tax_rate` is only the
        # blended effective rate; the audited per-slab rows come from the
        # component split written at checkout. Combo lines with no components
        # predate that split — fall through and use the single stored rate,
        # which is genuinely what they were charged at.
        components = list(item.components.all())
        if components:
            lines.extend(
                (c.allocated_amount, Decimal(str(c.tax_rate or 0))) for c in components
            )
            continue

        rate = Decimal(str(item.tax_rate or 0))
        tax = Decimal(str(item.tax_amount or 0))
        if rate <= 0 and tax > 0:
            legacy_tax += tax
            continue
        lines.append((item.final_price, rate))

    # The delivery fee is its own taxable supply (SAC 9968, 18%) and belongs on
    # the breakup as its own slab — otherwise the GST summary omits it and stops
    # reconciling against the grand total. It is billed net + GST, so the GROSS
    # figure fed to the inclusive grouper is fee + its tax; that recovers exactly
    # the `shipping_tax` that was charged. 0 on free shipping and on orders
    # placed before delivery was taxed, which therefore contribute no row.
    ship_tax = Decimal(str(getattr(order, 'shipping_tax', 0) or 0))
    if ship_tax > 0:
        ship_gross = Decimal(str(order.shipping_charge or 0)) + ship_tax
        lines.append((ship_gross, SHIPPING_TAX_RATE))

    rows = group_tax_by_rate(lines)

    # Whatever the lines could not explain belongs to the unattributed row, so
    # the breakup always adds up to the order's GST. The classic case is an
    # order predating per-line tax entirely: its lines report ₹0 while the
    # header carries the real figure, and printing "0%: ₹0.00 / Total ₹19.05"
    # on a tax invoice is worse than printing nothing.
    attributed = sum(
        (Decimal(str(row['tax_amount'])) for row in rows), Decimal('0.00')
    ) + legacy_tax
    # Measured against ALL output tax on the order (goods + delivery), since the
    # delivery slab is one of the rows above. Comparing to `order.tax` alone
    # would make the shipping GST look unaccounted-for and go negative.
    charged = Decimal(str(order.tax or 0)) + ship_tax
    unattributed = (charged - attributed).quantize(PAISA)
    if unattributed < 0:
        unattributed = Decimal('0.00')
    legacy_tax += unattributed

    if legacy_tax > 0:
        rows.append({'rate': None, 'taxable_value': None, 'tax_amount': float(legacy_tax)})
    return rows


def refund_tax_for(order, refund_amount):
    """GST contained in a refund of `refund_amount` against `order`.

    Refunding money reverses the output tax that came with it, so this is what
    gets subtracted from GST owed to the government.

    The apportionment, and why:

    * **Goods first, delivery last.** A refund is treated as returning goods
      until the goods value is exhausted; only the excess is treated as refunded
      delivery. This matches the ordinary case (an item comes back, the courier
      was still paid) and never over-reverses the goods slabs.
    * **Delivery carries its own GST now.** The fee is billed net + 18%, so once
      a refund eats into the delivery portion it must reverse that 18% too —
      otherwise refunding a whole order leaves the tax on its shipping stranded
      as a liability on money already returned. The delivery share is reversed in
      proportion to how much of the gross fee (net + its GST) came back.
    * **Blended rate across goods slabs.** A refund tells us an amount, not
      *which line* it belongs to, so anything short of the whole order is
      apportioned at the order's effective rate. A FULL refund is exact — it
      reverses `order.tax` and `order.shipping_tax` precisely. Only a partial on
      a mixed-rate order is an estimate, and it rounds in no particular direction.
    * **Capped at the tax actually charged**, per component, so repeated partial
      refunds can never reverse more GST than was collected.

    Legacy tax-exclusive orders (`tax_inclusive=False`) had GST added on top, so
    their goods base is subtotal − discount + tax. Orders placed before delivery
    was taxed carry `shipping_tax=0` and are unaffected by the delivery branch.
    """
    order_tax = Decimal(str(order.tax or 0))
    ship_tax = Decimal(str(getattr(order, 'shipping_tax', 0) or 0))
    refund_amount = Decimal(str(refund_amount or 0))
    if refund_amount <= 0 or (order_tax <= 0 and ship_tax <= 0):
        return Decimal('0.00')

    goods = Decimal(str(order.subtotal or 0)) - Decimal(str(order.discount_amount or 0))
    if not getattr(order, 'tax_inclusive', True):
        goods += order_tax          # tax sat outside the subtotal on legacy orders
    goods = max(goods, Decimal('0'))

    # --- goods portion ---
    tax = Decimal('0.00')
    if goods > 0 and order_tax > 0:
        goods_refunded = min(refund_amount, goods)
        tax = (order_tax * goods_refunded / goods).quantize(PAISA, rounding=ROUND_HALF_UP)

    # --- delivery portion: whatever the refund covers BEYOND the goods value ---
    if ship_tax > 0:
        ship_gross = Decimal(str(order.shipping_charge or 0)) + ship_tax
        ship_refunded = min(max(refund_amount - goods, Decimal('0')), ship_gross)
        if ship_gross > 0 and ship_refunded > 0:
            tax += (ship_tax * ship_refunded / ship_gross).quantize(
                PAISA, rounding=ROUND_HALF_UP)

    # Never reverse more than remains un-reversed on this order.
    charged = order_tax + ship_tax
    already = Decimal(str(getattr(order, 'refunded_tax', 0) or 0))
    return max(min(tax, charged - already), Decimal('0.00'))


def allocate_combo_components(combo, line_amount, line_quantity=1):
    """Split a combo line's charged amount across its components.

    A combo is one priced line to the customer but several taxable goods to the
    GST return: a festive box mixing 0% papad with 5% masala is a mixed supply,
    and a bill that reports it at one blended rate is unauditable. So the amount
    actually charged is pushed back onto the components and each one's GST is
    extracted at its OWN product's rate.

    The split is linear in the components' MRP share::

        w_i = variant_i.price * qty_i        # per single combo
        a_i = line_amount * w_i / sum(w)
        tax_i = extract_tax(a_i, product_i.tax_rate)

    `line_amount` is the FINAL figure — combo discount and any coupon already
    taken off. That is deliberate and not a shortcut: both discounts are linear
    in the same weights, so allocating once at the end is arithmetically
    identical to allocating, discounting, and re-allocating, and it is the only
    ordering where the parts are guaranteed to sum to what was charged.

    ROUNDING. Per-component rounding leaves a paisa or two unaccounted for, so
    the residual (`line_amount - sum(a_i)`) is handed to the largest component.
    Without this the invoice's GST summary would not reconcile against the grand
    total — the exact failure mode this module exists to prevent.

    Returns a list of dicts (empty if the combo has no components, or if
    `line_amount` is zero — a fully coupon-waived line has nothing to tax)::

        {'variant', 'quantity', 'tax_rate', 'allocated', 'tax'}

    `quantity` is the TOTAL units of that size the line consumes — the
    per-combo quantity times `line_quantity` — so it matches what checkout
    draws from stock. It does not affect the split, which depends only on the
    components' relative weights.
    """
    line_amount = Decimal(str(line_amount or 0))

    # Reuse a prefetched `productcomboitem_set` when the caller supplied one
    # (the cart and order serializers do); adding select_related() to a
    # prefetched manager would discard the cache and re-query per combo.
    if 'productcomboitem_set' in getattr(combo, '_prefetched_objects_cache', {}):
        items = list(combo.productcomboitem_set.all())
    else:
        items = list(
            combo.productcomboitem_set.select_related('variant', 'variant__product').all()
        )
    if not items or line_amount <= 0:
        return []

    weights = [Decimal(str(ci.variant.price or 0)) * ci.quantity for ci in items]
    total_weight = sum(weights, Decimal('0'))
    if total_weight <= 0:
        # Every component priced at zero: nothing to apportion against. Fall
        # back to an even split so the money is still fully accounted for.
        weights = [Decimal('1')] * len(items)
        total_weight = Decimal(str(len(items)))

    allocations = [
        (line_amount * w / total_weight).quantize(PAISA, rounding=ROUND_HALF_UP)
        for w in weights
    ]

    # Hand the rounding residual to the largest component, so the parts sum to
    # `line_amount` exactly in both directions.
    residual = line_amount.quantize(PAISA) - sum(allocations, Decimal('0'))
    if residual:
        biggest = max(range(len(weights)), key=lambda i: weights[i])
        allocations[biggest] += residual

    rows = []
    for ci, allocated in zip(items, allocations):
        rate = tax_rate_for(ci.variant.product)
        rows.append({
            'variant': ci.variant,
            'quantity': ci.quantity * line_quantity,
            'tax_rate': rate,
            # Carried alongside the rate so a combo line can still report an HSN
            # summary: the bundle itself has no single code, but each component
            # does, and Table 12 is built from those.
            'hsn_code': hsn_code_for(ci.variant.product),
            'allocated': allocated,
            'tax': extract_tax(allocated, rate),
        })
    return rows


def blended_rate(gross, tax):
    """The single GST rate that would produce `tax` out of `gross`.

    A combo line mixes slabs, so no one rate describes it. This is stored on
    `OrderItem.tax_rate` for DISPLAY only ("effective 3.7%"), and so a legacy
    reader that knows nothing about component rows still sees a plausible
    number. The audited per-slab breakup always comes from the components.
    """
    gross = Decimal(str(gross or 0))
    tax = Decimal(str(tax or 0))
    net = gross - tax
    if net <= 0:
        return Decimal('0.00')
    return (tax * Decimal('100') / net).quantize(PAISA, rounding=ROUND_HALF_UP)


def combo_line_tax(combo, line_amount):
    """Total GST contained in a combo line, summed over its components.

    The one-number view of `allocate_combo_components`, for the cart and coupon
    previews — which quote a tax figure but have no order rows to attach a split
    to. Both surfaces MUST route through here rather than applying a single rate
    to the line, or the cart would quote one GST and the placed order charge
    another.

    A combo with no components (mis-configured) falls back to `extract_tax` at
    the default rate, so a broken bundle still bills something sane rather than
    tax-free.
    """
    rows = allocate_combo_components(combo, line_amount)
    if not rows:
        return extract_tax(line_amount, DEFAULT_TAX_RATE)
    return sum((row['tax'] for row in rows), Decimal('0.00'))


def tax_rate_for(item):
    """GST rate (%) declared on a Product or ProductCombo.

    Falls back to DEFAULT_TAX_RATE when the attribute is missing entirely, but
    honours an explicit 0 (tax-exempt goods) rather than treating it as unset.
    """
    if item is None:
        return Decimal('0')
    return Decimal(str(getattr(item, 'tax_rate', DEFAULT_TAX_RATE) or 0))


def hsn_code_for(item):
    """HSN code declared on a Product, or '' when it has none.

    A ProductCombo has no `hsn_code` column and never will: a bundle is a mixed
    supply and its components can sit in different headings, so the only honest
    answer at bundle level is "no single code" — the per-component rows carry
    the real ones. Returns '' for combos and for unclassified products alike;
    the HSN summary reports those under an explicit "unclassified" bucket rather
    than guessing.
    """
    if item is None:
        return ''
    return (getattr(item, 'hsn_code', '') or '').strip()
