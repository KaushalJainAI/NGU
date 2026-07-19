"""Tests for the admin-panel features added in the management overhaul:
dashboard action-inbox, corrected active-coupon count, global search, the
admin customer directory + CSV export, and the on-demand report trigger.
"""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from admin_panel.models import Coupon
from orders.models import Order


# --------------------------------------------------------------------------- #
# Dashboard: corrected "active coupons" count
# --------------------------------------------------------------------------- #

@pytest.mark.django_db
class TestDashboardActiveCoupons:
    def test_only_redeemable_coupons_counted(self, admin_client):
        # A data migration seeds a coupon (e.g. SAVE10); start from a clean slate
        # so the absolute count is deterministic.
        Coupon.objects.all().delete()
        now = timezone.now()
        Coupon.objects.create(code='LIVE', discount_percent=10, is_active=True,
                              valid_until=now + timedelta(days=5))
        Coupon.objects.create(code='NOEXPIRY', discount_percent=10, is_active=True)
        Coupon.objects.create(code='OFF', discount_percent=10, is_active=False)
        Coupon.objects.create(code='EXPIRED', discount_percent=10, is_active=True,
                              valid_until=now - timedelta(days=1))
        Coupon.objects.create(code='USEDUP', discount_percent=10, is_active=True,
                              max_usage=2, usage_count=2)

        resp = admin_client.get('/api/dashboard/')
        assert resp.status_code == 200
        # LIVE + NOEXPIRY are redeemable; OFF/EXPIRED/USEDUP are not.
        assert resp.data['activeCoupons'] == 2


# --------------------------------------------------------------------------- #
# Dashboard: "Today" action inbox
# --------------------------------------------------------------------------- #

@pytest.mark.django_db
class TestDashboardActions:
    def test_counts_confirmable_and_low_stock(self, admin_client, test_user,
                                              test_product, out_of_stock_product):
        # A COD pending order is confirmable; low_stock_threshold default is 5.
        Order.objects.create(
            user=test_user, shipping_address='x', phone_number='1',
            payment_method='COD', subtotal=Decimal('10'), total_amount=Decimal('10'),
            status='pending',
        )
        test_product.stock = 3          # at/below threshold 5 → low stock
        test_product.save(update_fields=['stock'])

        resp = admin_client.get('/api/dashboard/actions/')
        assert resp.status_code == 200
        assert resp.data['orders_to_confirm'] == 1
        # test_product (3) is low; out_of_stock_product (0) is also <= threshold.
        assert resp.data['low_stock_count'] >= 1
        names = [i['name'] for i in resp.data['low_stock_items']]
        assert test_product.name in names

    def test_online_unpaid_pending_is_not_confirmable(self, admin_client, test_user):
        Order.objects.create(
            user=test_user, shipping_address='x', phone_number='1',
            payment_method='ONLINE', payment_status='pending',
            subtotal=Decimal('10'), total_amount=Decimal('10'), status='pending',
        )
        resp = admin_client.get('/api/dashboard/actions/')
        assert resp.data['orders_to_confirm'] == 0

    def test_requires_staff(self, authenticated_client):
        resp = authenticated_client.get('/api/dashboard/actions/')
        assert resp.status_code == 403


# --------------------------------------------------------------------------- #
# Global admin search
# --------------------------------------------------------------------------- #

@pytest.mark.django_db
class TestGlobalAdminSearch:
    def test_finds_product_and_customer(self, admin_client, test_user, test_product):
        resp = admin_client.get('/api/admin-search/', {'q': 'Turmeric'})
        assert resp.status_code == 200
        assert any(p['name'] == test_product.name for p in resp.data['products'])

    def test_finds_order_by_number_digits(self, admin_client, test_order):
        # Search by the full order number; the view pulls the digits and matches
        # the id. (A bare "1" is below the 2-char minimum by design.)
        resp = admin_client.get('/api/admin-search/', {'q': f'ORD-{test_order.id:06d}'})
        assert resp.status_code == 200
        numbers = [o['order_number'] for o in resp.data['orders']]
        assert f'ORD-{test_order.id:06d}' in numbers

    def test_short_query_returns_empty(self, admin_client, test_product):
        resp = admin_client.get('/api/admin-search/', {'q': 'a'})
        assert resp.status_code == 200
        assert resp.data['products'] == [] and resp.data['orders'] == []

    def test_requires_staff(self, authenticated_client):
        resp = authenticated_client.get('/api/admin-search/', {'q': 'test'})
        assert resp.status_code == 403


# --------------------------------------------------------------------------- #
# Admin customer directory
# --------------------------------------------------------------------------- #

@pytest.mark.django_db
class TestAdminCustomers:
    def test_list_includes_order_totals(self, admin_client, test_order, test_user):
        resp = admin_client.get('/api/admin-customers/')
        assert resp.status_code == 200
        row = next(r for r in resp.data['results'] if r['email'] == test_user.email)
        assert row['order_count'] == 1
        assert Decimal(row['total_spent']) == test_order.total_amount

    def test_cancelled_orders_excluded_from_spend(self, admin_client, test_user, test_order):
        test_order.status = 'cancelled'
        test_order.save(update_fields=['status'])
        resp = admin_client.get('/api/admin-customers/')
        row = next(r for r in resp.data['results'] if r['email'] == test_user.email)
        assert row['order_count'] == 0
        assert Decimal(row['total_spent']) == 0

    def test_search_by_email(self, admin_client, test_user):
        resp = admin_client.get('/api/admin-customers/', {'search': test_user.email})
        assert resp.status_code == 200
        assert any(r['email'] == test_user.email for r in resp.data['results'])

    def test_detail_returns_order_history(self, admin_client, test_user, test_order):
        resp = admin_client.get(f'/api/admin-customers/{test_user.id}/')
        assert resp.status_code == 200
        assert resp.data['order_count'] == 1
        assert len(resp.data['orders']) == 1
        assert resp.data['orders'][0]['order_number'] == f'ORD-{test_order.id:06d}'

    def test_requires_staff(self, authenticated_client):
        resp = authenticated_client.get('/api/admin-customers/')
        assert resp.status_code == 403

    def test_csv_export(self, admin_client, test_user, test_order):
        resp = admin_client.get('/api/admin-customers/export/')
        assert resp.status_code == 200
        assert resp['Content-Type'].startswith('text/csv')
        body = b''.join(resp.streaming_content).decode('utf-8-sig')
        assert 'Total Spent' in body
        assert test_user.email in body


# --------------------------------------------------------------------------- #
# CSV export: formula-injection neutralisation
# --------------------------------------------------------------------------- #

class TestCsvFormulaInjection:
    def test_formula_cells_are_escaped(self):
        from admin_panel.utils import _csv_safe
        # Anything a spreadsheet would evaluate gets a leading quote.
        assert _csv_safe('=HYPERLINK("http://evil","x")') == "'=HYPERLINK(\"http://evil\",\"x\")"
        assert _csv_safe('+1+1') == "'+1+1"
        assert _csv_safe('-2') == "'-2"
        assert _csv_safe('@SUM(A1)') == "'@SUM(A1)"
        assert _csv_safe('\tTAB') == "'\tTAB"

    def test_ordinary_values_untouched(self):
        from admin_panel.utils import _csv_safe
        assert _csv_safe('Garam Masala') == 'Garam Masala'
        assert _csv_safe('9998887776') == '9998887776'
        assert _csv_safe(264) == '264'
        assert _csv_safe(None) == ''

    @pytest.mark.django_db
    def test_export_escapes_malicious_customer_name(self, admin_client, django_user_model):
        # A customer whose name is a formula must not produce a live formula cell.
        django_user_model.objects.create_user(
            username='evil', email='evil@shop.test', password='TestPass123!',
            first_name='=cmd|calc', last_name='')
        resp = admin_client.get('/api/admin-customers/export/')
        body = b''.join(resp.streaming_content).decode('utf-8-sig')
        assert "'=cmd|calc" in body           # neutralised (leading quote)…
        # …and the formula never begins a cell (start of file or after a comma).
        assert '\n=cmd|calc' not in body and ',=cmd|calc' not in body
        assert not body.lstrip('﻿').startswith('=cmd|calc')
