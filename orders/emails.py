"""
Order notification emails.

Two customer-facing emails live here:

1. `send_order_confirmation(order)` — fired the moment an order is successfully
   placed. Gives the customer their order number and a summary so they can find
   the order later (the UI tells them to look for it here).

2. `send_order_status_email(order, ...)` — fired when an admin advances the
   order (status change) and/or enters a shipment tracking number. This is how
   the customer learns their order is being processed / on its way / delivered.

Both are best-effort: sent on a background thread and never allowed to break the
request that triggered them (an SMTP hiccup must not fail an order placement or a
status update). This mirrors the OTP-email pattern in `users/views.py`.
"""

import logging
import threading
import time

from django.conf import settings
from django.core.mail import send_mail
from django.db import connections

logger = logging.getLogger(__name__)

# Best-effort retry so a single transient SMTP hiccup doesn't silently lose a
# customer notification. A durable outbox/queue would be the "real" fix; this is
# the lightweight guard that covers the common flaky-network case.
_MAX_EMAIL_ATTEMPTS = 3
_EMAIL_RETRY_BACKOFF_SECONDS = 2


def _from_email():
    return getattr(settings, 'DEFAULT_FROM_EMAIL', None) or getattr(settings, 'EMAIL_HOST_USER', '')


def _frontend_url():
    return getattr(settings, 'FRONTEND_URL', 'https://nidhimasala.com').rstrip('/')


def _order_number(order):
    return f"ORD-{order.id:06d}"


def _recipient(order):
    """The customer's email, or None if the order has no usable address."""
    user = getattr(order, 'user', None)
    email = getattr(user, 'email', None)
    return email or None


def _send_async(subject, message, recipient):
    """Dispatch a plain-text email on a background thread, swallowing failures."""
    if not recipient:
        return
    from_email = _from_email()

    def _worker():
        try:
            for attempt in range(1, _MAX_EMAIL_ATTEMPTS + 1):
                try:
                    send_mail(
                        subject=subject,
                        message=message,
                        from_email=from_email,
                        recipient_list=[recipient],
                        fail_silently=False,
                    )
                    return  # sent
                except Exception as e:  # noqa: BLE001 - notifications must never raise
                    if attempt >= _MAX_EMAIL_ATTEMPTS:
                        # Loud, final failure so ops can see it and resend manually
                        # (subject identifies the order).
                        logger.error(
                            "Giving up sending order email to %s after %d attempts "
                            "(subject=%r): %s", recipient, attempt, subject, e)
                    else:
                        logger.warning(
                            "Order email to %s failed (attempt %d/%d), retrying: %s",
                            recipient, attempt, _MAX_EMAIL_ATTEMPTS, e)
                        time.sleep(_EMAIL_RETRY_BACKOFF_SECONDS * attempt)
        finally:
            # This runs on a fresh thread; close any DB connection it implicitly
            # opened so we never leak a connection back into the pool.
            connections.close_all()

    threading.Thread(target=_worker, daemon=True).start()


def _items_summary(order):
    lines = []
    for item in order.items.all():
        name = item.product_name or 'Item'
        lines.append(f"  - {name} x {item.quantity}")
    return "\n".join(lines)


# Human-friendly, customer-facing status copy.
STATUS_MESSAGES = {
    'pending': "We've received your order and it's awaiting processing.",
    'confirmed': "Your order has been confirmed and is being prepared.",
    'processing': "Good news — your order is now being processed.",
    'shipped': "Your order has been shipped and is on its way!",
    'delivering': "Your order is out for delivery and will reach you soon.",
    'delivered': "Your order has been delivered. We hope you enjoy it!",
    'cancelled': "Your order has been cancelled. If this wasn't expected, please contact us.",
}


def send_order_confirmation(order):
    """Order-placed confirmation email (contains the order number)."""
    recipient = _recipient(order)
    if not recipient:
        return

    number = _order_number(order)
    summary = _items_summary(order)
    orders_url = f"{_frontend_url()}/my-orders"

    message = (
        f"Thank you for your order with Nidhi Masala!\n\n"
        f"Your order number is {number}. Keep it handy — you'll need it to track "
        f"or ask about your order.\n\n"
        f"Items:\n{summary}\n\n"
        f"Order total: Rs. {order.total_amount}\n\n"
        f"Shipping to:\n{order.shipping_address}\n\n"
        f"You can view your order any time here: {orders_url}\n\n"
        f"We'll email you again as your order is processed and shipped.\n\n"
        f"— Team Nidhi Masala"
    )

    _send_async(
        subject=f"Order Confirmed — {number} | Nidhi Masala",
        message=message,
        recipient=recipient,
    )


def send_order_status_email(order, status_changed=False, tracking_added=False):
    """Notify the customer that their order status advanced and/or a tracking
    number was added. No-op if neither actually changed."""
    if not (status_changed or tracking_added):
        return

    recipient = _recipient(order)
    if not recipient:
        return

    number = _order_number(order)
    status_line = STATUS_MESSAGES.get(order.status, f"Your order status is now: {order.status}.")

    parts = [f"Update on your Nidhi Masala order {number}:", "", status_line]

    tracking = (order.tracking_number or '').strip()
    if tracking_added and tracking:
        parts += [
            "",
            f"Your tracking ID is: {tracking}",
            "You can track your parcel on the courier partner's website using "
            "this tracking ID to see its live status and expected delivery.",
        ]

    parts += ["", f"View your order: {_frontend_url()}/my-orders", "", "— Team Nidhi Masala"]

    # Subject reflects the most important thing that happened.
    if tracking_added and tracking:
        subject = f"Your order {number} has shipped | Nidhi Masala"
    else:
        subject = f"Order {number} update: {order.status} | Nidhi Masala"

    _send_async(subject=subject, message="\n".join(parts), recipient=recipient)
