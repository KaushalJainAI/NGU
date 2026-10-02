"""Detect stored rollups that no longer match the orders they were built from.

`DailySalesRollup` is a cache of a query. Like any cache it can go stale, and the
way it goes stale here is silent: the interval job only recomputes today, so any
order that changes later — a cancellation, a corrected courier cost, a Recycle
Bin restore, a COD confirmation — leaves its day's stored revenue and GST wrong
with nothing to say so. The nightly backfill (ROLLUP_BACKFILL_DAYS) is what
should prevent that; this command is what tells us when it doesn't.

It never writes. Recomputing on detection would hide exactly the signal worth
having — that something is reaching further back than the backfill window — so
drift is reported and the fix stays a deliberate act (`rollup_analytics --days N`).

Usage:
    python manage.py check_rollup_drift              # last 90 days
    python manage.py check_rollup_drift --days 400
    python manage.py check_rollup_drift --fail       # non-zero exit if drifted
"""
from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db.models import Count, F, Sum
from django.utils import timezone

from analytics.models import DailySalesRollup
from orders.refunds import refunded_totals_between
from spices_backend.timeranges import day_range

from .rollup_analytics import countable_orders

# Money is compared to the paisa, but a 1-paisa gap is rounding, not drift —
# flagging it would train everyone to ignore the alert.
TOLERANCE = Decimal('0.01')

# (rollup field, human label) pairs re-derived below. Deliberately the FINANCIAL
# ones only: order/unit counts drifting matters far less than revenue or GST,
# and a narrow check is one people actually act on.
CHECKED_FIELDS = [
    ('revenue', 'revenue'),
    ('gst_collected', 'GST collected'),
    ('refunds', 'refunds'),
    ('gst_refunded', 'GST reversed'),
]


class Command(BaseCommand):
    help = "Compare stored sales rollups against the source orders and report drift."

    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, default=90,
                            help='How many days back to verify (default 90).')
        parser.add_argument('--fail', action='store_true',
                            help='Exit non-zero when drift is found (for CI/alerting).')

    def handle(self, *args, **options):
        days = max(int(options['days']), 1)
        today = timezone.localdate()
        drifted = []

        rows = {
            r.date: r for r in DailySalesRollup.objects.filter(
                date__gte=today - timedelta(days=days - 1), date__lte=today)
        }

        for offset in range(days):
            day = today - timedelta(days=offset)
            actual = self._recompute(day)
            stored = rows.get(day)

            if stored is None:
                # A day with real sales and no rollup row at all is drift too —
                # the dashboard would silently report zero for it.
                if actual['revenue'] > 0:
                    drifted.append((day, 'no rollup row', actual['revenue'], Decimal('0')))
                continue

            for field, label in CHECKED_FIELDS:
                want = actual[field]
                got = Decimal(str(getattr(stored, field) or 0))
                if abs(want - got) > TOLERANCE:
                    drifted.append((day, label, want, got))

        if not drifted:
            self.stdout.write(self.style.SUCCESS(
                f"No rollup drift across the last {days} day(s)."))
            return

        for day, label, want, got in drifted:
            self.stderr.write(self.style.ERROR(
                f"{day}: {label} stored={got} but source says {want} "
                f"(off by {want - got})"))
        affected = sorted({d for d, *_ in drifted})
        self.stderr.write(self.style.WARNING(
            f"{len(drifted)} discrepancy(ies) across {len(affected)} day(s), "
            f"oldest {affected[0]}. Fix with: manage.py rollup_analytics --days "
            f"{(today - affected[0]).days + 1}"))
        if options['fail']:
            raise SystemExit(1)

    def _recompute(self, day):
        """Re-derive a day's financial totals straight from the orders."""
        start, end = day_range(day)
        agg = countable_orders().filter(
            created_at__gte=start, created_at__lt=end,
        ).aggregate(
            revenue=Sum('total_amount'),
            # Output tax is goods GST + the 18% on delivery — must mirror
            # rollup_analytics exactly, or the check reports phantom drift.
            gst=Sum(F('tax') + F('shipping_tax')),
            n=Count('id'),
        )
        refunded = refunded_totals_between(day, day)
        return {
            'revenue': Decimal(str(agg['revenue'] or 0)),
            'gst_collected': Decimal(str(agg['gst'] or 0)),
            'refunds': Decimal(str(refunded['amount'] or 0)),
            'gst_refunded': Decimal(str(refunded['tax'] or 0)),
        }
