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


class Command(BaseCommand):
    help = "Email the store owner a plain-language daily digest."

    def handle(self, *args, **options):
        from orders.models import Order
        from products.models import Product
        from assistant.models import AssistantConversation
        from orders.emails import _send_async  # shared best-effort sender

        recipient = getattr(settings, 'ADMIN_ALERT_EMAIL', '') or None
        if not recipient:
            self.stdout.write("ADMIN_ALERT_EMAIL not configured — skipping digest.")
            return

        now = timezone.now()
        yesterday = (now - timedelta(days=1)).date()

        y_orders = Order.objects.filter(
            is_deleted=False, created_at__date=yesterday,
        ).exclude(status='cancelled')
        y_stats = y_orders.aggregate(revenue=Sum('total_amount'))
        y_count = y_orders.count()
        y_revenue = y_stats['revenue'] or 0

        waiting = Order.objects.filter(
            is_deleted=False, status='pending',
        ).filter(Q(payment_method='COD') | Q(payment_status='paid')).count()

        to_ship = Order.objects.filter(
            is_deleted=False, status__in=['confirmed', 'processing']).count()

        low = list(Product.objects.filter(
            is_active=True, stock__lte=F('low_stock_threshold'),
        ).order_by('stock').values_list('name', 'stock')[:10])

        chats = AssistantConversation.objects.filter(
            needs_human=True, status='active').count()

        lines = [
            f"Good morning! Here's your Nidhi Masala update for {now.strftime('%d %b %Y')}.",
            "",
            f"Yesterday: {y_count} order{'s' if y_count != 1 else ''}, Rs. {y_revenue} in sales.",
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
