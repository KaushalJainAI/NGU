"""Tests for the admin order features added in the overhaul: the date-range
filter, the filtered CSV export, and the packing-slip PDF endpoint.
"""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from orders.models import Order, OrderItem


def _make_order(user, product, status='pending', payment='COD'):
    order = Order.objects.create(
        user=user, shipping_address='123 Test St, City', phone_number='9998887776',
        payment_method=payment, subtotal=Decimal('240.00'), tax=Decimal('24.00'),
        total_amount=Decimal('264.00'), status=status,
    )
    OrderItem.objects.create(
        order=order, product=product, item_type='product',
        product_name=product.name, product_weight=str(product.weight),
        quantity=2, price=product.final_price, final_price=product.final_price * 2,
    )
    return order


@pytest.mark.django_db
class TestOrderDateFilter:
    def test_date_range_filters_orders(self, admin_client, test_user, test_product):
        old = _make_order(test_user, test_product)
        Order.objects.filter(pk=old.pk).update(
            created_at=timezone.now() - timedelta(days=30))
        recent = _make_order(test_user, test_product)

        today = timezone.now().date()
        frm = (today - timedelta(days=7)).isoformat()
        resp = admin_client.get('/api/orders/', {'date_from': frm, 'date_to': today.isoformat()})
        assert resp.status_code == 200
        ids = [o['id'] for o in resp.data['results']]
        assert recent.id in ids
        assert old.id not in ids

    def test_bad_date_is_ignored_not_500(self, admin_client, test_user, test_product):
        _make_order(test_user, test_product)
        resp = admin_client.get('/api/orders/', {'date_from': 'not-a-date'})
        assert resp.status_code == 200  # unparseable filter ignored


@pytest.mark.django_db
class TestOrderCsvExport:
    def test_export_returns_csv_with_gst_columns(self, admin_client, test_user, test_product):
        _make_order(test_user, test_product)
        resp = admin_client.get('/api/orders/', {'export': 'csv'})
        assert resp.status_code == 200
        assert resp['Content-Type'].startswith('text/csv')
        body = b''.join(resp.streaming_content).decode('utf-8-sig')
        header = body.splitlines()[0]
        assert 'GST' in header and 'Taxable Amount' in header
        assert 'ORD-' in body

    def test_export_respects_status_filter(self, admin_client, test_user, test_product):
        _make_order(test_user, test_product, status='pending')
        _make_order(test_user, test_product, status='delivered')
        resp = admin_client.get('/api/orders/', {'export': 'csv', 'status': 'delivered'})
        body = b''.join(resp.streaming_content).decode('utf-8-sig')
        # Header + exactly one data row (the delivered order).
        data_rows = [ln for ln in body.splitlines()[1:] if ln.strip()]
        assert len(data_rows) == 1
        assert 'delivered' in data_rows[0]

    def test_export_requires_staff(self, authenticated_client, test_user, test_product):
        _make_order(test_user, test_product)
        resp = authenticated_client.get('/api/orders/', {'export': 'csv'})
        # A normal user's order list is a plain array (never the CSV export).
        assert resp.status_code == 200
        assert resp['Content-Type'].startswith('application/json')


@pytest.mark.django_db
class TestPackingSlip:
    def test_staff_gets_pdf(self, admin_client, test_user, test_product):
        order = _make_order(test_user, test_product)
        resp = admin_client.get(f'/api/orders/{order.id}/packing-slip/')
        assert resp.status_code == 200
        assert resp['Content-Type'] == 'application/pdf'
        assert resp.content[:4] == b'%PDF'

    def test_customer_cannot_download_packing_slip(self, authenticated_client, test_user, test_product):
        order = _make_order(test_user, test_product)
        resp = authenticated_client.get(f'/api/orders/{order.id}/packing-slip/')
        assert resp.status_code == 403
