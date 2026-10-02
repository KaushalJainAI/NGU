"""Rollups carry the GST/delivery split so the weekly email and Insights can
report them without re-querying every order."""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.management import call_command
from django.utils import timezone

from analytics.models import DailySalesRollup
from orders.models import Order


@pytest.mark.django_db
class TestSalesRollupCarriesGstAndDelivery:
    def _order(self, user, **kw):
        kw.setdefault("status", "confirmed")
        return Order.objects.create(
            user=user, shipping_address="1 Rd", phone_number="1234567890",
            payment_method="COD",
            subtotal=Decimal("400.00"), tax=Decimal("19.05"),
            shipping_charge=Decimal("69.00"), total_amount=Decimal("469.00"), **kw)

    def test_rollup_sums_gst_shipping_and_cost(self, test_user):
        self._order(test_user, shipping_cost=Decimal("52.00"))
        call_command("rollup_analytics")

        row = DailySalesRollup.objects.get(date=timezone.localdate())
        # Revenue stays GROSS — it must still tie out to what was collected.
        assert row.revenue == Decimal("469.00")
        assert row.gst_collected == Decimal("19.05")
        assert row.shipping_collected == Decimal("69.00")
        assert row.shipping_cost == Decimal("52.00")

    def test_cancelled_orders_are_excluded_from_gst(self, test_user):
        """A cancelled sale collects no GST, so it must not inflate the liability."""
        self._order(test_user, status="cancelled", shipping_cost=Decimal("52.00"))
        call_command("rollup_analytics")
        row = DailySalesRollup.objects.filter(date=timezone.localdate()).first()
        assert row is None or row.gst_collected == Decimal("0")

    def test_soft_deleted_orders_are_excluded(self, test_user):
        """An order in the Recycle Bin is hidden from the admin dashboard, so it
        must not count as revenue or GST here either — otherwise the two screens
        report different numbers for the same day, and the figure vanishes for
        good once purge_recycle_bin hard-deletes the row."""
        self._order(test_user, is_deleted=True, shipping_cost=Decimal("52.00"))
        call_command("rollup_analytics")
        row = DailySalesRollup.objects.filter(date=timezone.localdate()).first()
        assert row is None or (
            row.orders == 0 and row.revenue == Decimal("0")
            and row.gst_collected == Decimal("0"))

    def test_refund_on_soft_deleted_order_reverses_no_gst(self, test_user):
        """Symmetry: if the sale isn't counted, its reversal must not be either,
        or the day reports tax coming back that never went out."""
        from orders.refunds import record_refund

        order = self._order(test_user, payment_status="paid")
        record_refund(order, Decimal("469.00"), source="admin", mark_refunded=True)
        Order.objects.filter(pk=order.pk).update(is_deleted=True)

        call_command("rollup_analytics")
        row = DailySalesRollup.objects.filter(date=timezone.localdate()).first()
        assert row is None or (
            row.refunds == Decimal("0") and row.gst_refunded == Decimal("0"))

    def test_unrecorded_courier_cost_stays_zero_not_null(self, test_user):
        self._order(test_user)          # no shipping_cost entered
        call_command("rollup_analytics")
        row = DailySalesRollup.objects.get(date=timezone.localdate())
        assert row.shipping_cost == Decimal("0")
        assert row.shipping_collected == Decimal("69.00")


@pytest.mark.django_db
def test_insights_sales_reports_gst_alongside_gross_revenue(test_user):
    from analytics import insights

    Order.objects.create(
        user=test_user, shipping_address="1 Rd", phone_number="1234567890",
        payment_method="COD", status="confirmed",
        subtotal=Decimal("400.00"), tax=Decimal("19.05"),
        shipping_charge=Decimal("69.00"), shipping_cost=Decimal("52.00"),
        total_amount=Decimal("469.00"))
    call_command("rollup_analytics")

    today = timezone.localdate()
    data = insights.sales(today - timedelta(days=1), today)
    assert data["kpis"]["revenue"] == 469.0          # gross, unchanged
    assert data["kpis"]["gst_collected"] == 19.05
    assert data["kpis"]["shipping_margin"] == 17.0   # 69 charged - 52 paid
