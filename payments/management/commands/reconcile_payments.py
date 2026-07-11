"""L3 active reconciliation — the backstop that makes payments self-healing.

Run on a schedule (every ~15 min + a nightly sweep) via cron / Windows Task
Scheduler:

    python manage.py reconcile_payments

For each ONLINE order still unpaid past the TTL it asks Razorpay for the truth:
  * captured at Razorpay  → mark paid (a webhook was missed) — L3 saves L2
  * otherwise             → cancel the order + restore stock (through the same
                            cancel logic, so release stays exactly-once)

It also prunes the idempotency ledger and records a `last_run` heartbeat so a
dead job can itself be alerted on (the dead-man's switch, §7.6c).
"""
from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from orders.models import Order
from payments.models import Payment, ProcessedWebhookEvent
from payments import services
from payments.gateway import get_razorpay_client, RazorpayNotConfigured

RECONCILE_LAST_RUN_KEY = 'ngu:payments:reconcile:last_run'


class Command(BaseCommand):
    help = "Reconcile stuck ONLINE payments against Razorpay; auto-cancel abandoned orders."

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true',
                            help="Report what would happen without writing changes.")
        parser.add_argument('--ttl-minutes', type=int, default=None,
                            help="Override PAYMENT_STUCK_TTL_MINUTES.")

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        ttl_minutes = options['ttl_minutes'] or getattr(settings, 'PAYMENT_STUCK_TTL_MINUTES', 30)
        cutoff = timezone.now() - timedelta(minutes=ttl_minutes)

        try:
            client = get_razorpay_client()
        except RazorpayNotConfigured:
            self.stderr.write("Razorpay not configured — nothing to reconcile.")
            return

        stuck = Order.objects.filter(
            payment_method='ONLINE',
            payment_status__in=['pending', 'processing'],
            status='pending',
            created_at__lt=cutoff,
        )

        recovered = cancelled = errors = 0
        for order in stuck:
            payment = Payment.objects.filter(order=order, payment_gateway='razorpay').first()
            if payment is None or not payment.payment_id:
                # ONLINE order that never even started payment → abandoned.
                if not dry_run:
                    self._cancel_abandoned(order)
                cancelled += 1
                continue
            try:
                captured = self._captured_payment(client, payment.payment_id)
            except Exception as e:  # noqa: BLE001
                self.stderr.write(f"  order {order.id}: Razorpay fetch failed: {e}")
                errors += 1
                continue

            if captured:
                if not dry_run:
                    services.mark_payment_captured(
                        razorpay_order_id=payment.payment_id,
                        razorpay_payment_id=captured['id'],
                        source='reconcile', amount=captured.get('amount'),
                        raw_payload={'reconcile': True, 'payment': captured})
                    services.log_payment_event(
                        Payment.objects.filter(pk=payment.pk).first(),
                        event_type='recovered_paid', source='reconcile',
                        message=f"L3 found a missed capture {captured['id']}.",
                        is_exception=True)
                recovered += 1
            else:
                if not dry_run:
                    self._cancel_abandoned(order)
                cancelled += 1

        # Prune the idempotency ledger well past the 24h retry window.
        pruned = 0
        if not dry_run:
            pruned, _ = ProcessedWebhookEvent.objects.filter(
                received_at__lt=timezone.now() - timedelta(days=30)).delete()
            cache.set(RECONCILE_LAST_RUN_KEY, timezone.now().isoformat(), None)

        self.stdout.write(self.style.SUCCESS(
            f"reconcile_payments done (dry_run={dry_run}): "
            f"recovered={recovered} cancelled={cancelled} "
            f"errors={errors} pruned_events={pruned}"))

    def _captured_payment(self, client, razorpay_order_id):
        """Return the captured payment entity for a Razorpay order, or None."""
        resp = client.order.payments(razorpay_order_id)
        for p in resp.get('items', []):
            if p.get('status') == 'captured':
                return p
        return None

    def _cancel_abandoned(self, order):
        """Cancel an abandoned order and restore stock through the shared cancel
        logic, under the canonical Order→Payment lock (release stays exactly-once)."""
        from orders.views import restore_order_stock
        with transaction.atomic():
            locked = Order.objects.select_for_update().get(pk=order.pk)
            Payment.objects.select_for_update().filter(order=locked).first()
            if locked.status == 'cancelled':
                return
            # Guard: never auto-cancel an order that became paid between the query
            # and the lock.
            if locked.payment_status == 'paid':
                return
            restore_order_stock(locked)
            locked.status = 'cancelled'
            # An abandoned/expired online checkout is explicitly 'rejected'
            # (distinct from a gateway 'failed'), so the customer and admin see a
            # clear "payment rejected — order cancelled" state.
            locked.payment_status = 'rejected'
            locked.cancelled_at = timezone.now()
            locked.save(update_fields=['status', 'payment_status', 'cancelled_at'])
            services.log_payment_event(
                Payment.objects.filter(order=locked).first(), order=locked,
                event_type='auto_cancelled', source='reconcile',
                message=f"Order {locked.id} auto-cancelled after payment TTL; stock restored.")
