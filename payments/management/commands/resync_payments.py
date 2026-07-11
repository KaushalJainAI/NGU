"""Disaster-recovery resync — re-derive local payment state from Razorpay's truth.

Same code path as the L3 reconcile job, but a wider window and no TTL: it walks
every Razorpay payment we know about since a date and rewrites our Payment /
Order.payment_status to match, writing PaymentEvent(source='reconcile') rows for
every correction (PAYMENT_INTEGRATION_PLAN.md §7.9).

    python manage.py resync_payments --since 2026-01-01

Recovery from local data loss = restore latest DB backup → run this since the
backup timestamp → review the exceptions queue.
"""
from datetime import datetime

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from django.utils.dateparse import parse_datetime, parse_date

from payments.models import Payment
from payments import services
from payments.gateway import get_razorpay_client, RazorpayNotConfigured


class Command(BaseCommand):
    help = "Rebuild local payment state from Razorpay for all payments since a date."

    def add_arguments(self, parser):
        parser.add_argument('--since', required=True,
                            help="ISO date/datetime, e.g. 2026-01-01 or 2026-01-01T00:00:00")
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **options):
        since = self._parse_since(options['since'])
        dry_run = options['dry_run']

        try:
            client = get_razorpay_client()
        except RazorpayNotConfigured:
            raise CommandError("Razorpay not configured.")

        payments = Payment.objects.filter(
            payment_gateway='razorpay', created_at__gte=since
        ).select_related('order')

        corrected = matched = errors = 0
        for payment in payments:
            if not payment.payment_id:
                continue
            try:
                captured = self._captured_payment(client, payment.payment_id)
            except Exception as e:  # noqa: BLE001
                self.stderr.write(f"  payment {payment.id}: fetch failed: {e}")
                errors += 1
                continue

            order = payment.order
            if captured and payment.status != 'completed':
                if not dry_run:
                    services.mark_payment_captured(
                        razorpay_order_id=payment.payment_id,
                        razorpay_payment_id=captured['id'], source='reconcile',
                        amount=captured.get('amount'),
                        raw_payload={'resync': True, 'payment': captured})
                    services.log_payment_event(
                        Payment.objects.filter(pk=payment.pk).first(),
                        event_type='recovered_paid', source='reconcile',
                        message=f"resync: capture {captured['id']} was missing locally.",
                        is_exception=True)
                corrected += 1
            elif captured and order.payment_status != 'paid':
                # Payment says completed but the order drifted — realign + flag.
                if not dry_run:
                    services.log_payment_event(
                        payment, event_type='amount_mismatch', source='reconcile',
                        message="resync: payment completed but order not marked paid.",
                        is_exception=True)
                corrected += 1
            else:
                matched += 1

        self.stdout.write(self.style.SUCCESS(
            f"resync_payments done (dry_run={dry_run}): corrected={corrected} "
            f"matched={matched} errors={errors}"))

    def _parse_since(self, value):
        dt = parse_datetime(value)
        if dt is None:
            d = parse_date(value)
            if d is None:
                raise CommandError(f"Could not parse --since '{value}'.")
            dt = datetime(d.year, d.month, d.day)
        if timezone.is_naive(dt):
            dt = timezone.make_aware(dt, timezone.get_current_timezone())
        return dt

    def _captured_payment(self, client, razorpay_order_id):
        resp = client.order.payments(razorpay_order_id)
        for p in resp.get('items', []):
            if p.get('status') == 'captured':
                return p
        return None
