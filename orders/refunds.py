"""Recording refunds — the single write path for the OrderRefund ledger.

Every refund, whoever reports it (Razorpay webhook or an admin recording a COD
return), goes through `record_refund`. Keeping one entry point is what guarantees
the GST reversal, the denormalised order totals, and the order status can never
disagree with the ledger.

**Partial refunds are supported (changed 2026-08-01).** The admin dialog now has
an amount field, defaulting to the whole outstanding balance. Recording any
amount marks the order `refunded`, so the flag now means "a refund was recorded
against this order", NOT "the whole order came back". Two consequences:

* Every surface that shows `status='refunded'` must ALSO show `refunded_amount`,
  or it misleads — ₹200 back on a ₹500 order looks identical to a full refund
  otherwise. The admin table, the admin order dialog and the customer's order
  card all do this.
* The GST reversal is exact on a full refund and a blended-rate apportionment on
  a partial (see `pricing.refund_tax_for`). On a mixed 0%/5% order a partial is
  therefore an estimate — accepted deliberately as the price of the feature.

`refundable_balance` still tracks what is genuinely outstanding, so repeated
partials accumulate correctly and can never over-refund an order.

A refund can also ARRIVE from Razorpay's dashboard out of band, though as of
2026-08-01 the `refund.processed` webhook branch is disabled (manual-only mode),
so in practice every ledger row is written by an admin.
"""

import logging
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone

from spices_backend.timeranges import range_filter

from .models import Order, OrderRefund
from .pricing import refund_tax_for

logger = logging.getLogger(__name__)

PAISA = Decimal('0.01')


def refundable_balance(order):
    """What is still owed back on `order` — the amount a refund returns.

    The only amount the admin path ever refunds, since refunds are full (see the
    module docstring). Non-zero only while some of the order's money is still
    held.
    """
    return (Decimal(str(order.total_amount or 0))
            - Decimal(str(order.refunded_amount or 0)))


def record_refund(order, amount, *, source='gateway', reference=None, note='',
                  mark_refunded=False):
    """Append a refund to `order`'s ledger and reverse its share of GST.

    Returns the created `OrderRefund`, or the existing one when `reference` has
    already been recorded (idempotent — a redelivered webhook must not reverse
    the tax twice).

    Pass ``refundable_balance(order)`` as `amount` for a full refund; any smaller
    amount is a partial and is recorded just as truthfully.

    `mark_refunded=True` flips the order to `refunded` even when the amount is
    partial. It is set by the ADMIN path, where a human has deliberately entered
    an amount and expects the order to move: a partial refund they typed in is a
    settled outcome, not a half-finished one. Left False for gateway-sourced
    refunds, where a partial means "money moved out of band" and the order should
    stay put until someone looks at it.

    The caller is responsible for the surrounding lock if it needs one; this
    opens its own transaction so the ledger row and the order totals commit
    together or not at all.

    `amount` is clamped to what is still refundable, so a duplicate full refund
    or a gateway over-report can never push `refunded_amount` past the order
    total (which would show as negative GST owed).

    STOCK IS RESTORED HERE. Money going back means the goods came back, so the
    units return to inventory — otherwise every return silently ratchets stock
    down and the catalogue slowly under-reports what is on the shelf. It runs on
    the FIRST refund against the order and is idempotent thereafter
    (`restore_order_stock` stamps `Order.stock_restored_at`), so neither a
    refund-after-cancel nor a second instalment can credit the same units twice.
    A partial refund therefore returns the whole order's stock — the alternative
    is guessing which lines came back from an amount alone, and under-restocking
    a genuine return is the worse error.
    """
    amount = Decimal(str(amount or 0)).quantize(PAISA)
    if amount <= 0:
        return None

    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=order.pk)

        if reference:
            existing = OrderRefund.objects.filter(reference=reference).first()
            if existing:
                return existing

        refundable = refundable_balance(order)
        if refundable <= 0:
            logger.warning("Refund ignored for order %s: already fully refunded.", order.pk)
            return None
        if amount > refundable:
            logger.warning(
                "Refund %s exceeds refundable %s on order %s — clamping.",
                amount, refundable, order.pk)
            amount = refundable

        tax = refund_tax_for(order, amount)

        try:
            refund = OrderRefund.objects.create(
                order=order, amount=amount, tax_amount=tax,
                source=source, reference=reference or None, note=note,
            )
        except IntegrityError:
            # Lost a race on the unique `reference` — the other writer recorded
            # it, so this call is the no-op it was always meant to be.
            return OrderRefund.objects.filter(reference=reference).first()

        # Recompute the denormalised totals FROM the ledger rather than adding to
        # them, so they self-heal if a row is ever corrected or removed.
        totals = order.refunds.aggregate(amt=Sum('amount'), tax=Sum('tax_amount'))
        order.refunded_amount = totals['amt'] or Decimal('0.00')
        order.refunded_tax = totals['tax'] or Decimal('0.00')
        order.refunded_at = timezone.now()

        fields = ['refunded_amount', 'refunded_tax', 'refunded_at', 'updated_at']
        total = Decimal(str(order.total_amount or 0))
        fully_refunded = total > 0 and order.refunded_amount >= total

        # The flags say "a refund was recorded", not "all of it came back" — the
        # AMOUNT says how much, and every surface shows the two together. A
        # partial only moves them when a human entered it (`mark_refunded`); an
        # unattended gateway partial leaves the order alone so it stays visible
        # as something needing attention rather than quietly reading as settled.
        if fully_refunded or mark_refunded:
            order.status = 'refunded'
            fields.append('status')
            if order.payment_status != 'refunded':
                order.payment_status = 'refunded'
                fields.append('payment_status')

        if not fully_refunded:
            # Still money on the books either way — worth a line in the log so a
            # part-settled order can be found later without trawling the ledger.
            logger.warning(
                "PARTIAL refund on order %s: %s of %s returned (marked refunded: %s). "
                "Refund the balance to close it out.",
                order.pk, order.refunded_amount, total, bool(mark_refunded))

        order.save(update_fields=fields)

        # Goods back on the shelf. Imported lazily: orders.views imports THIS
        # module at module level, so a top-level import here would be circular.
        # Idempotent on `Order.stock_restored_at`, so an order that was already
        # cancelled (and restocked) before being refunded is left alone.
        from .views import restore_order_stock
        if restore_order_stock(order):
            logger.info("Stock restored for order %s on refund %s.", order.pk, refund.pk)

        return refund


def refunded_totals_between(date_from, date_to):
    """GST and money refunded in a date window, bucketed by REFUND date.

    Deliberately not by order date: a credit note reduces output tax in the
    period it is issued, so a refund in March must not retroactively change a
    January return that has already been filed.

    Refunds against soft-deleted orders are excluded, matching
    `rollup_analytics.countable_orders()`. The two must agree: if a recycled
    order's sale is not counted as revenue but its refund still reversed GST,
    the day would report tax coming back that never went out.
    """
    return OrderRefund.objects.filter(
        **range_filter('created_at', date_from, date_to),
        order__is_deleted=False,
    ).aggregate(amount=Sum('amount'), tax=Sum('tax_amount'))
