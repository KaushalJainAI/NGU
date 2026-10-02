"""Delivery GST, and the COD cash-collection tick.

Two changes land together here because they meet in one place — the tax owed on
an order and the money actually received for it are different questions, and the
system used to answer neither correctly:

* **Delivery is a taxable supply.** The fee is billed NET at ``SHIPPING_CHARGE``
  and taxed at ``SHIPPING_TAX_RATE`` (18%, SAC 9968) on top. This is the OPPOSITE
  convention to goods, whose MRP already contains their GST, so the delivery tax
  is a genuine addend to the total while the goods tax never is. Getting these
  two backwards is the failure mode every test below is guarding.
* **COD cash is confirmed by hand.** Nothing ever marked a COD order paid, so
  the cash the courier held was invisible and a COD return could not be recorded
  at all — its GST stayed on the books forever. An admin ticks ``cod_paid``.

The tick is deliberately a CASH fact, not a tax one: GST accrues at order date
either way (time of supply for goods is the invoice, not the payment), so
ticking must never move a GST figure. `test_ticking_moves_no_gst_figure` pins
that, and it is the assertion to keep if any of the others are ever rewritten.
"""
from decimal import Decimal

import pytest
from django.core.management import call_command
from django.utils import timezone

from analytics.models import DailySalesRollup
from orders.models import Order, OrderRefund
from orders.pricing import refund_tax_for, shipping_tax_for

URL = "/api/orders/"


@pytest.fixture
def cod_order(db, test_user):
    """Rs. 400 goods (Rs. 19.05 GST inside) + Rs. 59 delivery + Rs. 10.62 on it."""
    return Order.objects.create(
        user=test_user, shipping_address="1 Rd", phone_number="1234567890",
        payment_method="COD", payment_status="pending", status="delivered",
        subtotal=Decimal("400.00"), tax=Decimal("19.05"),
        shipping_charge=Decimal("59.00"), shipping_tax=Decimal("10.62"),
        total_amount=Decimal("469.62"))


# ---------------------------------------------------------------------------
# Delivery GST
# ---------------------------------------------------------------------------

class TestShippingTaxMath:
    def test_tax_is_added_on_top_not_carved_out(self):
        """59 net at 18% is 10.62 — NOT 59 * 18/118 (9.00), which is what an
        inclusive reading would produce and would under-collect on every order."""
        assert shipping_tax_for(Decimal("59")) == Decimal("10.62")

    def test_free_shipping_carries_no_tax(self):
        assert shipping_tax_for(Decimal("0")) == Decimal("0.00")


@pytest.mark.django_db
class TestOrderCarriesDeliveryTax:
    def test_total_tax_covers_goods_and_delivery(self, cod_order):
        """`tax` alone under-reports the liability by the GST on the fee."""
        assert cod_order.tax == Decimal("19.05")
        assert cod_order.shipping_tax == Decimal("10.62")
        assert cod_order.total_tax == Decimal("29.67")

    def test_grand_total_reconciles(self, cod_order):
        """Goods tax is inside the subtotal; delivery tax is outside it."""
        assert (cod_order.subtotal + cod_order.shipping_charge
                + cod_order.shipping_tax) == cod_order.total_amount

    def test_breakdown_carries_an_18_percent_delivery_slab(self, cod_order):
        from orders.pricing import order_tax_breakdown
        rows = order_tax_breakdown(cod_order)
        delivery = [r for r in rows if r["rate"] == 18.0]
        assert delivery == [
            {"rate": 18.0, "taxable_value": 59.0, "tax_amount": 10.62}]

    def test_breakdown_sums_to_total_tax(self, cod_order):
        """A GST summary that disagrees with its own total is unauditable."""
        from orders.pricing import order_tax_breakdown
        rows = order_tax_breakdown(cod_order)
        assert sum(Decimal(str(r["tax_amount"])) for r in rows) == cod_order.total_tax

    def test_legacy_order_without_delivery_tax_is_untouched(self, test_user):
        """Orders placed before delivery was taxed must still reconcile."""
        old = Order.objects.create(
            user=test_user, shipping_address="1 Rd", phone_number="1234567890",
            payment_method="COD", subtotal=Decimal("400.00"), tax=Decimal("19.05"),
            shipping_charge=Decimal("69.00"), total_amount=Decimal("469.00"))
        assert old.shipping_tax == Decimal("0")
        assert old.total_tax == Decimal("19.05")
        from orders.pricing import order_tax_breakdown
        assert not [r for r in order_tax_breakdown(old) if r["rate"] == 18.0]


@pytest.mark.django_db
class TestRefundReversesDeliveryTax:
    def test_full_refund_reverses_goods_and_delivery_tax(self, cod_order):
        """Refunding everything must leave no output tax stranded on the order —
        otherwise GST is owed on money already given back."""
        assert refund_tax_for(cod_order, Decimal("469.62")) == Decimal("29.67")

    def test_partial_within_goods_leaves_delivery_tax_alone(self, cod_order):
        """Goods come back first; the courier was still paid."""
        assert refund_tax_for(cod_order, Decimal("200.00")) == Decimal("9.53")

    def test_refund_past_the_goods_starts_reversing_delivery(self, cod_order):
        """400 of goods + the whole 69.62 gross fee = its full 10.62."""
        assert refund_tax_for(cod_order, Decimal("469.62")) == Decimal("29.67")
        # Half the gross fee returns half its tax.
        assert refund_tax_for(cod_order, Decimal("434.81")) == Decimal("24.36")

    def test_never_reverses_more_than_was_charged(self, cod_order):
        cod_order.refunded_tax = Decimal("29.67")
        assert refund_tax_for(cod_order, Decimal("469.62")) == Decimal("0.00")


@pytest.mark.django_db
class TestReportingCountsDeliveryTax:
    def test_rollup_gst_includes_delivery(self, cod_order):
        cod_order.status = "confirmed"
        cod_order.save(update_fields=["status"])
        call_command("rollup_analytics")
        row = DailySalesRollup.objects.get(date=timezone.localdate())
        assert row.gst_collected == Decimal("29.67")
        assert row.shipping_tax_collected == Decimal("10.62")

    def test_dashboard_gst_includes_delivery(self, admin_client, cod_order):
        from django.core.cache import cache
        cod_order.status = "confirmed"
        cod_order.save(update_fields=["status"])
        cache.clear()
        d = admin_client.get("/api/dashboard/actions/").json()
        assert Decimal(d["today_gst_collected"]) == Decimal("29.67")


# ---------------------------------------------------------------------------
# COD cash collection (11a) and the refund it unblocks (11b)
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestCodPaidTick:
    def test_cod_order_starts_unpaid_and_outstanding(self, cod_order):
        assert cod_order.payment_status == "pending"
        assert cod_order.cod_paid_at is None
        assert cod_order.cod_payment_outstanding is True

    def test_tick_marks_paid_and_records_who_and_when(
            self, admin_client, admin_user, cod_order):
        r = admin_client.patch(f"{URL}{cod_order.id}/", {"cod_paid": True},
                               format="json")
        assert r.status_code == 200
        cod_order.refresh_from_db()
        assert cod_order.payment_status == "paid"
        assert cod_order.cod_paid_at is not None
        # Confirming receipt of cash is the highest-trust action in the panel,
        # so it must never be anonymous.
        assert cod_order.cod_confirmed_by == admin_user
        assert cod_order.cod_payment_outstanding is False

    def test_advancing_status_alone_never_marks_paid(self, admin_client, test_user):
        """Delivery is not payment: the courier usually remits days later, and
        auto-ticking would record cash that has not arrived."""
        order = Order.objects.create(
            user=test_user, shipping_address="1 Rd", phone_number="1234567890",
            payment_method="COD", subtotal=Decimal("100.00"),
            total_amount=Decimal("100.00"), status="shipped")
        for nxt in ("delivering", "delivered"):
            assert admin_client.patch(f"{URL}{order.id}/", {"status": nxt},
                                      format="json").status_code == 200
        order.refresh_from_db()
        assert order.payment_status == "pending"
        assert order.cod_paid_at is None

    def test_tick_is_rejected_on_an_online_order(self, admin_client, test_user):
        """Otherwise an admin could hand-mark an unpaid online order settled and
        bypass gateway verification entirely."""
        order = Order.objects.create(
            user=test_user, shipping_address="1 Rd", phone_number="1234567890",
            payment_method="ONLINE", subtotal=Decimal("100.00"),
            total_amount=Decimal("100.00"))
        r = admin_client.patch(f"{URL}{order.id}/", {"cod_paid": True}, format="json")
        assert r.status_code == 400
        order.refresh_from_db()
        assert order.payment_status == "pending"

    def test_customer_cannot_tick_their_own_order(self, authenticated_client, cod_order):
        authenticated_client.patch(f"{URL}{cod_order.id}/", {"cod_paid": True},
                                   format="json")
        cod_order.refresh_from_db()
        assert cod_order.cod_paid_at is None

    def test_untick_reverses_a_misclick(self, admin_client, cod_order):
        admin_client.patch(f"{URL}{cod_order.id}/", {"cod_paid": True}, format="json")
        r = admin_client.patch(f"{URL}{cod_order.id}/", {"cod_paid": False},
                               format="json")
        assert r.status_code == 200
        cod_order.refresh_from_db()
        assert cod_order.cod_paid_at is None
        assert cod_order.cod_confirmed_by is None
        assert cod_order.payment_status == "pending"

    def test_cannot_untick_once_refunded_against_it(self, admin_client, cod_order):
        """Un-ticking would leave a refund recorded against cash the system then
        claims was never received."""
        admin_client.patch(f"{URL}{cod_order.id}/", {"cod_paid": True}, format="json")
        admin_client.patch(f"{URL}{cod_order.id}/", {"status": "refunded"},
                           format="json")
        r = admin_client.patch(f"{URL}{cod_order.id}/", {"cod_paid": False},
                               format="json")
        assert r.status_code == 400

    def test_ticking_moves_no_gst_figure(self, admin_client, cod_order):
        """The tick is a CASH fact. GST accrued at order date and must not move
        when the money turns up — otherwise the tax and cash views diverge."""
        before = (cod_order.tax, cod_order.shipping_tax, cod_order.total_tax)
        admin_client.patch(f"{URL}{cod_order.id}/", {"cod_paid": True}, format="json")
        cod_order.refresh_from_db()
        assert (cod_order.tax, cod_order.shipping_tax, cod_order.total_tax) == before


@pytest.mark.django_db
class TestCodRefundUnblocked:
    def test_unconfirmed_cod_order_cannot_be_refunded(self, admin_client, cod_order):
        """No cash was ever received, so a refund would reverse GST on money
        that never arrived."""
        r = admin_client.patch(f"{URL}{cod_order.id}/", {"status": "refunded"},
                               format="json")
        assert r.status_code == 400
        assert not OrderRefund.objects.exists()

    def test_confirmed_cod_order_can_be_refunded(self, admin_client, cod_order):
        """The hole this closes: before the tick existed a genuine COD return
        could not be recorded AT ALL, so its GST stayed owed forever."""
        admin_client.patch(f"{URL}{cod_order.id}/", {"cod_paid": True}, format="json")
        r = admin_client.patch(f"{URL}{cod_order.id}/", {"status": "refunded"},
                               format="json")
        assert r.status_code == 200
        cod_order.refresh_from_db()
        assert cod_order.refunded_amount == Decimal("469.62")
        # And the full output tax — goods AND delivery — comes back off.
        assert cod_order.refunded_tax == Decimal("29.67")

    def test_partial_cod_refund_is_recorded(self, admin_client, cod_order):
        admin_client.patch(f"{URL}{cod_order.id}/", {"cod_paid": True}, format="json")
        r = admin_client.patch(
            f"{URL}{cod_order.id}/",
            {"status": "refunded", "refund_amount": "200.00"}, format="json")
        assert r.status_code == 200
        cod_order.refresh_from_db()
        assert cod_order.refunded_amount == Decimal("200.00")
        assert cod_order.refunded_tax == Decimal("9.53")


@pytest.mark.django_db
class TestCodCashReporting:
    def test_dashboard_reports_cash_the_courier_holds(self, admin_client, cod_order):
        from django.core.cache import cache
        cache.clear()
        d = admin_client.get("/api/dashboard/actions/").json()
        assert Decimal(d["cod_pending_amount"]) == Decimal("469.62")
        assert d["cod_pending_count"] == 1

        admin_client.patch(f"{URL}{cod_order.id}/", {"cod_paid": True}, format="json")
        cache.clear()
        d = admin_client.get("/api/dashboard/actions/").json()
        assert Decimal(d["cod_pending_amount"]) == Decimal("0")
        assert Decimal(d["cod_collected_today"]) == Decimal("469.62")

    def test_rollup_buckets_cash_by_confirmation_date(self, admin_client, cod_order):
        """Not by order date: couriers remit in batches, so the order being
        settled is normally not one of today's."""
        admin_client.patch(f"{URL}{cod_order.id}/", {"cod_paid": True}, format="json")
        call_command("rollup_analytics")
        row = DailySalesRollup.objects.get(date=timezone.localdate())
        assert row.cod_collected == Decimal("469.62")
