"""Payment notifications — admin exception alerts + customer payment emails.

All best-effort and dispatched on a background thread, mirroring
`orders/emails.py`: a mail hiccup must never break a payment transition.
"""
import logging
import threading

from django.conf import settings
from django.core.mail import send_mail

logger = logging.getLogger(__name__)


def _from_email():
    return getattr(settings, 'DEFAULT_FROM_EMAIL', None) or getattr(settings, 'EMAIL_HOST_USER', '')


def _frontend_url():
    return getattr(settings, 'FRONTEND_URL', 'https://nidhimasala.com').rstrip('/')


def _alert_recipient():
    return getattr(settings, 'PAYMENT_ALERT_EMAIL', '') or _from_email()


def _order_number(order):
    return f"ORD-{order.id:06d}"


def _send_async(subject, message, recipient):
    if not recipient:
        return
    from_email = _from_email()

    def _worker():
        try:
            send_mail(subject=subject, message=message, from_email=from_email,
                      recipient_list=[recipient], fail_silently=False)
        except Exception as e:  # noqa: BLE001
            logger.error("Failed to send payment email to %s: %s", recipient, e)

    threading.Thread(target=_worker, daemon=True).start()


def send_admin_exception_alert(event_id):
    """Email the admin about a payment exception the moment it is recorded."""
    from .models import PaymentEvent
    event = PaymentEvent.objects.select_related('payment', 'order').filter(pk=event_id).first()
    if event is None:
        return
    recipient = _alert_recipient()
    if not recipient:
        logger.warning("Payment exception %s but no PAYMENT_ALERT_EMAIL configured", event_id)
        return

    order = event.order or (event.payment.order if event.payment else None)
    order_line = f"Order {_order_number(order)} (id {order.id})" if order else "No order"
    pay = event.payment
    pay_line = f"Payment {pay.payment_id} — status {pay.status}, ₹{pay.amount}" if pay else "No payment row"

    message = (
        f"A payment exception needs attention.\n\n"
        f"Type:    {event.event_type}\n"
        f"Source:  {event.source}\n"
        f"{order_line}\n"
        f"{pay_line}\n\n"
        f"Detail:\n{event.message}\n\n"
        f"Open the admin → Payments → Payment events (filter: exceptions) to act."
    )
    _send_async(subject=f"[NGU payments] {event.event_type} — needs attention",
                message=message, recipient=recipient)


# Customer-facing copy per terminal transition.
_CUSTOMER_COPY = {
    'paid': (
        "Payment received — {number} | Nidhi Masala",
        "We've received your payment for order {number}. Your order is confirmed "
        "and we're getting it ready.\n\nPayment reference: {ref}\n"
        "View your order: {orders_url}\n\n— Team Nidhi Masala",
    ),
    'failed': (
        "Payment failed — {number} | Nidhi Masala",
        "Your payment for order {number} didn't go through. No money has been "
        "taken. You can retry the payment from your orders page:\n\n{orders_url}\n\n"
        "If the problem persists, just reply to this email and we'll help.\n\n"
        "— Team Nidhi Masala",
    ),
    'refunded': (
        "Refund processed — {number} | Nidhi Masala",
        "We've processed a refund for order {number}. It should reflect in your "
        "account within a few business days.\n\n— Team Nidhi Masala",
    ),
}


def send_payment_customer_email(kind, order_id):
    """Notify the customer of a terminal payment transition (paid/failed/refunded)."""
    from orders.models import Order
    order = Order.objects.select_related('user').filter(pk=order_id).first()
    if order is None:
        return
    recipient = getattr(order.user, 'email', None)
    if not recipient:
        return
    subject_t, body_t = _CUSTOMER_COPY.get(kind, (None, None))
    if subject_t is None:
        return
    number = _order_number(order)
    ref = getattr(getattr(order, 'payment', None), 'razorpay_payment_id', None) or number
    orders_url = f"{_frontend_url()}/my-orders"
    _send_async(
        subject=subject_t.format(number=number),
        message=body_t.format(number=number, ref=ref, orders_url=orders_url),
        recipient=recipient,
    )
