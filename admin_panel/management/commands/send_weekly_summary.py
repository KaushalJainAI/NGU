"""Weekly plain-language business summary for the store owner.

A short, sentence-based email (no charts, no jargon) sent every Monday for the
previous 7 days: revenue vs the week before, order count, best sellers, searches
that found nothing, and anything low on stock. Built entirely from existing
rollups + orders — no LLM.

Scheduled by `run_scheduler` (weekly); safe to run manually any time:

    python manage.py send_weekly_summary
"""
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.models import F, Sum, Count
from django.utils import timezone

from spices_backend.timeranges import range_filter


class Command(BaseCommand):
    help = "Email the store owner a plain-language weekly summary."

    def handle(self, *args, **options):
        from analytics.models import DailySalesRollup, SearchTermStat
        from products.models import Product
        from orders.models import OrderItem
        from orders.emails import _send_async

        recipient = getattr(settings, 'ADMIN_ALERT_EMAIL', '') or None
        if not recipient:
            self.stdout.write("ADMIN_ALERT_EMAIL not configured — skipping weekly summary.")
            return

        # localdate(), NOT now().date() — see admin_panel/views.py
        # dashboard_stats. `now()` is UTC-aware, so .date() gives the UTC day
        # while range_filter reads its bounds in TIME_ZONE; the mismatch shifts
        # the whole reporting week by a day for part of every night.
        today = timezone.localdate()
        this_start = today - timedelta(days=7)   # last 7 days [this_start, today)
        prev_start = today - timedelta(days=14)  # the 7 days before that

        def sales_between(start, end):
            agg = DailySalesRollup.objects.filter(
                date__gte=start, date__lt=end
            ).aggregate(
                revenue=Sum('revenue'), orders=Sum('orders'),
                gst=Sum('gst_collected'), gst_refunded=Sum('gst_refunded'),
                ship_in=Sum('shipping_collected'), ship_out=Sum('shipping_cost'),
            )
            return agg

        this_agg = sales_between(this_start, today)
        prev_agg = sales_between(prev_start, this_start)
        this_rev, this_orders = this_agg['revenue'] or 0, this_agg['orders'] or 0
        prev_rev = prev_agg['revenue'] or 0
        this_gst = this_agg['gst'] or 0
        this_gst_refunded = this_agg['gst_refunded'] or 0
        this_ship_in = this_agg['ship_in'] or 0
        this_ship_out = this_agg['ship_out'] or 0

        # Revenue trend sentence.
        if prev_rev > 0:
            pct = round((float(this_rev) - float(prev_rev)) / float(prev_rev) * 100)
            if pct > 0:
                trend = f"{pct}% more than the week before"
            elif pct < 0:
                trend = f"{abs(pct)}% less than the week before"
            else:
                trend = "about the same as the week before"
        elif this_rev > 0:
            trend = "your first sales in this report"
        else:
            trend = "no sales the week before either"

        # Best sellers (by units) over the last 7 days, excluding cancelled orders.
        best = (
            OrderItem.objects.filter(
                order__is_deleted=False,
                # `today` is exclusive here — the week is [this_start, today).
                **range_filter('order__created_at', this_start,
                               today - timedelta(days=1)),
            ).exclude(order__status='cancelled')
            .values('product_name')
            .annotate(units=Sum('quantity'))
            .order_by('-units')[:3]
        )

        # Searches that found nothing (customers wanted something you don't list).
        zero = (
            SearchTermStat.objects.filter(
                date__gte=this_start, date__lt=today, zero_result=True
            ).values('term').annotate(n=Sum('count')).order_by('-n')[:5]
        )

        low = list(Product.objects.filter(
            is_active=True, stock__lte=F('low_stock_threshold'),
        ).order_by('stock').values_list('name', 'stock')[:10])

        # ---- Compose ----
        lines = [
            f"Here's your Nidhi Masala week: {this_start.strftime('%d %b')} – {(today - timedelta(days=1)).strftime('%d %b %Y')}.",
            "",
            f"You made Rs. {this_rev} from {this_orders} order{'s' if this_orders != 1 else ''} — {trend}.",
            f"Of that, Rs. {this_gst} was GST you collected from customers"
            + (f", less Rs. {this_gst_refunded} reversed by refunds "
               f"— Rs. {this_gst - this_gst_refunded} net" if this_gst_refunded else "")
            + f", on sales of Rs. {this_rev - this_gst} excluding GST.",
            "That's what you took, not what you owe — what you pay is that less "
            "the input credit on your purchases, which your books have and we don't.",
            f"Delivery: Rs. {this_ship_in} collected"
            + (f", Rs. {this_ship_out} paid to couriers "
               f"(margin Rs. {this_ship_in - this_ship_out})."
               if this_ship_out else " — courier costs not recorded."),
            "",
        ]

        if best:
            lines.append("Best sellers this week:")
            lines += [f"  {i}. {b['product_name']} — {b['units']} sold" for i, b in enumerate(best, 1)]
            lines.append("")

        if zero:
            lines.append("Customers searched for these but found nothing "
                         "(consider stocking them or adding search words):")
            lines += [f"  - {z['term']}" for z in zero]
            lines.append("")

        if low:
            lines.append("Running low on stock:")
            lines += [f"  - {name} ({stock} left)" for name, stock in low]
            lines.append("")

        lines += ["Open the admin panel to act on any of the above.", "", "— Your Nidhi Masala store"]

        _send_async(
            subject=f"Your week: Rs. {this_rev} from {this_orders} orders",
            message="\n".join(lines),
            recipient=recipient,
        )
        self.stdout.write(self.style.SUCCESS(f"Weekly summary queued to {recipient}."))
