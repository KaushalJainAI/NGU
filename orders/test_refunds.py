"""Refunds reverse GST, so the tax owed to the government goes down.

The rules being pinned here:
  * a refund reverses the GST that came with the money
  * it is counted on the day the REFUND happened, never the day of the sale
  * it can never reverse more GST than was collected, however many times it fires
  * money back means goods back: a refund restocks, exactly once per order
  * only an order that actually paid us ONLINE can be refunded at all
"""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.management import call_command
from django.utils import timezone

from analytics.models import DailySalesRollup
from orders.models import Order, OrderRefund
from orders.pricing import refund_tax_for
from orders.refunds import record_refund

URL = "/api/orders/"


@pytest.fixture
def paid_order(db, test_user):
    """Rs. 400 of 5%-GST goods (Rs. 19.05 GST inside) + Rs. 69 untaxed delivery."""
    return Order.objects.create(
        user=test_user, shipping_address="1 Rd", phone_number="1234567890",
        payment_method="ONLINE", payment_status="paid", status="delivered",
        subtotal=Decimal("400.00"), tax=Decimal("19.05"),
        shipping_charge=Decimal("69.00"), total_amount=Decimal("469.00"))


class TestRefundTaxMath:
    def test_full_refund_reverses_exactly_the_tax_charged(self, paid_order):
        assert refund_tax_for(paid_order, Decimal("469.00")) == Decimal("19.05")

    def test_half_the_goods_reverses_half_the_tax(self, paid_order):
        assert refund_tax_for(paid_order, Decimal("200.00")) == Decimal("9.53")

    def test_refunding_delivery_too_adds_no_extra_gst(self, paid_order):
        """Shipping carries no GST, so a refund is applied to goods first and the
        excess (delivery) reverses nothing further."""
        goods_only = refund_tax_for(paid_order, Decimal("400.00"))
        with_delivery = refund_tax_for(paid_order, Decimal("469.00"))
        assert goods_only == with_delivery == Decimal("19.05")

    def test_zero_rated_order_reverses_nothing(self, db, test_user):
        papad = Order.objects.create(
            user=test_user, shipping_address="1 Rd", phone_number="1",
            payment_method="COD", subtotal=Decimal("100.00"), tax=Decimal("0.00"),
            total_amount=Decimal("100.00"))
        assert refund_tax_for(papad, Decimal("100.00")) == Decimal("0.00")


@pytest.mark.django_db
class TestRefundLedger:
    def test_full_refund_reverses_gst_and_marks_the_order_refunded(self, paid_order):
        record_refund(paid_order, Decimal("469.00"), source="admin")
        paid_order.refresh_from_db()
        assert paid_order.refunded_amount == Decimal("469.00")
        assert paid_order.refunded_tax == Decimal("19.05")
        assert paid_order.status == "refunded"
        assert paid_order.payment_status == "refunded"

    def test_partial_refund_marks_nothing_refunded(self, paid_order):
        """We never issue partials, but the gateway can. Such an order is NOT
        refunded — most of the customer's money is still held, and saying
        otherwise misleads the admin table, the order card and the reconciler."""
        record_refund(paid_order, Decimal("200.00"))
        paid_order.refresh_from_db()
        assert paid_order.refunded_tax == Decimal("9.53"), "the money moved, so its GST reverses"
        assert paid_order.status == "delivered", "a part-refunded order was still delivered"
        assert paid_order.payment_status == "paid", "part-refunded is not refunded"

    def test_the_balancing_refund_then_closes_the_order(self, paid_order):
        record_refund(paid_order, Decimal("200.00"))
        record_refund(paid_order, Decimal("269.00"))
        paid_order.refresh_from_db()
        assert paid_order.refunded_amount == Decimal("469.00")
        assert paid_order.status == "refunded"
        assert paid_order.payment_status == "refunded"

    def test_repeated_partials_never_over_reverse_the_gst(self, paid_order):
        for _ in range(6):                     # 6 x 100 = 600 > the 469 total
            record_refund(paid_order, Decimal("100.00"), source="admin")
        paid_order.refresh_from_db()
        assert paid_order.refunded_amount == Decimal("469.00")
        assert paid_order.refunded_tax == Decimal("19.05"), "reversed more GST than charged"

    def test_same_gateway_reference_is_idempotent(self, paid_order):
        a = record_refund(paid_order, Decimal("469.00"), reference="rfnd_dup")
        b = record_refund(paid_order, Decimal("469.00"), reference="rfnd_dup")
        assert a.pk == b.pk
        paid_order.refresh_from_db()
        assert OrderRefund.objects.filter(order=paid_order).count() == 1
        assert paid_order.refunded_tax == Decimal("19.05")


@pytest.mark.django_db
class TestRefundWebhookReversesGst:
    def _payment(self, order, suffix):
        from payments.models import Payment
        # `payment_id` holds the Razorpay ORDER id (it exists earliest and is
        # unique per order); `razorpay_payment_id` is the captured payment.
        return Payment.objects.create(
            order=order, payment_id=f"order_{suffix}",
            razorpay_payment_id=f"pay_{suffix}",
            payment_gateway="razorpay", amount=order.total_amount, status="completed")

    def test_gateway_refund_records_amount_and_reverses_tax(self, paid_order):
        from payments import services
        self._payment(paid_order, "R1")

        services.mark_payment_refunded(
            razorpay_order_id="order_R1", event_id="evt_r1", source="webhook",
            refund_amount_paise=46900, refund_reference="rfnd_1")

        paid_order.refresh_from_db()
        assert paid_order.refunded_amount == Decimal("469.00")
        assert paid_order.refunded_tax == Decimal("19.05")
        assert paid_order.status == "refunded"

    def test_partial_gateway_refund_reverses_only_its_share(self, paid_order):
        """Razorpay's dashboard can issue a partial even though we never do.
        Record the money truthfully; close nothing."""
        from payments import services
        payment = self._payment(paid_order, "R2")

        services.mark_payment_refunded(
            razorpay_order_id="order_R2", event_id="evt_r2", source="webhook",
            refund_amount_paise=20000, refund_reference="rfnd_2")

        paid_order.refresh_from_db()
        payment.refresh_from_db()
        assert paid_order.refunded_tax == Decimal("9.53")
        # Not fully refunded, so nothing is terminal yet.
        assert paid_order.status == "delivered"
        assert paid_order.payment_status == "paid"
        assert payment.status == "completed"

    def test_partial_gateway_refund_does_not_email_the_customer(self, paid_order, mailoutbox):
        """"Your refund has been processed" is a promise about the whole order."""
        from payments import services
        self._payment(paid_order, "R4")

        services.mark_payment_refunded(
            razorpay_order_id="order_R4", event_id="evt_r4", source="webhook",
            refund_amount_paise=20000, refund_reference="rfnd_4")

        assert not [m for m in mailoutbox if 'refund' in m.subject.lower()]

    def test_missing_amount_is_treated_as_a_full_refund(self, paid_order):
        """Under-reversing GST means over-paying it, so an unsized refund must
        assume the whole order rather than silently reverse nothing."""
        from payments import services
        self._payment(paid_order, "R3")

        services.mark_payment_refunded(
            razorpay_order_id="order_R3", event_id="evt_r3", source="webhook")

        paid_order.refresh_from_db()
        assert paid_order.refunded_tax == Decimal("19.05")


@pytest.mark.django_db
class TestAdminCanRecordARefund:
    def test_setting_status_refunded_reverses_the_gst(self, admin_client, paid_order):
        r = admin_client.patch(f"{URL}{paid_order.id}/",
                               {"status": "refunded"}, format="json")
        assert r.status_code == 200
        paid_order.refresh_from_db()
        assert paid_order.status == "refunded"
        assert paid_order.refunded_tax == Decimal("19.05")

    def test_omitting_the_amount_refunds_the_whole_balance(self, admin_client, paid_order):
        """The amount is optional — a client that never sends it keeps the old
        all-or-nothing behaviour."""
        r = admin_client.patch(f"{URL}{paid_order.id}/",
                               {"status": "refunded"}, format="json")
        assert r.status_code == 200
        paid_order.refresh_from_db()
        assert paid_order.refunded_amount == Decimal("469.00")
        assert paid_order.refunded_tax == Decimal("19.05")

    def test_admin_can_refund_a_partial_amount(self, admin_client, paid_order):
        """An amount the admin typed is a settled outcome: the order moves to
        'refunded' even though money is still held, and `refunded_amount` is what
        says how much actually went back."""
        r = admin_client.patch(
            f"{URL}{paid_order.id}/",
            {"status": "refunded", "refund_amount": "200.00",
             "refund_note": "one jar returned"}, format="json")
        assert r.status_code == 200
        paid_order.refresh_from_db()
        assert paid_order.refunded_amount == Decimal("200.00")
        assert paid_order.refunded_tax == Decimal("9.53"), "pro-rata share of the GST"
        assert paid_order.status == "refunded"
        assert paid_order.refunds.get().note == "one jar returned"

    def test_the_partial_amount_reaches_the_customer_response(self, admin_client, paid_order):
        """The customer is told how much came back — the status alone would read
        as a full refund."""
        r = admin_client.patch(f"{URL}{paid_order.id}/",
                               {"status": "refunded", "refund_amount": "200.00"},
                               format="json")
        assert Decimal(str(r.data["refunded_amount"])) == Decimal("200.00")
        assert Decimal(str(r.data["total"])) == Decimal("469.00")
        assert len(r.data["refunds"]) == 1

    def test_a_second_partial_can_settle_the_balance(self, admin_client, paid_order):
        """Refund in instalments: re-sending an explicit amount on an already
        'refunded' order records a further partial rather than being ignored."""
        for amount in ("200.00", "269.00"):
            r = admin_client.patch(f"{URL}{paid_order.id}/",
                                   {"status": "refunded", "refund_amount": amount},
                                   format="json")
            assert r.status_code == 200
        paid_order.refresh_from_db()
        assert paid_order.refunds.count() == 2
        assert paid_order.refunded_amount == Decimal("469.00")
        assert paid_order.refunded_tax == Decimal("19.05"), "never more than was charged"

    def test_refund_amount_above_the_balance_is_rejected(self, admin_client, paid_order):
        """And rejecting it must leave NOTHING behind — the status write earlier in
        the same transaction has to roll back with it."""
        r = admin_client.patch(f"{URL}{paid_order.id}/",
                               {"status": "refunded", "refund_amount": "500.00"},
                               format="json")
        assert r.status_code == 400
        paid_order.refresh_from_db()
        assert paid_order.refunded_amount == Decimal("0")
        assert paid_order.status == "delivered", "the status change rolled back too"
        assert paid_order.refunds.count() == 0

    @pytest.mark.parametrize("bad", ["abc", "0", "-50"])
    def test_a_nonsense_amount_is_rejected(self, admin_client, paid_order, bad):
        r = admin_client.patch(f"{URL}{paid_order.id}/",
                               {"status": "refunded", "refund_amount": bad},
                               format="json")
        assert r.status_code == 400
        paid_order.refresh_from_db()
        assert paid_order.refunded_amount == Decimal("0")
        assert paid_order.status == "delivered"

    def test_refund_amount_alone_records_nothing(self, admin_client, paid_order):
        """Recording a refund requires saying the order was refunded — an amount
        on its own is not an instruction the API understands any more."""
        r = admin_client.patch(f"{URL}{paid_order.id}/",
                               {"refund_amount": "200.00"}, format="json")
        assert r.status_code == 200
        paid_order.refresh_from_db()
        assert paid_order.refunded_amount == Decimal("0")
        assert paid_order.payment_status == "paid"

    def test_refunding_twice_does_not_double_reverse(self, admin_client, paid_order):
        for _ in range(2):
            admin_client.patch(f"{URL}{paid_order.id}/",
                               {"status": "refunded"}, format="json")
        paid_order.refresh_from_db()
        assert paid_order.refunded_amount == Decimal("469.00")
        assert paid_order.refunded_tax == Decimal("19.05")
        assert paid_order.refunds.count() == 1

    def test_customer_cannot_record_a_refund(self, authenticated_client, paid_order):
        authenticated_client.patch(f"{URL}{paid_order.id}/",
                                   {"status": "refunded"}, format="json")
        paid_order.refresh_from_db()
        assert paid_order.refunded_tax == Decimal("0")


@pytest.fixture
def paid_order_with_stock(db, test_user, test_product):
    """A paid ONLINE order holding 2 units drawn from `test_product`'s size."""
    from orders.models import OrderItem
    from products.models import ProductVariant

    variant = ProductVariant.objects.filter(product=test_product).first()
    order = Order.objects.create(
        user=test_user, shipping_address="1 Rd", phone_number="1234567890",
        payment_method="ONLINE", payment_status="paid", status="delivered",
        subtotal=Decimal("400.00"), tax=Decimal("19.05"),
        shipping_charge=Decimal("69.00"), total_amount=Decimal("469.00"))
    OrderItem.objects.create(
        order=order, product=test_product, variant=variant, item_type="product",
        product_name=test_product.name, quantity=2,
        price=Decimal("200.00"), final_price=Decimal("400.00"))
    return order


@pytest.mark.django_db
class TestRefundReturnsTheGoodsToStock:
    """Money going back means the goods came back. Without this every return
    silently ratchets stock down and the catalogue over-promises."""

    def _stock(self, order):
        from products.models import ProductVariant
        return ProductVariant.objects.get(
            pk=order.items.get().variant_id).stock

    def test_a_refund_restocks_the_order(self, paid_order_with_stock):
        before = self._stock(paid_order_with_stock)
        record_refund(paid_order_with_stock, Decimal("469.00"), source="admin")
        assert self._stock(paid_order_with_stock) == before + 2

    def test_a_second_instalment_does_not_restock_again(self, paid_order_with_stock):
        """The goods came back once; two refunds against them are still one
        return. Crediting twice would invent stock that never existed."""
        before = self._stock(paid_order_with_stock)
        record_refund(paid_order_with_stock, Decimal("200.00"), source="admin")
        record_refund(paid_order_with_stock, Decimal("269.00"), source="admin")
        assert self._stock(paid_order_with_stock) == before + 2

    def test_refunding_an_already_cancelled_order_does_not_restock_twice(
            self, admin_client, paid_order_with_stock):
        """Cancel restocks; the refund that follows must not credit the same
        units a second time."""
        from orders.views import restore_order_stock

        before = self._stock(paid_order_with_stock)
        restore_order_stock(paid_order_with_stock)      # what cancel does
        assert self._stock(paid_order_with_stock) == before + 2

        record_refund(paid_order_with_stock, Decimal("469.00"), source="admin")
        assert self._stock(paid_order_with_stock) == before + 2

    def test_the_admin_patch_path_restocks_too(self, admin_client, paid_order_with_stock):
        before = self._stock(paid_order_with_stock)
        r = admin_client.patch(f"{URL}{paid_order_with_stock.id}/",
                               {"status": "refunded"}, format="json")
        assert r.status_code == 200
        assert self._stock(paid_order_with_stock) == before + 2


@pytest.mark.django_db
class TestOnlyOnlinePaidOrdersCanBeRefunded:
    """A ledger row reverses GST. Writing one for money we never took understates
    what is owed to the government, so eligibility is checked before anything."""

    def _order(self, user, **kw):
        defaults = dict(
            user=user, shipping_address="1 Rd", phone_number="1234567890",
            payment_method="ONLINE", payment_status="paid", status="delivered",
            subtotal=Decimal("400.00"), tax=Decimal("19.05"),
            shipping_charge=Decimal("69.00"), total_amount=Decimal("469.00"))
        defaults.update(kw)
        return Order.objects.create(**defaults)

    def test_a_cod_order_cannot_be_refunded(self, admin_client, test_user):
        """The cash never passed through us — there is nothing here to give back."""
        order = self._order(test_user, payment_method="COD")
        r = admin_client.patch(f"{URL}{order.id}/",
                               {"status": "refunded"}, format="json")
        assert r.status_code == 400
        order.refresh_from_db()
        assert order.status == "delivered", "the status must not move either"
        assert order.refunds.count() == 0

    @pytest.mark.parametrize("payment_status", ["pending", "failed", "rejected"])
    def test_an_unpaid_online_order_cannot_be_refunded(
            self, admin_client, test_user, payment_status):
        order = self._order(test_user, payment_status=payment_status, status="pending")
        r = admin_client.patch(f"{URL}{order.id}/",
                               {"status": "refunded"}, format="json")
        assert r.status_code == 400
        order.refresh_from_db()
        assert order.refunded_tax == Decimal("0")

    def test_an_order_with_nothing_left_is_rejected_rather_than_flagged(
            self, admin_client, paid_order):
        """Accepting this used to leave the order reading 'refunded' with an empty
        ledger — a refund that shows on every screen but never happened."""
        record_refund(paid_order, Decimal("469.00"), source="admin")
        r = admin_client.patch(f"{URL}{paid_order.id}/",
                               {"status": "refunded", "refund_amount": "10.00"},
                               format="json")
        assert r.status_code == 400
        paid_order.refresh_from_db()
        assert paid_order.refunds.count() == 1

    def test_an_instalment_on_a_refunded_order_still_works(self, admin_client, paid_order):
        """payment_status is 'refunded' by then — the gate must not strand the
        outstanding balance."""
        admin_client.patch(f"{URL}{paid_order.id}/",
                           {"status": "refunded", "refund_amount": "200.00"},
                           format="json")
        r = admin_client.patch(f"{URL}{paid_order.id}/",
                               {"status": "refunded", "refund_amount": "269.00"},
                               format="json")
        assert r.status_code == 200
        paid_order.refresh_from_db()
        assert paid_order.refunded_amount == Decimal("469.00")


@pytest.mark.django_db
class TestCreditNote:
    """The paperwork behind the reversal: a serial, a date, an invoice reference.

    The ledger already reduces the tax correctly; these pin the document that
    evidences it, and the disclosure that stops a refunded order printing a clean
    full-value bill.
    """

    def test_the_number_is_stable_across_reprints(self, paid_order):
        """A serial that moved between prints would be worse than none — the
        customer's copy and ours would cite different documents."""
        from orders.invoice import credit_note_number

        refund = record_refund(paid_order, Decimal("469.00"), source="admin")
        assert credit_note_number(refund) == f"CN-{refund.id:06d}"
        assert credit_note_number(OrderRefund.objects.get(pk=refund.pk)) \
            == credit_note_number(refund)

    def test_each_instalment_gets_its_own_number(self, paid_order):
        from orders.invoice import credit_note_number

        first = record_refund(paid_order, Decimal("200.00"), source="admin")
        second = record_refund(paid_order, Decimal("269.00"), source="admin")
        assert credit_note_number(first) != credit_note_number(second)

    def test_slabs_sum_to_the_tax_actually_reversed(self, paid_order):
        """A credit note whose rate-wise rows disagree with its own total is not
        evidence of anything."""
        from orders.invoice import credit_note_tax_rows

        refund = record_refund(paid_order, Decimal("200.00"), source="admin")
        rows = credit_note_tax_rows(refund)
        assert rows
        assert sum(Decimal(str(r["tax_amount"])) for r in rows) == refund.tax_amount

    def test_a_full_refund_reverses_the_whole_invoice_gst(self, paid_order):
        from orders.invoice import credit_note_tax_rows

        refund = record_refund(paid_order, Decimal("469.00"), source="admin")
        rows = credit_note_tax_rows(refund)
        assert sum(Decimal(str(r["tax_amount"])) for r in rows) == Decimal("19.05")

    def test_the_number_reaches_the_order_response(self, authenticated_client, paid_order):
        refund = record_refund(paid_order, Decimal("469.00"), source="admin")
        body = authenticated_client.get(f"{URL}{paid_order.id}/").json()
        assert body["refunds"][0]["credit_note_number"] == f"CN-{refund.id:06d}"

    def test_the_owner_can_download_the_credit_note(self, authenticated_client, paid_order):
        record_refund(paid_order, Decimal("469.00"), source="admin")
        r = authenticated_client.get(f"{URL}{paid_order.id}/credit-note/")
        assert r.status_code == 200
        assert r["Content-Type"] == "application/pdf"
        assert b"%PDF" in r.content[:8]

    def test_a_specific_instalment_can_be_requested(self, authenticated_client, paid_order):
        first = record_refund(paid_order, Decimal("200.00"), source="admin")
        record_refund(paid_order, Decimal("269.00"), source="admin")
        r = authenticated_client.get(
            f"{URL}{paid_order.id}/credit-note/?refund={first.id}")
        assert r.status_code == 200
        assert f"CN-{first.id:06d}" in r["Content-Disposition"]

    def test_an_unrefunded_order_has_no_credit_note(self, authenticated_client, paid_order):
        r = authenticated_client.get(f"{URL}{paid_order.id}/credit-note/")
        assert r.status_code == 404

    def test_a_stranger_cannot_download_it(self, authenticated_client_user2, paid_order):
        """Someone else's refund is someone else's money."""
        record_refund(paid_order, Decimal("469.00"), source="admin")
        r = authenticated_client_user2.get(f"{URL}{paid_order.id}/credit-note/")
        assert r.status_code in (403, 404)

    def test_a_refund_from_another_order_is_not_reachable(
            self, authenticated_client, paid_order, test_user):
        """The refund id is resolved WITHIN the order, so a guessed id from an
        unrelated order renders nothing."""
        other = Order.objects.create(
            user=test_user, shipping_address="2 Rd", phone_number="1",
            payment_method="ONLINE", payment_status="paid", status="delivered",
            subtotal=Decimal("400.00"), tax=Decimal("19.05"),
            total_amount=Decimal("400.00"))
        stray = record_refund(other, Decimal("400.00"), source="admin")
        r = authenticated_client.get(
            f"{URL}{paid_order.id}/credit-note/?refund={stray.id}")
        assert r.status_code == 404

    def test_the_invoice_discloses_the_refund(self, paid_order):
        """The invoice keeps its original amounts — it is never rewritten — but
        it must not read as if the money was kept."""
        from orders.invoice import generate_invoice_pdf

        from orders.invoicing import issue_invoice
        invoice, _ = issue_invoice(paid_order)
        before = generate_invoice_pdf(invoice)
        record_refund(paid_order, Decimal("469.00"), source="admin")
        paid_order.refresh_from_db()
        after = generate_invoice_pdf(invoice)
        assert after != before, "a refunded order printed an unchanged bill"


@pytest.mark.django_db
class TestReportingNetsOffRefunds:
    def test_rollup_books_the_refund_on_the_day_it_happened(self, paid_order):
        """Not on the day of the sale — an earlier month may already be filed."""
        record_refund(paid_order, Decimal("469.00"), source="admin")
        call_command("rollup_analytics")

        row = DailySalesRollup.objects.get(date=timezone.localdate())
        assert row.gst_refunded == Decimal("19.05")
        assert row.refunds == Decimal("469.00")
        assert row.net_gst_collected == row.gst_collected - Decimal("19.05")

    def test_dashboard_reports_gst_collected_net_of_refunds(self, admin_client, test_user):
        from django.core.cache import cache

        order = Order.objects.create(
            user=test_user, shipping_address="1 Rd", phone_number="1",
            payment_method="ONLINE", payment_status="paid", status="delivered",
            subtotal=Decimal("400.00"), tax=Decimal("19.05"),
            shipping_charge=Decimal("69.00"), total_amount=Decimal("469.00"))
        record_refund(order, Decimal("200.00"), source="admin")
        cache.clear()

        d = admin_client.get("/api/dashboard/actions/").json()
        assert Decimal(d["today_gst_refunded"]) == Decimal("9.53")
        assert (Decimal(d["today_gst_net_collected"])
                == Decimal(d["today_gst_collected"]) - Decimal("9.53"))
        assert Decimal(d["today_refunds"]) == Decimal("200.00")
        # Sold-value beside tax-collected: the pair the owner reads together.
        assert (Decimal(d["today_taxable_sales"])
                == Decimal(d["today_revenue"]) - Decimal(d["today_gst_collected"]))

    def test_insights_reports_net_gst_collected(self, paid_order):
        from analytics import insights

        record_refund(paid_order, Decimal("469.00"), source="admin")
        call_command("rollup_analytics")

        today = timezone.localdate()
        k = insights.sales(today - timedelta(days=1), today)["kpis"]
        assert k["gst_refunded"] == 19.05
        assert k["net_gst_collected"] == round(k["gst_collected"] - 19.05, 2)
        assert k["taxable_sales"] == round(k["revenue"] - k["gst_collected"], 2)
