"""Daily store-owner digest email.

One short, plain-English email every morning to ADMIN_ALERT_EMAIL:
yesterday's sales, anything that needs attention today (orders waiting,
low/out-of-stock products, customers waiting for a chat reply).

Scheduled by `run_scheduler` (daily); safe to run manually any time:

    python manage.py send_daily_digest
"""
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.models import F, Q, Sum
from django.utils import timezone

from spices_backend.timeranges import range_filter


class Command(BaseCommand):
    help = "Email the store owner a plain-language daily digest."

    def handle(self, *args, **options):
        from orders.models import Order
        from products.availability import low_stock_sizes
        from assistant.models import AssistantConversation
        from orders.emails import _send_async  # shared best-effort sender

        recipient = getattr(settings, 'ADMIN_ALERT_EMAIL', '') or None
        if not recipient:
            self.stdout.write("ADMIN_ALERT_EMAIL not configured — skipping digest.")
            return

        now = timezone.now()
        # localdate(), NOT .date() — see admin_panel/views.py dashboard_stats.
        # `now` is UTC-aware, so .date() gives the UTC day; the digest runs at
        # 08:00 IST where the two happen to agree, but the bug bites instantly
        # if the cron time or server timezone ever moves.
        yesterday = timezone.localdate() - timedelta(days=1)

        y_orders = Order.objects.filter(
            is_deleted=False, **range_filter('created_at', yesterday, yesterday),
        ).exclude(status='cancelled')
        # Revenue is GROSS (what was collected). GST and delivery are reported
        # alongside it, not deducted — see admin_panel/views.py dashboard_stats.
        y_stats = y_orders.aggregate(
            # Output tax = goods GST + the 18% on delivery.
            revenue=Sum('total_amount'), gst=Sum(F('tax') + F('shipping_tax')),
            shipping_collected=Sum('shipping_charge'), shipping_cost=Sum('shipping_cost'),
        )
        y_count = y_orders.count()
        y_revenue = y_stats['revenue'] or 0
        y_gst = y_stats['gst'] or 0
        y_ship_in = y_stats['shipping_collected'] or 0
        y_ship_out = y_stats['shipping_cost'] or 0
        # Refunds are counted on the day they happened — the order they reverse
        # may be much older, and its GST was reported in that earlier period.
        from orders.refunds import refunded_totals_between
        y_gst_refunded = refunded_totals_between(yesterday, yesterday)['tax'] or 0

        waiting = Order.objects.filter(
            is_deleted=False, status='pending',
        ).filter(Q(payment_method='COD') | Q(payment_status='paid')).count()

        to_ship = Order.objects.filter(
            is_deleted=False, status__in=['confirmed', 'processing']).count()

        # Per size, so a pack that is not the default one is reported too.
        low = [(f"{v.product.name} ({v.formatted_weight})" if v.formatted_weight
                else v.product.name, v.stock)
               for v in low_stock_sizes()[:10]]

        chats = AssistantConversation.objects.filter(
            needs_human=True, status='active').count()

        lines = [
            f"Good morning! Here's your Nidhi Masala update for {now.strftime('%d %b %Y')}.",
            "",
            f"Yesterday: {y_count} order{'s' if y_count != 1 else ''}, Rs. {y_revenue} in sales.",
            f"  Sold excl. GST: Rs. {y_revenue - y_gst}"
            f" | GST collected from customers: Rs. {y_gst}"
            + (f" | GST reversed by refunds: Rs. {y_gst_refunded}"
               f" | net GST held: Rs. {y_gst - y_gst_refunded}" if y_gst_refunded else "")
            + " (tax taken, not tax owed — input credit lives in your books)",
            f"  Delivery collected: Rs. {y_ship_in}"
            + (f" | courier cost: Rs. {y_ship_out} | margin: Rs. {y_ship_in - y_ship_out}"
               if y_ship_out else " | courier cost not recorded"),
            "",
        ]

        todo = []
        if waiting:
            todo.append(f"- {waiting} new order{'s' if waiting != 1 else ''} waiting to be confirmed")
        if to_ship:
            todo.append(f"- {to_ship} order{'s' if to_ship != 1 else ''} to pack and ship")
        if chats:
            todo.append(f"- {chats} customer{'s' if chats != 1 else ''} waiting for a chat reply")
        if low:
            todo.append("- Running low on stock:")
            todo += [f"    * {name} — {stock} left" for name, stock in low]

        if todo:
            lines += ["Needs your attention today:"] + todo
        else:
            lines.append("Nothing needs your attention right now — all caught up!")

        lines += ["", "Open the admin panel to take action.", "", "— Your Nidhi Masala store"]

        _send_async(
            subject=f"Your store this morning — {y_count} orders yesterday, Rs. {y_revenue}",
            message="\n".join(lines),
            recipient=recipient,
        )
        self.stdout.write(self.style.SUCCESS(f"Daily digest queued to {recipient}."))
