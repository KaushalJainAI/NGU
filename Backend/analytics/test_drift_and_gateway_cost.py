"""Rollup drift detection, net revenue, and the gateway's cut.

Three fixes that share a theme: numbers that were quietly wrong or quietly
missing, with nothing in the system to say so.

* **Drift.** `DailySalesRollup` is a cache of a query, and the interval job only
  ever recomputes today. Anything corrected later — a late cancellation, a COD
  confirmation, a Recycle Bin restore — used to leave that day permanently
  overstated. The backfill window now covers a month; `check_rollup_drift` is
  what reports it if something ever reaches back further.
* **Net revenue.** Gross revenue beside a separate refunds tile reads as net to
  almost everyone.
* **Gateway cost.** Razorpay's fee was dropped on the floor. It is a real
  expense, and the GST inside it is input tax credit that was never claimed.
"""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.management import call_command
from django.utils import timezone

from analytics.models import DailySalesRollup
from orders.models import Order
from payments.models import Payment
from payments.services import _extract_gateway_cost, mark_payment_captured


def _order(user, **kw):
    kw.setdefault('status', 'confirmed')
    kw.setdefault('payment_method', 'COD')
    return Order.objects.create(
        user=user, shipping_address='1 Rd', phone_number='1234567890',
        subtotal=Decimal('400.00'), tax=Decimal('19.05'),
        shipping_charge=Decimal('59.00'), shipping_tax=Decimal('10.62'),
        total_amount=Decimal('469.62'), **kw)


# ---------------------------------------------------------------------------
# Rollup drift
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestRollupDriftDetection:
    def test_reports_nothing_when_rollups_are_fresh(self, test_user, capsys):
        _order(test_user)
        call_command('rollup_analytics')
        call_command('check_rollup_drift', days=7)
        assert 'No rollup drift' in capsys.readouterr().out

    def test_detects_a_late_cancellation(self, test_user, capsys):
        """The exact scenario the 3-day backfill window used to miss: an order
        cancelled long after its day stopped being recomputed."""
        order = _order(test_user)
        call_command('rollup_analytics')

        # Cancel it WITHOUT recomputing — i.e. what a cancellation outside the
        # backfill window looks like.
        Order.objects.filter(pk=order.pk).update(status='cancelled')

        call_command('check_rollup_drift', days=7)
        err = capsys.readouterr().err
        assert 'revenue' in err
        assert '469.62' in err          # stored value, now wrong
        assert 'rollup_analytics --days' in err   # tells you how to fix it

    def test_detects_a_missing_rollup_row(self, test_user, capsys):
        """A day with sales and no row at all reports zero on the dashboard —
        that is drift too, and the noisiest kind."""
        _order(test_user)
        call_command('check_rollup_drift', days=2)
        assert 'no rollup row' in capsys.readouterr().err

    def test_never_writes(self, test_user):
        """Recomputing on detection would hide the signal worth having."""
        order = _order(test_user)
        call_command('rollup_analytics')
        Order.objects.filter(pk=order.pk).update(status='cancelled')

        call_command('check_rollup_drift', days=7)
        row = DailySalesRollup.objects.get(date=timezone.localdate())
        assert row.revenue == Decimal('469.62')   # untouched

    def test_fail_flag_exits_non_zero(self, test_user):
        order = _order(test_user)
        call_command('rollup_analytics')
        Order.objects.filter(pk=order.pk).update(status='cancelled')
        with pytest.raises(SystemExit):
            call_command('check_rollup_drift', days=7, fail=True)

    def test_backfill_window_covers_a_month(self):
        """The window is the ONLY thing that picks up a late correction, so a
        regression back to a few days must fail loudly here."""
        from django.conf import settings
        assert getattr(settings, 'ROLLUP_BACKFILL_DAYS', 0) >= 30


# ---------------------------------------------------------------------------
# Net revenue
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestNetRevenue:
    def test_insights_reports_gross_and_net(self, test_user):
        from analytics import insights
        from orders.refunds import record_refund

        order = _order(test_user, payment_method='ONLINE', payment_status='paid')
        record_refund(order, Decimal('100.00'), source='admin', mark_refunded=True)
        call_command('rollup_analytics')

        today = timezone.localdate()
        kpis = insights.sales(today - timedelta(days=1), today)['kpis']
        # Gross stays gross — it is what reconciles against settlements.
        assert kpis['revenue'] == 469.62
        assert kpis['refunds'] == 100.0
        assert kpis['net_revenue'] == 369.62

    def test_dashboard_reports_net_revenue(self, admin_client, test_user):
        from django.core.cache import cache
        from orders.refunds import record_refund

        order = _order(test_user, payment_method='ONLINE', payment_status='paid')
        record_refund(order, Decimal('100.00'), source='admin', mark_refunded=True)
        cache.clear()

        d = admin_client.get('/api/dashboard/actions/').json()
        assert Decimal(d['today_revenue']) == Decimal('469.62')
        assert Decimal(d['today_net_revenue']) == Decimal('369.62')


# ---------------------------------------------------------------------------
# Gateway fee / input tax credit
# ---------------------------------------------------------------------------

class TestGatewayCostExtraction:
    def test_converts_paise_to_rupees(self):
        """Razorpay reports fee and tax in paise; storing them raw would
        overstate the expense a hundredfold."""
        fee, tax = _extract_gateway_cost({'fee': 1108, 'tax': 169})
        assert (fee, tax) == (Decimal('11.08'), Decimal('1.69'))

    def test_absent_fee_is_none_not_zero(self):
        """None means 'not reported'. Returning 0 would let a later fee-less
        event erase a fee an earlier one supplied."""
        assert _extract_gateway_cost({'method': 'upi'}) == (None, None)
        assert _extract_gateway_cost(None) == (None, None)


@pytest.mark.django_db
class TestGatewayCostIsRecorded:
    @pytest.fixture
    def pending_payment(self, test_user):
        order = _order(test_user, payment_method='ONLINE',
                       payment_status='pending', status='pending')
        return Payment.objects.create(
            order=order, payment_id='order_TEST123', payment_gateway='razorpay',
            amount=order.total_amount, status='pending')

    def test_capture_records_fee_and_itc(self, pending_payment):
        mark_payment_captured(
            'order_TEST123', 'pay_TEST123', event_id='evt_1', source='webhook',
            payment_entity={'method': 'upi', 'vpa': 'a@b', 'fee': 1108, 'tax': 169})
        pending_payment.refresh_from_db()
        assert pending_payment.gateway_fee == Decimal('11.08')
        assert pending_payment.gateway_tax == Decimal('1.69')
        # What actually lands in the bank.
        assert pending_payment.net_settlement == Decimal('458.54')

    def test_webhook_backfills_a_fee_after_verify_completed_it(self, pending_payment):
        """The common case in production: /verify/ completes the payment with no
        entity, so the webhook arriving later is the FIRST time a fee exists."""
        mark_payment_captured('order_TEST123', 'pay_TEST123',
                              event_id='evt_verify', source='verify')
        pending_payment.refresh_from_db()
        assert pending_payment.status == 'completed'
        assert pending_payment.gateway_fee == Decimal('0')   # nothing reported yet

        mark_payment_captured(
            'order_TEST123', 'pay_TEST123', event_id='evt_hook', source='webhook',
            payment_entity={'method': 'card', 'fee': 1108, 'tax': 169})
        pending_payment.refresh_from_db()
        assert pending_payment.gateway_fee == Decimal('11.08')
        assert pending_payment.gateway_tax == Decimal('1.69')

    def test_a_later_feeless_event_does_not_erase_the_fee(self, pending_payment):
        mark_payment_captured(
            'order_TEST123', 'pay_TEST123', event_id='evt_1', source='webhook',
            payment_entity={'fee': 1108, 'tax': 169})
        mark_payment_captured(
            'order_TEST123', 'pay_TEST123', event_id='evt_2', source='reconcile',
            payment_entity={'method': 'upi'})
        pending_payment.refresh_from_db()
        assert pending_payment.gateway_fee == Decimal('11.08')

    def test_dashboard_surfaces_the_itc(self, admin_client, pending_payment):
        from django.core.cache import cache
        mark_payment_captured(
            'order_TEST123', 'pay_TEST123', event_id='evt_1', source='webhook',
            payment_entity={'fee': 1108, 'tax': 169})
        cache.clear()

        d = admin_client.get('/api/dashboard/actions/').json()
        assert Decimal(d['mtd_gateway_fee']) == Decimal('11.08')
        assert Decimal(d['mtd_gateway_tax']) == Decimal('1.69')
        # The evidenced input credit is reported on its OWN — the collected
        # figure must stay a pure record of tax taken from customers, not a
        # part-netted number that reads as an amount payable.
        assert (Decimal(d['mtd_gst_net_collected'])
                == Decimal(d['mtd_gst_collected']) - Decimal(d['mtd_gst_refunded']))
