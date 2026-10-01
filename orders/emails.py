"""
Order notification emails.

Three order emails live here (two customer-facing, one for the store owner —
`send_new_order_admin_alert`):

1. `send_order_confirmation(order)` — fired the moment an order is successfully
   placed. Gives the customer their order number and a summary so they can find
   the order later (the UI tells them to look for it here).

2. `send_order_status_email(order, ...)` — the customer's shipment/cancellation
   notice. By product decision it is NOT fired on routine status progression
   (confirmed → processing → delivered …); the order-edit path calls it ONLY
   when a tracking number is newly added (parcel shipped). The `cancel` action
   still calls it to tell the customer their order was cancelled. The function
   itself remains generic (it will render a status message if asked), but the
   callers gate it to just these two events.

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


def send_new_order_admin_alert(order):
    """Tell the store owner a new order just arrived (sent to ADMIN_ALERT_EMAIL).

    Written for a non-technical reader: what was ordered, who by, how they're
    paying, and where to act on it — nothing else.
    """
    recipient = getattr(settings, 'ADMIN_ALERT_EMAIL', '') or None
    if not recipient:
        return

    number = _order_number(order)
    summary = _items_summary(order)
    user = getattr(order, 'user', None)
    customer = getattr(user, 'name', '') or getattr(user, 'email', '') or 'Customer'
    phone = (getattr(order, 'phone_number', '') or '').strip()
    payment = 'Cash on Delivery' if order.payment_method == 'COD' else 'Paid online'

    message = (
        f"You have a new order!\n\n"
        f"Order: {number}\n"
        f"Customer: {customer}" + (f" ({phone})" if phone else "") + "\n"
        f"Payment: {payment}\n"
        f"Total: Rs. {order.total_amount}\n\n"
        f"Items:\n{summary}\n\n"
        f"Deliver to:\n{order.shipping_address}\n\n"
        f"Open the admin panel to confirm this order.\n"
    )

    _send_async(
        subject=f"New order {number} — Rs. {order.total_amount}",
        message=message,
        recipient=recipient,
    )


def send_low_stock_alert(items):
    """Tell the store owner a checkout just pushed products to/below their
    low-stock threshold (sent to ADMIN_ALERT_EMAIL).

    ``items`` is a list of dicts: {'name', 'stock', 'threshold'}. Only products
    that *crossed* the threshold on this order are passed in (see
    orders/views.py) so the owner isn't re-alerted on every subsequent order for
    an already-low product. Best-effort background send, like the other alerts.
    """
    if not items:
        return
    recipient = getattr(settings, 'ADMIN_ALERT_EMAIL', '') or None
    if not recipient:
        return

    out = [it for it in items if it['stock'] <= 0]
    low = [it for it in items if it['stock'] > 0]

    lines = ["A recent order has left some products low on stock.", ""]
    if out:
        lines.append("Out of stock now — customers can no longer buy these:")
        lines += [f"  - {it['name']}" for it in out]
        lines.append("")
    if low:
        lines.append("Running low (at or below your alert level):")
        lines += [
            f"  - {it['name']} — {it['stock']} left (alert at {it['threshold']})"
            for it in low
        ]
        lines.append("")
    lines += ["Restock these in the admin panel when you can.", "", "— Your Nidhi Masala store"]

    # Subject NAMES the product(s) so the owner sees what's low without opening
    # the email — out-of-stock leads (most urgent). One product → its name; more
    # than one → the first name + a count of the rest.
    lead = (out or low)[0]
    total = len(items)
    if total == 1:
        if out:
            subject = f"Stock alert — {lead['name']} is out of stock"
        else:
            subject = f"Stock alert — {lead['name']} running low ({lead['stock']} left)"
    else:
        rest = total - 1
        tail = f" and {rest} other product{'s' if rest != 1 else ''}"
        if out:
            subject = f"Stock alert — {lead['name']} is out of stock{tail}"
        else:
            subject = f"Stock alert — {lead['name']} running low{tail}"

    _send_async(subject=subject, message="\n".join(lines), recipient=recipient)


def _admin_recipient():
    return getattr(settings, 'ADMIN_ALERT_EMAIL', '') or None


def send_coupon_usage_alert(coupon):
    """Warn the owner a coupon is nearly exhausted (usage approaching max_usage).

    Fired at redemption time; deduped so it emails once as the coupon crosses the
    alert level, not on every remaining redemption."""
    recipient = _admin_recipient()
    if not recipient:
        return
    remaining = max(0, (coupon.max_usage or 0) - coupon.usage_count)
    exhausted = remaining == 0
    lines = [
        (f"Your coupon \"{coupon.code}\" has been fully used up "
         f"({coupon.usage_count}/{coupon.max_usage}) and can no longer be applied."
         if exhausted else
         f"Your coupon \"{coupon.code}\" is almost used up: "
         f"{coupon.usage_count} of {coupon.max_usage} uses, {remaining} left."),
        "",
        ("Create a new coupon or raise its usage limit to keep the offer running."
         if exhausted else
         "Raise its usage limit in the admin panel if you want the offer to continue."),
        "",
        "— Your Nidhi Masala store",
    ]
    subject = (f"Coupon {coupon.code} is used up" if exhausted
               else f"Coupon {coupon.code} almost used up — {remaining} left")
    _send_async(subject=subject, message="\n".join(lines), recipient=recipient)


def send_payment_spike_alert(cancelled, window_desc):
    """Warn the owner that an unusual number of ONLINE checkouts were auto-cancelled
    in one reconcile run — usually a payment/checkout problem, not chance."""
    recipient = _admin_recipient()
    if not recipient:
        return
    lines = [
        f"{cancelled} online orders were just auto-cancelled because their payment "
        f"was never completed ({window_desc}).",
        "",
        "A burst like this often means customers are hitting a problem at the "
        "payment step (gateway down, card failures, or a checkout bug). It's worth "
        "placing a small test order to make sure online payment is working.",
        "",
        "— Your Nidhi Masala store",
    ]
    _send_async(
        subject=f"Heads up — {cancelled} online payments just failed to complete",
        message="\n".join(lines),
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
    courier = (getattr(order, 'courier_name', '') or '').strip()
    tracking_url = (getattr(order, 'tracking_url', '') or '').strip()
    if tracking_added and (tracking or tracking_url):
        parts.append("")
        if courier:
            parts.append(f"Shipped with: {courier}")
        if tracking:
            parts.append(f"Your tracking ID is: {tracking}")
        if tracking_url:
            parts.append(f"Track your parcel here: {tracking_url}")
        else:
            parts.append(
                "You can track your parcel on the courier partner's website "
                "using this tracking ID.")

    parts += ["", f"View your order: {_frontend_url()}/my-orders", "", "— Team Nidhi Masala"]

    # Subject reflects the most important thing that happened.
    if tracking_added and (tracking or tracking_url):
        subject = f"Your order {number} has shipped | Nidhi Masala"
    else:
        subject = f"Order {number} update: {order.status} | Nidhi Masala"

    _send_async(subject=subject, message="\n".join(parts), recipient=recipient)
