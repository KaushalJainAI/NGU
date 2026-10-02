"""Basic accounts: expenses + monthly summary (WP7)."""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from admin_panel.books import monthly_summary
from admin_panel.models import Expense
from cart.models import Cart, CartItem
from conftest import create_test_image
from orders.invoicing import issue_invoice
from orders.models import Order
from orders.refunds import record_refund
from payments.models import Payment
from products.models import Product

URL = "/api/orders/"
ADDR = {"shipping_address": "1 Rd", "phone_number": "1234567890", "payment_method": "COD"}


def _product(category, name="Haldi", price="105.00"):
    return Product.objects.create(
        name=name, category=category, description="x", price=Decimal(price),
        stock=50, weight=Decimal("250"), unit="g", spice_form="powder",
        is_active=True, image=create_test_image(f"{name}.jpg"))


@pytest.mark.django_db
class TestExpenseApi:
    def test_non_staff_403_on_both_routes(self, authenticated_client):
        assert authenticated_client.get('/api/expenses/').status_code == 403
        assert authenticated_client.get('/api/admin/books/summary/').status_code == 403

    def test_gst_above_amount_rejected(self, admin_client):
        today = timezone.localdate().isoformat()
        r = admin_client.post('/api/expenses/', {
            'date': today, 'category': 'other', 'amount': '100.00',
            'gst_amount': '118.00',
        }, format='json')
        assert r.status_code == 400

    def test_itc_requires_gst(self, admin_client):
        today = timezone.localdate().isoformat()
        r = admin_client.post('/api/expenses/', {
            'date': today, 'category': 'other', 'amount': '100.00',
            'gst_amount': '0.00', 'itc_eligible': True,
        }, format='json')
        assert r.status_code == 400

    def test_itc_cost_counts_net_otherwise_gross(self, admin_client):
        today = timezone.localdate().isoformat()
        r = admin_client.post('/api/expenses/', {
            'date': today, 'category': 'packaging', 'amount': '118.00',
            'gst_amount': '18.00', 'itc_eligible': True,
        }, format='json')
        assert r.status_code == 201
        data = admin_client.get('/api/admin/books/summary/').json()
        packaging = next(c for c in data['costs']['expenses_by_category']
                         if c['category'] == 'packaging')
        assert packaging['cost'] == '100.00'

        exp = Expense.objects.latest('id')
        exp.itc_eligible = False
        exp.save(update_fields=['itc_eligible'])
        data = admin_client.get('/api/admin/books/summary/').json()
        packaging = next(c for c in data['costs']['expenses_by_category']
                         if c['category'] == 'packaging')
        assert packaging['cost'] == '118.00'

    def test_outside_range_excluded(self, admin_client):
        old = (timezone.localdate() - timedelta(days=60)).isoformat()
        r = admin_client.post('/api/expenses/', {
            'date': old, 'category': 'other', 'amount': '50.00',
        }, format='json')
        assert r.status_code == 201
        data = admin_client.get('/api/admin/books/summary/').json()
        assert all(c['category'] != 'other' or c['cost'] == '0.00'
                   for c in data['costs']['expenses_by_category'])
        assert data['costs']['expenses_total'] == '0.00'


@pytest.mark.django_db
class TestSummaryMath:
    def test_hand_worked_example(self, authenticated_client, test_user, test_category):
        """One invoice + one credit note + one expense + one gateway fee."""
        from django.utils import timezone as tz
        product = _product(test_category)
        cart, _ = Cart.objects.get_or_create(user=test_user)
        cart.items.all().delete()
        CartItem.objects.create(cart=cart, item_type="product", quantity=1, product=product)
        r = authenticated_client.post(URL, ADDR, format="json")
        assert r.status_code == 201, r.data
        order = Order.objects.latest("id")
        order.payment_method = 'ONLINE'
        order.payment_status = 'paid'
        order.save(update_fields=['payment_method', 'payment_status'])
        issue_invoice(order)
        Payment.objects.create(order=order, payment_id='pay_handworked',
                               payment_gateway='razorpay', amount=order.total_amount,
                               status='completed', gateway_fee=Decimal('5.90'),
                               gateway_tax=Decimal('0.90'))
        record_refund(order, Decimal('10.00'), source='admin', mark_refunded=True)
        today = tz.localdate()
        Expense.objects.create(date=today, category='packaging', amount=Decimal('118.00'),
                               gst_amount=Decimal('18.00'), itc_eligible=True)

        data = monthly_summary(today.replace(day=1), today)
        assert data['is_estimate'] is True
        # Profit = net ex-GST sales − gateway ex-GST − courier − expenses(net).
        profit = (Decimal(data['sales']['net_sales_ex_gst'])
                  - Decimal(data['costs']['gateway_fees_ex_gst'])
                  - Decimal(data['costs']['courier_cost'])
                  - Decimal(data['costs']['expenses_total']))
        assert Decimal(data['profit']['estimated_profit']) == profit
        gst = data['gst']
        assert Decimal(gst['estimated_net_gst']) == (
            Decimal(gst['output_tax']) - Decimal(gst['credit_note_tax'])
            - Decimal(gst['input_tax_expenses']) - Decimal(gst['input_tax_gateway']))
        assert data['costs']['gateway_fee_coverage'] == {'recorded': 1, 'total': 1}
