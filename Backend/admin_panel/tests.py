"""
Comprehensive tests for the Admin Panel app.
Covers dashboard, coupons, policies, superuser authorization, admin features, and store-owner emails.
"""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.management import call_command
from django.utils import timezone
from rest_framework import status

from admin_panel.models import Coupon, Policy
from orders.models import Order, OrderItem
from products.models import default_variant_for


# ==================== DASHBOARD TESTS ====================

@pytest.mark.django_db
class TestDashboard:
    """Tests for dashboard endpoint."""
    
    base_url = '/api/dashboard/'
    
    def test_dashboard_authenticated(self, authenticated_client):
        """Test a regular (non-admin) user is forbidden from the dashboard.

        DashboardViewSet is IsAdminUser-only (sales/business stats)."""
        response = authenticated_client.get(self.base_url)
        assert response.status_code == status.HTTP_403_FORBIDDEN
    
    def test_dashboard_admin(self, admin_client):
        """Test admin can access dashboard."""
        response = admin_client.get(self.base_url)
        assert response.status_code == status.HTTP_200_OK
    
    def test_dashboard_unauthenticated(self, api_client):
        """Test unauthenticated user cannot access dashboard."""
        response = api_client.get(self.base_url)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


# ==================== COUPON MANAGEMENT TESTS ====================

@pytest.mark.django_db
class TestCouponManagement:
    """Tests for coupon management (superuser only)."""
    
    base_url = '/api/coupons/'
    
    def test_list_coupons_admin(self, admin_client, test_coupon):
        """Test admin can list coupons."""
        response = admin_client.get(self.base_url)
        assert response.status_code == status.HTTP_200_OK
    
    def test_list_coupons_regular_user_forbidden(self, authenticated_client):
        """Test regular user cannot list coupons."""
        response = authenticated_client.get(self.base_url)
        assert response.status_code == status.HTTP_403_FORBIDDEN
    
    def test_list_coupons_unauthenticated_forbidden(self, api_client):
        """Test unauthenticated user cannot list coupons."""
        response = api_client.get(self.base_url)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
    
    def test_create_coupon_admin(self, admin_client):
        """Test admin can create coupon."""
        data = {
            'code': 'NEWCOUPON20',
            'discount_percent': 20,
            'is_active': True,
            'valid_until': (timezone.now() + timedelta(days=30)).isoformat()
        }
        response = admin_client.post(self.base_url, data, format='json')
        assert response.status_code == status.HTTP_201_CREATED
    
    def test_create_coupon_regular_user_forbidden(self, authenticated_client):
        """Test regular user cannot create coupon."""
        data = {
            'code': 'HACKEDCOUPON',
            'discount_percent': 100,
            'is_active': True
        }
        response = authenticated_client.post(self.base_url, data, format='json')
        assert response.status_code == status.HTTP_403_FORBIDDEN
    
    def test_update_coupon_admin(self, admin_client, test_coupon):
        """Test admin can update coupon."""
        data = {'discount_percent': 15}
        response = admin_client.patch(
            f'{self.base_url}{test_coupon.id}/',
            data,
            format='json'
        )
        assert response.status_code == status.HTTP_200_OK
    
    def test_delete_coupon_admin(self, admin_client, test_coupon):
        """Test admin can delete coupon."""
        response = admin_client.delete(f'{self.base_url}{test_coupon.id}/')
        assert response.status_code == status.HTTP_204_NO_CONTENT
    
    def test_delete_coupon_regular_user_forbidden(self, authenticated_client, test_coupon):
        """Test regular user cannot delete coupon."""
        response = authenticated_client.delete(f'{self.base_url}{test_coupon.id}/')
        assert response.status_code == status.HTTP_403_FORBIDDEN


# ==================== COUPON EDGE CASES ====================

@pytest.mark.django_db
class TestCouponEdgeCases:
    """Edge case tests for coupons."""
    
    base_url = '/api/coupons/'
    
    def test_create_coupon_duplicate_code(self, admin_client, test_coupon):
        """Test creating coupon with duplicate code fails."""
        data = {
            'code': test_coupon.code,  # Duplicate
            'discount_percent': 15,
            'is_active': True
        }
        response = admin_client.post(self.base_url, data, format='json')
        assert response.status_code == status.HTTP_400_BAD_REQUEST
    
    def test_create_coupon_negative_discount(self, admin_client):
        """Test creating coupon with negative discount."""
        data = {
            'code': 'NEGATIVEDISCOUNT',
            'discount_percent': -10,
            'is_active': True
        }
        response = admin_client.post(self.base_url, data, format='json')
        assert response.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR
    
    def test_create_coupon_over_100_discount(self, admin_client):
        """Test creating coupon with > 100% discount."""
        data = {
            'code': 'FREEDISCOUNT',
            'discount_percent': 150,
            'is_active': True
        }
        response = admin_client.post(self.base_url, data, format='json')
        assert response.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR
    
    def test_create_coupon_zero_discount(self, admin_client):
        """Test creating coupon with zero discount."""
        data = {
            'code': 'ZERODISCOUNT',
            'discount_percent': 0,
            'is_active': True
        }
        response = admin_client.post(self.base_url, data, format='json')
        assert response.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR
    
    def test_coupon_sql_injection_in_code(self, admin_client, malicious_inputs):
        """Test SQL injection in coupon code."""
        for payload in malicious_inputs.SQL_INJECTION:
            data = {
                'code': payload[:20],  # Truncate for code field
                'discount_percent': 10,
                'is_active': True
            }
            response = admin_client.post(self.base_url, data, format='json')
            assert response.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR


# ==================== POLICY MANAGEMENT TESTS ====================

@pytest.mark.skip(
    reason="Policy API retired — routes unregistered in spices_backend/urls.py; "
           "the storefront serves static policy pages. Remove this skip if the "
           "PolicyViewSet is re-registered."
)
@pytest.mark.django_db
class TestPolicyManagement:
    """Tests for policy management."""

    base_url = '/api/policies/'
    
    def test_list_policies_public(self, api_client):
        """Test anyone can list policies."""
        response = api_client.get(self.base_url)
        assert response.status_code == status.HTTP_200_OK
    
    def test_retrieve_policy_public(self, api_client, db):
        """Test anyone can retrieve a policy."""
        # Create a policy first
        policy = Policy.objects.create(
            type='shipping',
            content='Test privacy policy content'
        )
        
        # Use ID for lookup
        response = api_client.get(f'{self.base_url}{policy.type}/')
        assert response.status_code == status.HTTP_200_OK
    
    def test_update_policy_admin_only(self, admin_client, db):
        """Test only admin can update policy."""
        policy = Policy.objects.create(
            type='shipping',
            content='Original terms'
        )
        
        data = {'content': 'Updated terms content'}
        response = admin_client.patch(f'{self.base_url}{policy.type}/', data, format='json')
        assert response.status_code == status.HTTP_200_OK
    
    def test_update_policy_regular_user_forbidden(self, authenticated_client, db):
        """Test regular user cannot update policy."""
        policy = Policy.objects.create(
            type='return',
            content='Original refund policy'
        )
        
        data = {'content': 'Hacked content'}
        response = authenticated_client.patch(
            f'{self.base_url}{policy.type}/',
            data,
            format='json'
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN
    
    def test_update_policy_unauthenticated_forbidden(self, api_client, db):
        """Test unauthenticated user cannot update policy."""
        policy = Policy.objects.create(
            type='shipping',
            content='Original shipping policy'
        )
        
        data = {'content': 'Hacked content'}
        response = api_client.patch(f'{self.base_url}{policy.type}/', data, format='json')
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


# ==================== POLICY EDGE CASES ====================

@pytest.mark.skip(
    reason="Policy API retired — routes unregistered in spices_backend/urls.py; "
           "the storefront serves static policy pages. Remove this skip if the "
           "PolicyViewSet is re-registered."
)
@pytest.mark.django_db
class TestPolicyEdgeCases:
    """Edge case tests for policies."""

    base_url = '/api/policies/'
    
    def test_retrieve_nonexistent_policy(self, api_client, db):
        """Test retrieving a valid-but-unconfigured policy type returns 404.

        Policies are looked up by type (shipping/return); a valid type with no
        row yields 404, while an invalid type yields 400."""
        response = api_client.get(f'{self.base_url}shipping/')
        assert response.status_code == status.HTTP_404_NOT_FOUND
    
    def test_policy_xss_in_content(self, admin_client, db, malicious_inputs):
        """Test XSS payloads in policy content."""
        policy = Policy.objects.create(
            type='shipping',
            content='Original content'
        )
        
        for payload in malicious_inputs.XSS_PAYLOADS:
            data = {'content': payload}
            response = admin_client.patch(
                f'{self.base_url}{policy.type}/',
                data,
                format='json'
            )
            assert response.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR
    
    def test_policy_sql_injection_in_content(self, admin_client, db, malicious_inputs):
        """Test SQL injection in policy content."""
        policy = Policy.objects.create(
            type='return',
            content='Original'
        )
        
        for payload in malicious_inputs.SQL_INJECTION:
            data = {'content': payload}
            response = admin_client.patch(
                f'{self.base_url}{policy.type}/',
                data,
                format='json'
            )
            assert response.status_code != status.HTTP_500_INTERNAL_SERVER_ERROR


# ==================== RECEIVABLE ACCOUNT TESTS ====================

@pytest.mark.django_db
class TestReceivableAccount:
    """Tests for receivable account management."""
    
    base_url = '/api/receivable-accounts/'
    
    def test_list_receivable_accounts_authenticated(self, authenticated_client):
        """Test a regular (non-admin) user is forbidden from receivable accounts.

        ReceivableAccountViewSet is IsAdminUser-only (payment collection data)."""
        response = authenticated_client.get(self.base_url)
        assert response.status_code == status.HTTP_403_FORBIDDEN
    
    def test_list_receivable_accounts_unauthenticated(self, api_client):
        """Test unauthenticated user cannot list receivable accounts."""
        response = api_client.get(self.base_url)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


# --- From test_admin_features.py ---

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
        # Low stock is read per SIZE now; the product's own `stock` is only a
        # mirror of its default size.
        size = default_variant_for(test_product.pk)
        size.stock = 3                  # at/below threshold 5 → low stock
        size.save(update_fields=['stock'])

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

    def test_unread_chats_and_new_contacts(self, admin_client, test_user):
        from assistant.models import AssistantConversation, AssistantMessage
        from support.models import ContactSubmission

        # Customer wrote last → unread.
        waiting = AssistantConversation.objects.create(user=test_user, status='active')
        AssistantMessage.objects.create(conversation=waiting, role='user', content='hi?')
        # Assistant answered last → not unread.
        answered = AssistantConversation.objects.create(user=test_user, status='active')
        AssistantMessage.objects.create(conversation=answered, role='user', content='hi')
        AssistantMessage.objects.create(conversation=answered, role='assistant', content='hello')
        # Escalated threads are counted by chats_waiting, not twice here.
        escalated = AssistantConversation.objects.create(
            user=test_user, status='active', needs_human=True)
        AssistantMessage.objects.create(conversation=escalated, role='user', content='help')

        ContactSubmission.objects.create(
            name='A', email='a@example.com', subject='s', message='m')
        ContactSubmission.objects.create(
            name='B', email='b@example.com', subject='s', message='m', status='read')

        resp = admin_client.get('/api/dashboard/actions/')
        assert resp.status_code == 200
        assert resp.data['unread_chats'] == 1
        assert resp.data['chats_waiting'] == 1
        assert resp.data['new_contacts'] == 1


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


# --- From test_owner_emails.py ---

@pytest.fixture
def capture_email(monkeypatch):
    """Capture every _send_async(...) call across the order-email module."""
    sent = []

    def fake_send(subject, message, recipient):
        sent.append({'subject': subject, 'message': message, 'recipient': recipient})

    monkeypatch.setattr('orders.emails._send_async', fake_send)
    return sent


@pytest.fixture
def owner_email(settings):
    """Configure the store-owner alert address (pytest-django settings fixture
    restores it automatically after the test)."""
    settings.ADMIN_ALERT_EMAIL = 'owner@shop.test'
    return settings.ADMIN_ALERT_EMAIL


def _order(user, product, **kw):
    order = Order.objects.create(
        user=user, shipping_address='1 Test Rd, City', phone_number='9990001112',
        payment_method=kw.get('payment_method', 'COD'),
        subtotal=Decimal('240'), tax=Decimal('24'), total_amount=Decimal('264'),
        status=kw.get('status', 'pending'),
    )
    OrderItem.objects.create(
        order=order, product=product, item_type='product',
        product_name=product.name, product_weight=str(product.weight),
        quantity=2, price=product.final_price, final_price=product.final_price * 2,
    )
    return order


@pytest.mark.django_db
class TestNewOrderAlert:
    def test_alert_composed_for_owner(self, capture_email, owner_email, test_user, test_product):
        from orders.emails import send_new_order_admin_alert
        order = _order(test_user, test_product)
        send_new_order_admin_alert(order)
        assert len(capture_email) == 1
        mail = capture_email[0]
        assert mail['recipient'] == 'owner@shop.test'
        assert f'ORD-{order.id:06d}' in mail['message']
        assert 'Cash on Delivery' in mail['message']

    def test_no_alert_without_configured_email(self, capture_email, settings,
                                               test_user, test_product):
        from orders.emails import send_new_order_admin_alert
        settings.ADMIN_ALERT_EMAIL = ''
        send_new_order_admin_alert(_order(test_user, test_product))
        assert capture_email == []


@pytest.mark.django_db
class TestDailyDigest:
    def test_digest_lists_low_stock_and_waiting_orders(
            self, capture_email, owner_email, test_user, test_product):
        _order(test_user, test_product, status='pending')  # waiting to confirm
        size = default_variant_for(test_product.pk)
        size.stock = 2  # below default threshold 5
        size.save(update_fields=['stock'])

        call_command('send_daily_digest')

        assert len(capture_email) == 1
        body = capture_email[0]['message']
        assert 'waiting to be confirmed' in body
        assert test_product.name in body  # low-stock line

    def test_skipped_when_email_unset(self, capture_email, settings):
        settings.ADMIN_ALERT_EMAIL = ''
        call_command('send_daily_digest')
        assert capture_email == []


@pytest.mark.django_db
class TestWeeklySummary:
    def test_summary_reports_sales_and_best_sellers(
            self, capture_email, owner_email, test_user, test_product):
        from analytics.models import DailySalesRollup

        yesterday = timezone.now().date() - timedelta(days=1)
        DailySalesRollup.objects.create(
            date=yesterday, orders=3, units=6, revenue=Decimal('900'))
        # An order in the window feeds the best-seller list.
        o = _order(test_user, test_product, status='delivered')
        Order.objects.filter(pk=o.pk).update(
            created_at=timezone.now() - timedelta(days=1))

        call_command('send_weekly_summary')

        assert len(capture_email) == 1
        body = capture_email[0]['message']
        assert 'Rs. 900' in body
        assert test_product.name in body  # best seller

    def test_skipped_when_email_unset(self, capture_email, settings):
        settings.ADMIN_ALERT_EMAIL = ''
        call_command('send_weekly_summary')
        assert capture_email == []


@pytest.mark.django_db
class TestSendReportEndpoint:
    def test_staff_can_trigger_weekly(self, admin_client, capture_email, owner_email):
        resp = admin_client.post('/api/dashboard/send-report/', {'type': 'weekly'}, format='json')
        assert resp.status_code == 200
        assert resp.data['sent'] is True
        assert len(capture_email) == 1

    def test_invalid_type_rejected(self, admin_client):
        resp = admin_client.post('/api/dashboard/send-report/', {'type': 'monthly'}, format='json')
        assert resp.status_code == 400

    def test_requires_staff(self, authenticated_client):
        resp = authenticated_client.post('/api/dashboard/send-report/', {'type': 'weekly'}, format='json')
        assert resp.status_code == 403


# --------------------------------------------------------------------------- #
# Dashboard rebuild (WP5)
# --------------------------------------------------------------------------- #

@pytest.mark.django_db
class TestDashboardRebuild:
    def test_unpaid_online_excluded_cod_included(self, admin_client, test_user):
        # An unpaid ONLINE checkout is not a sale yet; a COD placement is.
        Order.objects.create(
            user=test_user, shipping_address='x', phone_number='1',
            payment_method='ONLINE', payment_status='pending',
            subtotal=Decimal('999'), total_amount=Decimal('999'), status='pending',
        )
        Order.objects.create(
            user=test_user, shipping_address='x', phone_number='1',
            payment_method='COD', payment_status='pending',
            subtotal=Decimal('100'), total_amount=Decimal('100'), status='pending',
        )
        resp = admin_client.get('/api/dashboard/actions/')
        assert resp.status_code == 200
        assert Decimal(resp.data['today_sales']) == Decimal('100.00')
        assert resp.data['today_real_orders'] == 1
        assert Decimal(resp.data['today_cod_booked']) == Decimal('100.00')
        assert Decimal(resp.data['today_online_received']) == Decimal('0.00')

    def test_today_sales_delta_none_when_last_week_zero(self, admin_client, test_user):
        # No orders 7 days ago, so there is nothing to compare against.
        Order.objects.create(
            user=test_user, shipping_address='x', phone_number='1',
            payment_method='COD', payment_status='pending',
            subtotal=Decimal('50'), total_amount=Decimal('50'), status='pending',
        )
        resp = admin_client.get('/api/dashboard/actions/')
        assert resp.status_code == 200
        assert Decimal(resp.data['last_week_same_day_sales']) == Decimal('0.00')
        assert resp.data['today_sales_delta_pct'] is None

    def test_invoices_missing_counts_paid_order(self, admin_client, test_user):
        # Paid but never invoiced: the bill still has to be raised.
        Order.objects.create(
            user=test_user, shipping_address='x', phone_number='1',
            payment_method='ONLINE', payment_status='paid',
            subtotal=Decimal('100'), total_amount=Decimal('100'), status='confirmed',
        )
        resp = admin_client.get('/api/dashboard/actions/')
        assert resp.status_code == 200
        assert resp.data['invoices_missing'] == 1

    def test_customer_total_gst_includes_shipping_tax(self, admin_client, test_user):
        # Goods GST + delivery GST both count as tax collected on the customer.
        Order.objects.create(
            user=test_user, shipping_address='x', phone_number='1',
            payment_method='COD', subtotal=Decimal('100'),
            tax=Decimal('10'), shipping_tax=Decimal('5'),
            total_amount=Decimal('115'), status='pending',
        )
        resp = admin_client.get('/api/admin-customers/', {'search': test_user.email})
        assert resp.status_code == 200
        row = next(r for r in resp.data['results'] if r['email'] == test_user.email)
        assert Decimal(row['total_gst']) == Decimal('15.00')

    def test_recent_orders_have_payment_fields(self, admin_client, test_user):
        Order.objects.create(
            user=test_user, shipping_address='x', phone_number='1',
            payment_method='COD', payment_status='pending',
            subtotal=Decimal('10'), total_amount=Decimal('10'), status='pending',
        )
        resp = admin_client.get('/api/dashboard/')
        assert resp.status_code == 200
        assert len(resp.data['recentOrders']) >= 1
        row = resp.data['recentOrders'][0]
        assert 'paymentMethod' in row and 'paymentStatus' in row
