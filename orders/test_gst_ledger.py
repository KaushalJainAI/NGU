"""GST on the invoice basis + real credit notes (WP6)."""
from datetime import date, timedelta
from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command
from django.utils import timezone

from cart.models import Cart, CartItem
from conftest import create_test_image
from orders.gst_ledger import (
    b2c_by_state, credit_notes_in, documents_issued, invoices_in, period_summary,
)
from orders.gst_reports import hsn_summary
from orders.invoicing import issue_invoice
from orders.models import CreditNote, Invoice, Order
from orders.refunds import record_refund
from products.models import Product
from spices_backend.timeranges import day_start

URL = "/api/orders/"
ADDR = {"shipping_address": "1 Rd", "phone_number": "1234567890", "payment_method": "COD"}


def _product(category, name="Haldi", price="105.00", rate="5", hsn="09103030"):
    return Product.objects.create(
        name=name, category=category, description="x", price=Decimal(price),
        stock=50, weight=Decimal("250"), unit="g", spice_form="powder",
        is_active=True, tax_rate=Decimal(rate), hsn_code=hsn,
        image=create_test_image(f"{name}.jpg"))


def _order_via_checkout(client, user, product, quantity=1):
    cart, _ = Cart.objects.get_or_create(user=user)
    cart.items.all().delete()
    CartItem.objects.create(cart=cart, item_type="product",
                            quantity=quantity, product=product)
    r = client.post(URL, ADDR, format="json")
    assert r.status_code == 201, r.data
    return Order.objects.latest("id")


def _at(day):
    return day_start(day) + timedelta(hours=5)


@pytest.mark.django_db
class TestInvoiceBasis:
    def test_order_invoiced_next_month_reported_there(
            self, authenticated_client, test_user, test_category):
        product = _product(test_category)
        order = _order_via_checkout(authenticated_client, test_user, product)
        Order.objects.filter(pk=order.pk).update(created_at=_at(date(2025, 8, 30)))
        order.refresh_from_db()
        issue_invoice(order, when=_at(date(2025, 9, 2)))

        aug = period_summary(date(2025, 8, 1), date(2025, 8, 31))
        sep = period_summary(date(2025, 9, 1), date(2025, 9, 30))
        assert aug['invoices']['count'] == 0
        assert sep['invoices']['count'] == 1
        assert hsn_summary(date(2025, 8, 1), date(2025, 8, 31))['order_count'] == 0
        assert hsn_summary(date(2025, 9, 1), date(2025, 9, 30))['order_count'] == 1

    def test_paid_order_without_invoice_in_no_report(
            self, authenticated_client, test_user, test_category):
        product = _product(test_category)
        order = _order_via_checkout(authenticated_client, test_user, product)
        order.payment_status = 'paid'
        order.save(update_fields=['payment_status'])
        today = timezone.localdate()
        data = period_summary(today, today)
        assert data['invoices']['count'] == 0
        assert hsn_summary(today, today)['order_count'] == 0


@pytest.mark.django_db
class TestCancellationCreditNotes:
    def test_cancel_unpaid_invoiced_cod_creates_one_full_note(
            self, authenticated_client, test_user, test_category):
        product = _product(test_category)
        order = _order_via_checkout(authenticated_client, test_user, product)
        issue_invoice(order)
        order.status = 'cancelled'
        order.save(update_fields=['status'])
        from orders.credit_notes import issue_credit_note_for_cancellation
        note = issue_credit_note_for_cancellation(order)
        assert note is not None and note.reason == 'cancellation'
        assert note.total_amount == order.total_amount
        assert issue_credit_note_for_cancellation(order) is None
        assert CreditNote.objects.filter(order=order, reason='cancellation').count() == 1

    def test_cancel_paid_creates_none_refund_creates_one(
            self, authenticated_client, test_user, test_category):
        product = _product(test_category)
        order = _order_via_checkout(authenticated_client, test_user, product)
        order.payment_status = 'paid'
        order.save(update_fields=['payment_status'])
        issue_invoice(order)
        order.status = 'cancelled'
        order.save(update_fields=['status'])
        from orders.credit_notes import issue_credit_note_for_cancellation
        assert issue_credit_note_for_cancellation(order) is None
        refund = record_refund(order, order.total_amount, source='admin', mark_refunded=True)
        assert refund is not None
        note = CreditNote.objects.filter(refund=refund).first()
        assert note is not None and note.reason == 'refund'


@pytest.mark.django_db
class TestCreditNoteNumbering:
    def test_numbers_are_continuous(self, authenticated_client, test_user, test_category):
        from orders.invoicing import financial_year_label
        product = _product(test_category)
        o1 = _order_via_checkout(authenticated_client, test_user, product)
        o1.payment_status = 'paid'
        o1.save(update_fields=['payment_status'])
        issue_invoice(o1)
        r1 = record_refund(o1, o1.total_amount, source='admin', mark_refunded=True)
        o2 = _order_via_checkout(authenticated_client, test_user, product)
        o2.payment_status = 'paid'
        o2.save(update_fields=['payment_status'])
        issue_invoice(o2)
        r2 = record_refund(o2, o2.total_amount, source='admin', mark_refunded=True)
        n1 = CreditNote.objects.get(refund=r1)
        n2 = CreditNote.objects.get(refund=r2)
        assert n1.number.startswith('CN/')
        assert n2.sequence == n1.sequence + 1
        assert n1.series == f"CN/{financial_year_label(r1.created_at)}"


@pytest.mark.django_db
class TestLedgerArithmetic:
    def test_net_is_invoices_minus_notes_and_heads_add_up(
            self, authenticated_client, test_user, test_category):
        product = _product(test_category)
        order = _order_via_checkout(authenticated_client, test_user, product)
        order.payment_status = 'paid'
        order.save(update_fields=['payment_status'])
        issue_invoice(order)
        record_refund(order, order.total_amount, source='admin', mark_refunded=True)
        today = timezone.localdate()
        data = period_summary(today - timedelta(days=1), today + timedelta(days=1))
        for block in ('invoices', 'credit_notes', 'net'):
            b = data[block]
            assert (b['cgst'] + b['sgst'] + b['igst']).quantize(Decimal('0.01')) == b['tax'].quantize(Decimal('0.01'))
        for key in ('taxable_value', 'cgst', 'sgst', 'igst', 'tax', 'total'):
            assert data['net'][key] == data['invoices'][key] - data['credit_notes'][key]

    def test_interstate_vs_intrastate_heads(
            self, authenticated_client, test_user, test_category):
        product = _product(test_category)
        intra = _order_via_checkout(authenticated_client, test_user, product)
        intra.place_of_supply_state_code = '23'
        intra.save(update_fields=['place_of_supply_state_code'])
        issue_invoice(intra)
        inter = _order_via_checkout(authenticated_client, test_user, product)
        inter.place_of_supply_state_code = '27'
        inter.save(update_fields=['place_of_supply_state_code'])
        issue_invoice(inter)
        today = timezone.localdate()
        rows = b2c_by_state(today - timedelta(days=1), today + timedelta(days=1))
        intra_rows = [r for r in rows if r['state_code'] == '23']
        inter_rows = [r for r in rows if r['state_code'] == '27']
        assert intra_rows and (intra_rows[0]['gross_cgst'] + intra_rows[0]['gross_sgst']) > 0
        assert intra_rows[0]['gross_igst'] == 0
        assert inter_rows and inter_rows[0]['gross_igst'] > 0
        assert inter_rows[0]['gross_cgst'] == 0 and inter_rows[0]['gross_sgst'] == 0

    def test_documents_gap_zero(self, authenticated_client, test_user, test_category):
        product = _product(test_category)
        for _ in range(2):
            order = _order_via_checkout(authenticated_client, test_user, product)
            order.payment_status = 'paid'
            order.save(update_fields=['payment_status'])
            issue_invoice(order)
        today = timezone.localdate()
        docs = documents_issued(today - timedelta(days=1), today + timedelta(days=1))
        assert docs['invoices'] and all(r['gap'] == 0 for r in docs['invoices'])


@pytest.mark.django_db
class TestGuards:
    def test_change_place_of_supply_after_invoice_400(
            self, admin_client, test_admin, test_category):
        product = _product(test_category)
        order = _order_via_checkout(admin_client, test_admin, product)
        issue_invoice(order)
        r = admin_client.patch(f"{URL}{order.id}/",
                               {'place_of_supply_state_code': '27'}, format='json')
        assert r.status_code == 400

    def test_backfill_dry_run_writes_nothing(
            self, authenticated_client, test_user, test_category):
        from orders.models import OrderRefund
        product = _product(test_category)
        order = _order_via_checkout(authenticated_client, test_user, product)
        order.payment_status = 'paid'
        order.save(update_fields=['payment_status'])
        invoice = issue_invoice(order)[0]
        refund = OrderRefund.objects.create(order=order, amount=order.total_amount,
                                            tax_amount=order.total_tax, source='admin')
        before = CreditNote.objects.count()
        out = StringIO()
        call_command('backfill_credit_notes', '--dry-run', stdout=out)
        assert CreditNote.objects.count() == before
        # And the real run picks it up.
        call_command('backfill_credit_notes', stdout=StringIO())
        assert CreditNote.objects.filter(refund=refund).exists()
        assert CreditNote.objects.get(refund=refund).invoice_id == invoice.pk
