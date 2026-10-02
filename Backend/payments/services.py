"""Payment state machine — the single, idempotent core.

Both the client callback (`/verify/`) and the webhook (`/webhook/`) — and the L3
reconciliation command — funnel every "money captured" / "payment failed"
transition through the functions here, so the guarantees live in one place:

* **Canonical lock order (project-wide invariant): Order row FIRST, then Payment
  row.** Every path that mutates payment/order state takes `select_for_update()`
  in this order. It is what makes "cancel racing capture" safe and prevents
  deadlocks (PAYMENT_INTEGRATION_PLAN.md §7.2).
* **Idempotent.** A second caller (L1/L2 race, webhook redelivery, double-click)
  sees a terminal status and no-ops. The `ProcessedWebhookEvent` unique
  constraint — not the advisory `exists()` — is the authoritative guard.
* **Out-of-order safe.** `payment.failed` arriving after `payment.captured`
  never un-pays a paid order.
* **Never resurrects a cancelled order.** Capture-after-cancel records the money
  truthfully on the Payment, raises an admin exception (→ refund), and leaves the
  order cancelled.
* **Side-effects via `transaction.on_commit`** so a rolled-back txn never emails a
  customer about a payment that didn't persist.
"""
import logging
from decimal import Decimal

from django.db import transaction, IntegrityError

from orders.models import Order
from .models import Payment, PaymentEvent, ProcessedWebhookEvent

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Audit trail + notifications
# ---------------------------------------------------------------------------

def log_payment_event(payment=None, order=None, *, event_type, source='system',
                      from_status=None, to_status=None, message='',
                      raw_payload=None, is_exception=False, alert_admin=False):
    """Append one immutable row to the audit trail. Call inside the same
    transaction as the state change so history can never disagree with state.

    When `alert_admin` (or `is_exception`) is set, an alert email is dispatched
    once the surrounding transaction commits — never a bare log line.
    """
    if order is None and payment is not None:
        order = payment.order
    event = PaymentEvent.objects.create(
        payment=payment,
        order=order,
        event_type=event_type,
        source=source,
        from_status=from_status,
        to_status=to_status,
        message=message or '',
        raw_payload=raw_payload,
        is_exception=is_exception or alert_admin,
    )
    if is_exception or alert_admin:
        # Defer until commit so we never alert about a rolled-back state.
        transaction.on_commit(lambda: _notify_admin_exception(event.id))
    return event


def _notify_admin_exception(event_id):
    try:
        from .emails import send_admin_exception_alert
        send_admin_exception_alert(event_id)
    except Exception:  # noqa: BLE001 — alerting must never raise
        logger.exception("Failed to dispatch admin exception alert for event %s", event_id)


def _on_commit_customer_email(kind, order_id):
    def _fire():
        try:
            from .emails import send_payment_customer_email
            send_payment_customer_email(kind, order_id)
        except Exception:  # noqa: BLE001
            logger.exception("Failed to send %s email for order %s", kind, order_id)
    transaction.on_commit(_fire)


def _on_commit_order_confirmation(order_id):
    def _fire():
        try:
            from orders.emails import send_order_confirmation, send_new_order_admin_alert
            order = Order.objects.filter(pk=order_id).first()
            if order:
                send_order_confirmation(order)
                send_new_order_admin_alert(order)
        except Exception:  # noqa: BLE001
            logger.exception("Failed to send order confirmation for order %s", order_id)
    transaction.on_commit(_fire)


# ---------------------------------------------------------------------------
# State transitions
# ---------------------------------------------------------------------------

class PaymentNotFound(Exception):
    pass


def _lock_order_and_payment(razorpay_order_id=None, payment_pk=None,
                            razorpay_payment_id=None):
    """Acquire the canonical Order→Payment locks and return (order, payment).

    Look the Payment up unlocked first (to learn the order id), then lock the
    Order, then lock the Payment. Raises PaymentNotFound if absent.

    Lookup precedence: local pk → Razorpay order id (our `payment_id` column) →
    captured Razorpay payment id (the `razorpay_payment_id` column). The last is
    the fallback for refund webhooks, whose entity does not reliably carry the
    order id but always carries the payment id.
    """
    ref = None
    if payment_pk is not None:
        ref = Payment.objects.filter(pk=payment_pk).first()
    elif razorpay_order_id is not None:
        ref = Payment.objects.filter(payment_id=razorpay_order_id).first()
    elif razorpay_payment_id is not None:
        ref = Payment.objects.filter(razorpay_payment_id=razorpay_payment_id).first()
    if ref is None:
        raise PaymentNotFound()
    # Canonical order: Order first…
    order = Order.objects.select_for_update().get(pk=ref.order_id)
    # …then Payment.
    payment = Payment.objects.select_for_update().get(pk=ref.pk)
    return order, payment


def _extract_instrument_details(entity):
    """Whitelist the display-safe instrument fields from a Razorpay payment
    entity (webhook `payment.entity` or a reconcile-fetched payment dict).

    Deliberately excludes contact/email (PII). Fee/tax are excluded too, but for
    a different reason — they are not display detail, they are accounting, and
    live in their own `gateway_fee`/`gateway_tax` columns via
    `_extract_gateway_cost`. Returns {} when there's nothing usable so callers
    can cheaply skip a write.
    """
    if not entity:
        return {}
    method = entity.get('method')
    details = {'method': method}
    if method == 'upi':
        details['vpa'] = entity.get('vpa')
    elif method == 'card':
        card = entity.get('card') or {}
        details['card_last4'] = card.get('last4')
        details['card_network'] = card.get('network')
        details['card_type'] = card.get('type')  # credit / debit
    elif method == 'netbanking':
        details['bank'] = entity.get('bank')
    elif method == 'wallet':
        details['wallet'] = entity.get('wallet')
    return {k: v for k, v in details.items() if v is not None}


def _extract_gateway_cost(entity):
    """Razorpay's cut of a captured payment, as (fee, tax) in RUPEES.

    Both fields arrive in **paise** on the payment entity and are ``None`` until
    the payment is actually captured, so this returns ``(None, None)`` whenever
    there is nothing trustworthy to record — the caller must then leave the
    stored values alone rather than zeroing them, or a later event with no fee
    would erase a fee an earlier one supplied.

    `tax` is the GST *inside* `fee`, not on top of it. It is input tax credit:
    GST we paid on a service, deductible from the output tax collected on sales.
    """
    if not entity:
        return None, None
    fee, tax = entity.get('fee'), entity.get('tax')
    if fee is None and tax is None:
        return None, None
    to_rupees = lambda paise: (          # noqa: E731 — trivial, local, used twice
        Decimal(str(paise)) / Decimal('100') if paise is not None else None)
    return to_rupees(fee), to_rupees(tax)


def _apply_gateway_cost(payment, entity, fields):
    """Copy the gateway's fee/tax onto `payment`, appending changed field names.

    Split out because every capture path — webhook, reconcile, and the terminal
    early-return that only backfills detail — has to do this identically. A
    payment captured via the browser /verify/ callback carries no entity, so its
    fee arrives later from the webhook or L3; that backfill is the whole point.
    """
    fee, tax = _extract_gateway_cost(entity)
    if fee is not None and payment.gateway_fee != fee:
        payment.gateway_fee = fee
        fields.append('gateway_fee')
    if tax is not None and payment.gateway_tax != tax:
        payment.gateway_tax = tax
        fields.append('gateway_tax')
    return fields


def mark_payment_captured(razorpay_order_id, razorpay_payment_id,
                          event_id=None, source='webhook', amount=None,
                          raw_payload=None, payment_entity=None):
    """Idempotently record a captured payment and confirm its order.

    Returns the Payment. Safe to call any number of times from verify, webhook
    (incl. redeliveries), and the reconciliation job.

    `payment_entity` is the raw Razorpay payment dict when the caller has it (the
    webhook and reconcile do; the client `/verify/` callback does not). Its
    instrument fields (method / vpa / card / bank / wallet) are merged into
    `transaction_details` on EVERY path — including the terminal-status early
    return — so a webhook that lands after `/verify/` already completed the
    payment still backfills the "how they paid" detail.
    """
    with transaction.atomic():
        order, payment = _lock_order_and_payment(razorpay_order_id=razorpay_order_id)
        details_update = _extract_instrument_details(payment_entity)

        # Idempotency guard — a terminal payment is a no-op for state, but we
        # still merge any newly-arrived instrument details (see docstring).
        if payment.status in ('completed', 'refunded'):
            terminal_fields = []
            if details_update and any(
                (payment.transaction_details or {}).get(k) != v
                for k, v in details_update.items()
            ):
                payment.transaction_details = {**(payment.transaction_details or {}),
                                               **details_update}
                terminal_fields.append('transaction_details')
            # The fee is the main reason this path exists in practice: /verify/
            # completes the payment with no entity, so the webhook arriving
            # afterwards is usually the FIRST time a fee is available at all.
            _apply_gateway_cost(payment, payment_entity, terminal_fields)
            if terminal_fields:
                payment.save(update_fields=terminal_fields + ['updated_at'])
            _record_processed_event(event_id, 'payment.captured')
            log_payment_event(payment, event_type='duplicate_ignored', source=source,
                              message=f"Capture ignored; status already {payment.status}.",
                              raw_payload=raw_payload)
            return payment

        # Event-id idempotency (advisory — the unique insert below is authoritative).
        if event_id and ProcessedWebhookEvent.objects.filter(event_id=event_id).exists():
            log_payment_event(payment, event_type='duplicate_ignored', source=source,
                              message=f"Duplicate event {event_id}.", raw_payload=raw_payload)
            return payment

        # Amount integrity — never fulfil on a mismatch (§7.5).
        if amount is not None:
            try:
                expected_paise = int(round(float(payment.amount) * 100))
                if int(amount) != expected_paise:
                    log_payment_event(
                        payment, event_type='amount_mismatch', source=source,
                        message=(f"Webhook amount {amount} paise != expected "
                                 f"{expected_paise} paise for order {order.id}."),
                        raw_payload=raw_payload, is_exception=True)
                    _record_processed_event(event_id, 'payment.captured')
                    return payment
            except (TypeError, ValueError):
                pass

        # Capture-after-cancel: record the money truthfully, never resurrect the
        # order — route to refund via an admin exception (§7.2/§7.8).
        if order.status == 'cancelled':
            payment.status = 'completed'
            payment.razorpay_payment_id = razorpay_payment_id
            payment.transaction_details = {**(payment.transaction_details or {}),
                                           'razorpay_payment_id': razorpay_payment_id,
                                           **details_update}
            _fields = _apply_gateway_cost(payment, payment_entity, [
                'status', 'razorpay_payment_id', 'transaction_details'])
            payment.save(update_fields=_fields + ['updated_at'])
            log_payment_event(
                payment, event_type='captured_after_cancel', source=source,
                from_status='pending', to_status='completed',
                message=("Payment captured for an already-cancelled order — needs "
                         "a refund. Order was NOT reopened."),
                raw_payload=raw_payload, is_exception=True)
            _record_processed_event(event_id, 'payment.captured')
            return payment

        # Happy path.
        from_status = payment.status
        payment.status = 'completed'
        payment.razorpay_payment_id = razorpay_payment_id
        payment.transaction_details = {**(payment.transaction_details or {}),
                                       'razorpay_payment_id': razorpay_payment_id,
                                       **details_update}
        _fields = _apply_gateway_cost(payment, payment_entity, [
            'status', 'razorpay_payment_id', 'transaction_details'])
        payment.save(update_fields=_fields + ['updated_at'])

        order.payment_status = 'paid'
        order.status = 'confirmed'
        order.save(update_fields=['payment_status', 'status', 'updated_at'])

        # The supply is now committed, so raise the tax invoice. Done HERE and
        # not at PDF download: the number comes from a continuous series and the
        # contents are frozen at this instant, so it must be allocated at a
        # defined business event rather than whenever someone clicks a button.
        # Never raises — a failure is logged and left for `backfill_invoices`,
        # because nothing about document generation may roll back a capture.
        from orders.invoicing import maybe_issue_invoice
        maybe_issue_invoice(order)

        # Cart is emptied HERE, at capture — an ONLINE order keeps the customer's
        # cart while payment is pending (orders.views.create) so an abandoned
        # payment never strands them with an empty cart. Now that the payment is
        # captured the order is complete, so clear the cart. Idempotent: the
        # terminal-status guard above makes repeated captures (verify + webhook +
        # reconcile) a no-op, so this runs at most once per order.
        from cart.models import CartItem
        CartItem.objects.filter(cart__user=order.user).delete()

        log_payment_event(payment, event_type='captured', source=source,
                          from_status=from_status, to_status='completed',
                          message=f"Payment {razorpay_payment_id} captured.",
                          raw_payload=raw_payload)
        _record_processed_event(event_id, 'payment.captured')

        # Side-effects exactly once, after commit.
        _on_commit_order_confirmation(order.id)
        _on_commit_customer_email('paid', order.id)
        return payment


def mark_payment_failed(razorpay_order_id, event_id=None, source='webhook',
                        error_code=None, error_description=None, raw_payload=None,
                        payment_entity=None):
    """Record a failed payment. Out-of-order safe: only applies when the payment
    is still `pending` — never downgrades a completed/refunded payment.

    Instrument details (which method the customer tried) are merged in too, so
    the admin can see e.g. "tried UPI and it failed"."""
    with transaction.atomic():
        order, payment = _lock_order_and_payment(razorpay_order_id=razorpay_order_id)

        if event_id and ProcessedWebhookEvent.objects.filter(event_id=event_id).exists():
            return payment

        if payment.status != 'pending':
            # Out-of-order: failed arrived after captured/refunded — ignore.
            log_payment_event(payment, event_type='out_of_order_ignored', source=source,
                              message=(f"payment.failed ignored; status is "
                                       f"{payment.status}."), raw_payload=raw_payload)
            _record_processed_event(event_id, 'payment.failed')
            return payment

        details_update = _extract_instrument_details(payment_entity)
        payment.status = 'failed'
        payment.failure_code = (error_code or '')[:64] or None
        payment.failure_reason = (error_description or '')[:255] or None
        if details_update:
            payment.transaction_details = {**(payment.transaction_details or {}),
                                           **details_update}
        payment.save(update_fields=['status', 'failure_code', 'failure_reason',
                                    'transaction_details', 'updated_at'])

        order.payment_status = 'failed'
        order.save(update_fields=['payment_status', 'updated_at'])

        log_payment_event(payment, event_type='failed', source=source,
                          from_status='pending', to_status='failed',
                          message=error_description or 'Payment failed.',
                          raw_payload=raw_payload)
        _record_processed_event(event_id, 'payment.failed')
        _on_commit_customer_email('failed', order.id)
        return payment


def mark_payment_refunded(razorpay_order_id=None, event_id=None, source='webhook',
                          raw_payload=None, razorpay_payment_id=None,
                          refund_amount_paise=None, refund_reference=None):
    """Record a refund: marks the payment/order refunded AND appends a ledger row
    that reverses the refund's share of GST. Stock restoration per business rule
    is left to the admin/cancel flow.

    Resolves the local Payment by Razorpay order id when present, else by the
    captured payment id — refund entities do not always carry the order id.

    `refund_amount_paise` / `refund_reference` come from the gateway's refund
    entity. When the amount is absent (older payloads), the refund is treated as
    FULL, because a refund we can't size must not silently reverse ₹0 of tax —
    under-reversing means over-paying GST.

    We never ISSUE a partial refund (orders/refunds.py), but Razorpay's dashboard
    can, so one may still arrive. It is recorded truthfully — the money really
    moved and its GST really is reversed — while the payment, the order status
    and the customer's "refund processed" email all wait for the whole amount to
    come back. Anything else would tell the customer they have been refunded
    while we still hold most of their money.
    """
    from decimal import Decimal
    from orders.refunds import record_refund, refundable_balance

    with transaction.atomic():
        order, payment = _lock_order_and_payment(
            razorpay_order_id=razorpay_order_id,
            razorpay_payment_id=razorpay_payment_id)

        if event_id and ProcessedWebhookEvent.objects.filter(event_id=event_id).exists():
            return payment
        # NOTE: a fully-refunded payment short-circuits, but a PARTIALLY refunded
        # one must fall through so a second partial refund is still recorded.
        if payment.status == 'refunded':
            _record_processed_event(event_id, 'refund.processed')
            return payment

        if refund_amount_paise is not None:
            amount = (Decimal(str(refund_amount_paise)) / 100).quantize(Decimal('0.01'))
        else:
            amount = refundable_balance(order)

        # The ledger owns the GST reversal, the running totals, and the order
        # status. It is idempotent on `reference`, so a redelivered webhook that
        # slips past the event-id check still cannot double-reverse the tax.
        refund = record_refund(order, amount, source='gateway',
                               reference=refund_reference,
                               note='Refund processed at Razorpay.')
        order.refresh_from_db()

        fully_refunded = (Decimal(str(order.refunded_amount or 0))
                          >= Decimal(str(order.total_amount or 0)) > 0)

        from_status = payment.status
        if fully_refunded:
            payment.status = 'refunded'
            payment.save(update_fields=['status', 'updated_at'])

        log_payment_event(
            payment, event_type='refunded', source=source,
            from_status=from_status,
            to_status='refunded' if fully_refunded else from_status,
            message=(f"Refund of Rs. {refund.amount} processed at Razorpay "
                     f"(GST reversed Rs. {refund.tax_amount})."
                     if refund else 'Refund processed at Razorpay.'),
            raw_payload=raw_payload)
        _record_processed_event(event_id, 'refund.processed')
        # Only once the whole order is back — "your refund has been processed"
        # is a promise about the entire order, not about a slice of it.
        if fully_refunded:
            _on_commit_customer_email('refunded', order.id)
        return payment


def _record_processed_event(event_id, event_type):
    """Insert the idempotency-ledger row. The unique constraint is the real guard:
    two workers can both pass the advisory exists() check before either commits,
    so a concurrent duplicate must resolve to a clean no-op, never a 500 (§7.2)."""
    if not event_id:
        return
    try:
        with transaction.atomic():
            ProcessedWebhookEvent.objects.create(event_id=event_id, event_type=event_type or '')
    except IntegrityError:
        # Someone else won the race — that's fine.
        pass
